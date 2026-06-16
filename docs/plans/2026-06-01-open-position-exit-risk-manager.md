# Open-Position Exit / Cash-Out Risk Manager Implementation Plan

> **For Hermes:** Use subagent-driven-development skill to implement this plan task-by-task after Kayvon approves it. Keep everything simulation-only unless Kayvon explicitly authorizes live execution.

**Goal:** Add a cross-vertical open-position risk manager that can mark open paper positions to market and recommend or execute paper cash-outs before a position goes to zero when the thesis is broken.

**Architecture:** Keep entry signals, settlement, and early exits as separate concepts. Add a side-effect-free risk-analysis layer that inspects open positions, refreshes market/source/model evidence, computes hold-vs-exit EV, and emits auditable exit recommendations. Only a separate paper-exit executor mutates the ledger, and only when configured rules pass; live order placement remains out of scope.

**Tech Stack:** Python, FastAPI, SQLAlchemy/SQLite, pytest, TypeScript/React dashboard, Polymarket Gamma/CLOB public APIs, Kalshi public market data where available.

---

## Executive Summary

The current bot has good entry gates and final settlement handling, but it does **not** yet protect open positions after entry. A weather trade can be opened in paper mode, drift from 45% to 10%, and the bot will wait until final settlement instead of salvaging remaining value.

This plan adds a dedicated **Open Position Risk Manager** across BTC, weather, and RT/entertainment:

1. **Mark every open paper trade to market** using current bid/ask/depth for the held side.
2. **Recompute the thesis** using the vertical's latest model/source evidence.
3. **Compare hold EV vs exit EV** after spread, liquidity, timing, and source uncertainty.
4. **Emit structured exit recommendations** such as `hold`, `watch`, `reduce`, or `exit`.
5. **Execute paper exits only when the policy is decisive**, preserving all evidence and avoiding over-trading.
6. **Display open-position risk on the dashboard** so we see not just final PnL, but also unrealized losses, salvage opportunities, and why positions were held/exited.

This is exactly where a bot can outperform a human: it can constantly monitor open risk, reprice the position, and act without denial/anchoring when the original bet is no longer defensible.

---

## Current State Verified Before Planning

Inspected files:

- `backend/models/database.py`
  - `Trade` currently has entry fields, final settlement fields, `result`, and `pnl`.
  - No exit/cash-out fields exist.
- `backend/core/scheduler.py`
  - BTC and weather jobs create paper trades.
  - Settlement job only checks final market resolution.
- `backend/core/settlement.py`
  - `settle_pending_trades()` marks trades `win/loss/push` only after market resolution.
  - No mark-to-market or early-close path.
- `backend/core/signals.py`
  - BTC signal generator already has structured no-trade gates, CLOB spread/depth context, and source metadata.
- `backend/core/weather_signals.py`
  - Weather signal generator already has structured no-trade gates, spread/depth, source/station metadata, composite score.
- `backend/config.py`
  - Current risk config has entry-size/loss controls, but no exit/cash-out policy config.
- Runtime DB check:
  - `tradingbot.db` currently contains 7 pending weather paper trades and no settled trades.

Conclusion: implement this as new risk-management plumbing rather than trying to overload settlement.

---

## Core Design Principles

### 1. Exit logic is not settlement logic

Final settlement answers: **What did the market resolve to?**

Exit logic answers: **Given current price + updated evidence, should we salvage value before resolution?**

These must remain separate. Early exits should set fields such as `closed_early=true`, while normal settlement uses `settled=true` only when the market resolves.

### 2. Paper-first, live-safe

This plan only implements **paper exits**. A future live execution layer can reuse the recommendation engine, but live orders need extra authorization, venue-specific order handling, and cancel/fill reconciliation.

### 3. The risk manager should be side-effect-free until the final executor

Most logic should be pure/testable:

- input: trade + current market quote + refreshed model/source evidence
- output: recommendation + reason list + EV numbers

