⚠️ Please, note that this repository uses git submodules. Use flag `--recurse-submodules` when cloning it, and verify that they have been initialised.

This document helps you run your LocalEGA instance, locally.

All files are encrypted using Crypt4GH.

It requires:
* a service key
* a master key
* a configuration file for the python services: `<service>.ini`, including its logger `<service>-logger.json`
* a configuration file for docker-compose: `docker-compose.yml`
* 2 configurations file for postgres: `pg.conf` and `pg_hba.conf`

# Sensitive data / configuration files

We provide in [`confs/`](confs) a list of dummy configuration files. This is fine for a test/local deployment.  
Of course, update the settings (and file permissions) in production environment!

The included message broker uses an administrator account with `admin:secret` as `username:password`.

We provide 2 pre-generated dummy keys and already injected the settings in the configuration files.

The master key should be stored securely.

# Mountpoints / File system

Prepare the storage mountpoints for:
* the inbox of the users
* staging area
* the vault location
* the backup location

	make data-directories


# FEGA Affiliates

If you are preparing a FEGA Affiliate (not a FEGA Node), modify  the `docker-compose.yml` file adding your affiliate name (which must be agreed with CEGA beforehand) in an environment variable:

 ```yaml
 mq:
    environment:
		- AFFILIATE_NAME=xxxx

```

# Container images

Create the docker images with:

	make -j5 images

# The vault database

You can pre-generate the file `confs/pg_su_password` with the superuser password.  
(if you don't, one will be generated with 'super-secret')

Then, initialize the Vault-DB before booting it

	make db

This will add the SQL definitions and necessary (dummy) settings (See confs/vault-db.sql)


# Instantiate the containers 

Finally, you are now ready to instantiate the containers

	make up
	
	# We tried to include heathchecks to start in the right order.
	# If that's not the case, (say elasticsearch or the message broker didn't start fast enough)
	# then restart again
	make up

Check the containers' status with

	make ps

You can follow along with

	make logs

and tear all down with

	make down

# (fake) Central EGA

The local deployment includes an instance of a fake Central EGA, with a message broker and a dummy server to handle (only) a few messages.

You can see the code in the [`cega`](cega) folder.

If you already have credentials for a test environment from Central EGA, you can update the docker-compose environment variable for the `mq` and `inbox` containers. Comment out the `cega` and `cega-mq` instances to avoid starting them.

# Local access and logging

An instance of Kibana (pointing to Elasticsearch) is running on [port 5601](http://localhost:5601)

The python containers ship their logs directly to Elasticsearch in the index `fega-app` (see [`confs/logger.json`](confs/logger.json). The vault-db dumps its logs on disk (see `data/vault-db/logs`) and an instance of [vector.dev](https://vector.dev/docs/reference/configuration/sinks/elasticsearch/) picks them up and ships to Elasticsearch.

You can inspect:
* the MQ broker on [port 15672](http://localhost:15672),
* the inbox MQ broker on [port 15673](http://localhost:15673) and,
* the (fake) Central EGA MQ broker on [port 15670](http://localhost:15670) (if you started it)

If you have `sqlite3` installed, you can inspect the _running ingestion jobs_ in the `confs/ingestion.db` database with 

	sqlite3 confs/ingestion.db
	> select * from jobs;

