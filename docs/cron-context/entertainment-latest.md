# Rotten Tomatoes / entertainment lane latest handoff

Timestamp: 2026-06-03 22:04 PDT

## Plan for this run
1. Read compact cron/entertainment context plus persistent research artifacts; inspect repo state/diff/test/API/DB surfaces under simulation-only/no-forced-trade safeguards.
2. Re-query public Polymarket RT/box-office markets, direct RT source pages, and The Numbers source state; save raw/summary snapshots and normalize rows.
3. Make durable RT/entertainment methodology progress if a current batch-level QA gap appears.
4. Verify focused/targeted/full backend tests, runner py_compile/live run, final DB reconciliation, and update research artifacts plus this handoff.

## Completed work
- Ran public/read-only RT/entertainment snapshotter twice:
  - `20260604T050056Z` pre-patch market/source capture.
  - `20260604T050414Z` post-patch authoritative current-book/coverage-summary capture.
- Current post-patch run captured **27** active entertainment rows: **12 Rotten Tomatoes** and **15 box-office**; imported **10** direct RT source states into the app DB; captured The Numbers weekend chart page.
- Added RED/GREEN coverage for latest-batch RT/entertainment coverage diagnostics.
- Patched `backend/core/entertainment_signals.py` with `summarize_rotten_tomatoes_market_coverage(...)` so operators can see batch-level row count, RT/box-office split, unique event count, direct/source-state rows, line-book/top-size coverage, bucket diagnostics, mass-outside-sanity rows, no-score rows, and paper-actionable rows.
- Patched dependency-free snapshot runner `/Users/kayvonai/.hermes/research/.snapshots/rt_entertainment_snapshot.py` so every public summary emits the same `coverage_summary`.
- Updated research playbook, watchlist, research log, and hypothesis tracker (`H087`).

## Evidence / sources
- Authoritative current snapshots:
  - `/Users/kayvonai/.hermes/research/.snapshots/20260604T050414Z-rt-entertainment-public-raw.json`
  - `/Users/kayvonai/.hermes/research/.snapshots/20260604T050414Z-rt-entertainment-public-summary.json`
  - `/Users/kayvonai/.hermes/research/.snapshots/20260604T050414Z-the-numbers-weekend-box-office.html`
- Pre-patch snapshot:
  - `/Users/kayvonai/.hermes/research/.snapshots/20260604T050056Z-rt-entertainment-public-summary.json`
- Coverage summary at `20260604T050414Z`:
  - **27** total rows, **12** RT rows, **15** box-office rows, **6** unique event slugs.
  - **27** line-book rows, **27** top-size rows, **15** box-office bucket rows.
  - **10** box-office mass-outside-sanity rows, **12** active no-score RT rows, **0** paper-actionable rows.
- Current box-office sets:
  - Masters of the Universe: **5** rows, mass **1.09**; `<$27M` **16/23¢** size **6.49**, `$27M–$30M` **30/37¢** size **184.36**, `>$36M` **17/20¢** size **9**. Rows carry mass-outside-sanity blockers.
  - Scary Movie: **5** rows, mass **1.0565**; `≥$52M` **55/58¢**, top ask size **17**. Rows carry mass-outside-sanity blockers.
  - The Amazing Digital Circus: The Last Act: **5** rows, mass **1.009**; `≥$14M` **93/94¢**, top ask size **30**.
- Current direct RT source-state values:
  - Backrooms: **89% / 229 reviews**.
  - I Love Boosters: **92% / 136 reviews**.
  - Passenger: **47% / 78 reviews**.
  - Pressure: **87% / 87 reviews**.
  - Star Wars: **62% / 290 reviews**.
  - The Breadwinner: **19% / 36 reviews**.
  - Scary Movie / Supergirl / Robin Hood / Last Viking: **no displayed score / 0 reviews**.

