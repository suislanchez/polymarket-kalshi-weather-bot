# Platform & API Research Findings

## Executive Summary

**Recommendation: Start with Kalshi only, add Polymarket later for arbitrage.**

| Factor | Kalshi | Polymarket |
|--------|--------|------------|
| **US Access** | Fully legal, regulated | Invite-only (late 2025), state lawsuits ongoing |
| **Fees** | ~1.2% average | 0.10% (100x cheaper) |
| **Weather Markets** | Daily temp for 4 cities (NYC, Chicago, Miami, Austin) | Daily temp + global anomaly markets |
| **Econ Markets** | Fed, CPI, jobs, GDP | Limited econ coverage |
| **API Quality** | REST + WebSocket, good docs | REST + WebSocket + CLOB, excellent docs |
| **Settlement** | USD via bank | USDC on Polygon |
| **Liquidity** | ~$500M/week | ~$300M/week |

**All free APIs in your blueprint are validated and working.**

---

## Platform Deep Dive

### Kalshi (Recommended for Primary)

**Pros:**
- CFTC-regulated, fully legal in US
- USD deposits/withdrawals via traditional banking
- Strong weather + econ market coverage
- REST API with 50-200ms latency
- Demo environment for testing (`demo-api.kalshi.co`)
- $25K bet limits per contract

**Cons:**
- Higher fees (~1.2% vs 0.1% Polymarket)
- Limited to 4 cities for daily weather (NYC, Chicago, Miami, Austin)
- JWT auth expires every 30 minutes (need refresh logic)
- Rate limits (not public, but "generous")

**API Endpoints:**
```
Base URL: https://trading-api.kalshi.com/trade-api/v2
Demo URL: https://demo-api.kalshi.co/trade-api/v2

GET /markets           - List all active markets
GET /markets/{ticker}  - Get specific market
GET /orderbook/{ticker} - Get order book
POST /orders           - Place order
DELETE /orders/{id}    - Cancel order
GET /portfolio         - Get positions
```

**Python SDK:** `pip install kalshi-python` (v2.1.4, Sept 2025)

**Settlement Source for Weather:** National Weather Service Daily Climate Report (not AccuWeather, not Google Weather)

---

### Polymarket (Add Later for Arbitrage)

**Pros:**
- 100x lower fees (0.10% taker)
- More weather markets (61 active, including global temp anomaly)
- Excellent API documentation
- Higher liquidity for political/crypto markets
- CLOB with WebSocket real-time updates

**Cons:**
- US access is invite-only as of Feb 2026
- Requires USDC on Polygon (crypto complexity)
- State lawsuits ongoing (Tennessee, Nevada, Massachusetts)
- Resolution differences from Kalshi (risk for arbitrage)
- KYC required through intermediaries

**API Endpoints:**
```
Gamma API: https://gamma-api.polymarket.com  (market discovery)
CLOB API:  https://clob.polymarket.com       (trading)
Data API:  https://data-api.polymarket.com   (positions)
WebSocket: wss://ws-subscriptions-clob.polymarket.com
```

**Python SDK:** `pip install py-clob-client`

**Settlement Source for Weather:** NASA GISTEMP for global temp anomaly markets

---

## Free API Validation

### Weather APIs (All Confirmed Working)

| API | Status | Rate Limit | Auth | Python Package |
|-----|--------|-----------|------|----------------|
| **NWS** | ✅ Free | "Generous" (retry after 5s if exceeded) | User-Agent header only | `requests` |
| **ECMWF Open Data** | ✅ Free | None stated | None | `ecmwf-opendata` |
| **HRRR via Herbie** | ✅ Free | None | None | `herbie-data` |

**NWS API:**
```
Endpoint: https://api.weather.gov/gridpoints/{office}/{x},{y}/forecast/hourly
Example:  https://api.weather.gov/gridpoints/OKX/33,37/forecast (NYC)
Updates:  Every 1-6 hours
Requires: User-Agent header ("YourApp, email@domain.com")
Version:  2.5 (upgraded May 2025)
```

**ECMWF Open Data:**
```python
from ecmwf.opendata import Client
client = Client(source="aws")  # or "azure", "google", "ecmwf"
# 51-member ensemble available
# 0.25° resolution, GRIB2 format
# 4x daily updates (00/06/12/18 UTC)
# Transitioned to open-data Oct 2025 (CC-BY 4.0)
```

**HRRR (Herbie):**
```python
from herbie import Herbie
H = Herbie("2025-02-10", model="hrrr", product="sfc")
# 3km resolution, hourly updates
# Free via AWS/NOAA NOMADS
# Archive since 2014
```

---

### Economics APIs (All Confirmed Working)

