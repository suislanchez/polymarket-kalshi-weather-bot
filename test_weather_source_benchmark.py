from datetime import datetime, timezone

from backend.core.weather_source_benchmark import (
    SourceObservation,
    benchmark_observation_sources,
    rank_source_benchmarks,
)


def test_source_benchmark_ranks_sources_by_latency_against_metar_authority():
    metar_observed = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    fetched_at = datetime(2026, 6, 3, 15, 53, tzinfo=timezone.utc)

    observations = [
        SourceObservation(
            source="aviationweather_metar",
            station_id="KJFK",
            observed_at=metar_observed,
            fetched_at=fetched_at,
            temp_f=68.0,
            source_url="https://aviationweather.gov/api/data/metar?ids=KJFK",
            raw_hash="metar",
        ),
        SourceObservation(
            source="nws_latest_observation",
            station_id="KJFK",
            observed_at=datetime(2026, 6, 3, 15, 50, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
            temp_f=68.2,
            source_url="https://api.weather.gov/stations/KJFK/observations/latest",
            raw_hash="nws",
        ),
        SourceObservation(
            source="open_meteo_current",
            station_id="KJFK",
            observed_at=datetime(2026, 6, 3, 15, 45, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 6, 3, 15, 54, tzinfo=timezone.utc),
            temp_f=66.0,
            source_url="https://api.open-meteo.com/v1/forecast",
            raw_hash="openmeteo",
        ),
    ]

    rows = rank_source_benchmarks(observations, authority_source="aviationweather_metar")

    assert [row.source for row in rows] == [
        "nws_latest_observation",
        "aviationweather_metar",
        "open_meteo_current",
    ]
    assert rows[0].source_lead_seconds_vs_authority == 60.0
    assert rows[0].temp_delta_f_vs_authority == 0.2
    assert rows[0].freshness_seconds == 120.0
    assert rows[0].authority_source == "aviationweather_metar"
    assert rows[2].quality_flags == ["temperature_delta_gt_1f", "slower_than_authority"]


def test_benchmark_observation_sources_keeps_provider_failures_visible():
    def ok_provider(_station_id, _lat, _lon):
        return SourceObservation(
            source="aviationweather_metar",
            station_id="KJFK",
            observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
            fetched_at=datetime(2026, 6, 3, 15, 53, tzinfo=timezone.utc),
            temp_f=68.0,
            source_url="metar-url",
            raw_hash="metar",
        )

    def failing_provider(_station_id, _lat, _lon):
        raise TimeoutError("nws timeout")

    result = benchmark_observation_sources(
        station_id="KJFK",
        lat=40.6413,
        lon=-73.7781,
        providers=[ok_provider, failing_provider],
    )

    assert [row.source for row in result.rows] == ["aviationweather_metar"]
    assert result.failures == {"failing_provider": "TimeoutError: nws timeout"}
    assert result.station_id == "KJFK"
