"""Signal engine for EPL soccer fixtures with Kalshi over-1.5 goals resolution."""
import logging
import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import List, Optional

import pytz
from pydantic import BaseModel, Field

from backend.config import settings
from backend.data.football import (
    fetch_epl_fixtures,
    fetch_team_stats,
    fetch_h2h_meetings,
    fetch_last_5_form,
    FootballFixtureData,
    MatchResultData,
    H2HMeetingData,
)
from backend.data.kalshi_client import KalshiClient

logger = logging.getLogger("trading_bot")

ET_TZ = pytz.timezone("America/New_York")
KALSHI_EPL_SERIES = "KXEPLTOTAL"


class H2HMeetingResp(BaseModel):
    date: str
    home: str
    away: str
    score: str


class FormMatchResp(BaseModel):
    date: str
    opponent: str
    score: str
    both_scored: bool


class KalshiMarketInfo(BaseModel):
    ticker: Optional[str] = None
    over_price: Optional[float] = None
    under_price: Optional[float] = None
    title: Optional[str] = None


class FootballFixtureResponse(BaseModel):
    id: str
    date: str
    home_team: str
    away_team: str
    home_avg_gf: float
    away_avg_gf: float
    h2h_count: int
    h2h_total_avg: float
    h2h_meetings: List[H2HMeetingResp]
    home_form: List[FormMatchResp]
    away_form: List[FormMatchResp]
    home_form_status: str
    away_form_status: str
    kalshi: Optional[KalshiMarketInfo] = None
    bet_signal: bool = False


def _compute_form_status(form: List[MatchResultData]) -> str:
    """
    Compute BTTS form status from last 5 matches.

    Rules:
    - "good": 4 or 5 matches with both_scored=True (>=4)
    - "bad": 2 or more matches with both_scored=False (>=2)
    - "neutral": otherwise (0-1 neither-scored matches, and <4 both_scored)
    """
    if not form:
        return "neutral"

    both_scored_count = sum(1 for m in form if m.both_scored)
    neither_scored_count = sum(1 for m in form if not m.both_scored)

    if both_scored_count >= 4:
        return "good"
    elif neither_scored_count >= 2:
        return "bad"
    else:
        return "neutral"


def _compute_bet_signal(
    home_form_status: str,
    away_form_status: str,
    kalshi: Optional[KalshiMarketInfo],
) -> bool:
    """
    Compute bet signal.

    Fires only when:
    - Both teams have "good" form status
    - Kalshi market exists with over_price <= 0.83
    """
    if home_form_status != "good" or away_form_status != "good":
        return False
    if not kalshi or kalshi.over_price is None:
        return False
    return kalshi.over_price <= 0.83


def _utc_to_et_iso(dt_utc: datetime) -> str:
    """Convert UTC datetime to ET ISO string."""
    if dt_utc.tzinfo is None:
        dt_utc = pytz.UTC.localize(dt_utc)
    dt_et = dt_utc.astimezone(ET_TZ)
    return dt_et.isoformat()


def _parse_kalshi_epl_ticker(ticker: str) -> Optional[dict]:
    """
    Parse Kalshi EPL total goals ticker.

    Format: KXEPLTOTAL-26NOV27-B1.5
      - 26NOV27 = 2026-11-27
      - B1.5 = over 1.5 goals (bottom boundary)
      - T1.5 = under 1.5 goals (top boundary)

    Returns dict with target_date, threshold, direction, or None if no match.
    """
    # Match: KXEPLTOTAL-YYMONDD-[BT]nn.n
    match = re.match(
        r'^KXEPLTOTAL-(\d{2})([A-Z]{3})(\d{2})-([BT])([\d.]+)$',
        ticker,
    )
    if not match:
        return None

    yy = int(match.group(1))
    mon_str = match.group(2)
    dd = int(match.group(3))
    boundary_type = match.group(4)
    threshold = float(match.group(5))

    MONTH_ABBR = {
        "JAN": 1, "FEB": 2, "MAR": 3, "APR": 4, "MAY": 5, "JUN": 6,
        "JUL": 7, "AUG": 8, "SEP": 9, "OCT": 10, "NOV": 11, "DEC": 12,
    }

    month = MONTH_ABBR.get(mon_str)
    if not month:
        return None

    year = 2000 + yy
    try:
        target_date = date(year, month, dd)
    except ValueError:
        return None

    # B = bottom boundary -> over threshold; T = top boundary -> under threshold
    direction = "over" if boundary_type == "B" else "under"

    return {
        "target_date": target_date,
        "threshold": threshold,
        "direction": direction,
    }


