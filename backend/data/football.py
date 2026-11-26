from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import List, Optional
import httpx
import logging
from backend.config import settings

logger = logging.getLogger("football_bot")

@dataclass
class MatchResultData:
    date: datetime
    home_team: str
    away_team: str
    home_goals: Optional[int]
    away_goals: Optional[int]
    both_scored: bool

@dataclass
class H2HMeetingData:
    date: datetime
    home: str
    away: str
    score: str   # e.g. "2-1"

@dataclass
class TeamStatsData:
    avg_goals_for: float
    avg_goals_against: float

@dataclass
class FootballFixtureData:
    fixture_id: str
    date: datetime
    home_team: str
    home_team_id: int
    away_team: str
    away_team_id: int
    home_avg_gf: float
    away_avg_gf: float
    h2h_count: int
    h2h_total_avg: float
    h2h_meetings: List[H2HMeetingData]
    home_form: List[MatchResultData]
    away_form: List[MatchResultData]

# API base URLs
FOOTBALL_DATA_BASE = "https://api.football-data.org/v4"
API_FOOTBALL_BASE = "https://v3.football.api-sports.io"
DATAHUB_BASE = "https://api.datahub.com"  # placeholder

# Headers
FOOTBALL_DATA_HEADERS = {"X-Auth-Token": settings.FOOTBALL_DATA_API_KEY} if settings.FOOTBALL_DATA_API_KEY else {}
API_FOOTBALL_HEADERS = {"x-apisports-key": settings.API_FOOTBALL_KEY} if settings.API_FOOTBALL_KEY else {}
DATAHUB_HEADERS = {"Authorization": f"Bearer {settings.DATAHUB_API_KEY}"} if settings.DATAHUB_API_KEY else {}

async def _get_async_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(timeout=15.0)

async def fetch_epl_fixtures() -> List[FootballFixtureData]:
    """Fetch EPL fixtures for the next 7 days from football-data.org, fallback to api-football.com."""

    # Try football-data.org first
    if settings.FOOTBALL_DATA_API_KEY:
        try:
            today = datetime.now(timezone.utc).date()
            date_from = today.isoformat()
            date_to = (today + timedelta(days=7)).isoformat()

            async with await _get_async_client() as client:
                response = await client.get(
                    f"{FOOTBALL_DATA_BASE}/competitions/PL/matches",
                    params={"dateFrom": date_from, "dateTo": date_to},
                    headers=FOOTBALL_DATA_HEADERS
                )
                response.raise_for_status()
                data = response.json()

                return _parse_football_data_fixtures(data)
        except Exception as e:
            logger.warning(f"football-data.org fetch failed, falling back: {e}")

    # Fallback to api-football.com
    if settings.API_FOOTBALL_KEY:
        try:
            async with await _get_async_client() as client:
                response = await client.get(
                    f"{API_FOOTBALL_BASE}/fixtures",
                    params={
                        "league": settings.EPL_LEAGUE_ID,
                        "season": 2025,
                        "from": datetime.now(timezone.utc).date().isoformat(),
                        "to": (datetime.now(timezone.utc).date() + timedelta(days=7)).isoformat(),
                        "timezone": "UTC"
                    },
                    headers=API_FOOTBALL_HEADERS
                )
                response.raise_for_status()
                data = response.json()

                return _parse_api_football_fixtures(data)
        except Exception as e:
            logger.warning(f"api-football.com fetch failed: {e}")

    return []

async def fetch_team_stats(team_id: int) -> Optional[TeamStatsData]:
    """Fetch team statistics from api-football.com."""
    if not settings.API_FOOTBALL_KEY:
        return None

    try:
        async with await _get_async_client() as client:
            response = await client.get(
                f"{API_FOOTBALL_BASE}/teams/statistics",
                params={"team": team_id, "league": settings.EPL_LEAGUE_ID, "season": 2025},
                headers=API_FOOTBALL_HEADERS
            )
            response.raise_for_status()
            data = response.json()

            stats = data.get("response", {})
            goals = stats.get("goals", {})
            for_avg = goals.get("for", {}).get("average", {}).get("total")
            against_avg = goals.get("against", {}).get("average", {}).get("total")

            return TeamStatsData(
                avg_goals_for=float(for_avg) if for_avg is not None else 0.0,
                avg_goals_against=float(against_avg) if against_avg is not None else 0.0
            )
    except Exception as e:
        logger.warning(f"Error fetching team stats for {team_id}: {e}")
        return None

