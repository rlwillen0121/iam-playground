"""HTTP JSON tools. Every provisioning call is authorized before a fault or a target call."""

from __future__ import annotations

import json
import os
from collections.abc import Callable

from fastapi import FastAPI, Header, Request
from fastapi.responses import JSONResponse

from iam_playground.mcp_pack.authz import (
    MUTATING_ACTIONS,
    PRINCIPALS,
    PROHIBITED_ACTIONS,
    REFERENCE,
    TOOL_ACTIONS,
    PrincipalGate,
    authorize,
    parse_tool_body,
    principal_from_header,
    reject_binding_fields,
    reject_control_fields,
    reject_query_controls,
    require_enabled,
)
from iam_playground.mcp_pack.errors import FaultStoreError, PackError
from iam_playground.mcp_pack.faults import (
    FaultCounter,
    FaultStore,
    apply_matched_fault,
    fault_status,
    fault_store_from_env,
    parse_fault_body,
    snapshot,
)
from iam_playground.mcp_pack.target import ScimTarget, TargetApi

_MAX_BODY = 65536
_DENY_METHODS = ["GET", "POST", "PUT", "PATCH", "DELETE"]
_DENY_PATHS = (
    "/bindings",
    "/bindings/{rest:path}",
    "/reset",
    "/fixtures",
    "/fixtures/{rest:path}",
    "/policy",
    "/shell",
    "/docker",
    "/docker/{rest:path}",
    "/verifier",
    "/verifier/{rest:path}",
    "/tools/bindings",
    "/tools/reset",
    "/tools/faults",
    "/tools/fixtures",
    "/tools/policy",
    "/tools/shell",
    "/tools/docker",
    "/tools/verifier",
)
TokenProvider = Callable[[], tuple[str, str]]


def env_mcp_tokens() -> tuple[str, str]:
    return (
        os.environ.get("MCP_AGENT_TOKEN", ""),
        os.environ.get("MCP_REFERENCE_TOKEN", ""),
    )


