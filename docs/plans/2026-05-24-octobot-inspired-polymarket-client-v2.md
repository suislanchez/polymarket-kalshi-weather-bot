# OctoBot-Inspired Clean-Room PolymarketClient v2 Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task if context is tight. Preserve simulation-only/no-forced-trade behavior.

**Goal:** Add a reusable, read-only Polymarket client layer inspired by OctoBot’s adapter surface, then use it as the foundation for future paper-only copy-trading research and cleaner BTC/weather/RT market discovery.

**Architecture:** Create `backend/data/polymarket_client.py` as a side-effect-free public client with normalized dataclasses and parsing helpers. Existing vertical modules (`btc_markets.py`, `weather_markets.py`, future entertainment/copy-trading modules) should consume this shared client instead of each duplicating Gamma/CLOB parsing. Do not add private-key auth, order placement, or live execution in this phase.

**Tech Stack:** Python 3.12, `httpx.AsyncClient`, dataclasses, pytest-style tests under `tests/`, existing FastAPI/backend package layout.

**Safety posture:** Read-only public APIs only. No credentials. No private signing. No live orders. Failed parses/books must return explicit non-actionable data, not hidden exceptions. Any future copy-trading watcher is paper-only and feeds the review queue rather than execution.

---

## Current codebase observations

- Existing Polymarket logic is duplicated in:
  - `backend/data/btc_markets.py`
  - `backend/data/weather_markets.py`
  - `backend/core/settlement.py`
- Existing tests already cover:
  - `tests/test_btc_market_parsing.py`
  - `tests/test_polymarket_weather_books.py`
- Useful existing helpers to consolidate:
  - JSON-string/list parsing for Gamma fields.
  - Outcome → `clobTokenIds` mapping.
  - CLOB best bid/ask/top ask size parsing.
  - Settlement source detection remains vertical-specific for now.
- Repo currently has many uncommitted Hermes changes; do **not** overwrite or commit them casually.

---

## Phase 1 — shared read-only Polymarket client foundation

### Task 1: Add shared normalized Polymarket dataclasses and pure parsers

**Objective:** Create the reusable public parser surface without network calls.

**Files:**
- Create: `backend/data/polymarket_client.py`
- Create: `tests/test_polymarket_client.py`

**Step 1: Write failing parser tests**

Add tests for:

```python
from backend.data.polymarket_client import (
    parse_gamma_list,
    map_outcome_tokens,
    parse_clob_book_top,
)


def test_parse_gamma_list_accepts_json_strings_and_lists():
    assert parse_gamma_list('["Yes", "No"]') == ["Yes", "No"]
    assert parse_gamma_list(["Up", "Down"]) == ["Up", "Down"]
    assert parse_gamma_list(None) == []
    assert parse_gamma_list("not-json") == []


def test_map_outcome_tokens_preserves_outcome_names_and_token_ids():
    mapping = map_outcome_tokens('["Yes", "No"]', '["yes-token", "no-token"]')
    assert mapping["yes"].token_id == "yes-token"
    assert mapping["no"].token_id == "no-token"
    assert mapping["yes"].outcome == "Yes"


def test_map_outcome_tokens_handles_mismatched_lengths_without_crashing():
    mapping = map_outcome_tokens('["Yes", "No"]', '["yes-token"]')
    assert mapping["yes"].token_id == "yes-token"
    assert "no" not in mapping


def test_parse_clob_book_top_uses_highest_bid_lowest_ask_and_sizes():
    top = parse_clob_book_top(
        "yes-token",
        {
            "bids": [
                {"price": "0.41", "size": "15"},
                {"price": "0.43", "size": "7"},
            ],
            "asks": [
                {"price": "0.48", "size": "11.5"},
                {"price": "0.46", "size": "8.25"},
            ],
        },
    )
    assert top.token_id == "yes-token"
    assert top.best_bid == 0.43
    assert top.best_bid_size == 7.0
    assert top.best_ask == 0.46
    assert top.best_ask_size == 8.25
    assert top.spread == 0.03
```

**Step 2: Run test to verify failure**

Run:

```bash
PYTHONPATH=. python3 -m pytest tests/test_polymarket_client.py -q
```

