#/bin/env bash

HERE="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"

# Add 2 groups
addgroup --gid 3000 users # || :
addgroup --gid 10000 fega

# Add 2 users
useradd -u 2001 -g users -M -s /usr/sbin/nologin colleague
useradd -u 2002 -M -s /usr/sbin/nologin guest

# Move files
mkdir -m 755 /data
umask 0027
mkdir /data/{vault,fega}
chgrp fega /data/{vault,fega}
chmod 2750 /data/vault
cp $HERE/example.txt example/lorem.txt.c4gh.payload /data/vault/.

# register the filesystem
echo "fega" > /etc/filesystems

# Configuration files
mkdir -m 700 /etc/fega
cp $HERE/options.conf /etc/fega/options.conf
cp $HERE/example.seckey /etc/fega/seckey
cp $HERE/example.sqlite /etc/fega/fs.sqlite
chmod 400 /etc/fega/seckey
chmod 600 /etc/fega/fs.sqlite /etc/fega/options.conf

# Check
ls -al /etc/fega
chown runner:users /data/fega
ls -ald /data/fega

# Prepare the mount unit
cp $HERE/data-fega.mount /etc/systemd/system/data-fega.mount
systemctl daemon-reload
