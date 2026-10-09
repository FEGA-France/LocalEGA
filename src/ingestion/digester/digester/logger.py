
import sys
assert sys.version_info >= (3, 13), "This tool requires python version 3.13 or higher"

import logging
import asyncio
import os
import json
import inspect
from socket import gethostname
from pwd import getpwuid
import time

_hostname = gethostname() # container id or hostname
_uid = os.getuid()
_username = getpwuid(os.getuid()).pw_name
_pid = os.getpid()
# _cli = ' '.join(sys.argv)
_appname = 'FEGA'
 
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


def capture_all_errors(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            #LOG.error('General error: %r', e, exc_info=True)
            #LOG.error('General error: %r', e, exc_info=False)
            print('General error:', repr(e), file=sys.stderr)
            sys.exit(2)
    return wrapper
