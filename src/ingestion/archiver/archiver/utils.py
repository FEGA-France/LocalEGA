# -*- coding: utf-8 -*-

import logging
import os

from json import loads as parse_json

LOG = logging.getLogger(__name__)

# try it first
_SETXATTR_SUPPORTED = getattr(os, 'setxattr', False)
_REMOVEXATTR_SUPPORTED = getattr(os, 'removexattr', False)

def format_time(seconds):
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    if hours > 0:
        return f'{int(hours)}:{int(minutes):02}:{int(seconds):02}'
    elif minutes > 0:
        return f'{int(minutes):02}:{int(seconds):02}'
    else:
        return f'{int(seconds)} seconds'


def _set_info_file(path, attribute, value):
    filepath = path + '.' + attribute
    LOG.debug('setxattr: %s', filepath)
    with open(filepath, 'wt') as f:
        f.write(value) # str
    os.chmod(filepath, 0o400) # don't bother with umask, and previous permissions

def set_info(path, attribute, value):
    global _SETXATTR_SUPPORTED
    assert attribute, "Invalid attribute"
    try:
        if _SETXATTR_SUPPORTED:
            os.setxattr(path, 'user.' + attribute, value.encode(), flags=0, #  XATTR_REPLACE or XATTR_CREATE
                        follow_symlinks=False)
        else:
            _set_info_file(path, attribute, value)
    except Exception as e:
        #LOG.debug('setxattr: %s', e)
        _SETXATTR_SUPPORTED = False
        _set_info_file(path, attribute, value)

def _remove_info_file(path, attribute):
    filepath = path + '.' + attribute
    try:
        os.chmod(filepath, 0o600) # don't bother with umask, and previous permissions
        os.unlink(filepath)
    except OSError as e:
        pass

def remove_info(path, attribute):
    global _REMOVEXATTR_SUPPORTED
    assert attribute, "Invalid attribute"
    try:
        if _REMOVEXATTR_SUPPORTED:
            os.removexattr(path, 'user.' + attribute, follow_symlinks=False)
        else:
            _remove_info_file(path, attribute)
    except Exception as e:
        #LOG.debug('getxattr: %s', e)
        _REMOVEXATTR_SUPPORTED = False
        _remove_info_file(path, attribute)



class ChecksumsNotMatching(Exception):
    """Raised when 2 checksums don't match."""

    def __init__(self, path, md1, md2):
        self.path = path
        self.md1 = md1
        self.md2 = md2

    def __str__(self):
        return f'Checksums for {self.path} do not match'

    def __repr__(self):
        return f'Checksums for {self.path} do not match:\n* {self.md1}\n* {self.md2}'
