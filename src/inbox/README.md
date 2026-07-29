# LocalEGA-inbox

OpenSSH dropbox, with local credentials and RabbitMQ notifications for file system events.

This doesn't connect to Central EGA.

Build the docker image (passing the current user/group, for access permissions), with:

	make latest LEGA_UID=$(id -u) LEGA_GID=$(id -g)
	# or adjust the user/group number accordingly

You then connect to the running instance with:

	sftp -P 2223 lega@localhost # adjust the port if needed, including in your compose file

On success, you should get a prompt such as:

	Welcome to Local EGA Demo instance
	Connected to localhost.
	sftp>
