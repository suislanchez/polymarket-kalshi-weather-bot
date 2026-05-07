"""Weather trade settlement logic for Kalshi markets."""
from __future__ import annotations

from datetime import datetime
from typing import List, Optional, Tuple
import logging

from sqlalchemy.orm import Session

from backend.models.database import BotState, Signal, Trade

logger = logging.getLogger("trading_bot")


def calculate_pnl(trade: Trade, settlement_value: float) -> float:
    """
    Calculate dollar-stake P&L for a Yes/No trade.

    `trade.size` is dollars risked/staked, not contract count.
    settlement_value: 1.0 if Yes won, 0.0 if No won.
    """
    direction = trade.direction
    if direction == "up":
        direction = "yes"
    elif direction == "down":
        direction = "no"

    if direction == "yes":
        if settlement_value == 1.0:
            pnl = trade.size * ((1.0 / trade.entry_price) - 1.0) if trade.entry_price else 0.0
        else:
            pnl = -trade.size
    else:
        if settlement_value == 0.0:
            pnl = trade.size * ((1.0 / trade.entry_price) - 1.0) if trade.entry_price else 0.0
        else:
            pnl = -trade.size
    return round(pnl, 2)


async def check_weather_settlement(trade: Trade) -> Tuple[bool, Optional[float], Optional[float]]:
    is_resolved, settlement_value = await _fetch_kalshi_resolution(trade.market_ticker)
    if is_resolved and settlement_value is not None:
        return True, settlement_value, calculate_pnl(trade, settlement_value)
    return False, None, None


async def _fetch_kalshi_resolution(ticker: str) -> Tuple[bool, Optional[float]]:
    try:
        from backend.data.kalshi_client import KalshiClient, kalshi_credentials_present
        if not kalshi_credentials_present():
            return False, None
        client = KalshiClient()
        data = await client.get_market(ticker)
        market = data.get("market", data)
        status = market.get("status", "")
        result = (market.get("result", "") or "").lower()
        if status in ("finalized", "determined") and result:
            if result == "yes":
                return True, 1.0
            if result == "no":
                return True, 0.0
        return False, None
    except Exception as e:
        logger.warning(f"Failed to fetch Kalshi resolution for {ticker}: {e}")
        return False, None


async def settle_pending_trades(db: Session) -> List[Trade]:
    try:
        pending = db.query(Trade).filter(Trade.settled == False, Trade.market_type == "weather").all()
    except Exception as e:
        logger.error(f"Failed to query pending weather trades: {e}")
        return []

    settled_trades = []
    for trade in pending:
        try:
            is_settled, settlement_value, pnl = await check_weather_settlement(trade)
            if is_settled and settlement_value is not None:
                trade.settled = True
                trade.settlement_value = settlement_value
                trade.pnl = pnl
                trade.settlement_time = datetime.utcnow()
                if pnl is not None and pnl > 0:
                    trade.result = "win"
                elif pnl is not None and pnl < 0:
                    trade.result = "loss"
                else:
                    trade.result = "push"
                settled_trades.append(trade)

                if trade.signal_id:
                    linked_signal = db.query(Signal).filter(Signal.id == trade.signal_id).first()
                    if linked_signal:
                        actual_outcome = "yes" if settlement_value == 1.0 else "no"
                        linked_signal.actual_outcome = actual_outcome
                        linked_signal.outcome_correct = linked_signal.direction == actual_outcome
                        linked_signal.settlement_value = settlement_value
                        linked_signal.settled_at = datetime.utcnow()
        except Exception as e:
            logger.error(f"Failed to settle weather trade {trade.id}: {e}")
            continue

    if settled_trades:
        try:
            db.commit()
            logger.info(f"Settled {len(settled_trades)} weather trades")
        except Exception as e:
            logger.error(f"Failed to commit weather settlements: {e}")
            db.rollback()
            return []
    return settled_trades


async def update_bot_state_with_settlements(db: Session, settled_trades: List[Trade]) -> None:
    if not settled_trades:
        return
    try:
        state = db.query(BotState).first()
        if not state:
            logger.warning("Bot state not found")
            return
        for trade in settled_trades:
            if trade.pnl is not None:
                state.total_pnl += trade.pnl
                state.bankroll += trade.pnl
                if trade.result == "win":
                    state.winning_trades += 1
        db.commit()
        logger.info(f"Updated bot state: Bankroll ${state.bankroll:.2f}, P&L ${state.total_pnl:+.2f}")
    except Exception as e:
        logger.error(f"Failed to update bot state: {e}")
        db.rollback()
