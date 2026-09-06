"""Turn Alpaca's bar responses into the exact shape the strategy loader accepts.

Two facts drive every test here, both established by inspecting the installed
SDK rather than assumed.

alpaca-py returns FLOATS for prices, and the float appears one layer below the
model: ``common/rest.py`` decodes with ``response.json()``, whose default parser
produces floats, so ``raw_data=True`` alone does not help and the ``Bar`` model
re-coerces Decimals back to float anyway. The only working path is raw mode plus
a decoder that parses numbers as Decimal. This module owns that seam, and the
tests refuse floats outright rather than laundering them through ``str()``.

Alpaca's bar records carry ``n`` (trade count) and ``vw`` (VWAP) that
``load_bar_series`` rejects as unexpected fields, and name the rest with single
letters. The transform is therefore not cosmetic -- a payload that skips it is
refused by the consumer.

That consumer is the point. Every assertion below that matters drives the real
``load_bar_series`` and, where it can, the real strategy. Asserting the shape
this module *intended* to produce would pass for a transform the loader rejects,
which is the failure this project has shipped repeatedly.
"""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.trading.alpaca_data import (
    AlpacaMarketDataError,
    bars_payload_from_alpaca,
    merge_bar_pages,
)
from backend.trading.market_data import load_bar_series
from backend.trading.strategies.trend_following import TrendFollowingStrategy


def raw_bar(t, o, h, l, c, v, **extra):
    """One Alpaca bar as it arrives after Decimal-aware decoding."""
    bar = {"t": t, "o": Decimal(o), "h": Decimal(h), "l": Decimal(l), "c": Decimal(c), "v": v}
    bar.update(extra)
    return bar


ORIGIN = datetime(2026, 1, 1, 5, tzinfo=timezone.utc)


def raw_page(count=60, *, start_day=1, base="100"):
    """Bars on consecutive days, built with real date arithmetic.

    An earlier version formatted the day as a zero-padded integer, which
    produced "2026-01-60" past the month boundary and made every downstream
    assertion fail on the timestamp rather than on what it was testing.
    """
    bars = []
    for i in range(count):
        price = Decimal(base) + Decimal(i)
        stamp = ORIGIN + timedelta(days=start_day - 1 + i)
        bars.append(
            raw_bar(
                stamp.isoformat().replace("+00:00", "Z"),
                str(price), str(price + 1), str(price - 1), str(price),
                1000 + i,
                n=42, vw=Decimal(str(price)),
            )
        )
    return bars


# ---------------------------------------------------------------------------
# The transform, asserted against the real consumer
# ---------------------------------------------------------------------------


def test_the_payload_is_accepted_by_the_real_loader():
    """The assertion that matters: the loader takes it.

    Checking the dict's shape against what this module meant to build would pass
    for a payload load_bar_series refuses.
    """
    payload = bars_payload_from_alpaca("SPY", "stock", raw_page(60))

    series = load_bar_series(payload)

    assert series.symbol == "SPY"
    assert len(series.bars) == 60
    assert series.bars[0].close == Decimal("100")
    assert series.bars[-1].close == Decimal("159")


def test_alpaca_only_fields_are_dropped_because_the_loader_refuses_them():
    """`n` and `vw` are unexpected fields to load_bar_series, not harmless extras."""
    payload = bars_payload_from_alpaca("SPY", "stock", raw_page(60))

    for bar in payload["bars"]:
        assert set(bar) == {"timestamp", "open", "high", "low", "close", "volume"}

    # And prove the claim rather than trusting it: a passed-through record fails.
    leaky = {
        "symbol": "SPY",
        "asset_class": "stock",
        "bars": [dict(b, n=1, vw="100") for b in payload["bars"]],
    }
    with pytest.raises(Exception):
        load_bar_series(leaky)


def test_a_float_price_is_refused_rather_than_rounded_through_str():
    """Laundering a float through str() hides the loss instead of preventing it.

    Decimal(0.3) is 0.29999999999999998889776975374843..., and while str() masks
    that for two-decimal equity prices it is not a guarantee. The money path
    forbids floats, so this seam refuses them at the boundary.
    """
    page = raw_page(60)
    page[10]["c"] = 100.3  # a real float, exactly what an un-overridden decoder yields

    with pytest.raises(AlpacaMarketDataError, match="exact"):
        bars_payload_from_alpaca("SPY", "stock", page)


