from __future__ import annotations

import asyncio
from typing import Any

import httpx
import pytest

from nonecap import AsyncNoneCap, SolveFailedError, SolveTimeoutError, ValidationError

from .conftest import Script, error_payload, solve_payload


def client_for(script: Script) -> AsyncNoneCap:
    return AsyncNoneCap(
        api_key="nc_test",
        http_client=httpx.AsyncClient(transport=script.transport),
    )


async def test_create_posts_with_bearer_auth() -> None:
    script = Script((202, solve_payload()))
    nc = client_for(script)
    await nc.solves.create(type="hcaptcha", sitekey="sk", url="https://e.com")
    request = script.requests[0]
    assert request.method == "POST"
    assert request.headers["Authorization"] == "Bearer nc_test"


async def test_solve_polls_until_terminal() -> None:
    script = Script(
        (202, solve_payload(status="pending")),
        (202, solve_payload(status="solving")),
        (200, solve_payload(status="solved", token="TOK")),
    )
    nc = client_for(script)
    solve = await nc.solve(type="hcaptcha", sitekey="sk", url="https://e.com")
    assert solve.token == "TOK"
    assert len(script.requests) == 3


async def test_solve_failed_raises_with_solve_attached() -> None:
    failed = solve_payload(status="failed", error={"code": "unsolvable", "message": "no"})
    script = Script((200, failed))
    nc = client_for(script)
    with pytest.raises(SolveFailedError) as exc_info:
        await nc.solve(type="hcaptcha", sitekey="sk", url="https://e.com")
    assert exc_info.value.solve.status == "failed"


async def test_solve_times_out() -> None:
    script = Script((202, solve_payload(status="solving")))
    nc = client_for(script)
    with pytest.raises(SolveTimeoutError):
        await nc.solve(type="hcaptcha", sitekey="sk", url="https://e.com", timeout=0)


async def test_enterprise_without_rqdata_raises_locally() -> None:
    script = Script((202, solve_payload()))
    nc = client_for(script)
    with pytest.raises(ValidationError):
        await nc.solves.create(type="hcaptcha_enterprise", sitekey="sk", url="https://e.com")  # type: ignore[call-overload]
    assert script.requests == []


async def test_list_all_walks_pages() -> None:
    page1 = {
        "object": "list",
        "data": [solve_payload(id="a"), solve_payload(id="b")],
        "has_more": True,
    }
    page2 = {"object": "list", "data": [solve_payload(id="c")], "has_more": False}
    script = Script((200, page1), (200, page2))
    nc = client_for(script)
    ids = [s.id async for s in nc.solves.list_all()]
    assert ids == ["a", "b", "c"]
    assert script.requests[1].url.params["starting_after"] == "b"


async def test_me() -> None:
    account = {
        "object": "account",
        "id": "u_1",
        "email": "a@b.com",
        "credits_balance": 7,
        "created_at": "x",
    }
    script = Script((200, account))
    nc = client_for(script)
    me = await nc.me()
    assert me.credits_balance == 7


async def test_start_returns_handle_then_result_polls() -> None:
    script = Script(
        (202, solve_payload(status="pending")),
        (200, solve_payload(status="solved", token="TOK")),
    )
    nc = client_for(script)
    handle = await nc.solves.start(type="hcaptcha", sitekey="sk", url="https://e.com")
    assert handle.id == "solve_1"
    assert len(script.requests) == 1  # only the create POST
    solve = await handle.result()
    assert solve.token == "TOK"
    assert len(script.requests) == 2


async def test_result_is_cached_when_awaited_twice() -> None:
    script = Script(
        (202, solve_payload(status="pending")),
        (200, solve_payload(status="solved", token="TOK")),
    )
    nc = client_for(script)
    handle = await nc.solves.start(type="hcaptcha", sitekey="sk", url="https://e.com")
    first = await handle.result()
    count = len(script.requests)
    second = await handle.result()
    assert first is second
    assert len(script.requests) == count


async def test_handle_cancel_after_terminal_swallows_conflict() -> None:
    script = Script(
        (202, solve_payload(status="pending")),
        (409, error_payload("conflict")),
        (200, solve_payload(status="solved", token="TOK")),
    )
    nc = client_for(script)
    handle = await nc.solves.start(type="hcaptcha", sitekey="sk", url="https://e.com")
    solve = await handle.cancel()
    assert solve.status == "solved"
    assert script.requests[1].method == "DELETE"
    assert script.requests[2].method == "GET"


