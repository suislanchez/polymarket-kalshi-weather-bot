"""Fail-closed execution-mode and Archives-runtime validation for the paper runtime."""

import os
from collections.abc import Callable, Iterable
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

    if isinstance(runtime_paths, (str, bytes)) or not isinstance(
        runtime_paths, Iterable
    ):
        raise ArchivesRuntimeError("Archives runtime paths must be a sequence.")
    for candidate in runtime_paths:
        resolved = _absolute_path(candidate)
        if not _is_within(resolved, root):
            raise ArchivesRuntimeError(
                "Mutable runtime state must live under the Archives root; "
                "internal-disk fallbacks are not permitted."
            )

    if isinstance(required_directories, (str, bytes)) or not isinstance(
        required_directories, Iterable
    ):
        raise ArchivesRuntimeError("Archives required directories must be a sequence.")
    for candidate in required_directories:
        resolved = _absolute_path(candidate)
        if not _is_within(resolved, root):
            raise ArchivesRuntimeError(
                "Required runtime directories must live under the Archives root."
            )
        if not resolved.is_dir():
            raise ArchivesRuntimeError(
                "A required Archives runtime directory is missing or is not a directory."
            )
