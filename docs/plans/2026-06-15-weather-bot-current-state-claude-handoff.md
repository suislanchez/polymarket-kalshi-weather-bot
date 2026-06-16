# Weather Prediction-Market Bot — Current State, Architecture, Methodology, API Inventory, Performance, and Improvement Plan

Generated locally: **2026-06-15 21:46 PDT**  
Repository: `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot`  
Active branch/commit at audit time: `main` / `e406394`  
Primary active lane: **weather prediction markets only**. BTC and entertainment/Rotten Tomatoes code still exists, but current operating preference is weather-only, selective/no-forced trades, simulation/paper-only unless Kayvon explicitly authorizes live trading.

> **Safety rule for Claude:** Do not expose secrets, wallet keys, API keys, passphrases, private keys, balances, or full private account payloads. Do not place live trades. Do not create paper trades unless the requested task explicitly asks for a paper-simulation action and the no-trade gates pass. Current mode is simulation/research.

---

## 0. Verification evidence used for this document

Fresh local checks run during this audit:

1. Repo state:
   - `git branch --show-current` -> `main`
   - `git rev-parse --short HEAD` -> `e406394`
   - `git status --short` showed a **broad dirty working tree**: many modified and untracked backend/frontend/tests/docs files. Treat current filesystem as the source of truth, but commit boundaries are unclear.
   - Local runtime: repo venv Python `3.12.13`; Node `22.22.3`; npm `10.9.8`.
2. Targeted backend/frontend-contract tests:
   - `PYTHONPATH=. ./venv/bin/python -m pytest -q tests/test_weather_paper_account.py tests/test_api_response_models.py tests/test_frontend_open_position_risk_contract.py`
   - Result: **68 passed, 6 existing warnings**.
3. Polymarket public API smoke:
   - `./venv/bin/python scripts/validate_polymarket_apis.py --json`
   - Result: public Gamma/Data/CLOB checks all returned HTTP 200; authenticated CLOB/order signing is **not ready** because required env fields are missing and auth is disabled.
4. Kalshi API smoke:
   - Public `/markets` and orderbook checks succeeded.
   - Private `/portfolio/balance` endpoint responded successfully with configured credentials. The actual balance payload was not copied into this document.
5. Open-Meteo smoke:
   - `fetch_ensemble_forecast('los_angeles', date(2026, 6, 16))` returned **31 members**, mean high `76.51°F`, mean low `65.65°F`.
6. Weather paper audit report:
   - `./venv/bin/python scripts/weather_audit_report.py --db tradingbot.db --window-hours 336 --format markdown`
   - Result: last 336h strict window: **15 trades, 15 settled, 2W/13L, -$343.75 PnL**, largest outlier `highest-temperature-in-seoul-on-june-6-2026` `+$550.00`; all-weather account state: **22 total / 22 settled / 0 pending / -$709.18 realized PnL / $290.82 equity**.
7. API smoke through FastAPI `TestClient` with `WEATHER_ENABLED=false`:
   - `/api/stats`, `/api/dashboard`, `/api/open-position-risk`, `/api/weather/polymarket-source-states?...`, `/api/kalshi/status`, `/api/polymarket/relayer/status` returned HTTP 200.
   - Important caveat: TestClient startup still starts the scheduler and a BTC scan even with weather disabled. It did **not** create new trades in the final DB reconciliation.
8. Final DB reconciliation after smokes:
   - `tradingbot.db`: `trades=22`, `signals=84504`, weather trades `22`, weather settled `22`, open `0`, weather realized PnL `-$709.18`, latest signal `2026-06-14 03:03:49.634360`.
9. Fresh verification from Kayvon's handoff request on 2026-06-16 UTC:
   - `git rev-parse --short HEAD` -> `e406394`; `git status --short` reported **51** dirty entries.
   - `PYTHONPATH=. ./venv/bin/python scripts/validate_polymarket_apis.py` -> all public Polymarket Gamma/Data/CLOB checks OK 200; authenticated CLOB/order signing still not ready (`POLYMARKET_API_PASSPHRASE`, `POLYMARKET_ADDRESS`, `PRIVATE_KEY`/`POLYMARKET_PRIVATE_KEY`, `POLYMARKET_FUNDER_ADDRESS` missing; auth disabled).
   - Direct Kalshi credential smoke -> credentials present, private key path exists, `/portfolio/balance` call OK (payload not copied here).
   - Direct Polymarket relayer smoke -> credentials present but validation false; direct `https://relayer.polymarket.com/submit` test raised DNS/connect error (`nodename nor servname provided`). Treat relayer as configured-but-broken/unusable until endpoint/credentials are fixed.
   - `PYTHONPATH=. ./venv/bin/python scripts/weather_audit_report.py --db tradingbot.db --window-hours 336 --format markdown` reproduced the key ledger numbers: 15 strict-window trades, 2W/13L, `-$343.75` window PnL; all-weather equity `$290.82`, realized PnL `-$709.18`, 22 total/settled, 0 pending.
   - `PYTHONPATH=. ./venv/bin/python -m pytest -q tests/test_weather_audit.py tests/test_polymarket_api_setup.py tests/test_weather_paper_account.py::test_polymarket_weather_source_state_rows_preserve_station_anomaly_diagnostics` -> **12 passed, 1 existing warning**.

---

## 1. Executive summary

The current project is a local FastAPI + SQLite + React dashboard prediction-market research/paper-trading system. It originally supported BTC 5-minute Polymarket markets, weather markets on Kalshi and Polymarket, and entertainment/Rotten Tomatoes research. The active product scope is now **weather**, with BTC and entertainment treated as legacy/paused lanes.

The active weather bot is **not a live trading bot** right now. It is a research and paper-trading system with conservative gates. It discovers weather markets, fetches public forecasts and market orderbooks, creates research-visible signals, applies many no-trade gates, optionally creates paper trades, settles paper trades from public outcome APIs, and shows calibration/source-state evidence in the dashboard.

Current performance is **bad after settlement repair**:

- Weather paper ledger: **22 trades / 22 settled / 0 open**.
- Wins/losses: **3W / 19L**.
- Realized PnL: **-$709.18** from a weather-specific starting bankroll of `$1,000`.
- Current weather equity: **$290.82** toward a `$1,100` target.
- Venue split:
  - Kalshi: **11 settled / 1W / 10L / -$665.43**.
  - Polymarket: **11 settled / 2W / 9L / -$43.75**.

A major lesson: older headline PnL was misleading. A settlement bug in Polymarket multi-market weather slates incorrectly scored some bucket trades by using the first market in an event instead of the held market. That bug made the ledger look much better than it was. The repair is documented in `docs/cron-context/weather-paper-settlement-repair-20260610T014508Z.md`; after repair the weather account is deeply negative.

The bot has since moved toward a safer state: most recent weather signal batches are filtered, Polymarket source-state rows are QA-only and `paper_actionable=false`, Kalshi paper execution is deliberately disabled, and open-position auto-exit is disabled.

---

## 2. Current repo and runtime map

### 2.1 Top-level project shape

