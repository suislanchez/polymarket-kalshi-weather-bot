"""Behavioral tests for the append-only trading ledger and order projection."""

from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timedelta, timezone, tzinfo
from decimal import Decimal
from pathlib import Path
from typing import ClassVar

import pytest
from sqlalchemy import create_engine, func, select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, sessionmaker

from backend.models.database import Base, Signal, Trade, TradingEvent, UnifiedOrder
from backend.trading.domain import ExecutionReport, OrderStatus, Venue
from backend.trading import ledger as ledger_module
from backend.trading.ledger import (
    ZERO_CHAIN_HASH,
    ChainVerification,
    LedgerConflictError,
    LedgerError,
    LedgerEventInput,
    LedgerSequenceError,
    LedgerValidationError,
    append_event,
    upsert_order_projection,
    verify_event_chain,
)


NOW = datetime(2026, 8, 24, 12, 30, 45, 123456, tzinfo=timezone.utc)


@pytest.fixture
def session(tmp_path: Path):
    database_path = tmp_path / "ledger.sqlite3"
    engine = create_engine(f"sqlite:///{database_path}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as database_session:
        yield database_session
    engine.dispose()


def event_input(**overrides: object) -> LedgerEventInput:
    values: dict[str, object] = {
        "event_id": "event-1",
        "aggregate_id": "order-1",
        "sequence": 1,
        "event_type": "order_submitted",
        "occurred_at": NOW,
        "payload": {"nested": {"quantity": 2}, "tags": ["paper", True, None]},
    }
    values.update(overrides)
    return LedgerEventInput(**values)  # type: ignore[arg-type]


def execution_report(**overrides: object) -> ExecutionReport:
    values: dict[str, object] = {
        "client_order_id": "client-1",
        "venue": Venue.ALPACA_PAPER,
        "status": OrderStatus.SUBMITTED,
        "broker_order_id": "broker-1",
        "filled_quantity": Decimal("0.000"),
        "filled_notional": Decimal("0.00"),
        "occurred_at": NOW,
        "metadata": {"attempt": 1, "route": ["paper"]},
    }
    values.update(overrides)
    return ExecutionReport(**values)


class FailingStorageSession:
    def __init__(self, stage: str, failure: Exception):
        self.stage = stage
        self.failure = failure
        self.calls: list[str] = []

    def scalar(self, statement):
        self.calls.append("scalar")
        if self.stage == "query":
            raise self.failure
        return None

    def add(self, value):
        self.calls.append("add")
        if self.stage == "add":
            raise self.failure

    def flush(self):
        self.calls.append("flush")
        if self.stage == "flush":
            raise self.failure


def call_storage_operation(operation: str, session: object):
    if operation == "append":
        return append_event(session, event_input())  # type: ignore[arg-type]
    return upsert_order_projection(session, execution_report())  # type: ignore[arg-type]


def assert_sanitized_exception(
    error: BaseException, expected_type: type, message: str, secrets: tuple[str, ...]
):
    assert type(error) is expected_type
    assert str(error) == message
    rendered = f"{str(error)} {repr(error)}"
    for secret in secrets:
        assert secret not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None


def deeply_nested_json(depth: int = 3000) -> dict[str, object]:
    root: dict[str, object] = {}
    current = root
    for _ in range(depth):
        child: dict[str, object] = {}
        current["nested"] = [child]
        current = child
    return root


@pytest.mark.parametrize("operation", ["append", "projection"])
@pytest.mark.parametrize("stage", ["query", "add", "flush"])
def test_storage_dependency_failures_are_fixed_and_fully_sanitized(operation: str, stage: str):
    sentinel = f"DB_PASSWORD_{operation.upper()}_{stage.upper()}_SENTINEL"
    fake_session = FailingStorageSession(stage, RuntimeError(sentinel))

    with pytest.raises(BaseException) as caught:
        call_storage_operation(operation, fake_session)

    storage_error = getattr(ledger_module, "LedgerStorageError", object)
    assert_sanitized_exception(
        caught.value,
        storage_error,
        "ledger storage failed",
        (sentinel, "RuntimeError"),
    )


@pytest.mark.parametrize(
    ("operation", "conflict_message"),
    [
        ("append", "ledger event conflicts with existing data"),
        ("projection", "order projection conflicts with existing data"),
    ],
)
def test_integrity_failures_keep_fixed_conflicts_without_exception_context(
    operation: str, conflict_message: str
):
    sentinel = f"DB_PASSWORD_{operation.upper()}_INTEGRITY_SENTINEL"
    secret_statement = f"INSERT SECRET_STATEMENT_{sentinel}"
    secret_parameter = f"SECRET_PARAM_{sentinel}"
    failure = IntegrityError(
        secret_statement,
        {"password": secret_parameter},
        RuntimeError(f"SECRET_ORIGINAL_{sentinel}"),
    )
    fake_session = FailingStorageSession("flush", failure)

    with pytest.raises(BaseException) as caught:
        call_storage_operation(operation, fake_session)

    assert_sanitized_exception(
        caught.value,
        LedgerConflictError,
        conflict_message,
        (sentinel, secret_statement, secret_parameter, "SECRET_ORIGINAL"),
    )


@pytest.mark.parametrize(
    ("operation", "invalid_value", "message"),
    [
        ("append", object(), "invalid ledger event"),
        ("append", event_input(sequence=0), "invalid ledger event"),
        ("projection", object(), "invalid execution report"),
    ],
)
def test_validation_precedes_any_exploding_storage_dependency(
    operation: str, invalid_value: object, message: str
):
    sentinel = f"DB_PASSWORD_{operation.upper()}_VALIDATION_SENTINEL"
    fake_session = FailingStorageSession("query", RuntimeError(sentinel))

    with pytest.raises(LedgerValidationError, match=f"^{message}$") as caught:
        if operation == "append":
            append_event(fake_session, invalid_value)  # type: ignore[arg-type]
        else:
            upsert_order_projection(fake_session, invalid_value)  # type: ignore[arg-type]

    assert fake_session.calls == []
    assert sentinel not in repr(caught.value)


@pytest.mark.parametrize("failure_kind", ["cyclic", "deep", "hostile_datetime"])
def test_event_validation_failures_clear_hostile_exception_context_before_storage(
    failure_kind: str,
):
    sentinel = "CALLER_EVENT_VALIDATION_SENTINEL"
    fake_session = FailingStorageSession("query", RuntimeError("storage must stay untouched"))
    if failure_kind == "cyclic":
        payload: dict[str, object] = {}
        payload["cycle"] = payload
        invalid_event = event_input(payload=payload)
    elif failure_kind == "deep":
        invalid_event = event_input(payload=deeply_nested_json())
    else:
        class HostileTimezone(tzinfo):
            def utcoffset(self, dt):
                raise RuntimeError(sentinel)

            def dst(self, dt):
                return timedelta(0)

        invalid_event = event_input(
            occurred_at=datetime(2026, 8, 24, 12, 30, tzinfo=HostileTimezone())
        )

    with pytest.raises(BaseException) as caught:
        append_event(fake_session, invalid_event)  # type: ignore[arg-type]

    assert_sanitized_exception(
        caught.value,
        LedgerValidationError,
        "invalid ledger event",
        (sentinel, "RecursionError"),
    )
    assert fake_session.calls == []


@pytest.mark.parametrize("failure_kind", ["cyclic", "deep"])
def test_projection_validation_failures_clear_context_before_storage(failure_kind: str):
    sentinel = "CALLER_REPORT_VALIDATION_SENTINEL"
    fake_session = FailingStorageSession("query", RuntimeError("storage must stay untouched"))
    report = execution_report()
    if failure_kind == "cyclic":
        metadata: dict[str, object] = {"secret": sentinel}
        metadata["cycle"] = metadata
    else:
        metadata = deeply_nested_json()
    object.__setattr__(report, "metadata", metadata)

    with pytest.raises(BaseException) as caught:
        upsert_order_projection(fake_session, report)  # type: ignore[arg-type]

    assert_sanitized_exception(
        caught.value,
        LedgerValidationError,
        "invalid execution report",
        (sentinel, "RecursionError"),
    )
    assert fake_session.calls == []


@pytest.mark.parametrize("failure_kind", ["object", "string_subclass", "blank"])
def test_verify_chain_aggregate_validation_clears_context_before_storage(
    failure_kind: str,
):
    class StringSubclass(str):
        pass

    sentinel = "AGGREGATE_STORAGE_MUST_STAY_UNTOUCHED"

    class ExplodingVerificationSession:
        calls = 0

        def scalars(self, statement):
            self.calls += 1
            raise RuntimeError(sentinel)

    fake_session = ExplodingVerificationSession()
    candidates = {
        "object": object(),
        "string_subclass": StringSubclass("order-1"),
        "blank": "   ",
    }

    with pytest.raises(BaseException) as caught:
        verify_event_chain(fake_session, candidates[failure_kind])  # type: ignore[arg-type]

    assert_sanitized_exception(
        caught.value,
        LedgerValidationError,
        "invalid aggregate id",
        (sentinel,),
    )
    assert fake_session.calls == 0


def test_storage_error_is_public_ledger_error_without_expanding_mutation_api():
    storage_error = getattr(ledger_module, "LedgerStorageError", None)
    assert isinstance(storage_error, type)
    assert issubclass(storage_error, LedgerError)
    assert "LedgerStorageError" in ledger_module.__all__
    assert "update_event" not in ledger_module.__all__
    assert "delete_event" not in ledger_module.__all__


def test_verify_chain_storage_failure_keeps_database_error_result():
    sentinel = "DB_PASSWORD_VERIFY_CHAIN_SENTINEL"

    class FailingVerificationSession:
        def scalars(self, statement):
            raise RuntimeError(sentinel)

    result = verify_event_chain(FailingVerificationSession(), "order-1")  # type: ignore[arg-type]

    assert result == ChainVerification("order-1", False, 0, "database_error")


def canonical_hash(event: TradingEvent) -> str:
    timestamp = event.occurred_at.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    document = {
        "event_id": event.event_id,
        "aggregate_id": event.aggregate_id,
        "sequence": event.sequence,
        "event_type": event.event_type,
        "occurred_at": timestamp,
        "payload": event.payload,
        "previous_hash": event.previous_hash,
    }
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def test_append_stores_complete_event_with_utc_and_defensive_payload(session: Session):
    payload = {"nested": {"quantity": 2}, "tags": ["paper", True, None]}
    stored = append_event(session, event_input(payload=payload))
    payload["nested"]["quantity"] = 999  # type: ignore[index]
    payload["tags"].append("mutated")  # type: ignore[union-attr]

    session.expire_all()
    loaded = session.scalar(select(TradingEvent).where(TradingEvent.event_id == "event-1"))
    assert loaded is not None
    assert loaded.id == stored.id
    assert loaded.aggregate_id == "order-1"
    assert loaded.sequence == 1
    assert loaded.event_type == "order_submitted"
    assert loaded.occurred_at == NOW
    assert type(loaded.occurred_at) is datetime
    assert loaded.occurred_at.tzinfo is timezone.utc
    assert loaded.payload == {"nested": {"quantity": 2}, "tags": ["paper", True, None]}
    assert loaded.previous_hash == ZERO_CHAIN_HASH
    assert len(loaded.event_hash) == 64
    assert loaded.event_hash == canonical_hash(loaded)


def test_second_event_links_to_first_and_hash_is_deterministic(session: Session):
    first = append_event(session, event_input())
    second = append_event(
        session,
        event_input(
            event_id="event-2",
            sequence=2,
            event_type="order_acknowledged",
            occurred_at=NOW + timedelta(seconds=1),
            payload={"broker_order_id": "paper-123", "unicode": "café"},
        ),
    )

    assert second.previous_hash == first.event_hash
    assert first.event_hash == canonical_hash(first)
    assert second.event_hash == canonical_hash(second)
    assert verify_event_chain(session, "order-1") == ChainVerification(
        aggregate_id="order-1", valid=True, event_count=2, failure_reason=None
    )


def test_each_aggregate_starts_an_independent_zero_chain(session: Session):
    first = append_event(session, event_input())
    independent = append_event(
        session, event_input(event_id="event-other", aggregate_id="order-2")
    )
    assert first.previous_hash == independent.previous_hash == ZERO_CHAIN_HASH
    assert verify_event_chain(session, "order-1").valid is True
    assert verify_event_chain(session, "order-2").valid is True


def test_empty_chain_is_valid_and_read_only(session: Session):
    before = session.execute(text("PRAGMA data_version")).scalar_one()
    result = verify_event_chain(session, "absent-order")
    after = session.execute(text("PRAGMA data_version")).scalar_one()
    assert result == ChainVerification("absent-order", True, 0, None)
    assert before == after
    assert session.scalar(select(func.count()).select_from(TradingEvent)) == 0


def test_append_flushes_but_never_commits(session: Session):
    append_event(session, event_input())
    assert session.scalar(select(func.count()).select_from(TradingEvent)) == 1
    session.rollback()
    assert session.scalar(select(func.count()).select_from(TradingEvent)) == 0


@pytest.mark.parametrize(
    ("first", "second", "error_type"),
    [
        (event_input(), event_input(aggregate_id="order-2"), LedgerConflictError),
        (event_input(), event_input(event_id="event-2"), LedgerConflictError),
    ],
)
def test_database_uniqueness_conflicts_are_sanitized(
    session: Session,
    first: LedgerEventInput,
    second: LedgerEventInput,
    error_type: type[LedgerError],
):
    append_event(session, first)
    with pytest.raises(error_type) as caught:
        append_event(session, second)
    assert str(caught.value) == "ledger event conflicts with existing data"
    assert "sqlite" not in str(caught.value).lower()
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    session.rollback()
    assert session.scalar(select(func.count()).select_from(TradingEvent)) == 0


@pytest.mark.parametrize("sequence", [0, -1, True, 1.0, "1"])
def test_sequence_boundary_requires_an_exact_positive_integer(session: Session, sequence: object):
    with pytest.raises(LedgerValidationError, match="^invalid ledger event$"):
        append_event(session, event_input(sequence=sequence))


def test_sequence_must_start_at_one_and_remain_contiguous(session: Session):
    with pytest.raises(LedgerSequenceError, match="^invalid ledger sequence$"):
        append_event(session, event_input(sequence=2))
    append_event(session, event_input())
    with pytest.raises(LedgerSequenceError, match="^invalid ledger sequence$"):
        append_event(session, event_input(event_id="event-3", sequence=3))


def test_corrupted_committed_sequence_is_sanitized_and_rollback_keeps_only_prior_row(
    session: Session,
):
    append_event(session, event_input())
    session.commit()
    session.execute(
        text("UPDATE trading_events SET sequence = :sequence WHERE event_id = :event_id"),
        {"sequence": "oops", "event_id": "event-1"},
    )
    session.commit()

    with pytest.raises(BaseException) as caught:
        append_event(session, event_input(event_id="event-2", sequence=2))

    assert_sanitized_exception(
        caught.value,
        LedgerSequenceError,
        "invalid ledger sequence",
        ("oops", "TypeError"),
    )
    session.rollback()
    assert session.execute(
        text("SELECT event_id, sequence FROM trading_events ORDER BY id")
    ).all() == [("event-1", "oops")]


class PriorReturningSession:
    def __init__(self, prior: object):
        self.prior = prior
        self.scalar_calls = 0
        self.add_calls = 0
        self.flush_calls = 0

    def scalar(self, statement):
        self.scalar_calls += 1
        return None if self.scalar_calls <= 2 else self.prior

    def add(self, value):
        self.add_calls += 1

    def flush(self):
        self.flush_calls += 1


def test_nonmodel_prior_is_rejected_without_touching_hostile_properties_or_storage():
    sentinel = "HOSTILE_PRIOR_SEQUENCE_SENTINEL"

    class HostilePrior:
        @property
        def sequence(self):
            raise RuntimeError(sentinel)

    fake_session = PriorReturningSession(HostilePrior())

    with pytest.raises(BaseException) as caught:
        append_event(fake_session, event_input(event_id="event-2", sequence=2))  # type: ignore[arg-type]

    assert_sanitized_exception(
        caught.value,
        LedgerSequenceError,
        "invalid ledger sequence",
        (sentinel,),
    )
    assert fake_session.scalar_calls == 3
    assert fake_session.add_calls == 0
    assert fake_session.flush_calls == 0


@pytest.mark.parametrize(
    ("prior_sequence", "prior_hash"),
    [(0, "a" * 64), (True, "a" * 64), (1, "A" * 64), (1, "short")],
)
def test_malformed_exact_prior_event_has_fixed_sequence_error_without_storage_mutation(
    prior_sequence: object, prior_hash: object
):
    prior = TradingEvent(sequence=prior_sequence, event_hash=prior_hash)
    fake_session = PriorReturningSession(prior)

    with pytest.raises(BaseException) as caught:
        append_event(fake_session, event_input(event_id="event-2", sequence=2))  # type: ignore[arg-type]

    assert_sanitized_exception(
        caught.value,
        LedgerSequenceError,
        "invalid ledger sequence",
        (),
    )
    assert fake_session.add_calls == 0
    assert fake_session.flush_calls == 0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("event_id", ""),
        ("event_id", "  \t"),
        ("event_id", 1),
        ("aggregate_id", ""),
        ("aggregate_id", None),
        ("event_type", " "),
        ("event_type", b"event"),
    ],
)
def test_string_boundaries_require_exact_nonblank_builtins(
    session: Session, field: str, value: object
):
    class StringSubclass(str):
        pass

    bad_value = StringSubclass("apparently-valid") if value == b"event" else value
    with pytest.raises(LedgerValidationError, match="^invalid ledger event$"):
        append_event(session, event_input(**{field: bad_value}))


