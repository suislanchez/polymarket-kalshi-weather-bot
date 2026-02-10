# Kalshi Weather + Econ Trading Bot Architecture

## Overview

A selective trading bot that exploits pricing inefficiencies in Kalshi prediction markets by combining deterministic data pipelines with disciplined position sizing. Focuses exclusively on **weather** and **economics** contracts where free, high-quality data sources provide genuine informational edges.

**Core Philosophy**: Deterministic math for clean signals, AI only for ambiguous synthesis. No edge, no trade.

---

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              LAYER 1: SCANNER                                │
│  Polls Kalshi API every 30s → Classifies contracts → Routes to pipelines    │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                    ┌─────────────────┴─────────────────┐
                    ▼                                   ▼
┌─────────────────────────────────┐   ┌─────────────────────────────────────┐
│     LAYER 2A: WEATHER PIPELINE  │   │     LAYER 2B: ECON PIPELINE         │
│  ┌───────────────────────────┐  │   │  ┌─────────────────────────────┐    │
│  │ NWS API (api.weather.gov) │  │   │  │ Fed: SOFR futures + pyfedwatch│  │
│  │ - Hourly forecasts        │  │   │  │ CPI: Cleveland Fed Nowcast    │  │
│  │ - Probability ranges      │  │   │  │      + PPI + Import Prices    │  │
│  └───────────────────────────┘  │   │  │ Jobs: Claims + ADP + ISM      │  │
│  ┌───────────────────────────┐  │   │  │ GDP: Atlanta Fed GDPNow       │  │
│  │ ECMWF Open Data           │  │   │  │ Yields: Treasury XML feed     │  │
│  │ - 51-member ensemble      │  │   │  └─────────────────────────────┘    │
│  │ - 4x daily updates        │  │   │                                     │
│  └───────────────────────────┘  │   │  Output: Probability + Confidence   │
│  ┌───────────────────────────┐  │   │                                     │
│  │ HRRR (for <12h contracts) │  │   │                                     │
│  │ - Hourly updates          │  │   │                                     │
│  │ - 3km resolution          │  │   │                                     │
│  └───────────────────────────┘  │   │                                     │
│                                 │   │                                     │
│  Output: Blended Probability    │   │                                     │
└─────────────────────────────────┘   └─────────────────────────────────────┘
                    │                                   │
                    └─────────────────┬─────────────────┘
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                         LAYER 3: EDGE CALCULATOR                             │
│                                                                              │
│  edge = bot_probability - market_probability                                 │
│                                                                              │
│  ┌─────────────────────────────────────────────────────────────────────┐    │
│  │                         FILTER CHAIN                                 │    │
│  │  1. Minimum Edge: 10-18pp depending on category + confidence        │    │
│  │  2. Confidence: Ensemble agreement, source correlation              │    │
│  │  3. Time Decay: 6h=10pp, 12h=12pp, 24h=14pp, 48h=18pp              │    │
│  │  4. Liquidity: Skip if <$200 on orderbook                          │    │
│  │  5. Concentration: Max 15% per city, 20% per econ release          │    │
│  └─────────────────────────────────────────────────────────────────────┘    │
│                                                                              │
│  ~200 contracts scanned → ~5 trades taken per cycle                         │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       LAYER 4: SIZING + EXECUTION                            │
│                                                                              │
│  Position Size = 0.25 × (edge / odds_against)  [Quarter-Kelly]              │
│  Caps: 5% bankroll per trade, $500 max, 2% of daily volume                  │
│                                                                              │
│  Execution:                                                                  │
│  - Limit orders only (post 1c inside spread)                                │
│  - Walk up 1c every 5 min if unfilled                                       │
│  - Cross spread immediately if edge >20pp and <2h to settlement            │
└─────────────────────────────────────────────────────────────────────────────┘
                                      │
                                      ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                       LAYER 5: CALIBRATION + LEARNING                        │