Important paths:

- `README.md` — repo overview/setup.
- `ARCHITECTURE.md` — original architecture overview.
- `VALIDATED_RESEARCH.md`, `RESEARCH.md` — research notes and market methodology context.
- `HERMES_SETUP_NOTES.md` — Hermes/local setup and historical sprint notes. Treat any sensitive material as `[REDACTED]`.
- `.env` — local runtime config with secrets; do not print values.
- `.env.example` — expected config keys, no real secrets.
- `requirements.txt` — Python dependencies, including optional `pmxt==2.46.14`.
- `frontend/package.json` — React/Vite dashboard dependencies.
- `tradingbot.db` — local app SQLite DB.
- `docs/cron-context/` — compact handoff files for weather/BTC/entertainment/platform cron lanes.
- `docs/plans/` — implementation plans, including the OctoBot-inspired Polymarket client plan.
- `scripts/` — validation/report scripts.
- `tests/` — current test suite.

### 2.2 Backend runtime layers

#### API / application layer

File: `backend/api/main.py`

Responsibilities:

- FastAPI app and routes.
- Scheduler startup/shutdown.
- Dashboard aggregation.
- Weather, BTC, calibration, open-position-risk, relayer, Kalshi status endpoints.
- WebSocket event stream.

Important endpoints:

- `/api/health`
- `/api/stats`
- `/api/dashboard`
- `/api/signals`
- `/api/signals/actionable`
- `/api/trades`
- `/api/open-position-risk`
- `/api/weather/forecasts`
- `/api/weather/markets`
- `/api/weather/signals`
- `/api/weather/divergences`
- `/api/weather/polymarket-source-states`
- `/api/calibration`
- `/api/kalshi/status`
- `/api/polymarket/relayer/status`
- `/api/bot/start`, `/api/bot/stop`, `/api/bot/reset`

Current issue: TestClient startup starts the scheduler and a BTC scan even when the audit only wants read-only endpoint checks. That did not create trades in this audit, but it is a design leak that should be fixed by separating app construction from scheduler startup.

#### Scheduler / orchestration layer

File: `backend/core/scheduler.py`

Jobs:

- `scan_and_trade_job()` — legacy BTC scan every `SCAN_INTERVAL_SECONDS`.
- `weather_scan_and_trade_job()` — weather scan every `WEATHER_SCAN_INTERVAL_SECONDS` when weather is enabled.
- `settlement_job()` — settles pending paper trades.
- `open_position_risk_job()` — marks open paper positions and records recommendations.
- `heartbeat_job()` — logs current state.

Weather paper execution has a final boundary via `_weather_paper_execution_blockers(signal)`:

- Blocks Kalshi paper execution when `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=false`.
- Blocks zero-size signals.
- Carries through signal-level `no_trade_reasons`.

Weather execution controls:

- Max 3 weather paper trades per scan.
- Min paper trade size `$10`.
- Max total weather pending exposure `$500`.
- Weather daily loss limit `$200`.
- Per-city open weather cap from `WEATHER_MAX_OPEN_POSITIONS_PER_CITY`.
- Max per-weather-trade size from `WEATHER_MAX_TRADE_SIZE`.

#### Configuration layer

File: `backend/config.py`

Important current settings:

- `DATABASE_URL = sqlite:///./tradingbot.db`
- `ACTIVE_PRODUCT_SCOPE = "weather"`
- `DASHBOARD_LEGACY_SECTIONS_ENABLED = False`
- `SIMULATION_MODE = True`
- `MIN_EDGE_THRESHOLD` is set to `999` in local `.env`, effectively suppressing BTC actionability.
- `WEATHER_ENABLED = True` in `.env`, but test smokes used `WEATHER_ENABLED=false` to avoid broad scans.
- `WEATHER_RESEARCH_ENABLED = True`
- `WEATHER_MIN_EDGE_THRESHOLD = 0.05` in `.env` even though code default is `0.08`.
- `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED = False`
- `PAPER_POSITION_RISK_ENABLED = True`
- `PAPER_AUTO_EXIT_ENABLED = False`
- `WEATHER_USE_AIGEFS = False`

---

## 3. Data stores and artifacts

### 3.1 App DB

Path: `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot/tradingbot.db`

Observed table counts after this audit:

- `trades=22`
- `signals=84504`
- `bot_state=1`
- `btc_price_snapshots=54623`
- `rotten_tomatoes_source_states=277`
- `ai_logs=0`
- `scan_logs=0`

Key ORM/model file: `backend/models/database.py`

Main app tables:

- `trades` — paper trades and risk marks.
- `signals` — generated signals, whether executed, calibration fields.
- `bot_state` — global bankroll/PnL counters.
- `btc_price_snapshots` — BTC model input price snapshots.
- `rotten_tomatoes_source_states` — entertainment source-state data.
- `ai_logs`, `scan_logs` — currently empty.

Important schema columns on `trades`:

- Market identity: `market_ticker`, `platform`, `event_slug`, `market_type`, `direction`.
- Entry/accounting: `entry_price`, `size`, `timestamp`, `settled`, `settlement_time`, `settlement_value`, `result`, `pnl`.
- Signal link: `signal_id`, `model_probability`, `market_price_at_entry`, `edge_at_entry`.
- Exit/risk fields: `closed_early`, `exit_time`, `exit_price`, `exit_size`, `exit_reason`, `exit_policy`, `exit_evidence`, `unrealized_pnl`, `last_mark_price`, `last_mark_time`, `last_risk_action`, `last_risk_reasons`, `last_risk_source_status`, `last_risk_evidence`.

### 3.2 Research DB

Path: `/Users/kayvonai/.hermes/research/prediction-market-edge-snapshots.sqlite`

Observed table counts:

- `market_quotes_v2=35420`
- `raw_snapshots_v2=184`
- `polymarket_weather_source_states=9208`
- `weather_signal_review_candidates=1178`
- `weather_bot_signal_calibrations=749`
- `weather_forecast_calibrations=20620`
- `outcome_resolutions=186`
- BTC research tables also exist: `btc_chainlink_boundary_v1`, `btc_chainlink_report_request_v1`, `btc_outcome_scoring_v1`.

Latest weather handoff reports:

- Latest weather snapshot batch: `20260615T151146Z`.
- Latest Polymarket source-state batch: **220 rows**, all `paper_actionable=false`.
- Neighbor-value audit: **132** rows have non-empty `station_anomaly_neighbor_values`.

This DB is used for research/calibration/source-state observability, not direct trade execution.

### 3.3 Snapshot files

Weather source snapshots live under:

- `/Users/kayvonai/.hermes/research/.snapshots/`

Latest run from `docs/cron-context/weather-latest.md`:

- `20260615T151146Z-weather-public-raw.json`
- `20260615T151146Z-weather-public-summary.json`
- `20260615T151146Z-weather-source-*`
- `20260615T151146Z-weather-history-source-*`
- `20260615T151146Z-weather-neighbor-history-source-*`

---

## 4. Active weather methodology

