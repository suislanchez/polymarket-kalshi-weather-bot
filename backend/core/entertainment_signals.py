"""No-trade gates for Rotten Tomatoes / entertainment paper signals.

The goal is to keep research signals visible while preventing forced paper
actions when source state, market state, or liquidity quality is weak.
"""

import json
import math
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Any, Optional

logger = logging.getLogger("trading_bot")

DEFAULT_RT_ENTERTAINMENT_SNAPSHOT_DIR = Path("/Users/kayvonai/.hermes/research/.snapshots")

KNOWN_ROTTEN_TOMATOES_SOURCE_URLS = {
    "backrooms-rotten-tomatoes-score": "https://www.rottentomatoes.com/m/backrooms",
    "i-love-boosters-rotten-tomatoes-score": "https://www.rottentomatoes.com/m/i_love_boosters",
    "passenger-rotten-tomatoes-score": "https://www.rottentomatoes.com/m/passenger_2026",
    "pressure-rotten-tomatoes-score": "https://www.rottentomatoes.com/m/pressure_2026",
    "scary-movie-rotten-tomatoes-score": "https://www.rottentomatoes.com/m/scary_movie_2026",
    "star-wars-the-mandalorian-and-grogu-rotten-tomatoes-score": "https://www.rottentomatoes.com/m/star_wars_the_mandalorian_and_grogu",
    "supergirl-rotten-tomatoes-score": "https://www.rottentomatoes.com/m/supergirl_2026",
    "the-death-of-robin-hood-rotten-tomatoes-score": "https://www.rottentomatoes.com/m/the_death_of_robin_hood",
    "the-last-viking-rotten-tomatoes-score": "https://www.rottentomatoes.com/m/the_last_viking",
    "the-breadwinner-rotten-tomatoes-score": "https://www.rottentomatoes.com/m/the_breadwinner_2026",
}

DEFAULT_BOX_OFFICE_SOURCE_URL = "https://www.the-numbers.com/weekend-box-office-chart"


def parse_box_office_bucket(question: str) -> dict[str, Any]:
    """Parse Polymarket box-office bucket phrasing into million-dollar bounds.

    The parsed range is diagnostic/source-resolution metadata only. It lets the
    review queue and future final-source scorer distinguish mutually-exclusive
    bucket rows such as ``between 73m and 79m`` from one-sided tails without
    using the row as a forecast or upgrading actionability.
    """
    normalized = str(question or "").lower().replace("$", "")

    between = re.search(
        r"between\s+(\d+(?:\.\d+)?)\s*m(?:illion)?\s+and\s+(\d+(?:\.\d+)?)\s*m(?:illion)?",
        normalized,
    )
    if between:
        lower = float(between.group(1))
        upper = float(between.group(2))
        return {
            "box_office_lower_m": lower,
            "box_office_upper_m": upper,
            "box_office_bucket_label": f"${lower:g}M–${upper:g}M",
            "box_office_bucket_type": "range",
        }

    less_than = re.search(r"(?:less than|under|below)\s+(\d+(?:\.\d+)?)\s*m(?:illion)?", normalized)
    if less_than:
        upper = float(less_than.group(1))
        return {
            "box_office_lower_m": None,
            "box_office_upper_m": upper,
            "box_office_bucket_label": f"<${upper:g}M",
            "box_office_bucket_type": "below",
        }

    greater_than = re.search(r"(?:greater than|over|above)\s+(\d+(?:\.\d+)?)\s*m(?:illion)?", normalized)
    if greater_than:
        lower = float(greater_than.group(1))
        return {
            "box_office_lower_m": lower,
            "box_office_upper_m": None,
            "box_office_bucket_label": f">${lower:g}M",
            "box_office_bucket_type": "above",
        }

    at_least = re.search(r"(?:at least|at or above|or more)\s+(\d+(?:\.\d+)?)\s*m(?:illion)?", normalized)
    if at_least:
        lower = float(at_least.group(1))
        return {
            "box_office_lower_m": lower,
            "box_office_upper_m": None,
            "box_office_bucket_label": f"≥${lower:g}M",
            "box_office_bucket_type": "at_least",
        }

    return {
        "box_office_lower_m": None,
        "box_office_upper_m": None,
        "box_office_bucket_label": None,
        "box_office_bucket_type": None,
    }


def _normalize_box_office_title(title: str) -> str:
    """Normalize movie titles for source-chart joins."""
    return re.sub(r"[^a-z0-9]+", " ", str(title or "").lower()).strip()


