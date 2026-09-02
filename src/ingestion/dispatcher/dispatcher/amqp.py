import logging
import sys
import asyncio
import os
import ssl

import aiormq
import pamqp

from .logger import (_hostname, _uid, _username, _pid)

LOG = logging.getLogger(__name__)

class MQConnection():

    __slots__ = (
        'connection',
        'consumer',
        'publisher',
        'conf',
        'connection_properties',
        'exchange',
        'qos',
        'queue',
    )

    def __init__(self, conf, conf_section='broker'):
        self.conf = conf

        self.connection = None
        self.consumer = None # aiormq.Channel
        self.publisher = None # aiormq.Channel

        self.exchange = conf.get(conf_section, 'exchange')
        self.qos = conf.getint(conf_section, 'qos', fallback=None) # default: from server
        self.queue = conf.get(conf_section, 'queue') # let it fail if missing

        # fetch args
        connection_params = conf.getsensitive(conf_section, 'connection', raw=True)
        if isinstance(connection_params, bytes):  # secret to str
            connection_params = connection_params.decode()

        connection_name = conf.get(conf_section, 'connection_name', fallback='dispatcher')
        self.connection_properties = { "connection_name": connection_name,
                                       "FEGA": {
                                           'hostname': _hostname,
                                           'uid': _uid,
                                           'username': _username,
                                           'pid': _pid,
                                       }
                                      }

        # Handling the SSL options
        ssl_options = None
        if connection_params.startswith('amqps'):

            LOG.debug("Enforcing a TLS context")
            context = ssl.SSLContext(protocol=ssl.PROTOCOL_TLS)

            context.verify_mode = ssl.CERT_NONE
            # Require server verification
            if conf.getboolean(conf_section, 'verify_peer', fallback=False):
                LOG.debug("Require server verification")
                context.verify_mode = ssl.CERT_REQUIRED
                cacertfile = conf.get(conf_section, 'cacertfile', fallback=None)
                if cacertfile:
                    context.load_verify_locations(cafile=cacertfile)

            # Check the server's hostname
            server_hostname = conf.get(conf_section, 'server_hostname', fallback=None)
            if conf.getboolean(conf_section, 'verify_hostname', fallback=False):
                LOG.debug("Require hostname verification")
                assert server_hostname, "server_hostname must be set if verify_hostname is"
                context.check_hostname = True
                context.verify_mode = ssl.CERT_REQUIRED

            # If client verification is required
            certfile = conf.get(conf_section, 'certfile', fallback=None)
            if certfile:
                LOG.debug("Prepare for client verification")
                keyfile = conf.get(conf_section, 'keyfile')
                context.load_cert_chain(certfile, keyfile=keyfile)

            # Finally, the ssl options
            ssl_options = { 'context': context, 'server_hostname': server_hostname }

        # Finally, prepare the object
        self.connection = aiormq.Connection(connection_params,
                                            context=ssl_options)
        LOG.info('Connection to %s', self.connection.url.with_password('****'))


    def __str__(self):
        return str(self.connection)

    def __repr__(self):
        return '<{0}: "{1}">'.format(self.__class__.__name__, str(self))

    async def connect(self):
        #
        # Since we use a consumer, we are not gonna get many disconnections
        # from the server regarding the publisher.
        # If the broker disconnects (eg, upon restart), we do not reconnect
        # and let the scheduler restart the service
        #
        # So we only create the objects once, and let exceptions be raised on connection errors.
        await self.connection.connect(self.connection_properties)
        assert self.connection.publisher_confirms, 'AMQP server must support publisher confirms'
        
        self.consumer = await self.connection.channel()
        assert self.consumer, "Invalid consumer channel"

        self.publisher = await self.connection.channel(publisher_confirms=True)
        assert self.publisher, "Invalid publisher channel"

        LOG.info('Connected to %s', self.connection.url.with_password('****'))

    async def consume(self, on_message, **kwargs):

        if self.qos:
            LOG.debug('QOS to %s', self.qos)
            await self.consumer.basic_qos(prefetch_count=self.qos)

        LOG.info('Consuming from <%s>', self.queue)
        return await self.consumer.basic_consume(self.queue, on_message, **kwargs)


    async def publish(self, correlation_id, routing_key, message):

        properties = {
            'delivery_mode': 2,
            'content_type': 'application/json',
        }

        if correlation_id:
           properties['correlation_id'] = correlation_id
 
        LOG.debug("Publishing [%s]: [ex: %s | rk: %s]", correlation_id, self.exchange, routing_key)
        LOG.debug('=> %s', message)
        try:
            await self.publisher.basic_publish(message.encode(),
                                               exchange=self.exchange,
                                               routing_key=routing_key,
                                               properties=aiormq.spec.Basic.Properties(**properties))
            return True
        except (aiormq.exceptions.AMQPError,
                aiormq.exceptions.AMQPConnectionError,
                pamqp.exceptions.PAMQPException) as e:
            LOG.error("AMQP error: %r", e)
            return False
        except Exception as e:
            LOG.error("%r", e)
            return False