def create_app(
    *,
    fault_store: FaultStore | None = None,
    target_caller: TargetApi | None = None,
    token_provider: TokenProvider | None = None,
    principal_gate: PrincipalGate | None = None,
) -> FastAPI:
    store = fault_store if fault_store is not None else fault_store_from_env()
    caller = target_caller if target_caller is not None else ScimTarget()
    gate = principal_gate if principal_gate is not None else PrincipalGate()
    tokens = token_provider or env_mcp_tokens
    app = FastAPI(title="IAM Playground MCP", redirect_slashes=False)

    def fail(exc: PackError) -> JSONResponse:
        body = {"detail": exc.detail}
        if exc.source:
            body["source"] = exc.source
        return JSONResponse(status_code=exc.status, content=body)

    def store_failed() -> JSONResponse:
        return JSONResponse(status_code=503, content={"detail": "fault store unavailable"})

    @app.get("/healthz", response_model=None)
    def health(request: Request):
        # Health is not a provisioning tool and does not read fault counters.
        try:
            _reject_query(request)
        except PackError as exc:
            return fail(exc)
        return {"ok": True}

    @app.get("/faults", response_model=None)
    def get_faults(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            _reject_query(request)
            principal_from_header(authorization, tokens())
            return {"faults": snapshot(store)}
        except PackError as exc:
            return fail(exc)
        except FaultStoreError:
            return store_failed()

    @app.post("/faults", response_model=None)
    async def post_faults(
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            body = await _json_object(request, allow_empty=False)
            principal = principal_from_header(authorization, tokens())
            if principal != REFERENCE:
                raise PackError(403, "reference token required")
            reject_binding_fields(body)
            name, remaining, rule = parse_fault_body(body)
            store.put_counter(name, remaining, rule)
        except PackError as exc:
            return fail(exc)
        except FaultStoreError:
            return store_failed()
        return {"name": name, "remaining": remaining, "rule": rule}

    @app.post("/principals/{name}/disable", response_model=None)
    async def disable_principal(
        name: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            body = await _json_object(request, allow_empty=True)
            principal = principal_from_header(authorization, tokens())
            if principal != REFERENCE:
                raise PackError(403, "reference token required")
            reject_binding_fields(body)
            if body:
                raise PackError(400, "unsupported field")
            if name not in PRINCIPALS:
                raise PackError(404, "principal not found")
            gate.disable(name)
        except PackError as exc:
            return fail(exc)
        return {"name": name, "enabled": False}

    async def handle_tool(
        request: Request,
        authorization: str | None,
        action: str,
        success_status: int,
    ):
        try:
            body = await _json_object(request, allow_empty=False)
            principal = require_enabled(authorization, tokens(), gate)
            reject_binding_fields(body)
            if action in PROHIBITED_ACTIONS or action not in TOOL_ACTIONS:
                raise PackError(403, "action is not allowed")
            args = parse_tool_body(action, body)
            authorize(principal, action, args)
            try:
                fault = apply_matched_fault(store, mutation=action in MUTATING_ACTIONS)
            except FaultStoreError:
                return store_failed()
            if fault is not None and fault.name != "commit_before_response":
                return _fault_response(fault)
            try:
                result = _dispatch(caller, action, args)
            except PackError:
                raise
            except Exception:
                raise PackError(502, "target request failed") from None
        except PackError as exc:
            return fail(exc)
        if fault is not None:
            return _fault_response(fault)
        return JSONResponse(status_code=success_status, content=result)

    def mount_tool(action: str, success_status: int) -> None:
        async def endpoint(
            request: Request,
            authorization: str | None = Header(default=None),
        ):
            return await handle_tool(request, authorization, action, success_status)

        endpoint.__name__ = action
        app.add_api_route(
            f"/tools/{action}",
            endpoint,
            methods=["POST"],
            response_model=None,
        )

    for action in TOOL_ACTIONS:
        mount_tool(action, 201 if action == "create_account" else 200)

    async def deny(
        request: Request,
        authorization: str | None = Header(default=None),
        rest: str = "",
    ):
        del rest
        try:
            body = await _json_object(request, allow_empty=True)
            require_enabled(authorization, tokens(), gate)
            reject_binding_fields(body)
            raise PackError(403, "action is not allowed")
        except PackError as exc:
            return fail(exc)

    for path in _DENY_PATHS:
        app.add_api_route(
            path,
            deny,
            methods=_DENY_METHODS,
            response_model=None,
            include_in_schema=False,
        )

    return app


def _dispatch(caller: TargetApi, action: str, args: dict[str, str]) -> dict[str, object]:
    # Authorization and terminal faults return before this is reached.
    if action == "lookup_account":
        return caller.lookup_account(args["app_id"], args["user_name"])
    if action == "list_groups":
        return caller.list_groups(args["app_id"])
    if action == "create_account":
        return caller.create_account(
            args["app_id"],
            args["user_name"],
            args["email"],
            args["employee_number"],
            args["department"],
        )
    if action == "add_member":
        return caller.add_member(args["app_id"], args["group_name"], args["user_id"])
    if action == "remove_member":
        return caller.remove_member(args["app_id"], args["group_name"], args["user_id"])
    if action == "disable_account":
        return caller.disable_account(args["app_id"], args["user_id"])
    raise PackError(403, "action is not allowed")


def _fault_response(fault: FaultCounter) -> JSONResponse:
    status = fault_status(fault.name)
    if fault.name == "commit_before_response":
        detail = "response timed out"
        headers = None
    else:
        detail = f"fault {fault.rule}"
        headers = {"Retry-After": "1"}
    return JSONResponse(
        status_code=status,
        content={
            "detail": detail,
            "name": fault.name,
            "rule": fault.rule,
            "remaining": fault.remaining,
        },
        headers=headers,
    )


def _reject_query(request: Request) -> None:
    reject_query_controls(request.query_params.keys())
    if request.url.query:
        raise PackError(400, "query parameters are not accepted")


async def _json_object(request: Request, *, allow_empty: bool) -> dict[str, object]:
    _reject_query(request)
    raw = await request.body()
    if len(raw) > _MAX_BODY:
        raise PackError(400, "request is too large")
    if raw == b"":
        if allow_empty:
            return {}
        raise PackError(400, "JSON object required")
    try:
        parsed = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError):
        raise PackError(400, "JSON object required") from None
    if not isinstance(parsed, dict):
        raise PackError(400, "JSON object required")
    reject_control_fields(parsed)
    return parsed


app = create_app()
