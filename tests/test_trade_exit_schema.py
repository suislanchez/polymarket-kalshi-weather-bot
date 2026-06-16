from sqlalchemy import create_engine, inspect, text

from backend.models import database


EXIT_COLUMNS = {
    "closed_early",
    "exit_time",
    "exit_price",
    "exit_size",
    "exit_reason",
    "exit_policy",
    "exit_evidence",
    "unrealized_pnl",
    "last_mark_price",
    "last_mark_time",
    "last_risk_action",
    "last_risk_reasons",
}


def test_ensure_schema_adds_open_position_exit_columns_to_existing_trades_table(tmp_path, monkeypatch):
    db_path = tmp_path / "legacy_trades.sqlite"
    engine = create_engine(f"sqlite:///{db_path}", connect_args={"check_same_thread": False})
    monkeypatch.setattr(database, "engine", engine)

    with engine.connect() as conn:
        with conn.begin():
            conn.execute(text("""
                CREATE TABLE trades (
                    id INTEGER PRIMARY KEY,
                    signal_id INTEGER,
                    market_ticker VARCHAR,
                    platform VARCHAR,
                    direction VARCHAR,
                    entry_price FLOAT,
                    size FLOAT,
                    timestamp DATETIME,
                    settled BOOLEAN,
                    settlement_time DATETIME,
                    settlement_value FLOAT,
                    result VARCHAR,
                    pnl FLOAT,
                    model_probability FLOAT,
                    market_price_at_entry FLOAT,
                    edge_at_entry FLOAT
                )
            """))
            conn.execute(text("""
                INSERT INTO trades (
                    id, signal_id, market_ticker, platform, direction, entry_price, size,
                    settled, result, model_probability, market_price_at_entry, edge_at_entry
                ) VALUES (1, 42, 'weather-denver-70-71', 'polymarket', 'yes', 0.45, 100.0,
                    0, 'pending', 0.40, 0.45, 0.05)
            """))

    database.ensure_schema()

    columns = {column["name"] for column in inspect(engine).get_columns("trades")}
    assert EXIT_COLUMNS.issubset(columns)

    with engine.connect() as conn:
        row = conn.execute(text("SELECT id, result, size FROM trades WHERE id = 1")).mappings().one()

    assert row["result"] == "pending"
    assert row["size"] == 100.0


def test_trade_model_declares_open_position_exit_columns():
    model_columns = set(database.Trade.__table__.columns.keys())

    assert EXIT_COLUMNS.issubset(model_columns)
