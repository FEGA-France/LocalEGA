#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import asyncio
import concurrent
#import traceback

from . import archive, conf, logger, connectors
from .message import FEGAMessage

LOG = logging.getLogger(__name__)

def mq_report(func):
    async def wrapper(message, publish, *args):
        try:
            return await func(message, publish, *args)
        except Exception as e: # any other error
            LOG.error('Publish error to Local EGA Sys admins: %r', e, exc_info=True)
            error = dict(message.parsed) # copy
            error['type'] = 'archival.error' # processed by dispatcher
            error['reason'] = str(e) # traceback.format_exception(e),
            # must contain "internal"
            await publish(error, 'error', # back to the dispatcher
                          correlation_id=message.correlation_id)
            raise
    return wrapper

def ack_nack_on_exception(on_message):
    async def wrapper(message, *args):
        try:
            correlation_id = message.correlation_id # logging will find it
            LOG.info('Working on message %s', message)
            await on_message(message, *args)
            await message.ack()
        except Exception as e:
            LOG.error('Message %s | %r', message, e)
            await message.nack(requeue=False)
    return wrapper

@ack_nack_on_exception
@mq_report # report _before_ we ack/nack
async def work(message, publish, *args):

    if not message.job_type:
        raise Exception('Missing job type: Invalid message')

    if message.job_type != 'accession':
        raise Exception(f'Invalid operation: {message.job_type} for message: {message.content}')

    data = await archive.execute(message.parsed, *args)
    data['type'] = 'archival.completed'
    await publish(data, 'archival.completed', correlation_id=message.correlation_id)


def main(conf_file, queue):

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_debug(True)

    logger._appname = queue

    os.umask(0o027) # no world permissions, no group-write

    config = conf.Configuration(conf_file, queue) # queue is used as connection name
    LOG.debug('Config ready: %s', config)

    # Load the source/vault/backup contexts
    # Internally, we do _not_ share the iouring/threadpool between contexts
    rctx = connectors.load(config.select_section('source'), loop=loop)
    vctx = connectors.load(config.select_section('destination'), loop=loop)

    do_backup = not config.getboolean('DEFAULT', 'skip_backup', fallback=False)
    if do_backup:
        bctx = connectors.load(config.select_section('backup'), loop=loop)
    else:
        bctx = connectors.NoContext()

    with rctx, vctx, bctx:

        async def do_work(message):
            await work(FEGAMessage(message), config.mq.publish, rctx, vctx, bctx)

        loop.create_task(config.mq.consume(queue, do_work,
                                           consumer_tag=queue,
                                           qos=config.getint('broker', 'qos', fallback=1))) # default: one at a time
        loop.run_forever()


if __name__ == '__main__':

    if len(sys.argv) < 3:
        print(f'Usage: {sys.argv[0]} <conf_file> <queue>')
        sys.exit(1)

    try:
        main(sys.argv[1], sys.argv[2])
    except KeyboardInterrupt as e:
        LOG.warning('Cancelled')
        sys.exit(0)
    except Exception as e:
        LOG.error('%s', e)
        sys.exit(2)
