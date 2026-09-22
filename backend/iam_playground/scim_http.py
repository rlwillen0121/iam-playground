"""SCIM HTTP routes. The actor is the application credential, never a JSON field."""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse, Response

from iam_playground.auth import bearer_matches
from iam_playground.constants import APPLICATIONS
from iam_playground.errors import DependencyFailure, ScimError
from iam_playground.scim_codec import ERROR_URN
from iam_playground.scim_filter import parse_page
from iam_playground.scim_meta import resource_type, resource_types, schema_by_id, schemas, service_provider_config
from iam_playground import scim_service

SCIM_MEDIA = "application/scim+json"
StoreFactory = Callable[[], object]
TokenProvider = Callable[[], dict[str, str]]


def env_scim_tokens() -> dict[str, str]:
    return {
        "app-a": os.environ.get("SCIM_TOKEN_APP_A", ""),
        "app-b": os.environ.get("SCIM_TOKEN_APP_B", ""),
    }


def env_scim_read_tokens() -> dict[str, str]:
    return {
        "app-a": os.environ.get("SCIM_TOKEN_APP_A_READ", ""),
        "app-b": os.environ.get("SCIM_TOKEN_APP_B_READ", ""),
    }


def mount_scim(
    app: FastAPI,
    *,
    store_factory: StoreFactory,
    token_provider: TokenProvider,
    read_token_provider: TokenProvider | None = None,
) -> None:
    read_tokens = read_token_provider or env_scim_read_tokens

    def actor_for(app_id: str, authorization: str | None, *, mutation: bool) -> str:
        if app_id not in APPLICATIONS:
            raise ScimError(404, "application not found")
        # A write token keeps full access. A read token is a different credential.
        if bearer_matches(authorization, token_provider().get(app_id, "")):
            return f"scim:{app_id}"
        if bearer_matches(authorization, read_tokens().get(app_id, "")):
            if mutation:
                raise ScimError(403, "read credential cannot modify")
            return f"scim:{app_id}:read"
        raise ScimError(401, "bearer token required")

    def finish(work: Callable[[], object]) -> object:
        try:
            return work()
        except ScimError as exc:
            return _error(exc)
        except DependencyFailure:
            return _error(ScimError(503, "dependency"))

    @app.get("/apps/{app_id}/scim/v2/ServiceProviderConfig")
    def service_provider(app_id: str, authorization: str | None = Header(default=None)):
        return finish(lambda: _checked(actor_for, app_id, authorization, service_provider_config()))

    @app.get("/apps/{app_id}/scim/v2/ResourceTypes")
    def list_resource_types(app_id: str, authorization: str | None = Header(default=None)):
        return finish(lambda: _checked(actor_for, app_id, authorization, resource_types()))

    @app.get("/apps/{app_id}/scim/v2/ResourceTypes/{type_id}")
    def one_resource_type(
        app_id: str,
        type_id: str,
        authorization: str | None = Header(default=None),
    ):
        def work() -> object:
            actor_for(app_id, authorization, mutation=False)
            found = resource_type(type_id)
            if found is None:
                raise ScimError(404, "resource type not found")
            return _json(found)

        return finish(work)

    @app.get("/apps/{app_id}/scim/v2/Schemas")
    def list_schemas(app_id: str, authorization: str | None = Header(default=None)):
        return finish(lambda: _checked(actor_for, app_id, authorization, schemas()))

    @app.get("/apps/{app_id}/scim/v2/Schemas/{schema_id}")
    def one_schema(app_id: str, schema_id: str, authorization: str | None = Header(default=None)):
        def work() -> object:
            actor_for(app_id, authorization, mutation=False)
            found = schema_by_id(schema_id)
            if found is None:
                raise ScimError(404, "schema not found")
            return _json(found)

        return finish(work)

    @app.get("/apps/{app_id}/scim/v2/Users")
    def list_users(app_id: str, request: Request, authorization: str | None = Header(default=None)):
        def work() -> object:
            actor_for(app_id, authorization, mutation=False)
            _reject_sort(request)
            start_index, count = parse_page(
                request.query_params.get("startIndex"),
                request.query_params.get("count"),
            )
            return _json(
                scim_service.list_users(
                    store_factory(),
                    app_id,
                    request.query_params.get("filter"),
                    start_index,
                    count,
                )
            )

        return finish(work)

    @app.post("/apps/{app_id}/scim/v2/Users")
    async def create_user(app_id: str, request: Request, authorization: str | None = Header(default=None)):
        try:
            body = await _read_body(request)
        except ScimError as exc:
            return _error(exc)

        def work() -> object:
            actor = actor_for(app_id, authorization, mutation=True)
            resource = scim_service.create_user(store_factory(), app_id, actor, body)
            return _json(resource, 201, {"Location": str(resource["meta"]["location"])})

        return finish(work)

    @app.get("/apps/{app_id}/scim/v2/Users/{user_id}")
    def get_user(app_id: str, user_id: str, authorization: str | None = Header(default=None)):
        def work() -> object:
            actor_for(app_id, authorization, mutation=False)
            return _json(scim_service.get_user(store_factory(), app_id, user_id))

        return finish(work)

    @app.patch("/apps/{app_id}/scim/v2/Users/{user_id}")
    async def patch_user(
        app_id: str,
        user_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            body = await _read_body(request)
        except ScimError as exc:
            return _error(exc)

        def work() -> object:
            actor = actor_for(app_id, authorization, mutation=True)
            return _json(scim_service.patch_user(store_factory(), app_id, actor, user_id, body))

        return finish(work)

    @app.delete("/apps/{app_id}/scim/v2/Users/{user_id}")
    def delete_user(app_id: str, user_id: str, authorization: str | None = Header(default=None)):
        def work() -> object:
            actor = actor_for(app_id, authorization, mutation=True)
            scim_service.delete_user(store_factory(), app_id, actor, user_id)
            return Response(status_code=204)

        return finish(work)

    @app.get("/apps/{app_id}/scim/v2/Groups")
    def list_groups(app_id: str, request: Request, authorization: str | None = Header(default=None)):
        def work() -> object:
            actor_for(app_id, authorization, mutation=False)
            _reject_sort(request)
            start_index, count = parse_page(
                request.query_params.get("startIndex"),
                request.query_params.get("count"),
            )
            return _json(
                scim_service.list_groups(
                    store_factory(),
                    app_id,
                    request.query_params.get("filter"),
                    start_index,
                    count,
                )
            )

        return finish(work)

    @app.post("/apps/{app_id}/scim/v2/Groups")
    async def create_group(app_id: str, request: Request, authorization: str | None = Header(default=None)):
        try:
            body = await _read_body(request)
        except ScimError as exc:
            return _error(exc)

        def work() -> object:
            actor = actor_for(app_id, authorization, mutation=True)
            resource = scim_service.create_group(store_factory(), app_id, actor, body)
            return _json(resource, 201, {"Location": str(resource["meta"]["location"])})

        return finish(work)

    @app.get("/apps/{app_id}/scim/v2/Groups/{group_id}")
    def get_group(app_id: str, group_id: str, authorization: str | None = Header(default=None)):
        def work() -> object:
            actor_for(app_id, authorization, mutation=False)
            return _json(scim_service.get_group(store_factory(), app_id, group_id))

        return finish(work)

    @app.patch("/apps/{app_id}/scim/v2/Groups/{group_id}")
    async def patch_group(
        app_id: str,
        group_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            body = await _read_body(request)
        except ScimError as exc:
            return _error(exc)

        def work() -> object:
            actor = actor_for(app_id, authorization, mutation=True)
            return _json(scim_service.patch_group(store_factory(), app_id, actor, group_id, body))

        return finish(work)

    @app.delete("/apps/{app_id}/scim/v2/Groups/{group_id}")
    def delete_group(app_id: str, group_id: str, authorization: str | None = Header(default=None)):
        def work() -> object:
            actor = actor_for(app_id, authorization, mutation=True)
            scim_service.delete_group(store_factory(), app_id, actor, group_id)
            return Response(status_code=204)

        return finish(work)

    @app.api_route("/apps/{app_id}/scim/v2/{rest:path}", methods=["PUT"])
    def put_unsupported(app_id: str, rest: str, authorization: str | None = Header(default=None)):
        del rest

        def work() -> object:
            actor_for(app_id, authorization, mutation=True)
            raise ScimError(501, "PUT is unsupported")

        return finish(work)


def _checked(actor_for: Callable, app_id: str, authorization: str | None, payload: dict) -> JSONResponse:
    actor_for(app_id, authorization, mutation=False)
    return _json(payload)


def _reject_sort(request: Request) -> None:
    if "sortBy" in request.query_params or "sortOrder" in request.query_params:
        raise ScimError(400, "sorting is unsupported", "invalidValue")


async def _read_body(request: Request) -> object:
    raw = await request.body()
    if not raw:
        raise ScimError(400, "request body is required", "invalidSyntax")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ScimError(400, "request body is not valid JSON", "invalidSyntax") from exc


def _json(payload: dict, status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload, headers=headers, media_type=SCIM_MEDIA)


def _error(exc: ScimError) -> JSONResponse:
    body: dict[str, str] = {
        "schemas": [ERROR_URN],
        "status": str(exc.status),
        "detail": exc.detail,
    }
    if exc.scim_type:
        body["scimType"] = exc.scim_type
    return JSONResponse(status_code=exc.status, content=body, media_type=SCIM_MEDIA)