### 4.1 Core philosophy: selective/no-forced trades

The bot should not trade just because a scan ran. A signal can be visible in the dashboard/research DB while still being non-executable. The current architecture intentionally separates:

1. **Discovery** — find markets and source data.
2. **Modeling** — estimate fair value.
3. **Review/calibration visibility** — persist signals and source-state rows.
4. **Actionability gates** — decide whether a paper trade may be created.
5. **Execution boundary** — final scheduler-level blockers before writing a `Trade` row.

Zero-trade periods are acceptable.

### 4.2 Market discovery

#### Kalshi weather markets

Files:

- `backend/data/kalshi_client.py`
- `backend/data/kalshi_markets.py`
- `backend/data/weather_station_map.py`

Flow:

1. `fetch_kalshi_weather_markets(city_keys=None)` iterates checked-in Kalshi series tickers from `KALSHI_WEATHER_STATION_MAP`.
2. Calls Kalshi `/markets` with `series_ticker`, `status=open`, `limit=200`, cursor pagination.
3. Parses Kalshi tickers like `KXHIGHLAX-26JUN16-B73` / `...-T73`.
4. Fetches `/markets/{ticker}/orderbook` and parses `orderbook_fp`.
5. Normalizes top-of-book fields into `WeatherMarket` objects.
6. Attaches exact station metadata from `weather_station_map.py`.

Kalshi station mapping is a key strength: forecasts target exact settlement stations rather than broad metro centroids. Examples:

- Los Angeles -> `KLAX`, CLI product `CLILAX`.
- NYC -> `KNYC` / Central Park, CLI product `CLINYC`.
- Chicago -> `KMDW`, CLI product `CLIMDW`.
- Miami -> `KMIA`, CLI product `CLIMIA`.

#### Polymarket weather markets

Files:

- `backend/data/weather_markets.py`
- `backend/data/polymarket_client.py`
- `backend/core/weather_methodology.py`

Flow:

1. `fetch_polymarket_weather_markets()` queries Gamma `public-search` for `highest temperature`, `lowest temperature`, and `temperature` because that surfaces grouped daily slates better than tag-only queries.
2. Also queries Gamma `/events` with weather-like filters and slug patterns.
3. Parses titles/questions for city, date, high/low, threshold, units, and whether the contract is directional or a mutually-exclusive bucket.
4. Converts Celsius thresholds to Fahrenheit for modeling.
5. Uses `map_outcome_tokens()` from `polymarket_client.py` to map Gamma outcomes to CLOB token IDs.
6. Fetches YES and NO token CLOB books directly so NO positions use real NO-token liquidity, not stale `1 - YES` math.
7. Parses rule text with `parse_settlement_metadata()` to capture Wunderground/HKO/NWS settlement source, station code, product code, URL, precision, and units.

### 4.3 Forecasting model

Files:

- `backend/data/weather.py`
- `backend/data/noaa_aigefs.py`
- `backend/core/weather_signals.py`

Primary forecast provider:

- Open-Meteo Ensemble API: `https://ensemble-api.open-meteo.com/v1/ensemble`
- Uses `gfs_seamless`, daily `temperature_2m_max` and `temperature_2m_min`, Fahrenheit.
- Collects control/member keys into per-member highs/lows.
- Cache: in-memory `(city_key, target_date)` cache with 15-minute TTL.

Optional secondary provider:

- NOAA AIGEFS adapter in `backend/data/noaa_aigefs.py`.
- Controlled by `WEATHER_USE_AIGEFS` and `WEATHER_AIGEFS_ENDPOINT_TEMPLATE`.
- Currently disabled. Treat as unconfigured/placeholder until proven.

Probability estimation:

- Above/below markets: fraction of ensemble members above/below threshold.
- Bucket/range markets: fraction of ensemble members inside inclusive bucket range via `estimate_bucket_probability()`.
- Extreme probabilities are clipped to `[0.05, 0.95]` to avoid betting as if the model has certainty.

Known weakness: clipping a 31-member unanimous ensemble to 95% is still overconfident near thresholds. The plan in `docs/plans/2026-06-07-weather-bot-reasoning-speed-audit.md` recommends a real calibration/shrinkage layer, but `backend/core/weather_calibration.py` does not currently exist.

### 4.4 Signal generation

File: `backend/core/weather_signals.py`

Signal type: `WeatherTradingSignal`

Fields include:

- `model_probability`
- `market_probability`
- `edge`
- `direction` (`yes` or `no`)
- `confidence`
- `kelly_fraction`
- `suggested_size`
- `sources`
- `reasoning`
- `ensemble_mean`, `ensemble_std`, `ensemble_members`
- `no_trade_reasons`
- `execution_spread`, `top_ask_size`
- bucket-set diagnostic fields
- composite execution-quality score

High-level flow in `generate_weather_signal(market)`:

1. Fetch ensemble forecast for `market.city_key` and `market.target_date`.
2. Estimate model YES probability using high/low/bucket logic.
3. Optionally blend with AIGEFS if enabled.
4. Clip model probability to `[5%, 95%]`.
5. Compare model YES probability to market YES price using `calculate_edge()`.
6. Choose YES or NO direction based on greater edge.
7. Use the held side's executable book:
   - YES: `best_bid`, `best_ask`, `top_ask_size`.
   - NO: `no_best_bid`, `no_best_ask`, `no_top_ask_size`.
8. Apply max entry price, settlement/source, spread/depth, threshold-distance, and composite-score gates.
9. Kelly-size the trade but zero size when gates fail.
10. Persist the signal for UI/research visibility.

### 4.5 No-trade/actionability gates

Core gate: `evaluate_weather_trade_gate()` in `backend/core/weather_methodology.py`.

Current checks include:

- Must have exact settlement source and station.
- Must have line-level bid/ask.
- Spread must not exceed configured max spread.
- Must have top ask size and enough top ask depth.
- Ensemble mean must be far enough from threshold.
- Market probability must be inside `(0, 1)`.

Additional weather signal blockers:

- Bucket contracts require mutually-exclusive set sanity before actionability.
- Bucket set sanity checks line count, parseable ranges, no overlaps, and total model probability mass roughly around one.
- Entry price above `WEATHER_MAX_ENTRY_PRICE` zeroes edge.
- Composite score below `WEATHER_COMPOSITE_MIN_SCORE` zeroes size.
- Kalshi paper execution is blocked at scheduler boundary unless `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=true`.

Composite score blends:

- Mispricing edge (`WEATHER_WEIGHT_MISPRICING`, default 0.60)
- Spread quality (`WEATHER_WEIGHT_SPREAD`, default 0.20)
- Liquidity quality (`WEATHER_WEIGHT_LIQUIDITY`, default 0.15)
- Orderbook imbalance (`WEATHER_WEIGHT_IMBALANCE`, default 0.05)

### 4.6 Source-state and final-source QA

File: `backend/core/weather_methodology.py` and `backend/core/weather_paper_account.py`

The bot now captures source-state evidence separately from trade actionability. This is important: source-state rows are for QA/calibration and currently remain non-actionable.

