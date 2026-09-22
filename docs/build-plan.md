# IAM Playground: phased build plan through feature-complete v1.0

**Planning status:** Proposed execution plan. This document does not claim that any implementation, runtime test, model trial, or release has been completed.

**Repository:** `rlwillen0121/iam-playground`  
**User's local checkout:** `/Users/ryanwillen/Documents/IGA/iam-playground`  
**Source of product requirements:** `docs/spec.md`, supported by `docs/architecture.md`, `docs/capabilities.md`, and `AGENTS.md`. The specification read for this plan had blob SHA `ee34003599e7d85ed3b0656788fdc52510ed05f4`. This is a file-content identifier, not an asserted repository commit.

The existing specification remains the product authority. The phase breakdown, proposed acceptance IDs, handoff format, and small CLI extensions below are planning recommendations. They are not descriptions of existing functionality. Resolve actual implementation differences against the current checkout before starting a phase.

## 1. What feature complete means

Feature-complete v1.0 is one usable, self-hosted integration lab with independent SCIM, proprietary REST, OpenLDAP, and legacy SQL account stores; synthetic HR feeds; real Keycloak authentication; an application that enforces provisioned access; reference and external execution; deterministic failures; lifecycle scenarios; independent verification; a five-view workbench; and an optional bounded MCP/agent-evaluation pack.

The core lab must run without a paid IAM tenant or model API key. The optional AI pack is part of the planned product, but live model execution is not a prerequisite for starting or testing the core lab. Its deterministic control tests require no model credentials.

Feature complete is bounded by documented support contracts. It does not mean every optional SCIM feature, every OAuth flow, every directory product, or compatibility with every IAM vendor. A remaining required capability cannot be relabeled unsupported just to close the release. Optional protocol behavior can be explicitly unsupported when the spec permits that boundary.

Two completion gates apply. **Functional completion** means the required features and acceptance tests are implemented and verified. **Release completion** also requires a clean-environment rehearsal, usable documentation, redacted evidence, tested packaging, and publication review.

## 2. Release and phase map

| Phase | Deliverable | Release gate |
|---|---|---|
| 1 | Bootable runtime, bootstrap, and truthful CLI | Foundation for v0.1 |
| 2 | Real SCIM target and application isolation | Foundation for v0.1 |
| 3 | OIDC, trusted binding, and application enforcement | Foundation for v0.1 |
| 4 | Independent verifier, first scenario, minimal workbench | v0.1 candidate |
| 5 | Bounded MCP, enforcement, starter faults, mutation journal | Foundation for v0.2 |
| 6 | Agent tasks, deterministic graders, optional live trials | v0.2 candidate |
| 7 | Modern/legacy REST, durable asynchronous operations, remaining HTTP faults | Foundation for v0.3 |
| 8 | HR feeds, lifecycle ownership, and external execution | v0.3 candidate |
| 9 | Native OpenLDAP pack | Foundation for v0.4 |
| 10 | Native SQL/Java JDBC pack | v0.4 candidate |
| 11 | Full cross-target scenarios, complete workbench, recovery hardening | Feature-complete v1.0 candidate |
| 12 | Independent release rehearsal and portfolio packaging | v1.0 release-ready |

The scaffolding is the starting point, not another implementation phase. Do not rebuild the lane framework before starting phase 1. Publish usable intermediate releases after their review and an explicit publication instruction; do not wait for v1.0 to show working software. Until that instruction, keep the repository private and prepare release candidates only.

## 3. Architecture and proof rules that apply throughout

Preserve Python/FastAPI, React/TypeScript, PostgreSQL, Keycloak, OpenLDAP, Java/pgJDBC, Playwright, and Docker Compose. Use the proposed modular layout rather than adding Kubernetes, an event bus, or a generic plugin platform.

Each target owns its account state. The demo application is intentionally the user-facing surface of the SCIM target and shares its account/membership store. An HR update never silently updates target accounts.

Reference and external clients use actual target protocols. A verifier uses independently authorized observations and synthetic-user authorization probes; it cannot provision, grant, repair, or silently bind accounts. Shared transport helpers are acceptable, but the verifier must not use target write services or treat driver output as observed truth.

The actor is the authenticated caller; the subject is the account being changed. Permissions come from verified credentials and server-controlled authorization, not request-body claims. Preparation, provisioning, trusted binding, faults, and explicit operator actions must be separately attributable.

Preserve the four verdicts: `PASSED`, `FAILED`, `INDETERMINATE`, and `CANCELLED`. Observing a forbidden change fails the relevant assertion. An unavailable required observation is not proof of success. A successful subset of targets is partial progress, not an overall pass.

