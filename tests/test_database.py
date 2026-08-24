"""Fresh-schema and legacy readability regressions for database models."""

from __future__ import annotations

import ast
from datetime import datetime, timedelta, timezone, tzinfo
import inspect as python_inspect
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import Column, MetaData, Table, create_engine, inspect, select
from sqlalchemy.orm import Session

from backend.models.database import (
    Base,
    Signal,
    Trade,
    TradingEvent,
    UTCDateTime,
    UnifiedOrder,
)


NOW = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)
BOUNDARY_VALUE = datetime(2026, 8, 24, 15, 1, 2, 345678, fold=1)


class CountingZeroOffset(tzinfo):
    def __init__(self):
        self.utcoffset_calls = 0

    def utcoffset(self, dt):
        self.utcoffset_calls += 1
        return timedelta(0)

    def dst(self, dt):
        raise AssertionError("dst must not be called")


class HostileOffset(tzinfo):
    def utcoffset(self, dt):
        raise RuntimeError("TZ_SECRET")


class InvalidOffset(tzinfo):
    def __init__(self, offset):
        self.offset = offset

    def utcoffset(self, dt):
        return self.offset


class HostileDatetime(datetime):
    @property
    def tzinfo(self):
        raise RuntimeError("SUBCLASS_SECRET")


@pytest.fixture
def sqlite_dialect():
    engine = create_engine("sqlite://")
    yield engine.dialect
    engine.dispose()


def assert_sanitized_datetime_error(call, message):
    with pytest.raises(ValueError) as raised:
        call()
    error = raised.value
    assert type(error) is ValueError
    assert str(error) == message
    rendered = f"{str(error)} {repr(error)}"
    for secret in ("TZ_SECRET", "SUBCLASS_SECRET", "RuntimeError", "HostileOffset"):
        assert secret not in rendered
    assert error.__cause__ is None
    assert error.__context__ is None


@pytest.fixture
def fresh_database(tmp_path: Path):
    engine = create_engine(f"sqlite:///{tmp_path / 'schema.sqlite3'}")
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


def test_fresh_schema_preserves_representative_weather_trade_and_signal(fresh_database):
    with Session(fresh_database) as session:
        trade = Trade(
            signal_id=17,
            market_ticker="KXHIGHNY-26AUG24-T85",
            platform="kalshi",
            event_slug="nyc-high-temp-aug-24",
            market_type="weather",
            direction="up",
            entry_price=0.43,
            size=35.5,
            timestamp=NOW.replace(tzinfo=None),
            settled=False,
            closed_early=False,
            model_probability=0.62,
            market_price_at_entry=0.43,
            edge_at_entry=0.19,
        )
        signal = Signal(
            market_ticker="KXHIGHNY-26AUG24-T85",
            platform="kalshi",
            market_type="weather",
            timestamp=NOW.replace(tzinfo=None),
            direction="up",
            model_probability=0.62,
            market_price=0.43,
            edge=0.19,
            confidence=0.81,
            kelly_fraction=0.10,
            suggested_size=35.5,
            sources={"forecast": "fixture", "stations": ["KNYC"]},
            reasoning="Representative legacy weather signal",
            executed=True,
            actual_outcome="up",
            outcome_correct=True,
            settlement_value=1.0,
            settled_at=NOW.replace(tzinfo=None),
        )
        session.add_all([trade, signal])
        session.commit()
        trade_id, signal_id = trade.id, signal.id

    with Session(fresh_database) as session:
        loaded_trade = session.get(Trade, trade_id)
        loaded_signal = session.get(Signal, signal_id)
        assert loaded_trade is not None
        assert loaded_signal is not None
        assert loaded_trade.market_ticker == "KXHIGHNY-26AUG24-T85"
        assert loaded_trade.event_slug == "nyc-high-temp-aug-24"
        assert loaded_trade.market_type == "weather"
        assert loaded_trade.entry_price == 0.43
        assert loaded_trade.size == 35.5
        assert loaded_trade.closed_early is False
        assert loaded_trade.model_probability == 0.62
        assert loaded_signal.market_type == "weather"
        assert loaded_signal.sources == {"forecast": "fixture", "stations": ["KNYC"]}
        assert loaded_signal.reasoning == "Representative legacy weather signal"
        assert loaded_signal.executed is True
        assert loaded_signal.actual_outcome == "up"
        assert loaded_signal.outcome_correct is True


