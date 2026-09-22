# An example

We'll assume a Federated EGA realistic situation where the vault payloads are mounted in `/data/vault`, the SQLite filesystem is mounted under `/data/fega` and the configuration files are in `/etc/fega`.

We'll create a `fega` group, that owns the files in the vault, and 2 regular users that don't belong to that group. Their group is, say, `users`.

	# Add 2 groups
	sudo addgroup --gid 3000 users
	sudo addgroup --gid 10000 fega
	
	# Add 2 users
	sudo adduser --no-create-home --uid 2001 --ingroup users --disabled-password --disabled-login colleague
	sudo adduser --no-create-home --uid 2002 --disabled-password --disabled-login guest

Before we mount the fega filesystem, a few configurations are necessary:
* register the file system (in `/etc/filesystem`
* include the systemd mount unit
* copy the underlying files under `/mnt/vault`
* setup the `/etc/fega` configuration files

	sudo mkdir -p /data/vault
	sudo chgrp fega /data/vault
	sudo chmod 2750 /data/vault
	sudo cp example/example.txt example/lorem.txt.c4gh.payload /data/vault/.
	
	# register the filesystem
	echo 'fega' > /etc/filesystem
	
	# Configuration files
	sudo mkdir /etc/fega
	sudo cp confs.sample/options.conf /etc/fega/options.conf
	sudo cp example/example.* /etc/fega/.
	
	# Prepare the mount unit
	cp confs.sample/data-fega.mount /etc/systemd/system/data-fega.mount
	systemctl daemon-reload

	# ready, steady, go
	systemctl start /data/fega


You should see the file system in the current directory under `/data/fega/`.

	$ tree /data/fega/
	/data/mnt/
	├── crypt4gh
	│   ├── cleartext
	│   └── encrypted
	├── extra
	│   ├── footer.txt
	│   └── header.txt
	├── full.txt
	├── slim.txt
	└── subdir
	    ├── file1.txt
	    └── file2.txt
	
	4 directories, 8 files

Directory and file permissions are _controlled_ by the `umask` at the mount call site.  
We use 0277 in the mount unit to show the content of `/data/fega` as read-only.  
If you want to share it to the 2 users, it is necessary to `allow_other` in the filesystem options, and update the `umask` to, say, `0027`, in the mount unit.

# Crypt4GH

The example includes a Crypt4GH-encrypted file, and a local Crypt4GH keypair.  
The keypair is locked by the passphrase "hello" (yeah... it's genius, I know).

You can view the file content in `/data/fega/crypt4gh/cleartext`, or the file itself (including its header) in `/data/fega/crypt4gh/encrypted`.

The following command should _not_ show you any differences.

	diff /data/fega/crypt4gh/cleartext <(C4GH_PASSPHRASE=hello sudo crypt4gh decrypt --sk /etc/fega/example.seckey < /data/fega/crypt4gh/encrypted 2>/dev/null)

