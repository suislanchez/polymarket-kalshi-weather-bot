# Unified Trading System Implementation Plan

> **For Hermes:** Execute this plan with the `superpowers:subagent-driven-development` workflow. Use one fresh implementation subagent per task, then run specification and code-quality review before moving to the next task. Do not skip red/green verification.

**Goal:** Turn the existing weather paper-trading repository into one archive-hosted, paper-only system for Alpaca stocks/crypto plus preserved Polymarket/Kalshi weather simulation, with one deterministic risk gate, normalized order lifecycle, append-only audit ledger, API, and dashboard.

**Architecture:** Keep the hardened weather modules and FastAPI/React shell. Add a broker-neutral trading domain and deterministic risk/execution gateway. Use LumiBot behind an injected Alpaca Paper adapter, never as an authority that can bypass risk checks. Polymarket and Kalshi remain simulation adapters. Agent/LLM research may emit typed `TradeProposal` objects but never receives broker credentials or an adapter reference.

**Tech stack:** Python 3.11, Pydantic 2, SQLAlchemy 2, FastAPI, SQLite, LumiBot with Alpaca Paper, pytest, React 18, TypeScript, Vite, Vitest, React Testing Library.

**Approved design:** `docs/superpowers/specs/2026-08-23-unified-trading-system-design.md`

---

## Execution rules

1. Use the Archives clone created in Task 1 for every implementation task after bootstrap.
2. Keep `EXECUTION_MODE=paper`; a non-paper value must fail startup.
3. Never print, commit, diff, or send credential values.
4. Do not request Alpaca credentials until Task 16. Robinhood and Coinbase credentials are out of scope for this implementation milestone.
5. Do not edit or delete the PrimoAgent checkout. It is reference-only.
6. Start every behavior change with a failing test, run it to observe the expected failure, implement the minimum code, then run the narrow test and relevant regression suite.
7. Commit each numbered task independently. Do not include `.firecrawl/`, `.env`, databases, virtual environments, `node_modules`, generated reports, or caches.
8. Do not remove the local legacy checkout. A symlink replacement is a separate final approval gate after all Archives verification succeeds.
9. No forced trades: a valid run with zero proposals/orders is a successful run.
10. Use `Decimal` for order/risk money and quantity calculations. Convert to strings at storage/API boundaries where precision must be preserved.
11. The Hermes parent process exports a `PYTHONPATH` that injects Hermes packages into child interpreters. Prefix every Python, pip, pytest, pip-tools, pip-audit, and Bandit command with `env -u PYTHONPATH`; add `PYTHONPATH=.` back only when the project import path is required.

## Canonical paths

```text
SOURCE=/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot
ROOT=/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system
REPO=$ROOT/unified-trading-system
DATA=$ROOT/data
ARTIFACTS=$ROOT/artifacts
LOGS=$ROOT/logs
ENVS=$ROOT/envs
BACKUPS=$ROOT/backups
PRIMO=$ROOT/PrimoAgent
```

## Target package map

```text
backend/trading/
├── __init__.py
├── domain.py
├── execution_mode.py
├── risk.py
├── ledger.py
├── service.py
├── market_data.py
├── strategies/
│   ├── __init__.py
│   └── trend_following.py
└── adapters/
    ├── __init__.py
    ├── base.py
    ├── fake.py
    ├── alpaca_paper.py
    ├── polymarket_paper.py
    └── kalshi_paper.py
```

---

### Task 1: Bootstrap the canonical Archives checkout

**Files:**
- Read: `docs/superpowers/specs/2026-08-23-unified-trading-system-design.md`
- Read: `docs/superpowers/plans/2026-08-23-unified-trading-system-implementation.md`
- Create on Archives: `unified-trading-system/`
- Create on Archives: `data/`, `artifacts/`, `logs/`, `envs/`, `backups/`

**Step 1: Verify the source and destination without mutating either**

Run:

```bash
test -d "$SOURCE/.git"
test -d /Volumes/Archives
test -w /Volumes/Archives
git -C "$SOURCE" status --short --branch
git -C "$SOURCE" fsck --full
```

Expected: Git integrity passes; only known untracked `.firecrawl/` may be present.

**Step 2: Fail closed if the destination already exists**

Run:

```bash
test ! -e "$REPO"
```

Expected: exit 0. If it fails, inspect the existing path and do not overwrite or delete it.

**Step 3: Create the directory layout and clone tracked history**

Run:

```bash
mkdir -p "$ROOT" "$DATA" "$ARTIFACTS" "$LOGS" "$ENVS" "$BACKUPS"
ORIGIN_URL="$(git -C "$SOURCE" remote get-url origin)"
git clone --no-local "$SOURCE" "$REPO"
git -C "$REPO" remote set-url origin "$ORIGIN_URL"
git -C "$REPO" switch -c feat/unified-paper-trading
```