Source-state methods:

- Parse NWS CLI daily climate reports and explicitly reject preliminary `VALID TODAY` / `VALID AS OF` products.
- Parse HKO Daily Extract observations.
- Parse Wunderground current observations and Wunderground history observations.
- Build Wunderground neighbor-source URLs.
- Evaluate station-anomaly diagnostics against neighboring station values.

Latest source-state facts from `docs/cron-context/weather-latest.md`:

- Latest batch `20260615T151146Z`: 220 Polymarket source-state rows.
- All rows are `paper_actionable=false`.
- Wunderground history: 154 rows, 132 complete, 22 partial.
- HKO rows: 66 total, 22 observed, 44 missing target date.
- Station anomaly: 132 checked, 88 pass, 44 warning, 88 not checked.
- Seoul/RKSI rows have warning examples with neighbor values `[90.0, 91.0]` and max delta around `9°F`.
- HKO/open rows remain blockers where target-date rows are missing or source context is partial.

Current interpretation: source-state visibility improved, but final settlement validation is still not strong enough to upgrade rows to actionability.

### 4.7 Paper execution

Weather paper trades are created only in `weather_scan_and_trade_job()` after signal gates and scheduler-level blockers.

Trade row fields:

- `market_ticker` = Kalshi ticker or Polymarket market ID.
- `platform` = `kalshi` or `polymarket`.
- `event_slug` = event/slug/ticker.
- `market_type = "weather"`.
- `direction = "yes"` or `"no"`.
- `entry_price` = held side executable ask if available, otherwise fallback market probability.
- `size` = Kelly-derived size clamped by max trade size.
- `model_probability`, `market_price_at_entry`, `edge_at_entry`.

The DB currently contains no open weather positions.

### 4.8 Settlement and PnL

File: `backend/core/settlement.py`

Polymarket settlement:

- `fetch_polymarket_resolution(market_id, event_slug)` uses Gamma event slug first, but now selects the exact held market by matching stored market ID against `id`, `conditionId`, or `condition_id`.
- Single-market fallback only when unambiguous.
- Parses `outcomePrices`: first outcome near 1 -> YES/UP won; first outcome near 0 -> NO/DOWN won.

Kalshi settlement:

- `_fetch_kalshi_resolution(ticker)` tries public `/markets/{ticker}` first.
- Falls back to authenticated `KalshiClient.get_market()` if credentials exist.
- Uses `status` and `result` to determine resolved YES/NO.

PnL:

- Uses `calculate_final_settlement_pnl()` from `backend/core/position_risk.py` through `calculate_pnl()`.
- Direction mapping handles `up/down` and `yes/no`.
- Linked `Signal` rows are updated with actual outcome and correctness for calibration.

Major repaired bug:

- Before 2026-06-10, Polymarket weather event slugs could resolve against `markets[0]` in a bucket slate, mis-scoring held bucket rows.
- Repair file: `docs/cron-context/weather-paper-settlement-repair-20260610T014508Z.md`.
- Post-repair state: 22 total / 22 settled / `-$709.18` realized weather PnL.

### 4.9 Open-position risk / cash-out system

Files:

- `backend/core/open_position_monitor.py`
- `backend/core/position_risk_weather.py`
- `backend/core/weather_exit_quotes.py`
- `backend/core/position_exit_executor.py`

Current state:

- `PAPER_POSITION_RISK_ENABLED=True`
- `PAPER_AUTO_EXIT_ENABLED=False`
- Since all weather trades are settled, current open-position risk rows are `0`.

Purpose:

- For open paper positions, fetch public held-side exit quotes.
- Analyze whether the held thesis is intact, weakened, or broken.
- Persist marks/recommendations to trade rows.
- If auto-exit were enabled, record paper exits only. Currently it is recommendations-only.

Kalshi quotes:

- Uses public orderbook endpoint and `orderbook_fp`.
- Converts YES/NO held-side bid/ask correctly.

Polymarket quotes:

- Uses Gamma market metadata + token-level CLOB book.
- Uses the held outcome token directly; NO exits do not infer liquidity from YES math.
- Handles closed/stale token 404 as `closed_market_or_stale_token`.

---

## 5. Legacy / paused methodologies

### 5.1 BTC 5-minute Polymarket lane

Files:

- `backend/core/signals.py`
- `backend/core/btc_methodology.py`
- `backend/data/btc_markets.py`
- `backend/data/crypto.py`

Current posture:

- Legacy/paused for current work.
- Local `.env` sets `MIN_EDGE_THRESHOLD=999`, effectively preventing BTC actionability.
- API startup still starts BTC scheduler; this should be cleaned up.

Methodology:

- Fetches Polymarket BTC 5-minute Up/Down markets by slug pattern `btc-updown-5m-{unix_timestamp}`.
- Uses Coinbase first for BTC 1-minute candles, then Kraken, Binance, Bybit fallback.
- Computes RSI, 1m/5m/15m momentum, VWAP deviation, SMA crossover, volatility, and market-skew.
- Converts weighted composite to model probability range `0.35–0.65`.
- Requires indicator convergence, time-to-expiry window, entry price cap, and settlement-source gates.
- BTC no-trade gates are strict because markets settle from Chainlink BTC/USD while model inputs are exchange spot microstructure.
- Chainlink Data Streams boundary report URLs are generated for exact window start/end but require authentication and are not fully wired as a live source.

### 5.2 Entertainment / Rotten Tomatoes / box office lane

Files:

- `backend/core/entertainment_signals.py`
- `backend/core/entertainment_paper_account.py`
- `docs/cron-context/entertainment-latest.md`

Current posture:

- Legacy/paused for current work.
- No active RT trades in the current weather-focused ledger.

Methodology:

- Source-state/calibration-first approach.
- Rotten Tomatoes known source URL mapping for specific movie market slugs.
- The Numbers weekend box-office parsing.
- Bucket parsing and exactly-one-winner diagnostics.
- Rows are calibration/source-state only unless future independent forecast, platform settlement, liquidity, and risk gates are added.

---

## 6. API inventory and current configuration state

### 6.1 Polymarket public APIs

Config keys:

- `POLYMARKET_GAMMA_API=https://gamma-api.polymarket.com`
- `POLYMARKET_DATA_API=https://data-api.polymarket.com`
- `POLYMARKET_CLOB_API=https://clob.polymarket.com`

Files:

- `backend/config.py`
- `backend/data/polymarket_client.py`
- `backend/data/polymarket_api_setup.py`
- `scripts/validate_polymarket_apis.py`
- `backend/data/weather_markets.py`
- `backend/data/btc_markets.py`
- `backend/core/settlement.py`
- `backend/core/weather_exit_quotes.py`

Live smoke result:

- Gamma `/markets?limit=5&closed=false`: OK 200.
- Data `/trades?limit=1`: OK 200.
- CLOB `/time`: OK 200.
- CLOB `/book`, `/midpoint`, `/price?side=BUY`, `/price?side=SELL` for a discovered token: OK 200.

Current status: **public Polymarket reads work**.

