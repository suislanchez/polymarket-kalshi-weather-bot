from datetime import datetime, timezone

from backend.core.weather_source_benchmark import SourceObservation
from backend.core.weather_source_fusion import fuse_weather_observations


def _obs(source, *, temp_f, fetched_second=0, qc=None, observed_minute=51):
    return SourceObservation(
        source=source,
        station_id="KJFK",
        observed_at=datetime(2026, 6, 3, 15, observed_minute, tzinfo=timezone.utc),
        fetched_at=datetime(2026, 6, 3, 15, 52, fetched_second, tzinfo=timezone.utc),
        temp_f=temp_f,
        source_url=f"https://example.com/{source}",
        raw_hash=f"{source}-{temp_f}",
        qc=qc,
    )


def test_fusion_uses_authority_for_lock_even_when_watch_source_is_faster():
    policy = {
        "aviationweather_metar": {"role": "lock_authority", "reason": "configured_physical_authority"},
        "nws_latest_observation": {"role": "watch_only", "reason": "faster_but_not_authority"},
    }

    fused = fuse_weather_observations(
        observations=[
            _obs("nws_latest_observation", temp_f=86.0, fetched_second=0),
            _obs("aviationweather_metar", temp_f=84.0, fetched_second=30),
        ],
        policy=policy,
        threshold_f=85.0,
        metric="high",
    )

    assert fused.authority_source == "aviationweather_metar"
    assert fused.authority_temp_f == 84.0
    assert fused.lock_state == "below"
    assert fused.trade_allowed is False
    assert fused.watch_sources == ["nws_latest_observation"]
    assert fused.conflicts == ["watch_source_crossed_but_authority_below:nws_latest_observation"]


def test_fusion_locks_when_authority_crosses_and_rejects_bad_sources():
    policy = {
        "aviationweather_metar": {"role": "lock_authority", "reason": "configured_physical_authority"},
        "open_meteo_current": {"role": "reject", "reason": "temperature_delta_quality_flags_present"},
    }

    fused = fuse_weather_observations(
        observations=[
            _obs("open_meteo_current", temp_f=80.0),
            _obs("aviationweather_metar", temp_f=86.0),
        ],
        policy=policy,
        threshold_f=85.0,
        metric="high",
    )

    assert fused.lock_state == "locked"
    assert fused.trade_allowed is True
    assert fused.rejected_sources == ["open_meteo_current"]
    assert fused.conflicts == []


def test_fusion_fails_closed_without_authority_observation():
    policy = {
        "nws_latest_observation": {"role": "watch_only", "reason": "faster_but_not_authority"},
    }

    fused = fuse_weather_observations(
        observations=[_obs("nws_latest_observation", temp_f=86.0)],
        policy=policy,
        threshold_f=85.0,
        metric="high",
    )

    assert fused.authority_source is None
    assert fused.lock_state == "unavailable"
    assert fused.trade_allowed is False
    assert fused.skip_reason == "lock_authority_observation_missing"


def test_fusion_treats_stale_authority_as_unavailable_even_if_watch_source_crossed():
    policy = {
        "aviationweather_metar": {"role": "lock_authority", "max_age_seconds": 300},
        "open_meteo_current": {"role": "watch_only"},
    }

    fused = fuse_weather_observations(
        observations=[
            _obs("aviationweather_metar", temp_f=84.0, fetched_second=0, observed_minute=40),
            _obs("open_meteo_current", temp_f=86.0, fetched_second=0, observed_minute=51),
        ],
        policy=policy,
        threshold_f=85.0,
        metric="high",
    )

    assert fused.authority_source == "aviationweather_metar"
    assert fused.lock_state == "unavailable"
    assert fused.trade_allowed is False
    assert fused.skip_reason == "lock_authority_observation_stale"
    assert fused.conflicts == ["watch_source_crossed_but_authority_unavailable:open_meteo_current"]
