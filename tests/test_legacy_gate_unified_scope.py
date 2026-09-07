"""Renaming the product scope must not silently re-enable the legacy lane.

_legacy_dashboard_sections_enabled() returned `flag or scope not in {weather…}`.
When ACTIVE_PRODUCT_SCOPE became "unified_paper", the scope fell outside the
weather set and every legacy BTC/RT dashboard section switched back ON -- the
panels, and ~17s per cold load of BTC market and signal fetching whose results
the unified scope then discards -- while DASHBOARD_LEGACY_SECTIONS_ENABLED=False
and BTC_LANE_ENABLED=False both said it was off.

The heuristic was "anything that isn't weather is legacy". The rule is now the
one config actually states: legacy is on when explicitly enabled, or when the
scope explicitly names the legacy product. A future scope name cannot flip it.
"""

import pytest

from backend.api import main as m
from backend.config import settings


@pytest.fixture
def scope(monkeypatch):
    def set_scope(value, explicit=False):
        monkeypatch.setattr(settings, "ACTIVE_PRODUCT_SCOPE", value)
        monkeypatch.setattr(settings, "DASHBOARD_LEGACY_SECTIONS_ENABLED", explicit)
    return set_scope


def test_unified_paper_scope_does_not_enable_legacy_sections(scope):
    scope("unified_paper")
    assert m._legacy_dashboard_sections_enabled() is False


@pytest.mark.parametrize("name", ["weather", "weather_only", "weather-only"])
def test_weather_scopes_stay_off(scope, name):
    scope(name)
    assert m._legacy_dashboard_sections_enabled() is False


def test_an_unknown_future_scope_defaults_to_off_not_on(scope):
    """The old heuristic would have turned this ON. That is the bug."""
    scope("some_scope_added_next_year")
    assert m._legacy_dashboard_sections_enabled() is False


@pytest.mark.parametrize("name", ["all", "legacy", "btc"])
def test_scopes_that_name_the_legacy_product_enable_it(scope, name):
    scope(name)
    assert m._legacy_dashboard_sections_enabled() is True


def test_the_explicit_flag_still_wins_under_unified_paper(scope):
    scope("unified_paper", explicit=True)
    assert m._legacy_dashboard_sections_enabled() is True


def test_the_dashboard_reports_legacy_off_under_the_shipped_default(scope):
    """The payload field the frontend keys its layout on."""
    from fastapi.testclient import TestClient

    scope(settings.__class__().ACTIVE_PRODUCT_SCOPE)  # the real default
    assert settings.ACTIVE_PRODUCT_SCOPE == "unified_paper"
    assert m._legacy_dashboard_sections_enabled() is False