### 6.2 Polymarket authenticated CLOB / order signing

Config keys:

- `POLYMARKET_API_KEY_ID`
- `POLYMARKET_API_SECRET`
- `POLYMARKET_API_PASSPHRASE`
- `POLYMARKET_ADDRESS`
- `POLYMARKET_FUNDER_ADDRESS`
- `POLYMARKET_SIGNATURE_TYPE`
- `POLYMARKET_ENABLE_AUTHENTICATED_CLOB`
- `PRIVATE_KEY` or `POLYMARKET_PRIVATE_KEY`

Current redacted local status from validator:

- API key ID present: yes.
- API secret present: yes.
- API passphrase present: **no**.
- address present: **no**.
- funder address present: **no**.
- private key present: **no**.
- authenticated CLOB enabled: **false**.
- L2 credentials ready: **false**.
- order signing ready: **false**.

Current status: **not configured for authenticated CLOB or order placement**. This is good for safety, but if live trading is ever requested, this is one of the required setup gaps.

### 6.3 Polymarket relayer API

Config keys:

- `RELAYER_API_KEY`
- `RELAYER_API_KEY_ADDRESS`

Files:

- `backend/data/polymarket_relayer.py`
- `/api/polymarket/relayer/status` in `backend/api/main.py`

Current redacted status:

- Credentials are present.
- `validate_credentials()` returned **false** in the direct smoke.
- TestClient route returned HTTP 200 with keys `configured`, `connected`, and `address`.

Current status: **configured but not validating/connected**.

Important security/UX gap:

- `/api/polymarket/relayer/status` returns `settings.RELAYER_API_KEY_ADDRESS`. That may not be a secret like an API key, but for safety and consistency this endpoint should return `address_present=true` or a shortened/redacted address rather than the full value.

### 6.4 Kalshi trade API

Base URL:

- `https://api.elections.kalshi.com/trade-api/v2`

Config keys:

- `KALSHI_API_KEY_ID`
- `KALSHI_PRIVATE_KEY_PATH`
- `KALSHI_ENABLED`
- `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED`

Files:

- `backend/data/kalshi_client.py`
- `backend/data/kalshi_markets.py`
- `backend/core/settlement.py`
- `/api/kalshi/status` in `backend/api/main.py`

Current redacted status:

- Credentials present: yes.
- Private key file exists: yes.
- Public `/markets` check: OK.
- Public orderbook sample: OK.
- Private `/portfolio/balance`: OK.
- `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=false` because Kalshi paper trades have underperformed.

Current status: **Kalshi API works, but Kalshi weather paper execution is deliberately monitor-only**.

Security/UX gap:

- `/api/kalshi/status` returns raw `balance_data`. It should return a redacted/summarized status unless a private operator view explicitly needs more.

### 6.5 Open-Meteo Ensemble API

Endpoint:

- `https://ensemble-api.open-meteo.com/v1/ensemble`

Files:

- `backend/data/weather.py`

Current status:

- No key required.
- Live smoke succeeded for LA Jun 16 with 31 ensemble members.

### 6.6 NOAA/NWS APIs and source pages

Used for:

- NWS station observations: `https://api.weather.gov/stations/{station}/observations` in `fetch_nws_observed_temperature()`.
- Final CLI daily climate products via NWS public product pages from station map.
- Chainlink-like exactness concepts in BTC lane; BTC Data Streams itself requires auth and is not fully active.

Files:

- `backend/data/weather.py`
- `backend/data/weather_station_map.py`
- `backend/core/weather_methodology.py`
- `backend/core/btc_methodology.py`

Current status:

- NWS station/source mapping is explicit for Kalshi weather cities.
- Final CLI source parsing exists and rejects preliminary products.
- Some source-state rows remain not checked/missing observation or missing neighbor context.

### 6.7 Wunderground / Weather.com / HKO source data

Used for:

- Polymarket international/weather-source settlement evidence and QA.
- Wunderground current/history observations.
- HKO Daily Extract observations.
- Neighbor station anomaly diagnostics.

Files:

- `backend/core/weather_methodology.py`
- `backend/core/weather_paper_account.py`
- Snapshot runner under `/Users/kayvonai/.hermes/research/.snapshots/weather_sprint_public_snapshot.py`

Current source-state issues:

- HKO target-date missing rows remain blockers.
- Seoul/RKSI Wunderground rows show anomaly warnings versus neighbor stations.
- All latest Polymarket source-state rows are `paper_actionable=false`.

### 6.8 Groq AI API

Config keys:

- `GROQ_API_KEY`
- `GROQ_MODEL`

Files:

- `backend/ai/groq.py`
- `backend/config.py`

Current status:

- `GROQ_API_KEY` was not present in the redacted local `.env` inventory.
- Not part of the active weather trading path in this audit.
- If invoked, `backend/ai/groq.py` raises `ValueError("GROQ_API_KEY not configured")`.

### 6.9 FRED/BLS keys

`.env.example` includes:

- `FRED_API_KEY`
- `BLS_API_KEY`

Current status:

- These do not appear in `backend/config.py` and were not found in active weather code during this audit.
- Treat as stale/unwired config until a macro/economic lane actually uses them.

### 6.10 Mapbox token

`.env.example` includes:

- `VITE_MAPBOX_TOKEN`

Current status:

- Frontend optional visualization config; not part of trading logic.

---

## 7. Open-source tool integration

There are two related open-source pieces to be aware of: **OctoBot / OctoBot-Prediction-Market** and **pmxt**.

### 7.1 OctoBot / OctoBot-Prediction-Market

Local research clones:

- `/Users/kayvonai/.hermes/research/octobot/OctoBot-Prediction-Market`
- `/Users/kayvonai/.hermes/research/octobot/OctoBot`

Assessment docs:

- `/Users/kayvonai/.hermes/research/octobot/octobot_prediction_market_assessment.md`
- `/Users/kayvonai/.hermes/research/octobot/new-context-handoff-2026-05-24.md`
- Repo plan: `docs/plans/2026-05-24-octobot-inspired-polymarket-client-v2.md`

What OctoBot-Prediction-Market is:

- Repository: `Drakkar-Software/OctoBot-Prediction-Market`.
- It is mostly a thin distribution/config wrapper around upstream `OctoBot[full]==2.1.1`.
- The package README says 99.99% of the code is in OctoBot and dependencies.
- It uses `profile_copy_trading` and distribution `prediction_market` in `octobot_prediction_market/config/default_config.json`.
- `start.py` calls `octobot_prediction_market.cli.main()`.
- The CLI calls `octobot.cli.main(..., default_config_file=DEFAULT_CONFIG_FILE)`.
- Requirements: `OctoBot[full]==2.1.1`.
- Python requirement from `setup.py`: `>=3.13`.
- License: GPL-3.0.

How to access/use locally:

```bash
cd /Users/kayvonai/.hermes/research/octobot/OctoBot-Prediction-Market
# Requires Python >=3.13; python3.13 is currently not on PATH in this environment.
python3.13 -m venv .venv
. .venv/bin/activate
python -m pip install -Ur requirements.txt
python start.py
```