| API | Status | Rate Limit | Auth | Python Package |
|-----|--------|-----------|------|----------------|
| **FRED** | ✅ Free | 120 calls/60 sec | API key (free) | `fredapi` or `fedfred` |
| **BLS** | ✅ Free | Tiered (higher with key) | API key (free) | `requests` |
| **Cleveland Fed Nowcast** | ⚠️ Scraping only | N/A | None | `requests` + parse |
| **Atlanta Fed GDPNow** | ✅ Via FRED | 120/min | FRED key | `fredapi` |
| **Treasury Yields** | ✅ Free | None | None | `requests` |

**FRED API (Best for Economic Data):**
```python
from fredapi import Fred
fred = Fred(api_key='your_key')
gdpnow = fred.get_series('GDPNOW')  # Atlanta Fed GDPNow
# 120 requests per minute
# 765,000+ time series available
# Free registration at fred.stlouisfed.org
```

**BLS API:**
```
Endpoint: https://api.bls.gov/publicAPI/v2/timeseries/data/
Series IDs:
  - CUSR0000SA0 (CPI-U All Items)
  - CES0000000001 (Nonfarm Payrolls)
  - LNS14000000 (Unemployment Rate)
Requires: Free API key for v2 features
```

**Cleveland Fed Nowcast (Manual Scraping Required):**
```
URL: https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting
Format: Excel spreadsheet download
Updates: Daily
Note: No REST API - need to scrape or download Excel file
```

**pyfedwatch (SOFR/Fed Funds):**
```python
# GitHub: ARahimiQuant/pyfedwatch
# Replicates CME FedWatch calculation
# Requires you to provide futures pricing data
# Outputs FOMC meeting probabilities
# Note: Does NOT fetch data itself - you supply SOFR futures prices
```

---

## Cross-Platform Arbitrage Analysis

### Feasibility: Possible but Risky

**The Math:**
- Research shows $40M+ arbitrage profits extracted from Polymarket alone (April 2024 - April 2025)
- Typical spread: 2-5% before fees
- After fees: Kalshi 1.2% + Polymarket 0.1% = 1.3% cost
- Net margin: 0.7% - 3.7% per trade

**Critical Risks:**

1. **Resolution Differences** - In 2024, a US shutdown market resolved YES on Polymarket and NO on Kalshi for the same event. This is not theoretical risk - it happened.

2. **Execution Risk** - 78% of arbitrage opportunities in low-volume markets failed due to execution lag (2025 study)

3. **Capital Lock-up** - Funds locked until settlement (days/weeks)

4. **Regulatory** - Massachusetts sued Kalshi in Sept 2025; state-level risk is real

