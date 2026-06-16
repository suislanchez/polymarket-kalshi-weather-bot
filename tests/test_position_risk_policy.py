from backend.core.position_risk import (
    PositionEvidence,
    PositionQuote,
    RiskAction,
    choose_exit_action,
)


def test_thesis_intact_prefers_hold_when_hold_ev_beats_exit():
    recommendation = choose_exit_action(
        quote=PositionQuote(exit_price=0.35, spread=0.03, top_bid_size=50.0),
        evidence=PositionEvidence(model_probability=0.42, thesis_status="intact", source_status="fresh"),
        entry_price=0.45,
        size=100.0,
    )

    assert recommendation.action == RiskAction.HOLD
    assert "thesis remains intact" in recommendation.reasons


def test_market_bad_but_source_missing_is_watch_not_exit():
    recommendation = choose_exit_action(
        quote=PositionQuote(exit_price=0.08, spread=0.04, top_bid_size=50.0),
        evidence=PositionEvidence(model_probability=None, thesis_status="unknown", source_status="missing"),
        entry_price=0.45,
        size=100.0,
    )

    assert recommendation.action == RiskAction.WATCH
    assert "source/model evidence incomplete" in recommendation.reasons


def test_model_below_threshold_with_executable_bid_exits():
    recommendation = choose_exit_action(
        quote=PositionQuote(exit_price=0.10, spread=0.03, top_bid_size=50.0),
        evidence=PositionEvidence(model_probability=0.05, thesis_status="broken", source_status="fresh"),
        entry_price=0.45,
        size=100.0,
    )

    assert recommendation.action == RiskAction.EXIT
    assert "model probability below exit threshold" in recommendation.reasons
    assert recommendation.exit_pnl == -77.78


def test_dust_or_no_liquidity_does_not_fake_exit():
    recommendation = choose_exit_action(
        quote=PositionQuote(exit_price=0.01, spread=0.03, top_bid_size=100.0),
        evidence=PositionEvidence(model_probability=0.01, thesis_status="broken", source_status="fresh"),
        entry_price=0.45,
        size=100.0,
    )

    assert recommendation.action == RiskAction.WATCH
    assert "exit price below minimum" in recommendation.reasons


def test_wide_spread_does_not_auto_exit_even_when_model_is_bad():
    recommendation = choose_exit_action(
        quote=PositionQuote(exit_price=0.12, spread=0.35, top_bid_size=100.0),
        evidence=PositionEvidence(model_probability=0.01, thesis_status="broken", source_status="fresh"),
        entry_price=0.45,
        size=100.0,
    )

    assert recommendation.action == RiskAction.WATCH
    assert "spread too wide for clean exit" in recommendation.reasons
