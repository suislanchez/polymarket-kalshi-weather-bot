"""Conservative weather observation source-fusion policy.

Only configured lock-authority observations may permit trading locks. Faster
comparator sources can raise watch/conflict context but cannot override the
physical authority without separate settlement evidence.
"""
from dataclasses import dataclass, field
from typing import Optional

from backend.core.weather_source_benchmark import SourceObservation


@dataclass(frozen=True)
class FusedWeatherObservation:
    station_id: Optional[str]
    authority_source: Optional[str]
    authority_temp_f: Optional[float]
    lock_state: str
    trade_allowed: bool
    watch_sources: list[str] = field(default_factory=list)
    rejected_sources: list[str] = field(default_factory=list)
    conflicts: list[str] = field(default_factory=list)
    skip_reason: Optional[str] = None


def _crossed(temp_f: float, threshold_f: float, metric: str) -> bool:
    if metric == "low":
        return temp_f <= threshold_f
    return temp_f >= threshold_f


def _role_for(source: str, policy: dict[str, dict]) -> str:
    return (policy.get(source) or {}).get("role", "insufficient_data")


def _max_age_for(source: str, policy: dict[str, dict]) -> Optional[float]:
    max_age = (policy.get(source) or {}).get("max_age_seconds")
    return float(max_age) if max_age is not None else None


def fuse_weather_observations(
    *,
    observations: list[SourceObservation],
    policy: dict[str, dict],
    threshold_f: float,
    metric: str,
) -> FusedWeatherObservation:
    authority = next((obs for obs in observations if _role_for(obs.source, policy) == "lock_authority"), None)
    watch = [obs for obs in observations if _role_for(obs.source, policy) == "watch_only"]
    rejected = [obs.source for obs in observations if _role_for(obs.source, policy) == "reject"]

    if authority is None:
        return FusedWeatherObservation(
            station_id=observations[0].station_id if observations else None,
            authority_source=None,
            authority_temp_f=None,
            lock_state="unavailable",
            trade_allowed=False,
            watch_sources=[obs.source for obs in watch],
            rejected_sources=rejected,
            skip_reason="lock_authority_observation_missing",
        )

    authority_crossed = _crossed(authority.temp_f, threshold_f, metric)
    authority_max_age = _max_age_for(authority.source, policy)
    authority_stale = authority_max_age is not None and authority.freshness_seconds > authority_max_age
    if authority_stale:
        conflicts = [
            f"watch_source_crossed_but_authority_unavailable:{obs.source}"
            for obs in watch
            if _crossed(obs.temp_f, threshold_f, metric)
        ]
        return FusedWeatherObservation(
            station_id=authority.station_id,
            authority_source=authority.source,
            authority_temp_f=authority.temp_f,
            lock_state="unavailable",
            trade_allowed=False,
            watch_sources=[obs.source for obs in watch],
            rejected_sources=rejected,
            conflicts=conflicts,
            skip_reason="lock_authority_observation_stale",
        )

    lock_state = "locked" if authority_crossed else "below"
    conflicts: list[str] = []
    for obs in watch:
        if _crossed(obs.temp_f, threshold_f, metric) and not authority_crossed:
            conflicts.append(f"watch_source_crossed_but_authority_below:{obs.source}")
        elif authority_crossed and not _crossed(obs.temp_f, threshold_f, metric):
            conflicts.append(f"authority_crossed_but_watch_source_below:{obs.source}")

    return FusedWeatherObservation(
        station_id=authority.station_id,
        authority_source=authority.source,
        authority_temp_f=authority.temp_f,
        lock_state=lock_state,
        trade_allowed=authority_crossed and not conflicts,
        watch_sources=[obs.source for obs in watch],
        rejected_sources=rejected,
        conflicts=conflicts,
        skip_reason=None if authority_crossed else "lock_authority_below_threshold",
    )