class RaisingTimezone(tzinfo):
    def utcoffset(self, dt):
        raise RuntimeError("caller-controlled timezone sentinel")

    def dst(self, dt):
        return timedelta(0)


class DatetimeSubclass(datetime):
    pass


@pytest.mark.parametrize(
    "occurred_at",
    [
        datetime(2026, 8, 24, 12, 30),
        datetime(2026, 8, 24, 8, 30, tzinfo=timezone(timedelta(hours=-4))),
        DatetimeSubclass(2026, 8, 24, 12, 30, tzinfo=timezone.utc),
        datetime(2026, 8, 24, 12, 30, tzinfo=RaisingTimezone()),
        "2026-08-24T12:30:00Z",
    ],
)
def test_datetime_boundary_is_exact_safe_utc_and_sanitized(session: Session, occurred_at: object):
    with pytest.raises(LedgerValidationError) as caught:
        append_event(session, event_input(occurred_at=occurred_at))
    assert str(caught.value) == "invalid ledger event"
    assert "sentinel" not in str(caught.value)


@pytest.mark.parametrize(
    "payload",
    [
        [],
        {1: "non-string key"},
        {"tuple": (1, 2)},
        {"decimal": Decimal("1.2")},
        {"bytes": b"no"},
        {"nan": float("nan")},
        {"positive_infinity": float("inf")},
        {"negative_infinity": float("-inf")},
        {"object": object()},
    ],
)
def test_payload_boundary_accepts_only_strict_finite_json_objects(
    session: Session, payload: object
):
    with pytest.raises(LedgerValidationError, match="^invalid ledger event$"):
        append_event(session, event_input(payload=payload))