Expected: the clone includes both approved documentation commits, retains the upstream GitHub remote rather than the local source path, and does not copy `.env`, databases, venv, node modules, or `.firecrawl/`.

**Step 4: Create the base Python environment on Archives**

Run:

```bash
env -u PYTHONPATH python3.11 -m venv "$ENVS/unified-trading-py311"
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pip install --upgrade pip
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pip install -r "$REPO/requirements.txt" pytest
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pip check
```

Expected: the only implementation Python environment is under `$ENVS`, and dependency integrity passes.

**Step 5: Verify parity**

Run:

```bash
test "$(git -C "$SOURCE" rev-parse HEAD)" = "$(git -C "$REPO" rev-parse HEAD)"
git -C "$REPO" fsck --full
git -C "$REPO" status --short --branch
```

Expected: clean `feat/unified-paper-trading` branch on the same commit as source.

**Step 6: Record no source commit**

This task creates the canonical checkout but does not alter tracked files. Do not commit directory creation.

---

### Task 2: Enforce archive paths and the paper-only startup invariant

**Files:**
- Create: `backend/trading/__init__.py`
- Create: `backend/trading/execution_mode.py`
- Modify: `backend/config.py`
- Modify: `.env.example`
- Create: `tests/test_execution_mode.py`
- Create: `tests/test_unified_config.py`
- Modify: `tests/test_scheduler_autostart.py`

**Step 1: Write failing mode tests**

Test these behaviors:

```python
from backend.trading.execution_mode import ExecutionModeError, require_paper_mode


def test_paper_mode_is_accepted():
    require_paper_mode("paper")


def test_live_mode_is_rejected():
    with pytest.raises(ExecutionModeError, match="paper-only"):
        require_paper_mode("live")
```

Also test that settings defaults expose:

```python
from backend.config import Settings

settings = Settings(_env_file=None)
assert settings.EXECUTION_MODE == "paper"
assert settings.LIVE_TRADING_ENABLED is False
assert settings.ACTIVE_PRODUCT_SCOPE == "unified_paper"
assert settings.TRADING_DATA_ROOT.startswith("/Volumes/Archives/")
```

Rename/update the existing weather-only default assertion in
`tests/test_scheduler_autostart.py` to expect `unified_paper`, while retaining
the assertions that scheduler autostart is explicit and the legacy BTC
prediction-market lane is disabled by default.

**Step 2: Run tests to verify RED**

Run:

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_execution_mode.py tests/test_unified_config.py -q
```

Expected: fail because the package and settings do not exist.

**Step 3: Implement the minimum invariant**

`backend/trading/execution_mode.py` must expose:

```python
class ExecutionModeError(RuntimeError):
    pass


def require_paper_mode(mode: str, live_enabled: bool = False) -> None:
    if mode.strip().lower() != "paper" or live_enabled:
        raise ExecutionModeError("Unified trading runtime is paper-only")
```

Add settings for `EXECUTION_MODE`, `LIVE_TRADING_ENABLED`,
`STOCK_CRYPTO_LANE_ENABLED`, `TRADING_SYSTEM_ROOT`, `TRADING_DATA_ROOT`,
`TRADING_ARTIFACTS_ROOT`, `TRADING_LOG_ROOT`, `TRADING_SYMBOL_ALLOWLIST`,
`MAX_ORDER_NOTIONAL_USD`, `MAX_ORDER_EQUITY_FRACTION`,
`MAX_SYMBOL_EXPOSURE_FRACTION`, `MAX_GROSS_EXPOSURE_FRACTION`,
`MAX_CRYPTO_EXPOSURE_FRACTION`, `MAX_DAILY_LOSS_FRACTION`,
`MAX_MARKET_DATA_AGE_SECONDS`, `GLOBAL_TRADING_KILL_SWITCH`,
`ALPACA_PAPER_BASE_URL`, and optional `ALPACA_API_KEY` / `ALPACA_API_SECRET`.
Call `require_paper_mode` at application startup before database initialization
or schedulers. Defaults must match the approved design: unified-paper scope,
lane disabled, paper endpoint only, `SPY,QQQ,BTC/USD,ETH/USD`, `$250`, 1%, 10%,
25%, 10%, 2%, and 60 seconds respectively.

`.env.example` contains names and safe dummy/blank values only. It must not contain a usable credential.

**Step 4: Run narrow and startup regression tests**

Run:

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_execution_mode.py tests/test_unified_config.py tests/test_scheduler_autostart.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add backend/trading backend/config.py .env.example tests/test_execution_mode.py tests/test_unified_config.py tests/test_scheduler_autostart.py
git diff --cached --check
git commit -m "feat: enforce paper-only unified runtime"
```

---

### Task 3: Add typed proposal, risk, order, and execution contracts

**Files:**
- Create: `backend/trading/domain.py`
- Create: `tests/test_trading_domain.py`

**Step 1: Write failing contract tests**

Cover:

- asset classes: `stock`, `crypto`, `prediction_weather`;
- venues: `alpaca_paper`, `polymarket_paper`, `kalshi_paper`;
- sides: `buy`, `sell`;
- order types: `market`, `limit`;
- order statuses: `proposed`, `risk_rejected`, `approved`, `submitted`, `partially_filled`, `filled`, `canceled`, `rejected`;
- positive quantity or notional, never both missing;
- limit orders require `limit_price`;
- timestamps are timezone-aware UTC;
- `client_order_id` and proposal idempotency key are stable strings;
- model output cannot add unknown fields.

Use Pydantic models with `ConfigDict(extra="forbid", frozen=True)`.

**Step 2: Run RED**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_trading_domain.py -q
```

Expected: import failure.

**Step 3: Implement minimum contracts**

Define:

```python
class TradeProposal(BaseModel):
    proposal_id: str
    strategy_id: str
    venue: Venue
    asset_class: AssetClass
    symbol: str
    side: Side
    quantity: Decimal | None = None
    notional: Decimal | None = None
    order_type: OrderType = OrderType.MARKET
    limit_price: Decimal | None = None
    reference_price: Decimal
    market_data_at: datetime
    created_at: datetime
    rationale: str
    metadata: dict[str, JsonValue] = Field(default_factory=dict)
```

Define matching immutable `RiskDecision`, `NormalizedOrder`, `ExecutionReport`, `AccountSnapshot`, and `PositionSnapshot` models. Validators enforce positivity and UTC.

**Step 4: Run GREEN**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_trading_domain.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add backend/trading/domain.py tests/test_trading_domain.py
git diff --cached --check
git commit -m "feat: add normalized trading contracts"
```

---

### Task 4: Implement the deterministic risk gate

**Files:**
- Create: `backend/trading/risk.py`
- Create: `tests/test_unified_risk_gate.py`

**Step 1: Write one failing test per gate**

Fixtures use `Decimal` and a fixed UTC clock. Cover rejection for:

1. symbol outside `SPY`, `QQQ`, `BTC/USD`, `ETH/USD`;
2. short/sell opening exposure;
3. non-stock/ETF/spot-crypto/weather asset;
4. notional over 1% of equity or `$250`, whichever is lower;
5. projected symbol exposure over 5% of equity;
6. projected gross exposure over 25% of equity;
7. projected crypto exposure over 10% of equity;
8. daily realized P&L at or below `-1%`;
9. quote older than 30 seconds;
10. duplicate idempotency key;
11. global kill switch;
12. any non-paper venue.

Add acceptance tests for one stock proposal, one crypto proposal, and a no-proposal/no-trade run.

**Step 2: Run RED**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_unified_risk_gate.py -q
```

Expected: import failure.

**Step 3: Implement pure evaluation**

Create immutable `RiskLimits`, `PortfolioState`, and `RiskContext` models and:

```python
def evaluate_proposal(
    proposal: TradeProposal,
    portfolio: PortfolioState,
    context: RiskContext,
    limits: RiskLimits,
) -> RiskDecision:
    ...
```

The function has no network/database calls. It returns all reasons, not only the first one. The approved order uses the smaller of proposed notional and all applicable caps.

**Step 4: Run GREEN and risk regressions**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_unified_risk_gate.py tests/test_position_risk.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add backend/trading/risk.py tests/test_unified_risk_gate.py
git diff --cached --check
git commit -m "feat: add deterministic unified risk gate"
```

---

### Task 5: Add the broker protocol and credential-free fake adapter

**Files:**
- Create: `backend/trading/adapters/__init__.py`
- Create: `backend/trading/adapters/base.py`
- Create: `backend/trading/adapters/fake.py`
- Create: `tests/test_broker_adapter_contract.py`

**Step 1: Write failing protocol tests**

Define a reusable contract suite that any adapter must satisfy:

- `name` and `paper_only` properties;
- account snapshot;
- positions snapshot;
- idempotent submit by `client_order_id`;
- cancel open order;
- read order;
- list recent orders;
- map partial/full fill statuses;
- reject a non-paper order before side effects;
- never expose a credential in `repr`, exception text, or returned metadata.

**Step 2: Run RED**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_broker_adapter_contract.py -q
```

Expected: import failure.

**Step 3: Implement protocol and fake**

`BrokerAdapter` is a `typing.Protocol`. `FakePaperAdapter` holds in-memory orders and deterministic balances, accepts an injected clock, and can simulate reject/partial/fill scenarios without network access.

**Step 4: Run GREEN**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_broker_adapter_contract.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add backend/trading/adapters tests/test_broker_adapter_contract.py
git diff --cached --check
git commit -m "feat: define paper broker adapter contract"
```

---

### Task 6: Add append-only trading events and order projections

**Files:**
- Modify: `backend/models/database.py`
- Create: `backend/trading/ledger.py`
- Create: `tests/test_trading_ledger.py`
- Modify: `tests/test_database.py`

**Step 1: Write failing ledger tests**