Use one active mutating scenario per lab environment initially. Parallel test jobs get isolated projects and volumes. Normal restart preserves state; reset changes generation and stops old work from affecting new state.

Choose explicit candidate dependency versions and lockfiles during implementation. Record tested versions only after execution. Do not leave dependencies floating merely because verification has not happened yet, and do not invent tested platforms or performance measurements.

## 4. The implementation phases

### Phase 1: bootable runtime and developer entry point

**Goal:** Replace the placeholder CLI with an environment an operator can start, inspect, stop, and diagnose.

**Work packages:**

| ID | Work |
|---|---|
| P1-A | Establish backend, frontend, infrastructure, fixture, and test package skeletons with selected candidate versions and lockfiles. |
| P1-B | Add Compose services for PostgreSQL, Keycloak, target-facing backend, administrative backend, and the minimal frontend. Preserve process and credential boundaries. |
| P1-C | Implement schema/bootstrap tracking and the static `enterprise-small-v1` fixture: 50 synthetic people, 12 entitlements, deterministic mappings, and a separate larger pagination fixture. |
| P1-D | Implement `./lab up`, `doctor`, `endpoints`, and `down`. Make bootstrap idempotent; normal restart must not silently overwrite user state. |
| P1-E | Add fast CI checks, dependency configuration checks, unit-test execution, and secret scanning. Establish the integration job entry point without pretending a scaffold test is end-to-end proof. |

For the flagship fixture, Alice exists at Keycloak but has no provisioned SCIM account. Other fixture accounts must not accidentally satisfy her journey. Keep named bad-data overlays separate from the healthy baseline.

`doctor` checks prerequisites, database/schema state, completed bootstrap, service readiness, credential validity where applicable, and issuer/callback configuration as authentication is implemented. Report not-ready or not-yet-implemented checks explicitly. Bind published ports to loopback and label any HTTP development exceptions.

**Exit evidence:** `BOOT-01` clean startup; `BOOT-02` repeated startup creates no duplicates; `BOOT-03` restart preserves a deliberate state change; `BOOT-04` a missing dependency produces a nonzero result and an actionable explanation; `BOOT-05` a future-pack command reports unavailable. Save the operator's command results and tested environment.

**Do not add:** LDAP, JDBC, REST profiles, full HR service, agent execution, or the full workbench.

### Phase 2: SCIM target with real persistence and isolation

**Depends on:** Phase 1.

**Goal:** Make the lab a useful provisioning target instead of a canned-response server.

Implement the spec's `/apps/{app_id}/scim/v2/` resource routes for Users, Groups, Schemas, ResourceTypes, and ServiceProviderConfig. Cover create/get/list/supported PATCH/delete, active status, core names/emails, memberships, and the enterprise fields required by fixtures. Publish exact supported attributes, paths, methods, filters, and errors.

Use server-assigned IDs and explicitly defined correlation/uniqueness behavior. Start with the equality-filter subset and 1-based pagination described in the spec. Unsupported or malformed filtering must not silently turn into an unfiltered result. Keep optional PUT, bulk, sorting, and ETags unsupported unless deliberately implemented and tested.

Implement transactional multi-operation PATCH, membership deduplication, filtered membership removal, and consistent read-only user group representations. Create two application instances with separate account state and credentials. Reject cross-application paths, object IDs, and membership references inside request bodies.

Build a reference SCIM client and protocol test suite that use HTTP only. Establish a stable correlation strategy for later ambiguous-create recovery; do not assume arbitrary targets make `externalId` unique.

**Exit evidence:** `SCIM-01` create/read/update/disable/delete; `SCIM-02` membership add/remove/readback; `SCIM-03` failed multi-operation PATCH leaves original state; `SCIM-04` no duplicate membership after repeat delivery; `SCIM-05` complete paging and explicit filter behavior; `SCIM-06` A credentials cannot read or change B; `SCIM-07` conflicting correlation and case rules behave as documented.

**Do not add:** A universal schema editor, every optional SCIM feature, or untested vendor compatibility badges.

### Phase 3: real authentication, trusted binding, and enforced access

**Depends on:** Phases 1 and 2.

**Goal:** A browser user actually gains and loses application capabilities because of provisioning state.

Implement Keycloak authorization-code authentication with PKCE and a backend-managed session. Follow the spec's explicit issuer, audience, lifetime, algorithm, redirect, and cookie contracts using maintained dependencies. Solve browser/container reachability without disabling issuer validation. Keep bearer tokens out of browser local storage.

Add the application-scoped binding from trusted issuer/subject to immutable SCIM account ID. Only preparation or a separately authorized administrator operation may create or replace it. Neither a normal SCIM client nor the demo user can claim an account through email matching or writable identity claims.