def parse_the_numbers_weekend_box_office_grosses(text: str) -> dict[str, dict[str, Any]]:
    """Parse The Numbers weekend chart into title -> gross metadata.

    This is final/direct source-state parsing for box-office calibration only. It
    does not create a forecast, trading recommendation, or actionability.
    Accepts either extracted markdown tables or lightly stripped HTML text.
    """
    rows: dict[str, dict[str, Any]] = {}
    cleaned = re.sub(r"<[^>]+>", " | ", str(text or ""))
    candidates = [str(text or ""), cleaned]
    pattern = re.compile(
        r"\|\s*(?:\d+|-)\s*\|\s*(?:\([^|]+\)|[^|]*?)\s*\|\s*(?P<title>[^|]+?)\s*\|\s*\$(?P<gross>[\d,]+)",
        re.IGNORECASE,
    )
    for candidate in candidates:
        for match in pattern.finditer(candidate):
            title = re.sub(r"\s+", " ", match.group("title")).strip()
            if not title or title.lower() in {"title", "gross"}:
                continue
            gross = float(match.group("gross").replace(",", ""))
            rows[_normalize_box_office_title(title)] = {
                "title": title,
                "domestic_weekend_gross": gross,
                "domestic_weekend_gross_m": round(gross / 1_000_000.0, 3),
            }
    html_row_pattern = re.compile(
        r"<tr>\s*<td[^>]*>(?:\d+|-)</td>\s*<td[^>]*>.*?</td>\s*<td[^>]*>\s*(?:<b>)?<a[^>]*>(?P<title>.*?)</a>(?:</b>)?\s*</td>\s*<td[^>]*>\$(?P<gross>[\d,]+)</td>",
        re.IGNORECASE | re.DOTALL,
    )
    for match in html_row_pattern.finditer(str(text or "")):
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", match.group("title"))).strip()
        gross = float(match.group("gross").replace(",", ""))
        rows[_normalize_box_office_title(title)] = {
            "title": title,
            "domestic_weekend_gross": gross,
            "domestic_weekend_gross_m": round(gross / 1_000_000.0, 3),
        }
    return rows


def resolve_box_office_bucket_outcome(question: str, actual_gross_m: float | int | None) -> dict[str, Any]:
    """Resolve a parsed box-office bucket against a direct-source gross.

    The comparison intentionally mirrors the diagnostic bucket parser. It is for
    calibration/outcome-resolution rows only; callers must keep paper action
    gates separate.
    """
    bucket = parse_box_office_bucket(question)
    if actual_gross_m is None or bucket.get("box_office_bucket_type") is None:
        return {**bucket, "resolved_yes": None}
    actual = float(actual_gross_m)
    bucket_type = bucket.get("box_office_bucket_type")
    lower = bucket.get("box_office_lower_m")
    upper = bucket.get("box_office_upper_m")
    if bucket_type == "range":
        resolved_yes = lower is not None and upper is not None and lower <= actual <= upper
    elif bucket_type == "below":
        resolved_yes = upper is not None and actual < float(upper)
    elif bucket_type == "above":
        resolved_yes = lower is not None and actual > float(lower)
    elif bucket_type == "at_least":
        resolved_yes = lower is not None and actual >= float(lower)
    else:
        resolved_yes = None
    return {**bucket, "resolved_yes": resolved_yes, "actual_gross_m": actual}


