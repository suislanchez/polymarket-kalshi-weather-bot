from backend.data.weather_markets import _parse_json_list, _parse_polymarket_clob_book


def test_parse_json_list_accepts_gamma_json_string_fields():
    assert _parse_json_list('["Yes", "No"]') == ["Yes", "No"]
    assert _parse_json_list(["123", "456"]) == ["123", "456"]
    assert _parse_json_list('not-json') == []


def test_parse_polymarket_clob_book_extracts_best_yes_bid_ask_and_top_ask_size():
    book = {
        "bids": [
            {"price": "0.41", "size": "15"},
            {"price": "0.43", "size": "7"},
        ],
        "asks": [
            {"price": "0.48", "size": "11.5"},
            {"price": "0.46", "size": "8.25"},
        ],
    }

    best_bid, best_ask, top_ask_size = _parse_polymarket_clob_book(book)

    assert best_bid == 0.43
    assert best_ask == 0.46
    assert top_ask_size == 8.25
