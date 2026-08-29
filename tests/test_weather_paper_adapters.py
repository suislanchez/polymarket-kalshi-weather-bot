"""Task 11: weather simulation preserved behind the normalized adapter contract.

These are preservation tests. The legacy weather paper path stays authoritative;
this suite proves the normalized translation refuses everything the legacy gates
refuse, and that the two prediction venues are credential-free simulations with
no order-signing or CLOB surface.
"""

import ast
import inspect
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, Inexact, Rounded, localcontext
from pathlib import Path

import pytest

from backend.config import settings
from backend.core.scheduler import (
    WEATHER_STRATEGY_ID,
    build_weather_paper_proposal,
    weather_paper_venue,
)
from backend.core.weather_methodology import WeatherGateInput, evaluate_weather_trade_gate
from backend.core.weather_signals import WeatherTradingSignal
from backend.data.weather_markets import WeatherMarket
from backend.trading.adapters.base import (
    BrokerAdapter,
    BrokerAdapterError,
    DuplicateClientOrderIdError,
    OrderNotCancelableError,
    OrderNotFoundError,
)
from backend.trading.adapters.kalshi_paper import KalshiPaperAdapter
from backend.trading.adapters.polymarket_paper import PolymarketPaperAdapter
from backend.trading.domain import (
    AssetClass,
    NormalizedOrder,
    OrderStatus,
    OrderType,
    Side,
    TradeProposal,
    Venue,
)
from backend.trading.execution_mode import ExecutionModeError

CLOCK_TIME = datetime(2026, 8, 28, 15, 30, tzinfo=timezone.utc)
MARKET_DATA_TIME = datetime(2026, 8, 28, 15, 29, tzinfo=timezone.utc)


def clock():
    return CLOCK_TIME


def make_market(platform: str = "polymarket", **overrides) -> WeatherMarket:
    values = dict(
        slug=f"{platform}-nyc-high-75f",
        market_id=f"{platform}-nyc-high-75f-1",
        platform=platform,
        title="Will the high temperature in New York exceed 75F?",
        city_key="nyc",
        city_name="New York City",
        target_date=date(2026, 8, 29),
        threshold_f=75.0,
        metric="high",
        direction="above",
        yes_price=0.55,
        no_price=0.45,
        volume=5000.0,
        best_bid=0.54,
        best_ask=0.56,
        top_ask_size=500.0,
        no_best_bid=0.44,
        no_best_ask=0.46,
        no_top_ask_size=400.0,
        yes_last_price=0.55,
        settlement_source="NWS_CLI",
        settlement_station="KNYC",
    )
    values.update(overrides)
    return WeatherMarket(**values)


def make_signal(platform: str = "polymarket", **overrides) -> WeatherTradingSignal:
    market_overrides = overrides.pop("market_overrides", {})
    values = dict(
        market=make_market(platform, **market_overrides),
        model_probability=0.72,
        market_probability=0.56,
        edge=0.16,
        direction="yes",
        confidence=0.8,
        kelly_fraction=0.05,
        suggested_size=50.0,
        sources=["gfs", "ecmwf"],
        reasoning="ensemble mean is well above threshold",
        timestamp=MARKET_DATA_TIME,
        ensemble_mean=83.0,
        ensemble_std=2.0,
        ensemble_members=31,
        bucket_set_probability_mass=None,
        bucket_set_sanity_passed=False,
        bucket_set_size=0,
    )
    values.update(overrides)
    return WeatherTradingSignal(**values)


def build_proposal(signal, *, size=50.0, entry_price=0.56):
    return build_weather_paper_proposal(
        signal, size=size, entry_price=entry_price, created_at=CLOCK_TIME
    )


def order_from(proposal: TradeProposal, *, client_order_id="wx-client-1") -> NormalizedOrder:
    """Mirror how PaperExecutionService normalizes an approved proposal."""
    return NormalizedOrder(
        client_order_id=client_order_id,
        proposal_id=proposal.proposal_id,
        venue=proposal.venue,
        asset_class=proposal.asset_class,
        symbol=proposal.symbol,
        side=proposal.side,
        status=OrderStatus.APPROVED,
        quantity=proposal.quantity,
        notional=proposal.notional,
        order_type=proposal.order_type,
        limit_price=proposal.limit_price,
        created_at=proposal.created_at,
        metadata=proposal.metadata,
    )


# ---------------------------------------------------------------------------
# Normalized translation of existing weather proposals
# ---------------------------------------------------------------------------


