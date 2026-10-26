# -*- coding: utf-8 -*-

import logging
import os

from . import connectors

LOG = logging.getLogger(__name__)

async def execute(config, message):

    data = message.parsed
    filepath = data['filepath'].lstrip('/')
    username = data['user'].strip()
    LOG.info('Cancelling [%s]/%s', username, filepath)
    assert '/' not in username
    filepath = os.path.join(username, filepath)

    try:
        with connectors.load(config.select_section('staging')) as staging:
            await staging.unlink(filepath)
    except OSError:
        pass
        
    # Notify job done
    data['type'] = 'cancel.completed'
    await config.mq.publish(data, 'cancel.completed',
                            correlation_id=message.correlation_id)
