"""The identity columns must reach a ledger that predates them.

unified_orders shipped without symbol/side, so an existing Archives ledger has
rows and a table without those columns. Base.metadata.create_all does not alter
an existing table, which makes ensure_schema the only thing standing between a
working upgrade and a startup that fails on every order write.
"""

from sqlalchemy import create_engine, inspect, text

from backend.models import database


IDENTITY_COLUMNS = {"proposal_id", "asset_class", "symbol", "side"}


def legacy_unified_orders_engine(tmp_path, name="legacy_orders.sqlite"):
    """A unified_orders table exactly as it existed before the identity columns."""
    engine = create_engine(
        f"sqlite:///{tmp_path / name}", connect_args={"check_same_thread": False}
    )
    with engine.connect() as conn:
        with conn.begin():
            conn.execute(
                text(
                    """
                    CREATE TABLE unified_orders (
                        id INTEGER PRIMARY KEY,
                        client_order_id VARCHAR NOT NULL,
                        venue VARCHAR NOT NULL,
                        status VARCHAR NOT NULL,
                        broker_order_id VARCHAR,
                        rejection_reason VARCHAR,
                        filled_quantity VARCHAR NOT NULL,
                        filled_notional VARCHAR NOT NULL,
                        average_fill_price VARCHAR,
                        occurred_at DATETIME NOT NULL,
                        metadata JSON NOT NULL
                    )
                    """
                )
            )
            conn.execute(
                text(
                    """
                    INSERT INTO unified_orders (
                        id, client_order_id, venue, status, filled_quantity,
                        filled_notional, occurred_at, metadata
                    ) VALUES (1, 'pre-existing-order', 'polymarket_paper', 'filled',
                        '89.285714', '49.99999984', '2026-08-24 12:30:45', '{}')
                    """
                )
            )
    return engine


def test_ensure_schema_adds_identity_columns_to_an_existing_orders_table(
    tmp_path, monkeypatch
):
    engine = legacy_unified_orders_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)

    database.ensure_schema()

    columns = {column["name"] for column in inspect(engine).get_columns("unified_orders")}
    assert IDENTITY_COLUMNS.issubset(columns)


def test_migration_preserves_the_rows_it_finds(tmp_path, monkeypatch):
    """An ALTER that dropped history would be worse than the missing columns."""
    engine = legacy_unified_orders_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)

    database.ensure_schema()

    with engine.connect() as conn:
        row = conn.execute(
            text(
                "SELECT client_order_id, filled_notional, symbol "
                "FROM unified_orders WHERE id = 1"
            )
        ).mappings().one()

    assert row["client_order_id"] == "pre-existing-order"
    assert row["filled_notional"] == "49.99999984"
    assert row["symbol"] is None, "a pre-existing row has no identity to invent"


def test_migration_runs_without_the_legacy_trades_table(tmp_path, monkeypatch):
    """ensure_schema returns early when trades is absent; this must run first.

    A fresh unified deployment has no legacy trades table at all, and that is
    exactly the database where a skipped migration would go unnoticed.
    """
    engine = legacy_unified_orders_engine(tmp_path, name="no_trades.sqlite")
    monkeypatch.setattr(database, "engine", engine)
    assert "trades" not in inspect(engine).get_table_names()

    database.ensure_schema()

    columns = {column["name"] for column in inspect(engine).get_columns("unified_orders")}
    assert IDENTITY_COLUMNS.issubset(columns)


def test_migration_is_idempotent(tmp_path, monkeypatch):
    engine = legacy_unified_orders_engine(tmp_path)
    monkeypatch.setattr(database, "engine", engine)

    database.ensure_schema()
    database.ensure_schema()

    columns = [column["name"] for column in inspect(engine).get_columns("unified_orders")]
    for column in IDENTITY_COLUMNS:
        assert columns.count(column) == 1


def test_model_and_migration_agree_on_the_identity_columns():
    """A column added to one and not the other is a silent divergence."""
    model_columns = set(database.UnifiedOrder.__table__.columns.keys())
    assert IDENTITY_COLUMNS.issubset(model_columns)