def test_polymarket_weather_proposal_maps_into_the_normalized_contract():
    proposal = build_proposal(make_signal("polymarket"))

    assert type(proposal) is TradeProposal
    assert proposal.venue is Venue.POLYMARKET_PAPER
    assert proposal.asset_class is AssetClass.PREDICTION_WEATHER
    assert proposal.side is Side.BUY
    assert proposal.order_type is OrderType.LIMIT
    assert proposal.symbol == "polymarket-nyc-high-75f-1:yes"
    assert proposal.notional == Decimal("50")
    assert proposal.quantity is None
    assert proposal.limit_price == Decimal("0.56")
    assert proposal.reference_price == Decimal("0.56")
    assert proposal.strategy_id == WEATHER_STRATEGY_ID
    assert proposal.market_data_at == MARKET_DATA_TIME
    assert proposal.created_at == CLOCK_TIME
    assert proposal.metadata["market_id"] == "polymarket-nyc-high-75f-1"
    assert proposal.metadata["platform"] == "polymarket"
    assert proposal.metadata["outcome"] == "yes"
    assert proposal.metadata["city_key"] == "nyc"
    assert proposal.metadata["threshold_f"] == 75.0
    assert proposal.metadata["settlement_station"] == "KNYC"


def test_kalshi_weather_proposal_maps_into_the_normalized_contract(monkeypatch):
    monkeypatch.setattr(settings, "WEATHER_KALSHI_PAPER_EXECUTION_ENABLED", True)
    proposal = build_proposal(make_signal("kalshi"))

    assert proposal.venue is Venue.KALSHI_PAPER
    assert proposal.asset_class is AssetClass.PREDICTION_WEATHER
    assert proposal.metadata["platform"] == "kalshi"
    assert proposal.symbol == "kalshi-nyc-high-75f-1:yes"


def test_no_direction_buys_the_no_leg_at_its_own_price():
    proposal = build_proposal(make_signal(direction="no"), entry_price=0.46)

    assert proposal.side is Side.BUY
    assert proposal.symbol == "polymarket-nyc-high-75f-1:no"
    assert proposal.metadata["outcome"] == "no"
    assert proposal.limit_price == Decimal("0.46")


def test_weather_paper_venue_maps_only_known_platforms():
    assert weather_paper_venue("polymarket") is Venue.POLYMARKET_PAPER
    assert weather_paper_venue("Kalshi") is Venue.KALSHI_PAPER
    assert weather_paper_venue("robinhood") is None
    assert weather_paper_venue("") is None
    assert weather_paper_venue(None) is None


def test_unknown_platform_produces_no_proposal():
    assert build_proposal(make_signal("robinhood")) is None


# ---------------------------------------------------------------------------
# proposal identity must distinguish everything that distinguishes an order
# ---------------------------------------------------------------------------


def test_proposal_id_is_deterministic_for_identical_inputs():
    first = build_proposal(make_signal())
    second = build_proposal(make_signal())
    assert first.proposal_id == second.proposal_id


@pytest.mark.parametrize(
    "kwargs",
    [
        {"size": 25.0},
        {"entry_price": 0.57},
    ],
)
def test_proposal_id_distinguishes_size_and_price(kwargs):
    baseline = build_proposal(make_signal())
    variant = build_proposal(make_signal(), **kwargs)
    assert variant.proposal_id != baseline.proposal_id


def test_proposal_id_distinguishes_outcome_market_and_venue(monkeypatch):
    monkeypatch.setattr(settings, "WEATHER_KALSHI_PAPER_EXECUTION_ENABLED", True)
    baseline = build_proposal(make_signal())
    assert build_proposal(make_signal(direction="no"), entry_price=0.46).proposal_id != baseline.proposal_id
    assert build_proposal(make_signal("kalshi")).proposal_id != baseline.proposal_id
    assert build_proposal(
        make_signal(market_overrides={"threshold_f": 80.0})
    ).proposal_id != baseline.proposal_id


# ---------------------------------------------------------------------------
# Gates remain authoritative
# ---------------------------------------------------------------------------


def test_kalshi_stays_monitor_only_while_the_flag_is_false(monkeypatch):
    monkeypatch.setattr(settings, "WEATHER_KALSHI_PAPER_EXECUTION_ENABLED", False)
    assert build_proposal(make_signal("kalshi")) is None
    # The Polymarket lane is unaffected by the Kalshi venue toggle.
    assert build_proposal(make_signal("polymarket")) is not None


