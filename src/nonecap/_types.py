"""Wire types for the NoneCap API.

Field names are snake_case and mirror the JSON on the wire exactly, so what
you read in the docs is what you access in code. Parsers pick known keys and
ignore unknown ones, so new server-side fields never break old clients.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal, Optional, TypedDict

SolveType = Literal["hcaptcha", "hcaptcha_enterprise"]
"""Captcha type a solve targets."""

SolveStatus = Literal["pending", "solving", "solved", "failed", "cancelled", "expired"]
"""Lifecycle of a solve. ``solved``/``failed``/``cancelled``/``expired`` are terminal."""

TERMINAL_STATUSES: frozenset[str] = frozenset({"solved", "failed", "cancelled", "expired"})
"""The statuses a solve can never leave."""


class Proxy(TypedDict, total=False):
    """A proxy the solve should egress through."""

    scheme: str
    host: str
    port: str | int
    username: str
    password: str


@dataclass(frozen=True)
class SolveError:
    """The error attached to a solve that did not succeed."""

    code: str
    message: str


@dataclass(frozen=True)
class Solve:
    """A solve resource, exactly as the API returns it."""

    id: str
    object: str
    type: SolveType
    status: SolveStatus
    sitekey: str
    url: str
    token: Optional[str]
    """The captcha token once ``status == "solved"``, otherwise None."""
    error: Optional[SolveError]
    """Set when the solve did not succeed, otherwise None."""
    credits_charged: Optional[int]
    """Credits charged for this solve. Only successful solves are charged."""
    proxy_bytes: Optional[int]
    """Bytes that egressed through the metered proxy, or None if none was used."""
    created_at: str
    started_at: Optional[str]
    finished_at: Optional[str]
    queue_ms: Optional[int]
    """Milliseconds the solve waited in the queue before a worker picked it up."""
    resolve_ms: Optional[int]
    """Milliseconds of actual solving."""

    @property
    def is_terminal(self) -> bool:
        """Whether the solve has reached a final state."""
        return self.status in TERMINAL_STATUSES

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> Solve:
        raw_error = data.get("error")
        return cls(
            id=data["id"],
            object=data.get("object", "solve"),
            type=data["type"],
            status=data["status"],
            sitekey=data.get("sitekey", ""),
            url=data.get("url", ""),
            token=data.get("token"),
            error=SolveError(code=raw_error["code"], message=raw_error["message"])
            if raw_error
            else None,
            credits_charged=data.get("credits_charged"),
            proxy_bytes=data.get("proxy_bytes"),
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            queue_ms=data.get("queue_ms"),
            resolve_ms=data.get("resolve_ms"),
        )


@dataclass(frozen=True)
class SolvePage:
    """One page of solves, newest first."""

    object: str
    data: list[Solve]
    has_more: bool

    @classmethod
    def _from_dict(cls, payload: dict[str, Any]) -> SolvePage:
        return cls(
            object=payload.get("object", "list"),
            data=[Solve._from_dict(item) for item in payload.get("data", [])],
            has_more=bool(payload.get("has_more", False)),
        )


@dataclass(frozen=True)
class Account:
    """Your account, including the current credit balance."""

    object: str
    id: str
    email: str
    credits_balance: int
    created_at: str

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> Account:
        return cls(
            object=data.get("object", "account"),
            id=data["id"],
            email=data.get("email", ""),
            credits_balance=int(data.get("credits_balance", 0)),
            created_at=data.get("created_at", ""),
        )
