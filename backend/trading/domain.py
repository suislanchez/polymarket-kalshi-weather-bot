"""Dependency-light, immutable contracts for normalized paper trading."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import (
    AfterValidator,
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)


class AssetClass(str, Enum):
    """Asset families supported by the unified paper-trading runtime."""

    STOCK = "stock"
    CRYPTO = "crypto"
    PREDICTION_WEATHER = "prediction_weather"


class Venue(str, Enum):
    """Approved paper or simulation venues."""

    ALPACA_PAPER = "alpaca_paper"
    POLYMARKET_PAPER = "polymarket_paper"
    KALSHI_PAPER = "kalshi_paper"


class Side(str, Enum):
    BUY = "buy"
    SELL = "sell"


class OrderType(str, Enum):
    MARKET = "market"
    LIMIT = "limit"


class OrderStatus(str, Enum):
    PROPOSED = "proposed"
    RISK_REJECTED = "risk_rejected"
    APPROVED = "approved"
    SUBMITTED = "submitted"
    PARTIALLY_FILLED = "partially_filled"
    FILLED = "filled"
    CANCELED = "canceled"
    REJECTED = "rejected"


def _require_nonblank(value: str) -> str:
    if not value.strip():
        raise ValueError("value must be a nonblank stable string")
    return value


def _require_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware UTC")
    if value.utcoffset() != timezone.utc.utcoffset(value):
        raise ValueError("timestamp must be timezone-aware UTC")
    return value.astimezone(timezone.utc)


NonBlankString = Annotated[str, AfterValidator(_require_nonblank)]
UtcDatetime = Annotated[datetime, AfterValidator(_require_utc)]
PositiveDecimal = Annotated[Decimal, Field(gt=0)]
NonNegativeDecimal = Annotated[Decimal, Field(ge=0)]


class DomainModel(BaseModel):
    """Shared strictness for all values crossing trading boundaries."""

    model_config = ConfigDict(extra="forbid", frozen=True)


class SizedOrderModel(DomainModel):
    """Shared normalized size and order-price invariants."""

    quantity: PositiveDecimal | None = None
    notional: PositiveDecimal | None = None
    order_type: OrderType = OrderType.MARKET
    limit_price: PositiveDecimal | None = None

    @model_validator(mode="after")
    def validate_size_and_limit(self) -> SizedOrderModel:
        if self.quantity is None and self.notional is None:
            raise ValueError("positive quantity or notional is required")
        if self.order_type is OrderType.LIMIT and self.limit_price is None:
            raise ValueError("limit_price is required for limit orders")
        return self


class TradeProposal(SizedOrderModel):
    """A strategy proposal that has not yet passed deterministic risk checks."""

    proposal_id: NonBlankString
    strategy_id: NonBlankString
    venue: Venue
    asset_class: AssetClass
    symbol: NonBlankString
    side: Side
    reference_price: PositiveDecimal
    market_data_at: UtcDatetime
    created_at: UtcDatetime
    rationale: NonBlankString
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class RiskDecision(DomainModel):
    """Deterministic risk result plus the limits active at decision time."""

    proposal_id: NonBlankString
    approved: bool
    reason_codes: tuple[NonBlankString, ...] = ()
    approved_quantity: PositiveDecimal | None = None
    approved_notional: PositiveDecimal | None = None
    decided_at: UtcDatetime
    limit_snapshot: dict[str, JsonValue] = Field(default_factory=dict)


class NormalizedOrder(SizedOrderModel):
    """Risk-normalized paper order passed to a venue adapter."""

    client_order_id: NonBlankString
    proposal_id: NonBlankString
    venue: Venue
    asset_class: AssetClass
    symbol: NonBlankString
    side: Side
    status: OrderStatus
    created_at: UtcDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class ExecutionReport(DomainModel):
    """Normalized adapter report for an order lifecycle transition."""

    client_order_id: NonBlankString
    venue: Venue
    status: OrderStatus
    broker_order_id: NonBlankString | None = None
    filled_quantity: NonNegativeDecimal = Decimal("0")
    filled_notional: NonNegativeDecimal = Decimal("0")
    average_fill_price: PositiveDecimal | None = None
    rejection_reason: NonBlankString | None = None
    occurred_at: UtcDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class PositionSnapshot(DomainModel):
    """Normalized long-only position state from a paper venue."""

    venue: Venue
    asset_class: AssetClass
    symbol: NonBlankString
    quantity: PositiveDecimal
    cost_basis: NonNegativeDecimal
    market_value: NonNegativeDecimal
    average_entry_price: PositiveDecimal
    current_price: PositiveDecimal
    realized_pnl: Decimal
    unrealized_pnl: Decimal
    captured_at: UtcDatetime
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


class AccountSnapshot(DomainModel):
    """Normalized account balances and positions at one UTC instant."""

    venue: Venue
    cash: NonNegativeDecimal
    equity: PositiveDecimal
    buying_power: NonNegativeDecimal
    captured_at: UtcDatetime
    positions: tuple[PositionSnapshot, ...] = ()
    metadata: dict[str, JsonValue] = Field(default_factory=dict)


__all__ = [
    "AccountSnapshot",
    "AssetClass",
    "ExecutionReport",
    "NormalizedOrder",
    "OrderStatus",
    "OrderType",
    "PositionSnapshot",
    "RiskDecision",
    "Side",
    "TradeProposal",
    "Venue",
]
