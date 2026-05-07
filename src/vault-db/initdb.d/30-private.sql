CREATE SCHEMA private;

CREATE TABLE private.user_password_table
(
    user_id             bigint NOT NULL PRIMARY KEY REFERENCES public.user_table(id),
    password_hash       text NOT NULL,
    is_enabled          boolean NOT NULL DEFAULT TRUE,

    -- auditing
    created_by_db_user      text NOT NULL DEFAULT CURRENT_USER,
    created_at              timestamp(6) with time zone NOT NULL DEFAULT now(),
    edited_by_db_user       text NOT NULL DEFAULT CURRENT_USER,
    edited_at               timestamp(6) with time zone NOT NULL DEFAULT now()
);


CREATE TABLE private.dataset_permission_table (
    id          	bigserial NOT NULL PRIMARY KEY,

    dataset_stable_id  	text NOT NULL, --- REFERENCES public.dataset_table(stable_id),
    user_id     	bigint NOT NULL REFERENCES public.user_table(id),
    UNIQUE(dataset_stable_id, user_id),
    
    expires_at          timestamp(6) with time zone,

    -- auditing
    created_by_db_user      text NOT NULL DEFAULT CURRENT_USER,
    created_at              timestamp(6) with time zone NOT NULL DEFAULT now(),
    edited_by_db_user       text NOT NULL DEFAULT CURRENT_USER,
    edited_at               timestamp(6) with time zone NOT NULL DEFAULT now()
);

------------------------------
-- Private file information --
------------------------------

CREATE TABLE private.file_table (
    stable_id            text NOT NULL PRIMARY KEY REFERENCES public.file_table(stable_id),
    -- mount_point   text DEFAULT current_setting('vault.dirpath'),
    relative_path text,
    header        bytea, -- not replicated
    header_size   integer GENERATED ALWAYS AS (octet_length(header)) VIRTUAL,
    payload_size  bigint,

    -- only sha256
    payload_sha256            bytea NULL CHECK (payload_sha256 IS NULL
                                                OR length(payload_sha256) = 32),
    decrypted_sha256          bytea NULL CHECK (decrypted_sha256 IS NULL
                                                OR length(decrypted_sha256) = 32),
    original_encrypted_sha256 bytea NULL CHECK (original_encrypted_sha256 IS NULL
                                                OR length(original_encrypted_sha256) = 32),

    -- auditing
    created_by_db_user      text NOT NULL DEFAULT CURRENT_USER,
    created_at              timestamp(6) with time zone NOT NULL DEFAULT now(),
    edited_by_db_user       text NOT NULL DEFAULT CURRENT_USER,
    edited_at               timestamp(6) with time zone NOT NULL DEFAULT now()
);
