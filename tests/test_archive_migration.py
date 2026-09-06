"""Move runtime state to Archives without ever risking the source.

The script this tests is the one operation in the plan that touches real user
data outside a Git clone: a live ledger, a research database, an .env holding
broker credentials, and a private key. Every assertion here is about a way that
could go wrong quietly -- a truncated copy that reports success, a secret
written world-readable, a key value echoed into a manifest, a rerun that
duplicates or clobbers, a "migration" that deleted the source first.

The tracked-source exclusion matters for a subtler reason: the Git clone in
Task 1 already owns those files. Copying them again would create a second,
diverging copy that nothing updates.
"""

import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from backend.config import Settings

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "migrate_runtime_to_archives.py"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_migration_module():
    """Import the script as a module.

    It must be registered in sys.modules before exec_module: the script uses
    `from __future__ import annotations`, so @dataclass resolves its string
    annotations by looking the module up there, and fails with a bare
    AttributeError if it is absent.
    """
    import importlib.util
    import sys

    spec = importlib.util.spec_from_file_location("migrate_runtime_to_archives", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def make_sqlite(path: Path, rows: int = 3) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path)
    connection.execute("CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT)")
    connection.executemany(
        "INSERT INTO t (v) VALUES (?)", [(f"row-{index}",) for index in range(rows)]
    )
    connection.commit()
    connection.close()


SECRET_VALUE = "SUPERSECRETAPIKEYVALUE_DO_NOT_LEAK"


@pytest.fixture
def source(tmp_path: Path) -> Path:
    """A source tree shaped like the real legacy checkout."""
    root = tmp_path / "legacy-checkout"
    (root / "backend").mkdir(parents=True)
    (root / "backend" / "app.py").write_text("# tracked source\n")
    (root / "README.md").write_text("# tracked\n")

    # Untracked runtime state.
    make_sqlite(root / "tradingbot.db", rows=5)
    (root / ".env").write_text(f"ALPACA_API_KEY={SECRET_VALUE}\n")
    (root / ".secrets").mkdir()
    (root / ".secrets" / "kalshi_private_key.pem").write_text(
        f"-----BEGIN PRIVATE KEY-----\n{SECRET_VALUE}\n-----END PRIVATE KEY-----\n"
    )
    (root / ".firecrawl" / "cache").mkdir(parents=True)
    (root / ".firecrawl" / "cache" / "page.json").write_text('{"scraped": true}')
    (root / "reports").mkdir()
    (root / "reports" / "audit.md").write_text("# generated report\n")

    # Recreatable: must be classified, never copied.
    (root / "node_modules" / "left-pad").mkdir(parents=True)
    (root / "node_modules" / "left-pad" / "index.js").write_text("module.exports=1")
    (root / ".venv" / "bin").mkdir(parents=True)
    (root / ".venv" / "bin" / "python").write_text("#!/bin/sh\n")
    (root / "frontend" / "dist").mkdir(parents=True)
    (root / "frontend" / "dist" / "index.js").write_text("built")
    (root / "__pycache__").mkdir()
    (root / "__pycache__" / "app.cpython-311.pyc").write_bytes(b"\x00\x01")

    subprocess.run(["git", "init", "-q"], cwd=root, check=True)
    subprocess.run(["git", "add", "backend/app.py", "README.md"], cwd=root, check=True)
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "tracked"],
        cwd=root,
        check=True,
    )
    return root


@pytest.fixture
def research(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "hermes-research" / "prediction-market-edge-snapshots.sqlite"
    make_sqlite(database, rows=7)
    snapshots = tmp_path / "hermes-research"
    (snapshots / "snap-1.json").write_text('{"a": 1}')
    return database, snapshots


def run_migration(source: Path, research, archive_root: Path, mode: str):
    database, snapshots = research
    return subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "--source", str(source),
            "--research-db-source", str(database),
            "--research-snapshot-source", str(snapshots),
            "--archive-root", str(archive_root),
            mode,
        ],
        capture_output=True,
        text=True,
        cwd=str(SCRIPT.resolve().parents[1]),
    )


@pytest.fixture
def archive_root(tmp_path: Path) -> Path:
    return tmp_path / "archive-root"


def manifest_of(archive_root: Path) -> dict:
    return json.loads((archive_root / "backups" / "migration-manifest.json").read_text())


# --- dry run ---------------------------------------------------------------


