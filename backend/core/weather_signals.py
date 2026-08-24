"""Signal generator for weather temperature markets using ensemble forecasts."""
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime
from typing import List, Optional

from backend.config import settings
from backend.core.signals import calculate_edge, calculate_kelly_size
from backend.core.weather_calibration import (
    calibrate_weather_probability,
    config_from_settings,
    reliability_weight_from_brier,
)
from backend.core.weather_audit import (
    WeatherTradeRow,
    summarize_probability_calibration_by_platform,
)
from backend.core.weather_scan_runtime import map_concurrently, prefetch_forecasts
from backend.core.weather_methodology import (
    WeatherBucketLine,
    WeatherGateInput,
    estimate_bucket_probability,
    evaluate_bucket_set_sanity,
    evaluate_weather_trade_gate,
)
from backend.core.weather_paper_account import (
    build_weather_signal_review_candidate_rows,
    persist_weather_signal_review_candidate_rows_to_sqlite,
    should_persist_weather_signal_for_calibration,
)
from backend.data.weather import fetch_ensemble_forecast, EnsembleForecast, CITY_CONFIG
from backend.data.noaa_aigefs import fetch_aigefs_forecast
from backend.data.weather_markets import WeatherMarket, fetch_polymarket_weather_markets
from backend.models.database import SessionLocal, Signal, Trade

logger = logging.getLogger("trading_bot")


@dataclass
class WeatherTradingSignal:
    """A trading signal for a weather temperature market."""
    market: WeatherMarket

    # Core signal data
    model_probability: float = 0.5   # Ensemble probability of YES outcome
    market_probability: float = 0.5  # Market's implied YES probability
    edge: float = 0.0
    direction: str = "yes"           # "yes" or "no"

    # Confidence and sizing
    confidence: float = 0.5
    kelly_fraction: float = 0.0
    suggested_size: float = 0.0

    # Metadata
    sources: List[str] = field(default_factory=list)
    reasoning: str = ""
    timestamp: datetime = field(default_factory=datetime.utcnow)

    # Forecast context
    ensemble_mean: float = 0.0
    ensemble_std: float = 0.0
    ensemble_members: int = 0
    no_trade_reasons: List[str] = field(default_factory=list)
    execution_spread: Optional[float] = None
    top_ask_size: Optional[float] = None
    bucket_set_probability_mass: Optional[float] = None
    bucket_set_sanity_passed: bool = False
    bucket_set_size: int = 0

    # Execution quality score
    composite_score: float = 0.0
    score_components: dict = field(default_factory=dict)

    @property
    def passes_threshold(self) -> bool:
        """Check if signal passes minimum edge threshold."""
        return abs(self.edge) >= settings.WEATHER_MIN_EDGE_THRESHOLD


def _clamp01(value: float) -> float:
    return max(0.0, min(1.0, value))


def _normalized_spread_penalty(best_bid: Optional[float], best_ask: Optional[float]) -> float:
    if best_bid is None or best_ask is None:
        return 0.5
    spread = max(0.0, best_ask - best_bid)
    # 0 spread => 1.0 quality ; >= 20c spread => 0 quality
    return _clamp01(1.0 - (spread / 0.20))


def _normalized_liquidity(top_ask_size: Optional[float], volume: float) -> float:
    ask_quality = _clamp01((top_ask_size or 0.0) / 500.0)
    volume_quality = _clamp01(max(0.0, volume) / 5000.0)
    return _clamp01(0.6 * ask_quality + 0.4 * volume_quality)


def _normalized_orderbook_imbalance(
    best_bid: Optional[float],
    best_ask: Optional[float],
    yes_last_price: Optional[float],
) -> float:
    if best_bid is None or best_ask is None or yes_last_price is None:
        return 0.5
    midpoint = (best_bid + best_ask) / 2.0
    # Small deviation from midpoint is healthier; >5c drift gets heavily penalized.
    drift = abs(yes_last_price - midpoint)
    return _clamp01(1.0 - (drift / 0.05))


