# Proprietary REST

Two applications, `rest-modern` and `rest-legacy`, each with its own account rows. They do not use `scim_users` or the SCIM routes. A credential for one profile does not authorize the other. The same numeric account id in one application is not the other application's account.

`iam_playground.targets.app` includes these routes by calling `create_router()` once:

```python
from iam_playground.rest import create_router

app.include_router(create_router())
```

Call `create_router()` once. The fault counters and stale-read images belong to that router. `store_factory`, when replaced, must hand back a store that sees the same rows on later calls. The default store uses `DATABASE_URL`.

This document is the HTTP contract. A local session created one modern account and watched one legacy operation reach `succeeded`. The rest of this contract was not walked call by call.

`infra/postgres/init.sh` applies `infra/postgres/packs/rest.sql` when that file is present. A second apply does not reset id counters or delete seeded roles. The Compose target service is not given the REST credential variables. The route code reads the process environment on each request.

## Account

| Field | Meaning |
| --- | --- |
| `id` | Server integer. Per application, starting at 1. Clients cannot choose it. |
| `login` | Unique inside the application, compared case-insensitively. ASCII, no whitespace, 1–200 characters. |
| `employeeRef` | Caller-supplied reference. Not unique. 1–200 characters, no leading or trailing space. |
| `status` | `enabled` or `disabled`. |
| `profile.firstName`, `profile.lastName`, `profile.department` | Required on create. Same string rules as `employeeRef`. |
| `roles` | Sorted role names currently assigned. Not accepted in a create or patch body. |

Unknown JSON fields are rejected. `status` omitted on create means `enabled`.

Seeded roles, per application, are `admin`, `operator`, and `reader`. There is no role-create route. Assignment of any other name is `404`.

## Credentials

| Profile | Write | Read-only | How it is sent |
| --- | --- | --- | --- |
| Modern | `REST_MODERN_TOKEN` | `REST_MODERN_READ` | `Authorization: Bearer` |
| Legacy | `REST_LEGACY_KEY` | `REST_LEGACY_READ` | `X-Api-Key` |

A write credential may read. A read credential receives `403` with `{"error": "read credential cannot modify"}` and does not change rows. A missing or wrong credential receives `401` and does not change rows. Empty environment values never match. The read value must be different from the write value; if they are equal, that value is the write credential.

The client id stored on a legacy operation is `rest-legacy` for the write key. The read key's client id is `rest-legacy-read`. It does not create operations.

Modern `401` responses include `WWW-Authenticate: Bearer`. Legacy does not.

## Shared behavior

Responses send `Cache-Control: no-store`. Error bodies are `{"error": "..."}` and do not include credentials or SQL text. A database failure is `503` with `{"error": "dependency"}`. That is not the `503` fault.

While `lab_meta.accepting` is false, live reads and new writes return `409` `lab is not accepting`. Account ids and logins are scoped by `app_id`. Integer ids above 2147483647 are rejected.

Lists are ordered by `id` ascending. There is no filter parameter.

| Query | Modern list | Legacy list |
| --- | --- | --- |
| `cursor`, `limit` | Used | `400` |
| `page`, `pageSize` | `400` | Used |

`limit` and `pageSize` default to 50 and must be from 1 to 100. `page` defaults to 1, is 1-based, and must be from 1 to 10000. A page past the end returns an empty `accounts` array and the real `total`. A cursor past the end returns an empty array and `nextCursor: null`. Repeated or unknown list parameters are `400`.

The modern cursor is opaque. Clients pass `nextCursor` back as `cursor` and do not parse it. An altered cursor is `400`.

Modern list:

```json
{"accounts": [], "nextCursor": null}
```

Legacy list:

```json
{"accounts": [], "page": 1, "pageSize": 50, "total": 0}
```

`GET /rest/modern/roles` and `GET /rest/legacy/roles` return `{"roles": ["admin", "operator", "reader"]}`.

## Modern profile

Bearer token. Cursor pagination. Writes are synchronous and commit before the success response is built.

| Method and path | Success |
| --- | --- |
| `POST /rest/modern/accounts` | `201` account, `Location: /rest/modern/accounts/{id}` |
| `GET /rest/modern/accounts` | `200` cursor page |
| `GET /rest/modern/accounts/{id}` | `200` account |
| `PATCH /rest/modern/accounts/{id}` | `200` account |
| `DELETE /rest/modern/accounts/{id}` | `204` |
| `POST /rest/modern/accounts/{id}/enable` | `200` account, status `enabled` |
| `POST /rest/modern/accounts/{id}/disable` | `200` account, status `disabled` |
| `GET /rest/modern/roles` | `200` role names |
| `POST /rest/modern/accounts/{id}/roles/{role}` | `200` account. Repeating the assignment is still `200`. |
| `DELETE /rest/modern/accounts/{id}/roles/{role}` | `204`. Missing assignment is `404`. |

