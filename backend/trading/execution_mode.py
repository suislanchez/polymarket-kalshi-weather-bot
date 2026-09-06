"""Fail-closed execution-mode and Archives-runtime validation for the paper runtime."""

import os
from collections.abc import Callable, Sequence
from pathlib import Path


class ExecutionModeError(RuntimeError):
    """Raised when runtime settings could permit non-paper execution."""


class ArchivesRuntimeError(RuntimeError):
    """Raised when mutable runtime state is not bound to available Archives storage."""


def require_paper_mode(mode: object, live_enabled: bool = False) -> None:
    """Reject any configuration other than explicitly disabled live paper mode."""
    normalized_mode = mode.strip().lower() if isinstance(mode, str) else ""
    if normalized_mode != "paper" or live_enabled is not False:
        raise ExecutionModeError(
            "This runtime is paper-only: EXECUTION_MODE must be 'paper' and "
            "LIVE_TRADING_ENABLED must be false."
        )


def _absolute_path(value: object) -> Path:
    """Return a normalized absolute path, rejecting anything else."""
    if type(value) is not str or not value.strip():
        raise ArchivesRuntimeError(
            "Archives runtime paths must be non-empty absolute strings."
        )
    candidate = Path(value)
    if not candidate.is_absolute():
        raise ArchivesRuntimeError(
            "Archives runtime paths must be absolute, never relative."
        )
    # Normalize lexically so parent traversal cannot escape the root, and so a
    # missing path is still comparable. resolve() would follow symlinks into
    # internal storage, which is exactly what this guard exists to reject.
    return Path(os.path.normpath(str(candidate)))


def _is_within(path: Path, root: Path) -> bool:
    """Component-aware containment: /Volumes/ArchivesEvil is not under /Volumes/Archives."""
    if path == root:
        return True
    return root in path.parents


def _resolved(path: Path) -> Path:
    """Resolve symlinks without requiring the path to exist yet."""
    try:
        return Path(os.path.realpath(str(path)))
    except OSError:
        raise ArchivesRuntimeError(
            "An Archives runtime path could not be resolved; refusing to start."
        ) from None


def _require_contained(candidate: object, root: Path, resolved_root: Path, message: str) -> Path:
    """Reject a path unless it is inside the root both lexically and after symlinks.

    The lexical check stops ".." escapes and sibling-prefix lookalikes. The resolved
    check stops a symlink planted inside Archives from redirecting mutable state onto
    internal storage. Both must hold.
    """

    path = _absolute_path(candidate)
    if not _is_within(path, root):
        raise ArchivesRuntimeError(message)
    if not _is_within(_resolved(path), resolved_root):
        raise ArchivesRuntimeError(message)
    return path


def require_archives_runtime(
    archives_root: object,
    runtime_paths: object = (),
    *,
    required_directories: object = (),
    mount_check: object = None,
) -> None:
    """Reject any runtime whose mutable state is not on an available Archives root.

    Fails closed on an unmounted or missing Archives root, on any runtime path that
    is relative or resolves outside that root, and on any required runtime directory
    that is absent or is not a directory. Messages name the setting boundary only and
    never echo the offending path, which may carry operator-specific content.
    """

    root = _absolute_path(archives_root)
    if root == Path(root.anchor):
        raise ArchivesRuntimeError(
            "The filesystem root cannot be the Archives root; containment would be void."
        )

    probe: Callable[[str], bool] = (
        os.path.ismount if mount_check is None else mount_check  # type: ignore[assignment]
    )
    if not callable(probe):
        raise ArchivesRuntimeError("Archives mount check is not callable.")
    try:
        mounted = probe(str(root))
    except Exception:
        raise ArchivesRuntimeError(
            "Archives root availability could not be determined; refusing to start."
        ) from None
    if mounted is not True:
        raise ArchivesRuntimeError(
            "Archives root is not an available mount point; refusing to start."
        )

    if not root.is_dir():
        raise ArchivesRuntimeError(
            "Archives root does not exist or is not a directory."
        )
    resolved_root = _resolved(root)

    # A concrete sequence is required, never a one-shot iterator: an already-consumed
    # generator would otherwise be indistinguishable from a legitimately empty list and
    # would pass vacuously.
    if isinstance(runtime_paths, (str, bytes)) or not isinstance(
        runtime_paths, Sequence
    ):
        raise ArchivesRuntimeError("Archives runtime paths must be a concrete sequence.")
    for candidate in runtime_paths:
        _require_contained(
            candidate,
            root,
            resolved_root,
            "Mutable runtime state must live under the Archives root; "
            "internal-disk fallbacks are not permitted.",
        )

    if isinstance(required_directories, (str, bytes)) or not isinstance(
        required_directories, Sequence
    ):
        raise ArchivesRuntimeError(
            "Archives required directories must be a concrete sequence."
        )
    for candidate in required_directories:
        directory = _require_contained(
            candidate,
            root,
            resolved_root,
            "Required runtime directories must live under the Archives root.",
        )
        if not directory.is_dir():
            raise ArchivesRuntimeError(
                "A required Archives runtime directory is missing or is not a directory."
            )


