# Security

IAM Playground is a local lab. Do not point it at a production tenant.

Published ports bind to `127.0.0.1`. Loopback binding is not the whole security model. The demo cookie is `HttpOnly` and `SameSite=Lax`, and it is not marked `Secure`, because the local issuer is HTTP. That exception is specific to this lab.

`.env` is gitignored. `./lab up` generates its values and does not print them. Do not commit passwords, bearer tokens, client secrets, authorization codes, cookies, or model keys.

Synthetic fixture passwords live in `fixtures/enterprise-small-v1.json` and `infra/ldap/seed.ldif`. They are lab data. Do not reuse them anywhere else. JSON export is written to drop `synthetic-lab-` strings, authorization headers, and cookies.

The public repository is [github.com/rlwillen0121/iam-playground](https://github.com/rlwillen0121/iam-playground). Report a vulnerability through a GitHub private security advisory. Do not open a public issue for an unpublished credential or a bypass.

Trusted account binding is an issuer and subject pair set by the admin API. A normal SCIM client cannot write that binding. The agent MCP token cannot grant `Administrators` or call app-b.