Using a temporary SQLite database, verify:

- every event has unique id, aggregate id, sequence, type, UTC time, JSON payload, previous hash, and SHA-256 hash;
- the first event uses the zero-chain sentinel;
- the second event links to the first hash;
- tampering causes chain verification to fail;
- duplicate `(aggregate_id, sequence)` and duplicate event IDs fail;
- projection updates are idempotent by `client_order_id`;
- no ledger API offers update/delete;
- current weather `Trade` and `Signal` tables remain readable.

**Step 2: Run RED**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_trading_ledger.py tests/test_database.py -q
```

Expected: missing models/module.

**Step 3: Add models and repository**

Add `TradingEvent` and `UnifiedOrder` SQLAlchemy models. `TradingEvent` is append-only at the repository layer. `UnifiedOrder` is a derived projection and may be updated as execution reports arrive.

Expose:

```python
append_event(session, event: LedgerEventInput) -> TradingEvent
verify_event_chain(session, aggregate_id: str) -> ChainVerification
upsert_order_projection(session, report: ExecutionReport) -> UnifiedOrder
```

Do not migrate or rewrite legacy weather rows.

**Step 4: Run GREEN and schema regressions**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_trading_ledger.py tests/test_database.py tests/test_weather_paper_account.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add backend/models/database.py backend/trading/ledger.py tests/test_trading_ledger.py tests/test_database.py
git diff --cached --check
git commit -m "feat: add append-only trading event ledger"
```

---

### Task 7: Route every order through risk, ledger, and adapter

**Files:**
- Create: `backend/trading/service.py`
- Create: `tests/test_paper_execution_service.py`

**Step 1: Write failing orchestration tests**

Verify exact event order:

```text
proposal_created
risk_approved | risk_rejected
order_submitted
order_acknowledged | order_rejected
order_partially_filled*
order_filled | order_canceled
```

Cover:

- rejected proposal never calls adapter;
- duplicate proposal returns the prior result without a second adapter call;
- adapter exception records a sanitized rejection event;
- successful fill updates order projection;
- kill switch checked again immediately before submit;
- venue mismatch rejected;
- no proposal produces no event and no call.

**Step 2: Run RED**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_paper_execution_service.py -q
```

Expected: import failure.

**Step 3: Implement service**

`PaperExecutionService` receives an adapter registry, risk evaluator, ledger repository, settings snapshot, clock, and kill-switch callable. It must not import LLM libraries.

**Step 4: Run GREEN plus domain suite**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_paper_execution_service.py tests/test_unified_risk_gate.py tests/test_trading_ledger.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add backend/trading/service.py tests/test_paper_execution_service.py
git diff --cached --check
git commit -m "feat: route paper orders through risk and ledger"
```

---

### Task 8: Isolate and pin LumiBot on Archives

**Files:**
- Create: `requirements-trading.in`
- Create: `requirements-trading.txt`
- Modify: `README.md`
- Create: `tests/test_lumibot_runtime.py`

**Step 1: Extend the existing Archives Python environment with tooling**

Run from `$REPO`:

```bash
test -x "$ENVS/unified-trading-py311/bin/python"
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pip install pip-tools pip-audit bandit
```

Expected: environment exists only on Archives.

**Step 2: Write a failing dependency smoke test**

```python
def test_lumibot_imports_without_starting_a_broker():
    import lumibot
    assert lumibot.__version__
```

The test must not read credentials or start network I/O.

**Step 3: Run RED**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_lumibot_runtime.py -q
```

Expected: `ModuleNotFoundError`.

**Step 4: Resolve then pin the compatible LumiBot release**

Put the minimal LumiBot/Alpaca dependency in `requirements-trading.in`, compile exact transitive versions into `requirements-trading.txt`, install it, and record the resolved LumiBot version in README. Do not guess a version in code.

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/pip-compile" requirements-trading.in --output-file requirements-trading.txt
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pip install -r requirements-trading.txt
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pip check
```

**Step 5: Run GREEN and security audit**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_lumibot_runtime.py -q
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/pip-audit" -r requirements-trading.txt
```

Expected: import and `pip check` pass. Any vulnerability must be triaged and resolved or documented as a blocker before continuing; do not suppress it silently.

**Step 6: Commit**

```bash
git add requirements-trading.in requirements-trading.txt README.md tests/test_lumibot_runtime.py
git diff --cached --check
git commit -m "build: pin LumiBot paper trading runtime"
```

---

### Task 9: Implement the injected Alpaca Paper adapter

**Files:**
- Create: `backend/trading/adapters/alpaca_paper.py`
- Create: `tests/test_alpaca_paper_adapter.py`
- Modify: `tests/test_broker_adapter_contract.py`

**Step 1: Write failing mapping and safety tests**

Use an injected fake LumiBot/Alpaca client—no network and no credentials. Verify:

- only `https://paper-api.alpaca.markets` is accepted;
- any live Alpaca host is rejected before client creation;
- account/position/order responses map into normalized models;
- stock `SPY` and crypto `BTC/USD` symbols map correctly;
- submit passes stable `client_order_id`;
- cancel and refresh map statuses;
- API errors redact key/secret values;
- adapter satisfies the shared broker contract.

