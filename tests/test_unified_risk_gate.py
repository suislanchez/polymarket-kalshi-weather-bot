"""Deterministic contract and behavior tests for the unified paper risk gate."""

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.trading.domain import AssetClass, Side, TradeProposal, Venue
from backend.trading.risk import (
    PortfolioState,
    RiskContext,
    RiskLimits,
    evaluate_proposal,
)


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def limits_data(**overrides):
    data = {
        "max_order_notional": Decimal("250"),
        "max_order_equity_fraction": Decimal("0.01"),
        "max_symbol_exposure_fraction": Decimal("0.05"),
        "max_gross_exposure_fraction": Decimal("0.25"),
        "max_crypto_exposure_fraction": Decimal("0.10"),
        "daily_loss_fraction": Decimal("0.01"),
        "stock_crypto_max_quote_age_seconds": Decimal("30"),
        "weather_max_quote_age_seconds": Decimal("300"),
        "allowed_symbols": frozenset({"SPY", "QQQ", "BTC/USD", "ETH/USD"}),
        "allowed_venues": frozenset(
            {Venue.ALPACA_PAPER, Venue.POLYMARKET_PAPER, Venue.KALSHI_PAPER}
        ),
    }
    data.update(overrides)
    return data


def make_limits(**overrides):
    return RiskLimits(**limits_data(**overrides))


def portfolio_data(**overrides):
    data = {
        "equity": Decimal("10000"),
        "start_of_day_nlv": Decimal("10000"),
        "daily_realized_pnl": Decimal("0"),
        "symbol_exposures": {},
        "gross_exposure": Decimal("0"),
        "crypto_exposure": Decimal("0"),
        "held_quantities": {},
    }
    data.update(overrides)
    return data


def make_portfolio(**overrides):
    return PortfolioState(**portfolio_data(**overrides))


def context_data(**overrides):
    data = {
        "now": NOW,
        "execution_mode": "paper",
        "idempotency_key": "risk:proposal-1",
        "seen_idempotency_keys": frozenset(),
        "global_kill_switch": False,
        "weather_upstream_approved": False,
        "weather_approval_evidence": (),
    }
    data.update(overrides)
    return data


def make_context(**overrides):
    return RiskContext(**context_data(**overrides))


def proposal_data(**overrides):
    data = {
        "proposal_id": "proposal-1",
        "strategy_id": "deterministic-test",
        "venue": Venue.ALPACA_PAPER,
        "asset_class": AssetClass.STOCK,
        "symbol": "SPY",
        "side": Side.BUY,
        "notional": Decimal("100"),
        "reference_price": Decimal("100"),
        "market_data_at": NOW,
        "created_at": NOW,
        "rationale": "fixed test proposal",
    }
    data.update(overrides)
    return data


def make_proposal(**overrides):
    return TradeProposal(**proposal_data(**overrides))


def decide(proposal=None, *, portfolio=None, context=None, limits=None):
    return evaluate_proposal(
        make_proposal() if proposal is None else proposal,
        make_portfolio() if portfolio is None else portfolio,
        make_context() if context is None else context,
        make_limits() if limits is None else limits,
    )


def assert_rejected(decision, *reasons):
    assert decision.approved is False
    assert decision.reason_codes == reasons
    assert decision.approved_quantity is None
    assert decision.approved_notional is None
    assert decision.decided_at == NOW
    assert decision.proposal_id == "proposal-1"


def test_accepts_valid_stock_with_one_normalized_notional_and_limit_snapshot():
    decision = decide()

    assert decision.approved is True
    assert decision.reason_codes == ()
    assert decision.approved_quantity is None
    assert decision.approved_notional == Decimal("100")
    assert decision.decided_at == NOW
    assert decision.proposal_id == "proposal-1"
    assert decision.model_dump()["limit_snapshot"] == {
        "max_order_notional": "250",
        "max_order_equity_fraction": "0.01",
        "max_symbol_exposure_fraction": "0.05",
        "max_gross_exposure_fraction": "0.25",
        "max_crypto_exposure_fraction": "0.10",
        "daily_loss_fraction": "0.01",
        "stock_crypto_max_quote_age_seconds": "30",
        "weather_max_quote_age_seconds": "300",
        "allowed_symbols": ["BTC/USD", "ETH/USD", "QQQ", "SPY"],
        "allowed_venues": ["alpaca_paper", "kalshi_paper", "polymarket_paper"],
    }
    assert json.loads(decision.model_dump_json())["limit_snapshot"] == decision.model_dump()[
        "limit_snapshot"
    ]


