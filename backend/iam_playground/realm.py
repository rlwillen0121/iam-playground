"""Keycloak realm document derived from the fixture.

The committed realm file omits credentials. `./lab up` writes a private import
that copies fixture passwords, because Keycloak imports users on first boot.
Token signature, issuer, and audience checks are not disabled here.
"""

from __future__ import annotations

import uuid

from iam_playground.constants import FIXTURE_ID
from iam_playground.fixture import idp_user_uuid

CLIENT_NAMESPACE = uuid.UUID("c0ffee00-0000-4000-8000-000000000001")


def build_realm(fixture: dict, *, include_credentials: bool) -> dict:
    users = []
    for person in fixture["people"]:
        user = {
            "id": str(idp_user_uuid(person["userName"])),
            "username": person["userName"],
            "enabled": True,
            "email": person["email"],
            "emailVerified": True,
            "firstName": person["givenName"],
            "lastName": person["familyName"],
        }
        if include_credentials:
            user["credentials"] = [
                {
                    "type": "password",
                    "value": person["password"],
                    "temporary": False,
                }
            ]
        users.append(user)
    client_id = str(uuid.uuid5(CLIENT_NAMESPACE, f"{FIXTURE_ID}:client:demo-app"))
    return {
        "realm": "iam-playground",
        "enabled": True,
        "displayName": "IAM Playground",
        "sslRequired": "none",
        "registrationAllowed": False,
        "loginWithEmailAllowed": False,
        "duplicateEmailsAllowed": False,
        "resetPasswordAllowed": False,
        "editUsernameAllowed": False,
        "users": users,
        "clients": [
            {
                "id": client_id,
                "clientId": "demo-app",
                "enabled": True,
                "protocol": "openid-connect",
                "publicClient": True,
                "standardFlowEnabled": True,
                "implicitFlowEnabled": False,
                "directAccessGrantsEnabled": False,
                "serviceAccountsEnabled": False,
                "redirectUris": ["http://127.0.0.1:8090/session/callback"],
                "webOrigins": ["http://127.0.0.1:8092"],
                "attributes": {"pkce.code.challenge.method": "S256"},
            }
        ],
    }
