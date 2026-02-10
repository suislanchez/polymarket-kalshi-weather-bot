# Validated Research: What Actually Works

This document contains **tested and verified** findings about APIs, data sources, and platforms.

---

## Critical Corrections to Original Blueprint

| Original Claim | Reality | Impact |
|----------------|---------|--------|
| NWS API has "probability ranges" | **FALSE** - NWS API returns deterministic point estimates only | Need different source for probabilities |
| ECMWF has 51 ensemble members | **FALSE** - ECMWF open data has **50** perturbed members + 1 control | Minor, still usable |
| HRRR provides ensemble/probability data | **FALSE** - HRRR is **deterministic only** | Need NBM or GEFS for probabilistic short-range |
| Kalshi has weather for many cities | **PARTIAL** - Core cities are NYC, Chicago, Miami, Austin; expanded to ~8-10 total | Fewer markets than implied |
| Cleveland Fed has API | **FALSE** - Must scrape website or download Excel | More complex integration |

---

## Verified Platform Markets

### Kalshi Weather Markets (Confirmed)

| City | Ticker Pattern | Settlement Source |
|------|---------------|-------------------|
| New York City | KXHIGHNY | NWS Daily Climate Report (Central Park) |
| Chicago | KXHIGHCHI | NWS Daily Climate Report |
| Miami | KXHIGHMIA | NWS Daily Climate Report |
| Austin | KXHIGHAUS | NWS Daily Climate Report |
| Los Angeles | KXHIGHLA | NWS Daily Climate Report |
| Atlanta | Available | NWS Daily Climate Report |
| Denver | Available | NWS Daily Climate Report |
| Philadelphia | Available | NWS Daily Climate Report |

**Key Insight**: Kalshi settles on NWS, so using NWS data gives you the actual settlement source.

**API Access**: Requires authentication (JWT), demo environment available at `demo-api.kalshi.co`

---

### Polymarket Weather Markets (Confirmed)

**56 active weather markets** with $3.5M+ total volume

| Market Type | Cities | Example Volume |
|-------------|--------|----------------|
| Daily High Temp | NYC, Chicago, Miami, Atlanta, Dallas, Seattle, London, Seoul, Buenos Aires, Ankara | $50k-$230k each |
| Monthly Global Temp Anomaly | Global (NASA GISTEMP) | $100k-$1M |
| Annual Records | "Hottest year on record" | $1M+ |

**API Endpoints** (confirmed working):
```
Gamma API: https://gamma-api.polymarket.com/events
CLOB API:  https://clob.polymarket.com
```

**Settlement**: NASA GISTEMP for global temp markets, likely NWS/NOAA for city temps

---

## Verified Weather Data Sources

### 1. NWS API (Tested ✅)

**What it provides**: Deterministic hourly forecasts, 7 days out

**Endpoint tested**:
```
https://api.weather.gov/gridpoints/OKX/33,37/forecast/hourly
```

**Response contains**:
- Point estimate temperature (single value per hour)
- Point estimate precipitation probability
- Wind speed/direction
- Forecast descriptions

**What it does NOT provide**:
- Ensemble members
- Probability distributions
- Confidence intervals

**Rate limit**: "Generous" - retry after 5 seconds if exceeded
**Auth**: User-Agent header required, no API key

---

### 2. NBM - National Blend of Models (Best for Probabilities ✅)

**This is the correct source for probabilistic US forecasts**

**What it provides**:
- Percentiles: 5th, 10th, 25th, 50th, 75th, 90th, 95th
- For MaxT (daily high) and MinT (daily low)
- Based on ~200 model members
- Covers CONUS, Alaska, Hawaii, Puerto Rico

**Access methods**:
```
AWS S3: s3://noaa-nbm-grib2-pds/blend.YYYYMMDD/CC/qmd/
NOMADS: https://nomads.ncep.noaa.gov/pub/data/nccf/com/blend/prod/
FTP: ftp://ftp.ncep.noaa.gov/pub/data/nccf/com/blend/prod/
```