│                                                                              │
│  Post-Settlement Logging:                                                    │
│  - Category, model prob, market price, edge, confidence, size, result, P&L  │
│                                                                              │
│  Weekly Calibration:                                                         │
│  - Brier score by category                                                  │
│  - Adjust edge thresholds if model over/under-confident                     │
│  - Reweight data sources by predictive accuracy                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## File Structure

```
kalshi-trading-bot/
├── ARCHITECTURE.md          # This file
├── config/
│   ├── settings.yaml        # API keys, thresholds, Kelly fraction
│   ├── cities.json          # City → NWS grid point mappings
│   └── econ_calendar.json   # Data release schedule
├── research/
│   ├── weather.py           # NWS + ECMWF + HRRR pipeline
│   ├── econ.py              # Fed/CPI/Jobs/GDP pipelines
│   └── parser.py            # Contract text → structured data (uses Claude for edge cases)
├── data/
│   ├── fetchers/
│   │   ├── nws.py           # api.weather.gov client
│   │   ├── ecmwf.py         # ecmwf-opendata wrapper
│   │   ├── hrrr.py          # NOAA NOMADS client
│   │   ├── sofr.py          # CME SOFR futures
│   │   ├── fed_nowcast.py   # Cleveland Fed + Atlanta Fed
│   │   └── bls.py           # BLS API (claims, jobs)
│   └── cache.py             # Local caching for API responses
├── execution/
│   ├── scanner.py           # Kalshi API polling + market classification
│   ├── pricing.py           # Edge calculation + filter chain
│   ├── sizing.py            # Kelly criterion + risk limits
│   ├── executor.py          # Order placement + management
│   └── kalshi_client.py     # Kalshi REST API wrapper
├── calibration/
│   ├── ledger.py            # Trade logging (SQLite)
│   ├── brier.py             # Brier score calculation
│   └── recalibrate.py       # Threshold + weight adjustments
├── logs/
│   └── trades.db            # SQLite database of all trades
└── main.py                  # Entry point: runs the scan→research→price→execute loop
```

---

## Layer-by-Layer Implementation Plan

### Layer 1: Market Scanner (`execution/scanner.py`)

**Purpose**: Continuously poll Kalshi for active markets, classify them, extract structured data.

**API Endpoint**: `GET https://trading-api.kalshi.com/trade-api/v2/markets`

**Implementation Steps**:
1. Authenticate with Kalshi API (JWT token)
2. Poll every 30 seconds
3. For each market, extract:
   - `ticker`, `title`, `yes_bid`, `yes_ask`, `volume`, `close_time`
4. Classify into categories using regex patterns:
   - Weather: matches city names + temperature/precipitation keywords
   - Econ: matches "CPI", "Fed", "payroll", "GDP", "yield" keywords
   - Skip: everything else
5. Parse contract details:
   - Weather: city, threshold (e.g., "45°F"), direction (above/below), settlement time
   - Econ: series (CPI/Fed/Jobs/GDP), threshold, release date
6. For edge cases regex can't handle, call Claude Sonnet API with structured prompt

**Output**: List of `ParsedContract` objects routed to appropriate research module

---

### Layer 2A: Weather Pipeline (`research/weather.py`)

**Purpose**: Produce probability estimates for weather contracts using ensemble model data.

**Data Sources**:

| Source | Endpoint | Update Freq | Best For |
|--------|----------|-------------|----------|
| NWS | `api.weather.gov/gridpoints/{office}/{x},{y}/forecast/hourly` | 1-6h | General forecasts |
| ECMWF | `ecmwf-opendata` Python package | 4x daily | 1-5 day range |
| HRRR | NOAA NOMADS `nomads.ncep.noaa.gov` | Hourly | <12h contracts |

