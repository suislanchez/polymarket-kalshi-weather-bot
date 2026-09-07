# Strategy Lab prompt pack — simple strategies only

**Prepared:** 2026-09-06 · **For:** the Upthriving Strategy Lab (three bounded templates) and the local replay engine in `research/bounded_replay/`.
**Status:** research only. Nothing here is a trading recommendation; every number the Lab returns is a fixed-size signal replay, not an investable portfolio.

## 1. What the evidence says (consolidated)

Sources: the 225-strategy shared library, the 15 deployed/shadow strategy configs, your Sep 1 Strategy Lab session, the Hermes 69-candidate research run, and outside backtests (StatOasis 33-year SPY Donchian study, QuantifiedStrategies mean-reversion catalog, CFA Institute volume-breakout note).

**Works on this platform**

- Long-lookback breakouts (30–50 sessions) on small, high-beta thematic baskets. 87% of 132 breakout tests were profitable; median +$4,097.
- Volume confirmation around 2x the prior-lookback average volume improved both P&L and drawdown on every top result.
- No profit target (let winners run) beat 20–30% targets on breakouts.
- Pullback recovery has the highest hit rate (median win rate 59%) and the mildest drawdowns (median −8.9%), with smaller payoffs.
- Fixed-hold exits are fine. The 33-year SPY study found a plain 20-bar hold beat the classic Donchian channel exit on both return and drawdown.
- Leveraged ETFs as a basket: 92% of 25 tests profitable.

**Does not work**

- SMA crossover is the weak template (61% profitable, median +$490) and the source of most losers.
- Very short lookbacks and holds, high trade counts. Every strategy with 500+ trades lost money. "Three down days" style patterns earn ~0.13% per trade before costs and cannot survive 25 bp.
- Crypto pairs at the account's real 240 bp round trip. Nearly every Coinbase test lost.
- Bonds, rates, VIX products, energy, solar, commodities, metals (20–40% profitable, negative medians).
- Broad-index breakouts: the SPY 20-day breakout's average forward return fell from +0.85% (1993–99) to +0.02% (2020–26). The edge lives in higher-beta names now.
- Anything requiring ranking, rotation, cash allocation, fundamentals, events, or a cross-asset regime filter. The Lab flattens all of those into one price rule and the result tells you nothing about the thesis.

**Caveats that apply to every result**

- Baskets chosen in 2026 know which themes ran. Results measure whether the *recipe* is robust across baskets, not whether the basket had ex-ante alpha.
- Three years is one regime (a strong bull market with two sharp corrections).
- The "standalone" column is unharvestable; capital competition inside the shared pool cut most strategies by 90–100%. Read the shared column.
- Fewer than 30 trades is a description, not a validation.

## 2. Rules for every prompt

1. Maximum three-year window. Same parameters on every symbol. At most three preregistered variants.
2. Fixed $1,000 per signal. 25 bp round trip for ETFs, 50 bp for single stocks, 240 bp then 500 bp for Coinbase.
3. Report each ticker separately. Never sum across tickers into a "portfolio."
4. Require trade count, net average return per trade, median return, payoff ratio, profit factor, maximum drawdown, and results by year.
5. Ask the Lab to state its exact template definitions before running (recovery average, pullback measurement, normal-volume measure). This is how we verify the local engine matches.
6. Publish each test once under the name given. If the Lab reduces two prompts to the same proxy, it must say so and not publish the duplicate.
7. Advance a strategy only if net expectancy is positive across several tickers and the neighboring variants agree. Do not tune further to rescue a failed baseline.

## 3. The shortlist

### Tier 1 — robustness checks on what already works

#### S1 · Leveraged-ETF pullback neighborhood
*Template:* pullback recovery · *Basket:* TQQQ, UPRO, SOXL, FAS, LABU, TECL, CURE, NUGT
*Why:* the deployed Leveraged Bull Pullback uses 10% pullback / 30-SMA reclaim / 20% stop / 20% target. This checks whether 10% is a parameter island and whether removing the target helps here as it did for breakouts.