Docker is available locally, so the README's Docker path is more realistic if we want to try the upstream distribution without installing Python 3.13:

```bash
cd /Users/kayvonai/.hermes/research/octobot/OctoBot-Prediction-Market
docker run -itd --name OctoBot-Prediction-Market \
  -p 80:5001 \
  -v $(pwd)/user:/octobot/user \
  -v $(pwd)/tentacles:/octobot/tentacles \
  -v $(pwd)/logs:/octobot/logs \
  drakkarsoftware/octobot:predictionmarket-stable
```

Important: do **not** copy GPL code directly into our repo unless we intentionally accept the license implications.

Most useful OctoBot asset:

- Upstream Polymarket CCXT-style adapter:
  - `/Users/kayvonai/.hermes/research/octobot/OctoBot/packages/tentacles/Trading/Exchange/polymarket/ccxt/polymarket_async.py`
- It supports broad Gamma/Data/CLOB endpoint mappings, CLOB books/prices/trades, private CLOB methods, order creation/cancellation, auth helpers, EIP-712 signing, rate-limit costs, positions, balances, etc.

How our project currently uses OctoBot:

- We do **not** run OctoBot as the production bot.
- We used it as clean-room inspiration for a read-only internal Polymarket client.
- Current internal implementation: `backend/data/polymarket_client.py`.
- Current plan: `docs/plans/2026-05-24-octobot-inspired-polymarket-client-v2.md`.

Why not port wholesale:

- Our bot is domain-specific: weather station mapping, source-state gates, selective/no-forced trades, Kalshi support, paper ledgers, dashboard calibration.
- OctoBot-Prediction-Market is early; Kalshi issue is still open in the assessed context.
- Copy trading/arbitrage are advertised but still work-in-progress/aspirational.
- Python >=3.13 and a large framework stack would increase operational complexity.
- GPL licensing makes direct code porting risky.

### 7.2 Our clean-room PolymarketClient

File: `backend/data/polymarket_client.py`

Purpose:

- Read-only public client.
- No private-key auth.
- No signing.
- No order placement.
- Safe for simulation/research mode.

Capabilities:

- `fetch_events()` -> Gamma events.
- `fetch_markets()` -> Gamma markets.
- `fetch_market()` -> one Gamma market.
- `fetch_book_top()` -> token-level CLOB top-of-book.
- `fetch_price()` -> CLOB price quote.
- `fetch_midpoint()` -> CLOB midpoint.
- `fetch_prices_history()` -> CLOB price history.
- `fetch_trades()` -> Data API trades.
- `fetch_positions()` -> Data API positions.
- `map_outcome_tokens()` maps Gamma outcomes to CLOB token IDs.
- `parse_clob_book_top()` normalizes bids/asks and sizes.

Example usage:

```python
from backend.data.polymarket_client import PolymarketClient, map_outcome_tokens

async with PolymarketClient() as pm:
    markets = await pm.fetch_markets(limit=5, closed=False)
    token_map = map_outcome_tokens(markets[0].get("outcomes"), markets[0].get("clobTokenIds"))
    yes = token_map.get("yes")
    if yes:
        top = await pm.fetch_book_top(yes.token_id)
        midpoint = await pm.fetch_midpoint(yes.token_id)
```

Current users:

- `backend/data/weather_markets.py`
- `backend/data/btc_markets.py`
- `backend/core/weather_exit_quotes.py`

### 7.3 pmxt

`requirements.txt` includes:

```txt
# Unified prediction-market SDK (optional integration layer)
pmxt==2.46.14
```

Current status:

- Installed in the repo venv: `pmxt==2.46.14`.
- Code search did not find active imports/usages in backend files.
- Treat `pmxt` as an optional, currently unused integration layer.

Open question:

- If Kayvon meant `pmxt` when saying “the open-source tool,” decide whether to actually evaluate/integrate it or remove it from dependencies. If he meant OctoBot, current approach is clean-room inspiration only.

---

## 8. Trade performance

### 8.1 Current all-weather ledger

From `tradingbot.db` after final reconciliation:

- Total weather paper trades: **22**.
- Settled: **22**.
- Open/pending: **0**.
- Closed early: **0**.
- Wins: **3**.
- Losses: **19**.
- Win rate: **13.64%**.
- Realized PnL: **-$709.18**.
- Weather equity from `$1,000` starting weather bankroll: **$290.82**.
- Remaining to `$1,100` target: **$809.18**.

### 8.2 Venue split

| Venue | Trades | Settled | Wins | Losses | Realized PnL |
|---|---:|---:|---:|---:|---:|
| Kalshi | 11 | 11 | 1 | 10 | -$665.43 |
| Polymarket | 11 | 11 | 2 | 9 | -$43.75 |

Interpretation:

- Kalshi is the biggest realized drag.
- Polymarket is close to breakeven only because of one large `+$550.00` Seoul win; otherwise it is also negative.
- Kalshi paper execution is correctly disabled until calibration improves.

### 8.3 Daily / platform breakdown

| Date | Venue | Trades | Wins | Losses | PnL |
|---|---|---:|---:|---:|---:|
| 2026-06-01 | Kalshi | 7 | 1 | 6 | -$365.43 |
| 2026-06-03 | Kalshi | 2 | 0 | 2 | -$150.00 |
| 2026-06-03 | Polymarket | 1 | 0 | 1 | -$75.00 |
| 2026-06-04 | Kalshi | 2 | 0 | 2 | -$150.00 |
| 2026-06-04 | Polymarket | 5 | 0 | 5 | -$375.00 |
| 2026-06-05 | Polymarket | 4 | 1 | 3 | -$143.75 |
| 2026-06-06 | Polymarket | 1 | 1 | 0 | +$550.00 |

### 8.4 Notable individual trades

Bad clusters:

- Many early Kalshi entries had model probability clipped to `95%` or `5%` and still lost.
- Multiple Polymarket Jun 4 and Jun 5 low/high bucket rows lost at fixed `$75` sizes.
- Several entries had huge apparent edge because the model was overconfident and/or market price was from a thin/stale/bucket context.

Largest current win:

- Trade 22, Polymarket `highest-temperature-in-seoul-on-june-6-2026`, YES @ `0.12`, size `$75`, result win, PnL `+$550.00`.

Settlement-repair examples:

- Trade 16, NYC Jun 4 low, was previously scored as a `+$2,702.78` win but was corrected to a `-$75.00` loss.
- Trade 12, Beijing Jun 4 high, corrected from win to loss.
- Trade 19, NYC Jun 5 low, corrected from pending to settled loss.
- Trade 22, Seoul Jun 6 high, corrected from pending to settled win.

This means any pre-2026-06-10 performance screenshots/reports should be treated as stale unless regenerated from the repaired DB.

### 8.5 Latest signals

Weather signal stats from `tradingbot.db`:

