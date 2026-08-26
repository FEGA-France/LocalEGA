# Distribution system for a Federated EGA node

This repository contains the code part of the [LocalEGA software stack](https://github.com/EGA-archive/LocalEGA).  
It allows the distribution of Crypt4GH-encrypted files.

## Summary

The required packages are:
* libfuse 3
* OpenSSL
* libpq
* glib-2.0
* Development tools: make cmake gcc git autoconf patch ...
* PAM

On Debian/Ubuntu, you can install the dependencies with:
```bash
apt-get update && \
apt-get install -y --no-install-recommends \
            ca-certificates pkg-config git gcc make \
            autoconf patch meson ninja-build openssl \
            libssl-dev libpq-dev libpam0g-dev libglib2.0-dev libfuse3-dev
```

You need to install the following components:

* the distribution file system, to [present Crypt4GH files](src/crypt4gh-fs), or [decrypt them locally](src/crypt4gh-sqlite)
* the [NSS module](src/nss) (to find users)
* the [PAM modules](src/pam) to create the user's homedirectory and automount user's file system
* [patch and deploy the SFTP server](src/openssh)


Once installed, you can extend the Vault database with [functions used
by the file system](db). They allow the fuse filesystem to be smaller,
as most string manipulation are done in the Postgres database itself.

# Installation

## Preliminaries

On Debian/Ubuntu, you can install the dependencies with:
```bash
apt-get update && \
apt-get install -y --no-install-recommends \
            ca-certificates pkg-config git gcc make \
            autoconf patch meson ninja-build openssl \
            libssl-dev libpq-dev libpam0g-dev libglib2.0-dev libfuse3-dev
```

We install all in `/opt/LocalEGA`:
```bash
sudo mkdir -p /opt/LocalEGA/{bin,etc,lib,homes}
```

Install libfuse 3.16.2 from the [official repository](https://github.com/libfuse/libfuse).

Uncomment `user_allow_other` in `/usr/local/etc/fuse.conf`

## Install the live distribution: crypt4gh.fs
```bash
cd crypt4gh-fs
autoreconf -i
./configure --prefix=/opt/LocalEGA
make
sudo make install
```
Find more information in [src/crypt4gh-fs](src/crypt4gh-fs/README.md).

## Install the NSS module

```bash
cd nss
make 
sudo make install

echo '/opt/LocalEGA/lib' > /etc/ld.so.conf.d/LocalEGA.conf

sudo ldconfig -v | grep egafiles
```

In `/etc/nsswitch.conf`, add `egafiles` such as:
```
passwd:         files egafiles systemd
group:          files egafiles systemd
shadow:         files egafiles
```
Find more information in [src/nss](src/nss/README.md).

## PAM
```bash
cd pam
make
sudo make install
```
Find more information in [src/pam](src/pam/README.md).

## OpenSSH

Follow the instructions in [src/openssh/README](src/openssh/README.md).

## Vault-DB extension

Go to `LocalEGA/deploy/docker` and run:
```bash
make load
```
This will load the files in load the SQL files in [src/db](src/db).

Update the `nss.*` configurations in `pg.conf`.

Recreate the container:
```bash
docker-compose up -d vault-db
```

Change permissions of the landing directories for the NSS files:
```bash
sudo chown 999 /opt/LocalEGA/etc/nss
sudo chown 999:lega /opt/LocalEGA/etc/authorized_keys
sudo chmod g+s /opt/LocalEGA/etc/authorized_keys
```

Call the NSS file creation:
```
make nss
```

And test it:
```bash
id jane
```

You should see:
```
uid=10001(jane) gid=20000(requesters) groups=20000(requesters)
```

Finally, for the Crypt4GH-fuse, copy the sample config file and change permissions:
```bash
cp crypt4gh-fs/fs.conf.sample /opt/LocalEGA/etc/fuse-vault-db.conf
chmod 600 /opt/LocalEGA/etc/fuse-vault-db.conf
```
Update password in `fuse-vault.db.conf`.
