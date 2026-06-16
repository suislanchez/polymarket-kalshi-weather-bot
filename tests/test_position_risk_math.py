from types import SimpleNamespace

from backend.core.position_risk import (
    PositionEvidence,
    PositionQuote,
    RiskAction,
    calculate_exit_pnl,
    calculate_final_settlement_pnl,
    calculate_unrealized_pnl,
)
from backend.core.settlement import calculate_pnl


def test_exit_pnl_salvages_value_before_zero_with_size_as_dollars_deployed():
    assert calculate_exit_pnl(entry_price=0.45, exit_price=0.10, size=100.0) == -77.78


def test_unrealized_pnl_uses_current_executable_bid_for_held_side():
    assert calculate_unrealized_pnl(entry_price=0.45, current_exit_price=0.10, size=100.0) == -77.78


def test_final_settlement_pnl_uses_size_as_dollars_deployed():
    assert calculate_final_settlement_pnl(entry_price=0.45, size=100.0, won=True) == 122.22
    assert calculate_final_settlement_pnl(entry_price=0.45, size=100.0, won=False) == -100.0


def test_settlement_calculate_pnl_uses_dollars_deployed_semantics_for_yes_no_and_up_down():
    yes_trade = SimpleNamespace(direction="yes", entry_price=0.45, size=100.0)
    no_trade = SimpleNamespace(direction="no", entry_price=0.45, size=100.0)
    up_trade = SimpleNamespace(direction="up", entry_price=0.50, size=40.0)
    down_trade = SimpleNamespace(direction="down", entry_price=0.25, size=20.0)

    assert calculate_pnl(yes_trade, settlement_value=1.0) == 122.22
    assert calculate_pnl(yes_trade, settlement_value=0.0) == -100.0
    assert calculate_pnl(no_trade, settlement_value=0.0) == 122.22
    assert calculate_pnl(up_trade, settlement_value=1.0) == 40.0
    assert calculate_pnl(down_trade, settlement_value=0.0) == 60.0


def test_invalid_entry_price_returns_zero_to_avoid_division_by_zero():
    assert calculate_exit_pnl(entry_price=0.0, exit_price=0.10, size=100.0) == 0.0
    assert calculate_final_settlement_pnl(entry_price=0.0, size=100.0, won=True) == 0.0
