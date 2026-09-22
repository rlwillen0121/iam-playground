# Capabilities

`implemented` means the code is in this repository. The notes say what a local session on 2026-09-22 exercised. That session is not a support matrix, and it is not the flagship demonstration.

| Capability | Status | Exercised |
| --- | --- | --- |
| SCIM subset | implemented | List on app-a. An app-a token was rejected on app-b. |
| Trusted binding | implemented | Not exercised end to end. |
| Two-app isolation | implemented | Cross-app token rejection, above. |
| Verifier verdicts | implemented | In-memory cases only. |
| Demo read/write/admin | implemented | Not exercised through a browser. |
| MCP tools and faults | implemented | Lookup on app-a. App-b lookup returned 403. |
| Ten eval tasks | implemented | In-memory run. Nine `PASSED`, `verification-unavailable` `INDETERMINATE`. |
| Modern and legacy REST | implemented | Modern create and list. One legacy operation reached `succeeded`. |
| HR feeds and lifecycle scenarios | implemented | `GET /hr/people`. Scenario files are listed by `./lab scenario list`. |
| OpenLDAP pack | implemented | Container healthy. Base organizational units present. `acl.conf` and `overlays.conf` are not applied by the image bootstrap. |
| JDBC client | implemented | Not connected to a database. |
| Five-view workbench | implemented | HTTP 200 from `./lab doctor`. |
| Flagship journey executed | not run | Provision, sign in, revoke, and the next-request denial have not been run. |
