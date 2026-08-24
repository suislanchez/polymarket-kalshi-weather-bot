"""Fail-closed tests for the unified runtime execution mode."""

import pytest

from backend.trading.execution_mode import ExecutionModeError, require_paper_mode


def test_require_paper_mode_accepts_paper_mode():
    require_paper_mode("paper")


def test_require_paper_mode_rejects_live_mode():
    with pytest.raises(ExecutionModeError, match="paper-only"):
        require_paper_mode("live")


def test_require_paper_mode_rejects_live_enablement_even_in_paper_mode():
    with pytest.raises(ExecutionModeError, match="paper-only"):
        require_paper_mode("paper", live_enabled=True)


@pytest.mark.parametrize("mode", [None, "", "   ", 0, False])
def test_require_paper_mode_rejects_blank_or_non_string_modes(mode):
    with pytest.raises(ExecutionModeError, match="paper-only"):
        require_paper_mode(mode)
