"""Contract tests for the deterministic, credential-free paper broker adapter."""

from __future__ import annotations

import ast
import inspect
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal, DecimalException, localcontext
from pathlib import Path
from typing import ClassVar, Protocol

import pytest

from backend.trading.adapters import (
    BrokerAdapter,
    BrokerAdapterError,
    DuplicateClientOrderIdError,
    FakeOrderScenario,
    FakePaperAdapter,
    OrderNotCancelableError,
    OrderNotFoundError,
)
from backend.trading.domain import (
    AccountSnapshot,
    AssetClass,
    ExecutionReport,
    NormalizedOrder,
    OrderStatus,
    OrderType,
    PositionSnapshot,
    Side,
    Venue,
)
from backend.trading.execution_mode import ExecutionModeError


NOW = datetime(2026, 8, 24, 12, 0, tzinfo=timezone.utc)
ORDINARY_REPORT_METADATA = {"adapter": "fake-paper", "simulation": True}


class CountingClock:
    def __init__(self) -> None:
        self.calls = 0

    def __call__(self) -> datetime:
        result = NOW + timedelta(seconds=self.calls)
        self.calls += 1
        return result


class SentinelClock:
    def __init__(self, result=None, *, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.result


class StatefulUtc(tzinfo):
    def __init__(self, sentinel: str) -> None:
        self.sentinel = sentinel
        self.calls = 0

    def utcoffset(self, dt):
        self.calls += 1
        if self.calls == 1:
            return timedelta(0)
        raise RuntimeError(self.sentinel)

    def dst(self, dt):
        return timedelta(0)


def order_data(**overrides):
    data = {
        "client_order_id": "client-1",
        "proposal_id": "proposal-1",
        "venue": Venue.ALPACA_PAPER,
        "asset_class": AssetClass.STOCK,
        "symbol": "SPY",
        "side": Side.BUY,
        "quantity": Decimal("4"),
        "status": OrderStatus.APPROVED,
        "created_at": NOW,
        "metadata": {"strategy": "fixed"},
    }
    data.update(overrides)
    return data


def make_order(**overrides) -> NormalizedOrder:
    return NormalizedOrder(**order_data(**overrides))


def make_position(**overrides) -> PositionSnapshot:
    data = {
        "venue": Venue.ALPACA_PAPER,
        "asset_class": AssetClass.STOCK,
        "symbol": "SPY",
        "quantity": Decimal("2"),
        "cost_basis": Decimal("190"),
        "market_value": Decimal("200"),
        "average_entry_price": Decimal("95"),
        "current_price": Decimal("100"),
        "realized_pnl": Decimal("3"),
        "unrealized_pnl": Decimal("10"),
        "captured_at": NOW - timedelta(days=1),
        "metadata": {"fixture": "position"},
    }
    data.update(overrides)
    return PositionSnapshot(**data)


def make_adapter(clock: CountingClock | None = None, **kwargs) -> FakePaperAdapter:
    return FakePaperAdapter(clock=clock or CountingClock(), **kwargs)


def submit(adapter: FakePaperAdapter, order: NormalizedOrder | None = None):
    return adapter.submit_order(order or make_order(), execution_mode="paper")


def test_broker_adapter_is_a_genuine_runtime_protocol():
    assert issubclass(BrokerAdapter, Protocol)
    assert BrokerAdapter.__dict__["_is_protocol"] is True
    assert BrokerAdapter.__dict__["_is_runtime_protocol"] is True
    assert isinstance(make_adapter(), BrokerAdapter)


def test_adapter_identity_is_fixed_and_paper_only():
    adapter = make_adapter()
    assert adapter.name == "fake-paper"
    assert adapter.paper_only is True


def test_adapter_error_hierarchy_is_fixed():
    assert issubclass(BrokerAdapterError, RuntimeError)
    assert issubclass(DuplicateClientOrderIdError, BrokerAdapterError)
    assert issubclass(OrderNotFoundError, BrokerAdapterError)
    assert issubclass(OrderNotCancelableError, BrokerAdapterError)


def test_account_snapshot_uses_one_operational_clock_value():
    clock = CountingClock()
    account = make_adapter(clock, positions=[make_position()]).get_account_snapshot()
    assert isinstance(account, AccountSnapshot)
    assert account.captured_at == NOW
    assert account.positions[0].captured_at == NOW
    assert clock.calls == 1


def test_account_snapshot_balances_are_exact_decimals():
    account = make_adapter(
        cash=Decimal("123.45"),
        equity=Decimal("456.78"),
        buying_power=Decimal("100.01"),
    ).get_account_snapshot()
    assert account.cash == Decimal("123.45")
    assert account.equity == Decimal("456.78")
    assert account.buying_power == Decimal("100.01")
    assert all(isinstance(value, Decimal) for value in (account.cash, account.equity, account.buying_power))


def test_constructor_balance_validation_does_not_consume_clock():
    clock = CountingClock()
    with pytest.raises(ValueError):
        FakePaperAdapter(clock=clock, equity=Decimal("0"))
    assert clock.calls == 0


def test_account_and_position_methods_share_logical_fixture_positions():
    clock = CountingClock()
    adapter = make_adapter(clock, positions=[make_position()])
    account_positions = adapter.get_account_snapshot().positions
    listed_positions = adapter.list_positions()
    assert account_positions[0].model_copy(update={"captured_at": listed_positions[0].captured_at}) == listed_positions[0]
    assert clock.calls == 2


def test_returned_snapshots_are_immutable_and_detached():
    caller_metadata = {"fixture": "position"}
    source = make_position(metadata=caller_metadata)
    adapter = make_adapter(positions=[source])
    listed = adapter.list_positions()
    caller_metadata["fixture"] = "mutated"
    with pytest.raises(Exception):
        listed[0].symbol = "QQQ"
    assert listed[0].metadata == {"fixture": "position"}
    assert listed[0] is not source


def test_constructor_copies_position_container():
    positions = [make_position()]
    adapter = make_adapter(positions=positions)
    positions.clear()
    assert len(adapter.list_positions()) == 1


@pytest.mark.parametrize("hostile", [False, True])
def test_constructor_rejects_position_snapshot_subclasses_before_virtual_copy(hostile):
    sentinel = "position-model-copy-sentinel"

    class BenignPosition(PositionSnapshot):
        pass

    class HostilePosition(PositionSnapshot):
        copy_calls: ClassVar[int] = 0

        def model_copy(self, *args, **kwargs):
            type(self).copy_calls += 1
            raise RuntimeError(sentinel)

    position_type = HostilePosition if hostile else BenignPosition
    clock = CountingClock()
    position = position_type(**make_position().model_dump())
    with pytest.raises(
        BrokerAdapterError,
        match="^positions must contain PositionSnapshot values$",
    ) as caught:
        FakePaperAdapter(clock=clock, positions=[position])
    assert str(caught.value) == "positions must contain PositionSnapshot values"
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert clock.calls == 0
    assert HostilePosition.copy_calls == 0


@pytest.mark.parametrize("malformed", [object(), 7, "SPY", None])
def test_constructor_rejects_malformed_position_fixture_types_without_clock(malformed):
    clock = CountingClock()
    with pytest.raises(
        BrokerAdapterError,
        match="^positions must contain PositionSnapshot values$",
    ) as caught:
        FakePaperAdapter(clock=clock, positions=[malformed])
    assert str(caught.value) == "positions must contain PositionSnapshot values"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert clock.calls == 0


def test_constructor_validates_all_position_types_before_copying_any_fixture(monkeypatch):
    sentinel = "mixed-position-model-copy-sentinel"

    class HostilePosition(PositionSnapshot):
        copy_calls: ClassVar[int] = 0

        def model_copy(self, *args, **kwargs):
            type(self).copy_calls += 1
            raise RuntimeError(sentinel)

    exact_position = make_position()
    hostile_position = HostilePosition(**make_position().model_dump())
    original_model_copy = PositionSnapshot.model_copy
    exact_copy_calls = 0

    def counting_model_copy(self, *args, **kwargs):
        nonlocal exact_copy_calls
        exact_copy_calls += 1
        return original_model_copy(self, *args, **kwargs)

    monkeypatch.setattr(PositionSnapshot, "model_copy", counting_model_copy)
    clock = CountingClock()
    with pytest.raises(
        BrokerAdapterError,
        match="^positions must contain PositionSnapshot values$",
    ) as caught:
        FakePaperAdapter(clock=clock, positions=[exact_position, hostile_position])
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert exact_copy_calls == 0
    assert HostilePosition.copy_calls == 0
    assert clock.calls == 0


def test_exact_position_fixtures_are_detached_and_recaptured_as_exact_snapshots():
    caller_metadata = {"fixture": {"source": "caller"}}
    source = make_position(metadata=caller_metadata)
    positions = [source]
    clock = CountingClock()
    adapter = make_adapter(clock, positions=positions)

    positions.clear()
    caller_metadata["fixture"]["source"] = "mutated"
    listed = adapter.list_positions()
    account = adapter.get_account_snapshot()

    assert type(listed[0]) is PositionSnapshot
    assert type(account.positions[0]) is PositionSnapshot
    assert listed[0] is not source
    assert account.positions[0] is not source
    assert listed[0] is not account.positions[0]
    assert listed[0].metadata == {"fixture": {"source": "caller"}}
    assert account.positions[0].metadata == {"fixture": {"source": "caller"}}
    assert listed[0].venue is Venue.ALPACA_PAPER
    assert account.positions[0].venue is Venue.ALPACA_PAPER
    assert listed[0].captured_at == NOW
    assert account.positions[0].captured_at == NOW + timedelta(seconds=1)
    assert listed[0].captured_at != source.captured_at
    with pytest.raises(Exception):
        listed[0].symbol = "QQQ"


def test_position_fixture_copying_uses_inert_base_model_dispatch():
    tree = ast.parse(inspect.getsource(FakePaperAdapter))
    model_copy_dispatches = sorted(
        ast.unparse(node.func)
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr == "model_copy"
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id in {"position", "PositionSnapshot"}
    )
    assert model_copy_dispatches == [
        "PositionSnapshot.model_copy",
        "PositionSnapshot.model_copy",
    ]


def test_constructor_rejects_position_from_another_venue_without_clock():
    clock = CountingClock()
    with pytest.raises(BrokerAdapterError, match="fixture venue"):
        FakePaperAdapter(clock=clock, positions=[make_position(venue=Venue.KALSHI_PAPER)])
    assert clock.calls == 0


@pytest.mark.parametrize("venue", ["alpaca_paper", 1, None])
def test_constructor_rejects_non_venue_instead_of_retaining_false_green_value(venue):
    with pytest.raises(BrokerAdapterError, match="adapter venue must be a Venue"):
        FakePaperAdapter(clock=CountingClock(), venue=venue)


@pytest.mark.parametrize("venue", list(Venue))
def test_constructor_accepts_exact_venue_enum_variants(venue):
    adapter = FakePaperAdapter(clock=CountingClock(), venue=venue)

    assert f"venue='{venue.value}'" in repr(adapter)


def test_constructor_rejects_spoofed_venue_before_any_caller_behavior():
    sentinel = "spoofed-venue-boundary-sentinel"
    calls = {
        "venue_class": 0,
        "venue_eq": 0,
        "venue_repr": 0,
        "venue_attributes": 0,
        "positions": 0,
        "scenarios": 0,
    }

    class VenueImpostor:
        @property
        def __class__(self):
            calls["venue_class"] += 1
            return Venue

        def __eq__(self, other):
            calls["venue_eq"] += 1
            raise AssertionError(sentinel)

        def __repr__(self):
            calls["venue_repr"] += 1
            raise AssertionError(sentinel)

        def __getattr__(self, name):
            calls["venue_attributes"] += 1
            raise AssertionError(sentinel)

    class ExplodingPositions:
        def __iter__(self):
            calls["positions"] += 1
            raise AssertionError(sentinel)

    class ExplodingScenarios(Mapping):
        def __getitem__(self, key):
            raise AssertionError(sentinel)

        def __iter__(self):
            raise AssertionError(sentinel)

        def __len__(self):
            raise AssertionError(sentinel)

        def items(self):
            calls["scenarios"] += 1
            raise AssertionError(sentinel)

    clock = SentinelClock(error=AssertionError(sentinel))
    with pytest.raises(
        BrokerAdapterError, match="^adapter venue must be a Venue$"
    ) as caught:
        FakePaperAdapter(
            clock=clock,
            venue=VenueImpostor(),
            positions=ExplodingPositions(),
            scenarios=ExplodingScenarios(),
        )

    assert str(caught.value) == "adapter venue must be a Venue"
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert calls == {
        "venue_class": 0,
        "venue_eq": 0,
        "venue_repr": 0,
        "venue_attributes": 0,
        "positions": 0,
        "scenarios": 0,
    }
    assert clock.calls == 0


def test_constructor_rejects_raising_class_property_without_invoking_it():
    sentinel = "raising-venue-class-sentinel"
    calls = {"venue_class": 0, "positions": 0, "scenarios": 0}

    class RaisingClassVenue:
        @property
        def __class__(self):
            calls["venue_class"] += 1
            raise AssertionError(sentinel)

    class ExplodingPositions:
        def __iter__(self):
            calls["positions"] += 1
            raise AssertionError(sentinel)

    class ExplodingScenarios(Mapping):
        def __getitem__(self, key):
            raise AssertionError(sentinel)

        def __iter__(self):
            raise AssertionError(sentinel)

        def __len__(self):
            raise AssertionError(sentinel)

        def items(self):
            calls["scenarios"] += 1
            raise AssertionError(sentinel)

    clock = SentinelClock(error=AssertionError(sentinel))
    with pytest.raises(
        BrokerAdapterError, match="^adapter venue must be a Venue$"
    ) as caught:
        FakePaperAdapter(
            clock=clock,
            venue=RaisingClassVenue(),
            positions=ExplodingPositions(),
            scenarios=ExplodingScenarios(),
        )

    assert str(caught.value) == "adapter venue must be a Venue"
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert calls == {"venue_class": 0, "positions": 0, "scenarios": 0}
    assert clock.calls == 0


def test_constructor_rejects_non_venue_before_fixtures_scenarios_or_clock():
    sentinel = "venue-false-green-sentinel"

    class ExplodingPositions:
        def __iter__(self):
            raise AssertionError(sentinel)

    with pytest.raises(BrokerAdapterError, match="adapter venue must be a Venue") as caught:
        FakePaperAdapter(
            clock=SentinelClock(error=AssertionError(sentinel)),
            venue="alpaca_paper",
            positions=ExplodingPositions(),
            scenarios={1: sentinel},
        )
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)