Implement read, write, and administrator demo actions backed by current SCIM account and group state. Recheck account status and membership on every protected request; do not add an authorization-state cache in this release. Show server-derived reasons for permission decisions in a small developer panel.

Exercise the complete journey with real browser authentication: authenticated but unprovisioned denial; SCIM create; visible trusted binding; reader allowance; administrator grant; administrator revoke using the same session; account disable denial. Keep fresh-login rejection after IdP disable as a separate scenario with distinct claims.

**Exit evidence:** `AUTH-01` successful OIDC sign-in; `AUTH-02` no-account denial; `AUTH-03` read/write/admin role behavior; `AUTH-04` next admin request after committed revoke denied with the same session; `AUTH-05` disabled account denied while IdP session remains valid; `AUTH-06` changed/duplicate email, different issuer/subject, attempted rebinding, and delete/recreate cannot steal or inherit a binding; `AUTH-07` wrong issuer/audience, expired, and insufficient-authority credentials rejected; `AUTH-08` required host/origin/CSRF and session protections tested.

Prove a denial is the expected authorization decision, not a broken dependency. Requests authorized before the revocation commit are outside the next-new-request claim.

### Phase 4: independent verification and the first shippable lab

**Depends on:** Phases 1 through 3.

**Goal:** Another engineer can execute the flagship scenario and inspect evidence rather than trust a green badge.

Define a small scenario/run contract: scenario and fixture versions, required capabilities, preconditions, allowed changes, protected state, deadline, lab generation, and cleanup. Snapshot this contract before execution. Build the driver/verifier separation now; later packs extend it instead of introducing new orchestration systems.

Implement `scim-login-revoke` reference execution, independent account/membership readback, and actual permission probes. Record the trusted binding step as a separate administrative action; do not credit the driver for a hidden provisioning shortcut. Compare expected changes and protected state, not only the requested result.

Implement scenario list/run/verify, smoke tests, reset, and redacted JSON export from the existing CLI contract. Preserve non-passing states for interrupted runs and partial reset. Implement the minimal workbench for health/connections, SCIM data inspection, one run, and its evidence. All displayed results must come from the real APIs and verifier.

Add core integration CI using PostgreSQL, Keycloak, the SCIM target, and actual Playwright. Add tests against deliberately false completion claims, extra membership changes, missing observations, and unavailable services. Add sentinel-secret tests for exports and inspect trace/log handling.

**Exit evidence:** `VERIFY-01` only observed outcomes can pass; `VERIFY-02` an extra privilege fails; `VERIFY-03` unavailable required observations never pass; `VERIFY-04` no verifier account-write authority; `VERIFY-05` redaction; `RUN-01` one mutating run at a time; `RUN-02` reset and interruption recovery; the full phase 2 and 3 suites.

**Release:** v0.1 candidate. Include the exact quickstart, capability matrix, threat model, redacted sample report, and flagship recording tied to the tested code. Obtain publication review and authorization before publishing. Everything after v0.1 stays visibly planned.

### Phase 5: bounded MCP and security controls

**Depends on:** Phase 4. It must use the existing protocol clients and verifier.

**Goal:** Expose useful identity operations to an agent without making it a lab administrator.

Implement typed account lookup, group listing, supported provisioning, permitted membership add/remove, and account disable operations. Fix targets in server configuration; do not accept arbitrary endpoints, SQL, or shell commands. Preserve public protocol calls rather than direct target database writes.

Implement a restricted principal with application/action/entitlement allowlists and server-side enablement checked on every call. Keep the privileged reference-demo principal separate. For HTTP MCP, select and test an explicit protocol version and resource-specific authorization flow, with separately authorized downstream credentials. Treat an optional stdio recipe as a separate credential-boundary claim, not proof of HTTP authorization.

Add deterministic control tests that deliberately request read-only writes, cross-application changes, administrator grants, binding edits, and use after principal disablement. Reject them even when the caller explicitly asks. Deny access to reset, fixtures, faults, policy changes, verifier report writes, Docker socket, host secrets, unrestricted filesystem, and shell.

Add the starter faults needed by the next phase: finite 429/503 failures and commit-before-response timeout. Authenticate and authorize before fault matching. Persist rule counters and label which client/verifier reads can consume them. UI polling must not change the test.

Add the SCIM target-side mutation journal in the same transaction as successful changes, using an allowlisted event schema. Keep journal modification outside the agent's authority. This supports detecting a forbidden intermediate grant even after subsequent removal; do not advertise tamper resistance against a host administrator.

**Exit evidence:** `CTRL-01` permitted calls reach the correct target; `CTRL-02` prohibited calls leave protected state unchanged; `CTRL-03` resource/credential validation; `CTRL-04` revoked authority blocks the next call; `FAULT-01` deterministic finite faults and counters survive restart; `JOURNAL-01` committed mutations and events agree, while rollback produces neither.

