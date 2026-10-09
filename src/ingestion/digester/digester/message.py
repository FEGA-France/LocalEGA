import logging
import json

LOG = logging.getLogger(__name__)

_sentinel = object()

class FEGAMessage:

    def __init__(self, message, max_retry=None):
        self.message = message

        self._body = _sentinel
        self._content = _sentinel
        self._delivery_tag = _sentinel
        self._correlation_id = _sentinel
        self._json = _sentinel
        self._properties = _sentinel
        self._type = _sentinel
        self._max_retry = max_retry or 10 # enforce default

    def __str__(self):
        try:
            return f'<Message {self.delivery.delivery_tag} | job: {self.job_type}>'
        except Exception as e:
            return f'<Message {self.delivery.delivery_tag} | job: None>'

    def __repr__(self):
        return str(self) +  '\n' + self.content

    @property
    def body(self):
        if self._body is _sentinel:
            self._body = self.message.body
        return self._body

    @property
    def content(self):
        if self._content is _sentinel:
            self._content = self.body.decode()
        return self._content

    @property
    def delivery_tag(self):
        if self._delivery_tag is _sentinel:
            self._delivery_tag = self.message.delivery.delivery_tag
        return self._delivery_tag

    @property
    def properties(self):
        if self._properties is _sentinel:
            self._properties = self.message.header.properties
        return self._properties


    @property
    def correlation_id(self):
        if self._correlation_id is _sentinel:
            self._correlation_id = self.properties.correlation_id
        return self._correlation_id

    @property
    def json(self):
        if self._json is _sentinel:
            self._json = json.loads(self.content)
        return self._json

    @json.setter
    def json(self, value):
        assert isinstance(value, dict)
        # self._body = value.encode()
        # self._content = json.dumps(value)
        self._json = value

    @property
    def job_type(self):
        if not self._type:
            self._type = self.json.get('type', None)
        return self._type

    def __getattr__(self, item):
        return getattr(self.message, item)

    async def ack(self, **kwargs):
        LOG.info('Acking: %s', self)
        return await self.channel.basic_ack(self.delivery_tag, **kwargs)

    async def nack(self, **kwargs):
        LOG.info('Nacking: %s', self)
        return await self.channel.basic_nack(self.delivery_tag, **kwargs)

    async def reject(self, **kwargs):
        LOG.info('Rejecting: %s', self)
        return await self.channel.basic_reject(self.delivery_tag, **kwargs)