def test_prices_survive_as_exact_decimals():
    page = raw_page(60)
    page[0]["c"] = Decimal("100.123456789")
    page[0]["h"] = Decimal("100.123456789")

    payload = bars_payload_from_alpaca("SPY", "stock", page)
    series = load_bar_series(payload)

    assert series.bars[0].close == Decimal("100.123456789")


def test_timestamps_normalize_to_utc_instants():
    page = raw_page(3)
    page[0]["t"] = "2026-01-01T05:00:00Z"
    page[1]["t"] = "2026-01-02T00:00:00-05:00"
    page[2]["t"] = datetime(2026, 1, 3, 6, tzinfo=timezone.utc)

    payload = bars_payload_from_alpaca("SPY", "stock", page)
    stamps = [b["timestamp"] for b in payload["bars"]]

    assert all(isinstance(s, str) and s.endswith("Z") for s in stamps)
    series = load_bar_series({**payload, "bars": payload["bars"]})
    assert all(b.timestamp.tzinfo is timezone.utc for b in series.bars)


# ---------------------------------------------------------------------------
# Refusals
# ---------------------------------------------------------------------------


def test_an_empty_response_is_named_rather_than_returned_as_an_empty_series():
    """The lane treats None as 'no data' and continues. An empty payload would
    reach load_bar_series and fail there with a less useful message."""
    with pytest.raises(AlpacaMarketDataError, match="no bars"):
        bars_payload_from_alpaca("SPY", "stock", [])


def test_a_bar_missing_a_field_is_refused_with_the_field_named():
    page = raw_page(3)
    del page[1]["l"]
    with pytest.raises(AlpacaMarketDataError, match="l"):
        bars_payload_from_alpaca("SPY", "stock", page)


def test_an_unsupported_symbol_is_refused_before_any_work():
    with pytest.raises(AlpacaMarketDataError, match="symbol"):
        bars_payload_from_alpaca("TSLA", "stock", raw_page(3))


# ---------------------------------------------------------------------------
# Pagination
# ---------------------------------------------------------------------------


def test_pages_merge_in_time_order_without_duplicates():
    first = raw_page(30, start_day=1, base="100")
    second = raw_page(30, start_day=31, base="130")
    overlap = [first[-1]] + second  # Alpaca can repeat the boundary bar

    merged = merge_bar_pages([first, overlap])

    assert len(merged) == 60
    stamps = [b["t"] for b in merged]
    assert stamps == sorted(stamps)
    assert len(set(stamps)) == len(stamps)

    # Pages handed over out of order must still come back ordered. Feeding them
    # in order proves nothing: insertion order already equals sorted order, so a
    # merge that never sorts passes. The loader refuses a non-increasing series,
    # so this is the assertion that keeps the payload loadable.
    reversed_pages = merge_bar_pages([second, first])
    assert [b["t"] for b in reversed_pages] == sorted(b["t"] for b in reversed_pages)
    assert load_bar_series(bars_payload_from_alpaca("SPY", "stock", reversed_pages))


def test_merged_pages_still_satisfy_the_loader_and_drive_the_strategy():
    """End to end: two Alpaca pages become a series the real strategy evaluates."""
    pages = [raw_page(30, start_day=1, base="100"), raw_page(30, start_day=31, base="130")]
    payload = bars_payload_from_alpaca("SPY", "stock", merge_bar_pages(pages))
    series = load_bar_series(payload)

    strategy = TrendFollowingStrategy()
    signal = strategy.propose(
        series,
        now=series.latest.timestamp,
        notional_cap=Decimal("1000"),
        position_quantity=Decimal("0"),
    )

    # 60 bars clears the 51-bar minimum, so the strategy reaches a real verdict
    # rather than refusing for want of history.
    assert signal.reason != "insufficient_history"


# ---------------------------------------------------------------------------
# The transport seam.
#
# Everything above tests the pure transform. Nothing above ever ran the client
# that fetches the bars, which is how ``_one_request`` shipped an override that
# silently disabled the SDK's rate-limit retry. These tests drive the real
# ``_request`` loop -- the actual consumer of the override -- with a real
# ``requests.Response``, so ``raise_for_status`` behaves exactly as in
# production. A fake response object with a hand-written ``raise_for_status``
# would pass against the broken code, which is the whole failure mode.
# ---------------------------------------------------------------------------

