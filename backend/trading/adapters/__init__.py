"""Paper broker adapter contracts and deterministic test implementation."""

from backend.trading.adapters.base import (
    BrokerAdapter,
    BrokerAdapterError,
    DuplicateClientOrderIdError,
    OrderNotCancelableError,
    OrderNotFoundError,
)
from backend.trading.adapters.fake import FakeOrderScenario, FakePaperAdapter

__all__ = [
    "BrokerAdapter",
    "BrokerAdapterError",
    "DuplicateClientOrderIdError",
    "FakeOrderScenario",
    "FakePaperAdapter",
    "OrderNotCancelableError",
    "OrderNotFoundError",
]
