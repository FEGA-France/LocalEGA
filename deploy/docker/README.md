⚠️ Please, note that this repository uses git submodules. Use flag `--recurse-submodules` when cloning it, and verify that they have been initialised.

This document helps you run your LocalEGA instance, locally.

All files are encrypted using Crypt4GH.

It requires:
* a service key
* a master key
* a configuration file for the python services: `<service>.ini`, including its logger `<service>-logger.json`
* a configuration file for docker-compose: `docker-compose.yml`
* 2 configurations file for postgres: `pg.conf` and `pg_hba.conf`

# Mountpoints / File system

Prepare the storage mountpoints for:
* the inbox of the users
* staging area
* the vault location
* the backup location

	make data-directories

# Sensitive data / configuration files

We provide in [`confs/`](confs) a list of dummy configuration files. This is fine for a test/local deployment.  
Of course, update the settings (and file permissions) in production environment!

The included message broker uses an administrator account with `admin:secret` as `username:password`.

We provide 2 pre-generated dummy keys and already injected the settings in the configuration files.

The master key should be stored securely.

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

You should get something like:

```
NAME                   IMAGE                                                  COMMAND                  SERVICE         CREATED          STATUS                    PORTS
cega                   cega                                                   "python -m server -d…"   cega            46 seconds ago   Up 40 seconds             0.0.0.0:8080->8080/tcp, [::]:8080->8080/tcp
cega-mq                rabbitmq:4.3-management-alpine                         "docker-entrypoint.s…"   cega-mq         46 seconds ago   Up 46 seconds (healthy)   0.0.0.0:15670->15672/tcp, [::]:15670->15672/tcp
lega-archiver-1        lega/archiver:latest                                   "python -m code /etc…"   archiver-1      46 seconds ago   Up 35 seconds
lega-archiver-2        lega/archiver:latest                                   "python -m code /etc…"   archiver-2      46 seconds ago   Up 35 seconds
lega-archiver-3        lega/archiver:latest                                   "python -m code /etc…"   archiver-3      46 seconds ago   Up 35 seconds
lega-archiver-4        lega/archiver:latest                                   "python -m code /etc…"   archiver-4      46 seconds ago   Up 35 seconds
lega-dispatcher        lega/dispatcher:latest                                 "python -m code /etc…"   dispatcher      46 seconds ago   Up 35 seconds
lega-elasticsearch     docker.elastic.co/elasticsearch/elasticsearch:8.12.0   "/bin/tini -- /usr/l…"   elasticsearch   46 seconds ago   Up 46 seconds (healthy)   9200/tcp, 9300/tcp
lega-inbox             crg/lega-inbox:latest                                  "/usr/local/bin/entr…"   inbox           46 seconds ago   Up 46 seconds             0.0.0.0:2222->9000/tcp, [::]:2222->9000/tcp, 0.0.0.0:15673->15672/tcp, [::]:15673->15672/tcp
lega-ingester-1        lega/ingester:latest                                   "python -m code /etc…"   ingester-1      46 seconds ago   Up 35 seconds
lega-ingester-2        lega/ingester:latest                                   "python -m code /etc…"   ingester-2      46 seconds ago   Up 35 seconds
lega-ingester-3        lega/ingester:latest                                   "python -m code /etc…"   ingester-3      46 seconds ago   Up 35 seconds
lega-ingester-4        lega/ingester:latest                                   "python -m code /etc…"   ingester-4      46 seconds ago   Up 35 seconds
lega-kibana            docker.elastic.co/kibana/kibana:8.12.0                 "/bin/tini -- /usr/l…"   kibana          46 seconds ago   Up 35 seconds             0.0.0.0:5601->5601/tcp, [::]:5601->5601/tcp
lega-mq                rabbitmq:4.3-management-alpine                         "/usr/local/bin/ega-…"   mq              46 seconds ago   Up 46 seconds (healthy)   0.0.0.0:15672->15672/tcp, [::]:15672->15672/tcp
lega-vault-db          lega/vault-db:latest                                   "postgres -c config_…"   vault-db        46 seconds ago   Up 46 seconds (healthy)   0.0.0.0:5432->5432/tcp, [::]:5432->5432/tcp
lega-vault-db-logger   timberio/vector:0.55.0-debian                          "/usr/bin/vector --c…"   vector          46 seconds ago   Up 35 seconds
```

You can follow along with

	make logs

and tear all down with

	make down


# Local access and logging

An instance of Kibana (pointing to Elasticsearch) is running on [port 5601](http://localhost:5601)

The python containers ship their logs directly to Elasticsearch in the index `lega-app` (see [`confs/logger.json`](confs/logger.json). The vault-db dumps its logs on disk (see `data/vault-db/logs`) and an instance of [vector.dev](https://vector.dev/docs/reference/configuration/sinks/elasticsearch/) picks them up and ships to Elasticsearch.

You can inspect:
* the MQ broker on [port 15672](http://localhost:15672),
* the inbox MQ broker on [port 15673](http://localhost:15673) and,

If you have `sqlite3` installed, you can inspect the _running ingestion jobs_ in the `confs/ingestion.db` database with 

	sqlite3 confs/ingestion.db
	> select * from jobs;
