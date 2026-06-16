# Weather Bot Hardening Handoff

**Generated:** 2026-06-16
**Branch:** `weather-bot-hardening-2026-06-16`
**Commit:** `3cb8a68` (checkpoint: weather-only buildout + session hardening)
**Repo:** `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot`

> **SAFETY BANNER — paper/simulation only.** This bot does not place live trades, does not create orders, and does not perform any private-account actions. `SIMULATION_MODE=true`. `PAPER_AUTO_EXIT_ENABLED=false` and `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=false` stay false unless Kayvon explicitly authorizes otherwise. No secrets are committed or exposed; status endpoints are redacted by default. Scope is **weather prediction markets only** — BTC and entertainment/Rotten Tomatoes lanes are legacy/paused. Every source-state / drilldown row stays `paper_actionable=false` until every final-source / model / liquidity / sizing / risk gate independently passes.

---

## 1. Executive summary

This session hardened the weather paper-trading bot across five workstreams, all using TDD. The full backend suite is **270 passed** and the frontend builds clean.

The headline change is a **probability calibration / anti-overconfidence layer** plus a **reproducible read-only audit** that, run against the real ledger, finally explains why the paper account lost money:

- **Brier score `0.7326`** (0 = perfect, 0.25 = a coin flip) on 22 settled weather trades.
- **Mean predicted held-side win probability `0.908`** versus an **empirical win rate of `0.136`**.
- **21 of 22 trades** landed in the `[0.8–1.0)` reliability bin — predicted `0.946`, actually won `0.143`.

In other words, the old model was extremely confident and almost always wrong near temperature thresholds. The losses were **systematic model overconfidence near thresholds**, which is exactly what the new calibration layer targets: it replaces the naive `[0.05, 0.95]` clip with a variance-inflated Gaussian re-estimate and gates actionability on a `confident` flag, so a clipped 95%/5% ensemble unanimity a fraction of a degree from the line can no longer, by itself, drive a paper trade.

The other four workstreams make the system safe to operate and audit: explicit scheduler/lane off-switches (so importing the app or running a smoke test never starts background jobs), redacted status endpoints (no raw balances or full addresses), a read-only audit/calibration reporter that reproduces the ledger exactly, and a scan runtime that de-duplicates forecast fetches under bounded concurrency.

---

## 2. The five hardening workstreams

### 2.1 Scheduler / lane safety flags

**What changed**

- `backend/config.py` adds two settings:
  - `SCHEDULER_AUTOSTART` (bool, default `True`): when false, FastAPI startup and the FastAPI `TestClient` construct the app **without** launching any background scan/settlement/heartbeat/risk jobs. Read-only API smokes should set it false.
  - `BTC_LANE_ENABLED` (bool, default `False`): the canonical BTC 5-min off-switch, replacing the prior `MIN_EDGE_THRESHOLD=999` suppression hack (the config comment explicitly says not to rely on that hack anymore).
- `backend/core/scheduler.py` adds `planned_scheduler_jobs()` — a pure, side-effect-free function returning the job ids `start_scheduler()` would register for the current settings, so the lane plan is unit-testable without an event loop or network. `start_scheduler()` only registers/fires the BTC `market_scan` job when `BTC_LANE_ENABLED`; `settlement_check` and `heartbeat` always run (so any existing pending paper trades can still settle), `open_position_risk` runs when `PAPER_POSITION_RISK_ENABLED`, and `weather_scan` runs when `WEATHER_ENABLED`.
- `backend/api/main.py` adds `_maybe_start_scheduler()`, which respects `SCHEDULER_AUTOSTART`; `startup()` calls it.

**Why it matters**

Previously, merely importing or constructing the app could kick off market scans and write paper trades, which makes tests and smokes unsafe and non-deterministic. The BTC off-switch is now explicit and discoverable instead of a magic threshold.

**Verified**

A `TestClient` built with `SCHEDULER_AUTOSTART=false` leaves `is_scheduler_running() == False` and creates no trades (the startup path logs that autostart is disabled and prints "No background scans/settlement/paper jobs started").

