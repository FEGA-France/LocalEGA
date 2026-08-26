--
-- We return SSH keys only if at least one crypt4gh key exists for the given user
--
CREATE OR REPLACE VIEW public.ssh_keys AS
SELECT --DISTINCT 
	ut.id 	AS uid,
       ut.username  AS username,
       uk.key       AS key
FROM public.user_key_table uk
INNER JOIN public.user_table ut ON ut.id = uk.user_id
WHERE (-- uk.is_enabled = true
       -- AND
       uk.key IS NOT NULL
       AND
       uk.type IN ('ssh'::public.key_type, 'ssh-ed25519'::public.key_type)
      );


CREATE OR REPLACE VIEW public.header_keys AS
SELECT --DISTINCT 
       ut.id        AS user_id,
       ut.username  AS username,
       uk.key       AS key
FROM public.user_key_table uk
INNER JOIN public.user_table ut ON ut.id = uk.user_id
WHERE (-- uk.is_enabled = true
       -- AND
       uk.key IS NOT NULL
       AND
       uk.type IN ('c4gh-v1'::public.key_type, 'ssh-ed25519'::public.key_type)
      );


--
-- We use the ID (and not the username) for the home directory, in case the username changes
-- We hard-code the group as requesters: 10000
-- We don't show the passwords
--
CREATE OR REPLACE VIEW public.requesters AS
SELECT DISTINCT
       db2sys_user_id(ut.id)                     AS uid,
       ut.id                                     AS db_uid,
       ut.group_id                                AS gid,
       ut.username                               AS username,
       --(concat('/home/', ut.id))::varchar        AS homedir,
       (concat_ws('/', RTRIM(current_setting('nss.homes'), '/'), ut.username))::varchar  AS homedir,
       'EGA Requester'::varchar                  AS gecos,
       '/bin/bash'::varchar                      AS shell
FROM public.user_table ut
LEFT JOIN public.user_key_table uk ON ut.id = uk.user_id AND uk.type IN ('c4gh-v1'::public.key_type, 'ssh-ed25519'::public.key_type)
WHERE ( ut.is_enabled = true);

