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

The included message broker uses an administrator account with `admin:secret` as `<username>:<password>`.

We provide 2 pre-generated dummy keys and already injected the settings in the configuration files.

The master key should be stored securely.

# Container images

Create the docker images with:

	make -j5 images

# Network

Create a external network to simulate public/external access (say to Central EGA or France EGA).  
We name it `fega-external`.

	docker network create fega-external

# The vault database

You can pre-generate the file `confs/pg_su_password` with the superuser password.  
(if you don't, one will be generated with `super-secret`)

Then, initialize the Vault-DB before booting it

	make db

This will add the SQL definitions and necessary (dummy) settings (See `confs/vault-db.sql`)

# Instantiate the containers 

Finally, you are now ready to instantiate the containers

	make up
	
Check the containers' status with

	make ps

We tried to include heathchecks to start in the right order. If that's
not the case, (say the message broker didn't start fast enough) then
restart again with the above.


You should get something like:

```
NAME              IMAGE                    COMMAND                  SERVICE      CREATED          STATUS                            PORTS
lega-archiver-1   lega/archiver:latest     "python -m code /etc…"   archiver-1   14 seconds ago   Up 2 seconds
lega-archiver-2   lega/archiver:latest     "python -m code /etc…"   archiver-2   14 seconds ago   Up 2 seconds
lega-archiver-3   lega/archiver:latest     "python -m code /etc…"   archiver-3   14 seconds ago   Up 2 seconds
lega-archiver-4   lega/archiver:latest     "python -m code /etc…"   archiver-4   14 seconds ago   Up 2 seconds
lega-dispatcher   lega/dispatcher:latest   "python -m code /etc…"   dispatcher   14 seconds ago   Up 2 seconds
lega-inbox        lega/inbox:latest        "/usr/local/bin/entr…"   inbox        14 seconds ago   Up 13 seconds (healthy)           0.0.0.0:15676->15672/tcp, [::]:15676->15672/tcp
lega-ingester-1   lega/ingester:latest     "python -m code /etc…"   ingester-1   14 seconds ago   Up 2 seconds
lega-ingester-2   lega/ingester:latest     "python -m code /etc…"   ingester-2   14 seconds ago   Up 2 seconds
lega-ingester-3   lega/ingester:latest     "python -m code /etc…"   ingester-3   14 seconds ago   Up 2 seconds
lega-ingester-4   lega/ingester:latest     "python -m code /etc…"   ingester-4   14 seconds ago   Up 2 seconds
lega-mq           lega/mq                  "/usr/local/bin/ega-…"   mq           14 seconds ago   Up 7 seconds (healthy)            0.0.0.0:5672->5672/tcp, [::]:5672->5672/tcp, 0.0.0.0:15672->15672/tcp, [::]:15672->15672/tcp
lega-vault-db     lega/vault-db:latest     "postgres -c config_…"   vault-db     14 seconds ago   Up 2 seconds (health: starting)   0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp
```
You can follow along with

	make logs

and tear all down with

	make down


# Local access and logging

The python containers and the vault-db ship their logs to `stderr` (see [`confs/logger.json`](confs/logger.json).

You can inspect:
* the MQ broker on [port 15676](http://localhost:15676),
* the inbox MQ broker on [port 15672](http://localhost:15672) and,

If you want to inspect SQLite `ingestion.db` in the container (we don't inject it), you need to install `sqlite3` in the container (we didn't include it to keep the image smaller).
That way, you can inspect the _running ingestion jobs_ in the `confs/ingestion.db` database with 

	docker compose exec --user root dispatcher
	# apt update
	# apt install sqlite3 confs/ingestion.db
	# sqlite3 /etc/ega/ingestion.db
	> select * from jobs;

The logging facility is kept minimal on purpose in this repo, because each sub-node installing it will have its own version of logging and tracing.  
The code is just ready to ship where needed.

# Central EGA and France EGA

The message broker `mq` tries to connect to an external broker, be it Central EGA itself, or France EGA.

Get the instructions to run locally the France EGA (and its fake Central EGA service) from [https://github.com/FEGA-France/RelayEGA](https://github.com/FEGA-France/RelayEGA).

The inbox does not connect to NSS from FranceEGA/CentralEGA, it has its own internal system-user.

In the FEGA France repo/directory, we created an SSH-keypair and
inject the public part in the `authrized_keys` of this user, in the
LEGA-inbox container. That way, FEGA-inbox keeps the private part and can connect to LEGA-inbox.

	# Go to the FEGA France repo/directory
	cd [fega-france]/deploy/docker
	make authorized-keys


If you already have credentials for a test environment from FranceEGA/CentralEGA, you can update the docker-compose environment variable for the `mq` containers.
