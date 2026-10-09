import logging
import ssl
import json

import aiormq

from .logger import (_hostname, _uid, _username, _pid)

LOG = logging.getLogger(__name__)

class MQConnection():

    __slots__ = (
        'connection',
        'connection_properties',
        'consumer',
        'publisher',
        'conf',
        'qos',
        'queue',
        'exchange',
        'routing_key_success',
        'routing_key_error',
    )

    def __init__(self, connection_name, conf, conf_section='broker'):
        self.conf = conf

        self.consumer = None
        self.publisher = None

        self.qos = conf.getint(conf_section, 'qos', fallback=1)
        if self.qos < 0:
            raise ValueError(f'Invalid QoS: {self.qos}')
        self.queue = conf.get(conf_section, 'queue') # let it fail if missing
        self.exchange = conf.get(conf_section, 'exchange') # let it fail if missing

        # let it fail if missing
        self.routing_key_success      = conf.get(conf_section, 'routing_key_success') 
        self.routing_key_error        = conf.get(conf_section, 'routing_key_error')

        #
        # Since we use a consumer, we are not gonna get many disconnections
        # from the server regarding the publisher.
        # If the broker disconnects (eg, upon restart), we do not reconnect
        # and let the scheduler restart the service
        #
        # So we only create the objects once, and let exceptions be raised on connection errors.
        # fetch args
        connection_params = self.conf.getsensitive(conf_section, 'connection', raw=True)
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
            if self.conf.getboolean(conf_section, 'verify_peer', fallback=False):
                LOG.debug("Require server verification")
                context.verify_mode = ssl.CERT_REQUIRED
                cacertfile = self.conf.get(conf_section, 'cacertfile', fallback=None)
                if cacertfile:
                    context.load_verify_locations(cafile=cacertfile)

            # Check the server's hostname
            server_hostname = self.conf.get(conf_section, 'server_hostname', fallback=None)
            if self.conf.getboolean(conf_section, 'verify_hostname', fallback=False):
                LOG.debug("Require hostname verification")
                assert server_hostname, "server_hostname must be set if verify_hostname is"
                context.check_hostname = True
                context.verify_mode = ssl.CERT_REQUIRED

            # If client verification is required
            certfile = self.conf.get(conf_section, 'certfile', fallback=None)
            if certfile:
                LOG.debug("Prepare for client verification")
                keyfile = self.conf.get(conf_section, 'keyfile')
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
        LOG.info('Connected to %s', self.connection.url.with_password('****'))

        assert self.connection.publisher_confirms, 'AMQP server must support publisher confirms'
        
        self.consumer = await self.connection.channel(publisher_confirms=False)
        assert self.consumer, "Invalid consumer channel"

        LOG.debug('QOS to %s', self.qos)
        await self.consumer.basic_qos(prefetch_count=self.qos)

        self.publisher = await self.connection.channel(publisher_confirms=True)
        assert self.publisher, "Invalid publisher channel"

    async def consume(self, on_message, **kwargs):
        LOG.info('Consuming from <%s>', self.queue)
        return await self.consumer.basic_consume(self.queue, on_message, **kwargs)

    async def _publish(self, message, routing_key, correlation_id=None):

        properties = {
            'delivery_mode': 2,
            'content_type': 'text/plain',
        }
        if correlation_id:
            properties['correlation_id'] = correlation_id

        if isinstance(message, FEGAMessage):
            _message = message.body
            properties['content_type']='application/json'
            properties = message.properties # reset
        elif isinstance(message, str):
            _message = message.encode()
        elif isinstance(message, bytes):
            _message = message
        else:
            _message = json.dumps(message, indent=4).encode()
            properties['content_type']='application/json'

        if isinstance(properties, dict):
            properties = aiormq.spec.Basic.Properties(**properties)

        LOG.debug("Publishing to exchange: %s [routing key: %s]", self.exchange, routing_key)
        # let it raise exceptions on disconnections, etc...
        # the message will be nacked+requeued
        await self.publisher.basic_publish(_message,
                                           exchange=self.exchange,
                                           routing_key=routing_key,
                                           properties=properties)


    async def publish_error(self, message):
        await self._publish(message, self.routing_key_error)

    async def publish_success(self, message):
        await self._publish(message, self.routing_key_success)
