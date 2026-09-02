-- if depends on 51 for: fs.decrypted_filesize and fs.header_size


CREATE OR REPLACE FUNCTION sqlite_fs.generate_box_checks(_username text, _datasets text[])
RETURNS bigint AS $BODY$
DECLARE
     _user_id int8;
     _number_recipient_keys integer;
BEGIN

	SELECT id INTO _user_id	FROM public.user_table where username=_username;

	IF (_user_id IS NULL) THEN
		RAISE EXCEPTION 'Could not find user id of user %', _username;
	END IF;

	RAISE NOTICE '_user_id is %', _user_id;

	SELECT count(*) INTO _number_recipient_keys FROM public.header_keys WHERE user_id=_user_id;
        IF _number_recipient_keys IS NULL OR _number_recipient_keys = 0 THEN
            RAISE EXCEPTION 'user has no encryption keys';
        END IF;

	RETURN _user_id;

END;
$BODY$
LANGUAGE plpgsql;


CREATE OR REPLACE FUNCTION sqlite_fs.generate_box(_username text, _datasets text[], _reset bool default false)
RETURNS text AS $BODY$
DECLARE
	_user_id int8;
	_error_message text;
BEGIN

	BEGIN
	    SELECT * INTO _user_id FROM sqlite_fs.generate_box_checks(_username, _datasets);
	EXCEPTION
	    WHEN raise_exception THEN
	        GET STACKED DIAGNOSTICS _error_message = message_text;
	    RETURN _error_message;
        END;

	PERFORM * FROM sqlite_fs.generate_sqlite_box(_username, _user_id, _datasets, _reset);

	RETURN 'OK';

END;
$BODY$
LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION sqlite_fs.generate_box(_username text, _reset bool default false)
RETURNS text AS $BODY$
SELECT * FROM sqlite_fs.generate_box(_username, null, _reset)
$BODY$
LANGUAGE SQL;


CREATE OR REPLACE FUNCTION sqlite_fs.generate_sqlite_box(_username text, _user_id int8, _datasets text[], _reset bool)
RETURNS void AS $BODY$
--do not call directly
DECLARE
   _box_path text;
BEGIN

 	SELECT concat_ws('', current_setting('sqlite_fs.location'), '/', _user_id, '.sqlite') INTO _box_path;

	RAISE NOTICE 'path for box is %', _box_path;

 	IF (_reset) THEN
	        RAISE NOTICE 'Deleting %', _box_path;
 		PERFORM sqlite_fs.remove(_box_path); -- maybe better just truncate
 	END IF;

 	--create box
 	PERFORM sqlite_fs.make(_box_path);

	--Create dbox content entries and files' info
	PERFORM (
	WITH datasets AS (
		SELECT *, 1::int8 AS parent_ino
		FROM fs.readdir(_username, 1, null, null)
		WHERE CASE WHEN _datasets IS NULL THEN TRUE ELSE display_name=ANY(_datasets) END
	), files AS (
	   	SELECT f.ino,
		       f.display_name, -- it contains .c4gh
		       f.ctime,
		       f.mtime,
		       f.nlink,
		       f.size,
		       f.decrypted_filesize,
		       f.is_dir,
		       datasets.ino AS parent_ino
		FROM datasets
		JOIN LATERAL fs.readdir(_username, datasets.ino, null, null) f ON TRUE
	), entries AS (
		SELECT * FROM datasets
		UNION ALL
		SELECT * FROM files
        ), -- insert entries
          inserted_entries AS (
	   	SELECT entries.ino, entries.is_dir, sqlite_fs.insert_entry(_box_path,
	                              entries.ino, entries.display_name, entries.parent_ino,
				      entries.decrypted_filesize,
				      entries.ctime,
				      entries.mtime,
				      entries.nlink,
				      entries.size,
				      entries.is_dir)
	        FROM entries
        ), -- get files
	   files_info AS (
	   	      SELECT info.filepath, info.header, files.ino
		      FROM files 
		      JOIN LATERAL fs.get_file_info(_username, files.ino) info ON TRUE
        )
	SELECT sqlite_fs.insert_file(_box_path,
	                             inserted_entries.ino, --files_info.ino,
			             files_info.filepath,
			             files_info.header)
        FROM files_info
        -- JOIN files ON files.ino=files_info.ino
        JOIN inserted_entries ON inserted_entries.ino=files_info.ino AND NOT inserted_entries.is_dir
	-- We force the execution of the inserted_entries CTE. If not, it skips it
        ); -- close PERFORM

END;
$BODY$
LANGUAGE plpgsql;
