-- MCP and fault pack. Apply on database lab as the role that applied schema.sql,
-- after infra/postgres/schema.sql. infra/postgres/init.sh applies this file.
-- A second apply does not drop fault_counters, mutation_journal, or SCIM tables.
--
-- fault_counters holds the finite faults. Health checks and fault reads do not
-- decrement remaining; the MCP service does that only after a provisioning tool
-- is authenticated and authorized.
--
-- mutation_event(generation, app_id, actor, op, subject_id) is the allowlisted
-- journal projection. record_event() inserts the base mutation_journal row on
-- the caller's open transaction and does not commit.

CREATE TABLE IF NOT EXISTS fault_counters (
    name text PRIMARY KEY,
    remaining integer NOT NULL,
    rule text NOT NULL,
    CONSTRAINT fault_counters_remaining_chk CHECK (remaining >= 0),
    CONSTRAINT fault_counters_rule_chk CHECK (
        (name = '429' AND rule = 'finite-429')
        OR (name = '503' AND rule = 'finite-503')
        OR (name = 'commit_before_response' AND rule = 'commit-before-response')
    )
);

ALTER TABLE fault_counters OWNER TO admin_owner;

REVOKE ALL ON TABLE fault_counters FROM PUBLIC;
REVOKE ALL ON TABLE fault_counters FROM target_owner, verifier_reader;
GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE fault_counters TO admin_owner;

CREATE OR REPLACE VIEW mutation_event AS
SELECT generation, app_id, actor, op, subject_id
FROM mutation_journal;

COMMENT ON VIEW mutation_event IS
    'mutation_event(generation, app_id, actor, op, subject_id)';

COMMENT ON TABLE mutation_journal IS
    'mutation_event(generation, app_id, actor, op, subject_id)';

REVOKE ALL ON mutation_event FROM PUBLIC;
GRANT SELECT ON mutation_event TO verifier_reader, admin_owner;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON mutation_event FROM PUBLIC;
REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON mutation_event
    FROM target_owner, verifier_reader, admin_owner;
