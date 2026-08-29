"""Task 12: unified paper jobs are integrated but not enabled by default.

Two lanes are wired here. The stock/crypto lane is new and registers only behind
its own flag. The weather lane already runs; this adds a *shadow* route that
mirrors accepted proposals into the unified event ledger while the legacy Trade
row stays authoritative for the compatibility phase.

The safety properties under test are: nothing new runs unless explicitly enabled,
the weather reliability gates still decide what executes, Kalshi stays
monitor-only end to end, and no failure in the new path can take down the lane
that was already working.
"""

import ast
import asyncio
import inspect
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import sessionmaker

from backend.models.database import Base, Trade, TradingEvent, UnifiedOrder
from backend.core import scheduler as scheduler_module
from backend.core.scheduler import (
    STOCK_CRYPTO_JOB_ID,
    build_weather_paper_proposal,
    planned_scheduler_jobs,
    shadow_route_weather_proposal,
    stock_crypto_paper_job,
    stock_crypto_symbols,
    weather_upstream_evidence,
)
from backend.core.weather_signals import WeatherTradingSignal
from backend.data.weather_markets import WeatherMarket
from backend.trading.domain import AssetClass, OrderStatus, TradeProposal, Venue

NOW = datetime(2026, 8, 28, 15, 30, tzinfo=timezone.utc)
MARKET_DATA_AT = datetime(2026, 8, 28, 15, 29, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


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
        suggested_size=50.0,
        reasoning="ensemble mean is well above threshold",
        timestamp=MARKET_DATA_AT,
        ensemble_mean=83.0,
        ensemble_std=2.0,
        ensemble_members=31,
    )
    values.update(overrides)
    return WeatherTradingSignal(**values)


def make_proposal(signal=None, **kwargs) -> TradeProposal:
    proposal = build_weather_paper_proposal(
        signal if signal is not None else make_signal(),
        size=kwargs.pop("size", 50.0),
        entry_price=kwargs.pop("entry_price", 0.56),
        created_at=NOW,
    )
    assert proposal is not None
    return proposal


class _StubDecision:
    def __init__(self, approved=True, reason_codes=()):
        self.approved = approved
        self.reason_codes = tuple(reason_codes)


class _StubReport:
    def __init__(self, status=OrderStatus.FILLED, rejection_reason=""):
        self.status = status
        self.rejection_reason = rejection_reason


class _StubResult:
    """The shape PaperExecutionResult presents to the route, and nothing more."""

    def __init__(self, *, approved=True, status=OrderStatus.FILLED, reason_codes=()):
        self.decision = _StubDecision(approved, reason_codes)
        self.report = _StubReport(status)


class RecordingService:
    """Records what the lane hands the service, and answers with a fixed result.

    This can assert what goes *in* -- the proposal, the risk context, the
    idempotency key -- and nothing about what comes back out. It does not
    evaluate risk, does not write the ledger, does not resolve an adapter, and
    does not run the size reconciliation a simulated fill has to satisfy. A
    defect on the far side of that boundary is invisible here by construction,
    which is how a broken fill derivation survived five commits under a green
    suite. Anything that depends on real service behaviour belongs in the
    real-service section at the bottom of this file.
    """

    def __init__(self, *, raises=None, result=None):
        self.calls = []
        self._raises = raises
        self._result = _StubResult() if result is None else result

    def execute(self, proposal, *, portfolio, context, limits):
        self.calls.append(
            {"proposal": proposal, "portfolio": portfolio, "context": context, "limits": limits}
        )
        if self._raises is not None:
            raise self._raises
        return self._result


def a_portfolio():
    """A real PortfolioState, so risk decisions in tests are evaluated for real."""
    from backend.trading.risk import PortfolioState

    return PortfolioState(
        equity=Decimal("1000"),
        start_of_day_nlv=Decimal("1000"),
        daily_realized_pnl=Decimal("0"),
        gross_exposure=Decimal("0"),
        crypto_exposure=Decimal("0"),
    )


def enable_routing(monkeypatch, service):
    """Wire both seams the shadow route needs: a service and real account state.

    Both are required on purpose. weather_portfolio_state returns None rather
    than a placeholder when it cannot read real state, because a risk decision
    made against invented exposure would be written to an append-only audit
    ledger as though it were real.
    """
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_UNIFIED_LEDGER_ENABLED", True)
    monkeypatch.setattr(scheduler_module, "build_paper_execution_service", lambda _s: service)
    monkeypatch.setattr(scheduler_module, "weather_portfolio_state", lambda _s: a_portfolio())
    return service


