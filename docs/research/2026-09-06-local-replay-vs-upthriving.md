# Local replay engine vs Upthriving Strategy Lab — calibration and first pass

**Date:** 2026-09-06 · **Engine:** `research/bounded_replay/` (see its README) · **Data:** Alpaca SIP daily bars, split-adjusted, cached under `$ROOT/data/bars/`

Research only. Every number is an independent fixed-size signal replay, not a portfolio return.

## 1. Bottom line

- **Yes, we can backtest locally**, over the same three-year window the Lab uses, with the same three templates, from Alpaca data your paper keys already have (equities back to 2016, crypto back to 2021).
- **The breakout template is reproduced.** Your Sep 1 test (8 mega-caps, 60-session breakout, $500, 10 bp) replays locally at exactly 95 trades and +$1,447.64 against the Lab's +$1,442.21, average +3.05% vs +3.04%. Only the win rate differs by three trades (61.1% vs 64.2%), which is the size of residual you expect from Robinhood-vs-Alpaca close prices.
- **SMA crossover is close but not exact** (trade counts within 0–3, P&L within roughly 10–25%). The template's entry timing is ambiguous with so few trades.
- **Pullback recovery is not reproduced.** The best local definition lands within 0.2% of the Lab's P&L on a 119-trade row but fires 142 trades. Until the Lab states its exact pullback and recovery rule, treat local-vs-Lab pullback comparisons as unverified. The prompt pack already asks the Lab for that definition before every pullback run.
- **The window is the problem, not the templates.** Adding an always-long benchmark (same symbols, exits and sizing, a signal every session) shows the 2023-09 → 2026-09 window pays almost any long entry. The 20/100 SMA "negative control" won 11 of 11 trades. Judge every result by its excess over always-long, not by raw P&L.

## 2. What the Lab actually does (calibrated semantics)

Read from the executable-config JSON on each Tradebot card, then confirmed by grid search against target T1.

| Question | Answer | Evidence |
|---|---|---|
| When does a trade enter? | Close of the **session after** the signal | config `entry_timing: next_session_close`; T1 P&L 19% off with signal-day entry |
| What is the "prior N-session high"? | Highest **close** of the prior N sessions | T1 grid; using highs breaks the trade count |
| How are stop and target checked? | On **daily closes** only | config `exit_evaluation: daily_close` |
| How is the hold counted? | Entry session counts as session 1 (**inclusive**) | T1 grid |
| Can a symbol re-enter while a trade is open? | **No** | T1: 740 trades if allowed, 95 if not |
| Sizing? | Fixed dollars, fractional shares | T1 grid; whole shares change P&L by <0.1% |
| Prices? | Split-adjusted closes and volume (no dividend adjustment) | config text; `adjustment=split` matches, `all` does not |
| Warm-up before the window? | **None** in the Lab (cache starts 2023-09-03) | T1 grid; deployed-bot replays do use warm-up |
| Volume filter? | Today's volume ≥ K × average of the prior N sessions, N = breakout lookback | config text on the quantum card |
| Costs? | Round-trip bps; splitting across legs vs charging on entry is indistinguishable at 10 bp | T1 grid |

These are the engine's defaults. Override with `--sem key=value` (for local research, `warmup=history` is the more sensible choice).

## 3. Calibration targets and results

