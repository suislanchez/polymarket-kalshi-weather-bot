from typing import cast

import httpx

from backend.core.position_risk import calculate_exit_pnl
from backend.core.weather_exit_quotes import (
    PublicWeatherExitQuoteProvider,
    WeatherExitQuote,
    quote_from_kalshi_orderbook_fp,
    quote_from_polymarket_book_top,
)
from backend.data.polymarket_client import PolymarketBookTop


def test_kalshi_exit_quote_for_held_no_uses_no_side_bid_and_depth():
    quote = quote_from_kalshi_orderbook_fp(
        market_ticker="KXLOWTDEN-26JUN04-T51",
        direction="no",
        orderbook_fp={"yes": [[42, 10]], "no": [[55, 7]]},
    )

    assert isinstance(quote, WeatherExitQuote)
    assert quote.held_side == "no"
    assert quote.held_side_bid == 0.55
    assert quote.held_side_ask == 0.58
    assert quote.top_bid_size == 7
    assert quote.top_ask_size == 10
    assert quote.source_status == "live_weather_exit_quote"


def test_polymarket_exit_quote_for_held_no_uses_no_token_book_directly():
    quote = quote_from_polymarket_book_top(
        market_ticker="2416225",
        direction="no",
        outcome="No",
        token_id="no-token",
        book_top=PolymarketBookTop(
            token_id="no-token",
            best_bid=0.61,
            best_ask=0.64,
            best_bid_size=42.5,
            best_ask_size=17.0,
        ),
    )

    assert quote.held_side == "no"
    assert quote.held_side_bid == 0.61
    assert quote.held_side_ask == 0.64
    assert quote.top_bid_size == 42.5
    assert quote.top_ask_size == 17.0
    assert quote.evidence["token_id"] == "no-token"
    assert calculate_exit_pnl(entry_price=0.70, exit_price=quote.held_side_bid, size=75.0) == -9.64


class _FakeResponse:
    def __init__(self, payload=None, *, status_code=200, url="https://example.test"):
        self._payload = payload
        self.status_code = status_code
        self.request = httpx.Request("GET", url)
        self.response = httpx.Response(status_code, request=self.request)

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError(
                f"HTTP {self.status_code}",
                request=self.request,
                response=self.response,
            )

    def json(self):
        return self._payload


class _FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def get(self, url, params=None):
        self.calls.append((url, params))
        if not self.responses:
            raise AssertionError("unexpected extra HTTP call")
        return self.responses.pop(0)


def test_polymarket_closed_market_404_is_typed_as_stale_token_not_generic_fetch_error():
    client = _FakeClient([
        _FakeResponse(
            {
                "closed": True,
                "outcomes": '["Yes", "No"]',
                "clobTokenIds": '["yes-token", "no-token"]',
            },
            url="https://gamma-api.polymarket.com/markets/2425070",
        ),
        _FakeResponse(status_code=404, url="https://clob.polymarket.com/book?token_id=yes-token"),
    ])
    provider = PublicWeatherExitQuoteProvider(client=cast(httpx.Client, client))

    quote = provider.fetch_polymarket_exit_quote("2425070", "yes")

    assert quote is not None
    assert quote.source_status == "closed_market_or_stale_token"
    assert quote.held_side == "yes"
    assert quote.held_side_bid is None
    assert quote.evidence["quote_source"] == "polymarket_gamma_clob"
    assert quote.evidence["gamma_closed"] is True
    assert quote.evidence["token_id"] == "yes-token"
    assert quote.evidence["quote_error"] == "CLOB book 404 for held YES token"
