#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import asyncio
import concurrent
import traceback

from . import ingest, conf, exceptions, logger, connectors
from .message import FEGAMessage

LOG = logging.getLogger(__name__)

def mq_report(func):
    async def wrapper(message, config, *args):
        try:
            return await func(message, config, *args)
        except exceptions.FromUser as e:
            LOG.error('Publish user error: %r', e)
            if e.__cause__:
                LOG.error('Error Cause: %r', e.__cause__)
            error = dict(message.parsed) # copy
            error['type'] = 'ingestion.error' # processed by dispatcher
            error['reason'] = str(e)
            # Note: must contain "internal"
            await config.mq.publish(error, 'error', correlation_id=message.correlation_id)
            raise
        except Exception as e:
            LOG.error('Publish system error: %r', e)
            if e.__cause__:
                LOG.error('Error Cause: %r', e.__cause__)
            error = {
                'message': message.parsed,
                'reason': traceback.format_exception(e),
            }
            await config.mq.publish(error, 'error.system', correlation_id=message.correlation_id)
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
            LOG.error('Message %s: %r', message, e)
            await message.nack(requeue=False)
    return wrapper

@ack_nack_on_exception
@mq_report # report _before_ we ack/nack
async def work(message, config, inbox_ctx, staging_ctx):

    if not message.job_type:
        raise Exception('Missing job type: Invalid message')

    data = message.parsed
    # prepend username to filepath
    filepath = data['filepath'].lstrip('/')
    username = data['user'].strip()
    LOG.info('Processing %s/%s', username, filepath)
    assert '/' not in username
    filepath = os.path.join(username, filepath)

    if message.job_type == 'ingest':

        master_key = (0, config.service_key.private(), config.master_pubkey) # from ingestion to recipient master
        service_key = (0, config.service_key.private(), None) # not checking the sender

        # Is there an inbox checksum ?
        encrypted_checksum = None
        for d in data.get('encrypted_checksums', []):
            if d['type'].lower() == 'sha256':
                encrypted_checksum = d['value']
                break

        do_reencryption = not config.getboolean('DEFAULT', 'skip_reencryption', fallback=False)
        bufsize = config.getint('DEFAULT', 'bufsize', fallback=None)

        try:

            _ = await ingest.execute(data, filepath,
                                     service_key, master_key,
                                     inbox_ctx, staging_ctx,
                                     do_reencryption = do_reencryption,
                                     bufsize = bufsize,
                                     inbox_checksum = encrypted_checksum)
            data['type'] = 'ingestion.completed'
            await config.mq.publish(data, 'ingestion.completed', correlation_id=message.correlation_id)

        except Exception as e:
            LOG.error('Cleaning staging on: %r', e)
            try:
                staging_ctx.unlink(filepath)
            except OSError:
                pass
            raise

    elif message.job_type == 'cancel':

        try:
            await staging_ctx.unlink(filepath)
        except OSError:
            pass
        # Notify job done
        data['type'] = 'cancel.completed'
        await config.mq.publish(data, 'cancel.completed', correlation_id=message.correlation_id)

    else:
        raise Exception(f'Invalid operation: {message.job_type} for message: {message.content}')




def main(conf_file, queue):

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_debug(True)

    logger._appname = queue

    os.umask(0o027) # no world permissions, no group-write

    config = conf.Configuration(conf_file, queue) # queue is used as connection name
    LOG.debug('Config ready: %s', config)

    # Load the inbox/staging contexts
    # Internally, we do _not_ share the iouring/threadpool between contexts
    rctx = connectors.load(config.select_section('source'), loop=loop)
    wctx = connectors.load(config.select_section('destination'), loop=loop)

    with rctx, wctx:

        async def do_work(message):
            await work(FEGAMessage(message), config, rctx, wctx)

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
