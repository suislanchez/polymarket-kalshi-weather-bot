"""Deterministic 20/50 SMA crossover proposal generation.

The strategy proposes only. It never submits, never sizes beyond the caller's
notional cap, and every rejection carries a fixed machine-readable reason.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import pytest

from backend.trading.domain import AssetClass, Side, TradeProposal, Venue
from backend.trading.market_data import (
    BarSeries,
    MarketBar,
    MarketDataError,
    load_bar_series,
)
from backend.trading.strategies import TrendFollowingStrategy
from backend.trading.strategies.trend_following import StrategySignal

FIXTURE = Path(__file__).resolve().parent / "fixtures" / "market_bars.json"
CAP = Decimal("250.0000")


@pytest.fixture(scope="module")
def series() -> dict[str, BarSeries]:
    payload = json.loads(FIXTURE.read_text())
    return {s["symbol"]: load_bar_series(s) for s in payload["series"]}


def strategy(**kw) -> TrendFollowingStrategy:
    return TrendFollowingStrategy(
        fast_window=kw.get("fast_window", 20),
        slow_window=kw.get("slow_window", 50),
        max_bar_age=kw.get("max_bar_age", timedelta(seconds=30)),
    )


def at(s: BarSeries, offset: int = 0) -> datetime:
    """A clock reading `offset` seconds after the series' last bar."""
    return s.bars[-1].timestamp + timedelta(seconds=offset)


def propose(s: BarSeries, **kw) -> StrategySignal:
    return strategy(**kw.pop("strategy", {})).propose(
        s,
        now=kw.pop("now", at(s)),
        notional_cap=kw.pop("notional_cap", CAP),
        position_quantity=kw.pop("position_quantity", Decimal("0")),
        **kw,
    )


# --- allowlist ----------------------------------------------------------------

@pytest.mark.parametrize("symbol", ["SPY", "QQQ", "BTC/USD", "ETH/USD"])
def test_supported_symbols_are_accepted(symbol, series):
    assert symbol in TrendFollowingStrategy.SUPPORTED_SYMBOLS


@pytest.mark.parametrize("symbol", ["TSLA", "DOGE/USD", "spy", "SPY ", "", "SPY/USD"])
def test_unsupported_symbols_yield_no_proposal(symbol, series):
    raw = json.loads(FIXTURE.read_text())["series"][0]
    hostile = dict(raw, symbol=symbol)
    if not symbol.strip():
        with pytest.raises(MarketDataError):
            load_bar_series(hostile)
        return
    signal = propose(load_bar_series(hostile))
    assert signal.proposal is None
    assert signal.reason == "symbol_not_supported"


# --- warm-up and data quality -------------------------------------------------

def test_insufficient_bars_yield_no_proposal(series):
    signal = propose(series["ETH/USD"])
    assert signal.proposal is None
    assert signal.reason == "insufficient_history"


def test_stale_bars_yield_no_proposal_with_reason(series):
    spy = series["SPY"]
    signal = propose(spy, now=at(spy, 31))
    assert signal.proposal is None
    assert signal.reason == "market_data_stale"


def test_bars_exactly_at_the_age_limit_are_still_fresh(series):
    spy = series["SPY"]
    assert propose(spy, now=at(spy, 30)).proposal is not None


def test_future_dated_bars_are_rejected(series):
    spy = series["SPY"]
    signal = propose(spy, now=at(spy, -1))
    assert signal.proposal is None
    assert signal.reason == "market_data_not_yet_valid"


@pytest.mark.parametrize(
    "mutation",
    ["duplicate_timestamp", "out_of_order", "negative_close", "missing_field", "non_decimal"],
)
def test_incomplete_or_malformed_bars_are_refused_at_load(mutation, series):
    raw = json.loads(FIXTURE.read_text())["series"][0]
    bars = [dict(b) for b in raw["bars"]]
    if mutation == "duplicate_timestamp":
        bars[10]["timestamp"] = bars[9]["timestamp"]
    elif mutation == "out_of_order":
        bars[10], bars[11] = bars[11], bars[10]
    elif mutation == "negative_close":
        bars[10]["close"] = "-5"
    elif mutation == "missing_field":
        bars[10].pop("close")
    elif mutation == "non_decimal":
        bars[10]["close"] = "not-a-number"
    with pytest.raises(MarketDataError):
        load_bar_series(dict(raw, bars=bars))


# --- crossover rules ----------------------------------------------------------

def test_golden_cross_creates_a_buy_proposal(series):
    signal = propose(series["SPY"])
    assert signal.reason == "golden_cross"
    proposal = signal.proposal
    assert proposal is not None
    assert type(proposal) is TradeProposal
    assert proposal.side is Side.BUY
    assert proposal.symbol == "SPY"
    assert proposal.asset_class is AssetClass.STOCK
    assert proposal.venue is Venue.ALPACA_PAPER
    assert proposal.notional == CAP
    assert proposal.quantity is None
    assert proposal.market_data_at == series["SPY"].bars[-1].timestamp


def test_no_cross_yields_no_proposal(series):
    signal = propose(series["BTC/USD"])
    assert signal.proposal is None
    assert signal.reason == "no_crossover"


