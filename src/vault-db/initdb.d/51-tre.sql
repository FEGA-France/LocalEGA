CREATE OR REPLACE FUNCTION tre.process_list_message(_message jsonb)
RETURNS bigint
LANGUAGE plpgsql
AS $_$
DECLARE
	_rows_inserted bigint;
 	_username text;
 	_user_id bigint;
BEGIN

    -- Find the user first
    _user_id := NULL;
    _username := NULL;
    SELECT id, username INTO _user_id, _username
    FROM public.user_table
    WHERE username = trim(_message->>'username');
    
    IF _username IS NULL THEN
       RAISE EXCEPTION 'User not found for %', _message;
    END IF;


    INSERT INTO tre.user_selection_table(username, selection)
    VALUES (_username, _message)
    ON CONFLICT (username)
    DO UPDATE
          SET selection = EXCLUDED.selection
        ;

    RETURN 1;

    -- -- Delete old mappings
    -- DELETE FROM tre.artifact_user_table
    -- WHERE username = _username
    -- ; -- on error: ROLLBACK

    -- -- Flatten the artifact lists
    -- WITH data_selection AS (
    -- 	 SELECT value->>'url'     AS url,
    -- 	        'data'::tre.artifact_type AS type,
    -- 		REPLACE(value->>'fspath', '..', '_') AS fspath
    -- 	 FROM jsonb_array_elements(_message->'selection'->'data')
    -- 	 WHERE value->>'url' IS NOT NULL
    -- 	   AND value->>'fspath' IS NOT NULL
    -- ), tool_selection AS (
    -- 	 SELECT value->>'image'   AS url,
    -- 	        'tool'::tre.artifact_type AS type,
    -- 		REPLACE(value->>'fspath', '..', '_') AS fspath
    -- 	 FROM jsonb_array_elements(_message->'selection'->'tools')
    -- 	 WHERE value->>'image' IS NOT NULL
    -- 	   AND value->>'fspath' IS NOT NULL
    -- ), selected AS (
    -- 	 SELECT * FROM data_selection
    -- 	 UNION
    -- 	 SELECT * FROM tool_selection
    -- ),inserted_artifacts AS (
    -- 	 INSERT INTO tre.artifact_table AS t(url, type)
    -- 	 SELECT s.url, s.type FROM selected s
    -- 	 ON CONFLICT (url) -- not type
    -- 	 DO NOTHING
    -- 	 -- DO UPDATE
    -- 	 -- 	SET selection = EXCLUDED.selection
    -- ), inserted_mappings AS (
    --    -- Insert new mappings
    --    INSERT INTO tre.artifact_user_table(artifact_id, username, fspath)
    --    SELECT a.id, _username, s.fspath
    --    FROM tre.artifact_table a
    --    JOIN selected s ON s.url = a.url -- add type, if added above
    --    RETURNING artifact_id, username
    -- )
    -- SELECT count(*) INTO _rows_inserted
    -- FROM inserted_mappings
    -- ;

    -- RETURN _rows_inserted;

END
$_$;
