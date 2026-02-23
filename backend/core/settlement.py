"""Trade settlement logic for BTC 5-min markets using Polymarket API."""
import httpx
import json
import logging
from datetime import datetime
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from backend.models.database import Trade, BotState, Signal

logger = logging.getLogger("trading_bot")


async def fetch_polymarket_resolution(market_id: str, event_slug: Optional[str] = None) -> Tuple[bool, Optional[float]]:
    """
    Fetch actual market resolution from Polymarket API.

    For BTC 5-min markets, uses event slug to find the market.

    Returns: (is_resolved, settlement_value)
        - settlement_value: 1.0 if Up won, 0.0 if Down won
    """
    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            # Try event slug first (more reliable for BTC 5-min markets)
            if event_slug:
                response = await client.get(
                    "https://gamma-api.polymarket.com/events",
                    params={"slug": event_slug}
                )
                response.raise_for_status()
                events = response.json()

                if events:
                    event = events[0] if isinstance(events, list) else events
                    markets = event.get("markets", [])
                    if markets:
                        return _parse_market_resolution(markets[0])

            # Fallback: try market ID directly
            url = f"https://gamma-api.polymarket.com/markets/{market_id}"
            response = await client.get(url)

            if response.status_code == 404:
                return await _search_market_in_events(market_id)

            response.raise_for_status()
            market = response.json()
            return _parse_market_resolution(market)

    except Exception as e:
        logger.warning(f"Failed to fetch resolution for {event_slug or market_id}: {e}")
        return False, None


async def _search_market_in_events(market_id: str) -> Tuple[bool, Optional[float]]:
    """Search for market in events (both active and closed)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            for closed in [True, False]:
                params = {
                    "closed": str(closed).lower(),
                    "limit": 200
                }
                response = await client.get(
                    "https://gamma-api.polymarket.com/events",
                    params=params
                )
                response.raise_for_status()
                events = response.json()

                for event in events:
                    for market in event.get("markets", []):
                        if str(market.get("id")) == str(market_id):
                            return _parse_market_resolution(market)

        return False, None

    except Exception as e:
        logger.warning(f"Failed to search for market {market_id}: {e}")
        return False, None


def _parse_market_resolution(market: dict) -> Tuple[bool, Optional[float]]:
    """
    Parse market data to determine if resolved and outcome.

    Handles both Yes/No and Up/Down outcomes.
    - outcomePrices[0] > 0.99 -> first outcome won (Yes or Up)
    - outcomePrices[0] < 0.01 -> second outcome won (No or Down)
    """
    is_closed = market.get("closed", False)

    if not is_closed:
        return False, None

    outcome_prices = market.get("outcomePrices", [])
    if not outcome_prices:
        return False, None

    try:
        if isinstance(outcome_prices, str):
            outcome_prices = json.loads(outcome_prices)

        first_price = float(outcome_prices[0]) if outcome_prices else 0.5

        if first_price > 0.99:
            # First outcome won (Up or Yes)
            logger.info(f"Market {market.get('id')} resolved: UP/YES won")
            return True, 1.0
        elif first_price < 0.01:
            # Second outcome won (Down or No)
            logger.info(f"Market {market.get('id')} resolved: DOWN/NO won")
            return True, 0.0
        else:
            return False, None

    except (ValueError, IndexError, TypeError) as e:
        logger.warning(f"Failed to parse outcome prices: {e}")
        return False, None


def calculate_pnl(trade: Trade, settlement_value: float) -> float:
    """
    Calculate P&L for a trade given the settlement value.

    settlement_value: 1.0 if Up/Yes outcome, 0.0 if Down/No outcome

    Maps up->yes, down->no internally:
    - UP position wins when settlement = 1.0
    - DOWN position wins when settlement = 0.0
    """
    # Map up/down to yes/no logic
    direction = trade.direction
    if direction == "up":
        direction = "yes"
    elif direction == "down":
        direction = "no"

    if direction == "yes":
        if settlement_value == 1.0:
            pnl = trade.size * (1.0 - trade.entry_price)
        else:
            pnl = -trade.size * trade.entry_price
    else:  # NO / DOWN position
        if settlement_value == 0.0:
            pnl = trade.size * (1.0 - trade.entry_price)
        else:
            pnl = -trade.size * trade.entry_price

    return round(pnl, 2)


async def check_market_settlement(trade: Trade) -> Tuple[bool, Optional[float], Optional[float]]:
    """
    Check if a trade's market has settled.

    Returns: (is_settled, settlement_value, pnl)
    """
    is_resolved, settlement_value = await fetch_polymarket_resolution(
        trade.market_ticker,
        event_slug=trade.event_slug
    )

    if not is_resolved or settlement_value is None:
        return False, None, None

    pnl = calculate_pnl(trade, settlement_value)

    mapped_dir = "UP" if trade.direction in ("up", "yes") else "DOWN"
    outcome = "UP" if settlement_value == 1.0 else "DOWN"
    result = "WIN" if mapped_dir == outcome else "LOSS"

    logger.info(f"Trade {trade.id} settled: {mapped_dir} @ {trade.entry_price:.0%} -> "
                f"{result} P&L: ${pnl:+.2f}")

    return True, settlement_value, pnl


async def settle_pending_trades(db: Session) -> List[Trade]:
    """
    Process all pending trades for settlement.
    Uses REAL market outcomes from Polymarket API.
    """
    try:
        pending = db.query(Trade).filter(Trade.settled == False).all()
    except Exception as e:
        logger.error(f"Failed to query pending trades: {e}")
        return []

    if not pending:
        logger.info("No pending trades to settle")
        return []

    logger.info(f"Checking {len(pending)} pending trades for settlement...")
    settled_trades = []

    for trade in pending:
        try:
            is_settled, settlement_value, pnl = await check_market_settlement(trade)

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

                # Update linked Signal with actual outcome for calibration
                if trade.signal_id:
                    linked_signal = db.query(Signal).filter(Signal.id == trade.signal_id).first()
                    if linked_signal:
                        actual_outcome = "up" if settlement_value == 1.0 else "down"
                        linked_signal.actual_outcome = actual_outcome
                        linked_signal.outcome_correct = (linked_signal.direction == actual_outcome)
                        linked_signal.settlement_value = settlement_value
                        linked_signal.settled_at = datetime.utcnow()
        except Exception as e:
            logger.error(f"Failed to settle trade {trade.id}: {e}")
            continue

    if settled_trades:
        try:
            db.commit()
            logger.info(f"Settled {len(settled_trades)} trades")
        except Exception as e:
            logger.error(f"Failed to commit settlements: {e}")
            db.rollback()
            return []
    else:
        logger.info("No trades ready for settlement (markets still open)")

    return settled_trades


async def update_bot_state_with_settlements(db: Session, settled_trades: List[Trade]) -> None:
    """Update bot state with P&L from settled trades."""
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
