ifeq ($(SERVICE),)
$(error "Please set the SERVICE variable")
endif

SHELL := /bin/bash
COMMIT ?= $(shell git rev-parse HEAD)
ARGS = 

IMG=fega/$(SERVICE):$(COMMIT)

.PHONY: latest build

ARCH=$(shell uname -m)
ifeq ($(ARCH), arm64) # reset for MacOS
	ARCH=aarch64
endif

define error-lega-gid-message
Please specify the group id via the LEGA_GID variable.
For example, by calling "make $@ LEGA_GID=$$(id -g lega)"
endef

define error-lega-ugid-message
Please specify the user and group ids via the LEGA_UID/LEGA_GID variable.
For example, by calling "make $@ LEGA_UID=$$(id -u lega) LEGA_GID=$$(id -g lega)"
endef

build: ARGS+=--target BUILD
latest build: 
ifeq ($(LEGA_UID),)
	$(error $(error-lega-ugid-message))
endif
ifeq ($(LEGA_GID),)
	$(error $(error-lega-ugid-message))
endif
	docker build $(ARGS) \
	       --build-arg ARCH=$(ARCH) \
	       --build-arg COMMIT=$(COMMIT) \
               --build-arg BUILD_DATE="$(shell date +%Y-%m-%d_%H.%M.%S)" \
               --build-arg LEGA_UID=$(LEGA_UID) \
               --build-arg LEGA_GID=$(LEGA_GID) \
	       -t $(IMG) .
	docker tag $(IMG) fega/$(SERVICE):$@
