#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
from pathlib import Path
import sys

repo_root = Path(__file__).resolve().parents[1]
if str(repo_root) not in sys.path:
    sys.path.insert(0, str(repo_root))

from backend.core.weather_audit import (
    build_weather_audit,
    connect_sqlite,
    dataclass_to_dict,
)


def _pnl(value: float) -> str:
    return f"${value:+.2f}"


def _money(value: float) -> str:
    return f"${value:.2f}"


def _summary_line(label: str, summary) -> str:
    win_rate = "n/a" if summary.win_rate is None else f"{summary.win_rate:.1f}%"
    return (
        f"- **{label}:** {summary.total} trades; {summary.settled} settled / "
        f"{summary.pending} pending; {summary.wins}W/{summary.losses}L; "
        f"PnL `{_pnl(summary.realized_pnl)}`; win rate `{win_rate}`; "
        f"ex-largest-outlier PnL `{_pnl(summary.ex_outlier_pnl)}`"
    )


def _account_line(account) -> str:
    return (
        f"- Equity before pending marks: `{_money(account.equity_before_pending_marks)}`; "
        f"Target: `{_money(account.target_bankroll)}`; "
        f"Realized PnL: `{_pnl(account.realized_pnl)}`; "
        f"Remaining: `{_money(account.remaining_to_target)}`; "
        f"Progress: `{account.progress_pct:.1f}%`; "
        f"Trades: `{account.total_trades}` total / `{account.settled_trades}` settled / "
        f"`{account.pending_trades}` pending / `{account.closed_early_trades}` closed early; "
        f"Pending size: `{_money(account.pending_size)}`"
    )


def render_markdown(report) -> str:
    lines = [
        "# Weather Paper-Trade Audit",
        "",
        f"Generated: `{report.generated_at}`",
        f"Window: `{report.window_hours}h`",
        "",
        "## Trade performance",
        _summary_line("Strict window", report.strict_window),
    ]

    if report.strict_window.outlier_event_slug:
        lines.append(
            f"- Largest outlier: `{report.strict_window.outlier_event_slug}` "
            f"PnL `{_pnl(report.strict_window.outlier_pnl or 0.0)}`"
        )

    lines.extend([
        "",
        "## Weather paper account",
        _account_line(report.account_state),
    ])

    if report.all_time is not None:
        lines.extend([
            "",
            "## All-time performance",
            _summary_line("All-time", report.all_time),
        ])
        if report.all_time.outlier_event_slug:
            lines.append(
                f"- Largest outlier: `{report.all_time.outlier_event_slug}` "
                f"PnL `{_pnl(report.all_time.outlier_pnl or 0.0)}`"
            )

    if report.trailing_windows:
        lines.extend(["", "## Trailing windows"])
        for label, summary in report.trailing_windows.items():
            lines.append(_summary_line(label, summary))

    lines.extend(["", "## Venue split"])
    if report.by_platform:
        for platform, summary in sorted(report.by_platform.items()):
            lines.append(_summary_line(platform, summary))
    else:
        lines.append("- No weather paper trades found in this window.")

    lines.extend(["", "## By city"])
    if report.by_city:
        for city, summary in sorted(report.by_city.items()):
            lines.append(_summary_line(city, summary))
    else:
        lines.append("- No weather paper trades recorded.")

    lines.extend(["", "## Probability calibration"])
    calib = report.calibration
    if calib is None or calib.sample_size == 0:
        lines.append("- No settled trades with usable model probabilities.")
    else:
        brier = "n/a" if calib.brier_score is None else f"{calib.brier_score:.4f}"
        mean_pred = "n/a" if calib.mean_predicted_win_prob is None else f"{calib.mean_predicted_win_prob:.3f}"
        emp = "n/a" if calib.empirical_win_rate is None else f"{calib.empirical_win_rate:.3f}"
        lines.append(
            f"- Sample: `{calib.sample_size}`; Brier `{brier}` (0=perfect, 0.25=coin flip); "
            f"mean predicted win prob `{mean_pred}`; empirical win rate `{emp}`"
        )
        for b in calib.bins:
            if b.count == 0:
                continue
            mp = "n/a" if b.mean_predicted is None else f"{b.mean_predicted:.3f}"
            wr = "n/a" if b.empirical_win_rate is None else f"{b.empirical_win_rate:.3f}"
            lines.append(
                f"  - `[{b.lower:.1f}–{b.upper:.1f})` n=`{b.count}` "
                f"predicted `{mp}` vs actual `{wr}`"
            )

    batch = report.latest_signal_batch
    lines.extend(
        [
            "",
            "## Latest signal batch",
            f"- Minute: `{batch.minute or 'n/a'}`",
            (
                f"- Signals: `{batch.total}` total; `{batch.actionable}` actionable; "
                f"`{batch.filtered}` filtered; `{batch.positive_size}` positive-size; "
                f"`{batch.executed}` executed"
            ),
            "",
            "Simulation-only: this report does not place trades or access private exchange accounts.",
        ]
    )
    return "\n".join(lines) + "\n"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate a read-only weather paper-trade audit from SQLite."
    )
    parser.add_argument("--db", default="tradingbot.db", help="Path to SQLite DB")
    parser.add_argument("--window-hours", type=int, default=72, help="Strict audit window")
    parser.add_argument("--format", choices=["markdown", "json"], default="markdown")
    parser.add_argument("--output", default="", help="Optional output path")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    conn = connect_sqlite(args.db)
    try:
        report = build_weather_audit(
            conn,
            now=datetime.now(timezone.utc).replace(tzinfo=None),
            window_hours=args.window_hours,
        )
    finally:
        conn.close()

    if args.format == "json":
        payload = json.dumps(report, default=dataclass_to_dict, indent=2) + "\n"
    else:
        payload = render_markdown(report)

    if args.output:
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(payload)
    else:
        print(payload, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
