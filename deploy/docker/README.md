⚠️ Please, note that this repository uses git submodules. Use flag `--recurse-submodules` when cloning it, and verify that they have been initialised.

This document helps you prepare the (mininum) settings for your LocalEGA instance.

All files are encrypted using Crypt4GH.
The master key should be stored securely.

It requires:
* a service key
* a master key
* a configuration file for the python services: `<service>.ini`, including its logger `<service>-logger.json`
* a configuration file for docker-compose: `docker-compose.yml`
* 2 configurations file for postgres: `pg.conf` and `pg_hba.conf`

We assume you have created a local user and a group named `lega`. If not, you can do it with

    groupadd -r lega
    useradd -M -g lega lega

# Sensitive data

We provide in [`confs/`](confs) a list of dummy configuration files. This is fine for a test/local deployment.  
Of course, update the settings (and file permissions) in production environment!

The included message broker uses an administrator account with `admin:secret` as `username:password`.

Generate the service and master keys with:

	crypt4gh-keygen -f --pk confs/service.pubkey --sk confs/service.seckey -C "service_key@LocalEGA"
	crypt4gh-keygen -f --pk confs/master.pubkey --sk confs/master.seckey -C "master_key@LocalEGA"

	# update the permissions
	chown lega:lega confs/{master,service}.{pubkey,seckey}
	chmod 600 confs/{master,service}.{pubkey,seckey}

Note: You will get prompted for the passphrase. Save it and update `confs/ingester.ini` accordingly, with the proper filepath and the chosen passphrase. (it is _not_ recommended _not to use_ any passphrase).

We provide 2 pre-generated dummy keys where the passphrase is 'hello'.
	
# Mountpoints / File system

Prepare the storage mountpoints for:
* the inbox of the users
* staging area
* the vault location
* the backup location

```bash
	# Create the directories (some with the setgid bit)
	mkdir -p data/{inbox,staging,vault,vault.bkp}

	# Change the ownership
	chown lega:lega data/{inbox,staging,vault,vault.bkp}

	# Change the access permissions
	chmod 2750 data/inbox # with the setgid bit, the `lega` user can _read_ the inbox files of each user.
	                      # Other users then the owner can't.
	chmod 700 data/staging
	chmod 750 data/vault  # lega group needs r,x in order to distribute files
	chmod 700 data/vault.bkp
```
Adjust the paths in the `docker-compose.yml` file and the `confs/*.ini` configuration files if you didn't create the directory in other location than `data/...`.

# FEGA Affiliates

If you are preparing a FEGA Affiliate (not a FEGA Node), modify  the `docker-compose.yml` file adding your affiliate name (which must be agreed with CEGA beforehand) in an environment variable:

 ```yaml
 mq:
    environment:
		- AFFILIATE_NAME=xxxx

```

# Container images

Create the docker images with:

	make -j3 images LEGA_UID=$(id -u lega) LEGA_GID=$(id -g lega)

# The vault database

Prepare the vault database 

	echo 'very-strong-password' > confs/pg_vault_su_password
	chmod 600 confs/pg_vault_su_password
	make init-vault
	
	# start the database
	docker-compose up -d vault-db

	# add settings
	make psql < confs/vault-db.sql

	# stop the database to pick-up new settings from confs/vault-db.sql on the next reboot
	docker-compose stop vault-db
	yes | docker-compose rm vault-db

In the `pg.conf` file, update the `crypt4gh.master_seckey` secret with the hex value of the master private key.  
You can run the following python snippet to get it: (you need the `crypt4gh` package: `pip install crypt4gh`).

```python
import crypt4gh.keys

key_content = crypt4gh.keys.get_private_key("/path/to/master.key.sec", lambda: "passphrase")

print(key_content.hex())
```

The `pg_hba.conf` controls the network accesses to the database.  
The default supplied one is not very restrictive, and you should adjust it in your production environment.  
(For example, by enabling TLS/SSL in the `pg.conf` and restricting network CIDRs in `pg_hba.conf`).

# Instantiate the containers 

Finally, you are now ready to instantiate the containers

	# Start all the containers
	make up
	
	# We tried to include heathchecks to start in the right order.
	# If that's not the case, (say elasticsearch or the message broker didn't start fast enough)
	# then restart again
	make up

You can follow along with

	make logs

and tear all down with

	make down


# (fake) Central EGA

The local deployment includes an instance of a fake Central EGA, with a message broker and a dummy server to handle (only) a few messages.

You can see the code in the [`cega`](cega) folder.

If you already have credentials for a test environment from Central EGA, you can update the docker-compose environment variable for the `mq` and `inbox` containers. Comment out the `cega` and `cega-mq` instances to avoid starting them.