> Test a pullback recovery on TQQQ, UPRO, SOXL, FAS, LABU, TECL, CURE, and NUGT over the maximum three-year period. Before running, state exactly how the template measures the pullback (from which high, over which lookback) and which moving-average period defines "recovery above average." Baseline: require a 10% pullback, enter on the next close after price recovers above the 30-session simple moving average, no volume confirmation, hold a maximum of 30 sessions, 20% stop, no profit target, fixed $1,000 per signal, 25 bp round-trip cost. Run only two preregistered variants: (A) 7% pullback and (B) 15% pullback, everything else unchanged. Report each ETF separately with trade count, net average return per trade, median return, payoff ratio, profit factor, maximum drawdown, and results by year. Publish once as "S1 Leveraged ETF Pullback Neighborhood" and do not relabel.

*Advance only if:* all three pullback depths are positive on most ETFs and the no-target baseline is not worse than the deployed 20%-target version.

#### S2 · Leveraged-ETF breakout
*Template:* price breakout · *Basket:* same eight
*Why:* leveraged ETFs were 92% profitable as a theme; this applies the breakout recipe to a basket the bot already trades.

> Test a price breakout on TQQQ, UPRO, SOXL, FAS, LABU, TECL, CURE, and NUGT over the maximum three-year period. Before running, confirm the breakout template supports volume confirmation and state its normal-volume measure; if unsupported, return UNSUPPORTED and do not substitute. Baseline: enter on the next close after a close above the prior 50-session high with volume at least 1.5x normal, hold a maximum of 30 sessions, 20% stop, no profit target, fixed $1,000 per signal, 25 bp round-trip cost. Run only two preregistered variants: (A) 30-session lookback with the same 1.5x volume filter; (B) 50-session lookback with no volume filter. Report each ETF separately with trade count, net average return per trade, median return, payoff ratio, profit factor, maximum drawdown, and results by year. Publish once as "S2 Leveraged ETF 50-Session Volume Breakout" and do not relabel.

*Advance only if:* positive on more than half the ETFs, 30- and 50-session variants agree in sign, and the volume filter does not merely delete most trades.

#### S3 · Winning-recipe transfer: semiconductors
*Template:* price breakout · *Basket:* NVDA, AMD, AVGO, MU, TSM, LRCX, AMAT, KLAC
*Why:* the best risk-adjusted result on the board (Full-History Quantum L30 Volume-2.0) is a 30-session breakout with 2x volume and no target. Same recipe, different high-beta basket.

> Test a price breakout on NVDA, AMD, AVGO, MU, TSM, LRCX, AMAT, and KLAC over the maximum three-year period. Before running, state the normal-volume measure the template uses. Baseline: enter on the next close after a close above the prior 30-session high with volume at least 2.0x normal, hold a maximum of 30 sessions, 20% stop, no profit target, fixed $1,000 per signal, 50 bp round-trip cost. Run only two preregistered variants: (A) 50-session lookback with the same 2.0x filter; (B) 30-session lookback with no volume filter. Report each stock separately with trade count, net average return per trade, median return, payoff ratio, profit factor, maximum drawdown, and results by year. Publish once as "S3 Semiconductor 30-Session Volume-2.0 Breakout" and do not relabel.

*Advance only if:* positive after 50 bp on at least five of eight names and not driven by NVDA alone.

### Tier 2 — the recipe on new thematic baskets

All four use the S3 prompt with the basket and name swapped. Baskets are limited to names with full history since September 2023.

#### S4 · AI infrastructure and power
*Basket:* VRT, ANET, SMCI, DELL, CEG, VST, NRG, ETN · *Name:* "S4 AI Infrastructure 30-Session Volume-2.0 Breakout"

#### S5 · Nuclear and uranium
*Basket:* CCJ, URA, UEC, LEU, SMR, DNN, NXE, URNM · *Name:* "S5 Nuclear Uranium 30-Session Volume-2.0 Breakout"

#### S6 · High-beta software
*Basket:* CRWD, PANW, ZS, NET, DDOG, SNOW, PLTR, MDB · *Name:* "S6 High-Beta Software 30-Session Volume-2.0 Breakout"

