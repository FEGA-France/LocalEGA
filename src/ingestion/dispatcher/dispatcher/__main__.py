#!/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import sys
import asyncio
import traceback

from . import conf, logger
from .message import FEGAMessage

LOG = logging.getLogger(__name__)

def mq_report(func):
    async def wrapper(config, jobs, message):
        try:
            return await func(config, jobs, message)
        except Exception as e: # any other error
            LOG.error('Publish error to Local EGA Sys admins: %r', e)
            error = {
                'message': message.parsed,
                'reason': traceback.format_exception(e),
            }
            # Goes to the local administrator / dashboard
            await config.mq.publish(error, 'error.system',
                                    correlation_id=message.header.properties.correlation_id)
            raise
    return wrapper

def ack_nack_on_exception(func):
    async def wrapper(config, jobs, message):
        try:
            correlation_id = message.correlation_id # logging will find it
            LOG.info('Working on message %s', message)
            await func(config, jobs, message)
            LOG.info('Acking message %s', message)
            await message.channel.basic_ack(message.delivery.delivery_tag)
        except Exception as e:
            LOG.info('Nacking message %s', message)
            await message.channel.basic_nack(message.delivery.delivery_tag, requeue=False)
    return wrapper

@ack_nack_on_exception
@mq_report # report _before_ we ack/nack
async def work(config, jobs, message):

    if not message.job_type:
        raise Exception('Missing job type: Invalid message')

    if message.job_type == 'heartbeat':
        return await config.mq.publish(message, 'heartbeat')

    job = jobs.get(message.job_type, None)

    if not job:
        return await config.mq.publish(message.correlation_id, 'relay.vault.db', message.content)

    LOG.debug('Running %s: %s', message.job_type, job.__name__)
    LOG.debug('on [%s]: %s', message.correlation_id, message.content)
    await job(message.correlation_id, message.parsed)
    

def capture_all_errors(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            #LOG.error('General error: %r', e, exc_info=True)
            LOG.error('General error: %r', e, exc_info=False)
            sys.exit(2)
    return wrapper

@capture_all_errors
async def main(loop, conf_file):

    logger._appname = 'dispatcher'

    os.umask(0o027) # no world permissions, no group-write

    config = conf.Configuration(conf_file)
    LOG.info('Config ready: %s', config)

    await config.mq.connect()

    jobs = {
        'ingest': config.db.do_ingest,
        'cancel': config.db.do_cancel,
        'accession': config.db.do_accession,
        # 'clean': config.db.do_force_clean,

        'ingestion.completed': config.db.do_ingestion_completed,
        'ingestion.error': config.db.do_error,

        'archival.completed': config.db.do_archival_completed,
        'archival.error': config.db.do_error,

        'cancel.completed': config.db.do_cancel_completed,
    }

    async def do_work(message):
        await work(config, jobs, FEGAMessage(message))


    return await asyncio.gather(loop.create_task(config.mq.consume(do_work, consumer_tag='dispatcher')),
                                loop.create_task(config.db.publish_messages()),
                                loop.create_task(config.db.tick_forever()))


if __name__ == '__main__':

    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} <conf_file>')
        sys.exit(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_debug(True)

    loop.create_task(main(loop,sys.argv[1]))
    
    try:
        loop.run_forever()
    except KeyboardInterrupt as e:
        LOG.warning('Cancelled')
        sys.exit(0)
    except Exception as e:
        LOG.error('%s', e)
        sys.exit(2)