@pytest.mark.parametrize(
    "reason",
    [
        "missing exact settlement source/station",
        "missing line-level bid/ask",
        "spread 12.0% exceeds 5.0% cap",
        "top ask size 10.0 below 100.0 minimum",
        "bucket market requires mutually-exclusive set sanity check before actionability",
    ],
)
def test_any_no_trade_reason_blocks_the_normalized_proposal(reason):
    assert build_proposal(make_signal(no_trade_reasons=[reason])) is None


def test_zero_or_negative_suggested_size_blocks_the_normalized_proposal():
    assert build_proposal(make_signal(suggested_size=0.0)) is None
    assert build_proposal(make_signal(suggested_size=-1.0)) is None


def test_the_real_gate_supplies_the_blocking_reason_for_a_missing_station():
    """End-to-end: the shipped gate rejects, and the translation honors it."""
    gate = evaluate_weather_trade_gate(
        WeatherGateInput(
            settlement_source=None,
            station_code=None,
            best_bid=0.54,
            best_ask=0.56,
            top_ask_size=500.0,
            ensemble_mean=83.0,
            threshold_f=75.0,
            market_probability=0.56,
        )
    )
    assert gate.allowed is False
    assert gate.reasons
    assert build_proposal(make_signal(no_trade_reasons=list(gate.reasons))) is None


def test_bucket_mass_failure_blocks_even_with_an_otherwise_clean_signal():
    signal = make_signal(
        market_overrides={"direction": "bucket", "bucket_low_f": 70.0, "bucket_high_f": 75.0},
        bucket_set_probability_mass=0.42,
        bucket_set_sanity_passed=False,
        bucket_set_size=3,
        no_trade_reasons=["bucket set probability mass 0.42 is not within tolerance of 1.0"],
    )
    assert build_proposal(signal) is None


@pytest.mark.parametrize("entry_price", [0.0, 1.0, -0.1, 1.5, float("nan"), float("inf")])
def test_prices_outside_the_open_probability_interval_produce_no_proposal(entry_price):
    assert build_proposal(make_signal(), entry_price=entry_price) is None


@pytest.mark.parametrize("size", [0.0, -5.0, float("nan"), float("inf")])
def test_nonpositive_or_nonfinite_size_produces_no_proposal(size):
    assert build_proposal(make_signal(), size=size) is None


# ---------------------------------------------------------------------------
# Simulation venues
# ---------------------------------------------------------------------------


def polymarket_adapter(**kwargs):
    return PolymarketPaperAdapter(clock=clock, **kwargs)


def kalshi_adapter(*, execution_enabled, **kwargs):
    return KalshiPaperAdapter(clock=clock, execution_enabled=execution_enabled, **kwargs)


def test_both_adapters_satisfy_the_broker_contract_and_are_paper_only():
    for adapter in (polymarket_adapter(), kalshi_adapter(execution_enabled=True)):
        assert isinstance(adapter, BrokerAdapter)
        assert adapter.paper_only is True

    assert polymarket_adapter().name == "polymarket-paper"
    assert kalshi_adapter(execution_enabled=True).name == "kalshi-paper"


def test_reports_are_labeled_simulation_and_never_carry_a_broker_venue():
    adapter = polymarket_adapter()
    report = adapter.submit_order(
        order_from(build_proposal(make_signal())), execution_mode="paper"
    )
    assert report.metadata["simulation"] is True
    assert report.metadata["adapter"] == "polymarket-paper"
    assert report.venue is Venue.POLYMARKET_PAPER


def test_simulated_fill_uses_the_limit_price_and_preserves_notional_exactly():
    proposal = build_proposal(make_signal(), size=50.0, entry_price=0.5)
    report = polymarket_adapter().submit_order(order_from(proposal), execution_mode="paper")

    assert report.status is OrderStatus.FILLED
    assert report.filled_notional == Decimal("50")
    assert report.average_fill_price == Decimal("0.5")
    assert report.filled_quantity == Decimal("100")


def test_inexact_share_counts_still_reconcile_against_the_recorded_notional():
    proposal = build_proposal(make_signal(), size=50.0, entry_price=0.56)
    report = polymarket_adapter().submit_order(order_from(proposal), execution_mode="paper")

    assert report.filled_notional == Decimal("50")
    assert report.average_fill_price == Decimal("0.56")
    # quantity * price must reproduce the notional to well within a cent.
    assert abs(report.filled_quantity * Decimal("0.56") - Decimal("50")) < Decimal("0.0001")


