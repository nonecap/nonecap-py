from __future__ import annotations

import httpx
import pytest

from nonecap import (
    APIError,
    AuthenticationError,
    ConflictError,
    InsufficientCreditsError,
    NoneCap,
    NotFoundError,
    PermissionDeniedError,
    RateLimitError,
    SolveFailedError,
    SolveTimeoutError,
    ValidationError,
)

from .conftest import Script, error_payload, solve_payload


def client_for(script: Script, **kwargs: object) -> NoneCap:
    return NoneCap(
        api_key="nc_test",
        http_client=httpx.Client(transport=script.transport),
        **kwargs,  # type: ignore[arg-type]
    )


class TestConstruction:
    def test_requires_api_key(self) -> None:
        with pytest.raises(ValueError, match="API key is required"):
            NoneCap(api_key="")

    def test_trims_trailing_slash_from_base_url(self) -> None:
        script = Script((200, solve_payload()))
        nc = client_for(script, base_url="https://x.test/")
        nc.solves.retrieve("solve_1")
        assert str(script.requests[0].url) == "https://x.test/v1/solves/solve_1"


class TestCreate:
    def test_posts_with_bearer_auth_and_json_body(self) -> None:
        script = Script((202, solve_payload()))
        nc = client_for(script)
        nc.solves.create(type="hcaptcha", sitekey="sk", url="https://e.com")

        request = script.requests[0]
        assert request.method == "POST"
        assert request.url.path == "/v1/solves"
        assert request.headers["Authorization"] == "Bearer nc_test"
        assert script.body_of(0) == {
            "type": "hcaptcha",
            "sitekey": "sk",
            "url": "https://e.com",
        }

    def test_passes_wait_as_query_param(self) -> None:
        script = Script((200, solve_payload(status="solved", token="t")))
        nc = client_for(script)
        nc.solves.create(type="hcaptcha", sitekey="sk", url="https://e.com", wait=30)
        assert script.requests[0].url.params["wait"] == "30"

    def test_202_is_success_not_an_error(self) -> None:
        script = Script((202, solve_payload(status="solving")))
        nc = client_for(script)
        solve = nc.solves.create(type="hcaptcha", sitekey="sk", url="https://e.com")
        assert solve.status == "solving"
        assert not solve.is_terminal

    def test_optional_fields_are_forwarded(self) -> None:
        script = Script((202, solve_payload()))
        nc = client_for(script)
        nc.solves.create(
            type="hcaptcha_enterprise",
            sitekey="sk",
            url="https://e.com",
            rqdata="blob",
            user_agent="UA",
            proxy={"scheme": "http", "host": "1.2.3.4", "port": 8080},
            webhook_url="https://hook.test",
        )
        body = script.body_of(0)
        assert body["rqdata"] == "blob"
        assert body["user_agent"] == "UA"
        assert body["proxy"] == {"scheme": "http", "host": "1.2.3.4", "port": 8080}
        assert body["webhook_url"] == "https://hook.test"

    def test_enterprise_without_rqdata_raises_locally(self) -> None:
        script = Script((202, solve_payload()))
        nc = client_for(script)
        with pytest.raises(ValidationError) as exc_info:
            nc.solves.create(type="hcaptcha_enterprise", sitekey="sk", url="https://e.com")  # type: ignore[call-overload]  # noqa: E501
        assert exc_info.value.param == "rqdata"
        assert script.requests == []  # never hit the network


class TestList:
    def test_forwards_list_params_as_query(self) -> None:
        script = Script((200, {"object": "list", "data": [], "has_more": False}))
        nc = client_for(script)
        page = nc.solves.list(
            limit=50, status="solved", type="hcaptcha", starting_after="solve_9"
        )
        params = script.requests[0].url.params
        assert params["limit"] == "50"
        assert params["status"] == "solved"
        assert params["type"] == "hcaptcha"
        assert params["starting_after"] == "solve_9"
        assert page.data == [] and page.has_more is False

    def test_list_all_walks_pages_until_has_more_false(self) -> None:
        page1 = {
            "object": "list",
            "data": [solve_payload(id="a"), solve_payload(id="b")],
            "has_more": True,
        }
        page2 = {"object": "list", "data": [solve_payload(id="c")], "has_more": False}
        script = Script((200, page1), (200, page2))
        nc = client_for(script)
        ids = [s.id for s in nc.solves.list_all()]
        assert ids == ["a", "b", "c"]
        assert script.requests[1].url.params["starting_after"] == "b"