**Do not add:** Provider-specific agent dependencies to core startup, a general policy language, end-user delegation claims, or production administration.

### Phase 6: agent evaluations and the AI-focused demonstration

**Depends on:** Phase 5.

**Goal:** Show useful agent execution, enforced restrictions, and truthful outcome reporting separately.

Implement the ten versioned tasks in the spec: allowed joiner; managed mover; leaver; read-only actor; cross-application request; prohibited administrator grant; misleading target data; commit-before-timeout; revoked agent authority; and verification unavailable.

Keep the v0.2 lifecycle tasks within SCIM. Implement the small grant-ownership ledger needed for the mover now and reuse it in phase 8. For that fixture, explicitly allow only its necessary nonprivileged department entitlements. Manual and lifecycle ownership of the same native membership must coexist without accidental removal. Do not expose ledger tampering to the agent.

Where an allowed joiner requires binding for an application probe, prescribe a visible trusted binding step outside agent authority. It is not an agent tool, it cannot grant access, and it must be labeled separately in the evidence. The agent must receive the legitimate task requirements and constraints, while verifier credentials and grading controls remain isolated.

Build a tool-only runner with bounded calls, execution deadlines, and an optional model adapter. Pin/report the actual model and harness configuration; do not require any particular paid provider. Use scripted callers for normal CI and deterministic state/authorization graders for verdicts. Record task result, prohibited attempts, prohibited successful mutations, unexpected changes, false completion claims, tool calls, and duration separately. Include cost/token data only when supported by actual measurements.

Test graders using deliberately wrong outcomes, not just successful reference runs. Explicitly distinguish a stopped run, model refusal, model mistake, rejected tool call, and successful prohibited mutation.

**Exit evidence:** `EVAL-01` all ten tasks have reliable independent graders; `EVAL-02` prohibited intermediate grants fail even after cleanup; `EVAL-03` commit-before-timeout recovery avoids duplicate accounts; `EVAL-04` truthful unavailable/partial reporting; `EVAL-05` isolated, repeatable fixtures; all deterministic control tests pass. Run and record a live suite only when explicitly authorized, publishing every trial and its configuration, including failures.

**Release:** v0.2 candidate. Produce the bounded-agent demonstration alongside the deterministic results. A model need not achieve perfect task success to demonstrate a useful evaluation system; enforcement and grading bugs remain release blockers. Without a live trial, describe deterministic verification accurately and leave the spec's live-demonstration gate outstanding.

### Phase 7: proprietary REST and durable failure handling

**Depends on:** Phase 4's scenario/verifier contracts. Build after phase 6 in the recommended release sequence; protocol work can proceed independently once those shared contracts are stable.

**Goal:** Demonstrate integration with APIs that are not SCIM and with writes that finish later.

Implement independent REST account/role state using the spec's integer account ID, `login`, `employeeRef`, `status`, and nested `profile`. Cover account CRUD, explicit enable/disable actions, role listing, assignment/removal, and operation polling.

Ship the two bounded profiles: Modern REST with OAuth client credentials, cursor pagination, and synchronous writes; Legacy REST with application-specific API keys, page-based pagination, and durable asynchronous operations. Add read-only and provisioning credentials and application isolation tests appropriate to both profiles. Do not share account tables with SCIM.

Persist operation acceptance and idempotency records before acknowledgment. Scope keys to authenticated client and application; identical key/payload resolves to the same operation and changed payload conflicts. Define operation states, restart recovery, bounded retries, and best-effort cancellation. Verify both actual target state and the operation's terminal status. Acceptance alone never means fulfillment.

Complete the HTTP fault set: bounded stale reads, eventual asynchronous failure, and malformed list envelopes, reusing phase 5's fault controls. Add the critical crash windows: before commit, after committed acceptance, after target mutation, and before response/acknowledgment. Define recovery for each without calling the system universally exactly-once.

Extend reset protection when workers first arrive, not at final hardening. A reset must prevent old operations from writing into the new generation. Test stale workers, interrupted reset, partial effects, and canceled operations that cannot be rolled back.

**Exit evidence:** `REST-01` both profiles perform documented operations; `REST-02` complete paging/correlation; `REST-03` application isolation; `ASYNC-01` restart resumes durable accepted work; `ASYNC-02` duplicate key returns the existing operation; `ASYNC-03` changed payload conflicts; `ASYNC-04` committed-but-timed-out writes reconcile without duplicate accounts; `ASYNC-05` failed/cancelled/partial outcomes do not pass incorrectly; `RESET-ASYNC-01` old work cannot affect the new generation; `FAULT-02` all six documented HTTP faults are deterministic and visible.

