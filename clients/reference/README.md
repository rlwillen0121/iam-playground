# Reference SCIM client

`scim_client.py` is the reference protocol caller. It speaks HTTP to one application's SCIM endpoints and nothing else. It does not open a database connection and it does not import `iam_playground`.

`scenario_scim_login_revoke.py` is the reference driver for `./lab scenario run scim-login-revoke --mode reference`. It uses this client and HTTP for the admin binding. It does not open a database and it does not decide a verdict. The verifier lives in `clients/verifier/verifier.py` and only reads.

The client uses `urllib.request` from the standard library. It does not use environment proxies, and it does not follow redirects, so the bearer token stays on the URL it was given.

## Calls

`ScimClient(base_url, app_id, token)` sends `Authorization: Bearer` on every request. It does not send `actor_id`. It does not send issuer or subject binding fields.

- `create_user`, `get_user`, `list_users(start_index, count, filter)`, `patch_user`, `delete_user`
- `create_group`, `list_groups(start_index, count, filter)`, `patch_group_add_member`, `patch_group_remove_member`, `delete_group`
- `get_service_provider_config`, `get_schemas`

Paths are `/apps/{app_id}/scim/v2/Users`, `/apps/{app_id}/scim/v2/Groups`, `/apps/{app_id}/scim/v2/ServiceProviderConfig`, and `/apps/{app_id}/scim/v2/Schemas`.

`start_index` is 1-based and is sent as `startIndex`. `count` is sent as `count`. The client does not shift those values. An equality filter is passed through as the SCIM `filter` query string, including an empty string. `None` omits the parameter. The client does not drop or rewrite a filter.

List methods return the server's document unchanged. A missing `Resources` array is not replaced with an empty list.

`patch_user` sends one PATCH whose `replace` operations cover the attributes you pass: `active`, `given_name`, `family_name`, `email`, `employee_number`, and `department`. Group helpers add or remove one member.

`externalId` is correlation data. It is not a uniqueness key the client may assume.

Bodies use `application/scim+json`. A non-success status raises `ScimClientError` (`status`, `detail`, `scim_type`). A connection failure raises `urllib.error.URLError`.

```python
client = ScimClient("http://127.0.0.1:8090", "app-a", token)
client.create_user(
    "alice@example.com",
    external_id="hr-alice",
    given_name="Alice",
    family_name="Example",
    email="alice@example.com",
    active=True,
)
client.list_users(1, 50, 'userName eq "alice@example.com"')
client.patch_group_add_member(group_id, user_id)
```

## Not wrapped

PUT, bulk, sort, and ETag are not wrapped.

## Tests

From the repository root. The tests use a local fake HTTP server and do not use a live network:

```bash
python -m unittest clients/reference/test_scim_client.py
```
