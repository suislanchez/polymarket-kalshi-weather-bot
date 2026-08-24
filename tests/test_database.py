"""Fresh-schema and legacy readability regressions for database models."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session

from backend.models.database import Base, Signal, Trade, TradingEvent, UnifiedOrder


NOW = datetime(2026, 8, 24, 15, 0, tzinfo=timezone.utc)


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
