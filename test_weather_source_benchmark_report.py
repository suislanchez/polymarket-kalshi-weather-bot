from datetime import datetime, timezone

from backend.core.weather_source_benchmark import (
    SourceBenchmarkRow,
    build_source_promotion_policy,
    summarize_source_benchmark,
)


def _row(
    source,
    *,
    lead_seconds,
    temp_delta=0.0,
    flags=None,
    station_id="KJFK",
):
    ts = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    return SourceBenchmarkRow(
        source=source,
        station_id=station_id,
        authority_source="aviationweather_metar",
        observed_at=ts,
        fetched_at=ts,
        temp_f=68.0 + temp_delta,
        freshness_seconds=60.0,
        source_lead_seconds_vs_authority=lead_seconds,
        temp_delta_f_vs_authority=temp_delta,
        raw_hash=f"{source}-hash",
        source_url=f"https://example.com/{source}",
        quality_flags=list(flags or []),
    )


def test_source_benchmark_summary_aggregates_latency_quality_and_missingness():
    rows = [
        _row("nws_latest_observation", lead_seconds=45.0, temp_delta=0.2),
        _row("nws_latest_observation", lead_seconds=15.0, temp_delta=-0.1, station_id="KORD"),
        _row("open_meteo_current", lead_seconds=-120.0, temp_delta=2.2, flags=["temperature_delta_gt_1f", "slower_than_authority"]),
    ]

    summary = summarize_source_benchmark(rows, failures={"madis": "not_configured"})

    assert summary["nws_latest_observation"]["sample_count"] == 2
    assert summary["nws_latest_observation"]["median_lead_seconds_vs_authority"] == 30.0
    assert summary["nws_latest_observation"]["mean_abs_temp_delta_f_vs_authority"] == 0.15
    assert summary["nws_latest_observation"]["quality_flag_counts"] == {}
    assert summary["open_meteo_current"]["sample_count"] == 1
    assert summary["open_meteo_current"]["median_lead_seconds_vs_authority"] == -120.0
    assert summary["open_meteo_current"]["quality_flag_counts"] == {
        "slower_than_authority": 1,
        "temperature_delta_gt_1f": 1,
    }
    assert summary["madis"]["sample_count"] == 0
    assert summary["madis"]["failure"] == "not_configured"


def test_promotion_policy_keeps_sources_from_lock_authority_without_evidence():
    summary = {
        "aviationweather_metar": {
            "sample_count": 12,
            "median_lead_seconds_vs_authority": 0.0,
            "mean_abs_temp_delta_f_vs_authority": 0.0,
            "quality_flag_counts": {},
        },
        "nws_latest_observation": {
            "sample_count": 12,
            "median_lead_seconds_vs_authority": 42.0,
            "mean_abs_temp_delta_f_vs_authority": 0.4,
            "quality_flag_counts": {},
        },
        "open_meteo_current": {
            "sample_count": 12,
            "median_lead_seconds_vs_authority": -300.0,
            "mean_abs_temp_delta_f_vs_authority": 1.8,
            "quality_flag_counts": {"temperature_delta_gt_1f": 8},
        },
        "madis": {
            "sample_count": 0,
            "failure": "not_configured",
            "quality_flag_counts": {},
        },
    }

    policy = build_source_promotion_policy(summary, minimum_samples=10)

    assert policy["aviationweather_metar"]["role"] == "lock_authority"
    assert policy["nws_latest_observation"]["role"] == "watch_only"
    assert policy["nws_latest_observation"]["reason"] == "faster_than_authority_but_not_lock_authority_without_settlement_backtest"
    assert policy["open_meteo_current"]["role"] == "reject"
    assert "median_lead_seconds_vs_authority_-300.0" in policy["open_meteo_current"]["reason"]
    assert policy["madis"]["role"] == "insufficient_data"
