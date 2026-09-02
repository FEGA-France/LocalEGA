
-- ALTER ROLE postgres WITH PASSWORD '__CHANGE-ME__';
-- ALTER ROLE dashboard WITH PASSWORD '__CHANGE-ME__';

ALTER ROLE distribution WITH PASSWORD 'secret';

INSERT INTO amqp.brokers(id, host, port, username, password, ssl)
VALUES (1, 'mq', 5672, 'admin', 'secret', false);

-- runs as superuser, but only executes controlled functions
INSERT INTO amqp.consumers(broker_id, channel_id, name, queue, command, restart)
VALUES (1, 10, 'vault-db', 'vault.db', $$SELECT * FROM public.dispatch_message($1::text, $2::jsonb)$$, 5);
