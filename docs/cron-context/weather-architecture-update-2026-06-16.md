# Weather bot architecture update for paused Hermes crons

Created: 2026-06-16
Scope: A cron-context architecture-update note for the two paused OpenAI Codex-backed weather/platform cron jobs (`222c5a493033` and `1e2966872a8d`) and whoever resumes them. The codebase changed materially while these jobs were paused. Read this before resuming so the scheduled agents do not operate from stale pre-pause assumptions. Simulation/paper only — nothing here authorizes live trading.

This file: `docs/cron-context/weather-architecture-update-2026-06-16.md`

---

## Orientation

- Repo: `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot`
- Branch: `weather-bot-hardening-2026-06-16`
- Commit: `3cb8a68` (checkpoint: weather-only buildout + session hardening)
- Prior comprehensive handoff: `docs/plans/2026-06-15-weather-bot-current-state-claude-handoff.md`

The hardening below shipped after the pause snapshot recorded in `docs/cron-context/weather-platform-cron-pause-reactivation-handoff.md`. That handoff captured the repo on branch `main`, HEAD `e406394`, with a broadly dirty tree. This work was committed together on `weather-bot-hardening-2026-06-16` (`3cb8a68`) because main HEAD had no clean commit boundary. The commit deliberately excludes `.env` (secrets), `*.db` (local ledger), `HERMES_SETUP_NOTES.md`, and unrelated `.firecrawl/` data.

Verification status at this commit: full backend suite **270 passed**; frontend builds clean.

---

## What changed since the pause

Five hardening workstreams shipped. Each introduced or relies on config flags the crons must now respect.

### 1. Scheduler / lane safety flags — `backend/config.py`, `backend/core/scheduler.py`, `backend/api/main.py`

- **`SCHEDULER_AUTOSTART`** (bool, default `True`). When false, FastAPI startup and any `TestClient` construct the app **without** launching the background scan/settlement/heartbeat jobs. Read-only API smokes must set this false.
- **`BTC_LANE_ENABLED`** (bool, default `False`). The canonical BTC 5-minute off-switch, replacing the old `MIN_EDGE_THRESHOLD=999` hack (the real `MIN_EDGE_THRESHOLD` is now back to its normal `0.02`).
- `backend/core/scheduler.py` added `planned_scheduler_jobs()` — a pure, unit-testable lane plan. `start_scheduler()` only registers/fires the BTC `market_scan` job when `BTC_LANE_ENABLED`; `settlement_check` and `heartbeat` always run so existing pending paper trades still settle; `open_position_risk` runs when `PAPER_POSITION_RISK_ENABLED` (default `True`); `weather_scan` runs only when `WEATHER_ENABLED`.
- `backend/api/main.py` added `_maybe_start_scheduler()`, which respects `SCHEDULER_AUTOSTART`; `startup()` calls it. Verified: a `TestClient` with `SCHEDULER_AUTOSTART=false` leaves `is_scheduler_running()==False` and creates no trades.
- Tests: `tests/test_scheduler_autostart.py`.

### 2. Status-endpoint redaction — `backend/api/main.py`

- Helpers `_redact_address()` and `_summarize_account_balance()`.
- `/api/kalshi/status` now returns `{connected, balance_available}` — no raw balance/cents.
- `/api/polymarket/relayer/status` now returns `{configured, connected, address_present, address_preview}` — a shortened address preview only, never the full address.
- Tests: `tests/test_status_endpoint_redaction.py`.

### 3. Probability calibration / anti-overconfidence — `backend/core/weather_calibration.py` (NEW)