**Step 2: Run RED**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_alpaca_paper_adapter.py -q
```

Expected: import failure.

**Step 3: Implement adapter with dependency injection**

Construction takes `client_factory` plus settings. Validate endpoint and `EXECUTION_MODE` before invoking the factory. Wrap the smallest stable LumiBot broker surface; do not let API routes or strategies instantiate Alpaca directly.

**Step 4: Run GREEN and contract tests**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_alpaca_paper_adapter.py tests/test_broker_adapter_contract.py -q
```

Expected: pass without network.

**Step 5: Commit**

```bash
git add backend/trading/adapters/alpaca_paper.py tests/test_alpaca_paper_adapter.py tests/test_broker_adapter_contract.py
git diff --cached --check
git commit -m "feat: add guarded Alpaca paper adapter"
```

---

### Task 10: Add deterministic stock and crypto proposal generation

**Files:**
- Create: `backend/trading/market_data.py`
- Create: `backend/trading/strategies/__init__.py`
- Create: `backend/trading/strategies/trend_following.py`
- Create: `tests/test_trend_following_strategy.py`
- Create: `tests/fixtures/market_bars.json`

**Step 1: Write failing strategy tests**

Use fixed OHLCV bars. Verify:

- strategy supports `SPY`, `QQQ`, `BTC/USD`, `ETH/USD` only;
- warm-up with insufficient bars returns no proposal;
- fast SMA crossing above slow SMA creates a buy proposal;
- no cross returns no proposal;
- sell signal may only reduce an existing long position;
- stale/incomplete bars return no proposal with reason;
- deterministic input yields byte-equivalent serialized proposal;
- rationale names data timestamp and rule, not LLM prose.

**Step 2: Run RED**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_trend_following_strategy.py -q
```

Expected: import failure.

**Step 3: Implement minimum strategy**

Implement a configurable 20/50 simple-moving-average crossover that emits typed proposals only. It does not submit orders and does not size beyond a requested notional cap. Keep BTC prediction-market signal code separate from spot crypto.

**Step 4: Run GREEN**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_trend_following_strategy.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add backend/trading/market_data.py backend/trading/strategies tests/test_trend_following_strategy.py tests/fixtures/market_bars.json
git diff --cached --check
git commit -m "feat: add deterministic stock crypto proposals"
```

---

### Task 11: Preserve weather simulation behind normalized adapters

**Files:**
- Create: `backend/trading/adapters/polymarket_paper.py`
- Create: `backend/trading/adapters/kalshi_paper.py`
- Modify: `backend/core/scheduler.py`
- Create: `tests/test_weather_paper_adapters.py`
- Modify: `tests/test_weather_venue_reliability_integration.py`

**Step 1: Write failing preservation tests**

Verify:

- existing Polymarket weather proposal maps into normalized contract;
- existing Kalshi weather proposal maps into normalized contract;
- both use simulation ledgers only;
- `WEATHER_KALSHI_PAPER_EXECUTION_ENABLED=false` keeps Kalshi monitor-only;
- venue reliability gates remain authoritative;
- unknown station, settlement source, stale quote, or bucket-mass failure returns no order;
- no adapter contains private CLOB/order-signing methods;
- legacy weather tests remain unchanged in intent.

**Step 2: Run RED**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_weather_paper_adapters.py tests/test_weather_venue_reliability_integration.py -q
```

Expected: new test fails because normalized adapters do not exist.

**Step 3: Implement thin adapters**

Translate existing weather signals into `TradeProposal`, reuse current validation/reliability methods, and route accepted simulation orders into the unified event ledger while retaining legacy `Trade` rows during the compatibility phase.

**Step 4: Run GREEN plus all weather tests**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_weather_paper_adapters.py tests/test_weather_venue_reliability_integration.py tests/test_weather_*.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add backend/trading/adapters/polymarket_paper.py backend/trading/adapters/kalshi_paper.py backend/core/scheduler.py tests/test_weather_paper_adapters.py tests/test_weather_venue_reliability_integration.py
git diff --cached --check
git commit -m "feat: normalize weather paper execution"
```

---

### Task 12: Integrate unified paper jobs without enabling them by default

**Files:**
- Modify: `backend/core/scheduler.py`
- Modify: `backend/config.py`
- Create: `tests/test_unified_scheduler.py`
- Modify: `tests/test_scheduler_autostart.py`

**Step 1: Write failing scheduler tests**

Verify:

- `SCHEDULER_AUTOSTART=false` starts nothing;
- `STOCK_CRYPTO_LANE_ENABLED=false` registers no Alpaca job;
- enabling it registers exactly one bounded job;
- weather jobs still register under existing flags;
- BTC prediction and entertainment jobs remain paused;
- one run can return zero proposals successfully;
- repeated job invocation cannot duplicate orders;
- adapter or data failure logs a sanitized event and does not crash weather jobs.

