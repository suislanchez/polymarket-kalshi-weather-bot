from datetime import date

from backend.core.weather_methodology import (
    WeatherBucketLine,
    WeatherGateInput,
    build_hko_daily_extract_url,
    build_wunderground_history_api_url,
    build_wunderground_neighbor_source_urls,
    evaluate_station_anomaly_diagnostic,
    estimate_bucket_probability,
    evaluate_bucket_set_sanity,
    evaluate_weather_trade_gate,
    infer_hko_temperature_metric,
    parse_hko_daily_extract_observation,
    parse_nws_cli_climate_report,
    parse_settlement_metadata,
    parse_weather_rule_target_date,
    parse_wunderground_current_observation,
    parse_wunderground_history_observation,
    select_final_nws_cli_report,
)
from backend.data.weather_markets import _parse_weather_market_title


def test_parse_settlement_metadata_extracts_wunderground_airport_station_and_precision():
    text = """
    This market will resolve according to the Weather Underground page for
    London City Airport Station (EGLC). The high will be measured in whole
    degrees Celsius and rounded to the nearest whole degree.
    """

    metadata = parse_settlement_metadata(text)

    assert metadata.source == "wunderground"
    assert metadata.station_code == "EGLC"
    assert metadata.station_name == "London City Airport"
    assert metadata.units == "celsius"
    assert metadata.precision == "whole-degree"
    assert metadata.has_exact_source is True


def test_parse_settlement_metadata_extracts_wunderground_url_station_name_and_source_url():
    text = """
    The resolution source will be information from Wunderground, specifically
    the highest temperature recorded for all times on this day by the Forecast
    for the Hartsfield-Jackson International Airport Station once information
    is finalized, available here:
    https://www.wunderground.com/history/daily/us/ga/atlanta/KATL.
    The resolution source measures temperatures to whole degrees Fahrenheit.
    """

    metadata = parse_settlement_metadata(text)

    assert metadata.source == "wunderground"
    assert metadata.station_code == "KATL"
    assert metadata.station_name == "Hartsfield-Jackson International Airport"
    assert metadata.source_url == "https://www.wunderground.com/history/daily/us/ga/atlanta/KATL"
    assert metadata.units == "fahrenheit"
    assert metadata.precision == "whole-degree"
    assert metadata.has_exact_source is True


def test_parse_settlement_metadata_extracts_recorded_at_wunderground_station_phrase():
    text = """
    This market will resolve to the temperature range that contains the highest
    temperature recorded at the Incheon Intl Airport Station in degrees Celsius
    on 3 Jun '26. The resolution source will be information from Wunderground,
    available here: https://www.wunderground.com/history/daily/kr/incheon/RKSI.
    The resolution source measures temperatures to whole degrees Celsius.
    """

    metadata = parse_settlement_metadata(text)

    assert metadata.source == "wunderground"
    assert metadata.station_code == "RKSI"
    assert metadata.station_name == "Incheon Intl Airport"
    assert metadata.source_url == "https://www.wunderground.com/history/daily/kr/incheon/RKSI"
    assert metadata.units == "celsius"
    assert metadata.precision == "whole-degree"
    assert metadata.has_exact_source is True


def test_parse_weather_rule_target_date_handles_polymarket_apostrophe_year_and_stale_years():
    fresh_text = """
    This market will resolve to the highest temperature recorded at the Incheon Intl Airport
    Station in degrees Celsius on 4 Jun '26. The resolution source is Wunderground.
    """
    stale_text = "Highest temperature in London on June 6? Resolves in degrees Fahrenheit on 6 Jun '25."

    assert parse_weather_rule_target_date(fresh_text).isoformat() == "2026-06-04"
    assert parse_weather_rule_target_date(stale_text).isoformat() == "2025-06-06"


def test_parse_weather_rule_target_date_uses_reference_year_for_month_day_titles():
    assert parse_weather_rule_target_date(
        "Highest temperature in Denver on June 5?",
        reference_date=date(2026, 6, 3),
    ).isoformat() == "2026-06-05"


