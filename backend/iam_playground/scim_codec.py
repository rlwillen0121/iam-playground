"""SCIM JSON for the supported subset. Binding fields are rejected, not stored."""

from __future__ import annotations

import re
import uuid

from iam_playground.errors import ScimError
from iam_playground.records import GroupRecord, UserInput, UserRecord

CORE_USER = "urn:ietf:params:scim:schemas:core:2.0:User"
CORE_GROUP = "urn:ietf:params:scim:schemas:core:2.0:Group"
ENTERPRISE_URN = "urn:ietf:params:scim:schemas:extension:enterprise:2.0:User"
LIST_RESPONSE = "urn:ietf:params:scim:api:messages:2.0:ListResponse"
PATCH_OP = "urn:ietf:params:scim:api:messages:2.0:PatchOp"
ERROR_URN = "urn:ietf:params:scim:api:messages:2.0:Error"
SERVICE_PROVIDER = "urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig"
RESOURCE_TYPE = "urn:ietf:params:scim:schemas:core:2.0:ResourceType"
SCHEMA_URN = "urn:ietf:params:scim:schemas:core:2.0:Schema"

_BINDING_KEYS = {"issuer", "subject", "binding", "accountbinding", "account_binding"}
_USER_PATHS = {
    "active": "active",
    "name.givenname": "name.givenName",
    "name.familyname": "name.familyName",
    "emails": "emails",
    f"{ENTERPRISE_URN}:employeenumber".lower(): "employeeNumber",
    f"{ENTERPRISE_URN}:department".lower(): "department",
}


def canonical_uuid(value: object) -> str | None:
    if not isinstance(value, str):
        return None
    try:
        return str(uuid.UUID(value))
    except ValueError:
        return None


def reject_binding_keys(value: object) -> None:
    if isinstance(value, dict):
        for key, child in value.items():
            if isinstance(key, str) and key.lower() in _BINDING_KEYS:
                raise ScimError(
                    400,
                    "issuer, subject, and bindings cannot be set through SCIM",
                    "invalidValue",
                )
            reject_binding_keys(child)
    elif isinstance(value, list):
        for item in value:
            reject_binding_keys(item)


def parse_user_create(body: object) -> UserInput:
    document = _object(body)
    reject_binding_keys(document)
    _only_keys(
        document,
        {"schemas", "id", "meta", "actor_id", "externalId", "userName", "name", "emails", "active", ENTERPRISE_URN},
    )
    _user_schemas(document.get("schemas"))
    user_name = document.get("userName")
    if not isinstance(user_name, str) or user_name == "":
        raise ScimError(400, "userName is required", "invalidValue")
    given_name, family_name = _name_pair(document.get("name")) if "name" in document else ("", "")
    email = _one_email(document["emails"]) if "emails" in document and document["emails"] is not None else ""
    active = True
    if "active" in document:
        if not isinstance(document["active"], bool):
            raise ScimError(400, "active must be a boolean", "invalidValue")
        active = document["active"]
    employee_number, department = _enterprise(document.get(ENTERPRISE_URN)) if ENTERPRISE_URN in document else ("", "")
    return UserInput(
        external_id=_external_id(document),
        user_name=user_name,
        active=active,
        given_name=given_name,
        family_name=family_name,
        email=email,
        employee_number=employee_number,
        department=department,
    )


def parse_group_create(body: object) -> tuple[str, str | None, list[str]]:
    document = _object(body)
    reject_binding_keys(document)
    _only_keys(document, {"schemas", "id", "meta", "actor_id", "externalId", "displayName", "members"})
    schemas = document.get("schemas")
    if schemas is not None and schemas != [CORE_GROUP]:
        raise ScimError(400, "unsupported schema", "invalidValue")
    display_name = document.get("displayName")
    if not isinstance(display_name, str) or display_name == "":
        raise ScimError(400, "displayName is required", "invalidValue")
    members: list[str] = []
    if "members" in document and document["members"] is not None:
        members = member_values(document["members"])
    return display_name, _external_id(document), members


def patch_operations(body: object) -> list[object]:
    document = _object(body)
    reject_binding_keys(document)
    _only_keys(document, {"schemas", "Operations", "actor_id"})
    if "schemas" in document and document["schemas"] != [PATCH_OP]:
        raise ScimError(400, "unsupported patch schema", "invalidValue")
    operations = document.get("Operations")
    if not isinstance(operations, list) or not operations:
        raise ScimError(400, "Operations must be a non-empty list", "invalidSyntax")
    return operations


