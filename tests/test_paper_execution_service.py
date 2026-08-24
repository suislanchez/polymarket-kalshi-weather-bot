"""Orchestration tests for the fail-closed paper execution service."""

from __future__ import annotations

import ast
import inspect
import json
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy import create_engine

from backend.models.database import Base, TradingEvent, UnifiedOrder
from backend.trading.domain import (
    AssetClass,
    ExecutionReport,
    NormalizedOrder,
    OrderStatus,
    RiskDecision,
    Side,
    TradeProposal,
    Venue,
)
from backend.trading.ledger import LedgerStorageError, verify_event_chain
from backend.trading.risk import PortfolioState, RiskContext, RiskLimits
from backend.trading.service import (
    PaperExecutionResult,
    PaperExecutionService,
    PaperExecutionServiceError,
    PaperExecutionSettings,
)

NOW = datetime(2026, 8, 24, 14, 30, 15, 123456, tzinfo=timezone.utc)


@pytest.fixture
def session(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'paper-execution.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as database_session:
        yield database_session
    engine.dispose()


def make_proposal(**overrides: object) -> TradeProposal:
    values: dict[str, object] = {
        "proposal_id": "proposal-1",
        "strategy_id": "strategy-fixed",
        "venue": Venue.ALPACA_PAPER,
        "asset_class": AssetClass.STOCK,
        "symbol": "SPY",
        "side": Side.BUY,
        "notional": Decimal("100.2500"),
        "reference_price": Decimal("500.125"),
        "market_data_at": NOW,
        "created_at": NOW - timedelta(seconds=1),
        "rationale": "deterministic paper proposal",
        "metadata": {"caller": {"secret": "must-not-be-copied"}},
    }
    values.update(overrides)
    return TradeProposal(**values)


def make_portfolio() -> PortfolioState:
    return PortfolioState(
        equity=Decimal("10000"),
        start_of_day_nlv=Decimal("10000"),
        daily_realized_pnl=Decimal("0"),
        gross_exposure=Decimal("0"),
        crypto_exposure=Decimal("0"),
    )


def make_limits() -> RiskLimits:
    return RiskLimits(
        max_order_notional=Decimal("250"),
        max_order_equity_fraction=Decimal("0.05"),
        max_symbol_exposure_fraction=Decimal("0.10"),
        max_gross_exposure_fraction=Decimal("0.50"),
        max_crypto_exposure_fraction=Decimal("0.20"),
        daily_loss_fraction=Decimal("0.02"),
        stock_crypto_max_quote_age_seconds=Decimal("30"),
        weather_max_quote_age_seconds=Decimal("300"),
        allowed_stock_symbols=frozenset({"SPY"}),
        allowed_crypto_symbols=frozenset({"BTC/USD"}),
        allowed_venues=frozenset({Venue.ALPACA_PAPER}),
    )


def make_context(**overrides: object) -> RiskContext:
    values: dict[str, object] = {
        "now": NOW - timedelta(days=1),
        "execution_mode": "paper",
        "idempotency_key": "paper:proposal-1",
        "seen_idempotency_keys": frozenset(),
        "global_kill_switch": False,
        "weather_upstream_approved": False,
        "weather_approval_evidence": (),
    }
    values.update(overrides)
    return RiskContext(**values)


class CountingClock:
    def __init__(self, value: object = NOW, error: Exception | None = None) -> None:
        self.value = value
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        return self.value


class SequenceKillSwitch:
    def __init__(self, *values: object, error: Exception | None = None) -> None:
        self.values = values
        self.error = error
        self.calls = 0

    def __call__(self):
        self.calls += 1
        if self.error is not None:
            raise self.error
        index = min(self.calls - 1, len(self.values) - 1)
        return self.values[index]


class RecordingRisk:
    def __init__(self, decision: object | None = None, error: Exception | None = None) -> None:
        self.decision = decision
        self.error = error
        self.calls: list[tuple[object, object, object, object]] = []

    def __call__(self, proposal, portfolio, context, limits):
        self.calls.append((proposal, portfolio, context, limits))
        if self.error is not None:
            raise self.error
        if self.decision is not None:
            return self.decision
        return RiskDecision(
            proposal_id=proposal.proposal_id,
            approved=True,
            approved_notional=proposal.notional,
            decided_at=context.now,
            limit_snapshot={"policy": "test-v1"},
        )


class RecordingAdapter:
    name = "recording-paper"
    paper_only = True

    def __init__(
        self,
        report_factory: Callable[[NormalizedOrder], object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self.report_factory = report_factory or self._filled_report
        self.error = error
        self.calls: list[tuple[NormalizedOrder, str]] = []

    @staticmethod
    def _filled_report(order: NormalizedOrder) -> ExecutionReport:
        return ExecutionReport(
            client_order_id=order.client_order_id,
            venue=order.venue,
            status=OrderStatus.FILLED,
            broker_order_id="paper-broker-1",
            filled_quantity=Decimal("0.2000"),
            filled_notional=Decimal("100.2500"),
            average_fill_price=Decimal("501.2500"),
            occurred_at=NOW + timedelta(seconds=1),
            metadata={"adapter": "recording-paper"},
        )

    def submit_order(self, order: NormalizedOrder, *, execution_mode: str):
        self.calls.append((order, execution_mode))
        if self.error is not None:
            raise self.error
        return self.report_factory(order)

    def get_account_snapshot(self):
        raise AssertionError("not used")

    def list_positions(self):
        raise AssertionError("not used")

    def cancel_order(self, client_order_id: str):
        raise AssertionError("not used")

    def get_order(self, client_order_id: str):
        raise AssertionError("not used")

    def list_recent_orders(self, *, limit: int = 100):
        raise AssertionError("not used")


def make_service(
    session: Session,
    *,
    adapter: object | None = None,
    adapters: object | None = None,
    risk: RecordingRisk | None = None,
    clock: CountingClock | None = None,
    kill_switch: SequenceKillSwitch | None = None,
    append_event_fn=None,
    upsert_order_projection_fn=None,
) -> tuple[PaperExecutionService, RecordingAdapter, RecordingRisk, CountingClock, SequenceKillSwitch]:
    selected_adapter = adapter if adapter is not None else RecordingAdapter()
    selected_risk = risk or RecordingRisk()
    selected_clock = clock or CountingClock()
    selected_kill = kill_switch or SequenceKillSwitch(False, False)
    registry = adapters if adapters is not None else {Venue.ALPACA_PAPER: selected_adapter}
    kwargs = {}
    if append_event_fn is not None:
        kwargs["append_event_fn"] = append_event_fn
    if upsert_order_projection_fn is not None:
        kwargs["upsert_order_projection_fn"] = upsert_order_projection_fn
    service = PaperExecutionService(
        session=session,
        adapters=registry,
        risk_evaluator=selected_risk,
        settings=PaperExecutionSettings(execution_mode="paper"),
        clock=selected_clock,
        kill_switch=selected_kill,
        **kwargs,
    )
    return service, selected_adapter, selected_risk, selected_clock, selected_kill  # type: ignore[return-value]


def execute(service: PaperExecutionService, proposal: TradeProposal | None = None):
    return service.execute(
        make_proposal() if proposal is None else proposal,
        portfolio=make_portfolio(),
        context=make_context(),
        limits=make_limits(),
    )


def stored_events(session: Session) -> list[TradingEvent]:
    return list(session.scalars(select(TradingEvent).order_by(TradingEvent.sequence)))


def assert_sanitized(error: BaseException, message: str, *sentinels: str) -> None:
    assert type(error) is PaperExecutionServiceError
    assert str(error) == message
    rendered = f"{str(error)} {repr(error)}"
    assert error.__cause__ is None
    assert error.__context__ is None
    for sentinel in sentinels:
        assert sentinel not in rendered


def test_no_proposal_is_a_true_noop_without_touching_dependencies(session: Session):
    class Exploding:
        def __getattribute__(self, name):
            raise AssertionError("no-op dependency was touched")

    service = PaperExecutionService(
        session=Exploding(),
        adapters=Exploding(),
        risk_evaluator=Exploding(),
        settings=PaperExecutionSettings(),
        clock=Exploding(),
        kill_switch=Exploding(),
    )

    assert service.execute(None, portfolio=Exploding(), context=Exploding(), limits=Exploding()) is None
    assert session.scalar(select(func.count()).select_from(TradingEvent)) == 0


def test_filled_order_uses_exact_risk_inputs_and_complete_hash_chained_lifecycle(session: Session):
    service, adapter, risk, clock, kill = make_service(session)
    proposal = make_proposal()
    portfolio = make_portfolio()
    source_context = make_context()
    limits = make_limits()

    result = service.execute(proposal, portfolio=portfolio, context=source_context, limits=limits)

    assert type(result) is PaperExecutionResult
    assert result.proposal == proposal
    assert result.proposal is not proposal
    assert result.decision.approved is True
    assert result.order is adapter.calls[0][0]
    assert result.report.status is OrderStatus.FILLED
    assert adapter.calls[0][1] == "paper"
    assert adapter.calls[0][0] == NormalizedOrder(
        client_order_id="paper:proposal-1",
        proposal_id="proposal-1",
        venue=Venue.ALPACA_PAPER,
        asset_class=AssetClass.STOCK,
        symbol="SPY",
        side=Side.BUY,
        notional=Decimal("100.2500"),
        order_type=proposal.order_type,
        limit_price=proposal.limit_price,
        status=OrderStatus.APPROVED,
        created_at=NOW,
        metadata={"strategy_id": "strategy-fixed"},
    )
    assert len(risk.calls) == 1
    assert risk.calls[0][0] == proposal
    assert risk.calls[0][0] is not proposal
    assert risk.calls[0][1] == portfolio
    assert risk.calls[0][1] is not portfolio
    assert risk.calls[0][3] == limits
    assert risk.calls[0][3] is not limits
    evaluated_context = risk.calls[0][2]
    assert type(evaluated_context) is RiskContext
    assert evaluated_context.now == NOW
    assert evaluated_context.global_kill_switch is False
    assert evaluated_context.idempotency_key == source_context.idempotency_key
    assert clock.calls == 1
    assert kill.calls == 2

    events = stored_events(session)
    assert [event.event_type for event in events] == [
        "proposal_created",
        "risk_approved",
        "order_submitted",
        "order_acknowledged",
        "order_filled",
    ]
    assert [event.sequence for event in events] == [1, 2, 3, 4, 5]
    assert all(event.aggregate_id == "proposal-1" for event in events)
    assert len({event.event_id for event in events}) == 5
    assert verify_event_chain(session, "proposal-1").valid is True
    encoded_payloads = json.dumps([event.payload for event in events])
    assert "must-not-be-copied" not in encoded_payloads
    assert "Decimal" not in encoded_payloads
    assert events[0].payload["notional"] == "100.2500"
    assert events[-1].payload["occurred_at"].endswith("Z")

    projection = session.scalar(select(UnifiedOrder))
    assert projection is not None
    assert projection.status == "filled"
    assert projection.filled_quantity == "0.2000"
    assert projection.filled_notional == "100.2500"
    assert projection.average_fill_price == "501.2500"


@pytest.mark.parametrize(
    ("status", "expected_types"),
    [
        (OrderStatus.SUBMITTED, ["proposal_created", "risk_approved", "order_submitted", "order_acknowledged"]),
        (
            OrderStatus.PARTIALLY_FILLED,
            ["proposal_created", "risk_approved", "order_submitted", "order_acknowledged", "order_partially_filled"],
        ),
        (OrderStatus.CANCELED, ["proposal_created", "risk_approved", "order_submitted", "order_acknowledged", "order_canceled"]),
        (OrderStatus.REJECTED, ["proposal_created", "risk_approved", "order_submitted", "order_rejected"]),
    ],
)
def test_adapter_report_status_maps_to_exact_lifecycle(session: Session, status: OrderStatus, expected_types: list[str]):
    def report(order: NormalizedOrder) -> ExecutionReport:
        fill = status is OrderStatus.PARTIALLY_FILLED
        return ExecutionReport(
            client_order_id=order.client_order_id,
            venue=order.venue,
            status=status,
            broker_order_id="paper-status-1",
            filled_quantity=Decimal("0.1") if fill else Decimal("0"),
            filled_notional=Decimal("50") if fill else Decimal("0"),
            average_fill_price=Decimal("500") if fill else None,
            rejection_reason="venue_rejected" if status is OrderStatus.REJECTED else None,
            occurred_at=NOW + timedelta(seconds=2),
        )

    service, _, _, _, _ = make_service(session, adapter=RecordingAdapter(report))
    result = execute(service)

    assert result.report.status is status
    assert [event.event_type for event in stored_events(session)] == expected_types
    assert session.scalar(select(UnifiedOrder)).status == status.value


def test_risk_rejection_records_only_proposal_and_decision_and_never_calls_adapter(session: Session):
    decision = RiskDecision(
        proposal_id="proposal-1",
        approved=False,
        reason_codes=("order_notional_limit",),
        decided_at=NOW,
        limit_snapshot={"max_order_notional": "10"},
    )
    risk = RecordingRisk(decision)
    service, adapter, _, _, kill = make_service(session, risk=risk)

    result = execute(service)

    assert result.order is None
    assert result.report is None
    assert result.decision == decision
    assert result.decision is not decision
    assert adapter.calls == []
    assert kill.calls == 1
    assert [event.event_type for event in stored_events(session)] == ["proposal_created", "risk_rejected"]
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 0


def test_approved_quantity_is_the_only_normalized_size(session: Session):
    proposal = make_proposal(quantity=Decimal("2.5"), notional=None)
    decision = RiskDecision(
        proposal_id="proposal-1",
        approved=True,
        approved_quantity=Decimal("2.25"),
        decided_at=NOW,
    )
    service, adapter, _, _, _ = make_service(session, risk=RecordingRisk(decision))

    execute(service, proposal)

    order = adapter.calls[0][0]
    assert order.quantity == Decimal("2.25")
    assert order.notional is None


def test_completed_duplicate_returns_same_immutable_result_without_any_new_effect(session: Session):
    service, adapter, risk, clock, kill = make_service(session)
    first = execute(service)
    counts = (len(adapter.calls), len(risk.calls), clock.calls, kill.calls, len(stored_events(session)))

    second = execute(service)

    assert second is first
    assert (len(adapter.calls), len(risk.calls), clock.calls, kill.calls, len(stored_events(session))) == counts
    with pytest.raises(Exception):
        second.report = None


def test_conflicting_proposal_identity_reuse_fails_closed_without_new_effect(session: Session):
    service, adapter, risk, clock, kill = make_service(session)
    execute(service)
    counts = (len(adapter.calls), len(risk.calls), clock.calls, kill.calls, len(stored_events(session)))
    conflict = make_proposal(symbol="QQQ")

    with pytest.raises(PaperExecutionServiceError) as caught:
        execute(service, conflict)

    assert_sanitized(caught.value, "proposal identity conflict", "QQQ")
    assert (len(adapter.calls), len(risk.calls), clock.calls, kill.calls, len(stored_events(session))) == counts


def test_idempotency_key_reuse_by_another_proposal_fails_closed_without_new_effect(session: Session):
    service, adapter, risk, clock, kill = make_service(session)
    execute(service)
    counts = (len(adapter.calls), len(risk.calls), clock.calls, kill.calls, len(stored_events(session)))
    conflict = make_proposal(proposal_id="proposal-2")

    with pytest.raises(PaperExecutionServiceError) as caught:
        execute(service, conflict)

    assert_sanitized(caught.value, "proposal identity conflict", "proposal-2")
    assert (len(adapter.calls), len(risk.calls), clock.calls, kill.calls, len(stored_events(session))) == counts


def test_adapter_exception_becomes_fixed_rejection_event_and_projection(session: Session):
    sentinel = "API_KEY_ADAPTER_EXCEPTION_SENTINEL"
    adapter = RecordingAdapter(error=RuntimeError(sentinel))
    service, _, _, _, _ = make_service(session, adapter=adapter)

    result = execute(service)

    assert result.report == ExecutionReport(
        client_order_id="paper:proposal-1",
        venue=Venue.ALPACA_PAPER,
        status=OrderStatus.REJECTED,
        rejection_reason="adapter_error",
        occurred_at=NOW,
        metadata={"service": "paper_execution"},
    )
    assert [event.event_type for event in stored_events(session)] == [
        "proposal_created",
        "risk_approved",
        "order_submitted",
        "order_rejected",
    ]
    assert sentinel not in json.dumps([event.payload for event in stored_events(session)])
    projection = session.scalar(select(UnifiedOrder))
    assert projection.rejection_reason == "adapter_error"


def test_kill_switch_is_rechecked_immediately_before_submit_and_never_claims_submission(session: Session):
    kill = SequenceKillSwitch(False, True)
    service, adapter, _, _, _ = make_service(session, kill_switch=kill)

    result = execute(service)

    assert kill.calls == 2
    assert adapter.calls == []
    assert result.report.status is OrderStatus.REJECTED
    assert result.report.rejection_reason == "kill_switch_active"
    assert [event.event_type for event in stored_events(session)] == [
        "proposal_created",
        "risk_approved",
        "order_rejected",
    ]


@pytest.mark.parametrize("case", ["missing", "non_paper", "wrong_object", "wrong_venue_key"])
def test_invalid_adapter_registry_fails_closed_without_submit(session: Session, case: str):
    good = RecordingAdapter()
    if case == "missing":
        registry: object = {}
    elif case == "wrong_venue_key":
        registry = {Venue.KALSHI_PAPER: good}
    elif case == "wrong_object":
        registry = {Venue.ALPACA_PAPER: object()}
    else:
        good.paper_only = False
        registry = {Venue.ALPACA_PAPER: good}
    service, _, _, _, _ = make_service(session, adapters=registry, adapter=good)

    result = execute(service)

    assert good.calls == []
    assert result.report.status is OrderStatus.REJECTED
    assert result.report.rejection_reason == "adapter_unavailable"
    assert [event.event_type for event in stored_events(session)][-1] == "order_rejected"
    assert "order_submitted" not in [event.event_type for event in stored_events(session)]


@pytest.mark.parametrize("mismatch", ["client_order_id", "venue", "malformed", "invalid_status"])
def test_adapter_report_mismatch_or_malformed_value_is_safely_rejected(session: Session, mismatch: str):
    sentinel = "HOSTILE_REPORT_SENTINEL"

    def report(order: NormalizedOrder):
        if mismatch == "malformed":
            class Hostile:
                def __repr__(self):
                    raise AssertionError(sentinel)

                def model_dump(self):
                    raise AssertionError(sentinel)
            return Hostile()
        status = OrderStatus.APPROVED if mismatch == "invalid_status" else OrderStatus.SUBMITTED
        return ExecutionReport(
            client_order_id="different-client" if mismatch == "client_order_id" else order.client_order_id,
            venue=Venue.KALSHI_PAPER if mismatch == "venue" else order.venue,
            status=status,
            occurred_at=NOW + timedelta(seconds=3),
        )

    service, adapter, _, _, _ = make_service(session, adapter=RecordingAdapter(report))
    result = execute(service)

    assert len(adapter.calls) == 1
    assert result.report.status is OrderStatus.REJECTED
    assert result.report.rejection_reason == "adapter_invalid_report"
    assert [event.event_type for event in stored_events(session)][-1] == "order_rejected"
    assert sentinel not in json.dumps([event.payload for event in stored_events(session)])


def test_ledger_failure_before_adapter_stops_submission(session: Session):
    calls = 0

    def failing_append(*args):
        nonlocal calls
        calls += 1
        if calls == 3:
            raise LedgerStorageError("ledger storage failed")
        from backend.trading.ledger import append_event
        return append_event(*args)

    service, adapter, _, _, _ = make_service(session, append_event_fn=failing_append)

    with pytest.raises(LedgerStorageError, match="^ledger storage failed$"):
        execute(service)

    assert adapter.calls == []


def test_ledger_failure_after_adapter_is_not_disguised_or_cached(session: Session):
    calls = 0

    def failing_projection(*args):
        nonlocal calls
        calls += 1
        raise LedgerStorageError("ledger storage failed")

    service, adapter, risk, clock, kill = make_service(
        session, upsert_order_projection_fn=failing_projection
    )

    with pytest.raises(LedgerStorageError, match="^ledger storage failed$"):
        execute(service)

    assert len(adapter.calls) == 1
    assert calls == 1
    assert len(risk.calls) == 1
    assert clock.calls == 1
    assert kill.calls == 2


def test_caller_owns_transaction_and_rollback_removes_events_and_projection(session: Session):
    service, _, _, _, _ = make_service(session)
    execute(service)
    assert session.scalar(select(func.count()).select_from(TradingEvent)) == 5
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 1

    session.rollback()

    assert session.scalar(select(func.count()).select_from(TradingEvent)) == 0
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 0


def test_rollback_clears_completed_replay_and_reexecutes_the_proposal(session: Session):
    service, adapter, risk, clock, kill = make_service(session)
    first = execute(service)
    assert len(stored_events(session)) == 5

    session.rollback()
    assert session.scalar(select(func.count()).select_from(TradingEvent)) == 0
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 0

    second = execute(service)

    assert second is not first
    assert len(adapter.calls) == 2
    assert len(risk.calls) == 2
    assert clock.calls == 2
    assert kill.calls == 4
    assert [event.event_type for event in stored_events(session)] == [
        "proposal_created",
        "risk_approved",
        "order_submitted",
        "order_acknowledged",
        "order_filled",
    ]
    assert verify_event_chain(session, "proposal-1").valid is True
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 1


def test_commit_keeps_completed_replay_without_new_effects(session: Session):
    service, adapter, risk, clock, kill = make_service(session)
    first = execute(service)
    session.commit()
    counts = (len(adapter.calls), len(risk.calls), clock.calls, kill.calls)

    second = execute(service)

    assert second is first
    assert (len(adapter.calls), len(risk.calls), clock.calls, kill.calls) == counts
    assert len(stored_events(session)) == 5
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 1


def test_adapter_rejection_reason_and_metadata_are_replaced_everywhere(session: Session):
    sentinel = "BROKER_SECRET_SENTINEL"
    source_metadata = {"api_key": sentinel, "nested": {"password": sentinel}}

    def rejected(order: NormalizedOrder) -> ExecutionReport:
        return ExecutionReport(
            client_order_id=order.client_order_id,
            venue=order.venue,
            status=OrderStatus.REJECTED,
            broker_order_id="broker-rejected-1",
            rejection_reason=sentinel,
            occurred_at=NOW + timedelta(seconds=2),
            metadata=source_metadata,
        )

    service, _, _, _, _ = make_service(session, adapter=RecordingAdapter(rejected))
    result = execute(service)

    assert result.report == ExecutionReport(
        client_order_id="paper:proposal-1",
        venue=Venue.ALPACA_PAPER,
        status=OrderStatus.REJECTED,
        broker_order_id="broker-rejected-1",
        rejection_reason="adapter_rejected",
        occurred_at=NOW + timedelta(seconds=2),
        metadata={"service": "paper_execution"},
    )
    source_metadata["api_key"] = "changed-after-return"
    event_json = json.dumps([event.payload for event in stored_events(session)])
    projection = session.scalar(select(UnifiedOrder))
    assert projection.rejection_reason == "adapter_rejected"
    assert projection.order_metadata == {"service": "paper_execution"}
    combined = f"{result!r} {event_json} {projection.order_metadata!r} {projection.rejection_reason}"
    assert sentinel not in combined


class HostileBoundary:
    def _raise(self, *args, **kwargs):
        raise RuntimeError("HOSTILE_BOUNDARY_SECRET_SENTINEL")

    __bool__ = _raise
    __eq__ = _raise
    __hash__ = _raise
    __iter__ = _raise
    __len__ = _raise
    __lt__ = _raise
    __le__ = _raise
    __gt__ = _raise
    __ge__ = _raise
    __str__ = _raise
    __repr__ = _raise

    def items(self):
        return self._raise()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("proposal_id", HostileBoundary()),
        ("approved", HostileBoundary()),
        ("approved_notional", HostileBoundary()),
        ("decided_at", HostileBoundary()),
        ("limit_snapshot", HostileBoundary()),
    ],
)
def test_corrupted_exact_risk_decision_is_sanitized_before_adapter(
    session: Session, field: str, value: object
):
    decision = RiskDecision(
        proposal_id="proposal-1",
        approved=True,
        approved_notional=Decimal("100.2500"),
        decided_at=NOW,
        limit_snapshot={"policy": "valid"},
    )
    object.__setattr__(decision, field, value)
    risk = RecordingRisk(decision)
    service, adapter, _, _, _ = make_service(session, risk=risk)

    with pytest.raises(PaperExecutionServiceError) as caught:
        execute(service)

    assert_sanitized(
        caught.value, "risk decision invalid", "HOSTILE_BOUNDARY_SECRET_SENTINEL"
    )
    assert len(risk.calls) == 1
    assert adapter.calls == []
    assert "order_submitted" not in [event.event_type for event in stored_events(session)]


def test_valid_exact_risk_decision_is_detached_and_accepted(session: Session):
    decision = RiskDecision(
        proposal_id="proposal-1",
        approved=True,
        approved_notional=Decimal("100.2500"),
        decided_at=NOW,
        limit_snapshot={"policy": "valid"},
    )
    service, adapter, risk, _, _ = make_service(session, risk=RecordingRisk(decision))

    result = execute(service)

    assert len(risk.calls) == 1
    assert len(adapter.calls) == 1
    assert result.decision == decision
    assert result.decision is not decision


@pytest.mark.parametrize(
    "field",
    [
        "client_order_id",
        "venue",
        "status",
        "filled_quantity",
        "filled_notional",
        "occurred_at",
        "metadata",
    ],
)
def test_corrupted_exact_adapter_report_becomes_safe_invalid_rejection(
    session: Session, field: str
):
    report = ExecutionReport(
        client_order_id="paper:proposal-1",
        venue=Venue.ALPACA_PAPER,
        status=OrderStatus.FILLED,
        broker_order_id="paper-broker-hostile",
        filled_quantity=Decimal("0.2"),
        filled_notional=Decimal("100.2500"),
        average_fill_price=Decimal("501.25"),
        occurred_at=NOW + timedelta(seconds=1),
        metadata={"adapter": "valid-before-corruption"},
    )
    object.__setattr__(report, field, HostileBoundary())
    adapter = RecordingAdapter(lambda order: report)
    service, _, _, _, _ = make_service(session, adapter=adapter)

    result = execute(service)

    assert len(adapter.calls) == 1
    assert result.report == ExecutionReport(
        client_order_id="paper:proposal-1",
        venue=Venue.ALPACA_PAPER,
        status=OrderStatus.REJECTED,
        rejection_reason="adapter_invalid_report",
        occurred_at=NOW,
        metadata={"service": "paper_execution"},
    )
    event_json = json.dumps([event.payload for event in stored_events(session)])
    projection = session.scalar(select(UnifiedOrder))
    combined = f"{result!r} {event_json} {projection.order_metadata!r} {projection.rejection_reason}"
    assert "HOSTILE_BOUNDARY_SECRET_SENTINEL" not in combined


@pytest.mark.parametrize(
    ("target", "field"),
    [
        ("proposal", "symbol"),
        ("proposal", "metadata"),
        ("portfolio", "equity"),
        ("portfolio", "symbol_exposures"),
        ("context", "idempotency_key"),
        ("context", "seen_idempotency_keys"),
        ("limits", "max_order_notional"),
        ("limits", "allowed_stock_symbols"),
    ],
)
def test_corrupted_exact_request_models_fail_before_execution_dependencies(
    session: Session, target: str, field: str
):
    proposal = make_proposal()
    portfolio = make_portfolio()
    context = make_context()
    limits = make_limits()
    objects = {
        "proposal": proposal,
        "portfolio": portfolio,
        "context": context,
        "limits": limits,
    }
    object.__setattr__(objects[target], field, HostileBoundary())
    clock = CountingClock()
    kill = SequenceKillSwitch(False, False)
    risk = RecordingRisk()
    service, adapter, _, _, _ = make_service(
        session, clock=clock, kill_switch=kill, risk=risk
    )

    with pytest.raises(PaperExecutionServiceError) as caught:
        service.execute(proposal, portfolio=portfolio, context=context, limits=limits)

    assert_sanitized(
        caught.value, "invalid execution request", "HOSTILE_BOUNDARY_SECRET_SENTINEL"
    )
    assert clock.calls == 0
    assert kill.calls == 0
    assert risk.calls == []
    assert adapter.calls == []
    assert session.scalar(select(func.count()).select_from(TradingEvent)) == 0


@pytest.mark.parametrize(
    ("boundary", "dependency", "message"),
    [
        ("clock", CountingClock(error=RuntimeError("CLOCK_SECRET_SENTINEL")), "service clock failed"),
        ("kill", SequenceKillSwitch(False, error=RuntimeError("KILL_SECRET_SENTINEL")), "kill switch failed"),
        ("risk", RecordingRisk(error=RuntimeError("RISK_SECRET_SENTINEL")), "risk evaluation failed"),
    ],
)
def test_hostile_pre_submit_boundaries_raise_fixed_context_free_errors(
    session: Session, boundary: str, dependency: object, message: str
):
    kwargs = {"clock": CountingClock(), "kill_switch": SequenceKillSwitch(False), "risk": RecordingRisk()}
    kwargs[{"clock": "clock", "kill": "kill_switch", "risk": "risk"}[boundary]] = dependency
    service, adapter, _, _, _ = make_service(session, **kwargs)

    with pytest.raises(PaperExecutionServiceError) as caught:
        execute(service)

    assert_sanitized(caught.value, message, "SECRET_SENTINEL", "RuntimeError")
    assert adapter.calls == []


@pytest.mark.parametrize("boundary", ["clock_non_datetime", "clock_non_utc", "kill_non_bool", "risk_wrong_type", "risk_wrong_proposal"])
def test_malformed_boundary_values_fail_closed_before_adapter(session: Session, boundary: str):
    kwargs: dict[str, object] = {}
    if boundary == "clock_non_datetime":
        kwargs["clock"] = CountingClock("2026-08-24T14:30:15Z")
    elif boundary == "clock_non_utc":
        kwargs["clock"] = CountingClock(datetime(2026, 8, 24, 14, 30))
    elif boundary == "kill_non_bool":
        kwargs["kill_switch"] = SequenceKillSwitch(1)
    elif boundary == "risk_wrong_type":
        kwargs["risk"] = RecordingRisk(object())
    else:
        kwargs["risk"] = RecordingRisk(
            RiskDecision(
                proposal_id="other-proposal",
                approved=True,
                approved_notional=Decimal("10"),
                decided_at=NOW,
            )
        )
    service, adapter, _, _, _ = make_service(session, **kwargs)

    with pytest.raises(PaperExecutionServiceError):
        execute(service)

    assert adapter.calls == []


def test_service_has_small_dependency_safe_surface_and_no_forbidden_imports():
    import backend.trading.service as service_module

    tree = ast.parse(inspect.getsource(service_module))
    imported_roots = {
        alias.name.split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    } | {
        (node.module or "").split(".")[0]
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
    }
    forbidden = {"openai", "anthropic", "langchain", "requests", "httpx", "socket", "os", "subprocess"}
    assert imported_roots.isdisjoint(forbidden)
    assert set(service_module.__all__) == {
        "PaperExecutionResult",
        "PaperExecutionService",
        "PaperExecutionServiceError",
        "PaperExecutionSettings",
    }
    source = inspect.getsource(service_module)
    assert ".commit(" not in source
    assert ".rollback(" not in source
    assert "uuid" not in source
