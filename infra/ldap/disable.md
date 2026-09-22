# Account disable

Disable is an OpenLDAP password-policy lock, not a custom `active` attribute and not an Active Directory `userAccountControl` flag.

The provisioning bind adds the operational attribute `pwdAccountLockedTime` with the value `000001010000Z`:

```text
dn: uid=alice,ou=People,dc=iam,dc=test
changetype: modify
add: pwdAccountLockedTime
pwdAccountLockedTime: 000001010000Z
```

`clients/ldap/client.py` `disable_user(dn)` returns that modify. It does not open a socket. `apply_plan` sends it with `connection.modify` when a connection is passed.

`000001010000Z` is the permanent administrative lock from `slapo-ppolicy`. The account stays locked until an administrator deletes the attribute. The overlay enforces the lock only when the effective policy has `pwdLockout: TRUE`. This directory's default policy is `cn=default,ou=System,dc=iam,dc=test`.

A new simple bind with the same password then fails. OpenLDAP still returns invalid credentials for that bind. `olcPPolicyUseLockout` is true, so a bind that also sends the password-policy request control gets `AccountLocked` in the password-policy response. The result code itself does not change.

Deleting `pwdAccountLockedTime` clears the lock:

```text
changetype: modify
delete: pwdAccountLockedTime
```

This does not revoke an LDAP connection that has already bound, and it does not revoke an application session established before the lock. Only a later bind is denied. A network or TLS failure is not a successful disable; check a healthy unlocked account on the same connection before treating a bind failure as account denial.
