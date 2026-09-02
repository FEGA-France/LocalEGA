# -*- coding: utf-8 -*-
# __init__ is here so that we don't collapse in sys.path with another lega module

"""The lega package contains code to ships *Local EGA* MQ messages to Elasticsearch."""

__title__ = 'Local EGA'
__version__ = '2.0'
__author__ = 'Frédéric Haziza'
__author_email__ = 'frederic.haziza@france-bioinformatique.fr'
__license__ = 'Apache License 2.0'
__copyright__ = __title__ + ' @ IFB, Marseille'

import sys
assert sys.version_info >= (3, 10), "This tool requires python version 3.10 or higher"

import logging
logging.logMultiprocessing = False
logging.logThreads = False
logging.logAsyncioTasks = False
logging.logProcesses = False
logging.raiseExceptions = False

# Send warnings using the package warnings to the logging system
# The warnings are logged to a logger named 'py.warnings' with a severity of WARNING.
# See: https://docs.python.org/3/library/logging.html#integration-with-the-warnings-module
import warnings
logging.captureWarnings(True)
warnings.simplefilter("default")  # do not ignore Deprecation Warnings
