"""Shared test helpers: a scripted httpx transport and solve payload factory."""

from __future__ import annotations

import json
from typing import Any, Callable, Optional, Union

import httpx

Responder = Union[tuple[int, Any], Callable[[httpx.Request], httpx.Response]]


class Script:
    """A scripted transport: replies from a queue of (status, body) entries and
    records every request. The last entry repeats if more requests arrive."""

    def __init__(self, *responders: Responder) -> None:
        self.responders = list(responders)
        self.requests: list[httpx.Request] = []

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        index = min(len(self.requests) - 1, len(self.responders) - 1)
        responder = self.responders[index]
        if callable(responder):
            return responder(request)
        status, body = responder
        return httpx.Response(status, json=body)

    @property
    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self)

    def body_of(self, index: int) -> Any:
        return json.loads(self.requests[index].content)


def solve_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": "solve_1",
        "object": "solve",
        "type": "hcaptcha",
        "status": "pending",
        "sitekey": "sk",
        "url": "https://example.com",
        "token": None,
        "error": None,
        "credits_charged": None,
        "proxy_bytes": None,
        "created_at": "2026-06-11T00:00:00Z",
        "started_at": None,
        "finished_at": None,
        "queue_ms": None,
        "resolve_ms": None,
    }
    base.update(overrides)
    return base


def error_payload(
    code: str, message: str = "nope", param: Optional[str] = None
) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "param": param}}
