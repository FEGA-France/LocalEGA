SHELL := /bin/bash
COMMIT ?= $(shell git rev-parse HEAD)
ARGS = 

IMG=lega/s3

all: latest

.PHONY: latest build

# ARCH=$(shell uname -m)
# ifeq ($(ARCH), arm64) # reset for MacOS
# 	ARCH=aarch64
# endif
# ARGS+=--build-arg ARCH=$(ARCH)


build: ARGS+=--target=BUILD
build latest:
	docker build $(ARGS) \
	       --build-arg COMMIT=$(COMMIT) \
               --build-arg BUILD_DATE="$(shell date +%Y-%m-%d_%H.%M.%S)" \
	       -t $(IMG):$(COMMIT) .
	docker tag $(IMG):$(COMMIT) $(IMG):$@
