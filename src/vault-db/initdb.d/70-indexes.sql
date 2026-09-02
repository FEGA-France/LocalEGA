
CREATE INDEX ON public.file_table (display_name);

CREATE INDEX ON private.file_table (decrypted_sha256) INCLUDE (stable_id);
CREATE INDEX ON private.file_table (original_encrypted_sha256) INCLUDE (stable_id);

-- #####################
-- Users
-- #####################


CREATE INDEX username_idx ON public.user_table USING btree (id, username);

CREATE INDEX user_id_idx ON private.dataset_permission_table USING btree (user_id, dataset_stable_id);


CREATE INDEX idx_user_id_user_key_table
ON public.user_key_table
USING btree (user_id ASC NULLS LAST)
;

CREATE INDEX idx_user_id_user_password_table
ON private.user_password_table
USING btree (user_id ASC NULLS LAST)
;


