#!/bin/bash

set -e

# Exit if failed ?
mkdir -p /ega/inbox/upload
chown root:root /ega/inbox
chmod 755 /ega/inbox
chown lega:lega /ega/inbox/upload
chmod 2700 /ega/inbox/upload

echo 'Creating rsa and ed25519 keys (on each boot)'
rm -f /etc/{ega,ssh}/ssh_host_{rsa,ed25519}_key
# No passphrase so far
/opt/openssh/bin/ssh-keygen -t rsa     -N '' -f /etc/ega/ssh_host_rsa_key
/opt/openssh/bin/ssh-keygen -t ed25519 -N '' -f /etc/ega/ssh_host_ed25519_key

if [ -f /etc/rabbitmq/definitions.json ]; then
    echo 'Starting the local RabbitMQ'
    # enforce rabbitmq user
    find /var/lib/rabbitmq \! -user rabbitmq -exec chown rabbitmq '{}' +
    chown -R rabbitmq /etc/rabbitmq
    # ... and cue music
    gosu rabbitmq rabbitmq-server &
fi

echo "Starting the SFTP server"
exec /opt/openssh/sbin/sshd -D -e -f /etc/ega/sshd_config
