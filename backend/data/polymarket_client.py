"""Read-only Polymarket public API client and normalized parsers.

This module intentionally contains no private-key auth, signing, or order-placement
code. It is safe to use in simulation/research mode.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Optional

import httpx

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"
DATA_API = "https://data-api.polymarket.com"

logger = logging.getLogger("trading_bot")


@dataclass(frozen=True)
class PolymarketOutcomeToken:
    """Mapping between a Gamma outcome label and its CLOB token id."""

    outcome: str
    token_id: str
    index: int


@dataclass(frozen=True)
class PolymarketBookTop:
    """Normalized token-level top-of-book data from the Polymarket CLOB."""

    token_id: str
    best_bid: Optional[float] = None
    best_ask: Optional[float] = None
    best_bid_size: Optional[float] = None
    best_ask_size: Optional[float] = None

    @property
    def spread(self) -> Optional[float]:
        if self.best_bid is None or self.best_ask is None:
            return None
        return round(self.best_ask - self.best_bid, 6)


def parse_gamma_list(value: Any) -> list:
    """Parse Gamma fields that may arrive as JSON strings or native lists."""
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except (TypeError, json.JSONDecodeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def map_outcome_tokens(
    outcomes_value: Any,
    token_ids_value: Any,
) -> dict[str, PolymarketOutcomeToken]:
    """Map normalized outcome keys to their CLOB token ids.

    Mismatched Gamma field lengths are tolerated: outcomes without a matching
    token are skipped so downstream gates can treat missing books as
    non-actionable rather than crashing.
    """
    outcomes = parse_gamma_list(outcomes_value)
    token_ids = parse_gamma_list(token_ids_value)
    mapping: dict[str, PolymarketOutcomeToken] = {}

    for index, outcome in enumerate(outcomes):
        if index >= len(token_ids):
            continue
        outcome_text = str(outcome)
        raw_token_id = token_ids[index]
        if raw_token_id is None:
            continue
        token_id = str(raw_token_id).strip()
        key = outcome_text.strip().lower()
        if key and token_id:
            mapping[key] = PolymarketOutcomeToken(
                outcome=outcome_text,
                token_id=token_id,
                index=index,
            )

    return mapping


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_clob_book_top(token_id: str, book: dict) -> PolymarketBookTop:
    """Parse highest bid, lowest ask, and corresponding sizes from CLOB rows."""
    bid_rows: list[tuple[float, Optional[float]]] = []
    ask_rows: list[tuple[float, Optional[float]]] = []

    for row in book.get("bids", []) or []:
        price = _float_or_none(row.get("price") if isinstance(row, dict) else None)
        size = _float_or_none(row.get("size") if isinstance(row, dict) else None)
        if price is not None:
            bid_rows.append((price, size))

    for row in book.get("asks", []) or []:
        price = _float_or_none(row.get("price") if isinstance(row, dict) else None)
        size = _float_or_none(row.get("size") if isinstance(row, dict) else None)
        if price is not None:
            ask_rows.append((price, size))

    best_bid = max(bid_rows, key=lambda item: item[0]) if bid_rows else None
    best_ask = min(ask_rows, key=lambda item: item[0]) if ask_rows else None

    return PolymarketBookTop(
        token_id=token_id,
        best_bid=best_bid[0] if best_bid else None,
        best_bid_size=best_bid[1] if best_bid else None,
        best_ask=best_ask[0] if best_ask else None,
        best_ask_size=best_ask[1] if best_ask else None,
    )


class PolymarketClient:
    """Read-only public Polymarket API client.

    The client intentionally exposes only public Gamma/CLOB reads. It contains
    no credential handling, signing, order placement, or copy-trading behavior.
    """

    def __init__(
        self,
        client: Optional[httpx.AsyncClient] = None,
        timeout: float = 15.0,
    ):
        self._client = client
        self._timeout = timeout
        self._owns_client = False

    async def __aenter__(self) -> "PolymarketClient":
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()

    async def fetch_events(self, **params: Any) -> list[dict]:
        """Fetch Gamma events with best-effort empty-list failure behavior."""
        assert self._client is not None
        try:
            response = await self._client.get(f"{GAMMA_API}/events", params=params)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else []
        except Exception as exc:
            logger.debug("Polymarket events fetch failed: %s", exc)
            return []



    async def fetch_markets(self, **params: Any) -> list[dict]:
        """Fetch Gamma markets with best-effort empty-list failure behavior."""
        assert self._client is not None
        try:
            response = await self._client.get(f"{GAMMA_API}/markets", params=params)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else []
        except Exception as exc:
            logger.debug("Polymarket markets fetch failed: %s", exc)
            return []

    async def fetch_market(self, market_id: str) -> Optional[dict]:
        """Fetch one Gamma market by id with best-effort None on failure."""
        assert self._client is not None
        try:
            response = await self._client.get(f"{GAMMA_API}/markets/{market_id}")
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, dict) else None
        except Exception as exc:
            logger.debug("Polymarket market fetch failed for %s: %s", market_id, exc)
            return None

    async def fetch_book_top(self, token_id: Optional[str]) -> Optional[PolymarketBookTop]:
        """Fetch and parse token-level CLOB top-of-book data.

        Missing/failed books stay explicit as None so callers can add
        no-trade blockers instead of inventing an executable price.
        """
        if not token_id:
            return None
        assert self._client is not None
        try:
            response = await self._client.get(
                f"{CLOB_API}/book",
                params={"token_id": token_id},
            )
            response.raise_for_status()
            payload = response.json()
            return parse_clob_book_top(token_id, payload if isinstance(payload, dict) else {})
        except Exception as exc:
            logger.debug("Polymarket CLOB book fetch failed for %s: %s", token_id, exc)
            return None

    async def fetch_price(
        self,
        token_id: Optional[str],
        side: Optional[str] = None,
    ) -> Optional[float]:
        """Fetch token-level CLOB price quote.

        Side is optional and forwarded to CLOB (`buy`/`sell`) when provided.
        """
        if not token_id:
            return None
        assert self._client is not None
        params: dict[str, Any] = {"token_id": token_id}
        if side:
            params["side"] = side
        try:
            response = await self._client.get(f"{CLOB_API}/price", params=params)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return _float_or_none(payload.get("price"))
            return None
        except Exception as exc:
            logger.debug("Polymarket CLOB price fetch failed for %s: %s", token_id, exc)
            return None

    async def fetch_midpoint(self, token_id: Optional[str]) -> Optional[float]:
        """Fetch token-level midpoint from CLOB."""
        if not token_id:
            return None
        assert self._client is not None
        try:
            response = await self._client.get(
                f"{CLOB_API}/midpoint",
                params={"token_id": token_id},
            )
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                return _float_or_none(payload.get("mid"))
            return None
        except Exception as exc:
            logger.debug("Polymarket CLOB midpoint fetch failed for %s: %s", token_id, exc)
            return None

    async def fetch_prices_history(self, **params: Any) -> list[dict]:
        """Fetch CLOB price history (`/prices-history`)."""
        assert self._client is not None
        try:
            response = await self._client.get(f"{CLOB_API}/prices-history", params=params)
            response.raise_for_status()
            payload = response.json()
            if isinstance(payload, dict):
                points = payload.get("history")
                return points if isinstance(points, list) else []
            return payload if isinstance(payload, list) else []
        except Exception as exc:
            logger.debug("Polymarket CLOB prices-history fetch failed: %s", exc)
            return []

    async def fetch_trades(self, **params: Any) -> list[dict]:
        """Fetch Data API trades (`/trades`) with best-effort empty-list behavior."""
        assert self._client is not None
        try:
            response = await self._client.get(f"{DATA_API}/trades", params=params)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else []
        except Exception as exc:
            logger.debug("Polymarket Data API trades fetch failed: %s", exc)
            return []

    async def fetch_positions(self, **params: Any) -> list[dict]:
        """Fetch Data API positions (`/positions`) with best-effort empty-list behavior."""
        assert self._client is not None
        try:
            response = await self._client.get(f"{DATA_API}/positions", params=params)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else []
        except Exception as exc:
            logger.debug("Polymarket Data API positions fetch failed: %s", exc)
            return []

