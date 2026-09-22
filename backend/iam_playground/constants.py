"""Shared lab constants. Issuer and loopback URLs must stay aligned."""

FIXTURE_ID = "enterprise-small-v1"
EXPECTED_ISSUER = "http://iam-playground.localhost:8080/realms/iam-playground"
DISCOVERY_URL = EXPECTED_ISSUER + "/.well-known/openid-configuration"
APPLICATIONS = ("app-a", "app-b")
DEMO_APP_ID = "app-a"
DEMO_CLIENT_ID = "demo-app"
DEMO_REDIRECT_URI = "http://127.0.0.1:8090/session/callback"
SESSION_COOKIE = "lab_session"
COOKIE_POLICY_HEADER = "X-Lab-Cookie-Policy"
COOKIE_POLICY_VALUE = "local-http-not-secure"

LOOPBACK_ENDPOINTS = {
    "postgres": "127.0.0.1:5432",
    "keycloak": "http://127.0.0.1:8080",
    "target": "http://127.0.0.1:8090",
    "admin": "http://127.0.0.1:8091",
    "workbench": "http://127.0.0.1:8092",
    "issuer": EXPECTED_ISSUER,
}