def test_parse_settlement_metadata_extracts_nws_daily_climate_station():
    text = "NWS Daily Climate Report for Chicago Midway (CLIMDW / KMDW), maximum temperature."

    metadata = parse_settlement_metadata(text)

    assert metadata.source == "nws_cli"
    assert metadata.station_code == "KMDW"
    assert metadata.product_code == "CLIMDW"
    assert metadata.station_name == "Chicago Midway"
    assert metadata.has_exact_source is True


def test_weather_market_title_parser_converts_celsius_city_markets_to_fahrenheit_threshold():
    parsed = _parse_weather_market_title("London highest temperature on May 21? 24°C or above")

    assert parsed is not None
    assert parsed["city_key"] == "london"
    assert parsed["city_name"] == "London"
    assert parsed["threshold_f"] == 75.2
    assert parsed["metric"] == "high"
    assert parsed["direction"] == "above"
    assert parsed["target_date"] == date(2026, 5, 21)


def test_weather_market_title_parser_preserves_polymarket_range_bucket_bounds():
    parsed = _parse_weather_market_title(
        "Will the lowest temperature in New York City be between 72-73°F on June 12?"
    )

    assert parsed is not None
    assert parsed["city_key"] == "nyc"
    assert parsed["metric"] == "low"
    assert parsed["direction"] == "bucket"
    assert parsed["bucket_low_f"] == 72.0
    assert parsed["bucket_high_f"] == 73.0
    assert parsed["target_date"] == date(2026, 6, 12)


def test_weather_market_title_parser_treats_exact_celsius_bucket_as_bucket_not_above():
    parsed = _parse_weather_market_title(
        "Will the lowest temperature in Hong Kong be 25°C on June 13?"
    )

    assert parsed is not None
    assert parsed["city_key"] == "hong_kong"
    assert parsed["metric"] == "low"
    assert parsed["direction"] == "bucket"
    assert parsed["threshold_f"] == 77.0
    assert parsed["bucket_low_f"] == 77.0
    assert parsed["bucket_high_f"] == 77.0
    assert parsed["target_date"] == date(2026, 6, 13)


def test_station_anomaly_diagnostic_blocks_missing_context_and_flags_large_neighbor_delta():
    missing_observation = evaluate_station_anomaly_diagnostic(None, [71.0, 72.0])
    assert missing_observation.status == "not_checked_missing_observation"
    assert missing_observation.neighbor_count == 2
    assert missing_observation.max_delta is None

    missing_neighbors = evaluate_station_anomaly_diagnostic(72.0, [])
    assert missing_neighbors.status == "not_checked_missing_neighbors"
    assert missing_neighbors.neighbor_count == 0
    assert missing_neighbors.max_delta is None

    passing = evaluate_station_anomaly_diagnostic(72.0, [70.8, 73.1], max_delta=3.0)
    assert passing.status == "pass"
    assert passing.neighbor_count == 2
    assert passing.max_delta == 1.2
    assert passing.threshold == 3.0

    warning = evaluate_station_anomaly_diagnostic(42.0, [29.5, 30.0], max_delta=5.0)
    assert warning.status == "warning"
    assert warning.neighbor_count == 2
    assert warning.max_delta == 12.5
    assert "exceeds 5.0" in warning.reason


def test_parse_hko_daily_extract_observation_reads_target_day_high_low_and_missing_date():
    payload = """
    {
      "stn": {
        "data": [
          {"month": 6, "dayData": [
            ["04", "1003.3", "34.2", "30.8", "27.5", "25.3", "73", "44", "  0.2"],
            ["Mean/Total", "1005.9", "33.5", "30.1", "28.0", "25.1", "75", "67", "  0.2"]
          ]}
        ]
      }
    }
    """

    high = parse_hko_daily_extract_observation(payload, date(2026, 6, 4), metric="high")
    assert high.status == "hko_daily_extract_observed"
    assert high.value_c == 34.2
    assert high.observed_at == "2026-06-04"
    assert high.metric == "high"

    low = parse_hko_daily_extract_observation(payload, date(2026, 6, 4), metric="low")
    assert low.status == "hko_daily_extract_observed"
    assert low.value_c == 27.5
    assert low.metric == "low"

    missing = parse_hko_daily_extract_observation(payload, date(2026, 6, 6), metric="high")
    assert missing.status == "hko_daily_extract_missing_target_date"
    assert missing.value_c is None


