# Vault database updates for distribution

You SQL files in the directory contains the database functions used by the distribution system.

They are file system listings, Crypt4GH header re-encryption, and triggers to build the NSS files.

You'll need to install the [Crypt4GH postgres
extension](https://github.com/silverdaz/pg_crypt4gh), and update the
postgres configuration file (usually `pg.conf`) with the
`crypt4gh.master_seckey` setting. In particular, if the [crypt4gh
python package](https://pypi.org/project/crypt4gh/) is installed, you
can get the HEX format of the private key with a few lines of python code
```python
import crypt4gh.keys
key = crypt4gh.keys.get_private_key("/path/to/master.key.sec", lambda: "passphrase")
print(key.hex())
```
Replace `/path/to/master.key.sec` and the `passphrase` accordingly.
