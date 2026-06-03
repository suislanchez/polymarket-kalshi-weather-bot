"""Benchmark observation source freshness against METAR authority.

This module is intentionally pure/offline by default. Provider functions can wrap
network fetches, while ranking and failure accounting stay deterministic and
unit-testable.
"""
from dataclasses import dataclass, field
from datetime import datetime
import hashlib
import json
import statistics
from pathlib import Path
from typing import Callable, Iterable, Optional
from urllib.parse import urlencode

import requests


@dataclass(frozen=True)
class SourceObservation:
    source: str
    station_id: str
    observed_at: datetime
    fetched_at: datetime
    temp_f: float
    source_url: str
    raw_hash: str
    qc: Optional[str] = None

    @property
    def freshness_seconds(self) -> float:
        return max(0.0, (self.fetched_at - self.observed_at).total_seconds())


@dataclass(frozen=True)
class SourceBenchmarkRow:
    source: str
    station_id: str
    authority_source: str
    observed_at: datetime
    fetched_at: datetime
    temp_f: float
    freshness_seconds: float
    source_lead_seconds_vs_authority: Optional[float]
    temp_delta_f_vs_authority: Optional[float]
    raw_hash: str
    source_url: str
    quality_flags: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SourceBenchmarkResult:
    station_id: str
    rows: list[SourceBenchmarkRow]
    failures: dict[str, str]


@dataclass(frozen=True)
class StationBenchmarkTarget:
    station_id: str
    lat: Optional[float] = None
    lon: Optional[float] = None


Provider = Callable[[str, Optional[float], Optional[float]], Optional[SourceObservation]]


def _utcnow() -> datetime:
    from datetime import timezone
    return datetime.now(timezone.utc)


def _parse_utc_datetime(value: object) -> Optional[datetime]:
    from datetime import timezone
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    return None


def _raw_hash(payload: object) -> str:
    raw_json = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw_json.encode("utf-8")).hexdigest()


def _c_to_f(celsius: float) -> float:
    return celsius * 9 / 5 + 32


def fetch_nws_latest_observation(
    station_id: str,
    lat: Optional[float],
    lon: Optional[float],
) -> Optional[SourceObservation]:
    del lat, lon
    station = station_id.upper()
    url = f"https://api.weather.gov/stations/{station}/observations/latest"
    response = requests.get(url, timeout=10, headers={"User-Agent": "WeatherEdge/benchmark"})
    response.raise_for_status()
    payload = response.json()
    props = payload.get("properties", {})
    temp = props.get("temperature", {})
    temp_c = temp.get("value")
    observed_at = _parse_utc_datetime(props.get("timestamp"))
    if temp_c is None or observed_at is None:
        return None
    return SourceObservation(
        source="nws_latest_observation",
        station_id=station,
        observed_at=observed_at,
        fetched_at=_utcnow(),
        temp_f=round(_c_to_f(float(temp_c)), 1),
        source_url=url,
        raw_hash=_raw_hash(payload),
        qc=temp.get("qualityControl"),
    )


def fetch_open_meteo_current(
    station_id: str,
    lat: Optional[float],
    lon: Optional[float],
) -> Optional[SourceObservation]:
    if lat is None or lon is None:
        return None
    params = {
        "latitude": lat,
        "longitude": lon,
        "current": "temperature_2m",
        "timezone": "UTC",
    }
    url = "https://api.open-meteo.com/v1/forecast?" + urlencode(params)
    response = requests.get("https://api.open-meteo.com/v1/forecast", params=params, timeout=10)
    response.raise_for_status()
    payload = response.json()
    current = payload.get("current", {})
    temp_c = current.get("temperature_2m")
    observed_at = _parse_utc_datetime(current.get("time"))
    if temp_c is None or observed_at is None:
        return None
    interval = current.get("interval")
    return SourceObservation(
        source="open_meteo_current",
        station_id=station_id.upper(),
        observed_at=observed_at,
        fetched_at=_utcnow(),
        temp_f=round(_c_to_f(float(temp_c)), 1),
        source_url=url,
        raw_hash=_raw_hash(payload),
        qc=f"interval_{interval}s" if interval is not None else None,
    )