Expected: FAIL because `backend.data.polymarket_client` does not exist.

**Step 3: Implement minimal parser module**

Create `backend/data/polymarket_client.py` with:

```python
"""Read-only Polymarket public API client and normalized parsers.

This module intentionally contains no private-key auth or order-placement code.
It is safe to use in simulation/research mode.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Optional

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_API = "https://clob.polymarket.com"


@dataclass(frozen=True)
class PolymarketOutcomeToken:
    outcome: str
    token_id: str
    index: int


@dataclass(frozen=True)
class PolymarketBookTop:
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
    if value is None:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except (TypeError, json.JSONDecodeError):
            return []
    return []


def map_outcome_tokens(outcomes_value: Any, token_ids_value: Any) -> dict[str, PolymarketOutcomeToken]:
    outcomes = parse_gamma_list(outcomes_value)
    token_ids = parse_gamma_list(token_ids_value)
    mapping: dict[str, PolymarketOutcomeToken] = {}
    for idx, outcome in enumerate(outcomes):
        if idx >= len(token_ids):
            continue
        outcome_text = str(outcome)
        key = outcome_text.strip().lower()
        token_id = str(token_ids[idx])
        if key and token_id:
            mapping[key] = PolymarketOutcomeToken(outcome=outcome_text, token_id=token_id, index=idx)
    return mapping


def _float_or_none(value: Any) -> Optional[float]:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def parse_clob_book_top(token_id: str, book: dict) -> PolymarketBookTop:
    bid_rows = []
    ask_rows = []
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
```

**Step 4: Run test to verify pass**

Run:

```bash
PYTHONPATH=. python3 -m pytest tests/test_polymarket_client.py -q
```

Expected: PASS.

---

### Task 2: Add async read-only public API methods

**Objective:** Add network methods for Gamma events/markets and token-level CLOB books while keeping error behavior explicit and safe.

**Files:**
- Modify: `backend/data/polymarket_client.py`
- Modify: `tests/test_polymarket_client.py`

**Step 1: Write tests using a fake async client**

Add a fake response/client class and tests for:
- `PolymarketClient.fetch_events()` calls `/events` with params.
- `PolymarketClient.fetch_market()` calls `/markets/{market_id}`.
- `PolymarketClient.fetch_book_top()` returns parsed book top.
- 404/exception returns `None` for book top and `[]` for event list only if configured as best-effort.

Example pattern:

```python
class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code
    def json(self):
        return self._payload
    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []
    async def get(self, url, params=None):
        self.calls.append((url, params))
        return self.responses.pop(0)
```

**Step 2: Run failing tests**

Run:

```bash
PYTHONPATH=. python3 -m pytest tests/test_polymarket_client.py -q
```

Expected: FAIL because `PolymarketClient` is missing.

**Step 3: Implement `PolymarketClient`**

Add:

```python
import logging
import httpx

logger = logging.getLogger("trading_bot")

class PolymarketClient:
    def __init__(self, client: Optional[httpx.AsyncClient] = None, timeout: float = 15.0):
        self._client = client
        self._timeout = timeout

    async def __aenter__(self):
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
            self._owns_client = True
        else:
            self._owns_client = False
        return self

    async def __aexit__(self, exc_type, exc, tb):
        if getattr(self, "_owns_client", False) and self._client is not None:
            await self._client.aclose()

    async def fetch_events(self, **params) -> list[dict]:
        assert self._client is not None
        try:
            response = await self._client.get(f"{GAMMA_API}/events", params=params)
            response.raise_for_status()
            payload = response.json()
            return payload if isinstance(payload, list) else []
        except Exception as exc:
            logger.debug("Polymarket events fetch failed: %s", exc)
            return []

    async def fetch_market(self, market_id: str) -> Optional[dict]:
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
        if not token_id:
            return None
        assert self._client is not None
        try:
            response = await self._client.get(f"{CLOB_API}/book", params={"token_id": token_id})
            response.raise_for_status()
            payload = response.json()
            return parse_clob_book_top(token_id, payload if isinstance(payload, dict) else {})
        except Exception as exc:
            logger.debug("Polymarket CLOB book fetch failed for %s: %s", token_id, exc)
            return None
```

