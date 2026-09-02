#!/usr/bin/env bash

set -eo pipefail

[[ -z "${FEGA_CONNECTION}" ]] && echo 'Environment variable FEGA_CONNECTION is empty' 1>&2 && exit 1
[[ -z "${INBOX_CONNECTION}" ]] && echo 'Environment variable INBOX_CONNECTION is empty' 1>&2 && exit 1

# It's just the hash for password: "secret".
# Obviously change in in production (by passing a different MQ_PASSWORD_HASH)
[[ -z "${MQ_PASSWORD_HASH}" ]] && export MQ_PASSWORD_HASH='IUBfMYLSSPynj8zjLxX3DtEHi0fhcKPhY/Cy7MJhrragBeP8'

sed 's|__FEGA_CONNECTION__|'"${FEGA_CONNECTION}"'|' \
    /etc/rabbitmq/definitions.tmpl.json > /etc/rabbitmq/definitions.json

sed -i 's|__INBOX_CONNECTION__|'"${INBOX_CONNECTION}"'|' /etc/rabbitmq/definitions.json

sed -i 's|__MQ_PASSWORD_HASH__|'"${MQ_PASSWORD_HASH}"'|' /etc/rabbitmq/definitions.json

chmod 600 /etc/rabbitmq/definitions.json

# if long and short hostnames are not the same, use long hostnames
if [ -z "${RABBITMQ_USE_LONGNAME:-}" ] && [ "$(hostname)" != "$(hostname -s)" ]; then
	: "${RABBITMQ_USE_LONGNAME:=true}"
fi

exec "$@"
