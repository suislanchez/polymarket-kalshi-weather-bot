from backend.data.kalshi_markets import (
    CITY_CLI_PRODUCTS,
    CITY_SERIES,
    CITY_STATION_CODES,
    _direction_from_title,
    _parse_kalshi_orderbook_fp,
)


def test_parse_kalshi_orderbook_fp_cent_ladders_derives_yes_ask_from_no_bid():
    orderbook = {
        "yes": [[33, 12.5], [34, 3.0]],
        "no": [[64, 7.0], [65, 21.0]],
    }

    parsed = _parse_kalshi_orderbook_fp(orderbook)

    assert parsed.best_bid == 0.34
    assert parsed.best_ask == 0.35
    assert parsed.top_bid_size == 3.0
    assert parsed.top_ask_size == 21.0


def test_parse_kalshi_orderbook_fp_dollar_ladders_and_sorting():
    orderbook = {
        "yes_dollars": [["0.2700", "10"], ["0.3100", "4.5"], ["0.2900", "8"]],
        "no_dollars": [["0.6600", "11"], ["0.6400", "2"], ["0.6200", "9"]],
    }

    parsed = _parse_kalshi_orderbook_fp(orderbook)

    assert parsed.best_bid == 0.31
    assert parsed.best_ask == 0.34
    assert parsed.top_bid_size == 4.5
    assert parsed.top_ask_size == 11.0


def test_parse_kalshi_orderbook_fp_empty_book_returns_nones():
    parsed = _parse_kalshi_orderbook_fp({"yes": [], "no": []})

    assert parsed.best_bid is None
    assert parsed.best_ask is None
    assert parsed.top_bid_size is None
    assert parsed.top_ask_size is None


def test_parse_kalshi_orderbook_fp_cent_ladder_one_cent_is_not_one_dollar():
    parsed = _parse_kalshi_orderbook_fp({"yes": [[1, 6]], "no": [[99, 7]]})

    assert parsed.best_bid == 0.01
    assert parsed.best_ask == 0.01
    assert parsed.top_bid_size == 6.0
    assert parsed.top_ask_size == 7.0


def test_kalshi_direction_from_title_distinguishes_tails_and_buckets():
    assert _direction_from_title("Will the high temp in NYC be >79°?", "below") == "above"
    assert _direction_from_title("Will the high temp in NYC be <72°?", "above") == "below"
    assert _direction_from_title("Will the high temp in NYC be 78-79°?", "above") == "bucket"


def test_kalshi_weather_city_metadata_includes_seattle_and_boston():
    assert CITY_SERIES["seattle"] == "KXHIGHTSEA"
    assert CITY_STATION_CODES["seattle"] == "KSEA"
    assert CITY_CLI_PRODUCTS["seattle"] == "CLISEA"

    assert CITY_SERIES["boston"] == "KXHIGHTBOS"
    assert CITY_STATION_CODES["boston"] == "KBOS"
    assert CITY_CLI_PRODUCTS["boston"] == "CLIBOS"
