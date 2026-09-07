"""Command line for the bounded replay engine.

  run SPEC.json [--variant LABEL | --variant all] [--sem k=v ...] [--out DIR]
  calibrate TARGET.json [--top N] [--out DIR]
  batch SPEC.json ... [--out DIR]

Never touches the ledger; reads Alpaca bars through the CSV cache only.
"""
from __future__ import annotations

import argparse
import copy
import itertools
import json
import sys
from dataclasses import fields
from pathlib import Path

import pandas as pd

from .data import load_daily_bars, trading_root
from .engine import ExitRules, Semantics, run_symbol
from .metrics import summarize
from .report import render, write

DEFAULT_OUT = trading_root() / "artifacts" / "backtests"


def load_spec(path: str) -> dict:
    return json.loads(Path(path).read_text())


def apply_variant(spec: dict, label: str | None) -> dict:
    if not label or label == "baseline":
        return spec
    for v in spec.get("variants", []):
        if v["label"] == label:
            out = copy.deepcopy(spec)
            out["params"].update(v.get("params", {}))
            out["rules"].update(v.get("rules", {}))
            out["variant"] = label
            out["variant_note"] = v.get("note", "")
            return out
    raise SystemExit(f"variant {label!r} not found in {spec.get('name')}")


def parse_sem(pairs: list[str] | None, base: Semantics | None = None) -> Semantics:
    kw = base.as_dict() if base else {}
    for p in pairs or []:
        k, v = p.split("=", 1)
        kw[k] = v
    return Semantics(**kw)


def bars_for(spec: dict, adjustment: str) -> dict[str, pd.DataFrame]:
    asset_class = spec.get("asset_class", "equity")
    return {s: load_daily_bars(s, asset_class=asset_class, adjustment=adjustment) for s in spec["symbols"]}


def execute(spec: dict, sem: Semantics, adjustment: str = "split", bars: dict | None = None,
            start: str | None = None, end: str | None = None):
    bars = bars or bars_for(spec, adjustment)
    rules = ExitRules(**spec["rules"])
    start = start or spec["start"]
    end = end or spec["end"]
    per_symbol, all_trades, all_open = {}, [], []
    for sym in spec["symbols"]:
        df = bars[sym]
        trades, opens = run_symbol(sym, df, spec["template"], spec["params"], rules, sem, start, end)
        idx = df.loc[pd.Timestamp(start):pd.Timestamp(end)].index
        per_symbol[sym] = summarize(trades, opens, index=idx)
        all_trades += trades
        all_open += opens
    pooled = summarize(all_trades, all_open)
    return per_symbol, pooled, all_trades, all_open


def benchmark(spec: dict, sem: Semantics, adjustment: str) -> dict:
    """Same symbols, window, exits and sizing, but a signal on every session (always-long)."""
    b = copy.deepcopy(spec)
    b["template"] = "unconditional"
    b["params"] = {"every": 1}
    _, pooled, _, _ = execute(b, sem, adjustment)
    return pooled


def cmd_run(args):
    base = load_spec(args.spec)
    labels = [None] + [v["label"] for v in base.get("variants", [])] if args.variant == "all" else [args.variant]
    out_dir = Path(args.out) / base["name"]
    for label in labels:
        spec = apply_variant(base, label)
        sem = parse_sem(args.sem, Semantics(**base.get("semantics", {})))
        per_symbol, pooled, trades, opens = execute(spec, sem, args.adjustment)
        bench = benchmark(spec, sem, args.adjustment)
        pooled["benchmark_always_long"] = {k: bench[k] for k in ("trades", "net_pnl", "win_rate_pct", "avg_return_pct", "max_drawdown_usd")}
        pooled["excess_avg_return_pct"] = pooled["avg_return_pct"] - bench["avg_return_pct"]
        slug = f"{base['name']}-{label or 'baseline'}"
        title = f"{base['name']} · {base.get('title','')} · {label or 'baseline'}"
        md = render(title, spec, sem.as_dict(), per_symbol, pooled, note=spec.get("variant_note", ""))
        payload = {"spec": spec, "semantics": sem.as_dict(), "adjustment": args.adjustment, "per_symbol": per_symbol, "pooled": pooled, "open_positions": opens}
        path = write(out_dir, slug, md, payload, trades)
        print(f"{slug}: trades={pooled['trades']} net={pooled['net_pnl']:+.2f} win={pooled['win_rate_pct']:.2f}% avg={pooled['avg_return_pct']:+.2f}% | always-long avg={bench['avg_return_pct']:+.2f}% win={bench['win_rate_pct']:.1f}% ({bench['trades']} trades) | excess/trade={pooled['excess_avg_return_pct']:+.2f}% -> {path}")