**Step 4: Run tests**

Run:

```bash
PYTHONPATH=. python3 -m pytest tests/test_polymarket_client.py -q
```

Expected: PASS.

---

### Task 3: Refactor BTC market parser to consume shared helpers

**Objective:** Remove duplicated Gamma/CLOB helper logic from `btc_markets.py` while preserving behavior.

**Files:**
- Modify: `backend/data/btc_markets.py`
- Modify: `tests/test_btc_market_parsing.py` if imports change.

**Step 1: Add/adjust tests first**

Run existing BTC parser tests before changes:

```bash
PYTHONPATH=. python3 -m pytest tests/test_btc_market_parsing.py -q
```

Expected: current PASS. If it fails due environment, record failure before editing.

**Step 2: Replace local helper usage**

- Import `map_outcome_tokens`, `parse_gamma_list`, `parse_clob_book_top`, `PolymarketClient`.
- Keep the existing public `BtcBookTop` dataclass if other code imports it, or alias/convert from `PolymarketBookTop` to avoid a breaking API.
- Replace `_parse_json_list` internals with a call to `parse_gamma_list` for backward compatibility.
- Replace `_book_top_from_rows` internals with `parse_clob_book_top` for consistency.
- Replace `_fetch_clob_book_top` implementation with `PolymarketClient.fetch_book_top` or shared parser if passing raw client remains easier.

**Step 3: Verify BTC tests**

Run:

```bash
PYTHONPATH=. python3 -m pytest tests/test_btc_market_parsing.py tests/test_btc_methodology.py -q
```

Expected: PASS.

---

### Task 4: Refactor weather market CLOB helper to consume shared helpers

**Objective:** Make weather CLOB parsing use the same `parse_clob_book_top` / outcome-token mapping as BTC.

**Files:**
- Modify: `backend/data/weather_markets.py`
- Modify: `tests/test_polymarket_weather_books.py` if imports change.

**Step 1: Preserve existing API wrapper**

Keep `_parse_json_list` and `_parse_polymarket_clob_book` as compatibility wrappers for now, but implement them via the shared helpers:

```python
def _parse_json_list(value) -> list:
    return parse_gamma_list(value)


def _parse_polymarket_clob_book(book: dict) -> tuple[Optional[float], Optional[float], Optional[float]]:
    top = parse_clob_book_top("yes", book)
    return top.best_bid, top.best_ask, top.best_ask_size
```

**Step 2: Improve `_fetch_yes_token_book` mapping**

Use `map_outcome_tokens`. Prefer explicit `yes` token; fallback to first token if outcomes are missing but tokens exist.

**Step 3: Verify weather tests**

Run:

```bash
PYTHONPATH=. python3 -m pytest tests/test_polymarket_weather_books.py tests/test_weather_methodology.py tests/test_weather_gate_structured_result.py -q
```

Expected: PASS.

---

## Phase 2 — normalize event/market records for future verticals

### Task 5: Add normalized market/event parser dataclasses

**Objective:** Create generic normalized records that can be consumed by BTC, weather, RT/entertainment, and future copy-trading watchers.

**Files:**
- Modify: `backend/data/polymarket_client.py`
- Modify: `tests/test_polymarket_client.py`

**Add dataclasses:**

```python
@dataclass(frozen=True)
class PolymarketNormalizedMarket:
    market_id: str
    question: str
    slug: Optional[str]
    event_slug: Optional[str]
    outcomes: tuple[str, ...]
    outcome_prices: tuple[float, ...]
    outcome_tokens: dict[str, PolymarketOutcomeToken]
    volume: float
    closed: bool
    raw: dict

@dataclass(frozen=True)
class PolymarketNormalizedEvent:
    event_id: Optional[str]
    slug: str
    title: str
    description: str
    markets: tuple[PolymarketNormalizedMarket, ...]
    raw: dict
```

**Tests:**
- Native list fields parse correctly.
- JSON-string fields parse correctly.
- Missing/invalid `outcomePrices` yields empty tuple, not crash.
- `closed` is true if either event or market is closed where appropriate.

**Verification:**

```bash
PYTHONPATH=. python3 -m pytest tests/test_polymarket_client.py -q
```