#### S7 · Defense and drones (lower-beta control)
*Basket:* KTOS, AVAV, LHX, RTX, LMT, NOC, GD, HII · *Name:* "S7 Defense 30-Session Volume-2.0 Breakout"
*Why:* if the recipe only works on high-beta baskets, S7 should be flat. That tells you whether the edge is "breakout" or "beta."

*Advance rule for Tier 2:* run S3 first. If S3 fails, do not run S4–S7. If S3 passes, run all four and count how many baskets are positive. Three of four is a recipe; one of four is a theme.

### Tier 3 — pullback flavors

#### S8 · Mega-cap dip buy
*Template:* pullback recovery · *Basket:* AAPL, MSFT, NVDA, AMZN, META, GOOGL, AVGO, TSLA
*Why:* the closest expressible proxy for the well-documented "RSI(2) dip above the 200-day" idea: buy modest dips in leaders, short hold, tight stop.

> Test a pullback recovery on AAPL, MSFT, NVDA, AMZN, META, GOOGL, AVGO, and TSLA over the maximum three-year period. Before running, state exactly how the template measures the pullback and which moving-average period defines recovery. Baseline: require a 7% pullback, enter on the next close after price recovers above the 20-session simple moving average, no volume confirmation, hold a maximum of 10 sessions, 7% stop, no profit target, fixed $1,000 per signal, 50 bp round-trip cost. Run only two preregistered variants: (A) 5% pullback and (B) 10% pullback. Report each stock separately with trade count, net average return per trade, median return, payoff ratio, profit factor, maximum drawdown, and results by year. Publish once as "S8 Mega-Cap 7% Dip Reclaim-20" and do not relabel.

*Advance only if:* win rate above 55% with positive net expectancy after 50 bp on most names, and the 5/7/10 neighborhood agrees.

#### S9 · Crypto-equity pullback
*Template:* pullback recovery · *Basket:* MSTR, COIN, MARA, RIOT, CLSK, HUT, IREN, WULF
*Why:* breakouts worked on this theme (74% profitable); this tests the mean-reversion side of the same basket without paying Coinbase fees.

> Test a pullback recovery on MSTR, COIN, MARA, RIOT, CLSK, HUT, IREN, and WULF over the maximum three-year period. Before running, state exactly how the template measures the pullback and which moving-average period defines recovery. Baseline: require a 15% pullback, enter on the next close after price recovers above the 20-session simple moving average, no volume confirmation, hold a maximum of 30 sessions, 25% stop, no profit target, fixed $1,000 per signal, 50 bp round-trip cost. Run only two preregistered variants: (A) 10% pullback and (B) 20% pullback. Report each stock separately with trade count, net average return per trade, median return, payoff ratio, profit factor, maximum drawdown, and results by year. Publish once as "S9 Crypto-Equity 15% Pullback Reclaim-20" and do not relabel.

*Advance only if:* positive on most names and maximum drawdown per ticker stays under 40%.

#### S10 · Broad-ETF pullback (boring-asset control)
*Template:* pullback recovery · *Basket:* SPY, QQQ, IWM, XLK, XLF, XLE, TLT, GLD
This is Test 5 from the earlier guide, unchanged. It exists to show whether pullback recovery has any edge on low-beta assets at 25 bp.

> Test a pullback recovery on SPY, QQQ, IWM, XLK, XLF, XLE, TLT, and GLD over the maximum three-year period. Before running, state the exact moving-average period and exact recovery condition used by the template. Baseline: require a 5% pullback, enter on the next close after the supported recovery-above-average trigger, no volume confirmation, hold 10 sessions, 5% stop, no profit target, fixed $1,000 per signal, 25 bp round-trip cost. Run only two variants: 3% pullback and 8% pullback. Report each ETF separately with trade count, net average return per trade, median return, payoff ratio, profit factor, maximum drawdown, and results by year. Publish once as "S10 Broad ETF 5% Pullback Control" and do not relabel.

