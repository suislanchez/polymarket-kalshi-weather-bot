"""Open-position mark-to-market and exit recommendation primitives."""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class RiskAction(str, Enum):
    HOLD = "hold"
    WATCH = "watch"
    REDUCE = "reduce"
    EXIT = "exit"


@dataclass(frozen=True)
class PositionQuote:
    """Executable quote context for the held side of an open position."""

    exit_price: float | None
    spread: float | None = None
    top_bid_size: float | None = None
    top_ask_size: float | None = None
    market_probability: float | None = None


@dataclass(frozen=True)
class PositionEvidence:
    """Updated source/model evidence for whether the original position thesis holds."""

    model_probability: float | None
    thesis_status: str = "unknown"
    source_status: str | None = None
    source_confidence: str | None = None
    alignment_count: int = 0
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExitRecommendation:
    action: RiskAction
    reasons: list[str]
    exit_price: float | None
    exit_pnl: float | None
    unrealized_pnl: float | None
    model_probability_for_held_side: float | None
    market_probability_for_held_side: float | None
    source_status: str | None
    evidence: dict[str, Any] = field(default_factory=dict)


EXIT_HARD_MODEL_PROB_THRESHOLD = 0.15
EXIT_MIN_SELL_PRICE = 0.03
EXIT_MAX_SPREAD = 0.20
EXIT_MIN_TOP_BID_SIZE = 5.0


def _shares_for_cost(entry_price: float, size: float) -> float:
    if entry_price <= 0 or size <= 0:
        return 0.0
    return size / entry_price


def calculate_exit_pnl(entry_price: float, exit_price: float, size: float) -> float:
    """Return realized PnL if a binary position bought with `size` dollars exits now."""
    shares = _shares_for_cost(entry_price, size)
    if shares <= 0:
        return 0.0
    proceeds = shares * exit_price
    return round(proceeds - size, 2)


def calculate_unrealized_pnl(entry_price: float, current_exit_price: float, size: float) -> float:
    """Mark-to-market PnL using the current executable sell price for the held side."""
    return calculate_exit_pnl(entry_price=entry_price, exit_price=current_exit_price, size=size)


def calculate_final_settlement_pnl(entry_price: float, size: float, won: bool) -> float:
    """Final binary settlement PnL with `size` interpreted as dollars deployed at entry."""
    shares = _shares_for_cost(entry_price, size)
    if shares <= 0:
        return 0.0
    proceeds = shares * (1.0 if won else 0.0)
    return round(proceeds - size, 2)


def choose_exit_action(
    quote: PositionQuote,
    evidence: PositionEvidence,
    entry_price: float,
    size: float,
    *,
    model_threshold: float = EXIT_HARD_MODEL_PROB_THRESHOLD,
    min_sell_price: float = EXIT_MIN_SELL_PRICE,
    max_spread: float = EXIT_MAX_SPREAD,
    min_top_bid_size: float = EXIT_MIN_TOP_BID_SIZE,
) -> ExitRecommendation:
    """Choose a deterministic recommendations-only risk action for an open position."""
    reasons: list[str] = []
    exit_price = quote.exit_price
    exit_pnl = (
        calculate_exit_pnl(entry_price=entry_price, exit_price=exit_price, size=size)
        if exit_price is not None
        else None
    )
    unrealized_pnl = exit_pnl

    executable = True
    if exit_price is None:
        executable = False
        reasons.append("missing executable exit price")
    elif exit_price < min_sell_price:
        executable = False
        reasons.append("exit price below minimum")

    if quote.spread is not None and quote.spread > max_spread:
        executable = False
        reasons.append("spread too wide for clean exit")

    if quote.top_bid_size is not None and quote.top_bid_size < min_top_bid_size:
        executable = False
        reasons.append("top bid size below minimum")

    thesis = (evidence.thesis_status or "unknown").lower()
    model_probability = evidence.model_probability
    model_bad = model_probability is not None and model_probability < model_threshold
    thesis_broken = thesis == "broken"
    thesis_intact = thesis == "intact"

    if thesis_intact and not model_bad:
        reasons.append("thesis remains intact")
        action = RiskAction.HOLD
    elif model_probability is None or thesis == "unknown" or (evidence.source_status or "").lower() == "missing":
        reasons.append("source/model evidence incomplete")
        action = RiskAction.WATCH
    elif not executable:
        action = RiskAction.WATCH
    elif thesis_broken or model_bad:
        if model_bad:
            reasons.append("model probability below exit threshold")
        if thesis_broken:
            reasons.append("thesis broken")
        action = RiskAction.EXIT
    else:
        reasons.append("thesis weakened but not broken")
        action = RiskAction.REDUCE

    return ExitRecommendation(
        action=action,
        reasons=reasons,
        exit_price=exit_price,
        exit_pnl=exit_pnl,
        unrealized_pnl=unrealized_pnl,
        model_probability_for_held_side=model_probability,
        market_probability_for_held_side=quote.market_probability if quote.market_probability is not None else exit_price,
        source_status=evidence.source_status,
        evidence={
            "thesis_status": evidence.thesis_status,
            "source_confidence": evidence.source_confidence,
            "alignment_count": evidence.alignment_count,
            **evidence.metadata,
        },
    )
