# Unified Trading System Design

**Date:** 2026-08-23
**Status:** Approved architecture; implementation not started
**Decision:** LumiBot hybrid with Alpaca Paper as the initial stock and crypto execution venue

## 1. Executive summary

Build one paper-first trading system for:

1. US stocks and ETFs;
2. spot cryptocurrency;
3. weather prediction markets on Polymarket and Kalshi.

The system will use LumiBot as the common strategy and broker-abstraction layer where it is mature, preserve the existing weather forecasting and venue-reliability work, and keep the existing FastAPI/React operational surface. Alpaca Paper is the only initially enabled external execution venue. Polymarket and Kalshi remain simulated. Robinhood and Coinbase integrations remain disconnected and incapable of order submission until a separately approved live-trading phase.

PrimoAgent is retained as an installed reference, not adopted as the runtime foundation. Its useful separation of data collection, technical analysis, news analysis, and portfolio review will inform optional research-agent boundaries. Deterministic application code remains authoritative for risk, order validation, and execution.

The canonical repository, state, dependency environments, caches, logs, and generated artifacts will run from the Archives external drive. The old local project path will become a symlink only after migration verification succeeds.

## 2. Goals

### 2.1 Functional goals

- Provide one normalized portfolio, signal, risk, order, fill, and audit model across active domains.
- Run stock and spot-crypto strategies against Alpaca's real-time paper environment.
- Preserve weather-market research, calibration, venue reliability, simulation, and reporting.
- Support deterministic backtests with explicit fees and slippage assumptions.
- Support optional AI research agents without granting those agents broker execution authority.
- Preserve the current paper-trading ledger and research history.
- Provide one API, dashboard, scheduler, runbook, and kill switch.
- Leave Robinhood and Coinbase connection as an explicit later user-operated onboarding step.

### 2.2 Storage goals

- Place all runtime-heavy data on `/Volumes/Archives`.
- Free the current repository's approximately 883 MB of internal-disk use.
- Recreate dependency environments on Archives instead of copying reproducible caches blindly.
- Preserve irreplaceable SQLite state and ignored configuration files without exposing secrets.
- Keep an exact rollback path until the Archives copy is fully verified.

### 2.3 Safety goals

- Make paper execution the only enabled mode.
- Fail closed if the Archives drive is unavailable, data is stale, broker mode is ambiguous, or an adapter reports a live endpoint.
- Prevent duplicate orders, stale orders, oversized positions, and order submission after a circuit breaker trips.
- Ensure an LLM cannot call a broker or venue execution tool.
- Require a separate specification and explicit approval before any real-money order path is enabled.

## 3. Non-goals

The initial system will not:

- submit real-money orders to Robinhood, Coinbase, Alpaca, Polymarket, or Kalshi;
- support options, futures, leverage, margin, short selling, staking, lending, or transfers;
- run entertainment prediction-market strategies;
- attempt high-frequency, market-making, or latency-sensitive trading;
- claim profitability from an LLM signal or a short backtest;
- copy PrimoAgent's legacy dependency stack into production;
- replace the current dashboard solely for visual redesign;
- delete the verified Archives copy or historical Git data;
- distribute LumiBot-derived code without a separate license review.

## 4. Evidence and decisions

### 4.1 Existing trading system

The current repository is:

`/Users/kayvonai/Documents/GitHub/polymarket-kalshi-weather-bot`

The baseline branch is `weather-bot-hardening-2026-06-16`. Existing uncommitted weather reliability changes were tested and committed as:

`3f5bd0e7fe7a981ba933233552b0514df179a96b` — `Add venue-aware weather calibration reliability`

Fresh baseline verification before that commit reported:

- 272 passing backend tests;
- a successful frontend production build;
- a clean staged whitespace check.

The active SQLite ledger contains approximately:

- 84,504 signals;
- 54,623 BTC snapshots;
- 22 paper trades.

The bulk of the repository's disk usage is reproducible dependencies:

- Python `venv`: approximately 382 MB;
- frontend `node_modules`: approximately 409 MB;
- live SQLite state: approximately 75–80 MB;
- source, tests, and documentation: only a few MB.

The untracked `.firecrawl/` directory contains unrelated creator-platform research and must not be committed to the trading repository. It will be archived separately during migration.

