"""Tests for /api/football/fixtures endpoint."""
import pytest
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from unittest.mock import AsyncMock, patch, MagicMock

from backend.api.main import app
from backend.core.football_signals import FootballFixtureResponse


@pytest.fixture
def client():
    return TestClient(app)


def test_football_fixtures_endpoint_returns_empty_on_error(client):
    """Test endpoint returns empty list when assemble_fixtures raises."""
    with patch("backend.api.main.assemble_fixtures", new_callable=AsyncMock) as mock_assemble:
        mock_assemble.side_effect = Exception("API error")

        response = client.get("/api/football/fixtures")

        assert response.status_code == 200
        assert response.json() == []


def test_football_fixtures_endpoint_returns_fixtures(client):
    """Test endpoint returns fixtures when assemble_fixtures succeeds."""
    mock_fixture = FootballFixtureResponse(
        id="fixture-123",
        date="2026-11-27T15:00:00-05:00",
        home_team="Arsenal",
        away_team="Chelsea",
        home_avg_gf=2.1,
        away_avg_gf=1.8,
        h2h_count=10,
        h2h_total_avg=2.5,
        h2h_meetings=[],
        home_form=[],
        away_form=[],
        home_form_status="good",
        away_form_status="good",
        kalshi=None,
        bet_signal=False
    )

    with patch("backend.api.main.assemble_fixtures", new_callable=AsyncMock) as mock_assemble:
        mock_assemble.return_value = [mock_fixture]

        response = client.get("/api/football/fixtures")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["id"] == "fixture-123"
        assert data[0]["home_team"] == "Arsenal"
        assert data[0]["away_team"] == "Chelsea"
        assert data[0]["home_avg_gf"] == 2.1
        assert data[0]["away_avg_gf"] == 1.8
        assert data[0]["home_form_status"] == "good"
        assert data[0]["away_form_status"] == "good"
        assert data[0]["bet_signal"] is False


def test_football_fixtures_endpoint_with_bet_signal(client):
    """Test endpoint returns bet_signal=true when conditions met."""
    from backend.core.football_signals import KalshiMarketInfo

    mock_fixture = FootballFixtureResponse(
        id="fixture-456",
        date="2026-11-27T15:00:00-05:00",
        home_team="Liverpool",
        away_team="Man City",
        home_avg_gf=2.5,
        away_avg_gf=2.2,
        h2h_count=8,
        h2h_total_avg=3.0,
        h2h_meetings=[],
        home_form=[],
        away_form=[],
        home_form_status="good",
        away_form_status="good",
        kalshi=KalshiMarketInfo(
            ticker="KXEPLTOTAL-26NOV27LIVMCI",
            over_price=0.80,
            under_price=0.25,
            title="Liverpool vs Man City - Over 1.5 Goals"
        ),
        bet_signal=True
    )

    with patch("backend.api.main.assemble_fixtures", new_callable=AsyncMock) as mock_assemble:
        mock_assemble.return_value = [mock_fixture]

        response = client.get("/api/football/fixtures")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1
        assert data[0]["bet_signal"] is True
        assert data[0]["kalshi"] is not None
        assert data[0]["kalshi"]["over_price"] == 0.80


def test_football_fixtures_response_model_shape(client):
    """Test response matches FootballFixtureResponse schema."""
    mock_fixture = FootballFixtureResponse(
        id="fixture-789",
        date="2026-11-28T12:30:00-05:00",
        home_team="Man Utd",
        away_team="Tottenham",
        home_avg_gf=1.5,
        away_avg_gf=1.7,
        h2h_count=5,
        h2h_total_avg=2.0,
        h2h_meetings=[
            {
                "date": "2026-10-15T15:00:00-05:00",
                "home": "Man Utd",
                "away": "Tottenham",
                "score": "2-1"
            }
        ],
        home_form=[
            {
                "date": "2026-11-20T15:00:00-05:00",
                "opponent": "Everton",
                "score": "2-1",
                "both_scored": True
            }
        ],
        away_form=[
            {
                "date": "2026-11-18T15:00:00-05:00",
                "opponent": "West Ham",
                "score": "1-2",
                "both_scored": True
            }
        ],
        home_form_status="neutral",
        away_form_status="neutral",
        kalshi=None,
        bet_signal=False
    )

    with patch("backend.api.main.assemble_fixtures", new_callable=AsyncMock) as mock_assemble:
        mock_assemble.return_value = [mock_fixture]

        response = client.get("/api/football/fixtures")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 1

        fixture = data[0]
        # Check all required fields are present
        assert "id" in fixture
        assert "date" in fixture
        assert "home_team" in fixture
        assert "away_team" in fixture
        assert "home_avg_gf" in fixture
        assert "away_avg_gf" in fixture
        assert "h2h_count" in fixture
        assert "h2h_total_avg" in fixture
        assert "h2h_meetings" in fixture
        assert "home_form" in fixture
        assert "away_form" in fixture
        assert "home_form_status" in fixture
        assert "away_form_status" in fixture
        assert "kalshi" in fixture
        assert "bet_signal" in fixture

        # Check form status values are valid
        assert fixture["home_form_status"] in ["good", "bad", "neutral"]
        assert fixture["away_form_status"] in ["good", "bad", "neutral"]


def test_football_fixtures_endpoint_returns_assemble_result(client):
    """Test endpoint returns whatever assemble_fixtures returns (no additional sorting)."""
    from backend.core.football_signals import KalshiMarketInfo

    mock_fixture_later = FootballFixtureResponse(
        id="fixture-later",
        date="2026-11-29T15:00:00-05:00",
        home_team="Brighton",
        away_team="Crystal Palace",
        home_avg_gf=1.4,
        away_avg_gf=1.2,
        h2h_count=3,
        h2h_total_avg=1.8,
        h2h_meetings=[],
        home_form=[],
        away_form=[],
        home_form_status="neutral",
        away_form_status="neutral",
        kalshi=None,
        bet_signal=False
    )

    mock_fixture_earlier = FootballFixtureResponse(
        id="fixture-earlier",
        date="2026-11-27T15:00:00-05:00",
        home_team="Arsenal",
        away_team="Chelsea",
        home_avg_gf=2.1,
        away_avg_gf=1.8,
        h2h_count=10,
        h2h_total_avg=2.5,
        h2h_meetings=[],
        home_form=[],
        away_form=[],
        home_form_status="good",
        away_form_status="good",
        kalshi=None,
        bet_signal=False
    )

    with patch("backend.api.main.assemble_fixtures", new_callable=AsyncMock) as mock_assemble:
        # Endpoint just returns whatever assemble_fixtures returns
        mock_assemble.return_value = [mock_fixture_later, mock_fixture_earlier]

        response = client.get("/api/football/fixtures")

        assert response.status_code == 200
        data = response.json()
        assert len(data) == 2
        # Endpoint returns mock result directly (no additional sorting in endpoint)
        assert data[0]["id"] == "fixture-later"
        assert data[1]["id"] == "fixture-earlier"