def test_accepts_valid_crypto_proposal():
    decision = decide(
        make_proposal(
            asset_class=AssetClass.CRYPTO,
            symbol="BTC/USD",
            reference_price=Decimal("60000"),
            notional=Decimal("80"),
        )
    )

    assert decision.approved is True
    assert decision.approved_notional == Decimal("80")
    assert decision.reason_codes == ()


def test_no_proposal_returns_no_decision_or_trade():
    assert evaluate_proposal(None, make_portfolio(), make_context(), make_limits()) is None


@pytest.mark.parametrize(
    ("asset_class", "symbol"),
    [(AssetClass.STOCK, "AAPL"), (AssetClass.CRYPTO, "DOGE/USD")],
)
def test_rejects_stock_or_crypto_symbol_outside_allowlist(asset_class, symbol):
    assert_rejected(
        decide(make_proposal(asset_class=asset_class, symbol=symbol)),
        "symbol_not_allowed",
    )


def test_rejects_sell_quantity_beyond_held_long_quantity():
    proposal = make_proposal(
        side=Side.SELL,
        quantity=Decimal("2"),
        notional=None,
        reference_price=Decimal("50"),
    )
    assert_rejected(decide(proposal), "opening_short_not_allowed")


def test_rejects_venue_outside_configured_paper_allowlist():
    restricted = make_limits(allowed_venues=frozenset({Venue.POLYMARKET_PAPER}))
    assert_rejected(decide(limits=restricted), "venue_not_allowed")


@pytest.mark.parametrize(
    ("asset_class", "venue"),
    [
        (AssetClass.STOCK, Venue.POLYMARKET_PAPER),
        (AssetClass.CRYPTO, Venue.KALSHI_PAPER),
        (AssetClass.PREDICTION_WEATHER, Venue.ALPACA_PAPER),
    ],
)
def test_rejects_incoherent_asset_and_venue(asset_class, venue):
    proposal = make_proposal(asset_class=asset_class, venue=venue)
    expected = (
        ("asset_venue_mismatch", "weather_upstream_not_approved")
        if asset_class is AssetClass.PREDICTION_WEATHER
        else ("asset_venue_mismatch",)
    )
    assert_rejected(decide(proposal), *expected)


def test_rejects_effective_notional_over_lesser_fixed_and_equity_order_cap():
    fixed_cap = decide(make_proposal(notional=Decimal("250.01")))
    equity_cap = decide(
        make_proposal(notional=Decimal("50.01")),
        portfolio=make_portfolio(equity=Decimal("5000")),
    )

    assert_rejected(fixed_cap, "order_notional_limit")
    assert_rejected(equity_cap, "order_notional_limit")


def test_rejects_projected_symbol_exposure_over_five_percent():
    state = make_portfolio(symbol_exposures={"SPY": Decimal("450")})
    assert_rejected(decide(portfolio=state), "symbol_exposure_limit")


def test_rejects_projected_gross_exposure_over_twenty_five_percent():
    state = make_portfolio(gross_exposure=Decimal("2450"))
    assert_rejected(decide(portfolio=state), "gross_exposure_limit")


def test_rejects_projected_crypto_exposure_over_ten_percent():
    proposal = make_proposal(asset_class=AssetClass.CRYPTO, symbol="BTC/USD")
    state = make_portfolio(crypto_exposure=Decimal("950"))
    assert_rejected(decide(proposal, portfolio=state), "crypto_exposure_limit")


@pytest.mark.parametrize("daily_pnl", [Decimal("-100"), Decimal("-101")])
def test_rejects_daily_realized_pnl_at_or_below_loss_threshold(daily_pnl):
    state = make_portfolio(daily_realized_pnl=daily_pnl)
    assert_rejected(decide(portfolio=state), "daily_loss_limit")


def test_rejects_stale_stock_or_crypto_quote():
    proposal = make_proposal(market_data_at=NOW - timedelta(seconds=30, microseconds=1))
    assert_rejected(decide(proposal), "stale_market_data")


def test_rejects_future_dated_quote_fail_closed():
    proposal = make_proposal(market_data_at=NOW + timedelta(microseconds=1))
    assert_rejected(decide(proposal), "future_market_data")