### Tier 4 — one crypto test and one negative control

#### S11 · BTC-USDC 50-session breakout, no target
Test 7 from the earlier guide, adjusted to the recipe (50 sessions, no target). The only crypto run; the 240 bp floor is the account's real cost.

> Test a price breakout on BTC-USDC over the maximum three-year period. Baseline: enter on the next close after a close above the prior 50-session high, hold a maximum of 30 sessions, 20% stop, no profit target, fixed $1,000 per signal, 240 bp round-trip cost. Run only two preregistered variants: (A) 30-session lookback; (B) 50-session lookback with volume at least 1.5x the prior-50-session average. Then rerun the best preregistered variant at 500 bp round-trip cost. Report gross and net expectancy, trade count, average win and loss, payoff ratio, profit factor, maximum drawdown, and results by year. Publish once as "S11 BTC-USDC 50-Session Breakout No-Target" and do not relabel.

*Advance only if:* positive at 240 bp, not dependent on one run, and not collapsing at 500 bp.

#### S12 · SMA 20/100 negative control
Expected to be weak. If this looks great, distrust the tester.

> Test a moving-average crossover on TQQQ, SOXL, QQQ, and SPY over the maximum three-year period. Baseline: fast SMA 20, slow SMA 100, enter on the next close after the bullish crossover, hold 30 sessions, no stop, no profit target, fixed $1,000 per signal, 25 bp round-trip cost. Run one variant with fast SMA 10 and slow SMA 50. Report each ETF separately with trade count, net average return per trade, median return, payoff ratio, profit factor, maximum drawdown, and results by year. Label the output "30-session post-crossover signal replay." Publish once as "S12 SMA 20/100 Control" and do not relabel.

## 4. Suggested run order

1. S1, S2, S3 (cheap, highest information).
2. S10 and S12 (controls) alongside, so you know what "no edge" looks like on this tester.
3. S4–S7 only if S3 passes.
4. S8, S9.
5. S11 last, and only once.

## 5. What was dropped, and why

- The 49 "do not force" items from the earlier guide (ranking, fundamentals, events, calendar, pairs, options, intraday, order book, prediction markets, ML). The Lab cannot express them.
- The 14 proxy-only factor and rotation theses. Their results would describe the proxy, not the thesis; three of them already collapsed into one identical test on Sep 1.
- Guide Tests 1–4 (broad ETF breakout and SMA studies). The library and the 33-year SPY study both say broad-index breakout and crossover edges are near zero now; the same effort spent on S1–S3 is more informative.
- Any lookback under 20 sessions, any second crypto pair, bonds/energy/commodity/metal baskets, and more quantum variants (14 exist; more is curve-fitting).

## 6. How the local engine relates

`research/bounded_replay/specs/S1..S12.json` hold these exact parameters, so the same test can be run locally against Alpaca SIP daily bars. `targets/T1..T5.json` hold five Upthriving results with fully known parameters; `cli.py calibrate` reports how closely the local engine reproduces them. Until calibration shows a match, treat local and Lab numbers as two independent opinions, not one confirmed number.

## 7. Local first pass (added after calibration)

The local engine reproduces the Lab's breakout template exactly on your Sep 1 test (95 trades, +$1,447.64 vs +$1,442.21). Running S1–S12 locally with the Lab's semantics and an always-long benchmark changes the run order:

- **Run first:** S4 (AI infrastructure) — +4 to +5% excess per trade over always-long, profit factor above 4. Then S1 (leveraged pullback, 10% and 15% depths, no target) and S7 (defense), both positive on every variant.
- **Run as a volume A/B:** S3 baseline vs variant B. Locally the no-volume variant wins; the 2x filter did not help on any new basket.
- **Run as controls:** S12 (SMA) and S10.
- **Deprioritise:** S2, S6, S9 (all below always-long locally), S8 (flat).
- **Ask every prompt for the always-long comparison** in this window; without it, raw P&L is uninformative.

Details, tables and caveats: `docs/research/2026-09-06-local-replay-vs-upthriving.md`.