def test_dry_run_writes_nothing_at_all(source, research, archive_root):
    result = run_migration(source, research, archive_root, "--dry-run")

    assert result.returncode == 0, result.stderr
    assert not archive_root.exists(), "dry run created the destination tree"


def test_dry_run_still_reports_a_categorized_plan(source, research, archive_root):
    result = run_migration(source, research, archive_root, "--dry-run")

    for category in ("repo", "recreate", "secret", "firecrawl", "database"):
        assert category in result.stdout, f"{category} missing from the dry-run plan"


def test_dry_run_never_prints_a_secret_value(source, research, archive_root):
    result = run_migration(source, research, archive_root, "--dry-run")

    assert SECRET_VALUE not in result.stdout
    assert SECRET_VALUE not in result.stderr


# --- inventory and classification ------------------------------------------


def test_manifest_inventories_path_size_hash_and_category(source, research, archive_root):
    run_migration(source, research, archive_root, "--apply")

    entries = manifest_of(archive_root)["entries"]
    by_path = {entry["relative_path"]: entry for entry in entries}
    ledger = by_path["tradingbot.db"]
    assert ledger["category"] == "database"
    assert ledger["size"] == (source / "tradingbot.db").stat().st_size
    assert ledger["sha256"] == sha256(source / "tradingbot.db")


def test_tracked_source_is_excluded_because_the_clone_owns_it(source, research, archive_root):
    run_migration(source, research, archive_root, "--apply")

    by_path = {e["relative_path"]: e for e in manifest_of(archive_root)["entries"]}
    assert by_path["backend/app.py"]["category"] == "repo"
    assert by_path["backend/app.py"].get("destination") is None
    assert not (archive_root / "data" / "legacy" / "backend" / "app.py").exists()


@pytest.mark.parametrize(
    "relative",
    [
        "node_modules/left-pad/index.js",
        ".venv/bin/python",
        "frontend/dist/index.js",
        "__pycache__/app.cpython-311.pyc",
    ],
)
def test_recreatable_trees_are_classified_and_never_copied(
    source, research, archive_root, relative
):
    run_migration(source, research, archive_root, "--apply")

    by_path = {e["relative_path"]: e for e in manifest_of(archive_root)["entries"]}
    assert by_path[relative]["category"] == "recreate"
    assert by_path[relative].get("destination") is None
    for candidate in archive_root.rglob(Path(relative).name):
        pytest.fail(f"recreatable file was copied to {candidate}")


# --- databases -------------------------------------------------------------


def test_databases_copy_byte_for_byte_and_pass_integrity_check(
    source, research, archive_root
):
    run_migration(source, research, archive_root, "--apply")

    ledger = archive_root / "data" / "ledgers" / "tradingbot.db"
    assert sha256(ledger) == sha256(source / "tradingbot.db")
    connection = sqlite3.connect(ledger)
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    connection.close()


def test_the_three_runtime_destinations_match_the_settings_defaults(
    source, research, archive_root
):
    """A migration that lands somewhere the runtime does not read is a no-op.

    These are the paths Task 15A configured; the assertion is that the script
    and the settings agree on all three rather than drifting apart.
    """
    run_migration(source, research, archive_root, "--apply")
    settings = Settings()

    def tail(path: str, depth: int) -> tuple[str, ...]:
        return tuple(Path(path).parts[-depth:])

    ledger_url = settings.DATABASE_URL.replace("sqlite:///", "")
    assert tail(ledger_url, 3) == ("data", "ledgers", "tradingbot.db")
    assert (archive_root / "data" / "ledgers" / "tradingbot.db").exists()

    assert tail(settings.RESEARCH_DATABASE_PATH, 3) == (
        "data", "research", "prediction-market-edge-snapshots.sqlite",
    )
    assert (
        archive_root / "data" / "research" / "prediction-market-edge-snapshots.sqlite"
    ).exists()

    assert tail(settings.RESEARCH_SNAPSHOT_ROOT, 3) == ("data", "research", "snapshots")
    assert (archive_root / "data" / "research" / "snapshots").is_dir()


# --- secrets ---------------------------------------------------------------


@pytest.mark.parametrize("name", [".env", "kalshi_private_key.pem"])
def test_secrets_go_to_the_secret_backup_with_owner_only_permissions(
    source, research, archive_root, name
):
    run_migration(source, research, archive_root, "--apply")

    matches = list((archive_root / "backups" / "secrets").rglob(name))
    assert matches, f"{name} was not backed up"
    mode = stat.S_IMODE(matches[0].stat().st_mode)
    assert mode == 0o600, f"{name} has mode {oct(mode)}, not 0600"


