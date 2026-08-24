# Hermes local setup notes

Last updated: 2026-05-25 02:04 PDT

Repository
- Upstream: https://github.com/suislanchez/polymarket-kalshi-weather-bot
- Local path: /Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot
- Checked out commit: e406394 Add dashboard screenshot to README, update project structure

Safety posture
- This local setup is paper/simulation only.
- No Kalshi credentials or Polymarket private credentials were configured.
- `.env` intentionally sets:
  - `SIMULATION_MODE=true`
  - `KALSHI_ENABLED=false`
  - `WEATHER_ENABLED=false`
  - `MIN_EDGE_THRESHOLD=999`
- The high edge threshold is deliberate for setup validation: the scheduler can fetch/read market data but should not create paper trades automatically during initial evaluation.

Backend setup
- Python used: /Users/kayvonai/.local/bin/python3.12
- Virtualenv: /Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot/venv
- Dependencies installed with `pip install -r requirements.txt`.
- Import smoke test passed for `backend.api.main:app`.
- Backend server command:

```bash
cd /Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot
source venv/bin/activate
uvicorn backend.api.main:app --port 8000
```

Frontend setup
- Node: v22.22.2
- npm: 10.9.7
- Dependencies installed with `npm install` in `frontend/`.
- Production build passed with `npm run build`.
- Frontend dev server command:

```bash
cd /Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot/frontend
npm run dev -- --host 127.0.0.1 --port 5173
```

Validated locally
- Backend listened on 127.0.0.1:8000.
- Frontend listened on 127.0.0.1:5173.
- Browser loaded http://127.0.0.1:5173 and displayed the Trading Terminal dashboard.
- Dashboard connected to backend WebSocket/log stream.
- Backend fetched live Polymarket BTC 5-minute markets and Coinbase BTC candles.
- With current guardrail threshold, logs showed 6 signals and 0 actionable trades.
- 2026-05-19 buildout added separate BTC and RT/entertainment $1,000→$1,100 paper-ledger summaries in the API/dashboard; local DB still has 0 trades, so both remain at $1,000 equity.
- 2026-05-19 weather buildout added settlement-source/depth no-trade gates and a Kalshi `orderbook_fp` top-of-book parser that handles both cent (`yes`/`no`) and dollar (`yes_dollars`/`no_dollars`) ladders, including 1¢ cent-ladder edge cases. Targeted tests (`4 passed`) and full pytest (`13 passed`) passed.
- 2026-05-20 RT/entertainment sprint found active Star Wars and I Love Boosters RT markets plus Mandalorian 4-day box-office buckets; direct Star Wars RT source was 60% on 129 reviews, but key RT CLOB lines were wide/shallow, so no paper trade was created. Added side-effect-free RT/entertainment Brier/log-loss scoring helper; full `python3 -m pytest tests` and frontend `npm run build` passed.
- 2026-05-20 evening platform sprint exposed structured weather no-trade/depth fields end-to-end: `WeatherGateResult` now carries execution spread and top ask size, weather signals/API responses expose `no_trade_reasons`, `execution_spread`, and `top_ask_size`, and the dashboard SignalsTable shows gate/depth details in expanded rows. Full `python -m pytest -q` passed (`25 passed`); frontend `npm run build` passed with the existing chunk-size warning.
- 2026-05-21 BTC sprint added tested BTC price-source persistence: `persist_btc_price_snapshot` records the exchange/source BTC microstructure price used during signal generation, and `generate_btc_signal` calls it after microstructure fetch. Public BTC 5-minute CLOB refresh showed mostly 1¢ spreads but uneven depth and one near-expiry collapsed row; no paper trades were created. Full `PYTHONPATH=. python3 -m pytest -q` passed (`26 passed`); frontend `npm run build` passed. Live scanner import from the cron Python env is blocked by missing SQLAlchemy, so `btc_price_snapshots` remains empty until app deps are available.
- 2026-05-21 weather sprint broadened weather parser coverage for Seattle/Boston and common Polymarket international cities, added Celsius threshold parsing/conversion to Fahrenheit, and added targeted coverage for a London `24°C` title. Public weather snapshots were normalized to SQLite (`market_quotes_v2=5376`, `raw_snapshots_v2=56`, `outcome_resolutions=21` point-in-time). No paper trades were created; weather account remains $1,000 equity / $1,100 target. The cron venv currently lacks pytest, so direct assertions and `py_compile` passed instead of the normal pytest command.
- 2026-05-23 weather sprint added Wunderground rule-source URL extraction and airport station-name parsing for Polymarket weather rules (e.g. Hartsfield-Jackson/KATL), carries `settlement_source_url` through `WeatherMarket`, and includes `settlement_url:*` in weather signal sources. Public/read-only refresh captured 84 Kalshi rows and 220 Polymarket weather rows; research SQLite point-in-time counts are quotes 6,097 / raw snapshots 63 / outcomes 21. Direct venv assertions, `py_compile`, and frontend `npm run build` passed; pytest is still absent from available Python envs. Weather paper account remains $1,000 equity / $1,100 target / 0 trades.