@pytest.mark.parametrize("key", [1, "", " ", "\t\n"])
def test_constructor_rejects_malformed_scenario_keys_without_clock(key):
    clock = CountingClock()
    with pytest.raises(BrokerAdapterError, match="scenario keys must be nonblank strings"):
        FakePaperAdapter(clock=clock, scenarios={key: FakeOrderScenario()})
    assert clock.calls == 0


@pytest.mark.parametrize("hostile", [False, True])
def test_constructor_rejects_str_subclass_scenario_keys_before_retaining_state(hostile):
    sentinel = "scenario-key-subclass-sentinel"

    class BenignKey(str):
        pass

    class ExplodingKey(str):
        __hash__ = str.__hash__

        def __eq__(self, other):
            raise RuntimeError(sentinel)

    key_type = ExplodingKey if hostile else BenignKey
    clock = SentinelClock(error=AssertionError(sentinel))

    with pytest.raises(
        BrokerAdapterError, match="^scenario keys must be nonblank strings$"
    ) as caught:
        FakePaperAdapter(
            clock=clock,
            scenarios={key_type("client-1"): FakeOrderScenario()},
        )

    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert clock.calls == 0


def test_default_submission_has_deterministic_identity_and_time():
    clock = CountingClock()
    report = submit(make_adapter(clock))
    assert report == ExecutionReport(
        client_order_id="client-1",
        venue=Venue.ALPACA_PAPER,
        status=OrderStatus.SUBMITTED,
        broker_order_id="fake-paper-000001",
        occurred_at=NOW,
        metadata=ORDINARY_REPORT_METADATA,
    )
    assert clock.calls == 1