IEM_ASOS_NETWORK_BY_ICAO = {
    "KJFK": "NY_ASOS",
    "KLAX": "CA_ASOS",
    "KORD": "IL_ASOS",
    "KDFW": "TX_ASOS",
    "KIAH": "TX_ASOS",
    "KATL": "GA_ASOS",
    "KMIA": "FL_ASOS",
    "KSEA": "WA_ASOS",
    "KDEN": "CO_ASOS",
    "KBOS": "MA_ASOS",
    "KPHX": "AZ_ASOS",
    "KMSY": "LA_ASOS",
    "KPHL": "PA_ASOS",
    "KAUS": "TX_ASOS",
    "KLAS": "NV_ASOS",
    "KDCA": "DC_ASOS",
    "KSFO": "CA_ASOS",
    "KMSP": "MN_ASOS",
    "KOKC": "OK_ASOS",
    "KSAT": "TX_ASOS",
}


def _iem_station_id(station_id: str) -> str:
    station = station_id.upper()
    return station[1:] if len(station) == 4 and station.startswith("K") else station


def fetch_iem_mesonet_current(
    station_id: str,
    lat: Optional[float],
    lon: Optional[float],
) -> Optional[SourceObservation]:
    """Fetch Iowa State IEM current ASOS/METAR observation as a mesonet comparator."""
    del lat, lon
    station = station_id.upper()
    network = IEM_ASOS_NETWORK_BY_ICAO.get(station)
    if network is None:
        return None
    iem_station = _iem_station_id(station)
    params = {"station": iem_station, "network": network}
    url = "https://mesonet.agron.iastate.edu/json/current.py?" + urlencode(params)
    response = requests.get(
        "https://mesonet.agron.iastate.edu/json/current.py",
        params=params,
        timeout=10,
        headers={"User-Agent": "WeatherEdge/benchmark"},
    )
    response.raise_for_status()
    payload = response.json()
    last_ob = payload.get("last_ob") or {}
    temp_f = last_ob.get("airtemp[F]")
    observed_at = _parse_utc_datetime(last_ob.get("utc_valid"))
    if temp_f is None or observed_at is None:
        return None
    return SourceObservation(
        source="iem_mesonet_current",
        station_id=station,
        observed_at=observed_at,
        fetched_at=_utcnow(),
        temp_f=round(float(temp_f), 1),
        source_url=url,
        raw_hash=_raw_hash(payload),
        qc=f"network_{network}",
    )


def fetch_aviationweather_metar(
    station_id: str,
    lat: Optional[float],
    lon: Optional[float],
) -> Optional[SourceObservation]:
    """Wrap Weather Edge's METAR authority fetcher for benchmark comparison."""
    del lat, lon
    from backend.core.weather_signals import fetch_latest_metar_observation

    observation = fetch_latest_metar_observation(station_id.upper())
    if observation is None:
        return None
    return SourceObservation(
        source=observation.source,
        station_id=observation.station_id,
        observed_at=observation.observed_at,
        fetched_at=observation.fetched_at,
        temp_f=observation.temp_f,
        source_url=observation.source_url,
        raw_hash=observation.raw_hash,
        qc=observation.qc,
    )


def default_benchmark_providers() -> list[Provider]:
    """Free/default providers used by INV-898 benchmark runs."""
    return [
        fetch_aviationweather_metar,
        fetch_nws_latest_observation,
        fetch_iem_mesonet_current,
        fetch_open_meteo_current,
    ]


def _provider_name(provider: Provider) -> str:
    return getattr(provider, "__name__", provider.__class__.__name__)


def rank_source_benchmarks(
    observations: Iterable[SourceObservation],
    *,
    authority_source: str = "aviationweather_metar",
) -> list[SourceBenchmarkRow]:
    observations = list(observations)
    authority = next((obs for obs in observations if obs.source == authority_source), None)

    rows: list[SourceBenchmarkRow] = []
    for obs in observations:
        lead_seconds = None
        temp_delta = None
        flags: list[str] = []
        if authority is not None:
            lead_seconds = (authority.fetched_at - obs.fetched_at).total_seconds()
            temp_delta = round(obs.temp_f - authority.temp_f, 3)
            if abs(temp_delta) > 1.0:
                flags.append("temperature_delta_gt_1f")
            if lead_seconds < 0:
                flags.append("slower_than_authority")

        rows.append(SourceBenchmarkRow(
            source=obs.source,
            station_id=obs.station_id,
            authority_source=authority_source,
            observed_at=obs.observed_at,
            fetched_at=obs.fetched_at,
            temp_f=obs.temp_f,
            freshness_seconds=obs.freshness_seconds,
            source_lead_seconds_vs_authority=lead_seconds,
            temp_delta_f_vs_authority=temp_delta,
            raw_hash=obs.raw_hash,
            source_url=obs.source_url,
            quality_flags=flags,
        ))

    return sorted(
        rows,
        key=lambda row: (
            row.source_lead_seconds_vs_authority is None,
            -(row.source_lead_seconds_vs_authority or 0.0),
            row.freshness_seconds,
            row.source,
        ),
    )


