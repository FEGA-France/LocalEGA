SHELL := /bin/bash
COMMIT ?= $(shell git rev-parse HEAD || echo 'init')
ARGS = 

IMG=lega/mq

.PHONY: latest build

all: latest

build: ARGS+=--target BUILD
build latest:
	docker build $(ARGS) \
	             -t $(IMG):$(COMMIT) .
	docker tag $(IMG):$(COMMIT) $(IMG):$@
