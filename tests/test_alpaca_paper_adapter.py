"""Guarded Alpaca Paper adapter: endpoint safety, mapping, and redaction.

Every test injects a fake client. Nothing here performs network I/O or reads
credentials, and the adapter must refuse to construct a client at all unless the
paper endpoint and paper execution mode are both confirmed first.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from backend.trading.adapters.alpaca_paper import (
    AlpacaPaperAdapter,
    AlpacaPaperAdapterError,
)
from backend.trading.adapters.base import (
    BrokerAdapter,
    OrderNotFoundError,
)
from backend.trading.domain import (
    AssetClass,
    NormalizedOrder,
    OrderStatus,
    OrderType,
    Side,
    Venue,
)

NOW = datetime(2026, 8, 28, 15, 0, 0, tzinfo=timezone.utc)
PAPER_URL = "https://paper-api.alpaca.markets"
SECRET = "SUPER-SECRET-ALPACA-KEY"


class FakeAccount:
    def __init__(self) -> None:
        self.cash = "10000.0000"
        self.equity = "12500.5000"
        self.buying_power = "20000.0000"


class FakePosition:
    def __init__(self, symbol="SPY", asset_class="us_equity") -> None:
        self.symbol = symbol
        self.asset_class = asset_class
        self.qty = "2.0000"
        self.cost_basis = "1000.0000"
        self.market_value = "1002.5000"
        self.avg_entry_price = "500.0000"
        self.current_price = "501.2500"
        self.realized_pl = "0.0000"
        self.unrealized_pl = "2.5000"


class FakeOrder:
    def __init__(self, client_order_id="paper:proposal-1", status="filled", **kw) -> None:
        self.client_order_id = client_order_id
        self.id = kw.get("broker_id", "alpaca-order-1")
        self.status = status
        self.filled_qty = kw.get("filled_qty", "0.2000")
        self.filled_avg_price = kw.get("filled_avg_price", "501.2500")
        self.symbol = kw.get("symbol", "SPY")


class FakeClient:
    """Minimal stable broker surface the adapter is allowed to wrap."""

    def __init__(self, **kw) -> None:
        self.calls: list[tuple[str, object]] = []
        self.account = kw.get("account", FakeAccount())
        self.positions = kw.get("positions", [FakePosition()])
        self.order = kw.get("order", FakeOrder())
        self.error = kw.get("error")
        self.orders = kw.get("orders", [FakeOrder()])

    def get_account(self):
        self.calls.append(("get_account", None))
        if self.error is not None:
            raise self.error
        return self.account

    def list_positions(self):
        self.calls.append(("list_positions", None))
        if self.error is not None:
            raise self.error
        return list(self.positions)

    def submit_order(self, **payload):
        self.calls.append(("submit_order", payload))
        if self.error is not None:
            raise self.error
        return self.order

    def cancel_order_by_client_id(self, client_order_id: str):
        self.calls.append(("cancel_order_by_client_id", client_order_id))
        if self.error is not None:
            raise self.error
        return FakeOrder(client_order_id=client_order_id, status="canceled",
                         filled_qty="0.0000", filled_avg_price=None)

    def get_order_by_client_id(self, client_order_id: str):
        self.calls.append(("get_order_by_client_id", client_order_id))
        if self.error is not None:
            raise self.error
        if client_order_id != self.order.client_order_id:
            return None
        return self.order

    def list_orders(self, *, limit: int = 100):
        self.calls.append(("list_orders", limit))
        if self.error is not None:
            raise self.error
        return list(self.orders)[:limit]


def make_adapter(**kw) -> tuple[AlpacaPaperAdapter, dict]:
    created: dict = {}

    def factory(*, base_url: str, api_key: str, api_secret: str):
        created["base_url"] = base_url
        created["client"] = kw.get("client") or FakeClient(
            **{k: v for k, v in kw.items() if k in {"account", "positions", "order", "error", "orders"}}
        )
        return created["client"]

    adapter = AlpacaPaperAdapter(
        client_factory=kw.get("client_factory", factory),
        base_url=kw.get("base_url", PAPER_URL),
        execution_mode=kw.get("execution_mode", "paper"),
        api_key=kw.get("api_key", ""),
        api_secret=kw.get("api_secret", ""),
        clock=kw.get("clock", lambda: NOW),
    )
    return adapter, created


def make_order(**overrides) -> NormalizedOrder:
    values = {
        "client_order_id": "paper:proposal-1",
        "proposal_id": "proposal-1",
        "venue": Venue.ALPACA_PAPER,
        "asset_class": AssetClass.STOCK,
        "symbol": "SPY",
        "side": Side.BUY,
        "notional": Decimal("100.2500"),
        "order_type": OrderType.MARKET,
        "status": OrderStatus.APPROVED,
        "created_at": NOW,
    }
    values.update(overrides)
    return NormalizedOrder(**values)


# --- endpoint and mode safety -------------------------------------------------

def test_adapter_satisfies_the_shared_broker_contract():
    adapter, _ = make_adapter()
    assert isinstance(adapter, BrokerAdapter)
    assert adapter.paper_only is True
    assert adapter.name


@pytest.mark.parametrize(
    "hostile_url",
    [
        "https://api.alpaca.markets",
        "https://live-api.alpaca.markets",
        "http://paper-api.alpaca.markets",
        "https://paper-api.alpaca.markets.evil.com",
        "https://paper-api.alpaca.markets/",
        "https://PAPER-API.ALPACA.MARKETS",
        "",
        None,
        7,
    ],
)
def test_non_paper_endpoint_is_rejected_before_a_client_is_created(hostile_url):
    invoked: list[int] = []

    def factory(**_kw):
        invoked.append(1)
        raise AssertionError("client factory must not run for a rejected endpoint")

    with pytest.raises(AlpacaPaperAdapterError):
        AlpacaPaperAdapter(
            client_factory=factory,
            base_url=hostile_url,
            execution_mode="paper",
            api_key="",
            api_secret="",
            clock=lambda: NOW,
        )
    assert invoked == []


@pytest.mark.parametrize("mode", ["live", "Paper", "", None, 3, "paper "])
def test_non_paper_execution_mode_is_rejected_before_a_client_is_created(mode):
    invoked: list[int] = []

    def factory(**_kw):
        invoked.append(1)
        raise AssertionError("client factory must not run for a rejected mode")

    with pytest.raises(AlpacaPaperAdapterError):
        AlpacaPaperAdapter(
            client_factory=factory,
            base_url=PAPER_URL,
            execution_mode=mode,
            api_key="",
            api_secret="",
            clock=lambda: NOW,
        )
    assert invoked == []


def test_paper_endpoint_is_passed_through_to_the_factory_verbatim():
    _adapter, created = make_adapter()
    assert created["base_url"] == PAPER_URL


def test_submit_rejects_a_non_paper_execution_mode_at_call_time():
    adapter, created = make_adapter()
    with pytest.raises(AlpacaPaperAdapterError):
        adapter.submit_order(make_order(), execution_mode="live")
    assert [c for c in created["client"].calls if c[0] == "submit_order"] == []


# --- mapping ------------------------------------------------------------------

def test_account_snapshot_maps_to_exact_decimals():
    adapter, _ = make_adapter()
    snapshot = adapter.get_account_snapshot()
    assert snapshot.venue is Venue.ALPACA_PAPER
    assert snapshot.cash == Decimal("10000.0000")
    assert snapshot.equity == Decimal("12500.5000")
    assert snapshot.buying_power == Decimal("20000.0000")
    assert snapshot.captured_at == NOW


@pytest.mark.parametrize(
    "symbol,raw_class,expected",
    [
        ("SPY", "us_equity", AssetClass.STOCK),
        ("QQQ", "us_equity", AssetClass.STOCK),
        ("BTC/USD", "crypto", AssetClass.CRYPTO),
        ("ETH/USD", "crypto", AssetClass.CRYPTO),
    ],
)
def test_stock_and_crypto_positions_map_to_normalized_models(symbol, raw_class, expected):
    adapter, _ = make_adapter(positions=[FakePosition(symbol=symbol, asset_class=raw_class)])
    positions = adapter.list_positions()
    assert len(positions) == 1
    assert positions[0].symbol == symbol
    assert positions[0].asset_class is expected
    assert positions[0].quantity == Decimal("2.0000")
    assert positions[0].current_price == Decimal("501.2500")


def test_positions_are_returned_as_an_immutable_tuple():
    adapter, _ = make_adapter()
    assert type(adapter.list_positions()) is tuple


@pytest.mark.parametrize(
    "raw_status,expected",
    [
        ("new", OrderStatus.SUBMITTED),
        ("accepted", OrderStatus.SUBMITTED),
        ("partially_filled", OrderStatus.PARTIALLY_FILLED),
        ("filled", OrderStatus.FILLED),
        ("canceled", OrderStatus.CANCELED),
        ("expired", OrderStatus.CANCELED),
        ("rejected", OrderStatus.REJECTED),
    ],
)
def test_broker_statuses_map_to_normalized_statuses(raw_status, expected):
    order = FakeOrder(status=raw_status)
    if expected in {OrderStatus.SUBMITTED, OrderStatus.CANCELED, OrderStatus.REJECTED}:
        order.filled_qty = "0.0000"
        order.filled_avg_price = None
    adapter, _ = make_adapter(order=order)
    report = adapter.submit_order(make_order(), execution_mode="paper")
    assert report.status is expected


def test_unknown_broker_status_fails_closed_without_guessing():
    adapter, _ = make_adapter(order=FakeOrder(status="something_new"))
    with pytest.raises(AlpacaPaperAdapterError):
        adapter.submit_order(make_order(), execution_mode="paper")


def test_submit_passes_the_stable_client_order_id():
    adapter, created = make_adapter()
    order = make_order(client_order_id="paper:proposal-42")
    adapter.submit_order(order, execution_mode="paper")
    payload = [c for c in created["client"].calls if c[0] == "submit_order"][0][1]
    assert payload["client_order_id"] == "paper:proposal-42"
    assert payload["symbol"] == "SPY"
    assert payload["side"] == "buy"


def test_cancel_maps_to_a_canceled_report():
    adapter, _ = make_adapter()
    report = adapter.cancel_order("paper:proposal-1")
    assert report.status is OrderStatus.CANCELED
    assert report.client_order_id == "paper:proposal-1"


def test_get_order_returns_none_when_absent_and_a_report_when_present():
    adapter, _ = make_adapter()
    assert adapter.get_order("paper:absent") is None
    found = adapter.get_order("paper:proposal-1")
    assert found is not None and found.status is OrderStatus.FILLED


def test_list_recent_orders_returns_normalized_reports():
    adapter, _ = make_adapter()
    reports = adapter.list_recent_orders(limit=5)
    assert type(reports) is tuple
    assert all(r.venue is Venue.ALPACA_PAPER for r in reports)


# --- redaction ----------------------------------------------------------------

@pytest.mark.parametrize(
    "method,args",
    [
        ("get_account_snapshot", ()),
        ("list_positions", ()),
        ("cancel_order", ("paper:proposal-1",)),
        ("get_order", ("paper:proposal-1",)),
        ("list_recent_orders", ()),
    ],
)
def test_client_errors_are_sanitized_and_never_leak_credentials(method, args):
    boom = RuntimeError(f"auth failed for key={SECRET} secret={SECRET}")
    adapter, _ = make_adapter(error=boom, api_key=SECRET, api_secret=SECRET)
    with pytest.raises(AlpacaPaperAdapterError) as caught:
        getattr(adapter, method)(*args)
    rendered = f"{caught.value!r} {caught.value!s}"
    assert SECRET not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_submit_errors_are_sanitized_and_never_leak_credentials():
    boom = RuntimeError(f"rejected key={SECRET}")
    adapter, _ = make_adapter(error=boom, api_key=SECRET, api_secret=SECRET)
    with pytest.raises(AlpacaPaperAdapterError) as caught:
        adapter.submit_order(make_order(), execution_mode="paper")
    rendered = f"{caught.value!r} {caught.value!s}"
    assert SECRET not in rendered


def test_repr_and_str_never_expose_credentials():
    adapter, _ = make_adapter(api_key=SECRET, api_secret=SECRET)
    assert SECRET not in f"{adapter!r} {adapter!s}"
