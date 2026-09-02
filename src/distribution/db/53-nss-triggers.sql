-- ################################################
-- On user updates
-- ################################################

CREATE OR REPLACE FUNCTION nss.trigger_bulk_users()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $BODY$
BEGIN
	-- rebuild all, inefficient but correct
	PERFORM * FROM nss.make_users();
	PERFORM * FROM nss.make_groups();
	PERFORM * FROM nss.make_passwords();
	RETURN NULL; -- cuz it's an after trigger
END;
$BODY$;

CREATE OR REPLACE FUNCTION nss.trigger_user_keys()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $BODY$
DECLARE
	_user_id bigint;
BEGIN
	IF TG_OP='DELETE' THEN
	   _user_id= OLD.id;
	ELSE -- if insert or update
	   _user_id = NEW.id;
	END IF;

	PERFORM * FROM nss.make_authorized_keys(_user_id);
	RETURN NULL; -- cuz it's an after trigger
END;
$BODY$;

CREATE OR REPLACE TRIGGER build_bulk_users
AFTER INSERT OR UPDATE OR DELETE
ON public.user_table
FOR EACH ROW
EXECUTE PROCEDURE nss.trigger_bulk_users();

CREATE OR REPLACE TRIGGER build_user_keys
AFTER INSERT OR UPDATE OR DELETE
ON public.user_table
FOR EACH ROW
EXECUTE PROCEDURE nss.trigger_user_keys();

-- ################################################
-- On password updates
-- ################################################

CREATE OR REPLACE FUNCTION nss.trigger_bulk_passwords()
RETURNS TRIGGER
LANGUAGE plpgsql VOLATILE
AS $BODY$
BEGIN
	-- rebuild all, inefficient but correct
	PERFORM * FROM nss.make_users();
	--PERFORM * FROM nss.make_groups();
	PERFORM * FROM nss.make_passwords();
	RETURN NULL; -- cuz it's an after trigger
END;
$BODY$;

CREATE OR REPLACE TRIGGER build_bulk_passwords
AFTER INSERT OR UPDATE OR DELETE
ON private.user_password_table
FOR EACH ROW
EXECUTE PROCEDURE nss.trigger_bulk_passwords();


-- ################################################
-- On user keys updates
-- ################################################

CREATE OR REPLACE FUNCTION nss.trigger_authorized_keys()
RETURNS TRIGGER
LANGUAGE plpgsql
AS $BODY$
DECLARE
	_user_id bigint;
	_detail text;
	_hint text;
	_context text;
	_message text;
BEGIN
	IF TG_OP='DELETE' THEN
	   _user_id= OLD.user_id;
	ELSE -- if insert or update
	   _user_id = NEW.user_id;
	END IF;

	PERFORM * FROM nss.make_authorized_keys(_user_id);
	RETURN NULL; -- cuz it's an after trigger
END;
$BODY$;

CREATE OR REPLACE TRIGGER build_authorized_keys
AFTER INSERT OR UPDATE OR DELETE
ON public.user_key_table
FOR EACH ROW
EXECUTE PROCEDURE nss.trigger_authorized_keys();