**Implementation Steps**:
1. Map contract city → NWS grid point (maintain lookup table in `config/cities.json`)
2. Pull NWS hourly forecast, extract temperature distribution for target time
3. Pull ECMWF ensemble, count members above/below threshold
4. For <12h contracts, also pull HRRR
5. Compute blended probability:
   - <12h: 50% HRRR, 30% ECMWF, 20% NWS
   - 12-24h: 45% ECMWF, 35% NWS, 20% HRRR
   - 24-48h: 55% ECMWF, 45% NWS
6. Compute confidence score: % of ensemble members agreeing

**Output**: `WeatherEstimate(probability=0.872, confidence=0.86, sources=["ECMWF", "NWS"])`

---

### Layer 2B: Economics Pipeline (`research/econ.py`)

**Purpose**: Produce probability estimates for economic data contracts.

**Sub-Modules**:

#### Fed Rate Decisions
- Pull SOFR futures curve (CME delayed data or `pyfedwatch` library)
- Replicate FedWatch calculation: derive meeting-by-meeting probabilities
- Cross-check with Atlanta Fed Market Probability Tracker
- Output: probability of hold/hike/cut

#### CPI
- Pull Cleveland Fed Inflation Nowcast (daily update)
- Pull recent PPI from BLS API (leading indicator)
- Pull import price index
- Weight by historical accuracy
- Output: probability CPI exceeds threshold

#### Jobs (Nonfarm Payrolls)
- Track 4-week moving average of initial claims (BLS)
- Pull ADP National Employment Report (2 days before BLS)
- Check ISM employment sub-index
- Output: probability jobs exceed threshold

#### GDP
- Pull Atlanta Fed GDPNow (real-time estimate)
- Output: probability GDP exceeds threshold

#### Treasury Yields
- Pull daily yields from Treasury XML feed
- Model yield volatility from recent history
- Compute probability of crossing threshold

**Output**: `EconEstimate(probability=0.71, confidence=0.75, sources=["Cleveland Fed", "PPI"], reasoning="...")`

---

### Layer 3: Edge Calculator (`execution/pricing.py`)

**Purpose**: Compare model probability to market price, apply filter chain, decide trade/skip.

**Edge Calculation**:
```python
edge = model_probability - market_mid_price  # for YES bets
# OR
edge = (1 - model_probability) - (1 - market_mid_price)  # for NO bets
```

**Filter Chain** (all must pass):

| Filter | Condition | Rationale |
|--------|-----------|-----------|
| Min Edge | Edge >= threshold (varies by category/confidence) | Small edges get eaten by spread |
| Confidence | If ensemble <35/51 agree, double threshold | Uncertain models need bigger edges |
| Time Decay | Shorter settlement = lower threshold | Near-term edges more reliable |
| Liquidity | Orderbook depth >= $200 | Must be able to fill |
| Concentration | <15% per city, <20% per release | Limit single-point-of-failure risk |

**Edge Thresholds**:
- Weather <24h, high confidence: 12pp
- Weather 24-48h: 16pp
- Econ with 3+ sources agreeing: 10pp
- Econ with 1 source: 18pp

**Output**: `TradeSignal(direction="YES", edge=0.15, confidence=0.86, pass_filters=True)`

---

### Layer 4: Sizing + Execution (`execution/sizing.py`, `execution/executor.py`)

**Kelly Criterion**:
```python
kelly_fraction = edge / (1 - market_price)  # odds against
position_fraction = 0.25 * kelly_fraction   # quarter-Kelly
```

**Risk Caps**:
- Max 5% of bankroll per trade
- Max $500 per trade
- Max 2% of contract's daily volume
- Max 15% of bankroll in any single city
- Max 20% of bankroll on any single econ release

**Execution Strategy**:
1. Post limit order 1 cent inside current spread
2. Wait 5 minutes for fill
3. If unfilled, walk up 1 cent, repeat
4. For <2h contracts with >20pp edge, cross spread immediately

**Order Management**:
- Track all open orders
- Cancel unfilled orders if edge shrinks below threshold
- Log all fills with timestamp, price, size

---

### Layer 5: Calibration (`calibration/ledger.py`, `calibration/brier.py`)

