from pathlib import Path

ROOT = Path(__file__).parent


def test_frontend_weather_signal_type_includes_latency_fields():
    types = (ROOT / "frontend/src/types.ts").read_text()

    for field in [
        "signal_source?: string",
        "metar_note?: string",
        "observation_source?: string",
        "station_id?: string",
        "observed_at?: string",
        "fetched_at?: string",
        "signal_at?: string",
        "observation_latency_seconds?: number",
        "signal_latency_seconds?: number",
        "threshold_state?: string",
        "fusion_lock_state?: string",
        "fusion_trade_allowed?: boolean",
        "fusion_authority_source?: string",
        "fusion_watch_sources?: string[]",
        "fusion_rejected_sources?: string[]",
        "fusion_conflicts?: string[]",
        "fusion_skip_reason?: string",
        "raw_hash?: string",
        "source_url?: string",
    ]:
        assert field in types


def test_frontend_weather_panel_renders_latency_and_source_fields():
    panel = (ROOT / "frontend/src/components/WeatherPanel.tsx").read_text()

    assert "observation_latency_seconds" in panel
    assert "station_id" in panel
    assert "signal_source" in panel
    assert "fusion_conflicts" in panel
    assert "fusion_lock_state" in panel
    assert "METAR" in panel
