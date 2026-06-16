"""Public read-only weather exit quote adapters for paper risk scans.

These helpers fetch or normalize executable held-side quote/depth context for
open weather paper positions. They never place orders, sign requests, or touch
private exchange/account endpoints.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional
import logging

import httpx

from backend.data.kalshi_client import BASE_URL as KALSHI_BASE_URL
from backend.data.kalshi_markets import _parse_kalshi_orderbook_fp
from backend.data.polymarket_client import (
    CLOB_API,
    GAMMA_API,
    PolymarketBookTop,
    map_outcome_tokens,
    parse_clob_book_top,
)

logger = logging.getLogger("trading_bot")


@dataclass(frozen=True)
class WeatherExitQuote:
    """Executable held-side quote/depth context for a weather paper trade."""

    platform: str
    market_ticker: str
    held_side: str
    held_side_bid: Optional[float]
    held_side_ask: Optional[float]
    top_bid_size: Optional[float]
    top_ask_size: Optional[float]
    source_status: str
    evidence: dict[str, Any] = field(default_factory=dict)


class PublicWeatherExitQuoteProvider:
    """Fetch current public weather exit quotes for open paper positions.

    This provider is intentionally public/read-only:
    - Kalshi: unsigned `/markets/{ticker}/orderbook` market-data endpoint.
    - Polymarket: public Gamma market metadata + token-level CLOB book.
    """

    def __init__(self, *, timeout: float = 10.0, client: httpx.Client | None = None):
        self.timeout = timeout
        self._client = client

    def __call__(self, trade: Any) -> WeatherExitQuote | None:
        platform = str(getattr(trade, "platform", "") or "").strip().lower()
        ticker = str(getattr(trade, "market_ticker", "") or "").strip()
        direction = str(getattr(trade, "direction", "yes") or "yes")
        if not ticker:
            return None

        try:
            if platform == "kalshi" or ticker.startswith("KX"):
                return self.fetch_kalshi_exit_quote(ticker, direction)
            if platform == "polymarket":
                return self.fetch_polymarket_exit_quote(ticker, direction)
        except Exception as exc:  # pragma: no cover - network defensive path
            logger.debug("weather exit quote fetch failed for %s/%s: %s", platform, ticker, exc)
            return WeatherExitQuote(
                platform=platform or "unknown",
                market_ticker=ticker,
                held_side=_held_side(direction),
                held_side_bid=None,
                held_side_ask=None,
                top_bid_size=None,
                top_ask_size=None,
                source_status="live_weather_exit_quote_fetch_error",
                evidence={"quote_error": str(exc)},
            )
        return None

    def fetch_kalshi_exit_quote(self, ticker: str, direction: str) -> WeatherExitQuote:
        payload = self._get_json(f"{KALSHI_BASE_URL}/markets/{ticker}/orderbook")
        orderbook = payload.get("orderbook", payload) if isinstance(payload, dict) else {}
        return quote_from_kalshi_orderbook_fp(
            market_ticker=ticker,
            direction=direction,
            orderbook_fp=orderbook.get("orderbook_fp") if isinstance(orderbook, dict) else None,
        )

    def fetch_polymarket_exit_quote(self, market_id: str, direction: str) -> WeatherExitQuote | None:
        market = self._get_json(f"{GAMMA_API}/markets/{market_id}")
        if not isinstance(market, dict):
            return None

        held_side = _held_side(direction)
        token_map = map_outcome_tokens(market.get("outcomes"), market.get("clobTokenIds"))
        outcome_token = token_map.get(held_side)
        if outcome_token is None:
            return WeatherExitQuote(
                platform="polymarket",
                market_ticker=market_id,
                held_side=held_side,
                held_side_bid=None,
                held_side_ask=None,
                top_bid_size=None,
                top_ask_size=None,
                source_status="missing_polymarket_exit_quote_token",
                evidence={
                    "quote_source": "polymarket_gamma_clob",
                    "available_outcomes": sorted(token_map.keys()),
                },
            )

        try:
            book_payload = self._get_json(
                f"{CLOB_API}/book",
                params={"token_id": outcome_token.token_id},
            )
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 404 and _market_closed(market):
                return WeatherExitQuote(
                    platform="polymarket",
                    market_ticker=market_id,
                    held_side=held_side,
                    held_side_bid=None,
                    held_side_ask=None,
                    top_bid_size=None,
                    top_ask_size=None,
                    source_status="closed_market_or_stale_token",
                    evidence={
                        "quote_source": "polymarket_gamma_clob",
                        "gamma_closed": True,
                        "token_id": outcome_token.token_id,
                        "outcome": outcome_token.outcome,
                        "quote_error": f"CLOB book 404 for held {held_side.upper()} token",
                    },
                )
            raise
        book_top = parse_clob_book_top(
            outcome_token.token_id,
            book_payload if isinstance(book_payload, dict) else {},
        )
        return quote_from_polymarket_book_top(
            market_ticker=market_id,
            direction=direction,
            outcome=outcome_token.outcome,
            token_id=outcome_token.token_id,
            book_top=book_top,
        )

    def _get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        if self._client is not None:
            response = self._client.get(url, params=params)
            response.raise_for_status()
            return response.json()

        with httpx.Client(timeout=self.timeout) as client:
            response = client.get(url, params=params)
            response.raise_for_status()
            return response.json()


def _held_side(direction: str | None) -> str:
    text = str(direction or "yes").strip().lower()
    if text in {"no", "down", "under", "below", "short"}:
        return "no"
    return "yes"


def _market_closed(market: dict[str, Any]) -> bool:
    value = market.get("closed")
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return bool(value)
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes", "closed"}
    return False


def _round_prob(value: float | None) -> float | None:
    if value is None:
        return None
    return round(max(0.0, min(1.0, float(value))), 6)


def _quote_status(held_side_bid: float | None) -> str:
    return "live_weather_exit_quote" if held_side_bid is not None else "missing_executable_exit_bid"


def quote_from_kalshi_orderbook_fp(
    *,
    market_ticker: str,
    direction: str,
    orderbook_fp: dict | None,
) -> WeatherExitQuote:
    """Normalize a Kalshi orderbook_fp into the held side's executable quote.

    For a held YES position, exit at the best Yes bid. For a held NO position,
    exit at the best No bid, derived from the same no-side ladder used by the
    Yes ask (`no_bid = 1 - yes_ask`).
    """
    book_top = _parse_kalshi_orderbook_fp(orderbook_fp)
    held_side = _held_side(direction)

    if held_side == "no":
        held_side_bid = _round_prob(1.0 - book_top.best_ask) if book_top.best_ask is not None else None
        held_side_ask = _round_prob(1.0 - book_top.best_bid) if book_top.best_bid is not None else None
        top_bid_size = book_top.top_ask_size
        top_ask_size = book_top.top_bid_size
    else:
        held_side_bid = book_top.best_bid
        held_side_ask = book_top.best_ask
        top_bid_size = book_top.top_bid_size
        top_ask_size = book_top.top_ask_size

    return WeatherExitQuote(
        platform="kalshi",
        market_ticker=market_ticker,
        held_side=held_side,
        held_side_bid=held_side_bid,
        held_side_ask=held_side_ask,
        top_bid_size=top_bid_size,
        top_ask_size=top_ask_size,
        source_status=_quote_status(held_side_bid),
        evidence={
            "quote_source": "kalshi_public_orderbook",
            "yes_best_bid": book_top.best_bid,
            "yes_best_ask": book_top.best_ask,
            "yes_top_bid_size": book_top.top_bid_size,
            "yes_top_ask_size": book_top.top_ask_size,
        },
    )


def quote_from_polymarket_book_top(
    *,
    market_ticker: str,
    direction: str,
    outcome: str,
    token_id: str,
    book_top: PolymarketBookTop,
) -> WeatherExitQuote:
    """Normalize a Polymarket held outcome token book into an exit quote.

    For Polymarket binary markets, a NO paper position must use the live NO
    token book directly; do not infer NO exit liquidity from stale `1 - YES`
    math.
    """
    held_side = _held_side(direction)
    return WeatherExitQuote(
        platform="polymarket",
        market_ticker=market_ticker,
        held_side=held_side,
        held_side_bid=book_top.best_bid,
        held_side_ask=book_top.best_ask,
        top_bid_size=book_top.best_bid_size,
        top_ask_size=book_top.best_ask_size,
        source_status=_quote_status(book_top.best_bid),
        evidence={
            "quote_source": "polymarket_gamma_clob",
            "token_id": token_id,
            "outcome": outcome,
            "execution_spread": book_top.spread,
        },
    )