| Target | What | Reported | Local (T1 semantics) | Verdict |
|---|---|---|---|---|
| T1 | Your Sep 1 8-stock 60-session breakout, 30 hold, 8% stop, 20% target, $500, 10 bp | 95 trades, +$1,442.21, 64.21%, +3.04%/trade | **95 trades, +$1,447.64, 61.05%, +3.05%** | Reproduced |
| T2 | Your Sep 1 sector-ETF 20/100 SMA (XLB XLE XLF XLK XLI XLV XLY XLP), 30 hold, $500, 10 bp | 40, +$490.26, 55.0% | 37, +$428.69, 59.5% | Close; unpinned grid reaches 41 trades / +$619 with warm-up and dividend adjustment, so the SMA path has one unexplained degree of freedom |
| T3 | Your Sep 1 SPY EFA AGG DBC GLD VNQ 20/100 SMA | 20, +$22.38, 40.0% | 20, +$79.72 (next-close entry) or +$21.43 (signal-close entry) | Trade count exact; entry timing ambiguous on a $22 result |
| T4 | Deployed Leveraged Bull Pullback per-ETF P&L (10% pullback, 30-SMA, 20/20, 30 hold, $1,000, 10 bp) | 71 closed trades; CURE +220, FAS −41, LABU −164, NUGT +775, SOXL +538, TECL +50, TQQQ +661, UPRO +951 | 71 trades reachable, but FAS +186 and LABU +661 (signs flipped) | Not reproduced; this replay also uses warm-up and quote-midpoint fills the Lab does not |
| T5 | Quantum shadow breakout (30-session, 2x volume, 20% stop, no target) | "11 trades" | 34 trades | Not usable: the 11 is the shared-pool count, standalone count is not published |
| T6 | Library row *SEC-Frozen Negative-Trial Recovery v212* (5% pullback, 20-SMA, hold 15, 20% stop, 25% target, 25 bp) | 119 trades, +$1,159.84, 49.58% | 142 trades, +$1,157.47, 48.6% (pullback measured from highs, close reclaims 20-SMA) | P&L matches, trade count 19% high; definition still open |

Full grids are in `$ROOT/artifacts/backtests/calibration/T*.json`.

**What would close the remaining gaps**

1. One Lab-run pullback test whose prompt spells out the rule (the S1/S8/S9/S10 prompts do this). Two or three numbers from that run should settle the pullback definition in one more grid pass.
2. One Lab-run SMA test on high-turnover symbols (S12 will do) to pin entry timing for that template.
3. The residual after that is data-source noise (Robinhood vs Alpaca closes, a handful of trades flipping sign), which no engine change removes.

## 4. Local first pass of the shortlist

Same parameters as the prompt pack; Lab semantics; costs 25 bp ETFs / 50 bp stocks / 240–500 bp BTC; window 2023-09-05 → 2026-09-04. **Excess** = average return per trade minus the always-long benchmark's average return per trade on the same basket with the same exits. Per-file detail (per-symbol tables, by-year, trade lists) under `$ROOT/artifacts/backtests/<spec>/`.

