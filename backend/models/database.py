"""Database models and connection for BTC 5-min trading bot."""
from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    Integer,
    JSON,
    String,
    UniqueConstraint,
    create_engine,
    inspect,
    text,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.types import TypeDecorator
import enum

from backend.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {}
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class UTCDateTime(TypeDecorator):
    """Persist UTC values portably and always restore exact aware UTC datetimes."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        failed = False
        normalized = None
        try:
            if type(value) is not datetime or value.tzinfo is None:
                raise ValueError
            offset = value.utcoffset()
            if offset != timezone.utc.utcoffset(None):
                raise ValueError
            normalized = datetime(
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
            failed = True
        if failed:
            raise ValueError("datetime must be an exact UTC datetime") from None
        return normalized.replace(tzinfo=None) if dialect.name == "sqlite" else normalized

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        failed = False
        normalized = None
        try:
            if type(value) is not datetime:
                raise ValueError
            if value.tzinfo is not None:
                offset = value.utcoffset()
                if offset != timezone.utc.utcoffset(None):
                    raise ValueError
            normalized = datetime(
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
            failed = True
        if failed:
            raise ValueError("stored datetime must be an exact UTC datetime") from None
        return normalized


class Trade(Base):
    """Simulated trades for tracking P&L."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, index=True)
    market_ticker = Column(String, index=True)
    platform = Column(String)
    event_slug = Column(String, nullable=True)
    market_type = Column(String, default="btc", index=True)  # "btc" or "weather"

    # Trade details
    direction = Column(String)  # "up" or "down"
    entry_price = Column(Float)
    size = Column(Float)
    timestamp = Column(DateTime, default=datetime.utcnow)

    # Settlement
    settled = Column(Boolean, default=False)
    settlement_time = Column(DateTime, nullable=True)
    settlement_value = Column(Float, nullable=True)  # 1.0=Up won, 0.0=Down won
    result = Column(String, default="pending")  # pending, win, loss, push, exited
    pnl = Column(Float, nullable=True)

    # Open-position exit / cash-out tracking
    closed_early = Column(Boolean, default=False, index=True)
    exit_time = Column(DateTime, nullable=True)
    exit_price = Column(Float, nullable=True)
    exit_size = Column(Float, nullable=True)
    exit_reason = Column(String, nullable=True)
    exit_policy = Column(String, nullable=True)
    exit_evidence = Column(JSON, nullable=True)
    unrealized_pnl = Column(Float, nullable=True)
    last_mark_price = Column(Float, nullable=True)
    last_mark_time = Column(DateTime, nullable=True)
    last_risk_action = Column(String, nullable=True)
    last_risk_reasons = Column(JSON, nullable=True)
    last_risk_source_status = Column(String, nullable=True)
    last_risk_evidence = Column(JSON, nullable=True)

    # Model performance tracking
    model_probability = Column(Float)
    market_price_at_entry = Column(Float)
    edge_at_entry = Column(Float)


class BtcPriceSnapshot(Base):
    """Cached BTC prices for momentum calculation."""
    __tablename__ = "btc_price_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    price = Column(Float)
    source = Column(String, default="coingecko")


class RottenTomatoesSourceState(Base):
    """Direct public Rotten Tomatoes source snapshots for RT market calibration."""
    __tablename__ = "rotten_tomatoes_source_states"

    id = Column(Integer, primary_key=True, index=True)
    captured_at = Column(DateTime, default=datetime.utcnow, index=True)
    title = Column(String, index=True)
    event_slug = Column(String, nullable=True, index=True)
    source_url = Column(String)
    source_method = Column(String)
    tomatometer_score = Column(Integer, nullable=True)
    review_count = Column(Integer, nullable=True)
    direct_source_status = Column(String, index=True)
    timing_risk_label = Column(String)
    cutoff_time = Column(String, nullable=True)


