"""Sync and async clients for the NoneCap API.

Both clients expose the same surface:

- ``client.solve(...)`` — submit a captcha and wait for the token (the
  convenient path; long-polls under the hood).
- ``client.solves.create / retrieve / cancel / list / list_all`` — the raw
  resource methods, mapping one to one to the REST API.
- ``client.me()`` — account info and credit balance.

``rqdata`` is required for ``type="hcaptcha_enterprise"`` and optional for
``type="hcaptcha"``; the ``@overload`` signatures enforce that in mypy and
pyright, and a runtime check backs it up for untyped callers.
"""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from typing import (
    Any,
    Literal,
    Optional,
    Union,
    overload,
)

import httpx

from ._errors import (
    APIConnectionError,
    APIError,
    APITimeoutError,
    SolveFailedError,
    SolveTimeoutError,
    ValidationError,
    error_from_response,
)
from ._types import Account, Proxy, Solve, SolvePage, SolveStatus, SolveType
from ._version import __version__

DEFAULT_BASE_URL = "https://api.nonecap.com"
DEFAULT_REQUEST_TIMEOUT = 100.0
"""Per-request timeout (seconds): just above the API's 90s long-poll window."""
DEFAULT_SOLVE_TIMEOUT = 180.0
"""Default overall budget (seconds) for the ``solve()`` helper."""
_MAX_WAIT_SECONDS = 90
"""The API caps server-side long-poll at 90 seconds."""

_USER_AGENT = f"nonecap-python/{__version__}"


def _wait_seconds(deadline: float) -> int:
    """The ``wait`` value for the next long-poll: whole seconds until
    ``deadline``, clamped to the server's 1-90 window. The floor of 1 keeps
    the param valid, so callers must decide whether the deadline has passed
    with the clock, not with this return value."""
    remaining = int(deadline - time.monotonic()) + 1
    return max(1, min(_MAX_WAIT_SECONDS, remaining))


def _request_timeout_for_wait(wait: Optional[int], default: float) -> float:
    """Give the socket a margin beyond the server's long-poll window."""
    if wait is None:
        return default
    return float(wait) + 15.0


def _build_solve_body(
    *,
    type: SolveType,
    sitekey: str,
    url: str,
    rqdata: Optional[str],
    user_agent: Optional[str],
    proxy: Union[Proxy, str, None],
    webhook_url: Optional[str],
) -> dict[str, Any]:
    if type == "hcaptcha_enterprise" and not rqdata:
        raise ValidationError(
            "rqdata is required for hcaptcha_enterprise solves.",
            code="validation_error",
            param="rqdata",
        )
    body: dict[str, Any] = {"type": type, "sitekey": sitekey, "url": url}
    if rqdata is not None:
        body["rqdata"] = rqdata
    if user_agent is not None:
        body["user_agent"] = user_agent
    if proxy is not None:
        body["proxy"] = proxy
    if webhook_url is not None:
        body["webhook_url"] = webhook_url
    return body


def _list_params(
    *,
    limit: Optional[int],
    starting_after: Optional[str],
    status: Optional[SolveStatus],
    type: Optional[SolveType],
) -> dict[str, Any]:
    params: dict[str, Any] = {}
    if limit is not None:
        params["limit"] = limit
    if starting_after is not None:
        params["starting_after"] = starting_after
    if status is not None:
        params["status"] = status
    if type is not None:
        params["type"] = type
    return params


def _process_response(response: httpx.Response) -> Any:
    """Parse a response, mapping non-2xx envelopes to typed errors.

    202 is a success here: the API returns it for a solve that is still
    pending/solving, with the solve resource as the body.
    """
    try:
        payload = response.json() if response.content else None
    except ValueError:
        raise APIError(
            f"Unexpected non-JSON response (HTTP {response.status_code}): "
            f"{response.text[:200]}",
            status=response.status_code,
        ) from None

    if response.status_code < 400:
        return payload

    error = (payload or {}).get("error") if isinstance(payload, dict) else None
    error = error if isinstance(error, dict) else {}
    raise error_from_response(
        response.status_code,
        error.get("code"),
        error.get("message") or f"HTTP {response.status_code}",
        error.get("param"),
    )


class _BaseClient:
    def __init__(self, *, api_key: str, base_url: Optional[str], timeout: float) -> None:
        if not api_key:
            raise ValueError(
                "A NoneCap API key is required. Pass it as NoneCap(api_key=...)."
            )
        self._api_key = api_key
        self._base_url = (base_url or DEFAULT_BASE_URL).rstrip("/")
        self._timeout = timeout

    def _url(self, path: str) -> str:
        return self._base_url + path

    @property
    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self._api_key}",
            "Accept": "application/json",
            "User-Agent": _USER_AGENT,
        }