- `calibrate_weather_probability()` re-estimates P(YES) with a variance-inflated Gaussian (using `normal_cdf`): a per-member std floor (`WEATHER_CALIBRATION_MIN_STD_F=1.5`), underdispersion inflation (`WEATHER_CALIBRATION_STD_INFLATION=1.5`), observation noise added in quadrature for an inexact source, member-count widening, and shrinkage toward 0.5 for degraded inputs.
- The `confident` flag requires the threshold to be at least `WEATHER_CALIBRATION_MIN_CONFIDENT_Z` (`1.0`) inflated sigmas from the ensemble mean, with at least `WEATHER_CALIBRATION_MIN_MEMBERS` (`20`) members **and** an exact source.
- `reliability_weight_from_brier()` helper exists for future per-venue calibration. `config_from_settings()` reads the `WEATHER_CALIBRATION_*` keys. `WEATHER_CALIBRATION_ENABLED` defaults `True`.
- Wired into `generate_weather_signal()` in `backend/core/weather_signals.py`: it replaces the naive `[0.05, 0.95]` clip (now kept only as a fallback when calibration is disabled), adds a "calibration not confident" no-trade reason (which zeroes edge and size) for above/below markets, and appends a `calibration:` source tag. `generate_weather_signal` now accepts a `forecast=` injection.
- Tests: `tests/test_weather_calibration.py`, `tests/test_weather_signal_calibration_integration.py`.

### 4. Reproducible audit + calibration reporting — `backend/core/weather_audit.py` + `scripts/weather_audit_report.py`

- All-time summary, trailing windows (72h/7d/14d), by-city splits (`derive_city_label` heuristic: Polymarket slug `temperature-in-<city>-on-`; Kalshi tickers `KXHIGH<station>` / `KXLOWT<station>`), and probability calibration (`summarize_probability_calibration` → Brier + reliability bins; `trade_win_probability` orients to the held side).
- Markdown and JSON (`--format json`) output. Read-only: `connect_sqlite` opens with `PRAGMA query_only = ON` and never creates a missing DB.
- Reproduces the ledger exactly: 336h strict window = 15 trades, 2W/13L, -343.75 USD; all-time = 22 trades, 3W/19L, -709.18 USD; weather equity 290.82 USD from a 1000 USD start.
- Tests: `tests/test_weather_audit.py`.

### 5. Scan runtime — `backend/core/weather_scan_runtime.py` (NEW) + `scripts/benchmark_weather_scan.py` (NEW)

- `prefetch_forecasts()` does one forecast fetch per unique `(city, target_date)` under bounded concurrency. `map_concurrently()` runs bounded-concurrency signal generation while preserving order. `ScanRuntimeStats` and `forecast_keys()` support reporting.
- **`WEATHER_SCAN_CONCURRENCY`** (default `8`). Wired into `scan_for_weather_signals` — prefetch, then concurrent generate with the forecast injected into `generate_weather_signal`.
- Synthetic benchmark (no network/DB): 120 markets across 12 cities → 12 forecast fetches (10x dedup) plus a large concurrency speedup. The numbers are synthetic; real speedup is lower but the dedup is real.
- Tests: `tests/test_weather_scan_runtime.py`.

---

## New invariants the crons must honor

1. **Calibration confidence gate is now load-bearing.** A clipped 95% unanimity can no longer, by itself, drive a trade. For above/below markets, `generate_weather_signal` zeroes edge and size and records a "calibration not confident" no-trade reason unless the threshold sits at least `WEATHER_CALIBRATION_MIN_CONFIDENT_Z` inflated sigmas from the mean with at least `WEATHER_CALIBRATION_MIN_MEMBERS` members and an exact source. Do not work around this gate.
2. **Status endpoints are redacted by default — keep them so.** `/api/kalshi/status` and `/api/polymarket/relayer/status` must not be reverted to expose raw balances or full addresses.
3. **The BTC 5-minute lane is off by flag.** `BTC_LANE_ENABLED` defaults `False` and is the canonical off-switch. Do not re-enable BTC scanning; do not resurrect the `MIN_EDGE_THRESHOLD=999` hack.
4. **Scheduler autostart must be off for smokes.** Any read-only API smoke (e.g. a FastAPI `TestClient`) must set `SCHEDULER_AUTOSTART=false` so no background scan/settlement/heartbeat jobs start and no trades are created.

---

## Key calibration finding and what it implies

Run on the real ledger, the new calibration section of the audit shows **Brier 0.7326**, a mean predicted held-side win probability of **0.908** against an empirical win rate of **0.136**. 21 of 22 trades carried a predicted win probability of 80–100% and won about 14%. The losses were systematic model overconfidence near thresholds — exactly what the calibration layer now targets.