def test_secrets_are_not_copied_into_the_repo_or_data_tree(source, research, archive_root):
    run_migration(source, research, archive_root, "--apply")

    for tree in ("data", "artifacts", "logs"):
        for found in (archive_root / tree).rglob("*") if (archive_root / tree).exists() else []:
            assert found.name != ".env", f"secret leaked into {found}"


def test_no_secret_value_reaches_the_manifest_or_the_output(source, research, archive_root):
    result = run_migration(source, research, archive_root, "--apply")

    raw_manifest = (archive_root / "backups" / "migration-manifest.json").read_text()
    assert SECRET_VALUE not in raw_manifest
    assert SECRET_VALUE not in result.stdout
    assert SECRET_VALUE not in result.stderr


# --- firecrawl -------------------------------------------------------------


def test_firecrawl_goes_to_its_own_backup_and_never_the_repo(source, research, archive_root):
    run_migration(source, research, archive_root, "--apply")

    assert (archive_root / "backups" / "firecrawl" / "cache" / "page.json").exists()
    by_path = {e["relative_path"]: e for e in manifest_of(archive_root)["entries"]}
    assert by_path[".firecrawl/cache/page.json"]["category"] == "firecrawl"
    assert not (archive_root / "data" / "legacy" / ".firecrawl").exists()


# --- safety ----------------------------------------------------------------


def test_the_source_is_never_modified(source, research, archive_root):
    before = {
        path.relative_to(source): sha256(path)
        for path in source.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }

    run_migration(source, research, archive_root, "--apply")

    after = {
        path.relative_to(source): sha256(path)
        for path in source.rglob("*")
        if path.is_file() and ".git" not in path.parts
    }
    assert before == after


def test_a_destination_mismatch_fails_without_deleting_anything(
    source, research, archive_root
):
    """A corrupted copy must stop the run, not be reported as migrated."""
    run_migration(source, research, archive_root, "--apply")
    ledger = archive_root / "data" / "ledgers" / "tradingbot.db"
    ledger.write_bytes(b"corrupted, and not the size or hash of the source")

    result = run_migration(source, research, archive_root, "--apply")

    assert result.returncode != 0, "a mismatched destination was accepted"
    assert (source / "tradingbot.db").exists(), "the source was deleted"
    assert ledger.exists(), "the destination was deleted"


def test_rerunning_is_idempotent(source, research, archive_root):
    first = run_migration(source, research, archive_root, "--apply")
    assert first.returncode == 0, first.stderr
    ledger = archive_root / "data" / "ledgers" / "tradingbot.db"
    first_hash = sha256(ledger)

    second = run_migration(source, research, archive_root, "--apply")

    assert second.returncode == 0, second.stderr
    assert sha256(ledger) == first_hash
    paths = [e["relative_path"] for e in manifest_of(archive_root)["entries"]]
    assert len(paths) == len(set(paths)), "the manifest gained duplicate entries"


def test_apply_and_dry_run_are_mutually_exclusive(source, research, archive_root):
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--source", str(source),
            "--research-db-source", str(research[0]),
            "--research-snapshot-source", str(research[1]),
            "--archive-root", str(archive_root),
            "--dry-run", "--apply",
        ],
        capture_output=True, text=True,
    )
    assert result.returncode != 0


def test_a_mode_must_be_chosen_explicitly(source, research, archive_root):
    """Defaulting to either mode is wrong: silent no-op or unrequested writes."""
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--source", str(source),
            "--research-db-source", str(research[0]),
            "--research-snapshot-source", str(research[1]),
            "--archive-root", str(archive_root),
        ],
        capture_output=True, text=True,
    )
    assert result.returncode != 0
    assert not archive_root.exists()


# --- snapshot scoping ------------------------------------------------------
#
# The snapshot directory is shared with other projects. Migrating all of it
# would drag unrelated working sets into the trading archive, so the real run
# names the prefixes it wants. Unfiltered remains the default.


@pytest.fixture
def mixed_snapshots(tmp_path: Path) -> tuple[Path, Path]:
    database = tmp_path / "mixed-research" / "prediction-market-edge-snapshots.sqlite"
    make_sqlite(database, rows=2)
    root = tmp_path / "mixed-research"
    (root / "prediction-market-edge-log.md").write_text("relevant\n")
    (root / "unrelated-project").mkdir()
    (root / "unrelated-project" / "crm.json").write_text('{"big": true}')
    return database, root


