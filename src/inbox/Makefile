SHELL := /bin/bash
COMMIT ?= $(shell git rev-parse HEAD)
ARGS = 

IMG=ifb/fega-inbox

.PHONY: build latest

all: latest

ARCH=$(shell uname -m)
ifeq ($(ARCH), arm64) # reset for MacOS
	ARCH=aarch64
endif


build: ARGS+=--target=BUILD
build latest:
ifeq ($(LEGA_UID),)
	$(error "Please specify the group id via the LEGA_UID variable")
endif
ifeq ($(LEGA_GID),)
	$(error "Please specify the group id via the LEGA_GID variable")
endif
	docker build $(ARGS) \
	       --build-arg ARCH=$(ARCH) \
               --build-arg LEGA_UID=$(LEGA_UID) \
               --build-arg LEGA_GID=$(LEGA_GID) \
	       -t $(IMG):$(COMMIT) .
	docker tag $(IMG):$(COMMIT) $(IMG):$@


############################################################
## Testing
############################################################

.PHONY: up run exec down patch
up:
	docker run -d --rm --name inbox-test \
	-v $(shell pwd)/conf/mq:/etc/rabbitmq \
	-v $(shell pwd)/tmp/authorized_keys:/ega/inbox/.ssh/authorized_keys:ro \
	-p 15676:15672 \
	-p 10000:22 \
	$(IMG):latest

#	-v $(shell pwd)/tmp/data:/ega/inbox/upload \


run:
	docker run -d --rm --name inbox-test --entrypoint /bin/sleep $(IMG):build 365d

exec:
	docker exec -it --user root inbox-test bash

logs:
	docker logs -f inbox-test

down:
	-docker stop inbox-test

patch:
	-make -C tmp patch
