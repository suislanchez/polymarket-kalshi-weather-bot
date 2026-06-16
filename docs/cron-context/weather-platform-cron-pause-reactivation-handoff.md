# Weather / platform prediction-market cron pause + reactivation handoff

Created: 2026-06-15 21:50 PDT
Scope: paused the two OpenAI Codex-backed weather prediction-market cron jobs so Kayvon can make one-off architecture changes before scheduled work resumes.

## Current pause state

The following jobs were intentionally paused, not removed:

| Job | ID | Original schedule | Repeat state at pause | Profile | Workdir | Model/provider |
|---|---|---|---|---|---|---|
| Prediction-market bot buildout — weather methodology + dashboard | `222c5a493033` | `0 8,18 * * *` | `49/9999` | `weather-markets` | `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot` | `gpt-5.5` / `openai-codex` |
| Prediction-market bot buildout — platform, paper trading, tech debt | `1e2966872a8d` | `0 6,20 * * *` | `48/9999` | `weather-markets` | `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot` | `gpt-5.5` / `openai-codex` |

Pause timestamps from `~/.hermes/cron/jobs.json`:

- `222c5a493033`: `2026-06-15T21:50:25.077560-07:00`
- `1e2966872a8d`: `2026-06-15T21:50:29.657978-07:00`

Cron metadata backup made before the pause:

- `/Users/kayvonai/.hermes/cron/jobs.json.backup-before-weather-platform-pause-20260615T215015-0700`

Both jobs retained their schedule, delivery, profile, workdir, skills, model/provider, and enabled toolsets. They should resume with `hermes cron resume <id>` / `cronjob(action="resume", job_id="...")` only after the re-review plan below is completed.

## Why paused

The last-30-day cron usage audit showed these were the top two active token consumers:

1. `222c5a493033` weather methodology + dashboard: ~340.8M total tokens across 48 runs.
2. `1e2966872a8d` platform / paper trading / tech debt: ~252.1M total tokens across 47 runs.

Kayvon expects to make one-off architecture changes in the next few days. The pause prevents scheduled agents from continuing against moving architecture or consuming Codex quota while the repo is in flux.

## Last known runtime state before pause

Current live cron metadata at pause time:

- Both jobs' `last_status` was `error`.
- Both jobs' `last_error` was: `RuntimeError: No Codex credentials stored. Run hermes auth to authenticate. Run hermes model to re-authenticate.`
- Delivery target was Slack DM `slack:D0B0H9CAL4W`.
- Toolsets were `web`, `terminal`, `file`, `skills`, `session_search`.

Repo state at pause time:

- Repo: `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot`
- Branch: `main`
- HEAD: `e406394` (`Add dashboard screenshot to README, update project structure`, 2026-03-01)
- Repo was broadly dirty from prior scheduled buildout work. Do **not** assume pause-time git status is clean.
- Notable uncommitted areas included backend API/core/data/model files, frontend dashboard/types/components, requirements, new `docs/cron-context/`, `docs/plans/`, `scripts/`, and `tests/` trees.

Latest lane handoffs to read before any restart:

- Weather lane: `docs/cron-context/weather-latest.md`
- Platform lane: `docs/cron-context/platform-latest.md`
- Context index: `docs/cron-context/INDEX.md`

Latest known weather/paper-account state from those handoffs:

- Latest weather snapshot batch in `weather-latest.md`: `20260615T151146Z`.
- Research DB: `/Users/kayvonai/.hermes/research/prediction-market-edge-snapshots.sqlite`.
- App DB: `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot/tradingbot.db`.
- Weather ledger at latest handoff: 22 trades, 22 settled, 0 open, 3 wins, realized PnL about `-$709.18`, weather equity about `$290.82`, remaining to `$1,100` target about `$809.18`.
- All recent platform/source-state work was visibility-only QA and must not be treated as actionability, sizing, execution, exit, or live-trading authorization.

## Re-review requirement before reactivation

Do **not** blindly resume these jobs. When Kayvon asks to kick them back up, first perform a fresh re-review because the architecture may have changed while paused.

