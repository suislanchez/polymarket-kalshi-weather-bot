# Weather Bot Hardening — Continuation Prompt (2026-06-16)

> **Target file:** `docs/plans/2026-06-16-weather-bot-hardening-prompt.md`
> **Audience:** the next agent session (Claude or Hermes/Codex) continuing this work.

---

> **You are continuing work on a weather prediction-market PAPER-TRADING bot.** Repo: `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot`. Branch: `weather-bot-hardening-2026-06-16` (checkpoint commit `3cb8a68`).
>
> **SCOPE & SAFETY (non-negotiable):**
> - **Weather prediction markets only.** BTC 5-min and entertainment/Rotten-Tomatoes lanes are legacy/paused — do not extend them.
> - **Simulation/paper only.** `SIMULATION_MODE=true` in `backend/config.py`. Never place a live trade, submit an order, or take any private-account action.
> - Keep `PAPER_AUTO_EXIT_ENABLED=false` and `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=false` (both default `false` in `backend/config.py`) **unless Kayvon explicitly authorizes** flipping them. Same for `BTC_LANE_ENABLED` (stays `false`) and any execution gate.
> - **Never expose secrets.** Status endpoints (`/api/kalshi/status`, `/api/polymarket/relayer/status` in `backend/api/main.py`) are redacted by default via `_redact_address()` and `_summarize_account_balance()`. Keep them redacted; never return raw balances/cents or full addresses.
> - **Every source-state / drilldown row stays `paper_actionable=false`** until every final-source, model-confidence, liquidity, sizing, and risk gate independently passes. Do not relax this default.
> - Read-only API smokes must construct the FastAPI `TestClient` with env `SCHEDULER_AUTOSTART=false` so no background scan/settlement/heartbeat jobs start and no trades are created.
>
> **CURRENT VERIFIED STATE (one paragraph).** The full backend suite passes (270 passed) and the frontend builds clean. This session shipped, via TDD: scheduler/lane safety flags (`SCHEDULER_AUTOSTART`, `BTC_LANE_ENABLED`, `planned_scheduler_jobs()` in `backend/core/scheduler.py`); status-endpoint redaction; an anti-overconfidence probability calibration layer (`backend/core/weather_calibration.py`, wired into `generate_weather_signal()`); a reproducible read-only audit (`backend/core/weather_audit.py` + `scripts/weather_audit_report.py`); and a deduped/concurrent scan runtime (`backend/core/weather_scan_runtime.py` + `scripts/benchmark_weather_scan.py`). The audit reproduces the ledger exactly: 336h strict window = 15 trades, 2W/13L, −343.75 USD; all-time = 22 trades, 3W/19L, −709.18 USD; weather equity 290.82 USD from a 1000 USD start. **Key finding:** the new calibration section of the audit shows Brier 0.7326 with a mean predicted held-side win probability of 0.908 vs an empirical win rate of 0.136 — 21 of 22 trades predicted 80–100% and won ~14%. The losses were systematic model overconfidence near temperature thresholds, which is exactly what `calibrate_weather_probability()` now gates (it adds a `"calibration not confident"` no-trade reason that zeroes edge and size for above/below markets).
>
> **READ FIRST (in this order):**
> 1. `docs/plans/2026-06-15-weather-bot-current-state-claude-handoff.md` — full prior background.
> 2. `docs/cron-context/weather-platform-cron-pause-reactivation-handoff.md` — the two paused Codex cron jobs (`222c5a493033` weather methodology+dashboard; `1e2966872a8d` platform/paper/tech-debt), both `last_status=error` (no Codex credentials), and the re-review checklist required before any resume. The architecture changed materially while they were paused, so their prompts/handoffs must be updated before resuming.
> 3. `docs/cron-context/weather-paper-settlement-repair-20260610T014508Z.md` — the settlement-bug repair.
> 4. `docs/cron-context/weather-latest.md` and `docs/cron-context/INDEX.md` — cron lane index/state.
>
> **PRIORITIZED TASKS (remaining roadmap):**
>
> 1. **P3 — Source-state hardening.** Add explicit source-state statuses for the two known degraded cases and keep their rows non-actionable:
>    - Seoul/`RKSI` anomaly-warning rows where the primary source diverges from neighbors (`[90.0, 91.0]`, max delta ~9°F).
>    - HKO missing-target-date rows.
>    - *Acceptance:* `generate_weather_signal()` emits a distinct source-state `no_trade_reason` for each case; affected rows remain `paper_actionable=false`; new tests cover both. (Note: no `RKSI`/`HKO`/source-state status exists in `backend/core/weather_signals.py` today — this is greenfield.)
>
> 2. **Per-venue calibration.** Feed `reliability_weight_from_brier()` (already in `backend/core/weather_calibration.py`) from the audit's by-venue Brier into `calibrate_weather_probability(venue_reliability=...)`.
>    - *Acceptance:* `backend/core/weather_audit.py` exposes a by-venue Brier split (today it has `by_city` but **no** `by_venue` — add it); the venue reliability weight flows into the calibrator; a test asserts a worse-Brier venue produces a lower `venue_reliability` and more shrinkage toward 0.5.
>
> 3. **P5 — Dashboard.** Surface the data the calibration/audit work now produces:
>    - a "why not trading" blocker-aggregation panel (aggregate `no_trade_reasons`),
>    - venue badges (Kalshi = monitor-only),
>    - a strategy-health view backed by Brier/calibration data,
>    - a paper-execution readiness checklist.
>    - *Acceptance:* frontend builds clean (`cd frontend && npm run build`); panels render real audit/calibration fields; no new actionable execution path is introduced.
>
> 4. **P6 — Open-source tooling decision.** Decide OctoBot (reference-only per `docs/plans/2026-05-24-octobot-inspired-polymarket-client-v2.md`) vs `pmxt` (`pmxt==2.46.14` is in `requirements.txt`, currently installed but unused) — spike a concrete use or remove the dependency.
>    - *Acceptance:* a written decision plus either a working read-only spike or a clean removal from `requirements.txt`; backend suite still passes.
>
> **OPEN QUESTION FOR KAYVON (do not act without authorization):** now that calibration honestly gates overconfidence, re-enable a small Kalshi paper sample to gather calibrated evidence, or keep monitor-only? It is currently left **monitor-only** per the safety rules.
>
> **DISCIPLINE (required):**
> - **TDD:** write the failing test first, then the implementation.
> - **Test order:** run the focused new test(s) first, then the targeted module/area tests, then the full backend suite before claiming done:
>   `PYTHONPATH=. ./venv/bin/python -m pytest -q` (baseline: 270 passed).
> - **Frontend:** if you touch the UI, run `cd frontend && npm run build` and confirm it is clean.
> - **No completion claims without fresh command output.** Re-run and paste current results; do not trust prior runs.
> - **Read-only verification commands** (no trades):
>   - Audit (markdown): `PYTHONPATH=. ./venv/bin/python scripts/weather_audit_report.py --db tradingbot.db --window-hours 336 --format markdown`
>   - Audit (JSON): same with `--format json`
>   - Scan benchmark: `PYTHONPATH=. ./venv/bin/python scripts/benchmark_weather_scan.py` (synthetic; no network/DB)
>   - API smoke: construct the FastAPI `TestClient` with env `SCHEDULER_AUTOSTART=false`.
> - **Keep all safety gates off** (`SIMULATION_MODE=true`, `PAPER_AUTO_EXIT_ENABLED=false`, `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=false`, `BTC_LANE_ENABLED=false`) unless Kayvon explicitly authorizes a change, and never commit `.env`, `*.db`, `HERMES_SETUP_NOTES.md`, or `.firecrawl/` data.