def test_hko_daily_extract_endpoint_and_metric_inference_are_target_specific():
    assert build_hko_daily_extract_url(date(2026, 6, 7)) == (
        "https://www.weather.gov.hk/cis/dailyExtract/dailyExtract_202606.xml"
    )
    assert infer_hko_temperature_metric("Will the highest temperature in Hong Kong be 28°C or below?") == "high"
    assert infer_hko_temperature_metric("Will the lowest temperature in Hong Kong be 26°C or above?") == "low"
    assert infer_hko_temperature_metric("lowest-temperature-in-hong-kong-on-june-7-2026") == "low"


def test_build_wunderground_neighbor_source_urls_replaces_station_segment_and_limits_neighbors():
    neighbors = build_wunderground_neighbor_source_urls(
        "https://www.wunderground.com/history/daily/us/ny/new-york-city/KLGA?cm_ven=localwx_history",
        ["KJFK", "klga", "KEWR", "KJFK", ""],
        max_neighbors=2,
    )

    assert neighbors == [
        ("KJFK", "https://www.wunderground.com/history/daily/us/ny/new-york-city/KJFK"),
        ("KEWR", "https://www.wunderground.com/history/daily/us/ny/new-york-city/KEWR"),
    ]
    assert build_wunderground_neighbor_source_urls(
        "https://www.weather.gov.hk/en/cis/climat.htm",
        ["VHHH"],
    ) == []



def test_parse_wunderground_current_observation_uses_station_specific_app_state_and_blocks_date_mismatch():
    payload = """
    <html><script id="app-root-state" type="application/json">{
      "111": {
        "s": 200,
        "u": "https://api.weather.com/v3/wx/observations/current?icaoCode=ZGSZ&units=e",
        "b": {
          "validTimeLocal": "2026-06-09T22:57:54+0800",
          "temperature": 79,
          "temperatureMax24Hour": 83,
          "temperatureMin24Hour": 76
        }
      },
      "222": {
        "s": 200,
        "u": "https://api.weather.com/v3/wx/observations/current?icaoCode=KSEA&units=e",
        "b": {
          "validTimeLocal": "2026-06-09T07:54:51-0700",
          "temperature": 61,
          "temperatureMax24Hour": 66,
          "temperatureMin24Hour": 58
        }
      }
    }</script></html>
    """

    high = parse_wunderground_current_observation(
        payload,
        date(2026, 6, 9),
        station_code="ZGSZ",
        metric="high",
    )
    assert high.status == "wunderground_current_24h_high_observed"
    assert high.value_f == 83
    assert high.observed_unit == "fahrenheit"
    assert high.observed_at == "2026-06-09T22:57:54+0800"
    assert high.source_field == "temperatureMax24Hour"

    low = parse_wunderground_current_observation(
        payload,
        date(2026, 6, 9),
        station_code="ZGSZ",
        metric="lowest temperature",
    )
    assert low.status == "wunderground_current_24h_low_observed"
    assert low.value_f == 76
    assert low.source_field == "temperatureMin24Hour"

    mismatch = parse_wunderground_current_observation(
        payload,
        date(2026, 6, 8),
        station_code="ZGSZ",
        metric="high",
    )
    assert mismatch.status == "wunderground_current_date_mismatch"
    assert mismatch.value_f is None
    assert "does not match target date" in mismatch.reason


