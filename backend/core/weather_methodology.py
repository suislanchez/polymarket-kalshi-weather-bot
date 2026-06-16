"""Weather market settlement parsing and paper-trade safety gates.

All helpers are read-only/simulation-oriented.  The gates are intentionally
conservative: if settlement source or executable book depth is unknown, the
signal may still be displayed for research but should not be paper-executed.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
import json
import re
from typing import Iterable, Iterator
from urllib.parse import quote, urlencode, urlsplit, urlunsplit


@dataclass(frozen=True)
class SettlementMetadata:
    """Best-effort normalized settlement/source details from public rule text."""

    source: str | None = None
    station_code: str | None = None
    station_name: str | None = None
    product_code: str | None = None
    source_url: str | None = None
    units: str | None = None
    precision: str | None = None
    raw_text: str = ""

    @property
    def has_exact_source(self) -> bool:
        return bool(self.source and (self.station_code or self.product_code))


@dataclass(frozen=True)
class WeatherGateInput:
    """Inputs required before a weather signal can be considered executable."""

    settlement_source: str | None
    station_code: str | None
    market_probability: float
    best_bid: float | None
    best_ask: float | None
    top_ask_size: float | None
    ensemble_mean: float | None
    threshold_f: float | None
    target_date: date | None = None
    max_spread: float = 0.08
    min_top_ask_size: float = 10.0
    min_threshold_buffer_f: float = 3.0


@dataclass(frozen=True)
class WeatherGateResult:
    allowed: bool
    reasons: list[str] = field(default_factory=list)
    execution_spread: float | None = None
    top_ask_size: float | None = None


@dataclass(frozen=True)
class WeatherBucketLine:
    """A single mutually-exclusive weather bucket candidate."""

    market_id: str
    bucket_low_f: float | None
    bucket_high_f: float | None
    model_probability: float | None


@dataclass(frozen=True)
class WeatherBucketSetDiagnostic:
    """Diagnostic for a same-city/date mutually-exclusive bucket set.

    This is deliberately an actionability blocker, not a trading permission. A
    bucket line can only become paper-actionable after its entire set is
    present, has parseable non-overlapping ranges, and the model probability
    mass sums close to one. Even then, normal source/depth/spread gates still
    apply elsewhere.
    """

    line_count: int
    valid_range_count: int
    probability_mass: float | None
    has_overlapping_ranges: bool
    has_probability_mass_sanity: bool
    passed: bool
    reasons: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class NwsCliClimateReport:
    """Parsed NWS Daily Climate Report for a target local date.

    Same-day CLI products can include ``VALID TODAY AS OF`` or shorter
    ``VALID AS OF`` preliminary text; those are useful source-state snapshots
    but must not be scored as final outcomes. A parsed row is final only when
    the report date matches the target date and the product text does not carry
    a preliminary marker.
    """

    report_date: date | None
    maximum_f: int | None
    product_code: str | None = None
    station_name: str | None = None
    is_final: bool = False
    preliminary_reason: str | None = None
    issuance_time: str | None = None
    product_id: str | None = None


@dataclass(frozen=True)
class HkoDailyExtractObservation:
    """Target-day value parsed from HKO Daily Extract JSON.

    HKO publishes the daily table as JSON behind `dailyExtract_YYYYMM.xml`.
    This is direct source-state evidence for a target date, but it is still
    treated as review/calibration metadata until platform settlement, anomaly,
    model, liquidity, fee, and sizing gates are separately satisfied.
    """

    target_date: date
    metric: str
    status: str
    value_c: float | None = None
    observed_at: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class WundergroundCurrentObservation:
    """Best-effort Wunderground current-app-state observation.

    Weather Underground history pages are JavaScript apps.  The SSR payload can
    include Weather.com current-observation fields for the exact ICAO station,
    but those fields are not a final daily-history table.  Treat parsed values as
    source-state QA only (current/24h context) until final-source validation,
    station-neighbor checks, model calibration, depth/spread, fees, and sizing
    gates pass.
    """

    target_date: date
    metric: str
    status: str
    value_f: float | None = None
    observed_unit: str | None = None
    observed_at: str | None = None
    source_field: str | None = None
    reason: str | None = None


@dataclass(frozen=True)
class WundergroundHistoryObservation:
    """Target-day high/low parsed from Weather.com/Wunderground history JSON.

    Wunderground daily pages use a public Weather.com historical-observations
    endpoint behind the app.  A parsed target-day value is direct source-state
    evidence for the exact station/date, but remains non-actionable until final
    source coverage, anomaly checks, independent model probability,
    line-level liquidity/spread/fees, sizing gates, and platform settlement are
    all separately validated.
    """

    target_date: date
    metric: str
    status: str
    value_f: float | None = None
    observed_unit: str | None = None
    observed_at: str | None = None
    source_field: str | None = None
    observation_count: int = 0
    reason: str | None = None


@dataclass(frozen=True)
class StationAnomalyDiagnostic:
    """Neighbor-station sanity check for single-station weather captures.

    This diagnostic is intentionally a blocker/QA label, not an actionability
    upgrade. A source observation without nearby-station context remains
    review-only because a single station can be stale, anomalous, or wrong for
    settlement.
    """

    status: str
    neighbor_count: int = 0
    max_delta: float | None = None
    threshold: float = 5.0
    reason: str | None = None


_MONTHS = {
    "JAN": 1,
    "JANUARY": 1,
    "FEB": 2,
    "FEBRUARY": 2,
    "MAR": 3,
    "MARCH": 3,
    "APR": 4,
    "APRIL": 4,
    "MAY": 5,
    "JUN": 6,
    "JUNE": 6,
    "JUL": 7,
    "JULY": 7,
    "AUG": 8,
    "AUGUST": 8,
    "SEP": 9,
    "SEPT": 9,
    "SEPTEMBER": 9,
    "OCT": 10,
    "OCTOBER": 10,
    "NOV": 11,
    "NOVEMBER": 11,
    "DEC": 12,
    "DECEMBER": 12,
}


_SUMMARY_DATE_RE = re.compile(
    r"\.\.\.\s*THE\s+(.+?)\s+CLIMATE\s+SUMMARY\s+FOR\s+"
    r"([A-Z]+)\s+(\d{1,2})\s+(\d{4})\.\.\.",
    re.IGNORECASE,
)
_MAXIMUM_LINE_RE = re.compile(r"^\s*MAXIMUM\s+(-?\d{1,3})\b", re.IGNORECASE | re.MULTILINE)
_WEATHER_RULE_DMY_RE = re.compile(
    r"\bon\s+(\d{1,2})\s+([A-Z][A-Za-z]+)\s+'?(\d{2}|\d{4})\b",
    re.IGNORECASE,
)
_WEATHER_RULE_MDY_RE = re.compile(
    r"\bon\s+([A-Z][A-Za-z]+)\s+(\d{1,2})(?:\s*,?\s*(\d{4}))?\b",
    re.IGNORECASE,
)


def _normalize_weather_year(year_text: str | None, reference_date: date | None) -> int:
    if year_text:
        year = int(year_text)
        return 2000 + year if year < 100 else year
    return (reference_date or date.today()).year


def parse_weather_rule_target_date(text: str | None, *, reference_date: date | None = None) -> date | None:
    """Parse a public weather market target date from title/rule text.

    Polymarket weather rules commonly say ``on 4 Jun '26`` while older public
    search results can still surface stale ``on 6 Jun '25`` slates.  Cron
    snapshotters use this helper to avoid mixing prior-year rows into the active
    weather source-state batch.  If the text only has a month/day title, the
    supplied reference year is used.
    """
    raw = re.sub(r"\s+", " ", text or "").strip()
    if not raw:
        return None

    for match in _WEATHER_RULE_DMY_RE.finditer(raw):
        day = int(match.group(1))
        month = _MONTHS.get(match.group(2).upper())
        if not month:
            continue
        try:
            return date(_normalize_weather_year(match.group(3), reference_date), month, day)
        except ValueError:
            continue

    for match in _WEATHER_RULE_MDY_RE.finditer(raw):
        month = _MONTHS.get(match.group(1).upper())
        if not month:
            continue
        day = int(match.group(2))
        try:
            return date(_normalize_weather_year(match.group(3), reference_date), month, day)
        except ValueError:
            continue
    return None


def build_hko_daily_extract_url(
    target_date: date,
    *,
    base_url: str = "https://www.weather.gov.hk",
) -> str:
    """Return the public HKO Daily Extract JSON endpoint for a target month.

    The visible HKO climatology page links to ``dailyExtract.htm`` but renders
    the table from ``/cis/dailyExtract/dailyExtract_YYYYMM.xml``.  Snapshotters
    should archive that direct JSON endpoint when recording final/source-state
    evidence, while keeping any parsed value non-actionable until downstream
    anomaly/model/liquidity gates pass.
    """
    root = base_url.rstrip("/")
    return f"{root}/cis/dailyExtract/dailyExtract_{target_date:%Y%m}.xml"


def infer_hko_temperature_metric(text: str | None) -> str:
    """Infer whether HKO source-state capture should read the high or low row.

    Most Polymarket HKO questions say either "highest temperature" or "lowest
    temperature".  Do not treat threshold words such as "below" as a low-temp
    market; they often appear in high-temperature bucket questions.
    """
    raw = (text or "high").strip().lower()
    if raw in {"low", "lowest", "min", "minimum"}:
        return "low"
    if re.search(r"\b(lowest[-_\s]+temperature|minimum[-_\s]+temperature|daily[-_\s]+min(?:imum)?|min[-_\s]+temp)\b", raw):
        return "low"
    return "high"


def _normalize_hko_metric(metric: str | None) -> str:
    return infer_hko_temperature_metric(metric)


def parse_hko_daily_extract_observation(
    payload: str | bytes | None,
    target_date: date,
    *,
    metric: str | None = "high",
) -> HkoDailyExtractObservation:
    """Parse HKO Daily Extract JSON for a target-day high/low temperature.

    The HKO climatology page loads `dailyExtract_YYYYMM.xml`, which is JSON
    despite the extension.  Columns in `dayData` are rendered by HKO as:
    day, mean pressure, absolute daily max temp, mean temp, absolute daily min
    temp, dew point, humidity, cloud, rainfall.  This parser reads only the
    target-date row and returns an explicit missing-target status when the HKO
    extract has not yet published that date.
    """
    normalized_metric = _normalize_hko_metric(metric)
    if not payload:
        return HkoDailyExtractObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="hko_daily_extract_empty_payload",
            reason="empty HKO daily extract payload",
        )
    text = payload.decode("utf-8-sig", "replace") if isinstance(payload, bytes) else str(payload).lstrip("\ufeff")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return HkoDailyExtractObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="hko_daily_extract_parse_error",
            reason=str(exc),
        )

    value_index = 4 if normalized_metric == "low" else 2
    month_blocks = ((data.get("stn") or {}).get("data") or []) if isinstance(data, dict) else []
    target_day = f"{target_date.day:02d}"
    for block in month_blocks:
        if not isinstance(block, dict):
            continue
        month_value = block.get("month")
        if month_value is None:
            continue
        try:
            block_month = int(month_value)
        except (TypeError, ValueError):
            continue
        if block_month != target_date.month:
            continue
        for row in block.get("dayData") or []:
            if not isinstance(row, list) or not row:
                continue
            if str(row[0]).strip() != target_day:
                continue
            if len(row) <= value_index:
                return HkoDailyExtractObservation(
                    target_date=target_date,
                    metric=normalized_metric,
                    status="hko_daily_extract_missing_metric_value",
                    reason=f"target row lacks {normalized_metric} temperature column",
                )
            value = _coerce_station_anomaly_float(str(row[value_index]).strip())
            if value is None:
                return HkoDailyExtractObservation(
                    target_date=target_date,
                    metric=normalized_metric,
                    status="hko_daily_extract_unparseable_value",
                    reason=f"unparseable HKO {normalized_metric} temperature value: {row[value_index]!r}",
                )
            return HkoDailyExtractObservation(
                target_date=target_date,
                metric=normalized_metric,
                status="hko_daily_extract_observed",
                value_c=value,
                observed_at=target_date.isoformat(),
            )

    return HkoDailyExtractObservation(
        target_date=target_date,
        metric=normalized_metric,
        status="hko_daily_extract_missing_target_date",
        reason="target date not present in HKO daily extract",
    )


def _extract_app_root_state_json(payload: str | bytes | None) -> dict[str, object] | None:
    if not payload:
        return None
    text = payload.decode("utf-8", "replace") if isinstance(payload, bytes) else str(payload)
    match = re.search(
        r'<script[^>]+id=["\']app-root-state["\'][^>]*>(.*?)</script>',
        text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    if not match:
        return None
    try:
        data = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def _iter_wunderground_current_observation_candidates(
    data: object,
    *,
    station_code: str | None,
) -> Iterator[tuple[str, dict[str, object]]]:
    station = (station_code or "").strip().upper()

    def maybe_candidate(obj: object) -> tuple[str, dict[str, object]] | None:
        if not isinstance(obj, dict):
            return None
        url = str(obj.get("u") or obj.get("url") or "")
        body = obj.get("b") if "b" in obj else obj.get("value")
        if not isinstance(body, dict):
            return None
        if "temperatureMax24Hour" not in body and "temperatureMin24Hour" not in body:
            return None
        if station and f"icaocode={station.lower()}" not in url.lower():
            return None
        return url, body

    if isinstance(data, dict):
        for value in data.values():
            candidate = maybe_candidate(value)
            if candidate:
                yield candidate
        wu_state = data.get("wu-next-state-key")
        if isinstance(wu_state, dict):
            for value in wu_state.values():
                candidate = maybe_candidate(value)
                if candidate:
                    yield candidate


def build_wunderground_neighbor_source_urls(
    source_url: str | None,
    station_codes: Iterable[str] | None,
    *,
    max_neighbors: int = 2,
) -> list[tuple[str, str]]:
    """Build same-page-pattern Wunderground URLs for nearby station checks.

    Polymarket weather rules usually provide one Wunderground daily-history URL
    whose final path segment is the ICAO station.  The source-state snapshotter
    can fetch a small, explicit allowlist of neighboring ICAO stations by
    replacing only that final segment, then parse the same Weather.com current
    app-state fields for anomaly QA.  Query strings/fragments are intentionally
    dropped so persisted source snapshots do not retain page-session/API-key
    parameters.  Returned URLs are source-state inputs only; neighbor presence
    never upgrades paper actionability by itself.
    """
    if not source_url or "wunderground.com/history/daily" not in source_url.lower():
        return []
    parts = urlsplit(str(source_url))
    if not parts.scheme or not parts.netloc:
        return []
    path_parts = [part for part in parts.path.split("/") if part]
    if len(path_parts) < 3:
        return []
    source_station = re.sub(r"[^A-Za-z0-9]", "", path_parts[-1]).upper()
    if not source_station:
        return []

    max_count = max(int(max_neighbors), 0)
    seen = {source_station}
    urls: list[tuple[str, str]] = []
    for raw_code in station_codes or []:
        station = re.sub(r"[^A-Za-z0-9]", "", str(raw_code or "")).upper()
        if not station or station in seen:
            continue
        seen.add(station)
        neighbor_path = "/" + "/".join([*path_parts[:-1], station])
        urls.append((station, urlunsplit((parts.scheme, parts.netloc, neighbor_path, "", ""))))
        if max_count and len(urls) >= max_count:
            break
    return urls


def build_wunderground_history_api_url(
    source_url: str | None,
    *,
    station_code: str | None,
    target_date: date,
    api_key: str | None = None,
    units: str = "e",
    base_url: str = "https://api.weather.com",
) -> str | None:
    """Build Weather.com historical-observations URL for a Wunderground station.

    Wunderground daily-history pages expose exact airport/PWS station identity in
    their path (for example ``/history/daily/cn/shanghai/ZSPD``). The public app
    fetches Weather.com history JSON at ``/v1/location/<ICAO>:9:<COUNTRY>/...``.
    This helper derives that endpoint without retaining query/fragments from the
    page URL. Returned URLs are public read-only source-state inputs only; callers
    must redact the public-page API key before persisting snapshots or summaries.
    """
    if not source_url or "wunderground.com/history/daily" not in source_url.lower():
        return None
    parts = urlsplit(str(source_url))
    path_parts = [part for part in parts.path.split("/") if part]
    try:
        daily_index = path_parts.index("daily")
    except ValueError:
        return None
    if len(path_parts) <= daily_index + 2:
        return None
    country_code = re.sub(r"[^A-Za-z]", "", path_parts[daily_index + 1]).upper()
    station = re.sub(r"[^A-Za-z0-9]", "", str(station_code or path_parts[-1])).upper()
    if not country_code or not station:
        return None

    location_id = f"{station}:9:{country_code}"
    query_items: list[tuple[str, str]] = [
        ("units", units),
        ("startDate", target_date.strftime("%Y%m%d")),
        ("endDate", target_date.strftime("%Y%m%d")),
    ]
    if api_key:
        query_items.append(("apiKey", str(api_key)))
    query = urlencode(query_items)
    return (
        f"{base_url.rstrip('/')}/v1/location/"
        f"{quote(location_id, safe=':')}/observations/historical.json?{query}"
    )


def parse_wunderground_history_observation(
    payload: str | bytes | None,
    target_date: date,
    *,
    station_code: str | None = None,
    metric: str | None = "high",
    complete_observation_threshold: int = 24,
) -> WundergroundHistoryObservation:
    """Parse Weather.com historical observations for target-day high/low.

    The JSON endpoint returns a station/day observation series.  We compute the
    daily high/low from observed ``temp`` values and label sparse series as
    ``partial`` so incomplete same-day captures remain review blockers.  This is
    direct source-state evidence only and never upgrades paper actionability.
    """
    normalized_metric = infer_hko_temperature_metric(metric)
    station = re.sub(r"[^A-Za-z0-9]", "", str(station_code or "")).upper()
    if not payload:
        return WundergroundHistoryObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_history_empty_payload",
            reason="empty Wunderground history payload",
        )
    text = payload.decode("utf-8-sig", "replace") if isinstance(payload, bytes) else str(payload).lstrip("\ufeff")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        return WundergroundHistoryObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_history_parse_error",
            reason=str(exc),
        )
    if not isinstance(data, dict):
        return WundergroundHistoryObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_history_parse_error",
            reason="Wunderground history payload is not a JSON object",
        )

    metadata = data.get("metadata") if isinstance(data.get("metadata"), dict) else {}
    location_id = str(metadata.get("location_id") or metadata.get("locationId") or "").upper()
    if station and location_id and not location_id.startswith(f"{station}:"):
        return WundergroundHistoryObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_history_station_mismatch",
            reason=f"history location {location_id} does not match station {station}",
        )

    raw_observations = data.get("observations")
    if not isinstance(raw_observations, list) or not raw_observations:
        return WundergroundHistoryObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_history_no_observations",
            reason="Wunderground history payload contained no observations",
        )

    station_matched = [
        obs
        for obs in raw_observations
        if isinstance(obs, dict)
        and station
        and str(obs.get("obs_id") or obs.get("key") or "").upper() == station
    ]
    observations = station_matched or [obs for obs in raw_observations if isinstance(obs, dict)]
    values = []
    for obs in observations:
        value = _coerce_station_anomaly_float(obs.get("temp"))
        if value is None:
            imperial = obs.get("imperial") if isinstance(obs.get("imperial"), dict) else {}
            value = _coerce_station_anomaly_float(imperial.get("temp"))
        if value is not None:
            values.append(value)
    if not values:
        return WundergroundHistoryObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_history_missing_temperature_values",
            observation_count=len(observations),
            reason="history observations lacked parseable temperature values",
        )

    observed_value = max(values) if normalized_metric == "high" else min(values)
    is_complete = len(values) >= max(int(complete_observation_threshold), 1)
    completeness = "" if is_complete else "partial_"
    reason = (
        f"historical observation series had {len(values)} temperature rows; source-state only"
        if is_complete
        else f"partial historical observation series had {len(values)} temperature rows; not final settlement evidence"
    )
    return WundergroundHistoryObservation(
        target_date=target_date,
        metric=normalized_metric,
        status=f"wunderground_history_{completeness}{normalized_metric}_observed",
        value_f=observed_value,
        observed_unit="fahrenheit",
        observed_at=target_date.isoformat(),
        source_field="temp",
        observation_count=len(values),
        reason=reason,
    )


def parse_wunderground_current_observation(
    payload: str | bytes | None,
    target_date: date,
    *,
    station_code: str | None = None,
    metric: str | None = "high",
) -> WundergroundCurrentObservation:
    """Parse Wunderground/Weather.com current 24h high/low from SSR app state.

    This intentionally does **not** claim final settlement.  It only extracts the
    current observation block for the requested ICAO station when the page's
    Weather.com app state exposes `temperatureMax24Hour` / `temperatureMin24Hour`.
    The returned status makes the provisional/current nature explicit.
    """
    normalized_metric = infer_hko_temperature_metric(metric)
    value_field = "temperatureMin24Hour" if normalized_metric == "low" else "temperatureMax24Hour"
    if not station_code:
        return WundergroundCurrentObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_current_missing_station_code",
            reason="missing station code for Wunderground current-observation parse",
        )
    data = _extract_app_root_state_json(payload)
    if data is None:
        return WundergroundCurrentObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_current_app_state_missing",
            reason="missing or unparseable Wunderground app-root-state JSON",
        )

    candidate = next(
        _iter_wunderground_current_observation_candidates(data, station_code=station_code),
        None,
    )
    if candidate is None:
        return WundergroundCurrentObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_current_station_observation_missing",
            reason=f"no current Weather.com observation block for station {station_code}",
        )
    _, observation = candidate
    observed_at = str(observation.get("validTimeLocal") or observation.get("obsTimeLocal") or "").strip() or None
    observed_date: date | None = None
    if observed_at and len(observed_at) >= 10:
        try:
            observed_date = date.fromisoformat(observed_at[:10])
        except ValueError:
            observed_date = None
    if observed_date != target_date:
        return WundergroundCurrentObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_current_date_mismatch",
            observed_at=observed_at,
            source_field=value_field,
            reason=f"current observation date {observed_date.isoformat() if observed_date else 'unknown'} does not match target date {target_date.isoformat()}",
        )
    value = _coerce_station_anomaly_float(observation.get(value_field))
    if value is None:
        return WundergroundCurrentObservation(
            target_date=target_date,
            metric=normalized_metric,
            status="wunderground_current_missing_metric_value",
            observed_at=observed_at,
            source_field=value_field,
            reason=f"current observation lacks parseable {value_field}",
        )
    return WundergroundCurrentObservation(
        target_date=target_date,
        metric=normalized_metric,
        status=f"wunderground_current_24h_{normalized_metric}_observed",
        value_f=value,
        observed_unit="fahrenheit",
        observed_at=observed_at,
        source_field=value_field,
        reason="current Weather.com 24h station observation; not final daily-history settlement evidence",
    )


def _coerce_station_anomaly_float(value: object) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def evaluate_station_anomaly_diagnostic(
    observed_value: object,
    neighbor_values: Iterable[object] | None = None,
    *,
    max_delta: float = 5.0,
) -> StationAnomalyDiagnostic:
    """Evaluate whether a captured source value needs neighbor-station review.

    The helper is pure and side-effect-free so snapshot runners/API loaders can
    share one conservative diagnostic. Missing observations or missing neighbor
    context are explicit QA blockers. A large delta is a stronger warning, but
    still only keeps the row in review/calibration state.
    """
    observed = _coerce_station_anomaly_float(observed_value)
    neighbors = [
        value
        for value in (_coerce_station_anomaly_float(item) for item in (neighbor_values or []))
        if value is not None
    ]

    if observed is None:
        return StationAnomalyDiagnostic(
            status="not_checked_missing_observation",
            neighbor_count=len(neighbors),
            threshold=max_delta,
            reason="missing source observation for station anomaly check",
        )
    if not neighbors:
        return StationAnomalyDiagnostic(
            status="not_checked_missing_neighbors",
            neighbor_count=0,
            threshold=max_delta,
            reason="missing neighboring-station observations",
        )

    largest_delta = max(abs(observed - neighbor) for neighbor in neighbors)
    rounded_delta = round(largest_delta, 2)
    if largest_delta > max_delta:
        return StationAnomalyDiagnostic(
            status="warning",
            neighbor_count=len(neighbors),
            max_delta=rounded_delta,
            threshold=max_delta,
            reason=f"largest neighboring-station delta {rounded_delta:g} exceeds {float(max_delta):.1f}",
        )
    return StationAnomalyDiagnostic(
        status="pass",
        neighbor_count=len(neighbors),
        max_delta=rounded_delta,
        threshold=max_delta,
        reason="neighboring-station observations within threshold",
    )


def parse_nws_cli_climate_report(
    text: str | None,
    *,
    product_id: str | None = None,
    issuance_time: str | None = None,
) -> NwsCliClimateReport:
    """Parse an NWS CLI product without confusing preliminary/final reports.

    The report date is read only from the ``...CLIMATE SUMMARY FOR <date>...``
    header.  This intentionally avoids substring matching elsewhere in the
    product body, where sunrise/sunset lines can mention adjacent dates and
    cause target-date scoring errors.
    """
    raw = text or ""
    product_match = _NWS_PRODUCT_RE.search(raw)
    product_code = product_match.group(1).upper() if product_match else None

    station_name: str | None = None
    report_date: date | None = None
    summary_match = _SUMMARY_DATE_RE.search(raw)
    if summary_match:
        station_name = re.sub(r"\s+", " ", summary_match.group(1)).strip(" .")
        month = _MONTHS.get(summary_match.group(2).upper())
        if month:
            report_date = date(int(summary_match.group(4)), month, int(summary_match.group(3)))

    maximum_match = _MAXIMUM_LINE_RE.search(raw)
    maximum_f = int(maximum_match.group(1)) if maximum_match else None

    preliminary_reason = None
    raw_upper = raw.upper()
    if "VALID TODAY AS OF" in raw_upper:
        preliminary_reason = "preliminary valid-today product"
    elif re.search(r"\bVALID\s+AS\s+OF\s+\d{3,4}\s+[AP]M\s+LOCAL\s+TIME", raw_upper):
        preliminary_reason = "preliminary valid-as-of product"
    elif report_date is None:
        preliminary_reason = "missing climate-summary report date"
    elif maximum_f is None:
        preliminary_reason = "missing maximum temperature line"

    return NwsCliClimateReport(
        report_date=report_date,
        maximum_f=maximum_f,
        product_code=product_code,
        station_name=station_name,
        is_final=preliminary_reason is None,
        preliminary_reason=preliminary_reason,
        issuance_time=issuance_time,
        product_id=product_id,
    )


def select_final_nws_cli_report(
    reports: Iterable[NwsCliClimateReport],
    target_date: date,
    *,
    expected_product_code: str | None = None,
    expected_station_name: str | None = None,
) -> NwsCliClimateReport | None:
    """Select the latest final CLI report matching date and expected station.

    Final selection requires the parsed header date to equal the requested
    local date and excludes preliminary ``VALID TODAY`` / ``VALID AS OF``
    products.  When expected station/product metadata is supplied, wrong-location
    are rejected instead of being accidentally scored as the market outcome.
    If multiple final products match, the latest issuance timestamp wins.
    """
    expected_product = expected_product_code.upper() if expected_product_code else None
    expected_station = re.sub(r"\s+", " ", expected_station_name or "").strip().lower()

    candidates = []
    for report in reports:
        if not (report.is_final and report.report_date == target_date and report.maximum_f is not None):
            continue
        if expected_product and (report.product_code or "").upper() != expected_product:
            continue
        if expected_station:
            report_station = re.sub(r"\s+", " ", report.station_name or "").strip().lower()
            if report_station != expected_station:
                continue
        candidates.append(report)
    if not candidates:
        return None

    def sort_key(report: NwsCliClimateReport) -> datetime:
        if not report.issuance_time:
            return datetime.min
        try:
            return datetime.fromisoformat(report.issuance_time.replace("Z", "+00:00"))
        except ValueError:
            return datetime.min

    return sorted(candidates, key=sort_key)[-1]


def estimate_bucket_probability(
    values: list[float],
    bucket_low_f: float | None,
    bucket_high_f: float | None,
) -> float:
    """Estimate inclusive bucket probability from ensemble member values.

    Kalshi bucket titles like ``77° to 78°`` resolve as a mutually-exclusive
    range.  This helper intentionally only estimates the line's range
    probability; callers should still block paper actionability until they have
    validated the full bucket set and exactly-one-winner semantics.
    """
    if not values or bucket_low_f is None or bucket_high_f is None:
        return 0.5
    low = min(bucket_low_f, bucket_high_f)
    high = max(bucket_low_f, bucket_high_f)
    count = sum(1 for value in values if low <= value <= high)
    return count / len(values)


def evaluate_bucket_set_sanity(
    lines: Iterable[WeatherBucketLine],
    *,
    min_lines: int = 3,
    min_probability_mass: float = 0.98,
    max_probability_mass: float = 1.02,
) -> WeatherBucketSetDiagnostic:
    """Check whether a bucket group is complete enough for paper review.

    Kalshi bucket/range contracts are mutually exclusive at the city/date set
    level. A single line probability can look attractive while the group is
    incomplete or internally inconsistent, so this function requires parseable
    ranges, no overlaps, and ensemble probability mass near one before the set
    passes the diagnostic. Passing this diagnostic does **not** make a line
    tradable; it only removes one methodology blocker.
    """
    rows = list(lines)
    reasons: list[str] = []
    valid_ranges: list[tuple[float, float]] = []
    probability_mass = 0.0
    probability_values = []

    for row in rows:
        if row.bucket_low_f is None or row.bucket_high_f is None:
            reasons.append(f"bucket {row.market_id} missing parsed range")
            continue
        low = min(row.bucket_low_f, row.bucket_high_f)
        high = max(row.bucket_low_f, row.bucket_high_f)
        valid_ranges.append((low, high))
        if row.model_probability is None:
            reasons.append(f"bucket {row.market_id} missing model probability")
        else:
            probability_values.append(float(row.model_probability))
            probability_mass += float(row.model_probability)

    if len(rows) < min_lines:
        reasons.append(f"bucket set has only {len(rows)} lines (<{min_lines} minimum)")

    has_overlaps = False
    for (_, prev_high), (next_low, _) in zip(sorted(valid_ranges), sorted(valid_ranges)[1:]):
        if next_low <= prev_high:
            has_overlaps = True
            reasons.append("bucket set has overlapping ranges")
            break

    mass_value = probability_mass if probability_values else None
    has_mass_sanity = bool(
        mass_value is not None and min_probability_mass <= mass_value <= max_probability_mass
    )
    if mass_value is None:
        reasons.append("bucket set has no model probability mass")
    elif not has_mass_sanity:
        reasons.append(
            f"bucket set probability mass {mass_value:.1%} outside "
            f"{min_probability_mass:.0%}-{max_probability_mass:.0%} sanity band"
        )

    passed = not reasons
    return WeatherBucketSetDiagnostic(
        line_count=len(rows),
        valid_range_count=len(valid_ranges),
        probability_mass=mass_value,
        has_overlapping_ranges=has_overlaps,
        has_probability_mass_sanity=has_mass_sanity,
        passed=passed,
        reasons=reasons,
    )


_STATION_PAREN_RE = re.compile(r"\(([A-Z0-9]{3,5})\)")
_NWS_PRODUCT_RE = re.compile(r"\b(CLI[A-Z0-9]{3})\b", re.IGNORECASE)
_ICAO_RE = re.compile(r"\bK[A-Z]{3}\b")
_SOURCE_URL_RE = re.compile(r"https?://[^\s)]+", re.IGNORECASE)
_WUNDERGROUND_STATION_URL_RE = re.compile(r"wunderground\.com/history/daily/[^\s)]+/([A-Z0-9]{3,5})\b", re.IGNORECASE)


def _station_name_before_code(text: str, code: str) -> str | None:
    """Return a readable station name immediately preceding a station code."""
    pattern = re.compile(rf"([A-Z][A-Za-z .'-]{{2,80}}?)\s*(?:Station\s*)?\({re.escape(code)}\)")
    match = pattern.search(text)
    if not match:
        # NWS formats often use "for Chicago Midway (CLIMDW / KMDW)".
        pattern = re.compile(rf"(?:for|at)\s+([A-Z][A-Za-z .'-]{{2,80}}?)\s*\([^)]*{re.escape(code)}[^)]*\)", re.IGNORECASE)
        match = pattern.search(text)
    if not match:
        return None
    name = re.sub(r"\s+", " ", match.group(1)).strip(" -/,")
    # Trim leading prose so "... page for London City Airport (EGLC)" becomes
    # the station-like tail rather than the whole sentence fragment.
    name = re.split(r"\b(?:for|at|source is)\b", name, flags=re.IGNORECASE)[-1].strip(" -/,")
    name = re.sub(r"\bStation$", "", name).strip()
    return name or None


def _station_name_from_forecast_phrase(text: str) -> str | None:
    """Extract station names from Wunderground prose without parenthesized code."""
    patterns = [
        r"Forecast\s+for\s+the\s+(.+?)\s+Station\b",
        r"recorded\s+at\s+the\s+(.+?)\s+Station\b",
    ]
    for pattern in patterns:
        match = re.search(pattern, text, flags=re.IGNORECASE)
        if match:
            name = re.sub(r"\s+", " ", match.group(1)).strip(" -/,")
            return name or None
    return None


def parse_settlement_metadata(text: str | None) -> SettlementMetadata:
    """Parse public market rule text into source/station metadata.

    Supports common weather market wording for Polymarket Wunderground airport
    pages and Kalshi/NWS daily climate report products.  It is deliberately
    best-effort; callers should treat missing fields as a no-trade condition.
    """
    raw = text or ""
    normalized = re.sub(r"\s+", " ", raw).strip()
    lower = normalized.lower()

    source_url = None
    url_match = _SOURCE_URL_RE.search(normalized)
    if url_match:
        source_url = url_match.group(0).rstrip(".,;\"'")

    source: str | None = None
    if "weather underground" in lower or "wunderground" in lower:
        source = "wunderground"
    elif "hong kong observatory" in lower or "hko" in lower or "hko.gov.hk" in lower:
        source = "hko"
    elif "daily climate report" in lower or "nws" in lower or "weather.gov" in lower:
        source = "nws_cli"

    product_code = None
    product_match = _NWS_PRODUCT_RE.search(normalized)
    if product_match:
        product_code = product_match.group(1).upper()
        source = source or "nws_cli"

    station_code = None
    icao_match = _ICAO_RE.search(normalized)
    if icao_match:
        station_code = icao_match.group(0).upper()
    if station_code is None and source_url:
        wunderground_station_match = _WUNDERGROUND_STATION_URL_RE.search(source_url)
        if wunderground_station_match:
            station_code = wunderground_station_match.group(1).upper()
    if station_code is None:
        # For Wunderground/international airports the code is often in parens.
        for match in _STATION_PAREN_RE.finditer(normalized):
            code = match.group(1).upper()
            if code != product_code:
                station_code = code
                break

    station_name = _station_name_before_code(normalized, station_code) if station_code else None
    if not station_name and source == "wunderground":
        station_name = _station_name_from_forecast_phrase(normalized)

    units = None
    if "celsius" in lower or "°c" in lower:
        units = "celsius"
    elif "fahrenheit" in lower or "°f" in lower:
        units = "fahrenheit"

    precision = None
    if "one decimal" in lower or "0.1" in lower or "tenths" in lower:
        precision = "one-decimal"
    elif "whole degree" in lower or "nearest whole" in lower or "integer" in lower:
        precision = "whole-degree"

    return SettlementMetadata(
        source=source,
        station_code=station_code,
        station_name=station_name,
        product_code=product_code,
        source_url=source_url,
        units=units,
        precision=precision,
        raw_text=normalized,
    )


def evaluate_weather_trade_gate(inputs: WeatherGateInput) -> WeatherGateResult:
    """Conservative no-trade gate for weather signals."""
    reasons: list[str] = []
    execution_spread: float | None = None

    if not inputs.settlement_source or not inputs.station_code:
        reasons.append("missing exact settlement source/station")

    if inputs.best_bid is None or inputs.best_ask is None:
        reasons.append("missing line-level bid/ask")
    else:
        execution_spread = inputs.best_ask - inputs.best_bid
        if execution_spread < 0:
            reasons.append("invalid negative spread")
        elif execution_spread > inputs.max_spread:
            reasons.append(f"spread {execution_spread:.1%} exceeds {inputs.max_spread:.1%} cap")

    if inputs.top_ask_size is None:
        reasons.append("missing top ask size")
    elif inputs.top_ask_size < inputs.min_top_ask_size:
        reasons.append(
            f"top ask size {inputs.top_ask_size:.1f} below {inputs.min_top_ask_size:.1f} minimum"
        )

    if inputs.ensemble_mean is None or inputs.threshold_f is None:
        reasons.append("missing threshold distance")
    else:
        distance = abs(inputs.ensemble_mean - inputs.threshold_f)
        if distance < inputs.min_threshold_buffer_f:
            reasons.append(
                f"ensemble mean is only {distance:.1f}°F from threshold (<{inputs.min_threshold_buffer_f:.1f}°F buffer)"
            )

    if inputs.market_probability <= 0 or inputs.market_probability >= 1:
        reasons.append("market probability outside open interval")

    return WeatherGateResult(
        allowed=not reasons,
        reasons=reasons,
        execution_spread=execution_spread,
        top_ask_size=inputs.top_ask_size,
    )
