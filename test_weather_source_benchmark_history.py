from datetime import datetime, timezone

from backend.core.weather_source_benchmark import (
    SourceBenchmarkResult,
    SourceBenchmarkRow,
    append_source_benchmark_result,
    load_source_benchmark_history,
    summarize_source_benchmark_history,
)


def _row(source, station_id="KJFK", lead=30.0, delta=0.2):
    ts = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    return SourceBenchmarkRow(
        source=source,
        station_id=station_id,
        authority_source="aviationweather_metar",
        observed_at=ts,
        fetched_at=ts,
        temp_f=68.0 + delta,
        freshness_seconds=90.0,
        source_lead_seconds_vs_authority=lead,
        temp_delta_f_vs_authority=delta,
        raw_hash=f"{source}-{station_id}",
        source_url=f"https://example.com/{source}",
        quality_flags=[],
    )


def test_append_and_load_source_benchmark_history_jsonl(tmp_path):
    path = tmp_path / "benchmark_history.jsonl"
    result = SourceBenchmarkResult(
        station_id="KJFK",
        rows=[_row("aviationweather_metar", lead=0.0, delta=0.0), _row("nws_latest_observation")],
        failures={"madis": "not_configured"},
    )

    append_source_benchmark_result(path, result, run_id="run-1")
    loaded = load_source_benchmark_history(path)

    assert len(loaded) == 2
    assert loaded[0]["run_id"] == "run-1"
    assert loaded[0]["station_id"] == "KJFK"
    assert loaded[0]["source"] == "aviationweather_metar"
    assert loaded[0]["failures"] == {"madis": "not_configured"}
    assert loaded[1]["source"] == "nws_latest_observation"
    assert loaded[1]["source_lead_seconds_vs_authority"] == 30.0


def test_summarize_source_benchmark_history_reuses_loaded_rows(tmp_path):
    path = tmp_path / "benchmark_history.jsonl"
    append_source_benchmark_result(
        path,
        SourceBenchmarkResult(
            station_id="KJFK",
            rows=[_row("nws_latest_observation", lead=60.0, delta=0.1)],
            failures={},
        ),
        run_id="run-1",
    )
    append_source_benchmark_result(
        path,
        SourceBenchmarkResult(
            station_id="KORD",
            rows=[_row("nws_latest_observation", station_id="KORD", lead=0.0, delta=-0.3)],
            failures={"open_meteo_current": "TimeoutError: timeout"},
        ),
        run_id="run-2",
    )

    summary = summarize_source_benchmark_history(path)

    assert summary["nws_latest_observation"]["sample_count"] == 2
    assert summary["nws_latest_observation"]["median_lead_seconds_vs_authority"] == 30.0
    assert summary["nws_latest_observation"]["stations"] == ["KJFK", "KORD"]
    assert summary["open_meteo_current"]["sample_count"] == 0
    assert summary["open_meteo_current"]["failure"] == "TimeoutError: timeout"
