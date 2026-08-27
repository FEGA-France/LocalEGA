# LocalEGA-inbox

OpenSSH dropbox, with RabbitMQ notifications for file system events.

Build the docker image (passing the current user/group, for access permissions), with:

	make latest LEGA_UID=$(id -u) LEGA_GID=$(id -g)
	# or adjust the user/group number accordingly

This doesn't connect to the NSS of Central EGA / France EGA, it has its own internal system-user instead.

In order to give access for uploading to the LEGA-inbox, you need an SSH-keypair and inject the public part in the `authrized_keys` of this user. The FEGA uploader keeps the private part.


If the LEGA-inbox container is running and you inject the public key part, you can connect, from the FEGA uploader, with:

	# cd [fega]/deploy/docker
	
	# Install SFTP first
	docker compose exec --user root apt update
	docker compose exec --user root apt install -y openssh-client
	
	# Connect to LEGA-inbox
	docker compose exec uploader sftp -i /etc/ega/seckey -o UserKnownHostsFile=/dev/null lega@lega-inbox

When prompted for the passphrase of the private key, you type `hello` (dummy passphrase, update it in production!).  
On success, you should get some similar to:

	The authenticity of host 'lega-inbox (172.18.0.2)' can't be established.
	ED25519 key fingerprint is SHA256:EPcpv2G5IM3Kyx0QNkgWGOD8XKyXF7hAzbohdXXjM6A.
	This key is not known by any other names.
	Are you sure you want to continue connecting (yes/no/[fingerprint])? yes
	Warning: Permanently added 'lega-inbox' (ED25519) to the list of known hosts.
	Welcome to Local EGA Demo instance
	Enter passphrase for key '/etc/ega/seckey':
	Connected to lega-inbox.
	sftp>
