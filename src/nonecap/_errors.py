"""The error tree. Catch :class:`NoneCapError` for everything this library
throws, or a subclass for one specific failure."""

from __future__ import annotations

from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from ._types import Solve


class NoneCapError(Exception):
    """Base class for every error raised by this library."""

    def __init__(
        self,
        message: str,
        *,
        code: Optional[str] = None,
        status: Optional[int] = None,
        param: Optional[str] = None,
        request_id: Optional[str] = None,
        retry_after: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        """Machine-readable error code from the API envelope, when there is one."""
        self.status = status
        """HTTP status, when the error came from a response."""
        self.param = param
        """The request field that was rejected, for validation errors."""
        self.request_id = request_id
        """The API's correlation id for this request (``X-Request-Id``); quote it to support."""
        self.retry_after = retry_after
        """Seconds to wait before retrying, when the API sent ``Retry-After``."""


class AuthenticationError(NoneCapError):
    """401 — the API key is missing, malformed, or revoked."""


class PermissionDeniedError(NoneCapError):
    """403 — the key is valid but not allowed to do this (scope or locked account)."""


class InsufficientCreditsError(NoneCapError):
    """402 — the account is out of credits."""


class KeyCreditLimitError(InsufficientCreditsError):
    """402 — this API key reached its own credit limit (the account may still have credits)."""


class ValidationError(NoneCapError):
    """422 / 400 — the request was rejected. ``param`` names the offending field."""


class PayloadTooLargeError(ValidationError):
    """413 — the request body exceeds the route's size limit."""


class UnsupportedMediaTypeError(ValidationError):
    """415 — a JSON route was called without ``Content-Type: application/json``."""


class NotFoundError(NoneCapError):
    """404 — no such resource."""


class ConflictError(NoneCapError):
    """409 — the solve is already in a terminal state."""


class RateLimitError(NoneCapError):
    """429 — back off and retry; ``retry_after`` (seconds) is set when the API sent it."""


class ConcurrencyLimitError(RateLimitError):
    """429 — too many solves in flight for this account. Wait for one to finish."""


class SitekeyRateLimitedError(RateLimitError):
    """429 — hCaptcha is refusing challenges for this sitekey, so the submit was shed.
    Wait ``retry_after`` seconds; the message says whether a different proxy pool can help."""


class APIError(NoneCapError):
    """5xx, or a response that was not the expected shape. ``request_id`` is the id to quote."""


class ServiceUnavailableError(APIError):
    """503 — new solves are paused for maintenance. Retry shortly."""


class APIConnectionError(NoneCapError):
    """The request never reached the API (DNS, TCP, TLS, offline)."""


class APITimeoutError(APIConnectionError):
    """A single HTTP request exceeded its timeout."""


class SolveTimeoutError(NoneCapError):
    """Raised by ``solve()`` / ``SolveHandle.result()`` when the overall timeout
    elapses before the solve reaches a terminal state.

    When the timeout originates from waiting on a specific solve, ``solve_id`` is
    the solve's id and ``solve`` is its last-known state (still non-terminal), so
    you can retry or inspect the latest status. Both are ``None`` only if the
    error was constructed without a solve in hand."""

    def __init__(
        self,
        message: str,
        *,
        solve_id: Optional[str] = None,
        solve: Optional[Solve] = None,
    ) -> None:
        super().__init__(message)
        self.solve_id = solve_id
        """The id of the solve that did not finish in time, when known."""
        self.solve = solve
        """The last-known (non-terminal) solve at the moment of timeout, when known."""


class SolveFailedError(NoneCapError):
    """Raised by ``solve()`` when a solve reaches a terminal state without a
    token: ``failed``, ``expired``, or ``cancelled``. The full solve is attached
    as ``.solve`` so you can inspect ``solve.error`` and the timings."""

    def __init__(self, solve: Solve) -> None:
        detail = f"{solve.error.code}: {solve.error.message}" if solve.error else solve.status
        super().__init__(f"Solve {solve.id} {solve.status} ({detail})")
        self.solve = solve

    @property
    def solve_code(self) -> str:
        """``solve.error.code`` (e.g. ``proxy_error``); the status when no error object
        came back."""
        return self.solve.error.code if self.solve.error else self.solve.status

    @property
    def reason(self) -> Optional[str]:
        """``solve.error.reason``, the typed sub-reason, or None."""
        return self.solve.error.reason if self.solve.error else None

    @property
    def retryable(self) -> bool:
        """Whether re-submitting the same request unchanged can succeed."""
        return self.solve.error.retryable if self.solve.error else False


def error_from_response(
    status: int,
    code: Optional[str],
    message: str,
    param: Optional[str],
    *,
    request_id: Optional[str] = None,
    retry_after: Optional[int] = None,
) -> NoneCapError:
    """Map an API error envelope (plus HTTP status) to the right subclass."""
    cls: type[NoneCapError]
    if code == "unauthorized":
        cls = AuthenticationError
    elif code in ("forbidden", "account_locked"):
        cls = PermissionDeniedError
    elif code == "insufficient_credits":
        cls = InsufficientCreditsError
    elif code == "key_credit_limit_exceeded":
        cls = KeyCreditLimitError
    elif code in ("invalid_request", "validation_error", "expired_window"):
        cls = ValidationError
    elif code == "payload_too_large":
        cls = PayloadTooLargeError
    elif code == "unsupported_media_type":
        cls = UnsupportedMediaTypeError
    elif code in ("not_found", "not_eligible"):
        cls = NotFoundError
    elif code == "conflict":
        cls = ConflictError
    elif code == "concurrency_limit_exceeded":
        cls = ConcurrencyLimitError
    elif code == "sitekey_rate_limited":
        cls = SitekeyRateLimitedError
    elif code in ("rate_limited", "ext_daily_limit"):
        cls = RateLimitError
    elif code == "maintenance":
        cls = ServiceUnavailableError
    else:
        cls = APIError
    return cls(
        message,
        code=code,
        status=status,
        param=param,
        request_id=request_id,
        retry_after=retry_after,
    )