async def _fetch_kalshi_epl_market(
    fixture_date_et: date,
    home_team: str,
    away_team: str,
) -> Optional[KalshiMarketInfo]:
    """
    Fetch Kalshi EPL total goals market for a specific fixture.

    Filters markets by:
    - Date within +/-1 day of fixture date
    - Title contains either home or away team name
    """
    try:
        client = KalshiClient()
        data = await client.get_markets(params={"series_ticker": KALSHI_EPL_SERIES, "status": "open", "limit": 200})

        raw_markets = data.get("markets", [])
        fixture_date_et_normalized = fixture_date_et

        for m in raw_markets:
            ticker = m.get("ticker", "")
            title = m.get("title", "")

            # Parse ticker for date and threshold
            parsed = _parse_kalshi_epl_ticker(ticker)
            if not parsed:
                continue

            # Check date within +/-1 day
            date_diff = abs((parsed["target_date"] - fixture_date_et_normalized).days)
            if date_diff > 1:
                continue

            # Check team name in title (case-insensitive)
            title_lower = title.lower()
            if home_team.lower() not in title_lower and away_team.lower() not in title_lower:
                continue

            # Found a match - extract prices
            yes_bid = float(m.get("yes_bid_dollars", 0) or 0)
            yes_ask = float(m.get("yes_ask_dollars", 0) or 0)
            no_bid = float(m.get("no_bid_dollars", 0) or 0)
            no_ask = float(m.get("no_ask_dollars", 0) or 0)

            # Calculate mid prices
            yes_mid = (yes_bid + yes_ask) / 2 if (yes_bid > 0 or yes_ask > 0) else 0
            no_mid = (no_bid + no_ask) / 2 if (no_bid > 0 or no_ask > 0) else 0

            if yes_mid > 0:
                yes_price = yes_mid
            elif no_mid > 0:
                yes_price = 1.0 - no_mid
            else:
                last = float(m.get("last_price_dollars", 0) or 0)
                yes_price = last if last > 0 else 0.5

            # For over/under 1.5 goals, the YES side is typically "over"
            # B boundary = over, T boundary = under
            if parsed["direction"] == "over":
                over_price = yes_price
                under_price = 1.0 - yes_price
            else:
                under_price = yes_price
                over_price = 1.0 - yes_price

            return KalshiMarketInfo(
                ticker=ticker,
                over_price=over_price,
                under_price=under_price,
                title=title,
            )

    except Exception as e:
        logger.warning(f"Kalshi EPL market lookup failed: {e}")

    return None


def _build_form_response(form: List[MatchResultData], team_name: str) -> List[FormMatchResp]:
    """Convert MatchResultData list to FormMatchResp for a specific team."""
    result = []
    for match in form:
        # Determine opponent from team perspective
        if match.home_team == team_name:
            opponent = match.away_team
            score = f"{match.home_goals}-{match.away_goals}" if match.home_goals is not None else "?"
        else:
            opponent = match.home_team
            score = f"{match.away_goals}-{match.home_goals}" if match.away_goals is not None else "?"

        result.append(FormMatchResp(
            date=_utc_to_et_iso(match.date),
            opponent=opponent,
            score=score,
            both_scored=match.both_scored,
        ))
    return result


def _build_h2h_response(meetings: List[H2HMeetingData]) -> List[H2HMeetingResp]:
    """Convert H2HMeetingData list to H2HMeetingResp."""
    result = []
    for m in meetings:
        result.append(H2HMeetingResp(
            date=_utc_to_et_iso(m.date),
            home=m.home,
            away=m.away,
            score=m.score,
        ))
    return result


def _calculate_h2h_total_avg(meetings: List[H2HMeetingData]) -> float:
    """Calculate average total goals from H2H meetings."""
    if not meetings:
        return 0.0

    total_goals = 0
    valid_count = 0
    for m in meetings:
        try:
            home_goals, away_goals = map(int, m.score.split("-"))
            total_goals += home_goals + away_goals
            valid_count += 1
        except Exception:
            continue

    if valid_count == 0:
        return 0.0
    return round(total_goals / valid_count, 2)


