# IAM Playground

A self-hosted lab for testing identity integrations and bounded agents against realistic applications, with failures and independently verified access outcomes.

## Demonstration

None recorded. The flagship journey (provision, sign in, revoke, prove the next protected request is denied) is the v0.1 exit proof and has not been run.

## Quickstart

`./lab doctor` exits 2 until that slice exists. Docker Compose is not a quickstart here: no compose file is shipped, and this repository does not start services.

## Supported scope

Nothing shipped. Planned is not implemented or verified.

| Release | Scope | Status |
| --- | --- | --- |
| v0.1 | SCIM, Keycloak, demo application, fixtures, CLI, minimal workbench, verifier | planned |
| v0.2 | Optional bounded MCP and agent pack, selected faults | planned |
| v0.3 | REST profiles, durable async operations, HR feeds, lifecycle cases | planned |
| v0.4 | OpenLDAP and native Java JDBC | planned |
| v1.0 | Consolidated lab, complete matrix, selected compatibility recipes | planned |

## Docs

- [docs/spec.md](docs/spec.md)
- [docs/architecture.md](docs/architecture.md)
- [docs/capabilities.md](docs/capabilities.md)
- [AGENTS.md](AGENTS.md)
- [SECURITY.md](SECURITY.md)
- [CONTRIBUTING.md](CONTRIBUTING.md)

The lab must run without a paid IAM tenant or a model API key. No dependency or image version has been tested yet, so none are pinned.
