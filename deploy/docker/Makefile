SHELL := /bin/bash

LEGA_UID=$(shell id -u)
LEGA_GID=$(shell id -g)

all: storage images db

#############################
## Build docker images
#############################

image-inbox:
	$(MAKE) -C ../../src/inbox latest LEGA_UID=$(shell id -u) LEGA_GID=$(shell id -g)
image-vault:
	$(MAKE) -C ../../src/vault-db latest PG_SU_PASSWORD=fake
image-dispatcher:
	$(MAKE) -C ../../src/ingestion/dispatcher latest
image-ingester:
	$(MAKE) -C ../../src/ingestion/ingester latest LEGA_UID=$(shell id -u) LEGA_GID=$(shell id -g)
image-archiver:
	$(MAKE) -C ../../src/ingestion/archiver latest LEGA_UID=$(shell id -u) LEGA_GID=$(shell id -g)

image-ingestion: image-dispatcher image-ingester image-archiver
images: image-inbox image-vault image-ingestion

#############################
## Initialize the database
#############################
# confs/pg_su_password:
# 	@echo $@ should be pre-generated
# 	@exit 1

confs/pg_su_password:
	@echo -n 'super-secret' > $@
	@chmod 600 $@

init-vault: confs/pg_su_password
	$(MAKE) -C ../../src/vault-db init \
	PG_SU_PASSWORD=$(shell cat $<) DB_DATA=$(shell pwd)/data/vault-db

# Connect to the database from the host machine
export PGHOST=localhost
export PGPORT=5432
export PGDATABASE=ega
export PGUSER=postgres
export PGPASSWORD=$(shell cat confs/pg_su_password 2>/dev/null || echo -n fake)
psql:
	@psql


up-db:
	docker-compose up -d vault-db
down-db:
	docker-compose stop vault-db
	yes | docker-compose rm vault-db
setup-db:
	psql < confs/vault-db.sql

wait-db:
	@sleep 2

db: init-vault up-db wait-db setup-db down-db

#############################
## Initialize the data directories
#############################

# with the setgid bit, the group can _read_ the inbox files of each user.
# Other users then the owner can't, because they're not in the group
data/disks/inbox:
	mkdir -p $@
	chmod 2750 $@

data/disks/staging:
	mkdir -p $@
	chmod 700 $@

# the group needs r,x in order to distribute files
data/disks/vault:
	mkdir -p $@
	chmod 750 $@

data/disks/vault.bkp:
	mkdir -p $@
	chmod 700 $@

storage: data/disks/inbox data/disks/staging data/disks/vault data/disks/vault.bkp

#############################
## Utility targets
#############################

logs:
	@docker-compose logs -f dispatcher {ingester,archiver}-{1..4} vector
logs-all:
	@docker-compose logs -f
ps:
	@docker-compose ps
up:
	@docker-compose up -d
down:
	@docker-compose down -v

clean:
	-echo -n '' > confs/ingestion.db
	-rm -rf data


-include example.mk
