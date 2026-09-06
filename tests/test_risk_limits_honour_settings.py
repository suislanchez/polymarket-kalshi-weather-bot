"""A risk control that cannot be tightened is not a risk control.

backend/config.py declares seven unified risk settings and tests pin their
default values. paper_risk_limits() hardcoded four of them and read a different
setting for a fifth, so every one of those knobs was inert: an operator who set
MAX_ORDER_NOTIONAL_USD=50 to reduce exposure got no change at all, and the
hardcoded fractions were two to three times LOOSER than the values config
advertised.

The last test is the one that matters. Comparing constructed fields would pass
against a paper_risk_limits() that read the settings and then handed the risk
gate something else, so it drives the real evaluator and asserts that
tightening a setting actually refuses an order the looser setting allowed.
"""

from decimal import Decimal

import pytest

from backend.core import scheduler as scheduler_module
from backend.trading.domain import AssetClass, Side, TradeProposal, Venue
from backend.trading.adapters.fake import FakePaperAdapter
from backend.trading.risk import PortfolioState, RiskContext, evaluate_proposal


@pytest.fixture
def configured(monkeypatch):
    """Settings the scheduler will read, distinct from every current default."""
    values = {
        "MAX_ORDER_NOTIONAL_USD": 40.0,
        "MAX_ORDER_EQUITY_FRACTION": 0.011,
        "MAX_SYMBOL_EXPOSURE_FRACTION": 0.051,
        "MAX_GROSS_EXPOSURE_FRACTION": 0.251,
        "MAX_CRYPTO_EXPOSURE_FRACTION": 0.101,
        "MAX_MARKET_DATA_AGE_SECONDS": 31,
        "STOCK_CRYPTO_LANE_ENABLED": True,
    }
    for name, value in values.items():
        monkeypatch.setattr(scheduler_module.settings, name, value, raising=False)
    return values


@pytest.mark.parametrize(
    "setting,field",
    [
        ("MAX_ORDER_EQUITY_FRACTION", "max_order_equity_fraction"),
        ("MAX_SYMBOL_EXPOSURE_FRACTION", "max_symbol_exposure_fraction"),
        ("MAX_GROSS_EXPOSURE_FRACTION", "max_gross_exposure_fraction"),
        ("MAX_CRYPTO_EXPOSURE_FRACTION", "max_crypto_exposure_fraction"),
    ],
)
def test_each_exposure_fraction_comes_from_its_setting(configured, setting, field):
    limits = scheduler_module.paper_risk_limits()
    assert getattr(limits, field) == Decimal(str(configured[setting]))


def test_the_market_data_age_bound_comes_from_its_setting(configured):
    limits = scheduler_module.paper_risk_limits()
    assert limits.stock_crypto_max_quote_age_seconds == Decimal(
        str(configured["MAX_MARKET_DATA_AGE_SECONDS"])
    )


def test_the_order_notional_ceiling_is_never_exceeded_by_a_lane_setting(
    configured, monkeypatch
):
    """MAX_ORDER_NOTIONAL_USD is a ceiling over every lane, not one lane's size.

    The weather lane sizes from WEATHER_MAX_TRADE_SIZE. If that is larger than
    the configured ceiling, the ceiling has to win, or it is decorative.
    """
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_MAX_TRADE_SIZE", 10_000.0)

    limits = scheduler_module.paper_risk_limits()

    assert limits.max_order_notional == Decimal("40")


def test_a_smaller_lane_size_still_wins_over_the_ceiling(configured, monkeypatch):
    """A ceiling must not raise a lane's own, tighter limit."""
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_MAX_TRADE_SIZE", 5.0)

    assert scheduler_module.paper_risk_limits().max_order_notional == Decimal("5")


def test_tightening_the_ceiling_actually_refuses_an_order_it_used_to_allow(
    configured, monkeypatch
):
    """The behavioural assertion: the gate must observe the change.

    Reading the setting into a field proves nothing if the evaluator is handed
    a different object. This drives the real evaluator twice.
    """
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_MAX_TRADE_SIZE", 10_000.0)

    proposal = TradeProposal(
        proposal_id="ceiling-probe",
        strategy_id="test",
        venue=Venue.ALPACA_PAPER,
        asset_class=AssetClass.STOCK,
        symbol="SPY",
        side=Side.BUY,
        notional=Decimal("60"),
        reference_price=Decimal("100"),
        market_data_at=NOW,
        created_at=NOW,
        rationale="ceiling probe",
    )
    portfolio = PortfolioState(
        equity=Decimal("100000"),
        start_of_day_nlv=Decimal("100000"),
        daily_realized_pnl=Decimal("0"),
        gross_exposure=Decimal("0"),
        crypto_exposure=Decimal("0"),
    )
    context = RiskContext(now=NOW, execution_mode="paper", idempotency_key="ceiling-probe")

    # 40 < 60: the configured ceiling refuses it.
    tight = evaluate_proposal(
        proposal, portfolio=portfolio, context=context,
        limits=scheduler_module.paper_risk_limits(),
    )
    assert not tight.approved
    assert "order_notional_limit" in tight.reason_codes

    # Raise only the ceiling; nothing else changes.
    monkeypatch.setattr(scheduler_module.settings, "MAX_ORDER_NOTIONAL_USD", 500.0)
    loose = evaluate_proposal(
        proposal, portfolio=portfolio, context=context,
        limits=scheduler_module.paper_risk_limits(),
    )
    assert loose.approved, f"the ceiling was not observed: {loose.reason_codes}"