def apply_user_operation(user: UserRecord, operation: object) -> None:
    if not isinstance(operation, dict):
        raise ScimError(400, "operation is invalid", "invalidSyntax")
    reject_binding_keys(operation)
    name = operation.get("op")
    if not isinstance(name, str) or name.lower() != "replace":
        raise ScimError(400, "user patch only supports replace", "invalidValue")
    path = operation.get("path")
    if path is None:
        value = operation.get("value")
        if not isinstance(value, dict):
            raise ScimError(400, "replace value must be an object", "invalidValue")
        _apply_user_object(user, value)
        return
    if not isinstance(path, str):
        raise ScimError(400, "path is not supported", "invalidPath")
    _assign_user_field(user, _user_path(path), operation.get("value"))


def group_change(operation: object) -> tuple[str, list[str]]:
    if not isinstance(operation, dict):
        raise ScimError(400, "operation is invalid", "invalidSyntax")
    reject_binding_keys(operation)
    name = operation.get("op")
    if not isinstance(name, str):
        raise ScimError(400, "operation is invalid", "invalidSyntax")
    kind = name.lower()
    path = operation.get("path")
    if kind == "add":
        if not isinstance(path, str) or path.lower() != "members":
            raise ScimError(400, "only members can be added", "invalidPath")
        return "add", member_values(operation.get("value"))
    if kind == "remove":
        if not isinstance(path, str):
            raise ScimError(400, "member remove filter is not supported", "invalidPath")
        return "remove", [member_remove_id(path)]
    raise ScimError(400, "group patch only supports add and remove of members", "invalidValue")


def member_values(value: object) -> list[str]:
    items = value if isinstance(value, list) else [value]
    if not items:
        raise ScimError(400, "members value is required", "invalidValue")
    found: list[str] = []
    seen: set[str] = set()
    for item in items:
        if not isinstance(item, dict):
            raise ScimError(400, "member value must be a user id", "invalidValue")
        reject_binding_keys(item)
        for key in item:
            if key not in {"value", "type", "display"}:
                raise ScimError(400, "member attribute is not supported", "invalidValue")
        if item.get("type") not in (None, "User"):
            raise ScimError(400, "only User members are supported", "invalidValue")
        canonical = canonical_uuid(item.get("value"))
        if canonical is None:
            raise ScimError(400, "member value is not a user id", "invalidValue")
        if canonical not in seen:
            seen.add(canonical)
            found.append(canonical)
    return found


def member_remove_id(path: str) -> str:
    if not path.lower().startswith("members[") or not path.endswith("]"):
        raise ScimError(400, "member remove filter is not supported", "invalidPath")
    inner = path[len("members[") : -1].strip()
    match = re.match(r"^value\s+eq\s+([\s\S]+)$", inner, re.IGNORECASE)
    if match is None:
        raise ScimError(400, "member remove filter is not supported", "invalidFilter")
    canonical = canonical_uuid(_parse_member_quoted(match.group(1).strip()))
    if canonical is None:
        raise ScimError(400, "member value is not a user id", "invalidValue")
    return canonical


def user_resource(user: UserRecord) -> dict[str, object]:
    body: dict[str, object] = {
        "schemas": [CORE_USER, ENTERPRISE_URN],
        "id": user.id,
        "userName": user.user_name,
        "name": {"givenName": user.given_name, "familyName": user.family_name},
        "active": user.active,
        ENTERPRISE_URN: {
            "employeeNumber": user.employee_number,
            "department": user.department,
        },
        "meta": {
            "resourceType": "User",
            "location": f"/apps/{user.app_id}/scim/v2/Users/{user.id}",
        },
    }
    if user.email:
        body["emails"] = [{"value": user.email, "type": "work", "primary": True}]
    else:
        body["emails"] = []
    if user.external_id is not None:
        body["externalId"] = user.external_id
    return body


def group_resource(group: GroupRecord, member_ids: list[str]) -> dict[str, object]:
    body: dict[str, object] = {
        "schemas": [CORE_GROUP],
        "id": group.id,
        "displayName": group.display_name,
        "members": [{"value": member_id, "type": "User"} for member_id in member_ids],
        "meta": {
            "resourceType": "Group",
            "location": f"/apps/{group.app_id}/scim/v2/Groups/{group.id}",
        },
    }
    if group.external_id is not None:
        body["externalId"] = group.external_id
    return body