- Weather signal rows: **70,770**.
- Latest weather signal timestamp: `2026-06-14 03:03:49.634360` UTC.
- Latest signal minute: `2026-06-14 03:03`.
- Latest batch: **114 total / 0 actionable / 114 filtered / 0 executed**.
- Total executed weather signals in DB: **22**, matching the 22 paper trades.

Recent signal batches:

| Minute | Total | Actionable | Filtered | Executed |
|---|---:|---:|---:|---:|
| 2026-06-14 03:03 | 114 | 0 | 114 | 0 |
| 2026-06-10 03:15 | 93 | 5 | 88 | 0 |
| 2026-06-10 03:08 | 94 | 5 | 89 | 0 |
| 2026-06-10 03:03 | 94 | 5 | 89 | 0 |
| 2026-06-10 01:49 | 88 | 2 | 86 | 0 |

Interpretation: after the safety/calibration/source-state tightening, the system is mostly generating research-visible filtered rows rather than executing paper trades.

---

## 9. What we have learned

1. **Settlement correctness matters more than model edge.** A single wrong settlement join made the paper ledger look profitable when it was not.
2. **Polymarket weather slates are multi-market events.** Never resolve a trade by taking the first market in an event; always match exact market ID/condition ID.
3. **Uncalibrated ensemble probabilities are dangerous.** A 31-member ensemble can be unanimous for the wrong reason, especially near thresholds or when station/source mismatch exists.
4. **Station mapping is a product advantage.** Exact settlement stations for Kalshi are essential; broad city centroids are not good enough.
5. **International Polymarket weather has messy source evidence.** Wunderground/HKO rows can be partial, missing target dates, or anomalous versus neighbors.
6. **Kalshi paper execution should stay off for now.** Current Kalshi paper results are very poor.
7. **NO trades are especially easy to misprice if using derived YES math.** The code now correctly fetches held-side NO token books for Polymarket rather than assuming `1 - YES` provides executable liquidity.
8. **Dashboard/source-state visibility is improving.** Recent work makes Wunderground/HKO/source-state blockers visible with category filters, open/closed filters, and row-level neighbor values.
9. **Two-database architecture is useful but confusing.** App DB handles paper ledger; research DB handles snapshots/calibration. This should be documented and formalized.
10. **The repo needs commit hygiene.** The working tree is very dirty; Claude should inspect diffs before modifying broadly.

---

## 10. Architecture gaps and things I am still confused/concerned about

### 10.1 Dirty working tree / source of truth

`git status --short` shows many modified and untracked files across backend, frontend, tests, docs, scripts, and setup notes. It is unclear which changes are intended to be committed as a coherent unit versus experimental sprint work.

Recommendation:

- Before major refactors, create a checkpoint branch or commit the current known-good state after reviewing diffs.
- At minimum, run full backend and frontend build again before committing.

### 10.2 Scheduler starts during API tests/imports

FastAPI startup starts the scheduler, and TestClient smokes triggered BTC scan logs even when this audit wanted read-only endpoint checks and used `WEATHER_ENABLED=false`.

Recommendation:

- Add a setting such as `SCHEDULER_AUTOSTART=false` for tests/read-only API smokes.
- Separate app creation from bot/scheduler lifecycle.
- Ensure `/api/health`, `/api/stats`, `/api/dashboard`, `/api/*/status` can be smoke-tested with zero background jobs.

### 10.3 Weather calibration layer is planned but not implemented as a module

The plan `docs/plans/2026-06-07-weather-bot-reasoning-speed-audit.md` calls for `backend/core/weather_calibration.py`, but this file does not exist.

Recommendation:

- Implement probability shrinkage and calibration before any future paper entries.
- Prevent near-threshold unanimity from creating fake 95% model confidence.

### 10.4 Runtime scan caching/concurrency is partially planned but not built

The same plan calls for `backend/core/weather_scan_runtime.py`; this file does not exist. `fetch_ensemble_forecast()` has a global 15-minute cache, but scan-level concurrency and repeated provider fetch de-duplication need formalization.

Recommendation:

- Add per-scan forecast/source cache keyed by `(provider, city, target_date)`.
- Add bounded concurrency for market scans.
- Add benchmark script and p50/p95 scan timings.

### 10.5 API redaction issues

Potentially sensitive/private routes:

- `/api/kalshi/status` returns raw `balance_data`.
- `/api/polymarket/relayer/status` returns full relayer address.

Recommendation:

- Return only boolean/summarized/redacted status by default.
- Add explicit operator-only endpoint if detailed private account diagnostics are needed.

### 10.6 Polymarket relayer credentials are present but not validating

Current relayer smoke returned `validate_credentials=false`. This may be because credentials are wrong, relayer behavior changed, or the invalid `_ping` body is no longer accepted as an auth-validating request.

Recommendation:

- Keep relayer out of trading flows.
- Add a safer, documented status check if Polymarket provides one.
- Redact address in status output.

### 10.7 Kalshi works but is disabled for execution

Kalshi API is configured and reachable. The reason it is disabled is performance/risk, not connectivity.

Recommendation:

- Keep `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=false` until venue-specific calibration has enough evidence and results improve.
- Add a venue gate in dashboard copy that makes this explicit.

### 10.8 Source-state rows are not yet final outcome evidence

The latest Polymarket source-state pipeline is useful but still QA-only. HKO missing target-date rows and Seoul/RKSI warnings show this is not robust enough to drive trades.

Recommendation:

- Continue treating all source-state rows as `paper_actionable=false` until final-source and anomaly diagnostics pass.
- Focus on Seoul/RKSI and HKO missing-target fixes next.

### 10.9 pmxt is installed but unused

`pmxt==2.46.14` is installed, but no active code imports it.

Recommendation:

- Decide whether `pmxt` is a future integration or dependency drift.
- If future integration, create a separate read-only spike with tests.
- If not, remove to simplify supply chain.

### 10.10 Legacy BTC/RT code still exists under weather scope

The dashboard is weather-scoped, but BTC scheduler behavior still leaks into startup. Entertainment/BTC data still exist.

Recommendation:

- Add explicit lane enablement flags and test them.
- Do not rely only on extreme thresholds like `MIN_EDGE_THRESHOLD=999` to disable BTC.

---

## 11. Improvement roadmap for Claude

### Priority 0 — Safety and repo hygiene

1. Inspect `git status` and `git diff` before changes.
2. Add/verify `SCHEDULER_AUTOSTART=false` behavior for tests and read-only API smokes.
3. Redact `/api/kalshi/status` and `/api/polymarket/relayer/status` outputs.
4. Keep `SIMULATION_MODE=true`, `PAPER_AUTO_EXIT_ENABLED=false`, and `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=false` unless Kayvon explicitly says otherwise.

Acceptance checks:

- TestClient can call `/api/stats` and `/api/dashboard` without starting scheduler jobs.
- Status endpoints no longer emit raw balance payloads or full relayer address.
- Existing targeted weather/API/frontend tests still pass.

### Priority 1 — Reproducible audit and performance reporting

Some audit work exists in:

- `backend/core/weather_audit.py`
- `scripts/weather_audit_report.py`
- `tests/test_weather_audit.py`