def test_rejects_duplicate_idempotency_key():
    context = make_context(seen_idempotency_keys=frozenset({"risk:proposal-1"}))
    assert_rejected(decide(context=context), "duplicate_idempotency_key")


def test_rejects_global_kill_switch():
    assert_rejected(decide(context=make_context(global_kill_switch=True)), "global_kill_switch")


@pytest.mark.parametrize("mode", ["live", "backtest", " PAPER "])
def test_rejects_any_execution_mode_other_than_exact_paper(mode):
    assert_rejected(decide(context=make_context(execution_mode=mode)), "execution_mode_not_paper")


def test_weather_requires_upstream_authoritative_approval_and_evidence():
    proposal = make_proposal(
        asset_class=AssetClass.PREDICTION_WEATHER,
        venue=Venue.POLYMARKET_PAPER,
        symbol="KNYC-HIGH-90",
    )
    assert_rejected(decide(proposal), "weather_upstream_not_approved")
    assert_rejected(
        decide(proposal, context=make_context(weather_upstream_approved=True)),
        "weather_upstream_not_approved",
    )


def test_weather_uses_separate_five_minute_freshness_boundary():
    proposal = make_proposal(
        asset_class=AssetClass.PREDICTION_WEATHER,
        venue=Venue.KALSHI_PAPER,
        symbol="KNYC-HIGH-90",
        market_data_at=NOW - timedelta(seconds=300),
    )
    context = make_context(
        weather_upstream_approved=True,
        weather_approval_evidence=("authoritative-weather-gate:v1",),
    )
    accepted = decide(proposal, context=context)
    stale = decide(
        proposal.model_copy(
            update={"market_data_at": NOW - timedelta(seconds=300, microseconds=1)}
        ),
        context=context,
    )

    assert accepted.approved is True
    assert accepted.approved_notional == Decimal("100")
    assert_rejected(stale, "stale_market_data")


def test_exact_hard_cap_and_quote_boundaries_are_accepted():
    proposal = make_proposal(notional=Decimal("100"), market_data_at=NOW - timedelta(seconds=30))
    state = make_portfolio(
        symbol_exposures={"SPY": Decimal("400")},
        gross_exposure=Decimal("2400"),
        daily_realized_pnl=Decimal("-99.99"),
    )
    decision = decide(proposal, portfolio=state)

    assert decision.approved is True
    assert decision.approved_notional == Decimal("100")


def test_both_size_intents_use_smaller_notional_without_losing_decimal_precision():
    proposal = make_proposal(
        quantity=Decimal("1.23456789"),
        notional=Decimal("99.00000001"),
        reference_price=Decimal("100"),
    )
    decision = decide(proposal)

    assert decision.approved is True
    assert decision.approved_notional == Decimal("99.00000001")
    assert decision.approved_quantity is None


def test_sell_safety_uses_larger_implied_quantity_from_both_size_intents():
    proposal = make_proposal(
        side=Side.SELL,
        quantity=Decimal("1"),
        notional=Decimal("200"),
        reference_price=Decimal("100"),
    )
    state = make_portfolio(
        symbol_exposures={"SPY": Decimal("100")},
        gross_exposure=Decimal("100"),
        held_quantities={"SPY": Decimal("1.5")},
    )
    assert_rejected(decide(proposal, portfolio=state), "opening_short_not_allowed")


def test_sell_that_only_reduces_long_position_reduces_exposure_and_passes():
    proposal = make_proposal(
        side=Side.SELL,
        quantity=Decimal("1"),
        notional=None,
        reference_price=Decimal("100"),
    )
    state = make_portfolio(
        symbol_exposures={"SPY": Decimal("550")},
        gross_exposure=Decimal("2600"),
        held_quantities={"SPY": Decimal("1")},
    )
    decision = decide(proposal, portfolio=state)

    assert decision.approved is True
    assert decision.approved_notional == Decimal("100")