async def _enrich_fixture(fixture: FootballFixtureData) -> FootballFixtureResponse:
    """Enrich a single fixture with team stats, H2H, form, and Kalshi market."""
    # Fetch team stats in parallel
    home_stats_task = fetch_team_stats(fixture.home_team_id)
    away_stats_task = fetch_team_stats(fixture.away_team_id)
    h2h_task = fetch_h2h_meetings(fixture.home_team_id, fixture.away_team_id)
    home_form_task = fetch_last_5_form(fixture.home_team_id)
    away_form_task = fetch_last_5_form(fixture.away_team_id)
    kalshi_task = _fetch_kalshi_epl_market(
        fixture.date.astimezone(ET_TZ).date(),
        fixture.home_team,
        fixture.away_team,
    )

    # Await all
    home_stats = await home_stats_task
    away_stats = await away_stats_task
    h2h_meetings = await h2h_task
    home_form = await home_form_task
    away_form = await away_form_task
    kalshi_market = await kalshi_task

    # Fill team stats (default 0.0 on failure)
    home_avg_gf = home_stats.avg_goals_for if home_stats else 0.0
    away_avg_gf = away_stats.avg_goals_for if away_stats else 0.0

    # H2H stats (cap at 10 most recent)
    h2h_meetings_sorted = sorted(h2h_meetings, key=lambda m: m.date, reverse=True)[:10]
    h2h_count = len(h2h_meetings_sorted)
    h2h_total_avg = _calculate_h2h_total_avg(h2h_meetings_sorted)

    # Form status
    home_form_status = _compute_form_status(home_form)
    away_form_status = _compute_form_status(away_form)

    # Build response objects
    home_form_resp = _build_form_response(home_form, fixture.home_team)
    away_form_resp = _build_form_response(away_form, fixture.away_team)
    h2h_resp = _build_h2h_response(h2h_meetings_sorted)

    # Bet signal
    bet_signal = _compute_bet_signal(home_form_status, away_form_status, kalshi_market)

    return FootballFixtureResponse(
        id=fixture.fixture_id,
        date=_utc_to_et_iso(fixture.date),
        home_team=fixture.home_team,
        away_team=fixture.away_team,
        home_avg_gf=round(home_avg_gf, 2),
        away_avg_gf=round(away_avg_gf, 2),
        h2h_count=h2h_count,
        h2h_total_avg=h2h_total_avg,
        h2h_meetings=h2h_resp,
        home_form=home_form_resp,
        away_form=away_form_resp,
        home_form_status=home_form_status,
        away_form_status=away_form_status,
        kalshi=kalshi_market,
        bet_signal=bet_signal,
    )


async def assemble_fixtures() -> List[FootballFixtureResponse]:
    """
    Main orchestration function: fetch EPL fixtures, enrich with all data, return response models.

    Fail-open: returns empty list on any top-level failure.
    Individual fixture failures are logged and that fixture is skipped.
    """
    try:
        fixtures = await fetch_epl_fixtures()
    except Exception as e:
        logger.warning(f"fetch_epl_fixtures raised exception: {e}")
        return []

    if not fixtures:
        return []

    # Filter to next 7 days in ET
    today_et = datetime.now(ET_TZ).date()
    week_later_et = today_et + timedelta(days=7)

    filtered = []
    for f in fixtures:
        fixture_date_et = f.date.astimezone(ET_TZ).date()
        if today_et <= fixture_date_et <= week_later_et:
            filtered.append(f)

    if not filtered:
        return []

    # Enrich each fixture (sequential for now to avoid API rate limits)
    results = []
    for fixture in filtered:
        try:
            enriched = await _enrich_fixture(fixture)
            results.append(enriched)
        except Exception as e:
            logger.warning(f"Failed to enrich fixture {fixture.fixture_id} ({fixture.home_team} vs {fixture.away_team}): {e}")
            continue

    # Sort by date ascending
    results.sort(key=lambda x: x.date)
    return results


# Need to import timedelta
from datetime import timedelta