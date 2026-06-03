# Weather Edge v2.1 — Kalshi Weather Signal Engine

A professional signal dashboard for Kalshi weather markets using **METAR real-time lock detection** confirmed by **GFS forecast validation**.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![React](https://img.shields.io/badge/react-18+-61DAFB) ![TypeScript](https://img.shields.io/badge/typescript-5.0+-blue)

**100% free to run** — No paid APIs required. All data sources are free (Open-Meteo, aviationweather.gov, Kalshi public API).

---

## How It Works

Weather Edge uses a two-step process to find high-confidence trades:

### Step 1: METAR Lock Detection
After 1pm local time, airport thermometers have already recorded the day's high temperature. If a Kalshi market is still pricing "Will Dallas reach 85°F?" at 40 cents when the airport already recorded 87°F — the outcome is physically confirmed. The market hasn't caught up yet.

A METAR lock requires the current temperature to already be **5°F past the threshold** — not close, not trending toward it. Past it. That's a near-certain outcome.

### Step 2: GFS Confirmation
Every METAR lock signal is validated against the GFS weather forecast before being flagged. This catches anomalous METAR readings — if the airport reads 87°F but the GFS forecast expects a cold front to drop temps to 80°F, the signal is suppressed. Only signals where METAR and GFS agree are shown as actionable.

### Signal Tiers
| Tier | Description | Trade? |
|---|---|---|
| **METAR-lock** | Current temp already past threshold + GFS confirms | ✅ Yes |
| **GFS-ensemble** | Model probability vs Kalshi price, future days | 👀 Monitor only |

**Never bet on GFS-only signals for same-day markets.** GFS is a probabilistic forecast. METAR is a physical measurement. The edge comes from confirmed readings, not projections.

---

## Quick Start

### Backend

```bash
cd weather-edge-dashboard

# Install Python dependencies
pip install -r requirements.txt

# Run the server
python run.py
```

Backend: http://localhost:8765
API docs: http://localhost:8765/docs

### Frontend

```bash
cd frontend

# Install Node dependencies
npm install

# Start development server
npm run dev
```

Frontend: http://localhost:5173

### Build for Production

```bash
cd frontend
npm run build
# Serve the dist/ folder as static files
```

---

## Configuration

Create a `.env` file in the root directory:

```env
# Required for live trading (optional for signals-only mode)
KALSHI_API_KEY_ID=your_key_id_here
KALSHI_PRIVATE_KEY_PATH=/path/to/private_key.pem

# Trading mode
SIMULATION_MODE=true          # Set false for live trading
KALSHI_ENABLED=true
WEATHER_ENABLED=true

# Risk limits
WEATHER_MAX_TRADE_SIZE=50     # Max $ per trade
WEATHER_DAILY_LOSS_LIMIT=200  # Stop trading if daily loss exceeds this

# Signal scan interval
WEATHER_SCAN_INTERVAL_SECONDS=300   # 5 minutes
```

**Start in SIMULATION_MODE=true** until you've verified signals manually. Paper trade with the virtual $10,000 bankroll before going live.

---

## Supported Markets

### Cities (20+)
New York City, Chicago, Los Angeles, Houston, Dallas, Miami, Seattle, Denver, Phoenix, Boston, Washington DC, San Francisco, Atlanta, Minneapolis, Oklahoma City, Austin, San Antonio, New Orleans, Philadelphia, Las Vegas

### Market Types
- **High temperature** — `KXHIGHTLV`, `KXHIGHTSFO`, `KXHIGHTATL`, `KXHIGHTBOS`, etc.
- **Rain** — `KXRAINNYC`, `KXRAINHOUM`, `KXRAINSFOM`, `KXRAINCHIM`, etc.

---

## Dashboard Features

- **Signal feed** — Live METAR-lock and GFS-ensemble signals with confidence, edge, and suggested size
- **Portfolio tracker** — Real Kalshi positions, fills, P&L (requires API key)
- **Equity curve** — Track performance over time in simulation or live mode
- **3D globe view** — City signal overlays on interactive globe
- **Settings** — Configure API keys, risk limits, simulation mode

---

## Risk Management

Weather Edge has built-in safeguards:
- **Daily loss limit** — Trading stops automatically if daily losses exceed `WEATHER_DAILY_LOSS_LIMIT`
- **Max trade size** — Hard cap per trade via `WEATHER_MAX_TRADE_SIZE`
- **GFS veto** — Any METAR lock that GFS disagrees with is automatically suppressed
- **Sanity checks** — Every order is validated before submission (correct direction, correct side)

---

## What Changed in v2.1

- **GFS confirmation added** — Every METAR-lock signal now validated against GFS forecast before flagging
- **METAR-early removed from actionable signals** — GFS-projection signals are now monitor-only; never shown as tradeable for same-day markets
- **Improved sanity checks** — T-prefix and B-prefix threshold direction validation hardened

---

## Requirements

- Python 3.10+
- Node.js 18+
- ~5 minutes to set up
- No paid API keys required for signals
- Kalshi API key required for live trading and portfolio tracking

---

## Support

Questions or issues: open an issue on GitHub or contact via Gumroad.
