"""Official Python client for the NoneCap hCaptcha solving API.

>>> from nonecap import NoneCap
>>> nc = NoneCap(api_key="nc_live_...")
>>> solve = nc.solve(type="hcaptcha", sitekey="...", url="https://example.com")
>>> solve.token
'P1_...'
"""

from ._client import (
    FEEDBACK_BATCH_MAX,
    AsyncNoneCap,
    AsyncSolveHandle,
    NoneCap,
    SolveHandle,
)
from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    ConcurrencyLimitError,
    ConflictError,
    InsufficientCreditsError,
    KeyCreditLimitError,
    NoneCapError,
    NotFoundError,
    PayloadTooLargeError,
    PermissionDeniedError,
    RateLimitError,
    ServiceUnavailableError,
    SitekeyRateLimitedError,
    SolveFailedError,
    SolveTimeoutError,
    UnsupportedMediaTypeError,
    ValidationError,
)
from ._types import (
    TERMINAL_STATUSES,
    Account,
    Feedback,
    FeedbackBatch,
    FeedbackItemError,
    FeedbackOutcome,
    FeedbackReport,
    FeedbackResult,
    FeedbackStatus,
    Proxy,
    Solve,
    SolveError,
    SolveErrorCode,
    SolveErrorReason,
    SolvePage,
    SolveStatus,
    SolveType,
)
from ._version import __version__

__all__ = [
    "__version__",
    # clients
    "NoneCap",
    "AsyncNoneCap",
    # handles
    "SolveHandle",
    "AsyncSolveHandle",
    # types
    "Solve",
    "SolveError",
    "SolveErrorCode",
    "SolveErrorReason",
    "SolvePage",
    "Account",
    "Proxy",
    "SolveType",
    "SolveStatus",
    "TERMINAL_STATUSES",
    "Feedback",
    "FeedbackReport",
    "FeedbackBatch",
    "FeedbackResult",
    "FeedbackItemError",
    "FeedbackOutcome",
    "FeedbackStatus",
    "FEEDBACK_BATCH_MAX",
    # errors
    "NoneCapError",
    "AuthenticationError",
    "PermissionDeniedError",
    "InsufficientCreditsError",
    "KeyCreditLimitError",
    "ValidationError",
    "PayloadTooLargeError",
    "UnsupportedMediaTypeError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "ConcurrencyLimitError",
    "SitekeyRateLimitedError",
    "APIError",
    "ServiceUnavailableError",
    "APIConnectionError",
    "APITimeoutError",
    "SolveFailedError",
    "SolveTimeoutError",
]
