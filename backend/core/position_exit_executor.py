"""Paper-only open-position exit executor."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from backend.core.position_risk import ExitRecommendation, RiskAction, calculate_exit_pnl
from backend.models.database import BotState, Trade


def _serialize_recommendation(recommendation: ExitRecommendation) -> dict[str, Any]:
    return {
        "action": recommendation.action.value,
        "reasons": list(recommendation.reasons),
        "exit_price": recommendation.exit_price,
        "exit_pnl": recommendation.exit_pnl,
        "unrealized_pnl": recommendation.unrealized_pnl,
        "model_probability_for_held_side": recommendation.model_probability_for_held_side,
        "market_probability_for_held_side": recommendation.market_probability_for_held_side,
        "source_status": recommendation.source_status,
        "evidence": dict(recommendation.evidence),
    }


def record_paper_exit(
    db: Session,
    trade: Trade,
    recommendation: ExitRecommendation,
    *,
    policy: str,
    exit_time: datetime | None = None,
) -> Trade:
    """Record a full paper cash-out for a trade and update paper BotState once.

    This never places live orders. It only mutates the simulation ledger after the
    recommendation layer has produced a decisive EXIT.
    """
    if recommendation.action != RiskAction.EXIT:
        raise ValueError(f"Recommendation is not an EXIT: {recommendation.action}")

    if getattr(trade, "settled", False) or getattr(trade, "closed_early", False):
        raise ValueError(f"Trade {getattr(trade, 'id', None)} is already closed")

    if recommendation.exit_price is None:
        raise ValueError("Cannot record paper exit without an exit price")

    realized_pnl = recommendation.exit_pnl
    if realized_pnl is None:
        realized_pnl = calculate_exit_pnl(
            entry_price=trade.entry_price,
            exit_price=recommendation.exit_price,
            size=trade.size,
        )

    now = exit_time or datetime.utcnow()
    evidence = _serialize_recommendation(recommendation)

    trade.closed_early = True
    trade.settled = True
    trade.result = "exited"
    trade.exit_time = now
    trade.settlement_time = now
    trade.exit_price = recommendation.exit_price
    trade.exit_size = trade.size
    trade.exit_reason = "; ".join(recommendation.reasons)
    trade.exit_policy = policy
    trade.exit_evidence = evidence
    trade.unrealized_pnl = recommendation.unrealized_pnl
    trade.last_mark_price = recommendation.exit_price
    trade.last_mark_time = now
    trade.last_risk_action = recommendation.action.value
    trade.last_risk_reasons = list(recommendation.reasons)
    trade.pnl = round(realized_pnl, 2)

    state = db.query(BotState).first()
    if state is not None:
        state.total_pnl = round((state.total_pnl or 0.0) + trade.pnl, 2)
        state.bankroll = round((state.bankroll or 0.0) + trade.pnl, 2)
        if trade.pnl > 0:
            state.winning_trades = (state.winning_trades or 0) + 1

    db.add(trade)
    db.commit()
    db.refresh(trade)
    return trade