def test_build_and_parse_wunderground_history_observation_uses_target_day_icao_history():
    url = build_wunderground_history_api_url(
        "https://www.wunderground.com/history/daily/cn/shanghai/ZSPD?cm_ven=localwx_history",
        station_code="ZSPD",
        target_date=date(2026, 6, 11),
        api_key="PUBLIC_PAGE_KEY",
    )

    assert url == (
        "https://api.weather.com/v1/location/ZSPD:9:CN/observations/historical.json"
        "?units=e&startDate=20260611&endDate=20260611&apiKey=PUBLIC_PAGE_KEY"
    )

    payload = """
    {
      "metadata": {"location_id": "ZSPD:9:CN", "status_code": 200},
      "observations": [
        {"valid_time_gmt": 1781107200, "obs_id": "ZSPD", "temp": 70},
        {"valid_time_gmt": 1781136000, "obs_id": "ZSPD", "temp": 88},
        {"valid_time_gmt": 1781191800, "obs_id": "ZSPD", "temp": 73}
      ]
    }
    """

    high = parse_wunderground_history_observation(
        payload,
        date(2026, 6, 11),
        station_code="ZSPD",
        metric="high",
    )

    assert high.status == "wunderground_history_partial_high_observed"
    assert high.value_f == 88
    assert high.observed_unit == "fahrenheit"
    assert high.observation_count == 3
    assert high.source_field == "temp"
    assert high.observed_at == "2026-06-11"
    assert "partial" in high.reason

    low = parse_wunderground_history_observation(
        payload,
        date(2026, 6, 11),
        station_code="ZSPD",
        metric="low",
    )
    assert low.status == "wunderground_history_partial_low_observed"
    assert low.value_f == 70

    mismatch = parse_wunderground_history_observation(
        '{"metadata": {"location_id": "RJTT:9:JP"}, "observations": []}',
        date(2026, 6, 11),
        station_code="ZSPD",
        metric="high",
    )
    assert mismatch.status == "wunderground_history_station_mismatch"
    assert mismatch.value_f is None


def test_weather_gate_rejects_missing_source_wide_spread_low_depth_and_near_threshold():
    bad = evaluate_weather_trade_gate(
        WeatherGateInput(
            settlement_source=None,
            station_code=None,
            market_probability=0.52,
            best_bid=0.42,
            best_ask=0.62,
            top_ask_size=4.0,
            ensemble_mean=78.0,
            threshold_f=77.0,
            target_date=date(2026, 5, 19),
        )
    )

    assert bad.allowed is False
    assert "missing exact settlement source/station" in bad.reasons
    assert "spread 20.0% exceeds 8.0% cap" in bad.reasons
    assert "top ask size 4.0 below 10.0 minimum" in bad.reasons
    assert "ensemble mean is only 1.0°F from threshold (<3.0°F buffer)" in bad.reasons


def test_weather_gate_allows_exact_source_liquid_book_and_buffered_threshold():
    ok = evaluate_weather_trade_gate(
        WeatherGateInput(
            settlement_source="nws_cli",
            station_code="KNYC",
            market_probability=0.40,
            best_bid=0.38,
            best_ask=0.42,
            top_ask_size=25.0,
            ensemble_mean=84.5,
            threshold_f=80.0,
            target_date=date(2026, 5, 19),
        )
    )

    assert ok.allowed is True
    assert ok.reasons == []


def test_weather_bucket_model_counts_ensemble_members_inside_inclusive_range():
    probability = estimate_bucket_probability(
        values=[76.9, 77.0, 77.4, 78.0, 78.9, 79.0],
        bucket_low_f=77.0,
        bucket_high_f=78.0,
    )

    assert probability == 0.5


def test_parse_nws_cli_climate_report_uses_summary_header_date_and_maximum_line():
    report = parse_nws_cli_climate_report(
        """
        000
        CDUS41 KOKX 260633
        CLINYC

        CLIMATE REPORT
        NATIONAL WEATHER SERVICE NEW YORK, NY
        233 AM EDT TUE MAY 26 2026

        ...THE CENTRAL PARK NY CLIMATE SUMMARY FOR MAY 25 2026...

        WEATHER ITEM   OBSERVED TIME   RECORD YEAR NORMAL DEPARTURE LAST
          MAXIMUM         73    529 PM  95    1880  74     -1       66
          MINIMUM         55    410 AM  41    1925  58     -3       52
        SUNRISE AND SUNSET
        MAY 26 2026..........SUNRISE   529 AM EDT
        """,
        product_id="final-nyc",
        issuance_time="2026-05-26T06:33:00+00:00",
    )

    assert report.report_date == date(2026, 5, 25)
    assert report.maximum_f == 73
    assert report.product_code == "CLINYC"
    assert report.station_name == "CENTRAL PARK NY"
    assert report.is_final is True
    assert report.preliminary_reason is None


