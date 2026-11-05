import logging

from crypt4gh.keys import get_public_key, get_private_key
from crypt4gh import sodium

LOG = logging.getLogger(__name__)

class C4GHFileKey():
    """Loading a Crypt4GH-formatted file, and unlocking it using a passphrase.

    See https://crypt4gh.readthedocs.io/en/latest/keys.html
    """

    def __init__(self, filepath, passphrase):

        if isinstance(passphrase, bytes):  # to str
            passphrase = passphrase.decode()

        assert(filepath and passphrase)

        LOG.debug('Unlocking private key: %s', filepath)
        self.seckey = get_private_key(filepath, lambda: passphrase)  # callback

        # Don't bother reading the public key from file,
        # We can simply recompute it from the private key
        self.pubkey = sodium.derive_pk(self.seckey)

        LOG.debug('Successfully loaded from %s', filepath)

    @property
    def public(self):
        """Get the public key part.

        Returns 32 bytes
        """
        return self.pubkey

    @property
    def private(self):
        """Get the private key part.

        Returns 32 bytes
        """
        return self.seckey

class C4GHFilePubKey():
    """Loading a Crypt4GH-formatted public key from a file."""

    def __init__(self, filepath):
        LOG.debug('Loading %s from %s', type(self), filepath)
        # We use the parser provided in the crypt4gh.keys module
        self.pubkey = get_public_key(filepath)
        LOG.debug('Successfully loaded from %s', filepath)

    @property
    def public(self):
        """Get the public key part.

        Returns 32 bytes
        """
        return self.pubkey

    @property
    def private(self):
        raise NotImplementedError('Not accessible')


# We don't use default values: bark if not supplied
def load(config, key):
    section = config.get('DEFAULT', key)
    # assert key in ('service_key', 'master_key')
    LOG.debug('Loading %s', section)
    t = config.get(section, 'type')
    match t:
        case 'c4gh-public':
            return C4GHFilePubKey(config.get(section, 'filepath'))
        case 'c4gh-private':
            return C4GHFileKey(config.get(section, 'filepath'),
                               config.getsensitive(section, 'passphrase')
                               )
        case _:
            raise ValueError(f"Unknown key type {t} for {key}")
