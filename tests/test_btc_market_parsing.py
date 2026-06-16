from datetime import datetime, timezone

from backend.data.btc_markets import _book_top_from_rows, _parse_event_to_btc_market


def test_parse_event_extracts_tokens_and_chainlink_settlement_source():
    event = {
        "slug": "btc-updown-5m-1779296400",
        "description": "This market resolves according to the Chainlink BTC/USD price stream.",
        "startDate": "2026-05-20T12:15:00Z",
        "endDate": "2026-05-20T12:20:00Z",
        "markets": [
            {
                "id": "123",
                "outcomes": '["Up", "Down"]',
                "clobTokenIds": '["up-token", "down-token"]',
                "outcomePrices": '["0.51", "0.50"]',
                "volume": "12.5",
                "closed": False,
            }
        ],
    }

    market = _parse_event_to_btc_market(event)

    assert market is not None
    assert market.up_token_id == "up-token"
    assert market.down_token_id == "down-token"
    assert market.up_price == 0.51
    assert market.down_price == 0.50
    assert market.settlement_source == "Chainlink BTC/USD"
    assert market.settlement_url == "https://data.chain.link/streams/btc-usd"
    assert market.chainlink_feed_id == "0x00039d9e45394f473ab1f050a1b963e6b05351e52d71e507509ada0c95ed75b8"
    assert market.chainlink_capture_method == "chainlink_data_streams_rest"
    assert market.chainlink_source_url == "https://data.chain.link/streams/btc-usd"


def test_parse_event_falls_back_to_slug_boundary_when_dates_missing():
    event = {
        "slug": "btc-updown-5m-1779873000",
        "description": "This market resolves according to the Chainlink BTC/USD price stream.",
        "markets": [
            {
                "id": "456",
                "outcomes": '["Up", "Down"]',
                "clobTokenIds": '["up-token", "down-token"]',
                "outcomePrices": '["0.51", "0.49"]',
                "volume": "22.0",
                "closed": False,
            }
        ],
    }

    market = _parse_event_to_btc_market(event)

    assert market is not None
    assert market.window_start == datetime.fromtimestamp(1779873000, tz=timezone.utc)
    assert market.window_end == datetime.fromtimestamp(1779873300, tz=timezone.utc)


def test_book_top_uses_highest_bid_and_lowest_ask_with_sizes():
    top = _book_top_from_rows(
        "token",
        {
            "bids": [
                {"price": "0.49", "size": "10"},
                {"price": "0.50", "size": "25"},
            ],
            "asks": [
                {"price": "0.53", "size": "40"},
                {"price": "0.51", "size": "60"},
            ],
        },
    )

    assert top.best_bid == 0.50
    assert top.best_bid_size == 25.0
    assert top.best_ask == 0.51
    assert top.best_ask_size == 60.0
    assert top.spread == 0.01
