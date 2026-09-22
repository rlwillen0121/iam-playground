# Contributing

Follow [AGENTS.md](AGENTS.md).

Orchestrate plans. Implement edits. Review runs before a publication claim and when auth, verifier, target protocol, or compose files change.

## Checks

Host unit tests, from the repository root, with the virtualenv that has `requirements.txt` installed:

```bash
.venv/bin/pytest -q
```

`tests/lab_stub_test.sh` checks the CLI without starting Compose.

With Docker:

```bash
./lab up
./lab doctor
./lab test smoke
```

`./lab doctor` exits 0 only when Postgres answers a query, Keycloak discovery returns the lab issuer, and the target, admin, and workbench HTTP checks succeed.

Record a capability as exercised only after the command or test that showed it. `docs/capabilities.md` keeps the flagship journey at `not run` until that browser journey is recorded. `./lab jdbc verify` does not open a database.