### 4.2 PrimoAgent findings

PrimoAgent is installed at:

`/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/PrimoAgent`

Audited commit:

`878f6719f3795546b16ccb43e9859e054a06cca1`

The repository is MIT-licensed and has a small source checkout, but it is a research demonstration rather than a broker-connected paper engine:

- a linear LangGraph flow: data collection → technical analysis → news intelligence → portfolio manager;
- Yahoo Finance market data;
- LLM-generated recommendations;
- Backtrader-based CSV backtests;
- no Robinhood, Coinbase, Alpaca, Polymarket, or Kalshi execution adapters;
- no repository test suite;
- seven total commits, one contributor, no releases;
- no persistent normalized order/fill/portfolio engine.

Its published install instructions are not reproducible on the current Python toolchain:

- declared `pyfolio` is legacy and fails to build;
- source imports `ta` and `langchain_openai`, but they are absent from `requirements.txt`;
- unbounded LangChain requirements install 1.x, while the source imports 0.3-era APIs.

An Archives-only compatibility environment was produced for evaluation. All source modules imported only after adding the missing packages and constraining LangChain to the 0.x line. That compatible environment reported 24 known dependency advisories across 11 packages. Static Bandit analysis found no medium/high issues and one low-severity use of non-cryptographic randomness.

The included AAPL backtest ran end to end for its Jan–Jun 2025 sample. It returned -6.87% versus -15.27% buy-and-hold, meaning it lost less than the benchmark rather than making money. It assumes zero commission and no explicit slippage model.

Decision: retain PrimoAgent as an architectural reference only.

### 4.3 Framework comparison

| Framework | Fit | Strengths | Material limitations | Decision |
|---|---|---|---|---|
| LumiBot | High | Python-first; Alpaca stock/crypto paper; Coinbase path; Polymarket execution/backtesting; agent support; active releases | GPL-3.0; custom Kalshi work; not designed for high-frequency execution | Selected foundation |
| NautilusTrader | Medium-high | Production-grade Rust core; deterministic event model; sandbox/backtest/live parity; Coinbase and Polymarket integrations | Higher migration cost; Coinbase v2/Rust-centric; no direct Robinhood/Alpaca path in reviewed evidence | Future upgrade candidate |
| LEAN | Medium | Mature Apache-2.0 engine; broad brokerage models; Alpaca and Coinbase integrations | Heavier .NET/Docker workflow; local CLI/deployment constraints; no native weather-market path | Not selected |
| Extend current engine | Medium | Least immediate conceptual change; preserves all custom behavior | Requires maintaining custom broker normalization, accounting, fills, calendars, and reconciliation | Use only where adapters are missing |
| Freqtrade | Low-medium | Mature crypto dry-run and exchange ecosystem | Crypto-focused; not a stocks/weather unification layer | Not selected |
| FinRL | Low | Useful reinforcement-learning research toolkit | Research/ML focus; not the execution and operations foundation | Not selected |

### 4.4 Broker and venue facts

- Alpaca Paper provides real-time simulated stock and crypto trading with separate paper credentials and the same API shape as live trading.
- Robinhood provides an official Agentic Trading MCP for a dedicated real Agentic account. The reviewed official documentation does not describe a paper or sandbox environment.
- Coinbase Advanced Trade's official sandbox returns static, predefined responses. It validates request/response plumbing but is not a dynamic paper venue.
- LumiBot supports Alpaca paper trading, a Coinbase CCXT path, Polymarket data/execution/backtesting, and broker-neutral strategy code.
- Polymarket does not expose a complete fake-money live venue. Weather trading remains backtest/simulation-only until a separately approved funded phase.
- Kalshi requires the existing custom integration and remains simulation-only.

## 5. Architecture

### 5.1 Runtime data flow

