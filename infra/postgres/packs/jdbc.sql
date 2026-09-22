-- Legacy SQL pack for the JDBC client.
-- Applied by infra/postgres/init.sh on database lab after schema.sql.
-- A second apply does not drop tables, roles, or rows, and does not reseed SCIM users.
-- Rows in legacy_app.accounts are application accounts, not PostgreSQL logins.
-- Passwords are not stored in this file.
-- Grant legacy_reader SELECT only and legacy_provisioner INSERT/UPDATE on these tables.
-- No superuser.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'legacy_reader') THEN
        CREATE ROLE legacy_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'legacy_provisioner') THEN
        CREATE ROLE legacy_provisioner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
END
$$;

COMMENT ON ROLE legacy_reader IS
    'SELECT only on legacy_app tables. Not a superuser.';
COMMENT ON ROLE legacy_provisioner IS
    'INSERT and UPDATE on legacy_app tables. Not a superuser.';

CREATE SCHEMA IF NOT EXISTS legacy_app;

COMMENT ON SCHEMA legacy_app IS
    'Application accounts and roles. These rows are not PostgreSQL logins.';

CREATE TABLE IF NOT EXISTS legacy_app.accounts (
    id uuid PRIMARY KEY,
    login text NOT NULL,
    employee_ref text,
    status text NOT NULL,
    display_name text,
    CONSTRAINT accounts_login_key UNIQUE (login)
);

COMMENT ON TABLE legacy_app.accounts IS
    'Application accounts, not PostgreSQL logins. legacy_reader has SELECT only. legacy_provisioner has INSERT and UPDATE.';

CREATE TABLE IF NOT EXISTS legacy_app.roles (
    id uuid PRIMARY KEY,
    name text NOT NULL,
    CONSTRAINT roles_name_key UNIQUE (name),
    CONSTRAINT roles_name_chk CHECK (length(btrim(name)) > 0)
);

COMMENT ON TABLE legacy_app.roles IS
    'Application roles, not PostgreSQL roles. A blank name violates roles_name_chk.';

CREATE TABLE IF NOT EXISTS legacy_app.account_roles (
    account_id uuid NOT NULL,
    role_id uuid NOT NULL,
    PRIMARY KEY (account_id, role_id),
    CONSTRAINT account_roles_account_fk
        FOREIGN KEY (account_id) REFERENCES legacy_app.accounts (id),
    CONSTRAINT account_roles_role_fk
        FOREIGN KEY (role_id) REFERENCES legacy_app.roles (id)
);

COMMENT ON TABLE legacy_app.account_roles IS
    'Application role grants. A missing role fails account_roles_role_fk.';

CREATE TABLE IF NOT EXISTS legacy_app.change_events (
    id bigserial PRIMARY KEY,
    account_id uuid NOT NULL,
    op text NOT NULL,
    at timestamptz NOT NULL,
    CONSTRAINT change_events_account_fk
        FOREIGN KEY (account_id) REFERENCES legacy_app.accounts (id)
);

COMMENT ON TABLE legacy_app.change_events IS
    'Changes to application accounts. Not a PostgreSQL login audit.';

REVOKE ALL ON SCHEMA legacy_app FROM PUBLIC;
GRANT USAGE ON SCHEMA legacy_app TO legacy_reader, legacy_provisioner;
REVOKE CREATE ON SCHEMA legacy_app FROM legacy_reader, legacy_provisioner;

REVOKE ALL ON
    legacy_app.accounts,
    legacy_app.roles,
    legacy_app.account_roles,
    legacy_app.change_events
    FROM PUBLIC;

GRANT SELECT ON
    legacy_app.accounts,
    legacy_app.roles,
    legacy_app.account_roles,
    legacy_app.change_events
    TO legacy_reader;

GRANT INSERT, UPDATE ON
    legacy_app.accounts,
    legacy_app.roles,
    legacy_app.account_roles,
    legacy_app.change_events
    TO legacy_provisioner;

-- Resolving a role name is a read. The foreign-key check itself does not grant this.
GRANT SELECT ON legacy_app.roles TO legacy_provisioner;

-- Revoke removes one membership row. Accounts, roles, and change events stay.
GRANT DELETE ON legacy_app.account_roles TO legacy_provisioner;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE, TRIGGER, REFERENCES ON
    legacy_app.accounts,
    legacy_app.roles,
    legacy_app.account_roles,
    legacy_app.change_events
    FROM legacy_reader;

REVOKE DELETE, TRUNCATE, TRIGGER, REFERENCES ON
    legacy_app.accounts,
    legacy_app.roles,
    legacy_app.change_events
    FROM legacy_provisioner;

REVOKE TRUNCATE, TRIGGER, REFERENCES ON legacy_app.account_roles FROM legacy_provisioner;

-- bigserial defaults call nextval. USAGE is not ownership and not superuser.
REVOKE ALL ON SEQUENCE legacy_app.change_events_id_seq FROM PUBLIC, legacy_reader;
GRANT USAGE ON SEQUENCE legacy_app.change_events_id_seq TO legacy_provisioner;