def list_body(resources: list[object], total: int, start_index: int) -> dict[str, object]:
    return {
        "schemas": [LIST_RESPONSE],
        "totalResults": total,
        "startIndex": start_index,
        "itemsPerPage": len(resources),
        "Resources": resources,
    }


def _object(body: object) -> dict:
    if not isinstance(body, dict):
        raise ScimError(400, "request body must be an object", "invalidSyntax")
    return body


def _only_keys(document: dict, allowed: set[str]) -> None:
    for key in document:
        if key not in allowed:
            raise ScimError(400, "unsupported attribute", "invalidValue")


def _user_schemas(schemas: object) -> None:
    if schemas is None:
        return
    if not isinstance(schemas, list) or any(item not in {CORE_USER, ENTERPRISE_URN} for item in schemas):
        raise ScimError(400, "unsupported schema", "invalidValue")


def _external_id(document: dict) -> str | None:
    if "externalId" not in document or document["externalId"] is None:
        return None
    if not isinstance(document["externalId"], str):
        raise ScimError(400, "externalId must be a string", "invalidValue")
    return document["externalId"]


def _name_pair(value: object) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ScimError(400, "name is invalid", "invalidValue")
    _only_keys(value, {"givenName", "familyName"})
    given = _string(value["givenName"], "givenName") if "givenName" in value else ""
    family = _string(value["familyName"], "familyName") if "familyName" in value else ""
    return given, family


def _enterprise(value: object) -> tuple[str, str]:
    if not isinstance(value, dict):
        raise ScimError(400, "enterprise extension is invalid", "invalidValue")
    _only_keys(value, {"employeeNumber", "department"})
    employee = _string(value["employeeNumber"], "employeeNumber") if "employeeNumber" in value else ""
    department = _string(value["department"], "department") if "department" in value else ""
    return employee, department


def _string(value: object, name: str) -> str:
    if not isinstance(value, str):
        raise ScimError(400, f"{name} must be a string", "invalidValue")
    return value


def _one_email(value: object) -> str:
    items = value if isinstance(value, list) else [value]
    if len(items) != 1:
        raise ScimError(400, "only one work email is supported", "invalidValue")
    item = items[0]
    if not isinstance(item, dict):
        raise ScimError(400, "email is invalid", "invalidValue")
    reject_binding_keys(item)
    _only_keys(item, {"value", "type", "primary"})
    if item.get("type") not in (None, "work"):
        raise ScimError(400, "only a work email is supported", "invalidValue")
    return _string(item.get("value"), "email value")


def _user_path(path: str) -> str:
    field = _USER_PATHS.get(path.lower())
    if field is None:
        raise ScimError(400, "path is not supported", "invalidPath")
    return field


def _apply_user_object(user: UserRecord, value: dict) -> None:
    _only_keys(value, {"active", "name", "emails", ENTERPRISE_URN})
    if "active" in value:
        _assign_user_field(user, "active", value["active"])
    if "name" in value:
        given_name, family_name = _name_pair(value["name"])
        if "givenName" in value["name"]:
            user.given_name = given_name
        if "familyName" in value["name"]:
            user.family_name = family_name
    if "emails" in value:
        _assign_user_field(user, "emails", value["emails"])
    if ENTERPRISE_URN in value:
        employee_number, department = _enterprise(value[ENTERPRISE_URN])
        enterprise = value[ENTERPRISE_URN]
        if "employeeNumber" in enterprise:
            user.employee_number = employee_number
        if "department" in enterprise:
            user.department = department


def _assign_user_field(user: UserRecord, field: str, value: object) -> None:
    if field == "active":
        if not isinstance(value, bool):
            raise ScimError(400, "active must be a boolean", "invalidValue")
        user.active = value
        return
    if field == "name.givenName":
        user.given_name = _string(value, "givenName")
        return
    if field == "name.familyName":
        user.family_name = _string(value, "familyName")
        return
    if field == "emails":
        user.email = _one_email(value)
        return
    if field == "employeeNumber":
        user.employee_number = _string(value, "employeeNumber")
        return
    if field == "department":
        user.department = _string(value, "department")
        return
    raise ScimError(400, "path is not supported", "invalidPath")


def _parse_member_quoted(rest: str) -> str:
    if len(rest) < 2 or not rest.startswith('"') or not rest.endswith('"'):
        raise ScimError(400, "member remove filter is malformed", "invalidFilter")
    inner = rest[1:-1]
    if '"' in inner or "\\" in inner:
        raise ScimError(400, "member remove filter is malformed", "invalidFilter")
    return inner
