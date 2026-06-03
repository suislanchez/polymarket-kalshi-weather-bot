from datetime import datetime, timezone

from backend.core.weather_source_benchmark import (
    SourceObservation,
    StationBenchmarkTarget,
    load_source_benchmark_history,
    run_station_benchmark_batch,
)


def provider(station_id, lat, lon):
    return SourceObservation(
        source="fake_source",
        station_id=station_id,
        observed_at=datetime(2026, 6, 3, 15, 51, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 52, tzinfo=timezone.utc),
        temp_f=68.0,
        source_url=f"https://example.com/{station_id}?lat={lat}&lon={lon}",
        raw_hash=f"hash-{station_id}",
    )


def failing_provider(station_id, lat, lon):
    raise TimeoutError(f"{station_id} timeout")


def test_station_benchmark_batch_collects_multiple_stations_and_persists_jsonl(tmp_path):
    history_path = tmp_path / "batch.jsonl"
    targets = [
        StationBenchmarkTarget(station_id="KJFK", lat=40.6413, lon=-73.7781),
        StationBenchmarkTarget(station_id="KORD", lat=41.9742, lon=-87.9073),
    ]

    results = run_station_benchmark_batch(
        targets,
        providers=[provider, failing_provider],
        history_path=history_path,
        run_id="batch-1",
    )

    assert [result.station_id for result in results] == ["KJFK", "KORD"]
    assert results[0].failures == {"failing_provider": "TimeoutError: KJFK timeout"}
    records = load_source_benchmark_history(history_path)
    assert [record["station_id"] for record in records] == ["KJFK", "KORD"]
    assert {record["run_id"] for record in records} == {"batch-1"}
    assert records[0]["source"] == "fake_source"