Next steps:

1. Extend audit reporting with:
   - all-time metrics,
   - trailing 72h/7d/14d metrics,
   - by-venue and by-city splits,
   - outlier-adjusted metrics,
   - pre/post settlement repair notes,
   - calibration of model probability vs actual outcome.
2. Generate `docs/cron-context/weather-latest.md` from the audit script rather than hand-editing.
3. Add a stable JSON output for dashboard and cron use.

Acceptance checks:

- `python scripts/weather_audit_report.py --db tradingbot.db --window-hours 336 --format markdown` reproduces the reported ledger numbers.
- Report clearly separates headline PnL from outlier-adjusted PnL.
- Report never touches network or private accounts.

### Priority 2 — Probability calibration / anti-overconfidence

Create:

- `backend/core/weather_calibration.py`
- `tests/test_weather_calibration.py`

Needed behavior:

1. Shrink raw ensemble probabilities toward 50% based on:
   - distance from threshold,
   - ensemble spread,
   - source/station match quality,
   - venue/platform calibration history,
   - sample size,
   - recent Brier/log-loss.
2. Add special handling for bucket markets.
3. Add per-venue calibration so Kalshi and Polymarket do not share blind confidence.
4. Prevent clipped 95%/5% probabilities from being considered enough for actionability by themselves.

Acceptance checks:

- A 31/31 unanimous ensemble within a small threshold buffer does **not** produce an actionable 95% signal.
- Kalshi can remain monitor-only until settled evidence improves.

### Priority 3 — Final-source and station anomaly hardening

Focus files:

- `backend/core/weather_methodology.py`
- `backend/core/weather_paper_account.py`
- snapshot scripts in `/Users/kayvonai/.hermes/research/.snapshots/`
- API schemas and frontend source-state display.

Tasks:

1. Investigate Seoul/RKSI warning rows where primary source diverges from neighbors `[90.0, 91.0]` by around 9°F.
2. Re-query HKO Daily Extract after local-day completion for the 44 missing-target rows.
3. Add explicit source-state statuses for:
   - final source observed,
   - preliminary source only,
   - target date missing,
   - station anomaly warning,
   - missing neighbors,
   - unit conversion uncertainty.
4. Keep these rows QA-only until final-source and anomaly gates pass.

Acceptance checks:

- Source-state rows expose enough evidence for an operator to understand why they are blocked.
- No source-state improvement upgrades paper actionability without explicit gate changes and tests.

### Priority 4 — Scan runtime speed

Create:

- `backend/core/weather_scan_runtime.py`
- `scripts/benchmark_weather_scan.py`
- `tests/test_weather_scan_runtime.py`

Tasks:

1. Deduplicate forecast fetches per `(provider, city, target_date)` per scan.
2. Add bounded concurrency around market/source fetches.
3. Cache CLOB book reads where identical token IDs appear in the same scan.
4. Benchmark normal active market set and report p50/p95 per-market signal time.

Acceptance checks:

- Normal weather scan is under 20 seconds or at least 2x faster than baseline.
- Forecast fetch count is much smaller than market count when many lines share a city/date.

### Priority 5 — Product/dashboard improvements

Tasks:

1. Add a clear “why not trading” panel that aggregates top blockers by count.
2. Add venue badges: Kalshi monitor-only, Polymarket source-state-only, etc.
3. Add stable links from dashboard cards to source-state drilldowns.
4. Add strategy health view: calibration, Brier score, sample count, recent PnL, outlier-adjusted PnL.
5. Add a “paper execution readiness checklist” before enabling any lane.

### Priority 6 — Open-source tooling decisions

Tasks:

1. Decide whether OctoBot remains reference-only or becomes a separate sidecar research tool.
2. Decide whether `pmxt` should be used, spiked, or removed.
3. If borrowing from OctoBot, keep a clean-room boundary:
   - do not copy GPL code,
   - write our own tests and abstractions,
   - preserve simulation-only defaults.
4. Consider a paper-only copy-trading research lane inspired by OctoBot profile filters, but feed it into the review queue rather than auto-execution.

---

## 12. Questions for Kayvon / Claude to resolve

1. Do you mean **OctoBot** or **pmxt** when you say “the open-source tool we’re using”? Right now OctoBot is reference-only and pmxt is installed but unused.
2. Should we commit the current broad dirty working tree as a checkpoint before more changes, or should Claude separate it into logical commits?
3. Should status endpoints redact all private account data by default, even for local dashboard use? I recommend yes.
4. Should Kalshi remain fully monitor-only until it has a statistically meaningful positive calibration sample? I recommend yes.
5. Do we want a true live-trading path eventually, or should this stay paper/research until the product is robust? If live is desired, Polymarket authenticated CLOB fields are not ready.
6. What is the target product UX: operator dashboard for human approval, fully automated paper bot, or eventually live automated executor? The architecture should diverge based on this.
7. Should the weather account be separate from global `bot_state` bankroll forever? Current weather reports use `$1,000 -> $1,100`, while global bot state starts at `$10,000`; this can confuse dashboard/accounting.
8. Should source-state snapshots be promoted into the app DB, or remain in the research DB with read-only loaders?

---

## 13. Suggested prompt for Claude

Use the following as a Claude implementation prompt:

> You are working in `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot` on branch `main`. The active product scope is weather prediction markets only. Preserve simulation-only/no-forced-trade behavior. Do not expose secrets. Do not place live trades. Do not enable Kalshi paper execution or auto-exits without explicit authorization.
>
> First read `docs/plans/2026-06-15-weather-bot-current-state-claude-handoff.md`, `docs/cron-context/weather-latest.md`, `docs/cron-context/platform-latest.md`, and `docs/cron-context/weather-paper-settlement-repair-20260610T014508Z.md`.
>
> Current verified state: weather ledger has 22 settled trades, 3 wins, 19 losses, realized PnL -$709.18, Kalshi -$665.43, Polymarket -$43.75, no open positions. Latest weather signal batch has 114 filtered / 0 actionable / 0 executed. Polymarket public APIs work; Polymarket authenticated CLOB/order signing is incomplete; relayer credentials are present but validation is false; Kalshi API works but weather paper execution is disabled; Open-Meteo works; AIGEFS is disabled/unconfigured.
>
> Implement improvements in this order:
> 1. Add a test/read-only mode that prevents FastAPI TestClient startup from starting scheduler jobs.
> 2. Redact/summarize `/api/kalshi/status` and `/api/polymarket/relayer/status` outputs.
> 3. Extend `weather_audit.py` / `weather_audit_report.py` into a reproducible all-time + windowed performance/calibration report.
> 4. Implement `weather_calibration.py` to shrink raw ensemble probabilities and block overconfident near-threshold trades.
> 5. Improve source-state final-source handling for Seoul/RKSI warnings and HKO missing target dates, keeping all rows non-actionable until final gates pass.
> 6. Add scan runtime caching/concurrency and a benchmark script.
>
> Use TDD. Run focused tests first, then targeted weather/API/frontend-contract tests. Do not claim completion without fresh command output.
