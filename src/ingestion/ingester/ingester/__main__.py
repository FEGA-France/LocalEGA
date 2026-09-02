#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import asyncio
import concurrent
import traceback
import time

from . import ingest, conf, exceptions, logger
from .message import FEGAMessage

LOG = logging.getLogger(__name__)

def mq_report(func):
    async def wrapper(config, message):
        try:
            return await func(config, message)
        except Exception as e:
            if e.__cause__:
                LOG.error('Error Cause: %r', e.__cause__)

            if isinstance(e, exceptions.FromUser):
                LOG.error('Publish user error: %r', e)
                routing_key = 'error'
                error = dict(message.parsed) # copy
                error['type'] = 'ingestion.error' # processed by dispatcher
                error['reason'] = str(e)
                # must contain "internal"
            else:
                LOG.error('Publish system error: %r', e)
                routing_key = 'error.system'
                error = {
                    'message': message.parsed,
                    'reason': traceback.format_exception(e),
                }

            await config.mq.publish(error, routing_key,
                                    correlation_id=message.correlation_id)
            raise
    return wrapper

def ack_nack_on_exception(on_message):
    async def wrapper(config, message):
        try:
            correlation_id = message.correlation_id # logging will find it
            LOG.info('Working on message %s', message)
            start_time = time.time()
            await on_message(config, message)
            elapsed_time = time.time() - start_time
            LOG.info('Acking message %s | job time: %s', message, ingest.format_time(elapsed_time))
            await message.channel.basic_ack(message.delivery.delivery_tag)
        except Exception as e:
            elapsed_time = time.time() - start_time
            LOG.info('Nacking message %s | job time: %s', message, ingest.format_time(elapsed_time))
            await message.channel.basic_nack(message.delivery.delivery_tag, requeue=False)
    return wrapper

@ack_nack_on_exception
@mq_report # report _before_ we ack/nack
async def work(config, message):

    if not message.job_type:
        raise Exception('Missing job type: Invalid message')

    if message.job_type == 'ingest':
        await ingest.execute(config, message)

    elif message.job_type == 'cancel':

        data = message.parsed
        filepath = data['filepath']
        username = data['user']
        LOG.info('Cancelling [%s]%s', username, filepath)
        staging_prefix = config.get('staging', 'location', raw=True)
        staging_path = os.path.join(staging_prefix % username, filepath.strip('/') )
        LOG.debug('Staging path: %s', staging_path)
        try:
            os.unlink(staging_path)
        except OSError:
            pass
        
        # Notify job done
        data['type'] = 'cancel.completed'
        await config.mq.publish(data, 'cancel.completed',
                                correlation_id=message.correlation_id)


    else:
        raise Exception(f'Invalid operation: {message.job_type} for message: {message.content}')


def capture_all_errors(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            #LOG.error('General error: %r', e, exc_info=True)
            LOG.error('General error: %r', e, exc_info=False)
            LOG.error('General error: %s', e.__dict__)
            sys.exit(2)
    return wrapper


@capture_all_errors
async def main(conf_file, queue):

    logger._appname = queue

    os.umask(0o027) # no world permissions, no group-write

    config = conf.Configuration(conf_file, queue) # queue is used as connection name
    LOG.debug('Config ready: %s', config)

    async def do_work(message):
        try:
            await work(config, FEGAMessage(message))
        except Exception as e:
            LOG.error('ERROR: %r', e, exc_info=True)

    return await config.mq.consume(queue, do_work,
                                   consumer_tag=queue,
                                   qos=config.getint('broker', 'qos', fallback=1)) # default: one at a time



if __name__ == '__main__':

    if len(sys.argv) < 3:
        print(f'Usage: {sys.argv[0]} <conf_file> <queue>')
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