@pytest.mark.parametrize("precision", [1, 5, 60])
def test_simulated_fill_is_independent_of_the_ambient_decimal_context(precision):
    """Fill values must not depend on the decimal context the caller happens to have."""
    order = order_from(build_proposal(make_signal(), size=50.0, entry_price=0.56))
    with localcontext() as context:
        context.prec = 28
        normal = polymarket_adapter().submit_order(order, execution_mode="paper")
    with localcontext() as context:
        context.prec = precision
        hostile = polymarket_adapter().submit_order(order, execution_mode="paper")

    assert hostile.filled_quantity == normal.filled_quantity
    assert hostile.filled_notional == normal.filled_notional == Decimal("50")
    assert hostile.average_fill_price == normal.average_fill_price


@pytest.mark.parametrize("trap", [Inexact, Rounded])
@pytest.mark.parametrize(
    "size,entry_price,precision",
    [
        # A short price: the drift needs 2 significant digits, so only precision 1 escapes.
        (50.0, 0.56, 1),
        # A repr-17 price, which is the ordinary case rather than the exotic one:
        # WeatherMarket.best_ask is a plain float, and _exact_decimal preserves all 17
        # digits via Decimal(str(value)). Here the drift needs 17 significant digits and
        # the pre-fix expression escapes at every precision through 16.
        (5.0, 0.30000000000000004, 16),
    ],
)
def test_a_strict_ambient_context_cannot_escape_the_sanitized_error_boundary(
    trap, size, entry_price, precision
):
    """A raw decimal exception must never escape submit_order.

    The reconciliation check compares a long inexact quotient against the recorded
    notional. Unpinned, that subtraction raises decimal.Inexact straight out of
    submit_order under a caller that traps inexactness -- which is what this
    codebase does internally -- bypassing the BrokerAdapterError boundary every
    adapter failure is required to surface through.

    How wide the window is depends on the price, not on a constant: the drift's
    significant-digit count tracks the price's coefficient width. A 2-digit price
    escapes only at precision 1; a 17-digit float price escapes at every precision
    through 16. Both are parametrized here because the second is the reachable one
    and an earlier version of this test, written only against the first, passed
    against the unfixed code and proved nothing.
    """
    order = order_from(build_proposal(make_signal(), size=size, entry_price=entry_price))
    with localcontext() as context:
        context.prec = precision
        context.traps[trap] = True
        report = polymarket_adapter().submit_order(order, execution_mode="paper")

    assert report.status is OrderStatus.FILLED
    assert report.filled_notional == Decimal(str(size))


def test_kalshi_monitor_only_refuses_to_simulate_a_fill(monkeypatch):
    """Defense in depth: even if the scheduler gate is opened, the venue refuses.

    The scheduler flag and the adapter flag are independent. This test opens the
    scheduler gate so a proposal exists at all, then hands it to a monitor-only
    adapter, which must still refuse to simulate a fill.
    """
    monkeypatch.setattr(settings, "WEATHER_KALSHI_PAPER_EXECUTION_ENABLED", True)
    adapter = kalshi_adapter(execution_enabled=False)
    proposal = build_proposal(make_signal("kalshi"))
    assert proposal is not None
    report = adapter.submit_order(order_from(proposal), execution_mode="paper")

    assert report.status is OrderStatus.REJECTED
    assert report.rejection_reason == "venue_monitor_only"
    assert report.filled_quantity == Decimal("0")
    assert report.filled_notional == Decimal("0")
    assert report.average_fill_price is None


def test_kalshi_execution_enabled_has_no_default():
    signature = inspect.signature(KalshiPaperAdapter)
    assert signature.parameters["execution_enabled"].default is inspect.Parameter.empty
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )


def test_adapters_refuse_a_non_paper_execution_mode():
    order = order_from(build_proposal(make_signal()))
    for mode in ("live", "LIVE", "", "paper_live"):
        with pytest.raises(ExecutionModeError):
            polymarket_adapter().submit_order(order, execution_mode=mode)


def test_adapters_refuse_orders_from_another_venue():
    """A Polymarket order handed to the Kalshi venue must be refused outright."""
    proposal = build_proposal(make_signal())
    with pytest.raises(BrokerAdapterError):
        kalshi_adapter(execution_enabled=True).submit_order(
            order_from(proposal), execution_mode="paper"
        )


def test_adapters_refuse_a_non_prediction_asset_class():
    proposal = build_proposal(make_signal())
    order = order_from(proposal).model_copy(update={"asset_class": AssetClass.STOCK})
    with pytest.raises(BrokerAdapterError):
        polymarket_adapter().submit_order(order, execution_mode="paper")


