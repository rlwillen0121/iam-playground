"""REST routes. Authenticate before fault matching. Include the router; do not mount it here."""

from __future__ import annotations

import json
from collections.abc import Callable

from fastapi import APIRouter, Header, Request
from fastapi.responses import JSONResponse, Response

from iam_playground.errors import DependencyFailure
from iam_playground.rest.auth import (
    Principal,
    env_legacy_key,
    env_legacy_read_key,
    env_modern_read_token,
    env_modern_token,
    legacy_principal,
    modern_principal,
)
from iam_playground.rest.codec import (
    cursor_page,
    decode_cursor,
    malformed_list,
    number_page,
    operation_json,
    parse_account_id,
    parse_create,
    parse_idempotency_key,
    parse_limit,
    parse_operation_id,
    parse_page,
    parse_page_size,
    parse_patch,
    parse_role_name,
    reject_unknown,
    single_value,
)
from iam_playground.rest.constants import (
    ALREADY_FINISHED,
    APP_LEGACY,
    APP_MODERN,
    BODY_MAX_BYTES,
    FAULT_429,
    FAULT_503,
    FAULT_ASYNC_FAILURE,
    FAULT_COMMIT_TIMEOUT,
    FAULT_HEADER,
    FAULT_MALFORMED_LIST,
    FAULT_STALE_READ,
    KIND_ASSIGN,
    KIND_CREATE,
    KIND_DELETE,
    KIND_DISABLE,
    KIND_ENABLE,
    KIND_PATCH,
    KIND_REMOVE,
    OP_CANCEL,
    OP_GET_ACCOUNT,
    OP_GET_OPERATION,
    OP_LIST_ACCOUNTS,
    OP_LIST_ROLES,
    OUTCOME_FAULTS,
    RETRY_AFTER_SECONDS,
    STATE_ACCEPTED,
    STATE_RUNNING,
    STATUS_DISABLED,
    STATUS_ENABLED,
    SUCCEEDED_NOT_ROLLED_BACK,
    TRANSPORT_FAULTS,
)
from iam_playground.rest.errors import RestError
from iam_playground.rest.faults import FaultStore
from iam_playground.rest import service
from iam_playground.rest.snapshots import AccountSnapshots

StoreFactory = Callable[[], object]
TokenSource = Callable[[], str]
_MODERN_LIST = frozenset({"cursor", "limit"})
_LEGACY_LIST = frozenset({"page", "pageSize"})
_NO_QUERY = frozenset()