Only one narrow function should mutate the DB to record a paper exit.

### 4. Do not exit merely because odds moved against us

A drop from 45% to 10% is a warning, not automatically an exit. We exit when **the thesis is broken** or **exit EV is superior** after costs.

Examples:

- Bad exit: market drifts to 10% but our final-source model still says 35%, liquidity is thin, spread is wide → maybe hold/watch.
- Good exit: market drifts to 10%, our model now says 5%, final source confirms opposite direction, and there is bid liquidity to sell → exit/reduce.

### 5. Each vertical needs different evidence

A generic price stop-loss is not enough. The bot should know *why* the trade is wrong.

- Weather: final/source station readings, forecast updates, station anomaly checks, local-day timing.
- BTC: short-window price/microstructure, time-to-close, Chainlink boundary-source coverage.
- RT/Entertainment: direct source-state updates, review count/score velocity, cutoff/settlement source timing, box office direct source state.

---

## Proposed Data Model

### Modify `backend/models/database.py` — `Trade`

Add early-exit / mark-to-market fields:

```python
# Open-position exit / cash-out tracking
closed_early = Column(Boolean, default=False, index=True)
exit_time = Column(DateTime, nullable=True)
exit_price = Column(Float, nullable=True)          # executable sell price for held side
exit_size = Column(Float, nullable=True)           # for partial exits; default full size
exit_reason = Column(String, nullable=True)
exit_policy = Column(String, nullable=True)        # e.g. weather_thesis_broken_v1
exit_evidence = Column(JSON, nullable=True)        # structured recommendation snapshot
unrealized_pnl = Column(Float, nullable=True)
last_mark_price = Column(Float, nullable=True)
last_mark_time = Column(DateTime, nullable=True)
last_risk_action = Column(String, nullable=True)   # hold/watch/reduce/exit
last_risk_reasons = Column(JSON, nullable=True)
```

Schema guard should also add these columns for existing SQLite DBs.

### Result values

Keep current `result='pending'|'win'|'loss'|'push'`, but allow:

- `result='exited'` for early full cash-outs.
- Optional later: `result='partially_exited'` if we implement partial exits.

For phase 1, implement **full paper exits only**. Add partial-exit-friendly fields but do not implement partial fills yet unless easy.

---

## Proposed New Modules

### `backend/core/position_risk.py`

Pure shared risk primitives:

- `PositionQuote`
- `PositionEvidence`
- `ExitRecommendation`
- `calculate_unrealized_pnl()`
- `calculate_exit_pnl()`
- `calculate_hold_ev()`
- `choose_exit_action()`

Recommended action enum:

```python
class RiskAction(str, Enum):
    HOLD = "hold"
    WATCH = "watch"
    REDUCE = "reduce"
    EXIT = "exit"
```

Phase 1 can compute `REDUCE` but execute it as `WATCH` unless partial exits are explicitly enabled.

### `backend/core/position_risk_btc.py`

BTC-specific refresh and policy:

- Fetch current active BTC market by `event_slug` / `market_ticker`.
- Determine held side current sell/bid price.
- Recompute model probability using current microstructure when market still open.
- Apply BTC-specific exit rules:
  - Near expiry + thesis broken → exit if executable.
  - Model flips direction strongly → exit.
  - Held-side bid below hard stop and model agrees with market → exit.
  - Missing Chainlink/source evidence keeps exit conservative unless price collapse is severe.

### `backend/core/position_risk_weather.py`

Weather-specific refresh and policy:

- Fetch current market quote by venue/market id/token where possible.
- Recompute weather probability with current forecast/source mapping.
- Use station/source metadata from the trade's linked signal or market row.
- Apply weather-specific exit rules:
  - Direct/final source or near-final source strongly contradicts held side → exit.
  - Model probability for held side falls below hard threshold → exit if bid exists.
  - Forecast distribution moves outside threshold buffer → watch/exit depending on time to final and liquidity.
  - Station anomaly or missing final-source context → watch, not auto-exit, unless price/source/model all agree.

