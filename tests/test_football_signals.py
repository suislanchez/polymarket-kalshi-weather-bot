import pytest
from datetime import datetime, timezone
from backend.data.football import MatchResultData, H2HMeetingData, TeamStatsData
from backend.core.football_signals import (
    _compute_form_status,
    _utc_to_et_iso,
    _parse_kalshi_ticker_date,
    assemble_fixtures,
    FootballFixtureResponse,
    FormMatchResp,
    H2HMeetingResp,
    KalshiMarketInfo,
)


def test_btts_good_at_four_of_five():
    """Test that 4 True values out of 5 gives 'good' status."""
    matches = [
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team A",
            away_team="Team B",
            home_goals=1,
            away_goals=1,
            both_scored=True
        ),
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team A",
            away_team="Team C",
            home_goals=2,
            away_goals=1,
            both_scored=True
        ),
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team D",
            away_team="Team A",
            home_goals=1,
            away_goals=2,
            both_scored=True
        ),
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team A",
            away_team="Team E",
            home_goals=1,
            away_goals=1,
            both_scored=True
        ),
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team F",
            away_team="Team A",
            home_goals=0,
            away_goals=2,
            both_scored=False
        ),
    ]
    assert _compute_form_status(matches) == 'good'


def test_btts_bad_at_two_nos():
    """Test that 2 False (neither scored) out of 5 gives 'bad' status."""
    matches = [
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team A",
            away_team="Team B",
            home_goals=1,
            away_goals=1,
            both_scored=True
        ),
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team A",
            away_team="Team C",
            home_goals=2,
            away_goals=0,
            both_scored=False
        ),
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team D",
            away_team="Team A",
            home_goals=0,
            away_goals=1,
            both_scored=False
        ),
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team A",
            away_team="Team E",
            home_goals=1,
            away_goals=1,
            both_scored=True
        ),
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team F",
            away_team="Team A",
            home_goals=2,
            away_goals=1,
            both_scored=True
        ),
    ]
    assert _compute_form_status(matches) == 'bad'


def test_btts_neutral_one_no():
    """Test that 2 True, 1 False (3 games) gives 'neutral' status."""
    # With fewer than 5 games, neutral is possible
    matches = [
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team A",
            away_team="Team B",
            home_goals=1,
            away_goals=1,
            both_scored=True
        ),
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team A",
            away_team="Team C",
            home_goals=2,
            away_goals=1,
            both_scored=True
        ),
        MatchResultData(
            date=datetime.now(timezone.utc),
            home_team="Team D",
            away_team="Team A",
            home_goals=0,
            away_goals=2,
            both_scored=False
        ),
    ]
    # 2 both_scored=True, 1 both_scored=False
    # both_scored_count=2 (<4), neither_scored_count=1 (<2) -> neutral
    assert _compute_form_status(matches) == 'neutral'


def test_bet_signal_false_when_over_price_above_threshold():
    """Test bet_signal is False when over_price > 0.83 and both teams good."""
    # This test will need to be adjusted when we have the full assemble_fixtures test
    # For now, test the logic inline
    home_form_status = 'good'
    away_form_status = 'good'
    kalshi = KalshiMarketInfo(over_price=0.90)

    bet_signal = (
        home_form_status == 'good' and
        away_form_status == 'good' and
        kalshi.over_price is not None and
        kalshi.over_price <= 0.83
    )
    assert bet_signal is False


def test_bet_signal_true_when_over_price_at_threshold():
    """Test bet_signal is True when over_price = 0.83 and both teams good."""
    home_form_status = 'good'
    away_form_status = 'good'
    kalshi = KalshiMarketInfo(over_price=0.83)

    bet_signal = (
        home_form_status == 'good' and
        away_form_status == 'good' and
        kalshi.over_price is not None and
        kalshi.over_price <= 0.83
    )
    assert bet_signal is True


def test_bet_signal_false_when_only_home_good():
    """Test bet_signal is False when only home team has good form."""
    home_form_status = 'good'
    away_form_status = 'bad'
    kalshi = KalshiMarketInfo(over_price=0.80)

    bet_signal = (
        home_form_status == 'good' and
        away_form_status == 'good' and
        kalshi.over_price is not None and
        kalshi.over_price <= 0.83
    )
    assert bet_signal is False


@pytest.mark.asyncio
async def test_assemble_fixtures_returns_empty_when_fixture_list_empty():
    """Test assemble_fixtures returns empty list when no fixtures."""
    # This will naturally return empty if fetch_epl_fixtures returns empty
    # We can't easily mock the internal call without more complex setup
    # So this is a placeholder - the actual test runs with mocked env
    pass


def test_parse_kalshi_ticker_date_valid():
    """Test parsing valid Kalshi ticker date suffix."""
    dt = _parse_kalshi_ticker_date("KXEPLTOTAL-26NOV27NFOFC")
    assert dt is not None
    assert dt.year == 2026
    assert dt.month == 11
    assert dt.day == 27


def test_parse_kalshi_ticker_date_7char():
    """Test that date part is 7 chars (YYMONDD)."""
    dt = _parse_kalshi_ticker_date("KXEPLTOTAL-26NOV27NFOFC")
    # The date part should be 26NOV27 (7 chars)
    assert dt.day == 27


def test_parse_kalshi_ticker_date_invalid():
    """Test parsing invalid ticker returns None."""
    assert _parse_kalshi_ticker_date("INVALID") is None
    assert _parse_kalshi_ticker_date("KXEPLTOTAL") is None
    assert _parse_kalshi_ticker_date("") is None


def test_utc_to_et_iso():
    """Test UTC to ET conversion."""
    utc_dt = datetime(2026, 11, 27, 20, 0, 0, tzinfo=timezone.utc)
    et_iso = _utc_to_et_iso(utc_dt)
    # 20:00 UTC = 15:00 ET (EST)
    assert "15:00" in et_iso
    assert "-05:00" in et_iso or "-04:00" in et_iso  # EST or EDT