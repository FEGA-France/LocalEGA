import logging
import sys

from . import main

LOG = logging.getLogger(__name__)

if __name__ == '__main__':

    try:
        if len(sys.argv) < 2:
            print(f'Usage: {sys.argv[0]} <conf_file>')
            sys.exit(1)
        main(sys.argv[1])
    except KeyboardInterrupt as e:
        LOG.warning('Cancelled')
        sys.exit(0)
    except Exception as e:
        LOG.error('%s', e)
        sys.exit(2)
