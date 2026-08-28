"""Fail-closed Archives runtime binding for all mutable state."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.config import Settings
from backend.trading.execution_mode import (
    ArchivesRuntimeError,
    require_archives_runtime,
)

ARCHIVES_ROOT = "/Volumes/Archives"
TRADING_ROOT = f"{ARCHIVES_ROOT}/Hermes-Offload/2026-08-23/trading-system"


@pytest.fixture
def archives(tmp_path: Path) -> Path:
    root = tmp_path / "Archives"
    (root / "data" / "research").mkdir(parents=True)
    (root / "data" / "ledgers").mkdir(parents=True)
    return root


def mounted(_path: object) -> bool:
    return True


def test_available_archives_root_with_contained_paths_is_accepted(archives: Path):
    require_archives_runtime(
        str(archives),
        [str(archives / "data" / "ledgers" / "tradingbot.db")],
        required_directories=[str(archives / "data" / "research")],
        mount_check=mounted,
    )


@pytest.mark.parametrize(
    "root",
    ["", "   ", "relative/archives", None, 17, b"/Volumes/Archives"],
)
def test_unusable_archives_root_is_rejected(root: object):
    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(root, [], mount_check=mounted)


def test_unmounted_archives_root_is_rejected(archives: Path):
    with pytest.raises(ArchivesRuntimeError) as caught:
        require_archives_runtime(str(archives), [], mount_check=lambda _p: False)
    assert "archives" in str(caught.value).lower()


def test_mount_check_failure_fails_closed(archives: Path):
    def exploding(_path: object) -> bool:
        raise OSError("mount probe failed")

    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(str(archives), [], mount_check=exploding)


def test_missing_archives_root_directory_is_rejected(tmp_path: Path):
    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(
            str(tmp_path / "absent"), [], mount_check=mounted
        )


@pytest.mark.parametrize(
    "runtime_path",
    [
        "tradingbot.db",
        "./tradingbot.db",
        "/Users/kayvonai/.hermes/research/prediction-market-edge-snapshots.sqlite",
        "/tmp/tradingbot.db",
        "",
        None,
    ],
)
def test_runtime_paths_outside_archives_are_rejected(
    archives: Path, runtime_path: object
):
    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(
            str(archives), [runtime_path], mount_check=mounted
        )


def test_sibling_directory_sharing_a_prefix_is_not_inside_archives(tmp_path: Path):
    root = tmp_path / "Archives"
    root.mkdir()
    sibling = tmp_path / "ArchivesEvil"
    sibling.mkdir()
    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(
            str(root), [str(sibling / "tradingbot.db")], mount_check=mounted
        )


def test_parent_traversal_escaping_archives_is_rejected(archives: Path):
    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(
            str(archives),
            [str(archives / ".." / "escaped.db")],
            mount_check=mounted,
        )


def test_missing_required_runtime_directory_is_rejected(archives: Path):
    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(
            str(archives),
            [],
            required_directories=[str(archives / "data" / "absent")],
            mount_check=mounted,
        )


def test_required_directory_that_is_a_file_is_rejected(archives: Path):
    impostor = archives / "data" / "not-a-directory"
    impostor.write_text("x")
    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(
            str(archives),
            [],
            required_directories=[str(impostor)],
            mount_check=mounted,
        )


def test_error_message_never_leaks_path_contents(archives: Path):
    with pytest.raises(ArchivesRuntimeError) as caught:
        require_archives_runtime(
            str(archives), ["/Users/kayvonai/.hermes/secret-token"], mount_check=mounted
        )
    assert "secret-token" not in str(caught.value)


def test_canonical_archives_settings_defaults():
    settings = Settings(_env_file=None)
    assert settings.TRADING_ARCHIVES_ROOT == ARCHIVES_ROOT
    assert settings.DATABASE_URL == (
        f"sqlite:///{TRADING_ROOT}/data/ledgers/tradingbot.db"
    )
    assert settings.RESEARCH_DATABASE_PATH == (
        f"{TRADING_ROOT}/data/research/prediction-market-edge-snapshots.sqlite"
    )
    assert settings.RESEARCH_SNAPSHOT_ROOT == (
        f"{TRADING_ROOT}/data/research/snapshots"
    )


@pytest.mark.parametrize(
    "setting_name",
    [
        "TRADING_SYSTEM_ROOT",
        "TRADING_DATA_ROOT",
        "TRADING_ARTIFACTS_ROOT",
        "TRADING_LOG_ROOT",
        "RESEARCH_DATABASE_PATH",
        "RESEARCH_SNAPSHOT_ROOT",
    ],
)
def test_no_mutable_runtime_default_is_relative_or_off_archives(setting_name: str):
    settings = Settings(_env_file=None)
    value = getattr(settings, setting_name)
    assert Path(value).is_absolute()
    assert Path(value) == Path(value).resolve()
    assert str(value).startswith(f"{ARCHIVES_ROOT}/")


def test_database_url_default_points_inside_archives():
    settings = Settings(_env_file=None)
    path = settings.DATABASE_URL.removeprefix("sqlite:///")
    assert Path(path).is_absolute()
    assert path.startswith(f"{ARCHIVES_ROOT}/")


def test_root_filesystem_as_archives_root_is_rejected():
    """'/' is a mount point and contains everything, which would void containment."""
    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime("/", ["/etc/passwd"], mount_check=mounted)


def test_exhausted_iterator_of_runtime_paths_does_not_pass_vacuously(archives: Path):
    outside = iter(["/Users/kayvonai/.hermes/research.sqlite"])
    list(outside)  # exhaust it before the guard sees it
    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(str(archives), outside, mount_check=mounted)


def test_symlink_inside_archives_targeting_internal_disk_is_rejected(
    archives: Path, tmp_path: Path
):
    internal = tmp_path / "internal"
    internal.mkdir()
    escape = archives / "data" / "escape"
    escape.symlink_to(internal, target_is_directory=True)

    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(
            str(archives), [str(escape / "tradingbot.db")], mount_check=mounted
        )
    with pytest.raises(ArchivesRuntimeError):
        require_archives_runtime(
            str(archives), [], required_directories=[str(escape)], mount_check=mounted
        )


def test_symlink_staying_inside_archives_is_still_accepted(archives: Path):
    inner = archives / "data" / "real"
    inner.mkdir()
    link = archives / "data" / "link"
    link.symlink_to(inner, target_is_directory=True)
    require_archives_runtime(
        str(archives),
        [str(link / "tradingbot.db")],
        required_directories=[str(link)],
        mount_check=mounted,
    )


def test_env_example_documents_the_archives_settings():
    root = Path(__file__).resolve().parent.parent
    text = (root / ".env.example").read_text()
    for name in (
        "TRADING_ARCHIVES_ROOT",
        "RESEARCH_DATABASE_PATH",
        "RESEARCH_SNAPSHOT_ROOT",
    ):
        assert name in text
