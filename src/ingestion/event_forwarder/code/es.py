import logging
import sys
import os

from elasticsearch import Elasticsearch, AsyncElasticsearch, RequestError

LOG = logging.getLogger(__name__)

class ESClient():

    __slots__ = (
        'client',
        'conf',
        'index_name',
        'url',
        'cacert',
        'verify_hostname',
    )

    def __init__(self, conf, conf_section='elasticsearch'):
        self.conf = conf
        
        self.url = conf.getsensitive(conf_section, 'url', raw=True)
        self.index_name = conf.get(conf_section, 'index')
        self.cacert = conf.get(conf_section, 'cacert', fallback=None)
        self.verify_hostname = conf.getboolean(conf_section, 'verify_hostname', fallback=False)

        # Make sure the index is created,
        # let it raise the ApiError otherwise
        _client = Elasticsearch(self.url,
                                ca_certs=self.cacert,
                                verify_certs=self.verify_hostname)
        LOG.info('Checking index "%s"', self.index_name)
        if not _client.indices.exists(index=self.index_name):
            LOG.info('Creating index "%s"', self.index_name)
            _client.indices.create(
                index = self.index_name,
                body = {
                    "settings": {
                        "number_of_shards": 1,
                        "number_of_replicas": 1
                    },
                    "mappings": {
                        "properties": {
                            '@timestamp': {'type': 'date', 'format': 'epoch_second'},
                            'exchange':   {'type': 'keyword'},
                            'routing_key': {'type': 'keyword'},
                            # properties
                            # See https://gmr.github.io/pamqp/api/commands/#pamqp.commands.Basic.Properties
                        'content_type': {'type': 'keyword'},
                        'content_encoding': {'type': 'keyword'},	
                        'correlation_id':  {'type': 'text'}, #
                        'delivery_mode': {'type': 'integer'}, # Non-persistent (1) or persistent (2)
                        'priority': {'type': 'integer'}, # 0 to 9
                        'reply_to': {'type': 'text'}, # Address to reply to
                        'expiration': {'type': 'text'}, # Message expiration specification
                        'message_id':  {'type': 'text'}, # Application message identifier
                        'message_type':  {'type': 'text'}, # Message type name
                        'user_id':  {'type': 'keyword'}, # Creating user id
                        'app_id':  {'type': 'keyword'}, # Creating application id
                        # Adding headers
                        'headers':    {'type': 'text'}, # json-formatted key/value pairs
                        # and payload
                        'payload':    {'type': 'text'},
                        }
                    }
                })

        # All good => create an async client
        self.client = AsyncElasticsearch(self.url,
                                         ca_certs=self.cacert,
                                         verify_certs=self.verify_hostname)


    def __str__(self):
        return str(self.client)

    def __repr__(self):
        return '<{0}: "{1}">'.format(self.__class__.__name__, str(self))

    async def index(self, document):
        LOG.debug('Sending document to index: %s\n%s', self.index_name, document)
        try:
            return await self.client.index(index=self.index_name,
                                           document=document)
        except Exception as e:
            LOG.error('Indexing %r', e)
            raise