**Tests:** `tests/test_scheduler_autostart.py`

### 2.2 Status-endpoint redaction

**What changed**

- `backend/api/main.py` adds two helpers:
  - `_redact_address()` — shortens an account/wallet address to a `0x1234…ABCD` preview (first six chars, an ellipsis, last four) and never returns the full value; inputs of 12 characters or fewer collapse to a single ellipsis so a whole short identifier is not revealed.
  - `_summarize_account_balance()` — reduces a raw private balance payload to a non-sensitive boolean presence flag (true when the payload carries a balance-like key such as `balance` / `available_balance` / `portfolio_value` / `cash`).
- `/api/kalshi/status` returns `{connected, balance_available}` — no raw balance or cents.
- `/api/polymarket/relayer/status` returns `{configured, connected, address_present, address_preview}` — the address is a shortened preview only, never the full string.

**Why it matters**

Dashboard/status surfaces can show "funded / connected" without ever leaking a balance value or a full wallet address, keeping the no-secret-exposure rule intact by default.

**Verified**

A read-only smoke against these routes returns `kalshi_status: {connected, balance_available}` and `relayer_status: {configured, connected, address_present, address_preview}` where `address_preview` is a truncated `0x…` form (e.g. `0xD4b2…E167`) — a preview only, no raw balance value, no full address.

**Tests:** `tests/test_status_endpoint_redaction.py`

### 2.3 Probability calibration / anti-overconfidence

**What changed**

New module `backend/core/weather_calibration.py`:

- `calibrate_weather_probability()` — a variance-inflated Gaussian re-estimate of P(YES) using `normal_cdf`, with:
  - a std floor (`WEATHER_CALIBRATION_MIN_STD_F = 1.5`),
  - underdispersion inflation (`WEATHER_CALIBRATION_STD_INFLATION = 1.5`),
  - observation noise (`obs_std_f`, default 2.0 °F) added in quadrature when the settlement source/station is **not** an exact match,
  - member-count widening (capped by `max_member_factor`) when the ensemble has fewer than a full set of members (`full_members` default 31),
  - and shrinkage toward 0.5 for degraded inputs (`shrink_weight`).
- The `confident` flag is True only when the threshold is at least `WEATHER_CALIBRATION_MIN_CONFIDENT_Z` (1.0) inflated sigmas from the ensemble mean, **and** there are at least `WEATHER_CALIBRATION_MIN_MEMBERS` (20) members, **and** the source is exact.
- `reliability_weight_from_brier()` — maps a venue's recent Brier score to a `[floor, 1]` reliability multiplier (floor `0.4`; `[0, 0.25]` Brier → `[1, floor]`, shrinking toward neutral for small samples, full trust at roughly 30 samples); this is the seam for future per-venue calibration.
- `config_from_settings()` reads the `WEATHER_CALIBRATION_*` keys from settings. `WEATHER_CALIBRATION_ENABLED` defaults `True`.

Wired into `backend/core/weather_signals.py` `generate_weather_signal()`:

- replaces the naive `max(0.05, min(0.95, …))` clip (that fallback now only runs when calibration is disabled),
- for `above`/`below` markets, appends a `"calibration not confident: …"` entry to `no_trade_reasons` when `calibration.confident` is false, which zeroes the edge and the suggested size,
- appends a `calibration:z=…,conf=…` source tag for traceability,
- and `generate_weather_signal()` now accepts a `forecast=` injection (used by the scan runtime).

**Why it matters**

This is the direct fix for the key finding (§1): the old estimator was unanimous-and-overconfident near thresholds. The calibration layer widens the forecast, shrinks degraded inputs toward 0.5, and — critically — refuses to mark a row actionable unless the threshold is comfortably separated from the inflated forecast.

**Tests:** `tests/test_weather_calibration.py`, `tests/test_weather_signal_calibration_integration.py` (the integration test asserts a unanimous near-threshold signal — 31 members all at 75.5 °F against a 75 °F line — is blocked by calibration: model probability drops below 0.80, edge and suggested size become 0, and a `calibration not confident` reason plus a `calibration:` source tag are attached).

