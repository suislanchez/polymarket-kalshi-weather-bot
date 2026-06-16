import asyncio

from backend.data.polymarket_client import (
    CLOB_API,
    DATA_API,
    GAMMA_API,
    PolymarketClient,
    map_outcome_tokens,
    parse_clob_book_top,
    parse_gamma_list,
)


def test_parse_gamma_list_accepts_json_strings_and_lists():
    assert parse_gamma_list('["Yes", "No"]') == ["Yes", "No"]
    assert parse_gamma_list(["Up", "Down"]) == ["Up", "Down"]
    assert parse_gamma_list(None) == []
    assert parse_gamma_list("not-json") == []


def test_map_outcome_tokens_preserves_outcome_names_and_token_ids():
    mapping = map_outcome_tokens('["Yes", "No"]', '["yes-token", "no-token"]')

    assert mapping["yes"].token_id == "yes-token"
    assert mapping["no"].token_id == "no-token"
    assert mapping["yes"].outcome == "Yes"


def test_map_outcome_tokens_handles_mismatched_lengths_without_crashing():
    mapping = map_outcome_tokens('["Yes", "No"]', '["yes-token"]')

    assert mapping["yes"].token_id == "yes-token"
    assert "no" not in mapping


def test_map_outcome_tokens_skips_missing_or_blank_token_ids():
    mapping = map_outcome_tokens(
        '["Yes", "No", "Maybe", "Other"]',
        '["yes-token", null, "   ", ""]',
    )

    assert list(mapping) == ["yes"]
    assert mapping["yes"].token_id == "yes-token"


def test_parse_clob_book_top_uses_highest_bid_lowest_ask_and_sizes():
    top = parse_clob_book_top(
        "yes-token",
        {
            "bids": [
                {"price": "0.41", "size": "15"},
                {"price": "0.43", "size": "7"},
            ],
            "asks": [
                {"price": "0.48", "size": "11.5"},
                {"price": "0.46", "size": "8.25"},
            ],
        },
    )

    assert top.token_id == "yes-token"
    assert top.best_bid == 0.43
    assert top.best_bid_size == 7.0
    assert top.best_ask == 0.46
    assert top.best_ask_size == 8.25
    assert top.spread == 0.03


class FakeResponse:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class FakeAsyncClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def get(self, url, params=None):
        self.calls.append((url, params))
        return self.responses.pop(0)


async def _fetch_events_with_fake_client():
    fake_client = FakeAsyncClient([FakeResponse([{"slug": "btc-up-down"}])])
    client = PolymarketClient(client=fake_client)  # type: ignore[arg-type]

    events = await client.fetch_events(active=True, limit=5)

    return events, fake_client.calls


def test_polymarket_client_fetch_events_calls_gamma_events_with_params():
    events, calls = asyncio.run(_fetch_events_with_fake_client())

    assert events == [{"slug": "btc-up-down"}]
    assert calls == [(f"{GAMMA_API}/events", {"active": True, "limit": 5})]


async def _fetch_market_with_fake_client():
    fake_client = FakeAsyncClient([FakeResponse({"id": "market-123"})])
    client = PolymarketClient(client=fake_client)  # type: ignore[arg-type]

    market = await client.fetch_market("market-123")

    return market, fake_client.calls


def test_polymarket_client_fetch_market_calls_gamma_market_by_id():
    market, calls = asyncio.run(_fetch_market_with_fake_client())

    assert market == {"id": "market-123"}
    assert calls == [(f"{GAMMA_API}/markets/market-123", None)]


async def _fetch_book_top_with_fake_client():
    fake_client = FakeAsyncClient(
        [
            FakeResponse(
                {
                    "bids": [{"price": "0.40", "size": "3"}],
                    "asks": [{"price": "0.44", "size": "6"}],
                }
            )
        ]
    )
    client = PolymarketClient(client=fake_client)  # type: ignore[arg-type]

    top = await client.fetch_book_top("yes-token")

    return top, fake_client.calls


def test_polymarket_client_fetch_book_top_calls_clob_and_parses_top():
    top, calls = asyncio.run(_fetch_book_top_with_fake_client())

    assert top.token_id == "yes-token"
    assert top.best_bid == 0.40
    assert top.best_ask == 0.44
    assert top.best_ask_size == 6.0
    assert calls == [(f"{CLOB_API}/book", {"token_id": "yes-token"})]


async def _fetch_best_effort_failures_with_fake_client():
    fake_client = FakeAsyncClient([
        FakeResponse({"error": "not found"}, status_code=404),
        FakeResponse({"error": "not found"}, status_code=404),
        FakeResponse({"error": "not found"}, status_code=404),
    ])
    client = PolymarketClient(client=fake_client)  # type: ignore[arg-type]

    events = await client.fetch_events(active=True)
    market = await client.fetch_market("missing-market")
    top = await client.fetch_book_top("missing-token")

    return events, market, top


def test_polymarket_client_best_effort_failures_return_empty_or_none():
    events, market, top = asyncio.run(_fetch_best_effort_failures_with_fake_client())

    assert events == []
    assert market is None
    assert top is None


async def _fetch_extended_endpoints_with_fake_client():
    fake_client = FakeAsyncClient(
        [
            FakeResponse([{"id": "m1"}]),
            FakeResponse({"price": "0.61"}),
            FakeResponse({"mid": "0.605"}),
            FakeResponse({"history": [{"p": "0.55"}, {"p": "0.60"}]}),
            FakeResponse([{"id": "trade-1"}]),
            FakeResponse([{"asset": "token-a"}]),
        ]
    )
    client = PolymarketClient(client=fake_client)  # type: ignore[arg-type]

    markets = await client.fetch_markets(closed=False, limit=10)
    price = await client.fetch_price("token-a", side="buy")
    midpoint = await client.fetch_midpoint("token-a")
    history = await client.fetch_prices_history(market="0xabc", interval="1h")
    trades = await client.fetch_trades(limit=5)
    positions = await client.fetch_positions(user="0xabc", limit=5)

    return (markets, price, midpoint, history, trades, positions, fake_client.calls)


def test_polymarket_client_extended_endpoints():
    markets, price, midpoint, history, trades, positions, calls = asyncio.run(
        _fetch_extended_endpoints_with_fake_client()
    )

    assert markets == [{"id": "m1"}]
    assert price == 0.61
    assert midpoint == 0.605
    assert history == [{"p": "0.55"}, {"p": "0.60"}]
    assert trades == [{"id": "trade-1"}]
    assert positions == [{"asset": "token-a"}]
    assert calls == [
        (f"{GAMMA_API}/markets", {"closed": False, "limit": 10}),
        (f"{CLOB_API}/price", {"token_id": "token-a", "side": "buy"}),
        (f"{CLOB_API}/midpoint", {"token_id": "token-a"}),
        (f"{CLOB_API}/prices-history", {"market": "0xabc", "interval": "1h"}),
        (f"{DATA_API}/trades", {"limit": 5}),
        (f"{DATA_API}/positions", {"user": "0xabc", "limit": 5}),
    ]
