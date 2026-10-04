from __future__ import annotations

import base64
from typing import Any

import httpx
import pytest

from nonecap import (
    AsyncNoneCap,
    ConcurrencyLimitError,
    InsufficientCreditsError,
    NoneCap,
    NotFoundError,
    PayloadTooLargeError,
    RecognitionFailedError,
    RecognizeTasklist,
    ValidationError,
)

from .conftest import Script, error_payload

PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
PNG_B64 = base64.b64encode(PNG).decode("ascii")
SESSION_ID = "extsess_01JABCDEFGHJKMNPQRSTVWXYZ0"


def client_for(script: Script) -> NoneCap:
    return NoneCap(api_key="nc_test", http_client=httpx.Client(transport=script.transport))


def async_client_for(script: Script) -> AsyncNoneCap:
    return AsyncNoneCap(
        api_key="nc_test", http_client=httpx.AsyncClient(transport=script.transport)
    )


def recognition_payload(**overrides: Any) -> dict[str, Any]:
    base: dict[str, Any] = {
        "id": SESSION_ID,
        "data": [True, False, True],
        "credits_charged": 10,
    }
    base.update(overrides)
    return base


def drag_tasklist() -> RecognizeTasklist:
    return {
        "request_type": "image_drag_drop",
        "requester_question": {"en": "Drag the piece to complete the image"},
        "tasklist": [
            {
                "task_key": "k1",
                "datapoint_uri": PNG_B64,
                "entities": [
                    {
                        "entity_id": "e1",
                        "entity_uri": PNG_B64,
                        "coords": [10, 20],
                        "size": [40, 30],
                    }
                ],
            }
        ],
    }


class TestRecognize:
    def test_posts_the_simple_form_with_bearer_auth(self) -> None:
        script = Script((200, recognition_payload()))
        rec = client_for(script).recognize(
            type="hcaptcha",
            task="Please click each image containing a bus",
            image_data=[PNG_B64, PNG_B64, PNG_B64],
            host="example.com",
        )

        request = script.requests[0]
        assert request.method == "POST"
        assert request.url.path == "/v1/recognize"
        assert request.headers["Authorization"] == "Bearer nc_test"
        assert script.body_of(0) == {
            "type": "hcaptcha",
            "task": "Please click each image containing a bus",
            "image_data": [PNG_B64, PNG_B64, PNG_B64],
            "host": "example.com",
        }
        assert rec.id == SESSION_ID
        assert rec.data == [True, False, True]
        assert rec.points is None
        assert rec.credits_charged == 10

    def test_base64_encodes_raw_image_bytes(self) -> None:
        script = Script((200, recognition_payload()))
        client_for(script).recognize(
            type="hcaptcha",
            task="t",
            image_data=[PNG, "data:image/png;base64," + PNG_B64],
            image_examples=[PNG],
        )
        body = script.body_of(0)
        assert body["image_data"] == [PNG_B64, "data:image/png;base64," + PNG_B64]
        assert body["image_examples"] == [PNG_B64]

    def test_area_select_returns_the_box_and_every_point(self) -> None:
        script = Script(
            (
                200,
                recognition_payload(
                    data={"x": 12.5, "y": 40.0, "w": 0, "h": 0},
                    points=[{"x": 12.5, "y": 40.0}, {"x": 70.0, "y": 22.25}],
                ),
            )
        )
        rec = client_for(script).recognize(
            type="hcaptcha_area_select",
            task="Please click on the head of the animal",
            image_urls=["https://imgs.hcaptcha.com/abc"],
        )
        assert script.body_of(0) == {
            "type": "hcaptcha_area_select",
            "task": "Please click on the head of the animal",
            "image_urls": ["https://imgs.hcaptcha.com/abc"],
        }
        assert rec.data["x"] == 12.5
        assert [p["x"] for p in rec.points] == [12.5, 70.0]

    def test_sends_the_full_tasklist_under_data(self) -> None:
        placements = [[{"entity_id": "e1", "x": 30.0, "y": 50.0, "w": 8.33, "h": 9.38}]]
        script = Script((200, recognition_payload(data=placements)))
        tasklist = drag_tasklist()
        rec = client_for(script).recognize(data=tasklist)

        assert script.body_of(0) == {"data": tasklist}
        assert rec.data == placements
        assert rec.points is None

    def test_refuses_both_forms_at_once(self) -> None:
        script = Script((200, recognition_payload()))
        with pytest.raises(ValueError):
            client_for(script).recognize(data=drag_tasklist(), type="hcaptcha")
        assert script.requests == []

    @pytest.mark.parametrize(
        "images",
        [
            {},
            {"image_data": [PNG_B64], "image_urls": ["https://imgs.hcaptcha.com/abc"]},
        ],
    )
    def test_refuses_anything_but_exactly_one_image_source(
        self, images: dict[str, Any]
    ) -> None:
        script = Script((200, recognition_payload()))
        with pytest.raises(ValueError):
            client_for(script).recognize(type="hcaptcha", task="t", **images)
        assert script.requests == []

    def test_refuses_a_single_image_passed_as_the_list(self) -> None:
        script = Script((200, recognition_payload()))
        with pytest.raises(TypeError):
            client_for(script).recognize(
                type="hcaptcha_area_select",
                task="t",
                image_urls="https://imgs.hcaptcha.com/abc",
            )
        assert script.requests == []

    def test_raises_recognition_failed_when_no_answer_came_back(self) -> None:
        script = Script(
            (
                422,
                error_payload(
                    "recognition_failed", "No answer was found. Nothing was charged."
                ),
            )
        )
        with pytest.raises(RecognitionFailedError) as excinfo:
            client_for(script).recognize(type="hcaptcha", task="t", image_data=[PNG_B64])
        assert excinfo.value.status == 422
        assert excinfo.value.code == "recognition_failed"

    @pytest.mark.parametrize(
        ("status", "code", "error"),
        [
            (422, "validation_error", ValidationError),
            (413, "payload_too_large", PayloadTooLargeError),
            (402, "insufficient_credits", InsufficientCreditsError),
        ],
    )
    def test_maps_request_errors(self, status: int, code: str, error: type[Exception]) -> None:
        script = Script((status, error_payload(code, param="image_data[0]")))
        with pytest.raises(error):
            client_for(script).recognize(type="hcaptcha", task="t", image_data=[PNG_B64])

    def test_concurrency_limit_carries_retry_after(self) -> None:
        script = Script(
            lambda request: httpx.Response(
                429,
                json=error_payload("concurrency_limit_exceeded", "too many in flight"),
                headers={"Retry-After": "1"},
            )
        )
        with pytest.raises(ConcurrencyLimitError) as excinfo:
            client_for(script).recognize(type="hcaptcha", task="t", image_data=[PNG_B64])
        assert excinfo.value.retry_after == 1


