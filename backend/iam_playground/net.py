"""Loopback HTTP without using environment proxies."""

from __future__ import annotations

import json
import urllib.error
import urllib.request


def fetch_bytes(url: str, timeout: float, *, method: str = "GET", data: bytes | None = None, headers: dict[str, str] | None = None) -> tuple[int, bytes]:
    request = urllib.request.Request(url, data=data, headers=headers or {}, method=method)
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
    try:
        with opener.open(request, timeout=timeout) as response:
            return response.status, response.read()
    except urllib.error.HTTPError as exc:
        return exc.code, exc.read()


def fetch_json(url: str, timeout: float) -> tuple[int, object]:
    status, body = fetch_bytes(url, timeout, headers={"Accept": "application/json"})
    if not body:
        return status, None
    return status, json.loads(body.decode("utf-8"))
