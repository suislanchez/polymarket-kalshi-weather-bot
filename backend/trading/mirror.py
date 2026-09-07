"""Read-only mirroring of an external brokerage account.

An agent that holds a broker connection (the Robinhood Agentic MCP is OAuth in
the MCP client; the backend cannot call it) reads positions and balances and
pushes a snapshot here. Three properties are load-bearing:

1. **Only the normalised form crosses this boundary.** Raw broker payloads are
   mapped on the agent side (see scripts/mirror_robinhood.py); this module
   validates an allowlist and rejects everything else, so a broker adding a
   field cannot leak it into storage or the API.
2. **Account numbers never arrive.** ``account_ref`` must already be masked to
   the last four digits. Any run of five or more digits anywhere in the
   snapshot is refused.
3. **The mirror is not portfolio state.** Nothing in backend/trading/risk.py or
   service.py imports this module, and a test pins that. A mirrored balance
   must never be something the paper risk gate sizes an order against.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.models.database import MirroredPortfolioSnapshot

MIRROR_VENUES = frozenset({"robinhood"})
MASKED_REF = re.compile(r"^[•*]{4}\d{4}$")
RAW_IDENTIFIER = re.compile(r"\d{5,}")
ASSET_CLASSES = frozenset({"stock", "crypto", "option"})


class MirrorValidationError(ValueError):
    """Fixed, caller-safe message. Never echoes the offending value."""


def _exact_nonnegative(value: object, field: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{field} must be a decimal string")
    try:
        number = Decimal(value.strip())
    except InvalidOperation:
        raise ValueError(f"{field} must be a decimal string") from None
    if not number.is_finite() or number < 0:
        raise ValueError(f"{field} must be finite and non-negative")
    return str(number)


class MirroredPosition(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    asset_class: str
    symbol: str = Field(min_length=1, max_length=32)
    quantity: str
    average_cost: Optional[str] = None

    @field_validator("asset_class")
    @classmethod
    def _asset_class(cls, value: str) -> str:
        if value not in ASSET_CLASSES:
            raise ValueError("asset_class not allowed")
        return value

    @field_validator("symbol")
    @classmethod
    def _symbol(cls, value: str) -> str:
        if RAW_IDENTIFIER.search(value):
            raise ValueError("symbol looks like an identifier")
        return value.strip().upper()

    @field_validator("quantity")
    @classmethod
    def _quantity(cls, value: str) -> str:
        return _exact_nonnegative(value, "quantity")

    @field_validator("average_cost")
    @classmethod
    def _average_cost(cls, value: Optional[str]) -> Optional[str]:
        return None if value is None else _exact_nonnegative(value, "average_cost")


class MirroredAccount(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    label: str = Field(min_length=1, max_length=64)
    account_ref: str
    tradable_by_agent: bool
    currency: str = "USD"
    total_value: str
    cash: str
    buying_power: str
    positions: List[MirroredPosition] = Field(default_factory=list)

    @field_validator("account_ref")
    @classmethod
    def _masked(cls, value: str) -> str:
        if not MASKED_REF.match(value):
            raise ValueError("account_ref must be masked to the last four digits")
        return value

    @field_validator("label")
    @classmethod
    def _label(cls, value: str) -> str:
        if RAW_IDENTIFIER.search(value):
            raise ValueError("label looks like an identifier")
        return value.strip()

    @field_validator("total_value", "cash", "buying_power")
    @classmethod
    def _money(cls, value: str, info) -> str:
        return _exact_nonnegative(value, info.field_name)


class MirrorSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    venue: str
    captured_at: datetime
    source_agent: str = Field(min_length=1, max_length=64)
    accounts: List[MirroredAccount] = Field(min_length=1)

    @field_validator("venue")
    @classmethod
    def _venue(cls, value: str) -> str:
        if value not in MIRROR_VENUES:
            raise ValueError("venue is not a mirror venue")
        return value

    @field_validator("captured_at")
    @classmethod
    def _utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("captured_at must be timezone-aware")
        return value.astimezone(timezone.utc)

    @model_validator(mode="after")
    def _no_raw_identifiers_anywhere(self) -> "MirrorSnapshot":
        # Belt and braces over the per-field checks: serialise and scan.
        text = self.model_dump_json()
        # captured_at contains digits legitimately; strip it before scanning.
        text = re.sub(r'"captured_at":"[^"]*"', "", text)
        # Decimal strings contain digit runs legitimately (e.g. "5673.84004803").
        text = re.sub(r'"(quantity|average_cost|total_value|cash|buying_power)":"[^"]*"', "", text)
        if RAW_IDENTIFIER.search(text):
            raise ValueError("snapshot contains an unmasked identifier")
        return self

    @property
    def position_count(self) -> int:
        return sum(len(account.positions) for account in self.accounts)

    @property
    def total_value(self) -> str:
        total = sum((Decimal(a.total_value) for a in self.accounts), Decimal("0"))
        return str(total)


def validate_snapshot(payload: object) -> MirrorSnapshot:
    """Validate an untrusted payload. The message never carries the payload."""
    try:
        return MirrorSnapshot.model_validate(payload)
    except Exception:
        raise MirrorValidationError("mirror snapshot rejected") from None


def record_snapshot(session: Session, snapshot: MirrorSnapshot) -> MirroredPortfolioSnapshot:
    row = MirroredPortfolioSnapshot(
        venue=snapshot.venue,
        captured_at=snapshot.captured_at,
        source_agent=snapshot.source_agent,
        account_count=len(snapshot.accounts),
        position_count=snapshot.position_count,
        total_value=snapshot.total_value,
        payload=snapshot.model_dump(mode="json"),
    )
    session.add(row)
    session.flush()
    return row


def latest_snapshot(session: Session, venue: str) -> Optional[MirroredPortfolioSnapshot]:
    if venue not in MIRROR_VENUES:
        return None
    return session.execute(
        select(MirroredPortfolioSnapshot)
        .where(MirroredPortfolioSnapshot.venue == venue)
        .order_by(MirroredPortfolioSnapshot.captured_at.desc(), MirroredPortfolioSnapshot.id.desc())
        .limit(1)
    ).scalar_one_or_none()


__all__ = [
    "MIRROR_VENUES",
    "MirrorSnapshot",
    "MirrorValidationError",
    "MirroredAccount",
    "MirroredPosition",
    "latest_snapshot",
    "record_snapshot",
    "validate_snapshot",
]