**Tools for Arbitrage:**
- [EventArb Calculator](https://www.eventarb.com/)
- [GitHub: polymarket-arbitrage](https://github.com/ImMike/polymarket-arbitrage)
- [Polymarket Analytics](https://polymarketanalytics.com)

**Recommendation:** Only pursue arbitrage after you have:
1. Profitable single-platform trading for 3+ months
2. Understanding of resolution differences per market type
3. Accounts funded on both platforms
4. Automated execution (manual is too slow)

---

## Weather Markets: Where the Edge Is

### Kalshi Weather (Your Primary Target)

**Available Markets:**
- NYC, Chicago, Miami, Austin daily high temperature
- Settles on NWS Daily Climate Report
- New global temperature contracts added Dec 2025

**Your Edge Sources:**
| Source | Horizon | Advantage |
|--------|---------|-----------|
| HRRR | 0-12h | 1.5°F avg error, hourly updates |
| ECMWF 51-member | 1-5 days | Ensemble probabilities |
| NWS Gridpoints | 0-7 days | Official source (matches settlement!) |

**Key Insight:** Kalshi settles on NWS, but most bettors use AccuWeather/Google. Your NWS ensemble data IS the settlement source.

### Polymarket Weather

**Available Markets:**
- Daily city temperatures (61 active markets)
- Global temperature anomaly (monthly)
- "Hottest year on record" markets

**Settlement:** NASA GISTEMP for global temp markets

---

## Economics Markets: Secondary Edge

### Kalshi Econ Markets

- Fed rate decisions
- CPI (above/below threshold)
- Nonfarm payrolls
- GDP growth
- Treasury yields

### Your Edge Sources

**Fed Decisions (Strongest Edge):**
```
Source: SOFR futures → pyfedwatch calculation
Edge: Market prices often lag futures by 2-4 hours
Horizon: Updates continuously as futures trade
```

**CPI (Moderate Edge):**
```
Primary: Cleveland Fed Nowcast (daily update)
Secondary: PPI release (2 days before CPI)
Issue: Cleveland Fed has no API - must scrape
```

**Jobs (Moderate Edge):**
```
Leading: Initial claims (weekly, BLS API)
Leading: ADP report (2 days before NFP)
Secondary: ISM employment sub-index
```

**GDP (Weak Edge):**
```
Source: Atlanta Fed GDPNow (via FRED API)
Issue: Widely followed, probably priced in
```

---

## Implementation Priority

### Phase 1: Kalshi Weather Only (Weeks 1-4)
- Simplest, highest edge, one platform
- NWS + ECMWF + HRRR pipeline
- 4 cities only (NYC, Chicago, Miami, Austin)
- Paper trade first week

### Phase 2: Kalshi Econ (Weeks 5-8)
- Add Fed decisions (SOFR futures)
- Add CPI (Cleveland Fed scraping)
- Lower edge, more complex

### Phase 3: Polymarket (When US access stabilizes)
- Monitor their regulatory situation
- Add for arbitrage only initially
- Requires USDC/Polygon setup

### Phase 4: Cross-Platform Arbitrage (Month 4+)
- Only after profitable on single platform
- Automated execution required
- Start with non-weather markets (less resolution risk)

---

## Data Source Summary Table

| Data | Source | API | Rate Limit | Package | Cost |
|------|--------|-----|------------|---------|------|
| NWS Forecast | api.weather.gov | REST | ~60/min | requests | Free |
| ECMWF Ensemble | AWS/Azure/GCP | Python | None | ecmwf-opendata | Free |
| HRRR Model | NOAA NOMADS/AWS | Python | None | herbie-data | Free |
| GDPNow | FRED | REST | 120/min | fredapi | Free |
| CPI/Jobs/Claims | BLS | REST | Tiered | requests | Free |
| Cleveland Nowcast | Website | Scrape | N/A | bs4 | Free |
| SOFR Futures | CME delayed | Manual | N/A | pyfedwatch | Free |
| Treasury Yields | Treasury.gov | XML | None | requests | Free |
| Kalshi Markets | Kalshi API | REST | "Generous" | kalshi-python | Free |
| Polymarket | Polymarket API | REST+WS | None | py-clob-client | Free |

---

## Key Corrections to Original Blueprint

1. **Cleveland Fed Nowcast has no API** - You'll need to scrape or download Excel files daily

2. **pyfedwatch doesn't fetch data** - You must supply SOFR futures prices yourself (CME delayed data or paid feed)

3. **Polymarket US access is limited** - Invite-only as of late 2025, ongoing state lawsuits

4. **Kalshi weather is only 4 cities** - Not arbitrary cities; only NYC, Chicago, Miami, Austin for daily temp

5. **Resolution differences are real** - Same event resolved differently on Kalshi vs Polymarket in 2024

6. **ECMWF went fully open Oct 2025** - Even better than before, CC-BY 4.0 license

7. **NWS is the settlement source** - This is your edge: you're using the actual settlement data source

---

## Sources

### Platform APIs
- [Kalshi API Documentation](https://docs.kalshi.com/welcome)
- [Polymarket API Endpoints](https://docs.polymarket.com/quickstart/reference/endpoints)
- [Polymarket CLOB Introduction](https://docs.polymarket.com/developers/CLOB/introduction)

### Weather Data
- [NWS API Documentation](https://www.weather.gov/documentation/services-web-api)
- [NWS Gridpoints FAQ](https://weather-gov.github.io/api/gridpoints)
- [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data)
- [Herbie Documentation](https://herbie.readthedocs.io/)
- [NOAA HRRR on AWS](https://registry.opendata.aws/noaa-hrrr-pds/)

### Economic Data
- [FRED API](https://fred.stlouisfed.org/docs/api/fred/)
- [BLS API Features](https://www.bls.gov/bls/api_features.htm)
- [Cleveland Fed Nowcasting](https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting)
- [Atlanta Fed GDPNow](https://www.atlantafed.org/research-and-data/data/gdpnow)
- [pyfedwatch GitHub](https://github.com/ARahimiQuant/pyfedwatch)

### Platform Comparison
- [Kalshi vs Polymarket Comparison](https://www.vegasinsider.com/prediction-markets/kalshi-vs-polymarket/)
- [Prediction Market Fees](https://defirate.com/learn/prediction-market-fees/)
- [Polymarket US Legal Status](https://www.gamblinginsider.com/in-depth/106291/is-polymarket-legal-in-the-us)

### Arbitrage
- [Prediction Market Arbitrage Guide](https://newyorkcityservers.com/blog/prediction-market-arbitrage-guide)
- [Cross-Platform Arbitrage Bot](https://github.com/ImMike/polymarket-arbitrage)
- [EventArb Calculator](https://www.eventarb.com/)