Required re-review checklist:

1. Load the relevant skills/context:
   - `hermes-agent`
   - `hermes-context-budget-maintenance`
   - `prediction-market-edge-sprint`
   - `weather-prediction-market-research`
2. Re-read this file, `docs/cron-context/INDEX.md`, `weather-latest.md`, and `platform-latest.md`.
3. Inspect current cron metadata for both paused jobs and confirm they are still paused with the same IDs.
4. Check whether Codex credentials are healthy before any resume/run. If still broken, ask Kayvon to re-authenticate or switch model/provider explicitly; do not burn retries blindly.
5. Inspect repo architecture changes since the pause:
   - `git status --short`
   - current branch and HEAD
   - changed backend/API/data/model/frontend/test/config files
   - any dependency, DB schema, migration, env, scheduler, or API contract changes
6. Reconcile current artifacts and state:
   - `docs/cron-context/weather-latest.md`
   - `docs/cron-context/platform-latest.md`
   - `/Users/kayvonai/.hermes/research/prediction-market-edge-*.md`
   - latest `.snapshots/` weather batch summaries
   - research SQLite counts/latest batch IDs
   - app SQLite weather ledger and open/pending exposure
7. Re-run verification against the current architecture before scheduling autonomous work:
   - focused tests for any touched area
   - full backend tests where practical
   - frontend build if dashboard/frontend changed
   - dependency-light API smokes, ideally with `WEATHER_ENABLED=false` unless deliberately testing scheduler behavior
   - final DB / paper-account reconciliation
8. Re-check safety gates:
   - research/paper-only unless Kayvon explicitly authorizes otherwise
   - no live trades
   - no private-account/exchange actions
   - no auto-exit enablement without explicit approval
   - all source-state/drilldown rows remain `paper_actionable=false` unless every final-source/model/liquidity/sizing/risk gate independently passes
9. Update this handoff or the lane handoff files with the re-review findings before resuming cron.

## Reactivation plan

Recommended sequence when Kayvon says to resume:

1. Complete the re-review checklist above.
2. If architecture changed materially, patch the cron prompts and/or lane handoffs so both jobs start from the new architecture, not stale assumptions.
3. Resume one job at a time:
   - First resume or manually run `222c5a493033` (weather methodology + dashboard) as the canary if market/source-state refresh is needed.
   - Inspect its actual output, artifact updates, DB reconciliation, and delivery.
   - Then resume or run `1e2966872a8d` (platform / paper trading / tech debt) after the weather lane state is known-good.
4. Preserve original schedules unless Kayvon asks for a different cadence:
   - Weather: `0 8,18 * * *`
   - Platform: `0 6,20 * * *`
5. After the first successful post-pause run of each job, update:
   - `docs/cron-context/weather-latest.md`
   - `docs/cron-context/platform-latest.md`
   - `/Users/kayvonai/.hermes/research/prediction-market-edge-research-log.md`
   - `/Users/kayvonai/.hermes/research/prediction-market-edge-watchlist.md`
   - `/Users/kayvonai/.hermes/research/prediction-market-edge-hypothesis-tracker.md`

## Resume commands

Only after re-review:

```bash
hermes cron resume 222c5a493033
hermes cron resume 1e2966872a8d
hermes cron list --all
```

Or with the Hermes tool:

```text
cronjob(action="resume", job_id="222c5a493033")
cronjob(action="resume", job_id="1e2966872a8d")
cronjob(action="list")
```

If a dry canary is preferred, run one job manually after re-review, inspect output, then resume the schedule.

## Guardrails while paused

- Do not delete either cron job unless Kayvon explicitly asks.
- Do not rewrite schedules/models/toolsets as part of reactivation unless the re-review shows they are stale or Kayvon asks for a new cadence/provider.
- Do not infer live-trading authorization from the phrase "kick things back up". That only means resume scheduled research/buildout unless Kayvon explicitly says otherwise.
- If architecture changes create ambiguity, ask Kayvon whether to update prompts/docs before resuming.
