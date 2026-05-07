SHELL := /bin/bash

# This Makefile uses $(file < ...) so it requires GNU Make 4.0 or later
MAKE_VERSION := $(shell $(MAKE) --version | head -n 1 | awk '{print $$3}')
ifneq ($(filter 4.%,$(MAKE_VERSION)),$(MAKE_VERSION))
$(error This Makefile requires GNU Make 4.0 or later (found: $(MAKE_VERSION)))
endif

#############################
## Build docker images
#############################

image-inbox:
	$(MAKE) -C ../../src/inbox latest
image-vault:
	$(MAKE) -C ../../src/vault-db latest PG_SU_PASSWORD=fake
image-dispatcher:
	$(MAKE) -C ../../src/ingestion/dispatcher latest
image-ingester:
	$(MAKE) -C ../../src/ingestion/ingester latest
image-archiver:
	$(MAKE) -C ../../src/ingestion/archiver latest

image-ingestion: image-dispatcher image-ingester image-archiver
images: image-inbox image-vault image-ingestion

#############################
## Initialize the database
#############################
confs/pg_su_password:
	@echo $@ should be pre-generated
	@exit 1

init-vault: confs/pg_su_password
	$(MAKE) -C ../../src/vault-db init \
	PG_SU_PASSWORD=$(file < $<) DB_DATA=$(shell pwd)/data/vault-db

# Connect to the database from the host machine
export PGHOST=localhost
export PGPORT=5432
export PGUSER=postgres
export PGPASSWORD=$(file < confs/pg_su_password)
export PGDATABASE=ega
psql:
	psql


#############################
## Utility targets
#############################

down:
	docker-compose down -v
logs:
	docker-compose logs -f vault-db dispatcher {ingester,archiver}-{1..4} vector
logs-all:
	docker-compose logs -f
ps:
	docker-compose ps

pre-up:
	docker-compose up -d mq cega-mq elasticsearch inbox
	sleep 1
	docker-compose up -d cega
up:
	docker-compose up -d

clean:
	-echo -n '' > confs/ingestion.db
	-rm -rf data/{vault,backup,vault.bkp,staging,inbox}/*
	-rm -rf data/vault-db


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


-include example.mk
