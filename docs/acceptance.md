These IDs are the plan's proof names; none have been executed.

| ID | Named proof | Status |
|---|---|---|
| BOOT-01 | Clean startup | not run |
| BOOT-02 | Repeated startup creates no duplicates | not run |
| BOOT-03 | Restart preserves a deliberate state change | not run |
| BOOT-04 | A missing dependency produces a nonzero result and an actionable explanation | not run |
| BOOT-05 | A future-pack command reports unavailable | not run |
| SCIM-01 | Create/read/update/disable/delete | not run |
| SCIM-02 | Membership add/remove/readback | not run |
| SCIM-03 | Failed multi-operation PATCH leaves original state | not run |
| SCIM-04 | No duplicate membership after repeat delivery | not run |
| SCIM-05 | Complete paging and explicit filter behavior | not run |
| SCIM-06 | A credentials cannot read or change B | not run |
| SCIM-07 | Conflicting correlation and case rules behave as documented | not run |
| AUTH-01 | Successful OIDC sign-in | not run |
| AUTH-02 | No-account denial | not run |
| AUTH-03 | Read/write/admin role behavior | not run |
| AUTH-04 | Next admin request after committed revoke denied with the same session | not run |
| AUTH-05 | Disabled account denied while IdP session remains valid | not run |
| AUTH-06 | Changed/duplicate email, different issuer/subject, attempted rebinding, and delete/recreate cannot steal or inherit a binding | not run |
| AUTH-07 | Wrong issuer/audience, expired, and insufficient-authority credentials rejected | not run |
| AUTH-08 | Required host/origin/CSRF and session protections tested | not run |
| VERIFY-01 | Only observed outcomes can pass | not run |
| VERIFY-02 | An extra privilege fails | not run |
| VERIFY-03 | Unavailable required observations never pass | not run |
| VERIFY-04 | No verifier account-write authority | not run |
| VERIFY-05 | Redaction | not run |
| RUN-01 | One mutating run at a time | not run |
| RUN-02 | Reset and interruption recovery | not run |
| CTRL-01 | Permitted calls reach the correct target | not run |
| CTRL-02 | Prohibited calls leave protected state unchanged | not run |
| CTRL-03 | Resource/credential validation | not run |
| CTRL-04 | Revoked authority blocks the next call | not run |
| FAULT-01 | Deterministic finite faults and counters survive restart | not run |
| JOURNAL-01 | Committed mutations and events agree, while rollback produces neither | not run |
| EVAL-01 | All ten tasks have reliable independent graders | not run |
| EVAL-02 | Prohibited intermediate grants fail even after cleanup | not run |
| EVAL-03 | Commit-before-timeout recovery avoids duplicate accounts | not run |
| EVAL-04 | Truthful unavailable/partial reporting | not run |
| EVAL-05 | Isolated, repeatable fixtures | not run |
| REST-01 | Both profiles perform documented operations | not run |
| REST-02 | Complete paging/correlation | not run |
| REST-03 | Application isolation | not run |
| ASYNC-01 | Restart resumes durable accepted work | not run |
| ASYNC-02 | Duplicate key returns the existing operation | not run |
| ASYNC-03 | Changed payload conflicts | not run |
| ASYNC-04 | Committed-but-timed-out writes reconcile without duplicate accounts | not run |
| ASYNC-05 | Failed/cancelled/partial outcomes do not pass incorrectly | not run |
| RESET-ASYNC-01 | Old work cannot affect the new generation | not run |
| FAULT-02 | All six documented HTTP faults are deterministic and visible | not run |
| HR-01 | Consistent REST/CSV/SQL observations | not run |
| HR-02 | Sequence feed resumes without losing equal-timestamp changes | not run |
| LIFE-01 | Joiner baseline | not run |
| LIFE-02 | Managed mover preserves manual and overlapping access | not run |
| LIFE-03 | HTTP leaver enforcement | not run |
| LIFE-04 | Rehire without stale privileges/duplicates | not run |
| LIFE-05 | Rename stability | not run |
| LIFE-06 | Orphan visibility | not run |
| LIFE-07 | Failed target prevents overall pass | not run |
| EXT-01 | External client completes the same scenario | not run |
| EXT-02 | External inactivity produces no hidden provisioning | not run |
| LDAP-01 | Synthetic user binds successfully | not run |
| LDAP-02 | A real disable operation rejects a subsequent bind with the same credentials | not run |
| LDAP-03 | A valid control user and healthy trusted connection distinguish account denial from outage/TLS failure | not run |
| LDAP-04 | Aggregation principal cannot write | not run |
| LDAP-05 | Paging and CRUD | not run |
| LDAP-06 | Membership/reverse membership | not run |
| LDAP-07 | Empty groups and rename/delete integrity | not run |
| LDAP-08 | Restart persistence and reset isolation | not run |
| JDBC-01 | Actual Java connection/aggregation | not run |
| JDBC-02 | Create/update/disable and native readback | not run |
| JDBC-03 | Role grant/revoke | not run |
| JDBC-04 | Read-only principal cannot write | not run |
| JDBC-05 | Invalid dependent assignment leaves no partial commit | not run |
| JDBC-06 | State independent of SCIM/REST | not run |
| JDBC-07 | Restart/reset isolation | not run |
| ALL-01 | All required scenarios pass across declared targets | not run |
| ALL-02 | Deliberate adverse outcomes fail or remain indeterminate correctly | not run |
| UI-01 | Every required view and action is usable through Playwright | not run |
| RECOVER-01 | Restart/cancel/reset matrix | not run |
| BOUNDARY-01 | Callers cannot cross intended authority boundaries | not run |
| MATRIX-01 | Every required capability maps to evidence with no unresolved required planned items | not run |
| RELEASE-01 | Independent fresh-environment rehearsal | not run |
| RELEASE-02 | Docs/commands match actual behavior | not run |
| RELEASE-03 | Tested environment/version inventory | not run |
| RELEASE-04 | Redacted artifacts | not run |
| RELEASE-05 | Recordings and evidence match the release | not run |
| RELEASE-06 | Required publication review and no unresolved release blockers | not run |
