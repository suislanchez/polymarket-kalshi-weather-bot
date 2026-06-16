# BTC lane latest handoff

_Last updated: 2026-06-03 12:05 PDT by daily BTC prediction-market bot buildout cron._

## Scope / safety
- Lane: BTC 5-minute Polymarket Up/Down markets and paper-only platform buildout.
- Safety: public/read-only market/source data only; no private exchange accounts, live orders, execution automation, authenticated Chainlink report fetches, or lowered safeguards.
- Paper ledger: separate BTC hypothetical account remains **$1,000 initial / $1,100 target** with selective/no-forced-trade behavior.

## Plan for this run
1. Read compact BTC cron context plus persistent research artifacts; inspect repo state/diff/test/API/dashboard/DB surfaces under simulation-only/no-forced-trade safeguards.
2. Re-query public Polymarket BTC 5-minute markets, token-level CLOB books, public spot context, and Chainlink report-request metadata; save raw/summary snapshots and normalize SQLite.
3. Make durable BTC methodology/platform progress by exposing newest-batch window-state coverage counts alongside source/auth blockers.
4. Verify focused RED/GREEN, targeted/full backend tests, frontend build, runner py_compile/live snapshot, live paper-only BTC scan, final DB reconciliation, and update artifacts/handoff.

## Completed work
- Ran public/read-only BTC snapshotter; authoritative run saved:
  - `/Users/kayvonai/.hermes/research/.snapshots/20260603T190424Z-btc-public-raw.json`
  - `/Users/kayvonai/.hermes/research/.snapshots/20260603T190424Z-btc-public-summary.json`
- Normalized authoritative run into `/Users/kayvonai/.hermes/research/prediction-market-edge-snapshots.sqlite`:
  - **16** BTC Up/Down quote rows in `market_quotes_v2`
  - **8** market-aligned Chainlink-boundary metadata rows in `btc_chainlink_boundary_v1`
  - **16** exact Chainlink Data Streams report-request rows in `btc_chainlink_report_request_v1`
  - **16** BTC scoring rows in `btc_outcome_scoring_v1`
- Added BTC window-state coverage observability:
  - `backend/core/btc_paper_account.py` now parses BTC window start timestamps from scoring rows / report-boundary timestamps / slug suffixes and summarizes newest-batch `unique_window_count`, active/upcoming/expired counts, and seconds-to-window-end range.
  - `backend/api/schemas.py` and `frontend/src/types.ts` expose the aggregate fields.
  - `frontend/src/App.tsx` BTC calibration audit panel displays compact `windows`, `active`, `upcoming`, and `expired` summary context.
  - This is observability only; all BTC calibration rows remain `paper_actionable=false`.
- Ran live paper-only BTC scan: **6 BTC signals / 0 actionable**. No BTC paper or live trade created.
- Updated playbook, research log, hypothesis tracker (`H083`), watchlist, and this compact handoff.

## Files changed this run
- Repo:
  - `backend/core/btc_paper_account.py`
  - `backend/api/schemas.py`
  - `frontend/src/types.ts`
  - `frontend/src/App.tsx`
  - `tests/test_btc_paper_account.py`
  - `tests/test_api_response_models.py`
  - `docs/cron-context/btc-latest.md`
- Research artifacts:
  - `/Users/kayvonai/.hermes/research/prediction-market-edge-playbook.md`
  - `/Users/kayvonai/.hermes/research/prediction-market-edge-research-log.md`
  - `/Users/kayvonai/.hermes/research/prediction-market-edge-hypothesis-tracker.md`
  - `/Users/kayvonai/.hermes/research/prediction-market-edge-watchlist.md`
  - `/Users/kayvonai/.hermes/research/.snapshots/20260603T190424Z-btc-public-raw.json`
  - `/Users/kayvonai/.hermes/research/.snapshots/20260603T190424Z-btc-public-summary.json`
  - `/Users/kayvonai/.hermes/research/prediction-market-edge-snapshots.sqlite`

## Evidence / source snapshot
- Re-queried current Polymarket BTC 5-minute windows at **20260603T190424Z**.
- Snapshot captured **8** current/upcoming `btc-updown-5m-*` events and **16** token-level Up/Down CLOB books; no errored rows.
- Examples:
  - `btc-updown-5m-1780513200`: Up **20/21¢** top ask size **339.67**; Down **79/80¢** size **3,630.26**.
  - `btc-updown-5m-1780513500`: Up **50/51¢** size **588.98**; Down **49/50¢** size **705.55**.
  - `btc-updown-5m-1780513800`: Up **50/51¢** size **369.14**; Down **49/50¢** size **1,485.12**.
- Public spot context: Coinbase **$65,908.545** and Binance US **$65,958.16**; model context only, not settlement evidence.
- Chainlink source/request evidence:
  - Settlement/source URL: `https://data.chain.link/streams/btc-usd`.
  - Feed id: `0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8`.
  - Newest report-request rows store exact URLs like `https://api.dataengine.chain.link/api/v1/reports?feedID=<feed>&timestamp=<window_start_or_end>` with `requires_authentication=1`, `status=auth_required_not_fetched`, and loader/API-visible boundary timestamps (example **1780513200 → 1780513500**).
