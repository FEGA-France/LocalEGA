
CREATE SCHEMA tre;

CREATE TABLE tre.user_selection_table
(
    --user_id           bigint NOT NULL PRIMARY KEY REFERENCES public.user_table(id),
    username          text NOT NULL PRIMARY KEY REFERENCES public.user_table(username),
    selection         jsonb,

    -- auditing
    created_by_db_user      text NOT NULL DEFAULT CURRENT_USER,
    created_at              timestamp(6) with time zone NOT NULL DEFAULT now(),
    edited_by_db_user       text NOT NULL DEFAULT CURRENT_USER,
    edited_at               timestamp(6) with time zone NOT NULL DEFAULT now()
);

-- CREATE TYPE tre.status_type AS ENUM (
--     'caching', 'cached',
--     'uploading', -- 'uploaded',
--     'archiving', 'archived',
--     'error'
-- );


-- ----------------
-- -- DATA/TOOLS -- 
-- ----------------

-- CREATE TYPE tre.artifact_type AS ENUM (
--     'data',
--     'tool'
-- );

-- CREATE SEQUENCE tre.artifact_table_id_seq;

-- -- if we are in this table, the data/tool file was downloaded at FEGA,
-- -- ready to be uploaded to LEGA
-- CREATE TABLE tre.artifact_table (

--     id        bigint NOT NULL PRIMARY KEY DEFAULT nextval('tre.artifact_table_id_seq'),
--     url       text NOT NULL UNIQUE,

--     -- attributes
--     type      tre.artifact_type NOT NULL,
--     version   text, -- info

--     -- after download
--     filesize  bigint,
--     sha256    bytea,
--     path      text, -- local FEGA path

--     -- auditing
--     created_by_db_user      text NOT NULL DEFAULT CURRENT_USER,
--     created_at              timestamp(6) with time zone NOT NULL DEFAULT now(),
--     edited_by_db_user       text NOT NULL DEFAULT CURRENT_USER,
--     edited_at               timestamp(6) with time zone NOT NULL DEFAULT now()
-- )
-- ;

-- -------------------------------
-- -- USER DATA/TOOLS SELECTION --
-- -------------------------------

-- CREATE TABLE tre.artifact_user_table (

--     artifact_id bigint NOT NULL REFERENCES tre.artifact_table(id),
--     username 	text NOT NULL REFERENCES public.user_table(username),
--     PRIMARY KEY(artifact_id, username),

--     fspath text NOT NULL,
--     CONSTRAINT unique_path_across_users UNIQUE(username, fspath),

--     -- auditing
--     created_by_db_user      text NOT NULL DEFAULT CURRENT_USER,
--     created_at              timestamp(6) with time zone NOT NULL DEFAULT now(),
--     edited_by_db_user       text NOT NULL DEFAULT CURRENT_USER,
--     edited_at               timestamp(6) with time zone NOT NULL DEFAULT now()
-- );