**Do not add:** A generic workflow engine, arbitrary scriptable API mocking, or more REST profiles before these two pass.

### Phase 8: HR sources, lifecycle ownership, and external integration

**Depends on:** Phase 7, reusing the SCIM ownership rules introduced in phase 6.

**Goal:** The playground becomes a reusable lifecycle lab, not just a single hand-authored demonstration.

Expose the same authoritative synthetic HR data through REST, CSV, and a read-only SQL feed. Add a sequence-based change feed so equal timestamps do not lose updates. Document field mappings, correlation rules, manager/reference treatment, and named overlays for deliberately inconsistent data. An HR update changes only HR; the driver or external system must make target changes.

Implement versioned joiner, mover, leaver, rehire, rename, orphan, partial-failure, retry-ambiguity, and authorization-failure scenarios against the available HTTP targets. Retain transaction rollback as unavailable until the JDBC pack exists. Where full leaver checks require LDAP, label the HTTP subset explicitly instead of treating a missing directory test as passing.

Expand the reference driver's ownership ledger to target-specific grants. Remove only obsolete lifecycle ownership; preserve manual grants and overlapping ownership. Do not adopt observed preexisting access as lifecycle-owned. Rehire reuses an explicitly correlated retained account and grants current authorized access rather than replaying historical privileges. Rename must not create a duplicate identity or replace a trusted binding.

Finish external execution: prepare fixture/preconditions, publish task and scoped connection details through the authenticated management surface, wait for the external client, then independently verify the result. No driver may run automatically in external mode. A visible trusted binding step remains separately authorized where required.

Supply one small, independent external-client example that does not import the reference orchestrator or target database code. That proves the external interface without requiring Okta, Entra, Lumos, SailPoint, or ConductorOne. Vendor recipes remain untested unless an actual tenant run supports them.

**Exit evidence:** `HR-01` consistent REST/CSV/SQL observations; `HR-02` sequence feed resumes without losing equal-timestamp changes; `LIFE-01` joiner baseline; `LIFE-02` managed mover preserves manual and overlapping access; `LIFE-03` HTTP leaver enforcement; `LIFE-04` rehire without stale privileges/duplicates; `LIFE-05` rename stability; `LIFE-06` orphan visibility; `LIFE-07` failed target prevents overall pass; `EXT-01` external client completes the same scenario; `EXT-02` external inactivity produces no hidden provisioning.

**Release:** v0.3 candidate. Ship both REST profiles, all HR feeds, HTTP lifecycle scenarios, complete HTTP faults, durable recovery, and a tested external-client walkthrough. Keep native-pack prerequisites explicit.

### Phase 9: real OpenLDAP

**Depends on:** The core fixture/run/verifier contracts; phase 8 supplies lifecycle integration.

**Goal:** Native directory behavior, including access denial that actually prevents a bind.

Add an OpenLDAP Compose pack with checked-in schema, ACLs, TLS/trust configuration, fixture loading, and a tested account-disable mechanism. Use `dc=iam,dc=test` and the People, Groups, ServiceAccounts, and System organizational units. Keep directory entries independent from other targets.

Provide distinct aggregation and provisioning bind identities. Implement reference operations and native verification for bind, search, paging, add, modify, rename, delete, and membership. Configure real reverse membership, schema-valid empty-group behavior, and referential integrity for rename/delete. Display native results rather than fabricating them in the workbench.

Integrate directory readiness/trust checks into `doctor`, connection recipes into Applications, entries/memberships into Data, and directory assertions into lifecycle scenarios. Use native permission/schema failures for the initial negative pack.

Implement restart/reset handling that drains or closes relevant clients and directory sessions before reseeding. Ensure a held old connection or stale writer cannot mutate the new generation. A UI generation number alone is not sufficient.

**Exit evidence:** `LDAP-01` synthetic user binds successfully; `LDAP-02` a real disable operation rejects a subsequent bind with the same credentials; `LDAP-03` a valid control user and healthy trusted connection distinguish account denial from outage/TLS failure; `LDAP-04` aggregation principal cannot write; `LDAP-05` paging and CRUD; `LDAP-06` membership/reverse membership; `LDAP-07` empty groups and rename/delete integrity; `LDAP-08` restart persistence and reset isolation.

**Claim boundary:** Generic LDAP for the tested OpenLDAP configuration, not Active Directory compatibility. Existing established sessions are not universally revoked merely because new binds are denied.

### Phase 10: native legacy database and Java JDBC

**Depends on:** The core contracts and phase 8's lifecycle integration. Can be developed in parallel with phase 9 after shared infrastructure changes are coordinated.