### `backend/core/position_risk_entertainment.py`

RT/entertainment-specific refresh and policy:

- Phase 1 probably only supports open positions if any exist later; current ledger has none.
- Use direct source-state rows and market quotes.
- Exit rules:
  - Direct RT score/review-count velocity crosses threshold against us with enough review count → exit.
  - Box-office direct source/gross evidence contradicts held bucket → exit.
  - Low review count/no displayed score → watch, not exit, unless market + model both move strongly.

### `backend/core/position_exit_executor.py`

DB mutation boundary:

- `record_paper_exit(db, trade, recommendation)`
- Marks trade as `closed_early=True`, `settled=True`, `result='exited'`, `exit_time`, `exit_price`, `pnl`.
- Updates `BotState.bankroll` and `BotState.total_pnl` using realized exit PnL.
- Does **not** place live orders.

Important: A paper exit is effectively a settlement for the paper ledger, but it should be distinguishable from platform resolution.

### `backend/core/open_position_monitor.py`

Scheduler-facing orchestrator:

- Query open trades: `settled == False AND closed_early == False`.
- Route by `market_type`.
- Refresh risk recommendation.
- Persist latest mark-to-market fields on every run.
- Execute paper exit only if:
  - recommendation action is `EXIT`,
  - `settings.PAPER_AUTO_EXIT_ENABLED=True`,
  - sell price/depth meets minimum execution gates,
  - no missing critical evidence blocker forbids auto-exit.

---

## Exit Policy Defaults

Add to `backend/config.py`:

```python
# Open-position risk manager
PAPER_POSITION_RISK_ENABLED: bool = True
PAPER_AUTO_EXIT_ENABLED: bool = False  # start recommendations-only; turn on after validation
POSITION_RISK_SCAN_INTERVAL_SECONDS: int = 120

# Generic exit thresholds
EXIT_HARD_MODEL_PROB_THRESHOLD: float = 0.15       # held side model prob below this can trigger exit
EXIT_HARD_MARKET_PROB_THRESHOLD: float = 0.10      # held side market bid below this is danger zone
EXIT_MIN_SELL_PRICE: float = 0.03                  # don't fake exits into no liquidity/dust
EXIT_MAX_SPREAD: float = 0.20
EXIT_MIN_TOP_BID_SIZE: float = 5.0
EXIT_HOLD_EV_MARGIN: float = 0.02                  # exit must beat hold by 2c/share equiv unless thesis broken

# Weather-specific
WEATHER_EXIT_MODEL_PROB_THRESHOLD: float = 0.15
WEATHER_EXIT_FINAL_SOURCE_CONFIDENCE_REQUIRED: bool = True
WEATHER_EXIT_NEAR_FINAL_HOURS: float = 2.0
WEATHER_EXIT_MIN_SOURCE_ALIGNMENT: int = 2         # model + market, or source + model, etc.

# BTC-specific
BTC_EXIT_MODEL_PROB_THRESHOLD: float = 0.20
BTC_EXIT_NEAR_CLOSE_SECONDS: int = 90
BTC_EXIT_STRONG_FLIP_EDGE: float = 0.08

# Entertainment-specific
ENTERTAINMENT_EXIT_MODEL_PROB_THRESHOLD: float = 0.15
ENTERTAINMENT_EXIT_MIN_REVIEW_COUNT: int = 30
```

I recommend `PAPER_AUTO_EXIT_ENABLED=False` at first, meaning the dashboard and reports show exit recommendations but do not mutate trades. Once we trust the analysis, flip it on for paper mode.

---

## PnL Math

For a binary share bought at `entry_price` with dollar notional `size`:

- Number of shares = `size / entry_price`
- If we sell at `exit_price`, proceeds = `shares * exit_price`
- Early-exit PnL = `proceeds - size`

