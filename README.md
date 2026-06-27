<h1 align="center">nonecap</h1>

<p align="center">
  <a href="https://github.com/nonecap/nonecap-py/actions/workflows/ci.yml"><img src="https://github.com/nonecap/nonecap-py/actions/workflows/ci.yml/badge.svg" alt="CI"></a>
  <a href="https://pypi.org/project/nonecap/"><img src="https://img.shields.io/pypi/v/nonecap.svg" alt="PyPI"></a>
  <a href="https://pypi.org/project/nonecap/"><img src="https://img.shields.io/pypi/pyversions/nonecap.svg" alt="Python versions"></a>
  <a href="LICENSE"><img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT"></a>
</p>

<p align="center">Official Python client for the <a href="https://nonecap.com">NoneCap</a> hCaptcha solving API.</p>

Submit a captcha, get back a token. The client handles the polling, the timeouts, and the error cases so you don't write the request loop yourself. Sync and async, fully typed.

## Install

```sh
pip install nonecap
```

Python 3.9+. The only dependency is [httpx](https://www.python-httpx.org/).

## Quick start

Grab an API key from [dashboard.nonecap.com](https://dashboard.nonecap.com), then:

```python
from nonecap import NoneCap

nc = NoneCap(api_key="nc_live_...")

solve = nc.solve(
    type="hcaptcha",
    sitekey="10000000-ffff-ffff-ffff-000000000001",
    url="https://example.com/login",
)

print(solve.token)  # the hCaptcha token, ready to submit
```

`solve()` submits the captcha and waits until it's done, using the API's long-poll so you aren't hammering it with requests. It returns the solved solve, or raises if the solve fails or your timeout runs out.

## Async

Same surface, `await`ed. Use it as an async context manager so the connection pool gets cleaned up:

```python
import asyncio
from nonecap import AsyncNoneCap

async def main() -> None:
    async with AsyncNoneCap(api_key="nc_live_...") as nc:
        solve = await nc.solve(type="hcaptcha", sitekey="...", url="https://example.com")
        print(solve.token)

asyncio.run(main())
```

## Handling failures

Every error this library raises extends `NoneCapError`, so you can catch the whole family or pick out the one you care about.

```python
from nonecap import (
    NoneCap,
    SolveFailedError,
    InsufficientCreditsError,
    RateLimitError,
)

try:
    solve = nc.solve(type="hcaptcha", sitekey=sitekey, url=url)
except SolveFailedError as err:
    print("Could not solve it:", err.solve.error.code if err.solve.error else "?")
except InsufficientCreditsError:
    print("Out of credits. Top up at dashboard.nonecap.com")
except RateLimitError:
    print("Too many solves in flight, back off and retry")
```

The subclasses are `AuthenticationError` (401), `PermissionDeniedError` (403), `InsufficientCreditsError` (402), `ValidationError` (422/400, with a `param` naming the bad field), `NotFoundError` (404), `ConflictError` (409), `RateLimitError` (429), `APIError` (5xx), `APIConnectionError` and `APITimeoutError` (the request never landed), and `SolveTimeoutError` (your `solve()` budget ran out). `SolveFailedError` carries the full `solve` so you can read the underlying error code and the timings.

## Enterprise captchas

For `hcaptcha_enterprise`, `rqdata` is required. The `@overload` signatures enforce that in mypy and pyright, so leaving it out fails your type check, and a runtime check backs it up before any network call:

```python
solve = nc.solve(
    type="hcaptcha_enterprise",
    sitekey=sitekey,
    url=url,
    rqdata="...",  # required for enterprise
)
```

## Proxies

Pass a proxy as a dict or a URL string. The solve runs through it, and the bytes are metered back on the solve.

```python
nc.solve(
    type="hcaptcha",
    sitekey=sitekey,
    url=url,
    proxy={"scheme": "http", "host": "1.2.3.4", "port": 8080, "username": "u", "password": "p"},
    # or: proxy="http://u:p@1.2.3.4:8080"
    # scheme can be http, https, socks5, socks5h, or socks4 (default http)
    # e.g. proxy="socks5://u:p@1.2.3.4:1080"
)
```

## Lower-level API

`solve()` is the convenient path. When you want control over submission and polling, the resource methods map one to one to the REST API:

```python
# Submit without waiting: returns immediately with a pending solve
pending = nc.solves.create(type="hcaptcha", sitekey=sitekey, url=url)

# Submit and hold the connection up to 30s for it to finish
maybe_done = nc.solves.create(type="hcaptcha", sitekey=sitekey, url=url, wait=30)

# Poll one solve, long-polling up to 30s
solve = nc.solves.retrieve(pending.id, wait=30)

# Cancel a pending or in-flight solve
nc.solves.cancel(pending.id)

# List a page of solves
page = nc.solves.list(limit=50, status="solved")

# Or iterate every solve, newest first
for s in nc.solves.list_all():
    print(s.id, s.status)

# Your account and credit balance
me = nc.me()
print(me.credits_balance)
```

On `AsyncNoneCap` the same methods are coroutines, and `list_all()` is an async iterator (`async for s in nc.solves.list_all()`).

## Configuration

```python
NoneCap(
    api_key="nc_live_...",              # required
    base_url="https://api.nonecap.com", # override if you need to
    timeout=100.0,                      # per HTTP request, seconds
    http_client=my_httpx_client,        # inject your own httpx.Client
)
```

`solve()` takes its own `timeout` (seconds, default 180) for the overall wait.

## Typing

The package ships a `py.typed` marker and full inline annotations. Solves come back as frozen dataclasses with the exact field names the API uses (`solve.token`, `solve.credits_charged`, `solve.queue_ms`), so what you read in the [API reference](https://nonecap.com/api-reference) is what you get in code.

## License

MIT, see [LICENSE](LICENSE).
