from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from backend.core.position_risk import ExitRecommendation, RiskAction
from backend.core.position_exit_executor import record_paper_exit
from backend.models.database import Base, BotState, Trade


def _session(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'exit_executor.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    return Session()


def _exit_recommendation():
    return ExitRecommendation(
        action=RiskAction.EXIT,
        reasons=["model probability below exit threshold", "thesis broken"],
        exit_price=0.10,
        exit_pnl=-77.78,
        unrealized_pnl=-77.78,
        model_probability_for_held_side=0.05,
        market_probability_for_held_side=0.10,
        source_status="fresh",
        evidence={"policy": "test_policy_v1"},
    )


def test_record_paper_exit_marks_trade_exited_and_updates_bot_state_once(tmp_path):
    db = _session(tmp_path)
    state = BotState(bankroll=1000.0, total_pnl=0.0, total_trades=1, winning_trades=0)
    trade = Trade(
        signal_id=1,
        market_ticker="weather-denver-70-71",
        platform="polymarket",
        event_slug="denver-weather",
        market_type="weather",
        direction="yes",
        entry_price=0.45,
        size=100.0,
        settled=False,
        result="pending",
        model_probability=0.40,
        market_price_at_entry=0.45,
        edge_at_entry=0.05,
    )
    db.add_all([state, trade])
    db.commit()

    exited = record_paper_exit(db, trade, _exit_recommendation(), policy="weather_exit_v1")

    assert exited.closed_early is True
    assert exited.settled is True
    assert exited.result == "exited"
    assert exited.exit_price == 0.10
    assert exited.exit_size == 100.0
    assert exited.exit_reason == "model probability below exit threshold; thesis broken"
    assert exited.exit_policy == "weather_exit_v1"
    assert exited.pnl == -77.78
    assert exited.exit_evidence["action"] == "exit"
    assert state.bankroll == 922.22
    assert state.total_pnl == -77.78


def test_record_paper_exit_rejects_non_exit_recommendations(tmp_path):
    db = _session(tmp_path)
    trade = Trade(
        market_ticker="btc-updown-5m",
        platform="polymarket",
        market_type="btc",
        direction="up",
        entry_price=0.50,
        size=40.0,
        settled=False,
        result="pending",
    )
    db.add(trade)
    db.commit()
    recommendation = ExitRecommendation(
        action=RiskAction.WATCH,
        reasons=["source/model evidence incomplete"],
        exit_price=0.10,
        exit_pnl=-32.0,
        unrealized_pnl=-32.0,
        model_probability_for_held_side=None,
        market_probability_for_held_side=0.10,
        source_status="missing",
    )

    try:
        record_paper_exit(db, trade, recommendation, policy="btc_exit_v1")
    except ValueError as exc:
        assert "not an EXIT" in str(exc)
    else:
        raise AssertionError("record_paper_exit should reject WATCH recommendations")


def test_record_paper_exit_rejects_already_closed_trade_without_double_counting(tmp_path):
    db = _session(tmp_path)
    state = BotState(bankroll=1000.0, total_pnl=0.0)
    trade = Trade(
        market_ticker="weather-denver-70-71",
        platform="polymarket",
        market_type="weather",
        direction="yes",
        entry_price=0.45,
        size=100.0,
        settled=False,
        result="pending",
    )
    db.add_all([state, trade])
    db.commit()

    record_paper_exit(db, trade, _exit_recommendation(), policy="weather_exit_v1")

    try:
        record_paper_exit(db, trade, _exit_recommendation(), policy="weather_exit_v1")
    except ValueError as exc:
        assert "already closed" in str(exc)
    else:
        raise AssertionError("record_paper_exit should reject already closed trades")

    assert state.bankroll == 922.22
    assert state.total_pnl == -77.78
