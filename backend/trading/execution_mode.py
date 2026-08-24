"""Fail-closed execution-mode validation for the paper-only runtime."""


class ExecutionModeError(RuntimeError):
    """Raised when runtime settings could permit non-paper execution."""


def require_paper_mode(mode: object, live_enabled: bool = False) -> None:
    """Reject any configuration other than explicitly disabled live paper mode."""
    normalized_mode = mode.strip().lower() if isinstance(mode, str) else ""
    if normalized_mode != "paper" or live_enabled is not False:
        raise ExecutionModeError(
            "This runtime is paper-only: EXECUTION_MODE must be 'paper' and "
            "LIVE_TRADING_ENABLED must be false."
        )
