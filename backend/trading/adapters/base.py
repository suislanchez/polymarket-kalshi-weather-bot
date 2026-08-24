"""Synchronous broker adapter contract for the paper-only trading runtime."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from backend.trading.domain import (
    AccountSnapshot,
    ExecutionReport,
    NormalizedOrder,
    PositionSnapshot,
)


class BrokerAdapterError(RuntimeError):
    """Base error for sanitized broker-adapter failures."""


class DuplicateClientOrderIdError(BrokerAdapterError):
    """Raised when an idempotency key is reused with a different payload."""


class OrderNotFoundError(BrokerAdapterError):
    """Raised when an order cannot be found."""


class OrderNotCancelableError(BrokerAdapterError):
    """Raised when an order is already terminal and cannot be canceled."""


@runtime_checkable
class BrokerAdapter(Protocol):
    """Structural contract implemented by synchronous paper broker adapters."""

    @property
    def name(self) -> str: ...

    @property
    def paper_only(self) -> bool: ...

    def get_account_snapshot(self) -> AccountSnapshot: ...

    def list_positions(self) -> tuple[PositionSnapshot, ...]: ...

    def submit_order(
        self, order: NormalizedOrder, *, execution_mode: str
    ) -> ExecutionReport: ...

    def cancel_order(self, client_order_id: str) -> ExecutionReport: ...

    def get_order(self, client_order_id: str) -> ExecutionReport | None: ...

    def list_recent_orders(self, *, limit: int = 100) -> tuple[ExecutionReport, ...]: ...


__all__ = [
    "BrokerAdapter",
    "BrokerAdapterError",
    "DuplicateClientOrderIdError",
    "OrderNotCancelableError",
    "OrderNotFoundError",
]
