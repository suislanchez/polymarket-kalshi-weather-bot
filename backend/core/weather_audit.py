from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from os import PathLike
from pathlib import Path
import re
import sqlite3
from typing import Any, Iterable, Sequence

WEATHER_MARKET_TYPES: tuple[str, ...] = (
    "weather",
    "kalshi_weather",
    "polymarket_weather",
    "temperature",
    "rain",
)
INITIAL_WEATHER_BANKROLL = 1000.0
TARGET_WEATHER_BANKROLL = 1100.0
LATEST_SIGNAL_BATCH_MAX_GAP_SECONDS = 10

# Trailing windows reported alongside the strict/all-time view.
TRAILING_WINDOWS: tuple[tuple[str, int], ...] = (("72h", 72), ("7d", 168), ("14d", 336))
# Reliability bins for probability calibration.
DEFAULT_CALIBRATION_BIN_EDGES: tuple[float, ...] = (0.0, 0.2, 0.4, 0.6, 0.8, 1.0)

# Best-effort city extraction. Polymarket weather slugs look like
# "highest-temperature-in-seoul-on-june-6-2026"; Kalshi tickers look like
# "KXHIGHLAX-26JUN16-B73" (station code follows the metric prefix).
_POLY_CITY_RE = re.compile(r"temperature-in-([a-z][a-z\-]*?)-on-")
# Kalshi temperature series prefixes are inconsistent: highs are KXHIGH<station>
# while lows are KXLOWT<station> (e.g. KXLOWTDEN = low-temp Denver). List the
# longer "...T" prefixes first so the station code is captured, not the T.
_KALSHI_CITY_RE = re.compile(
    r"^KX(?:HIGHT|HIGH|LOWT|LOW|MAXT|MAX|MINT|MIN|AVGT|AVG)([A-Z]+?)(?:-|\d|$)"
)


@dataclass(frozen=True)
class WeatherTradeRow:
    id: int
    platform: str
    event_slug: str
    direction: str
    entry_price: float
    size: float
    timestamp: str
    settled: bool
    settlement_time: str | None
    result: str
    pnl: float | None
    model_probability: float | None = None
    market_price_at_entry: float | None = None
    edge_at_entry: float | None = None
    market_ticker: str | None = None


@dataclass(frozen=True)
class WeatherTradeSummary:
    total: int
    settled: int
    pending: int
    wins: int
    losses: int
    realized_pnl: float
    win_rate: float | None
    outlier_event_slug: str | None
    outlier_pnl: float | None
    ex_outlier_pnl: float


@dataclass(frozen=True)
class WeatherAccountState:
    initial_bankroll: float
    target_bankroll: float
    total_trades: int
    settled_trades: int
    pending_trades: int
    closed_early_trades: int
    pending_size: float
    realized_pnl: float
    equity_before_pending_marks: float
    remaining_to_target: float
    progress_pct: float


@dataclass(frozen=True)
class SignalBatchSummary:
    minute: str | None
    total: int
    actionable: int
    filtered: int
    positive_size: int
    executed: int


@dataclass(frozen=True)
class ProbabilityCalibrationBin:
    lower: float
    upper: float
    count: int
    mean_predicted: float | None
    empirical_win_rate: float | None


@dataclass(frozen=True)
class ProbabilityCalibrationSummary:
    """Model-probability-vs-outcome calibration over settled trades.

    ``brier_score`` is the mean squared error of the held-side win probability
    against the binary win/loss outcome (0 is perfect; 0.25 is a coin flip).
    """

    sample_size: int
    brier_score: float | None
    mean_predicted_win_prob: float | None
    empirical_win_rate: float | None
    bins: list[ProbabilityCalibrationBin] = field(default_factory=list)