Implication for any future actionability decision: do not treat a high model probability as evidence on its own. The honest, calibrated probability and its `confident` flag are the gate. Until calibrated evidence accumulates that the model is well-calibrated, any move toward actionability or a paper-execution sample is premature. There is an explicit open question for Kayvon — whether to re-enable a small Kalshi paper sample now that calibration honestly gates overconfidence, or to stay monitor-only — and it was left **monitor-only** per the safety rules. Crons must not resolve that question autonomously.

---

## Safety gates (restated, non-negotiable)

- **Weather prediction markets only.** BTC and entertainment/Rotten Tomatoes are legacy/paused.
- **Simulation/paper only.** `SIMULATION_MODE=true`. No live trades, no order placement, no private-account or exchange actions.
- Keep `PAPER_AUTO_EXIT_ENABLED=false` and `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=false` unless Kayvon explicitly authorizes otherwise.
- **Never expose secrets.** Status endpoints are redacted by default; keep them redacted.
- **All source-state/drilldown rows stay `paper_actionable=false`** until every final-source/model/liquidity/sizing/risk gate independently passes.
- Do not infer live-trading authorization from "kick things back up" — that means resume scheduled research/buildout only.

---

## Verification commands (read-only, no trades)

- Full backend tests: `PYTHONPATH=. ./venv/bin/python -m pytest -q` (270 passed)
- Audit report: `PYTHONPATH=. ./venv/bin/python scripts/weather_audit_report.py --db tradingbot.db --window-hours 336 --format markdown`
- Audit JSON: same with `--format json`
- Scan benchmark: `PYTHONPATH=. ./venv/bin/python scripts/benchmark_weather_scan.py`
- Frontend: `(cd frontend && npm run build)`
- Read-only API smoke: construct a FastAPI `TestClient` with env `SCHEDULER_AUTOSTART=false` (no background jobs start).

---

## Resume checklist hook

**Before resuming cron jobs `222c5a493033` (weather methodology + dashboard) and `1e2966872a8d` (platform / paper trading / tech debt):**

1. Complete the full re-review checklist in `docs/cron-context/weather-platform-cron-pause-reactivation-handoff.md`. Both jobs' `last_status` was `error` (no Codex credentials), so confirm credential health before any resume/run rather than burning retries.
2. Update each cron's prompt and lane handoff to this new architecture so they start from the post-hardening state, not stale pre-pause assumptions — specifically the calibration confidence gate, the redacted status endpoints, `BTC_LANE_ENABLED=False`, and `SCHEDULER_AUTOSTART=false` for smokes.
3. Resume one job at a time per the reactivation plan: weather (`222c5a493033`) as canary first, then platform (`1e2966872a8d`) after the weather lane state is known-good. Preserve original schedules (`0 8,18 * * *` and `0 6,20 * * *`) unless Kayvon asks otherwise.

Do not resume until the re-review is complete and the prompts/handoffs are updated.

---

## Remaining roadmap (NOT done this session)

- **P3 source-state hardening:** Seoul/RKSI anomaly-warning rows (primary source vs neighbors `[90.0, 91.0]`, max delta ~9F) and HKO missing-target-date rows; add explicit source-state statuses; keep all rows `paper_actionable=false` until final gates pass.
- **P5 dashboard:** a "why not trading" blocker-aggregation panel; venue badges (Kalshi monitor-only); a strategy-health view (now that Brier/calibration data exists); a paper-execution readiness checklist.
- **P6 open-source tooling:** decide OctoBot (reference-only) vs pmxt (installed, unused) — spike or remove.
- **Per-venue calibration:** feed `reliability_weight_from_brier()` from the audit's by-venue Brier into `calibrate_weather_probability(venue_reliability=...)`.

---

## Pointers

- Cron pause + re-review checklist (the gating doc): `docs/cron-context/weather-platform-cron-pause-reactivation-handoff.md`
- Full background handoff: `docs/plans/2026-06-15-weather-bot-current-state-claude-handoff.md`
- Settlement bug repair: `docs/cron-context/weather-paper-settlement-repair-20260610T014508Z.md`
- Lane handoff and index: `docs/cron-context/weather-latest.md`, `docs/cron-context/INDEX.md`
