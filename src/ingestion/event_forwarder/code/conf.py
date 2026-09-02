"""Configuration Module provides a dictionary-like with configuration settings.

It also sets up the logging.
"""

import logging
import os
import configparser
import warnings
import stat
from logging.config import dictConfig
from pathlib import Path
import json

from .amqp import MQConnection
from .es import ESClient

LOG = logging.getLogger(__name__)

def get_from_file(filepath, mode='rb', remove_after=False):
    """Return file content.

    Raises ValueError if it errors.
    """
    try:
        with open(filepath, mode) as s:
            return s.read()
    except Exception as e:  # Crash if not found, or permission denied
        raise ValueError(f'Error loading {filepath}') from e
    finally:
        if remove_after:
            try:
                os.remove(filepath)
            except Exception:  # Crash if not found, or permission denied
                LOG.warning('Could not remove %s', filepath, exc_info=True)


def convert_sensitive(value):
    """Fetch a sensitive value from different sources.

    * If `value` starts with 'env://', we strip it out and the remainder acts as the name of an environment variable to read.
    If the environment variable does not exist, we raise a ValueError exception.

    * If `value` starts with 'file://', we strip it out and the remainder acts as the filepath of a file to read (in text mode).
    If any error occurs while read the file content, we raise a ValueError exception.

    * If `value` starts with 'secret://', we strip it out and the remainder acts as the filepath of a file to read (in binary mode), and we remove it after.
    If any error occurs while read the file content, we raise a ValueError exception.

    * If `value` starts with 'value://', we strip it out and the remainder acts as the value itself.
    It is used to enforce the value, in case its content starts with env:// or file:// (eg a file:// URL).

    * Otherwise, `value` is the value content itself.
    """
    if value is None:  # Not found
        return None

    # Short-circuit in case the value starts with value:// (ie, it is enforced)
    if value.startswith('value://'):
        return value[8:]

    if value.startswith('env://'):
        envvar = value[6:]
        LOG.debug('Loading value from env var: %s', envvar)
        warnings.warn(
            "Loading sensitive data from environment variable is not recommended "
            "and might be removed in future versions."
            " Use secret:// instead",
            DeprecationWarning, stacklevel=4
        )
        envvalue = os.getenv(envvar, None)
        if envvalue is None:
            raise ValueError(f'Environment variable {envvar} not found')
        return envvalue

    if value.startswith('file://'):
        path = value[7:]
        LOG.debug('Loading value from path: %s', path)
        statinfo = os.stat(path)
        if statinfo.st_mode & stat.S_IRGRP or statinfo.st_mode & stat.S_IROTH:
            warnings.warn(
                "Loading sensitive data from a file that is group or world readable "
                "is not recommended and might be removed in future versions."
                " Use secret:// instead",
                DeprecationWarning, stacklevel=4
            )
        return get_from_file(path, mode='rt')  # str

    if value.startswith('secret://'):
        path = value[9:]
        LOG.debug('Loading secret from path: %s', path)
        return get_from_file(path, mode='rb', remove_after=True)  # bytes

    # It's the value itself (even if it starts with postgres:// or amqp(s)://)
    return value



class Configuration(configparser.RawConfigParser):
    """Configuration from a config file."""

    __slots__ = ('conf_file', '_mq', '_es')

    def __init__(self, conf_file):
        self.conf_file = conf_file
        self._mq = None
        self._es = None

        # Load the configuration settings
        super().__init__(self,
                         delimiters=('=', ':'),
                         comment_prefixes=('#', ';'),
                         default_section='DEFAULT',
                         interpolation=None,
                         converters={
                             'sensitive': convert_sensitive,
                         })
        if (
                not conf_file  # has no value
                or
                not os.path.isfile(conf_file)  # does not exist
                or
                not os.access(conf_file, os.R_OK)  # is not readable
        ):
            raise ValueError("No configuration settings found")

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
            self._mq = MQConnection(self, conf_section='broker')
        return self._mq

    @property
    def es(self):
        if self._es is None:
            self._es = ESClient(self, conf_section='elasticsearch')
        return self._es