def test_death_cross_without_a_long_position_yields_no_proposal(series):
    signal = propose(series["QQQ"], position_quantity=Decimal("0"))
    assert signal.proposal is None
    assert signal.reason == "no_long_to_reduce"


def test_death_cross_reduces_an_existing_long_only(series):
    signal = propose(series["QQQ"], position_quantity=Decimal("3.5"))
    proposal = signal.proposal
    assert signal.reason == "death_cross"
    assert proposal is not None
    assert proposal.side is Side.SELL
    assert proposal.quantity == Decimal("3.5")
    assert proposal.notional is None


def test_sell_never_exceeds_the_held_quantity(series):
    for held in ("0.25", "1", "10.125"):
        signal = propose(series["QQQ"], position_quantity=Decimal(held))
        assert signal.proposal.quantity == Decimal(held)


@pytest.mark.parametrize("held", ["-1", "-0.0001"])
def test_negative_position_quantity_is_refused(held, series):
    signal = propose(series["QQQ"], position_quantity=Decimal(held))
    assert signal.proposal is None
    assert signal.reason == "invalid_position_quantity"


def test_crypto_series_map_to_the_crypto_asset_class(series):
    """The same golden-cross shape on a crypto symbol yields a crypto proposal."""
    spy = json.loads(FIXTURE.read_text())["series"][0]
    crypto_bars = [
        dict(bar, open=bar["close"], close=bar["close"])
        for bar in spy["bars"]
    ]
    crypto = {"symbol": "ETH/USD", "asset_class": "crypto", "bars": crypto_bars}
    signal = propose(load_bar_series(crypto))
    assert signal.reason == "golden_cross"
    assert signal.proposal is not None
    assert signal.proposal.asset_class is AssetClass.CRYPTO
    assert signal.proposal.symbol == "ETH/USD"


# --- sizing and authority -----------------------------------------------------

@pytest.mark.parametrize("cap", ["0", "-1"])
def test_non_positive_notional_cap_is_refused(cap, series):
    signal = propose(series["SPY"], notional_cap=Decimal(cap))
    assert signal.proposal is None
    assert signal.reason == "invalid_notional_cap"


def test_proposal_never_sizes_beyond_the_requested_cap(series):
    for cap in ("10.0000", "250.0000", "1000.0000"):
        signal = propose(series["SPY"], notional_cap=Decimal(cap))
        assert signal.proposal.notional == Decimal(cap)


def test_strategy_has_no_execution_authority():
    """The strategy must not be able to submit, or even reach, an adapter."""
    import inspect

    from backend.trading.strategies import trend_following

    source = inspect.getsource(trend_following)
    for forbidden in ("submit_order", "adapter", "Adapter", "session", "commit", "requests"):
        assert forbidden not in source, forbidden


# --- determinism and rationale ------------------------------------------------

def test_deterministic_input_yields_byte_equivalent_proposals(series):
    first = propose(series["SPY"]).proposal
    second = propose(series["SPY"]).proposal
    assert first == second
    assert first.model_dump_json() == second.model_dump_json()
    assert first.proposal_id == second.proposal_id


def test_proposal_ids_differ_across_symbols_and_timestamps(series):
    spy = propose(series["SPY"]).proposal
    qqq = propose(series["QQQ"], position_quantity=Decimal("1")).proposal
    assert spy.proposal_id != qqq.proposal_id


def test_rationale_names_the_data_timestamp_and_the_rule(series):
    proposal = propose(series["SPY"]).proposal
    rationale = proposal.rationale
    assert "20" in rationale and "50" in rationale
    assert "SMA" in rationale.upper()
    assert series["SPY"].bars[-1].timestamp.isoformat().replace("+00:00", "Z") in rationale
    # Deterministic rule text, never model prose.
    for prose in ("I think", "likely", "suggests", "believe", "opinion", "recommend"):
        assert prose.lower() not in rationale.lower()


def test_rationale_is_stable_across_runs(series):
    assert propose(series["SPY"]).proposal.rationale == propose(series["SPY"]).proposal.rationale


@pytest.mark.parametrize("precision", [1, 3, 9, 15, 28, 60])
def test_signal_is_identical_under_any_ambient_decimal_precision(precision, series):
    """A caller's decimal context must never change the trading signal."""
    from decimal import localcontext

    with localcontext() as ctx:
        ctx.prec = precision
        signal = propose(series["SPY"])

    assert signal.reason == "golden_cross"
    assert signal.proposal is not None
    assert signal.proposal.notional == CAP


def test_serialized_proposal_is_byte_identical_across_decimal_precisions(series):
    from decimal import localcontext

    rendered = set()
    for precision in (1, 9, 28, 60):
        with localcontext() as ctx:
            ctx.prec = precision
            rendered.add(propose(series["SPY"]).proposal.model_dump_json())
    assert len(rendered) == 1


def test_no_crossover_verdict_is_also_precision_independent(series):
    from decimal import localcontext

    for precision in (1, 28):
        with localcontext() as ctx:
            ctx.prec = precision
            assert propose(series["BTC/USD"]).reason == "no_crossover"
