# bounded_replay — local mirror of the Upthriving Strategy Lab templates

Research tooling only. Pure pandas/numpy, no new dependencies, no imports from `backend/`, never touches `DATABASE_URL` or the ledger.

```bash
ROOT=/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system
cd $ROOT/unified-trading-system
PY="env -u PYTHONPATH $ROOT/envs/unified-trading-py311/bin/python"

$PY -m pytest research/bounded_replay/tests -q                 # synthetic-bar unit tests
$PY -m research.bounded_replay.cli run research/bounded_replay/specs/S3.json            # baseline + all variants
$PY -m research.bounded_replay.cli run research/bounded_replay/specs/S3.json --variant B --sem warmup=history
$PY -m research.bounded_replay.cli batch research/bounded_replay/specs/S*.json
$PY -m research.bounded_replay.cli calibrate research/bounded_replay/targets/T1.json   # grid over undocumented semantics
```

- Bars: Alpaca SIP daily (`adjustment=split`, matching Upthriving's split-adjusted closes) cached under `$ROOT/data/bars/`. Equities from 2016-01-04, crypto from 2021-01-01. Credentials from `$ROOT/secrets/alpaca-paper.env`.
- Outputs: `$ROOT/artifacts/backtests/<spec>/<spec>-<variant>.{md,json,trades.csv}`.
- Templates: `breakout` (n, volume_multiple), `sma_crossover` (fast, slow), `pullback_recovery` (lookback, pullback_pct, slow, fast, volume_multiple), `unconditional` (benchmark: a signal every session).
- Exits: max hold, % stop, % target, all evaluated on daily closes. Fixed notional per signal. Round-trip bps split across both legs.
- Default `Semantics` are the values calibrated against Upthriving target T1 (see `docs/research/2026-09-06-local-replay-vs-upthriving.md`): next-session-close entry, prior high on closes, hold counted inclusive of entry, no re-entry while a position is open, fractional shares, no warm-up history before the window start. Override any of them with `--sem key=value`.
- Every run also reports an **always-long benchmark** (same symbols, window, exits, sizing; a signal on every session) and the strategy's excess average return per trade over it. In a bull window a positive net P&L means little until it clears that benchmark.
