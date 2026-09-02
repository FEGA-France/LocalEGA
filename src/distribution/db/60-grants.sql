-- ###################################################
-- Grant permissions to the outgestion user
-- ###################################################

GRANT USAGE ON SCHEMA public TO distribution;
GRANT SELECT ON public.dataset_table to distribution;
GRANT SELECT ON public.dataset_file_table TO distribution;
GRANT SELECT ON public.file_table TO distribution;
GRANT SELECT ON public.user_table to distribution;
GRANT SELECT ON public.user_key_table to distribution;
GRANT SELECT ON public.header_keys to distribution;

GRANT USAGE ON SCHEMA private TO distribution;
GRANT SELECT ON private.file_table TO distribution;
GRANT SELECT ON private.username_file_header to distribution;
GRANT SELECT ON private.dataset_permission_table to distribution;

GRANT USAGE ON SCHEMA fs TO distribution;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA fs TO distribution;

GRANT USAGE     ON SCHEMA crypt4gh                                      TO distribution;
GRANT EXECUTE   ON FUNCTION crypt4gh.header_reencrypt(bytea,bytea)      TO distribution;
GRANT EXECUTE   ON FUNCTION crypt4gh.header_reencrypt(bytea,bytea[])    TO distribution;

-- #####################################################
-- Grant permissions for the NSS system
-- #####################################################

GRANT USAGE ON SCHEMA nss TO lega;
GRANT EXECUTE ON ALL FUNCTIONS IN SCHEMA nss TO lega;

GRANT SELECT ON TABLE public.requesters TO lega;
GRANT SELECT ON TABLE public.ssh_keys TO lega;

-- Required to write files
GRANT pg_write_server_files TO lega;