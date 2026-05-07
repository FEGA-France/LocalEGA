#!/bin/env python3
# -*- coding: utf-8 -*-

import logging
import os
import sys
import asyncio
from datetime import datetime, timedelta
import json

from . import conf

LOG = logging.getLogger(__name__)

epoch = datetime.utcfromtimestamp(0)
millis = timedelta(milliseconds=1)

def show_and_reraise_exception(func):
    async def wrapper(*args, **kwargs):
        try:
            return await func(*args, **kwargs)
        except Exception as e:
            LOG.error('%r', e)
            raise
    return wrapper


# If we can't handle the message, instead of nacking it,
# we "disconnect" and let the server return it to the queue as it was.
# If we'd nack it, with requeue, it would go at the end of the queue, and the server would give it a new timestamp
# (because we activated that internal plugin, to ensure there is a timestamp)
@show_and_reraise_exception
async def work(config, message):

    LOG.debug('Message %s', message.delivery_tag)

    properties = dict(message.header.properties)
    headers = properties.pop('headers', {})

    # timestamp = properties.pop('timestamp', None) # should be there
    # assert timestamp, 'Missing timestamp from properties'
    timestamp = properties.pop('timestamp', None) or datetime.now()

    document = dict((k,v) for k,v in properties.items() if v) # filter nulls

    # document['@timestamp'] = (timestamp - epoch).total_seconds()
    document['@timestamp'] = timestamp.timestamp()
    document['exchange'] = message.exchange
    document['routing_key'] = message.routing_key
    document['headers'] = json.dumps(headers)

    document['payload'] = message.body.decode()

    await config.es.index(document)
    
    LOG.info('Acking message %s', message.delivery_tag)
    await message.channel.basic_ack(message.delivery_tag)

@show_and_reraise_exception
async def main(conf_file):
    config = conf.Configuration(conf_file)
    LOG.info('Config ready: %s', config)
    LOG.info('Process ID: %d', os.getpid())

    async def do_work(message):
        return await work(config, message)

    return await config.mq.consume(do_work)


if __name__ == '__main__':

    if len(sys.argv) < 2:
        print(f'Usage: {sys.argv[0]} <conf_file>')
        sys.exit(1)

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    loop.set_debug(True)
    
    loop.create_task(main(sys.argv[1]))
    
    try:
        loop.run_forever()
    except KeyboardInterrupt as e:
        LOG.warning('Cancelled')
        sys.exit(0)
    except Exception as e:
        sys.exit(2) # and the scheduler will restart it
