"""Deterministic proposal-generating strategies.

Strategies propose only. They never hold a broker reference, a database handle, or
credentials, and nothing here can submit an order.
"""

from backend.trading.strategies.trend_following import (
    STRATEGY_ID,
    StrategySignal,
    TrendFollowingStrategy,
)

__all__ = ["STRATEGY_ID", "StrategySignal", "TrendFollowingStrategy"]
