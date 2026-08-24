"""Append-only hash-chained events and idempotent order projections.

Repository functions flush but never commit.  After a conflict raised during ``flush``,
the caller must roll back its SQLAlchemy transaction before reusing the session.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from typing import Any

import sqlalchemy
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from backend.models.database import TradingEvent, UnifiedOrder
from backend.trading.domain import ExecutionReport


ZERO_CHAIN_HASH = "0" * 64
_LOWER_HEX = frozenset("0123456789abcdef")


class LedgerError(RuntimeError):
    """Base class for fixed, caller-safe repository errors."""


class LedgerValidationError(LedgerError):
    """A repository boundary received an invalid value."""


class LedgerSequenceError(LedgerError):
    """An event did not continue its aggregate's sequence."""


class LedgerConflictError(LedgerError):
    """A unique ledger identity already exists."""


class LedgerStorageError(LedgerError):
    """A ledger storage dependency failed."""


@dataclasses.dataclass(frozen=True, slots=True)
class LedgerEventInput:
    event_id: str
    aggregate_id: str
    sequence: int
    event_type: str
    occurred_at: datetime
    payload: dict[str, object]


@dataclasses.dataclass(frozen=True, slots=True)
class ChainVerification:
    aggregate_id: str
    valid: bool
    event_count: int
    failure_reason: str | None = None


def _plain_json(value: object) -> object:
    value_type = type(value)
    if value is None or value_type in (bool, str, int):
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise ValueError
        return value
    if value_type is list:
        return [_plain_json(item) for item in value]
    if value_type is dict:
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError
            result[key] = _plain_json(item)
        return result
    raise ValueError


def _plain_json_object(value: object) -> dict[str, object]:
    if type(value) is not dict:
        raise ValueError
    result = _plain_json(value)
    if type(result) is not dict:
        raise ValueError
    return result


def _plain_domain_json(value: object) -> object:
    """Thaw the domain model's trusted immutable JSON representation."""
    value_type = type(value)
    if value is None or value_type in (bool, str, int):
        return value
    if value_type is float:
        if not math.isfinite(value):
            raise ValueError
        return value
    if isinstance(value, Mapping):
        result: dict[str, object] = {}
        for key, item in value.items():
            if type(key) is not str:
                raise ValueError
            result[key] = _plain_domain_json(item)
        return result
    if value_type in (list, tuple):
        return [_plain_domain_json(item) for item in value]
    raise ValueError


def _domain_json_object(value: object) -> dict[str, object]:
    result = _plain_domain_json(value)
    if type(result) is not dict:
        raise ValueError
    return result


def _nonblank_string(value: object) -> str:
    if type(value) is not str or not value.strip():
        raise ValueError
    return value


def _utc_datetime(value: object) -> datetime:
    try:
        if type(value) is not datetime or value.tzinfo is None:
            raise ValueError
        if value.utcoffset() != timedelta(0):
            raise ValueError
        return datetime(
            value.year,
            value.month,
            value.day,
            value.hour,
            value.minute,
            value.second,
            value.microsecond,
            tzinfo=timezone.utc,
            fold=value.fold,
        )
    except Exception:
        raise ValueError from None


def _timestamp_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _is_hash(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in _LOWER_HEX for character in value)
    )


def _event_document(
    *,
    event_id: str,
    aggregate_id: str,
    sequence: int,
    event_type: str,
    occurred_at: datetime,
    payload: dict[str, object],
    previous_hash: str,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "aggregate_id": aggregate_id,
        "sequence": sequence,
        "event_type": event_type,
        "occurred_at": _timestamp_text(occurred_at),
        "payload": payload,
        "previous_hash": previous_hash,
    }