def test_multi_failure_returns_all_reasons_once_in_stable_gate_order():
    proposal = make_proposal(
        venue=Venue.POLYMARKET_PAPER,
        symbol="AAPL",
        side=Side.SELL,
        quantity=Decimal("4"),
        notional=Decimal("400"),
        reference_price=Decimal("100"),
        market_data_at=NOW + timedelta(seconds=1),
    )
    state = make_portfolio(
        equity=Decimal("1000"),
        start_of_day_nlv=Decimal("1000"),
        daily_realized_pnl=Decimal("-10"),
        symbol_exposures={"AAPL": Decimal("100")},
        gross_exposure=Decimal("1000"),
    )
    context = make_context(
        execution_mode="live",
        seen_idempotency_keys=frozenset({"risk:proposal-1"}),
        global_kill_switch=True,
    )

    assert_rejected(
        decide(proposal, portfolio=state, context=context),
        "execution_mode_not_paper",
        "global_kill_switch",
        "duplicate_idempotency_key",
        "asset_venue_mismatch",
        "symbol_not_allowed",
        "opening_short_not_allowed",
        "order_notional_limit",
        "gross_exposure_limit",
        "daily_loss_limit",
        "future_market_data",
    )


def test_risk_models_are_frozen_extra_forbidden_and_deeply_immutable():
    symbols = {"SPY", "QQQ", "BTC/USD", "ETH/USD"}
    exposures = {"SPY": Decimal("10")}
    seen = {"already-seen"}
    limits = make_limits(allowed_symbols=symbols)
    state = make_portfolio(symbol_exposures=exposures, held_quantities={"SPY": Decimal("1")})
    context = make_context(seen_idempotency_keys=seen)
    symbols.add("AAPL")
    exposures["SPY"] = Decimal("999")
    seen.add("risk:proposal-1")

    assert "AAPL" not in limits.allowed_symbols
    assert state.symbol_exposures["SPY"] == Decimal("10")
    assert "risk:proposal-1" not in context.seen_idempotency_keys
    with pytest.raises(ValidationError, match="frozen"):
        limits.max_order_notional = Decimal("999")
    with pytest.raises(TypeError):
        state.symbol_exposures["SPY"] = Decimal("999")
    with pytest.raises(ValidationError, match="Extra inputs"):
        RiskContext(**context_data(secret="forbidden"))


@pytest.mark.parametrize(
    ("factory", "overrides"),
    [
        (RiskLimits, {"max_order_notional": Decimal("NaN")}),
        (RiskLimits, {"daily_loss_fraction": Decimal("Infinity")}),
        (PortfolioState, {"equity": Decimal("NaN")}),
        (PortfolioState, {"daily_realized_pnl": Decimal("-Infinity")}),
        (PortfolioState, {"gross_exposure": Decimal("-1")}),
        (PortfolioState, {"held_quantities": {"SPY": Decimal("NaN")}}),
    ],
)
def test_models_reject_nonfinite_and_invalid_numeric_state(factory, overrides):
    base = limits_data() if factory is RiskLimits else portfolio_data()
    with pytest.raises(ValidationError):
        factory(**{**base, **overrides})


@pytest.mark.parametrize(
    "field",
    [
        "max_order_notional",
        "max_order_equity_fraction",
        "max_symbol_exposure_fraction",
        "max_gross_exposure_fraction",
        "max_crypto_exposure_fraction",
        "daily_loss_fraction",
        "stock_crypto_max_quote_age_seconds",
        "weather_max_quote_age_seconds",
    ],
)
def test_risk_limits_require_strictly_positive_values(field):
    with pytest.raises(ValidationError):
        RiskLimits(**limits_data(**{field: Decimal("0")}))


def test_risk_context_requires_utc_nonblank_key_and_weather_evidence_items():
    with pytest.raises(ValidationError, match="UTC"):
        make_context(now=NOW.replace(tzinfo=None))
    with pytest.raises(ValidationError):
        make_context(idempotency_key="  ")
    with pytest.raises(ValidationError):
        make_context(weather_approval_evidence=("",))


def test_risk_model_copy_revalidates_updates_and_preserves_deep_immutability():
    limits = make_limits()
    state = make_portfolio()
    context = make_context()

    with pytest.raises(ValidationError):
        limits.model_copy(update={"max_order_notional": Decimal("NaN")})
    with pytest.raises(ValidationError, match="Extra inputs"):
        context.model_copy(update={"unknown": "unsafe"})

    mutable = {"SPY": Decimal("10")}
    copied = state.model_copy(update={"symbol_exposures": mutable})
    mutable["SPY"] = Decimal("999")
    assert copied.symbol_exposures["SPY"] == Decimal("10")
    with pytest.raises(TypeError):
        copied.symbol_exposures["SPY"] = Decimal("20")
