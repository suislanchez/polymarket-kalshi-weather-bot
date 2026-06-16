"""Checked-in weather settlement station/source metadata.

Kalshi daily US temperature markets settle from final NWS Daily Climate
Report/CLI products.  Forecast/model inputs must target the same station, not a
broad metro centroid.  This module is deliberately dependency-light so cron and
unit tests can import it without ORM/API setup.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, Optional, Tuple


@dataclass(frozen=True)
class WeatherStationMapping:
    """Exact settlement/model station metadata for a weather city/series."""

    city_key: str
    city_name: str
    series_tickers: Tuple[str, ...]
    observation_station: str
    station_name: str
    latitude: float
    longitude: float
    nws_office: str
    nws_gridpoint: Optional[str]
    cli_product_code: str
    cli_location_code: str
    settlement_source_url: str
    settlement_source: str = "nws_cli"
    units: str = "fahrenheit"
    precision: str = "whole-degree"


# Station coordinates are the settlement station/observation point, not broad
# downtown metro coordinates.  URLs are official NWS CLI product pages observed
# in Kalshi public series metadata.
KALSHI_WEATHER_STATION_MAP: Dict[str, WeatherStationMapping] = {
    "los_angeles": WeatherStationMapping(
        city_key="los_angeles",
        city_name="Los Angeles",
        series_tickers=("KXHIGHLAX", "KXLOWTLAX", "KXLOWLAX"),
        observation_station="KLAX",
        station_name="Los Angeles International Airport",
        latitude=33.9416,
        longitude=-118.4085,
        nws_office="LOX",
        nws_gridpoint="LOX/149,43",
        cli_product_code="CLILAX",
        cli_location_code="LAX",
        settlement_source_url="https://forecast.weather.gov/product.php?site=LOX&product=CLI&issuedby=LAX",
    ),
    "san_francisco": WeatherStationMapping(
        city_key="san_francisco",
        city_name="San Francisco",
        series_tickers=("KXHIGHTSFO", "KXLOWTSFO"),
        observation_station="KSFO",
        station_name="San Francisco Airport",
        latitude=37.6213,
        longitude=-122.3790,
        nws_office="MTR",
        nws_gridpoint="MTR/87,87",
        cli_product_code="CLISFO",
        cli_location_code="SFO",
        settlement_source_url="https://forecast.weather.gov/product.php?site=MTR&product=CLI&issuedby=SFO",
    ),
    "nyc": WeatherStationMapping(
        city_key="nyc",
        city_name="New York City",
        series_tickers=("KXHIGHNY", "KXLOWTNYC", "KXLOWNYC", "KXLOWNY", "HIGHNY"),
        observation_station="KNYC",
        station_name="Central Park, NY",
        latitude=40.7794,
        longitude=-73.9692,
        nws_office="OKX",
        nws_gridpoint="OKX/33,37",
        cli_product_code="CLINYC",
        cli_location_code="NYC",
        settlement_source_url="https://forecast.weather.gov/product.php?site=OKX&product=CLI&issuedby=NYC",
    ),
    "chicago": WeatherStationMapping(
        city_key="chicago",
        city_name="Chicago",
        series_tickers=("KXHIGHCHI", "KXLOWTCHI", "KXLOWCHI", "HIGHCHI"),
        observation_station="KMDW",
        station_name="Chicago Midway",
        latitude=41.7868,
        longitude=-87.7522,
        nws_office="LOT",
        nws_gridpoint="LOT/73,70",
        cli_product_code="CLIMDW",
        cli_location_code="MDW",
        settlement_source_url="https://forecast.weather.gov/product.php?site=LOT&product=CLI&issuedby=MDW",
    ),
    "miami": WeatherStationMapping(
        city_key="miami",
        city_name="Miami",
        series_tickers=("KXHIGHMIA", "KXLOWTMIA", "KXLOWMIA", "HIGHMIA"),
        observation_station="KMIA",
        station_name="Miami International Airport",
        latitude=25.7959,
        longitude=-80.2870,
        nws_office="MFL",
        nws_gridpoint="MFL/75,53",
        cli_product_code="CLIMIA",
        cli_location_code="MIA",
        settlement_source_url="https://forecast.weather.gov/product.php?site=MFL&product=CLI&issuedby=MIA",
    ),
    "denver": WeatherStationMapping(
        city_key="denver",
        city_name="Denver",
        series_tickers=("KXHIGHDEN", "KXDENHIGH", "KXHIGHTEMPDEN", "KXLOWTDEN", "KXLOWDEN"),
        observation_station="KDEN",
        station_name="Denver International Airport",
        latitude=39.8561,
        longitude=-104.6737,
        nws_office="BOU",
        nws_gridpoint="BOU/65,61",
        cli_product_code="CLIDEN",
        cli_location_code="DEN",
        settlement_source_url="https://forecast.weather.gov/product.php?site=BOU&product=CLI&issuedby=DEN",
    ),
    "seattle": WeatherStationMapping(
        city_key="seattle",
        city_name="Seattle",
        series_tickers=("KXHIGHTSEA", "KXLOWTSEA"),
        observation_station="KSEA",
        station_name="Seattle-Tacoma International Airport",
        latitude=47.4502,
        longitude=-122.3088,
        nws_office="SEW",
        nws_gridpoint="SEW/123,65",
        cli_product_code="CLISEA",
        cli_location_code="SEA",
        settlement_source_url="https://forecast.weather.gov/product.php?site=SEW&product=CLI&issuedby=SEA",
    ),
    "boston": WeatherStationMapping(
        city_key="boston",
        city_name="Boston",
        series_tickers=("KXHIGHTBOS", "KXLOWTBOS"),
        observation_station="KBOS",
        station_name="Boston Logan International Airport",
        latitude=42.3656,
        longitude=-71.0096,
        nws_office="BOX",
        nws_gridpoint="BOX/72,90",
        cli_product_code="CLIBOS",
        cli_location_code="BOS",
        settlement_source_url="https://forecast.weather.gov/product.php?site=BOX&product=CLI&issuedby=BOS",
    ),
    "philadelphia": WeatherStationMapping(
        city_key="philadelphia",
        city_name="Philadelphia",
        series_tickers=("KXHIGHPHIL", "KXPHILHIGH", "KXLOWTPHIL", "KXLOWPHIL"),
        observation_station="KPHL",
        station_name="Philadelphia International Airport",
        latitude=39.8733,
        longitude=-75.2268,
        nws_office="PHI",
        nws_gridpoint="PHI/50,75",
        cli_product_code="CLIPHL",
        cli_location_code="PHL",
        settlement_source_url="https://forecast.weather.gov/product.php?site=PHI&product=CLI&issuedby=PHL",
    ),
    "atlanta": WeatherStationMapping(
        city_key="atlanta",
        city_name="Atlanta",
        series_tickers=("KXHIGHTATL", "KXLOWTATL"),
        observation_station="KATL",
        station_name="Atlanta Hartsfield-Jackson International Airport",
        latitude=33.6407,
        longitude=-84.4277,
        nws_office="FFC",
        nws_gridpoint="FFC/52,86",
        cli_product_code="CLIATL",
        cli_location_code="ATL",
        settlement_source_url="https://forecast.weather.gov/product.php?site=FFC&product=CLI&issuedby=ATL",
    ),
    "dallas": WeatherStationMapping(
        city_key="dallas",
        city_name="Dallas",
        series_tickers=("KXHIGHTDAL", "KXLOWTDAL"),
        observation_station="KDFW",
        station_name="Dallas/Fort Worth International Airport",
        latitude=32.8998,
        longitude=-97.0403,
        nws_office="FWD",
        nws_gridpoint="FWD/88,105",
        cli_product_code="CLIDFW",
        cli_location_code="DFW",
        settlement_source_url="https://forecast.weather.gov/product.php?site=FWD&product=CLI&issuedby=DFW",
    ),
    "new_orleans": WeatherStationMapping(
        city_key="new_orleans",
        city_name="New Orleans",
        series_tickers=("KXHIGHTNOLA", "KXLOWTNOLA"),
        observation_station="KMSY",
        station_name="New Orleans International Airport",
        latitude=29.9934,
        longitude=-90.2580,
        nws_office="LIX",
        nws_gridpoint="LIX/59,90",
        cli_product_code="CLIMSY",
        cli_location_code="MSY",
        settlement_source_url="https://forecast.weather.gov/product.php?site=LIX&product=CLI&issuedby=MSY",
    ),
    "oklahoma_city": WeatherStationMapping(
        city_key="oklahoma_city",
        city_name="Oklahoma City",
        series_tickers=("KXHIGHTOKC", "KXLOWTOKC"),
        observation_station="KOKC",
        station_name="Oklahoma City Will Rogers World Airport",
        latitude=35.3931,
        longitude=-97.6007,
        nws_office="OUN",
        nws_gridpoint="OUN/53,73",
        cli_product_code="CLIOKC",
        cli_location_code="OKC",
        settlement_source_url="https://forecast.weather.gov/product.php?site=OUN&product=CLI&issuedby=OKC",
    ),
    "las_vegas": WeatherStationMapping(
        city_key="las_vegas",
        city_name="Las Vegas",
        series_tickers=("KXHIGHTLV", "KXLOWTLV"),
        observation_station="KLAS",
        station_name="Las Vegas Harry Reid International Airport",
        latitude=36.0719,
        longitude=-115.1634,
        nws_office="VEF",
        nws_gridpoint="VEF/124,96",
        cli_product_code="CLILAS",
        cli_location_code="LAS",
        settlement_source_url="https://forecast.weather.gov/product.php?site=VEF&product=CLI&issuedby=LAS",
    ),
}

SERIES_TO_WEATHER_STATION: Dict[str, WeatherStationMapping] = {
    series: mapping
    for mapping in KALSHI_WEATHER_STATION_MAP.values()
    for series in mapping.series_tickers
}


def get_station_mapping_for_city(city_key: str) -> Optional[WeatherStationMapping]:
    """Return exact station mapping for a normalized city key."""
    return KALSHI_WEATHER_STATION_MAP.get(city_key)


def get_station_mapping_for_series(series_ticker: str) -> Optional[WeatherStationMapping]:
    """Return exact station mapping for a Kalshi temperature series ticker."""
    return SERIES_TO_WEATHER_STATION.get(series_ticker)


def city_config_from_mapping(mapping: WeatherStationMapping) -> dict:
    """Convert a settlement mapping into a forecast/observation city config."""
    return {
        "name": mapping.city_name,
        "lat": mapping.latitude,
        "lon": mapping.longitude,
        "nws_station": mapping.observation_station,
        "nws_office": mapping.nws_office,
        "nws_gridpoint": mapping.nws_gridpoint,
        "settlement_source": mapping.settlement_source,
        "settlement_station_name": mapping.station_name,
        "settlement_product_code": mapping.cli_product_code,
        "settlement_source_url": mapping.settlement_source_url,
    }