- Latest BTC calibration/scoring state: **16** newest scoring rows, **16 pending**, **0 settled forecasts**, **0 exact boundary rows**, **16 auth-required report requests**, **16** rows with line-book spread, **16** rows with top ask size, **0** rows with independent model probability, **16** rows with exchange-spot model context, **16** source-mismatch rows, **16** Chainlink-auth-blocked rows, **8 unique windows**, **1 active**, **7 upcoming**, **0 expired**, seconds-to-window-end **36–2,136**, max spread **1¢**, min top ask **339.67**, Brier/log-loss null, `paper_actionable=false`, source snapshot `/Users/kayvonai/.hermes/research/.snapshots/20260603T190424Z-btc-public-raw.json`.
- API smoke loaded **16** newest BTC detail rows; first row preserved `paper_actionable=false` and exposed structured no-trade reasons: missing exact Chainlink boundary values, missing independent BTC model probability, pending outcome, exchange-spot-vs-Chainlink source mismatch, and Chainlink auth-required report requests.

## Current BTC paper account state
- Equity: **$1,000**
- Target: **$1,100**
- Realized PnL: **$0**
- Remaining to target: **$100**
- Progress: **0%**
- Settled BTC trades: **0**
- Pending BTC trades: **0**
- Settled forecasts: **0**
- Brier/log-loss: **null / not available yet** because no settled BTC forecast rows exist.
- Behavior: **simulation-only, selective no-forced-trade**.

## Verification run
- Runner syntax/live snapshot: `python3 -m py_compile /Users/kayvonai/.hermes/research/.snapshots/btc_sprint_public_snapshot.py && python3 /Users/kayvonai/.hermes/research/.snapshots/btc_sprint_public_snapshot.py` -> passed/completed.
- RED focused BTC/API tests failed first with missing `unique_window_count` / frontend contract fields.
- Focused BTC/API tests: `PYTHONPATH=. venv/bin/python -m pytest -q tests/test_btc_paper_account.py::test_latest_btc_calibration_summary_uses_latest_batch_and_counts_pending_rows tests/test_api_response_models.py::test_btc_calibration_summary_schema_preserves_window_state_counts tests/test_api_response_models.py::test_frontend_btc_calibration_contract_renders_window_state_counts` -> **3 passed**.
- Targeted BTC/API tests: `PYTHONPATH=. venv/bin/python -m pytest -q tests/test_btc_paper_account.py tests/test_btc_methodology.py tests/test_btc_market_parsing.py tests/test_api_response_models.py` -> **40 passed**.
- Full backend: `PYTHONPATH=. venv/bin/python -m pytest -q` -> **170 passed**, existing warnings only.
- Frontend: `npm run build` in `frontend/` -> passed, existing large-chunk warnings.
- Live paper-only BTC scan via repo venv: **6 signals / 0 actionable**; no BTC trade created (`0` before/after).
- API smoke: `_load_latest_btc_calibration_summary()` returned **16** scoring rows, `unique_window_count=8`, `active_window_count=1`, `upcoming_window_count=7`, `expired_window_count=0`, `min_seconds_to_window_end=36`, `max_seconds_to_window_end=2136`, `line_book_rows=16`, `top_ask_size_rows=16`, `model_probability_rows=0`, `exchange_spot_model_rows=16`, `source_mismatch_rows=16`, `chainlink_auth_blocked_rows=16`, `auth_required_report_requests=16`, `max_execution_spread=0.01`, `min_signal_top_ask_size=339.67`; `_load_latest_btc_calibration_rows(limit=16)` loaded **16** detail rows and all rows remained `paper_actionable=false`.
- Research DB point-in-time: `market_quotes_v2=18224`, `raw_snapshots_v2=143`, `outcome_resolutions=166`, `weather_forecast_calibrations=12369`, `weather_bot_signal_calibrations=734`, `weather_signal_review_candidates=857`, `polymarket_weather_source_states=2112`, `btc_chainlink_boundary_v1=128`, `btc_chainlink_report_request_v1=160`, `btc_outcome_scoring_v1=256`.
- App DB point-in-time: `trades=10` total (**8 weather settled, 2 weather pending, 0 BTC trades**), settled weather PnL **-$440.43**, pending weather size **$150**, `signals=36982`, `btc_price_snapshots=34718`, `rotten_tomatoes_source_states=237`.

## Open blockers / risks
- Exact Chainlink start/end Data Streams report collector is still missing; request rows, boundary timestamps, and window-state counts are audit metadata only, not decoded report values or boundary evidence.
- Chainlink Data Streams production REST API requires authenticated headers; do not fetch/decode reports with private credentials unless explicitly authorized as public/read-only research-only access.
- Current BTC model inputs remain exchange spot context, so rows continue to fail Coinbase/spot-vs-Chainlink settlement-source alignment.
- Latest scoring batch has **0** independent model-probability rows; Brier/log-loss remain null and no alpha should be inferred.
- Window-state aggregates improve freshness/auditability but are not alpha validation or an actionability upgrade.
- No validated BTC alpha, no BTC paper trade, no live trade.

## Recommended next tasks
1. If a safe public/read-only authenticated Chainlink Data Streams path exists, implement a side-effect-free report fetcher/decoder with tests, raw source snapshots, feed id, observation timestamp, and exact boundary value validation.
2. Add independent BTC model-probability persistence only after the forecast source is explicitly labeled and not confused with Chainlink settlement evidence.
3. Use summary window-state/depth/source/auth fields plus row-level spread/top ask size to add CLV/liquidity QA once exact Chainlink boundaries/outcomes exist.
4. Keep the $1,000 BTC paper account separate and report no-forced-trade state when no row passes all gates.