- 2026-05-21 20:07 flexible platform sprint added normalized RT source-state persistence: `persist_rotten_tomatoes_source_snapshot` in `backend/core/entertainment_signals.py`, `RottenTomatoesSourceState` in `backend/models/database.py`, and fake-DB tests in `tests/test_entertainment_account_and_gates.py`. `venv/bin/python` `init_db()` created `rotten_tomatoes_source_states` in `tradingbot.db`; verified counts are trades 0, signals 13734, BTC snapshots 96, RT source states 0. Targeted tests passed (`8 passed`), full pytest passed (`30 passed`, existing Pydantic warning), and frontend `npm run build` passed with the existing chunk-size warning. BTC/weather/RT ledgers all remain $1,000 equity / $1,100 target / 0 trades; no paper action was created.

- 2026-05-23 20:10 flexible platform sprint added a read-only cross-vertical Signal Review Queue. `backend/core/signal_review.py` summarizes blocked BTC/weather/RT candidates by vertical, top blocker, priority, edge, and no-trade reasons; `/api/dashboard` now includes `signal_review_queue`; frontend types and `App.tsx` render a no-execution review panel. Added `tests/test_signal_review_queue.py`. Verification: `PYTHONPATH=. python3 -m pytest -q` passed (`38 passed`, existing Pydantic warning) and frontend `npm run build` passed with the existing Vite chunk-size warning. Venv still lacks pytest (`venv/bin/python -m pytest` reports `No module named pytest`). BTC/weather/RT ledgers remain $1,000 equity / $1,100 target / 0 trades.

- 2026-05-25 BTC sprint tightened Chainlink boundary methodology. `backend/core/btc_methodology.py` now defines `CHAINLINK_BTC_USD_FEED_ID` and `BtcChainlinkBoundarySnapshot`, and `evaluate_btc_no_trade_gate` requires exact boundary prices plus observation timestamps, feed id, and capture method before a Chainlink-labeled BTC 5m row can pass. `/Users/kayvonai/.hermes/research/.snapshots/btc_sprint_public_snapshot.py` now records Chainlink feed context while explicitly marking boundary reports missing. Verification: BTC targeted pytest passed (`11 passed`), full `PYTHONPATH=. python3 -m pytest -q` passed (`53 passed`, existing Pydantic warning), and a live paper-only venv scan returned 6 BTC signals / 0 actionable. App DB remains `trades=0`; BTC ledger remains $1,000 equity / $1,100 target / 0 trades.
- 2026-05-26 BTC sprint tightened boundary evidence further: `BtcChainlinkBoundarySnapshot` now preserves `source_snapshot_path`, `validate_chainlink_boundary_snapshot(...)` requires raw source path plus price/timestamp/feed/method, and the no-trade gate can reject boundary evidence whose observed timestamp does not match the expected market start/end unix boundary. Public BTC refresh normalized 16 rows at `20260526T090140Z`; focused BTC pytest passed (`15 passed`), full backend passed (`59 passed`, 1 skipped), frontend build passed, and live paper scan remained 6 signals / 0 actionable.
- 2026-05-27 12:05 BTC sprint corrected the BTC Polymarket slug-boundary convention after fresh Gamma/CLOB data showed `btc-updown-5m-{unix}` suffix equals the **window start** and `endDate` is five minutes later, not `unix_end`. Updated `backend/data/btc_markets.py`, the public BTC snapshot runner, API schemas/main, frontend types, and tests to expose `window_start_ts`/`window_end_ts` using the start-based convention. Public snapshot `20260527T190534Z` captured 8 windows / 16 books; live paper-only BTC scan still returned 6 signals / 0 actionable. Focused BTC/API tests passed (`17 passed`), full backend passed (`72 passed`), frontend build passed.

Known caveats / early observations
- README says Python 3.10+; macOS system python was 3.9.6, so Python 3.12 was used.
- Startup currently forces `BotState.is_running=True` and starts scheduler immediately. This is acceptable for paper-mode exploration but should be changed before any real-credential experiments.
- The backend emits a Pydantic warning: `model_probability` conflicts with protected namespace `model_`. It does not block startup.
- `npm install` reported 15 vulnerabilities: 5 moderate, 10 high. Do not run `npm audit fix --force` casually; review dependency impact first.
- Vite build warns that some chunks are >500 KB, mostly Globe/3D visualization code.
- Current strategy stores simulated trades in SQLite; I found no live order-placement code in backend execution paths during setup inspection.

Recommended next runs
1. Keep this repo isolated from our existing prediction-market research store until we understand data schemas.
2. Add a real paper-trading/evaluation mode that never starts scans/trades on import/startup unless explicitly enabled.
3. Add tests around:
   - Kalshi KXHIGH ticker discovery and orderbook parsing.
   - Polymarket BTC 5-minute market parsing.
   - Weather-market source/station mapping.
   - Kelly sizing limits.
4. Compare this bot's weather probability model against our existing lessons:
   - station/source mapping is mandatory;
   - exact settlement source/rules matter;
   - point forecasts alone are not enough;
   - CLOB depth/liquidity must gate any paper edge.
5. Run a paper-only backtest or snapshot logger before considering any live-credential flow.
