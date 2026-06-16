# Prediction-market cron context index

Keep this file intentionally small. Cron jobs should read this index first, then open only the lane-specific files they need.

## Core project context
- Repository: `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot`
- Primary strategy: selective/no-forced trades. Estimate fair value and uncertainty; only trade when edge clears liquidity, spread, fee, and confidence gates. Zero-trade periods are acceptable.
- Current mode: simulation/paper trading only unless Kayvon explicitly authorizes live trading.

## Lane summaries
- BTC lane: `docs/cron-context/btc-latest.md`
- Weather lane: `docs/cron-context/weather-latest.md`
- Rotten Tomatoes / entertainment lane: `docs/cron-context/entertainment-latest.md`
- Platform / dashboard / tech debt lane: `docs/cron-context/platform-latest.md`
- Weather/platform cron pause + reactivation handoff: `docs/cron-context/weather-platform-cron-pause-reactivation-handoff.md`
- Post-hardening architecture update (READ before resuming crons; architecture changed materially while paused): `docs/cron-context/weather-architecture-update-2026-06-16.md`

## Heavier context files to open only when needed
- `README.md` — project overview.
- `ARCHITECTURE.md` — system architecture.
- `RESEARCH.md` and `VALIDATED_RESEARCH.md` — research notes and validated signals.
- `HERMES_SETUP_NOTES.md` — Hermes-specific setup notes.
- `docs/plans/` — implementation plans.

## Run discipline
Each scheduled run should:
1. Read this index and its lane summary.
2. Make a short plan with multiple concrete tasks.
3. Execute systematically, prioritizing useful progress over broad unfocused browsing.
4. Update the lane summary with: timestamp, what changed, files touched, evidence/sources, blockers, and next-run handoff.
5. Keep summaries compact and link/pointer-heavy; do not paste large raw datasets into context files.