```python
def calculate_exit_pnl(entry_price: float, exit_price: float, size: float) -> float:
    if entry_price <= 0:
        return 0.0
    shares = size / entry_price
    proceeds = shares * exit_price
    return round(proceeds - size, 2)
```

Final-settlement PnL remains current logic:

- Win: `size * (1 - entry_price)`
- Loss: `-size * entry_price`

### Example

If we bought $100 of YES at 45c:

- Shares = 222.22
- If current bid is 10c, cash-out proceeds = $22.22
- PnL = -$77.78
- Holding to zero would be -$100
- Salvage value = $22.22

The bot should exit if updated evidence says the chance of recovery is tiny and the current 10c bid is better than hold EV.

---

## Recommendation Logic

### Shared scoring inputs

Every open-position risk check should produce:

- `held_side`: yes/no/up/down
- `entry_price`
- `current_bid_for_held_side`
- `current_ask_for_held_side`
- `current_spread`
- `top_bid_size`
- `top_ask_size`
- `current_market_probability_for_held_side`
- `model_probability_for_held_side`
- `time_to_resolution`
- `source_status`
- `thesis_status`: intact / weakened / broken / unknown
- `hold_ev`
- `exit_ev`
- `unrealized_pnl`
- `exit_pnl`
- `reasons[]`

### Generic rules

Recommend `EXIT` when all are true:

1. Held-side current bid is executable enough:
   - `exit_price >= EXIT_MIN_SELL_PRICE`
   - spread <= max spread
   - top bid size >= needed size or at least meaningful partial size
2. Evidence says thesis is broken:
   - model probability below threshold, or
   - model flipped against us by strong margin, or
   - final/direct source evidence contradicts us
3. Exit EV is better than hold EV by margin, **or** the position is likely unrecoverable.

Recommend `WATCH` when:

- Price is bad, but source/model evidence is incomplete.
- Market moved against us but our model still disagrees.
- Spread is too wide to exit cleanly.

Recommend `HOLD` when:

- Thesis remains intact.
- Hold EV exceeds exit EV.
- No strong adverse source evidence.

Recommend `REDUCE` when:

- Thesis is weakened but not broken.
- There is enough liquidity for partial salvage.
- Phase 1 should surface this but not auto-execute partial exits yet.

---

## Vertical-Specific Exit Policy

## Weather

Weather exits matter most because daily temperature/weather markets can become very obviously wrong as source data converges.

### Evidence hierarchy

1. **Final direct source**: Wunderground/HKO/NWS CLI final product matching exact market rules.
2. **Near-final source**: station readings late in the local day, but not yet official final.
3. **Independent model**: ensemble probability, updated with exact station/source mapping.
4. **Market quote**: useful but not sufficient by itself.
5. **Station anomaly check**: neighboring stations vs settlement station.

### Weather exit examples

#### Exit

- We bought YES on “Denver 70–71°F”.
- Current source/forecast says final is likely 75°F.
- Held-side bid falls to 10c.
- Model YES probability is 5%.
- Current bid has enough size.
- Recommendation: `EXIT`, reason `weather final/source evidence contradicts held bucket`.

#### Watch, not exit

- Held-side bid is 10c.
- But exact source station is unavailable or station anomaly is unresolved.
- Model says 25% and market says 10%.
- Recommendation: `WATCH`; do not auto-exit because market may be overreacting.

### Weather-specific blockers

Never auto-exit solely from price collapse if:

- settlement station/source is unknown,
- current quote is stale,
- spread is too wide,
- direct source is missing and model still gives meaningful probability,
- the market is a bucket set and bucket grouping is incomplete.

---

## BTC 5-Minute Up/Down

BTC exits are time-sensitive. Most markets have short windows, so exit logic must be fast and simple.

### Evidence hierarchy

