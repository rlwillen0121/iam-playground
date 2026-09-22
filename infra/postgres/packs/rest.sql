-- Proprietary REST accounts for rest-modern and rest-legacy.
-- These tables are not scim_users, scim_groups, or scim_members.
-- Applied by infra/postgres/init.sh after schema.sql.
-- A second apply does not drop rows, reset id counters, or delete seeded roles.

CREATE TABLE IF NOT EXISTS rest_id_alloc (
    app_id text PRIMARY KEY,
    next_id integer NOT NULL,
    CONSTRAINT rest_id_alloc_app_chk CHECK (app_id IN ('rest-modern', 'rest-legacy')),
    CONSTRAINT rest_id_alloc_next_chk CHECK (next_id >= 1)
);

CREATE TABLE IF NOT EXISTS rest_accounts (
    app_id text NOT NULL,
    id integer NOT NULL,
    login text NOT NULL,
    employee_ref text NOT NULL,
    status text NOT NULL,
    first_name text NOT NULL,
    last_name text NOT NULL,
    department text NOT NULL,
    PRIMARY KEY (app_id, id),
    CONSTRAINT rest_accounts_app_chk CHECK (app_id IN ('rest-modern', 'rest-legacy')),
    CONSTRAINT rest_accounts_status_chk CHECK (status IN ('enabled', 'disabled')),
    CONSTRAINT rest_accounts_login_len CHECK (char_length(login) BETWEEN 1 AND 200),
    CONSTRAINT rest_accounts_employee_ref_len CHECK (char_length(employee_ref) BETWEEN 1 AND 200),
    CONSTRAINT rest_accounts_first_name_len CHECK (char_length(first_name) BETWEEN 1 AND 200),
    CONSTRAINT rest_accounts_last_name_len CHECK (char_length(last_name) BETWEEN 1 AND 200),
    CONSTRAINT rest_accounts_department_len CHECK (char_length(department) BETWEEN 1 AND 200)
);

-- Login uniqueness is case-insensitive inside one application.
CREATE UNIQUE INDEX IF NOT EXISTS rest_accounts_login_lower_idx
    ON rest_accounts (app_id, lower(login));

CREATE TABLE IF NOT EXISTS rest_roles (
    app_id text NOT NULL,
    name text NOT NULL,
    PRIMARY KEY (app_id, name),
    CONSTRAINT rest_roles_app_chk CHECK (app_id IN ('rest-modern', 'rest-legacy')),
    CONSTRAINT rest_roles_name_chk CHECK (name ~ '^[a-z][a-z0-9-]{0,63}$')
);

CREATE TABLE IF NOT EXISTS rest_account_roles (
    app_id text NOT NULL,
    account_id integer NOT NULL,
    role_name text NOT NULL,
    PRIMARY KEY (app_id, account_id, role_name),
    CONSTRAINT rest_account_roles_account_fk
        FOREIGN KEY (app_id, account_id) REFERENCES rest_accounts (app_id, id) ON DELETE CASCADE,
    CONSTRAINT rest_account_roles_role_fk
        FOREIGN KEY (app_id, role_name) REFERENCES rest_roles (app_id, name)
);

CREATE TABLE IF NOT EXISTS rest_operations (
    id text PRIMARY KEY,
    app_id text NOT NULL,
    client_id text NOT NULL,
    idempotency_key text NOT NULL,
    payload_hash text NOT NULL,
    payload text NOT NULL,
    kind text NOT NULL,
    state text NOT NULL,
    account_id integer,
    role_name text,
    applied boolean NOT NULL,
    error text,
    generation integer NOT NULL,
    created_at timestamptz NOT NULL,
    updated_at timestamptz NOT NULL,
    CONSTRAINT rest_operations_app_chk CHECK (app_id IN ('rest-modern', 'rest-legacy')),
    CONSTRAINT rest_operations_client_chk CHECK (
        client_id IN (
            'rest-modern',
            'rest-modern-read',
            'rest-legacy',
            'rest-legacy-read'
        )
    ),
    CONSTRAINT rest_operations_kind_chk CHECK (
        kind IN (
            'create-account',
            'patch-account',
            'delete-account',
            'enable-account',
            'disable-account',
            'assign-role',
            'remove-role'
        )
    ),
    CONSTRAINT rest_operations_state_chk CHECK (
        state IN ('accepted', 'running', 'succeeded', 'failed', 'cancelled')
    ),
    CONSTRAINT rest_operations_idempotency_key
        UNIQUE (app_id, client_id, idempotency_key)
);

-- No account foreign key: acceptance is stored before the account exists,
-- and a delete operation outlives the account row.
CREATE INDEX IF NOT EXISTS rest_operations_resume_idx
    ON rest_operations (app_id, created_at, id)
    WHERE state IN ('accepted', 'running');

-- Do not reset next_id. A later apply must keep ids already handed out.
INSERT INTO rest_id_alloc (app_id, next_id) VALUES
    ('rest-modern', 1),
    ('rest-legacy', 1)
ON CONFLICT (app_id) DO NOTHING;

INSERT INTO rest_roles (app_id, name) VALUES
    ('rest-modern', 'admin'),
    ('rest-modern', 'operator'),
    ('rest-modern', 'reader'),
    ('rest-legacy', 'admin'),
    ('rest-legacy', 'operator'),
    ('rest-legacy', 'reader')
ON CONFLICT (app_id, name) DO NOTHING;

REVOKE ALL ON
    rest_id_alloc, rest_accounts, rest_roles, rest_account_roles, rest_operations
    FROM PUBLIC;

ALTER TABLE rest_id_alloc OWNER TO target_owner;
ALTER TABLE rest_accounts OWNER TO target_owner;
ALTER TABLE rest_roles OWNER TO target_owner;
ALTER TABLE rest_account_roles OWNER TO target_owner;
ALTER TABLE rest_operations OWNER TO target_owner;

GRANT SELECT ON
    rest_id_alloc, rest_accounts, rest_roles, rest_account_roles, rest_operations
    TO admin_owner, verifier_reader;
-- Truncate drops seeded roles and id counters. Reseed both before accepting work.
GRANT TRUNCATE ON
    rest_id_alloc, rest_accounts, rest_roles, rest_account_roles, rest_operations
    TO admin_owner;

REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
    rest_id_alloc, rest_accounts, rest_roles, rest_account_roles, rest_operations
    FROM verifier_reader;
