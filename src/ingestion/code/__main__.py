import logging
import sys

LOG = logging.getLogger(__name__)

if __name__ == '__main__':

    try:
        command = sys.argv[1]
        match command:
            case 'dispatcher':
                if len(sys.argv) < 2:
                    print(f'Usage: {sys.argv[0]} dispatcher <conf_file>')
                    sys.exit(1)
                from . import dispatcher
                dispatcher.main(sys.argv[2])
            case 'ingester':
                if len(sys.argv) < 3:
                    print(f'Usage: {sys.argv[0]} ingester <conf_file> <queue>')
                    sys.exit(1)
                from . import ingester
                ingester.main(sys.argv[2], sys.argv[3])
            case 'archiver':
                if len(sys.argv) < 3:
                    print(f'Usage: {sys.argv[0]} archiver <conf_file> <queue>')
                    sys.exit(1)
                from . import archiver
                archiver.main(sys.argv[2], sys.argv[3])
            case _:
                raise ValueError(f'Invalid command "{command}"')
    except KeyboardInterrupt as e:
        LOG.warning('Cancelled')
        sys.exit(0)
    except Exception as e:
        LOG.error('%s', e)
        sys.exit(2)
