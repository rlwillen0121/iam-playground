# Architecture

These are requirements, not a description of running code. No component below is implemented in this repository.

## Components

| Component | Release |
| --- | --- |
| Synthetic HR fixture | v0.1 |
| SCIM application | v0.1 |
| Keycloak | v0.1 |
| Demo application | v0.1 |
| CLI and minimal workbench | v0.1 |
| Verifier | v0.1 |
| Optional MCP and agent pack | v0.2 |
| Proprietary REST application | v0.3 |
| HR REST, CSV, and SQL feeds | v0.3 |
| OpenLDAP | v0.4 |
| Legacy SQL application and Java JDBC client | v0.4 |

Release labels are scope, not completion. v1.0 is the consolidated lab after those packs, and it is not started.

## Account state

SCIM, later REST, LDAP, and JDBC own separate account state. They are not interchangeable projections of one identity table. Sharing a database server does not permit cross-target account updates.

The demo application shares the SCIM application's account store. It is that application's user-facing surface, not another provisioning target.

## Trust

| Principal or process | Allowed authority | Excluded authority |
| --- | --- | --- |
| Lab administrator | Prepare and reset runs, register targets, configure faults and trusted bindings | Not the identity used by normal demonstrations |
| Reference or external client | Documented source reads and target operations | Reset, hidden fixture changes, verifier verdict writes |
| Agent principal | Explicit target, operation, and entitlement allowlists | Administrator endpoints, arbitrary URLs, SQL, shell, and policy edits |
| Verifier | Read target state and execute controlled authorization probes | Provision accounts, grant memberships, or repair failures |
| Demo user | Sign in and use permitted application actions | Change account bindings or provisioning permissions |

The identity subject and the authenticated caller are separate. The employee whose account changes is not automatically the actor. Trusted account binding is an issuer and subject pair attached by preparation or an administrator, not an email match.

Separate credentials enforce these boundaries. The verifier may write its own reports, not target account state.