def test_payload_rejects_container_and_key_subclasses(session: Session):
    class DictSubclass(dict):
        pass

    class StringSubclass(str):
        pass

    for payload in (DictSubclass(ok=True), {StringSubclass("key"): "value"}):
        with pytest.raises(LedgerValidationError, match="^invalid ledger event$"):
            append_event(session, event_input(payload=payload))


def _committed_chain(tmp_path: Path) -> tuple[object, sessionmaker[Session]]:
    engine = create_engine(f"sqlite:///{tmp_path / 'tamper.sqlite3'}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    with factory() as writer:
        append_event(writer, event_input())
        append_event(writer, event_input(event_id="event-2", sequence=2))
        writer.commit()
    return engine, factory


@pytest.mark.parametrize(
    ("statement", "reason"),
    [
        ("UPDATE trading_events SET payload = '[1,2]' WHERE sequence = 1", "malformed_event"),
        ("UPDATE trading_events SET event_hash = :bad WHERE sequence = 1", "event_hash_mismatch"),
        ("UPDATE trading_events SET previous_hash = :bad WHERE sequence = 2", "previous_hash_mismatch"),
        ("UPDATE trading_events SET sequence = 7 WHERE sequence = 2", "sequence_gap"),
    ],
)
def test_direct_database_tampering_returns_fixed_failure_without_mutation(
    tmp_path: Path, statement: str, reason: str
):
    engine, factory = _committed_chain(tmp_path)
    bad_hash = "f" * 64
    with engine.begin() as connection:
        connection.execute(text(statement), {"bad": bad_hash})
    with factory() as reader:
        before = reader.execute(
            text(
                "SELECT event_id, aggregate_id, sequence, event_type, occurred_at, payload, "
                "previous_hash, event_hash FROM trading_events ORDER BY id"
            )
        ).all()
        result = verify_event_chain(reader, "order-1")
        after = reader.execute(
            text(
                "SELECT event_id, aggregate_id, sequence, event_type, occurred_at, payload, "
                "previous_hash, event_hash FROM trading_events ORDER BY id"
            )
        ).all()
    engine.dispose()
    assert result == ChainVerification("order-1", False, 2, reason)
    assert after == before


def test_first_previous_hash_tampering_has_fixed_reason(tmp_path: Path):
    engine, factory = _committed_chain(tmp_path)
    with engine.begin() as connection:
        connection.execute(
            text("UPDATE trading_events SET previous_hash = :bad WHERE sequence = 1"),
            {"bad": "a" * 64},
        )
    with factory() as reader:
        assert verify_event_chain(reader, "order-1").failure_reason == "first_previous_hash"
    engine.dispose()


def test_ledger_has_no_update_or_delete_repository_api():
    from backend.trading import ledger

    assert "update_event" not in ledger.__all__
    assert "delete_event" not in ledger.__all__
    public_functions = {
        name
        for name, value in vars(ledger).items()
        if inspect.isfunction(value) and not name.startswith("_")
    }
    assert public_functions == {
        "append_event",
        "verify_event_chain",
        "upsert_order_projection",
    }


def test_projection_create_preserves_decimal_strings_metadata_and_utc(session: Session):
    metadata = {"attempt": 1, "route": ["paper"]}
    report = execution_report(metadata=metadata)
    projection = upsert_order_projection(session, report)
    metadata["attempt"] = 99
    metadata["route"].append("live")

    session.expire_all()
    loaded = session.get(UnifiedOrder, projection.id)
    assert loaded is not None
    assert loaded.client_order_id == "client-1"
    assert loaded.venue == "alpaca_paper"
    assert loaded.status == "submitted"
    assert loaded.broker_order_id == "broker-1"
    assert loaded.rejection_reason is None
    assert loaded.filled_quantity == "0.000"
    assert loaded.filled_notional == "0.00"
    assert loaded.average_fill_price is None
    assert loaded.occurred_at == NOW
    assert type(loaded.occurred_at) is datetime
    assert loaded.occurred_at.tzinfo is timezone.utc
    assert loaded.order_metadata == {"attempt": 1, "route": ["paper"]}


def test_projection_repeat_is_idempotent_and_transition_updates_same_row(session: Session):
    submitted = execution_report()
    first = upsert_order_projection(session, submitted)
    second = upsert_order_projection(session, submitted)
    assert second.id == first.id
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 1

    filled = execution_report(
        status=OrderStatus.FILLED,
        filled_quantity=Decimal("1.2300"),
        filled_notional=Decimal("123.4500"),
        average_fill_price=Decimal("100.3658536585365853658536585"),
        occurred_at=NOW + timedelta(minutes=1),
        metadata={"attempt": 2, "liquidity": "simulated"},
    )
    updated = upsert_order_projection(session, filled)
    assert updated.id == first.id
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 1
    assert updated.status == "filled"
    assert updated.filled_quantity == "1.2300"
    assert updated.filled_notional == "123.4500"
    assert updated.average_fill_price == "100.3658536585365853658536585"
    assert updated.occurred_at == NOW + timedelta(minutes=1)
    assert updated.order_metadata == {"attempt": 2, "liquidity": "simulated"}


def test_projection_flushes_without_commit_and_rollback_removes_create(session: Session):
    projection = upsert_order_projection(session, execution_report())
    assert projection.id is not None
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 1
    session.rollback()
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 0


def test_projection_requires_exact_execution_report_before_virtual_behavior(session: Session):
    class HostileReport(ExecutionReport):
        dump_calls: ClassVar[int] = 0

        def model_dump(self, *args, **kwargs):
            type(self).dump_calls += 1
            raise RuntimeError("caller-controlled model dump sentinel")

    hostile = HostileReport(**execution_report().model_dump())
    for candidate in (hostile, object(), None):
        with pytest.raises(LedgerValidationError, match="^invalid execution report$"):
            upsert_order_projection(session, candidate)  # type: ignore[arg-type]
    assert HostileReport.dump_calls == 0
    assert session.scalar(select(func.count()).select_from(UnifiedOrder)) == 0


def test_ledger_and_projection_do_not_mutate_legacy_trade_or_signal(session: Session):
    trade = Trade(
        signal_id=10,
        market_ticker="KXHIGHNY-26AUG24-T85",
        platform="kalshi",
        event_slug="nyc-high-temp",
        market_type="weather",
        direction="up",
        entry_price=0.42,
        size=25.0,
    )
    signal = Signal(
        market_ticker="KXHIGHNY-26AUG24-T85",
        platform="kalshi",
        market_type="weather",
        direction="up",
        model_probability=0.61,
        market_price=0.42,
        edge=0.19,
        confidence=0.8,
        kelly_fraction=0.1,
        suggested_size=25.0,
        sources={"weather": "fixture"},
        reasoning="fixture",
    )
    session.add_all([trade, signal])
    session.flush()
    before_trade = (trade.market_type, trade.entry_price, trade.size, trade.settled)
    before_signal = (signal.market_type, signal.edge, signal.executed)

    append_event(session, event_input())
    upsert_order_projection(session, execution_report())

    session.refresh(trade)
    session.refresh(signal)
    assert (trade.market_type, trade.entry_price, trade.size, trade.settled) == before_trade
    assert (signal.market_type, signal.edge, signal.executed) == before_signal