def test_identical_payload_retry_returns_exact_report_without_side_effects():
    clock = CountingClock()
    adapter = make_adapter(clock)
    order = make_order()
    first = submit(adapter, order)
    second = submit(adapter, order.model_copy(deep=True))
    assert second is first
    assert adapter.list_recent_orders() == (first,)
    assert clock.calls == 1


@pytest.mark.parametrize(
    "field,value",
    [
        ("proposal_id", "proposal-2"),
        ("symbol", "QQQ"),
        ("side", Side.SELL),
        ("quantity", Decimal("5")),
        ("created_at", NOW + timedelta(seconds=1)),
        ("metadata", {"strategy": "different"}),
    ],
)
def test_same_client_id_with_any_different_payload_conflicts_without_mutation(field, value):
    clock = CountingClock()
    adapter = make_adapter(clock)
    first = submit(adapter)
    changed = make_order(**{field: value})
    with pytest.raises(DuplicateClientOrderIdError, match="payload conflicts") as caught:
        submit(adapter, changed)
    assert "client-1" not in str(caught.value)
    assert adapter.list_recent_orders() == (first,)
    assert clock.calls == 1
    next_report = submit(adapter, make_order(client_order_id="client-2"))
    assert next_report.broker_order_id == "fake-paper-000002"


def test_unknown_order_read_returns_none():
    assert make_adapter().get_order("unknown-secret-sentinel") is None


def test_unknown_cancel_is_sanitized_and_has_no_side_effect():
    clock = CountingClock()
    adapter = make_adapter(clock)
    with pytest.raises(OrderNotFoundError) as caught:
        adapter.cancel_order("unknown-secret-sentinel")
    assert "unknown-secret-sentinel" not in str(caught.value)
    assert clock.calls == 0
    assert adapter.list_recent_orders() == ()


def test_cancel_submitted_order_transitions_once():
    clock = CountingClock()
    adapter = make_adapter(clock)
    submitted = submit(adapter)
    canceled = adapter.cancel_order("client-1")
    assert canceled.status is OrderStatus.CANCELED
    assert canceled.broker_order_id == submitted.broker_order_id
    assert canceled.occurred_at == NOW + timedelta(seconds=1)
    assert canceled.filled_quantity == Decimal("0")
    assert canceled.filled_notional == Decimal("0")
    assert clock.calls == 2


def test_cancel_partial_order_preserves_cumulative_fill():
    clock = CountingClock()
    scenario = FakeOrderScenario(
        status=OrderStatus.PARTIALLY_FILLED,
        fill_fraction=Decimal("0.25"),
        average_fill_price=Decimal("101.5"),
    )
    adapter = make_adapter(clock, scenarios={"client-1": scenario})
    partial = submit(adapter)
    canceled = adapter.cancel_order("client-1")
    assert canceled.status is OrderStatus.CANCELED
    assert canceled.filled_quantity == partial.filled_quantity
    assert canceled.filled_notional == partial.filled_notional
    assert canceled.average_fill_price == partial.average_fill_price


