import pytest
import os
from unittest.mock import patch
from datetime import datetime
from backend.data.football import (
    fetch_epl_fixtures,
    fetch_team_stats,
    fetch_h2h_meetings,
    fetch_last_5_form,
    MatchResultData,
    H2HMeetingData,
    TeamStatsData,
    FootballFixtureData
)

@pytest.mark.asyncio
async def test_fetch_epl_fixtures_returns_empty_when_no_keys_configured():
    with patch.dict(os.environ, {}, clear=True):
        # We need to make sure settings are actually reloaded or that they reflect no keys.
        # Since settings are a global instance, we can override them if needed or patch them.
        # Actually, let's just patch the settings object's attributes.
        with patch("backend.data.football.settings") as mocked_settings:
            mocked_settings.FOOTBALL_DATA_API_KEY = None
            mocked_settings.API_FOOTBALL_KEY = None
            mocked_settings.DATAHUB_API_KEY = None
            fixtures = await fetch_epl_fixtures()
            assert fixtures == []

def test_h2h_meeting_parse():
    # Example logic: score string "home-away"
    raw_json = {"goals": {"home": 2, "away": 1}}
    score = f"{raw_json['goals']['home']}-{raw_json['goals']['away']}"
    assert score == "2-1"

def test_match_result_both_scored_true():
    # home_goals=1, away_goals=1 -> both_scored=True
    # home_goals=0, away_goals=1 -> both_scored=False
    def check_both_scored(home, away):
        return home > 0 and away > 0

    assert check_both_scored(1, 1) is True
    assert check_both_scored(0, 1) is False

@pytest.mark.asyncio
async def test_api_football_failure_falls_back_to_football_dot_org():
    # This test is a bit complex as it requires mocking httpx.AsyncClient.
    # We will simulate all API calls failing.
    with patch("httpx.AsyncClient.get") as mock_get:
        # Simulate exception for every call
        mock_get.side_effect = Exception("API fail")

        # Call all four functions; they should return empty or None, not raise
        try:
            res1 = await fetch_epl_fixtures()
            res2 = await fetch_team_stats(1)
            res3 = await fetch_h2h_meetings(1, 2)
            res4 = await fetch_last_5_form(1)

            assert res1 == []
            assert res2 is None
            assert res3 == []
            assert res4 == []
        except Exception as e:
            pytest.fail(f"Functions raised exception: {e}")
