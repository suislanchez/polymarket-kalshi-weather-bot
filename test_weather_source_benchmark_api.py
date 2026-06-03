from datetime import datetime, timezone

from fastapi.testclient import TestClient

from backend.api import main as api_main
from backend.api.main import app
from backend.core.weather_source_benchmark import SourceBenchmarkResult, SourceBenchmarkRow


def _row(source, lead=30.0, delta=0.2):
    ts = datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc)
    return SourceBenchmarkRow(
        source=source,
        station_id="KJFK",
        authority_source="aviationweather_metar",
        observed_at=ts,
        fetched_at=ts,
        temp_f=68.0 + delta,
        freshness_seconds=90.0,
        source_lead_seconds_vs_authority=lead,
        temp_delta_f_vs_authority=delta,
        raw_hash=f"{source}-hash",
        source_url=f"https://example.com/{source}",
        quality_flags=[],
    )


def test_weather_source_benchmark_endpoint_returns_summary_and_policy(tmp_path, monkeypatch):
    history_path = tmp_path / "benchmark_history.jsonl"
    monkeypatch.setattr(api_main.settings, "WEATHER_SOURCE_BENCHMARK_HISTORY_PATH", str(history_path), raising=False)

    from backend.core.weather_source_benchmark import append_source_benchmark_result
    append_source_benchmark_result(
        history_path,
        SourceBenchmarkResult(
            station_id="KJFK",
            rows=[
                _row("aviationweather_metar", lead=0.0, delta=0.0),
                _row("nws_latest_observation", lead=45.0, delta=0.3),
            ],
            failures={},
        ),
        run_id="run-1",
    )

    response = TestClient(app).get("/api/weather/source-benchmark")

    assert response.status_code == 200
    body = response.json()
    assert body["history_path"] == str(history_path)
    assert body["summary"]["nws_latest_observation"]["sample_count"] == 1
    assert body["policy"]["aviationweather_metar"]["role"] == "lock_authority"
    assert body["policy"]["nws_latest_observation"]["role"] == "insufficient_data"
