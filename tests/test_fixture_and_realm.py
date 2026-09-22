import json
from pathlib import Path

from iam_playground.constants import FIXTURE_ID
from iam_playground.fixture import build_fixture, default_fixture_path, group_rows, load_fixture
from iam_playground.realm import build_realm
from iam_playground.seed_sql import render_seed_sql

ROOT = Path(__file__).resolve().parents[1]


def test_committed_fixture_matches_generator():
    fixture = build_fixture()
    on_disk = json.loads(default_fixture_path().read_text(encoding="utf-8"))
    assert on_disk == fixture
    load_fixture()


def test_alice_and_shape():
    fixture = build_fixture()
    assert fixture["fixtureId"] == FIXTURE_ID
    assert fixture["applications"] == ["app-a", "app-b"]
    people = fixture["people"]
    assert len(people) == 50
    alice = people[0]
    assert alice["userName"] == "alice"
    assert alice["email"] == "alice@lab.example"
    assert alice["employeeNumber"] == "E1001"
    assert alice["department"] == "Engineering"
    assert alice["password"] == "synthetic-lab-alice"
    assert alice["idpAccount"] is True
    assert alice["scimUser"] is None
    assert all(person["scimUser"] is None for person in people)
    assert all(person["idpAccount"] is True for person in people)
    assert all(person["password"].startswith("synthetic-lab-") for person in people)
    names = [item["name"] for item in fixture["entitlements"]]
    assert len(names) == 12
    assert "Readers" in names
    assert "Administrators" in names
    assert "http://" not in json.dumps(fixture)
    assert "https://" not in json.dumps(fixture)


def test_groups_are_empty_seed_rows_for_both_apps():
    rows = group_rows(build_fixture())
    assert len(rows) == 24
    apps = {row["app_id"] for row in rows}
    names = {row["display_name"] for row in rows}
    assert apps == {"app-a", "app-b"}
    assert "Readers" in names
    assert "Administrators" in names


def test_seed_sql_matches_fixture_and_has_no_passwords():
    sql = render_seed_sql(load_fixture())
    assert sql == (ROOT / "infra" / "postgres" / "seed.sql").read_text(encoding="utf-8")
    assert "synthetic-lab-" not in sql
    assert "INSERT INTO scim_users" not in sql
    assert "INSERT INTO scim_members" not in sql
    assert "WHERE NOT EXISTS (SELECT 1 FROM lab_meta)" in sql
    assert "app-a" in sql and "app-b" in sql
    assert "Readers" in sql and "Administrators" in sql


def test_committed_realm_has_users_and_no_secrets():
    fixture = load_fixture()
    expected = build_realm(fixture, include_credentials=False)
    realm_path = ROOT / "infra" / "keycloak" / "iam-playground-realm.json"
    on_disk = json.loads(realm_path.read_text(encoding="utf-8"))
    assert on_disk == expected
    text = realm_path.read_text(encoding="utf-8")
    assert "synthetic-lab-" not in text
    assert "credentials" not in text
    assert "secret" not in text


def test_runtime_realm_copies_fixture_passwords_and_client_policy():
    fixture = load_fixture()
    realm = build_realm(fixture, include_credentials=True)
    assert realm["realm"] == "iam-playground"
    assert realm["sslRequired"] == "none"
    users = {user["username"]: user for user in realm["users"]}
    assert len(users) == 50
    for person in fixture["people"]:
        user = users[person["userName"]]
        assert user["enabled"] is True
        assert user["email"] == person["email"]
        assert user["credentials"] == [
            {"type": "password", "value": person["password"], "temporary": False}
        ]
    assert len(realm["clients"]) == 1
    client = realm["clients"][0]
    assert client["clientId"] == "demo-app"
    assert client["publicClient"] is True
    assert client["standardFlowEnabled"] is True
    assert client["implicitFlowEnabled"] is False
    assert client["directAccessGrantsEnabled"] is False
    assert client["serviceAccountsEnabled"] is False
    assert client["redirectUris"] == ["http://127.0.0.1:8090/session/callback"]
    assert client["webOrigins"] == ["http://127.0.0.1:8092"]
    assert client["attributes"]["pkce.code.challenge.method"] == "S256"
    assert "secret" not in client