def test_parse_nws_cli_climate_report_marks_valid_today_as_preliminary():
    report = parse_nws_cli_climate_report(
        """
        CLIMDW
        ...THE CHICAGO-MIDWAY CLIMATE SUMMARY FOR MAY 25 2026...
        VALID TODAY AS OF 0400 PM LOCAL TIME.
          MAXIMUM         83   3:35 PM  90    1950  74     9       66
        """
    )

    assert report.report_date == date(2026, 5, 25)
    assert report.maximum_f == 83
    assert report.is_final is False
    assert report.preliminary_reason == "preliminary valid-today product"


def test_parse_nws_cli_climate_report_marks_valid_as_of_same_day_product_as_preliminary():
    report = parse_nws_cli_climate_report(
        """
        CLIDEN
        ...THE DENVER CO CLIMATE SUMMARY FOR JUNE 13 2026...
        VALID AS OF 0600 AM LOCAL TIME.
          MAXIMUM         69   1200 AM  99    1994  83    -14       86
        """,
        product_id="early-denver",
        issuance_time="2026-06-13T12:28:00+00:00",
    )

    assert report.report_date == date(2026, 6, 13)
    assert report.maximum_f == 69
    assert report.is_final is False
    assert report.preliminary_reason == "preliminary valid-as-of product"


def test_select_final_nws_cli_report_requires_target_date_and_final_product():
    preliminary = parse_nws_cli_climate_report(
        """
        CLISEA
        ...THE SEATTLE-TACOMA WA AIRPORT CLIMATE SUMMARY FOR MAY 25 2026...
        VALID TODAY AS OF 0500 PM LOCAL TIME.
          MAXIMUM         59    851 AM  87    1947  68     -9       69
        """,
        product_id="prelim",
        issuance_time="2026-05-26T01:17:00+00:00",
    )
    wrong_date = parse_nws_cli_climate_report(
        """
        CLISEA
        ...THE SEATTLE-TACOMA WA AIRPORT CLIMATE SUMMARY FOR MAY 24 2026...
          MAXIMUM         69    851 AM  87    1947  68      1       69
        """,
        product_id="wrong-date",
        issuance_time="2026-05-25T08:37:00+00:00",
    )
    final = parse_nws_cli_climate_report(
        """
        CLISEA
        ...THE SEATTLE-TACOMA WA AIRPORT CLIMATE SUMMARY FOR MAY 25 2026...
          MAXIMUM         60    851 AM  87    1947  68     -8       69
        """,
        product_id="final",
        issuance_time="2026-05-26T08:26:00+00:00",
    )

    selected = select_final_nws_cli_report([preliminary, wrong_date, final], date(2026, 5, 25))

    assert selected is not None
    assert selected == final
    assert selected.product_id == "final"


def test_weather_bucket_set_sanity_blocks_incomplete_probability_mass():
    diagnostic = evaluate_bucket_set_sanity([
        WeatherBucketLine("b77", 77, 78, 0.25),
        WeatherBucketLine("b79", 79, 80, 0.25),
        WeatherBucketLine("b81", 81, 82, 0.20),
    ])

    assert diagnostic.passed is False
    assert diagnostic.line_count == 3
    assert diagnostic.valid_range_count == 3
    assert diagnostic.probability_mass == 0.70
    assert "bucket set probability mass 70.0% outside 98%-102% sanity band" in diagnostic.reasons


def test_weather_bucket_set_sanity_passes_complete_non_overlapping_mass():
    diagnostic = evaluate_bucket_set_sanity([
        WeatherBucketLine("b77", 77, 78, 0.25),
        WeatherBucketLine("b79", 79, 80, 0.35),
        WeatherBucketLine("b81", 81, 82, 0.40),
    ])

    assert diagnostic.passed is True
    assert diagnostic.probability_mass == 1.0
    assert diagnostic.has_probability_mass_sanity is True
    assert diagnostic.has_overlapping_ranges is False
    assert diagnostic.reasons == []
