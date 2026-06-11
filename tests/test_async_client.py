from __future__ import annotations

import httpx
import pytest

from nonecap import AsyncNoneCap, SolveFailedError, SolveTimeoutError, ValidationError

from .conftest import Script, solve_payload


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


async def test_async_context_manager_closes_owned_client() -> None:
    async with AsyncNoneCap(api_key="k") as nc:
        http = nc._http
    assert http.is_closed