1. Current line-level CLOB bid/ask/depth.
2. Time-to-close.
3. Current BTC microstructure model.
4. Chainlink boundary availability/status.
5. Settlement source mapping.

### BTC exit examples

#### Exit

- We bought UP at 48c.
- 90 seconds remain.
- BTC momentum flips hard down.
- Held-side bid is 18c with enough depth.
- Model UP probability is 12%.
- Recommendation: `EXIT`.

#### Hold

- Held-side bid is 18c.
- 4 minutes remain.
- Microstructure model still gives UP 35%.
- Spread is huge.
- Recommendation: `WATCH` or `HOLD` depending EV.

### BTC-specific caution

Because BTC windows are short, overactive exits may just lock in noise. Default should be:

- recommendations-only first,
- auto-exit only near close or on strong model flip,
- skip if current bid/depth is poor.

---

## RT / Entertainment

No current open RT/entertainment paper trades, but the architecture should support them.

### Evidence hierarchy

1. Direct source state: Rotten Tomatoes score/review count, The Numbers/BoxOfficeMojo gross.
2. Source velocity: score/review count deltas.
3. Cutoff/timing risk.
4. Market quote/depth.
5. Independent model probability.

### Entertainment exit examples

#### Exit

- We bought YES on RT >= 80%.
- Direct RT now shows 65% with 100 reviews.
- Held-side bid falls to 8c.
- Review velocity is stable against us.
- Recommendation: `EXIT`.

#### Watch

- RT shows 65%, but only 8 reviews.
- Market falls to 12c.
- Review count is too low for confidence.
- Recommendation: `WATCH`.

---

## Dashboard / API Changes

### API

Add:

- `GET /api/open-position-risk`
  - Returns latest risk recommendations for all open trades.
- Optional after approval: `POST /api/open-position-risk/run`
  - Runs risk scan immediately.
- Optional after approval: `POST /api/trades/{id}/paper-exit`
  - Manual paper cash-out using the latest recommendation.

Extend `/api/dashboard` with:

- `open_position_risk_summary`
- `open_position_risk_rows`

### Frontend

Add a panel near Trades / Signal Review Queue:

**Open Position Risk**

Columns:

- Market / vertical
- Direction
- Entry price
- Current exit bid
- Unrealized PnL
- Model probability for held side
- Market probability for held side
- Action: HOLD / WATCH / REDUCE / EXIT
- Reasons
- Source status

Trades table additions:

- Show `closed early` badge.
- Show `exit price` and `exit reason` if present.
- Distinguish `settled by market` vs `paper exited`.

Stats card additions:

- Realized PnL remains separate.
- Add unrealized PnL for open positions.
- Add salvage value / at-risk value if simple enough.

---

## Implementation Tasks

### Task 1: Add schema fields for paper exits and mark-to-market

**Objective:** Extend `Trade` with early-exit fields and SQLite migration guard.

**Files:**
- Modify: `backend/models/database.py`
- Test: `tests/test_trade_exit_schema.py`

**Steps:**
1. Write a failing test that initializes the DB and asserts `trades` has the new columns.
2. Run: `PYTHONPATH=. venv/bin/python -m pytest -q tests/test_trade_exit_schema.py`
3. Add ORM fields to `Trade`.
4. Extend schema guard to add columns if missing.
5. Rerun the test.

**Acceptance:** Existing DBs get columns without dropping trades.

---

### Task 2: Add pure PnL math for early exits

**Objective:** Implement tested cash-out PnL math independent of DB/API.

**Files:**
- Create: `backend/core/position_risk.py`
- Test: `tests/test_position_risk_math.py`

**Core tests:**

```python
def test_exit_pnl_salvages_value_before_zero():
    assert calculate_exit_pnl(entry_price=0.45, exit_price=0.10, size=100.0) == -77.78


def test_final_loss_would_be_worse_than_exit():
    exit_pnl = calculate_exit_pnl(0.45, 0.10, 100.0)
    final_loss = -100.0 * 0.45
    # Wait: current settlement logic treats size as notional risk, so expected comparison must
    # align with existing ledger semantics. This test should force us to standardize size semantics.
```