def test_snapshots_are_migrated_whole_when_no_prefix_is_given(
    source, mixed_snapshots, archive_root
):
    run_migration(source, mixed_snapshots, archive_root, "--apply")

    snapshots = archive_root / "data" / "research" / "snapshots"
    assert (snapshots / "prediction-market-edge-log.md").exists()
    assert (snapshots / "unrelated-project" / "crm.json").exists()


def test_a_prefix_restricts_snapshots_without_touching_the_database(
    source, mixed_snapshots, archive_root
):
    database, snapshot_root = mixed_snapshots
    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--source", str(source),
            "--research-db-source", str(database),
            "--research-snapshot-source", str(snapshot_root),
            "--archive-root", str(archive_root),
            "--snapshot-name-prefix", "prediction-market-edge",
            "--apply",
        ],
        capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    snapshots = archive_root / "data" / "research" / "snapshots"
    assert (snapshots / "prediction-market-edge-log.md").exists()
    assert not (snapshots / "unrelated-project").exists(), "an excluded tree was copied"
    # The research database is routed independently and must still arrive.
    assert (
        archive_root / "data" / "research" / "prediction-market-edge-snapshots.sqlite"
    ).exists()


# --- a live destination must never be overwritten by its own predecessor ----


def test_preserve_as_legacy_diverts_instead_of_clobbering_a_live_destination(
    source, research, archive_root
):
    """The archive ledger is live and ahead of the legacy copy.

    Overwriting it with the older source would destroy the history the
    migration exists to protect, so the source is preserved under data/legacy
    and the manifest records where it was meant to go.
    """
    run_migration(source, research, archive_root, "--apply")
    ledger = archive_root / "data" / "ledgers" / "tradingbot.db"
    ledger.unlink()
    make_sqlite(ledger, rows=99)  # the destination moves on independently
    live_hash = sha256(ledger)

    result = subprocess.run(
        [
            sys.executable, str(SCRIPT),
            "--source", str(source),
            "--research-db-source", str(research[0]),
            "--research-snapshot-source", str(research[1]),
            "--archive-root", str(archive_root),
            "--on-existing-mismatch", "preserve-as-legacy",
            "--apply",
        ],
        capture_output=True, text=True,
    )

    assert result.returncode == 0, result.stderr
    assert sha256(ledger) == live_hash, "the live destination was overwritten"
    preserved = archive_root / "data" / "legacy" / "tradingbot.db"
    assert preserved.exists(), "the source copy was not preserved anywhere"
    assert sha256(preserved) == sha256(source / "tradingbot.db")

    entry = next(
        e for e in manifest_of(archive_root)["entries"]
        if e["relative_path"] == "tradingbot.db"
    )
    assert entry["diverted_from"].endswith("data/ledgers/tradingbot.db")


def test_fail_remains_the_default_for_an_existing_mismatch(source, research, archive_root):
    run_migration(source, research, archive_root, "--apply")
    (archive_root / "data" / "ledgers" / "tradingbot.db").write_bytes(b"corrupt")

    result = run_migration(source, research, archive_root, "--apply")

    assert result.returncode != 0


# --- classification of key material ----------------------------------------
#
# A secret routed to data/legacy instead of backups/secrets is filed in the
# wrong place and labelled "data" in the manifest. mkstemp creates at 0600 and
# os.replace preserves it, so the mode happens to survive -- but relying on
# that would make the explicit chmod the only stated guarantee and the real one
# an accident.


@pytest.mark.parametrize(
    "relative",
    [
        "id_rsa",                    # bare private key, no suffix
        "id_ed25519",
        ".ssh/id_ecdsa",
        "config/secrets.yaml",       # named secret, not under a secrets/ dir
        "keys/alpaca.txt",           # key material by directory
        "certs/chain.txt",
        ".netrc",
        "app/service_credentials.ini",
    ],
)
def test_key_material_is_classified_as_secret(relative):
    mig = load_migration_module()

    assert mig.classify(Path(relative), set()) == "secret", (
        f"{relative} would be copied outside backups/secrets"
    )


@pytest.mark.parametrize(
    "relative", ["backend/config.py", "tradingbot.db", "README.md", "reports/audit.md"]
)
def test_ordinary_files_are_not_swept_up_as_secrets(relative):
    """Over-classification is fail-safe but must not swallow the whole tree."""
    mig = load_migration_module()

    assert mig.classify(Path(relative), set()) != "secret"