### 2.4 Reproducible audit + calibration reporting

**What changed**

`backend/core/weather_audit.py` plus the CLI `scripts/weather_audit_report.py`:

- All-time summary, trailing windows (`72h` / `7d` / `14d`), and by-city splits. City labels come from `derive_city_label()` — a heuristic that parses the Polymarket slug (`temperature-in-<city>-on-`) and the Kalshi ticker (e.g. `KXHIGH<station>` / `KXLOWT<station>`, with the longer `…T` prefixes matched first so the station code is captured rather than a trailing `T`).
- Probability calibration via `summarize_probability_calibration()` → Brier score plus reliability bins; `trade_win_probability()` orients the stored YES probability to the held side (a NO/DOWN position wins with `1 - model_probability`).
- Markdown output by default; JSON via `--format json`.
- Read-only by construction: `connect_sqlite()` opens the DB via a SQLite URI with `mode=ro` and forces `PRAGMA query_only = ON`, and **never** creates a missing DB.

**Why it matters**

This is the evidence layer. It is safe to run against the live ledger (it cannot mutate or create the DB), and it surfaces the calibration story that the prior tooling hid.

**Reproduces the ledger exactly** (from the live run this session against `tradingbot.db`):

- 336h strict window = **15 trades, 2W/13L, `-$343.75`**.
- All-time = **22 trades, 3W/19L, `-$709.18`**.
- Weather equity **`$290.82`** from a `$1000` start (target `$1100`).
- Calibration: Brier `0.7326`, mean predicted `0.908`, empirical `0.136`; `[0.8–1.0)` bin n=21 predicted `0.946` vs actual `0.143`.

(The `*.db` ledger is intentionally not committed, so these are live-run figures; the test suite asserts the audit *logic* on synthetic fixtures rather than baking in these numbers.)

**Tests:** `tests/test_weather_audit.py`

### 2.5 Scan runtime (forecast dedup + bounded concurrency)

**What changed**

New module `backend/core/weather_scan_runtime.py` plus the synthetic benchmark `scripts/benchmark_weather_scan.py`:

- `prefetch_forecasts()` — fetches one forecast per unique `(city, target_date)` under a bounded-concurrency semaphore; per-key failures are isolated (an exception or `None` drops that key and increments `forecast_errors` rather than aborting the scan).
- `map_concurrently()` — bounded-concurrency application of an async function over items, **preserving order**.
- `ScanRuntimeStats` and `forecast_keys()` support the above.
- `WEATHER_SCAN_CONCURRENCY` (default `8`) controls the cap. This is wired into `scan_for_weather_signals` in `backend/core/weather_signals.py`: it prefetches the forecast map, then generates signals concurrently with the matching forecast injected into `generate_weather_signal(market, forecast=…)`.

**Why it matters**

A single scan produces dozens of market lines that share the same city/day forecast (every temperature bucket for a city/day). De-duplicating means forecast-fetch count tracks unique city/days, not market count — fewer hits against public APIs and a shorter wall clock.

**Benchmark (synthetic, no network/DB)**

With the script's defaults (120 markets across 12 cities × 2 days, which collapse to 12 unique city/day keys), the run reports **12 forecast fetches** for 120 markets (**10.0× dedup**) plus a large concurrency speedup. The synthetic wall-clock speedup is illustrative — the **dedup ratio is the real, load-bearing result; real-world speedup is lower**.

**Tests:** `tests/test_weather_scan_runtime.py`

---

## 3. Verification evidence

All commands are read-only and place no trades. Run from the repo root with the project venv. The results below are what this session's runs reported.

