#!/usr/bin/env python3
"""Report whether this runtime is safe to trade on paper, and exit accordingly.

Exit 0 means every gate passed. Absent Alpaca credentials do not affect the
exit status -- they are reported as `credential_ready: false`, because the
system is meant to be verifiable before keys exist.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from backend.config import settings  # noqa: E402
from backend.trading.preflight import render, run_preflight  # noqa: E402


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable report")
    args = parser.parse_args(argv)

    report = run_preflight(settings)
    print(json.dumps(report.as_dict(), indent=2) if args.json else render(report))
    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
