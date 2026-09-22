from pathlib import Path

from iam_playground.constants import FIXTURE_ID
from iam_playground.reset_lab import TRUNCATE_SQL, ResetError, apply_reset

ROOT = Path(__file__).resolve().parents[1]


class _Result:
    def __init__(self, rowcount: int = 1) -> None:
        self.rowcount = rowcount

    def first(self):
        if self.rowcount != 1:
            return None
        return (1,)


class _Conn:
    def __init__(self) -> None:
        self.calls: list[tuple[str, object]] = []

    def execute(self, statement, params=None):
        self.calls.append((str(statement), params))
        return _Result()


class _Begin:
    def __init__(self, conn: _Conn) -> None:
        self.conn = conn

    def __enter__(self) -> _Conn:
        return self.conn

    def __exit__(self, exc_type, exc, tb) -> bool:
        return False


class _Engine:
    def __init__(self) -> None:
        self.conn = _Conn()
        self.begins = 0

    def begin(self) -> _Begin:
        self.begins += 1
        return _Begin(self.conn)


def test_compose_pins_loopback_and_hostname():
    compose = (ROOT / "infra" / "compose.yml").read_text(encoding="utf-8")
    dockerfile = (ROOT / "infra" / "Dockerfile.api").read_text(encoding="utf-8")
    workbench = (ROOT / "infra" / "Dockerfile.workbench").read_text(encoding="utf-8")
    assert "image: postgres:16.6" in compose
    assert "image: quay.io/keycloak/keycloak:26.0.7" in compose
    assert 'command: ["start", "--import-realm"]' in compose
    assert "KC_HOSTNAME: http://iam-playground.localhost:8080" in compose
    assert "OIDC_ISSUER: http://iam-playground.localhost:8080/realms/iam-playground" in compose
    assert "KC_HOSTNAME_STRICT" not in compose
    assert "start-dev" not in compose
    assert "host-gateway" not in compose
    assert "extra_hosts" not in compose
    assert "0.0.0.0:" not in compose
    postgres = compose.split("\n  postgres:\n", 1)[1].split("\n  keycloak:\n", 1)[0]
    keycloak = compose.split("\n  keycloak:\n", 1)[1].split("\n  target:\n", 1)[0]
    target = compose.split("\n  target:\n", 1)[1].split("\n  admin:\n", 1)[0]
    admin = compose.split("\n  admin:\n", 1)[1].split("\n  workbench:\n", 1)[0]
    assert "\n    networks:\n      - lab\n" in postgres
    assert "\n    networks:\n      - lab\n" in target
    assert "\n    networks:\n      - lab\n" in admin
    assert "networks:\n      lab:\n        aliases:\n          - iam-playground.localhost\n" in keycloak
    assert "\nnetworks:\n  lab:\n" in compose
    for mapping in (
        "127.0.0.1:5432:5432",
        "127.0.0.1:8080:8080",
        "127.0.0.1:8090:8090",
        "127.0.0.1:8091:8091",
        "127.0.0.1:8092:80",
    ):
        assert mapping in compose
    assert "python:3.12.8-slim" in dockerfile
    assert "node:22.14.0-alpine" in workbench
    assert "nginx:1.27.4-alpine" in workbench
    assert "iam_playground.targets.app:app" in compose
    assert "iam_playground.admin.app:app" in compose


def test_schema_boundaries():
    schema = (ROOT / "infra" / "postgres" / "schema.sql").read_text(encoding="utf-8")
    init = (ROOT / "infra" / "postgres" / "init.sh").read_text(encoding="utf-8")
    for name in (
        "lab_meta",
        "scim_users",
        "scim_groups",
        "scim_members",
        "mutation_journal",
        "account_bindings",
        "sessions",
        "login_transactions",
        "runs",
        "evidence",
    ):
        assert name in schema
    assert "lower(user_name)" in schema
    assert "ON DELETE CASCADE" in schema
    assert "GRANT SELECT ON lab_meta TO target_owner" in schema
    assert "GRANT SELECT ON scim_users, scim_groups, scim_members, mutation_journal TO verifier_reader" in schema
    assert "TO target_owner" in schema
    assert "GRANT INSERT, TRUNCATE ON scim_groups TO admin_owner" in schema
    assert "account_bindings FROM target_owner, verifier_reader" in schema
    assert "GRANT SELECT ON account_bindings TO target_owner" in schema
    assert "REVOKE INSERT, UPDATE, DELETE, TRUNCATE ON account_bindings FROM target_owner" in schema
    assert "ALTER TABLE sessions OWNER TO target_owner" in schema
    assert "ALTER TABLE login_transactions OWNER TO target_owner" in schema
    assert "GRANT TRUNCATE ON sessions, login_transactions TO admin_owner" in schema
    assert "access_token" not in schema
    assert "refresh_token" not in schema
    assert "synthetic-lab-" not in schema
    assert "synthetic-lab-" not in init
    for variable in (
        "TARGET_OWNER_PASSWORD",
        "VERIFIER_READER_PASSWORD",
        "ADMIN_OWNER_PASSWORD",
        "KEYCLOAK_DB_PASSWORD",
    ):
        assert variable in init
    assert "NOSUPERUSER" in init
    example = (ROOT / ".env.example").read_text(encoding="utf-8")
    script = (ROOT / "lab").read_text(encoding="utf-8")
    compose = (ROOT / "infra" / "compose.yml").read_text(encoding="utf-8")
    for key in (
        "SCIM_TOKEN_APP_A",
        "SCIM_TOKEN_APP_B",
        "SCIM_TOKEN_APP_A_READ",
        "SCIM_TOKEN_APP_B_READ",
    ):
        assert key in example
        assert key in script
        assert key in compose


def test_reset_rejects_other_fixtures_without_sql():
    engine = _Engine()
    try:
        apply_reset(engine, "other-fixture")
    except ResetError as exc:
        assert exc.detail == "fixture is not in this checkpoint"
    else:
        raise AssertionError("expected ResetError")
    assert engine.begins == 0


def test_reset_fences_truncates_and_reseeds_groups_only():
    engine = _Engine()
    apply_reset(engine, FIXTURE_ID)
    assert engine.begins == 2
    statements = [sql for sql, _params in engine.conn.calls]
    assert "accepting = false" in statements[0]
    assert "TRUNCATE" in statements[1]
    for table in (
        "account_bindings",
        "scim_members",
        "scim_users",
        "scim_groups",
        "mutation_journal",
        "runs",
        "evidence",
        "sessions",
        "login_transactions",
    ):
        assert table in TRUNCATE_SQL
    assert "keycloak" not in TRUNCATE_SQL.lower()
    _sql, params = engine.conn.calls[2]
    assert isinstance(params, list)
    assert len(params) == 24
    names = {row["display_name"] for row in params}
    apps = {row["app_id"] for row in params}
    assert names >= {"Readers", "Administrators"}
    assert apps == {"app-a", "app-b"}
    update_sql, update_params = engine.conn.calls[3]
    assert "generation = generation + 1" in update_sql
    assert "accepting = true" in update_sql
    assert update_params == {"fixture_id": FIXTURE_ID}
    joined = "\n".join(statements).lower()
    assert "drop database" not in joined
    assert "keycloak" not in joined
