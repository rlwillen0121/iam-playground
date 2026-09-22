"""HR HTTP routes.

GET /hr/people, GET /hr/people/{employeeNumber}, GET /hr/changes?after=<sequence>.
POST /hr/people updates only the HR list. An HR write is not a target-account write.
This module does not accept an account store and does not call one.
"""

from __future__ import annotations

import json
import re
from urllib.parse import quote

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from iam_playground.hr.feed import FEED_COLUMNS, FeedError, HrFeed, normalize_person

_AFTER = re.compile(r"[0-9]{1,18}")


def mount_hr(app: FastAPI, feed: HrFeed | None = None) -> HrFeed:
    source = feed if feed is not None else HrFeed()
    app.state.hr_feed = source

    @app.get("/hr/people")
    def list_people() -> JSONResponse:
        return _json(
            {
                "fixtureId": source.fixture_id,
                "columns": list(FEED_COLUMNS),
                "people": source.people(),
            }
        )

    @app.get("/hr/people/{employeeNumber}")
    def get_person(employeeNumber: str) -> JSONResponse:
        found = source.person(employeeNumber)
        if found is None:
            return _error(404, "person not found")
        return _json(found)

    @app.get("/hr/changes")
    def list_changes(after: str | None = None) -> JSONResponse:
        try:
            cursor = _parse_after(after)
            changes = source.changes_after(cursor)
        except FeedError as exc:
            return _error(400, exc.detail)
        return _json({"after": cursor, "order": "sequence", "changes": changes})

    @app.post("/hr/people")
    async def post_person(request: Request) -> JSONResponse:
        # Updates the HR list only. No SCIM, REST, LDAP, or SQL account write.
        try:
            body = await _read_json(request)
            if not isinstance(body, dict):
                raise FeedError("body must be an object")
            if "password" in body:
                raise FeedError("password is not accepted")
            fields = normalize_person(body)
            occurred = _optional_occurred_at(body)
            person, created = source.upsert(fields, occurred_at=occurred)
        except FeedError as exc:
            return _error(400, exc.detail)
        status = 201 if created else 200
        location = "/hr/people/" + quote(person["employeeNumber"], safe="")
        return _json(person, status, {"Location": location})

    return source


def _parse_after(value: str | None) -> int:
    if value is None:
        return 0
    if not isinstance(value, str) or _AFTER.fullmatch(value) is None:
        raise FeedError("after must be a non-negative integer sequence")
    return int(value)


def _optional_occurred_at(body: dict) -> str | None:
    if "occurredAt" not in body:
        return None
    value = body.get("occurredAt")
    if not isinstance(value, str) or value == "":
        raise FeedError("occurredAt must be a non-empty string")
    return value


async def _read_json(request: Request) -> object:
    raw = await request.body()
    if not raw:
        raise FeedError("request body is required")
    try:
        return json.loads(raw)
    except json.JSONDecodeError as exc:
        raise FeedError("request body is not valid JSON") from exc


def _json(payload: object, status: int = 200, headers: dict[str, str] | None = None) -> JSONResponse:
    return JSONResponse(status_code=status, content=payload, headers=headers)


def _error(status: int, detail: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"detail": detail})