def test_repeated_cancel_is_idempotent_without_clock_or_order_move():
    clock = CountingClock()
    adapter = make_adapter(clock)
    submit(adapter, make_order(client_order_id="older"))
    submit(adapter, make_order(client_order_id="newer"))
    first_cancel = adapter.cancel_order("older")
    before = adapter.list_recent_orders()
    second_cancel = adapter.cancel_order("older")
    assert second_cancel is first_cancel
    assert adapter.list_recent_orders() == before
    assert clock.calls == 3


@pytest.mark.parametrize("status", [OrderStatus.FILLED, OrderStatus.REJECTED])
def test_terminal_order_is_not_cancelable_without_mutation(status):
    clock = CountingClock()
    scenario = (
        FakeOrderScenario(status=status, fill_fraction=Decimal("1"), average_fill_price=Decimal("10"))
        if status is OrderStatus.FILLED
        else FakeOrderScenario(status=status)
    )
    adapter = make_adapter(clock, scenarios={"client-1": scenario})
    terminal = submit(adapter)
    with pytest.raises(OrderNotCancelableError) as caught:
        adapter.cancel_order("client-1")
    assert "client-1" not in str(caught.value)
    assert adapter.get_order("client-1") is terminal
    assert clock.calls == 1


def test_rejected_scenario_maps_to_fixed_sanitized_report():
    report = submit(make_adapter(scenarios={"client-1": FakeOrderScenario(status=OrderStatus.REJECTED)}))
    assert report.status is OrderStatus.REJECTED
    assert report.rejection_reason == "simulated_rejection"
    assert report.broker_order_id == "fake-paper-000001"
    assert report.filled_quantity == report.filled_notional == Decimal("0")
    assert report.average_fill_price is None


@pytest.mark.parametrize(
    "fraction,expected_status,expected_quantity,expected_notional",
    [
        (Decimal("0.25"), OrderStatus.PARTIALLY_FILLED, Decimal("1.00"), Decimal("101.500")),
        (Decimal("1"), OrderStatus.FILLED, Decimal("4"), Decimal("406.0")),
    ],
)
def test_quantity_order_fill_math_is_exact(fraction, expected_status, expected_quantity, expected_notional):
    scenario = FakeOrderScenario(
        status=expected_status,
        fill_fraction=fraction,
        average_fill_price=Decimal("101.5"),
    )
    report = submit(make_adapter(scenarios={"client-1": scenario}))
    assert report.filled_quantity == expected_quantity
    assert report.filled_notional == expected_notional
    assert report.average_fill_price == Decimal("101.5")
    assert all(isinstance(value, Decimal) for value in (report.filled_quantity, report.filled_notional, report.average_fill_price))


@pytest.mark.parametrize(
    "fraction,expected_status,expected_notional,expected_quantity",
    [
        (Decimal("0.25"), OrderStatus.PARTIALLY_FILLED, Decimal("25.00"), Decimal("25.00") / Decimal("3")),
        (Decimal("1"), OrderStatus.FILLED, Decimal("100"), Decimal("100") / Decimal("3")),
    ],
)
def test_notional_order_fill_math_is_exact(fraction, expected_status, expected_notional, expected_quantity):
    scenario = FakeOrderScenario(
        status=expected_status,
        fill_fraction=fraction,
        average_fill_price=Decimal("3"),
    )
    order = make_order(quantity=None, notional=Decimal("100"))
    report = submit(make_adapter(scenarios={"client-1": scenario}), order)
    assert report.filled_notional == expected_notional
    assert report.filled_quantity == expected_quantity


def test_full_quantity_fill_preserves_more_than_28_digit_coefficient():
    quantity = Decimal("12345678901234567890123456789")
    scenario = FakeOrderScenario(
        status=OrderStatus.FILLED,
        fill_fraction=Decimal("1"),
        average_fill_price=Decimal("1"),
    )
    report = submit(
        make_adapter(scenarios={"client-1": scenario}),
        make_order(quantity=quantity),
    )
    assert report.filled_quantity.as_tuple() == quantity.as_tuple()
    assert report.filled_notional.as_tuple() == quantity.as_tuple()


def test_full_notional_fill_preserves_more_than_28_digit_coefficient():
    notional = Decimal("12345678901234567890123456789")
    scenario = FakeOrderScenario(
        status=OrderStatus.FILLED,
        fill_fraction=Decimal("1"),
        average_fill_price=Decimal("1"),
    )
    report = submit(
        make_adapter(scenarios={"client-1": scenario}),
        make_order(quantity=None, notional=notional),
    )
    assert report.filled_notional.as_tuple() == notional.as_tuple()
    assert report.filled_quantity.as_tuple() == notional.as_tuple()


def test_partial_fill_multiplication_is_exact_beyond_28_digits():
    quantity = Decimal("12345678901234567890123456789")
    fraction = Decimal("0.12345678901234567890123456789")
    price = Decimal("7")
    scenario = FakeOrderScenario(
        status=OrderStatus.PARTIALLY_FILLED,
        fill_fraction=fraction,
        average_fill_price=price,
    )
    report = submit(
        make_adapter(scenarios={"client-1": scenario}),
        make_order(quantity=quantity),
    )
    expected_quantity = Decimal(
        "1524157875323883675049535156.25361987875019051998750190521"
    )
    expected_notional = Decimal(
        "10669105127267185725346746093.77533915125133363991251333647"
    )
    assert report.filled_quantity.as_tuple() == expected_quantity.as_tuple()
    assert report.filled_notional.as_tuple() == expected_notional.as_tuple()


def test_fill_math_is_independent_of_ambient_decimal_precision():
    scenario = FakeOrderScenario(
        status=OrderStatus.FILLED,
        fill_fraction=Decimal("1"),
        average_fill_price=Decimal("3"),
    )
    order = make_order(quantity=None, notional=Decimal("100"))

    with localcontext() as context:
        context.prec = 28
        normal = submit(make_adapter(scenarios={"client-1": scenario}), order)
    with localcontext() as context:
        context.prec = 3
        low_precision = submit(
            make_adapter(scenarios={"client-1": scenario}), order
        )

    assert low_precision.filled_quantity == normal.filled_quantity
    assert low_precision.filled_notional == normal.filled_notional == Decimal("100")


@pytest.mark.parametrize(
    "value", [Decimal("NaN"), Decimal("Infinity"), Decimal("-Infinity")]
)
def test_scenario_rejects_nonfinite_decimal_with_sanitized_validation(value):
    with pytest.raises(ValueError, match="invalid fake order scenario"):
        FakeOrderScenario(
            status=OrderStatus.PARTIALLY_FILLED,
            fill_fraction=value,
            average_fill_price=Decimal("1"),
        )


