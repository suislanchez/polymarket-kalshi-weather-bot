"""Contract tests for normalized, immutable paper-trading domain values."""

import json
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


def test_json_metadata_is_deeply_immutable_and_dumps_as_mutable_json():
    proposal = TradeProposal(
        **proposal_data(
            metadata={"audit": {"sources": ["strategy", {"version": 1}]}}
        )
    )

    with pytest.raises(TypeError):
        proposal.metadata["new"] = "value"
    with pytest.raises(TypeError):
        proposal.metadata["audit"]["sources"][1]["version"] = 2
    with pytest.raises(TypeError):
        proposal.metadata["audit"]["sources"][0] = "adapter"

    dumped = proposal.model_dump()
    assert dumped["metadata"] == {
        "audit": {"sources": ["strategy", {"version": 1}]}
    }
    assert isinstance(dumped["metadata"], dict)
    assert isinstance(dumped["metadata"]["audit"], dict)
    assert isinstance(dumped["metadata"]["audit"]["sources"], list)
    def reject_non_finite_constant(value):
        raise ValueError(f"non-finite JSON constant: {value}")

    assert json.loads(
        proposal.model_dump_json(), parse_constant=reject_non_finite_constant
    )["metadata"] == dumped["metadata"]

    dumped["metadata"]["audit"]["sources"][1]["version"] = 99
    assert proposal.metadata["audit"]["sources"][1]["version"] == 1


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_json_metadata_rejects_non_finite_python_floats(value):
    with pytest.raises(ValidationError, match="finite JSON number"):
        TradeProposal(**proposal_data(metadata={"nested": [value]}))


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_json_metadata_rejects_non_finite_constants_from_raw_json(constant):
    raw = json.dumps(
        proposal_data(
            venue=Venue.ALPACA_PAPER.value,
            asset_class=AssetClass.STOCK.value,
            side=Side.BUY.value,
            notional="100.00",
            reference_price="642.31",
            market_data_at=NOW.isoformat(),
            created_at=NOW.isoformat(),
            metadata={"nested": [0]},
        )
    ).replace('"nested": [0]', f'"nested": [{constant}]')

    with pytest.raises(ValidationError, match="finite JSON number"):
        TradeProposal.model_validate_json(raw)


def test_model_copy_validates_and_deeply_freezes_metadata_updates():
    proposal = TradeProposal(**proposal_data())
    mutable_metadata = {"audit": {"sources": ["strategy"]}}

    copied = proposal.model_copy(update={"metadata": mutable_metadata})
    mutable_metadata["audit"]["sources"].append("caller")

    assert copied is not proposal
    assert copied.model_dump()["metadata"] == {
        "audit": {"sources": ["strategy"]}
    }
    with pytest.raises(TypeError):
        copied.metadata["audit"]["sources"][0] = "adapter"
    assert json.loads(copied.model_dump_json())["metadata"] == {
        "audit": {"sources": ["strategy"]}
    }


def test_model_copy_rejects_invalid_scalar_updates():
    proposal = TradeProposal(**proposal_data())

    with pytest.raises(ValidationError):
        proposal.model_copy(update={"notional": Decimal("-1")})


def test_normalized_order_model_copy_rejects_dual_sizing():
    order = NormalizedOrder(**order_data())

    with pytest.raises(ValidationError, match="exactly one sizing field"):
        order.model_copy(update={"quantity": Decimal("1")})


def test_execution_report_model_copy_revalidates_lifecycle():
    report = ExecutionReport(
        client_order_id="order:trend:SPY:2026-08-23T12:00:00Z",
        venue=Venue.ALPACA_PAPER,
        status=OrderStatus.SUBMITTED,
        occurred_at=NOW,
    )

    with pytest.raises(ValidationError, match="positive fill basis"):
        report.model_copy(update={"status": OrderStatus.FILLED})


def test_deep_model_copy_reconstructs_a_distinct_deeply_frozen_model():
    proposal = TradeProposal(
        **proposal_data(metadata={"audit": {"sources": ["strategy"]}})
    )

    copied = proposal.model_copy(deep=True)

    assert copied == proposal
    assert copied is not proposal
    assert copied.metadata is not proposal.metadata
    assert copied.metadata["audit"] is not proposal.metadata["audit"]
    with pytest.raises(TypeError):
        copied.metadata["audit"]["sources"][0] = "adapter"


