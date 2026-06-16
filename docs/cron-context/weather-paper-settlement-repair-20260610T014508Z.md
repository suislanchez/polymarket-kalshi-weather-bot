# Weather paper settlement repair — 2026-06-10 01:45 UTC

## Scope / safety
- Weather-only paper ledger repair in `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot`.
- Public/read-only Polymarket Gamma data only.
- No private exchange accounts, no live trades, no order placement, no paper entries, and no auto-exit enablement.

## Root cause
`backend/core/settlement.py::fetch_polymarket_resolution()` used `event_slug` first and resolved `event[0].markets[0]` whenever Gamma returned an event. Polymarket weather event slugs represent a full bucket slate, so `markets[0]` is often not the paper trade's held market. This mis-scored non-first bucket positions and left two closed/stale positions unresolved.

## Code fix
- Added exact market selection for Gamma event resolution by matching the stored `market_ticker` against each event market's `id` / `conditionId` / `condition_id`.
- Kept a single-market fallback only when the event is unambiguous.
- Added direction-vocabulary-aware signal outcome labeling so weather `yes`/`no` signals are calibrated as `yes`/`no` rather than `up`/`down`.
- Regression tests added in `tests/test_settlement.py`.

## DB backup
Before mutating the paper DB, copied:

`/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot/tradingbot.db`

to:

`/Users/kayvonai/.hermes/backups/weather-paper-repair-20260610T014508Z/tradingbot-before-polymarket-weather-settlement-repair-20260610T014508Z.db`

## Paper ledger repair applied
Updated the local paper DB using exact public Gamma market outcomes:

| Trade | Market | Previous | Corrected |
|---|---|---:|---:|
| 12 | Beijing Jun 4 high, 28°C | win, +$47.95, settlement_value 0.0 | loss, -$75.00, settlement_value 1.0 |
| 16 | NYC Jun 4 low, 66–67°F | win, +$2,702.78, settlement_value 0.0 | loss, -$75.00, settlement_value 1.0 |
| 19 | NYC Jun 5 low, 62–63°F | pending | settled loss, -$75.00, settlement_value 0.0 |
| 22 | Seoul Jun 6 high, 24°C | pending | settled win, +$550.00, settlement_value 1.0 |

Recomputed `bot_state` from the repaired trade ledger.

## Post-repair state
- Weather paper trades: **22 total / 22 settled / 0 pending**.
- Wins: **3**.
- Realized weather PnL: **-$709.18**.
- Weather-specific paper equity from $1,000 starting bankroll: **$290.82**.
- Global DB bot state: bankroll **$9,290.82**, total PnL **-$709.18**, total trades **22**, winning trades **3**.

## Verification
- RED: `PYTHONPATH=. ./venv/bin/python -m pytest -q tests/test_settlement.py` failed before implementation because the new exact-market helper did not exist.
- GREEN: `tests/test_settlement.py` -> **4 passed**.
- Live exact-market smoke after code fix:
  - `2425070 / lowest-temperature-in-nyc-on-june-5-2026` -> `(True, 0.0)`.
  - `2440776 / highest-temperature-in-seoul-on-june-6-2026` -> `(True, 1.0)`.
  - `2416597 / lowest-temperature-in-nyc-on-june-4-2026` -> `(True, 1.0)`.
