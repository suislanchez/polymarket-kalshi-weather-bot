"""Football signal engine: computes BTTS form status, resolves Kalshi markets, emits bet signals."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import List, Optional
import pytz

from pydantic import BaseModel
from typing import Literal

from backend.data.football import (
    fetch_epl_fixtures,
    fetch_team_stats,
    fetch_h2h_meetings,
    fetch_last_5_form,
    FootballFixtureData,
    H2HMeetingData,
    MatchResultData,
    TeamStatsData,
)
from backend.data.kalshi_client import KalshiClient

logger = logging.getLogger("football_bot")

ET = pytz.timezone("America/New_York")


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
    home_form_status: Literal['good', 'bad', 'neutral']
    away_form_status: Literal['good', 'bad', 'neutral']
    kalshi: Optional[KalshiMarketInfo] = None
    bet_signal: bool


def _compute_form_status(matches: List[MatchResultData]) -> Literal['good', 'bad', 'neutral']:
    both_scored_count = sum(1 for m in matches if m.both_scored)
    neither_scored_count = sum(1 for m in matches if not m.both_scored)

    if both_scored_count >= 4:
        return 'good'
    elif neither_scored_count >= 2:
        return 'bad'
    else:
        return 'neutral'


def _utc_to_et_iso(dt_utc: datetime) -> str:
    if dt_utc.tzinfo is None:
        dt_utc = dt_utc.replace(tzinfo=timezone.utc)
    dt_et = dt_utc.astimezone(ET)
    return dt_et.isoformat()


def _parse_kalshi_ticker_date(ticker: str) -> Optional[datetime]:
    try:
        parts = ticker.split('-')
        if len(parts) < 2:
            return None
        date_part = parts[1][:7]
        year = 2000 + int(date_part[:2])
        month_str = date_part[2:5].upper()
        day = int(date_part[5:7])

        month_map = {
            'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4,
            'MAY': 5, 'JUN': 6, 'JUL': 7, 'AUG': 8,
            'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12
        }
        month = month_map.get(month_str)
        if month is None:
            return None

        return datetime(year, month, day, tzinfo=timezone.utc)
    except Exception:
        return None


async def _fetch_kalshi_market_for_fixture(
    fixture: FootballFixtureData,
    all_markets: dict
) -> Optional[KalshiMarketInfo]:
    fixture_date_utc = fixture.date
    if fixture_date_utc.tzinfo is None:
        fixture_date_utc = fixture_date_utc.replace(tzinfo=timezone.utc)

    fixture_date = fixture_date_utc.date()

    markets = all_markets.get("markets", [])
    for market in markets:
        ticker = market.get("ticker", "")
        title = market.get("title", "")

        if not ticker.startswith("KXEPLTOTAL"):
            continue

        market_date = _parse_kalshi_ticker_date(ticker)
        if market_date is None:
            continue

        market_date_only = market_date.date()

        day_diff = abs((market_date_only - fixture_date).days)
        if day_diff > 1:
            continue

        if fixture.home_team.lower() not in title.lower() and fixture.away_team.lower() not in title.lower():
            continue

        # Verify this is an "Over 1.5 Goals" market (not Under, Correct Score, etc.)
        title_lower = title.lower()
        if "over 1.5" not in title_lower and "over 1.5" not in ticker.lower():
            continue

        over_price = market.get("yes_bid")
        under_price = market.get("no_bid")

        return KalshiMarketInfo(
            ticker=ticker,
            over_price=over_price,
            under_price=under_price,
            title=title
        )

    return None


async def assemble_fixtures() -> List[FootballFixtureResponse]:
    try:
        fixtures = await fetch_epl_fixtures()
    except Exception as e:
        logger.warning(f"fetch_epl_fixtures raised: {e}")
        return []

    if not fixtures:
        return []

    kalshi_markets = {"markets": []}
    kalshi_client = None
    if KalshiClient().kalshi_credentials_present():
        try:
            kalshi_client = KalshiClient()
            kalshi_markets = await kalshi_client.get_markets(params={"series_ticker": "KXEPLTOTAL"})
        except Exception as e:
            logger.warning(f"Failed to fetch Kalshi markets: {e}")

    # Batch fetch team stats for all unique team IDs
    all_team_ids = set()
    for f in fixtures:
        all_team_ids.add(f.home_team_id)
        all_team_ids.add(f.away_team_id)

    team_stats_map = {}
    if all_team_ids and settings.API_FOOTBALL_KEY:
        stats_results = await asyncio.gather(
            *[fetch_team_stats(tid) for tid in all_team_ids],
            return_exceptions=True
        )
        for tid, result in zip(all_team_ids, stats_results):
            if isinstance(result, TeamStatsData):
                team_stats_map[tid] = result
            elif isinstance(result, Exception):
                logger.warning(f"Error fetching team stats for {tid}: {result}")

    # Batch fetch H2H for all fixture pairs
    h2h_map = {}
    if settings.API_FOOTBALL_KEY:
        h2h_results = await asyncio.gather(
            *[fetch_h2h_meetings(f.home_team_id, f.away_team_id) for f in fixtures],
            return_exceptions=True
        )
        for fixture, result in zip(fixtures, h2h_results):
            if isinstance(result, list):
                h2h_map[fixture.fixture_id] = result[:10]
            elif isinstance(result, Exception):
                logger.warning(f"Error fetching H2H for {fixture.home_team} vs {fixture.away_team}: {result}")

    # Batch fetch last-5 form for all unique team IDs
    form_map = {}
    if all_team_ids and settings.API_FOOTBALL_KEY:
        form_results = await asyncio.gather(
            *[fetch_last_5_form(tid) for tid in all_team_ids],
            return_exceptions=True
        )
        for tid, result in zip(all_team_ids, form_results):
            if isinstance(result, list):
                form_map[tid] = result
            elif isinstance(result, Exception):
                logger.warning(f"Error fetching form for team {tid}: {result}")

    results = []

    for fixture in fixtures:
        try:
            home_stats = team_stats_map.get(fixture.home_team_id)
            away_stats = team_stats_map.get(fixture.away_team_id)

            home_avg_gf = home_stats.avg_goals_for if home_stats else 0.0
            away_avg_gf = away_stats.avg_goals_for if away_stats else 0.0

            h2h_meetings = h2h_map.get(fixture.fixture_id, [])

            h2h_total_avg = 0.0
            if h2h_meetings:
                total_goals = 0
                for m in h2h_meetings:
                    try:
                        home_g, away_g = map(int, m.score.split('-'))
                        total_goals += home_g + away_g
                    except Exception:
                        continue
                h2h_total_avg = total_goals / len(h2h_meetings)

            home_form = form_map.get(fixture.home_team_id, [])
            away_form = form_map.get(fixture.away_team_id, [])

            home_form_status = _compute_form_status(home_form)
            away_form_status = _compute_form_status(away_form)

            home_form_resp = []
            for m in home_form:
                opponent = m.away_team if m.home_team == fixture.home_team else m.home_team
                score = f"{m.home_goals}-{m.away_goals}" if m.home_goals is not None and m.away_goals is not None else "?"
                home_form_resp.append(FormMatchResp(
                    date=_utc_to_et_iso(m.date),
                    opponent=opponent,
                    score=score,
                    both_scored=m.both_scored
                ))

            away_form_resp = []
            for m in away_form:
                opponent = m.away_team if m.home_team == fixture.away_team else m.home_team
                score = f"{m.home_goals}-{m.away_goals}" if m.home_goals is not None and m.away_goals is not None else "?"
                away_form_resp.append(FormMatchResp(
                    date=_utc_to_et_iso(m.date),
                    opponent=opponent,
                    score=score,
                    both_scored=m.both_scored
                ))

            h2h_resp = []
            for m in h2h_meetings:
                h2h_resp.append(H2HMeetingResp(
                    date=_utc_to_et_iso(m.date),
                    home=m.home,
                    away=m.away,
                    score=m.score
                ))

            kalshi_info = await _fetch_kalshi_market_for_fixture(fixture, kalshi_markets)

            bet_signal = (
                home_form_status == 'good' and
                away_form_status == 'good' and
                kalshi_info is not None and
                kalshi_info.over_price is not None and
                kalshi_info.over_price <= 0.83
            )

            results.append(FootballFixtureResponse(
                id=fixture.fixture_id,
                date=_utc_to_et_iso(fixture.date),
                home_team=fixture.home_team,
                away_team=fixture.away_team,
                home_avg_gf=home_avg_gf,
                away_avg_gf=away_avg_gf,
                h2h_count=len(h2h_meetings),
                h2h_total_avg=h2h_total_avg,
                h2h_meetings=h2h_resp,
                home_form=home_form_resp,
                away_form=away_form_resp,
                home_form_status=home_form_status,
                away_form_status=away_form_status,
                kalshi=kalshi_info,
                bet_signal=bet_signal
            ))

        except Exception as e:
            logger.warning(f"Error assembling fixture {fixture.fixture_id}: {e}")
            continue

    results.sort(key=lambda x: x.date)
    return results