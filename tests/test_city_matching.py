"""City alias matching must be whole-token, not substring."""
import unittest
from datetime import date, timedelta

from backend.data.weather_markets import _match_city, _parse_weather_event


def _future_title_date() -> str:
    return (date.today() + timedelta(days=45)).strftime("%B %d, %Y")


def _event(city_phrase: str, market_id: str = "1"):
    when = _future_title_date()
    return {
        "title": f"Highest temperature in {city_phrase} on {when}?",
        "slug": f"highest-temperature-in-{city_phrase.lower().replace(' ', '-')}",
        "markets": [
            {
                "id": market_id,
                "groupItemTitle": "80-81°F",
                "question": f"Highest temperature in {city_phrase} on {when}? 80-81°F",
                "outcomePrices": ["0.40", "0.60"],
                "closed": False,
                "volume": 100,
            }
        ],
    }


class CityMatchingTests(unittest.TestCase):
    def test_atlanta_does_not_map_to_los_angeles(self):
        key, name = _match_city("Atlanta")
        self.assertIsNone(key)
        self.assertIsNone(name)

    def test_philadelphia_and_las_vegas_do_not_match_la_alias(self):
        self.assertEqual(_match_city("Philadelphia"), (None, None))
        self.assertEqual(_match_city("Las Vegas"), (None, None))
        self.assertEqual(_match_city("Dallas"), (None, None))

    def test_configured_cities_still_match(self):
        self.assertEqual(_match_city("Los Angeles")[0], "los_angeles")
        self.assertEqual(_match_city("LA")[0], "los_angeles")
        self.assertEqual(_match_city("la")[0], "los_angeles")
        self.assertEqual(_match_city("New York")[0], "nyc")
        self.assertEqual(_match_city("New York City")[0], "nyc")
        self.assertEqual(_match_city("Chicago")[0], "chicago")
        self.assertEqual(_match_city("Miami")[0], "miami")
        self.assertEqual(_match_city("Denver")[0], "denver")

    def test_unlisted_city_is_not_silently_remapped(self):
        markets = _parse_weather_event(_event("Atlanta"), city_keys=None)
        self.assertEqual(markets, [])

    def test_atlanta_event_title_does_not_produce_los_angeles_market(self):
        markets = _parse_weather_event(
            _event("Atlanta"),
            city_keys=["los_angeles", "nyc", "chicago", "miami", "denver"],
        )
        self.assertEqual(markets, [])

    def test_los_angeles_event_still_parses(self):
        markets = _parse_weather_event(_event("Los Angeles"), city_keys=None)
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].city_key, "los_angeles")

    def test_standalone_la_still_parses(self):
        markets = _parse_weather_event(_event("LA"), city_keys=None)
        self.assertEqual(len(markets), 1)
        self.assertEqual(markets[0].city_key, "los_angeles")


if __name__ == "__main__":
    unittest.main()
