-- if depends on 60 for: fs.decrypted_filesize and fs.header_size

-- DROP FUNCTION sqlite_fs.datasets(_username text);

CREATE OR REPLACE FUNCTION sqlite_fs.datasets(_username text)
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
BEGIN

	-- checks
	SELECT ut.id INTO _user_id
	FROM public.user_table ut
	WHERE username = lower(_username);

	IF _user_id IS NULL THEN
	   RAISE EXCEPTION 'Could not find user id of user %', _username;
	END IF;

	-- RAISE NOTICE '_user_id is %', _user_id;

	SELECT count(*) INTO _number_recipient_keys FROM public.header_keys WHERE user_id=_user_id;
        IF _number_recipient_keys IS NULL OR _number_recipient_keys = 0 THEN
           RAISE EXCEPTION 'user has no encryption keys';
        END IF;

	
	RETURN QUERY
	SELECT ft.stable_id, ft.display_name,
	       extract(epoch from pft.created_at)::bigint,
               extract(epoch from pft.edited_at)::bigint,
	       pft.payload_size,
	       pft.relative_path,
	       v.reencrypted_header, null::bytea, null::bytea,
	       pft.decrypted_sha256,
       	       d.stable_id, d.ctime, d.mtime
	FROM fs.lookup_dataset(_user_id, NULL) d -- checks permissions
	INNER JOIN public.dataset_file_table dft ON dft.dataset_stable_id = d.stable_id
	INNER JOIN private.file_table pft ON pft.stable_id = dft.file_stable_id
	INNER JOIN public.file_table ft ON ft.stable_id = dft.file_stable_id
	INNER JOIN private.username_file_header v ON v.stable_id = pft.stable_id
    	WHERE v.user_id = _user_id
	  AND v.reencrypted_header IS NOT NULL
	;

END;
$_$;