@pytest.mark.parametrize(
    ("status", "kwargs"),
    [
        ("submitted", {}),
        ("rejected", {}),
        (
            "partially_filled",
            {
                "fill_fraction": Decimal("0.5"),
                "average_fill_price": Decimal("1"),
            },
        ),
        (
            "filled",
            {
                "fill_fraction": Decimal("1"),
                "average_fill_price": Decimal("1"),
            },
        ),
        ("canceled", {}),
    ],
)
def test_scenario_rejects_every_plain_string_status_with_fixed_sanitized_error(
    status, kwargs
):
    with pytest.raises(ValueError, match="^invalid fake order scenario$") as caught:
        FakeOrderScenario(status=status, **kwargs)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("status", ["unexpected", 7, None])
def test_scenario_rejects_other_non_enum_status_types_with_fixed_sanitized_error(
    status,
):
    with pytest.raises(ValueError, match="^invalid fake order scenario$") as caught:
        FakeOrderScenario(status=status)

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("hostile", [False, True])
def test_scenario_rejects_str_subclass_status_without_invoking_caller_behavior(hostile):
    sentinel = "scenario-status-subclass-sentinel"
    calls = {"eq": 0, "hash": 0, "repr": 0}

    class BenignStatus(str):
        pass

    class HostileStatus(str):
        def __eq__(self, other):
            calls["eq"] += 1
            raise AssertionError(sentinel)

        def __hash__(self):
            calls["hash"] += 1
            raise AssertionError(sentinel)

        def __repr__(self):
            calls["repr"] += 1
            raise AssertionError(sentinel)

    status_type = HostileStatus if hostile else BenignStatus
    with pytest.raises(ValueError, match="^invalid fake order scenario$") as caught:
        FakeOrderScenario(status=status_type("submitted"))

    assert calls == {"eq": 0, "hash": 0, "repr": 0}
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("hostile", [False, True])
def test_scenario_rejects_decimal_subclass_fill_fraction_before_caller_behavior(
    hostile,
):
    sentinel = "scenario-fill-fraction-subclass-sentinel"
    calls = {
        "is_finite": 0,
        "eq": 0,
        "lt": 0,
        "le": 0,
        "gt": 0,
        "ge": 0,
        "as_tuple": 0,
        "repr": 0,
    }

    class BenignDecimal(Decimal):
        pass

    class HostileDecimal(Decimal):
        def is_finite(self):
            calls["is_finite"] += 1
            raise AssertionError(sentinel)

        def __eq__(self, other):
            calls["eq"] += 1
            raise AssertionError(sentinel)

        def __lt__(self, other):
            calls["lt"] += 1
            raise AssertionError(sentinel)

        def __le__(self, other):
            calls["le"] += 1
            raise AssertionError(sentinel)

        def __gt__(self, other):
            calls["gt"] += 1
            raise AssertionError(sentinel)

        def __ge__(self, other):
            calls["ge"] += 1
            raise AssertionError(sentinel)

        def as_tuple(self):
            calls["as_tuple"] += 1
            raise AssertionError(sentinel)

        def __repr__(self):
            calls["repr"] += 1
            raise AssertionError(sentinel)

    decimal_type = HostileDecimal if hostile else BenignDecimal
    with pytest.raises(
        TypeError, match="^fill_fraction must be a Decimal$"
    ) as caught:
        FakeOrderScenario(fill_fraction=decimal_type("0"))

    assert calls == {name: 0 for name in calls}
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("hostile", [False, True])
def test_scenario_rejects_decimal_subclass_average_price_before_caller_behavior(
    hostile,
):
    sentinel = "scenario-average-price-subclass-sentinel"
    calls = {
        "is_finite": 0,
        "eq": 0,
        "lt": 0,
        "le": 0,
        "gt": 0,
        "ge": 0,
        "as_tuple": 0,
        "repr": 0,
    }

    class BenignDecimal(Decimal):
        pass

    class HostileDecimal(Decimal):
        def is_finite(self):
            calls["is_finite"] += 1
            raise AssertionError(sentinel)

        def __eq__(self, other):
            calls["eq"] += 1
            raise AssertionError(sentinel)

        def __lt__(self, other):
            calls["lt"] += 1
            raise AssertionError(sentinel)

        def __le__(self, other):
            calls["le"] += 1
            raise AssertionError(sentinel)

        def __gt__(self, other):
            calls["gt"] += 1
            raise AssertionError(sentinel)

        def __ge__(self, other):
            calls["ge"] += 1
            raise AssertionError(sentinel)

        def as_tuple(self):
            calls["as_tuple"] += 1
            raise AssertionError(sentinel)

        def __repr__(self):
            calls["repr"] += 1
            raise AssertionError(sentinel)

    decimal_type = HostileDecimal if hostile else BenignDecimal
    with pytest.raises(
        TypeError, match="^average_fill_price must be a Decimal$"
    ) as caught:
        FakeOrderScenario(
            status=OrderStatus.PARTIALLY_FILLED,
            fill_fraction=Decimal("0.5"),
            average_fill_price=decimal_type("1"),
        )

    assert calls == {name: 0 for name in calls}
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("hostile", [False, True])
def test_scenario_subclass_is_rejected_before_field_behavior(hostile):
    sentinel = "scenario-instance-subclass-sentinel"
    calls = {"is_finite": 0, "eq": 0, "repr": 0}

    class HostileDecimal(Decimal):
        def is_finite(self):
            calls["is_finite"] += 1
            raise AssertionError(sentinel)

        def __eq__(self, other):
            calls["eq"] += 1
            raise AssertionError(sentinel)

        def __repr__(self):
            calls["repr"] += 1
            raise AssertionError(sentinel)

    class ScenarioSubclass(FakeOrderScenario):
        pass

    kwargs = {"fill_fraction": HostileDecimal("0")} if hostile else {}
    with pytest.raises(ValueError, match="^invalid fake order scenario$") as caught:
        ScenarioSubclass(**kwargs)

    assert calls == {"is_finite": 0, "eq": 0, "repr": 0}
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_constructor_rejects_scenario_subclass_that_bypasses_base_validation():
    sentinel = "scenario-mapping-subclass-sentinel"
    calls = {"is_finite": 0, "eq": 0, "repr": 0}

    class HostileDecimal(Decimal):
        def is_finite(self):
            calls["is_finite"] += 1
            raise AssertionError(sentinel)

        def __eq__(self, other):
            calls["eq"] += 1
            raise AssertionError(sentinel)

        def __repr__(self):
            calls["repr"] += 1
            raise AssertionError(sentinel)

    class BypassScenario(FakeOrderScenario):
        def __post_init__(self):
            pass

    bypass = BypassScenario(fill_fraction=HostileDecimal("0"))
    valid = FakeOrderScenario(status=OrderStatus.REJECTED)
    clock = SentinelClock(error=AssertionError(sentinel))

    with pytest.raises(
        TypeError, match="^scenarios must contain FakeOrderScenario values$"
    ) as caught:
        FakePaperAdapter(
            clock=clock,
            scenarios={"valid": valid, "bypass": bypass},
        )

    assert calls == {"is_finite": 0, "eq": 0, "repr": 0}
    assert sentinel not in str(caught.value)
    assert sentinel not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert clock.calls == 0