**Format**: GRIB2 (need `cfgrib` or `pygrib` to read)

**How to interpret**:
- 90th percentile MaxT = 10% chance actual temp exceeds this value
- 10th percentile MaxT = 90% chance actual temp exceeds this value

---

### 3. ECMWF Open Data (Tested ✅)

**What it provides**:
- 50 ensemble members (perturbed forecasts)
- 1 control forecast
- 2m temperature, pressure levels, precipitation
- Global coverage at 0.25° resolution

**Python package**:
```python
pip install ecmwf-opendata

from ecmwf.opendata import Client
client = Client(source="aws")  # or "ecmwf", "azure", "google"

# Get all 50 ensemble members for 2m temperature
client.retrieve(
    stream="enfo",
    type="pf",          # perturbed forecast
    param="2t",         # 2-meter temperature
    step=24,
    number=list(range(1, 51)),  # members 1-50
    target="ensemble_temp.grib2"
)
```

**Updates**: 4x daily (00, 06, 12, 18 UTC)
**Horizon**: Up to 360 hours (15 days)
**Cost**: Free (CC-BY 4.0 license as of Oct 2025)

---

### 4. HRRR via Herbie (Tested ✅)

**What it provides**:
- High-resolution (3km) deterministic forecasts
- Hourly updates
- Up to 48 hours out
- Excellent for short-range (<12h)

**What it does NOT provide**:
- ❌ Ensemble members
- ❌ Probability distributions
- ❌ Percentiles

**Python package**:
```python
pip install herbie-data

from herbie import Herbie
H = Herbie("2026-02-10 12:00", model="hrrr", product="sfc")
ds = H.xarray("TMP:2 m")  # 2-meter temperature
```

**For probabilistic short-range, use HREF or NBM instead**

---

### 5. Open-Meteo Ensemble API (Verified ✅)

**Free alternative** that provides ensemble data via simple REST API

**What it provides**:
- 20+ ensemble models (GFS, ECMWF, ICON, etc.)
- Temperature, precipitation, wind
- Individual ensemble members accessible

**Example API call**:
```
https://ensemble-api.open-meteo.com/v1/ensemble?
  latitude=40.71&longitude=-74.01
  &hourly=temperature_2m
  &models=gfs_seamless
```

**Pricing**: Free for non-commercial use

---

## Verified Economic Data Sources

### 1. FRED API (Tested ✅)

**GDPNow tested and working**:
```
https://fred.stlouisfed.org/graph/fredgraph.csv?id=GDPNOW
```

Returns CSV with quarterly GDP estimates back to 2011.

**Python**:
```python
pip install fredapi

from fredapi import Fred
fred = Fred(api_key='your_free_key')
gdpnow = fred.get_series('GDPNOW')
```

**Rate limit**: 120 calls per 60 seconds
**Cost**: Free (register at fred.stlouisfed.org)

---

### 2. BLS API (Tested ✅)

**CPI data tested and working**:
```
https://api.bls.gov/publicAPI/v2/timeseries/data/CUSR0000SA0?startyear=2024&endyear=2025
```

Returns monthly CPI values.

**Note**: October 2025 data was missing due to government funding lapse.

**Key series IDs**:
- `CUSR0000SA0` - CPI All Items
- `CES0000000001` - Nonfarm Payrolls
- `LNS14000000` - Unemployment Rate

**Rate limit**: Tiered (higher with free API key)

---

### 3. Cleveland Fed Nowcast (Manual Only ⚠️)

**No REST API exists**. Must either:
1. Scrape the webpage
2. Download Excel file from: https://www.clevelandfed.org/indicators-and-data/inflation-nowcasting

Updates daily.

---

### 4. pyfedwatch (Partial ⚠️)

**Does NOT fetch data** - you must supply SOFR futures prices

