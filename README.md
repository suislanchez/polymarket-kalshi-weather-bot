# Prediction Market Trading Bot

A sophisticated trading bot that identifies pricing inefficiencies in weather prediction markets by comparing ensemble weather forecasts against market odds. Features a professional React dashboard with interactive 3D globe visualization.

![Python](https://img.shields.io/badge/python-3.10+-blue) ![React](https://img.shields.io/badge/react-18+-61DAFB) ![TypeScript](https://img.shields.io/badge/typescript-5.0+-blue) ![License](https://img.shields.io/badge/license-MIT-green)

**100% free to run** - No paid APIs, no subscriptions. All data sources are free.

## Overview

This bot scans weather-related prediction markets on **Kalshi** and **Polymarket**, then uses ensemble weather forecasting data to calculate the true probability of weather outcomes. When the model's probability significantly differs from market prices (edge > 8%), it generates trading signals with Kelly-optimal position sizing.

### Key Features

- **Ensemble Weather Forecasting** - Uses 31-member GFS ensemble from Open-Meteo for probabilistic temperature predictions
- **Multi-Platform Support** - Scans both Kalshi and Polymarket for weather markets
- **Edge Detection** - Identifies mispriced markets where model probability differs from market odds
- **Kelly Criterion Sizing** - Calculates optimal position sizes using quarter-Kelly for risk management
- **3D Globe Visualization** - Interactive globe showing weather data confidence across 13+ cities
- **Professional Dashboard** - React frontend with Framer Motion animations and glass morphism design
- **Simulation Mode** - Paper trading with virtual bankroll tracking and equity curves

## Quick Start

### 1. Backend Setup

```bash
cd kalshi-trading-bot

# Create virtual environment
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Run the backend
uvicorn api.main:app --reload --port 8000
```

Backend will be at: http://localhost:8000
API docs at: http://localhost:8000/docs

### 2. Frontend Setup

```bash
cd frontend

# Install dependencies
npm install

# Run the frontend
npm run dev
```

Frontend will be at: http://localhost:3000

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                         FRONTEND                                 │
│  React + TypeScript + Framer Motion + react-globe.gl            │
│  ┌─────────┐ ┌─────────┐ ┌─────────┐ ┌─────────┐               │
│  │ 3D Globe│ │  Stats  │ │ Signals │ │ Trades  │               │
│  └─────────┘ └─────────┘ └─────────┘ └─────────┘               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                         BACKEND                                  │
│  FastAPI + Python + SQLite                                      │
│  ┌─────────────┐ ┌─────────────┐ ┌─────────────┐               │
│  │   Weather   │ │   Markets   │ │   Signals   │               │
│  │   Fetcher   │ │   Scanner   │ │  Generator  │               │
│  └─────────────┘ └─────────────┘ └─────────────┘               │
└─────────────────────────────────────────────────────────────────┘
                              │
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│                       DATA SOURCES                               │
│  ┌───────────┐ ┌───────────┐ ┌───────────┐ ┌───────────┐       │
│  │ Open-Meteo│ │  NWS API  │ │  Kalshi   │ │Polymarket │       │
│  │ Ensemble  │ │           │ │   API     │ │ Gamma API │       │
│  └───────────┘ └───────────┘ └───────────┘ └───────────┘       │
└─────────────────────────────────────────────────────────────────┘
```

## How It Works

### 1. Weather Data Collection
- Fetches 31-member GFS ensemble forecasts from Open-Meteo
- Calculates probability distributions for temperature thresholds (40°F, 50°F, 60°F)
- Confidence scores based on ensemble agreement

### 2. Market Scanning
- Scans Kalshi for temperature high/low markets
- Scans Polymarket for weather-related contracts
- Extracts current market probabilities (yes/no prices)

### 3. Edge Calculation
```
edge = model_probability - market_probability
```
Signals are generated when `|edge| > 8%` (configurable threshold)

### 4. Position Sizing (Quarter-Kelly)
```
kelly_fraction = (edge * confidence) / (1 - market_probability)
position_size = bankroll * kelly_fraction * 0.25
```
Capped at 5% of bankroll per trade.

## API Endpoints

| Endpoint | Method | Description |
|----------|--------|-------------|
| `/api/dashboard` | GET | All dashboard data in one call |
| `/api/weather` | GET | Current weather predictions |
| `/api/markets` | GET | Active weather markets |
| `/api/signals` | GET | All trading signals |
| `/api/signals/actionable` | GET | Signals above threshold |
| `/api/trades` | GET | Trade history |
| `/api/stats` | GET | Bot statistics |
| `/api/run-scan` | POST | Trigger market scan |
| `/api/simulate-trade` | POST | Simulate a trade |

## Configuration

Edit `backend/config.py` to customize:

```python
BOT_CONFIG = {
    "bankroll": 10000,           # Starting virtual bankroll
    "min_edge": 0.08,            # Minimum edge to generate signal (8%)
    "kelly_fraction": 0.25,      # Quarter-Kelly for risk management
    "max_position_pct": 0.1,     # Max 10% of bankroll per trade
    "min_confidence": 0.5,       # Minimum model confidence
}
```

## Supported Cities

Weather data and markets tracked for 13 US cities:
- New York, Chicago, Los Angeles, Miami, Denver
- Seattle, Phoenix, Houston, Philadelphia, San Francisco
- Boston, Atlanta, Dallas

## Tech Stack

### Backend
- **FastAPI** - Modern async web framework
- **SQLAlchemy** - ORM for trade logging
- **httpx** - Async HTTP client
- **NumPy/SciPy** - Statistical calculations

### Frontend
- **React 18** - UI framework
- **TypeScript** - Type safety
- **react-globe.gl** - 3D globe visualization
- **Framer Motion** - Professional animations
- **Recharts** - Charts and graphs
- **TanStack Query** - Data fetching
- **Tailwind CSS** - Styling

## Data Sources

All free, no API keys required:

| Source | Data | Rate Limit |
|--------|------|------------|
| Open-Meteo | GFS Ensemble (31 members) | 10,000/day |
| NWS API | US Weather Forecasts | Unlimited |
| Kalshi | Temperature Markets | Public API |
| Polymarket | Weather Contracts | Gamma API |

## Project Structure

```
kalshi-trading-bot/
├── backend/
│   ├── api/
│   │   └── main.py              # FastAPI app
│   ├── core/
│   │   └── signals.py           # Signal generator
│   ├── data/
│   │   ├── weather.py           # Weather fetchers
│   │   └── markets.py           # Market fetchers
│   ├── models/
│   │   └── database.py          # SQLAlchemy models
│   └── config.py                # Settings
├── frontend/
│   ├── src/
│   │   ├── components/
│   │   │   ├── Globe.tsx        # 3D globe visualization
│   │   │   ├── StatsCards.tsx   # Performance metrics
│   │   │   ├── SignalsTable.tsx # Trading signals
│   │   │   ├── TradesTable.tsx  # Trade history
│   │   │   └── EquityChart.tsx  # P&L chart
│   │   ├── App.tsx
│   │   ├── api.ts
│   │   └── types.ts
│   └── package.json
├── requirements.txt
├── run.py
└── README.md
```

## Deployment Options

### Option A: Single VPS ($5/mo)

```bash
# On your VPS
git clone <your-repo>
cd kalshi-trading-bot

# Backend (with systemd or pm2)
pip install -r requirements.txt
uvicorn api.main:app --host 0.0.0.0 --port 8000 &

# Frontend (build static files)
cd frontend
npm install && npm run build
# Serve with nginx
```

### Option B: Railway + Vercel (Free Tier)

1. Push to GitHub
2. Connect backend to Railway
3. Connect frontend to Vercel
4. Update API URL in frontend

## Disclaimer

This is a **simulation tool** for educational purposes. It does not place real trades or use real money. Past performance in simulation does not guarantee future results. Prediction markets involve risk of loss.

## License

MIT - do whatever you want with it.
