-- DROP FUNCTION sqlite_fs.datasets(text);
-- DROP FUNCTION sqlite_fs.datasets(text, text, boolean);
-- DROP FUNCTION sqlite_fs.datasets(text, text[], boolean);


CREATE OR REPLACE FUNCTION sqlite_fs.parse_pubkey(_key text)
RETURNS bytea
LANGUAGE plpgsql
AS $_$
DECLARE
	_message text;
BEGIN

    BEGIN
	RETURN crypt4gh.parse_pubkey(_key);
    EXCEPTION WHEN OTHERS THEN
	GET STACKED DIAGNOSTICS _message = MESSAGE_TEXT;
        RAISE NOTICE '%: invalid Crypt4gh key: %', _key, _message;
        RETURN NULL;
    END;

END
$_$;



CREATE OR REPLACE FUNCTION sqlite_fs.datasets(username text,
       	  	  	                      pubkeys text[],
        				      include_user_keys boolean DEFAULT FALSE)
RETURNS TABLE(
               stable_id      text,
	       filename      text,

	       ctime         bigint,
	       mtime         bigint,
	       payload_size  bigint,

	       rel_path      text,
	       header        bytea,
 	       prepend       bytea,
 	       append 	     bytea,

	       sha256         bytea,

	       dataset_stable_id text,
	       dataset_ctime     bigint,
	       dataset_mtime     bigint)
LANGUAGE plpgsql
AS $_$
DECLARE
	_user_id int8;
        _number_recipient_keys integer;
        _recipient_keys bytea[];
BEGIN

	-- checks
	SELECT ut.id INTO _user_id
	FROM public.user_table ut
	WHERE username = lower(username);

	IF _user_id IS NULL THEN
	   RAISE EXCEPTION 'Could not find user id of user %', username;
	END IF;

	-- RAISE NOTICE '_user_id is %', _user_id;

	WITH c4gh_keys AS (
	     SELECT -- DISTINCT
	     	    CASE WHEN (starts_with(trim(key), 'ssh-ed25519') OR 
	     	               starts_with(trim(key), '-----BEGIN CRYPT4GH PUBLIC KEY-----'))
		         THEN sqlite_fs.parse_pubkey(key)
		         ELSE NULL
		    END AS pubkey
	     FROM unnest(pubkeys) AS t(key)
	     UNION -- ALL
	     SELECT -- DISTINCT
	            CASE WHEN include_user_keys
		         THEN ukt.pubkey
		         ELSE NULL
		    END AS pubkey
	     FROM public.user_key_table ukt
	        WHERE ukt.type IN ('c4gh-v1'::public.key_type,'ssh-ed25519'::public.key_type)
	          AND ukt.user_id = _user_id
        )
	SELECT array_agg(pubkey)
	INTO _recipient_keys
	FROM c4gh_keys
	WHERE pubkey IS NOT NULL
	;

	-- RAISE NOTICE '% recipient keys: %', cardinality(_recipient_keys), _recipient_keys;

        IF _recipient_keys IS NULL OR cardinality(_recipient_keys) = 0 THEN
           RAISE EXCEPTION 'no encryption keys found';
        END IF;

	
	RETURN QUERY
	SELECT ft.stable_id, ft.display_name,
	       extract(epoch from pft.created_at)::bigint,
               extract(epoch from pft.edited_at)::bigint,
	       pft.payload_size,
	       pft.relative_path,
	       crypt4gh.header_reencrypt(pft.header, _recipient_keys) AS header,
	       null::bytea, null::bytea, -- append/prepend
	       pft.decrypted_sha256,
       	       d.stable_id, d.ctime, d.mtime
	FROM fs.lookup_dataset(_user_id, NULL) d -- checks permissions
	INNER JOIN public.dataset_file_table dft ON dft.dataset_stable_id = d.stable_id
	INNER JOIN private.file_table pft ON pft.stable_id = dft.file_stable_id
	INNER JOIN public.file_table ft ON ft.stable_id = dft.file_stable_id
	;



END;
$_$;


CREATE OR REPLACE FUNCTION sqlite_fs.datasets(username text,
       	  	  	                      pubkey text,
        				      include_user_keys boolean DEFAULT FALSE)
RETURNS TABLE(
               stable_id      text,
	       filename      text,

	       ctime         bigint,
	       mtime         bigint,
	       payload_size  bigint,

	       rel_path      text,
	       header        bytea,
 	       prepend       bytea,
 	       append 	     bytea,

	       sha256         bytea,

	       dataset_stable_id text,
	       dataset_ctime     bigint,
	       dataset_mtime     bigint)
LANGUAGE SQL
AS $_$
	SELECT * FROM sqlite_fs.datasets(username,
				         ARRAY[pubkey]::text[],
	       	      			 include_user_keys => include_user_keys);
$_$;

CREATE OR REPLACE FUNCTION sqlite_fs.datasets(username text)
RETURNS TABLE(
               stable_id      text,
	       filename      text,

	       ctime         bigint,
	       mtime         bigint,
	       payload_size  bigint,

	       rel_path      text,
	       header        bytea,
 	       prepend       bytea,
 	       append 	     bytea,

	       sha256         bytea,

	       dataset_stable_id text,
	       dataset_ctime     bigint,
	       dataset_mtime     bigint)
LANGUAGE SQL
AS $_$
	SELECT * FROM sqlite_fs.datasets(username,
				         ARRAY[]::text[],
	       	      			 include_user_keys => TRUE);

$_$;
