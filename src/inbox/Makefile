SHELL := /bin/bash
COMMIT ?= $(shell git rev-parse HEAD)
ARGS = 

IMG=lega/inbox

all: latest

.PHONY: latest build

# ARCH=$(shell uname -m)
# ifeq ($(ARCH), arm64) # reset for MacOS
# 	ARCH=aarch64
# endif
# ARGS+=--build-arg ARCH=$(ARCH)

ifneq ($(LEGA_UID),)
	ARGS+=--build-arg LEGA_UID=$(LEGA_UID)
endif

ifneq ($(LEGA_GID),)
	ARGS+=--build-arg LEGA_GID=$(LEGA_GUID)
endif

build: ARGS+=--target=BUILD
build latest:
	docker build $(ARGS) \
	       --build-arg COMMIT=$(COMMIT) \
               --build-arg BUILD_DATE="$(shell date +%Y-%m-%d_%H.%M.%S)" \
	       -t $(IMG):$(COMMIT) .
	docker tag $(IMG):$(COMMIT) $(IMG):$@


############################################################
## Testing
############################################################

-include testing.mk
