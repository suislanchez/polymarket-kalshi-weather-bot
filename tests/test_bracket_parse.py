"""Polymarket ladder bracket labels parse into integer thresholds."""
import unittest

from backend.data.weather_markets import _parse_bracket


class BracketParseTests(unittest.TestCase):
    def test_range_80_81_f(self):
        parsed = _parse_bracket("80-81°F")
        self.assertIsNotNone(parsed)
        self.assertEqual(parsed["direction"], "between")
        self.assertEqual(parsed["threshold_f"], 80.0)
        self.assertEqual(parsed["threshold_high_f"], 81.0)

    def test_range_without_degree_symbol(self):
        parsed = _parse_bracket("80-81F")
        self.assertEqual(parsed["direction"], "between")
        self.assertEqual(parsed["threshold_f"], 80.0)
        self.assertEqual(parsed["threshold_high_f"], 81.0)

    def test_or_below(self):
        parsed = _parse_bracket("79°F or below")
        self.assertEqual(parsed["direction"], "below")
        self.assertEqual(parsed["threshold_f"], 79.0)
        self.assertIsNone(parsed["threshold_high_f"])

    def test_or_higher(self):
        parsed = _parse_bracket("98°F or higher")
        self.assertEqual(parsed["direction"], "above")
        self.assertEqual(parsed["threshold_f"], 98.0)
        self.assertIsNone(parsed["threshold_high_f"])

    def test_unparseable_label_returns_none(self):
        self.assertIsNone(_parse_bracket("something else"))


if __name__ == "__main__":
    unittest.main()
