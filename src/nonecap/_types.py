"""Wire types for the NoneCap API.

Field names are snake_case and mirror the JSON on the wire exactly, so what
you read in the docs is what you access in code. Parsers pick known keys and
ignore unknown ones, so new server-side fields never break old clients.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Literal, Optional, TypedDict, Union

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


SolveErrorCode = Literal[
    "challenge_not_loaded",
    "token_not_granted",
    "challenge_expired",
    "challenge_errored",
    "proxy_error",
    "target_unreachable",
    "vision_error",
    "internal_error",
    "unsolvable_variant",
    "capacity_exhausted",
    "cancelled",
    "expired",
]
"""Why a solve did not produce a token. Codes the API adds later still arrive as
plain strings, so compare with ``==`` and keep a default branch."""

SolveErrorReason = Literal[
    "sitekey_rate_limited",
    "passive_required",
    "rounds_exhausted",
    "proxy_rejected",
    "proxy_tls",
    "proxy_stalled",
    "proxy_egress_blocked",
    "target_egress_blocked",
    "profile_engine_unavailable",
    "type_not_served",
    "browser_lane_capped",
]
"""A typed sub-reason within :data:`SolveErrorCode`, set when the solver knows more
than the code says."""


@dataclass(frozen=True)
class SolveError:
    """The error attached to a solve that did not succeed."""

    code: str
    """A :data:`SolveErrorCode`."""
    message: str
    """What happened, what to do, and whether the solve was charged."""
    reason: Optional[str] = None
    """A :data:`SolveErrorReason`, or None when the code says it all."""
    retryable: bool = True
    """Whether re-submitting the same request unchanged can succeed."""
    docs_url: str = "https://nonecap.com/api-reference#errors"
    """Reference for the codes and reasons."""


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
    resp_key: Optional[str]
    """hCaptcha's response key for the challenge behind ``token`` (what the widget's
    ``hcaptcha.getRespKey()`` returns, ``E0_…``). Sites that verify the token and key
    together need both. Set alongside ``token``, otherwise None."""
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
    user_agent: Optional[str] = None
    """The browser user agent the solve presented while it earned ``token``. Some sites
    reject a token submitted by a different browser version, so send the token with this
    as your ``User-Agent`` header (and from the same IP as your proxy, if you gave one).
    Set alongside ``token``, otherwise None."""

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
            resp_key=data.get("resp_key"),
            error=SolveError(
                code=raw_error["code"],
                message=raw_error["message"],
                reason=raw_error.get("reason"),
                retryable=bool(raw_error.get("retryable", True)),
                docs_url=raw_error.get("docs_url", "https://nonecap.com/api-reference#errors"),
            )
            if raw_error
            else None,
            credits_charged=data.get("credits_charged"),
            proxy_bytes=data.get("proxy_bytes"),
            created_at=data.get("created_at", ""),
            started_at=data.get("started_at"),
            finished_at=data.get("finished_at"),
            queue_ms=data.get("queue_ms"),
            resolve_ms=data.get("resolve_ms"),
            user_agent=data.get("user_agent"),
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


FeedbackOutcome = Literal["accepted", "rejected", "unknown", "unused", "error"]
"""What the downstream target did with a solve's token.

``accepted`` and ``rejected`` are the quality signal and the only two that
count toward the acceptance rate. ``unknown`` (submitted, verdict
undetermined), ``unused`` (never submitted — expired, aborted, deduped) and
``error`` (downstream broke for a non-token reason) are recorded but kept out
of the denominator, so a client-side outage can't look like a regression.
"""

FeedbackStatus = Literal["recorded", "updated", "unchanged", "error"]
"""What happened to one reported item: first report, overwrote an earlier one,
identical to what was stored (no write), or rejected."""


class _FeedbackReportRequired(TypedDict):
    solve_id: str
    outcome: FeedbackOutcome


class FeedbackReport(_FeedbackReportRequired, total=False):
    """One verdict to report, as passed to ``client.feedback.report_many``.

    ``solve_id`` is the id from ``solves.create`` / ``solve()``, and must be
    your own solve that produced a token. ``reason`` is the code or message your
    target gave you when it refused the token (e.g. ``"invalid-response"``),
    truncated to 512 chars server-side. ``context`` is optional free text with no
    schema — anything about the attempt you think would help us diagnose it,
    truncated to 2000 chars. Neither is parsed; they are what a human reads when
    you raise a ticket, and they carry the half of a rejection NoneCap cannot
    observe on its own. ``reported_at`` is advisory only — the server stamps its
    own timestamps.
    """

    reason: Optional[str]
    context: Optional[str]
    reported_at: Union[str, datetime, None]


@dataclass(frozen=True)
class Feedback:
    """A recorded feedback resource."""

    object: str
    solve_id: str
    outcome: FeedbackOutcome
    reason: Optional[str]
    context: Optional[str]
    reported_at: Optional[str]
    report_count: int
    """How many times this solve's verdict has been written. 1 on first report."""
    created_at: str
    updated_at: str

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> Feedback:
        return cls(
            object=data.get("object", "feedback"),
            solve_id=data["solve_id"],
            outcome=data["outcome"],
            reason=data.get("reason"),
            context=data.get("context"),
            reported_at=data.get("reported_at"),
            report_count=int(data.get("report_count", 1)),
            created_at=data.get("created_at", ""),
            updated_at=data.get("updated_at", ""),
        )


@dataclass(frozen=True)
class FeedbackItemError:
    """Why one item of a batch was rejected."""

    code: str
    message: str
    param: Optional[str]


@dataclass(frozen=True)
class FeedbackResult:
    """One item's result, in the same position as the report you sent."""

    solve_id: str
    status: FeedbackStatus
    error: Optional[FeedbackItemError]
    """Set only when ``status == "error"``."""

    @classmethod
    def _from_dict(cls, data: dict[str, Any]) -> FeedbackResult:
        raw_error = data.get("error")
        return cls(
            solve_id=data.get("solve_id", ""),
            status=data["status"],
            error=FeedbackItemError(
                code=raw_error.get("code", ""),
                message=raw_error.get("message", ""),
                param=raw_error.get("param"),
            )
            if raw_error
            else None,
        )


@dataclass(frozen=True)
class FeedbackBatch:
    """The result of ``client.feedback.report_many``.

    Items are resolved independently, so one bad solve id never discards the
    rest — which also means a broken integration reports zero failures at the
    HTTP level. Check ``failed`` (or scan ``results``), not just the absence of
    a raised error.
    """

    object: str
    recorded: int
    updated: int
    unchanged: int
    failed: int
    results: list[FeedbackResult]
    """One entry per report you sent, in request order."""

    @classmethod
    def _from_dict(cls, payload: dict[str, Any]) -> FeedbackBatch:
        return cls(
            object=payload.get("object", "feedback_batch"),
            recorded=int(payload.get("recorded", 0)),
            updated=int(payload.get("updated", 0)),
            unchanged=int(payload.get("unchanged", 0)),
            failed=int(payload.get("failed", 0)),
            results=[FeedbackResult._from_dict(item) for item in payload.get("results", [])],
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