**Step 2: Run RED**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_unified_scheduler.py tests/test_scheduler_autostart.py -q
```

Expected: new tests fail.

**Step 3: Add a bounded unified job**

Add `stock_crypto_paper_job()` and register it only when both scheduler autostart and lane flag are enabled. It obtains market data, asks strategy for proposals, then hands proposals to `PaperExecutionService`. No direct broker call is allowed in scheduler code.

**Step 4: Run GREEN and scheduler regressions**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_unified_scheduler.py tests/test_scheduler_autostart.py tests/test_scheduler_jobs.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add backend/core/scheduler.py backend/config.py tests/test_unified_scheduler.py tests/test_scheduler_autostart.py
git diff --cached --check
git commit -m "feat: schedule guarded stock crypto paper lane"
```

---

### Task 13: Add unified read APIs and a safe manual paper-run API

**Files:**
- Modify: `backend/api/schemas.py`
- Modify: `backend/api/main.py`
- Create: `tests/test_unified_trading_api.py`
- Modify: `tests/test_api_schemas.py`

**Step 1: Write failing API tests**

With scheduler disabled and fake adapter injected, verify:

- `GET /api/trading/status` returns mode, adapter states, lane flags, kill switch, archive paths, and credential-presence booleans only;
- `GET /api/trading/orders` returns normalized projections;
- `GET /api/trading/events` returns sanitized audit events;
- `GET /api/trading/portfolio` returns cash/equity/positions;
- `POST /api/trading/paper/run` may produce zero proposals and returns a clear result;
- a proposed order runs through the service;
- API never returns secrets or complete credential strings;
- there is no live-order endpoint;
- entertainment data is excluded from active unified scope.

**Step 2: Run RED**

```bash
env -u PYTHONPATH SCHEDULER_AUTOSTART=false "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_unified_trading_api.py tests/test_api_schemas.py -q
```

Expected: 404/missing schemas.

**Step 3: Implement dependency-injected routes**

Add response schemas and route dependencies for read models and the safe run service. Keep route handlers thin. Rename API title/description to the unified paper product while retaining weather endpoints.

**Step 4: Run GREEN and full API regressions**

```bash
env -u PYTHONPATH SCHEDULER_AUTOSTART=false "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_unified_trading_api.py tests/test_api_schemas.py tests/test_dashboard_product_scope.py tests/test_scheduler_autostart.py -q
```

Expected: pass.

**Step 5: Commit**

```bash
git add backend/api/schemas.py backend/api/main.py tests/test_unified_trading_api.py tests/test_api_schemas.py
git diff --cached --check
git commit -m "feat: expose unified paper trading API"
```

---

### Task 14: Replace the weather-only dashboard shell with a unified paper dashboard

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/types.ts`
- Modify: `frontend/src/api.ts`
- Modify: `frontend/src/App.tsx`
- Create: `frontend/src/components/TradingStatusPanel.tsx`
- Create: `frontend/src/components/PortfolioPanel.tsx`
- Create: `frontend/src/components/UnifiedOrdersTable.tsx`
- Create: `frontend/src/components/TradingStatusPanel.test.tsx`
- Create: `frontend/src/components/UnifiedOrdersTable.test.tsx`

**Step 1: Add test tooling and write failing component tests**

Add Vitest, jsdom, and React Testing Library. Tests verify:

- a prominent `PAPER ONLY` badge;
- Alpaca shows disconnected/configured/connected without secret values;
- Robinhood and Coinbase show `Deferred / disabled`;
- Polymarket and Kalshi show simulation/monitor state;
- global kill-switch state is visible;
- orders show venue, symbol, side, status, quantity/notional, and paper mode;
- entertainment panels are absent;
- weather panels still render.

**Step 2: Run RED**

```bash
cd frontend
npm install
npm test -- --run
```

Expected: missing components/tests fail.

**Step 3: Implement the smallest unified shell**

Add typed API calls and panels. Preserve the existing weather calibration, source-state, and risk views. De-emphasize legacy BTC prediction-market panels; spot crypto appears through unified portfolio/orders.

**Step 4: Run GREEN and production build**

```bash
npm test -- --run
npm run build
```

Expected: tests and TypeScript/Vite build pass.

**Step 5: Commit**

```bash
cd "$REPO"
git add frontend/package.json frontend/package-lock.json frontend/src
git diff --cached --check
git commit -m "feat: add unified paper trading dashboard"
```

---

### Task 15: Build and execute non-destructive runtime-data migration

**Files:**
- Create: `scripts/migrate_runtime_to_archives.py`
- Create: `tests/test_archive_migration.py`
- Create at runtime: `$BACKUPS/migration-manifest.json`
- Create at runtime: `$DATA/legacy/`
- Create at runtime: `$BACKUPS/secrets/`
- Create at runtime: `$BACKUPS/firecrawl/`

**Step 1: Write failing migration tests**

Use temporary directories. Verify:

- dry-run writes nothing;
- source files are inventoried by relative path, size, SHA-256, and category;
- tracked source is excluded because Git clone owns it;
- SQLite files copy byte-for-byte and pass `PRAGMA integrity_check` at destination;
- `.env` and key-like files copy opaquely to `backups/secrets` with mode `0600` and values are never logged;
- `venv`, `.venv`, `node_modules`, build output, and caches are classified `recreate`, not copied into the repo;
- `.firecrawl` routes to its own backup, never the repo;
- destination mismatch fails without deleting source or destination;
- rerun is idempotent;
- manifest contains no secret file contents.

**Step 2: Run RED**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_archive_migration.py -q
```