def test_default_metadata_and_limit_snapshots_are_deeply_immutable():
    proposal = TradeProposal(**proposal_data())
    decision = RiskDecision(
        proposal_id=proposal.proposal_id,
        approved=False,
        reason_codes=("position_limit",),
        decided_at=NOW,
        limit_snapshot={"limits": {"symbols": ["SPY"]}},
    )

    with pytest.raises(TypeError):
        proposal.metadata["new"] = "value"
    with pytest.raises(TypeError):
        decision.limit_snapshot["limits"]["symbols"][0] = "QQQ"

    assert decision.model_dump()["limit_snapshot"] == {
        "limits": {"symbols": ["SPY"]}
    }
    assert json.loads(decision.model_dump_json())["limit_snapshot"] == {
        "limits": {"symbols": ["SPY"]}
    }


@pytest.mark.parametrize(
    ("approved_quantity", "approved_notional"),
    [(Decimal("1"), None), (None, Decimal("100"))],
)
def test_approved_risk_decision_requires_exactly_one_size(
    approved_quantity, approved_notional
):
    decision = RiskDecision(
        proposal_id="trend:SPY:2026-08-23T12:00:00Z",
        approved=True,
        reason_codes=("capped_to_limit",),
        approved_quantity=approved_quantity,
        approved_notional=approved_notional,
        decided_at=NOW,
    )

    assert decision.approved_quantity == approved_quantity
    assert decision.approved_notional == approved_notional


@pytest.mark.parametrize(
    ("approved_quantity", "approved_notional"),
    [(None, None), (Decimal("1"), Decimal("100"))],
)
def test_approved_risk_decision_rejects_missing_or_ambiguous_size(
    approved_quantity, approved_notional
):
    with pytest.raises(ValidationError, match="exactly one"):
        RiskDecision(
            proposal_id="trend:SPY:2026-08-23T12:00:00Z",
            approved=True,
            approved_quantity=approved_quantity,
            approved_notional=approved_notional,
            decided_at=NOW,
        )


def test_rejected_risk_decision_requires_reason_and_prohibits_approved_size():
    decision = RiskDecision(
        proposal_id="trend:SPY:2026-08-23T12:00:00Z",
        approved=False,
        reason_codes=("position_limit",),
        decided_at=NOW,
    )
    assert decision.reason_codes == ("position_limit",)

    with pytest.raises(ValidationError, match="reason code"):
        RiskDecision(
            proposal_id=decision.proposal_id,
            approved=False,
            reason_codes=(),
            decided_at=NOW,
        )
    with pytest.raises(ValidationError, match="prohibit"):
        RiskDecision(
            proposal_id=decision.proposal_id,
            approved=False,
            reason_codes=("position_limit",),
            approved_notional=Decimal("100"),
            decided_at=NOW,
        )


@pytest.mark.parametrize(
    ("quantity", "notional"),
    [(Decimal("1"), None), (None, Decimal("100"))],
)
def test_normalized_order_accepts_exactly_one_positive_size(quantity, notional):
    order = NormalizedOrder(**order_data(quantity=quantity, notional=notional))
    assert order.quantity == quantity
    assert order.notional == notional


@pytest.mark.parametrize(
    ("quantity", "notional"),
    [
        (None, None),
        (Decimal("0"), None),
        (None, Decimal("0")),
        (Decimal("1"), Decimal("100")),
    ],
)
def test_normalized_order_rejects_missing_nonpositive_or_ambiguous_size(
    quantity, notional
):
    with pytest.raises(ValidationError):
        NormalizedOrder(**order_data(quantity=quantity, notional=notional))