def _weather_trade_row_from_model(trade: Trade) -> WeatherTradeRow:
    """Convert an ORM Trade row into the audit calibration DTO."""
    return WeatherTradeRow(
        id=int(trade.id),
        platform=str(trade.platform or "unknown"),
        event_slug=str(trade.event_slug or trade.market_ticker or "unknown"),
        direction=str(trade.direction or "unknown"),
        entry_price=float(trade.entry_price or 0.0),
        size=float(trade.size or 0.0),
        timestamp=str(trade.timestamp or ""),
        settled=bool(trade.settled),
        settlement_time=None if trade.settlement_time is None else str(trade.settlement_time),
        result=str(trade.result or "pending"),
        pnl=None if trade.pnl is None else float(trade.pnl),
        model_probability=None if trade.model_probability is None else float(trade.model_probability),
        market_price_at_entry=None if trade.market_price_at_entry is None else float(trade.market_price_at_entry),
        edge_at_entry=None if trade.edge_at_entry is None else float(trade.edge_at_entry),
        market_ticker=None if trade.market_ticker is None else str(trade.market_ticker),
    )


def load_venue_reliability_weights_from_ledger() -> dict[str, float]:
    """Load per-venue calibration reliability weights from settled weather paper trades.

    This is a conservative read-only input to signal generation. If the ledger is
    missing/unreadable, the caller falls back to neutral reliability (1.0) rather
    than blocking market discovery.
    """
    db = SessionLocal()
    try:
        trades = db.query(Trade).filter(Trade.market_type == "weather").all()
        calibration_by_platform = summarize_probability_calibration_by_platform(
            _weather_trade_row_from_model(trade) for trade in trades
        )
        return {
            platform: reliability_weight_from_brier(
                brier=summary.brier_score,
                sample_size=summary.sample_size,
            )
            for platform, summary in calibration_by_platform.items()
            if summary.sample_size > 0
        }
    except Exception as exc:  # noqa: BLE001 - calibration should not kill scans
        logger.warning("Failed to load venue reliability weights: %s", exc)
        return {}
    finally:
        db.close()


def compute_weather_composite_score(
    *,
    mispricing_edge: float,
    best_bid: Optional[float],
    best_ask: Optional[float],
    top_ask_size: Optional[float],
    volume: float,
    yes_last_price: Optional[float],
) -> float:
    """Composite score in [0,1] blending edge and execution quality."""
    edge_component = _clamp01(abs(mispricing_edge) / 0.20)
    if edge_component <= 0.0:
        return 0.0
    spread_component = _normalized_spread_penalty(best_bid, best_ask)
    liquidity_component = _normalized_liquidity(top_ask_size, volume)
    imbalance_component = _normalized_orderbook_imbalance(best_bid, best_ask, yes_last_price)

    score = (
        settings.WEATHER_WEIGHT_MISPRICING * edge_component
        + settings.WEATHER_WEIGHT_SPREAD * spread_component
        + settings.WEATHER_WEIGHT_LIQUIDITY * liquidity_component
        + settings.WEATHER_WEIGHT_IMBALANCE * imbalance_component
    )
    return _clamp01(score)