class TestReportRecognitionOutcome:
    def test_posts_the_outcome(self) -> None:
        script = Script((200, {"id": SESSION_ID, "result": "failed", "refunded_credits": 0}))
        result = client_for(script).report_recognition_outcome(SESSION_ID, "failed")

        assert script.requests[0].method == "POST"
        assert script.requests[0].url.path == "/v1/recognize/outcome"
        assert script.body_of(0) == {"id": SESSION_ID, "result": "failed"}
        assert result.id == SESSION_ID
        assert result.result == "failed"
        assert result.refunded_credits == 0

    def test_raises_not_found_for_an_unknown_id(self) -> None:
        script = Script((404, error_payload("not_found")))
        with pytest.raises(NotFoundError):
            client_for(script).report_recognition_outcome(SESSION_ID, "solved")

    def test_a_repeat_returns_the_first_report(self) -> None:
        script = Script((200, {"id": SESSION_ID, "result": "solved", "refunded_credits": 0}))
        result = client_for(script).report_recognition_outcome(SESSION_ID, "failed")
        assert result.result == "solved"


class TestAsyncRecognize:
    async def test_recognize(self) -> None:
        script = Script((200, recognition_payload()))
        async with async_client_for(script) as nc:
            rec = await nc.recognize(type="hcaptcha", task="t", image_data=[PNG])
        assert script.requests[0].url.path == "/v1/recognize"
        assert script.body_of(0) == {"type": "hcaptcha", "task": "t", "image_data": [PNG_B64]}
        assert rec.data == [True, False, True]

    async def test_recognize_full_tasklist_area_select(self) -> None:
        tasklist: RecognizeTasklist = {
            "request_type": "image_label_area_select",
            "requester_question": {"en": "Please click on the head of the animal"},
            "tasklist": [
                {"task_key": "k1", "datapoint_uri": PNG_B64},
                {"task_key": "k2", "datapoint_uri": PNG_B64},
            ],
        }
        script = Script(
            (
                200,
                recognition_payload(
                    data=[{"x": 10.0, "y": 20.0, "w": 0, "h": 0}, None],
                    points=[[{"x": 10.0, "y": 20.0}], []],
                ),
            )
        )
        async with async_client_for(script) as nc:
            rec = await nc.recognize(data=tasklist, host="example.com")
        assert script.body_of(0) == {"data": tasklist, "host": "example.com"}
        assert rec.data[1] is None
        assert rec.points == [[{"x": 10.0, "y": 20.0}], []]

    async def test_recognize_failed(self) -> None:
        script = Script((422, error_payload("recognition_failed")))
        async with async_client_for(script) as nc:
            with pytest.raises(RecognitionFailedError):
                await nc.recognize(type="hcaptcha", task="t", image_data=[PNG_B64])

    async def test_report_recognition_outcome(self) -> None:
        script = Script((200, {"id": SESSION_ID, "result": "solved", "refunded_credits": 0}))
        async with async_client_for(script) as nc:
            result = await nc.report_recognition_outcome(SESSION_ID, "solved")
        assert script.requests[0].url.path == "/v1/recognize/outcome"
        assert script.body_of(0) == {"id": SESSION_ID, "result": "solved"}
        assert result.refunded_credits == 0
