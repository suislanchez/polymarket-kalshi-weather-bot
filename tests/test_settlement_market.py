"""Weather settlement must resolve the traded ladder rung, not markets[0]."""
import unittest

from backend.core.settlement import _parse_market_resolution, select_event_market


def _resolved(market_id, slug, yes_won):
    prices = ["1.0", "0.0"] if yes_won else ["0.0", "1.0"]
    return {
        "id": market_id,
        "slug": slug,
        "ticker": slug,
        "closed": True,
        "outcomePrices": prices,
    }


class SelectEventMarketTests(unittest.TestCase):
    def setUp(self):
        self.ladder_event = {
            "slug": "highest-temperature-in-miami-on-september-1",
            "markets": [
                _resolved("111", "miami-79-or-below", yes_won=False),
                _resolved("222", "miami-80-81", yes_won=True),
                _resolved("333", "miami-98-or-higher", yes_won=False),
            ],
        }

    def test_picks_traded_bracket_not_markets_zero(self):
        picked = select_event_market(self.ladder_event, "222")
        self.assertIsNotNone(picked)
        self.assertEqual(str(picked["id"]), "222")
        self.assertNotEqual(str(picked["id"]), str(self.ladder_event["markets"][0]["id"]))

        traded_resolved, traded_value = _parse_market_resolution(picked)
        first_resolved, first_value = _parse_market_resolution(self.ladder_event["markets"][0])
        self.assertTrue(traded_resolved)
        self.assertEqual(traded_value, 1.0)
        self.assertTrue(first_resolved)
        self.assertEqual(first_value, 0.0)

    def test_matches_market_slug_and_ticker(self):
        by_slug = select_event_market(self.ladder_event, "miami-80-81")
        self.assertEqual(str(by_slug["id"]), "222")

    def test_unmatched_ladder_does_not_fall_back_to_markets_zero(self):
        self.assertIsNone(select_event_market(self.ladder_event, "no-such-market"))

    def test_btc_single_market_event_still_resolves(self):
        btc_event = {
            "slug": "btc-updown-5m-1708531200",
            "markets": [_resolved("btc-1", "btc-updown-5m-1708531200", yes_won=True)],
        }
        matched = select_event_market(btc_event, "btc-1")
        self.assertEqual(str(matched["id"]), "btc-1")
        # One market per event: still works if the id field is missing from the lookup.
        fallback = select_event_market(btc_event, "missing-id")
        self.assertEqual(str(fallback["id"]), "btc-1")
        resolved, value = _parse_market_resolution(matched)
        self.assertTrue(resolved)
        self.assertEqual(value, 1.0)


if __name__ == "__main__":
    unittest.main()