Enable and disable have no request body. Patch sends any non-empty subset of `login`, `employeeRef`, `status`, and `profile`. A duplicate login is `409` `login is already in use`. A missing account is `404`.

Modern does not read `Idempotency-Key`. A timed-out create is reconciled by listing accounts and finding `login`. A second create with that login is `409` and does not insert another row. A timed-out delete is reconciled by getting the account: `404` means it is gone.

## Legacy profile

`X-Api-Key`. Page pagination. Account writes return `202` and an operation id. Acceptance is not fulfillment. Reads, role listing, operation polling, and cancel are synchronous.

| Method and path | Success |
| --- | --- |
| `POST /rest/legacy/accounts` | `202` operation |
| `PATCH /rest/legacy/accounts/{id}` | `202` operation |
| `DELETE /rest/legacy/accounts/{id}` | `202` operation |
| `POST /rest/legacy/accounts/{id}/enable` and `/disable` | `202` operation |
| `POST` and `DELETE /rest/legacy/accounts/{id}/roles/{role}` | `202` operation |
| `GET /rest/legacy/accounts` and `GET /rest/legacy/accounts/{id}` | Same shapes as modern, with page fields on the list |
| `GET /rest/legacy/roles` | `200` |
| `GET /rest/legacy/operations/{id}` | `200` operation |
| `POST /rest/legacy/operations/{id}/cancel` | `200` when cancelled. Does not use `Idempotency-Key`. |

Every legacy account write requires `Idempotency-Key` (1–255 characters, no leading or trailing whitespace, no control characters). The key is scoped to the write client and `rest-legacy`.

The operation body is:

```json
{
  "id": "uuid",
  "state": "accepted",
  "operation": "create-account",
  "accountId": null,
  "role": null,
  "clientId": "rest-legacy",
  "error": null
}
```

`operation` is one of `create-account`, `patch-account`, `delete-account`, `enable-account`, `disable-account`, `assign-role`, `remove-role`.

`accountId` on an accepted create is null. The id is reserved when execution starts and is visible on a later get. A failed create may still show a reserved `accountId` with no account row. Fulfillment is `state: succeeded` plus the account row, not the presence of `accountId`.

### Acceptance and the worker

`accept_operation` inserts the operation row and commits that transaction before the handler builds the `202` response. The first `202` body is that accepted row, even if the inline worker finishes before the bytes are sent.

The inline worker then runs, unless an outcome fault says otherwise. A following `GET /rest/legacy/operations/{id}` therefore usually sees a terminal state. `GET` does not run the worker. A read credential cannot apply writes.

A later legacy account write also calls `resume`, which finishes leftover `accepted` and `running` operations for `rest-legacy`. Cancel does not resume other operations. After a process restart, an integrator can call `iam_playground.rest.service.resume` so accepted work is not stuck waiting for the next write.

Unknown accounts and roles are rejected before acceptance (`404`). A duplicate login on create or patch is `409` before acceptance when it is already visible. A conflict that appears only at execution marks the operation `failed` and does not leave the new row.

### Idempotency

The same client, application, key, and canonical payload return the same operation. The canonical payload is the kind, path account id, role name, and normalized body. Key order and insignificant whitespace do not matter. A create that omits `status` matches one that sends `enabled`.

A retry of an operation that is still `accepted` or `running` resumes that operation. It does not insert a second account. The retry's `202` body is the current row, which may already be terminal.

The same key with a different payload is `409` `idempotency key was reused with a different payload`. The original operation is unchanged.

### States

| State | Meaning |
| --- | --- |
| `accepted` | Row committed. The account change is not done. |
| `running` | A worker has claimed it. Still not fulfillment. |
| `succeeded` | The account change is committed. `error` is null. |
| `failed` | The account change from this operation is not committed. `error` says why. |
| `cancelled` | Claimed or accepted work was cancelled before it finished. |

Cancel sets `cancelled` only when the row is still `accepted` or `running`. It does not delete or restore account rows.

| Current state | Cancel result |
| --- | --- |
| `accepted` or `running` | `200`, state `cancelled`. No account rollback. |
| `cancelled` | `200`, still `cancelled`. |
| `succeeded` | `409` `succeeded operation was not rolled back`. State stays `succeeded`. The account change remains. |
| `failed` | `409` `operation is already finished`. State stays `failed`. |

The `409` body includes the operation object.

Execution will not apply an operation whose stored `generation` differs from `lab_meta`. If the mutation was not applied, the operation becomes `failed` with `stale generation`. If it was already applied, the row is marked `succeeded` and the account is left as it is. While the lab is not accepting, execution does not change the operation or the accounts. Reset is not wired to these tables. Truncating them without reseeding `rest_roles` and `rest_id_alloc` breaks later assignment and id allocation. A reset must also keep an old worker from applying accepted work to the new generation; the generation check is the fence this pack provides.

