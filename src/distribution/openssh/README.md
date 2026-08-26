# Install SSHD for EGA requesters


For Ubuntu, install the following packages:

	apt update
	apt upgrade -y
	apt install -y --no-install-recommends ca-certificates pkg-config git gcc make automake autoconf libtool bzip2 zlib1g-dev libssl-dev libedit-dev libpam0g-dev libpq-dev libsystemd-dev uuid-dev

Then run the following to configure it with its own user/group and privilege-separation.

	export OPENSSH_DIR=/opt/LocalEGA
	export SSHD_UID=75
	export SSHD_GID=75
	export OPENSSH_PRIVSEP_PATH=/run/ega-sshd
	export OPENSSH_PRIVSEP_USER=ega-sshd
	export OPENSSH_PRIVSEP_GROUP=ega-sshd
	# export OPENSSH_GROUP_SSHKEYS=ega-ssh-keys
	export OPENSSH_PID_PATH=/run/ega-sshd


	getent group ${OPENSSH_PRIVSEP_GROUP} || groupadd -g ${SSHD_GID} -r ${OPENSSH_PRIVSEP_GROUP}

	mkdir -p ${OPENSSH_PRIVSEP_PATH}
	chmod 700 ${OPENSSH_PRIVSEP_PATH}

	# ${OPENSSH_PRIVSEP_PATH} must be owned by root and not group or world-writable.
	useradd -c "Privilege-separated SSH" \
            -u ${SSHD_UID} \
	        -g ${OPENSSH_PRIVSEP_GROUP} \
	        -s /usr/sbin/nologin \
	        -r \
	        -d ${OPENSSH_PRIVSEP_PATH} ${OPENSSH_PRIVSEP_USER}

	cd src
	patch -p1 < ../patches/systemd-readyness.patch

	patch -p1 < ../patches/sftp.patch

	autoreconf
	./configure --prefix=${OPENSSH_DIR} \
                --with-pam --with-pam-service=ega \
    		    --with-zlib \
    		    --with-openssl \
    		    --with-libedit \
    		    --with-privsep-user=${OPENSSH_PRIVSEP_USER} \
    		    --with-privsep-path=${OPENSSH_PRIVSEP_PATH} \
		        --without-xauth \
		        --without-maildir \
			    --without-selinux \
			    --with-systemd \
			    --with-pid-dir=${OPENSSH_PID_PATH}

	make
	make install-nosysconf

Create the new host keys

	mkdir -p /opt/LocalEGA/etc/sshd
	rm -f /opt/LocalEGA/etc/sshd/host_{rsa,dsa,ed25519}_key{,.pub}
	/opt/LocalEGA/bin/ssh-keygen -t ed25519 -N '' -f /opt/LocalEGA/etc/sshd/host_ed25519_key
	/opt/LocalEGA/bin/ssh-keygen -t rsa     -N '' -f /opt/LocalEGA/etc/sshd/host_rsa_key
	/opt/LocalEGA/bin/ssh-keygen -t dsa     -N '' -f /opt/LocalEGA/etc/sshd/host_dsa_key

Copy the system files into place

	# For OpenSSH
	echo 'Welcome to your LocalEGA outbox' > /opt/LocalEGA/etc/sshd/banner
	cp sshd_config.sample /opt/LocalEGA/etc/sshd/sshd_config
	# and adjust the paths, if necessary
	
	# For PAM
	cp ../pam/pam.ega /etc/pam.d/ega
	# and update accordingly
	
	# For the Systemd files
	echo 'SSHD_OPTS=-o LogLevel=DEBUG3' > /opt/LocalEGA/etc/sshd/options
	cp ega-sshd.service /etc/systemd/system/ega-sshd.service
	systemctl daemon-reload
	
Finally, start the service:

    systemctl start ega-sshd