async def test_handle_result_times_out() -> None:
    script = Script((202, solve_payload(status="solving")))
    nc = client_for(script)
    handle = await nc.solves.start(type="hcaptcha", sitekey="sk", url="https://e.com")
    with pytest.raises(SolveTimeoutError):
        await handle.result(timeout=0)


async def test_timeout_carries_solve_id_and_solve() -> None:
    script = Script((202, solve_payload(status="solving")))
    nc = client_for(script)
    handle = await nc.solves.start(type="hcaptcha", sitekey="sk", url="https://e.com")
    with pytest.raises(SolveTimeoutError) as exc_info:
        await handle.result(timeout=0)
    assert exc_info.value.solve_id == "solve_1"
    assert exc_info.value.solve is not None
    assert exc_info.value.solve.status == "solving"


async def test_timeout_is_not_cached_and_resumes() -> None:
    script = Script(
        (202, solve_payload(status="solving")),
        (200, solve_payload(status="solved", token="TOK")),
    )
    nc = client_for(script)
    handle = await nc.solves.start(type="hcaptcha", sitekey="sk", url="https://e.com")
    with pytest.raises(SolveTimeoutError):
        await handle.result(timeout=0)
    assert len(script.requests) == 1  # the timeout never polled
    solve = await handle.result(timeout=30)
    assert solve.token == "TOK"
    assert len(script.requests) == 2  # re-polled, did not replay the timeout


async def test_concurrent_result_calls_share_one_poll() -> None:
    script = Script(
        (202, solve_payload(status="pending")),
        (200, solve_payload(status="solved", token="TOK")),
    )
    nc = client_for(script)
    handle = await nc.solves.start(type="hcaptcha", sitekey="sk", url="https://e.com")
    first, second = await asyncio.gather(handle.result(), handle.result())
    assert first is second  # both observe the same settled outcome
    assert first.token == "TOK"
    # one POST + exactly one shared GET poll, not two.
    assert len(script.requests) == 2
    assert sum(1 for r in script.requests if r.method == "GET") == 1


async def test_cancel_then_result_settles_to_cancelled_without_polling() -> None:
    script = Script(
        (202, solve_payload(status="pending")),
        (200, solve_payload(status="cancelled")),
    )
    nc = client_for(script)
    handle = await nc.solves.start(type="hcaptcha", sitekey="sk", url="https://e.com")
    await handle.cancel()
    with pytest.raises(SolveFailedError) as exc_info:
        await handle.result()
    assert exc_info.value.solve.status == "cancelled"
    assert len(script.requests) == 2  # POST + DELETE only


class _GatedTransport(httpx.AsyncBaseTransport):
    """Async transport whose GET polls block until ``release`` is set, so a
    cancel() can land while a result() poll is genuinely in flight."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.get_count = 0
        self.requests: list[httpx.Request] = []

    async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        if request.method == "POST":
            return httpx.Response(202, json=solve_payload(status="pending"))
        if request.method == "DELETE":
            return httpx.Response(200, json=solve_payload(status="cancelled"))
        # GET poll: block so the test can interleave a cancel().
        self.get_count += 1
        await self.release.wait()
        return httpx.Response(200, json=solve_payload(status="pending"))


async def test_cancel_settles_a_result_already_awaiting() -> None:
    transport = _GatedTransport()
    nc = AsyncNoneCap(api_key="k", http_client=httpx.AsyncClient(transport=transport))
    handle = await nc.solves.start(type="hcaptcha", sitekey="sk", url="https://e.com")
    waiter: asyncio.Task[Any] = asyncio.create_task(handle.result(timeout=30))
    # Let result() start polling and block inside the gated GET.
    while transport.get_count == 0:
        await asyncio.sleep(0)
    cancelled = await handle.cancel()
    assert cancelled.status == "cancelled"
    # The already-awaiting result() settles to the cancelled (terminal) solve.
    with pytest.raises(SolveFailedError) as exc_info:
        await waiter
    assert exc_info.value.solve.status == "cancelled"
    transport.release.set()  # unblock any straggler so the client closes cleanly
    await nc.close()


async def test_async_context_manager_closes_owned_client() -> None:
    async with AsyncNoneCap(api_key="k") as nc:
        http = nc._http
    assert http.is_closed