| spec | variant | trades | net P&L | win % | avg/trade % | median % | PF | max DD $ | symbols +/− | always-long avg % | excess/trade % |
|---|---|---|---|---|---|---|---|---|---|---|---|
| S1 | baseline | 99 | +8,659 | 58.6 | +8.75 | +6.99 | 2.29 | -2,450 | 8/0 | +7.02 | +1.72 |
| S1 | A | 113 | +7,337 | 54.0 | +6.49 | +2.61 | 1.95 | -3,072 | 7/1 | +7.02 | -0.53 |
| S1 | B | 72 | +6,913 | 56.9 | +9.60 | +6.58 | 2.21 | -2,004 | 8/0 | +7.02 | +2.58 |
| S1 | C | 104 | +6,002 | 63.5 | +5.77 | +11.57 | 1.94 | -1,773 | 7/1 | +4.71 | +1.06 |
| S2 | baseline | 25 | +1,220 | 60.0 | +4.88 | +6.57 | 1.76 | -562 | 5/3 | +7.02 | -2.15 |
| S2 | A | 36 | +332 | 47.2 | +0.92 | -1.40 | 1.13 | -868 | 4/4 | +7.02 | -6.10 |
| S2 | B | 100 | +5,998 | 57.0 | +6.00 | +5.04 | 2.04 | -1,167 | 8/0 | +7.02 | -1.03 |
| S3 | baseline | 35 | +2,326 | 57.1 | +6.65 | +7.28 | 2.27 | -897 | 5/3 | +6.46 | +0.19 |
| S3 | A | 29 | +1,503 | 58.6 | +5.18 | +3.56 | 1.96 | -682 | 4/4 | +6.46 | -1.28 |
| S3 | B | 120 | +10,390 | 70.0 | +8.66 | +9.06 | 3.53 | -2,178 | 8/0 | +6.46 | +2.20 |
| S4 | baseline | 38 | +3,966 | 52.6 | +10.44 | +4.76 | 4.60 | -380 | 7/1 | +6.10 | +4.34 |
| S4 | A | 31 | +3,595 | 51.6 | +11.60 | +4.79 | 4.48 | -592 | 7/1 | +6.10 | +5.50 |
| S4 | B | 108 | +8,913 | 63.9 | +8.25 | +4.74 | 3.48 | -1,417 | 8/0 | +6.10 | +2.16 |
| S5 | baseline | 51 | +2,485 | 47.1 | +4.87 | -2.64 | 1.59 | -918 | 5/3 | +4.16 | +0.71 |
| S5 | A | 41 | +1,018 | 43.9 | +2.48 | -3.45 | 1.34 | -1,275 | 2/6 | +4.16 | -1.68 |
| S5 | B | 96 | +4,598 | 50.0 | +4.79 | -0.10 | 1.67 | -1,477 | 8/0 | +4.16 | +0.63 |
| S6 | baseline | 49 | +870 | 61.2 | +1.78 | +3.60 | 1.29 | -869 | 4/4 | +4.80 | -3.03 |
| S6 | A | 40 | +167 | 57.5 | +0.42 | +1.55 | 1.07 | -1,054 | 4/4 | +4.80 | -4.38 |
| S6 | B | 108 | +3,887 | 56.5 | +3.60 | +2.06 | 1.61 | -1,792 | 6/2 | +4.80 | -1.20 |
| S7 | baseline | 46 | +1,454 | 65.2 | +3.16 | +2.57 | 1.97 | -458 | 7/1 | +2.40 | +0.76 |
| S7 | A | 37 | +1,218 | 62.2 | +3.29 | +1.70 | 2.13 | -302 | 7/1 | +2.40 | +0.89 |
| S7 | B | 112 | +3,697 | 66.1 | +3.30 | +3.61 | 2.03 | -790 | 8/0 | +2.40 | +0.90 |
| S8 | baseline | 152 | +77 | 48.7 | +0.05 | -0.55 | 1.02 | -1,738 | 4/4 | +0.68 | -0.63 |
| S8 | A | 196 | +704 | 50.0 | +0.36 | -0.02 | 1.13 | -1,747 | 4/4 | +0.68 | -0.32 |
| S8 | B | 91 | -738 | 46.2 | -0.81 | -1.18 | 0.77 | -1,352 | 3/5 | +0.68 | -1.49 |
| S9 | baseline | 118 | +2,141 | 38.1 | +1.81 | -7.36 | 1.16 | -4,336 | 4/4 | +8.96 | -7.15 |
| S9 | A | 138 | +5,742 | 40.6 | +4.16 | -6.71 | 1.39 | -4,123 | 6/2 | +8.96 | -4.80 |
| S9 | B | 102 | +1,203 | 35.3 | +1.18 | -8.98 | 1.10 | -4,153 | 4/4 | +8.96 | -7.78 |
| S10 | baseline | 99 | +180 | 56.6 | +0.18 | +0.64 | 1.12 | -376 | 5/3 | +0.57 | -0.39 |
| S10 | A | 189 | +336 | 54.5 | +0.18 | +0.52 | 1.13 | -485 | 6/2 | +0.57 | -0.39 |
| S10 | B | 34 | +197 | 58.8 | +0.58 | +0.82 | 1.38 | -292 | 4/4 | +0.57 | +0.01 |
| S11 | baseline | 15 | +264 | 33.3 | +1.76 | -3.30 | 1.36 | -550 | 1/0 | +1.03 | +0.73 |
| S11 | A | 20 | +260 | 30.0 | +1.30 | -3.10 | 1.25 | -585 | 1/0 | +1.03 | +0.27 |
| S11 | B | 12 | +783 | 50.0 | +6.53 | +1.75 | 2.92 | -388 | 1/0 | +1.03 | +5.50 |
| S11 | C | 15 | -134 | 33.3 | -0.89 | -5.88 | 0.86 | -700 | 0/1 | -1.61 | +0.72 |
| S12 | baseline | 11 | +3,176 | 100.0 | +28.88 | +19.96 | — | 0 | 4/0 | +5.32 | +23.56 |
| S12 | A | 26 | +3,181 | 65.4 | +12.23 | +4.45 | 3.91 | -984 | 4/0 | +5.32 | +6.92 |

### Reading the table

**Clears the always-long benchmark on more than one variant**

