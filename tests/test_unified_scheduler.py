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


class RecordingService:
    """Stands in for PaperExecutionService, recording what the lane hands it."""

    def __init__(self, *, raises=None, result="ok"):
        self.calls = []
        self._raises = raises
        self._result = result

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


def test_accepted_weather_proposal_reaches_the_ledger_service(monkeypatch, captured_events):
    service = enable_routing(monkeypatch, RecordingService())

    signal = make_signal()
    outcome = shadow_route_weather_proposal(
        object(), signal, make_proposal(signal), now=NOW
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


def test_the_risk_context_carries_the_evidence_to_the_service(monkeypatch):
    service = enable_routing(monkeypatch, RecordingService())

    signal = make_signal()
    shadow_route_weather_proposal(object(), signal, make_proposal(signal), now=NOW)

    context = service.calls[0]["context"]
    assert context.weather_upstream_approved is True
    assert context.weather_approval_evidence == weather_upstream_evidence(signal)
    assert context.execution_mode == "paper"


def test_the_idempotency_key_is_stable_for_one_proposal_and_distinct_across_them(monkeypatch):
    service = enable_routing(monkeypatch, RecordingService())

    signal = make_signal()
    # Two separately constructed, equal proposals. Reusing one object would make
    # any identity-derived key look stable whether or not it actually is.
    first = make_proposal(signal)
    second = make_proposal(signal)
    assert first is not second and first.proposal_id == second.proposal_id
    shadow_route_weather_proposal(object(), signal, first, now=NOW)
    shadow_route_weather_proposal(object(), signal, second, now=NOW + timedelta(hours=3))
    other = make_proposal(signal, size=25.0)
    shadow_route_weather_proposal(object(), signal, other, now=NOW)

    keys = [call["context"].idempotency_key for call in service.calls]
    assert keys[0] == keys[1], "the same proposal must replay under one key"
    assert keys[2] != keys[0], "a different proposal must not reuse a key"


# ---------------------------------------------------------------------------
# Failure in the new path must never take down the lane that already worked
# ---------------------------------------------------------------------------


def test_a_service_failure_is_sanitized_logged_and_swallowed(monkeypatch, captured_events):
    secret = "sk-live-DO-NOT-LEAK-9999"
    enable_routing(monkeypatch, RecordingService(raises=RuntimeError(f"boom {secret}")))

    outcome = shadow_route_weather_proposal(object(), make_signal(), make_proposal(), now=NOW)

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


def test_shadow_routing_never_raises_for_any_outcome(monkeypatch):
    """Exhaustive: every branch of the shadow path returns rather than raises."""
    monkeypatch.setattr(scheduler_module, "weather_portfolio_state", lambda _s: a_portfolio())
    monkeypatch.setattr(scheduler_module.settings, "WEATHER_UNIFIED_LEDGER_ENABLED", True)
    for service in (
        RecordingService(raises=RuntimeError("x")),
        RecordingService(raises=KeyError("x")),
        RecordingService(raises=ValueError("x")),
        RecordingService(result=None),
    ):
        monkeypatch.setattr(
            scheduler_module, "build_paper_execution_service", lambda _s, svc=service: svc
        )
        outcome = shadow_route_weather_proposal(
            object(), make_signal(), make_proposal(), now=NOW
        )
        assert outcome in {"routed", "failed", "unavailable"}


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