| Check | Command | Result |
|---|---|---|
| Full backend tests | `PYTHONPATH=. ./venv/bin/python -m pytest -q` | **270 passed** |
| Audit (markdown) | `PYTHONPATH=. ./venv/bin/python scripts/weather_audit_report.py --db tradingbot.db --window-hours 336 --format markdown` | Reproduces ledger: 336h = 15 trades 2W/13L `-$343.75`; all-time = 22 trades 3W/19L `-$709.18`; equity `$290.82`; Brier `0.7326`, mean pred `0.908` vs empirical `0.136` |
| Audit (JSON) | same command with `--format json` | Same figures as machine-readable JSON |
| Scan benchmark | `PYTHONPATH=. ./venv/bin/python scripts/benchmark_weather_scan.py` | 120 markets → 12 unique forecast keys → 12 fetches (10.0× dedup) |
| Frontend build | `(cd frontend && npm run build)` | Built clean, no errors |
| Read-only API smoke | Construct a FastAPI `TestClient` with env `SCHEDULER_AUTOSTART=false` | `is_scheduler_running() == False`; `/api/kalshi/status` → `{connected, balance_available}`; `/api/polymarket/relayer/status` → `{configured, connected, address_present, address_preview}` (truncated `0x…` preview only — no raw balance, no full address) |

---

## 4. Commit / working-tree note

This session's work plus the accumulated prior weather buildout were committed **together** on branch `weather-bot-hardening-2026-06-16` (commit `3cb8a68`). They were combined because `main` HEAD `e406394` left a broadly dirty tree with no clean commit boundary, so this checkpoint captures a coherent, test-passing state.

**Deliberately excluded from the commit:**

- `.env` — secrets.
- `*.db` — the local SQLite paper ledger (e.g. `tradingbot.db`).
- `HERMES_SETUP_NOTES.md`.
- `.firecrawl/` — unrelated scraped data.

`.env` and `*.db` are gitignored (never tracked). `.firecrawl/` and `HERMES_SETUP_NOTES.md` remain untracked in the working tree (`git status` still shows `?? .firecrawl/` and `?? HERMES_SETUP_NOTES.md`), and the commit message itself documents the exclusion.

---

## 5. Remaining roadmap and the open Kalshi question

Not done this session:

- **P3 — source-state hardening.** Handle Seoul/RKSI anomaly-warning rows (primary source vs neighbors `[90.0, 91.0]`, max delta ~9 °F) and HKO missing-target-date rows. Add explicit source-state statuses, and keep all such rows `paper_actionable=false` until the final gates pass.
- **P5 — dashboard.** A "why not trading" blocker-aggregation panel; venue badges (Kalshi marked monitor-only); a strategy-health view (now that Brier/calibration data exists); a paper-execution readiness checklist.
- **P6 — open-source tooling.** Decide between OctoBot (reference-only) and pmxt (installed but unused): spike it or remove it.
- **Per-venue calibration.** Feed `reliability_weight_from_brier()` from the audit's by-venue Brier into `calibrate_weather_probability(venue_reliability=…)`. The seam already exists in both modules; the by-venue split is already produced by the audit. (For context, the current ledger's venue split shows Kalshi losing on a small sample versus Polymarket — feeding that asymmetry through `venue_reliability` is the intended next step.)

**Open question for Kayvon:** now that calibration honestly gates overconfidence, do we re-enable a small Kalshi paper sample to gather calibrated evidence, or keep it monitor-only? Per the safety rules it was **left monitor-only** this session (`WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=false`, enforced again at execution time by `_weather_paper_execution_blockers()` in the scheduler).

---

## 6. Pointers to the other docs

- **Prior comprehensive handoff (full background):** `docs/plans/2026-06-15-weather-bot-current-state-claude-handoff.md`
- **Settlement bug repair:** `docs/cron-context/weather-paper-settlement-repair-20260610T014508Z.md`
- **Paused cron context & re-review checklist:** `docs/cron-context/weather-platform-cron-pause-reactivation-handoff.md`. Two OpenAI Codex-backed weather/platform cron jobs are paused (ids `222c5a493033` weather methodology + dashboard, `1e2966872a8d` platform / paper trading / tech debt); both had `last_status = error` (no Codex credentials). The architecture changed materially while they were paused (this hardening), so their prompts/handoffs **must be updated before resuming** — follow the re-review checklist in that doc.
- **Cron context index / latest:** `docs/cron-context/INDEX.md`, `docs/cron-context/weather-latest.md`
