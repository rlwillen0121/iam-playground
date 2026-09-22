# OpenLDAP

This is generic OpenLDAP for this configuration, not Active Directory. Existing established sessions are not revoked when new binds are denied.

`infra/ldap/compose.fragment.yml` is copied into `infra/compose.yml`. A local session started `osixia/openldap:1.5.0` and an admin search returned `ou=People`, `ou=Groups`, `ou=ServiceAccounts`, and `ou=System`. `LDAP-01` through `LDAP-08` have not been run as named proofs.

The image bootstrap applies `infra/ldap/seed.ldif` and the schema file. It does not apply `infra/ldap/slapd/acl.conf` or `overlays.conf`, because that bootstrap identity cannot change `cn=config`. Those two files remain the intended ACL and overlay. `clients/ldap/fake.py` enforces that ACL in process. A healthy container is not evidence that the aggregator bind was denied a write.

## Server

| Item | Value |
| --- | --- |
| Image | `osixia/openldap:1.5.0` (image Dockerfile packages OpenLDAP 2.4.57) |
| Domain | `iam.test` |
| Base DN | `dc=iam,dc=test` |
| Listen | `127.0.0.1:389` (LDAP) and `127.0.0.1:636` (LDAPS) only |
| Hostname inside the container | `ldap.iam.test` |
| Data | Independent of SCIM, REST, and JDBC |

`LDAP_ADMIN_PASSWORD` and `LDAP_CONFIG_PASSWORD` come from the environment. They are not stored in this repo. The image creates `cn=admin,dc=iam,dc=test` from the admin password.

TLS is on. The image writes a CA and a certificate for `ldap.iam.test` under `/container/service/slapd/assets/certs/` (the `openldap-certs` volume). A client that checks the server name has to reach `ldap.iam.test` and trust that CA. Client certificates are not required (`LDAP_TLS_VERIFY_CLIENT=try`). Port 389 is left open on loopback so a clear-text probe and a TLS failure can be told apart from a locked account. Loopback binding is not the whole security model.

First start needs `--copy-service`. The image substitutes `{{ LDAP_BASE_DN }}` and `{{ LDAP_BACKEND }}` in the mounted LDIF and would otherwise edit those files in place.

## Directory

Organizational units in `infra/ldap/seed.ldif`:

- `ou=People,dc=iam,dc=test`
- `ou=Groups,dc=iam,dc=test`
- `ou=ServiceAccounts,dc=iam,dc=test`
- `ou=System,dc=iam,dc=test`

| Bind | DN | Authority |
| --- | --- | --- |
| Aggregation | `cn=aggregator,ou=ServiceAccounts,dc=iam,dc=test` | Read. Cannot write. Cannot read `userPassword`. |
| Provisioning | `cn=provisioner,ou=ServiceAccounts,dc=iam,dc=test` | Write under `ou=People` and `ou=Groups`, including `children` so entries can be added. Read elsewhere. No write outside those two subtrees. |
| Administrator | `cn=admin,dc=iam,dc=test` | Manage, from the image bootstrap. Not a demonstration identity. |

Seeded service-account passwords are synthetic lab values: `synthetic-lab-aggregator` and `synthetic-lab-provisioner`. OpenLDAP `write` includes `read`, so the provisioner can read `userPassword` under People and Groups. The aggregator cannot.

People entries are added by the provisioning bind. They are not copied from the SCIM database.

## Groups, memberOf, and rename

`iamGroup` in `infra/ldap/schema/playground.schema` is structural, requires `cn`, and may omit `member`. `cn=empty,ou=Groups,dc=iam,dc=test` is that empty group. `groupOfNames` and `groupOfUniqueNames` are not used for this, because each requires a member.

`infra/ldap/slapd/overlays.conf` points the `memberof` overlay at `iamGroup` / `member` / `memberOf`. Reverse membership is the overlay's operational attribute. Clients write `member` and read `memberOf` (operational attributes are returned for `+` or an explicit attribute list).

The `refint` overlay rewrites `member`, `memberOf`, `manager`, `owner`, and `uniqueMember` on rename, and removes those values on delete. It runs as the database root DN. Because `member` is optional, the last member can be removed and the group remains. There is no placeholder DN.

## Disable

See `infra/ldap/disable.md`. The disable operation adds `pwdAccountLockedTime: 000001010000Z` on the person entry. The `ppolicy` overlay and `cn=default,ou=System,dc=iam,dc=test` (`pwdLockout: TRUE`, `pwdAttribute: userPassword`) make a later bind fail. An already bound LDAP connection stays bound. An application session created before the lock is also left in place.

## Client

`clients/ldap/client.py` does not encode BER and does not open a socket. `search`, `add`, `modify`, `rename`, `delete`, `bind`, and `disable` / `disable_user` each return a list of operations. Every operation is a dict with `op`, `dn`, and `changes`. `disable_user(dn)` is a modify that adds the lock value above.

`apply_plan(plan, connection)` calls `connection.search`, `add`, `modify`, `delete`, `rename`, or `bind` with `(dn, changes)` when a connection is passed. Without a connection it returns the plan. Do not log a plan that contains a bind password.

`FakeConnection` in `clients/ldap/fake.py` loads `infra/ldap/seed.ldif` unless a directory dict is passed. Sharing that dict between two connections shares entries and not binds. Aggregator writes raise `PermissionError`. A locked user fails the next `bind` with `BindError.reason == "locked"`. A healthy unlocked user with the right password binds. Empty groups are allowed. Rename rewrites member DNs stored in the directory, and `memberOf` is rebuilt from `member`.