**Goal:** Make the JDBC claim real, including least-privilege access and transaction rollback.

Implement independent `legacy_app.accounts`, `roles`, `account_roles`, and `change_events` tables. Separate read-only and provisioning database identities with narrow grants. These rows are application accounts, not PostgreSQL login users.

Build the Java/pgJDBC client with reproducible dependencies, parameterized statements, explicit transactions, and native database connectivity. Support aggregation, account create/update/disable, role grant/revoke, and independent readback. Do not route the JDBC acceptance path through an HTTP shim.

Implement the rollback proof: insert an account, attempt an invalid role assignment in the same transaction, roll back, and verify that neither effect remains. Include constraints, denied writes, correlation, and connection errors without turning infrastructure failure into proof of account removal.

Integrate `./lab jdbc verify`, SQL doctor checks, workbench table views, source-to-target mappings, and native lifecycle assertions. Add worker/client fencing and connection handling so old writers cannot survive reset into new state. Label change events and client observations according to their actual collection mechanism; do not inherit the SCIM journal's history claim automatically.

**Exit evidence:** `JDBC-01` actual Java connection/aggregation; `JDBC-02` create/update/disable and native readback; `JDBC-03` role grant/revoke; `JDBC-04` read-only principal cannot write; `JDBC-05` invalid dependent assignment leaves no partial commit; `JDBC-06` state independent of SCIM/REST; `JDBC-07` restart/reset isolation; all OpenLDAP acceptance tests remain passing.

**Release:** v0.4 candidate. Ship native LDAP and JDBC recipes and evidence, including the bind-denial and rollback demonstrations. Do not wait for final UI polish to make the native packs usable.

### Phase 11: complete cross-target product and recovery behavior

**Depends on:** Phases 1 through 10.

**Goal:** Close the specified product surface and cross-target gaps without introducing new product categories.

Run the complete lifecycle pack against its declared SCIM, REST, LDAP, and JDBC targets. Extend the HTTP scenarios from phase 8 rather than creating competing definitions. Prove joiner provisioning; managed mover access transfer; leaver cleanup with application denial and native LDAP bind denial; retained-account rehire; rename stability; orphan reporting; partial failure; retry ambiguity; authorization failure; and JDBC rollback.

Use target-specific account IDs and ownership/correlation records. A missing required pack, unreadable target, or failed native assertion prevents an overall pass. Report final-state versus mutation-history guarantees separately. The optional MCP pack may remain explicitly SCIM-scoped; v1.0 does not require granting agents direct LDAP/SQL access or universal target control.

Complete the workbench's five specified views:

| View | Required completion |
|---|---|
| Overview | Real service health, selected packs, active fixture/generation, runs, faults, and readiness problems. |
| Applications | Endpoints, schemas, supported behavior, scoped credential management, and tested connection recipes. Do not place secrets in logs or exports. |
| Data | Native accounts, groups/roles, memberships, raw representations, paging/filtering, and useful state inspection across targets. |
| Scenarios | Prepare, reference-run, external-run workflow, verify, cancel, prerequisites, allowed changes, and expected-versus-observed results. |
| Activity | Requests, operation progress, observations, failures, applied faults, redacted evidence, and honest per-target outcomes. |

Keep the demo application separate, with working read/write/admin actions and server-derived authorization explanations. Do not add access-request workflows, certification campaigns, or a graph product.

Complete operating behavior: errors identify a failed dependency and useful next action; unsupported packs do not masquerade as healthy; UI polling cannot consume fault budgets; restart preserves state; concurrent mutation is fenced; partial reset can be recovered; stale async, LDAP, and JDBC writers cannot mutate new state; cancellation does not promise rollback of committed changes. Expose supported recovery through `./lab` instead of requiring ad hoc shell commands from the operator.

Finish isolated CI coverage, redaction tests, and explicit feature-to-test links for every required capability. Each acceptance gate runs against real dependencies where its claim requires them. Evaluate targeted adverse outcomes such as an extra admin grant, failed target read, accepted-but-unfinished operation, and reset during pending work.

**Exit evidence:** `ALL-01` all required scenarios pass across declared targets; `ALL-02` deliberate adverse outcomes fail or remain indeterminate correctly; `UI-01` every required view and action is usable through Playwright; `RECOVER-01` restart/cancel/reset matrix; `BOUNDARY-01` callers cannot cross intended authority boundaries; `MATRIX-01` every required capability maps to evidence with no unresolved required planned items.

**Completion gate:** Feature-complete v1.0 candidate. Required omissions and failing acceptance tests are blockers. Optional unsupported protocol features and deferred vendor recipes are limitations, not fabricated successes.

### Phase 12: independent release rehearsal and public portfolio package

