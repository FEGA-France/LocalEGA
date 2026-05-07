
all: latest

build: ARGS+=--target BUILD
build latest:
	docker build $(ARGS) -t fega/vault-db:$@ .

###########################
DB_DATA=$(shell pwd)/data

$(DB_DATA):
	mkdir -p $@
	-chown -R 999:999 $@ # that the postgres user and group in the container

rm:
	rm -rI $(DB_DATA)

###########################
DATABASE_NAME=ega
SERVICE=vault-db
IMG=fega/vault-db:latest

PG_SU_PASSWORD=supersecret
# Reset at the command-line "make PG_SU_PASSWORD=verysecret"

init: | $(DB_DATA)
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
	docker run --rm \
	$(MOUNTPOINTS) \
	$(ENVVARS) \
	--hostname "$(SERVICE)-build" \
	--name "$(SERVICE)-build" \
	$(ENTRYPOINT) $(IMG) $(CMD)

down:
	-docker stop $(SERVICE)-build
	-docker rm $(SERVICE)-build