@pytest.mark.parametrize("limit_price", [None, Decimal("0.56")])
def test_adapters_refuse_market_orders_in_a_binary_book(limit_price):
    """A market order into a binary book has unbounded slippage; refuse it.

    The priced case is the one that matters: an unpriced market order is already
    caught by the limit-price check, so only a market order *carrying* a valid
    price proves the order-type check is doing any work.
    """
    proposal = build_proposal(make_signal())
    order = order_from(proposal).model_copy(
        update={"order_type": OrderType.MARKET, "limit_price": limit_price}
    )
    with pytest.raises(BrokerAdapterError):
        polymarket_adapter().submit_order(order, execution_mode="paper")


@pytest.mark.parametrize("limit_price", [Decimal("1"), Decimal("1.5"), Decimal("100")])
def test_adapters_refuse_prices_at_or_above_certainty(limit_price):
    proposal = build_proposal(make_signal())
    order = order_from(proposal).model_copy(update={"limit_price": limit_price})
    with pytest.raises(BrokerAdapterError):
        polymarket_adapter().submit_order(order, execution_mode="paper")


def test_adapters_refuse_unapproved_orders():
    proposal = build_proposal(make_signal())
    order = order_from(proposal).model_copy(update={"status": OrderStatus.PROPOSED})
    with pytest.raises(BrokerAdapterError):
        polymarket_adapter().submit_order(order, execution_mode="paper")


def test_replaying_an_identical_order_returns_the_same_report():
    adapter = polymarket_adapter()
    order = order_from(build_proposal(make_signal()))
    first = adapter.submit_order(order, execution_mode="paper")
    assert adapter.submit_order(order, execution_mode="paper") is first


def test_reusing_a_client_order_id_with_a_different_payload_is_rejected():
    adapter = polymarket_adapter()
    adapter.submit_order(order_from(build_proposal(make_signal())), execution_mode="paper")
    conflicting = order_from(build_proposal(make_signal(), size=25.0))
    with pytest.raises(DuplicateClientOrderIdError):
        adapter.submit_order(conflicting, execution_mode="paper")


def test_cancel_and_lookup_follow_the_shared_adapter_semantics():
    adapter = polymarket_adapter()
    order = order_from(build_proposal(make_signal()))
    report = adapter.submit_order(order, execution_mode="paper")

    assert adapter.get_order(order.client_order_id) is report
    assert adapter.get_order("absent") is None
    assert adapter.list_recent_orders()[0] is report
    with pytest.raises(OrderNotFoundError):
        adapter.cancel_order("absent")
    # A simulated fill is terminal, so it cannot be canceled.
    with pytest.raises(OrderNotCancelableError):
        adapter.cancel_order(order.client_order_id)


def test_simulated_fills_do_not_mutate_account_or_positions():
    adapter = polymarket_adapter()
    before = adapter.get_account_snapshot()
    adapter.submit_order(order_from(build_proposal(make_signal())), execution_mode="paper")
    after = adapter.get_account_snapshot()

    assert after.cash == before.cash
    assert after.equity == before.equity
    assert after.buying_power == before.buying_power
    assert after.positions == before.positions


def test_account_snapshots_are_stamped_from_the_injected_clock():
    assert polymarket_adapter().get_account_snapshot().captured_at == CLOCK_TIME


def test_adapter_repr_exposes_only_fixed_identity_fields():
    assert repr(polymarket_adapter()) == (
        "PolymarketPaperAdapter(name='polymarket-paper', "
        "venue='polymarket_paper', paper_only=True)"
    )
    assert repr(kalshi_adapter(execution_enabled=False)) == (
        "KalshiPaperAdapter(name='kalshi-paper', venue='kalshi_paper', "
        "paper_only=True, execution_enabled=False)"
    )


# ---------------------------------------------------------------------------
# No venue-trading surface may exist in adapter sources
# ---------------------------------------------------------------------------

ADAPTER_ROOT = Path(__file__).parents[1] / "backend" / "trading" / "adapters"
# Whole-identifier substrings that are unambiguous venue-trading machinery.
SIGNING_SUBSTRINGS = ("clob", "privatekey", "wallet", "eip712", "mnemonic", "keccak", "web3")
# Underscore-separated parts that mean order signing. Deliberately exact: "signal"
# and "assign" are ordinary words, and matching them would make this guard noise.
SIGNING_PARTS = frozenset({"sign", "signed", "signing", "signature", "signer", "presign"})


