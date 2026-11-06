#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import logging
import asyncio
import concurrent
import traceback

from . import ingest, key
from ..utils import conf, exceptions, logger, connectors, amqp
from ..utils.message import FEGAMessage, ack_nack_on_exception

LOG = logging.getLogger(__name__)

def mq_report(func):
    async def wrapper(message, publish, *args):
        try:
            return await func(message, publish, *args)
        except exceptions.FromUser as e:
            LOG.error('Publish user error: %r', e)
            if e.__cause__:
                LOG.error('Error Cause: %r', e.__cause__)
            error = dict(message.parsed) # copy
            error['type'] = 'ingestion.error' # processed by dispatcher
            error['reason'] = str(e)
            # Note: must contain "internal"
            await publish(error, 'error', correlation_id=message.correlation_id)
            raise
        except Exception as e:
            LOG.error('Publish system error: %r', e)
            if e.__cause__:
                LOG.error('Error Cause: %r', e.__cause__)
            error = {
                'message': message.parsed,
                'reason': traceback.format_exception(e),
            }
            await publish(error, 'error.system', correlation_id=message.correlation_id)
            raise
    return wrapper

@ack_nack_on_exception
@mq_report # report _before_ we ack/nack
async def work(message, publish,
               service_key, master_key, inbox_ctx, staging_ctx,
               do_reencryption, bufsize):

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

        # Is there an inbox checksum ?
        encrypted_checksum = None
        for d in data.get('encrypted_checksums', []):
            if d['type'].lower() == 'sha256':
                encrypted_checksum = d['value']
                break


        try:

            _ = await ingest.execute(data, filepath,
                                     service_key, master_key,
                                     inbox_ctx, staging_ctx,
                                     do_reencryption = do_reencryption,
                                     bufsize = bufsize,
                                     inbox_checksum = encrypted_checksum)
            data['type'] = 'ingestion.completed'
            await publish(data, 'ingestion.completed', correlation_id=message.correlation_id)

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
        await publish(data, 'cancel.completed', correlation_id=message.correlation_id)

    else:
        raise Exception(f'Invalid operation: {message.job_type} for message: {message.content}')




def main(conf_file, queue):

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_debug(True)

    logger._appname = queue

    os.umask(0o027) # no world permissions, no group-write

    config = conf.Configuration(conf_file)
    LOG.debug('Config ready: %s', config)

    mq = amqp.MQConnection(queue, config, conf_section='broker')
    
    # Load the inbox/staging contexts
    # Internally, we do _not_ share the iouring/threadpool between contexts
    rctx = connectors.load(config.select_section('source'), loop=loop)
    wctx = connectors.load(config.select_section('destination'), loop=loop)

    service_key = key.load(config, 'service_key')
    master_pubkey = key.load(config, 'master_pubkey')

    # Crypt4gh format
    mkey = (0, service_key.private, master_pubkey.public) # from ingestion to recipient master
    skey = (0, service_key.private, None) # not checking the sender

    do_reencryption = not config.getboolean('DEFAULT', 'skip_reencryption', fallback=False)
    bufsize = config.getint('DEFAULT', 'bufsize', fallback=None)

    with rctx, wctx:

        async def do_work(message):
            await work(FEGAMessage(message), mq.publish,
                       skey, mkey, rctx, wctx,
                       do_reencryption, bufsize)

        loop.create_task(mq.consume(queue, do_work,
                                     consumer_tag=queue,
                                     qos=config.getint('broker', 'qos', fallback=1))) # default: one at a time
        loop.run_forever()
