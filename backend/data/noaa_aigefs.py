"""Optional NOAA AIGEFS forecast adapter.

This module is intentionally defensive: any upstream shape changes or transport
errors return ``None`` so weather scans continue with the primary provider.
"""

from __future__ import annotations

import logging
from datetime import date
from typing import Optional

import httpx

from backend.config import settings
from backend.data.weather import CITY_CONFIG, EnsembleForecast

logger = logging.getLogger("trading_bot")


async def fetch_aigefs_forecast(city_key: str, target_date: date) -> Optional[EnsembleForecast]:
    """Fetch AIGEFS-style ensemble for a city/date.

    Expected payload (flexible):
      {
        "member_highs_f": [..],
        "member_lows_f": [..]
      }

    Any failure returns ``None`` and the caller should fall back to Open-Meteo.
    """
    city = CITY_CONFIG.get(city_key)
    if not city:
        return None

    url = settings.WEATHER_AIGEFS_ENDPOINT_TEMPLATE.format(
        date=target_date.isoformat(),
        city=city_key,
    )

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.get(url)
            if response.status_code != 200:
                return None
            payload = response.json()

        highs = payload.get("member_highs_f") if isinstance(payload, dict) else None
        lows = payload.get("member_lows_f") if isinstance(payload, dict) else None
        if not isinstance(highs, list) or not highs:
            return None
        if not isinstance(lows, list) or not lows:
            lows = highs

        return EnsembleForecast(
            city_key=city_key,
            city_name=city["name"],
            target_date=target_date,
            member_highs=[float(v) for v in highs if v is not None],
            member_lows=[float(v) for v in lows if v is not None],
        )
    except Exception as exc:
        logger.debug("AIGEFS fetch failed for %s: %s", city_key, exc)
        return None