def test_new_table_names_columns_indexes_and_constraints(fresh_database):
    schema = inspect(fresh_database)
    assert {"trading_events", "unified_orders"} <= set(schema.get_table_names())

    event_columns = {column["name"]: column for column in schema.get_columns("trading_events")}
    assert set(event_columns) == {
        "id",
        "event_id",
        "aggregate_id",
        "sequence",
        "event_type",
        "occurred_at",
        "payload",
        "previous_hash",
        "event_hash",
    }
    assert event_columns["event_id"]["nullable"] is False
    assert event_columns["aggregate_id"]["nullable"] is False
    assert event_columns["sequence"]["nullable"] is False
    assert event_columns["event_type"]["nullable"] is False
    assert event_columns["payload"]["nullable"] is False

    event_unique_sets = {
        tuple(constraint["column_names"])
        for constraint in schema.get_unique_constraints("trading_events")
    }
    assert ("event_id",) in event_unique_sets
    assert ("event_hash",) in event_unique_sets
    assert ("aggregate_id", "sequence") in event_unique_sets
    event_indexes = {
        tuple(index["column_names"]) for index in schema.get_indexes("trading_events")
    }
    assert ("aggregate_id",) in event_indexes

    order_columns = {column["name"]: column for column in schema.get_columns("unified_orders")}
    assert set(order_columns) == {
        "id",
        "client_order_id",
        "venue",
        "status",
        "broker_order_id",
        "rejection_reason",
        "filled_quantity",
        "filled_notional",
        "average_fill_price",
        "occurred_at",
        "metadata",
    }
    assert order_columns["client_order_id"]["nullable"] is False
    assert order_columns["venue"]["nullable"] is False
    assert order_columns["status"]["nullable"] is False
    assert order_columns["filled_quantity"]["nullable"] is False
    assert order_columns["filled_notional"]["nullable"] is False
    order_unique_sets = {
        tuple(constraint["column_names"])
        for constraint in schema.get_unique_constraints("unified_orders")
    }
    assert ("client_order_id",) in order_unique_sets
    order_indexes = {
        tuple(index["column_names"]) for index in schema.get_indexes("unified_orders")
    }
    assert ("client_order_id",) in order_indexes


def test_new_model_tables_are_bound_to_shared_base_without_changing_legacy_tables():
    assert TradingEvent.__table__.metadata is Base.metadata
    assert UnifiedOrder.__table__.metadata is Base.metadata
    assert Trade.__tablename__ == "trades"
    assert Signal.__tablename__ == "signals"
    assert TradingEvent.__tablename__ == "trading_events"
    assert UnifiedOrder.__tablename__ == "unified_orders"


def test_utc_datetime_result_accepts_none_and_exact_driver_datetimes(sqlite_dialect):
    utc_type = UTCDateTime()
    assert utc_type.process_result_value(None, sqlite_dialect) is None

    naive_result = utc_type.process_result_value(BOUNDARY_VALUE, sqlite_dialect)
    assert type(naive_result) is datetime
    assert naive_result == BOUNDARY_VALUE.replace(tzinfo=timezone.utc)
    assert naive_result.tzinfo is timezone.utc
    assert naive_result.microsecond == BOUNDARY_VALUE.microsecond
    assert naive_result.fold == BOUNDARY_VALUE.fold

    aware_value = BOUNDARY_VALUE.replace(tzinfo=timezone.utc)
    aware_result = utc_type.process_result_value(aware_value, sqlite_dialect)
    assert type(aware_result) is datetime
    assert aware_result == aware_value
    assert aware_result.tzinfo is timezone.utc


def test_utc_datetime_result_calls_custom_zero_offset_once_and_discards_it(sqlite_dialect):
    custom_timezone = CountingZeroOffset()
    value = BOUNDARY_VALUE.replace(tzinfo=custom_timezone)

    result = UTCDateTime().process_result_value(value, sqlite_dialect)

    assert custom_timezone.utcoffset_calls == 1
    assert type(result) is datetime
    assert result == BOUNDARY_VALUE.replace(tzinfo=timezone.utc)
    assert result.tzinfo is timezone.utc
    assert result.tzinfo is not custom_timezone