Expected: missing script/module.

**Step 3: Implement dry-run and apply modes**

The script takes explicit `--source`, `--archive-root`, and either `--dry-run` or `--apply`. It uses Python file APIs, temporary destination names, `fsync`, atomic rename, SHA-256 verification, and restrictive secret permissions. It never deletes source data.

**Step 4: Run GREEN**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_archive_migration.py -q
```

Expected: pass.

**Step 5: Run dry-run against the real source**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" scripts/migrate_runtime_to_archives.py \
  --source "$SOURCE" \
  --archive-root "$ROOT" \
  --dry-run
```

Expected: categorized plan only; no values from `.env` or key files printed.

**Step 6: Apply and verify**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" scripts/migrate_runtime_to_archives.py \
  --source "$SOURCE" \
  --archive-root "$ROOT" \
  --apply
```

Expected: manifest, copied databases/data, controlled secret backup, and separate `.firecrawl` backup; source remains untouched.

**Step 7: Commit code only**

```bash
git add scripts/migrate_runtime_to_archives.py tests/test_archive_migration.py
git diff --cached --check
git commit -m "feat: add verified Archives runtime migration"
```

Do not add runtime manifests, backups, secrets, databases, or copied data.

---

### Task 16: Add operator commands and credential-ready preflight

**Files:**
- Create: `scripts/trading_preflight.py`
- Create: `scripts/run_paper_strategy.py`
- Create: `scripts/verify_alpaca_paper.py`
- Create: `tests/test_trading_preflight.py`
- Create: `tests/test_paper_strategy_cli.py`
- Modify: `README.md`

**Step 1: Write failing CLI tests**

Verify:

- preflight checks Archives mount/writeability, paper mode, DB integrity, dependency imports, kill switch, and adapter state;
- no credentials yields `credential_ready=false`, not a traceback;
- paper strategy CLI can run with `--adapter fake` and record deterministic events;
- `--adapter alpaca` refuses missing credentials cleanly;
- any live endpoint or live flag exits nonzero before client construction;
- verification script only accepts the Alpaca paper endpoint;
- output redacts credentials.

**Step 2: Run RED**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_trading_preflight.py tests/test_paper_strategy_cli.py -q
```

Expected: scripts missing.

**Step 3: Implement commands**

Required operator flows:

```bash
python scripts/trading_preflight.py
python scripts/run_paper_strategy.py --adapter fake --symbols SPY BTC/USD --once
python scripts/verify_alpaca_paper.py --read-only
python scripts/verify_alpaca_paper.py --submit-cancel SPY
```

`--submit-cancel` is unavailable until Alpaca Paper credentials are present and preflight proves the paper account/endpoint.

**Step 4: Run GREEN and fake end-to-end smoke**

```bash
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pytest tests/test_trading_preflight.py tests/test_paper_strategy_cli.py -q
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" scripts/trading_preflight.py
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" scripts/run_paper_strategy.py --adapter fake --symbols SPY BTC/USD --once
```

Expected: tests pass; preflight reports credentials absent; fake run records a proposal/risk/order lifecycle or a valid no-trade result.

**Step 5: Commit**

```bash
git add scripts/trading_preflight.py scripts/run_paper_strategy.py scripts/verify_alpaca_paper.py tests/test_trading_preflight.py tests/test_paper_strategy_cli.py README.md
git diff --cached --check
git commit -m "feat: add paper trading operator commands"
```

**Step 6: User credential gate**

Only now ask the user to place Alpaca Paper credentials in the controlled Archives secret configuration. Never ask them to paste credentials into chat. Robinhood and Coinbase remain disconnected.

With user participation, run read-only verification first, then a bounded submit/cancel for `SPY`. Record the real command result and sanitized order ID/status in the audit ledger. If credentials are not yet available, stop here and report that code is credential-ready but real Alpaca paper execution is blocked on user action.

---

### Task 17: Full regression, security, and Archives acceptance verification

**Files:**
- Modify only if verification reveals a defect.
- Create runtime report: `$ARTIFACTS/verification/unified-paper-acceptance.md`