def declared_identifiers(source: str) -> set[str]:
    """Identifiers the module actually defines or touches, excluding literals.

    String constants are deliberately excluded: a denial list naming
    ``secret_key`` is protective, not a signing surface.
    """
    names: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
        elif isinstance(node, ast.Attribute):
            names.add(node.attr)
        elif isinstance(node, ast.Name):
            names.add(node.id)
        elif isinstance(node, ast.arg):
            names.add(node.arg)
    return names


def signing_violations(source: str) -> list[str]:
    violations = []
    for name in declared_identifiers(source):
        lowered = name.lower()
        squashed = lowered.replace("_", "")
        parts = set(lowered.split("_"))
        if any(term in squashed for term in SIGNING_SUBSTRINGS) or parts & SIGNING_PARTS:
            violations.append(name)
    return sorted(violations)


def test_the_identifier_scan_would_catch_a_real_signing_surface():
    """Guard the guard: this scan must fail on code that signs orders."""
    assert signing_violations(
        "class C:\n    def _sign_order(self, payload):\n        return payload\n"
    ) == ["_sign_order"]
    assert signing_violations("def build_clob_request():\n    return None\n") == [
        "build_clob_request"
    ]
    # ...and it must not fire on a protective string constant or ordinary words.
    assert signing_violations('_DENIED = {"private_key", "clob_signature"}\n') == []
    assert signing_violations(
        "for signal in traps:\n    assigned = signal\n"
    ) == []


def test_no_adapter_declares_a_clob_or_order_signing_surface():
    for path in sorted(ADAPTER_ROOT.glob("*.py")):
        violations = signing_violations(path.read_text(encoding="utf-8"))
        assert violations == [], f"{path.name}: {violations}"


# Same rule as the signing guard: identifiers only. A module whose denial list
# names "api_key" is protecting against credentials, not reaching for them.
NETWORK_SUBSTRINGS = (
    "http",
    "requests",
    "websocket",
    "urlopen",
    "urllib",
    "socket",
    "apikey",
    "apisecret",
    "environ",
    "getenv",
)


def network_violations(source: str) -> list[str]:
    return sorted(
        name
        for name in declared_identifiers(source)
        if any(term in name.lower().replace("_", "") for term in NETWORK_SUBSTRINGS)
    )


def test_the_network_scan_would_catch_a_real_venue_client():
    assert network_violations("import requests\nr = requests.get(url)\n") == ["requests"]
    assert network_violations("key = os.environ['API_KEY']\n") == ["environ"]
    assert network_violations('_DENIED = {"api_key", "api_secret"}\n') == []


def test_prediction_adapters_declare_no_network_or_credential_dependency():
    for name in ("polymarket_paper.py", "kalshi_paper.py", "prediction_paper.py"):
        source = (ADAPTER_ROOT / name).read_text(encoding="utf-8")
        assert network_violations(source) == [], name


# ---------------------------------------------------------------------------
# The legacy weather path is untouched
# ---------------------------------------------------------------------------


def test_legacy_execution_blockers_are_the_single_source_of_refusal():
    """The normalized translation must not weaken or duplicate the legacy gate."""
    from backend.core.scheduler import _weather_paper_execution_blockers

    blocked = make_signal(no_trade_reasons=["spread 12.0% exceeds 5.0% cap"])
    assert _weather_paper_execution_blockers(blocked)
    assert build_proposal(blocked) is None

    clean = make_signal()
    assert _weather_paper_execution_blockers(clean) == []
    assert build_proposal(clean) is not None


def test_translation_is_pure_and_touches_no_database_or_ledger():
    """Task 11 preserves behavior; ledger routing is Task 12's integration lane."""
    source = inspect.getsource(build_weather_paper_proposal)
    for term in ("SessionLocal", "db.", "Trade(", "commit", "PaperExecutionService"):
        assert term not in source, f"translation must not reach for {term}"


def test_a_naive_signal_timestamp_is_read_as_utc():
    naive = datetime(2026, 8, 28, 15, 29)
    proposal = build_proposal(make_signal(timestamp=naive))
    assert proposal.market_data_at == MARKET_DATA_TIME


def test_a_signal_timestamp_in_another_zone_is_converted_not_relabeled():
    eastern = timezone(timedelta(hours=-4))
    proposal = build_proposal(
        make_signal(timestamp=datetime(2026, 8, 28, 11, 29, tzinfo=eastern))
    )
    assert proposal.market_data_at == MARKET_DATA_TIME
