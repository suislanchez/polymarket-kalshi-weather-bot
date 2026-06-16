from datetime import date

from backend.data.weather import CITY_CONFIG
from backend.data.weather_station_map import (
    KALSHI_WEATHER_STATION_MAP,
    SERIES_TO_WEATHER_STATION,
    get_station_mapping_for_city,
    get_station_mapping_for_series,
)
from backend.data.kalshi_markets import CITY_CLI_PRODUCTS, CITY_SERIES, CITY_STATION_CODES
from backend.core.weather_methodology import parse_nws_cli_climate_report, select_final_nws_cli_report


def test_core_kalshi_city_series_map_to_exact_settlement_stations():
    expected = {
        "los_angeles": ("KXHIGHLAX", "KXLOWTLAX", "KLAX", "CLILAX", "LAX", "LOX"),
        "san_francisco": ("KXHIGHTSFO", "KXLOWTSFO", "KSFO", "CLISFO", "SFO", "MTR"),
        "nyc": ("KXHIGHNY", "KXLOWTNYC", "KNYC", "CLINYC", "NYC", "OKX"),
        "chicago": ("KXHIGHCHI", "KXLOWTCHI", "KMDW", "CLIMDW", "MDW", "LOT"),
        "miami": ("KXHIGHMIA", "KXLOWTMIA", "KMIA", "CLIMIA", "MIA", "MFL"),
    }

    for city_key, (high_series, low_series, station, cli_product, cli_location, office) in expected.items():
        mapping = get_station_mapping_for_city(city_key)
        assert mapping is not None
        assert high_series in mapping.series_tickers
        assert low_series in mapping.series_tickers
        assert mapping.observation_station == station
        assert mapping.cli_product_code == cli_product
        assert mapping.cli_location_code == cli_location
        assert mapping.nws_office == office
        assert get_station_mapping_for_series(high_series) == mapping
        assert get_station_mapping_for_series(low_series) == mapping


def test_active_kalshi_temperature_series_have_checked_in_station_metadata():
    # Coverage for the current cities we scan or discovered from Kalshi public
    # weather series. This keeps new city additions from silently falling back to
    # broad metro coordinates/source metadata.
    required_city_keys = {
        "nyc",
        "chicago",
        "miami",
        "los_angeles",
        "denver",
        "seattle",
        "boston",
        "san_francisco",
        "philadelphia",
        "atlanta",
        "dallas",
        "new_orleans",
        "oklahoma_city",
        "las_vegas",
    }
    assert required_city_keys.issubset(KALSHI_WEATHER_STATION_MAP)

    for city_key in required_city_keys:
        mapping = KALSHI_WEATHER_STATION_MAP[city_key]
        assert mapping.observation_station
        assert mapping.cli_product_code.startswith("CLI")
        assert mapping.cli_location_code
        assert mapping.settlement_source_url.endswith(f"issuedby={mapping.cli_location_code}")
        assert mapping.latitude is not None and mapping.longitude is not None
        for series in mapping.series_tickers:
            assert SERIES_TO_WEATHER_STATION[series] == mapping


def test_legacy_kalshi_metadata_dicts_are_derived_from_station_map():
    assert CITY_SERIES["san_francisco"] == "KXHIGHTSFO"
    assert CITY_STATION_CODES["chicago"] == "KMDW"
    assert CITY_CLI_PRODUCTS["los_angeles"] == "CLILAX"


def test_weather_forecast_config_uses_station_coordinates_not_broad_metro_points():
    # Chicago is the critical regression: Kalshi settles at Midway, not O'Hare
    # and not downtown Chicago. NYC should target Central Park rather than a
    # generic city centroid.
    assert CITY_CONFIG["chicago"]["nws_station"] == "KMDW"
    assert round(CITY_CONFIG["chicago"]["lat"], 3) == 41.787
    assert round(CITY_CONFIG["chicago"]["lon"], 3) == -87.752

    assert CITY_CONFIG["nyc"]["nws_station"] == "KNYC"
    assert round(CITY_CONFIG["nyc"]["lat"], 3) == 40.779
    assert round(CITY_CONFIG["nyc"]["lon"], 3) == -73.969

    assert CITY_CONFIG["san_francisco"]["nws_station"] == "KSFO"
    assert round(CITY_CONFIG["san_francisco"]["lat"], 3) == 37.621


def test_select_final_nws_cli_report_can_require_station_and_product_match():
    target = date(2026, 6, 2)
    wrong_station = parse_nws_cli_climate_report(
        """
        CLIMDW
        ...THE CHICAGO-MIDWAY CLIMATE SUMMARY FOR JUNE 2 2026...
        TEMPERATURE (F)
          MAXIMUM         75   2:51 PM
        """,
        issuance_time="2026-06-03T06:33:00+00:00",
    )
    correct = parse_nws_cli_climate_report(
        """
        CLILAX
        ...THE LOS ANGELES INTL AIRPORT CA CLIMATE SUMMARY FOR JUNE 2 2026...
        TEMPERATURE (F)
          MAXIMUM         70  12:50 PM
        """,
        issuance_time="2026-06-03T08:41:00+00:00",
    )

    selected = select_final_nws_cli_report(
        [wrong_station, correct],
        target,
        expected_product_code="CLILAX",
        expected_station_name="LOS ANGELES INTL AIRPORT CA",
    )

    assert selected == correct
    assert selected.maximum_f == 70
    assert select_final_nws_cli_report(
        [wrong_station],
        target,
        expected_product_code="CLILAX",
        expected_station_name="LOS ANGELES INTL AIRPORT CA",
    ) is None