async def fetch_h2h_meetings(team1_id: int, team2_id: int) -> List[H2HMeetingData]:
    """Fetch head-to-head meetings from api-football.com."""
    if not settings.API_FOOTBALL_KEY:
        return []

    try:
        async with await _get_async_client() as client:
            response = await client.get(
                f"{API_FOOTBALL_BASE}/fixtures/headtohead",
                params={"h2h": f"{team1_id}:{team2_id}", "last": 10},
                headers=API_FOOTBALL_HEADERS
            )
            response.raise_for_status()
            data = response.json()

            meetings = []
            for fixture in data.get("response", []):
                fixture_data = fixture.get("fixture", {})
                teams = fixture.get("teams", {})
                goals = fixture.get("goals", {})

                home_name = teams.get("home", {}).get("name", "")
                away_name = teams.get("away", {}).get("name", "")
                home_goals = goals.get("home")
                away_goals = goals.get("away")
                date_str = fixture_data.get("date")

                if home_name and away_name and date_str:
                    try:
                        date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        score = f"{home_goals}-{away_goals}"
                        meetings.append(H2HMeetingData(
                            date=date,
                            home=home_name,
                            away=away_name,
                            score=score
                        ))
                    except Exception:
                        continue

            return meetings
    except Exception as e:
        logger.warning(f"Error fetching H2H for {team1_id}:{team2_id}: {e}")
        return []

async def fetch_last_5_form(team_id: int) -> List[MatchResultData]:
    """Fetch last 5 matches form from api-football.com."""
    if not settings.API_FOOTBALL_KEY:
        return []

    try:
        async with await _get_async_client() as client:
            response = await client.get(
                f"{API_FOOTBALL_BASE}/fixtures",
                params={"team": team_id, "last": 5, "season": 2025, "timezone": "UTC"},
                headers=API_FOOTBALL_HEADERS
            )
            response.raise_for_status()
            data = response.json()

            results = []
            for fixture in data.get("response", []):
                fixture_data = fixture.get("fixture", {})
                teams = fixture.get("teams", {})
                goals = fixture.get("goals", {})

                home_name = teams.get("home", {}).get("name", "")
                away_name = teams.get("away", {}).get("name", "")
                home_goals = goals.get("home")
                away_goals = goals.get("away")
                date_str = fixture_data.get("date")

                if home_name and away_name and date_str:
                    try:
                        date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                        both = home_goals is not None and away_goals is not None and home_goals > 0 and away_goals > 0
                        results.append(MatchResultData(
                            date=date,
                            home_team=home_name,
                            away_team=away_name,
                            home_goals=home_goals,
                            away_goals=away_goals,
                            both_scored=both
                        ))
                    except Exception:
                        continue

            return results
    except Exception as e:
        logger.warning(f"Error fetching form for team {team_id}: {e}")
        return []

def _parse_football_data_fixtures(data: dict) -> List[FootballFixtureData]:
    """Parse football-data.org fixtures response."""
    fixtures = []
    for match in data.get("matches", []):
        try:
            fixture_id = str(match.get("id", ""))
            date_str = match.get("utcDate", "")
            date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            home_team = match.get("homeTeam", {}).get("name", "")
            away_team = match.get("awayTeam", {}).get("name", "")
            home_team_id = match.get("homeTeam", {}).get("id", 0)
            away_team_id = match.get("awayTeam", {}).get("id", 0)

            fixtures.append(FootballFixtureData(
                fixture_id=fixture_id,
                date=date,
                home_team=home_team,
                home_team_id=home_team_id,
                away_team=away_team,
                away_team_id=away_team_id,
                home_avg_gf=0.0,
                away_avg_gf=0.0,
                h2h_count=0,
                h2h_total_avg=0.0,
                h2h_meetings=[],
                home_form=[],
                away_form=[]
            ))
        except Exception:
            continue
    return fixtures

def _parse_api_football_fixtures(data: dict) -> List[FootballFixtureData]:
    """Parse api-football.com fixtures response."""
    fixtures = []
    for item in data.get("response", []):
        try:
            fixture = item.get("fixture", {})
            teams = item.get("teams", {})

            fixture_id = str(fixture.get("id", ""))
            date_str = fixture.get("date", "")
            date = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
            home_team = teams.get("home", {}).get("name", "")
            away_team = teams.get("away", {}).get("name", "")
            home_team_id = teams.get("home", {}).get("id", 0)
            away_team_id = teams.get("away", {}).get("id", 0)

            fixtures.append(FootballFixtureData(
                fixture_id=fixture_id,
                date=date,
                home_team=home_team,
                home_team_id=home_team_id,
                away_team=away_team,
                away_team_id=away_team_id,
                home_avg_gf=0.0,
                away_avg_gf=0.0,
                h2h_count=0,
                h2h_total_avg=0.0,
                h2h_meetings=[],
                home_form=[],
                away_form=[]
            ))
        except Exception:
            continue
    return fixtures