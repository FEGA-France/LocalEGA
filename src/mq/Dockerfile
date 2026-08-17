FROM rabbitmq:4.3-management-alpine

COPY --chown=rabbitmq:rabbitmq --chmod=600 conf/enabled_plugins /etc/rabbitmq/enabled_plugins
COPY --chown=rabbitmq:rabbitmq --chmod=600 conf/rabbitmq.conf /etc/rabbitmq/rabbitmq.conf
COPY --chown=rabbitmq:rabbitmq --chmod=755 entrypoint.sh /usr/local/bin/ega-entrypoint.sh

COPY --chown=rabbitmq:rabbitmq --chmod=600 conf/definitions.tmpl.json /etc/rabbitmq/definitions.tmpl.json

USER rabbitmq
ENTRYPOINT ["/usr/local/bin/ega-entrypoint.sh"]
CMD ["rabbitmq-server"]
