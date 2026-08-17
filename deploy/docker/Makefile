SHELL := /bin/bash
ARGS = 

all: images db

DB_DATA_VOLUME=lega-vault-db

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


images: image-dispatcher image-ingester image-archiver
images: image-inbox image-vault-db image-mq



#############################
## Initialize the database
#############################
# confs/pg_su_password:
# 	@echo $@ should be pre-generated
# 	@exit 1

confs/pg_su_password:
	@echo -n 'super-secret' > $@
	@chmod 600 $@

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


.PHONY: up-db down-db setup-db wait-db
up-db:
	docker-compose up -d vault-db
down-db:
	docker-compose stop vault-db
	yes | docker-compose rm vault-db
setup-db:
	psql < confs/vault-db.sql

wait-db:
	@sleep 2

.PHONY: $(DB_DATA_VOLUME)
$(DB_DATA_VOLUME):
	@docker volume create $@
rm-db:
	-docker volume rm $(DB_DATA_VOLUME)

db: down-db rm-db init-vault up-db wait-db setup-db


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
