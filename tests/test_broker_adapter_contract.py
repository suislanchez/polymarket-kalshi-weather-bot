"""Contract tests for the deterministic, credential-free paper broker adapter."""

from __future__ import annotations

import ast
import inspect
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from typing import Protocol

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


def test_constructor_rejects_position_from_another_venue_without_clock():
    clock = CountingClock()
    with pytest.raises(BrokerAdapterError, match="fixture venue"):
        FakePaperAdapter(clock=clock, positions=[make_position(venue=Venue.KALSHI_PAPER)])
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


def test_adapter_sources_have_no_external_or_credential_machinery():
    root = Path(__file__).parents[1]
    adapter_files = sorted((root / "backend" / "trading" / "adapters").glob("*.py"))
    assert [path.name for path in adapter_files] == ["__init__.py", "base.py", "fake.py"]
    forbidden_import_roots = {
        "aiohttp", "alpaca", "boto3", "database", "db", "dotenv", "httpx", "os",
        "psycopg", "requests", "secrets", "socket", "sqlalchemy", "urllib",
    }
    forbidden_calls = {"getenv", "environ", "open", "urlopen"}
    for path in adapter_files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                assert all(alias.name.split(".")[0] not in forbidden_import_roots for alias in node.names)
            if isinstance(node, ast.ImportFrom) and node.module:
                assert node.module.split(".")[0] not in forbidden_import_roots
            if isinstance(node, ast.Call):
                called = node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
                assert called not in forbidden_calls


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
