"""Market data types and fetching - simplified for BTC 5-min focus."""
import logging
from datetime import datetime
from typing import Optional, List
from dataclasses import dataclass

from backend.data.btc_markets import BtcMarket, fetch_active_btc_markets

logger = logging.getLogger(__name__)


@dataclass
class MarketData:
    """Structured market data."""
    platform: str
    ticker: str
    title: str
    category: str
    subcategory: Optional[str]

    yes_price: float  # 0-1 (Up price for BTC markets)
    no_price: float   # (Down price for BTC markets)
    volume: float
    settlement_time: Optional[datetime]

    threshold: Optional[float] = None
    direction: Optional[str] = None

    event_slug: Optional[str] = None
    window_start: Optional[datetime] = None
    window_end: Optional[datetime] = None


def btc_market_to_market_data(btc: BtcMarket) -> MarketData:
    """Convert a BtcMarket to the generic MarketData format."""
    return MarketData(
        platform="polymarket",
        ticker=btc.market_id,
        title=f"BTC Up or Down 5m - {btc.slug}",
        category="crypto",
        subcategory="btc-5m",
        yes_price=btc.up_price,
        no_price=btc.down_price,
        volume=btc.volume,
        settlement_time=btc.window_end,
        event_slug=btc.slug,
        window_start=btc.window_start,
        window_end=btc.window_end,
    )


async def fetch_all_markets(**kwargs) -> List[MarketData]:
    """Fetch all markets - currently only BTC 5-min markets."""
    btc_markets = await fetch_active_btc_markets()
    return [btc_market_to_market_data(m) for m in btc_markets]