**Step 1: Verify repository hygiene**

```bash
git status --short --branch
git diff --check
git fsck --full
```

Expected: clean tracked state.

**Step 2: Run complete Python suite from Archives**

```bash
env -u PYTHONPATH PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -m pytest -q
```

Expected: all legacy and new tests pass. Record the actual count; do not preclaim 272 because the suite will grow.

**Step 3: Run frontend tests/build from Archives**

```bash
cd "$REPO/frontend"
npm test -- --run
npm run build
```

Expected: pass.

**Step 4: Run dependency and static security checks**

```bash
cd "$REPO"
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m pip check
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/pip-audit" -r requirements.txt
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/pip-audit" -r requirements-trading.txt
env -u PYTHONPATH "$ENVS/unified-trading-py311/bin/python" -m bandit -r backend scripts -q
```

Expected: no untriaged high/critical issue. Fix application findings; document upstream-only residuals with package, advisory, exposure, and mitigation.

**Step 5: Run paper-only negative tests explicitly**

```bash
env -u PYTHONPATH EXECUTION_MODE=live PYTHONPATH=. "$ENVS/unified-trading-py311/bin/python" -c 'from backend.config import settings; from backend.trading.execution_mode import require_paper_mode; require_paper_mode(settings.EXECUTION_MODE)'
```

Expected: nonzero with paper-only error.

Search tracked source for forbidden live hosts/order bypasses and secret-like assignments. Review every match; a match is not automatically a defect, but no live execution path or usable secret may remain.

**Step 6: Verify migrated data and startup**

- Rehash every migration manifest entry.
- Run SQLite `PRAGMA integrity_check` for every copied DB.
- Start API with `SCHEDULER_AUTOSTART=false` from Archives.
- Verify `/api/health` and `/api/trading/status`.
- Run the fake paper strategy once.
- If Alpaca credentials were supplied, run read-only account verification and bounded submit/cancel.
- Confirm Polymarket/Kalshi weather endpoints still return valid simulation/research responses or honest upstream-empty states.

**Step 7: Write the acceptance report**

The report must include exact commands, exit statuses, actual test counts, dependency audit status, migration manifest path, DB integrity results, branch/commit, API smoke results, weather preservation results, and credential gate state. Do not include secrets.

**Step 8: Commit any documentation-only acceptance index**

If the generated acceptance report is intentionally untracked under `artifacts/`, add only a short tracked pointer in README or `docs/operations/` and commit it. Never commit generated market/account data.

---

### Task 18: Final local-storage switchover approval gate

**Files:**
- No tracked source changes expected.
- Potential local path change: `/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot`

**Step 1: Prove the Archives system is canonical**

Required evidence:

- Archives Git checkout clean and passes `git fsck`;
- source and archive history both contain the pre-migration commits;
- archive implementation branch contains all new commits;
- complete Python/frontend/security verification passes;
- copied databases pass integrity and checksum comparison;
- API/dashboard and fake paper run work entirely from Archives;
- credentials are either verified in Alpaca Paper or clearly listed as the only remaining execution blocker.

**Step 2: Ask for explicit destructive-local approval**

Do not remove or rename the local checkout automatically. Ask whether to:

1. keep it as a verified fallback;
2. rename it to a temporary local backup and create a symlink;
3. remove it after one more checksum and create a symlink.

**Step 3: If approved, perform a reversible switchover first**

Preferred first action:

```bash
mv "$SOURCE" "${SOURCE}.pre-archives-backup"
ln -s "$REPO" "$SOURCE"
```

Verify Git, tests, and API through the old path. Do not delete `.pre-archives-backup` in the same step. Deletion requires a second explicit approval after the user has had time to confirm normal use.

---

## Completion definition

The implementation milestone is complete when:

- all source, environments, active data, logs, and artifacts run from Archives;
- stocks and crypto share the normalized proposal/risk/order/ledger path;
- Alpaca adapter is paper-endpoint-only;
- a fake end-to-end paper lifecycle is verified;
- a real Alpaca paper submit/cancel is verified after user-supplied credentials, or credentials are the sole stated blocker;
- Polymarket/Kalshi weather simulation and calibration still pass regressions;
- entertainment and live trading remain disabled;
- Robinhood and Coinbase remain deferred with no credentials stored in the app;
- full Python/frontend/security/migration verification is captured with real output;
- the local checkout is not deleted without a separate explicit approval.

## Deferred roadmap (not part of this plan)

1. Robinhood read-only holdings import, then carefully gated live adapter only if an official supported route meets safety requirements.
2. Coinbase read-only portfolio import, then live spot adapter only after paper validation and separate approval.
3. Multi-user/friends deployment, authentication, permissions, capital isolation, and licensing/distribution review.
4. Additional strategies only after the baseline ledger has enough paper history for evaluation.
5. Optional PrimoAgent-inspired research workers that emit schema-validated proposals but remain unable to access broker tools.