@dataclass(frozen=True)
class WeatherAuditReport:
    generated_at: str
    window_hours: int
    strict_window: WeatherTradeSummary
    by_platform: dict[str, WeatherTradeSummary]
    latest_signal_batch: SignalBatchSummary
    account_state: WeatherAccountState
    all_time: WeatherTradeSummary | None = None
    trailing_windows: dict[str, WeatherTradeSummary] = field(default_factory=dict)
    by_city: dict[str, WeatherTradeSummary] = field(default_factory=dict)
    calibration: ProbabilityCalibrationSummary | None = None


def dataclass_to_dict(value: Any) -> Any:
    """Convert nested audit dataclasses to plain containers for JSON output."""
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


def connect_sqlite(path: str | PathLike[str]) -> sqlite3.Connection:
    """Open an existing SQLite database read-only for audit/reporting.

    `sqlite3.connect('missing.db')` silently creates a new DB by default. Audit
    reporting should never do that, so use SQLite's URI mode and force the
    connection into query-only mode after opening.
    """
    db_path = Path(path).expanduser()
    uri = f"{db_path.resolve(strict=False).as_uri()}?mode=ro"
    conn = sqlite3.connect(uri, uri=True)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA query_only = ON")
    return conn


def cutoff_from_window(now: datetime, window_hours: int) -> str:
    return (now - timedelta(hours=window_hours)).strftime("%Y-%m-%d %H:%M:%S")


def _format_sql_timestamp(value: datetime) -> str:
    return value.strftime("%Y-%m-%d %H:%M:%S")


def _parse_timestamp(value: Any) -> datetime | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M"):
            try:
                return datetime.strptime(text, fmt)
            except ValueError:
                continue
    return None


def _query_rows(
    conn: sqlite3.Connection,
    query: str,
    params: Sequence[Any] = (),
) -> list[dict[str, Any]]:
    """Fetch rows as dictionaries without requiring the caller to set row_factory."""
    cursor = conn.execute(query, params)
    columns = [description[0] for description in cursor.description]
    return [dict(zip(columns, row)) for row in cursor.fetchall()]


def _weather_type_placeholders() -> str:
    return ", ".join("?" for _ in WEATHER_MARKET_TYPES)


def _market_type_params(extra: Sequence[Any] = ()) -> tuple[Any, ...]:
    return (*WEATHER_MARKET_TYPES, *extra)


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return float(value)


def _rounded_float(value: float) -> float:
    return round(float(value), 2)


def _rounded_optional_float(value: Any) -> float | None:
    if value is None:
        return None
    return _rounded_float(float(value))


def _row_to_trade(row: dict[str, Any]) -> WeatherTradeRow:
    event_slug = row.get("event_slug") or row.get("market_ticker") or "unknown"
    return WeatherTradeRow(
        id=int(row["id"]),
        platform=str(row.get("platform") or "unknown"),
        event_slug=str(event_slug),
        direction=str(row.get("direction") or "unknown").lower(),
        entry_price=float(row.get("entry_price") or 0.0),
        size=float(row.get("size") or 0.0),
        timestamp=str(row.get("timestamp") or ""),
        settled=bool(row.get("settled")),
        settlement_time=row.get("settlement_time"),
        result=str(row.get("result") or "pending").lower(),
        pnl=_rounded_optional_float(row.get("pnl")),
        model_probability=_optional_float(row.get("model_probability")),
        market_price_at_entry=_optional_float(row.get("market_price_at_entry")),
        edge_at_entry=_optional_float(row.get("edge_at_entry")),
        market_ticker=(str(row["market_ticker"]) if row.get("market_ticker") else None),
    )


def load_weather_trades(
    conn: sqlite3.Connection,
    *,
    since: str,
    until: str | None = None,
) -> list[WeatherTradeRow]:
    where_until = "" if until is None else "AND timestamp <= ?"
    params: tuple[Any, ...]
    if until is None:
        params = _market_type_params((since,))
    else:
        params = _market_type_params((since, until))
    rows = _query_rows(
        conn,
        f"""
        SELECT id, market_ticker, platform, event_slug, direction, entry_price,
               size, timestamp, settled, settlement_time, result, pnl,
               model_probability, market_price_at_entry, edge_at_entry
        FROM trades
        WHERE market_type IN ({_weather_type_placeholders()})
          AND timestamp >= ?
          {where_until}
        ORDER BY timestamp ASC, id ASC
        """,
        params,
    )
    return [_row_to_trade(row) for row in rows]


