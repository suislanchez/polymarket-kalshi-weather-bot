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

- Python suite: 1405 passed. Frontend: 24 passed, production build clean.
- Migration manifest: 18/18 copied destinations rehash to their recorded
  SHA-256; 498 databases pass `PRAGMA integrity_check`.
- With Archives unavailable, `POST /api/trading/paper/run` returns 409
  `archives_unavailable` and no internal-disk SQLite fallback is created.
- Alpaca paper is verified live: read-only account access, and a bounded
  submit/cancel leaving zero open orders and zero positions.
- Nine starlette advisories remain, blocked by FastAPI's `starlette<0.36.0`
  pin. Exposure and mitigation are recorded in the report.
- `/api/dashboard` cold load is 12.6s (was 108s) and cached reloads are
  instant; see report §16–§17, including the legacy-gate defect found on the way.

Task 18 (local-storage switchover) has not been performed. It needs explicit
approval, and the plan's original `$SOURCE` path no longer exists.

## Adversarial review, 2026-09-06

The report carries an addendum recording an 8-dimension adversarial review of
the implementation commits: 47 findings raised, 21 independently verified by
skeptics instructed to refute them, 13 survived, 7 fixed. Two corrections to
the report's own earlier claims are recorded there:

- The venv **was not** self-contained on Archives; this is now fixed. The base
  interpreter lives at `envs/cpython-3.11.15` and the venv is rebuilt against it
  with `--copies`, so nothing reaches the internal disk. The exact package set
  is pinned at `envs/unified-trading-py311.freeze.txt`, and the previous
  environment is kept at `envs/unified-trading-py311.internal-dep-backup` until
  you delete it.
- The live ledger digest has changed since the migration section was written —
  explained by the schema migration plus 12 audit events written by CLI runs
  during review. `unified_orders` is still empty and every event chain verifies.

## Rebuilding the environment

Everything the runtime needs is on Archives. To rebuild from scratch:

```bash
ROOT=/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system
$ROOT/envs/cpython-3.11.15/bin/python3.11 -m venv --copies $ROOT/envs/unified-trading-py311
env -u PYTHONPATH $ROOT/envs/unified-trading-py311/bin/python -m pip install \
  -r $ROOT/envs/unified-trading-py311.freeze.txt
```

Use `--copies`, and build at the final path. A symlinked venv still reaches its
base tree at runtime, and renaming a venv afterwards leaves every `bin/` shebang
pointing at the old absolute path — `pytest`, `pip-audit` and `bandit` break
while `python -m pytest` keeps working, which is a confusing way to find out.
