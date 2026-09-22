# Lifecycle

HR is a source. SCIM, REST, LDAP, and legacy SQL each own their own accounts. An HR update does not silently change those accounts. `POST /hr/people` writes the HR list only. A reference driver or an external client has to call the target's own API before a target account changes.

`infra/postgres/init.sh` applies `infra/postgres/packs/hr.sql` when that file is present. A second apply does not drop tables or reseed SCIM users. That file is the SQL feed definition. It is not a second copy of the people, and the HTTP feed does not read it. Role `hr_reader` is created without a login or a password. Its only table privilege is `SELECT`.

## Feeds

The flagship people live in `fixtures/enterprise-small-v1.json`. When that file is present, the HTTP feed loads it. If it is absent, the HR list is empty. The feed does not load `pagination-large-v1` or `overlays/inconsistent-v1`. Passwords, `idpAccount`, and `scimUser` are not feed fields.

The same people are projected three ways:

| Feed | Where | Identity columns |
| --- | --- | --- |
| REST | `GET /hr/people`, `GET /hr/people/{employeeNumber}` | `employeeNumber`, `userName`, `email`, `department`, `managerEmployeeNumber` |
| CSV | `fixtures/feeds/enterprise-small-v1.csv` | those columns, in that order |
| SQL | `hr_people` and `hr_changes` in `infra/postgres/packs/hr.sql` | `employee_number`, `user_name`, `email`, `department`, `manager_employee_number` |

REST adds `sequence` on each person. CSV does not have a sequence column; row order after the header is the initial sequence order. SQL stores `sequence` on both tables. A blank CSV `managerEmployeeNumber`, a JSON `null`, and a SQL `NULL` are the same absent manager.

`managerEmployeeNumber` is a reference to another employee number. It is not a foreign key and it is not an account. The flagship fixture has no managers, so the column is present and empty. An unknown reference does not create a person.

Correlation is the employee number, compared exactly, including case. `userName` is not the identity key.

## Sequence

Every HR change gets the next integer sequence, starting at 1. `sequence` is the order key. `occurredAt` is not unique and is not a key.

The fixture load uses one timestamp for every row, `2020-01-01T00:00:00Z`. Those rows stay distinct. `GET /hr/changes?after=1` returns the change with sequence 2 and every later change, including rows whose timestamp equals the row that was skipped. Asking again with a timestamp would be ambiguous. The API does not offer that. Resume with the greatest sequence already applied.

`GET /hr/changes?after=<sequence>` returns `order: "sequence"`. A missing `after` means `0`. A negative or non-integer `after` is rejected. A later `POST /hr/people` that repeats an earlier `occurredAt` still receives a new sequence and appears in the feed. Two identical timestamps are two changes.

`POST /hr/people` upserts by `employeeNumber`. The body is the feed columns, plus optional `occurredAt`. Omitted manager clears the reference. A password is rejected. The write updates the process's HR list and does not rewrite the fixture file. A restart loads the file again. `201` means a new HR person. `200` means the existing HR person was replaced. Neither status means a target account was created or changed. These routes do not use the SCIM bearer token. Calling them still cannot create or change a target account.

## Ownership

`OwnershipLedger` records lifecycle and manual grants per target. It does not write a target and it does not adopt access merely because that access was observed.

`remove_obsolete()` deletes lifecycle ownership for the entitlements it is given. Manual grants stay. When the same entitlement has both owners, the manual grant remains and the entitlement is not returned for native removal. Native membership may be removed only for an entitlement the method returns, which is one that no longer has an owner.

`rehire()` grants the current entitlements it is given. It does not copy historical privileges back onto the person. It does not create a person or a second account. A rehire of a retained person reuses that employee number.

`rename()` changes `userName` and, when supplied, `email`. The employee number stays the same. Rename does not insert a second person and does not replace a trusted binding. The ledger has no binding field.

## Scenarios

Each file under `scenarios/` has an id, version, fixture, required capabilities, preconditions, allowed changes, protected state, and mode `reference|external`. The files are the contract. `./lab scenario list` prints `scim-login-revoke` and each of these ids. `transaction-rollback` is listed as unavailable. `./lab scenario run` still executes only `scim-login-revoke` in reference mode. Listing a file does not run it.

| Scenario | What it bounds |
| --- | --- |
| `joiner` | One correlated account and the current non-administrator entitlement |
| `mover-engineering-to-sales` | Drop obsolete lifecycle access; keep manual and overlapping access |
| `leaver` | HTTP subset only. A missing LDAP bind check is not a pass |
| `rehire` | Current access on a retained account. No historical privileges and no duplicate |
| `rename` | Same employee number. No second person and no binding replacement |
| `orphan` | Report a target account or manager reference the HR feed does not know. Do not delete it and do not invent an HR person from the account |
| `partial-failure` | One failed target blocks an overall pass |
| `retry-ambiguity` | Reconcile a lost create response. Do not create a second account |
| `authorization-failure` | The denied write leaves target state unchanged. Denial is not a pass |

`scenarios/transaction-rollback.json` is unavailable until JDBC and is not passable. Do not treat it as a passed result.

External mode does not run a driver by itself. `clients/external/walkthrough.py` is the external-client example. It does not run itself. It GETs `/hr/changes` and POSTs to a target base URL passed in. It does not import the playground package and it does not open a database.