async def generate_weather_signal(
    market: WeatherMarket,
    *,
    forecast: Optional[EnsembleForecast] = None,
    venue_reliability: float = 1.0,
) -> Optional[WeatherTradingSignal]:
    """
    Generate a trading signal for a weather temperature market.

    Uses ensemble forecast to estimate probability:
    - Count fraction of ensemble members above/below the threshold
    - Compare to market price to find edge
    - Size using Kelly criterion

    ``forecast`` may be supplied by the scan runtime (one fetch per unique
    city/date); when omitted it is fetched here (with the 15-minute cache).
    """
    if forecast is None:
        forecast = await fetch_ensemble_forecast(market.city_key, market.target_date)
    if not forecast or not forecast.member_highs:
        return None

    manual_no_trade_reasons: List[str] = []

    # Calculate model probability based on market's question. Bucket markets use
    # an inclusive range count when parsed, but remain blocked for paper
    # actionability until the full mutually-exclusive bucket set has a
    # one-winner sanity check.
    if market.direction == "bucket":
        members = forecast.member_highs if market.metric == "high" else forecast.member_lows
        model_yes_prob = estimate_bucket_probability(
            members,
            market.bucket_low_f,
            market.bucket_high_f,
        )
        manual_no_trade_reasons.append("bucket market requires mutually-exclusive set sanity check before actionability")
    elif market.metric == "high":
        if market.direction == "above":
            model_yes_prob = forecast.probability_high_above(market.threshold_f)
        else:
            model_yes_prob = forecast.probability_high_below(market.threshold_f)
    else:  # "low"
        if market.direction == "above":
            model_yes_prob = forecast.probability_low_above(market.threshold_f)
        else:
            model_yes_prob = forecast.probability_low_below(market.threshold_f)

    source_tags = [f"open_meteo_ensemble_{forecast.num_members}m"]

    # Optional secondary NOAA AIGEFS provider (defensive fallback)
    if settings.WEATHER_USE_AIGEFS:
        aigefs = await fetch_aigefs_forecast(market.city_key, market.target_date)
        if aigefs and aigefs.member_highs:
            if market.direction == "bucket":
                alt_members = aigefs.member_highs if market.metric == "high" else aigefs.member_lows
                aigefs_yes_prob = estimate_bucket_probability(
                    alt_members,
                    market.bucket_low_f,
                    market.bucket_high_f,
                )
            elif market.metric == "high":
                aigefs_yes_prob = (
                    aigefs.probability_high_above(market.threshold_f)
                    if market.direction == "above"
                    else aigefs.probability_high_below(market.threshold_f)
                )
            else:
                aigefs_yes_prob = (
                    aigefs.probability_low_above(market.threshold_f)
                    if market.direction == "above"
                    else aigefs.probability_low_below(market.threshold_f)
                )

            blend_weight = max(0.0, min(1.0, settings.WEATHER_AIGEFS_WEIGHT))
            model_yes_prob = (1.0 - blend_weight) * model_yes_prob + blend_weight * aigefs_yes_prob
            source_tags.append(f"aigefs_ensemble_{aigefs.num_members}m")
        else:
            source_tags.append("aigefs_fallback_open_meteo")

    # Ensemble stats for display, gating, and calibration.
    mean_val = forecast.mean_high if market.metric == "high" else forecast.mean_low
    std_val = forecast.std_high if market.metric == "high" else forecast.std_low

    # Calibration / anti-overconfidence. Replaces a naive [5%, 95%] clip with a
    # variance-inflated Gaussian estimate, and surfaces a confidence flag so a
    # clipped 95%/5% unanimity near a threshold cannot, by itself, be actionable.
    calibration = None
    if settings.WEATHER_CALIBRATION_ENABLED:
        calibration = calibrate_weather_probability(
            metric=market.metric,
            direction=market.direction,
            threshold_f=market.threshold_f,
            bucket_low_f=market.bucket_low_f,
            bucket_high_f=market.bucket_high_f,
            ensemble_mean=mean_val,
            ensemble_std=std_val,
            ensemble_members=forecast.num_members,
            raw_probability=model_yes_prob,
            exact_source=bool(market.settlement_source and market.settlement_station),
            venue_reliability=venue_reliability,
            config=config_from_settings(),
        )
        model_yes_prob = calibration.calibrated_probability
        source_tags.append(
            f"calibration:z={calibration.threshold_z},conf={calibration.confident},venue_reliability={venue_reliability:.2f}"
        )
        if not calibration.confident and market.direction in ("above", "below"):
            manual_no_trade_reasons.append(
                "calibration not confident: "
                + (calibration.reasons[0] if calibration.reasons else "low threshold separation")
            )
    else:
        # Fallback clip if calibration is disabled (ensemble can be unanimous).
        model_yes_prob = max(0.05, min(0.95, model_yes_prob))

    market_yes_prob = market.yes_price

    # Use existing edge calculation (treats yes=up, no=down)
    raw_edge, direction_raw = calculate_edge(model_yes_prob, market_yes_prob)
    edge = raw_edge
    direction = "yes" if direction_raw == "up" else "no"

    # Entry price and live executable book filter. Use the held side's live
    # bid/ask/depth, not always the Yes side; otherwise NO bets can look cheap
    # from stale/derived odds while the live No ask/depth says otherwise.
    if direction == "yes":
        entry_price = market.best_ask if market.best_ask is not None else market.yes_price
        side_best_bid = market.best_bid
        side_best_ask = market.best_ask
        side_top_ask_size = market.top_ask_size
    else:
        entry_price = market.no_best_ask if market.no_best_ask is not None else market.no_price
        side_best_bid = market.no_best_bid
        side_best_ask = market.no_best_ask
        side_top_ask_size = market.no_top_ask_size
    if entry_price > settings.WEATHER_MAX_ENTRY_PRICE:
        edge = 0.0  # Zero out but still return for UI visibility

    # Confidence = ensemble agreement (how one-sided the members are)
    if market.metric == "high":
        members = forecast.member_highs
    else:
        members = forecast.member_lows

    threshold_for_confidence = market.threshold_f if market.threshold_f is not None else mean_val
    above_count = sum(1 for m in members if m > threshold_for_confidence)
    agreement_frac = max(above_count, len(members) - above_count) / len(members)
    confidence = min(0.9, agreement_frac)

    gate = evaluate_weather_trade_gate(
        WeatherGateInput(
            settlement_source=market.settlement_source,
            station_code=market.settlement_station,
            market_probability=entry_price,
            best_bid=side_best_bid,
            best_ask=side_best_ask,
            top_ask_size=side_top_ask_size,
            ensemble_mean=mean_val,
            threshold_f=market.threshold_f,
            target_date=market.target_date,
        )
    )
    if not gate.allowed or manual_no_trade_reasons:
        # Keep the signal visible for research/calibration, but make it
        # non-executable in the simulation ledger until source/depth gates pass.
        edge = 0.0

    no_trade_reasons = [*manual_no_trade_reasons, *gate.reasons]

    composite_score = compute_weather_composite_score(
        mispricing_edge=raw_edge,
        best_bid=side_best_bid,
        best_ask=side_best_ask,
        top_ask_size=side_top_ask_size,
        volume=market.volume,
        yes_last_price=market.yes_last_price,
    )
    score_components = {
        "mispricing_edge": round(abs(raw_edge), 4),
        "spread_quality": round(_normalized_spread_penalty(side_best_bid, side_best_ask), 4),
        "liquidity_quality": round(_normalized_liquidity(side_top_ask_size, market.volume), 4),
        "imbalance_quality": round(_normalized_orderbook_imbalance(side_best_bid, side_best_ask, entry_price), 4),
    }
    if composite_score < settings.WEATHER_COMPOSITE_MIN_SCORE:
        no_trade_reasons.append(
            f"composite score {composite_score:.2f} below min {settings.WEATHER_COMPOSITE_MIN_SCORE:.2f}"
        )
        edge = 0.0

    # Kelly sizing
    bankroll = settings.INITIAL_BANKROLL
    kelly_market_price = entry_price if direction_raw == "up" else 1.0 - entry_price
    suggested_size = calculate_kelly_size(
        edge=abs(edge),
        probability=model_yes_prob,
        market_price=kelly_market_price,
        direction=direction_raw,  # calculate_kelly_size expects "up"/"down"
        bankroll=bankroll,
    )
    suggested_size = min(suggested_size, settings.WEATHER_MAX_TRADE_SIZE)
    if edge == 0.0 or no_trade_reasons:
        suggested_size = 0.0

    # Build reasoning
    filter_status = "ACTIONABLE" if abs(edge) >= settings.WEATHER_MIN_EDGE_THRESHOLD else "FILTERED"
    filter_notes = []
    if entry_price > settings.WEATHER_MAX_ENTRY_PRICE:
        filter_notes.append(f"entry {entry_price:.0%} > {settings.WEATHER_MAX_ENTRY_PRICE:.0%}")
    if no_trade_reasons:
        filter_notes.extend(no_trade_reasons)
    filter_note = f" [{', '.join(filter_notes)}]" if filter_notes else ""

    reasoning = (
        f"[{filter_status}]{filter_note} "
        f"{market.city_name} {market.metric} {market.direction} {market.threshold_f:.0f}F on {market.target_date} | "
        f"Ensemble: {mean_val:.1f}F +/- {std_val:.1f}F ({forecast.num_members} members) | "
        f"Model YES: {model_yes_prob:.0%} vs Market: {market_yes_prob:.0%} | "
        f"Edge: {edge:+.1%} -> {direction.upper()} @ {entry_price:.0%} | "
        f"Composite: {composite_score:.2f} (spread={score_components['spread_quality']:.2f}, "
        f"liq={score_components['liquidity_quality']:.2f}, imb={score_components['imbalance_quality']:.2f}) | "
        f"Agreement: {agreement_frac:.0%}"
    )

    return WeatherTradingSignal(
        market=market,
        model_probability=model_yes_prob,
        market_probability=market_yes_prob,
        edge=edge,
        direction=direction,
        confidence=confidence,
        kelly_fraction=suggested_size / bankroll if bankroll > 0 else 0,
        suggested_size=suggested_size,
        sources=[
            *source_tags,
            *( [f"kalshi_outcome_text:{market.title}"] if market.platform == "kalshi" and market.title else [] ),
            *( [f"settlement:{market.settlement_source}:{market.settlement_station}"] if market.settlement_source else [] ),
            *( [f"settlement_url:{market.settlement_source_url}"] if market.settlement_source_url else [] ),
        ],
        reasoning=reasoning,
        ensemble_mean=mean_val,
        ensemble_std=std_val,
        ensemble_members=forecast.num_members,
        no_trade_reasons=no_trade_reasons,
        execution_spread=gate.execution_spread,
        top_ask_size=side_top_ask_size,
        composite_score=composite_score,
        score_components=score_components,
    )


