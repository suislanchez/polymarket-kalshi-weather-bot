"""A swallowed 429 is a silently incomplete slate, not an error.

fetch_kalshi_weather_markets catches every exception per series and logs a
warning, so a rate-limited request does not fail the run -- it removes a series
from the slate and carries on. Concurrency makes that far more likely to fire:
raising city concurrency once produced ~20 rate-limited series and a slate
missing a fifth of its markets, while the run still reported success.

So the retry lives in the client, where it protects every caller, and the
tests assert on the number of attempts rather than on elapsed time.
"""

import asyncio

import pytest

from backend.data import kalshi_client as kalshi_client_module
from backend.data.kalshi_client import KalshiClient


class FakeResponse:
    def __init__(self, status_code: int, payload=None):
        self.status_code = status_code
        self._payload = payload if payload is not None else {"markets": []}
        self.headers = {}

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=self  # type: ignore[arg-type]
            )

    def json(self):
        return self._payload


class FakeClient:
    """Returns queued responses and counts attempts."""

    def __init__(self, responses):
        self.responses = list(responses)
        self.attempts = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def get(self, url, headers=None, params=None):
        self.attempts += 1
        return self.responses.pop(0) if self.responses else FakeResponse(200)


@pytest.fixture
def instant_backoff(monkeypatch):
    """Skip the real delay.

    kalshi_client.asyncio is the asyncio module itself, so patching sleep on it
    patches it globally -- a replacement that called asyncio.sleep would call
    itself. Capture the real one first.
    """
    real_sleep = asyncio.sleep

    async def no_delay(_seconds):
        await real_sleep(0)

    monkeypatch.setattr(kalshi_client_module.asyncio, "sleep", no_delay)


def install(monkeypatch, responses) -> FakeClient:
    fake = FakeClient(responses)
    monkeypatch.setattr(
        kalshi_client_module.httpx, "AsyncClient", lambda *a, **k: fake
    )
    return fake


def test_a_rate_limited_request_is_retried_and_then_succeeds(monkeypatch, instant_backoff):
    fake = install(
        monkeypatch,
        [FakeResponse(429), FakeResponse(200, {"markets": [{"ticker": "T"}]})],
    )

    result = asyncio.run(KalshiClient().get("/markets"))

    assert fake.attempts == 2, "the 429 was not retried"
    assert result == {"markets": [{"ticker": "T"}]}


def test_retries_are_bounded_and_the_error_still_surfaces(monkeypatch, instant_backoff):
    """Retrying forever would hang the dashboard instead of degrading it."""
    import httpx

    fake = install(monkeypatch, [FakeResponse(429) for _ in range(10)])

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(KalshiClient().get("/markets"))

    assert fake.attempts == kalshi_client_module.RATE_LIMIT_MAX_ATTEMPTS
    assert fake.attempts < 10, "unbounded retry"


def test_a_non_rate_limit_error_is_not_retried(monkeypatch, instant_backoff):
    """A 404 will not become a 200 by asking again."""
    import httpx

    fake = install(monkeypatch, [FakeResponse(404), FakeResponse(200)])

    with pytest.raises(httpx.HTTPStatusError):
        asyncio.run(KalshiClient().get("/markets"))

    assert fake.attempts == 1


def test_a_successful_request_makes_exactly_one_attempt(monkeypatch, instant_backoff):
    fake = install(monkeypatch, [FakeResponse(200, {"markets": []})])

    asyncio.run(KalshiClient().get("/markets"))

    assert fake.attempts == 1
