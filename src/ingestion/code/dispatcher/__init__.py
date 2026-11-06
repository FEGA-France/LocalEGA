#!/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import sys
import asyncio
import traceback

from . import db
from ..utils import conf, logger, amqp
from ..utils.message import FEGAMessage, ack_nack_on_exception

LOG = logging.getLogger(__name__)

def mq_report(func):
    async def wrapper(message, jobs, publish):
        try:
            return await func(message, jobs, publish)
        except Exception as e: # any other error
            LOG.error('Publish error to Local EGA Sys admins: %r', e)
            error = {
                'message': message.parsed,
                'reason': traceback.format_exception(e),
            }
            # Goes to the local administrator / dashboard
            await publish(error, 'error.system',
                          correlation_id=message.correlation_id)
            raise
    return wrapper

@ack_nack_on_exception
@mq_report # report _before_ we ack/nack
async def work(message, jobs, publish):

    if not message.job_type:
        raise Exception('Missing job type: Invalid message')

    if message.job_type == 'heartbeat':
        return await publish(message, 'heartbeat')

    job = jobs.get(message.job_type, None)

    if not job:
        return await publish(message, 'relay.vault.db')

    LOG.debug('Running %s: %s', message.job_type, job.__name__)
    LOG.debug('on [%s]: %s', message.correlation_id, message.content)
    await job(message.correlation_id, message.parsed)
    


def main(conf_file):

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_debug(True)

    logger._appname = 'dispatcher'

    os.umask(0o027) # no world permissions, no group-write

    config = conf.Configuration(conf_file)
    LOG.info('Config ready: %s', config)

    queue = config.get('broker', 'queue')

    _db = db.DBConnection(config, conf_section='db')
    mq = amqp.MQConnection('dispatcher', config, conf_section='broker')

    jobs = {
        'ingest': _db.do_ingest,
        'cancel': _db.do_cancel,
        'accession': _db.do_accession,
        # 'clean': _db.do_force_clean,

        'ingestion.completed': _db.do_ingestion_completed,
        'ingestion.error': _db.do_error,

        'archival.completed': _db.do_archival_completed,
        'archival.error': _db.do_error,

        'cancel.completed': _db.do_cancel_completed,
    }

    async def do_work(message):
        await work(FEGAMessage(message), jobs, mq.publish)

    loop.create_task(mq.consume(queue, do_work, consumer_tag='dispatcher'))
    loop.create_task(_db.publish_messages(mq.publish))
    loop.create_task(_db.tick_forever())

    loop.run_forever()
