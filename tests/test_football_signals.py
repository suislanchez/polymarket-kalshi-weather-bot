import pytest
from datetime import datetime
from unittest.mock import patch, AsyncMock, MagicMock
from backend.core.football_signals import (
    assemble_fixtures,
    _compute_form_status,
    _compute_bet_signal,
    FootballFixtureResponse,
    FormMatchResp,
    H2HMeetingResp,
    KalshiMarketInfo,
)
from backend.data.football import FootballFixtureData, MatchResultData, H2HMeetingData


class TestFormStatus:
    """Tests for BTTS form status computation."""

    def test_btts_good_at_four_of_five(self):
        """Form with 4 BTTS True -> 'good'."""
        form = [
            MatchResultData(date=datetime.now(), home_team="A", away_team="B", home_goals=1, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="C", home_goals=2, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="D", home_goals=1, away_goals=2, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="E", home_goals=3, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="F", home_goals=0, away_goals=2, both_scored=False),
        ]
        assert _compute_form_status(form) == "good"

    def test_btts_good_at_five_of_five(self):
        """Form with 5 BTTS True -> 'good'."""
        form = [
            MatchResultData(date=datetime.now(), home_team="A", away_team="B", home_goals=1, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="C", home_goals=2, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="D", home_goals=1, away_goals=2, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="E", home_goals=3, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="F", home_goals=2, away_goals=2, both_scored=True),
        ]
        assert _compute_form_status(form) == "good"

    def test_btts_bad_at_two_nos(self):
        """Form with 3 BTTS True, 2 False -> 'bad'."""
        form = [
            MatchResultData(date=datetime.now(), home_team="A", away_team="B", home_goals=1, away_goals=0, both_scored=False),
            MatchResultData(date=datetime.now(), home_team="A", away_team="C", home_goals=2, away_goals=0, both_scored=False),
            MatchResultData(date=datetime.now(), home_team="A", away_team="D", home_goals=1, away_goals=2, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="E", home_goals=3, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="F", home_goals=2, away_goals=2, both_scored=True),
        ]
        assert _compute_form_status(form) == "bad"

    def test_btts_bad_at_three_nos(self):
        """Form with 2 BTTS True, 3 False -> 'bad'."""
        form = [
            MatchResultData(date=datetime.now(), home_team="A", away_team="B", home_goals=1, away_goals=0, both_scored=False),
            MatchResultData(date=datetime.now(), home_team="A", away_team="C", home_goals=2, away_goals=0, both_scored=False),
            MatchResultData(date=datetime.now(), home_team="A", away_team="D", home_goals=0, away_goals=1, both_scored=False),
            MatchResultData(date=datetime.now(), home_team="A", away_team="E", home_goals=3, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="F", home_goals=2, away_goals=2, both_scored=True),
        ]
        assert _compute_form_status(form) == "bad"

    def test_btts_good_at_four_of_five_boundary(self):
        """Form with 4 BTTS True, 1 False -> 'good' (boundary case: >=4 both_scored = good)."""
        form = [
            MatchResultData(date=datetime.now(), home_team="A", away_team="B", home_goals=1, away_goals=0, both_scored=False),
            MatchResultData(date=datetime.now(), home_team="A", away_team="C", home_goals=2, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="D", home_goals=1, away_goals=2, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="E", home_goals=3, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="F", home_goals=2, away_goals=2, both_scored=True),
        ]
        assert _compute_form_status(form) == "good"

    def test_btts_neutral_two_yes(self):
        """Form with 2 BTTS True, 3 False -> 'bad' (not neutral)."""
        form = [
            MatchResultData(date=datetime.now(), home_team="A", away_team="B", home_goals=1, away_goals=0, both_scored=False),
            MatchResultData(date=datetime.now(), home_team="A", away_team="C", home_goals=2, away_goals=0, both_scored=False),
            MatchResultData(date=datetime.now(), home_team="A", away_team="D", home_goals=0, away_goals=1, both_scored=False),
            MatchResultData(date=datetime.now(), home_team="A", away_team="E", home_goals=3, away_goals=1, both_scored=True),
            MatchResultData(date=datetime.now(), home_team="A", away_team="F", home_goals=2, away_goals=2, both_scored=True),
        ]
        # This should be 'bad' because 3 neither-scored >= 2
        assert _compute_form_status(form) == "bad"

    def test_btts_empty_form_neutral(self):
        """Empty form -> 'neutral'."""
        assert _compute_form_status([]) == "neutral"


