"""Database models and connection for Weather Edge."""
from datetime import datetime, timezone
from sqlalchemy import create_engine, Column, Integer, String, Float, DateTime, Boolean, JSON, text, inspect
from sqlalchemy.orm import declarative_base, sessionmaker

from backend.config import settings

engine = create_engine(
    settings.DATABASE_URL,
    connect_args={"check_same_thread": False} if "sqlite" in settings.DATABASE_URL else {},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


class Trade(Base):
    """Weather Edge paper/live trade record."""
    __tablename__ = "trades"

    id = Column(Integer, primary_key=True, index=True)
    signal_id = Column(Integer, index=True)
    market_ticker = Column(String, index=True)
    platform = Column(String, default="kalshi")
    event_slug = Column(String, nullable=True)
    market_type = Column(String, default="weather", index=True)

    direction = Column(String)  # "yes" or "no"
    entry_price = Column(Float)
    size = Column(Float)  # dollar stake
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    settled = Column(Boolean, default=False)
    settlement_time = Column(DateTime, nullable=True)
    settlement_value = Column(Float, nullable=True)  # 1.0=Yes won, 0.0=No won
    result = Column(String, default="pending")  # pending, win, loss, push
    pnl = Column(Float, nullable=True)

    model_probability = Column(Float)
    market_price_at_entry = Column(Float)
    edge_at_entry = Column(Float)


class BotState(Base):
    """Weather Edge runtime state and paper P&L stats."""
    __tablename__ = "bot_state"

    id = Column(Integer, primary_key=True)
    bankroll = Column(Float, default=10000.0)
    total_trades = Column(Integer, default=0)
    winning_trades = Column(Integer, default=0)
    total_pnl = Column(Float, default=0.0)
    last_run = Column(DateTime, nullable=True)
    is_running = Column(Boolean, default=False)


class Signal(Base):
    """Weather Edge signal generated from Kalshi markets, GFS ensemble, and METAR."""
    __tablename__ = "signals"

    id = Column(Integer, primary_key=True, index=True)
    market_ticker = Column(String, index=True)
    platform = Column(String, default="kalshi")
    market_type = Column(String, default="weather", index=True)
    timestamp = Column(DateTime, default=lambda: datetime.now(timezone.utc), index=True)

    direction = Column(String)  # "yes" or "no"
    model_probability = Column(Float)
    market_price = Column(Float)
    edge = Column(Float)
    confidence = Column(Float)

    kelly_fraction = Column(Float)
    suggested_size = Column(Float)
    sources = Column(JSON)
    reasoning = Column(String)
    executed = Column(Boolean, default=False)

    actual_outcome = Column(String, nullable=True)  # "yes" or "no"
    outcome_correct = Column(Boolean, nullable=True)
    settlement_value = Column(Float, nullable=True)  # 1.0=Yes won, 0.0=No won
    settled_at = Column(DateTime, nullable=True)


def init_db():
    Base.metadata.create_all(bind=engine)
    ensure_schema()


def ensure_schema():
    """Keep old local SQLite DBs compatible with current Weather Edge schema."""
    inspector = inspect(engine)
    try:
        trade_columns = [col["name"] for col in inspector.get_columns("trades")]
    except Exception:
        return

    with engine.connect() as conn:
        for col, coltype in [
            ("event_slug", "VARCHAR"),
            ("market_type", "VARCHAR DEFAULT 'weather'"),
        ]:
            if col not in trade_columns:
                try:
                    with conn.begin():
                        conn.execute(text(f"ALTER TABLE trades ADD COLUMN {col} {coltype}"))
                except Exception:
                    pass

        try:
            signal_columns = [col["name"] for col in inspector.get_columns("signals")]
        except Exception:
            signal_columns = []
        for col, coltype in [
            ("actual_outcome", "TEXT"),
            ("outcome_correct", "BOOLEAN"),
            ("settlement_value", "FLOAT"),
            ("settled_at", "DATETIME"),
            ("market_type", "VARCHAR DEFAULT 'weather'"),
        ]:
            if signal_columns and col not in signal_columns:
                try:
                    with conn.begin():
                        conn.execute(text(f"ALTER TABLE signals ADD COLUMN {col} {coltype}"))
                except Exception:
                    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