Important implementation note: verify current `Trade.size` semantics before finalizing math. Current settlement logic uses `size` as dollar amount staked/risked, but its loss is `-size * entry_price`, which may not match the intuitive `$100 stake at 45c` example. This must be clarified and tested before execution.

**Acceptance:** PnL math is explicit and documented; no hidden size/share ambiguity.

---

### Task 3: Standardize paper trade size semantics

**Objective:** Decide and test whether `Trade.size` means dollar cost, dollar exposure, or number of shares.

**Files:**
- Modify: `backend/core/settlement.py`
- Modify or test: `tests/test_settlement.py` or new `tests/test_trade_pnl_semantics.py`

**Recommendation:** Treat `size` as **dollar cost at entry**, because dashboard/logs currently say `size=$X`, and risk caps are dollar caps.

If so, final PnL should be:

- shares = `size / entry_price`
- win proceeds = `shares * 1.0`
- win pnl = `proceeds - size`
- loss pnl = `-size`
- exit pnl = `shares * exit_price - size`

This is more realistic than current `size * (1 - entry_price)` / `-size * entry_price` if `size` is intended as dollars deployed.

**Important:** This is a potentially behavior-changing accounting fix. If we do not want to change historical semantics yet, create helper functions for new trades only and label old PnL accordingly. I recommend fixing it now in paper mode before more trades accumulate.

**Acceptance:** One explicit test suite defines accounting semantics for final win, final loss, and early exit.

---

### Task 4: Build `ExitRecommendation` model and generic policy

**Objective:** Return auditable hold/watch/reduce/exit decisions without DB mutation.

**Files:**
- Modify: `backend/core/position_risk.py`
- Test: `tests/test_position_risk_policy.py`

**Scenarios:**

- Thesis intact -> `HOLD`.
- Market bad but source missing -> `WATCH`.
- Model probability below hard threshold + executable bid -> `EXIT`.
- Exit bid below dust/min liquidity -> `WATCH`, not fake exit.
- Exit EV beats hold EV by margin -> `EXIT`.

**Acceptance:** Generic policy is deterministic and returns structured reasons.

---

### Task 5: Add paper exit executor

**Objective:** Mutate paper ledger only when an approved recommendation exits a trade.

**Files:**
- Create: `backend/core/position_exit_executor.py`
- Test: `tests/test_position_exit_executor.py`

**Behavior:**

- Full exit only in phase 1.
- Set `closed_early=True`.
- Set `settled=True` and `result='exited'`.
- Set `exit_price`, `exit_time`, `exit_reason`, `exit_evidence`.
- Set `pnl` to realized exit PnL.
- Update `BotState.bankroll` and `total_pnl` once.
- Ensure calling executor twice on same trade is idempotently rejected.

**Acceptance:** Paper exit records salvage PnL and cannot double-count.

---

### Task 6: BTC open-position risk analyzer

**Objective:** Produce BTC exit recommendations for pending BTC trades.

**Files:**
- Create: `backend/core/position_risk_btc.py`
- Test: `tests/test_position_risk_btc.py`

**Approach:**

- Build pure helper that accepts fake current market + fake model output.
- Later wire live fetchers.
- Identify held side's current sell bid:
  - if held `up`, use current `up_bid`.
  - if held `down`, use current `down_bid`.
- Compare model probability for held side to thresholds.
- Include time-to-close.

**Acceptance:** BTC tests cover model flip, near-close urgency, wide-spread watch state.

---

### Task 7: Weather open-position risk analyzer

**Objective:** Produce weather exit recommendations for pending weather trades.

**Files:**
- Create: `backend/core/position_risk_weather.py`
- Test: `tests/test_position_risk_weather.py`

**Approach:**

