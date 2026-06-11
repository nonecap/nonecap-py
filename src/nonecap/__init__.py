"""Official Python client for the NoneCap hCaptcha solving API.

>>> from nonecap import NoneCap
>>> nc = NoneCap(api_key="nc_live_...")
>>> solve = nc.solve(type="hcaptcha", sitekey="...", url="https://example.com")
>>> solve.token
'P1_...'
"""

from ._client import AsyncNoneCap, NoneCap
from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    AuthenticationError,
    ConflictError,
    InsufficientCreditsError,
    NoneCapError,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    SolveFailedError,
    SolveTimeoutError,
    ValidationError,
)
from ._types import (
    TERMINAL_STATUSES,
    Account,
    Proxy,
    Solve,
    SolveError,
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
    # types
    "Solve",
    "SolveError",
    "SolvePage",
    "Account",
    "Proxy",
    "SolveType",
    "SolveStatus",
    "TERMINAL_STATUSES",
    # errors
    "NoneCapError",
    "AuthenticationError",
    "PermissionDeniedError",
    "InsufficientCreditsError",
    "ValidationError",
    "NotFoundError",
    "ConflictError",
    "RateLimitError",
    "APIError",
    "APIConnectionError",
    "APITimeoutError",
    "SolveFailedError",
    "SolveTimeoutError",
]
