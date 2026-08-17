
import sys
assert sys.version_info >= (3, 13), "This tool requires python version 3.13 or higher"

import logging
import asyncio
import signal
import os
import json
import inspect
from socket import gethostname
from pwd import getpwuid
import time

from elasticsearch import AsyncElasticsearch, ApiError
from elasticsearch.helpers import async_bulk

_hostname = gethostname() # container id or hostname
_uid = os.getuid()
_username = getpwuid(os.getuid()).pw_name
_pid = os.getpid()
# _cli = ' '.join(sys.argv)
_appname = 'FEGA'

class FrontQueue(asyncio.Queue):

    def put_front_nowait(self, item):
        """Put an item into the front of the queue without blocking.

        If no free slot is immediately available, raise QueueFull.

        Raises QueueShutDown if the queue has been shut down.
        """
        if self._is_shutdown:
            raise asyncio.QueueShutDown
        if self.full():
            raise QueueFull
        #self._put(item)
        self._queue.appendleft(item)
        self._unfinished_tasks += 1
        self._finished.clear()
        self._wakeup_next(self._getters)
 
class LEGALogRecord(logging.LogRecord):

    def __init__(self,
                 name, level, pathname, lineno,
                 msg, args, exc_info, func=None, sinfo=None, extra=None):

        self.name = name
        created = time.time_ns()
        self.created = created / 1e9  # ns to float seconds
        self.epoch_millis = created / 1e6
        self.levelname = logging.getLevelName(level)
        self.levelno = level
        self.args = args
        self.msg = msg
        self.pathname = pathname
        # try:
        #     self.filename = os.path.basename(pathname)
        #     self.module = os.path.splitext(self.filename)[0]
        # except (TypeError, ValueError, AttributeError):
        #     self.filename = pathname
        #     self.module = "Unknown module"
        self.exc_info = exc_info
        self.exc_text = None      # used to cache the traceback text
        self.stack_info = sinfo
        self.lineno = lineno
        self.funcName = func

        self.stack_info = sinfo

        self.msecs = 0.0
        self.relativeCreated = 0.0
        self.taskName = None
        self.processName = 'main'

        correlation_id = None
        if isinstance(extra, dict):
            correlation_id = extra.get('correlation_id', None)
        
        if not correlation_id:
            # Reset correlation_id if found in caller's local variables
            frame = inspect.currentframe()
            if frame is None:
                raise RuntimeError('cannot inspect stack frames')
            frame = frame.f_back
            sentinel = object()
            correlation_id = sentinel
            while frame is not None:
                correlation_id = frame.f_locals.get('correlation_id', sentinel)
                if correlation_id is not sentinel:
                    break
                frame = frame.f_back
            if correlation_id is sentinel:
                correlation_id = None

        self.correlation_id = correlation_id or ''
        self.hostname = _hostname
        self.uid = _uid
        self.username = _username
        self.pid = _pid
        self.appname = _appname



