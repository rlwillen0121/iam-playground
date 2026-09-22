#!/bin/bash
# Runs only when the Postgres data directory is empty. Passwords come from
# the container environment and are not stored in this file.
set -euo pipefail

: "${POSTGRES_USER:?}"
: "${POSTGRES_DB:?}"
: "${TARGET_OWNER_PASSWORD:?}"
: "${VERIFIER_READER_PASSWORD:?}"
: "${ADMIN_OWNER_PASSWORD:?}"
: "${KEYCLOAK_DB_PASSWORD:?}"

sql_quote() {
  printf "'%s'" "$(printf '%s' "$1" | sed "s/'/''/g")"
}

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname "$POSTGRES_DB" <<SQL
CREATE ROLE target_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    PASSWORD $(sql_quote "$TARGET_OWNER_PASSWORD");
CREATE ROLE verifier_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    PASSWORD $(sql_quote "$VERIFIER_READER_PASSWORD");
CREATE ROLE admin_owner LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    PASSWORD $(sql_quote "$ADMIN_OWNER_PASSWORD");
CREATE ROLE keycloak LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION
    PASSWORD $(sql_quote "$KEYCLOAK_DB_PASSWORD");

CREATE DATABASE keycloak OWNER keycloak;
CREATE DATABASE lab;

REVOKE ALL ON DATABASE lab FROM PUBLIC;
REVOKE ALL ON DATABASE keycloak FROM PUBLIC;
REVOKE ALL ON DATABASE postgres FROM PUBLIC;
GRANT CONNECT ON DATABASE postgres TO postgres;
GRANT CONNECT ON DATABASE lab TO target_owner, verifier_reader, admin_owner;
GRANT CONNECT ON DATABASE keycloak TO keycloak;
SQL

psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname keycloak \
  -c "ALTER SCHEMA public OWNER TO keycloak;"
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname lab \
  -f /opt/lab/schema.sql

# After schema.sql, in this order. Skip a pack that is not mounted.
# Pack SQL must tolerate a second apply: no DROP of SCIM tables, no user reseed.
for pack in mcp.sql rest.sql hr.sql jdbc.sql; do
  pack_file="/opt/lab/packs/${pack}"
  if [ -f "$pack_file" ]; then
    psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname lab -f "$pack_file"
  fi
done

# Groups only, and only when lab_meta is empty. This file does not insert
# SCIM users. The entrypoint runs this script on an empty data directory,
# not when the container restarts.
psql -v ON_ERROR_STOP=1 --username "$POSTGRES_USER" --dbname lab \
  -f /opt/lab/seed.sql
