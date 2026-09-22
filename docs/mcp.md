# MCP pack

Optional v0.2 HTTP JSON tools in front of the lab SCIM API. This is not an MCP SDK
session and it does not implement the 2026-07-28 MCP authorization flow. The process
entry is `iam_playground.mcp_pack.app:app`. The admin app mounts `create_app()`
under `/mcp`. `./lab` does not start a separate MCP process. Live calls
were not run.

The inbound bearer token is checked here and is not forwarded. Downstream SCIM calls
use `SCIM_TOKEN_APP_A` or `SCIM_TOKEN_APP_B`. The target base URL is `LAB_TARGET_URL`,
default `http://127.0.0.1:8090`. A request cannot choose that URL.

A field named `url`, `sql`, or `command` is rejected with HTTP 400 before the target
is called. The service has no shell, no Docker socket, and no file reads.

## Tools

All six are `POST` JSON bodies. Each call authenticates the bearer token, checks
server-side enablement, and authorizes the application, action, and entitlement.
Nothing is cached between calls.

| Tool | Path | Body fields | SCIM call |
| --- | --- | --- | --- |
| `lookup_account` | `/tools/lookup_account` | `app_id`, `user_name` | `GET Users` filtered by `userName eq` |
| `list_groups` | `/tools/list_groups` | `app_id` | `GET Groups` |
| `create_account` | `/tools/create_account` | `app_id`, `user_name`, `email`, `employee_number`, `department` | `POST Users` |
| `add_member` | `/tools/add_member` | `app_id`, `group_name`, `user_id` | `PATCH` group members add |
| `remove_member` | `/tools/remove_member` | `app_id`, `group_name`, `user_id` | `PATCH` group members remove |
| `disable_account` | `/tools/disable_account` | `app_id`, `user_id` | `PATCH` user `active` false |

Paths are under `/apps/{app_id}/scim/v2/`. `user_id` is a SCIM user id. Group
membership is chosen by `group_name`, not by a caller-supplied group URL.

## Allowlist

| Principal | Token | Applications | Actions | Entitlements |
| --- | --- | --- | --- | --- |
| `agent` | `MCP_AGENT_TOKEN` | `app-a` only | the six tools above | `Readers`, `Editors`, `Engineering`, `Sales` |
| `reference` | `MCP_REFERENCE_TOKEN` | `app-a` and `app-b` | the same six tools | any group, including `Administrators` |

`Administrators` is not on the agent list. Any other group name is denied for the
agent as well. An agent call that would grant `Administrators`, touch `app-b`, or
edit bindings returns 403 and does not call the target.

Bindings, reset, and fault tools are denied for both principals. `POST /tools/faults`,
`/bindings`, and `/reset` return 403 and do not call the target. The reference token
still cannot call those actions. Fault configuration is the separate route below, not
a tool.

`POST /principals/{name}/disable` requires `MCP_REFERENCE_TOKEN`. `name` is `agent`
or `reference`. The next tool call by that principal returns 403 even if the same
bearer token is still presented. This is workload authorization, not token revocation.
Enablement is process memory and is not in `fault_counters`. Restarting the process
enables the principal again. There is no enable route.

The two MCP tokens must be distinct. Health does not require a token: `GET /healthz`.

## Faults

Counters live in `fault_counters(name text primary key, remaining integer, rule text)`,
defined in `infra/postgres/packs/mcp.sql`. Set `MCP_FAULT_DSN` to a libpq or
SQLAlchemy Postgres URL that can write that table (`admin_owner`). The
`postgresql+psycopg://` scheme is accepted. If `MCP_FAULT_DSN` is unset, the same
`list_counters`, `put_counter`, and `consume` methods use process memory, which does
not survive restart. `infra/postgres/init.sh` applies `infra/postgres/packs/mcp.sql`
after `schema.sql`. A second apply does not drop the table. A missing table or a
failed store returns 503 and does not call the target.

Default is no active faults. `remaining` must be an integer from 0 through 1000.

| Name | Rule | When it matches | Effect |
| --- | --- | --- | --- |
| `429` | `finite-429` | any of the six tools | HTTP 429, target not called |
| `503` | `finite-503` | any of the six tools | HTTP 503, target not called |
| `commit_before_response` | `commit-before-response` | the four writes | HTTP 504 after a successful write, no resource body |

Writes are `create_account`, `add_member`, `remove_member`, and `disable_account`.
HTTP 429 and 503 include `Retry-After: 1`.

If more than one counter is above zero, the order is `429`, then `503`, then
`commit_before_response`. One call consumes one matching counter.

Authentication and authorization happen before a fault is applied. A 400 or 403 does
not decrement a counter and does not call the target. `GET /healthz` does not
decrement. `GET /faults` shows `name`, `remaining`, and `rule` for the three faults,
including zeros, and does not write. `POST /faults` replaces one counter and is
reference-token only; it does not decrement. Body:
`{"name": "429", "remaining": 2, "rule": "finite-429"}`.

`commit_before_response` decrements when the authorized write matches, including when
the target then rejects the write. The 504 timeout body is returned only after the
target accepts the write. The body does not include the created or updated resource.
Read the target again to see whether the write landed.

## Journal

`mutation_event(generation, app_id, actor, op, subject_id)` is the allowlisted
projection of `mutation_journal`. `record_event()` inserts that row on the caller's
connection. Arguments are `connection`, `generation`, `app_id`, `actor`, `op`, and
`subject_id`. It does not commit. Call it on the open SCIM transaction connection so
a rollback keeps both the account change and the event, and a commit keeps both.
Allowed `op` values are `create`, `replace`, `delete`, `member.add`, and
`member.remove`. The SCIM service is not wired to this helper. The agent has no HTTP
route and no database grant to write the journal.

A local session called lookup on app-a (200) and lookup on app-b with the agent token (403). Fault counters and the journal helper were not exercised in that session. The SCIM service does not call `record_event()` yet.