# ---------------------------------------------------------------------------
# Sync
# ---------------------------------------------------------------------------


class Solves:
    """Operations on solves (sync). Reached as ``client.solves``."""

    def __init__(self, client: NoneCap) -> None:
        self._client = client

    @overload
    def create(
        self,
        *,
        type: Literal["hcaptcha"],
        sitekey: str,
        url: str,
        rqdata: Optional[str] = None,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        wait: Optional[int] = None,
    ) -> Solve: ...

    @overload
    def create(
        self,
        *,
        type: Literal["hcaptcha_enterprise"],
        sitekey: str,
        url: str,
        rqdata: str,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        wait: Optional[int] = None,
    ) -> Solve: ...

    def create(
        self,
        *,
        type: SolveType,
        sitekey: str,
        url: str,
        rqdata: Optional[str] = None,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        wait: Optional[int] = None,
    ) -> Solve:
        """Submit a solve. Pass ``wait`` (1-90 seconds) to hold the connection
        open until it finishes instead of returning a pending solve."""
        body = _build_solve_body(
            type=type,
            sitekey=sitekey,
            url=url,
            rqdata=rqdata,
            user_agent=user_agent,
            proxy=proxy,
            webhook_url=webhook_url,
        )
        payload = self._client._request(
            "POST",
            "/v1/solves",
            params={"wait": wait} if wait is not None else None,
            json=body,
            wait=wait,
        )
        return Solve._from_dict(payload)

    def retrieve(self, solve_id: str, *, wait: Optional[int] = None) -> Solve:
        """Fetch a solve by id. Pass ``wait`` to long-poll until it finishes."""
        payload = self._client._request(
            "GET",
            f"/v1/solves/{solve_id}",
            params={"wait": wait} if wait is not None else None,
            wait=wait,
        )
        return Solve._from_dict(payload)

    def cancel(self, solve_id: str) -> Solve:
        """Cancel a pending or in-flight solve. Cancelled solves are never charged."""
        payload = self._client._request("DELETE", f"/v1/solves/{solve_id}")
        return Solve._from_dict(payload)

    def list(
        self,
        *,
        limit: Optional[int] = None,
        starting_after: Optional[str] = None,
        status: Optional[SolveStatus] = None,
        type: Optional[SolveType] = None,
    ) -> SolvePage:
        """Fetch one page of solves, newest first."""
        payload = self._client._request(
            "GET",
            "/v1/solves",
            params=_list_params(
                limit=limit, starting_after=starting_after, status=status, type=type
            ),
        )
        return SolvePage._from_dict(payload)

    def list_all(
        self,
        *,
        limit: Optional[int] = None,
        status: Optional[SolveStatus] = None,
        type: Optional[SolveType] = None,
    ) -> Iterator[Solve]:
        """Iterate every solve across pages, newest first.

        >>> for solve in client.solves.list_all():
        ...     print(solve.id, solve.status)
        """
        cursor: Optional[str] = None
        while True:
            page = self.list(limit=limit, starting_after=cursor, status=status, type=type)
            yield from page.data
            if not page.has_more or not page.data:
                return
            cursor = page.data[-1].id


