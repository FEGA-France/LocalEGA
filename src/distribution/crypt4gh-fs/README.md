# Exposing Crypt4GH-encrypted files

This file system retrieves files and directories from the Vault database. It is paired with the [SQL implementation](../src/db) of the file system.

On Debian/Ubuntu, you can install the dependencies with:
```bash
apt-get update && \
apt-get install -y --no-install-recommends \
            pkg-config git gcc make autoconf \
            libssl-dev libpq-dev libglib2.0-dev libfuse3-dev
```

## Installation

```bash
autoreconf -i
./configure --prefix=/opt/LocalEGA
make
sudo make install
```

## Security and testing

The file system requires to read a configuration file containing the credentials to connect to the Vault database. The FUSE file system runs in userland, while the configuration file is sensitive and should remain invisible to most users (for example, be owned by root and only readable by root).

Therefore, a suitable strategy is to open the file by the root user and pass the file descriptor to the userland process. This is what the [PAM module](../src/pam) implements.

For testing purposes, you can make the configuration file readable by the test user, and call the fuse file system using the following impersonation script:

```bash
#!/bin/bash

if [[ "$(id -u)" != "0" ]]; then
    echo "You need to be root" >&2
    exit 1
fi

if [[ "$#" -lt 1 ]]; then
    echo "Usage: $0 <username> [options]" >&2
    exit 1
fi

exec 5</opt/LocalEGA/etc/fuse-vault-db.conf
exec 9>/dev/null

prog=/opt/LocalEGA/bin/crypt4gh-db.fs

username=$1
shift

setpriv --ruid $(id -u $username) --rgid $(id -g $username) --groups $(id -g lega) -- \
	${prog} \
	   -o ro,default_permissions,allow_root,fsname=EGAFS,max_idle_threads=2 \
	   -o conf_fd=5 \
	   -o parent_fd=9 \
	   $@ \
	   /opt/LocalEGA/homes/$username/outbox

```

Note: the `setpriv` utility allows to start a process as another user, including attaching extra groups to the running process.