```text
market and external data
    │
    ├── stocks and crypto: Alpaca market data
    ├── weather: NOAA/NWS and station-normalization pipeline
    ├── prediction: Polymarket/Kalshi market discovery and quotes
    └── optional research: news and point-in-time datasets
    │
strategy and research layer
    │
    ├── deterministic strategies
    └── optional read-only research agents
    │
normalized SignalProposal
    │
deterministic risk engine
    │
normalized OrderIntent or Rejection
    │
execution router
    │
    ├── AlpacaPaperAdapter       enabled
    ├── PolymarketPaperAdapter   enabled
    ├── KalshiPaperAdapter       enabled
    ├── CoinbaseAdapter          disabled
    └── RobinhoodMCPAdapter      disabled
    │
normalized lifecycle events
    │
append-only ledger → API → dashboard → audit/reporting
```

### 5.2 Component boundaries

#### Domain contracts

One small, dependency-light package defines immutable typed contracts:

- `Instrument`: normalized asset identity, venue, quote currency, precision, and market schedule;
- `MarketSnapshot`: timestamped bid, ask, last, source, and freshness metadata;
- `SignalProposal`: strategy, instrument, direction, confidence, horizon, evidence references, and model/data timestamps;
- `RiskDecision`: accepted/rejected status, reason codes, approved size, and active limit snapshot;
- `OrderIntent`: idempotency key, side, quantity/notional, order type, limit, time in force, venue, and paper/live mode;
- `ExecutionEvent`: accepted, rejected, partially filled, filled, canceled, or expired event with broker identifiers;
- `PositionSnapshot`: normalized quantity, cost basis, mark, realized/unrealized P&L, and source timestamp.

Domain contracts must not import LumiBot, FastAPI, broker SDKs, or LLM libraries.

#### Market-data adapters

Adapters translate venue-specific data into `MarketSnapshot` and instrument metadata. They do not submit orders. Data-source failures produce explicit stale/unavailable states rather than reused values without provenance.

#### Strategy layer

Strategies consume normalized data and emit `SignalProposal` objects. They cannot submit orders. Initial active families are:

- conservative stock/ETF strategies;
- spot-crypto strategies;
- weather probability/market-edge strategies.

Entertainment strategies remain inactive and reachable only through Git history or an archived legacy module.

#### Research-agent layer

Optional agents follow the useful Primo separation:

1. data collection;
2. technical analysis;
3. news intelligence;
4. portfolio review.

Agent results must conform to a typed schema and include source timestamps. Agents have read-only tools. Their outputs are advisory inputs to a strategy or review queue, never an `OrderIntent` and never direct calls to broker tools.

#### Risk engine

The risk engine is deterministic and independent of any LLM. It evaluates:

- execution mode;
- venue allowlist;
- instrument allowlist;
- market-data freshness;
- trading session;
- duplicate/idempotency state;
- current positions and open orders;
- maximum order and position limits;
- aggregate exposure;
- daily realized/unrealized loss circuit breaker;
- global kill-switch state.

Initial defaults prohibit leverage, shorts, options, derivatives, and live execution. Numeric paper limits are configuration values with conservative defaults and must be visible in the dashboard and each `RiskDecision`.

#### Execution router

The router accepts only risk-approved `OrderIntent` values. Each adapter declares capabilities and environment identity. An adapter must refuse operation when:

- its environment is not positively identified as paper/simulation;
- the venue does not support the requested order type;
- quantity precision or minimums are invalid;
- the Archives state path is unavailable;
- its kill switch is active.

#### Ledger and reconciliation

The ledger is append-only for signals, risk decisions, order intents, and execution events. Derived positions and P&L can be rebuilt from lifecycle events. Alpaca paper positions and open orders are reconciled against local state at startup and periodically while running. Disagreements are surfaced and block new orders until resolved.

#### API and dashboard

Preserve the existing FastAPI and React foundations. Extend them rather than rebuilding unrelated UI. The unified dashboard must show:

- current mode, with `PAPER` visually unambiguous;
- venue health and environment identity;
- portfolio and exposure by asset class;
- open orders and lifecycle state;
- strategy proposals and risk rejections;
- weather calibration/reliability reports;
- circuit-breaker and kill-switch state;
- audit links for every paper order.

## 6. Execution modes

The configuration schema supports these modes:

1. `backtest`: historical data and simulated execution;
2. `paper`: external Alpaca paper execution or internal prediction-market simulation;
3. `read_only`: account/market inspection with order methods unavailable;
4. `live`: reserved enum value but disabled by policy and build-time/startup validation.