def create_router(
    store_factory: StoreFactory | None = None,
    *,
    modern_token: TokenSource | None = None,
    modern_read_token: TokenSource | None = None,
    legacy_key: TokenSource | None = None,
    legacy_read_key: TokenSource | None = None,
    fault_store: FaultStore | None = None,
    snapshots: AccountSnapshots | None = None,
) -> APIRouter:
    """Build the modern and legacy routes. Call once and include the result."""
    factory = store_factory or _default_store_factory
    write_token = modern_token or env_modern_token
    read_token = modern_read_token or env_modern_read_token
    write_key = legacy_key or env_legacy_key
    read_key = legacy_read_key or env_legacy_read_key
    faults = fault_store or FaultStore()
    images = snapshots or AccountSnapshots()
    router = APIRouter()

    def modern(authorization: str | None, *, mutation: bool) -> Principal:
        return modern_principal(
            authorization,
            mutation=mutation,
            write_token=write_token(),
            read_token=read_token(),
        )

    def legacy(api_key: str | None, *, mutation: bool) -> Principal:
        return legacy_principal(
            api_key,
            mutation=mutation,
            write_key=write_key(),
            read_key=read_key(),
        )

    def open_store() -> object:
        try:
            return factory()
        except Exception as exc:
            raise DependencyFailure("database") from exc

    def transport(principal: Principal, operation: str) -> JSONResponse | None:
        # The principal exists only after authentication succeeded.
        name = faults.match(
            authenticated=True,
            app_id=principal.app_id,
            operation=operation,
            only=TRANSPORT_FAULTS,
        )
        if name is None:
            return None
        return _transport(name)

    def read_fault(principal: Principal, operation: str) -> str | None:
        return faults.match(authenticated=True, app_id=principal.app_id, operation=operation)

    @router.get("/rest/modern/accounts")
    def modern_list(request: Request, authorization: str | None = Header(default=None)):
        def work() -> object:
            principal = modern(authorization, mutation=False)
            query = _query(request, _MODERN_LIST)
            after_id = decode_cursor(query["cursor"]) if query["cursor"] is not None else None
            limit = parse_limit(query["limit"])
            fault = read_fault(principal, OP_LIST_ACCOUNTS)
            if fault == FAULT_429 or fault == FAULT_503:
                return _transport(fault)
            if fault == FAULT_MALFORMED_LIST:
                return _json(malformed_list("modern"), headers={FAULT_HEADER: fault})
            if fault == FAULT_STALE_READ:
                body = cursor_page(list(images.prior(APP_MODERN)), after_id, limit)
                return _json(body, headers={FAULT_HEADER: fault})
            return _json(service.list_accounts_cursor(open_store(), APP_MODERN, after_id, limit))

        return _finish(work)

    @router.post("/rest/modern/accounts")
    async def modern_create(request: Request, authorization: str | None = Header(default=None)):
        try:
            principal = modern(authorization, mutation=True)
            body = parse_create(await _read_json(request))
        except RestError as exc:
            return _error(exc)

        def work() -> object:
            blocked = transport(principal, KIND_CREATE)
            if blocked is not None:
                return blocked
            created = service.create_account(open_store(), images, APP_MODERN, body)
            response = _json(created, 201, {"Location": f"/rest/modern/accounts/{created['id']}"})
            return _or_timeout(principal, KIND_CREATE, response)

        return _finish(work)

    @router.get("/rest/modern/accounts/{account_id}")
    def modern_get(account_id: str, request: Request, authorization: str | None = Header(default=None)):
        def work() -> object:
            principal = modern(authorization, mutation=False)
            _query(request, _NO_QUERY)
            ident = parse_account_id(account_id)
            fault = read_fault(principal, OP_GET_ACCOUNT)
            if fault == FAULT_429 or fault == FAULT_503:
                return _transport(fault)
            if fault == FAULT_STALE_READ:
                return _stale_account(APP_MODERN, ident)
            return _json(service.get_account(open_store(), APP_MODERN, ident))

        return _finish(work)

    @router.patch("/rest/modern/accounts/{account_id}")
    async def modern_patch(
        account_id: str,
        request: Request,
        authorization: str | None = Header(default=None),
    ):
        try:
            principal = modern(authorization, mutation=True)
            ident = parse_account_id(account_id)
            patch = parse_patch(await _read_json(request))
        except RestError as exc:
            return _error(exc)

        def work() -> object:
            blocked = transport(principal, KIND_PATCH)
            if blocked is not None:
                return blocked
            updated = service.patch_account(open_store(), images, APP_MODERN, ident, patch)
            return _or_timeout(principal, KIND_PATCH, _json(updated))

        return _finish(work)

    @router.delete("/rest/modern/accounts/{account_id}")
    def modern_delete(account_id: str, authorization: str | None = Header(default=None)):
        def work() -> object:
            principal = modern(authorization, mutation=True)
            ident = parse_account_id(account_id)
            blocked = transport(principal, KIND_DELETE)
            if blocked is not None:
                return blocked
            service.delete_account(open_store(), images, APP_MODERN, ident)
            return _or_timeout(principal, KIND_DELETE, Response(status_code=204, headers=_headers()))

        return _finish(work)

    @router.post("/rest/modern/accounts/{account_id}/enable")
    def modern_enable(account_id: str, authorization: str | None = Header(default=None)):
        return _modern_status(account_id, authorization, enabled=True)

    @router.post("/rest/modern/accounts/{account_id}/disable")
    def modern_disable(account_id: str, authorization: str | None = Header(default=None)):
        return _modern_status(account_id, authorization, enabled=False)

    def _modern_status(account_id: str, authorization: str | None, *, enabled: bool) -> object:
        kind = KIND_ENABLE if enabled else KIND_DISABLE
        status = STATUS_ENABLED if enabled else STATUS_DISABLED

        def work() -> object:
            principal = modern(authorization, mutation=True)
            ident = parse_account_id(account_id)
            blocked = transport(principal, kind)
            if blocked is not None:
                return blocked
            updated = service.set_status(open_store(), images, APP_MODERN, ident, status)
            return _or_timeout(principal, kind, _json(updated))

        return _finish(work)

    @router.get("/rest/modern/roles")
    def modern_roles(request: Request, authorization: str | None = Header(default=None)):
        return _roles(request, authorization, modern=True)

    @router.post("/rest/modern/accounts/{account_id}/roles/{role}")
    def modern_assign(account_id: str, role: str, authorization: str | None = Header(default=None)):
        def work() -> object:
            principal = modern(authorization, mutation=True)
            ident = parse_account_id(account_id)
            role_name = parse_role_name(role)
            blocked = transport(principal, KIND_ASSIGN)
            if blocked is not None:
                return blocked
            updated = service.assign_role(open_store(), images, APP_MODERN, ident, role_name)
            return _or_timeout(principal, KIND_ASSIGN, _json(updated))

        return _finish(work)

    @router.delete("/rest/modern/accounts/{account_id}/roles/{role}")
    def modern_unassign(account_id: str, role: str, authorization: str | None = Header(default=None)):
        def work() -> object:
            principal = modern(authorization, mutation=True)
            ident = parse_account_id(account_id)
            role_name = parse_role_name(role)
            blocked = transport(principal, KIND_REMOVE)
            if blocked is not None:
                return blocked
            service.remove_role(open_store(), images, APP_MODERN, ident, role_name)
            return _or_timeout(principal, KIND_REMOVE, Response(status_code=204, headers=_headers()))

        return _finish(work)

    @router.get("/rest/legacy/accounts")
    def legacy_list(
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    ):
        def work() -> object:
            principal = legacy(x_api_key, mutation=False)
            query = _query(request, _LEGACY_LIST)
            page = parse_page(query["page"])
            page_size = parse_page_size(query["pageSize"])
            fault = read_fault(principal, OP_LIST_ACCOUNTS)
            if fault == FAULT_429 or fault == FAULT_503:
                return _transport(fault)
            if fault == FAULT_MALFORMED_LIST:
                return _json(malformed_list("legacy", page), headers={FAULT_HEADER: fault})
            if fault == FAULT_STALE_READ:
                body = number_page(list(images.prior(APP_LEGACY)), page, page_size)
                return _json(body, headers={FAULT_HEADER: fault})
            return _json(service.list_accounts_page(open_store(), APP_LEGACY, page, page_size))

        return _finish(work)

    @router.post("/rest/legacy/accounts")
    async def legacy_create(
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        try:
            principal = legacy(x_api_key, mutation=True)
            key = parse_idempotency_key(idempotency_key)
            body = parse_create(await _read_json(request))
        except RestError as exc:
            return _error(exc)
        return _legacy_write(principal, KIND_CREATE, None, None, body, key)

    @router.get("/rest/legacy/accounts/{account_id}")
    def legacy_get(
        account_id: str,
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    ):
        def work() -> object:
            principal = legacy(x_api_key, mutation=False)
            _query(request, _NO_QUERY)
            ident = parse_account_id(account_id)
            fault = read_fault(principal, OP_GET_ACCOUNT)
            if fault == FAULT_429 or fault == FAULT_503:
                return _transport(fault)
            if fault == FAULT_STALE_READ:
                return _stale_account(APP_LEGACY, ident)
            return _json(service.get_account(open_store(), APP_LEGACY, ident))

        return _finish(work)

    @router.patch("/rest/legacy/accounts/{account_id}")
    async def legacy_patch(
        account_id: str,
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        try:
            principal = legacy(x_api_key, mutation=True)
            ident = parse_account_id(account_id)
            key = parse_idempotency_key(idempotency_key)
            patch = parse_patch(await _read_json(request))
        except RestError as exc:
            return _error(exc)
        return _legacy_write(principal, KIND_PATCH, ident, None, patch, key)

    @router.delete("/rest/legacy/accounts/{account_id}")
    def legacy_delete(
        account_id: str,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        try:
            principal = legacy(x_api_key, mutation=True)
            ident = parse_account_id(account_id)
            key = parse_idempotency_key(idempotency_key)
        except RestError as exc:
            return _error(exc)
        return _legacy_write(principal, KIND_DELETE, ident, None, None, key)

    @router.post("/rest/legacy/accounts/{account_id}/enable")
    def legacy_enable(
        account_id: str,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return _legacy_status(account_id, x_api_key, idempotency_key, enabled=True)

    @router.post("/rest/legacy/accounts/{account_id}/disable")
    def legacy_disable(
        account_id: str,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        return _legacy_status(account_id, x_api_key, idempotency_key, enabled=False)

    def _legacy_status(
        account_id: str,
        api_key: str | None,
        idempotency_key: str | None,
        *,
        enabled: bool,
    ) -> object:
        try:
            principal = legacy(api_key, mutation=True)
            ident = parse_account_id(account_id)
            key = parse_idempotency_key(idempotency_key)
        except RestError as exc:
            return _error(exc)
        kind = KIND_ENABLE if enabled else KIND_DISABLE
        return _legacy_write(principal, kind, ident, None, None, key)

    @router.get("/rest/legacy/roles")
    def legacy_roles(
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    ):
        return _roles(request, x_api_key, modern=False)

    @router.post("/rest/legacy/accounts/{account_id}/roles/{role}")
    def legacy_assign(
        account_id: str,
        role: str,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        try:
            principal = legacy(x_api_key, mutation=True)
            ident = parse_account_id(account_id)
            role_name = parse_role_name(role)
            key = parse_idempotency_key(idempotency_key)
        except RestError as exc:
            return _error(exc)
        return _legacy_write(principal, KIND_ASSIGN, ident, role_name, None, key)

    @router.delete("/rest/legacy/accounts/{account_id}/roles/{role}")
    def legacy_unassign(
        account_id: str,
        role: str,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ):
        try:
            principal = legacy(x_api_key, mutation=True)
            ident = parse_account_id(account_id)
            role_name = parse_role_name(role)
            key = parse_idempotency_key(idempotency_key)
        except RestError as exc:
            return _error(exc)
        return _legacy_write(principal, KIND_REMOVE, ident, role_name, None, key)

    @router.get("/rest/legacy/operations/{operation_id}")
    def legacy_operation(
        operation_id: str,
        request: Request,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    ):
        def work() -> object:
            principal = legacy(x_api_key, mutation=False)
            _query(request, _NO_QUERY)
            ident = parse_operation_id(operation_id)
            fault = read_fault(principal, OP_GET_OPERATION)
            if fault == FAULT_429 or fault == FAULT_503:
                return _transport(fault)
            op = service.get_operation(open_store(), APP_LEGACY, ident)
            return _json(operation_json(op))

        return _finish(work)

    @router.post("/rest/legacy/operations/{operation_id}/cancel")
    def legacy_cancel(
        operation_id: str,
        x_api_key: str | None = Header(default=None, alias="X-Api-Key"),
    ):
        def work() -> object:
            principal = legacy(x_api_key, mutation=True)
            ident = parse_operation_id(operation_id)
            blocked = transport(principal, OP_CANCEL)
            if blocked is not None:
                return blocked
            # Cancel does not resume other work and does not roll back a success.
            op, outcome = service.cancel_operation(open_store(), APP_LEGACY, ident)
            body = operation_json(op)
            if outcome == "succeeded":
                return _json({"error": SUCCEEDED_NOT_ROLLED_BACK, "operation": body}, 409)
            if outcome == "finished":
                return _json({"error": ALREADY_FINISHED, "operation": body}, 409)
            return _json(body)

        return _finish(work)

    def _roles(request: Request, credential: str | None, *, modern: bool) -> object:
        def work() -> object:
            if modern:
                principal = modern_principal(
                    credential,
                    mutation=False,
                    write_token=write_token(),
                    read_token=read_token(),
                )
                app_id = APP_MODERN
            else:
                principal = legacy_principal(
                    credential,
                    mutation=False,
                    write_key=write_key(),
                    read_key=read_key(),
                )
                app_id = APP_LEGACY
            _query(request, _NO_QUERY)
            fault = read_fault(principal, OP_LIST_ROLES)
            if fault == FAULT_429 or fault == FAULT_503:
                return _transport(fault)
            return _json(service.list_roles(open_store(), app_id))

        return _finish(work)

    def _legacy_write(
        principal: Principal,
        kind: str,
        account_id: int | None,
        role_name: str | None,
        body: dict | None,
        idempotency_key: str,
    ) -> object:
        def work() -> object:
            blocked = transport(principal, kind)
            if blocked is not None:
                return blocked
            store = open_store()
            service.resume(store, images, APP_LEGACY)
            # The insert commits inside accept_operation, before this response exists.
            op, created = service.accept_operation(
                store,
                app_id=APP_LEGACY,
                client_id=principal.client_id,
                kind=kind,
                idempotency_key=idempotency_key,
                account_id=account_id,
                role_name=role_name,
                body=body,
            )
            if not created:
                if op.state in {STATE_ACCEPTED, STATE_RUNNING}:
                    op = service.execute_operation(store, images, APP_LEGACY, op.id)
                return _json(operation_json(op), 202)
            accepted = _json(operation_json(op), 202)
            outcome = faults.match(
                authenticated=True,
                app_id=APP_LEGACY,
                operation=kind,
                only=OUTCOME_FAULTS,
            )
            if outcome == FAULT_ASYNC_FAILURE:
                service.fail_unapplied(store, APP_LEGACY, op.id, FAULT_ASYNC_FAILURE)
                accepted.headers[FAULT_HEADER] = FAULT_ASYNC_FAILURE
                return accepted
            if outcome == FAULT_COMMIT_TIMEOUT:
                service.execute_operation(store, images, APP_LEGACY, op.id)
                return _transport(FAULT_COMMIT_TIMEOUT)
            service.execute_operation(store, images, APP_LEGACY, op.id)
            return accepted

        return _finish(work)

    def _or_timeout(principal: Principal, operation: str, response: Response) -> Response:
        outcome = faults.match(
            authenticated=True,
            app_id=principal.app_id,
            operation=operation,
            only=OUTCOME_FAULTS,
        )
        if outcome == FAULT_COMMIT_TIMEOUT:
            return _transport(FAULT_COMMIT_TIMEOUT)
        return response

    def _stale_account(app_id: str, account_id: int) -> JSONResponse:
        for row in images.prior(app_id):
            if int(row["id"]) == account_id:
                return _json(row, headers={FAULT_HEADER: FAULT_STALE_READ})
        return _error(RestError(404, "account not found"), {FAULT_HEADER: FAULT_STALE_READ})

    return router


def _default_store_factory() -> object:
    from iam_playground.db import database_url_from_env, get_engine
    from iam_playground.rest.store import SqlRestStore

    return SqlRestStore(get_engine(database_url_from_env()))


def _query(request: Request, allowed: frozenset[str]) -> dict[str, str | None]:
    reject_unknown(list(request.query_params.keys()), allowed)
    return {name: single_value(request.query_params.getlist(name), name) for name in allowed}


async def _read_json(request: Request) -> dict:
    raw = await request.body()
    if len(raw) > BODY_MAX_BYTES:
        raise RestError(400, "request body is too large")
    if not raw:
        raise RestError(400, "request body is required")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise RestError(400, "request body is not valid JSON") from exc
    if not isinstance(parsed, dict):
        raise RestError(400, "request body must be an object")
    return parsed


def _finish(work: Callable[[], object]) -> object:
    try:
        return work()
    except RestError as exc:
        return _error(exc)
    except DependencyFailure:
        return _error(RestError(503, "dependency"))


def _transport(name: str) -> JSONResponse:
    if name == FAULT_429:
        return _json(
            {"error": "rate limit"},
            429,
            {FAULT_HEADER: name, "Retry-After": RETRY_AFTER_SECONDS},
        )
    if name == FAULT_503:
        return _json({"error": "unavailable"}, 503, {FAULT_HEADER: name})
    return _json({"error": "commit timeout"}, 504, {FAULT_HEADER: FAULT_COMMIT_TIMEOUT})


def _headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    headers = {"Cache-Control": "no-store"}
    if extra:
        headers.update(extra)
    return headers


def _json(payload: dict, status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload, headers=_headers(headers))


def _error(exc: RestError, headers: dict[str, str] | None = None) -> JSONResponse:
    extra = dict(headers or {})
    if exc.status == 401 and exc.detail == "bearer token required":
        extra["WWW-Authenticate"] = "Bearer"
    return _json({"error": exc.detail}, exc.status, extra)