class NoneCap(_BaseClient):
    """The NoneCap API client (sync).

    >>> from nonecap import NoneCap
    >>> nc = NoneCap(api_key="nc_live_...")
    >>> solve = nc.solve(type="hcaptcha", sitekey="...", url="https://example.com")
    >>> solve.token
    'P1_...'
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
        http_client: Optional[httpx.Client] = None,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout)
        self._http = http_client or httpx.Client()
        self._owns_http = http_client is None
        self.solves = Solves(self)

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        wait: Optional[int] = None,
    ) -> Any:
        try:
            response = self._http.request(
                method,
                self._url(path),
                params=params,
                json=json,
                headers=self._headers,
                timeout=_request_timeout_for_wait(wait, self._timeout),
            )
        except httpx.TimeoutException as exc:
            raise APITimeoutError(f"Request to {path} timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(
                f"Could not reach the NoneCap API at {self._base_url}: {exc}"
            ) from exc
        return _process_response(response)

    @overload
    def solve(
        self,
        *,
        type: Literal["hcaptcha"],
        sitekey: str,
        url: str,
        rqdata: Optional[str] = None,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        timeout: float = DEFAULT_SOLVE_TIMEOUT,
    ) -> Solve: ...

    @overload
    def solve(
        self,
        *,
        type: Literal["hcaptcha_enterprise"],
        sitekey: str,
        url: str,
        rqdata: str,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        timeout: float = DEFAULT_SOLVE_TIMEOUT,
    ) -> Solve: ...

    def solve(
        self,
        *,
        type: SolveType,
        sitekey: str,
        url: str,
        rqdata: Optional[str] = None,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        timeout: float = DEFAULT_SOLVE_TIMEOUT,
    ) -> Solve:
        """Submit a solve and wait for it to finish, returning the solved solve.

        Uses the server's long-poll under the hood and keeps polling until the
        solve is terminal or ``timeout`` seconds elapse. Raises
        :class:`SolveFailedError` if the solve fails/expires/is cancelled, or
        :class:`SolveTimeoutError` on timeout.
        """
        deadline = time.monotonic() + timeout
        # Build the body directly rather than dispatching through the
        # overloaded create(): the union-typed passthrough args defeat
        # overload resolution, and the runtime rqdata check lives in
        # _build_solve_body either way.
        body = _build_solve_body(
            type=type,
            sitekey=sitekey,
            url=url,
            rqdata=rqdata,
            user_agent=user_agent,
            proxy=proxy,
            webhook_url=webhook_url,
        )
        wait = _wait_seconds(deadline)
        payload = self._request(
            "POST", "/v1/solves", params={"wait": wait}, json=body, wait=wait
        )
        solve = Solve._from_dict(payload)
        while not solve.is_terminal:
            if time.monotonic() >= deadline:
                raise SolveTimeoutError(
                    f"Solve {solve.id} did not finish within {timeout:g}s "
                    f"(last status: {solve.status})."
                )
            solve = self.solves.retrieve(solve.id, wait=_wait_seconds(deadline))
        if solve.status != "solved":
            raise SolveFailedError(solve)
        return solve

    def me(self) -> Account:
        """Fetch your account, including the current credit balance."""
        return Account._from_dict(self._request("GET", "/v1/me"))

    def close(self) -> None:
        """Close the underlying HTTP client (only if this client created it)."""
        if self._owns_http:
            self._http.close()

    def __enter__(self) -> NoneCap:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()


# ---------------------------------------------------------------------------
# Async
# ---------------------------------------------------------------------------


class AsyncSolves:
    """Operations on solves (async). Reached as ``client.solves``."""

    def __init__(self, client: AsyncNoneCap) -> None:
        self._client = client

    @overload
    async def create(
        self,
        *,
        type: Literal["hcaptcha"],
        sitekey: str,
        url: str,
        rqdata: Optional[str] = None,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        wait: Optional[int] = None,
    ) -> Solve: ...

    @overload
    async def create(
        self,
        *,
        type: Literal["hcaptcha_enterprise"],
        sitekey: str,
        url: str,
        rqdata: str,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        wait: Optional[int] = None,
    ) -> Solve: ...

    async def create(
        self,
        *,
        type: SolveType,
        sitekey: str,
        url: str,
        rqdata: Optional[str] = None,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        wait: Optional[int] = None,
    ) -> Solve:
        """Submit a solve. Pass ``wait`` (1-90 seconds) to hold the connection
        open until it finishes instead of returning a pending solve."""
        body = _build_solve_body(
            type=type,
            sitekey=sitekey,
            url=url,
            rqdata=rqdata,
            user_agent=user_agent,
            proxy=proxy,
            webhook_url=webhook_url,
        )
        payload = await self._client._request(
            "POST",
            "/v1/solves",
            params={"wait": wait} if wait is not None else None,
            json=body,
            wait=wait,
        )
        return Solve._from_dict(payload)

    async def retrieve(self, solve_id: str, *, wait: Optional[int] = None) -> Solve:
        """Fetch a solve by id. Pass ``wait`` to long-poll until it finishes."""
        payload = await self._client._request(
            "GET",
            f"/v1/solves/{solve_id}",
            params={"wait": wait} if wait is not None else None,
            wait=wait,
        )
        return Solve._from_dict(payload)

    async def cancel(self, solve_id: str) -> Solve:
        """Cancel a pending or in-flight solve. Cancelled solves are never charged."""
        payload = await self._client._request("DELETE", f"/v1/solves/{solve_id}")
        return Solve._from_dict(payload)

    async def list(
        self,
        *,
        limit: Optional[int] = None,
        starting_after: Optional[str] = None,
        status: Optional[SolveStatus] = None,
        type: Optional[SolveType] = None,
    ) -> SolvePage:
        """Fetch one page of solves, newest first."""
        payload = await self._client._request(
            "GET",
            "/v1/solves",
            params=_list_params(
                limit=limit, starting_after=starting_after, status=status, type=type
            ),
        )
        return SolvePage._from_dict(payload)

    async def list_all(
        self,
        *,
        limit: Optional[int] = None,
        status: Optional[SolveStatus] = None,
        type: Optional[SolveType] = None,
    ) -> AsyncIterator[Solve]:
        """Iterate every solve across pages, newest first.

        >>> async for solve in client.solves.list_all():
        ...     print(solve.id, solve.status)
        """
        cursor: Optional[str] = None
        while True:
            page = await self.list(
                limit=limit, starting_after=cursor, status=status, type=type
            )
            for solve in page.data:
                yield solve
            if not page.has_more or not page.data:
                return
            cursor = page.data[-1].id


class AsyncNoneCap(_BaseClient):
    """The NoneCap API client (async).

    >>> from nonecap import AsyncNoneCap
    >>> async with AsyncNoneCap(api_key="nc_live_...") as nc:
    ...     solve = await nc.solve(type="hcaptcha", sitekey="...", url="https://example.com")
    """

    def __init__(
        self,
        *,
        api_key: str,
        base_url: Optional[str] = None,
        timeout: float = DEFAULT_REQUEST_TIMEOUT,
        http_client: Optional[httpx.AsyncClient] = None,
    ) -> None:
        super().__init__(api_key=api_key, base_url=base_url, timeout=timeout)
        self._http = http_client or httpx.AsyncClient()
        self._owns_http = http_client is None
        self.solves = AsyncSolves(self)

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: Optional[dict[str, Any]] = None,
        json: Optional[dict[str, Any]] = None,
        wait: Optional[int] = None,
    ) -> Any:
        try:
            response = await self._http.request(
                method,
                self._url(path),
                params=params,
                json=json,
                headers=self._headers,
                timeout=_request_timeout_for_wait(wait, self._timeout),
            )
        except httpx.TimeoutException as exc:
            raise APITimeoutError(f"Request to {path} timed out: {exc}") from exc
        except httpx.HTTPError as exc:
            raise APIConnectionError(
                f"Could not reach the NoneCap API at {self._base_url}: {exc}"
            ) from exc
        return _process_response(response)

    @overload
    async def solve(
        self,
        *,
        type: Literal["hcaptcha"],
        sitekey: str,
        url: str,
        rqdata: Optional[str] = None,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        timeout: float = DEFAULT_SOLVE_TIMEOUT,
    ) -> Solve: ...

    @overload
    async def solve(
        self,
        *,
        type: Literal["hcaptcha_enterprise"],
        sitekey: str,
        url: str,
        rqdata: str,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        timeout: float = DEFAULT_SOLVE_TIMEOUT,
    ) -> Solve: ...

    async def solve(
        self,
        *,
        type: SolveType,
        sitekey: str,
        url: str,
        rqdata: Optional[str] = None,
        user_agent: Optional[str] = None,
        proxy: Union[Proxy, str, None] = None,
        webhook_url: Optional[str] = None,
        timeout: float = DEFAULT_SOLVE_TIMEOUT,
    ) -> Solve:
        """Submit a solve and wait for it to finish, returning the solved solve.

        Uses the server's long-poll under the hood and keeps polling until the
        solve is terminal or ``timeout`` seconds elapse. Raises
        :class:`SolveFailedError` if the solve fails/expires/is cancelled, or
        :class:`SolveTimeoutError` on timeout.
        """
        deadline = time.monotonic() + timeout
        # Same shape as the sync client: build the body directly instead of
        # dispatching through the overloaded create() with union-typed args.
        body = _build_solve_body(
            type=type,
            sitekey=sitekey,
            url=url,
            rqdata=rqdata,
            user_agent=user_agent,
            proxy=proxy,
            webhook_url=webhook_url,
        )
        wait = _wait_seconds(deadline)
        payload = await self._request(
            "POST", "/v1/solves", params={"wait": wait}, json=body, wait=wait
        )
        solve = Solve._from_dict(payload)
        while not solve.is_terminal:
            if time.monotonic() >= deadline:
                raise SolveTimeoutError(
                    f"Solve {solve.id} did not finish within {timeout:g}s "
                    f"(last status: {solve.status})."
                )
            solve = await self.solves.retrieve(solve.id, wait=_wait_seconds(deadline))
        if solve.status != "solved":
            raise SolveFailedError(solve)
        return solve

    async def me(self) -> Account:
        """Fetch your account, including the current credit balance."""
        return Account._from_dict(await self._request("GET", "/v1/me"))

    async def close(self) -> None:
        """Close the underlying HTTP client (only if this client created it)."""
        if self._owns_http:
            await self._http.aclose()

    async def __aenter__(self) -> AsyncNoneCap:
        return self

    async def __aexit__(self, *exc_info: object) -> None:
        await self.close()