class TestBetSignal:
    """Tests for bet signal logic."""

    def test_bet_signal_false_when_over_price_above_threshold(self):
        """over_price=0.90, both good -> bet_signal=False."""
        kalshi = KalshiMarketInfo(ticker="TEST", over_price=0.90, under_price=0.10, title="Test")
        assert _compute_bet_signal("good", "good", kalshi) is False

    def test_bet_signal_true_when_over_price_at_threshold(self):
        """over_price=0.83, both good -> bet_signal=True."""
        kalshi = KalshiMarketInfo(ticker="TEST", over_price=0.83, under_price=0.17, title="Test")
        assert _compute_bet_signal("good", "good", kalshi) is True

    def test_bet_signal_true_when_over_price_below_threshold(self):
        """over_price=0.75, both good -> bet_signal=True."""
        kalshi = KalshiMarketInfo(ticker="TEST", over_price=0.75, under_price=0.25, title="Test")
        assert _compute_bet_signal("good", "good", kalshi) is True

    def test_bet_signal_false_when_only_home_good(self):
        """home good, away neutral -> bet_signal=False."""
        kalshi = KalshiMarketInfo(ticker="TEST", over_price=0.80, under_price=0.20, title="Test")
        assert _compute_bet_signal("good", "neutral", kalshi) is False

    def test_bet_signal_false_when_away_bad(self):
        """home good, away bad -> bet_signal=False."""
        kalshi = KalshiMarketInfo(ticker="TEST", over_price=0.80, under_price=0.20, title="Test")
        assert _compute_bet_signal("good", "bad", kalshi) is False

    def test_bet_signal_false_when_kalshi_none(self):
        """kalshi=None -> bet_signal=False."""
        assert _compute_bet_signal("good", "good", None) is False

    def test_bet_signal_false_when_over_price_none(self):
        """kalshi has no over_price -> bet_signal=False."""
        kalshi = KalshiMarketInfo(ticker="TEST", over_price=None, under_price=0.20, title="Test")
        assert _compute_bet_signal("good", "good", kalshi) is False


