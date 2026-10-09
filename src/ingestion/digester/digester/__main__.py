#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import asyncio
import traceback
import time
import hashlib
from hmac import compare_digest

from . import connectors, conf, logger, format_time
from .message import FEGAMessage

if os.getenv('LEGA_TRACING', None) == '1':
    from .connectors import ProgressBar as Tracer
else:
    from .connectors import NoTracer as Tracer

LOG = logging.getLogger(__name__)

class ChecksumsNotMatching(Exception):
    """Raised when 2 checksums don't match."""

    def __init__(self, path, md1, md2):
        self.path = path
        self.md1 = md1
        self.md2 = md2

    def __str__(self):
        return f'Checksums for {self.path} do not match'

    def __repr__(self):
        return f'Checksums for {self.path} do not match:\n* {self.md1}\n* {self.md2}'

def capture_error(func):
    async def wrapper(source, mq, m):
        try:
            LOG.info("Working on %r", m)
            correlation_id = m.correlation_id # logging will find it
            sha256hex = await func(source, mq, m)
            # Success: send completion
            m.json['type'] = 'digest.completed'
            m.json['encrypted_checksums'] = [{ 'type': 'sha256', 'value': sha256hex }]
            await mq.publish_success(m)
            await m.ack()
        except Exception as e:
            LOG.error("Working on %s: %r", m, e)
            try:
                m.json['type'] = 'digest.error'
                m.json['reason'] = str(e)
                # trace = ''.join(traceback.format_exception(e))
                trace = []
                for line in traceback.format_exception(e):
                    for s in line.split('\n'):
                        s = s.strip()
                        if s:
                            trace.append(s)
                m.json['trace'] = trace
                await mq.publish_error(m)
            except Exception as ee:
                LOG.error('Poo poo: %r', ee)
            await m.reject(requeue=False)
    return wrapper


@capture_error
async def work(source, mq, message):

    if not message.job_type:
        raise ValueError('Missing job type: Invalid message')

    if message.job_type != 'digest':
        raise ValueError(f'Unsupported operation: {message.job_type}')

    rctx = connectors.load(source)

    with rctx:

        filepath = message.json['filepath']

        async with rctx.open(filepath, 'r') as r:

            LOG.info('Checksuming %s', filepath) 
            tracer = Tracer('Checksuming', r.size)
            sha256 = hashlib.sha256()
            start_time = time.time()

            LOG.debug('Selected chunksize: %s', r.CHUNK_SIZE)
            chunk = bytearray(r.CHUNK_SIZE)
            bytes_read = 0

            while True:
                n = await r.readinto(chunk)
                if n == 0:
                    break
                bytes_read += n
                sha256.update(chunk[:n])
                tracer.update(n)

            tracer.close()
            # del tracer
            elapsed_time = time.time() - start_time
            LOG.debug('Bytes read: %s [file size: %s]', bytes_read, r.size)
            speed = (bytes_read / elapsed_time) / (1<<20) # (1024 * 1024)

            LOG.debug('Elapsed time: %s | Speed: %s MB/s', format_time(elapsed_time), '{:.2f}'.format(speed))

            # c = sha256.digest()
            # if not compare_digest(c, orgmd): # could use c != orgmd
            #     LOG.error('Different file checksums')
            #     LOG.error('* computed: %s', c)
            #     LOG.error('* compared: %s', orgmd)
            #     raise ChecksumsNotMatching(path, c, orgmd)

            h = sha256.hexdigest()
            LOG.debug('Checksum: %s', h)
            return h


@logger.capture_all_errors
async def main(conf_file, connection_name):

    logger._appname = connection_name

    os.umask(0o027) # no world permissions, no group-write

    config = conf.Configuration(conf_file, connection_name)
    LOG.info('Config ready: %s', config)

    mq = config.mq

    await mq.connect()

    source = config.select_section('source')
    LOG.info('Source: %s', source)
    
    async def do_work(message):
        await work(source, mq, FEGAMessage(message))

    return await mq.consume(do_work,
                            consumer_tag=connection_name)


if __name__ == '__main__':

    if len(sys.argv) < 3:
        print(f'Usage: {sys.argv[0]} <conf_file> <connection_name>')
        sys.exit(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_debug(True)

    loop.create_task(main(sys.argv[1], sys.argv[2]))
    
    try:
        loop.run_forever()
    except KeyboardInterrupt as e:
        LOG.warning('Cancelled')
        sys.exit(0)
    except Exception as e:
        LOG.error('%s', e)
        sys.exit(2)
