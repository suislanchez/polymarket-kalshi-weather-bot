# Weather Architecture Upgrades Implementation Plan

> **For Hermes:** Implement task-by-task with strict test-first workflow and intermittent verification after each milestone.

**Goal:** Implement four upgrades for weather paper trading: per-city/capital risk controls, weather-specific kill switch, composite execution score, and NOAA AIGEFS ingestion path with graceful fallback.

**Architecture:** Keep existing weather scan/scheduler flow intact, but add configurable gates in `weather_scan_and_trade_job`, enrich `WeatherTradingSignal` scoring in `weather_signals.py`, and add an optional secondary forecast provider (`AIGEFS`) behind feature flags. Preserve simulation safety and no-trade transparency.

**Tech Stack:** Python 3.11, SQLAlchemy, APScheduler, pytest, existing weather data modules.

---

## Task 1: Add configuration knobs for new controls

**Objective:** Make all new behavior configurable and default-safe.

**Files:**
- Modify: `backend/config.py`
- Test: `tests/test_weather_architecture_config.py` (new)

**Changes:**
1. Add settings:
   - `WEATHER_DAILY_LOSS_LIMIT` (default 200.0)
   - `WEATHER_MAX_OPEN_POSITIONS_PER_CITY` (default 2)
   - `WEATHER_COMPOSITE_MIN_SCORE` (default 0.10)
   - `WEATHER_WEIGHT_MISPRICING` (default 0.60)
   - `WEATHER_WEIGHT_SPREAD` (default 0.20)
   - `WEATHER_WEIGHT_LIQUIDITY` (default 0.15)
   - `WEATHER_WEIGHT_IMBALANCE` (default 0.05)
   - `WEATHER_USE_AIGEFS` (default False)
   - `WEATHER_AIGEFS_WEIGHT` (default 0.50)
2. Add a small test ensuring settings class exposes these keys with expected defaults.

**Verification:**
- Run: `pytest tests/test_weather_architecture_config.py -q`

---

## Task 2: Add composite weather score and explainability fields

**Objective:** Rank/filter weather opportunities using a composite score (mispricing + spread + liquidity + imbalance).

**Files:**
- Modify: `backend/core/weather_signals.py`
- Test: `tests/test_weather_composite_score.py` (new)

**Changes:**
1. Extend `WeatherTradingSignal` with:
   - `composite_score: float = 0.0`
   - `score_components: dict = field(default_factory=dict)`
2. Add helper functions:
   - `_normalized_spread_penalty(best_bid, best_ask)`
   - `_normalized_liquidity(top_ask_size, volume)`
   - `_normalized_orderbook_imbalance(best_bid, best_ask, last_price)`
   - `compute_weather_composite_score(...)`
3. In `generate_weather_signal`:
   - Compute raw edge as today.
   - Compute composite score.
   - If score < `WEATHER_COMPOSITE_MIN_SCORE`, zero out executable edge (`edge = 0.0`) and append no-trade reason.
   - Append score breakdown in `reasoning`.
4. Persist score context via reasoning/sources while keeping DB schema unchanged.

**Verification:**
- Run: `pytest tests/test_weather_composite_score.py -q`
- Run: `pytest tests/test_weather_methodology.py tests/test_weather_gate_structured_result.py -q`

---

## Task 3: Add scheduler risk controls (kill switch + per-city cap)

**Objective:** Prevent correlated weather blowups while allowing more frequent entries.

**Files:**
- Modify: `backend/core/scheduler.py`
- Test: `tests/test_weather_scheduler_risk_controls.py` (new)

**Changes:**
1. In `weather_scan_and_trade_job` before order loop:
   - Compute weather-only settled PnL since UTC day start.
   - If <= `-WEATHER_DAILY_LOSS_LIMIT`, stop weather trades this run.
2. Add helper to derive city key from signal (`signal.market.city_key`).
3. Count current open weather trades per city from `Trade` table (using market metadata available in active signals for this scan).
4. Enforce max open positions per city:
   - Skip signal if city already at cap.
   - Add clear `log_event("info", ...)` skip reason.
5. Keep existing max weather allocation logic and per-trade caps.

**Verification:**
- Run: `pytest tests/test_weather_scheduler_risk_controls.py -q`
- Run: `pytest tests/test_weather_paper_account.py -q`

---

## Task 4: Add optional NOAA AIGEFS provider path with fallback

**Objective:** Add model diversity without destabilizing current scan reliability.

**Files:**
- Create: `backend/data/noaa_aigefs.py`
- Modify: `backend/core/weather_signals.py`
- Test: `tests/test_weather_aigefs_fallback.py` (new)

**Changes:**
1. Add provider module with function:
   - `fetch_aigefs_forecast(city_key, target_date) -> Optional[EnsembleForecastLike]`
   - Network errors return `None` (never hard-fail scan).
2. In `generate_weather_signal`, when `WEATHER_USE_AIGEFS=True`:
   - Attempt AIGEFS fetch.
   - If successful, blend Open-Meteo + AIGEFS probabilities using `WEATHER_AIGEFS_WEIGHT`.
   - If failed/unavailable, fall back to Open-Meteo and annotate reason in `sources`.
3. Ensure no behavior change when feature flag is false.

**Verification:**
- Run: `pytest tests/test_weather_aigefs_fallback.py -q`
- Run: `pytest tests/test_weather_composite_score.py tests/test_weather_scheduler_risk_controls.py -q`

---

## Task 5: Integration checks and smoke run

**Objective:** Validate end-to-end behavior and ensure weather lane still runs.

**Files:**
- No source changes expected.

**Checks:**
1. Run focused suite:
   - `pytest tests/test_weather_*.py -q`
2. Run scheduler/DB sanity subset:
   - `pytest tests/test_weather_paper_account.py tests/test_weather_divergence.py -q`
3. Runtime smoke (no secrets printed):
   - one manual scan call to confirm signals generate and include composite info.

**Success Criteria:**
- Tests green.
- Weather scan returns signals and actionable count logic still works.
- Logs show explicit skip reasons for city cap/daily loss when triggered.

---

## Rollout Notes

- Keep `SIMULATION_MODE=true`.
- Start with conservative settings (`WEATHER_USE_AIGEFS=false` until stability confirmed).
- After 24h paper logs, tune `WEATHER_COMPOSITE_MIN_SCORE` and weights to target ~1–2 daily opportunities.