GRID_COMMON = {
    "entry": ["next_close", "signal_close"],
    "hold_count": ["exclusive", "inclusive"],
    "overlap": ["independent", "one_per_symbol"],
    "shares": ["fractional", "whole"],
    "cost_model": ["split", "entry"],
    "warmup": ["history", "none"],
}
GRID_BY_TEMPLATE = {
    "breakout": {"breakout_level": ["close", "high"]},
    "sma_crossover": {"cross": ["loose", "strict"]},
    "pullback_recovery": {"recovery": ["close_cross_slow", "fast_cross_slow", "close_above_slow"], "pullback_ref": ["close", "high"], "pullback_mode": ["any_in_window", "depth_at_signal"]},
}


def cmd_calibrate(args):
    spec = load_spec(args.target)
    rep = spec["reported"]
    grid = dict(GRID_COMMON)
    grid.update(GRID_BY_TEMPLATE[spec["template"]])
    if args.fix:
        for p in args.fix:
            k, v = p.split("=", 1)
            grid[k] = [v]
    keys = list(grid)
    adjustments = args.adjustments.split(",")
    end_offsets = [int(x) for x in args.end_offsets.split(",")]
    results = []
    bars_cache = {adj: bars_for(spec, adj) for adj in adjustments}
    sessions = bars_cache[adjustments[0]][spec["symbols"][0]].index
    base_end = pd.Timestamp(spec["end"])
    end_pos = sessions.searchsorted(base_end, side="right") - 1
    combos = list(itertools.product(*[grid[k] for k in keys]))
    total = len(combos) * len(adjustments) * len(end_offsets)
    print(f"grid: {total} combinations", file=sys.stderr)
    for adj in adjustments:
        for off in end_offsets:
            if not (0 <= end_pos + off < len(sessions)):
                continue
            end = str(sessions[end_pos + off].date())
            for combo in combos:
                sem = Semantics(**dict(zip(keys, combo)))
                try:
                    _, pooled, trades, _ = execute(spec, sem, adj, bars_cache[adj], end=end)
                except ValueError:
                    continue
                score = (abs(pooled["trades"] - rep["trades"]),
                         abs(pooled["net_pnl"] - rep["net_pnl"]) / max(abs(rep["net_pnl"]), 1.0),
                         abs(pooled["win_rate_pct"] - rep.get("win_rate_pct", pooled["win_rate_pct"])))
                results.append((score, adj, end, sem.as_dict(), pooled))
    results.sort(key=lambda r: r[0])
    print(f"target {spec['name']}: reported trades={rep['trades']} net={rep['net_pnl']:+.2f} win={rep.get('win_rate_pct')}%")
    for score, adj, end, sem, pooled in results[: args.top]:
        diff = ", ".join(f"{k}={v}" for k, v in sem.items())
        print(f"  Δtrades={score[0]:>3} Δpnl={100*score[1]:5.1f}% Δwin={score[2]:4.1f} | trades={pooled['trades']} net={pooled['net_pnl']:+.2f} win={pooled['win_rate_pct']:.2f}% avg={pooled['avg_return_pct']:+.2f}% | adj={adj} end={end} | {diff}")
    if args.out:
        out = Path(args.out) / "calibration"
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{spec['name']}.json").write_text(json.dumps([{"score": s, "adjustment": a, "end": e, "semantics": sem, "pooled": p} for s, a, e, sem, p in results[:50]], indent=2, default=str))
    if "reported_by_symbol" in spec and results:
        best = results[0]
        sem = Semantics(**best[3])
        per_symbol, _, _, _ = execute(spec, sem, best[1], bars_cache[best[1]], end=best[2])
        print("  per-symbol (best combo) local vs reported:")
        for sym, val in spec["reported_by_symbol"].items():
            print(f"    {sym:6s} local {per_symbol[sym]['net_pnl']:+9.2f} ({per_symbol[sym]['trades']} trades)  reported {val:+9.2f}")


def cmd_batch(args):
    for spec_path in args.specs:
        ns = argparse.Namespace(spec=spec_path, variant="all", sem=args.sem, out=args.out, adjustment=args.adjustment)
        cmd_run(ns)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="bounded_replay")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run"); r.add_argument("spec"); r.add_argument("--variant", default="all"); r.add_argument("--sem", nargs="*"); r.add_argument("--out", default=str(DEFAULT_OUT)); r.add_argument("--adjustment", default="split"); r.set_defaults(fn=cmd_run)
    c = sub.add_parser("calibrate"); c.add_argument("target"); c.add_argument("--top", type=int, default=10); c.add_argument("--out", default=str(DEFAULT_OUT)); c.add_argument("--adjustments", default="split,all"); c.add_argument("--end-offsets", default="0,-1,-2,1"); c.add_argument("--fix", nargs="*", help="pin a grid key, e.g. warmup=history"); c.set_defaults(fn=cmd_calibrate)
    b = sub.add_parser("batch"); b.add_argument("specs", nargs="+"); b.add_argument("--sem", nargs="*"); b.add_argument("--out", default=str(DEFAULT_OUT)); b.add_argument("--adjustment", default="split"); b.set_defaults(fn=cmd_batch)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