def summarize_box_office_bucket_sets(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Group box-office bucket rows and run exactly-one-winner diagnostics.

    This is source-resolution/calibration QA only. Passing the sanity check means
    the captured final gross maps cleanly to one bucket in the fetched set; it
    does not create a forecast, paper trade, or actionability because platform
    settlement, calibrated model probability, bucket completeness, liquidity,
    and sizing gates remain separate requirements.
    """
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows or []:
        if not isinstance(row, dict) or row.get("error"):
            continue
        market_type = infer_entertainment_market_type(row)
        if market_type != "box_office":
            continue
        question = row.get("question") or row.get("title") or ""
        bucket = parse_box_office_bucket(question)
        if not bucket.get("box_office_bucket_type"):
            continue
        key = str(row.get("event_slug") or _question_title(question)).strip()
        if not key:
            continue
        grouped.setdefault(key, []).append({**row, **bucket})

    summaries: dict[str, dict[str, Any]] = {}
    for key, bucket_rows in grouped.items():
        resolved_rows = [row for row in bucket_rows if row.get("box_office_resolved_yes") is not None]
        yes_rows = [row for row in resolved_rows if bool(row.get("box_office_resolved_yes"))]
        probability_values: list[float] = []
        for row in bucket_rows:
            try:
                probability_values.append(float(row.get("probability")))
            except (TypeError, ValueError):
                continue
        probability_mass = round(sum(probability_values), 4) if probability_values else None
        sanity_passed = bool(resolved_rows) and len(yes_rows) == 1
        diagnostics: list[str] = []
        if not resolved_rows:
            diagnostics.append("no resolved buckets from direct final source yet")
        elif sanity_passed:
            diagnostics.append("exactly-one-winner sanity passed")
        else:
            diagnostics.append(f"expected exactly one resolved Yes bucket; found {len(yes_rows)}")
        diagnostics.append("calibration-only; platform settlement and independent forecast gates still required")

        winner = yes_rows[0] if yes_rows else None
        actual_values = [row.get("box_office_actual_gross_m") for row in bucket_rows if row.get("box_office_actual_gross_m") is not None]
        summaries[key] = {
            "event_slug": key,
            "source_title": _question_title(bucket_rows[0].get("question") or bucket_rows[0].get("title")),
            "bucket_set_size": len(bucket_rows),
            "resolved_bucket_count": len(resolved_rows),
            "resolved_yes_count": len(yes_rows),
            "bucket_set_probability_mass": probability_mass,
            "bucket_set_sanity_passed": sanity_passed,
            "resolved_winner_label": winner.get("box_office_bucket_label") if winner else None,
            "actual_gross_m": actual_values[0] if actual_values else None,
            "diagnostics": diagnostics,
            "paper_actionable": False,
        }
    return summaries


def infer_entertainment_market_type(row: dict[str, Any]) -> str:
    """Classify an entertainment market for source-state/gate diagnostics."""
    event_slug = str(row.get("event_slug") or "").lower()
    question = str(row.get("question") or row.get("title") or "").lower()
    if "box-office" in event_slug or "box office" in question:
        return "box_office"
    if "rotten-tomatoes" in event_slug or "rotten tomatoes" in question or "tomatometer" in question:
        return "rotten_tomatoes"
    return "entertainment"


def infer_box_office_source_url(row: dict[str, Any]) -> str:
    """Return the direct final-source URL that a box-office row still needs."""
    rules = str(row.get("rules") or row.get("event_description") or "").lower()
    if "box office mojo" in rules and "the numbers" not in rules:
        return "https://www.boxofficemojo.com/weekend/"
    return DEFAULT_BOX_OFFICE_SOURCE_URL


def infer_rotten_tomatoes_source_url(event_slug: Optional[str]) -> Optional[str]:
    """Return the public Rotten Tomatoes movie URL for a known RT market slug.

    The mapping is intentionally explicit rather than guessing arbitrary movie
    slugs; exposing an inferred URL helps review queues show the source that must
    be refreshed while keeping rows non-actionable until the direct source state
    is actually captured.
    """
    if not event_slug:
        return None
    return KNOWN_ROTTEN_TOMATOES_SOURCE_URLS.get(str(event_slug))


@dataclass(frozen=True)
class EntertainmentSignalGateInput:
    market_question: str
    market_probability: float
    model_probability: Optional[float]
    best_bid: Optional[float]
    best_ask: Optional[float]
    top_ask_size: Optional[float]
    direct_source_status: str  # e.g. "fresh", "stale", "missing", "fallback_only"
    source_score: Optional[float]
    review_count: Optional[int]
    threshold: Optional[float]
    hours_since_source_refresh: Optional[float]
    market_closed: bool = False
    min_edge: float = 0.08
    max_spread: float = 0.08
    min_top_ask_size: float = 25.0
    min_review_count: int = 30
    max_source_age_hours: float = 12.0


@dataclass(frozen=True)
class EntertainmentSignalGateResult:
    actionable: bool
    reasons: list[str] = field(default_factory=list)
    spread: Optional[float] = None
    edge: Optional[float] = None
    top_ask_size: Optional[float] = None
    source_state_label: str = "source-state: unknown"
    market_state_label: str = "market-state: unknown"


@dataclass(frozen=True)
class EntertainmentCalibrationResult:
    """Resolution-time score for an RT/entertainment binary forecast."""

    market_question: str
    forecast_probability: float
    resolved_yes: bool
    brier_score: float
    log_loss: float
    source_state_label: str


@dataclass(frozen=True)
class RottenTomatoesSourceSnapshot:
    """Parsed direct-source state from a public Rotten Tomatoes extraction."""

    title: str
    tomatometer_score: Optional[int]
    review_count: Optional[int]
    direct_source_status: str
    timing_risk_label: str


def parse_rotten_tomatoes_source_snapshot(text: str, *, title: str = "") -> RottenTomatoesSourceSnapshot:
    """Extract score/review-count source state from public RT page text.

    The parser intentionally stays conservative: a review count without a
    displayed percentage is ``no_displayed_score`` rather than model-ready.
    Low review counts are labelled for timing risk so gates can block paper
    action while still preserving the candidate for calibration.
    """
    score: Optional[int] = None
    review_count: Optional[int] = None

    # Current Rotten Tomatoes pages often hide the visible score in embedded
    # JSON rather than plain page text. Prefer the criticsScore block because
    # aggregateRating can lag or be duplicated for non-critic ratings.
    critics_block = re.search(r'"criticsScore"\s*:\s*\{(?P<body>[^{}]*?)\}', text, re.IGNORECASE | re.DOTALL)
    if critics_block:
        body = critics_block.group("body")
        score_match = re.search(r'"(?:score|scorePercent)"\s*:\s*"?(\d{1,3})%?"?', body, re.IGNORECASE)
        review_match = re.search(r'"reviewCount"\s*:\s*(\d[\d,]*)', body, re.IGNORECASE)
        if score_match:
            score = int(score_match.group(1))
        if review_match:
            review_count = int(review_match.group(1).replace(",", ""))

    if score is None or review_count is None:
        aggregate_block = re.search(r'"aggregateRating"\s*:\s*\{(?P<body>[^{}]*?)\}', text, re.IGNORECASE | re.DOTALL)
        if aggregate_block:
            body = aggregate_block.group("body")
            if "Tomatometer" in body:
                rating_match = re.search(r'"ratingValue"\s*:\s*"?(\d{1,3})"?', body, re.IGNORECASE)
                review_match = re.search(r'"(?:reviewCount|ratingCount)"\s*:\s*"?(\d[\d,]*)"?', body, re.IGNORECASE)
                if score is None and rating_match:
                    score = int(rating_match.group(1))
                if review_count is None and review_match:
                    review_count = int(review_match.group(1).replace(",", ""))

    score_patterns = [
        r"Tomatometer:\s*\*\*(\d{1,3})%\*\*",
        r"(\d{1,3})%\s+Tomatometer\s+(\d[\d,]*)\s+Reviews?",
        r"Tomatometer\s+(\d{1,3})%\s+on\s+(\d[\d,]*)\s+critic",
    ]
    if score is None or review_count is None:
        for pattern in score_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                if score is None:
                    score = int(match.group(1))
                if len(match.groups()) >= 2 and review_count is None:
                    review_count = int(match.group(2).replace(",", ""))
                break

    if review_count is None:
        review_patterns = [
            r"Critic Reviews:\s*\*\*(\d[\d,]*)\*\*",
            r"(\d[\d,]*)\s+Reviews?",
            r"on\s+(\d[\d,]*)\s+critic reviews?",
        ]
        for pattern in review_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                review_count = int(match.group(1).replace(",", ""))
                break

    if score is not None and review_count is not None:
        status = "fresh"
    elif review_count is not None:
        status = "no_displayed_score"
    else:
        status = "missing"

    if review_count is None:
        timing = "review-count missing"
    elif review_count < 30:
        timing = "high timing risk: below 30 reviews"
    elif review_count < 75:
        timing = "medium timing risk: review wave still small"
    else:
        timing = "lower timing risk: review count above gate"

    return RottenTomatoesSourceSnapshot(
        title=title,
        tomatometer_score=score,
        review_count=review_count,
        direct_source_status=status,
        timing_risk_label=timing,
    )


def summarize_latest_rotten_tomatoes_source_states(
    rows: list[Any],
    *,
    limit: int = 10,
    now: Optional[datetime] = None,
) -> list[dict[str, Any]]:
    """Return latest direct RT source-state snapshots per event/title.

    This is intentionally source-state only: it makes direct Rotten Tomatoes
    freshness visible to API/dashboard callers without implying a market edge
    or allowing a paper action. Market quotes, CLOB depth, thresholds, and gate
    checks must still be joined separately before any paper signal can become
    actionable.
    """
    if not rows or limit <= 0:
        return []

    reference_time = now or datetime.now(timezone.utc)

    def _captured_at(row: Any) -> Optional[datetime]:
        captured = getattr(row, "captured_at", None)
        if isinstance(captured, datetime):
            return captured
        if isinstance(captured, str):
            try:
                return datetime.fromisoformat(captured.replace("Z", "+00:00"))
            except ValueError:
                return None
        return None

    def _dedupe_key(row: Any) -> str:
        event_slug = getattr(row, "event_slug", None)
        if event_slug:
            return f"event:{event_slug}"
        title = getattr(row, "title", None)
        if title:
            return f"title:{title.strip().lower()}"
        source_url = getattr(row, "source_url", None)
        return f"source:{source_url or id(row)}"

    latest_by_key: dict[str, Any] = {}
    history_by_key: dict[str, list[Any]] = {}
    for row in rows:
        key = _dedupe_key(row)
        history_by_key.setdefault(key, []).append(row)
        existing = latest_by_key.get(key)
        if existing is None:
            latest_by_key[key] = row
            continue
        captured = _captured_at(row)
        existing_captured = _captured_at(existing)
        if existing_captured is None or (captured is not None and captured > existing_captured):
            latest_by_key[key] = row

    ordered_rows = sorted(
        latest_by_key.values(),
        key=lambda row: _captured_at(row) or datetime.min,
        reverse=True,
    )

    summaries: list[dict[str, Any]] = []
    for row in ordered_rows[:limit]:
        key = _dedupe_key(row)
        history = sorted(
            history_by_key.get(key, []),
            key=lambda candidate: _captured_at(candidate) or datetime.min,
            reverse=True,
        )
        previous = next((candidate for candidate in history if candidate is not row), None)

        captured = _captured_at(row)
        if captured is None:
            hours_since_refresh = None
            captured_iso = None
        else:
            reference = reference_time
            captured_for_delta = captured
            if reference.tzinfo is not None and captured_for_delta.tzinfo is None:
                captured_for_delta = captured_for_delta.replace(tzinfo=reference.tzinfo)
            elif reference.tzinfo is None and captured_for_delta.tzinfo is not None:
                reference = reference.replace(tzinfo=captured_for_delta.tzinfo)
            hours_since_refresh = max((reference - captured_for_delta).total_seconds() / 3600, 0.0)
            captured_iso = captured.isoformat()

        status = getattr(row, "direct_source_status", None) or "unknown"
        score = getattr(row, "tomatometer_score", None)
        review_count = getattr(row, "review_count", None)
        previous_captured = _captured_at(previous) if previous is not None else None
        previous_score = getattr(previous, "tomatometer_score", None) if previous is not None else None
        previous_review_count = getattr(previous, "review_count", None) if previous is not None else None
        score_delta = score - previous_score if score is not None and previous_score is not None else None
        review_count_delta = (
            review_count - previous_review_count
            if review_count is not None and previous_review_count is not None
            else None
        )
        if captured is not None and previous_captured is not None:
            captured_for_delta = captured
            previous_for_delta = previous_captured
            if captured_for_delta.tzinfo is not None and previous_for_delta.tzinfo is None:
                previous_for_delta = previous_for_delta.replace(tzinfo=captured_for_delta.tzinfo)
            elif captured_for_delta.tzinfo is None and previous_for_delta.tzinfo is not None:
                captured_for_delta = captured_for_delta.replace(tzinfo=previous_for_delta.tzinfo)
            hours_since_previous = max((captured_for_delta - previous_for_delta).total_seconds() / 3600, 0.0)
            previous_captured_iso = previous_captured.isoformat()
        else:
            hours_since_previous = None
            previous_captured_iso = None

        source_label_bits = [f"source-state: {status}"]
        if score is not None:
            source_label_bits.append(f"score={score:g}")
        if review_count is not None:
            source_label_bits.append(f"reviews={review_count}")
        if score_delta is not None:
            source_label_bits.append(f"score_delta={score_delta:+g}")
        if review_count_delta is not None:
            source_label_bits.append(f"reviews_delta={review_count_delta:+d}")

        no_trade_reasons = [
            "source state only; requires current market quote, threshold, CLOB depth, and gate evaluation"
        ]
        timing_risk = getattr(row, "timing_risk_label", None)
        timing_risk_lower = timing_risk.lower() if isinstance(timing_risk, str) else ""
        if status != "fresh":
            no_trade_reasons.append(f"direct source status is {status!r}, not fresh")
        if review_count is None or review_count < 75 or ("risk" in timing_risk_lower and "lower" not in timing_risk_lower):
            no_trade_reasons.append("review count/timing risk gate blocks action")

        summaries.append(
            {
                "title": getattr(row, "title", None),
                "event_slug": getattr(row, "event_slug", None),
                "source_url": getattr(row, "source_url", None),
                "source_method": getattr(row, "source_method", None),
                "captured_at": captured_iso,
                "hours_since_source_refresh": round(hours_since_refresh, 3) if hours_since_refresh is not None else None,
                "tomatometer_score": score,
                "review_count": review_count,
                "previous_captured_at": previous_captured_iso,
                "previous_tomatometer_score": previous_score,
                "previous_review_count": previous_review_count,
                "score_delta": score_delta,
                "review_count_delta": review_count_delta,
                "hours_since_previous_source": round(hours_since_previous, 3) if hours_since_previous is not None else None,
                "direct_source_status": status,
                "timing_risk_label": timing_risk,
                "cutoff_time": getattr(row, "cutoff_time", None),
                "source_state_label": "; ".join(source_label_bits),
                "paper_actionable": False,
                "no_trade_reason": no_trade_reasons[0],
                "no_trade_reasons": no_trade_reasons,
            }
        )

    return summaries


def persist_rotten_tomatoes_source_snapshot(
    snapshot: RottenTomatoesSourceSnapshot,
    *,
    source_url: str,
    source_method: str,
    cutoff_time: Optional[str] = None,
    event_slug: Optional[str] = None,
    captured_at: Optional[datetime] = None,
    db_factory: Optional[Callable[[], Any]] = None,
    snapshot_cls: Optional[type] = None,
) -> bool:
    """Persist a parsed RT source-state snapshot for later calibration joins.

    This keeps source-state evidence separate from market quotes and remains
    injectable for tests/cron environments. It never contacts venues or trades.
    Snapshot importers can pass ``captured_at`` so dashboard freshness reflects
    the public-source capture time instead of the later import time.
    """
    if snapshot is None:
        return False

    if db_factory is None or snapshot_cls is None:
        from backend.models.database import RottenTomatoesSourceState, SessionLocal

        db_factory = db_factory or SessionLocal
        snapshot_cls = snapshot_cls or RottenTomatoesSourceState

    db = db_factory()
    try:
        fields = {
            "title": snapshot.title,
            "event_slug": event_slug,
            "source_url": source_url,
            "source_method": source_method,
            "tomatometer_score": snapshot.tomatometer_score,
            "review_count": snapshot.review_count,
            "direct_source_status": snapshot.direct_source_status,
            "timing_risk_label": snapshot.timing_risk_label,
            "cutoff_time": cutoff_time,
        }
        if captured_at is not None:
            fields["captured_at"] = captured_at
        db.add(snapshot_cls(**fields))
        db.commit()
        return True
    except Exception as exc:
        logger.warning(f"Failed to persist Rotten Tomatoes source snapshot: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            db.close()
        except Exception:
            pass


def _question_title(question: Optional[str], fallback: Optional[str] = None) -> str:
    if not question:
        return fallback or "unknown RT/entertainment market"
    match = re.search(r'"([^"]+)"', question)
    return match.group(1) if match else (fallback or question)


def summarize_rotten_tomatoes_market_coverage(rows: list[dict[str, Any]]) -> dict[str, int]:
    """Count latest RT/entertainment snapshot coverage for operator QA.

    These counts are diagnostic only. They help cron summaries and dashboard
    loaders tell whether the current batch has direct sources, line books,
    bucket-set diagnostics, and no-score blockers, without changing paper
    actionability or ledger state.
    """
    summary = {
        "total_rows": 0,
        "rotten_tomatoes_rows": 0,
        "box_office_rows": 0,
        "unique_event_count": 0,
        "direct_source_rows": 0,
        "fresh_rt_source_rows": 0,
        "no_score_rt_rows": 0,
        "line_book_rows": 0,
        "top_ask_size_rows": 0,
        "box_office_bucket_rows": 0,
        "box_office_mass_outside_sanity_rows": 0,
        "paper_actionable_rows": 0,
    }
    event_slugs: set[str] = set()
    for row in rows or []:
        if not isinstance(row, dict) or row.get("error"):
            continue
        summary["total_rows"] += 1
        event_slug = row.get("event_slug")
        if event_slug:
            event_slugs.add(str(event_slug))
        market_type = row.get("market_type") or infer_entertainment_market_type(row)
        if market_type == "rotten_tomatoes":
            summary["rotten_tomatoes_rows"] += 1
        elif market_type == "box_office":
            summary["box_office_rows"] += 1

        source_state = row.get("source_state") if isinstance(row.get("source_state"), dict) else {}
        direct_source_status = row.get("direct_source_status") or source_state.get("direct_source_status")
        if source_state or row.get("source_url"):
            summary["direct_source_rows"] += 1
        if market_type == "rotten_tomatoes" and direct_source_status == "fresh":
            summary["fresh_rt_source_rows"] += 1
        if market_type == "rotten_tomatoes" and direct_source_status == "no_displayed_score":
            summary["no_score_rt_rows"] += 1
        if row.get("yes_bid", row.get("best_bid")) is not None and row.get("yes_ask", row.get("best_ask")) is not None:
            summary["line_book_rows"] += 1
        if row.get("top_ask_size") is not None:
            summary["top_ask_size_rows"] += 1
        if market_type == "box_office" and row.get("box_office_bucket_set_size") is not None:
            summary["box_office_bucket_rows"] += 1
        no_trade_reasons_raw = row.get("no_trade_reasons")
        no_trade_reasons = no_trade_reasons_raw if isinstance(no_trade_reasons_raw, list) else []
        probability_mass_outside_sanity = False
        probability_mass = row.get("box_office_bucket_set_probability_mass")
        if probability_mass is not None:
            try:
                probability_mass_outside_sanity = not 0.95 <= float(probability_mass) <= 1.05
            except (TypeError, ValueError):
                probability_mass_outside_sanity = False
        if market_type == "box_office" and (
            "box-office bucket-set probability mass outside 0.95-1.05 sanity band" in no_trade_reasons
            or probability_mass_outside_sanity
        ):
            summary["box_office_mass_outside_sanity_rows"] += 1
        if bool(row.get("paper_actionable")):
            summary["paper_actionable_rows"] += 1
    summary["unique_event_count"] = len(event_slugs)
    return summary


def summarize_rotten_tomatoes_market_candidates(
    market_rows: list[dict[str, Any]],
    *,
    source_summaries: Optional[list[dict[str, Any]]] = None,
    limit: int = 25,
) -> list[dict[str, Any]]:
    """Join current RT market rows to latest direct-source summaries.

    The joined rows are designed for read-only review queues/dashboard panels.
    They intentionally keep ``paper_actionable=False`` unless a caller has an
    independent calibrated model probability and every no-trade gate passes;
    source-state-implied 0/1 probabilities are not treated as forecasts.
    """
    if not market_rows or limit <= 0:
        return []

    source_by_slug: dict[str, dict[str, Any]] = {}
    for summary in source_summaries or []:
        slug = summary.get("event_slug") if isinstance(summary, dict) else None
        if slug:
            source_by_slug[str(slug)] = summary
    bucket_set_summaries = summarize_box_office_bucket_sets(market_rows)

    candidates: list[dict[str, Any]] = []
    for row in market_rows:
        if not isinstance(row, dict) or row.get("error"):
            continue
        market_type = infer_entertainment_market_type(row)
        event_slug = row.get("event_slug")
        source_state = row.get("source_state") if isinstance(row.get("source_state"), dict) else {}
        source_summary = source_by_slug.get(str(event_slug)) or {}
        inferred_source_url = infer_rotten_tomatoes_source_url(event_slug) if market_type == "rotten_tomatoes" else None
        source = {**source_state, **source_summary}
        if inferred_source_url and not source.get("source_url"):
            source["source_url"] = inferred_source_url
        if inferred_source_url and not source_state and not source_summary:
            source.setdefault("direct_source_status", "missing")
        if market_type == "box_office" and not source:
            source = {
                "source_url": infer_box_office_source_url(row),
                "source_method": "final-box-office-source-required",
                "direct_source_status": "missing_final_box_office_source",
            }

        best_bid = row.get("yes_bid", row.get("best_bid"))
        best_ask = row.get("yes_ask", row.get("best_ask"))
        market_probability = best_ask if best_ask is not None else row.get("probability")
        if market_probability is None:
            market_probability = 0.0
        box_office_bucket = parse_box_office_bucket(row.get("question") or row.get("title") or "") if market_type == "box_office" else {}

        gate = evaluate_entertainment_signal_gate(
            EntertainmentSignalGateInput(
                market_question=row.get("question") or row.get("title") or "RT/entertainment market",
                market_probability=float(market_probability),
                model_probability=row.get("model_probability"),
                best_bid=best_bid,
                best_ask=best_ask,
                top_ask_size=row.get("top_ask_size"),
                direct_source_status=source.get("direct_source_status") or "missing",
                source_score=source.get("tomatometer_score"),
                review_count=source.get("review_count"),
                threshold=row.get("threshold"),
                hours_since_source_refresh=source.get("hours_since_source_refresh"),
                market_closed=bool(row.get("market_closed", False)),
            )
        )
        no_trade_reasons = list(gate.reasons)
        if inferred_source_url and not source_state and not source_summary:
            inferred_reason = "no direct RT source snapshot for inferred source URL"
            if inferred_reason not in no_trade_reasons:
                no_trade_reasons.append(inferred_reason)
        if market_type == "box_office":
            no_trade_reasons = [
                reason for reason in no_trade_reasons
                if not reason.startswith("direct source status is 'final_source_captured'")
                and reason != "missing score/threshold source data"
                and reason != "review count below timing-risk gate"
            ]
            if source.get("direct_source_status") == "final_source_captured":
                reason = "box-office final source captured for calibration only; platform settlement still required"
                if reason not in no_trade_reasons:
                    no_trade_reasons.append(reason)
            elif "missing direct final box-office source snapshot" not in no_trade_reasons:
                no_trade_reasons.append("missing direct final box-office source snapshot")
            reason = "box-office market requires calibrated distribution plus final-source watcher"
            if reason not in no_trade_reasons:
                no_trade_reasons.append(reason)
            source_state_reason = None
        else:
            source_state_reason = "source-state snapshot is current-state evidence, not an independent calibrated forecast"
            if source_state_reason not in no_trade_reasons:
                no_trade_reasons.append(source_state_reason)

        if market_type == "box_office":
            bucket_set_summary = bucket_set_summaries.get(str(event_slug or ""))
            probability_mass = bucket_set_summary.get("bucket_set_probability_mass") if bucket_set_summary else None
            if probability_mass is not None and not 0.95 <= float(probability_mass) <= 1.05:
                reason = "box-office bucket-set probability mass outside 0.95-1.05 sanity band"
                if reason not in no_trade_reasons:
                    no_trade_reasons.append(reason)
        else:
            bucket_set_summary = None

        question = row.get("question") or row.get("title") or "RT/entertainment market"
        candidates.append(
            {
                "event_slug": event_slug,
                "market_key": row.get("condition_id") or row.get("market_id") or question,
                "title": question,
                "source_title": source.get("title") or _question_title(question),
                "market_type": market_type,
                "paper_actionable": False if (source_state_reason and source_state_reason in no_trade_reasons) or market_type == "box_office" else gate.actionable,
                "no_trade_reason": no_trade_reasons[0] if no_trade_reasons else "",
                "no_trade_reasons": no_trade_reasons,
                "edge": gate.edge,
                "best_bid": best_bid,
                "best_ask": best_ask,
                "threshold": row.get("threshold"),
                "box_office_lower_m": box_office_bucket.get("box_office_lower_m"),
                "box_office_upper_m": box_office_bucket.get("box_office_upper_m"),
                "box_office_bucket_label": box_office_bucket.get("box_office_bucket_label"),
                "box_office_bucket_type": box_office_bucket.get("box_office_bucket_type"),
                "box_office_actual_gross_m": row.get("box_office_actual_gross_m") or source.get("domestic_weekend_gross_m"),
                "box_office_resolved_yes": row.get("box_office_resolved_yes"),
                "box_office_bucket_set_size": bucket_set_summary.get("bucket_set_size") if bucket_set_summary else None,
                "box_office_bucket_set_probability_mass": bucket_set_summary.get("bucket_set_probability_mass") if bucket_set_summary else None,
                "box_office_bucket_set_sanity_passed": bucket_set_summary.get("bucket_set_sanity_passed") if bucket_set_summary else False,
                "box_office_resolved_yes_count": bucket_set_summary.get("resolved_yes_count") if bucket_set_summary else None,
                "box_office_resolved_winner_label": bucket_set_summary.get("resolved_winner_label") if bucket_set_summary else None,
                "market_closed": bool(row.get("market_closed", False)),
                "market_probability": row.get("probability"),
                "model_probability": row.get("model_probability"),
                "execution_spread": gate.spread,
                "top_ask_size": row.get("top_ask_size"),
                "hours_since_source_refresh": source.get("hours_since_source_refresh"),
                "source_url": source.get("source_url"),
                "source_method": source.get("source_method"),
                "direct_source_status": source.get("direct_source_status"),
                "tomatometer_score": source.get("tomatometer_score"),
                "review_count": source.get("review_count"),
                "previous_captured_at": source.get("previous_captured_at") or source.get("previous_source_captured_at"),
                "previous_tomatometer_score": source.get("previous_tomatometer_score"),
                "previous_review_count": source.get("previous_review_count"),
                "score_delta": source.get("score_delta"),
                "review_count_delta": source.get("review_count_delta"),
                "hours_since_previous_source": source.get("hours_since_previous_source"),
                "captured_at": source.get("captured_at"),
                "cutoff_time": source.get("cutoff_time"),
                "timing_risk_label": source.get("timing_risk_label"),
                "source_state_label": gate.source_state_label,
                "market_state_label": gate.market_state_label,
            }
        )

    return candidates[:limit]


def build_rotten_tomatoes_review_rows(
    market_rows: list[dict[str, Any]],
    source_summaries: Optional[list[dict[str, Any]]] = None,
) -> list[dict[str, Any]]:
    """Build a complete RT/entertainment review-row set for dashboard counts.

    The dashboard review queue applies its own display limit after blocker
    counting. This helper therefore keeps every row from the latest public
    market summary visible to the queue, then appends direct source-state rows
    whose slugs are not represented by a current market row. Rows remain
    non-actionable diagnostics; this helper never mutates state or creates
    paper trades.
    """
    source_summaries = source_summaries or []
    market_candidates = summarize_rotten_tomatoes_market_candidates(
        market_rows,
        source_summaries=source_summaries,
        limit=len(market_rows),
    )
    candidate_slugs = {
        candidate.get("event_slug")
        for candidate in market_candidates
        if candidate.get("event_slug")
    }
    source_only_rows = [
        {**summary, "paper_actionable": False}
        for summary in source_summaries
        if summary.get("event_slug") not in candidate_slugs
    ]
    return market_candidates + source_only_rows


def load_latest_rotten_tomatoes_market_rows(
    *,
    snapshot_dir: str | Path = DEFAULT_RT_ENTERTAINMENT_SNAPSHOT_DIR,
) -> tuple[list[dict[str, Any]], Optional[str], Optional[str]]:
    """Load active RT/entertainment rows from the newest public summary snapshot.

    This is a read-only dashboard bridge for the cron-produced public snapshot
    files. It only reads local JSON and returns market/source diagnostics;
    callers must still run no-trade gates before treating a row as reviewable,
    and this helper never mutates DB state or creates trades.
    """
    base = Path(snapshot_dir)
    try:
        candidates = sorted(
            base.glob("*-rt-entertainment-public-summary.json"),
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return [], None, None

    for path in candidates:
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        rows = payload.get("active_rows")
        if not isinstance(rows, list):
            continue
        normalized_rows = [row for row in rows if isinstance(row, dict)]
        return normalized_rows, str(path), payload.get("ts")

    return [], None, None


def score_entertainment_binary_forecast(
    *,
    market_question: str,
    forecast_probability: float,
    resolved_yes: bool,
    direct_source_status: str,
    source_score: Optional[float] = None,
    review_count: Optional[int] = None,
) -> EntertainmentCalibrationResult:
    """Score a settled RT/entertainment forecast for calibration tracking.

    This helper is deliberately side-effect-free: callers can persist the
    returned fields to a paper ledger/outcome table once platform settlement
    and direct-source resolution evidence have been captured.
    """
    if not 0 <= forecast_probability <= 1:
        raise ValueError("forecast_probability must be between 0 and 1")

    outcome = 1.0 if resolved_yes else 0.0
    brier = (forecast_probability - outcome) ** 2
    clipped_probability = min(max(forecast_probability, 1e-12), 1 - 1e-12)
    log_loss = -math.log(clipped_probability if resolved_yes else 1 - clipped_probability)

    source_label_bits = [f"source-state: {direct_source_status}"]
    if source_score is not None:
        source_label_bits.append(f"score={source_score:g}")
    if review_count is not None:
        source_label_bits.append(f"reviews={review_count}")

    return EntertainmentCalibrationResult(
        market_question=market_question,
        forecast_probability=forecast_probability,
        resolved_yes=resolved_yes,
        brier_score=round(brier, 6),
        log_loss=round(log_loss, 6),
        source_state_label="; ".join(source_label_bits),
    )


def evaluate_entertainment_signal_gate(gate: EntertainmentSignalGateInput) -> EntertainmentSignalGateResult:
    """Evaluate whether an RT/entertainment signal may become a paper action.

    This does not size or execute anything. Failed gates should still be logged
    as research/candidate signals with ``actionable=False``.
    """
    reasons: list[str] = []

    if gate.market_closed:
        reasons.append("market closed; calibration/source-resolution only")

    if gate.model_probability is None:
        edge = None
        reasons.append("missing model probability")
    else:
        edge = round(gate.model_probability - gate.market_probability, 6)
        if abs(edge) < gate.min_edge:
            reasons.append(f"edge {edge:.3f} below min_edge {gate.min_edge:.3f}")

    if gate.best_bid is None or gate.best_ask is None:
        spread = None
        reasons.append("missing line-level bid/ask")
    else:
        spread = round(gate.best_ask - gate.best_bid, 6)
        if spread < 0:
            reasons.append("invalid negative spread")
        elif spread > gate.max_spread:
            reasons.append(f"spread {spread:.3f} above max_spread {gate.max_spread:.3f}")

    if gate.top_ask_size is None or gate.top_ask_size < gate.min_top_ask_size:
        reasons.append("top ask size below liquidity gate")

    if gate.direct_source_status != "fresh":
        reasons.append(f"direct source status is {gate.direct_source_status!r}, not fresh")

    if gate.hours_since_source_refresh is None or gate.hours_since_source_refresh > gate.max_source_age_hours:
        reasons.append("source refresh is missing/stale")

    if gate.source_score is None or gate.threshold is None:
        reasons.append("missing score/threshold source data")

    if gate.review_count is None or gate.review_count < gate.min_review_count:
        reasons.append("review count below timing-risk gate")

    source_label_bits = [f"source-state: {gate.direct_source_status}"]
    if gate.source_score is not None:
        source_label_bits.append(f"score={gate.source_score:g}")
    if gate.review_count is not None:
        source_label_bits.append(f"reviews={gate.review_count}")

    market_label_bits = ["market-state: closed" if gate.market_closed else "market-state: open"]
    if gate.best_bid is not None and gate.best_ask is not None:
        market_label_bits.append(f"bid={gate.best_bid:.3f}/ask={gate.best_ask:.3f}")
    if gate.top_ask_size is not None:
        market_label_bits.append(f"top_ask={gate.top_ask_size:g}")
    if edge is not None:
        market_label_bits.append(f"edge={edge:.3f}")

    return EntertainmentSignalGateResult(
        actionable=not reasons,
        reasons=reasons,
        spread=spread,
        edge=edge,
        top_ask_size=gate.top_ask_size,
        source_state_label="; ".join(source_label_bits),
        market_state_label="; ".join(market_label_bits),
    )