Initial deployment permits only `backtest`, `paper`, and `read_only`. Merely setting an environment variable must not enable `live`. Live support requires a separate implementation, credentials store, specification, explicit user approval, and test evidence.

## 7. Initial adapter matrix

| Adapter | Data | Orders | Initial mode | Credentials required now |
|---|---:|---:|---|---:|
| Alpaca Paper | Yes | Paper only | Enabled after paper credentials | Yes, at final paper connection |
| Internal stock/crypto simulator | Yes | Simulated | Enabled for credential-free smoke tests | No |
| Polymarket | Public/read-only | Simulated only | Enabled | No for public data |
| Kalshi | Public/read-only where supported | Simulated only | Enabled | No for public data |
| Coinbase | Optional public/read-only | Disabled | Disconnected | No |
| Robinhood Trading MCP | Disabled | Disabled | Disconnected | No |

Alpaca is the sole external paper order destination. Crypto paper orders also use Alpaca. Coinbase is not required to reach paper-ready status.

## 8. Storage and migration design

### 8.1 Canonical layout

```text
/Volumes/Archives/Hermes-Offload/2026-08-23/trading-system/
├── unified-trading-system/
│   ├── .git/
│   ├── backend/
│   ├── frontend/
│   ├── trading/
│   ├── tests/
│   └── docs/
├── PrimoAgent/
├── data/
│   ├── ledgers/
│   ├── market/
│   └── research/
├── artifacts/
│   ├── backtests/
│   └── reports/
├── logs/
├── envs/
├── caches/
└── backups/
```

The existing system is the history-bearing base of `unified-trading-system`; this is not a from-scratch replacement.

### 8.2 Preflight

Before each runtime start and migration step:

- confirm `/Volumes/Archives` is mounted;
- confirm the expected APFS volume identity;
- confirm writability with an actual create/write/flush/fsync/rename test;
- confirm sufficient free space;
- refuse to fall back to the internal disk.

The preflight performed during design found the drive writable, fsync-capable, and approximately 11 TiB free.

### 8.3 Migration sequence

1. Stop and verify absence of trading-system processes.
2. Create the canonical Archives directories.
3. Copy the Git working tree and metadata without treating ignored caches as source.
4. Copy ignored configuration files with restrictive permissions and without logging values.
5. Use SQLite's online backup mechanism for each live database.
6. Recreate Python and frontend dependencies under Archives.
7. Place pip/npm/application caches and temporary paths on Archives.
8. Archive unrelated `.firecrawl` data outside the trading repository.
9. Verify file manifests, hashes for irreplaceable state, Git commit identity, SQLite integrity, row counts, tests, frontend build, and runtime smoke checks.
10. Rename the original local directory to a temporary rollback path.
11. Create a symlink at the original path pointing to the canonical Archives repository.
12. Re-run tests and startup through the symlink.
13. Remove the temporary local rollback copy only after explicit final migration verification and user-visible reporting.

No existing Archives data is deleted or overwritten silently. Conflicting paths cause a stop and report.

### 8.4 Drive-unavailable behavior

If Archives is absent, the system must:

- refuse order evaluation/submission;
- not create a substitute database on the internal disk;
- emit a clear health failure;
- keep the dashboard/API unavailable or read-only using no stale mutable state.

## 9. Paper-trading safety defaults

The initial configuration uses these conservative, visible defaults:

- long-only;
- default instrument allowlist: `SPY`, `QQQ`, `BTC/USD`, and `ETH/USD`; weather contracts must separately pass the existing venue, station, liquidity, and edge gates;
- no leverage or margin;
- no options, futures, derivatives, staking, lending, transfers, or shorting;
- maximum order notional: the lesser of $1,000 and 1% of current paper net liquidation value;
- maximum position notional per instrument: 5% of paper net liquidation value;
- maximum aggregate gross exposure: 25% of paper net liquidation value;
- maximum concurrent non-weather positions: five;
- maximum submitted orders: 20 per UTC day across stock and crypto strategies;
- daily-loss circuit breaker: halt new orders at a 1% decline from start-of-day paper net liquidation value;
- stock and crypto quote freshness: reject snapshots older than 30 seconds at decision time;
- prediction-market quote freshness: reject snapshots older than five minutes;
- weather forecast freshness: retain the stricter existing provider/station policy and reject any forecast whose run metadata is absent;
- equity market-hours validation;
- duplicate order-intent rejection by deterministic idempotency key;
- cancel/reconcile before retry after ambiguous broker responses;
- market orders permitted only for the bounded Alpaca paper smoke test; automated strategies use limit orders with a two-percent midpoint collar;
- global kill switch available from CLI and dashboard;
- audit record for every proposal, rejection, submission, and broker event.

