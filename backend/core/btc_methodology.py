"""Conservative BTC 5-minute signal gates.

BTC Up/Down markets settle from Chainlink BTC/USD, while the current model
uses exchange spot microstructure (Coinbase/Kraken/Binance/Bybit).  These
helpers are side-effect-free and intentionally strict: research signals can be
shown, but paper actionability is blocked until settlement-source, line-level
book depth, and source-alignment requirements are met.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import logging
from typing import Optional, Callable, Any
from urllib.parse import urlencode

logger = logging.getLogger("trading_bot")

CHAINLINK_BTC_USD_FEED_ID = "0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8"
CHAINLINK_DATA_STREAMS_API_BASE = "https://api.dataengine.chain.link"


@dataclass(frozen=True)
class BtcChainlinkReportRequest:
    """Exact Data Streams report request needed for one BTC market boundary.

    The production Data Streams REST API is authenticated.  Persisting the exact
    URL/timestamp/feed-id request plan is still useful for research QA because it
    prevents future boundary collectors from using scrape time or nearby reports
    as implicit settlement evidence.
    """

    boundary: str
    timestamp: int
    feed_id: str = CHAINLINK_BTC_USD_FEED_ID
    url: str = ""
    requires_authentication: bool = True
    status: str = "auth_required_not_fetched"


@dataclass(frozen=True)
class BtcChainlinkBoundarySnapshot:
    """Exact Chainlink source evidence for one side of a 5-minute window.

    A Chainlink-labeled model source is not enough for BTC 5m actionability.
    The gate needs the observed Chainlink value at the relevant start/end
    boundary plus feed/timestamp/method metadata so later settlement scoring can
    distinguish source-aligned evidence from exchange-spot context.
    """

    price: Optional[float]
    observed_at: Optional[int | str]
    feed_id: str = CHAINLINK_BTC_USD_FEED_ID
    method: str = "unknown"
    source_snapshot_path: Optional[str] = None


def _normalize_boundary_ts(value: Optional[int | str]) -> Optional[int]:
    """Normalize a boundary timestamp to unix seconds when possible."""
    if value is None or value == "":
        return None
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _datetime_to_unix_seconds(value: Any) -> Optional[int]:
    """Convert a datetime-like value to unix seconds without raising."""
    if value is None:
        return None
    if isinstance(value, datetime):
        dt_value = value
        if dt_value.tzinfo is None:
            dt_value = dt_value.replace(tzinfo=timezone.utc)
        return int(dt_value.timestamp())
    return _normalize_boundary_ts(value)


def derive_btc_window_boundary_timestamps(market: Any) -> tuple[Optional[int], Optional[int]]:
    """Return expected Chainlink start/end unix boundaries for a BTC 5m market.

    Polymarket BTC Up/Down slugs encode the 5-minute window start, and the
    platform code already carries parsed ``window_start``/``window_end`` values.
    This helper centralizes the conversion so source-evidence validators can
    require Chainlink observations at the exact market boundaries rather than at
    arbitrary nearby scrape times.
    """
    if market is None:
        return None, None
    return (
        _datetime_to_unix_seconds(getattr(market, "window_start", None)),
        _datetime_to_unix_seconds(getattr(market, "window_end", None)),
    )


def build_chainlink_boundary_report_requests(
    market: Any,
    *,
    feed_id: str = CHAINLINK_BTC_USD_FEED_ID,
    api_base: str = CHAINLINK_DATA_STREAMS_API_BASE,
) -> list[BtcChainlinkReportRequest]:
    """Build exact authenticated Data Streams REST report URLs for a market.

    The helper does not fetch reports or require credentials. It records the
    precise report endpoint that a future read-only/authenticated boundary
    collector must query for the BTC window start and end. Rows produced from
    these request plans remain non-actionable until fetched reports provide exact
    prices, observation timestamps, and raw source snapshots.
    """
    start_ts, end_ts = derive_btc_window_boundary_timestamps(market)
    requests: list[BtcChainlinkReportRequest] = []
    for boundary, timestamp in (("start", start_ts), ("end", end_ts)):
        if timestamp is None:
            continue
        query = urlencode({"feedID": feed_id, "timestamp": int(timestamp)})
        requests.append(
            BtcChainlinkReportRequest(
                boundary=boundary,
                timestamp=int(timestamp),
                feed_id=feed_id,
                url=f"{api_base.rstrip('/')}/api/v1/reports?{query}",
            )
        )
    return requests


def validate_chainlink_boundary_snapshot(
    snapshot: Optional[BtcChainlinkBoundarySnapshot],
    *,
    expected_observed_at: Optional[int | str] = None,
) -> list[str]:
    """Return missing/invalid Chainlink boundary-evidence fields.

    A Chainlink price value is not sufficient for BTC 5m scoring or paper
    actionability.  The row must preserve observation time, feed id, capture
    method, and a raw/source snapshot pointer. When the caller knows the market
    boundary, the observation timestamp must match that boundary exactly.
    """
    if snapshot is None:
        return ["missing Chainlink boundary source snapshot"]

    reasons: list[str] = []
    if snapshot.price is None:
        reasons.append("missing Chainlink boundary price")

    observed = _normalize_boundary_ts(snapshot.observed_at)
    if observed is None:
        reasons.append("missing Chainlink boundary observation timestamp")

    expected = _normalize_boundary_ts(expected_observed_at)
    if observed is not None and expected is not None and observed != expected:
        reasons.append(
            f"Chainlink boundary observation timestamp {observed} does not match expected market boundary {expected}"
        )

    if (snapshot.feed_id or "").lower() != CHAINLINK_BTC_USD_FEED_ID.lower():
        reasons.append("missing Chainlink BTC/USD feed id for boundary snapshot")
    if not snapshot.method or snapshot.method == "unknown":
        reasons.append("missing Chainlink boundary capture method")
    if not snapshot.source_snapshot_path:
        reasons.append("missing Chainlink boundary raw source snapshot path")
    return reasons


@dataclass(frozen=True)
class BtcNoTradeGateResult:
    actionable: bool
    reasons: list[str] = field(default_factory=list)
    entry_price: Optional[float] = None
    spread: Optional[float] = None
    top_ask_size: Optional[float] = None


def persist_btc_price_snapshot(
    micro: Any,
    *,
    db_factory: Optional[Callable[[], Any]] = None,
    snapshot_cls: Optional[type] = None,
) -> bool:
    """Persist the BTC model/source price snapshot used for a signal scan.

    The BTC methodology needs a durable record of the model input source
    (Coinbase/Kraken/Binance/Bybit spot microstructure today; Chainlink only
    once a settlement-aligned feed exists).  This helper is deliberately small
    and injectable so tests can validate persistence without importing
    SQLAlchemy or touching the real database.
    """
    if micro is None or getattr(micro, "price", None) is None:
        return False

    if db_factory is None or snapshot_cls is None:
        from backend.models.database import BtcPriceSnapshot, SessionLocal

        db_factory = db_factory or SessionLocal
        snapshot_cls = snapshot_cls or BtcPriceSnapshot

    db = db_factory()
    try:
        db.add(
            snapshot_cls(
                price=float(micro.price),
                source=str(getattr(micro, "source", "unknown") or "unknown"),
            )
        )
        db.commit()
        return True
    except Exception as exc:
        logger.warning(f"Failed to persist BTC price snapshot: {exc}")
        try:
            db.rollback()
        except Exception:
            pass
        return False
    finally:
        try:
            db.close()
        except Exception:
            pass


def validate_btc_signal_for_simulation(signal: Any) -> tuple[bool, str]:
    """Return whether a BTC signal may create a simulation/paper trade.

    This guard is intentionally reusable outside FastAPI so tests can validate
    the safety rule without importing app/runtime dependencies. The dashboard
    hides the Trade button for filtered rows, but the API must also enforce the
    same no-forced-trade policy for direct endpoint calls.
    """
    if signal is None:
        return False, "No paper BTC trade: signal not found"

    reasons = list(getattr(signal, "no_trade_reasons", []) or [])
    if not bool(getattr(signal, "actionable", False)):
        if not reasons:
            reasons.append("signal did not pass BTC no-trade gates")
    if not bool(getattr(signal, "passes_threshold", False)):
        reasons.append("signal does not pass edge/actionability threshold")
    try:
        suggested_size = float(getattr(signal, "suggested_size", 0.0) or 0.0)
    except (TypeError, ValueError):
        suggested_size = 0.0
    if suggested_size <= 0:
        reasons.append("suggested paper size is zero")

    if reasons:
        return False, "No paper BTC trade: " + "; ".join(dict.fromkeys(reasons))
    return True, ""


def evaluate_btc_no_trade_gate(
    *,
    direction: str,
    settlement_source: Optional[str],
    model_price_source: Optional[str],
    up_bid: Optional[float],
    up_ask: Optional[float],
    up_ask_size: Optional[float],
    down_bid: Optional[float],
    down_ask: Optional[float],
    down_ask_size: Optional[float],
    max_entry_price: float,
    max_spread: float = 0.02,
    min_top_ask_size: float = 50.0,
    require_chainlink_model_source: bool = True,
    require_chainlink_boundary_snapshot: bool = True,
    chainlink_start_price: Optional[float] = None,
    chainlink_end_price: Optional[float] = None,
    chainlink_start_observed_at: Optional[int | str] = None,
    chainlink_end_observed_at: Optional[int | str] = None,
    chainlink_feed_id: Optional[str] = None,
    chainlink_capture_method: Optional[str] = None,
    chainlink_start_source_snapshot_path: Optional[str] = None,
    chainlink_end_source_snapshot_path: Optional[str] = None,
    expected_window_start_ts: Optional[int | str] = None,
    expected_window_end_ts: Optional[int | str] = None,
) -> BtcNoTradeGateResult:
    """Return whether a BTC signal is eligible for paper action.

    This is stricter than a generic signal threshold. It requires exact
    Chainlink settlement mapping and line-level executable book inputs. Until a
    Chainlink-aware model/source snapshot exists, exchange spot microstructure
    is allowed for research display but rejected for paper actionability.
    """
    reasons: list[str] = []
    normalized_direction = (direction or "").lower()
    normalized_settlement = (settlement_source or "").lower()
    normalized_model_source = (model_price_source or "").lower()

    if "chainlink" not in normalized_settlement or "btc" not in normalized_settlement:
        reasons.append("settlement source is not confirmed as Chainlink BTC/USD")

    if require_chainlink_model_source and "chainlink" not in normalized_model_source:
        reasons.append(
            f"model price source {model_price_source or 'unknown'} is not Chainlink settlement source"
        )

    if require_chainlink_boundary_snapshot:
        start_snapshot = BtcChainlinkBoundarySnapshot(
            price=chainlink_start_price,
            observed_at=chainlink_start_observed_at,
            feed_id=chainlink_feed_id or "",
            method=chainlink_capture_method or "unknown",
            source_snapshot_path=chainlink_start_source_snapshot_path,
        )
        end_snapshot = BtcChainlinkBoundarySnapshot(
            price=chainlink_end_price,
            observed_at=chainlink_end_observed_at,
            feed_id=chainlink_feed_id or "",
            method=chainlink_capture_method or "unknown",
            source_snapshot_path=chainlink_end_source_snapshot_path,
        )
        if chainlink_start_price is None or chainlink_end_price is None:
            reasons.append("missing Chainlink boundary source snapshot for this 5-minute window")
        if chainlink_start_observed_at is None or chainlink_end_observed_at is None:
            reasons.append("missing Chainlink boundary observation timestamp for this 5-minute window")
        for reason in validate_chainlink_boundary_snapshot(
            start_snapshot,
            expected_observed_at=expected_window_start_ts,
        ) + validate_chainlink_boundary_snapshot(
            end_snapshot,
            expected_observed_at=expected_window_end_ts,
        ):
            if reason not in reasons:
                reasons.append(reason)

    if normalized_direction == "up":
        bid = up_bid
        ask = up_ask
        ask_size = up_ask_size
    elif normalized_direction == "down":
        bid = down_bid
        ask = down_ask
        ask_size = down_ask_size
    else:
        bid = ask = ask_size = None
        reasons.append(f"unknown direction {direction!r}")

    spread: Optional[float] = None
    if bid is None or ask is None:
        reasons.append("missing line-level bid/ask")
    else:
        spread = round(ask - bid, 6)
        if spread < 0:
            reasons.append(f"invalid negative spread {spread:.3f}")
        elif spread > max_spread:
            reasons.append(f"spread {spread:.1%} exceeds {max_spread:.1%} max")

    if ask is None:
        reasons.append("missing executable ask price")
    elif ask > max_entry_price:
        reasons.append(f"entry ask {ask:.0%} exceeds {max_entry_price:.0%} max")

    if ask_size is None:
        reasons.append("missing top ask size")
    elif ask_size < min_top_ask_size:
        reasons.append(f"top ask size {ask_size:.2f} below {min_top_ask_size:.2f} minimum")

    return BtcNoTradeGateResult(
        actionable=not reasons,
        reasons=reasons,
        entry_price=ask,
        spread=spread,
        top_ask_size=ask_size,
    )
