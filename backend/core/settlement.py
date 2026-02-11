"""Trade settlement logic - checks REAL market outcomes from Polymarket."""
import httpx
import logging
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from backend.models.database import Trade, BotState

logger = logging.getLogger("trading_bot")


async def fetch_polymarket_resolution(market_id: str) -> Tuple[bool, Optional[float]]:
    """
    Fetch actual market resolution from Polymarket API.

    Returns: (is_resolved, settlement_value)
        - settlement_value: 1.0 if YES won, 0.0 if NO won
    """
    try:
        # Try to get market directly
        url = f"https://gamma-api.polymarket.com/markets/{market_id}"

        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(url)

            if response.status_code == 404:
                # Market not found by ID, try searching events
                return await _search_market_in_events(market_id)

            response.raise_for_status()
            market = response.json()

            return _parse_market_resolution(market)

    except Exception as e:
        logger.warning(f"Failed to fetch Polymarket resolution for {market_id}: {e}")
        return False, None


async def _search_market_in_events(market_id: str) -> Tuple[bool, Optional[float]]:
    """Search for market in events (both active and closed)."""
    try:
        async with httpx.AsyncClient(timeout=15.0) as client:
            # Search closed events first (more likely to be resolved)
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
    """Parse market data to determine if resolved and outcome."""
    is_closed = market.get("closed", False)

    if not is_closed:
        return False, None

    # Get outcome prices
    outcome_prices = market.get("outcomePrices", [])
    if not outcome_prices:
        return False, None

    try:
        # Parse YES price
        if isinstance(outcome_prices, str):
            import json
            outcome_prices = json.loads(outcome_prices)

        yes_price = float(outcome_prices[0]) if outcome_prices else 0.5

        # If YES price is very close to 0 or 1, market is resolved
        if yes_price > 0.99:
            logger.info(f"Market {market.get('id')} resolved: YES won")
            return True, 1.0  # YES won
        elif yes_price < 0.01:
            logger.info(f"Market {market.get('id')} resolved: NO won")
            return True, 0.0  # NO won
        else:
            # Market is closed but not fully resolved (maybe disputed)
            return False, None

    except (ValueError, IndexError, TypeError) as e:
        logger.warning(f"Failed to parse outcome prices: {e}")
        return False, None


def calculate_pnl(trade: Trade, settlement_value: float) -> float:
    """
    Calculate P&L for a trade given the settlement value.

    settlement_value: 1.0 if YES outcome, 0.0 if NO outcome

    For YES position:
      - Win if settlement = 1: pnl = size * (1 - entry_price)
      - Loss if settlement = 0: pnl = -size * entry_price

    For NO position:
      - Win if settlement = 0: pnl = size * (1 - entry_price)
      - Loss if settlement = 1: pnl = -size * entry_price
    """
    if trade.direction == "yes":
        if settlement_value == 1.0:
            # YES wins
            pnl = trade.size * (1.0 - trade.entry_price)
        else:
            # YES loses
            pnl = -trade.size * trade.entry_price
    else:  # NO position
        if settlement_value == 0.0:
            # NO wins
            pnl = trade.size * (1.0 - trade.entry_price)
        else:
            # NO loses
            pnl = -trade.size * trade.entry_price

    return round(pnl, 2)


async def check_market_settlement(trade: Trade) -> Tuple[bool, Optional[float], Optional[float]]:
    """
    Check if a trade's market has settled and determine the outcome.

    Uses REAL Polymarket API data - no simulation!

    Returns: (is_settled, settlement_value, pnl)
    """
    # Get real resolution from Polymarket
    is_resolved, settlement_value = await fetch_polymarket_resolution(trade.market_ticker)

    if not is_resolved or settlement_value is None:
        # Market not yet resolved
        return False, None, None

    # Calculate real P&L
    pnl = calculate_pnl(trade, settlement_value)

    logger.info(f"Trade {trade.id} settled: {trade.direction.upper()} @ {trade.entry_price:.0%} -> "
                f"{'WIN' if (trade.direction == 'yes' and settlement_value == 1.0) or (trade.direction == 'no' and settlement_value == 0.0) else 'LOSS'} "
                f"P&L: ${pnl:+.2f}")

    return True, settlement_value, pnl


async def settle_pending_trades(db: Session) -> List[Trade]:
    """
    Process all pending trades that are ready for settlement.
    Uses REAL market outcomes from Polymarket API.

    Returns list of newly settled trades.
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
                # Update trade record
                trade.settled = True
                trade.settlement_value = settlement_value
                trade.pnl = pnl
                trade.settlement_time = datetime.utcnow()

                # Determine result
                if pnl is not None and pnl > 0:
                    trade.result = "win"
                elif pnl is not None and pnl < 0:
                    trade.result = "loss"
                else:
                    trade.result = "push"  # Breakeven

                settled_trades.append(trade)
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
            logger.warning("Bot state not found, cannot update with settlements")
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
        logger.error(f"Failed to update bot state with settlements: {e}")
        db.rollback()