**Depends on:** Phase 11 for v1.0. Apply the relevant smaller version of this release gate at v0.1, v0.2, v0.3, and v0.4 as well.

**Goal:** Someone other than the builder can reproduce the claimed product from the release artifacts.

Run the documented setup from a fresh checkout and isolated environment with no preexisting volumes, cached lab credentials, or undocumented repair steps. A separate operator should use only the documented commands. Test every platform/profile advertised as supported and record actual resolved image/dependency versions. Where Apple Silicon or Linux cannot be tested, leave that support claim unverified rather than inferring it from configuration.

Rehearse core startup, reference journey, external-client workflow, HTTP failures, LDAP bind disablement, Java JDBC rollback, cross-target lifecycle, reset, shutdown, and deterministic agent controls. Live model trials remain separately authorized and their results remain tied to their actual model/harness versions. Measure startup/resource use rather than inventing performance claims.

Finish README, architecture, threat model, capability matrix, demonstration guide, workshop, contributor setup, security notes, and tested recipes. Include one guided exercise, one deliberate failure, and one real failure investigation linking observed behavior to its fix and regression test.

Prepare tagged source, tested container artifacts, redacted sample JSON reports, release notes, and recordings tied to the same release. Check logs, browser traces, screenshots, fixtures, and history for secrets or client data. Keep every untested vendor recipe visibly untested; generic protocol recipes can satisfy the no-paid-tenant release path.

Obtain the repository's `Proven for publication` review verdict. Changing visibility, pushing release artifacts, or making a publication claim requires the appropriate explicit user instruction. This plan itself authorizes no remote writes or live execution.

**Exit evidence:** `RELEASE-01` independent fresh-environment rehearsal; `RELEASE-02` docs/commands match actual behavior; `RELEASE-03` tested environment/version inventory; `RELEASE-04` redacted artifacts; `RELEASE-05` recordings and evidence match the release; `RELEASE-06` required publication review and no unresolved release blockers.

**Release:** v1.0 release-ready. Publish only after authorization. Subsequent scope is new versioned work, not an excuse to redefine this finish line.

## 5. Requirements coverage map

| Spec section | Implementation phases | Main proof |
|---|---|---|
| 1. Product and reference/external/agent modes | 4, 6, 8, 11 | Same outcome contract; execution modes do not silently assist each other. |
| 2. Included systems and independent state | 1, 2, 3, 7, 8, 9, 10 | Each target owns accounts; only the demo app intentionally shares SCIM state. |
| 3. Architecture and trust boundaries | 1 onward | Separate processes/credentials and verified actor identity. |
| 4. SCIM | 2, 4 | Contract operations, PATCH atomicity, filters, paging, two-app isolation. |
| 5. Proprietary REST | 7 | Both profiles, durable operation state, idempotency, restart, cancellation. |
| 6. LDAP | 9 | Native bind/ACL/membership/TLS/disable behavior. |
| 7. JDBC | 10 | Actual Java/pgJDBC, scoped grants, transactional rollback, readback. |
| 8. OAuth/OIDC and application | 3, 4 | Real browser authentication and same-session access revocation. |
| 9. HR and lifecycle | 1, 6, 8, 11 | Static fixtures, feeds, ownership, rehire/rename/orphan, full JML. |
| 10. Failure injection | 5, 7, 9, 10, 11 | Six bounded HTTP faults plus native permissions/schema/constraint failures. |
| 11. Verification, evidence, reset | 4 onward | Independent observations; journal where supported; reset fencing; no false pass. |
| 12. Workbench and CLI | 1, 4, 7-11 | Minimal early UI, full five-view product, truthful supported commands. |
| 13. Testing and releases | Every phase, 12 | Fast/core/native/control/live/release tiers, capability matrix, rehearsals. |
| 14. Optional MCP/AI evaluation | 5, 6 | Typed tools, enforced authority, ten tasks, deterministic graders and recorded trials. |
| 15. Public deliverables | 4, 6, 8, 10, 12 | Usable release candidates, demonstrations, workshop, failure investigation. |

## 6. How to execute phases with the existing lanes

Use a repeated loop, not one giant implementation task:

**Orchestrate scopes a small change → implement edits and performs permitted fast checks → review examines affected boundaries → lab-operator exercises the exact code through `./lab` → evidence or defects return to orchestrate.** Implement fixes failures in a new code revision; the operator never patches source.

Respect the existing review composition: rules/security/completeness and the required engineering/lab lanes for relevant changes. Full review applies to publication and the specified auth/verifier/protocol/Compose boundaries. This plan does not change AGENTS.md or relax those rules. Update stale setup documentation as commands become real, but do not build another review framework.