def load_all_weather_trades(conn: sqlite3.Connection) -> list[WeatherTradeRow]:
    """Load every weather paper trade (no time filter) for all-time/by-city views."""
    rows = _query_rows(
        conn,
        f"""
        SELECT id, market_ticker, platform, event_slug, direction, entry_price,
               size, timestamp, settled, settlement_time, result, pnl,
               model_probability, market_price_at_entry, edge_at_entry
        FROM trades
        WHERE market_type IN ({_weather_type_placeholders()})
        ORDER BY timestamp ASC, id ASC
        """,
        WEATHER_MARKET_TYPES,
    )
    return [_row_to_trade(row) for row in rows]


def derive_city_label(
    event_slug: str | None,
    market_ticker: str | None,
    platform: str | None = None,
) -> str:
    """Best-effort city label from a Polymarket slug or Kalshi ticker.

    Returns ``"unknown"`` when nothing parseable is found. Labels are raw tokens
    (city slug or station code), not normalized to a canonical city key — the
    audit groups by what the ledger actually recorded.
    """
    slug = (event_slug or "").lower()
    match = _POLY_CITY_RE.search(slug)
    if match:
        return match.group(1)
    ticker = (market_ticker or "").upper()
    kalshi = _KALSHI_CITY_RE.match(ticker)
    if kalshi:
        return kalshi.group(1).lower()
    # Kalshi rows often store the ticker in event_slug too.
    kalshi_slug = _KALSHI_CITY_RE.match((event_slug or "").upper())
    if kalshi_slug:
        return kalshi_slug.group(1).lower()
    return "unknown"


def trade_win_probability(direction: str | None, model_probability: float | None) -> float | None:
    """Probability the *held side* wins, given the model's YES probability.

    The stored ``model_probability`` is always the model's YES/UP probability, so
    a NO/DOWN position wins with ``1 - model_probability``.
    """
    if model_probability is None:
        return None
    prob = float(model_probability)
    if str(direction or "").lower() in ("no", "down", "below", "sell"):
        return 1.0 - prob
    return prob


def summarize_probability_calibration(
    trades: Iterable[WeatherTradeRow],
    *,
    bin_edges: Sequence[float] = DEFAULT_CALIBRATION_BIN_EDGES,
) -> ProbabilityCalibrationSummary:
    """Brier score + reliability bins of held-side win prob vs win/loss outcome."""
    pairs: list[tuple[float, float]] = []
    for trade in trades:
        if not trade.settled or trade.result not in ("win", "loss"):
            continue
        prob = trade_win_probability(trade.direction, trade.model_probability)
        if prob is None:
            continue
        outcome = 1.0 if trade.result == "win" else 0.0
        pairs.append((max(0.0, min(1.0, prob)), outcome))

    if not pairs:
        return ProbabilityCalibrationSummary(
            sample_size=0,
            brier_score=None,
            mean_predicted_win_prob=None,
            empirical_win_rate=None,
            bins=[],
        )

    n = len(pairs)
    brier = sum((p - o) ** 2 for p, o in pairs) / n
    mean_pred = sum(p for p, _ in pairs) / n
    empirical = sum(o for _, o in pairs) / n

    edges = list(bin_edges)
    bins: list[ProbabilityCalibrationBin] = []
    for i in range(len(edges) - 1):
        lower, upper = edges[i], edges[i + 1]
        is_last = i == len(edges) - 2
        in_bin = [
            (p, o)
            for p, o in pairs
            if (lower <= p < upper) or (is_last and p == upper)
        ]
        if in_bin:
            mean_p = round(sum(p for p, _ in in_bin) / len(in_bin), 4)
            win_rate = round(sum(o for _, o in in_bin) / len(in_bin), 4)
        else:
            mean_p = None
            win_rate = None
        bins.append(
            ProbabilityCalibrationBin(
                lower=lower,
                upper=upper,
                count=len(in_bin),
                mean_predicted=mean_p,
                empirical_win_rate=win_rate,
            )
        )

    return ProbabilityCalibrationSummary(
        sample_size=n,
        brier_score=round(brier, 6),
        mean_predicted_win_prob=round(mean_pred, 6),
        empirical_win_rate=round(empirical, 6),
        bins=bins,
    )


