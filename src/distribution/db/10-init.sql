

-- ############################################
-- Specific user for distribution permissions
-- ############################################
CREATE USER distribution WITH LOGIN ENCRYPTED PASSWORD 'change-me';

-- ############################################
--        NSS <--> DB user IDs conversions
-- ############################################
CREATE OR REPLACE FUNCTION public.sys2db_user_id(_sys_uid bigint)
RETURNS bigint
LANGUAGE SQL
AS $_$
   SELECT _sys_uid - (current_setting('nss.uid_shift'))::bigint;
$_$;

CREATE OR REPLACE FUNCTION public.db2sys_user_id(_db_uid bigint)
RETURNS bigint
LANGUAGE SQL
AS $_$
   SELECT _db_uid + (current_setting('nss.uid_shift'))::bigint;
$_$;