def benchmark_observation_sources(
    *,
    station_id: str,
    lat: Optional[float] = None,
    lon: Optional[float] = None,
    providers: Iterable[Provider],
    authority_source: str = "aviationweather_metar",
) -> SourceBenchmarkResult:
    observations: list[SourceObservation] = []
    failures: dict[str, str] = {}

    for provider in providers:
        name = _provider_name(provider)
        try:
            observation = provider(station_id, lat, lon)
        except Exception as exc:
            failures[name] = f"{type(exc).__name__}: {exc}"
            continue
        if observation is not None:
            observations.append(observation)

    return SourceBenchmarkResult(
        station_id=station_id,
        rows=rank_source_benchmarks(observations, authority_source=authority_source),
        failures=failures,
    )


def summarize_source_benchmark(
    rows: Iterable[SourceBenchmarkRow],
    *,
    failures: Optional[dict[str, str]] = None,
) -> dict[str, dict]:
    """Aggregate benchmark rows into per-source latency/quality statistics."""
    grouped: dict[str, list[SourceBenchmarkRow]] = {}
    for row in rows:
        grouped.setdefault(row.source, []).append(row)

    summary: dict[str, dict] = {}
    for source, source_rows in sorted(grouped.items()):
        leads = [
            row.source_lead_seconds_vs_authority
            for row in source_rows
            if row.source_lead_seconds_vs_authority is not None
        ]
        temp_deltas = [
            abs(row.temp_delta_f_vs_authority)
            for row in source_rows
            if row.temp_delta_f_vs_authority is not None
        ]
        flag_counts: dict[str, int] = {}
        for row in source_rows:
            for flag in row.quality_flags:
                flag_counts[flag] = flag_counts.get(flag, 0) + 1

        summary[source] = {
            "sample_count": len(source_rows),
            "stations": sorted({row.station_id for row in source_rows}),
            "median_lead_seconds_vs_authority": statistics.median(leads) if leads else None,
            "mean_abs_temp_delta_f_vs_authority": (
                round(sum(temp_deltas) / len(temp_deltas), 3) if temp_deltas else None
            ),
            "quality_flag_counts": dict(sorted(flag_counts.items())),
        }

    for source, failure in (failures or {}).items():
        summary.setdefault(source, {
            "sample_count": 0,
            "stations": [],
            "median_lead_seconds_vs_authority": None,
            "mean_abs_temp_delta_f_vs_authority": None,
            "quality_flag_counts": {},
        })["failure"] = failure

    return summary


def _dt_to_iso(value: datetime) -> str:
    return value.isoformat()


def _dt_from_iso(value: str) -> datetime:
    parsed = _parse_utc_datetime(value)
    if parsed is None:
        raise ValueError(f"invalid datetime: {value}")
    return parsed


def _row_to_record(row: SourceBenchmarkRow, *, run_id: str, failures: dict[str, str]) -> dict:
    return {
        "run_id": run_id,
        "station_id": row.station_id,
        "source": row.source,
        "authority_source": row.authority_source,
        "observed_at": _dt_to_iso(row.observed_at),
        "fetched_at": _dt_to_iso(row.fetched_at),
        "temp_f": row.temp_f,
        "freshness_seconds": row.freshness_seconds,
        "source_lead_seconds_vs_authority": row.source_lead_seconds_vs_authority,
        "temp_delta_f_vs_authority": row.temp_delta_f_vs_authority,
        "raw_hash": row.raw_hash,
        "source_url": row.source_url,
        "quality_flags": row.quality_flags,
        "failures": failures,
    }


