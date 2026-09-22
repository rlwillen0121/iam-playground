-- Applied once, on an empty data directory, by infra/postgres/init.sh.
-- App roles are not superusers. Restart does not run this file again.

REVOKE ALL ON SCHEMA public FROM PUBLIC;
GRANT USAGE ON SCHEMA public TO target_owner, verifier_reader, admin_owner;

CREATE TABLE lab_meta (
    generation integer NOT NULL,
    fixture_id text NOT NULL,
    seeded_at timestamptz NOT NULL,
    accepting boolean NOT NULL
);

CREATE UNIQUE INDEX lab_meta_one_row ON lab_meta ((true));

CREATE TABLE scim_users (
    id uuid PRIMARY KEY,
    app_id text NOT NULL,
    external_id text,
    user_name text NOT NULL,
    active boolean NOT NULL,
    given_name text NOT NULL,
    family_name text NOT NULL,
    email text NOT NULL,
    employee_number text NOT NULL,
    department text NOT NULL,
    CONSTRAINT scim_users_app_id_key UNIQUE (app_id, id)
);

CREATE UNIQUE INDEX scim_users_app_username_lower_idx
    ON scim_users (app_id, lower(user_name));

CREATE TABLE scim_groups (
    id uuid PRIMARY KEY,
    app_id text NOT NULL,
    display_name text NOT NULL,
    external_id text,
    CONSTRAINT scim_groups_app_display_key UNIQUE (app_id, display_name),
    CONSTRAINT scim_groups_app_id_key UNIQUE (app_id, id)
);

CREATE TABLE scim_members (
    app_id text NOT NULL,
    group_id uuid NOT NULL,
    user_id uuid NOT NULL,
    PRIMARY KEY (app_id, group_id, user_id),
    CONSTRAINT scim_members_group_fk
        FOREIGN KEY (app_id, group_id) REFERENCES scim_groups (app_id, id),
    CONSTRAINT scim_members_user_fk
        FOREIGN KEY (app_id, user_id) REFERENCES scim_users (app_id, id)
);

CREATE TABLE mutation_journal (
    id bigserial PRIMARY KEY,
    generation integer NOT NULL,
    app_id text NOT NULL,
    actor text NOT NULL,
    op text NOT NULL,
    subject_id text NOT NULL,
    at timestamptz NOT NULL
);

CREATE TABLE account_bindings (
    app_id text NOT NULL,
    issuer text NOT NULL,
    subject text NOT NULL,
    scim_user_id uuid NOT NULL,
    PRIMARY KEY (app_id, issuer, subject),
    -- Deleting a SCIM user removes its binding so a recreated user cannot inherit it.
    CONSTRAINT account_bindings_user_fk
        FOREIGN KEY (app_id, scim_user_id)
        REFERENCES scim_users (app_id, id)
        ON DELETE CASCADE
);

CREATE INDEX account_bindings_scim_user_idx ON account_bindings (scim_user_id);

-- Opaque browser session. No access token, refresh token, or cookie value beyond this id.
CREATE TABLE sessions (
    id text PRIMARY KEY,
    issuer text NOT NULL,
    subject text NOT NULL,
    expires_at timestamptz NOT NULL
);

-- PKCE login state. code_verifier stays server-side. No tokens.
CREATE TABLE login_transactions (
    state text PRIMARY KEY,
    code_verifier text NOT NULL,
    expires_at timestamptz NOT NULL
);

CREATE TABLE runs (
    id uuid PRIMARY KEY,
    generation integer NOT NULL,
    scenario_id text,
    created_at timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE evidence (
    id bigserial PRIMARY KEY,
    run_id uuid,
    kind text,
    body jsonb,
    created_at timestamptz NOT NULL DEFAULT now(),
    CONSTRAINT evidence_run_fk
        FOREIGN KEY (run_id) REFERENCES runs (id) ON DELETE CASCADE
);

ALTER TABLE scim_users OWNER TO target_owner;
ALTER TABLE scim_groups OWNER TO target_owner;
ALTER TABLE scim_members OWNER TO target_owner;
ALTER TABLE mutation_journal OWNER TO target_owner;
ALTER SEQUENCE mutation_journal_id_seq OWNER TO target_owner;
ALTER TABLE sessions OWNER TO target_owner;
ALTER TABLE login_transactions OWNER TO target_owner;

ALTER TABLE lab_meta OWNER TO admin_owner;
ALTER TABLE account_bindings OWNER TO admin_owner;
ALTER TABLE runs OWNER TO admin_owner;
ALTER TABLE evidence OWNER TO admin_owner;
ALTER SEQUENCE evidence_id_seq OWNER TO admin_owner;

GRANT SELECT ON lab_meta TO target_owner;

GRANT SELECT ON scim_users, scim_groups, scim_members, mutation_journal TO admin_owner;
GRANT SELECT ON scim_users, scim_groups, scim_members, mutation_journal TO verifier_reader;
GRANT TRUNCATE ON scim_users, scim_members, mutation_journal TO admin_owner;
GRANT INSERT, TRUNCATE ON scim_groups TO admin_owner;

REVOKE ALL ON account_bindings FROM target_owner, verifier_reader;
-- The demo app reads bindings. It cannot insert, update, delete, or truncate them.
GRANT SELECT ON account_bindings TO target_owner;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON account_bindings FROM target_owner;

REVOKE ALL ON runs FROM target_owner, verifier_reader;
REVOKE ALL ON evidence FROM target_owner, verifier_reader;
REVOKE ALL ON lab_meta FROM verifier_reader;
REVOKE ALL ON sessions, login_transactions FROM verifier_reader, admin_owner;
GRANT TRUNCATE ON sessions, login_transactions TO admin_owner;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON
    scim_users, scim_groups, scim_members, mutation_journal
    FROM verifier_reader;