---

## Phase 3 — paper-only copy-trading research lane design

### Task 6: Add copy-trading config/types only; no network/private execution

**Objective:** Capture OctoBot-like copy-trading profile concepts as local paper-only configuration types.

**Files:**
- Create: `backend/core/copy_trading_research.py`
- Create: `tests/test_copy_trading_research.py`

**Dataclasses:**

```python
@dataclass(frozen=True)
class CopyTradingProfile:
    profile_id: str
    label: str
    allocation_pct: float
    allocation_padding_pct: float = 0.0
    new_positions_only: bool = True
    min_position_size_usdc: float = 1.0
    min_pnl_pct: Optional[float] = None
    max_mark_price: Optional[float] = None
```

**Pure validation function:**

```python
def validate_copy_profiles(profiles: list[CopyTradingProfile]) -> list[str]:
    # Return explicit blockers; never raises for user-facing config mistakes.
```

**Tests:**
- Total allocation >100% returns blocker.
- Negative allocation returns blocker.
- Duplicate profile IDs return blocker.
- Safe valid profiles return empty list.

**Verification:**

```bash
PYTHONPATH=. python3 -m pytest tests/test_copy_trading_research.py -q
```

---

### Task 7: Add paper-only copy-trade candidate normalization

**Objective:** Convert hypothetical observed external profile positions into review-queue candidates without making trades.

**Files:**
- Modify: `backend/core/copy_trading_research.py`
- Create/modify: `tests/test_copy_trading_research.py`

**Design:**
- `ObservedProfilePosition`: profile ID, market ID, outcome, size, avg price, mark price, opened timestamp.
- `CopyTradeCandidate`: market ID, outcome, suggested max paper allocation, blockers, `paper_actionable=False` by default.
- `build_copy_trade_candidate(profile, observed_position, account_equity)` returns a candidate with blockers if profile validation/price/size filters fail.

**Critical safety test:**
- Even valid candidates must not create `Trade` rows or call any execution path.
- The returned object should be suitable for a future Signal Review Queue adapter only.

---

## Phase 4 — integration hooks after foundation passes

### Task 8: Add optional signal-review queue rows for copy-trading candidates

**Objective:** Make copy-trading observations visible as research leads while preserving no-execution behavior.

**Files:**
- Modify: `backend/core/signal_review.py`
- Modify: `tests/test_signal_review_queue.py`

**Design:**
- Add a new vertical/category: `copy_trading_research`.
- Preserve fields: profile ID, observed outcome, mark price, profile label, blockers.
- Keep `paper_actionable=false` until a future explicit methodology joins current market quotes, CLOB depth, settlement/rules, and no-trade gates.

**Verification:**

```bash
PYTHONPATH=. python3 -m pytest tests/test_signal_review_queue.py tests/test_copy_trading_research.py -q
```

---

## Final verification commands

Run from `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot`:

```bash
PYTHONPATH=. python3 -m pytest -q
cd frontend && npm run build
```

Expected:
- Backend tests pass. Existing Pydantic protected-namespace warning may still appear.
- Frontend build passes. Existing Vite chunk-size warning may still appear.

If `python3 -m pytest` fails because pytest is unavailable in a specific environment, use the known working environment from prior notes if available and also run targeted `py_compile` checks:

```bash
python3 -m py_compile backend/data/polymarket_client.py backend/data/btc_markets.py backend/data/weather_markets.py backend/core/copy_trading_research.py
```

---

## Explicit non-goals

- No live order placement.
- No private Polymarket auth/signing.
- No automatic copy trading.
- No migration into OctoBot.
- No GPL code copy/paste from OctoBot.
- No changes to paper-ledger balances unless a later user-approved paper-simulation task requires it.

---

## Handoff notes

A compact new-context handoff for this work exists at:

`/Users/kayvonai/.hermes/research/octobot/new-context-handoff-2026-05-24.md`

The prior OctoBot assessment is at:

`/Users/kayvonai/.hermes/research/octobot/octobot_prediction_market_assessment.md`

Proceed implementation in small TDD steps. If context is tight, dispatch tasks 1–4 first; defer copy-trading tasks until the shared client is stable.