These are paper-safety controls, not recommendations about investment suitability. Values live in versioned configuration rather than strategy code, appear in every `RiskDecision`, and can be tightened without changing a strategy. Expanding the instrument allowlist or loosening a limit requires an explicit configuration change and an audit event.

## 10. Backtesting requirements

Every promoted strategy must have:

- an explicit evaluation period and out-of-sample period;
- point-in-time-safe inputs;
- a relevant passive benchmark;
- fees and exchange/broker fee assumptions;
- spread/slippage assumptions;
- market-hours and liquidity constraints;
- trade count, turnover, drawdown, volatility, and exposure reporting;
- no claim of edge based solely on aggregate return;
- a no-trade outcome when confidence/edge thresholds are not met.

AI-agent runs used in backtests must be cached/replayable or replaced by deterministic fixtures so the same test inputs produce reproducible results.

## 11. Error handling and reconciliation

- Network timeouts produce unknown/ambiguous outcomes, not automatic duplicate submissions.
- The router queries broker state by client/idempotency identifier before retrying.
- Rejected and unsupported orders are terminal unless a new `OrderIntent` is created.
- Partial fills update exposure incrementally.
- Startup reconciliation occurs before strategies can emit executable intents.
- Clock skew and stale-data errors block orders.
- SQLite writes use transactions and durability settings appropriate for an external APFS volume.
- Corrupt or failed integrity checks block startup and preserve the database for diagnosis.
- Adapter exceptions are normalized into typed error codes and do not leak credentials.

## 12. Testing and verification

### 12.1 Baseline preservation

- Existing 272 backend tests must continue to pass.
- The frontend production build must continue to pass.
- Existing weather audit, calibration, and venue-reliability tests remain mandatory.

### 12.2 New automated tests

- domain-contract serialization and validation;
- risk-gate acceptance/rejection matrix;
- mode and endpoint fail-closed behavior;
- stale-data and duplicate-order rejection;
- position/exposure accounting;
- adapter capability contracts;
- Alpaca paper request/response normalization using mocks;
- Polymarket/Kalshi simulation parity;
- append-only ledger and deterministic rebuild;
- startup reconciliation scenarios;
- drive-unavailable behavior;
- secret-redaction tests;
- API/dashboard contract tests.

### 12.3 Integration verification

Without credentials:

- run deterministic stock, crypto, and weather backtests;
- run an internal paper simulation;
- verify the system rejects all live endpoints;
- verify the dashboard/API from the Archives path and old-path symlink.

After the user supplies Alpaca paper credentials:

- positively verify the Alpaca paper endpoint and account identity;
- read balances, positions, clock, and assets;
- submit a bounded paper order;
- observe its broker lifecycle;
- cancel if still open;
- reconcile broker and local state;
- verify the complete audit chain.

No Robinhood or Coinbase credentials are needed for initial acceptance.

## 13. Paper-ready acceptance criteria

The system is paper-ready only when all of the following are true:

1. The canonical runtime and mutable state are on Archives.
2. The old local project path resolves to the Archives repository.
3. Git history includes the weather reliability baseline commit.
4. Legacy SQLite integrity and expected row counts are verified.
5. Existing and new automated suites pass from Archives.
6. The frontend production build passes from Archives.
7. One command starts the API/dashboard with `PAPER` mode visible.
8. One command starts a selected paper strategy.
9. Internal simulation runs without credentials.
10. Alpaca paper mode refuses a live endpoint or live credential set.
11. After paper credentials are supplied, an Alpaca paper-order lifecycle is recorded and reconciled.
12. Polymarket and Kalshi execute only against internal simulated ledgers.
13. Robinhood and Coinbase order paths remain unavailable.
14. A global kill switch halts new intents and is covered by tests.
15. The migration report includes exact source/destination paths and verification results.

