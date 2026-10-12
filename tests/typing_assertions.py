"""Compile-time checks for the public types. This file is type-checked by
``mypy --strict`` in CI, never executed (no ``test_`` prefix, so pytest skips
it).

The negative cases lean on ``warn_unused_ignores = true``: each ``# type:
ignore[...]`` below marks a call that MUST be a type error. If the signatures
ever stop rejecting it, the ignore becomes unused and mypy fails the build.
"""

from __future__ import annotations

from typing import Optional

from nonecap import (
    AsyncNoneCap,
    AsyncSolveHandle,
    Feedback,
    FeedbackBatch,
    FeedbackReport,
    NoneCap,
    Recognition,
    RecognitionOutcomeResult,
    RecognitionTasklistData,
    RecognizeBox,
    RecognizePoint,
    RecognizeTasklist,
    Solve,
    SolveErrorReason,
    SolveHandle,
    SolveTimeoutError,
)

nc = NoneCap(api_key="k")
anc = AsyncNoneCap(api_key="k")


def positive_cases() -> None:
    # hcaptcha: rqdata optional.
    nc.solve(type="hcaptcha", sitekey="s", url="u")
    nc.solve(type="hcaptcha", sitekey="s", url="u", rqdata="r")
    # enterprise: rqdata optional too.
    nc.solve(type="hcaptcha_enterprise", sitekey="s", url="u")
    nc.solves.create(type="hcaptcha_enterprise", sitekey="s", url="u")
    nc.solve(type="hcaptcha_enterprise", sitekey="s", url="u", rqdata="r")
    nc.solves.create(type="hcaptcha_enterprise", sitekey="s", url="u", rqdata="r")
    # start() returns a handle; result()/cancel() return Solve.
    handle: SolveHandle = nc.solves.start(type="hcaptcha", sitekey="s", url="u")
    _id: str = handle.id
    _r: Solve = handle.result()
    _r2: Solve = handle.result(timeout=10.0)
    _c: Solve = handle.cancel()
    nc.solves.start(type="hcaptcha_enterprise", sitekey="s", url="u", rqdata="r")


async def positive_cases_async() -> None:
    await anc.solve(type="hcaptcha", sitekey="s", url="u")
    await anc.solves.create(type="hcaptcha_enterprise", sitekey="s", url="u", rqdata="r")
    await anc.solve(type="hcaptcha_enterprise", sitekey="s", url="u")
    handle: AsyncSolveHandle = await anc.solves.start(type="hcaptcha", sitekey="s", url="u")
    _id: str = handle.id
    _r: Solve = await handle.result()
    _r2: Solve = await handle.result(timeout=10.0)
    _c: Solve = await handle.cancel()


def feedback_cases() -> None:
    _f: Feedback = nc.feedback.report("solve_1", outcome="accepted")
    nc.feedback.report("solve_1", outcome="rejected", reason="why", context="ctx")
    reports: list[FeedbackReport] = [
        {"solve_id": "solve_1", "outcome": "accepted"},
        {"solve_id": "solve_2", "outcome": "rejected", "reason": "why", "context": "ctx"},
    ]
    _b: FeedbackBatch = nc.feedback.report_many(reports)
    # An unknown outcome must not type-check.
    nc.feedback.report("solve_1", outcome="maybe")  # type: ignore[arg-type]
    # A report missing `outcome` must not type-check.
    _bad: FeedbackReport = {"solve_id": "solve_1"}  # type: ignore[typeddict-item]


async def feedback_cases_async() -> None:
    _f: Feedback = await anc.feedback.report("solve_1", outcome="unused")
    _b: FeedbackBatch = await anc.feedback.report_many(
        [{"solve_id": "solve_1", "outcome": "accepted"}]
    )


def recognize_cases() -> None:
    grid: Recognition[list[bool], None] = nc.recognize(
        type="hcaptcha", task="t", image_data=["b64", b"raw"]
    )
    _tiles: list[bool] = grid.data
    area: Recognition[RecognizeBox, list[RecognizePoint]] = nc.recognize(
        type="hcaptcha_area_select", task="t", image_urls=["https://imgs.hcaptcha.com/x"]
    )
    _x: float = area.data["x"]
    _first: RecognizePoint = area.points[0]
    tasklist: RecognizeTasklist = {
        "request_type": "image_drag_drop",
        "requester_question": {"en": "t"},
        "tasklist": [
            {
                "task_key": "k",
                "datapoint_uri": "b64",
                "entities": [{"entity_id": "e", "coords": [1, 2], "size": [3.5, 4]}],
            }
        ],
    }
    full: Recognition[RecognitionTasklistData, Optional[list[list[RecognizePoint]]]] = (
        nc.recognize(data=tasklist, host="example.com")
    )
    _id: str = full.id
    _o: RecognitionOutcomeResult = nc.report_recognition_outcome(full.id, "failed")
    # An unknown recognition type must not type-check.
    nc.recognize(type="hcaptcha_multiple_choice", task="t", image_data=["b64"])  # type: ignore[call-overload]
    # The simple form and the tasklist do not mix.
    nc.recognize(data=tasklist, type="hcaptcha", task="t")  # type: ignore[call-overload]
    # An outcome other than solved/failed must not type-check.
    nc.report_recognition_outcome("extsess_1", "accepted")  # type: ignore[arg-type]
    # A tasklist with an unknown request_type must not type-check.
    _bad: RecognizeTasklist = {
        "request_type": "image_label_multiple_choice",  # type: ignore[typeddict-item]
        "requester_question": {"en": "t"},
        "tasklist": [],
    }


async def recognize_cases_async() -> None:
    grid = await anc.recognize(type="hcaptcha", task="t", image_data=[b"raw"])
    _tiles: list[bool] = grid.data
    _o: RecognitionOutcomeResult = await anc.report_recognition_outcome(grid.id, "solved")


def negative_cases() -> None:
    # A non-string rqdata must not type-check.
    nc.solve(type="hcaptcha_enterprise", sitekey="s", url="u", rqdata=1)  # type: ignore[arg-type]
    # Unknown captcha type must not type-check.
    nc.solve(type="recaptcha", sitekey="s", url="u")  # type: ignore[arg-type]


def egress_blocked_reasons() -> None:
    # The egress guard's reasons are part of the typed vocabulary.
    _r1: SolveErrorReason = "proxy_egress_blocked"
    _r2: SolveErrorReason = "target_egress_blocked"
    _r3: SolveErrorReason = "profile_engine_unavailable"
    _r4: SolveErrorReason = "type_not_served"
    _r5: SolveErrorReason = "browser_lane_capped"
    _r6: SolveErrorReason = "recaptcha_not_loaded"
    _r7: SolveErrorReason = "refused_wording_unescaped"
    _r8: SolveErrorReason = "session_capped"
    # A reason the API never defined must not type-check.
    _bad: SolveErrorReason = "proxy_egress_blockd"  # type: ignore[assignment]


def timeout_error_fields(err: SolveTimeoutError) -> None:
    # SolveTimeoutError exposes the solve it timed out on.
    _sid: Optional[str] = err.solve_id
    _solve: Optional[Solve] = err.solve


async def negative_cases_async() -> None:
    await anc.solves.create(type="recaptcha", sitekey="s", url="u")  # type: ignore[arg-type]