class TestMe:
    def test_gets_v1_me(self) -> None:
        account = {
            "object": "account",
            "id": "u_1",
            "email": "a@b.com",
            "credits_balance": 42,
            "created_at": "x",
        }
        script = Script((200, account))
        nc = client_for(script)
        me = nc.me()
        assert me.credits_balance == 42
        assert script.requests[0].url.path == "/v1/me"


class TestErrorMapping:
    @pytest.mark.parametrize(
        ("status", "code", "expected"),
        [
            (401, "unauthorized", AuthenticationError),
            (403, "forbidden", PermissionDeniedError),
            (403, "account_locked", PermissionDeniedError),
            (402, "insufficient_credits", InsufficientCreditsError),
            (422, "validation_error", ValidationError),
            (429, "concurrency_limit_exceeded", RateLimitError),
            (429, "rate_limited", RateLimitError),
            (409, "conflict", ConflictError),
            (404, "not_found", NotFoundError),
            (500, "internal_error", APIError),
        ],
    )
    def test_maps_envelope_to_subclass(
        self, status: int, code: str, expected: type[Exception]
    ) -> None:
        script = Script((status, error_payload(code)))
        nc = client_for(script)
        with pytest.raises(expected):
            nc.me()

    def test_exposes_param_code_and_status(self) -> None:
        script = Script((422, error_payload("validation_error", "bad", "sitekey")))
        nc = client_for(script)
        with pytest.raises(ValidationError) as exc_info:
            nc.me()
        assert exc_info.value.param == "sitekey"
        assert exc_info.value.code == "validation_error"
        assert exc_info.value.status == 422

    def test_non_json_body_becomes_api_error(self) -> None:
        script = Script(lambda _req: httpx.Response(502, text="<html>502</html>"))
        nc = client_for(script)
        with pytest.raises(APIError, match="non-JSON"):
            nc.me()


class TestSolveHelper:
    def test_returns_immediately_when_create_resolves_solved(self) -> None:
        script = Script((200, solve_payload(status="solved", token="TOK")))
        nc = client_for(script)
        solve = nc.solve(type="hcaptcha", sitekey="sk", url="https://e.com")
        assert solve.token == "TOK"
        assert len(script.requests) == 1  # no extra polling

    def test_polls_retrieve_until_terminal(self) -> None:
        script = Script(
            (202, solve_payload(status="pending")),
            (202, solve_payload(status="solving")),
            (200, solve_payload(status="solved", token="TOK")),
        )
        nc = client_for(script)
        solve = nc.solve(type="hcaptcha", sitekey="sk", url="https://e.com")
        assert solve.token == "TOK"
        assert len(script.requests) == 3
        assert script.requests[1].method == "GET"
        assert script.requests[1].url.path == "/v1/solves/solve_1"

    def test_failed_solve_raises_with_solve_attached(self) -> None:
        failed = solve_payload(
            status="failed", error={"code": "unsolvable", "message": "no"}
        )
        script = Script((200, failed))
        nc = client_for(script)
        with pytest.raises(SolveFailedError) as exc_info:
            nc.solve(type="hcaptcha", sitekey="sk", url="https://e.com")
        assert exc_info.value.solve.error is not None
        assert exc_info.value.solve.error.code == "unsolvable"

    def test_times_out_when_solve_never_finishes(self) -> None:
        script = Script((202, solve_payload(status="solving")))
        nc = client_for(script)
        with pytest.raises(SolveTimeoutError):
            nc.solve(type="hcaptcha", sitekey="sk", url="https://e.com", timeout=0)


class TestLifecycle:
    def test_cancel_deletes(self) -> None:
        script = Script((200, solve_payload(status="cancelled")))
        nc = client_for(script)
        solve = nc.solves.cancel("solve_1")
        assert solve.status == "cancelled"
        assert script.requests[0].method == "DELETE"

    def test_context_manager_closes_owned_client(self) -> None:
        with NoneCap(api_key="k") as nc:
            http = nc._http
        assert http.is_closed

    def test_does_not_close_injected_client(self) -> None:
        external = httpx.Client(transport=Script((200, {})).transport)
        with NoneCap(api_key="k", http_client=external):
            pass
        assert not external.is_closed
        external.close()