## 14. Implementation tracks

The umbrella design will be implemented through independently reviewable plans:

### Track A — Storage migration and core contracts

- establish canonical Archives layout;
- migrate Git and state safely;
- create domain contracts, execution modes, ledger abstractions, and drive preflight;
- preserve rollback and compatibility symlink.

### Track B — Alpaca stock and crypto paper trading

- integrate LumiBot/Alpaca paper dependencies;
- implement normalized Alpaca adapter and reconciliation;
- add conservative sample stock and spot-crypto strategies;
- validate credential-free mocks, then user-connected paper smoke.

### Track C — Weather prediction-market preservation

- port existing weather signals and audit pipeline behind normalized contracts;
- retain Polymarket/Kalshi discovery and station mappings;
- keep both venues simulation-only;
- prove behavior with existing and new parity tests.

### Track D — Unified API, dashboard, and operations

- expose portfolio, proposals, risk decisions, orders, fills, and venue health;
- extend dashboard for stocks, crypto, and weather;
- add scheduler, health checks, kill switch, runbooks, and audit reports.

A later separately approved track may add read-only Robinhood/Coinbase account mirroring. Any real-money capability requires a new design and plan.

## 15. Licensing and dependency policy

- LumiBot is GPL-3.0. The initial system is for private/internal use.
- Do not vendor or modify LumiBot source unless necessary; depend on a pinned, audited release.
- Before sharing the system with friends, distributing binaries/source, or commercializing it, perform a dedicated GPL compliance/legal review.
- If distribution requirements conflict with the intended use, reconsider NautilusTrader (LGPL-3.0) or LEAN (Apache-2.0) before external distribution.
- Pin all direct dependencies and commit lockfiles.
- Run dependency auditing in CI and record approved exceptions with expiry dates.
- Do not adopt PrimoAgent's vulnerable LangChain 0.x environment.

## 16. Credential boundary

Credentials must never be committed, logged, copied into prompts, or written to generated reports.

Initial credential sequence:

1. Build and verify without credentials.
2. User creates/connects an Alpaca Paper account and supplies paper-only credentials through the approved local secret mechanism.
3. System verifies the endpoint is paper before enabling the adapter.
4. Robinhood Agentic MCP onboarding remains disconnected.
5. Coinbase CDP credentials remain absent.

A future Robinhood connection must use Robinhood's official MCP and a dedicated Agentic account. A future Coinbase connection must use scoped CDP credentials tied to a segregated portfolio. Neither future connection inherits permission to trade merely because credentials exist.

## 17. Rollback

Migration rollback is successful when:

- the original local path can be restored from the temporary rollback directory;
- the pre-migration commit and database hashes match;
- no external paper orders remain open unexpectedly;
- no Archives data is deleted;
- failures and recovery actions are recorded in the migration report.

Implementation rollback occurs per track through small commits. The pre-unification branch and commit remain addressable.

## 18. Primary sources

- Alpaca Paper Trading: https://docs.alpaca.markets/us/docs/paper-trading
- Robinhood Agentic Trading: https://robinhood.com/us/en/support/articles/agentic-trading-overview/
- Robinhood Trading With Your Agent: https://robinhood.com/us/en/support/articles/trading-with-your-agent/
- Coinbase Advanced Trade Sandbox: https://docs.cdp.coinbase.com/coinbase-app/advanced-trade-apis/sandbox
- LumiBot Alpaca integration: https://lumibot.lumiwealth.com/brokers.alpaca.html
- LumiBot Coinbase integration: https://lumibot.lumiwealth.com/brokers.ccxt.coinbase.html
- LumiBot Polymarket integration: https://lumibot.lumiwealth.com/brokers.polymarket.html
- LumiBot backtesting: https://lumibot.lumiwealth.com/backtesting.html
- NautilusTrader overview: https://nautilustrader.io/docs/latest/concepts/overview/
- NautilusTrader Coinbase integration: https://nautilustrader.io/docs/latest/integrations/coinbase/
- NautilusTrader Polymarket integration: https://nautilustrader.io/docs/latest/integrations/polymarket/
- PrimoAgent: https://github.com/ivebotunac/PrimoAgent