```python
# You provide the futures data, pyfedwatch calculates probabilities
from pyfedwatch import FedWatch
# Requires manual data input
```

For actual futures data, need CME delayed data or paid feed.

---

## Recommended Architecture Changes

### Original Blueprint Weather Pipeline:
```
NWS (probability ranges) → ECMWF (51 members) → HRRR (ensemble)
```

### Corrected Weather Pipeline:
```
NBM (percentiles 5-95) → ECMWF (50 members) → HRRR (deterministic short-range)
     ↓                         ↓                      ↓
 Probabilistic           Ensemble for           Best point estimate
 for US cities          global/longer range        for <12h
```

### Alternative Simple Pipeline (using Open-Meteo):
```
Open-Meteo Ensemble API (free, REST, multiple models)
     ↓
 Get all ensemble members → Calculate your own percentiles
```

---

## Platform Comparison for Simulation

| Factor | Kalshi | Polymarket |
|--------|--------|------------|
| **Weather Markets** | 8-10 US cities | 10+ global cities + monthly anomaly |
| **API Auth** | JWT (required) | None for read, wallet for write |
| **Demo/Sandbox** | Yes (demo-api.kalshi.co) | No official sandbox |
| **Data Format** | JSON REST | JSON REST + GraphQL |
| **Settlement Source** | NWS Daily Climate Report | Varies (NWS, NASA GISTEMP) |
| **For Simulation** | Need demo account | Can read markets freely |

---

## Revised Data Source Priority

### For US City Temperature (Kalshi/Polymarket):

1. **NBM Percentiles** (primary) - Actual probabilistic forecasts, ~200 members
2. **ECMWF Ensemble** (secondary) - 50 members, global
3. **Open-Meteo Ensemble** (alternative) - Easy API, free
4. **NWS API** (settlement reference) - What Kalshi actually settles on
5. **HRRR** (short-range boost) - Best <12h deterministic

### For Global Temperature Anomaly (Polymarket):

1. **ERA5 reanalysis** (historical baseline)
2. **ECMWF seasonal** (trend)
3. **NASA GISTEMP monitoring** (actual resolution source)

### For Economics:

1. **FRED** - GDPNow, unemployment, many indicators
2. **BLS API** - CPI, jobs (with API key)
3. **Cleveland Fed** - CPI nowcast (scrape)
4. **Treasury.gov** - Yield curve (XML feed)

---

## What Still Needs Validation

1. **Kalshi demo API** - Need account to test order placement simulation
2. **Polymarket CLOB** - Need to test actual order book depth
3. **NBM GRIB2 parsing** - Need to write code to extract percentiles
4. **Settlement timing** - Exact timing of NWS Daily Climate Report release

---

## Sources

### APIs Tested
- [NWS API](https://api.weather.gov) - Tested gridpoints endpoint
- [Polymarket Gamma API](https://gamma-api.polymarket.com) - Tested events/markets
- [FRED CSV](https://fred.stlouisfed.org) - Tested GDPNOW series
- [BLS API](https://api.bls.gov) - Tested CPI series

### Documentation Verified
- [ECMWF Open Data](https://www.ecmwf.int/en/forecasts/datasets/open-data)
- [ecmwf-opendata GitHub](https://github.com/ecmwf/ecmwf-opendata)
- [Herbie Documentation](https://herbie.readthedocs.io/)
- [NBM Weather Elements](https://vlab.noaa.gov/web/mdl/nbm-weather-elements)
- [NBM on AWS](https://registry.opendata.aws/noaa-nbm/)
- [Open-Meteo Ensemble API](https://open-meteo.com/en/docs/ensemble-api)

### Market Research
- [Kalshi Weather Markets](https://help.kalshi.com/markets/popular-markets/weather-markets)
- [Polymarket Weather](https://polymarket.com/predictions/weather)
- [NYC Temperature Forecasting Research](https://github.com/aheck3/nyc-temperature-forecasting-polymarket)
