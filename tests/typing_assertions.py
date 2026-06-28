"""Compile-time checks for the public types. This file is type-checked by
``mypy --strict`` in CI, never executed (no ``test_`` prefix, so pytest skips
it).

The negative cases lean on ``warn_unused_ignores = true``: each ``# type:
ignore[call-overload]`` below marks a call that MUST be an overload error. If
the overloads ever stop rejecting it, the ignore becomes unused and mypy fails
the build.
"""

from __future__ import annotations

from typing import Optional

from nonecap import (
    AsyncNoneCap,
    AsyncSolveHandle,
    NoneCap,
    Solve,
    SolveHandle,
    SolveTimeoutError,
)

nc = NoneCap(api_key="k")
anc = AsyncNoneCap(api_key="k")


def positive_cases() -> None:
    # hcaptcha: rqdata optional.
    nc.solve(type="hcaptcha", sitekey="s", url="u")
    nc.solve(type="hcaptcha", sitekey="s", url="u", rqdata="r")
    # enterprise: rqdata provided.
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
    handle: AsyncSolveHandle = await anc.solves.start(type="hcaptcha", sitekey="s", url="u")
    _id: str = handle.id
    _r: Solve = await handle.result()
    _r2: Solve = await handle.result(timeout=10.0)
    _c: Solve = await handle.cancel()


def negative_cases() -> None:
    # Enterprise without rqdata must not type-check.
    nc.solve(type="hcaptcha_enterprise", sitekey="s", url="u")  # type: ignore[call-overload]
    nc.solves.create(type="hcaptcha_enterprise", sitekey="s", url="u")  # type: ignore[call-overload]
    nc.solves.start(type="hcaptcha_enterprise", sitekey="s", url="u")  # type: ignore[call-overload]
    # Unknown captcha type must not type-check.
    nc.solve(type="recaptcha", sitekey="s", url="u")  # type: ignore[call-overload]


def timeout_error_fields(err: SolveTimeoutError) -> None:
    # SolveTimeoutError exposes the solve it timed out on.
    _sid: Optional[str] = err.solve_id
    _solve: Optional[Solve] = err.solve


async def negative_cases_async() -> None:
    await anc.solve(type="hcaptcha_enterprise", sitekey="s", url="u")  # type: ignore[call-overload]
    await anc.solves.create(type="hcaptcha_enterprise", sitekey="s", url="u")  # type: ignore[call-overload]
    await anc.solves.start(type="hcaptcha_enterprise", sitekey="s", url="u")  # type: ignore[call-overload]