class AsyncBufferedSocketHandler(logging.Handler):

    __slots__ = ('_host',
                 '_port',
                 '_path',
                 '_queue',
                 '_writer',
                 '_lock',
                 '_loop',
                 '_bg_task',
                 '_retry_after',
                 '_org_retry_after'
                 )

    def __init__(self,
                 host: str = None, port: int = None,
                 path: str = None,
                 retry_after: int = 1,
                 maxsize: int = 5000,
                 keep_latest: bool = False):
        super().__init__()
        self._host = host
        self._port = port
        self._path = path
        self._queue = FrontQueue(maxsize=maxsize) # maxsize might be None
        self._writer = None
        self._lock = asyncio.Lock()
        self._loop = asyncio.get_running_loop()
        self._bg_task = self._loop.create_task(self._send_messages())
        self._org_retry_after = retry_after or 1
        self._retry_after = self._org_retry_after
        self._keep_latest = keep_latest
        
        # Register SIGHUP handler
        self._loop.add_signal_handler(signal.SIGUSR1, self._handle_sigusr1)
        self._loop.add_signal_handler(signal.SIGUSR2, self._handle_sigusr2)

    async def _connect(self):
        '''Open a persistent socket connection.'''

        if self._path: # priority to Unix Domain Socket
            _, self._writer = await asyncio.open_unix_connection(path=self._path)
        else:
            _, self._writer = await asyncio.open_connection(self._host, self._port)

    async def _send_messages(self):
        '''Background task to send logs from the queue.'''
        #await self._connect()
        while True:
            try:
                message = await self._queue.get()
                
                if not self._writer:
                    await self._connect()

                async with self._lock:
                    self._writer.write(message.encode())
                    self._writer.write(b'\n')
                    await self._writer.drain()
                    # Reset to initial value
                    self._retry_after = self._org_retry_after
                    self._queue.task_done()
            except Exception as e:

                # print('====== Error sending log:', repr(e), file=sys.stderr)
                
                # Put if back in the front
                async with self._lock:
                    self._queue.put_front_nowait(message)

                if self._writer:
                    self._writer.close()
                    # await self._writer.wait_closed()
                    self._writer = None

                # print('====== Sleeping for', self._retry_after, 'seconds', file=sys.stderr)
                await asyncio.sleep(self._retry_after)  # Wait before reconnecting
                self._retry_after = self._retry_after * 2

    def _handle_sigusr1(self):
        '''Inspect and print the queue size.'''
        if self._queue.qsize():
            print('+++ Queue:', self._queue.qsize(), 'messages | retry after:', self._retry_after,'seconds +++', file=sys.stderr)
        else:
            print('--- Queue: Empty | retry after:', self._retry_after,'seconds ---', file=sys.stderr)

    def _handle_sigusr2(self):
        '''Inspect and print the queue content without dequeueing.'''
        # Create a copy of the queue for inspection
        # Note: This is a simple approach; for large queues, consider limiting the output
        print('=== Queue ===', file=sys.stderr)
        for i, item in enumerate(self._queue._queue, 1):
            print(f'{i}:', item, file=sys.stderr)
        print('=============', file=sys.stderr)

    def emit(self, record):
        '''Thread-safe emit: enqueue the log message.'''
        try:
            # Might raise Queue.Full.
            # We have 2 cases, depending on self.keep_latest.
            # If true, we drop the first message and append the current one.
            # If false, we don't add the message.
            # That effectively keep the latest maxsize messages
            #
            # Alternatively, we can call asyncio.run_coroutine_threadsafe(self.queue.put(message), self.loop)
            # which would block in the loop and not raise the Queue.Full error.
            # However, we are likely disconnected from the socket, so drop something. Bad luck ¯\_(ツ)_/¯
            message = json.dumps(self.format(record))
            self._queue.put_nowait(message)
        except asyncio.QueueFull:
            if self._keep_latest:
                dropped_message = self._queue.get_nowait()
                print(self.__class__.__name__, 'dropped', dropped_message)
                self._queue.put_nowait(message)
        except Exception as e:
            # pass
            print('====== Failed to enqueue log:', repr(e), file=sys.stderr)

    def close(self):
        '''Close the socket and stop the background task.'''
        if self._writer:
            self._writer.close()
            self._loop.run_until_complete(self._writer.wait_closed())
        if self._bg_task:
            self._bg_task.cancel()
        super().close()