def detect_largest_outlier(trades: Iterable[WeatherTradeRow]) -> WeatherTradeRow | None:
    settled = [trade for trade in trades if trade.settled and trade.pnl is not None]
    if not settled:
        return None
    return max(settled, key=lambda trade: abs(float(trade.pnl or 0.0)))


def aggregate_trades(trades: Iterable[WeatherTradeRow]) -> WeatherTradeSummary:
    rows = list(trades)
    settled = [trade for trade in rows if trade.settled]
    settled_with_pnl = [trade for trade in settled if trade.pnl is not None]
    wins = [trade for trade in settled if trade.result == "win"]
    losses = [trade for trade in settled if trade.result == "loss"]
    realized = _rounded_float(sum(float(trade.pnl or 0.0) for trade in settled_with_pnl))
    outlier = detect_largest_outlier(rows)
    outlier_pnl = None if outlier is None or outlier.pnl is None else _rounded_float(float(outlier.pnl))
    ex_outlier_pnl = _rounded_float(realized - (outlier_pnl or 0.0))
    win_rate = None if not settled else round(100.0 * len(wins) / len(settled), 1)
    return WeatherTradeSummary(
        total=len(rows),
        settled=len(settled),
        pending=len(rows) - len(settled),
        wins=len(wins),
        losses=len(losses),
        realized_pnl=realized,
        win_rate=win_rate,
        outlier_event_slug=None if outlier is None else outlier.event_slug,
        outlier_pnl=outlier_pnl,
        ex_outlier_pnl=ex_outlier_pnl,
    )


def load_weather_account_state(conn: sqlite3.Connection) -> WeatherAccountState:
    rows = _query_rows(
        conn,
        f"""
        SELECT settled, closed_early, size, pnl
        FROM trades
        WHERE market_type IN ({_weather_type_placeholders()})
        """,
        WEATHER_MARKET_TYPES,
    )
    total_trades = len(rows)
    closed_early = [row for row in rows if bool(row.get("closed_early"))]
    settled = [row for row in rows if bool(row.get("settled"))]
    pending = [row for row in rows if not bool(row.get("settled")) and not bool(row.get("closed_early"))]
    realized_pnl = _rounded_float(sum(float(row.get("pnl") or 0.0) for row in settled + closed_early))
    pending_size = _rounded_float(sum(float(row.get("size") or 0.0) for row in pending))
    equity = _rounded_float(INITIAL_WEATHER_BANKROLL + realized_pnl)
    remaining = _rounded_float(max(0.0, TARGET_WEATHER_BANKROLL - equity))
    target_gain = TARGET_WEATHER_BANKROLL - INITIAL_WEATHER_BANKROLL
    progress_pct = 100.0 if remaining == 0.0 else max(0.0, min(100.0, (realized_pnl / target_gain) * 100.0))
    return WeatherAccountState(
        initial_bankroll=INITIAL_WEATHER_BANKROLL,
        target_bankroll=TARGET_WEATHER_BANKROLL,
        total_trades=total_trades,
        settled_trades=len(settled),
        pending_trades=len(pending),
        closed_early_trades=len(closed_early),
        pending_size=pending_size,
        realized_pnl=realized_pnl,
        equity_before_pending_marks=equity,
        remaining_to_target=remaining,
        progress_pct=round(progress_pct, 1),
    )


