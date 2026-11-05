import sys
import logging
import asyncio
import json
import os
import ssl

import aiormq
import pamqp

from .logger import (_hostname, _uid, _username, _pid)
from .message import FEGAMessage

LOG = logging.getLogger(__name__)

class MQConnection():
    """ Connection abstraction """

    __slots__ = (
        'connection',
        'consumer',
        'publisher',
        'lock',
        'exchange',
        'qos',
        'connection_properties'
    )

    def __init__(self, connection_name, conf, conf_section='broker'):
        self.connection = None
        self.consumer = None # aiormq.Channel
        self.publisher = None # aiormq.Channel
        self.lock = asyncio.Lock()

        self.exchange = conf.get(conf_section, 'exchange', fallback=None)
        self.qos = conf.getint(conf_section, 'qos', fallback=None) # default: from server

        # fetch args
        connection_params = conf.getsensitive(conf_section, 'connection', raw=True)
        if isinstance(connection_params, bytes):  # secret to str
            connection_params = connection_params.decode()

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
        return str(self.connection) if self.connection else "MQConnection"

    def __repr__(self):
        return '<{0}: "{1}">'.format(self.__class__.__name__, str(self))

    async def connect(self):
        async with self.lock:
            await self.connection.connect(self.connection_properties)
            LOG.debug('Creating the consumer and publisher channels')
            self.consumer = await self.connection.channel()
            self.publisher = await self.connection.channel()

    async def consume(self, queue, on_message, qos=None, **kwargs):
        assert queue, "No queue specified"
        if self.consumer is None:
            await self.connect()
        if self.consumer.is_closed:
            LOG.debug("Consumer Channel closed: reconnecting")
            await asyncio.gather(self.connection.close(), return_exceptions=False)
            self.consumer = None
            await self.connect()

        if qos:
            LOG.debug('QOS to %s', qos)
            await self.consumer.basic_qos(prefetch_count=qos)

        LOG.info('Consuming from <%s>', queue)
        return await self.consumer.basic_consume(queue, on_message, **kwargs)


    async def _publish(self, message, routing_key,
                      exchange=None,
                      correlation_id=None,
                      headers=None):

        if not exchange:
            exchange = self.exchange
        assert exchange, 'Missing exchange while publishing'
            
        if self.publisher is None:
            await self.connect()
        if self.publisher.is_closed:
            LOG.debug("Publisher Channel closed: reconnecting")
            await asyncio.gather(self.connection.close(), return_exceptions=False)
            self.publisher = None
            await self.connect()

        if self.publisher is None:
            return False

        properties = {
            'delivery_mode': 2,
            'content_type': 'text/plain',
        }
        if correlation_id:
            properties['correlation_id'] = correlation_id

        if headers:
            assert isinstance(headers, dict), "Headers should be a dict"
            # LOG.debug('\tHeaders: %s', headers)
            properties['headers'] = headers

        if isinstance(message, FEGAMessage):
            _message = message.body
            properties['content_type']='application/json'
            properties['correlation_id'] = message.correlation_id
            # Todo: reset with the message.properties
        elif isinstance(message, str):
            _message = message.encode()
        elif isinstance(message, bytes):
            _message = message
        else:
            _message = json.dumps(message, indent=4).encode()
            properties['content_type']='application/json'

            
        LOG.debug("Publishing to exchange: %s [routing key: %s]", exchange, routing_key)
        await self.publisher.basic_publish(_message,
                                           exchange=exchange,
                                           routing_key=routing_key,
                                           properties=aiormq.spec.Basic.Properties(**properties)
                                           )
        return True

    async def publish(self, *args, reraise_exception=True, **kwargs):
        try:
            return await self._publish(*args, **kwargs)
        # except (aiormq.exceptions.AMQPError,
        #         aiormq.exceptions.AMQPConnectionError,
        #         pamqp.exceptions.PAMQPException) as e:
        #     LOG.error("AMQP error: %r", e)
        #     return False
        except Exception as e:
            LOG.error("Publish error: %r", e)
            if reraise_exception:
                raise
            return False