class BotState(Base):
    """Bot state and statistics."""
    __tablename__ = "bot_state"

    id = Column(Integer, primary_key=True)
    bankroll = Column(Float, default=10000.0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    last_run = Column(DateTime, nullable=True)
    is_running = Column(Boolean, default=False)


class Signal(Base):
    """Trading signals generated by the bot."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    market_ticker = Column(String, index=True)
    platform = Column(String)
    market_type = Column(String, default="btc", index=True)  # "btc" or "weather"
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)

    direction = Column(String)
    model_probability = Column(Float)
    market_price = Column(Float)
    edge = Column(Float)
    confidence = Column(Float)

    kelly_fraction = Column(Float)
    suggested_size = Column(Float)

    sources = Column(JSON)
    reasoning = Column(String)

    executed = Column(Boolean, default=False)

    # Calibration tracking — filled after settlement
    actual_outcome = Column(String, nullable=True)    # "up" or "down" — actual market result
    outcome_correct = Column(Boolean, nullable=True)   # did our direction prediction match?
    settlement_value = Column(Float, nullable=True)     # 1.0=UP won, 0.0=DOWN won
    settled_at = Column(DateTime, nullable=True)        # when we recorded the outcome


class TradingEvent(Base):
    """Immutable-at-the-repository-boundary event in an aggregate hash chain."""

    __tablename__ = "trading_events"
    __table_args__ = (
        UniqueConstraint("event_id", name="uq_trading_events_event_id"),
        UniqueConstraint("event_hash", name="uq_trading_events_event_hash"),
        UniqueConstraint(
            "aggregate_id", "sequence", name="uq_trading_events_aggregate_sequence"
        ),
        CheckConstraint("length(trim(event_id)) > 0", name="ck_trading_events_event_id"),
        CheckConstraint(
            "length(trim(aggregate_id)) > 0", name="ck_trading_events_aggregate_id"
        ),
        CheckConstraint("sequence > 0", name="ck_trading_events_sequence"),
        CheckConstraint(
            "length(trim(event_type)) > 0", name="ck_trading_events_event_type"
        ),
        CheckConstraint("length(previous_hash) = 64", name="ck_trading_events_previous_hash"),
        CheckConstraint("length(event_hash) = 64", name="ck_trading_events_event_hash"),
    )

    id = Column(Integer, primary_key=True)
    event_id = Column(String, nullable=False, index=True)
    aggregate_id = Column(String, nullable=False, index=True)
    sequence = Column(Integer, nullable=False)
    event_type = Column(String, nullable=False)
    occurred_at = Column(UTCDateTime(), nullable=False)
    payload = Column(JSON, nullable=False)
    previous_hash = Column(String(64), nullable=False)
    event_hash = Column(String(64), nullable=False, index=True)


class UnifiedOrder(Base):
    """Mutable idempotent projection of normalized execution reports."""

    __tablename__ = "unified_orders"
    __table_args__ = (
        UniqueConstraint("client_order_id", name="uq_unified_orders_client_order_id"),
        CheckConstraint(
            "length(trim(client_order_id)) > 0", name="ck_unified_orders_client_order_id"
        ),
        CheckConstraint("length(trim(venue)) > 0", name="ck_unified_orders_venue"),
        CheckConstraint("length(trim(status)) > 0", name="ck_unified_orders_status"),
    )

    id = Column(Integer, primary_key=True)
    client_order_id = Column(String, nullable=False, index=True)
    # Order identity, copied from the typed NormalizedOrder at submit time.
    # Nullable because a later execution report updates the same row without
    # restating the order, and because rows written before these columns
    # existed cannot be reconstructed.
    proposal_id = Column(String, nullable=True, index=True)
    asset_class = Column(String, nullable=True)
    symbol = Column(String, nullable=True)
    side = Column(String, nullable=True)
    venue = Column(String, nullable=False)
    status = Column(String, nullable=False)
    broker_order_id = Column(String, nullable=True)
    rejection_reason = Column(String, nullable=True)
    filled_quantity = Column(String, nullable=False)
    filled_notional = Column(String, nullable=False)
    average_fill_price = Column(String, nullable=True)
    occurred_at = Column(UTCDateTime(), nullable=False)
    order_metadata = Column("metadata", JSON, nullable=False)


class MirroredPortfolioSnapshot(Base):
    """A read-only mirror of an external brokerage account, as reported by an agent.

    This table is deliberately outside the trading domain's portfolio state.
    Nothing in risk.py or service.py reads it: a snapshot is an *observation*
    an agent pushed, not account state the risk gate may size against. The
    payload is the already-normalised, already-masked form -- raw broker
    responses never reach this row.
    """

    __tablename__ = "mirrored_portfolio_snapshots"

    id = Column(Integer, primary_key=True)
    venue = Column(String, nullable=False, index=True)
    captured_at = Column(UTCDateTime(), nullable=False, index=True)
    source_agent = Column(String, nullable=False)
    account_count = Column(Integer, nullable=False)
    position_count = Column(Integer, nullable=False)
    total_value = Column(String, nullable=False)
    payload = Column(JSON, nullable=False)


class AILog(Base):
    """Log of all AI API calls."""
    __tablename__ = "ai_logs"

    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(DateTime, default=datetime.utcnow, index=True)
    provider = Column(String, index=True)
    model = Column(String)

    prompt = Column(String)
    response = Column(String)
    call_type = Column(String, index=True)

    latency_ms = Column(Float)
    tokens_used = Column(Integer)
    cost_usd = Column(Float)

    related_market = Column(String, nullable=True)
    success = Column(Boolean, default=True)
    error = Column(String, nullable=True)


class ScanLog(Base):
    """Log of each market scan run."""
    __tablename__ = "scan_logs"

    id = Column(Integer, primary_key=True, index=True)
    run_id = Column(String, unique=True, index=True)
    started_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)

    categories_scanned = Column(JSON)
    platforms_scanned = Column(JSON)

    markets_found = Column(Integer, default=0)
    signals_generated = Column(Integer, default=0)
    trades_executed = Column(Integer, default=0)

    ai_calls_made = Column(Integer, default=0)
    ai_cost_usd = Column(Float, default=0.0)

    success = Column(Boolean, default=True)
    error = Column(String, nullable=True)


def init_db():
    """Initialize database tables."""
    Base.metadata.create_all(bind=engine)
    ensure_schema()


def ensure_schema():
    """Ensure newer schema fields exist even if migration wasn't run."""
    inspector = inspect(engine)

    # Order identity columns on unified_orders. Added after the table shipped,
    # so an existing ledger needs them applied in place. This runs before the
    # trades inspection below, which returns early on a database that has no
    # legacy trades table -- a path that would otherwise skip this migration.
    try:
        unified_order_columns = [col["name"] for col in inspector.get_columns("unified_orders")]
    except Exception:
        unified_order_columns = []

    if unified_order_columns:
        with engine.connect() as conn:
            for col in ("proposal_id", "asset_class", "symbol", "side"):
                if col not in unified_order_columns:
                    try:
                        with conn.begin():
                            conn.execute(
                                text(f"ALTER TABLE unified_orders ADD COLUMN {col} VARCHAR")
                            )
                    except Exception:
                        pass  # column already exists

    try:
        columns = [col["name"] for col in inspector.get_columns("trades")]
    except Exception:
        return

    if "event_slug" not in columns:
        stmt = "ALTER TABLE trades ADD COLUMN event_slug VARCHAR"
        if engine.dialect.name not in ("sqlite", "mysql"):
            stmt = "ALTER TABLE trades ADD COLUMN IF NOT EXISTS event_slug VARCHAR"

        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text(stmt))

    if "market_type" not in columns:
        with engine.connect() as conn:
            with conn.begin():
                conn.execute(text("ALTER TABLE trades ADD COLUMN market_type VARCHAR DEFAULT 'btc'"))

    trade_exit_columns = [
        ("closed_early", "BOOLEAN DEFAULT 0"),
        ("exit_time", "DATETIME"),
        ("exit_price", "FLOAT"),
        ("exit_size", "FLOAT"),
        ("exit_reason", "VARCHAR"),
        ("exit_policy", "VARCHAR"),
        ("exit_evidence", "JSON"),
        ("unrealized_pnl", "FLOAT"),
        ("last_mark_price", "FLOAT"),
        ("last_mark_time", "DATETIME"),
        ("last_risk_action", "VARCHAR"),
        ("last_risk_reasons", "JSON"),
        ("last_risk_source_status", "VARCHAR"),
        ("last_risk_evidence", "JSON"),
    ]
    with engine.connect() as conn:
        for col, coltype in trade_exit_columns:
            if col not in columns:
                try:
                    with conn.begin():
                        conn.execute(text(f"ALTER TABLE trades ADD COLUMN {col} {coltype}"))
                except Exception:
                    pass  # column already exists

    # Add calibration columns to signals table
    try:
        signal_columns = [col["name"] for col in inspector.get_columns("signals")]
    except Exception:
        signal_columns = []

    if signal_columns:
        with engine.connect() as conn:
            for col, coltype in [
                ("actual_outcome", "TEXT"),
                ("outcome_correct", "BOOLEAN"),
                ("settlement_value", "FLOAT"),
                ("settled_at", "DATETIME"),
                ("market_type", "VARCHAR DEFAULT 'btc'"),
            ]:
                if col not in signal_columns:
                    try:
                        with conn.begin():
                            conn.execute(text(f"ALTER TABLE signals ADD COLUMN {col} {coltype}"))
                    except Exception:
                        pass  # column already exists


def get_db():
    """Get database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