- **S4 AI infrastructure & power** — the standout: +4.3 to +5.5% excess per trade with the volume filter, profit factor above 4, seven of eight names positive, and the smallest drawdowns of any breakout basket. Worth running in the Lab first.
- **S1 leveraged-ETF pullback** — 10% and 15% depths clear the benchmark (+1.7 / +2.6%), all eight ETFs positive; 7% does not (−0.5%). Dropping the 20% target improves excess (+1.7 vs +1.1). The deployed setting is not an island, but the shallow neighbour is weaker, so keep the depth at 10% or above.
- **S7 defense** — small but consistent excess (+0.8 to +0.9%) across all three variants with modest drawdowns. Edge does not require high beta, which supports "breakout" over "beta" as the driver.
- **S3 semiconductors** — only the no-volume variant clears (+2.2%); the volume-filtered baseline is flat against the benchmark.
- **S11 BTC** — the 50-session breakout with a 1.5x volume filter is +5.5% excess at 240 bp, but on 12 trades; the plain 50-session version survives 500 bp only barely. Descriptive, not validated.

**Does not clear the benchmark**

- **S2 leveraged-ETF breakout** (−1 to −6%): breakouts on leveraged ETFs underperform simply holding them with the same exits.
- **S6 high-beta software** (−1 to −4%) and **S9 crypto-equity pullback** (−5 to −8%): both baskets went up a lot; the entry rules captured less of it than always-long did.
- **S8 mega-cap dip** and **S10 broad-ETF pullback**: near zero either way. Short-hold pullback buying at 25–50 bp has no measurable edge here.

**Two findings that contradict the board's folklore**

1. **The 2x volume filter did not help on new baskets.** The no-volume variant produced more trades and higher raw P&L in every breakout basket, and higher excess in S3 and S7. Only in S4 did the filter raise excess per trade (at the cost of two thirds of the trades). The library's "volume improves P&L" pattern looks specific to the quantum and miner baskets it was tuned on.
2. **Raw P&L is nearly meaningless in this window.** Always-long returned +4 to +9% per 30-session hold on every high-beta basket. Any breakout or pullback rule that stays long a similar fraction of the time will show thousands of dollars of "profit". The Lab does not report this benchmark; ask for it in prompts, or compare against the local run.

### Caveats

- One regime. Nothing here has seen a bear market.
- Baskets were chosen in 2026. S4 in particular is a list of names known to have run; the excess-over-always-long framing removes the basket's drift but not the selection.
- Pullback numbers use the local definition, which is not yet confirmed against the Lab.
- Fewer than 30 trades in S2-baseline, S3-A, S11, S12-baseline: descriptive only.
- No slippage or spread beyond the flat bps; leveraged ETFs and small caps are optimistic at 25–50 bp.

## 5. Suggested Lab order after this pass

1. **S4** (baseline and variant A), then **S1** (baseline and B) and **S7** — the three with positive excess on more than one variant.
2. **S3 variant B** and **S3 baseline** together, to see whether the Lab agrees that the volume filter subtracts.
3. **S12** as the control and as the SMA calibration point.
4. Skip S2, S6, S9 unless you want the Lab's numbers as negative controls; S8 and S10 are near-zero locally and low priority.
5. S11 only once, at 240 bp.

Run each Lab prompt unchanged, then compare against the local `.md` for that spec. Where the two disagree by more than a few trades, that is the next calibration target.

## 6. Files

- Engine: `research/bounded_replay/{data,engine,metrics,report,cli}.py`, tests in `research/bounded_replay/tests/` (13 synthetic-bar tests, no network).
- Targets: `research/bounded_replay/targets/T1..T6.json`; shortlist: `research/bounded_replay/specs/S1..S12.json`.
- Results: `$ROOT/artifacts/backtests/<spec>/`, summary table `summary-2026-09-06.md`, calibration grids `calibration/`.
- Library snapshot: `$ROOT/artifacts/backtests/upthriving-library-2026-09-06.json` (225 rows: title, template, symbols, author, date, P&L, trades, win rate, average return, drawdown, and the visible part of the assumption line). Target and cost fields were cut by the page's rendering and are not in the snapshot.
- Prompt pack: `docs/research/2026-09-06-strategy-lab-prompt-pack.md`.
