

-- ALTER ROLE lega WITH PASSWORD 'z61GSxD5R2XP4EI8EQW6gKDm';

ALTER ROLE distribution WITH PASSWORD 'sIrqr3E8UNH83C2O8Gn6e3A1';

-- ALTER ROLE dashboard WITH PASSWORD '2zfm6dE76QrBJ2bd';

INSERT INTO amqp.brokers(id, host, port, username, password, ssl)
VALUES (1, 'mq', 5672, 'admin', 'secret', false);

-- runs as superuser, but only executes controlled functions
INSERT INTO amqp.consumers(broker_id, channel_id, name, queue, command, restart)
VALUES (1, 10, 'vault-db', 'vault.db', $$SELECT * FROM public.dispatch_message($1::text, $2::jsonb)$$, 5);