def _load_recent_weather_signals(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    return _query_rows(
        conn,
        f"""
        SELECT timestamp, reasoning, suggested_size, executed
        FROM signals
        WHERE market_type IN ({_weather_type_placeholders()})
        ORDER BY timestamp DESC, id DESC
        LIMIT 1000
        """,
        WEATHER_MARKET_TYPES,
    )


def summarize_latest_signal_batch(conn: sqlite3.Connection) -> SignalBatchSummary:
    rows = _load_recent_weather_signals(conn)
    if not rows:
        return SignalBatchSummary(None, 0, 0, 0, 0, 0)

    latest_time = _parse_timestamp(rows[0].get("timestamp"))
    if latest_time is None:
        minute = str(rows[0].get("timestamp") or "")[:16] or None
        latest_batch = [rows[0]]
    else:
        latest_batch = []
        previous_time = latest_time
        for row in rows:
            timestamp = _parse_timestamp(row.get("timestamp"))
            if timestamp is None:
                break
            gap = abs((previous_time - timestamp).total_seconds())
            if latest_batch and gap > LATEST_SIGNAL_BATCH_MAX_GAP_SECONDS:
                break
            latest_batch.append(row)
            previous_time = timestamp
        minute = _format_sql_timestamp(latest_time)[:16]

    def reasoning_starts(row: dict[str, Any], prefix: str) -> bool:
        return str(row.get("reasoning") or "").startswith(prefix)

    return SignalBatchSummary(
        minute=minute,
        total=len(latest_batch),
        actionable=sum(1 for row in latest_batch if reasoning_starts(row, "[ACTIONABLE]")),
        filtered=sum(1 for row in latest_batch if reasoning_starts(row, "[FILTERED]")),
        positive_size=sum(1 for row in latest_batch if float(row.get("suggested_size") or 0.0) > 0.0),
        executed=sum(1 for row in latest_batch if bool(row.get("executed"))),
    )


def build_weather_audit(
    conn: sqlite3.Connection,
    *,
    now: datetime,
    window_hours: int,
) -> WeatherAuditReport:
    since = cutoff_from_window(now, window_hours)
    until = _format_sql_timestamp(now)
    trades = load_weather_trades(conn, since=since, until=until)
    by_platform_rows: dict[str, list[WeatherTradeRow]] = {}
    for trade in trades:
        by_platform_rows.setdefault(trade.platform, []).append(trade)

    all_trades = load_all_weather_trades(conn)

    by_city_rows: dict[str, list[WeatherTradeRow]] = {}
    for trade in all_trades:
        city = derive_city_label(trade.event_slug, trade.market_ticker, trade.platform)
        by_city_rows.setdefault(city, []).append(trade)

    trailing_windows: dict[str, WeatherTradeSummary] = {}
    for label, hours in TRAILING_WINDOWS:
        window_trades = load_weather_trades(
            conn, since=cutoff_from_window(now, hours), until=until
        )
        trailing_windows[label] = aggregate_trades(window_trades)

    return WeatherAuditReport(
        generated_at=now.isoformat(timespec="seconds"),
        window_hours=window_hours,
        strict_window=aggregate_trades(trades),
        by_platform={
            platform: aggregate_trades(platform_trades)
            for platform, platform_trades in sorted(by_platform_rows.items())
        },
        latest_signal_batch=summarize_latest_signal_batch(conn),
        account_state=load_weather_account_state(conn),
        all_time=aggregate_trades(all_trades),
        trailing_windows=trailing_windows,
        by_city={
            city: aggregate_trades(city_trades)
            for city, city_trades in sorted(by_city_rows.items())
        },
        calibration=summarize_probability_calibration(all_trades),
    )
