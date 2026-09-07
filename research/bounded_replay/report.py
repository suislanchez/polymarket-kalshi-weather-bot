"""Markdown/JSON rendering of replay results."""
from __future__ import annotations

import json
from dataclasses import asdict
from pathlib import Path

from .engine import Trade

KEYS = ["trades", "win_rate_pct", "net_pnl", "avg_return_pct", "median_return_pct", "payoff_ratio",
        "profit_factor", "max_drawdown_usd", "max_drawdown_pct", "open_positions"]


def _fmt(v):
    if v is None:
        return "—"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def table(rows: dict[str, dict], keys=KEYS) -> str:
    head = "| symbol | " + " | ".join(keys) + " |"
    sep = "|" + "---|" * (len(keys) + 1)
    body = ["| " + sym + " | " + " | ".join(_fmt(m.get(k)) for k in keys) + " |" for sym, m in rows.items()]
    return "\n".join([head, sep, *body])


def by_year_table(pooled: dict) -> str:
    rows = pooled.get("by_year", {})
    if not rows:
        return "_no closed trades_"
    out = ["| year | trades | wins | net_pnl |", "|---|---|---|---|"]
    for y, v in rows.items():
        out.append(f"| {y} | {v['trades']} | {v['wins']} | {v['net_pnl']:,.2f} |")
    return "\n".join(out)


def render(title: str, spec: dict, sem: dict, per_symbol: dict[str, dict], pooled: dict, note: str = "") -> str:
    lines = [f"# {title}", "", "**Independent fixed-size signal replay. Not a portfolio backtest. Per-ticker results are not additive into an investable return.**", ""]
    if note:
        lines += [note, ""]
    lines += ["## Spec", "", "```json", json.dumps({k: spec[k] for k in spec if k not in ("reported", "reported_by_symbol", "variants")}, indent=2, default=str), "```", "",
              "## Semantics", "", "```json", json.dumps(sem, indent=2), "```", "",
              "## Per symbol", "", table(per_symbol), "",
              "## Pooled (for comparison with Lab output only)", "", table({"ALL": pooled}), "",
              "Exit reasons: " + json.dumps(pooled.get("exit_reasons", {})), "",
              "## Always-long benchmark (signal every session, same exits and sizing)", "",
              table({"ALWAYS-LONG": pooled.get("benchmark_always_long", {})}, keys=["trades", "win_rate_pct", "net_pnl", "avg_return_pct", "max_drawdown_usd"]), "",
              f"Excess average return per trade vs always-long: **{pooled.get('excess_avg_return_pct', 0):+.2f}%**", "",
              "## By year (exit year)", "", by_year_table(pooled), ""]
    return "\n".join(lines)


def write(out_dir: Path, slug: str, markdown: str, payload: dict, trades: list[Trade]) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{slug}.md").write_text(markdown)
    (out_dir / f"{slug}.json").write_text(json.dumps(payload, indent=2, default=str))
    with (out_dir / f"{slug}.trades.csv").open("w") as fh:
        fh.write("symbol,signal_date,entry_date,exit_date,entry,exit,shares,gross_pnl,cost,net_pnl,return_pct,sessions_held,exit_reason\n")
        for t in trades:
            fh.write(f"{t.symbol},{t.signal_date.date()},{t.entry_date.date()},{t.exit_date.date()},{t.entry:.6f},{t.exit:.6f},{t.shares:.6f},{t.gross_pnl:.4f},{t.cost:.4f},{t.net_pnl:.4f},{t.return_pct:.4f},{t.sessions_held},{t.exit_reason}\n")
    return out_dir / f"{slug}.md"