---

## Reference: what shipped this session

| Area | Key files | Notable symbols / settings |
| --- | --- | --- |
| Scheduler / lane flags | `backend/config.py`, `backend/core/scheduler.py`, `backend/api/main.py` | `SCHEDULER_AUTOSTART` (default `True`), `BTC_LANE_ENABLED` (default `False`), `planned_scheduler_jobs()`, `start_scheduler()`, `is_scheduler_running()`, `_maybe_start_scheduler()`; `settlement_check`/`heartbeat` always run, `weather_scan` gated by `WEATHER_ENABLED` |
| Status redaction | `backend/api/main.py` | `_redact_address()`, `_summarize_account_balance()`; `/api/kalshi/status` → `{connected, balance_available}`; `/api/polymarket/relayer/status` → `{configured, connected, address_present, address_preview}` |
| Calibration | `backend/core/weather_calibration.py` (new), `backend/core/weather_signals.py` | `calibrate_weather_probability()`, `reliability_weight_from_brier()`, `config_from_settings()`, `normal_cdf()`; settings keys `WEATHER_CALIBRATION_ENABLED` (`True`), `WEATHER_CALIBRATION_MIN_STD_F` (1.5), `WEATHER_CALIBRATION_STD_INFLATION` (1.5), `WEATHER_CALIBRATION_MIN_CONFIDENT_Z` (1.0), `WEATHER_CALIBRATION_MIN_MEMBERS` (20) — populated into the `CalibrationConfig` dataclass fields `min_std_f`/`std_inflation`/`min_confident_z`/`min_members`; `generate_weather_signal()` now accepts `forecast=` and adds a `"calibration not confident"` no-trade reason + a `calibration:` filter tag |
| Audit | `backend/core/weather_audit.py`, `scripts/weather_audit_report.py` | `derive_city_label()`, `summarize_probability_calibration()`, `trade_win_probability()`, `connect_sqlite()` (URI `mode=ro` + `PRAGMA query_only`; never creates a missing DB), `TRAILING_WINDOWS` (72h/7d/14d), `by_city` split; markdown + `--format json` |
| Scan runtime | `backend/core/weather_scan_runtime.py` (new), `scripts/benchmark_weather_scan.py`, `backend/core/weather_signals.py` | `prefetch_forecasts()`, `map_concurrently()`, `forecast_keys()`, `ScanRuntimeStats`; `WEATHER_SCAN_CONCURRENCY` (default 8); wired into `scan_for_weather_signals()` |

**Calibration mechanics (for the per-venue follow-up):** `calibrate_weather_probability()` is a variance-inflated Gaussian re-estimate of P(YES) via `normal_cdf()`, with a per-member std floor, underdispersion inflation, quadrature observation noise for inexact sources, member-count widening, and shrinkage toward 0.5 for degraded inputs. The `confident` flag requires the threshold to sit at least `min_confident_z` (1.0) inflated sigmas from the ensemble mean, with at least `min_members` (20) members and an exact source. `reliability_weight_from_brier()` maps a venue's recent Brier into a `[floor, 1]` reliability multiplier (shrinking toward neutral for small samples) and is the intended input to `calibrate_weather_probability(venue_reliability=...)`.

**Tests for the above:** `tests/test_scheduler_autostart.py`, `tests/test_status_endpoint_redaction.py`, `tests/test_weather_calibration.py`, `tests/test_weather_signal_calibration_integration.py`, `tests/test_weather_audit.py`, `tests/test_weather_scan_runtime.py`.

**Commit note:** this session's work plus the accumulated prior weather buildout were committed together on `weather-bot-hardening-2026-06-16` (`3cb8a68`) because `main` HEAD `e406394` had a broadly dirty tree with no commit boundary. Excluded from the commit: `.env`, `*.db`, `HERMES_SETUP_NOTES.md`, `.firecrawl/`.
