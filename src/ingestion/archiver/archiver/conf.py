"""Configuration Module provides a dictionary-like with configuration settings.

It also sets up the logging.
"""
import logging
import os
import sys
import configparser
import warnings
from pathlib import Path
from logging.config import dictConfig
import json

from . import amqp

LOG = logging.getLogger(__name__)

class Configuration(configparser.RawConfigParser):
    """Configuration from a config file."""

    __slots__ = ('conf_file',
                 '_mq',
                 '_mq_connection_name',
                 '_db',
                 '_service_pubkey'
                 )

    def __init__(self, conf_file, mq_connection_name):
        self.conf_file = conf_file
        self._mq = None
        self._mq_connection_name = mq_connection_name
        self._db = None
        self._service_pubkey = None
        # Load the configuration settings
        super().__init__(self,
                         delimiters=('=', ':'),
                         comment_prefixes=('#', ';'),
                         default_section='DEFAULT',
                         interpolation=None)
        if (
                not conf_file  # has no value
                or
                not os.path.isfile(conf_file)  # does not exist
                or
                not os.access(conf_file, os.R_OK)  # is not readable
        ):
            warnings.warn("No configuration settings found", UserWarning, stacklevel=2)
        else:
            self.read([conf_file], encoding='utf-8')

        # Configure the logging system
        logger = self.get('DEFAULT', 'logger',
                          fallback=str(Path(__file__).parent / 'logger.json')) # default in package

        # Try in order, (1) locally, (2) in the package, (3) where the conf file is
        for p in [logger, Path(__file__).parent / logger, Path(conf_file).parent / logger]:
            if os.path.isfile(p):
                logger = p
                break
        else:
            warnings.warn(f"Logger {logger} not found", UserWarning, stacklevel=3)
                
        with open(logger, 'rt') as stream:
            dictConfig(json.load(stream))
        
    def __repr__(self):
        """Show the configuration files."""
        return f'<{self.__class__.__name__}: {self.conf_file}>'

    @property
    def mq(self):
        if self._mq is None:
            self._mq = amqp.MQConnection(self._mq_connection_name,
                                         self, conf_section='broker')
        return self._mq