**Trade Logging** (SQLite):
```sql
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    timestamp TEXT,
    category TEXT,           -- "weather" or "econ"
    subcategory TEXT,        -- city name or econ series
    contract_ticker TEXT,
    model_probability REAL,
    market_price REAL,
    edge REAL,
    confidence REAL,
    position_size REAL,
    direction TEXT,          -- "YES" or "NO"
    result TEXT,             -- "WIN" or "LOSS"
    pnl REAL,
    sources TEXT             -- JSON array of data sources used
);
```

**Weekly Calibration**:
1. Group trades by predicted probability bucket (50-60%, 60-70%, etc.)
2. Compute actual win rate per bucket
3. If model says 80% but actual is 72%, model is 8pp overconfident
4. Adjust edge thresholds: required_edge += (predicted - actual)
5. Compute Brier score by category, track trend over time

**Source Reweighting**:
- Track accuracy by data source
- If ECMWF trades outperform NWS trades, shift blend weights
- If Cleveland Fed Nowcast beats PPI model, increase its weight

---

## AI Integration Points

**Where AI is used** (Claude Sonnet API):

1. **Contract Parsing** (~5% of operations)
   - When regex can't parse contract title cleanly
   - Prompt: "Extract category, city/series, threshold, direction, settlement from: [title]"
   - Output: JSON

2. **Daily Anomaly Check** (1x per day)
   - Send summary of trades, outcomes, calibration stats
   - Prompt: "Review this trading summary. Flag any concerning patterns."
   - Output: List of flags for human review (not auto-acted)

**Where AI is NOT used**:
- Probability calculations (deterministic math on ensemble data)
- Edge calculations (simple subtraction)
- Kelly sizing (formula)
- Execution logic (deterministic rules)
- Calibration updates (statistical recalculation)

---

## Data Source Reference

### Weather

| Source | URL | Auth | Update Frequency |
|--------|-----|------|------------------|
| NWS Forecast | `api.weather.gov/gridpoints/{office}/{x},{y}/forecast` | None | 1-6 hours |
| ECMWF Open | `ecmwf-opendata` Python package | None | 4x daily (00/06/12/18Z) |
| HRRR | `nomads.ncep.noaa.gov/pub/data/nccf/com/hrrr/prod/` | None | Hourly |

### Economics

| Source | URL/Method | Auth | Update Frequency |
|--------|------------|------|------------------|
| SOFR Futures | CME delayed data or `pyfedwatch` | None | Daily |
| Cleveland Fed Nowcast | `clevelandfed.org/indicators-and-data/inflation-nowcasting` | None | Daily |
| Atlanta Fed GDPNow | `atlantafed.org/cqer/research/gdpnow` | None | After each release |
| BLS Claims | `api.bls.gov/publicAPI/v2/timeseries/data/` | API Key (free) | Weekly |
| Treasury Yields | `home.treasury.gov/resource-center/data-chart-center/interest-rates/` | None | Daily |

---

## Expected Performance

Based on documented mispricing in these markets:

- **Trades per day**: 8-15 (highly filtered from 150-250 scanned)
- **Win rate**: 60-70% (on filtered high-edge trades)
- **Average win**: $15-40
- **Average loss**: $10-25
- **Monthly return**: 15-40% initially, declining as markets become more efficient

**Key Success Factor**: Selectivity. The bot that trades everything loses. The bot that waits for 15pp edges on 24h weather contracts with 45/51 ensemble agreement wins.

---

## Implementation Order

1. **Week 1**: Scanner + Kalshi API client
2. **Week 2**: Weather pipeline (NWS + ECMWF)
3. **Week 3**: Edge calculator + filter chain
4. **Week 4**: Sizing + execution
5. **Week 5**: Econ pipeline (start with Fed, then CPI)
6. **Week 6**: Calibration + logging
7. **Week 7**: Paper trading (log signals but don't execute)
8. **Week 8**: Live trading with 10% of intended bankroll
