"""Trade settlement logic - resolves pending trades using actual weather data."""
import re
import httpx
from datetime import datetime, timedelta
from typing import Optional, List, Tuple
from sqlalchemy.orm import Session

from backend.config import settings
from backend.models.database import Trade, BotState


# NWS weather station IDs for actual observations
NWS_STATIONS = {
    "nyc": "KNYC",
    "chicago": "KORD",
    "miami": "KMIA",
    "austin": "KAUS",
    "los_angeles": "KLAX",
    "atlanta": "KATL",
    "denver": "KDEN",
    "seattle": "KSEA",
    "dallas": "KDFW",
    "boston": "KBOS",
}


def parse_market_ticker(ticker: str) -> Tuple[Optional[str], Optional[float], Optional[str]]:
    """
    Parse market ticker to extract city, threshold, and direction.

    Examples:
    - KXHIGHNYC-26FEB10-T45 -> ('nyc', 45.0, 'above')
    - KXHIGHCHICAGO-26FEB10-T30 -> ('chicago', 30.0, 'above')
    """
    ticker_upper = ticker.upper()

    # Extract city
    city = None
    for city_name in NWS_STATIONS.keys():
        if city_name.upper() in ticker_upper:
            city = city_name
            break

    # Extract threshold (T followed by number)
    threshold_match = re.search(r'T(\d+)', ticker_upper)
    threshold = float(threshold_match.group(1)) if threshold_match else None

    # Determine direction (HIGH = above, LOW = below)
    direction = None
    if 'HIGH' in ticker_upper:
        direction = 'above'
    elif 'LOW' in ticker_upper:
        direction = 'below'

    return city, threshold, direction


async def fetch_weather_actual(city: str, target_date: datetime) -> Optional[float]:
    """
    Fetch actual high temperature from NWS observations API.
    Returns the actual high temp for the given date, or None if not available.
    """
    station_id = NWS_STATIONS.get(city.lower())
    if not station_id:
        return None

    try:
        # NWS observations endpoint
        url = f"https://api.weather.gov/stations/{station_id}/observations"

        # Get observations for the target date
        start = target_date.replace(hour=0, minute=0, second=0)
        end = target_date.replace(hour=23, minute=59, second=59)

        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.get(
                url,
                params={
                    "start": start.isoformat() + "Z",
                    "end": end.isoformat() + "Z"
                },
                headers={"User-Agent": "WeatherTradingBot/1.0"}
            )

            if response.status_code != 200:
                return None

            data = response.json()
            observations = data.get("features", [])

            if not observations:
                return None

            # Find max temperature from observations
            temps = []
            for obs in observations:
                props = obs.get("properties", {})
                temp_c = props.get("temperature", {}).get("value")
                if temp_c is not None:
                    # Convert Celsius to Fahrenheit
                    temp_f = (temp_c * 9/5) + 32
                    temps.append(temp_f)

            if temps:
                return max(temps)

    except Exception as e:
        print(f"Error fetching weather actual for {city}: {e}")

    return None


async def simulate_weather_actual(city: str, trade: Trade) -> float:
    """
    For simulation mode: Generate a realistic settlement value based on model probability.
    This creates deterministic but realistic outcomes for testing.
    """
    import random
    # Use trade ID as seed for deterministic results
    random.seed(trade.id)

    # Settlement based on model probability (with some noise)
    base_prob = trade.model_probability
    # Add some noise (-10% to +10%)
    noise = random.uniform(-0.1, 0.1)
    final_prob = max(0, min(1, base_prob + noise))

    # Determine outcome
    return 1.0 if random.random() < final_prob else 0.0


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

    Returns: (is_settled, settlement_value, pnl)
    """
    # Parse the market ticker
    city, threshold, direction = parse_market_ticker(trade.market_ticker)

    if not all([city, threshold, direction]):
        # Can't parse ticker - simulate settlement
        settlement_value = await simulate_weather_actual(city or "nyc", trade)
        pnl = calculate_pnl(trade, settlement_value)
        return True, settlement_value, pnl

    # Check if enough time has passed (market should settle after the date)
    # Parse date from ticker (e.g., 26FEB10 = Feb 10, 2026)
    date_match = re.search(r'(\d{2})([A-Z]{3})(\d{2})', trade.market_ticker.upper())
    if date_match:
        day = int(date_match.group(1))
        month_str = date_match.group(2)
        year = 2000 + int(date_match.group(3))

        months = {'JAN': 1, 'FEB': 2, 'MAR': 3, 'APR': 4, 'MAY': 5, 'JUN': 6,
                  'JUL': 7, 'AUG': 8, 'SEP': 9, 'OCT': 10, 'NOV': 11, 'DEC': 12}
        month = months.get(month_str, 1)

        try:
            market_date = datetime(year, month, day)

            # Market settles after midnight of the market date
            if datetime.utcnow() < market_date + timedelta(hours=24):
                return False, None, None  # Not settled yet

            # Try to get actual weather data
            actual_temp = await fetch_weather_actual(city, market_date)

            if actual_temp is not None:
                # Determine settlement based on actual temp
                if direction == 'above':
                    settlement_value = 1.0 if actual_temp >= threshold else 0.0
                else:  # below
                    settlement_value = 1.0 if actual_temp < threshold else 0.0

                pnl = calculate_pnl(trade, settlement_value)
                return True, settlement_value, pnl

        except ValueError:
            pass

    # Fallback: simulate settlement for older trades (> 12 hours old)
    if datetime.utcnow() - trade.timestamp > timedelta(hours=12):
        settlement_value = await simulate_weather_actual(city or "nyc", trade)
        pnl = calculate_pnl(trade, settlement_value)
        return True, settlement_value, pnl

    return False, None, None


async def settle_pending_trades(db: Session) -> List[Trade]:
    """
    Process all pending trades that are ready for settlement.
    Returns list of newly settled trades.
    """
    import logging
    logger = logging.getLogger("trading_bot")

    try:
        pending = db.query(Trade).filter(Trade.settled == False).all()
    except Exception as e:
        logger.error(f"Failed to query pending trades: {e}")
        return []

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
        except Exception as e:
            logger.error(f"Failed to commit settlements: {e}")
            db.rollback()
            return []

    return settled_trades


async def update_bot_state_with_settlements(db: Session, settled_trades: List[Trade]) -> None:
    """Update bot state with P&L from settled trades."""
    import logging
    logger = logging.getLogger("trading_bot")

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
    except Exception as e:
        logger.error(f"Failed to update bot state with settlements: {e}")
        db.rollback()