def test_extreme_fill_arithmetic_fails_closed_without_state_mutation():
    clock = CountingClock()
    adapter = make_adapter(
        clock,
        scenarios={
            "extreme": FakeOrderScenario(
                status=OrderStatus.FILLED,
                fill_fraction=Decimal("1"),
                average_fill_price=Decimal("1E+999999"),
            )
        },
    )
    extreme = make_order(
        client_order_id="extreme",
        quantity=Decimal("1E+999999"),
    )

    try:
        with pytest.raises(BrokerAdapterError, match="fill arithmetic"):
            submit(adapter, extreme)
    except DecimalException as error:  # pragma: no cover - fail-closed regression
        pytest.fail(f"adapter leaked {type(error).__name__}")

    assert clock.calls == 0
    assert adapter.get_order("extreme") is None
    assert adapter.list_recent_orders() == ()
    assert submit(adapter).broker_order_id == "fake-paper-000001"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"status": OrderStatus.SUBMITTED, "fill_fraction": Decimal("0.1")},
        {"status": OrderStatus.SUBMITTED, "average_fill_price": Decimal("1")},
        {"status": OrderStatus.REJECTED, "fill_fraction": Decimal("0.1")},
        {"status": OrderStatus.REJECTED, "average_fill_price": Decimal("1")},
        {"status": OrderStatus.PARTIALLY_FILLED, "fill_fraction": Decimal("0") , "average_fill_price": Decimal("1")},
        {"status": OrderStatus.PARTIALLY_FILLED, "fill_fraction": Decimal("1") , "average_fill_price": Decimal("1")},
        {"status": OrderStatus.PARTIALLY_FILLED, "fill_fraction": Decimal("0.5")},
        {"status": OrderStatus.FILLED, "fill_fraction": Decimal("0.5"), "average_fill_price": Decimal("1")},
        {"status": OrderStatus.FILLED, "fill_fraction": Decimal("1")},
        {"status": OrderStatus.FILLED, "fill_fraction": Decimal("1"), "average_fill_price": Decimal("0")},
        {"status": OrderStatus.CANCELED},
    ],
)
def test_scenario_rejects_invalid_status_fraction_price_combinations(kwargs):
    with pytest.raises((TypeError, ValueError)):
        FakeOrderScenario(**kwargs)


def test_scenario_is_frozen_and_slotted():
    scenario = FakeOrderScenario()
    with pytest.raises(Exception):
        scenario.status = OrderStatus.REJECTED
    assert not hasattr(scenario, "__dict__")


def test_constructor_copies_scenario_mapping():
    scenarios = {"client-1": FakeOrderScenario(status=OrderStatus.REJECTED)}
    adapter = make_adapter(scenarios=scenarios)
    scenarios["client-1"] = FakeOrderScenario()
    assert submit(adapter).status is OrderStatus.REJECTED


def test_recent_orders_are_most_recently_transitioned_first():
    adapter = make_adapter()
    first = submit(adapter, make_order(client_order_id="first"))
    second = submit(adapter, make_order(client_order_id="second"))
    canceled_first = adapter.cancel_order("first")
    assert adapter.list_recent_orders() == (canceled_first, second)
    assert first not in adapter.list_recent_orders()


def test_recent_orders_limit_zero_is_empty():
    adapter = make_adapter()
    submit(adapter)
    assert adapter.list_recent_orders(limit=0) == ()


def test_recent_orders_positive_limit_is_applied():
    adapter = make_adapter()
    first = submit(adapter, make_order(client_order_id="first"))
    second = submit(adapter, make_order(client_order_id="second"))
    assert adapter.list_recent_orders(limit=1) == (second,)
    assert adapter.list_recent_orders(limit=10) == (second, first)


def test_recent_orders_negative_limit_is_rejected_with_fixed_text():
    with pytest.raises(ValueError, match="limit must be non-negative"):
        make_adapter().list_recent_orders(limit=-1)


@pytest.mark.parametrize("limit", [True, False, 1.0, "1", None])
def test_recent_orders_rejects_non_exact_int_limit_with_fixed_text(limit):
    with pytest.raises(TypeError, match="^limit must be an int$"):
        make_adapter().list_recent_orders(limit=limit)


@pytest.mark.parametrize("mode", ["live", "", "paper-ish", None, False])
def test_nonpaper_mode_is_rejected_before_all_observable_side_effects(mode):
    secret = "benign-unique-sentinel-value"
    clock = CountingClock()
    scenarios = {"client-1": FakeOrderScenario(status=OrderStatus.REJECTED)}
    adapter = make_adapter(clock, scenarios=scenarios)
    invalid = make_order(status=OrderStatus.PROPOSED, venue=Venue.KALSHI_PAPER, metadata={"password": secret})
    with pytest.raises(ExecutionModeError):
        adapter.submit_order(invalid, execution_mode=mode)
    assert clock.calls == 0
    assert adapter.get_order("client-1") is None
    assert adapter.list_recent_orders() == ()
    valid = submit(adapter)
    assert valid.broker_order_id == "fake-paper-000001"


def test_nonapproved_order_is_rejected_before_allocation():
    clock = CountingClock()
    adapter = make_adapter(clock)
    with pytest.raises(BrokerAdapterError, match="approved orders") as caught:
        submit(adapter, make_order(status=OrderStatus.PROPOSED, client_order_id="secret-id"))
    assert "secret-id" not in str(caught.value)
    assert clock.calls == 0
    assert submit(adapter).broker_order_id == "fake-paper-000001"