## Crash windows

`iam_playground.rest.recovery` defines `before_commit`, `after_acceptance`, `after_mutation`, and `before_response`. Each takes an `Operation` and returns the row image a restart should see. They do not touch the database. None of the windows is exactly-once by itself.

| Function | Operation row | Account mutation |
| --- | --- | --- |
| `before_commit` | Absent. The idempotency key was not recorded. A retry may start a new operation. | Absent. |
| `after_acceptance` | Present, `accepted`. Resume this id. Do not open a second operation for the same key and payload. | Absent. |
| `after_mutation` | Present, `running`. | Present. Do not apply it again. |
| `before_response` | Present, in the state that was committed (`op.state`). | Present when that state is `succeeded`, or when a `running` or `cancelled` row has `applied`. A `failed` or `accepted` row does not show the mutation. Cancel does not erase a mutation that already committed. |

The handler commits a create's reserved id before inserting the account, and commits the account change in the same transaction as `applied` and `succeeded`. A crash after that commit is `before_response`, not a second account. A crash after the id is reserved and before that transaction leaves `running`, the reserved id, and no account; resume inserts that id. This process does not commit the account while leaving the operation `running`, which is the `after_mutation` image. Resume still treats an account that already has the reserved id as already created.

A response that never reached the client is reconciled with the idempotency key, not with a new create.

## Faults

Fault names are data on the in-memory rule list in `iam_playground.rest.faults`:

| Name | When it applies | What the client sees |
| --- | --- | --- |
| `429` | Any authenticated operation the rule names | `429` `{"error": "rate limit"}`, `Retry-After: 1` |
| `503` | Any authenticated operation the rule names | `503` `{"error": "unavailable"}` |
| `stale-read` | `list-accounts`, `get-account` | `200` with the previous account image, or `404` if that account was not in it. One committed write behind. |
| `async-failure` | Legacy account writes only | Operation row becomes `failed` with `error` `async-failure`. No account change from that operation. The first `202` body is still the accepted row. |
| `malformed-list` | `list-accounts` | `200` with a broken envelope. Records are not returned inside a valid list. |
| `commit-timeout` | Account writes on either profile, only after that write commits | `504` `{"error": "commit timeout"}`. The committed rows remain. |

Every applied fault sets `X-Lab-Fault` to that name. `429` and `503` are matched before the write, so they do not create an operation or an account. `commit-timeout` and `async-failure` are matched only for a newly accepted legacy operation, or after a modern write has committed. A replay of an existing idempotency key does not take those two faults again and does not create another account.

`malformed-list` for modern is exactly `{"accounts": {"unexpected": true}}`. For legacy it is exactly `{"accounts": {"unexpected": true}, "page": <requested page>}`. `nextCursor`, `pageSize`, and `total` are absent. The status is `200`, so a client must notice the broken envelope.

`stale-read` uses a process-local image captured before the latest write this process committed. Until that first write, the image is empty. The list total and the account body are the stale image, not the live rows. The header marks the response. Role listing is not a stale account read.

Rules are inserted with `FaultStore.add(name, app_id, operation, times)`. `app_id` is `rest-modern`, `rest-legacy`, or `*`. `operation` is one of the operation names above or `*`. `times` is the finite remaining count. The first inserted rule that still has remaining count, matches the scope, and applies to the request wins and then loses one count. A rule that does not apply to the request is not decremented.

There is no HTTP route to add or reset rules. The default store has no rules. Counters and stale images are not durable across restart. Unauthenticated requests, including a wrong token, do not match and do not decrement. `401` and `403` are decided before matching. A malformed body or a missing idempotency key is also decided before matching.

`FaultStore.hits()` lists the rule id, revision, name, application, operation, and remaining count after each match. `FaultStore.remaining(rule_id)` reads the current count. UI polling is a read. It consumes a count only when that read itself matches a rule. It does not run the legacy worker.

## SQL pack

`infra/postgres/packs/rest.sql` creates `rest_accounts`, `rest_roles`, `rest_account_roles`, `rest_operations`, and the per-application id counter `rest_id_alloc`. It does not alter SCIM tables.

`target_owner` owns the tables and is the role that serves the routes. `admin_owner` and `verifier_reader` can select. `verifier_reader` cannot change them. `admin_owner` can truncate. Truncate removes the seeded roles and id counters; both have to be inserted again before the routes can assign roles or allocate ids.

Login uniqueness is `lower(login)` per `app_id`. Deleting an account deletes its role assignments. Deleting an account does not delete operation history.
