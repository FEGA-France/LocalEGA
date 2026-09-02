SHELL := /bin/bash
COMMIT ?= $(shell git rev-parse HEAD)
ARGS = 

IMG=lega/vault-db
SERVICE=vault-db

###########################
DATABASE_NAME=ega
PG_SU_PASSWORD=supersecret
# Reset at the command-line "make PG_SU_PASSWORD=verysecret"

.PHONY: latest build

all: latest

build: ARGS+=--target BUILD
build latest:
	docker build $(ARGS) -t $(IMG):$(COMMIT) .
	docker tag $(IMG):$(COMMIT) $(IMG):$@



init: MOUNTPOINTS=
init: ENVVARS=

init: MOUNTPOINTS+=-v $(DB_DATA):/ega/data
init: MOUNTPOINTS+=-v $(shell pwd)/build.sh:/ega/build.sh
init: MOUNTPOINTS+=-v $(shell pwd)/initdb.d:/ega/initdb.d
init: ENVVARS+=-e PGDATA=/ega/data
init: ENVVARS+=-e POSTGRES_PASSWORD=$(PG_SU_PASSWORD)
init: ENVVARS+=-e POSTGRES_DB=$(DATABASE_NAME)

ifdef DEBUG
init: ENTRYPOINT=-d --entrypoint /bin/sleep
init: CMD=356d
else
init: ENTRYPOINT=-it --entrypoint /ega/build.sh --user root
endif
init:
ifeq ($(DB_DATA),)
	$(error "Please specify the DB_DATA variable")
endif
	docker run --rm \
	$(MOUNTPOINTS) \
	$(ENVVARS) \
	--hostname "$(SERVICE)-build" \
	--name "$(SERVICE)-build" \
	$(ENTRYPOINT) $(IMG):latest $(CMD)

down:
	-docker stop $(SERVICE)-build
	-docker rm $(SERVICE)-build
