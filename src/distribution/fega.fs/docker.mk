SHELL := /bin/bash
COMMIT ?= $(shell git rev-parse HEAD || echo 'init')
ARGS = 

IMG=fega/fs-dev

.PHONY: build latest

all: latest

########## This is only useful for compilation.
########## Not for running, cuz there is no kernel in a container.
########## (unless you mount /dev/fuse, but I'm on a Mac)

build: ARGS+=--target BUILD
latest build: 
	docker build $(ARGS) \
	       --build-arg COMMIT=$(COMMIT) \
               --build-arg BUILD_DATE="$(shell date +%Y-%m-%d_%H.%M.%S)" \
	       -t $(IMG):$(COMMIT) .
	docker tag $(IMG):$(COMMIT) $(IMG):$@

run:
	docker run -d --rm --name fega.fs-dev \
		--hostname dev \
		-v $(shell pwd):/var/src \
	$(IMG):build

exec:
	docker exec -it fega.fs-dev bash

down:
	-docker stop fega.fs-dev
	-docker rm fega-fs.dev