from datetime import datetime, timezone  # noqa: E402

NOW = datetime(2026, 9, 5, 12, 0, tzinfo=timezone.utc)


def test_the_daily_loss_ceiling_bounds_the_lane_derived_fraction(configured, monkeypatch):
    """MAX_DAILY_LOSS_FRACTION was the fifth inert knob, missed by 45a9787.

    The lane derives its fraction from WEATHER_DAILY_LOSS_LIMIT / INITIAL_BANKROLL.
    At stock defaults that is 200/10000 = 0.02, twice the declared 0.01 ceiling,
    so the advertised limit was not the one enforced.
    """
    monkeypatch.setattr(scheduler_module.settings, "MAX_DAILY_LOSS_FRACTION", 0.01)
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_DAILY_LOSS_LIMIT", 200.0)
    monkeypatch.setattr(scheduler_module.settings, "INITIAL_BANKROLL", 10_000.0)

    assert scheduler_module.paper_risk_limits().daily_loss_fraction == Decimal("0.01")


def test_a_tighter_lane_fraction_still_wins_over_the_ceiling(configured, monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "MAX_DAILY_LOSS_FRACTION", 0.05)
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_DAILY_LOSS_LIMIT", 50.0)
    monkeypatch.setattr(scheduler_module.settings, "INITIAL_BANKROLL", 10_000.0)

    assert scheduler_module.paper_risk_limits().daily_loss_fraction == Decimal("0.005")


def test_the_ceiling_is_observed_by_the_service_not_just_the_evaluator(
    configured, monkeypatch, tmp_path
):
    """Routes through PaperExecutionService, which is what production calls.

    The test above drives evaluate_proposal directly. That proves the evaluator
    honours the limits it is handed, but not that the object production hands it
    is the one paper_risk_limits() built -- which is the actual claim.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from backend.models.database import Base
    from backend.trading.service import PaperExecutionService, PaperExecutionSettings

    monkeypatch.setattr(scheduler_module.settings, "WEATHER_MAX_TRADE_SIZE", 10_000.0)
    monkeypatch.setattr(scheduler_module.settings, "EXECUTION_MODE", "paper")
    monkeypatch.setattr(scheduler_module.settings, "LIVE_TRADING_ENABLED", False)
    monkeypatch.setattr(scheduler_module.settings, "GLOBAL_TRADING_KILL_SWITCH", False)

    engine = create_engine(f"sqlite:///{tmp_path / 'gate.sqlite'}")
    Base.metadata.create_all(engine)

    def route(notional: str):
        proposal = TradeProposal(
            proposal_id=f"service-ceiling-{notional}",
            strategy_id="test",
            venue=Venue.ALPACA_PAPER,
            asset_class=AssetClass.STOCK,
            symbol="SPY",
            side=Side.BUY,
            notional=Decimal(notional),
            reference_price=Decimal("100"),
            market_data_at=NOW,
            created_at=NOW,
            rationale="service ceiling probe",
        )
        with sessionmaker(bind=engine, expire_on_commit=False)() as session:
            service = PaperExecutionService(
                session=session,
                adapters={Venue.ALPACA_PAPER: FakePaperAdapter(clock=lambda: NOW)},
                settings=PaperExecutionSettings(execution_mode="paper"),
                clock=lambda: NOW,
                kill_switch=scheduler_module.trading_kill_switch_engaged,
            )
            return service.execute(
                proposal,
                portfolio=PortfolioState(
                    equity=Decimal("100000"),
                    start_of_day_nlv=Decimal("100000"),
                    daily_realized_pnl=Decimal("0"),
                    gross_exposure=Decimal("0"),
                    crypto_exposure=Decimal("0"),
                ),
                context=RiskContext(
                    now=NOW,
                    execution_mode="paper",
                    idempotency_key=f"service-ceiling:{notional}",
                ),
                limits=scheduler_module.paper_risk_limits(),
            )

    # Ceiling is 40 (from the `configured` fixture): 60 must be refused...
    assert route("60").decision.approved is False
    # ...and raising only the ceiling must let the same size through.
    monkeypatch.setattr(scheduler_module.settings, "MAX_ORDER_NOTIONAL_USD", 500.0)
    approved = route("60")
    assert approved.decision.approved is True, approved.decision.reason_codes
    assert approved.report is not None and approved.report.status.value == "submitted"

    engine.dispose()
