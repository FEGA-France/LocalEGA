



CREATE OR REPLACE FUNCTION public.dispatch_message(_m text, _properties jsonb)
--RETURNS TABLE(routing_key text, response jsonb, correlation_id text)
RETURNS void
LANGUAGE plpgsql
AS $_$
DECLARE
	_reenc_result bytea;
	_header bytea;
	_pubkey bytea;
	_message jsonb;
BEGIN

    _message := _m::jsonb;

    -- Dispatch based on the value of "type"
    CASE _message->>'type'

	WHEN 'file.archived' THEN

	     -- RAISE NOTICE 'Archiving message: %', _message::text;

	    _header := decode(_message->>'header', 'hex')::bytea;

	    -- Use itself as dummy key
	    SELECT * INTO _pubkey
            FROM crypt4gh.parse_pubkey(
	     	     'ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIH+oXzyoURWMTEkWQ9yvll2f8VuHnq4VZdVa2GzF68IW master@lega'
		 );

	    -- Check if properly encrypted: reencrypt the header for dummy key!
	    SELECT header_reencrypt INTO _reenc_result
	    FROM crypt4gh.header_reencrypt(_header, _pubkey);

	    IF _reenc_result IS NULL
	    THEN 
		RAISE EXCEPTION 'could not reencrypt header for itself';
	    END IF;

	    WITH pub_ins AS (
                INSERT INTO public.file_table AS t(stable_id, filesize, display_name)
                VALUES (_message->>'accession_id',
	    	        (_message->>'payload_size')::bigint + octet_length(_header),
		        -- we add "this" header size (once re-encrypted it might be bigger)
			REGEXP_REPLACE(_message->>'filepath', '^.*\/([^\/]*?)(\.c4gh)*$', '\1'))
	    	RETURNING stable_id
            )
	    INSERT INTO private.file_table(stable_id, relative_path, header,
	                                   payload_size, payload_sha256, decrypted_sha256, original_encrypted_sha256)
            SELECT p.stable_id, _message->>'relative_path', _header, (_message->>'payload_size')::bigint,
		   decode(_message->>'payload_sha256', 'hex')::bytea,
		   decode(_message->>'plaintext_sha256', 'hex')::bytea,
		   decode(_message->>'inbox_sha256', 'hex')::bytea
            FROM pub_ins p;

	-- Cases when we should remove files from the Vault
	-- eg after a consent was retracted
        WHEN 'clean' THEN

            IF _message->>'accession_id' IS NULL
            THEN
               RAISE EXCEPTION 'Missing required fields';
            END IF;

	    -- this takes care of removing an archived file from the vault
	    WITH deleted_mapping AS (
		  DELETE FROM public.dataset_file_table dft WHERE dft.file_stable_id = _message->>'accession_id'
	    ), deleted_priv AS (		  
		  DELETE FROM private.file_table pft WHERE pft.stable_id = _message->>'accession_id'
            )
	    DELETE FROM public.file_table ft WHERE ft.stable_id = _message->>'accession_id'
	    ;


	-- datasets
        WHEN 'mapping' THEN
            PERFORM public.process_mapping_message(_message);
        WHEN 'deprecate' THEN
            PERFORM public.process_deprecated_message(_message);
        WHEN 'release' THEN
            PERFORM public.process_release_message(_message);

	-- permissions
        WHEN 'permission' THEN
            PERFORM public.process_permission_message(_message);
        WHEN 'permission.deleted' THEN
            PERFORM public.process_deleted_permission_message(_message);

	-- users
        WHEN 'password.updated' THEN
            PERFORM public.process_user_password_message(_message);
        WHEN 'contact.updated' THEN
            PERFORM public.process_user_contact_message(_message);
        WHEN 'keys.updated' THEN
            PERFORM public.process_user_keys_message(_message);

	-- datasets
        WHEN 'dac' THEN
            PERFORM public.process_dac_message(_message);
        WHEN 'dac.dataset' THEN
            PERFORM public.process_dac_dataset_message(_message);
        WHEN 'dac.members' THEN
            PERFORM public.process_dac_members_message(_message);
        WHEN 'dac' THEN
            PERFORM public.process_dac_dataset_message(_message);

        -- Add more cases as needed
        ELSE
            RAISE EXCEPTION 'Invalid message type "%" for message %', _message->>'type', _message;
    END CASE;

END;
$_$;