def _annotate_bucket_set_sanity(signals: List[WeatherTradingSignal]) -> None:
    """Attach same-city/date bucket-set diagnostics to bucket signals.

    The annotation is read-only and only adds blockers/metadata. It never turns
    a signal actionable; buckets remain non-executable unless a later, explicit
    gate removes all no-trade reasons.
    """
    groups: dict[tuple[str, str, object, str], list[WeatherTradingSignal]] = {}
    for signal in signals:
        if signal.market.direction != "bucket":
            continue
        key = (
            signal.market.platform,
            signal.market.city_key,
            signal.market.target_date,
            signal.market.metric,
        )
        groups.setdefault(key, []).append(signal)

    for bucket_signals in groups.values():
        diagnostic = evaluate_bucket_set_sanity(
            WeatherBucketLine(
                market_id=s.market.market_id,
                bucket_low_f=s.market.bucket_low_f,
                bucket_high_f=s.market.bucket_high_f,
                model_probability=s.model_probability,
            )
            for s in bucket_signals
        )
        blocker = None
        if not diagnostic.passed:
            blocker = "; ".join(diagnostic.reasons)
        for signal in bucket_signals:
            signal.bucket_set_probability_mass = diagnostic.probability_mass
            signal.bucket_set_sanity_passed = diagnostic.passed
            signal.bucket_set_size = diagnostic.line_count
            if blocker and blocker not in signal.no_trade_reasons:
                signal.no_trade_reasons.append(blocker)
            if blocker and blocker not in signal.reasoning:
                signal.reasoning = f"{signal.reasoning} | Bucket-set diagnostic: {blocker}"
            signal.edge = 0.0
            signal.suggested_size = 0.0
            signal.kelly_fraction = 0.0