@pytest.mark.parametrize(
    "value",
    [
        BOUNDARY_VALUE.replace(tzinfo=HostileOffset()),
        BOUNDARY_VALUE.replace(tzinfo=timezone(timedelta(hours=1))),
        BOUNDARY_VALUE.replace(tzinfo=InvalidOffset(None)),
        BOUNDARY_VALUE.replace(tzinfo=InvalidOffset("invalid")),
        HostileDatetime(2026, 8, 24, 15, 1, 2, 345678),
        "2026-08-24T15:01:02Z",
        object(),
    ],
    ids=("hostile", "nonzero", "none-offset", "invalid-offset", "subclass", "string", "object"),
)
def test_utc_datetime_result_rejects_invalid_values_without_leaking(value, sqlite_dialect):
    assert_sanitized_datetime_error(
        lambda: UTCDateTime().process_result_value(value, sqlite_dialect),
        "stored datetime must be an exact UTC datetime",
    )


def test_utc_datetime_result_has_no_astimezone_virtual_path():
    source = python_inspect.getsource(UTCDateTime.process_result_value)
    tree = ast.parse(source.lstrip())
    assert not any(
        isinstance(node, ast.Attribute) and node.attr == "astimezone"
        for node in ast.walk(tree)
    )


def test_utc_datetime_bind_accepts_none_and_reconstructs_exact_values(sqlite_dialect):
    utc_type = UTCDateTime()
    assert utc_type.process_bind_param(None, sqlite_dialect) is None

    aware_value = BOUNDARY_VALUE.replace(tzinfo=timezone.utc)
    sqlite_result = utc_type.process_bind_param(aware_value, sqlite_dialect)
    assert type(sqlite_result) is datetime
    assert sqlite_result == BOUNDARY_VALUE
    assert sqlite_result.tzinfo is None
    assert sqlite_result.microsecond == BOUNDARY_VALUE.microsecond
    assert sqlite_result.fold == BOUNDARY_VALUE.fold

    postgres_result = utc_type.process_bind_param(
        aware_value, SimpleNamespace(name="postgresql")
    )
    assert type(postgres_result) is datetime
    assert postgres_result == aware_value
    assert postgres_result.tzinfo is timezone.utc


@pytest.mark.parametrize("dialect_name", ["sqlite", "postgresql"])
def test_utc_datetime_bind_calls_custom_zero_offset_once_and_discards_it(dialect_name):
    custom_timezone = CountingZeroOffset()
    value = BOUNDARY_VALUE.replace(tzinfo=custom_timezone)

    result = UTCDateTime().process_bind_param(value, SimpleNamespace(name=dialect_name))

    assert custom_timezone.utcoffset_calls == 1
    assert type(result) is datetime
    assert result.tzinfo is (None if dialect_name == "sqlite" else timezone.utc)
    assert result.tzinfo is not custom_timezone
    assert result.replace(tzinfo=None) == BOUNDARY_VALUE


@pytest.mark.parametrize(
    "value",
    [
        BOUNDARY_VALUE,
        BOUNDARY_VALUE.replace(tzinfo=HostileOffset()),
        BOUNDARY_VALUE.replace(tzinfo=timezone(timedelta(hours=-1))),
        BOUNDARY_VALUE.replace(tzinfo=InvalidOffset(None)),
        BOUNDARY_VALUE.replace(tzinfo=InvalidOffset("invalid")),
        HostileDatetime(2026, 8, 24, 15, 1, 2, 345678, tzinfo=timezone.utc),
    ],
    ids=("naive", "hostile", "nonzero", "none-offset", "invalid-offset", "subclass"),
)
def test_utc_datetime_bind_rejects_invalid_values_without_leaking(value, sqlite_dialect):
    assert_sanitized_datetime_error(
        lambda: UTCDateTime().process_bind_param(value, sqlite_dialect),
        "datetime must be an exact UTC datetime",
    )


def test_utc_datetime_real_sqlite_round_trip_returns_exact_aware_utc():
    engine = create_engine("sqlite://")
    metadata = MetaData()
    timestamps = Table(
        "utc_datetime_round_trip",
        metadata,
        Column("occurred_at", UTCDateTime(), nullable=False),
    )
    metadata.create_all(engine)
    value = BOUNDARY_VALUE.replace(tzinfo=timezone.utc, fold=0)

    with engine.begin() as connection:
        connection.execute(timestamps.insert().values(occurred_at=value))
        result = connection.execute(select(timestamps.c.occurred_at)).scalar_one()

    engine.dispose()
    assert type(result) is datetime
    assert result == value
    assert result.tzinfo is timezone.utc
    assert result.microsecond == value.microsecond
    assert result.fold == value.fold