def _record_to_row(record: dict) -> SourceBenchmarkRow:
    return SourceBenchmarkRow(
        source=record["source"],
        station_id=record["station_id"],
        authority_source=record["authority_source"],
        observed_at=_dt_from_iso(record["observed_at"]),
        fetched_at=_dt_from_iso(record["fetched_at"]),
        temp_f=float(record["temp_f"]),
        freshness_seconds=float(record["freshness_seconds"]),
        source_lead_seconds_vs_authority=record.get("source_lead_seconds_vs_authority"),
        temp_delta_f_vs_authority=record.get("temp_delta_f_vs_authority"),
        raw_hash=record["raw_hash"],
        source_url=record["source_url"],
        quality_flags=list(record.get("quality_flags") or []),
    )


def append_source_benchmark_result(path: str | Path, result: SourceBenchmarkResult, *, run_id: str) -> None:
    """Append one benchmark run to JSONL for later promotion-policy evidence."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        for row in result.rows:
            handle.write(json.dumps(_row_to_record(row, run_id=run_id, failures=result.failures), sort_keys=True) + "\n")


def load_source_benchmark_history(path: str | Path) -> list[dict]:
    path = Path(path)
    if not path.exists():
        return []
    records = []
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def summarize_source_benchmark_history(path: str | Path) -> dict[str, dict]:
    records = load_source_benchmark_history(path)
    rows = [_record_to_row(record) for record in records]
    failures: dict[str, str] = {}
    for record in records:
        failures.update(record.get("failures") or {})
    return summarize_source_benchmark(rows, failures=failures)


def run_station_benchmark_batch(
    targets: Iterable[StationBenchmarkTarget],
    *,
    providers: Iterable[Provider],
    history_path: str | Path,
    run_id: str,
    authority_source: str = "aviationweather_metar",
) -> list[SourceBenchmarkResult]:
    """Run and persist benchmark collection for multiple stations."""
    results: list[SourceBenchmarkResult] = []
    for target in targets:
        result = benchmark_observation_sources(
            station_id=target.station_id.upper(),
            lat=target.lat,
            lon=target.lon,
            providers=providers,
            authority_source=authority_source,
        )
        append_source_benchmark_result(history_path, result, run_id=run_id)
        results.append(result)
    return results


def build_source_promotion_policy(
    summary: dict[str, dict],
    *,
    authority_source: str = "aviationweather_metar",
    minimum_samples: int = 10,
    max_mean_abs_temp_delta_f: float = 1.0,
    min_median_lead_seconds: float = 0.0,
) -> dict[str, dict[str, str]]:
    """Produce a conservative source role policy from benchmark evidence.

    Faster comparators may become watch-only, but only the configured authority
    can lock/trade until separate settlement-backtest evidence exists.
    """
    policy: dict[str, dict[str, str]] = {}
    for source, stats in sorted(summary.items()):
        sample_count = int(stats.get("sample_count") or 0)
        if source == authority_source:
            policy[source] = {
                "role": "lock_authority",
                "reason": "configured_physical_authority",
            }
            continue
        if sample_count < minimum_samples:
            policy[source] = {
                "role": "insufficient_data",
                "reason": f"sample_count_{sample_count}_lt_{minimum_samples}",
            }
            continue

        lead = stats.get("median_lead_seconds_vs_authority")
        temp_delta = stats.get("mean_abs_temp_delta_f_vs_authority")
        flag_counts = stats.get("quality_flag_counts") or {}
        if lead is None or temp_delta is None:
            policy[source] = {
                "role": "insufficient_data",
                "reason": "missing_latency_or_temperature_delta",
            }
        elif lead < min_median_lead_seconds:
            policy[source] = {
                "role": "reject",
                "reason": f"median_lead_seconds_vs_authority_{lead}_lt_{min_median_lead_seconds}",
            }
        elif temp_delta > max_mean_abs_temp_delta_f:
            policy[source] = {
                "role": "reject",
                "reason": f"mean_abs_temp_delta_f_vs_authority_{temp_delta}_gt_{max_mean_abs_temp_delta_f}",
            }
        elif flag_counts.get("temperature_delta_gt_1f", 0) > 0:
            policy[source] = {
                "role": "reject",
                "reason": "temperature_delta_quality_flags_present",
            }
        else:
            policy[source] = {
                "role": "watch_only",
                "reason": "faster_than_authority_but_not_lock_authority_without_settlement_backtest",
            }

    return policy
