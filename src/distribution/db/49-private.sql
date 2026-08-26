CREATE SCHEMA IF NOT EXISTS private;

CREATE OR REPLACE VIEW private.header_user_keys AS
  SELECT ukt.user_id,
    ukt.key,
    ukt.type
   FROM public.user_key_table ukt
  WHERE ukt.type IN ('c4gh-v1'::public.key_type,'ssh-ed25519'::public.key_type);


-- View to get re-encrypted headers
--maybe like this to add the public datasets? but how did we do this in the current one?
CREATE OR REPLACE VIEW private.username_file_header AS
SELECT ut.id           AS user_id,
       ut.username     AS username,
       pubft.stable_id AS stable_id,
       crypt4gh.header_reencrypt(ft.header, array_agg(ukt.pubkey))
                       AS reencrypted_header
FROM private.file_table ft
JOIN public.file_table pubft ON pubft.stable_id = ft.stable_id
JOIN public.dataset_file_table dft ON dft.file_stable_id = ft.stable_id
JOIN public.dataset_table dt ON dt.stable_id = dft.dataset_stable_id
JOIN private.dataset_permission_table dpt ON dpt.dataset_stable_id = dt.stable_id
JOIN public.user_table ut ON ut.id = dpt.user_id
JOIN public.user_key_table ukt ON ukt.user_id = ut.id AND  ukt.type IN ('c4gh-v1'::public.key_type,'ssh-ed25519'::public.key_type)
GROUP BY ut.id, ut.username, pubft.stable_id, ft.header
--
UNION ALL
--
SELECT ut.id           AS user_id,
       ut.username     AS username,
       pubft.stable_id AS stable_id,
       crypt4gh.header_reencrypt(ft.header, array_agg(ukt.pubkey))
                       AS reencrypted_header
FROM private.file_table ft
JOIN public.file_table pubft ON pubft.stable_id = ft.stable_id
JOIN public.dataset_file_table dft ON dft.file_stable_id = ft.stable_id
JOIN public.dataset_table dt ON (dt.stable_id = dft.dataset_stable_id AND
                                 dt.access_type IN ('public'::access_type, 'registered'::access_type))
CROSS JOIN public.user_table ut
      JOIN public.user_key_table ukt ON (ukt.user_id = ut.id AND
                                         ukt.type IN ('c4gh-v1'::public.key_type,'ssh-ed25519'::public.key_type))
GROUP BY ut.id, ut.username, pubft.stable_id, ft.header
;