def sqlite_path(database_url: object) -> str:
    """Return the on-disk path behind a sqlite URL, or the value unchanged."""
    if type(database_url) is not str:
        return ""
    for prefix in ("sqlite:////", "sqlite:///", "sqlite://"):
        if database_url.startswith(prefix):
            remainder = database_url[len(prefix):]
            return remainder if remainder.startswith("/") else f"/{remainder}"
    return database_url


def archives_runtime_paths(active_settings) -> list[str]:
    """Every mutable runtime location that must live on Archives."""
    return [
        sqlite_path(active_settings.DATABASE_URL),
        active_settings.RESEARCH_DATABASE_PATH,
        active_settings.RESEARCH_SNAPSHOT_ROOT,
        active_settings.TRADING_DATA_ROOT,
        active_settings.TRADING_ARTIFACTS_ROOT,
        active_settings.TRADING_LOG_ROOT,
    ]


def archives_required_directories(active_settings) -> list[str]:
    """Runtime directories that must already exist before startup proceeds."""
    return [
        str(Path(sqlite_path(active_settings.DATABASE_URL)).parent),
        str(Path(active_settings.RESEARCH_DATABASE_PATH).parent),
    ]


def archives_runtime_guard(active_settings) -> Callable[[], None]:
    """A zero-argument guard that re-checks Archives against live settings.

    API startup checks Archives once. A scheduler job runs for as long as the
    process does, so the execution service re-checks immediately before it
    writes -- but only if something hands it a guard, because it cannot build
    one without reaching back into configuration it deliberately does not import.
    This is that seam, and it reads the settings each call so a root that
    disappears mid-run is seen rather than remembered.
    """

    def guard() -> None:
        require_archives_runtime(
            active_settings.TRADING_ARCHIVES_ROOT,
            archives_runtime_paths(active_settings),
            required_directories=archives_required_directories(active_settings),
        )

    return guard


# The flags that halt trading. Both are gates, not just labels: a setting named
# GLOBAL_TRADING_KILL_SWITCH that an operator can set while orders keep
# submitting is worse than having no switch, because it is reached for exactly
# when someone needs trading to stop.
KILL_SWITCH_FLAGS = ("GLOBAL_TRADING_KILL_SWITCH", "LIVE_TRADING_ENABLED")

# The name reported to operators. It lists every flag that actually gates, so
# the reported source can never be a flag nothing reads.
KILL_SWITCH_SOURCE = " or ".join(KILL_SWITCH_FLAGS)


def kill_switch_engaged(active_settings: object) -> bool:
    """True when any configured kill-switch flag is set.

    Read from settings on every call rather than captured once, so a switch
    thrown while a long-lived scheduler job is running is observed by the next
    order rather than by the next process restart.
    """
    for flag in KILL_SWITCH_FLAGS:
        if bool(getattr(active_settings, flag, False)):
            return True
    return False
