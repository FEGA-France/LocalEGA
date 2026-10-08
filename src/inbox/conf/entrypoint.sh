#!/bin/bash

set -e

# Exit if failed ?
mkdir -p /ega/inbox/{home,data,tools}
chown root:root /ega/inbox
chmod 755 /ega/inbox
chown lega:lega /ega/inbox/{home,data,tools}
chmod 2700 /ega/inbox/{home,data,tools}

echo 'Creating rsa and ed25519 keys (on each boot)'
rm -f /etc/{ega,ssh}/ssh_host_{rsa,ed25519}_key
# No passphrase so far
/opt/openssh/bin/ssh-keygen -t rsa     -N '' -f /etc/ega/ssh_host_rsa_key
/opt/openssh/bin/ssh-keygen -t ed25519 -N '' -f /etc/ega/ssh_host_ed25519_key


if [[ -n "${WITH_SYSLOG}" ]]; then
    # Syslog settings
    cat > /etc/rsyslog.conf <<'EOF'
module(load="imuxsock")
$FileOwner root
$FileGroup lega
$FileCreateMode 0640
$DirCreateMode 0755
$Umask 0022
$WorkDirectory /var/spool/rsyslog
$IncludeConfig /etc/rsyslog.d/*.conf
*.*;auth,authpriv.none		-/var/log/syslog
*.emerg				:omusrmsg:*
EOF

    cat > /etc/rsyslog.d/sftp.conf <<'EOF'
# create additional sockets for the sftp chrooted users
input(type="imuxsock" Socket="/ega/inbox/dev/log" CreatePath="on")
local4.*   /var/log/lega.log
EOF
    echo "Starting Rsyslog"
    rsyslogd
fi

echo "Starting the SFTP server"
exec /opt/openssh/sbin/sshd -D -e -f /etc/ega/sshd_config
