"""Deterministic enterprise-small-v1 fixture.

Passwords live only in the fixture document. They are synthetic and obvious.
"""

from __future__ import annotations

import json
import uuid
from pathlib import Path

from iam_playground.constants import APPLICATIONS, FIXTURE_ID

# Fixed namespaces so reset recreates the same group ids and IdP user ids.
GROUP_NAMESPACE = uuid.UUID("8c9c0b2a-6d1e-4f3a-9b7c-1a2d3e4f5061")
IDP_NAMESPACE = uuid.UUID("1b2c3d4e-5f60-4781-9abc-def012345678")

DEPARTMENTS = (
    "Engineering",
    "Sales",
    "Support",
    "Finance",
    "People",
    "Operations",
)

# 50 synthetic people. Alice is first and is the flagship IdP account.
_PEOPLE = (
    ("alice", "Alice", "Adler"),
    ("bruno", "Bruno", "Bennett"),
    ("chloe", "Chloe", "Chen"),
    ("diego", "Diego", "Diaz"),
    ("elena", "Elena", "Ellis"),
    ("farid", "Farid", "Farouk"),
    ("gina", "Gina", "Garcia"),
    ("hiro", "Hiro", "Hayashi"),
    ("ines", "Ines", "Ibarra"),
    ("jules", "Jules", "Jensen"),
    ("kira", "Kira", "Khan"),
    ("leo", "Leo", "Larsen"),
    ("mina", "Mina", "Moreau"),
    ("nico", "Nico", "Novak"),
    ("olga", "Olga", "Olsen"),
    ("priya", "Priya", "Patel"),
    ("quinn", "Quinn", "Quintero"),
    ("rosa", "Rosa", "Rossi"),
    ("samir", "Samir", "Santos"),
    ("tara", "Tara", "Tanaka"),
    ("umar", "Umar", "Ueda"),
    ("vera", "Vera", "Vogel"),
    ("wade", "Wade", "Walsh"),
    ("xia", "Xia", "Xu"),
    ("yara", "Yara", "Yilmaz"),
    ("zane", "Zane", "Zimmer"),
    ("aaron", "Aaron", "Abbott"),
    ("bianca", "Bianca", "Berg"),
    ("colin", "Colin", "Costa"),
    ("daria", "Daria", "Dubois"),
    ("ethan", "Ethan", "Evans"),
    ("fatima", "Fatima", "Fernandes"),
    ("gustav", "Gustav", "Greco"),
    ("hana", "Hana", "Horvat"),
    ("ivan", "Ivan", "Ivanov"),
    ("julia", "Julia", "Johansson"),
    ("kenji", "Kenji", "Kobayashi"),
    ("lina", "Lina", "Lind"),
    ("marco", "Marco", "Martin"),
    ("nadia", "Nadia", "Nielsen"),
    ("oscar", "Oscar", "Ortega"),
    ("paula", "Paula", "Petrov"),
    ("rafael", "Rafael", "Reyes"),
    ("sofia", "Sofia", "Silva"),
    ("tomas", "Tomas", "Torres"),
    ("ursula", "Ursula", "Urban"),
    ("victor", "Victor", "Varga"),
    ("willa", "Willa", "Weber"),
    ("xavier", "Xavier", "Xiong"),
    ("yasmin", "Yasmin", "Young"),
)

ENTITLEMENTS = (
    ("Readers", "Read application records"),
    ("Administrators", "Administer application records"),
    ("Editors", "Edit application records"),
    ("Auditors", "Review audit records"),
    ("Engineering", "Engineering entitlement"),
    ("Sales", "Sales entitlement"),
    ("Support", "Support entitlement"),
    ("Finance", "Finance entitlement"),
    ("Contractors", "Contractor entitlement"),
    ("Operators", "Operator entitlement"),
    ("Viewers", "View application records"),
    ("Billing", "Billing entitlement"),
)


def default_fixture_path() -> Path:
    return Path(__file__).resolve().parents[2] / "fixtures" / f"{FIXTURE_ID}.json"


def group_uuid(app_id: str, display_name: str) -> uuid.UUID:
    return uuid.uuid5(GROUP_NAMESPACE, f"{FIXTURE_ID}:{app_id}:{display_name}")


def idp_user_uuid(user_name: str) -> uuid.UUID:
    return uuid.uuid5(IDP_NAMESPACE, f"{FIXTURE_ID}:idp:{user_name}")


def build_fixture() -> dict:
    people = []
    for index, (user_name, given_name, family_name) in enumerate(_PEOPLE):
        people.append(
            {
                "userName": user_name,
                "givenName": given_name,
                "familyName": family_name,
                "email": f"{user_name}@lab.example",
                "employeeNumber": f"E{1001 + index}",
                "department": DEPARTMENTS[index % len(DEPARTMENTS)],
                "password": f"synthetic-lab-{user_name}",
                "idpAccount": True,
                "scimUser": None,
            }
        )
    fixture = {
        "fixtureId": FIXTURE_ID,
        "applications": list(APPLICATIONS),
        "entitlements": [
            {"name": name, "description": description} for name, description in ENTITLEMENTS
        ],
        "people": people,
    }
    validate_fixture(fixture)
    return fixture


def validate_fixture(fixture: dict) -> None:
    if fixture.get("fixtureId") != FIXTURE_ID:
        raise ValueError("fixture id")
    if fixture.get("applications") != list(APPLICATIONS):
        raise ValueError("applications")
    entitlements = fixture.get("entitlements")
    if not isinstance(entitlements, list) or len(entitlements) != 12:
        raise ValueError("entitlements")
    names = [item.get("name") for item in entitlements]
    if "Readers" not in names or "Administrators" not in names:
        raise ValueError("entitlements")
    if names[0] != "Readers" or names[1] != "Administrators":
        raise ValueError("entitlements")
    people = fixture.get("people")
    if not isinstance(people, list) or len(people) != 50:
        raise ValueError("people")
    seen: set[str] = set()
    for index, person in enumerate(people):
        user_name = person.get("userName")
        if not isinstance(user_name, str) or not user_name or user_name in seen:
            raise ValueError("userName")
        seen.add(user_name)
        if person.get("email") != f"{user_name}@lab.example":
            raise ValueError("email")
        if person.get("employeeNumber") != f"E{1001 + index}":
            raise ValueError("employeeNumber")
        password = person.get("password")
        if not isinstance(password, str) or not password.startswith("synthetic-lab-"):
            raise ValueError("password prefix")
        if person.get("idpAccount") is not True or person.get("scimUser") is not None:
            raise ValueError("account flags")
        if "://" in json.dumps(person):
            raise ValueError("url")
    alice = people[0]
    if (
        alice["userName"] != "alice"
        or alice["email"] != "alice@lab.example"
        or alice["employeeNumber"] != "E1001"
        or alice["department"] != "Engineering"
    ):
        raise ValueError("alice")


def load_fixture(path: Path | None = None) -> dict:
    fixture_path = path or default_fixture_path()
    with fixture_path.open(encoding="utf-8") as handle:
        fixture = json.load(handle)
    validate_fixture(fixture)
    return fixture


def group_rows(fixture: dict | None = None) -> list[dict[str, str]]:
    document = fixture or load_fixture()
    rows: list[dict[str, str]] = []
    for app_id in document["applications"]:
        for entitlement in document["entitlements"]:
            display_name = entitlement["name"]
            rows.append(
                {
                    "id": str(group_uuid(app_id, display_name)),
                    "app_id": app_id,
                    "display_name": display_name,
                }
            )
    return rows
