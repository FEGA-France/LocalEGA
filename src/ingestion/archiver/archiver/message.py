import logging
import json

from aiormq.abc import DeliveredMessage

LOG = logging.getLogger(__name__)

_sentinel = object()

class FEGAMessage:

    def __init__(self, message, max_retry=None):
        self.message = message

        assert isinstance(message, DeliveredMessage), f"Should be a DeliveredMessage. Got type: {type(message)}"

        self._body = _sentinel
        self._content = _sentinel
        self._delivery_tag = _sentinel
        self._correlation_id = _sentinel
        self._type = _sentinel
        self._parsed = _sentinel
        self._properties = _sentinel
        self._max_retry = max_retry or 10 # enforce default

    @property
    def job_type(self):
        if self._type is _sentinel:
            self._type = self.parsed.get('type', None)
        return self._type

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
            try:
                self._correlation_id = self.properties.correlation_id
            except KeyError as e:
                self._correlation_id = None
        return self._correlation_id

    @property
    def parsed(self):
        if self._parsed is _sentinel:
            self._parsed = json.loads(self.content)
        return self._parsed

    async def ack(self, **kwargs):
        LOG.info('Acking: %s', self)
        return await self.channel.basic_ack(self.delivery_tag, **kwargs)

    async def nack(self, **kwargs):
        LOG.info('Nacking: %s', self)
        return await self.channel.basic_nack(self.delivery_tag, **kwargs)

    async def reject(self, **kwargs):
        LOG.info('Rejecting: %s', self)
        return await self.channel.basic_reject(self.delivery_tag, **kwargs)

    @property
    def reached_max_retry(self):
        count = self.properties.headers.get('x-retry-count', 0)
        return count > self._max_retry

    def __str__(self):
        return f'<Message {self.delivery_tag} | job: {self.job_type}>'

    def __repr__(self):
        return str(self) + '\n' + self.content

    def __getattr__(self, item):
        return getattr(self.message, item)
