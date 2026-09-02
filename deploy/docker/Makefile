SHELL := /bin/bash
ARGS = 

all: images db

DB_DATA_VOLUME=lega-vault-db

DC=docker compose

#############################
## Build docker images
#############################

image-inbox:
	$(MAKE) -C ../../src/inbox latest ARGS=$(ARGS)
image-vault-db:
	$(MAKE) -C ../../src/vault-db latest ARGS=$(ARGS) PG_SU_PASSWORD=fake
image-dispatcher:
	$(MAKE) -C ../../src/ingestion/dispatcher latest ARGS=$(ARGS)
image-ingester:
	$(MAKE) -C ../../src/ingestion/ingester latest ARGS=$(ARGS)
image-archiver:
	$(MAKE) -C ../../src/ingestion/archiver latest ARGS=$(ARGS)
image-mq:
	$(MAKE) -C ../../src/mq latest ARGS=$(ARGS)
image-tre:
	$(MAKE) -C ../../src/distribution/fake-tre latest ARGS=$(ARGS)


images: image-dispatcher image-ingester image-archiver
images: image-inbox image-vault-db image-mq
images: image-tre



#############################
## Initialize the database
#############################
# confs/pg_su_password:
# 	@echo $@ should be pre-generated
# 	@exit 1

confs/pg_su_password:
	@echo -n 'super-secret' > $@
	@chmod 600 $@

.PHONY: init-vault up-db down-db setup-db wait-db psql

init-vault: confs/pg_su_password $(DB_DATA_VOLUME)
	@$(MAKE) -C ../../src/vault-db init \
	PG_SU_PASSWORD=$(shell cat $<) DB_DATA=$(DB_DATA_VOLUME)

# Connect to the database from the host machine
export PGHOST=localhost
export PGPORT=5432
export PGDATABASE=ega
export PGUSER=postgres
export PGPASSWORD=$(shell cat confs/pg_su_password 2>/dev/null || echo -n fake)
psql:
	@psql


up-db:
	$(DC) up -d --no-deps vault-db
down-db:
	$(DC) stop vault-db
	yes | $(DC) rm vault-db
setup-db:
	psql < confs/vault-db.sql

wait-db:
	@sleep 2

.PHONY: $(DB_DATA_VOLUME)
$(DB_DATA_VOLUME):
	@docker volume create $@
rm-db:
	-docker volume rm $(DB_DATA_VOLUME)

logs-db:
	-$(DC) logs -f vault-db

destroy-db: down-db rm-db
post-db: up-db wait-db setup-db

# Enforce order
# stop it at the end so that, on next "up", the DB/MQ-consumer starts
db:
	@$(MAKE) --no-print-directory down-db
	@$(MAKE) --no-print-directory rm-db
	@$(MAKE) --no-print-directory init-vault
	@$(MAKE) --no-print-directory up-db
	@$(MAKE) --no-print-directory wait-db
	@$(MAKE) --no-print-directory setup-db
	@$(MAKE) --no-print-directory down-db


#############################
## Utility targets
#############################

logs:
	@$(DC) logs -f dispatcher {ingester,archiver}-{1..4}
logs-all:
	@$(DC) logs -f
ps:
	@$(DC) ps
psa:
	@$(DC) ps -a
up:
	@$(DC) up -d
down:
	@$(DC) down -v

clean:
	-rm -rf data


-include example.mk