@pytest.mark.parametrize("status", [OrderStatus.RISK_REJECTED, OrderStatus.REJECTED])
def test_rejected_execution_report_requires_reason_and_prohibits_fills(status):
    report = ExecutionReport(
        client_order_id="order:trend:SPY:2026-08-23T12:00:00Z",
        venue=Venue.ALPACA_PAPER,
        status=status,
        rejection_reason="risk or venue rejection",
        occurred_at=NOW,
    )
    assert report.rejection_reason == "risk or venue rejection"

    with pytest.raises(ValidationError, match="rejection_reason"):
        ExecutionReport(
            client_order_id=report.client_order_id,
            venue=report.venue,
            status=status,
            occurred_at=NOW,
        )
    with pytest.raises(ValidationError, match="prohibit fills"):
        ExecutionReport(
            client_order_id=report.client_order_id,
            venue=report.venue,
            status=status,
            rejection_reason="rejected",
            filled_quantity=Decimal("1"),
            average_fill_price=Decimal("10"),
            occurred_at=NOW,
        )


def test_non_rejected_execution_report_prohibits_rejection_reason():
    with pytest.raises(ValidationError, match="prohibit rejection_reason"):
        ExecutionReport(
            client_order_id="order:trend:SPY:2026-08-23T12:00:00Z",
            venue=Venue.ALPACA_PAPER,
            status=OrderStatus.SUBMITTED,
            rejection_reason="contradictory",
            occurred_at=NOW,
        )


@pytest.mark.parametrize(
    ("status", "fill_values"),
    [
        (status, fill_values)
        for status in (
            OrderStatus.PROPOSED,
            OrderStatus.APPROVED,
            OrderStatus.SUBMITTED,
        )
        for fill_values in (
            {"filled_quantity": Decimal("1")},
            {"filled_notional": Decimal("10")},
        )
    ],
)
def test_non_fill_execution_statuses_prohibit_fill_values(status, fill_values):
    report = ExecutionReport(
        client_order_id="order:trend:SPY:2026-08-23T12:00:00Z",
        venue=Venue.ALPACA_PAPER,
        status=status,
        occurred_at=NOW,
    )
    assert report.filled_quantity == Decimal("0")
    assert report.filled_notional == Decimal("0")
    assert report.average_fill_price is None

    with pytest.raises(ValidationError, match="prohibit fills"):
        ExecutionReport(
            client_order_id=report.client_order_id,
            venue=report.venue,
            status=status,
            average_fill_price=Decimal("10"),
            occurred_at=NOW,
            **fill_values,
        )


@pytest.mark.parametrize("status", [OrderStatus.PARTIALLY_FILLED, OrderStatus.FILLED])
def test_fill_status_requires_positive_fill_basis_and_average_price(status):
    report = ExecutionReport(
        client_order_id="order:trend:SPY:2026-08-23T12:00:00Z",
        venue=Venue.ALPACA_PAPER,
        status=status,
        filled_notional=Decimal("50"),
        average_fill_price=Decimal("10"),
        occurred_at=NOW,
    )
    assert report.filled_notional == Decimal("50")

    with pytest.raises(ValidationError, match="positive fill basis"):
        ExecutionReport(
            client_order_id=report.client_order_id,
            venue=report.venue,
            status=status,
            occurred_at=NOW,
        )
    with pytest.raises(ValidationError, match="average_fill_price"):
        ExecutionReport(
            client_order_id=report.client_order_id,
            venue=report.venue,
            status=status,
            filled_quantity=Decimal("1"),
            occurred_at=NOW,
        )


def test_execution_report_rejects_average_price_without_fill_basis():
    with pytest.raises(ValidationError, match="positive fill basis"):
        ExecutionReport(
            client_order_id="order:trend:SPY:2026-08-23T12:00:00Z",
            venue=Venue.ALPACA_PAPER,
            status=OrderStatus.SUBMITTED,
            average_fill_price=Decimal("10"),
            occurred_at=NOW,
        )


def test_execution_report_allows_submitted_no_fill_and_canceled_partial_fill():
    submitted = ExecutionReport(
        client_order_id="order:trend:SPY:2026-08-23T12:00:00Z",
        venue=Venue.ALPACA_PAPER,
        status=OrderStatus.SUBMITTED,
        occurred_at=NOW,
    )
    canceled = ExecutionReport(
        client_order_id=submitted.client_order_id,
        venue=submitted.venue,
        status=OrderStatus.CANCELED,
        filled_quantity=Decimal("0.5"),
        average_fill_price=Decimal("10"),
        occurred_at=NOW,
    )

    assert submitted.average_fill_price is None
    assert canceled.filled_quantity == Decimal("0.5")
