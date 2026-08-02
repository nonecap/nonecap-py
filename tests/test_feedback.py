from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import httpx
import pytest

from nonecap import (
    FEEDBACK_BATCH_MAX,
    AsyncNoneCap,
    FeedbackReport,
    NoneCap,
    NotFoundError,
    ValidationError,
)

from .conftest import Script, error_payload


def client_for(script: Script) -> NoneCap:
    return NoneCap(api_key="nc_test", http_client=httpx.Client(transport=script.transport))


def async_client_for(script: Script) -> AsyncNoneCap:
    return AsyncNoneCap(
        api_key="nc_test", http_client=httpx.AsyncClient(transport=script.transport)
    )


def feedback_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "object": "feedback",
        "solve_id": "solve_1",
        "outcome": "accepted",
        "estado": None,
        "reason": None,
        "reported_at": None,
        "report_count": 1,
        "created_at": "2026-08-01T00:00:00Z",
        "updated_at": "2026-08-01T00:00:00Z",
    }
    base.update(overrides)
    return base


def batch_payload(request: httpx.Request) -> httpx.Response:
    """Reply to a batch request with every item recorded."""
    import json

    items = json.loads(request.content)["feedback"]
    return httpx.Response(
        200,
        json={
            "object": "feedback_batch",
            "recorded": len(items),
            "updated": 0,
            "unchanged": 0,
            "failed": 0,
            "results": [
                {"solve_id": item["solve_id"], "status": "recorded", "error": None}
                for item in items
            ],
        },
    )


class TestReport:
    def test_posts_to_the_solves_feedback_path(self) -> None:
        script = Script((200, feedback_payload(outcome="rejected", estado=True)))
        nc = client_for(script)
        result = nc.feedback.report(
            "solve_1", outcome="rejected", estado=True, reason="documento no vigente"
        )

        assert script.requests[0].method == "POST"
        assert script.requests[0].url.path == "/v1/solves/solve_1/feedback"
        assert script.body_of(0) == {
            "outcome": "rejected",
            "estado": True,
            "reason": "documento no vigente",
        }
        assert result.outcome == "rejected"
        assert result.estado is True

    def test_omits_fields_the_caller_left_unset(self) -> None:
        script = Script((200, feedback_payload()))
        client_for(script).feedback.report("solve_1", outcome="accepted")
        assert script.body_of(0) == {"outcome": "accepted"}

    def test_sends_estado_false(self) -> None:
        # `if estado:` would drop the accepted signal — the one that matters.
        script = Script((200, feedback_payload(estado=False)))
        client_for(script).feedback.report("solve_1", outcome="accepted", estado=False)
        assert script.body_of(0) == {"outcome": "accepted", "estado": False}

    def test_serializes_a_datetime_reported_at(self) -> None:
        script = Script((200, feedback_payload()))
        client_for(script).feedback.report(
            "solve_1",
            outcome="accepted",
            reported_at=datetime(2026, 8, 1, 14, 3, tzinfo=timezone.utc),
        )
        assert script.body_of(0)["reported_at"] == "2026-08-01T14:03:00+00:00"

    def test_raises_not_found_for_an_unreportable_solve(self) -> None:
        script = Script((404, error_payload("not_found", "solve not found or not reportable")))
        with pytest.raises(NotFoundError):
            client_for(script).feedback.report("solve_x", outcome="accepted")

    def test_raises_validation_error_once_the_window_closed(self) -> None:
        script = Script(
            (422, error_payload("expired_window", "solve is too old", param="solve_id"))
        )
        with pytest.raises(ValidationError) as excinfo:
            client_for(script).feedback.report("solve_old", outcome="accepted")
        assert excinfo.value.code == "expired_window"
        assert excinfo.value.param == "solve_id"


class TestReportMany:
    def test_posts_one_batch_under_the_wire_format(self) -> None:
        script = Script(batch_payload)
        batch = client_for(script).feedback.report_many(
            [
                {"solve_id": "solve_1", "outcome": "accepted", "estado": False},
                {"solve_id": "solve_2", "outcome": "rejected", "estado": True},
            ]
        )

        assert len(script.requests) == 1
        assert script.requests[0].url.path == "/v1/feedback"
        assert script.body_of(0) == {
            "feedback": [
                {"solve_id": "solve_1", "outcome": "accepted", "estado": False},
                {"solve_id": "solve_2", "outcome": "rejected", "estado": True},
            ]
        }
        assert batch.recorded == 2
        assert [r.solve_id for r in batch.results] == ["solve_1", "solve_2"]

    def test_empty_sequence_makes_no_request(self) -> None:
        script = Script((500, {}))
        batch = client_for(script).feedback.report_many([])
        assert script.requests == []
        assert (batch.recorded, batch.updated, batch.unchanged, batch.failed) == (0, 0, 0, 0)
        assert batch.results == []

    def test_splits_over_the_batch_cap_and_merges_in_order(self) -> None:
        reports: list[FeedbackReport] = [
            {"solve_id": f"solve_{i}", "outcome": "accepted"}
            for i in range(FEEDBACK_BATCH_MAX + 3)
        ]
        script = Script(batch_payload)
        batch = client_for(script).feedback.report_many(reports)

        assert len(script.requests) == 2
        assert len(script.body_of(0)["feedback"]) == FEEDBACK_BATCH_MAX
        assert len(script.body_of(1)["feedback"]) == 3
        assert batch.recorded == FEEDBACK_BATCH_MAX + 3
        assert [r.solve_id for r in batch.results] == [r["solve_id"] for r in reports]

    def test_does_not_raise_when_individual_items_fail(self) -> None:
        script = Script(
            (
                200,
                {
                    "object": "feedback_batch",
                    "recorded": 1,
                    "updated": 0,
                    "unchanged": 0,
                    "failed": 1,
                    "results": [
                        {"solve_id": "solve_1", "status": "recorded", "error": None},
                        {
                            "solve_id": "solve_x",
                            "status": "error",
                            "error": {
                                "code": "not_eligible",
                                "message": "solve not found or not reportable",
                                "param": "solve_id",
                            },
                        },
                    ],
                },
            )
        )
        batch = client_for(script).feedback.report_many(
            [
                {"solve_id": "solve_1", "outcome": "accepted"},
                {"solve_id": "solve_x", "outcome": "accepted"},
            ]
        )
        assert batch.failed == 1
        assert batch.results[1].error is not None
        assert batch.results[1].error.code == "not_eligible"


class TestAsyncFeedback:
    async def test_report(self) -> None:
        script = Script((200, feedback_payload(outcome="unused")))
        async with async_client_for(script) as nc:
            result = await nc.feedback.report("solve_1", outcome="unused")
        assert script.requests[0].url.path == "/v1/solves/solve_1/feedback"
        assert script.body_of(0) == {"outcome": "unused"}
        assert result.outcome == "unused"

    async def test_report_many_splits_over_the_batch_cap(self) -> None:
        reports: list[FeedbackReport] = [
            {"solve_id": f"solve_{i}", "outcome": "accepted"}
            for i in range(FEEDBACK_BATCH_MAX + 1)
        ]
        script = Script(batch_payload)
        async with async_client_for(script) as nc:
            batch = await nc.feedback.report_many(reports)

        assert len(script.requests) == 2
        assert batch.recorded == FEEDBACK_BATCH_MAX + 1
        assert [r.solve_id for r in batch.results] == [r["solve_id"] for r in reports]

    async def test_report_many_empty_makes_no_request(self) -> None:
        script = Script((500, {}))
        async with async_client_for(script) as nc:
            batch = await nc.feedback.report_many([])
        assert script.requests == []
        assert batch.results == []