## Files changed / touched this run
- Repo logic: `backend/core/entertainment_signals.py`.
- Repo tests: `tests/test_entertainment_account_and_gates.py`.
- Snapshot runner: `/Users/kayvonai/.hermes/research/.snapshots/rt_entertainment_snapshot.py`.
- Research artifacts: `/Users/kayvonai/.hermes/research/prediction-market-edge-playbook.md`, `prediction-market-edge-watchlist.md`, `prediction-market-edge-hypothesis-tracker.md`, `prediction-market-edge-research-log.md`.
- Generated snapshots: `/Users/kayvonai/.hermes/research/.snapshots/20260604T050056Z-rt-entertainment-public-{raw,summary}.json`, `/Users/kayvonai/.hermes/research/.snapshots/20260604T050414Z-rt-entertainment-public-{raw,summary}.json`, `/Users/kayvonai/.hermes/research/.snapshots/20260604T050414Z-the-numbers-weekend-box-office.html`.

## Verification
- RED: `test_rt_entertainment_market_coverage_summary_counts_source_depth_and_bucket_blockers` failed first because `summarize_rotten_tomatoes_market_coverage` was missing.
- Focused GREEN + syntax: `PYTHONPATH=. venv/bin/python -m pytest -q tests/test_entertainment_account_and_gates.py::test_rt_entertainment_market_coverage_summary_counts_source_depth_and_bucket_blockers tests/test_entertainment_account_and_gates.py::test_box_office_candidate_summary_flags_bucket_probability_mass_outside_sanity_band && python3 -m py_compile /Users/kayvonai/.hermes/research/.snapshots/rt_entertainment_snapshot.py` → **2 passed**.
- Targeted entertainment + review + API tests: `PYTHONPATH=. venv/bin/python -m pytest -q tests/test_entertainment_account_and_gates.py tests/test_signal_review_queue.py tests/test_api_response_models.py` → **47 passed**.
- Full backend: `PYTHONPATH=. venv/bin/python -m pytest -q` → **180 passed**, existing warnings only.
- Runner live run: `python3 /Users/kayvonai/.hermes/research/.snapshots/rt_entertainment_snapshot.py` → completed and saved `20260604T050414Z` raw/summary snapshots.
- Final research SQLite point-in-time: `market_quotes_v2=18996` latest `20260604T050414Z`, `raw_snapshots_v2=149` latest `20260604T050414Z`, `outcome_resolutions=168` latest `20260604T010832Z`, `entertainment_forecast_calibrations` absent, `weather_signal_review_candidates=987`, `polymarket_weather_source_states=2608`, `btc_outcome_scoring_v1=256` latest `20260603T190424Z`.
- Final app DB point-in-time: `rotten_tomatoes_source_states=277` latest `2026-06-04 05:04:14`, `trades=11` total (all weather; **0 RT trades**), `signals=49408`, `btc_price_snapshots=38408`.

## Account / safety state
- RT/entertainment paper account: **$1,000 equity**, **$1,100 target**, **$0 realized PnL**, **$100 remaining**, **0% progress**, **0 settled RT trades**, **0 pending RT trades**, **0 settled forecasts**, Brier/log-loss null.
- No live trades, no private accounts, no order placement, no paper RT trades, no paper exits, and no safeguards lowered.
- All current RT/box-office rows remain non-actionable due to missing final/direct source where applicable, no-score/timing risk, wide spreads/thin depth, lack of independent calibrated forecast probabilities, bucket-set sanity/mass blockers, and no-forced-trade gates.

## Open blockers
- Post-patch snapshot is authoritative for current books and coverage summary, but source velocity deltas are same-run duplicate-contaminated because it followed the pre-patch capture by minutes.
- Box-office rows are pre-release/current market state; direct final source snapshots should be captured near/after release weekend, then treated as calibration/source-resolution evidence only.
- `entertainment_forecast_calibrations` remains absent/null until independent model probabilities and final outcomes can be joined cleanly.

## Recommended next tasks
1. Continue clean RT/box-office snapshots without duplicate same-run captures unless patch verification requires it; interpret source velocity only from clean scheduled intervals.
2. Track Masters of the Universe, Scary Movie, and The Amazing Digital Circus bucket-set probability mass and line depth; keep mass-outside rows blocked.
3. Add The Numbers/BoxOfficeMojo final-source capture only when release timing is relevant, and keep it calibration/source-resolution-only.
4. If useful for operators, surface the new `coverage_summary` through dashboard/API in compact form; do not use coverage counts to upgrade actionability.
