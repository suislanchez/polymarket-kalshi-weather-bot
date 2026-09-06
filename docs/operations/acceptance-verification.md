# Acceptance verification

The full acceptance report is generated output and is deliberately **not**
tracked: it records account balances, endpoint timings, and database digests
from a specific run, none of which belong in version control.

It is written to:

```
/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/artifacts/verification/unified-paper-acceptance.md
```

## Regenerating it

The report is assembled by hand from the Task 17 verification steps in
`docs/superpowers/plans/2026-08-23-unified-trading-system-implementation.md`.
The commands, in order:

```bash
ROOT=/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system
ENVS=$ROOT/envs
PY="env -u PYTHONPATH PYTHONPATH=. $ENVS/unified-trading-py311/bin/python"

git status --short --branch && git diff --check && git fsck --full
$PY -m pytest -q
(cd frontend && npm test -- --run && npm run build)
env -u PYTHONPATH $ENVS/unified-trading-py311/bin/python -m pip check
env -u PYTHONPATH $ENVS/unified-trading-py311/bin/pip-audit -r requirements.txt
env -u PYTHONPATH $ENVS/unified-trading-py311/bin/pip-audit -r requirements-trading.txt
env -u PYTHONPATH $ENVS/unified-trading-py311/bin/python -m bandit -r backend scripts -q
$PY scripts/trading_preflight.py
$PY scripts/run_paper_strategy.py --adapter fake --symbols SPY --once
$PY scripts/verify_alpaca_paper.py --read-only
```

## What the last accepted run established

- Python suite: 1369 passed. Frontend: 20 passed, production build clean.
- Migration manifest: 18/18 copied destinations rehash to their recorded
  SHA-256; 498 databases pass `PRAGMA integrity_check`.
- With Archives unavailable, `POST /api/trading/paper/run` returns 409
  `archives_unavailable` and no internal-disk SQLite fallback is created.
- Alpaca paper is verified live: read-only account access, and a bounded
  submit/cancel leaving zero open orders and zero positions.
- Nine starlette advisories remain, blocked by FastAPI's `starlette<0.36.0`
  pin. Exposure and mitigation are recorded in the report.
- `/api/dashboard` takes ~105s because it fetches a Polymarket midpoint per
  market serially inside the request. Pre-existing, and the largest open issue.

Task 18 (local-storage switchover) has not been performed. It needs explicit
approval, and the plan's original `$SOURCE` path no longer exists.