def test_clock_failure_does_not_consume_broker_id_or_store_order():
    class FailOnceClock:
        def __init__(self) -> None:
            self.calls = 0

        def __call__(self) -> datetime:
            self.calls += 1
            if self.calls == 1:
                raise RuntimeError("injected clock failure")
            return NOW

    clock = FailOnceClock()
    adapter = FakePaperAdapter(clock=clock)

    with pytest.raises(BrokerAdapterError, match="^adapter clock failed$") as caught:
        submit(adapter, make_order(client_order_id="failed"))

    assert "injected clock failure" not in str(caught.value)
    assert "injected clock failure" not in repr(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None

    assert adapter.get_order("failed") is None
    assert adapter.list_recent_orders() == ()
    assert submit(adapter, make_order(client_order_id="successful")).broker_order_id == (
        "fake-paper-000001"
    )


@pytest.mark.parametrize(
    "clock",
    [
        SentinelClock("clock-invalid-sentinel"),
        SentinelClock(datetime(2026, 8, 24, 12, 0)),
        SentinelClock(datetime(2026, 8, 24, 12, 0, tzinfo=timezone(timedelta(hours=1)))),
        SentinelClock(error=RuntimeError("clock-raising-sentinel")),
    ],
)
@pytest.mark.parametrize("operation", ["account", "positions", "submit", "cancel"])
def test_all_clock_paths_fail_sanitized_and_atomically(clock, operation):
    adapter = FakePaperAdapter(clock=clock)
    existing = None
    if operation == "cancel":
        adapter._clock = CountingClock()
        existing = submit(adapter)
        adapter._clock = clock

    with pytest.raises(BrokerAdapterError, match="^adapter clock failed$") as caught:
        if operation == "account":
            adapter.get_account_snapshot()
        elif operation == "positions":
            adapter.list_positions()
        elif operation == "submit":
            submit(adapter, make_order(client_order_id="failed"))
        else:
            adapter.cancel_order("client-1")

    exposed = f"{caught.value!s} {caught.value!r}"
    assert "sentinel" not in exposed
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    if operation == "submit":
        assert adapter.get_order("failed") is None
        adapter._clock = CountingClock()
        assert submit(adapter, make_order(client_order_id="successful")).broker_order_id == "fake-paper-000001"
    elif operation == "cancel":
        assert adapter.get_order("client-1") is existing
        assert adapter.list_recent_orders() == (existing,)
    else:
        assert adapter.list_recent_orders() == ()


@pytest.mark.parametrize("operation", ["account", "positions", "submit", "cancel"])
def test_all_clock_paths_normalize_stateful_custom_utc_to_safe_base_datetime(operation):
    sentinel = f"stateful-clock-{operation}-sentinel"
    custom_timezone = StatefulUtc(sentinel)
    clock_value = datetime(
        2026,
        8,
        24,
        12,
        34,
        56,
        789012,
        tzinfo=custom_timezone,
        fold=1,
    )
    clock = SentinelClock(clock_value)
    adapter = FakePaperAdapter(clock=clock, positions=[make_position()])

    if operation == "account":
        account = adapter.get_account_snapshot()
        returned_times = (account.captured_at, account.positions[0].captured_at)
    elif operation == "positions":
        returned_times = (adapter.list_positions()[0].captured_at,)
    elif operation == "submit":
        returned_times = (submit(adapter).occurred_at,)
    else:
        adapter._clock = CountingClock()
        submit(adapter)
        adapter._clock = clock
        returned_times = (adapter.cancel_order("client-1").occurred_at,)

    expected_fields = (2026, 8, 24, 12, 34, 56, 789012, 1)
    for returned in returned_times:
        assert type(returned) is datetime
        assert returned.tzinfo is timezone.utc
        assert (
            returned.year,
            returned.month,
            returned.day,
            returned.hour,
            returned.minute,
            returned.second,
            returned.microsecond,
            returned.fold,
        ) == expected_fields
    assert custom_timezone.calls == 1


def test_clock_rejects_datetime_subclass_with_fixed_sanitized_error():
    class CustomDatetime(datetime):
        pass

    clock = SentinelClock(CustomDatetime(2026, 8, 24, tzinfo=timezone.utc))
    adapter = FakePaperAdapter(clock=clock)

    with pytest.raises(BrokerAdapterError, match="^adapter clock failed$") as caught:
        adapter.get_account_snapshot()

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_venue_mismatch_is_rejected_before_allocation():
    clock = CountingClock()
    adapter = make_adapter(clock)
    with pytest.raises(BrokerAdapterError, match="adapter venue") as caught:
        submit(adapter, make_order(venue=Venue.KALSHI_PAPER, client_order_id="secret-id"))
    assert "secret-id" not in str(caught.value)
    assert clock.calls == 0
    assert submit(adapter).broker_order_id == "fake-paper-000001"


@pytest.mark.parametrize(
    "metadata",
    [
        {"api_key": "sentinel"},
        {"outer": {"API_SECRET": "sentinel"}},
        {"outer": [{"secret-key": "sentinel"}]},
        {"outer": {"nested": ({"access token": "sentinel"},)}},
        {"credential": "sentinel"},
        {"credentials": "sentinel"},
        {"password": "sentinel"},
    ],
)
def test_recursive_denied_metadata_key_is_rejected_without_leak_or_mutation(metadata):
    clock = CountingClock()
    adapter = make_adapter(clock)
    order = make_order(client_order_id="secret-id", metadata=metadata)
    with pytest.raises(BrokerAdapterError, match="prohibited metadata key") as caught:
        submit(adapter, order)
    assert "sentinel" not in str(caught.value)
    assert "secret-id" not in str(caught.value)
    assert clock.calls == 0
    assert adapter.list_recent_orders() == ()
    assert submit(adapter).broker_order_id == "fake-paper-000001"


REPEATED_SEPARATOR_DENIED_KEYS = [
    variant
    for prefix, suffix in (
        ("api", "key"),
        ("api", "secret"),
        ("secret", "key"),
        ("access", "token"),
    )
    for variant in (
        f"{prefix}__{suffix}",
        f"{prefix}--{suffix}",
        f"{prefix}  {suffix}",
        f"{prefix} - {suffix}",
        f"{prefix.upper()}\t--__ {suffix.title()}",
    )
] + [" PASSWORD ", "CrEdEnTiAl", "\tCREDENTIALS\n"]

WRAPPED_SEPARATOR_DENIED_KEYS = [
    "_api_key",
    "api_key_",
    "--api--key--",
    " -_ API -- KEY _- ",
    "__api__secret--",
    "--secret__key__",
    " _- ACCESS -- TOKEN -_ ",
    "__password--",
    "--credential__",
    "--credentials__",
]


@pytest.mark.parametrize("key", REPEATED_SEPARATOR_DENIED_KEYS)
def test_repeated_mixed_separator_denied_metadata_keys_fail_closed(key):
    sentinel = "repeated-separator-metadata-sentinel"
    client_order_id = "repeated-separator-client"
    clock = CountingClock()
    adapter = make_adapter(clock)
    metadata = {"outer": [{"safe": [{key: sentinel}]}]}
    order = make_order(client_order_id=client_order_id, metadata=metadata)

    with pytest.raises(
        BrokerAdapterError, match="^order contains a prohibited metadata key$"
    ) as caught:
        submit(adapter, order)

    exposed = f"{caught.value!s} {caught.value!r} {adapter!r} {adapter.__dict__!r}"
    assert sentinel not in exposed
    assert client_order_id not in exposed
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert FakePaperAdapter._contains_denied_metadata_key(
        ({"safe": {key: sentinel}},)
    )
    assert clock.calls == 0
    assert adapter.get_order(client_order_id) is None
    assert adapter.list_recent_orders() == ()
    assert submit(adapter).broker_order_id == "fake-paper-000001"


@pytest.mark.parametrize("key", WRAPPED_SEPARATOR_DENIED_KEYS)
def test_wrapped_denied_metadata_keys_fail_closed_before_allocation(key):
    sentinel = "wrapped-separator-metadata-sentinel"
    client_order_id = "wrapped-separator-client"
    clock = CountingClock()
    adapter = make_adapter(clock)
    metadata = {"outer": [{"safe": [{key: sentinel}]}]}
    order = make_order(client_order_id=client_order_id, metadata=metadata)

    with pytest.raises(
        BrokerAdapterError, match="^order contains a prohibited metadata key$"
    ) as caught:
        submit(adapter, order)

    exposed = f"{caught.value!s} {caught.value!r} {adapter!r} {adapter.__dict__!r}"
    assert sentinel not in exposed
    assert client_order_id not in exposed
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert clock.calls == 0
    assert adapter.get_order(client_order_id) is None
    assert adapter.list_recent_orders() == ()
    assert submit(adapter).broker_order_id == "fake-paper-000001"


@pytest.mark.parametrize("key", ["apikey", "my_api_key_note", "ordinary-note", "_ordinary_"])
def test_noncanonical_metadata_key_names_remain_benign(key):
    sentinel = "ordinary-metadata-sentinel"
    report = submit(make_adapter(), make_order(metadata={key: sentinel}))

    assert report.metadata == ORDINARY_REPORT_METADATA
    assert sentinel not in repr(report)


def test_benign_metadata_value_is_not_retained_or_echoed():
    sentinel = "benign-unique-sentinel-value"
    adapter = make_adapter()
    report = submit(adapter, make_order(metadata={"ordinary_note": {"nested": [sentinel]}}))
    assert report.metadata == ORDINARY_REPORT_METADATA
    assert sentinel not in repr(report)
    assert sentinel not in repr(adapter)
    assert sentinel not in repr(adapter.__dict__)


def test_safe_adapter_repr_contains_only_fixed_identity_fields():
    representation = repr(make_adapter(scenarios={"secret-id": FakeOrderScenario()}))
    assert representation == "FakePaperAdapter(name='fake-paper', venue='alpaca_paper', paper_only=True)"
    assert "secret-id" not in representation


def test_constructor_signature_is_keyword_only_and_credential_free():
    signature = inspect.signature(FakePaperAdapter)
    assert all(parameter.kind is inspect.Parameter.KEYWORD_ONLY for parameter in signature.parameters.values())
    assert set(signature.parameters) == {
        "clock", "venue", "cash", "equity", "buying_power", "positions", "scenarios"
    }
    assert signature.parameters["clock"].default is inspect.Parameter.empty
    assert signature.parameters["positions"].default == ()
    assert signature.parameters["scenarios"].default is None


ALLOWED_ADAPTER_IMPORTS = {
    "__future__",
    "typing",
    "collections.abc",
    "dataclasses",
    "datetime",
    "decimal",
    "hashlib",
    "json",
    "backend.trading.adapters.base",
    "backend.trading.adapters.fake",
    "backend.trading.domain",
    "backend.trading.execution_mode",
}
FORBIDDEN_ADAPTER_CALLS = {
    "open", "__import__", "eval", "exec", "compile", "getenv", "environ", "urlopen"
}


def adapter_source_policy_violations(source: str) -> list[str]:
    violations = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Import):
            violations.extend(
                alias.name for alias in node.names if alias.name not in ALLOWED_ADAPTER_IMPORTS
            )
        elif isinstance(node, ast.ImportFrom) and node.module:
            if node.module not in ALLOWED_ADAPTER_IMPORTS:
                violations.append(node.module)
        elif isinstance(node, ast.Call):
            called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
            if called in FORBIDDEN_ADAPTER_CALLS:
                violations.append(called)
    return violations