async def scan_for_weather_signals() -> List[WeatherTradingSignal]:
    """
    Scan weather markets and generate ensemble-based signals.
    """
    signals = []

    city_keys = [c.strip() for c in settings.WEATHER_CITIES.split(",") if c.strip()]

    logger.info("=" * 50)
    logger.info("WEATHER SCAN: Fetching temperature markets...")

    markets = []

    # Polymarket
    try:
        poly_markets = await fetch_polymarket_weather_markets(city_keys)
        markets.extend(poly_markets)
        logger.info(f"Polymarket: {len(poly_markets)} weather markets")
    except Exception as e:
        logger.error(f"Failed to fetch Polymarket weather markets: {e}")

    # Kalshi public market-data endpoints do not require credentials. Keep this
    # path read-only/simulation-safe and do not block weather discovery on
    # private exchange account setup.
    if settings.KALSHI_ENABLED or settings.WEATHER_RESEARCH_ENABLED:
        try:
            from backend.data.kalshi_markets import fetch_kalshi_weather_markets
            kalshi_markets = await fetch_kalshi_weather_markets(city_keys)
            markets.extend(kalshi_markets)
            logger.info(f"Kalshi: {len(kalshi_markets)} weather markets")
        except Exception as e:
            logger.error(f"Failed to fetch Kalshi weather markets: {e}")

    logger.info(f"Found {len(markets)} total weather temperature markets")

    venue_reliability = load_venue_reliability_weights_from_ledger()
    if venue_reliability:
        logger.info("Venue calibration reliability weights: %s", venue_reliability)

    # Prefetch one forecast per unique (city, date) under bounded concurrency, so
    # the many bucket lines that share a city/day do not each hit the provider.
    concurrency = max(1, int(settings.WEATHER_SCAN_CONCURRENCY))
    forecast_map, runtime_stats = await prefetch_forecasts(
        markets, fetcher=fetch_ensemble_forecast, concurrency=concurrency
    )
    logger.info(
        "Forecast prefetch: %s markets -> %s unique city/date forecasts (%s errors)",
        runtime_stats.market_count,
        runtime_stats.unique_forecast_keys,
        runtime_stats.forecast_errors,
    )

    async def _generate(market: WeatherMarket) -> Optional[WeatherTradingSignal]:
        try:
            forecast = forecast_map.get((market.city_key, market.target_date))
            reliability = venue_reliability.get(str(market.platform or "").lower(), 1.0)
            return await generate_weather_signal(
                market,
                forecast=forecast,
                venue_reliability=reliability,
            )
        except Exception as e:  # noqa: BLE001 - one bad market must not abort the scan
            logger.debug(f"Weather signal generation failed for {market.title}: {e}")
            return None

    generated = await map_concurrently(markets, _generate, concurrency=concurrency)
    signals = [signal for signal in generated if signal]

    _annotate_bucket_set_sanity(signals)

    # Sort by absolute edge
    signals.sort(key=lambda s: abs(s.edge), reverse=True)

    actionable = [s for s in signals if s.passes_threshold]
    logger.info(f"WEATHER SCAN COMPLETE: {len(signals)} signals, {len(actionable)} actionable")

    for signal in actionable[:5]:
        logger.info(f"  {signal.market.city_name}: {signal.market.metric} {signal.market.direction} "
                     f"{signal.market.threshold_f:.0f}F | Edge: {signal.edge:+.1%}")

    _persist_weather_review_candidates(signals)

    # Persist signals to DB
    _persist_weather_signals(signals)

    return signals


