"""Discovery documents for this subset. They do not claim full SCIM compliance."""

from __future__ import annotations

from iam_playground.scim_codec import (
    CORE_GROUP,
    CORE_USER,
    ENTERPRISE_URN,
    RESOURCE_TYPE,
    SCHEMA_URN,
    SERVICE_PROVIDER,
    list_body,
)

_SUBSET = (
    "Subset only. Not a complete RFC 7643 or RFC 7644 implementation. "
    "Equality filters are limited to the attributes marked supported below."
)


def _attribute(
    name: str,
    type_name: str,
    *,
    multi: bool = False,
    required: bool = False,
    case_exact: bool = False,
    mutability: str = "readWrite",
    uniqueness: str = "none",
    description: str = "",
    sub_attributes: list[dict] | None = None,
) -> dict:
    body = {
        "name": name,
        "type": type_name,
        "multiValued": multi,
        "description": description,
        "required": required,
        "caseExact": case_exact,
        "mutability": mutability,
        "returned": "default",
        "uniqueness": uniqueness,
    }
    if sub_attributes is not None:
        body["subAttributes"] = sub_attributes
    return body


def service_provider_config() -> dict:
    return {
        "schemas": [SERVICE_PROVIDER],
        "patch": {"supported": True},
        "bulk": {"supported": False, "maxOperations": 0, "maxPayloadSize": 0},
        "filter": {"supported": True, "maxResults": 100},
        "changePassword": {"supported": False},
        "sort": {"supported": False},
        "etag": {"supported": False},
        "authenticationSchemes": [
            {
                "type": "oauthbearertoken",
                "name": "Bearer token",
                "description": (
                    "One bearer token per application. "
                    "This server implements a subset of SCIM "
                    "(equality filters, limited PATCH, no PUT, bulk, sort, or ETag) "
                    "and is not a complete RFC 7643 or RFC 7644 implementation."
                ),
                "specUri": "https://www.rfc-editor.org/rfc/rfc6750.html",
                "primary": True,
            }
        ],
        "meta": {"resourceType": "ServiceProviderConfig"},
    }


def resource_types() -> dict:
    resources = [
        {
            "schemas": [RESOURCE_TYPE],
            "id": "User",
            "name": "User",
            "endpoint": "/Users",
            "description": _SUBSET,
            "schema": CORE_USER,
            "schemaExtensions": [{"schema": ENTERPRISE_URN, "required": False}],
            "meta": {"resourceType": "ResourceType"},
        },
        {
            "schemas": [RESOURCE_TYPE],
            "id": "Group",
            "name": "Group",
            "endpoint": "/Groups",
            "description": _SUBSET,
            "schema": CORE_GROUP,
            "meta": {"resourceType": "ResourceType"},
        },
    ]
    return list_body(resources, len(resources), 1)


def resource_type(type_id: str) -> dict | None:
    for resource in resource_types()["Resources"]:
        if resource["id"] == type_id:
            return resource
    return None


def schemas() -> dict:
    documents = [_user_schema(), _enterprise_schema(), _group_schema()]
    return list_body(documents, len(documents), 1)


def schema_by_id(schema_id: str) -> dict | None:
    for document in schemas()["Resources"]:
        if document["id"] == schema_id:
            return document
    return None


def _user_schema() -> dict:
    return {
        "schemas": [SCHEMA_URN],
        "id": CORE_USER,
        "name": "User",
        "description": _SUBSET,
        "attributes": [
            _attribute(
                "userName",
                "string",
                required=True,
                case_exact=False,
                mutability="immutable",
                uniqueness="server",
                description="Equality filter supported. Stored as submitted. Unique per application, case-insensitive.",
            ),
            _attribute(
                "externalId",
                "string",
                case_exact=True,
                mutability="immutable",
                description="Equality filter supported. Not unique.",
            ),
            _attribute(
                "name",
                "complex",
                description="givenName and familyName only.",
                sub_attributes=[
                    _attribute("givenName", "string", description="PATCH replace supported."),
                    _attribute("familyName", "string", description="PATCH replace supported."),
                ],
            ),
            _attribute(
                "emails",
                "complex",
                multi=True,
                description="One work email. Equality filter on emails.value is supported.",
                sub_attributes=[
                    _attribute("value", "string"),
                    _attribute("type", "string", description="work only."),
                    _attribute("primary", "boolean"),
                ],
            ),
            _attribute("active", "boolean", description="Equality filter and PATCH replace supported."),
        ],
        "meta": {"resourceType": "Schema"},
    }


def _enterprise_schema() -> dict:
    return {
        "schemas": [SCHEMA_URN],
        "id": ENTERPRISE_URN,
        "name": "EnterpriseUser",
        "description": "employeeNumber and department only. " + _SUBSET,
        "attributes": [
            _attribute("employeeNumber", "string", description="PATCH replace supported."),
            _attribute("department", "string", description="PATCH replace supported."),
        ],
        "meta": {"resourceType": "Schema"},
    }


def _group_schema() -> dict:
    return {
        "schemas": [SCHEMA_URN],
        "id": CORE_GROUP,
        "name": "Group",
        "description": _SUBSET,
        "attributes": [
            _attribute(
                "displayName",
                "string",
                required=True,
                case_exact=True,
                mutability="immutable",
                uniqueness="server",
                description="Equality filter supported. Unique per application, case-sensitive.",
            ),
            _attribute(
                "externalId",
                "string",
                case_exact=True,
                mutability="immutable",
                description="Not filtered in this subset. Not unique.",
            ),
            _attribute(
                "members",
                "complex",
                multi=True,
                description="Add by value. Remove with members[value eq \"id\"].",
                sub_attributes=[
                    _attribute("value", "string", description="SCIM user id in this application."),
                    _attribute("type", "string", description="User only."),
                ],
            ),
        ],
        "meta": {"resourceType": "Schema"},
    }
