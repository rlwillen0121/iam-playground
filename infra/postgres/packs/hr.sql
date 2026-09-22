-- HR source rows. Not SCIM users, not REST accounts, not LDAP entries,
-- and not legacy SQL accounts.
-- Applied by infra/postgres/init.sh on database lab after schema.sql.
-- A second apply does not drop tables or reseed SCIM users.
-- The SQL feed is SELECT only for role hr_reader.
-- Do not add a unique constraint on occurred_at. Equal timestamps are two changes.
-- sequence is the order key.

DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'hr_reader') THEN
        CREATE ROLE hr_reader NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION;
    END IF;
END
$$;

CREATE TABLE IF NOT EXISTS hr_people (
    employee_number text PRIMARY KEY,
    user_name text NOT NULL,
    email text NOT NULL,
    department text NOT NULL,
    manager_employee_number text,
    sequence bigint NOT NULL,
    CONSTRAINT hr_people_sequence_key UNIQUE (sequence),
    CONSTRAINT hr_people_sequence_positive CHECK (sequence > 0)
);

-- manager_employee_number is a reference, not a foreign key and not an account.
-- CSV columns, in order: employeeNumber, userName, email, department,
-- managerEmployeeNumber. sequence is the change order and is not a CSV column.

CREATE TABLE IF NOT EXISTS hr_changes (
    sequence bigint PRIMARY KEY,
    occurred_at timestamptz NOT NULL,
    employee_number text NOT NULL,
    operation text NOT NULL,
    user_name text NOT NULL,
    email text NOT NULL,
    department text NOT NULL,
    manager_employee_number text,
    CONSTRAINT hr_changes_sequence_positive CHECK (sequence > 0)
);

COMMENT ON TABLE hr_changes IS
    'sequence is the order key. Equal occurred_at values are distinct changes.';

REVOKE ALL ON TABLE hr_people, hr_changes FROM PUBLIC;
REVOKE ALL ON TABLE hr_people, hr_changes FROM hr_reader;
GRANT SELECT ON TABLE hr_people, hr_changes TO hr_reader;
GRANT USAGE ON SCHEMA public TO hr_reader;
GRANT CONNECT ON DATABASE lab TO hr_reader;