@pytest.fixture
def captured_events(monkeypatch):
    events = []
    monkeypatch.setattr(
        scheduler_module,
        "log_event",
        lambda kind, message, data=None: events.append((kind, message, data or {})),
    )
    return events


# ---------------------------------------------------------------------------
# Job registration: nothing new runs unless explicitly enabled
# ---------------------------------------------------------------------------


def test_stock_crypto_lane_registers_no_job_when_disabled(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_LANE_ENABLED", False)
    assert STOCK_CRYPTO_JOB_ID not in planned_scheduler_jobs()


def test_enabling_the_lane_registers_exactly_one_bounded_job(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_LANE_ENABLED", True)
    jobs = planned_scheduler_jobs()
    assert jobs.count(STOCK_CRYPTO_JOB_ID) == 1


def test_weather_jobs_still_register_under_their_existing_flags(monkeypatch):
    """The new lane flag must not disturb the weather lane in either direction."""
    for lane_enabled in (False, True):
        monkeypatch.setattr(
            scheduler_module.settings, "STOCK_CRYPTO_LANE_ENABLED", lane_enabled
        )
        monkeypatch.setattr(scheduler_module.settings, "WEATHER_ENABLED", True)
        assert "weather_scan" in planned_scheduler_jobs()
        monkeypatch.setattr(scheduler_module.settings, "WEATHER_ENABLED", False)
        assert "weather_scan" not in planned_scheduler_jobs()


def test_btc_prediction_and_entertainment_lanes_remain_paused(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_LANE_ENABLED", True)
    monkeypatch.setattr(scheduler_module.settings, "BTC_LANE_ENABLED", False)
    jobs = planned_scheduler_jobs()
    assert "market_scan" not in jobs
    assert not [job for job in jobs if "entertainment" in job]


def test_lane_defaults_are_off_in_a_fresh_settings_object():
    from backend.config import Settings

    fresh = Settings(_env_file=None)
    assert fresh.STOCK_CRYPTO_LANE_ENABLED is False
    assert fresh.WEATHER_UNIFIED_LEDGER_ENABLED is False
    assert fresh.WEATHER_KALSHI_PAPER_EXECUTION_ENABLED is False


# ---------------------------------------------------------------------------
# Weather shadow routing
# ---------------------------------------------------------------------------


def test_accepted_weather_proposal_reaches_the_ledger_service(
    monkeypatch, captured_events, ledger_session
):
    service = enable_routing(monkeypatch, RecordingService())

    signal = make_signal()
    outcome = shadow_route_weather_proposal(
        ledger_session, signal, make_proposal(signal), now=NOW
    )

    assert outcome == "routed"
    assert len(service.calls) == 1
    routed = service.calls[0]["proposal"]
    assert routed.asset_class is AssetClass.PREDICTION_WEATHER
    assert routed.venue is Venue.POLYMARKET_PAPER


def test_routing_is_off_by_default_and_calls_nothing(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_UNIFIED_LEDGER_ENABLED", False)
    service = RecordingService()
    monkeypatch.setattr(scheduler_module, "build_paper_execution_service", lambda _s: service)

    outcome = shadow_route_weather_proposal(object(), make_signal(), make_proposal(), now=NOW)

    assert outcome == "disabled"
    assert service.calls == []


def test_a_refused_signal_reaches_neither_the_ledger_nor_an_adapter(monkeypatch):
    """The reliability gates decide, and they decide before anything is routed."""
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_UNIFIED_LEDGER_ENABLED", True)
    service = RecordingService()
    monkeypatch.setattr(scheduler_module, "build_paper_execution_service", lambda _s: service)

    refused = make_signal(no_trade_reasons=["spread 12.0% exceeds 5.0% cap"])
    assert build_weather_paper_proposal(
        refused, size=50.0, entry_price=0.56, created_at=NOW
    ) is None

    outcome = shadow_route_weather_proposal(object(), refused, None, now=NOW)
    assert outcome == "no_proposal"
    assert service.calls == []


def test_kalshi_stays_monitor_only_end_to_end(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_UNIFIED_LEDGER_ENABLED", True)
    monkeypatch.setattr(
        scheduler_module.settings, "WEATHER_KALSHI_PAPER_EXECUTION_ENABLED", False
    )
    service = RecordingService()
    monkeypatch.setattr(scheduler_module, "build_paper_execution_service", lambda _s: service)

    kalshi = make_signal("kalshi")
    assert build_weather_paper_proposal(
        kalshi, size=50.0, entry_price=0.56, created_at=NOW
    ) is None
    assert shadow_route_weather_proposal(object(), kalshi, None, now=NOW) == "no_proposal"
    assert service.calls == []


def test_upstream_approval_evidence_names_the_gate_that_approved(monkeypatch):
    """The risk layer refuses weather without evidence; the evidence must be real."""
    evidence = weather_upstream_evidence(make_signal())

    assert evidence
    assert all(type(item) is str and item.strip() for item in evidence)
    joined = " ".join(evidence)
    assert "NWS_CLI" in joined and "KNYC" in joined
    assert "polymarket" in joined


def test_a_refused_signal_yields_no_upstream_approval_evidence():
    blocked = make_signal(no_trade_reasons=["missing exact settlement source/station"])
    assert weather_upstream_evidence(blocked) == ()


def test_the_risk_context_carries_the_evidence_to_the_service(monkeypatch, ledger_session):
    service = enable_routing(monkeypatch, RecordingService())

    signal = make_signal()
    shadow_route_weather_proposal(ledger_session, signal, make_proposal(signal), now=NOW)

    context = service.calls[0]["context"]
    assert context.weather_upstream_approved is True
    assert context.weather_approval_evidence == weather_upstream_evidence(signal)
    assert context.execution_mode == "paper"


def test_the_idempotency_key_is_stable_for_one_proposal_and_distinct_across_them(
    monkeypatch, ledger_session
):
    service = enable_routing(monkeypatch, RecordingService())

    signal = make_signal()
    # Two separately constructed, equal proposals. Reusing one object would make
    # any identity-derived key look stable whether or not it actually is.
    first = make_proposal(signal)
    second = make_proposal(signal)
    assert first is not second and first.proposal_id == second.proposal_id
    shadow_route_weather_proposal(ledger_session, signal, first, now=NOW)
    shadow_route_weather_proposal(ledger_session, signal, second, now=NOW + timedelta(hours=3))
    other = make_proposal(signal, size=25.0)
    shadow_route_weather_proposal(ledger_session, signal, other, now=NOW)

    keys = [call["context"].idempotency_key for call in service.calls]
    assert keys[0] == keys[1], "the same proposal must replay under one key"
    assert keys[2] != keys[0], "a different proposal must not reuse a key"


# ---------------------------------------------------------------------------
# Failure in the new path must never take down the lane that already worked
# ---------------------------------------------------------------------------


def test_a_service_failure_is_sanitized_logged_and_swallowed(
    monkeypatch, captured_events, ledger_session
):
    secret = "sk-live-DO-NOT-LEAK-9999"
    service = enable_routing(
        monkeypatch, RecordingService(raises=RuntimeError(f"boom {secret}"))
    )

    outcome = shadow_route_weather_proposal(
        ledger_session, make_signal(), make_proposal(), now=NOW
    )

    # The service must actually have been reached, or this asserts nothing.
    assert len(service.calls) == 1
    assert outcome == "failed"
    assert any(kind in {"warning", "error"} for kind, _m, _d in captured_events)
    rendered = repr(captured_events)
    assert secret not in rendered, "adapter failure text must not be echoed verbatim"


def test_an_unavailable_service_does_not_raise(monkeypatch, captured_events):
    """Archives unbound, or any construction failure, must degrade quietly."""
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_UNIFIED_LEDGER_ENABLED", True)
    monkeypatch.setattr(scheduler_module, "build_paper_execution_service", lambda _s: None)

    assert shadow_route_weather_proposal(object(), make_signal(), make_proposal(), now=NOW) == (
        "unavailable"
    )


def test_a_service_construction_error_does_not_escape(monkeypatch, captured_events):
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_UNIFIED_LEDGER_ENABLED", True)

    def explode(_session):
        raise RuntimeError("archives unbound")

    monkeypatch.setattr(scheduler_module, "build_paper_execution_service", explode)

    assert shadow_route_weather_proposal(object(), make_signal(), make_proposal(), now=NOW) == (
        "failed"
    )


def test_shadow_routing_never_raises_for_any_outcome(monkeypatch, ledger_session):
    """Exhaustive: every branch of the shadow path returns rather than raises."""
    monkeypatch.setattr(scheduler_module, "weather_portfolio_state", lambda _s: a_portfolio())
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_UNIFIED_LEDGER_ENABLED", True)
    for service in (
        RecordingService(raises=RuntimeError("x")),
        RecordingService(raises=KeyError("x")),
        RecordingService(raises=ValueError("x")),
        # A result the route cannot read is a refusal, not a route.
        RecordingService(result="ok"),
        RecordingService(result=_StubResult(approved=False, status=OrderStatus.RISK_REJECTED)),
        RecordingService(result=_StubResult(status=OrderStatus.REJECTED)),
    ):
        monkeypatch.setattr(
            scheduler_module, "build_paper_execution_service", lambda _s, svc=service: svc
        )
        outcome = shadow_route_weather_proposal(
            ledger_session, make_signal(), make_proposal(), now=NOW
        )
        assert outcome in {"routed", "refused", "failed", "unavailable"}


# ---------------------------------------------------------------------------
# Stock/crypto lane
# ---------------------------------------------------------------------------


def test_one_run_with_no_market_data_returns_zero_proposals_successfully(
    monkeypatch, captured_events
):
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_LANE_ENABLED", True)
    monkeypatch.setattr(scheduler_module, "load_stock_crypto_bars", lambda _symbol: None)
    service = RecordingService()
    monkeypatch.setattr(scheduler_module, "build_paper_execution_service", lambda _s: service)

    asyncio.run(stock_crypto_paper_job())

    assert service.calls == []


def test_the_job_does_nothing_at_all_when_its_lane_is_disabled(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_LANE_ENABLED", False)
    called = {"bars": 0}

    def counting_provider(_symbol):
        called["bars"] += 1
        return None

    monkeypatch.setattr(scheduler_module, "load_stock_crypto_bars", counting_provider)
    asyncio.run(stock_crypto_paper_job())
    assert called["bars"] == 0


def test_a_market_data_failure_is_sanitized_and_does_not_crash_the_job(
    monkeypatch, captured_events
):
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_LANE_ENABLED", True)
    secret = "token-ABCDEF-secret"

    def failing_provider(_symbol):
        raise RuntimeError(f"upstream exploded {secret}")

    monkeypatch.setattr(scheduler_module, "load_stock_crypto_bars", failing_provider)
    monkeypatch.setattr(
        scheduler_module, "build_paper_execution_service", lambda _s: RecordingService()
    )

    asyncio.run(stock_crypto_paper_job())

    assert secret not in repr(captured_events)


def test_configured_symbols_are_parsed_and_deduplicated(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_SYMBOLS", " SPY , QQQ,SPY ,, ")
    assert stock_crypto_symbols() == ("SPY", "QQQ")


def test_repeated_invocation_cannot_duplicate_orders(monkeypatch):
    """Two runs over identical data must reuse one proposal id and one key."""
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_LANE_ENABLED", True)
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_SYMBOLS", "SPY")
    service = enable_routing(monkeypatch, RecordingService())
    monkeypatch.setattr(scheduler_module, "SessionLocal", lambda: object())
    bars = _golden_cross_bars()
    monkeypatch.setattr(scheduler_module, "load_stock_crypto_bars", lambda _s: bars)
    monkeypatch.setattr(scheduler_module, "paper_clock", lambda: _just_after(bars))

    asyncio.run(stock_crypto_paper_job())
    asyncio.run(stock_crypto_paper_job())

    assert len(service.calls) == 2, "both runs should reach the service"
    first, second = service.calls
    assert first["proposal"].proposal_id == second["proposal"].proposal_id
    assert first["context"].idempotency_key == second["context"].idempotency_key


def _golden_cross_bars():
    """The SPY payload whose fast SMA strictly crosses above the slow one."""
    import json

    fixture = Path(__file__).parent / "fixtures" / "market_bars.json"
    scenarios = json.loads(fixture.read_text(encoding="utf-8"))["scenarios"]
    payload = next(s for s in scenarios if s["name"] == "spy_golden_strict")
    return {key: value for key, value in payload.items() if key != "name"}


def _just_after(payload) -> datetime:
    """A clock reading one second after the payload's final bar."""
    last = payload["bars"][-1]["timestamp"].replace("Z", "+00:00")
    return datetime.fromisoformat(last) + timedelta(seconds=1)


# ---------------------------------------------------------------------------
# Structural constraints
# ---------------------------------------------------------------------------


def test_scheduler_makes_no_direct_broker_call():
    """Proposals reach venues only through PaperExecutionService."""
    source = Path(scheduler_module.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    called = {
        node.func.attr if isinstance(node.func, ast.Attribute) else getattr(node.func, "id", "")
        for node in ast.walk(tree)
        if isinstance(node, ast.Call)
    }
    for forbidden in ("submit_order", "cancel_order", "get_account_snapshot", "list_positions"):
        assert forbidden not in called, f"scheduler calls {forbidden} directly"


def test_the_broker_call_scan_would_catch_a_real_direct_call():
    tree = ast.parse("adapter.submit_order(order, execution_mode='paper')\n")
    called = {
        node.func.attr for node in ast.walk(tree) if isinstance(node, ast.Call)
    }
    assert "submit_order" in called


def test_shadow_routing_cannot_be_reached_without_the_flag():
    """The flag check must be the first thing the routing function does."""
    source = inspect.getsource(shadow_route_weather_proposal)
    body = ast.parse(source.lstrip()).body[0].body
    statements = [node for node in body if not isinstance(node, ast.Expr)]
    assert statements, "routing function has no executable guard"
    first = ast.dump(statements[0])
    assert "WEATHER_UNIFIED_LEDGER_ENABLED" in first


# ---------------------------------------------------------------------------
# Risk-layer configuration derived from the venue safety toggles
# ---------------------------------------------------------------------------


def test_kalshi_is_admitted_to_the_risk_allowlist_only_when_its_flag_is_on(monkeypatch):
    """The monitor-only boundary is enforced at the risk layer too, not only at
    the scheduler gate and inside the adapter."""
    monkeypatch.setattr(
        scheduler_module.settings, "WEATHER_KALSHI_PAPER_EXECUTION_ENABLED", False
    )
    assert Venue.KALSHI_PAPER not in scheduler_module.paper_allowed_venues()
    assert Venue.POLYMARKET_PAPER in scheduler_module.paper_allowed_venues()

    monkeypatch.setattr(
        scheduler_module.settings, "WEATHER_KALSHI_PAPER_EXECUTION_ENABLED", True
    )
    assert Venue.KALSHI_PAPER in scheduler_module.paper_allowed_venues()


def test_alpaca_is_admitted_only_when_the_stock_crypto_lane_is_on(monkeypatch):
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_LANE_ENABLED", False)
    assert Venue.ALPACA_PAPER not in scheduler_module.paper_allowed_venues()
    monkeypatch.setattr(scheduler_module.settings, "STOCK_CRYPTO_LANE_ENABLED", True)
    assert Venue.ALPACA_PAPER in scheduler_module.paper_allowed_venues()


@pytest.mark.parametrize(
    "configured,stock,crypto",
    [
        (("SPY", "QQQ"), {"SPY", "QQQ"}, {"BTC/USD"}),
        (("BTC/USD",), {"SPY"}, {"BTC/USD"}),
        (("SPY", "BTC/USD", "ETH/USD"), {"SPY"}, {"BTC/USD", "ETH/USD"}),
        ((), {"SPY"}, {"BTC/USD"}),
    ],
)
def test_symbol_allowlists_are_partitioned_and_never_overlap(configured, stock, crypto):
    """The risk layer rejects overlapping allowlists outright, so the split must
    be total rather than best-effort."""
    got_stock, got_crypto = scheduler_module.partition_stock_and_crypto_symbols(configured)
    assert set(got_stock) == stock
    assert set(got_crypto) == crypto
    assert not (got_stock & got_crypto)


def test_risk_limits_build_for_a_mixed_symbol_configuration(monkeypatch):
    """A crypto symbol in the configuration must not collide the two allowlists."""
    monkeypatch.setattr(
        scheduler_module.settings, "STOCK_CRYPTO_SYMBOLS", "SPY,QQQ,BTC/USD"
    )
    limits = scheduler_module.paper_risk_limits()
    assert not (limits.allowed_stock_symbols & limits.allowed_crypto_symbols)
    assert "BTC/USD" in limits.allowed_crypto_symbols
    assert "SPY" in limits.allowed_stock_symbols


# ---------------------------------------------------------------------------
# Portfolio state: refuse rather than invent
# ---------------------------------------------------------------------------


class _FakeScalarQuery:
    def __init__(self, value):
        self._value = value

    def filter(self, *_args, **_kwargs):
        return self

    def first(self):
        return self._value

    def scalar(self):
        return self._value


class _FakeSession:
    """Minimal stand-in for the pieces weather_portfolio_state actually reads.

    ``explode`` fails every query; ``explode_exposure`` fails only the exposure
    sum, which is the more dangerous case: the account read succeeds, so a naive
    implementation would report zero exposure rather than admitting it does not
    know.
    """

    def __init__(
        self, *, bankroll=1000.0, total_pnl=0.0, pending=0.0,
        explode=False, explode_exposure=False,
    ):
        self._state = type("S", (), {"bankroll": bankroll, "total_pnl": total_pnl})()
        self._pending = pending
        self._explode = explode
        self._explode_exposure = explode_exposure

    def query(self, target):
        if self._explode:
            raise RuntimeError("database unavailable")
        if target is scheduler_module.BotState:
            return _FakeScalarQuery(self._state)
        if self._explode_exposure:
            raise RuntimeError("exposure query unavailable")
        return _FakeScalarQuery(self._pending)


def test_portfolio_state_reads_real_account_values():
    portfolio = scheduler_module.weather_portfolio_state(
        _FakeSession(bankroll=2500.0, total_pnl=-40.0, pending=300.0)
    )
    assert portfolio is not None
    assert portfolio.equity == Decimal("2500.0")
    assert portfolio.daily_realized_pnl == Decimal("-40.0")
    assert portfolio.gross_exposure == Decimal("300.0")


@pytest.mark.parametrize(
    "session",
    [
        _FakeSession(explode=True),
        # Account read succeeds, exposure read fails. Reporting zero exposure
        # here would understate risk with real-looking equity attached.
        _FakeSession(explode_exposure=True),
        _FakeSession(bankroll=0.0),
        _FakeSession(bankroll=None),
        _FakeSession(pending=-10.0),
        object(),
    ],
)
def test_portfolio_state_refuses_rather_than_inventing_exposure(session):
    """A risk decision made against invented state would be written to an
    append-only audit ledger as though it were real. Returning None is the
    honest failure, and the routing path treats it as unavailable."""
    assert scheduler_module.weather_portfolio_state(session) is None


def test_unavailable_portfolio_stops_the_route_without_raising(monkeypatch, captured_events):
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_UNIFIED_LEDGER_ENABLED", True)
    service = RecordingService()
    monkeypatch.setattr(scheduler_module, "build_paper_execution_service", lambda _s: service)
    monkeypatch.setattr(scheduler_module, "weather_portfolio_state", lambda _s: None)

    assert shadow_route_weather_proposal(
        object(), make_signal(), make_proposal(), now=NOW
    ) == "unavailable"
    assert service.calls == []


def test_evidence_requires_settlement_identity_even_when_the_gate_is_silent():
    """The evidence function must stand on its own.

    In production the execution gate populates no_trade_reasons for a market with
    no settlement identity, so this signal should not occur. The evidence
    function is what the risk layer trusts, so it must refuse on its own reading
    rather than inheriting a guarantee from a caller.
    """
    anonymous = make_signal(
        market_overrides={"settlement_source": None, "settlement_station": None}
    )
    assert scheduler_module._weather_paper_execution_blockers(anonymous) == []
    assert weather_upstream_evidence(anonymous) == ()

    half = make_signal(market_overrides={"settlement_station": None})
    assert weather_upstream_evidence(half) == ()


# ---------------------------------------------------------------------------
# The same lane, driven through the real PaperExecutionService
#
# Everything above this line routes through RecordingService, which records four
# kwargs and returns a string. It cannot reject, cannot write a ledger row, and
# cannot run the size reconciliation a simulated fill has to satisfy -- so any
# defect on the far side of that boundary is invisible to it. That is not
# hypothetical: the fill derivation shipped broken for five commits underneath
# these tests, and every one of them stayed green, because none of them ever
# reached an adapter.
#
# These tests pay for the real thing: a real sqlite ledger, the real adapters,
# the real service, built by the same production constructor the scheduler uses.
# ---------------------------------------------------------------------------


@pytest.fixture
def ledger_session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'unified-scheduler.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as database_session:
        yield database_session
    engine.dispose()


def a_funded_portfolio():
    """Enough equity that the real per-order cap admits a 50-dollar weather order.

    paper_risk_limits caps a single order at 3% of equity, so the 1000-dollar
    book used by the stub tests refuses every proposal in this section on size
    before any of the behaviour under test is reached.
    """
    from backend.trading.risk import PortfolioState

    return PortfolioState(
        equity=Decimal("10000"),
        start_of_day_nlv=Decimal("10000"),
        daily_realized_pnl=Decimal("0"),
        gross_exposure=Decimal("0"),
        crypto_exposure=Decimal("0"),
    )


def route_for_real(monkeypatch):
    """Enable the shadow route without substituting the service.

    Only the account-state read is stubbed, and only because it needs a live
    broker session; the risk gate, the ledger, the adapters and the projection
    are all the production objects.
    """
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_UNIFIED_LEDGER_ENABLED", True)
    monkeypatch.setattr(
        scheduler_module, "weather_portfolio_state", lambda _s: a_funded_portfolio()
    )


def a_fresh_route(*, size=50.0, entry_price=0.56, platform="polymarket", market_id=None):
    """A signal and proposal whose market data is fresh enough for the real gate.

    The module-level fixtures are pinned to a fixed date. The real service reads
    its own clock, so anything built from them is stale on arrival -- which is
    useful for the refusal tests below and useless for the acceptance ones.
    """
    at = datetime.now(timezone.utc)
    market_overrides = {} if market_id is None else {"market_id": market_id, "slug": market_id}
    signal = make_signal(platform, market_overrides=market_overrides, timestamp=at)
    proposal = build_weather_paper_proposal(
        signal, size=size, entry_price=entry_price, created_at=at
    )
    assert proposal is not None
    return signal, proposal, at


def ledger_event_types(session) -> list[str]:
    return [
        row.event_type
        for row in session.query(TradingEvent).order_by(TradingEvent.sequence).all()
    ]


def test_the_real_service_accepts_a_fresh_weather_proposal(monkeypatch, ledger_session):
    """The acceptance path, asserted against what the ledger actually holds.

    This is the assertion that would have caught the fill defect: the reconciled
    fill has to survive the service's size check and land in the projection. With
    the pre-fix derivation the report is discarded as adapter_invalid_report and
    the terminal event is order_rejected.
    """
    route_for_real(monkeypatch)
    signal, proposal, at = a_fresh_route()

    outcome = shadow_route_weather_proposal(ledger_session, signal, proposal, now=at)

    assert outcome == "routed"
    assert ledger_event_types(ledger_session) == [
        "proposal_created",
        "risk_approved",
        "order_submitted",
        "order_acknowledged",
        "order_filled",
    ]
    order = ledger_session.query(UnifiedOrder).one()
    assert order.status == "filled"
    # The exact strings the adapter produced, not a rounded restatement of them.
    assert order.filled_quantity == "89.285714"
    assert order.filled_notional == "49.99999984"
    assert order.average_fill_price == "0.56"


def test_a_proposal_the_unified_path_refuses_is_not_reported_as_routed(
    monkeypatch, ledger_session, captured_events
):
    """A refusal is a disagreement with the legacy lane, and must be visible.

    The module fixtures are deliberately stale against the real clock, so the
    risk gate refuses. The legacy Trade row for the same signal is written and
    committed by the caller regardless, so if this returns "routed" and logs
    nothing, the two lanes have diverged in silence.
    """
    route_for_real(monkeypatch)
    signal = make_signal()
    proposal = make_proposal(signal)

    outcome = shadow_route_weather_proposal(ledger_session, signal, proposal, now=NOW)

    assert outcome != "routed"
    assert "risk_rejected" in ledger_event_types(ledger_session)
    assert ledger_session.query(UnifiedOrder).count() == 0
    assert captured_events, "a refusal that logs nothing is exactly the silent divergence"


def test_every_order_in_one_run_carries_its_own_broker_reference(
    monkeypatch, ledger_session
):
    """Three distinct orders, three distinct broker references.

    The adapter numbers orders from an instance counter, so an adapter rebuilt
    per proposal restarts it and every order in the run is stamped -000001.
    """
    route_for_real(monkeypatch)

    for index in range(3):
        signal, proposal, at = a_fresh_route(market_id=f"polymarket-nyc-high-{index}")
        assert shadow_route_weather_proposal(
            ledger_session, signal, proposal, now=at
        ) == "routed"

    orders = ledger_session.query(UnifiedOrder).all()
    assert len(orders) == 3
    references = {order.broker_order_id for order in orders}
    assert len(references) == 3, references


def test_the_production_constructor_supplies_an_archives_guard(ledger_session):
    """An unwired guard is a fail-open, and the service cannot supply its own.

    PaperExecutionService returns immediately from _require_archives when no
    guard was injected, so both of its checks are dead code unless the caller
    that builds it wires one. This is that caller.
    """
    service = scheduler_module.build_paper_execution_service(ledger_session)

    assert service is not None
    assert service._archives_guard is not None


def test_a_storage_failure_leaves_the_legacy_lane_committable(
    monkeypatch, ledger_session, captured_events
):
    """The shadow route must not be able to take down the lane it shadows.

    The route shares the caller's session, and the caller commits authoritative
    legacy Trade rows on it. If a failure inside the route leaves that session
    poisoned or leaves a partial event chain behind, the compatibility phase has
    made things worse rather than safer.
    """
    route_for_real(monkeypatch)

    legacy = Trade(
        market_ticker="polymarket-nyc-high-75f-1",
        platform="polymarket",
        market_type="weather",
        direction="yes",
        entry_price=0.56,
        size=50.0,
        timestamp=datetime.now(timezone.utc),
        settled=False,
    )
    ledger_session.add(legacy)
    ledger_session.flush()

    failures = {"remaining": 1}

    @event.listens_for(ledger_session.get_bind(), "before_cursor_execute")
    def fail_the_projection(conn, cursor, statement, parameters, context, executemany):
        lowered = statement.lower().lstrip()
        if lowered.startswith("insert") and "unified_orders" in lowered and failures["remaining"]:
            failures["remaining"] -= 1
            raise OperationalError("insert", {}, Exception("database is locked"))

    signal, proposal, at = a_fresh_route()
    outcome = shadow_route_weather_proposal(ledger_session, signal, proposal, now=at)

    assert outcome == "failed"
    assert captured_events

    # The session survives, and the legacy row the caller owns still commits.
    ledger_session.commit()
    assert ledger_session.query(Trade).count() == 1
    # No half-written unified order, and no event chain claiming one was filled.
    assert ledger_session.query(UnifiedOrder).count() == 0
    assert "order_filled" not in ledger_event_types(ledger_session)


def test_the_service_is_not_retained_after_its_session_ends(tmp_path):
    """A per-session cache must not outlive the sessions it is keyed on.

    The scheduler jobs open a fresh session every tick and run for as long as the
    process does, so anything the cache keeps is kept forever: the session and
    its identity map, the service, both adapters with their report and
    fingerprint caches, and the replay caches. A weak *key* does not buy this on
    its own -- if the stored value references the session, the entry pins its own
    key and the weak reference can never fire.
    """
    import gc
    import weakref

    engine = create_engine(f"sqlite:///{tmp_path / 'retention.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    witnesses = []
    for _ in range(3):
        session = factory()
        service = scheduler_module.build_paper_execution_service(session)
        assert service is not None
        witnesses.append(weakref.ref(session))
        session.close()
        del session, service

    gc.collect()
    gc.collect()

    assert [witness() for witness in witnesses] == [None, None, None]
    engine.dispose()


def test_each_session_gets_its_own_service(tmp_path):
    """Sharing one service across sessions would write one session's ledger
    through another's transaction."""
    engine = create_engine(f"sqlite:///{tmp_path / 'per-session.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)

    with factory() as first, factory() as second:
        service_one = scheduler_module.build_paper_execution_service(first)
        service_two = scheduler_module.build_paper_execution_service(second)

        assert service_one is not None and service_two is not None
        assert service_one is not service_two
        # ...and the same session keeps getting the same one.
        assert scheduler_module.build_paper_execution_service(first) is service_one

    engine.dispose()