- Start with pure helper using injected quote/evidence objects.
- Use weather-specific source confidence fields:
  - settlement source known?
  - station known?
  - direct/final source captured?
  - model probability for held side?
  - source/model/market alignment count?
- Add policy cases:
  - direct source contradicts held side + held bid exists -> `EXIT`.
  - market collapse but source/model unknown -> `WATCH`.
  - model below threshold but source incomplete -> `WATCH` unless price collapse is severe and model confidence is high.

**Acceptance:** Weather analyzer is conservative without source context but decisive when source+model agree we are wrong.

---

### Task 8: Entertainment open-position risk analyzer

**Objective:** Support future RT/box-office exits even though current ledger has no entertainment trades.

**Files:**
- Create: `backend/core/position_risk_entertainment.py`
- Test: `tests/test_position_risk_entertainment.py`

**Approach:**

- RT score threshold crossing with sufficient review count -> `EXIT`.
- Low review count -> `WATCH`.
- Box-office direct source contradicts held bucket -> `EXIT`.

**Acceptance:** Entertainment exits are source-driven and do not fire on low-confidence source states.

---

### Task 9: Open position monitor orchestrator

**Objective:** Route all open trades through the right risk analyzer and optionally execute paper exits.

**Files:**
- Create: `backend/core/open_position_monitor.py`
- Modify: `backend/core/scheduler.py`
- Test: `tests/test_open_position_monitor.py`

**Behavior:**

- Query `Trade.settled == False` and `closed_early == False`.
- Route by `market_type`.
- Persist mark-to-market fields even when not exiting.
- Execute paper exits only if `PAPER_AUTO_EXIT_ENABLED=True`.
- Log summary counts: hold/watch/reduce/exit.

**Scheduler:**

Add job:

```python
scheduler.add_job(
    open_position_risk_job,
    IntervalTrigger(seconds=settings.POSITION_RISK_SCAN_INTERVAL_SECONDS),
    id="open_position_risk",
    replace_existing=True,
    max_instances=1,
)
```

**Acceptance:** With auto-exit disabled, monitor updates marks/recommendations only. With auto-exit enabled in test, it exits exactly eligible trades.

---

### Task 10: API response schemas

**Objective:** Expose open-position risk rows without importing heavy app dependencies in schema tests.

**Files:**
- Modify: `backend/api/schemas.py`
- Modify: `backend/api/main.py`
- Test: `tests/test_api_response_models.py`

**Fields:**

```python
class OpenPositionRiskRow(BaseModel):
    trade_id: int
    market_type: str
    market_ticker: str
    event_slug: str | None
    direction: str
    entry_price: float
    size: float
    current_exit_price: float | None
    unrealized_pnl: float | None
    model_probability_for_held_side: float | None
    market_probability_for_held_side: float | None
    action: str
    reasons: list[str]
    source_status: str | None
    checked_at: datetime
```

**Acceptance:** `/api/dashboard` can include risk rows; schema-only tests serialize them.

---

### Task 11: API endpoints

**Objective:** Let operator inspect risk and manually run risk scan.

**Files:**
- Modify: `backend/api/main.py`
- Test: `tests/test_api_open_position_risk.py`

**Endpoints:**

- `GET /api/open-position-risk`
- `POST /api/open-position-risk/run`
- `POST /api/trades/{trade_id}/paper-exit` — manual paper-only exit, uses latest recommendation or requires explicit override flag.

**Acceptance:** Manual exit endpoint refuses when no executable current exit price exists unless override is explicitly passed.

---

### Task 12: Frontend open-position risk panel

**Objective:** Make exit recommendations visible and actionable in dashboard.

