# LocalEGA internal message broker in a docker image

We use [RabbitMQ 4](https://hub.docker.com/_/rabbitmq) including the management plugins.

## Configuration

The following environment variables can be used to configure the broker:

| Variable | Description |
|---------:|:------------|
| `MQ_PASSWORD_HASH` | Default user password hash (with admin rights) |
| `MQ_PASSWORD_HASH_LEGA` | Default user password hash (no admin rights) |
| `CEGA_CONNECTION` | DSN URL for the shovels and federated queues with CentralEGA |
| `INBOX_CONNECTION` | DSN URL for inbox federated queue |

If you want persistent data, you can use a named volume or a bind-mount and make it point to `/var/lib/rabbitmq`.

> Note: we only create a generic user named `admin` with administrative rights.
> In your production environment, adjust accordingly with multiple users/permissions

## Sample Docker Compose definition

```
services:

  mq:
    image: rabbitmq:management-alpine
    hostname: mq
    ports:
      - "5672:5672"
      - "15672:15672"
    environment:
      - MQ_PASSWORD_HASH=<some-hashed-secret>
      - CEGA_CONNECTION=amqps://<node>:<password>@rabbitmq.test.ega-archive.org:5671/<node>

```

and replace `<...>` accordingly.

Run `docker-compose up -d` to test it.