def _hash_document(document: dict[str, object]) -> str:
    encoded = json.dumps(
        document,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _validated_event(event: object) -> tuple[str, str, int, str, datetime, dict[str, object]]:
    try:
        if type(event) is not LedgerEventInput:
            raise ValueError
        event_id = _nonblank_string(event.event_id)
        aggregate_id = _nonblank_string(event.aggregate_id)
        if type(event.sequence) is not int or event.sequence <= 0:
            raise ValueError
        event_type = _nonblank_string(event.event_type)
        occurred_at = _utc_datetime(event.occurred_at)
        payload = _plain_json_object(event.payload)
        return event_id, aggregate_id, event.sequence, event_type, occurred_at, payload
    except Exception:
        raise LedgerValidationError("invalid ledger event") from None


def _storage_scalar(session: Session, statement: object) -> Any:
    failed = False
    result = None
    try:
        result = session.scalar(statement)
    except Exception:
        failed = True
    if failed:
        raise LedgerStorageError("ledger storage failed") from None
    return result


def _add_and_flush(
    session: Session, pending: object | None, conflict_message: str
) -> None:
    conflict = False
    storage_failure = False
    try:
        if pending is not None:
            session.add(pending)
        session.flush()
    except IntegrityError:
        conflict = True
    except Exception:
        storage_failure = True
    if conflict:
        raise LedgerConflictError(conflict_message) from None
    if storage_failure:
        raise LedgerStorageError("ledger storage failed") from None


def append_event(session: Session, event: LedgerEventInput) -> TradingEvent:
    """Append one contiguous event and flush it without committing."""
    event_id, aggregate_id, sequence, event_type, occurred_at, payload = _validated_event(event)

    duplicate_id = _storage_scalar(
        session,
        sqlalchemy.select(TradingEvent.id).where(TradingEvent.event_id == event_id)
    )
    duplicate_sequence = _storage_scalar(
        session,
        sqlalchemy.select(TradingEvent.id).where(
            TradingEvent.aggregate_id == aggregate_id,
            TradingEvent.sequence == sequence,
        )
    )
    if duplicate_id is not None or duplicate_sequence is not None:
        raise LedgerConflictError("ledger event conflicts with existing data")

    prior = _storage_scalar(
        session,
        sqlalchemy.select(TradingEvent)
        .where(TradingEvent.aggregate_id == aggregate_id)
        .order_by(TradingEvent.sequence.desc())
        .limit(1)
    )
    if prior is None:
        if sequence != 1:
            raise LedgerSequenceError("invalid ledger sequence")
        previous_hash = ZERO_CHAIN_HASH
    else:
        if sequence != prior.sequence + 1 or not _is_hash(prior.event_hash):
            raise LedgerSequenceError("invalid ledger sequence")
        previous_hash = prior.event_hash

    document = _event_document(
        event_id=event_id,
        aggregate_id=aggregate_id,
        sequence=sequence,
        event_type=event_type,
        occurred_at=occurred_at,
        payload=payload,
        previous_hash=previous_hash,
    )
    stored = TradingEvent(
        event_id=event_id,
        aggregate_id=aggregate_id,
        sequence=sequence,
        event_type=event_type,
        occurred_at=occurred_at,
        payload=payload,
        previous_hash=previous_hash,
        event_hash=_hash_document(document),
    )
    _add_and_flush(session, stored, "ledger event conflicts with existing data")
    return stored


def verify_event_chain(session: Session, aggregate_id: str) -> ChainVerification:
    """Verify one aggregate without mutation; an empty chain is valid."""
    try:
        normalized_aggregate_id = _nonblank_string(aggregate_id)
    except Exception:
        raise LedgerValidationError("invalid aggregate id") from None

    try:
        events = list(
            session.scalars(
                sqlalchemy.select(TradingEvent)
                .where(TradingEvent.aggregate_id == normalized_aggregate_id)
                .order_by(TradingEvent.sequence, TradingEvent.id)
            )
        )
    except Exception:
        return ChainVerification(normalized_aggregate_id, False, 0, "database_error")

    count = len(events)
    expected_previous = ZERO_CHAIN_HASH
    for index, event in enumerate(events, start=1):
        try:
            if type(event.sequence) is not int or event.sequence != index:
                return ChainVerification(normalized_aggregate_id, False, count, "sequence_gap")
            if index == 1 and event.previous_hash != ZERO_CHAIN_HASH:
                return ChainVerification(
                    normalized_aggregate_id, False, count, "first_previous_hash"
                )
            if event.previous_hash != expected_previous:
                return ChainVerification(
                    normalized_aggregate_id, False, count, "previous_hash_mismatch"
                )
            if not _is_hash(event.event_hash) or not _is_hash(event.previous_hash):
                return ChainVerification(normalized_aggregate_id, False, count, "malformed_event")
            event_id = _nonblank_string(event.event_id)
            row_aggregate_id = _nonblank_string(event.aggregate_id)
            event_type = _nonblank_string(event.event_type)
            occurred_at = _utc_datetime(event.occurred_at)
            payload = _plain_json_object(event.payload)
            expected_hash = _hash_document(
                _event_document(
                    event_id=event_id,
                    aggregate_id=row_aggregate_id,
                    sequence=event.sequence,
                    event_type=event_type,
                    occurred_at=occurred_at,
                    payload=payload,
                    previous_hash=event.previous_hash,
                )
            )
            if event.event_hash != expected_hash:
                return ChainVerification(
                    normalized_aggregate_id, False, count, "event_hash_mismatch"
                )
            expected_previous = event.event_hash
        except Exception:
            return ChainVerification(normalized_aggregate_id, False, count, "malformed_event")
    return ChainVerification(normalized_aggregate_id, True, count, None)


def upsert_order_projection(session: Session, report: ExecutionReport) -> UnifiedOrder:
    """Create or update one client-order projection, flushing without commit."""
    try:
        if type(report) is not ExecutionReport:
            raise ValueError
        client_order_id = _nonblank_string(report.client_order_id)
        occurred_at = _utc_datetime(report.occurred_at)
        order_metadata = _domain_json_object(report.metadata)
        venue = _nonblank_string(report.venue.value)
        status = _nonblank_string(report.status.value)
        broker_order_id = report.broker_order_id
        rejection_reason = report.rejection_reason
        if broker_order_id is not None:
            broker_order_id = _nonblank_string(broker_order_id)
        if rejection_reason is not None:
            rejection_reason = _nonblank_string(rejection_reason)
    except Exception:
        raise LedgerValidationError("invalid execution report") from None

    projection = _storage_scalar(
        session,
        sqlalchemy.select(UnifiedOrder).where(
            UnifiedOrder.client_order_id == client_order_id
        )
    )
    pending = None
    if projection is None:
        projection = UnifiedOrder(client_order_id=client_order_id)
        pending = projection

    projection.venue = venue
    projection.status = status
    projection.broker_order_id = broker_order_id
    projection.rejection_reason = rejection_reason
    projection.filled_quantity = str(report.filled_quantity)
    projection.filled_notional = str(report.filled_notional)
    projection.average_fill_price = (
        None if report.average_fill_price is None else str(report.average_fill_price)
    )
    projection.occurred_at = occurred_at
    projection.order_metadata = order_metadata
    _add_and_flush(session, pending, "order projection conflicts with existing data")
    return projection


__all__ = [
    "ZERO_CHAIN_HASH",
    "ChainVerification",
    "LedgerConflictError",
    "LedgerError",
    "LedgerEventInput",
    "LedgerSequenceError",
    "LedgerStorageError",
    "LedgerValidationError",
    "append_event",
    "upsert_order_projection",
    "verify_event_chain",
]