**Files:**
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/components/TradesTable.tsx`
- Possibly create: `frontend/src/components/OpenPositionRiskPanel.tsx`

**UI:**

- Add risk panel with HOLD/WATCH/REDUCE/EXIT badges.
- Show current exit bid and unrealized PnL.
- Show reasons in expandable detail.
- Show `closed early` in trades table.

**Acceptance:** `npm run build` passes and dashboard fallback/mock data includes new fields.

---

### Task 13: Paper-mode validation run

**Objective:** Validate recommendations before enabling auto-exit.

**Commands:**

```bash
PYTHONPATH=. venv/bin/python -m pytest -q tests/test_position_risk_math.py tests/test_position_risk_policy.py tests/test_position_risk_weather.py tests/test_position_risk_btc.py tests/test_position_exit_executor.py tests/test_open_position_monitor.py
PYTHONPATH=. venv/bin/python -m pytest -q
cd frontend && npm run build
```

Then run a manual risk scan against current DB with `PAPER_AUTO_EXIT_ENABLED=false`.

**Acceptance:** Report current 7 pending weather trades with risk recommendations but no DB exits.

---

### Task 14: Turn on paper auto-exit only after review

**Objective:** After Kayvon reviews recommendation behavior, enable paper auto-exits.

**Steps:**

1. Review risk recommendations for the current 7 pending weather trades.
2. Check whether proposed exits match human intuition.
3. If acceptable, set `PAPER_AUTO_EXIT_ENABLED=true` in local paper mode only.
4. Run monitor.
5. Verify trades exited or held exactly according to policy.

**Acceptance:** Auto-exit is enabled only after operator review; no live orders.

---

## Verification Checklist

Before claiming implementation complete:

- [ ] Schema fields added and existing DB migrates safely.
- [ ] Accounting semantics are explicit and tested.
- [ ] Early-exit PnL and final-settlement PnL are consistent.
- [ ] Generic policy tests cover hold/watch/reduce/exit.
- [ ] Weather tests cover thesis-broken vs source-missing cases.
- [ ] BTC tests cover near-close/model-flip behavior.
- [ ] Entertainment tests cover RT review-count/source-confidence behavior.
- [ ] Paper exit executor cannot double-count PnL.
- [ ] Scheduler risk job respects `PAPER_AUTO_EXIT_ENABLED`.
- [ ] Dashboard/API expose risk rows and closed-early fields.
- [ ] Full backend tests pass.
- [ ] Frontend build passes.
- [ ] Current pending paper trades can be scanned in recommendations-only mode.

---

## Open Questions for Kayvon Before Implementation

1. **Auto-exit default:** Should paper auto-exit start disabled with recommendations only? I recommend yes.
2. **Accounting semantics:** Do you want `Trade.size` to mean dollars deployed/cost? I recommend yes, but this may require correcting current PnL math.
3. **Partial exits:** Do we want phase 1 to support only full exits, or also partial de-risking? I recommend full exits first, partial exits later.
4. **Weather aggressiveness:** For weather, should direct/final source contradiction be enough to auto-exit even if liquidity is poor? I recommend no — still require some executable bid/depth.
5. **Live readiness:** When live trading eventually arrives, should cash-outs require explicit human approval at first? I recommend yes.

---

## My Recommended Implementation Sequence

1. **Accounting + schema first.** Without correct PnL semantics, exit logic is dangerous.
2. **Recommendations-only risk rows second.** Get visibility before mutation.
3. **Weather analyzer third.** Weather has the most obvious salvage opportunities and current pending trades.
4. **BTC analyzer fourth.** Useful but more sensitive to noise.
5. **Entertainment analyzer fifth.** No open positions now, but architecture should be ready.
6. **Paper auto-exit last.** Turn on only after recommendation behavior looks sane.

---

## Why This Matters

This is not a minor dashboard feature. It changes the bot from a simple “enter and wait for settlement” simulator into an active risk manager.

The main edge is not just finding mispriced entries. It is also:

- admitting when the thesis is broken,
- preserving capital before zero,
- distinguishing temporary adverse price movement from true evidence failure,
- systematically doing this across every open position without emotional bias.

That is exactly the kind of work a bot should do better than a human.
