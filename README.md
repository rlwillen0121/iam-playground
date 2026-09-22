# IAM Playground

A self-hosted lab for testing identity integrations and bounded agents against realistic applications, with failures and independently verified access outcomes.

The lab runs on your machine. It does not need a paid IAM tenant or a model API key. Published ports bind to `127.0.0.1`.

## Status

A local Docker session on 2026-09-22 started the stack and `./lab doctor` reported Postgres, Keycloak, the target API, the admin API, and the workbench ready. OpenLDAP became healthy and the directory contained `ou=People`, `ou=Groups`, `ou=ServiceAccounts`, and `ou=System`. Host `pytest` reported 59 passed.

Spot checks in that same session:

- SCIM list on app-a returned an empty page. An app-a token was rejected on app-b.
- Modern REST account create returned 201, and the following list returned that account.
- Legacy REST create returned 202, and the operation later read as `succeeded`.
- An MCP lookup on app-a returned 200. The same call on app-b returned 403.
- The ten in-memory evaluation tasks ran. Nine returned `PASSED`. `verification-unavailable` returned `INDETERMINATE`.

The flagship browser journey (provision, sign in, revoke, prove the next protected request is denied) has not been run. The JDBC client has not been connected to a database. That session was one macOS machine with Docker Compose v5.1.3. It is not a support matrix for other platforms.

## Quickstart

Prerequisites: Docker with Compose, OpenSSL, and Python 3.12. `./lab` uses `.venv/bin/python` when that file is executable, and otherwise `python3`. The host checks need the packages in `requirements.txt` (`psycopg` is one of them).

```bash
python3.12 -m venv .venv
.venv/bin/pip install -r requirements.txt
./lab up
./lab doctor
./lab endpoints
```

`./lab up` writes `.env` on first run and fills any missing generated secrets later. It does not print those values. `.env` is gitignored.

| Port | Service |
| --- | --- |
| 127.0.0.1:5432 | Postgres |
| 127.0.0.1:8080 | Keycloak. Issuer `http://iam-playground.localhost:8080/realms/iam-playground` |
| 127.0.0.1:8090 | Target API: SCIM, demo sign-in, HR, REST |
| 127.0.0.1:8091 | Admin API: reset, bindings, `/meta`, `/activity`, scenarios, MCP under `/mcp` |
| 127.0.0.1:8092 | Workbench |
| 127.0.0.1:389 and :636 | OpenLDAP |

`./lab down` stops containers and keeps the database volume. `./lab down --destroy-data` deletes volumes. A volume created before a schema change does not replay `infra/postgres/init.sh`. A new data directory applies `schema.sql` and then `infra/postgres/packs/`.

## Commands

| Command | What it does |
| --- | --- |
| `./lab doctor` | Checks Postgres, Keycloak discovery, target and admin `/healthz`, and the workbench. An open port alone is not ready. |
| `./lab test smoke` | Checks target and admin readiness. The output says ready or not ready. |
| `./lab scenario list` | Lists `scim-login-revoke` and the files in `scenarios/`. `transaction-rollback` is unavailable until the JDBC path is exercised. |
| `./lab scenario run scim-login-revoke --mode reference` | Runs the reference driver and the verifier. Exit 0 is `PASSED`, 1 is `FAILED`, 2 is `INDETERMINATE`. |
| `./lab scenario verify <run-id>` | Reads the stored report. It does not probe again. |
| `./lab export <run-id> --format json` | Prints the redacted report. |
| `./lab reset --fixture enterprise-small-v1` | Reseeds groups and clears SCIM users. It does not delete the Keycloak realm. |
| `./lab jdbc verify` | Reports that `clients/jdbc` is present. It does not open a database. |

## What is in the tree

`implemented` means the code is in this repository. The status column says what the local session actually exercised.

| Capability | Status |
| --- | --- |
| SCIM subset and two-app token separation | implemented; list and cross-app rejection exercised |
| Trusted issuer/subject binding | implemented; not exercised end to end |
| Demo read, write, and admin checks | implemented |
| Verifier verdicts | implemented |
| MCP tools, allowlist, and faults | implemented; lookup and app-b denial exercised |
| Ten evaluation tasks | implemented; in-memory run exercised |
| Modern and legacy REST | implemented; create, list, and one legacy operation exercised |
| HR feeds and lifecycle scenario files | implemented; `GET /hr/people` exercised |
| OpenLDAP directory | implemented; container healthy and base entries present. Image bootstrap does not apply `infra/ldap/slapd/acl.conf` or `overlays.conf` |
| JDBC client | implemented; not connected |
| Five-view workbench | implemented; HTTP 200 exercised |
| Flagship journey | not run |

## Docs

- [docs/spec.md](docs/spec.md) is the product design.
- [docs/architecture.md](docs/architecture.md)
- [docs/capabilities.md](docs/capabilities.md)
- [docs/versions.md](docs/versions.md)
- [docs/mcp.md](docs/mcp.md), [docs/rest.md](docs/rest.md), [docs/lifecycle.md](docs/lifecycle.md), [docs/ldap.md](docs/ldap.md), [docs/evals.md](docs/evals.md)
- [clients/jdbc/README.md](clients/jdbc/README.md)
- [SECURITY.md](SECURITY.md), [CONTRIBUTING.md](CONTRIBUTING.md), [AGENTS.md](AGENTS.md)
