"""Economic data fetcher using FRED API and other sources."""
import httpx
import logging
from datetime import datetime, timedelta
from typing import Optional, Dict, Any, List
from dataclasses import dataclass

logger = logging.getLogger(__name__)

# FRED API (requires free API key)
FRED_API = "https://api.stlouisfed.org/fred"


@dataclass
class EconomicIndicator:
    """Economic indicator data point."""
    series_id: str
    name: str
    value: float
    previous_value: Optional[float]
    units: str
    release_date: datetime
    next_release: Optional[datetime]
    frequency: str  # monthly, quarterly, etc.


# Common FRED series IDs
FRED_SERIES = {
    "CPI": {
        "id": "CPIAUCSL",
        "name": "Consumer Price Index",
        "units": "Index 1982-1984=100"
    },
    "CORE_CPI": {
        "id": "CPILFESL",
        "name": "Core CPI (less food & energy)",
        "units": "Index 1982-1984=100"
    },
    "UNEMPLOYMENT": {
        "id": "UNRATE",
        "name": "Unemployment Rate",
        "units": "Percent"
    },
    "GDP": {
        "id": "GDP",
        "name": "Gross Domestic Product",
        "units": "Billions of Dollars"
    },
    "FED_FUNDS": {
        "id": "FEDFUNDS",
        "name": "Federal Funds Rate",
        "units": "Percent"
    },
    "NONFARM_PAYROLLS": {
        "id": "PAYEMS",
        "name": "Nonfarm Payrolls",
        "units": "Thousands of Persons"
    },
    "RETAIL_SALES": {
        "id": "RSXFS",
        "name": "Retail Sales",
        "units": "Millions of Dollars"
    },
    "HOUSING_STARTS": {
        "id": "HOUST",
        "name": "Housing Starts",
        "units": "Thousands of Units"
    },
    "CONSUMER_SENTIMENT": {
        "id": "UMCSENT",
        "name": "Consumer Sentiment",
        "units": "Index 1966:Q1=100"
    },
    "PCE": {
        "id": "PCEPI",
        "name": "PCE Price Index",
        "units": "Index 2017=100"
    }
}


async def fetch_fred_series(
    series_id: str,
    api_key: Optional[str] = None,
    limit: int = 10
) -> Optional[EconomicIndicator]:
    """
    Fetch latest data for a FRED series.

    Args:
        series_id: FRED series ID (e.g., "CPIAUCSL")
        api_key: FRED API key (optional, limited without it)
        limit: Number of observations to fetch

    Returns:
        EconomicIndicator or None
    """
    if not api_key:
        from backend.config import settings
        api_key = settings.FRED_API_KEY

    if not api_key:
        logger.warning("FRED_API_KEY not configured, using mock data")
        return _get_mock_indicator(series_id)

    url = f"{FRED_API}/series/observations"
    params = {
        "series_id": series_id,
        "api_key": api_key,
        "file_type": "json",
        "sort_order": "desc",
        "limit": limit
    }

    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url, params=params, timeout=10.0)
            response.raise_for_status()
            data = response.json()

            observations = data.get("observations", [])
            if not observations:
                return None

            latest = observations[0]
            previous = observations[1] if len(observations) > 1 else None

            # Get series metadata
            series_info = FRED_SERIES.get(series_id.upper(), {})

            return EconomicIndicator(
                series_id=series_id,
                name=series_info.get("name", series_id),
                value=float(latest.get("value", 0)),
                previous_value=float(previous.get("value")) if previous else None,
                units=series_info.get("units", ""),
                release_date=datetime.strptime(latest.get("date"), "%Y-%m-%d"),
                next_release=None,
                frequency="monthly"
            )

        except Exception as e:
            logger.error(f"Error fetching FRED series {series_id}: {e}")
            return None


def _get_mock_indicator(series_id: str) -> EconomicIndicator:
    """Return mock data for testing without API key."""
    mock_values = {
        "CPIAUCSL": (315.7, 314.8),
        "UNRATE": (3.7, 3.8),
        "FEDFUNDS": (5.33, 5.33),
        "GDP": (28269.5, 27956.0),
        "PAYEMS": (157533, 157275),
    }

    value, prev = mock_values.get(series_id.upper(), (100.0, 99.5))
    series_info = FRED_SERIES.get(series_id.upper(), {})

    return EconomicIndicator(
        series_id=series_id,
        name=series_info.get("name", series_id),
        value=value,
        previous_value=prev,
        units=series_info.get("units", ""),
        release_date=datetime.now() - timedelta(days=30),
        next_release=datetime.now() + timedelta(days=5),
        frequency="monthly"
    )


async def fetch_multiple_indicators(
    series_ids: List[str],
    api_key: Optional[str] = None
) -> Dict[str, EconomicIndicator]:
    """Fetch multiple FRED series."""
    import asyncio

    tasks = [fetch_fred_series(sid, api_key) for sid in series_ids]
    results = await asyncio.gather(*tasks)

    return {
        sid: result
        for sid, result in zip(series_ids, results)
        if result is not None
    }


def estimate_indicator_probability(
    current_value: float,
    threshold: float,
    direction: str,
    indicator_type: str = "general"
) -> float:
    """
    Estimate probability of indicator hitting threshold.

    Uses simple heuristics based on indicator type.
    Real implementation would use econometric models.
    """
    distance = abs(threshold - current_value)
    relative_distance = distance / current_value if current_value != 0 else 0.5

    # Different volatilities for different indicators
    volatility_estimates = {
        "unemployment": 0.05,  # +-0.2 points typical
        "cpi": 0.003,  # Very stable
        "fed_funds": 0.0,  # Usually stays put unless meeting
        "gdp": 0.02,  # 2% typical quarterly change
        "payrolls": 0.002,  # Small relative changes
    }

    vol = volatility_estimates.get(indicator_type, 0.02)

    if direction == "above":
        if current_value >= threshold:
            return 0.9
        # Simplified model
        prob = 0.5 - (relative_distance / (2 * vol))
    else:
        if current_value <= threshold:
            return 0.9
        prob = 0.5 - (relative_distance / (2 * vol))

    return max(0.05, min(0.95, prob))


# BLS Jobs Report helper
async def fetch_bls_jobs_forecast() -> Dict[str, Any]:
    """
    Fetch consensus forecast for upcoming jobs report.

    In production, you'd scrape from financial data providers
    or use a paid API. This returns mock data for now.
    """
    return {
        "nonfarm_payrolls_forecast": 185000,
        "unemployment_forecast": 3.7,
        "avg_hourly_earnings_forecast": 0.3,
        "release_date": datetime.now() + timedelta(days=5),
        "source": "mock"
    }


# Quick test
if __name__ == "__main__":
    import asyncio

    async def test():
        print("Fetching economic indicators (mock data)...")

        for key, info in list(FRED_SERIES.items())[:5]:
            indicator = await fetch_fred_series(info["id"])
            if indicator:
                change = ""
                if indicator.previous_value:
                    diff = indicator.value - indicator.previous_value
                    change = f" ({diff:+.2f})"
                print(f"  {indicator.name}: {indicator.value:.2f} {indicator.units}{change}")

    asyncio.run(test())