@pytest.mark.parametrize("module", ["http.client", "sqlite3", "subprocess"])
def test_adapter_source_policy_rejects_previously_false_green_imports(module):
    assert adapter_source_policy_violations(f"import {module}\n") == [module]


def test_adapter_sources_have_only_exact_allowed_dependencies_and_no_effect_calls():
    root = Path(__file__).parents[1]
    adapter_files = sorted((root / "backend" / "trading" / "adapters").glob("*.py"))
    assert [path.name for path in adapter_files] == ["__init__.py", "base.py", "fake.py"]
    for path in adapter_files:
        source = path.read_text(encoding="utf-8")
        assert adapter_source_policy_violations(source) == [], path


def test_get_order_and_recent_orders_return_domain_model_types():
    adapter = make_adapter()
    report = submit(adapter)
    assert isinstance(adapter.get_order("client-1"), ExecutionReport)
    assert isinstance(adapter.list_recent_orders(), tuple)
    assert adapter.list_recent_orders()[0] is report


def test_fills_do_not_mutate_accounting_or_positions():
    adapter = make_adapter(
        positions=[make_position()],
        scenarios={
            "client-1": FakeOrderScenario(
                status=OrderStatus.FILLED,
                fill_fraction=Decimal("1"),
                average_fill_price=Decimal("101.5"),
            )
        },
    )
    before = adapter.get_account_snapshot()
    submit(adapter)
    after = adapter.get_account_snapshot()
    assert before.model_copy(update={"captured_at": after.captured_at, "positions": after.positions}) == after
