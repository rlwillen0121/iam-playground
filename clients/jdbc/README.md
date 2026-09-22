# Legacy SQL JDBC client

The acceptance path is this Java client, not an HTTP shim. `LabJdbc` connects with pgJDBC through `DriverManager`. It does not expose an HTTP service.

`infra/postgres/packs/jdbc.sql` creates `legacy_app`. Rows in `legacy_app.accounts` are application accounts, not PostgreSQL logins. `legacy_reader` has SELECT only. `legacy_provisioner` has INSERT and UPDATE on those tables, SELECT on `legacy_app.roles` so a grant can resolve a role name, and DELETE only on `legacy_app.account_roles` so a grant can be revoked. Neither role is a superuser. Passwords are not in the pack. `infra/postgres/init.sh` applies it after `schema.sql`. A second apply does not drop rows.

Statements are parameterized. Each call uses an explicit transaction on an autocommit connection. `createAccount` sets `status` to `active`. `disableAccount` sets it to `disabled`. `readAccount` returns null when the account is absent. `grantRole` and `revokeRole` take a role name. A missing role fails `account_roles_role_fk`. Inserting a blank name into `legacy_app.roles` violates `roles_name_chk`.

`rollbackProof(connection)` starts a transaction, inserts an account, attempts a grant of a role name that is not in `legacy_app.roles`, rolls back, and returns without committing.

Pins: `org.postgresql:postgresql:42.7.5`, Java 17. No version ranges. The driver jar has to be on the classpath so `DriverManager` can load it. Reads use `legacy_reader`. Writes use `legacy_provisioner`. Do not connect as a superuser.

This client has not been executed against a database. `./lab jdbc verify` prints that the JDBC client is implemented and that the command does not open a database. That exit is not a connection.
