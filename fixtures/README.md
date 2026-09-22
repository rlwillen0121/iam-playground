# Fixtures

Synthetic lab data only. No real people, customer URLs, or secrets.

## Flagship seed

`enterprise-small-v1.json` (`enterprise-small-v1`) is the flagship seed. Alice (`userName` `alice`) has an IdP identity and no SCIM account (`idpAccount` true, `scimUser` null).

## Paging set

`pagination-large-v1.json` (`pagination-large-v1`) is the paging set: 250 synthetic people, `page0001` through `page0250`. It is for paging tests and is not the flagship seed.

## Bad-data overlay

`overlays/inconsistent-v1.json` (`inconsistent-v1`) is a named bad-data overlay, separate from the healthy baseline. It labels three deliberate problems: a duplicate email across two synthetic people, a missing department, and a manager reference to an unknown employee number. It has no passwords.

## What the running lab applies

None of these fixtures are applied by the running lab except `enterprise-small-v1`. That is existing behavior and must not be changed. `pagination-large-v1` and `inconsistent-v1` are not seeds for the running lab.