import json as _json

import requests
from alpaca.common.exceptions import APIError

from backend.trading.alpaca_data import decimal_stock_client

BARS_BODY = _json.dumps(
    {
        "bars": {
            "SPY": [
                {
                    "t": "2026-01-01T05:00:00Z",
                    "o": 100.5,
                    "h": 101.5,
                    "l": 99.5,
                    "c": 101.25,
                    "v": 1000,
                    "n": 5,
                    "vw": 100.9,
                }
            ]
        }
    }
)


def canned(status, body):
    """A real ``requests.Response``, not a stand-in.

    ``raise_for_status`` is the branch under test; substituting our own would
    test the substitute.
    """
    response = requests.Response()
    response.status_code = status
    response._content = body.encode()
    response.url = "https://data.alpaca.markets/v2/stocks/bars"
    response.encoding = "utf-8"
    return response


class RecordingSession:
    """Hands back queued responses and records every attempt."""

    def __init__(self, *responses):
        self._responses = list(responses)
        self.calls = []

    def request(self, method, url, **opts):
        self.calls.append((method, url))
        if not self._responses:
            raise AssertionError("client made more attempts than the test queued")
        return self._responses.pop(0)


@pytest.fixture
def instant_retries(monkeypatch):
    """The SDK sleeps ``_retry_wait`` seconds between attempts; the test must not."""
    import alpaca.common.rest as rest

    monkeypatch.setattr(rest.time, "sleep", lambda _seconds: None)


@pytest.fixture
def client():
    stock_client = decimal_stock_client(api_key="not-a-real-key", secret_key="not-a-real-secret")
    assert stock_client._retry_codes == [429, 504], "the retryable set moved; update these tests"
    return stock_client


@pytest.mark.parametrize("retryable_status", [429, 504])
def test_retryable_status_is_retried_and_the_next_response_is_used(
    client, instant_retries, retryable_status
):
    """A rate limit must cost one extra attempt, not the whole pull.

    Pulling years of daily bars for several symbols is paginated, so a 429
    mid-pull is the expected case rather than the exotic one. Surfacing it
    aborts the run.
    """
    client._session = RecordingSession(
        canned(retryable_status, '{"code": 42900000, "message": "rate limit"}'),
        canned(200, BARS_BODY),
    )

    payload = client._request("GET", "/stocks/bars", {"symbols": "SPY"})

    assert len(client._session.calls) == 2, f"{retryable_status} was not retried"
    bar = payload["bars"]["SPY"][0]
    assert type(bar["c"]) is Decimal, "the retried response must still decode exactly"
    assert bar["c"] == Decimal("101.25")


def test_retries_are_bounded_and_end_as_an_api_error_carrying_the_body(client, instant_retries):
    """When the limit never clears, the caller gets Alpaca's message, not a bare HTTPError."""
    body = '{"code": 42900000, "message": "rate limit exceeded"}'
    client._session = RecordingSession(*[canned(429, body) for _ in range(4)])

    with pytest.raises(APIError) as caught:
        client._request("GET", "/stocks/bars", {"symbols": "SPY"})

    # _retry defaults to 3: one initial attempt plus three retries, then stop.
    assert len(client._session.calls) == 4
    assert caught.value.message == "rate limit exceeded"


def test_non_retryable_error_keeps_alpacas_message_and_status(client, instant_retries):
    """A bad request must arrive as APIError with the body intact.

    ``APIError.message`` and ``.code`` parse the response body, so an exception
    that drops it cannot answer *why* the request failed -- exactly what a bare
    ``raise_for_status`` produces.
    """
    client._session = RecordingSession(
        canned(422, '{"code": 42210000, "message": "invalid symbol: NOPE"}')
    )

    with pytest.raises(APIError) as caught:
        client._request("GET", "/stocks/bars", {"symbols": "NOPE"})

    assert len(client._session.calls) == 1, "a 422 is not retryable"
    assert caught.value.message == "invalid symbol: NOPE"
    assert caught.value.code == 42210000
    assert caught.value.status_code == 422


def test_empty_body_decodes_to_none_rather_than_raising(client, instant_retries):
    """The SDK treats an empty body as 'no payload'; the override must agree."""
    client._session = RecordingSession(canned(200, ""))

    assert client._request("GET", "/stocks/bars", {"symbols": "SPY"}) is None