class TestAssembleFixtures:
    """Tests for the main assemble_fixtures function."""

    @pytest.mark.asyncio
    async def test_assemble_fixtures_returns_empty_when_fixture_list_empty(self):
        """Empty fixture list -> empty response."""
        with patch("backend.core.football_signals.fetch_epl_fixtures", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = []
            result = await assemble_fixtures()
            assert result == []

    @pytest.mark.asyncio
    async def test_assemble_fixtures_handles_fetch_exception(self):
        """fetch_epl_fixtures raises -> empty response (fail-open)."""
        with patch("backend.core.football_signals.fetch_epl_fixtures", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.side_effect = Exception("API error")
            result = await assemble_fixtures()
            assert result == []

    @pytest.mark.asyncio
    async def test_assemble_fixtures_populates_all_fields(self):
        """Single fixture gets fully populated with stats, H2H, form, and Kalshi."""
        # Use a future date relative to today (2026-11-26)
        from datetime import timedelta
        future_date = datetime.now() + timedelta(days=3)  # 3 days from now

        # Create a mock fixture
        mock_fixture = FootballFixtureData(
            fixture_id="12345",
            date=future_date,
            home_team="Arsenal",
            home_team_id=1,
            away_team="Chelsea",
            away_team_id=2,
            home_avg_gf=0.0,
            away_avg_gf=0.0,
            h2h_count=0,
            h2h_total_avg=0.0,
            h2h_meetings=[],
            home_form=[],
            away_form=[],
        )

        with patch("backend.core.football_signals.fetch_epl_fixtures", new_callable=AsyncMock) as mock_fetch:
            with patch("backend.core.football_signals.fetch_team_stats", new_callable=AsyncMock) as mock_team_stats:
                with patch("backend.core.football_signals.fetch_h2h_meetings", new_callable=AsyncMock) as mock_h2h:
                    with patch("backend.core.football_signals.fetch_last_5_form", new_callable=AsyncMock) as mock_form:
                        with patch("backend.core.football_signals.KalshiClient") as mock_client_class:
                            mock_fetch.return_value = [mock_fixture]
                            mock_team_stats.return_value = None  # Will use defaults
                            mock_h2h.return_value = [
                                H2HMeetingData(date=datetime(2025, 10, 1), home="Arsenal", away="Chelsea", score="2-1"),
                                H2HMeetingData(date=datetime(2025, 4, 1), home="Chelsea", away="Arsenal", score="1-3"),
                            ]
                            # Home form: 4 BTTS -> good
                            mock_form.side_effect = [
                                [  # home form
                                    MatchResultData(date=datetime(2026, 1, 1), home_team="Arsenal", away_team="X", home_goals=2, away_goals=1, both_scored=True),
                                    MatchResultData(date=datetime(2025, 12, 20), home_team="Arsenal", away_team="Y", home_goals=1, away_goals=1, both_scored=True),
                                    MatchResultData(date=datetime(2025, 12, 15), home_team="Arsenal", away_team="Z", home_goals=3, away_goals=1, both_scored=True),
                                    MatchResultData(date=datetime(2025, 12, 10), home_team="Arsenal", away_team="W", home_goals=2, away_goals=2, both_scored=True),
                                    MatchResultData(date=datetime(2025, 12, 5), home_team="Arsenal", away_team="V", home_goals=0, away_goals=1, both_scored=False),
                                ],
                                [  # away form
                                    MatchResultData(date=datetime(2026, 1, 1), home_team="Chelsea", away_team="X", home_goals=1, away_goals=2, both_scored=True),
                                    MatchResultData(date=datetime(2025, 12, 20), home_team="Chelsea", away_team="Y", home_goals=2, away_goals=1, both_scored=True),
                                    MatchResultData(date=datetime(2025, 12, 15), home_team="Chelsea", away_team="Z", home_goals=1, away_goals=3, both_scored=True),
                                    MatchResultData(date=datetime(2025, 12, 10), home_team="Chelsea", away_team="W", home_goals=2, away_goals=2, both_scored=True),
                                    MatchResultData(date=datetime(2025, 12, 5), home_team="Chelsea", away_team="V", home_goals=1, away_goals=0, both_scored=False),
                                ],
                            ]
                            # Mock Kalshi client - ticker date must match fixture date
                            ticker_date = future_date.strftime("%y%b%d").upper()  # e.g., 26NOV29
                            mock_client = MagicMock()
                            mock_client.get_markets = AsyncMock(return_value={
                                "markets": [
                                    {
                                        "ticker": f"KXEPLTOTAL-{ticker_date}-B1.5",
                                        "title": "Arsenal vs Chelsea - Over 1.5 Total Goals",
                                        "yes_bid_dollars": "0.80",
                                        "yes_ask_dollars": "0.82",
                                        "no_bid_dollars": "0.18",
                                        "no_ask_dollars": "0.20",
                                        "last_price_dollars": "0.81",
                                        "volume_fp": "1000",
                                    }
                                ]
                            })
                            mock_client_class.return_value = mock_client

                            result = await assemble_fixtures()

                            assert len(result) == 1
                            fixture = result[0]
                            assert fixture.id == "12345"
                            assert fixture.home_team == "Arsenal"
                            assert fixture.away_team == "Chelsea"
                            assert fixture.h2h_count == 2
                            assert fixture.h2h_total_avg > 0
                            assert fixture.home_form_status == "good"
                            assert fixture.away_form_status == "good"
                            assert fixture.kalshi is not None
                            assert fixture.kalshi.ticker == f"KXEPLTOTAL-{ticker_date}-B1.5"
                            assert fixture.kalshi.over_price is not None
                            assert fixture.kalshi.over_price <= 0.83
                            assert fixture.bet_signal is True