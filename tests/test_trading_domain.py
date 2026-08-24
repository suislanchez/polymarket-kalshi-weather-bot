"""Contract tests for normalized, immutable paper-trading domain values."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.trading.domain import (
    AccountSnapshot,
    AssetClass,
    ExecutionReport,
    NormalizedOrder,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    RiskDecision,
    Side,
    TradeProposal,
    Venue,
)


NOW = datetime(2026, 8, 23, 12, 0, tzinfo=timezone.utc)


def proposal_data(**overrides):
    data = {
        "proposal_id": "trend:SPY:2026-08-23T12:00:00Z",
        "strategy_id": "trend-following-v1",
        "venue": Venue.ALPACA_PAPER,
        "asset_class": AssetClass.STOCK,
        "symbol": "SPY",
        "side": Side.BUY,
        "notional": Decimal("100.00"),
        "reference_price": Decimal("642.31"),
        "market_data_at": NOW,
        "created_at": NOW,
        "rationale": "20/50 SMA crossover at 2026-08-23T12:00:00Z",
    }
    data.update(overrides)
    return data


def order_data(**overrides):
    data = {
        "client_order_id": "order:trend:SPY:2026-08-23T12:00:00Z",
        "proposal_id": "trend:SPY:2026-08-23T12:00:00Z",
        "venue": Venue.ALPACA_PAPER,
        "asset_class": AssetClass.STOCK,
        "symbol": "SPY",
        "side": Side.BUY,
        "notional": Decimal("100.00"),
        "order_type": OrderType.MARKET,
        "status": OrderStatus.APPROVED,
        "created_at": NOW,
    }
    data.update(overrides)
    return data


def test_domain_enums_cover_the_approved_contract_vocabulary():
    assert {item.value for item in AssetClass} == {
        "stock",
        "crypto",
        "prediction_weather",
    }
    assert {item.value for item in Venue} == {
        "alpaca_paper",
        "polymarket_paper",
        "kalshi_paper",
    }
    assert {item.value for item in Side} == {"buy", "sell"}
    assert {item.value for item in OrderType} == {"market", "limit"}
    assert {item.value for item in OrderStatus} == {
        "proposed",
        "risk_rejected",
        "approved",
        "submitted",
        "partially_filled",
        "filled",
        "canceled",
        "rejected",
    }


@pytest.mark.parametrize(
    ("quantity", "notional"),
    [
        (Decimal("1"), None),
        (None, Decimal("100")),
        (Decimal("0.5"), Decimal("100")),
    ],
)
def test_trade_proposal_accepts_positive_quantity_or_notional(quantity, notional):
    proposal = TradeProposal(**proposal_data(quantity=quantity, notional=notional))

    assert proposal.quantity == quantity
    assert proposal.notional == notional


@pytest.mark.parametrize(
    ("quantity", "notional"),
    [
        (None, None),
        (Decimal("0"), None),
        (Decimal("-1"), None),
        (None, Decimal("0")),
        (None, Decimal("-0.01")),
    ],
)
def test_trade_proposal_rejects_missing_or_non_positive_size(quantity, notional):
    with pytest.raises(ValidationError):
        TradeProposal(**proposal_data(quantity=quantity, notional=notional))


def test_limit_proposal_requires_a_positive_limit_price():
    with pytest.raises(ValidationError, match="limit_price"):
        TradeProposal(**proposal_data(order_type=OrderType.LIMIT))

    proposal = TradeProposal(
        **proposal_data(order_type=OrderType.LIMIT, limit_price=Decimal("640.00"))
    )
    assert proposal.limit_price == Decimal("640.00")


@pytest.mark.parametrize(
    "field",
    ["market_data_at", "created_at"],
)
def test_trade_proposal_requires_utc_aware_timestamps(field):
    with pytest.raises(ValidationError, match="UTC"):
        TradeProposal(**proposal_data(**{field: NOW.replace(tzinfo=None)}))

    with pytest.raises(ValidationError, match="UTC"):
        TradeProposal(
            **proposal_data(
                **{field: NOW.astimezone(timezone(timedelta(hours=-4)))}
            )
        )


def test_identifiers_are_nonblank_stable_strings():
    proposal_id = "  deterministic:proposal:id  "
    proposal = TradeProposal(**proposal_data(proposal_id=proposal_id))
    order_id = "  deterministic:client-order:id  "
    order = NormalizedOrder(**order_data(client_order_id=order_id))

    assert proposal.proposal_id == proposal_id
    assert order.client_order_id == order_id

    for field, value in (("proposal_id", ""), ("proposal_id", "   ")):
        with pytest.raises(ValidationError):
            TradeProposal(**proposal_data(**{field: value}))
    with pytest.raises(ValidationError):
        NormalizedOrder(**order_data(client_order_id="   "))


def test_contracts_are_frozen_and_forbid_unknown_model_output():
    proposal = TradeProposal(**proposal_data())

    with pytest.raises(ValidationError, match="frozen"):
        proposal.symbol = "QQQ"
    with pytest.raises(ValidationError, match="Extra inputs"):
        TradeProposal(**proposal_data(broker_client=object()))


def test_risk_decision_is_an_immutable_utc_contract():
    decision = RiskDecision(
        proposal_id="trend:SPY:2026-08-23T12:00:00Z",
        approved=True,
        reason_codes=(),
        approved_notional=Decimal("100.00"),
        decided_at=NOW,
        limit_snapshot={"max_order_notional": "250.00"},
    )

    assert decision.approved_notional == Decimal("100.00")
    with pytest.raises(ValidationError, match="frozen"):
        decision.approved = False
    with pytest.raises(ValidationError, match="UTC"):
        RiskDecision(
            proposal_id=decision.proposal_id,
            approved=False,
            reason_codes=("stale_market_data",),
            decided_at=NOW.replace(tzinfo=None),
        )


def test_normalized_order_enforces_size_limit_price_and_utc():
    order = NormalizedOrder(**order_data())
    assert order.status is OrderStatus.APPROVED

    with pytest.raises(ValidationError):
        NormalizedOrder(**order_data(quantity=None, notional=None))
    with pytest.raises(ValidationError, match="limit_price"):
        NormalizedOrder(**order_data(order_type=OrderType.LIMIT))
    with pytest.raises(ValidationError, match="UTC"):
        NormalizedOrder(**order_data(created_at=NOW.replace(tzinfo=None)))


def test_execution_report_captures_normalized_fill_lifecycle():
    report = ExecutionReport(
        client_order_id="order:trend:SPY:2026-08-23T12:00:00Z",
        venue=Venue.ALPACA_PAPER,
        status=OrderStatus.PARTIALLY_FILLED,
        broker_order_id="paper-broker-123",
        filled_quantity=Decimal("0.1"),
        average_fill_price=Decimal("642.50"),
        occurred_at=NOW,
        metadata={"source": "fake-paper-adapter"},
    )

    assert report.filled_quantity == Decimal("0.1")
    with pytest.raises(ValidationError):
        ExecutionReport(
            client_order_id=report.client_order_id,
            venue=report.venue,
            status=report.status,
            filled_quantity=Decimal("-0.1"),
            occurred_at=NOW,
        )


def test_account_and_position_snapshots_use_decimal_and_utc_values():
    position = PositionSnapshot(
        venue=Venue.ALPACA_PAPER,
        asset_class=AssetClass.CRYPTO,
        symbol="BTC/USD",
        quantity=Decimal("0.01"),
        cost_basis=Decimal("650.00"),
        market_value=Decimal("680.00"),
        average_entry_price=Decimal("65000"),
        current_price=Decimal("68000"),
        realized_pnl=Decimal("0"),
        unrealized_pnl=Decimal("30.00"),
        captured_at=NOW,
    )
    account = AccountSnapshot(
        venue=Venue.ALPACA_PAPER,
        cash=Decimal("9320.00"),
        equity=Decimal("10030.00"),
        buying_power=Decimal("9320.00"),
        captured_at=NOW,
        positions=(position,),
    )

    assert account.positions == (position,)
    assert isinstance(account.equity, Decimal)
    with pytest.raises(ValidationError, match="UTC"):
        PositionSnapshot(**{**position.model_dump(), "captured_at": NOW.replace(tzinfo=None)})
    with pytest.raises(ValidationError, match="Extra inputs"):
        AccountSnapshot(**{**account.model_dump(), "secret_key": "never"})