A phase is not required to be one pull request. Split large phases into coherent work packages, typically configuration/schema, behavior, and proof/UI/documentation, while keeping integration testability. Review is not a replacement for execution; implemented is not verified.

Use this compact implementation handoff:

```text
Phase and work package:
Code revision / exact local state:
Implemented scope:
Known unimplemented scope:
Permitted fast checks and results:
Required review result:
Exact operator ./lab commands:
Expected assertions and artifact locations:
Cleanup / reset precautions:
```

Use this operator return:

```text
Code revision tested:
Environment and resolved versions:
Commands and exit codes:
Scenario/run IDs:
Verified assertions:
Failures / indeterminate outcomes / skipped checks:
Redacted evidence locations:
Defects with expected versus observed behavior:
```

Do not mark a phase complete with an unexecuted command list. When runtime access is unavailable, leave the status implemented/unverified and retain the precise operator handoff. Do not bypass the lane split with direct Compose commands or treat an agent's narrative as test evidence.

### CI progression

| Introduced | Required CI behavior |
|---|---|
| Phase 1 | Lint, type checks, unit tests, schema/configuration validation, secret checks. |
| Phases 2-4 | Real core protocol/integration tests and bootstrap followed by Playwright for relevant changes. |
| Phases 5-6 | Deterministic agent control tests and grader regressions without model secrets. |
| Phases 7-8 | REST async/crash/reset tests, HR feed tests, HTTP lifecycle and external-mode tests. |
| Phases 9-10 | Native LDAP and real Java JDBC jobs for affected packs and release gates. |
| Phase 11 | Declared cross-target scenario matrix, full workbench flows, recovery and isolation regressions. |
| Every release candidate | Clean-environment rehearsal and redacted evidence review for all advertised capabilities. |

Lab-running automation should use the same supported `./lab` surface in isolated operator execution, not mutate tracked source during a run. Contributor fast checks remain separate. Untrusted PR jobs must not receive production, model, or publication secrets. Live model trials are explicit trusted runs, not a default pull-request dependency.

## 7. CLI completion contract

These entry points are already intended by the product spec; the plan does not claim they exist yet:

```bash
./lab up
./lab doctor
./lab endpoints
./lab scenario list
./lab scenario run scim-login-revoke --mode reference
./lab scenario prepare mover-engineering-to-sales --mode external
./lab scenario verify <run-id>
./lab jdbc verify
./lab test smoke
./lab export <run-id> --format json
./lab reset --fixture enterprise-small-v1
./lab down
```

Implement each when its capability arrives. Include noninteractive execution and documented nonzero error/unsupported states. Keep the current unsupported convention unless the implemented CLI deliberately documents a change. Do not invent success codes for unfinished packs.

The spec also requires cancellation, diagnosis, native-pack tests, and optional agent execution without prescribing every CLI spelling. Proposed additions are `./lab scenario status <run-id>`, `./lab scenario cancel <run-id>`, targeted `./lab test <suite>` commands, and a documented optional agent-run entry point. Finalize names during the relevant implementation phase, update help/tests/docs together, and never advertise them as runnable before they are implemented.

## 8. Dependency management and parallelism

The recommended main sequence is phases 1-4, then 5-6, then 7-8, then 9-10, then 11-12. That yields useful IAM and AI-focused demonstrations before every target pack exists.

After phase 4, REST work is technically independent of most agent work. Keep shared scenario/fault/evidence contracts stable before parallel changes. LDAP and JDBC can be implemented in parallel later with separate branches and isolated lab environments, coordinating shared Compose/bootstrap edits. Keep one owner for shared CLI, evidence schema, and lifecycle contracts rather than creating duplicate implementations.

Do not run two mutating scenarios against the same fixture. Parallelism should reduce independent work time, not undermine evidence validity.

## 9. Scope lock and stop conditions

v1.0 excludes SAML, AD-specific behavior, SOAP, additional databases, workload-identity federation, delegated token exchange, a universal mocking DSL, visual workflow authoring, hosted multi-tenant operation, production IGA workflows, and autonomous production changes. Existing vendor MCPs are not silently imported into this repo.

The mandatory external recipes are for tested generic protocols and the included independent client. Paid-vendor compatibility is a separate, explicitly tested extension; do not hold the release hostage to obtaining every named tenant. The optional agent pack can remain SCIM-scoped with that limitation stated.

The v1.0 release gate is satisfied when every required feature has verified acceptance evidence, every required scenario works through its real path, deliberate failures are reported correctly, the workbench and CLI expose supported operations, resets/restarts are reliable, and an independent operator can reproduce the documented release.

**Immediate action:** Begin phase 1. Use this roadmap to bound each implementation task, not as a prompt to build all twelve phases in one uninterrupted coding pass.
