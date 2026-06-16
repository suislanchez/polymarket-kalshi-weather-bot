from types import SimpleNamespace

from backend.core.settlement import (
    _actual_outcome_label_for_direction,
    _select_polymarket_market_for_resolution,
    calculate_pnl,
)


def test_select_polymarket_resolution_market_matches_market_id_in_multi_market_weather_event():
    markets = [
        {"id": "2440767", "outcomePrices": '["0", "1"]', "closed": True},
        {"id": "2440776", "outcomePrices": '["1", "0"]', "closed": True},
    ]

    selected = _select_polymarket_market_for_resolution(markets, "2440776")

    assert selected == markets[1]


def test_select_polymarket_resolution_market_uses_single_market_event_fallback_only_when_unambiguous():
    single = {"id": "abc", "outcomePrices": '["1", "0"]', "closed": True}
    ambiguous = [
        {"id": "first", "outcomePrices": '["0", "1"]', "closed": True},
        {"id": "second", "outcomePrices": '["1", "0"]', "closed": True},
    ]

    assert _select_polymarket_market_for_resolution([single], "missing") == single
    assert _select_polymarket_market_for_resolution(ambiguous, "missing") is None


def test_calculate_pnl_uses_actual_bucket_outcome_not_first_event_market():
    no_trade = SimpleNamespace(direction="no", entry_price=0.027, size=75.0)
    yes_trade = SimpleNamespace(direction="yes", entry_price=0.12, size=75.0)

    assert calculate_pnl(no_trade, 1.0) == -75.0
    assert calculate_pnl(yes_trade, 1.0) == 550.0


def test_actual_outcome_label_matches_trade_direction_vocabulary_for_weather_yes_no_signals():
    assert _actual_outcome_label_for_direction("yes", 1.0) == "yes"
    assert _actual_outcome_label_for_direction("yes", 0.0) == "no"
    assert _actual_outcome_label_for_direction("no", 1.0) == "yes"
    assert _actual_outcome_label_for_direction("no", 0.0) == "no"
    assert _actual_outcome_label_for_direction("up", 1.0) == "up"
    assert _actual_outcome_label_for_direction("down", 0.0) == "down"
