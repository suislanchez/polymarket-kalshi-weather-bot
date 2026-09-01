"""Integer-high YES probability and confidence must use the same definition."""
import unittest
from datetime import date

from backend.core.weather_signals import ensemble_yes_agreement, model_yes_probability
from backend.data.kalshi_markets import _parse_kalshi_ticker
from backend.data.weather import EnsembleForecast, settlement_temp_f
from backend.data.weather_markets import WeatherMarket


def _forecast(highs):
    return EnsembleForecast(
        city_key="miami",
        city_name="Miami",
        target_date=date(2026, 12, 15),
        member_highs=list(highs),
        member_lows=[70.0] * len(highs),
    )


def _market(direction, threshold_f, threshold_high_f=None, metric="high"):
    return WeatherMarket(
        slug="highest-temperature-in-miami-on-december-15",
        market_id="222",
        platform="polymarket",
        title="80-81°F",
        city_key="miami",
        city_name="Miami",
        target_date=date(2026, 12, 15),
        threshold_f=threshold_f,
        metric=metric,
        direction=direction,
        yes_price=0.40,
        no_price=0.60,
        threshold_high_f=threshold_high_f,
    )


class IntegerHighProbabilityTests(unittest.TestCase):
    def test_settlement_rounds_half_up(self):
        self.assertEqual(settlement_temp_f(79.4), 79)
        self.assertEqual(settlement_temp_f(79.5), 80)
        self.assertEqual(settlement_temp_f(81.4), 81)
        self.assertEqual(settlement_temp_f(81.5), 82)

    def test_between_80_81_uses_integer_high(self):
        # Float members that round to 80, 80, 81 — all YES for 80-81°F.
        # Strict float 80 <= h <= 81 would only count 80.2 (1/3).
        # P(h > 79) - P(h > 81) would count 79.6 and 80.2 but not 81.4 (2/3).
        forecast = _forecast([79.6, 80.2, 81.4])
        self.assertEqual(forecast.probability_high_between(80, 81), 1.0)

        market = _market("between", 80, 81)
        self.assertEqual(model_yes_probability(forecast, market), 1.0)
        self.assertEqual(ensemble_yes_agreement(forecast, market), 0.9)

    def test_probability_and_confidence_agree_on_between(self):
        forecast = _forecast([79.4, 79.6, 80.4, 81.4, 81.6])
        # integers: 79, 80, 80, 81, 82 → 3/5 in [80, 81]
        market = _market("between", 80, 81)
        prob = model_yes_probability(forecast, market)
        agree = ensemble_yes_agreement(forecast, market)
        self.assertAlmostEqual(prob, 0.6)
        self.assertAlmostEqual(agree, 0.6)

    def test_or_higher_includes_exact_integer_threshold(self):
        forecast = _forecast([81.4, 81.6, 82.0])
        # integers: 81, 82, 82 — 82°F or higher is 2/3
        # float h > 82 would count none (82.0 is not > 82)
        self.assertAlmostEqual(forecast.probability_high_above(82), 2 / 3)
        market = _market("above", 82)
        self.assertAlmostEqual(model_yes_probability(forecast, market), 2 / 3)
        self.assertAlmostEqual(ensemble_yes_agreement(forecast, market), 2 / 3)

    def test_or_below_includes_exact_integer_threshold(self):
        forecast = _forecast([78.6, 79.0, 79.4, 79.6])
        # integers: 79, 79, 79, 80 — 79°F or below is 3/4
        self.assertAlmostEqual(forecast.probability_high_below(79), 0.75)
        market = _market("below", 79)
        self.assertAlmostEqual(model_yes_probability(forecast, market), 0.75)

    def test_missing_threshold_high_f_returns_none_without_typeerror(self):
        forecast = _forecast([80.0, 81.0])
        market = _market("between", 80, None)
        try:
            result = model_yes_probability(forecast, market)
        except TypeError:
            self.fail("missing threshold_high_f must not raise TypeError")
        self.assertIsNone(result)
        self.assertIsNone(ensemble_yes_agreement(forecast, market))


class KalshiAboveBelowTests(unittest.TestCase):
    def test_ticker_b_is_above_and_t_is_below(self):
        above = _parse_kalshi_ticker("KXHIGHMIA-26DEC15-B45.5", "miami")
        below = _parse_kalshi_ticker("KXHIGHMIA-26DEC15-T45.5", "miami")
        self.assertEqual(above["direction"], "above")
        self.assertEqual(above["threshold_f"], 45.5)
        self.assertEqual(below["direction"], "below")
        self.assertEqual(below["threshold_f"], 45.5)

    def test_kalshi_b45_5_uses_integer_high_at_or_above_46(self):
        forecast = _forecast([45.4, 45.6, 46.2])
        # integers: 45, 46, 46 — B45.5 YES iff integer >= 46
        market = _market("above", 45.5)
        self.assertAlmostEqual(model_yes_probability(forecast, market), 2 / 3)
        self.assertAlmostEqual(forecast.probability_high_above(45.5), 2 / 3)

    def test_kalshi_t45_5_uses_integer_high_at_or_below_45(self):
        forecast = _forecast([45.4, 45.6, 46.2])
        market = _market("below", 45.5)
        self.assertAlmostEqual(model_yes_probability(forecast, market), 1 / 3)
        self.assertAlmostEqual(forecast.probability_high_below(45.5), 1 / 3)


if __name__ == "__main__":
    unittest.main()
