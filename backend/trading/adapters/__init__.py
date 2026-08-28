"""Paper broker adapter contracts and deterministic test implementation."""

from backend.trading.adapters.alpaca_paper import (
    AlpacaPaperAdapter,
    AlpacaPaperAdapterError,
)
from backend.trading.adapters.base import (
    BrokerAdapter,
    BrokerAdapterError,
    DuplicateClientOrderIdError,
    OrderNotCancelableError,
    OrderNotFoundError,
)
from backend.trading.adapters.fake import FakeOrderScenario, FakePaperAdapter

__all__ = [
    "AlpacaPaperAdapter",
    "AlpacaPaperAdapterError",
    "BrokerAdapter",
    "BrokerAdapterError",
    "DuplicateClientOrderIdError",
    "FakeOrderScenario",
    "FakePaperAdapter",
    "OrderNotCancelableError",
    "OrderNotFoundError",
]