class AsyncBufferedElasticSearchHandler(logging.Handler):

    __slots__ = ('url',
                 'queue',
                 'client',
                 'lock',
                 'index',
                 'notify',
                 'loop',
                 'bg_task',
                 'retry_after',
                 'org_retry_after',
                 'tick',
                 'mappings'
                 )

    def __init__(self,
                 url: str,
                 index: str = 'lega',
                 retry_after: int = 1,
                 maxsize: int = 5000,
                 keep_latest: bool = False,
                 ca_certs=None, # Path to your CA certificate
                 verify_certs: bool = False
                 ):
        super().__init__()
        self.url = url
        self.index = index
        self.queue = FrontQueue(maxsize=maxsize)
        self.notify = asyncio.Event()
        self._lock = asyncio.Lock()
        self.loop = asyncio.get_running_loop()
        self.org_retry_after = retry_after or 1
        self.retry_after = self.org_retry_after
        self.client = AsyncElasticsearch(url, # including basic auth
                                         ca_certs=ca_certs,
                                         verify_certs=verify_certs)
        self.bg_task = self.loop.create_task(self._send_messages())
        self.tick = self.loop.create_task(self._tick_forever())
        self.mappings = {
            # Time fields
            "@timestamp": {"type": "date", "format": "epoch_millis"},
            "asctime":    {"type": "date"},
            # Categorical/Filterable fields (exact matches)
            "pid":          {"type": "integer"},  # Process ID
            "hostname":     {"type": "keyword"},  # Machine name
            "appname":      {"type": "keyword"},  # Application name
            "username":     {"type": "keyword"},  # User who triggered the log
            "levelname":    {"type": "keyword"},  # Log level (INFO, ERROR, etc.)
            "name":         {"type": "keyword"},  # Logger name
            "module":       {"type": "keyword"},  # Python module
            "funcName":     {"type": "keyword"},  # Function name
            "lineno":       {"type": "integer"},  # Line number
            # Full-text searchable fields
            "message":      {"type": "text"},     # Log message
            # Correlation/ID fields (exact matches)
            "correlation_id": {"type": "keyword"},  # For tracing logs across services
        }
        self.loop.create_task(self._ensure_index())

    async def _ensure_index(self):
        try:
            await self.client.indices.create(
                index = self.index,
                body = {
                    "settings": {
                        "number_of_shards": 1,
                        "number_of_replicas": 1
                    },
                    "mappings": {
                        "properties": self.mappings
                    }
                },
                ignore=400  # Ignore 400 errors (e.g., index already exists)
            )
        except ApiError as e:
            print("Failed to create index:", repr(e), file=sys.stderr)


    async def _tick_forever(self):
        while True:
            await asyncio.sleep(self.retry_after)
            self.notify.set()

    async def _send_messages(self):
        '''Background task to send logs from the queue.'''

        while True:

            await self.notify.wait()

            if not self.client: # not yet ready
                self.notify.clear()
                continue

            try:
                # take a snapshot
                async with self._lock:
                    size = self.queue.qsize()
                    actions = [
                        {"_op_type": "index",
                         "_index": self.index,
                         "_source": await self.queue.get()
                         }
                        for _ in range(size)]

                if actions:
                    await async_bulk(self.client, actions,
                                     stats_only = True)
                    # restore timer on success
                    self.retry_after = self.org_retry_after

                self.notify.clear()

            except Exception as e:

                # print('====== Error sending log:', repr(e), file=sys.stderr)
                
                # Put if back in the front
                async with self._lock:
                    for action in actions.reverse():
                        self._queue.put_front_nowait(action['_source'])

                await self.client.close()

                self.retry_after = min(self.retry_after * 2, 60)  # Cap at 60s

    def emit(self, record):
        action = self.format(record)
        action['@timestamp'] = record.epoch_millis # str => float ?
        action.pop('asctime', None)
        self.queue.put_nowait(action)

    def close(self):
        self.bg_task.cancel()
        self.tick.cancel()
        self.loop.run_until_complete(self.client.close())
        super().close()


class JSONFormatter(logging.Formatter):
    """Json Logs formatting."""

    def __init__(self, fmt, dfmt, style, **kwargs):
        """Initialize formatter."""
        validate = kwargs.pop('validate', False)
        self.defaults = kwargs.pop('defaults', {})
        self.defaults.update()

        fields = set(fmt.split(','))

        self.asctime = 'asctime' in fields
        fields.discard('asctime')

        self.message = 'message' in fields
        fields.discard('message')

        #fields.discard('created')

        super().__init__(None, dfmt, style,
                         defaults=self.defaults, validate=False, **kwargs)
        self._fields = fields


    def format(self, record):
        """Format a log record and serializes to json."""
        _record = {}

        for field in self._fields:
            attr = getattr(record, field, None)
            if attr is None:
                attr = self.defaults.get(field, None)
            #assert attr, f"Attribute {field} missing in LogRecord"
            if attr: # ignores empty strings too
                _record[field] = attr

        if self.asctime:
            _record['asctime'] = time.strftime(self.datefmt, time.localtime(record.created))

        if self.message:
            _record['message'] = record.getMessage()

        if record.exc_info:
            _record['exc_info'] = self.formatException(record.exc_info)

        if record.stack_info:
            _record['stack_info'] = self.formatStack(record.stack_info)

        return _record
