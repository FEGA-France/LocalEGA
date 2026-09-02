
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