def _persist_weather_review_candidates(signals: list):
    """Export threshold-passing weather candidates for manual review only.

    This writes to the research SQLite database, not the app trade ledger. Rows
    are forced non-actionable/non-executed by the helper and are meant to retain
    diagnostics for later revalidation.
    """
    captured_at = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    rows = build_weather_signal_review_candidate_rows(
        signals,
        captured_at=captured_at,
        min_abs_edge=settings.WEATHER_MIN_EDGE_THRESHOLD,
    )
    if not rows:
        return
    db_path = "/Users/kayvonai/.hermes/research/prediction-market-edge-snapshots.sqlite"
    try:
        with sqlite3.connect(db_path) as conn:
            inserted = persist_weather_signal_review_candidate_rows_to_sqlite(conn, rows)
        logger.info("Persisted %s weather review-only candidate rows", inserted)
    except Exception as e:
        logger.warning("Failed to persist weather review-only candidates: %s", e)

def _persist_weather_signals(signals: list):
    """Save weather signals to DB for calibration/review tracking.

    This writes non-executed signal rows only. It does not create paper trades,
    live orders, or bypass no-trade gates; blocked rows keep ``edge=0`` and
    ``suggested_size=0`` but remain available for future forecast calibration.
    """
    to_save = [s for s in signals if should_persist_weather_signal_for_calibration(s)]
    if not to_save:
        return

    db = SessionLocal()
    try:
        for signal in to_save:
            # Dedup: skip if already logged for this market
            existing = db.query(Signal).filter(
                Signal.market_ticker == signal.market.market_id,
                Signal.timestamp >= signal.timestamp.replace(second=0, microsecond=0),
            ).first()
            if existing:
                continue

            db_signal = Signal(
                market_ticker=signal.market.market_id,
                platform=signal.market.platform,
                market_type="weather",
                timestamp=signal.timestamp,
                direction=signal.direction,
                model_probability=signal.model_probability,
                market_price=signal.market_probability,
                edge=signal.edge,
                confidence=signal.confidence,
                kelly_fraction=signal.kelly_fraction,
                suggested_size=signal.suggested_size,
                sources=signal.sources,
                reasoning=signal.reasoning,
                executed=False,
            )
            db.add(db_signal)

        db.commit()
    except Exception as e:
        logger.warning(f"Failed to persist weather signals: {e}")
        db.rollback()
    finally:
        db.close()
