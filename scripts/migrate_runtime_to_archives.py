#!/usr/bin/env python3
"""Copy runtime state from the legacy checkout onto Archives, verifiably.

This is the one operation in the unified-trading plan that touches real user
data outside a Git clone: a live ledger, a research database, an ``.env`` with
broker credentials, and a private key. It is therefore written to be boring and
paranoid.

Three rules shape the whole file:

1. **The source is read-only.** Nothing here deletes, moves, or rewrites a
   source path. A migration that loses data to save disk is not a migration.
2. **A copy is not complete until it is verified.** Every file is written to a
   temporary name in the destination directory, fsynced, atomically renamed,
   and then re-hashed. A mismatch stops the run rather than being reported as
   success.
3. **Secrets are handled without being read into the report.** They are copied
   like anything else, but land under ``backups/secrets`` with mode 0600, and
   only their size and digest reach the manifest.

Tracked files are deliberately skipped: the Task 1 clone already owns them, and
copying them again would create a second copy that nothing keeps in sync.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, Optional

CHUNK = 1 << 16

# Directory names whose contents are rebuilt by a package manager or a build,
# never migrated. Copying a venv to another machine's path breaks it anyway.
RECREATE_DIRS = frozenset(
    {
        "node_modules", "venv", ".venv", "env", "__pycache__", ".pytest_cache",
        ".mypy_cache", ".ruff_cache", ".vite", "dist", "build", ".next",
        ".turbo", ".parcel-cache", "coverage", ".tox", "htmlcov", ".eggs",
    }
)
RECREATE_SUFFIXES = frozenset({".pyc", ".pyo"})

# Key material is recognised by name, by suffix, by directory, and by an
# unmistakable substring. All four are needed: an SSH private key is `id_rsa`
# with no suffix at all, and a file called `secrets.yaml` sitting in `config/`
# matches none of the first three.
SECRET_NAMES = frozenset(
    {
        ".env", ".envrc", ".netrc", ".pgpass", "credentials", "credentials.json",
        "id_rsa", "id_dsa", "id_ecdsa", "id_ed25519",
    }
)
SECRET_SUFFIXES = frozenset({".pem", ".key", ".p12", ".pfx", ".keystore", ".jks", ".asc"})
SECRET_DIRS = frozenset({".secrets", "secrets", "keys", "certs", ".ssh", ".gnupg", ".aws"})
# Matched against the file name only. Over-classification is fail-safe -- the
# file is copied to backups/secrets at 0600 instead of data/legacy -- but the
# terms are kept narrow so ordinary source is not swept in.
SECRET_NAME_FRAGMENTS = ("secret", "credential", "private_key", "privatekey")

DATABASE_SUFFIXES = frozenset({".db", ".sqlite", ".sqlite3"})

# Never walked: Git's own object store is the clone's business.
SKIP_DIRS = frozenset({".git"})


@dataclass
class Entry:
    relative_path: str
    size: int
    sha256: str
    category: str
    destination: Optional[str] = None
    # Set when the canonical destination was already occupied by different,
    # live bytes and this source was preserved elsewhere instead.
    diverted_from: Optional[str] = None


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(CHUNK), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def tracked_paths(source: Path) -> set[str]:
    """Files Git already owns. An error here means 'assume nothing is tracked'.

    Being wrong in that direction copies a file unnecessarily; being wrong the
    other way would silently skip real runtime state.
    """
    try:
        result = subprocess.run(
            ["git", "-C", str(source), "ls-files", "-z"],
            capture_output=True, check=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError):
        return set()
    return {name for name in result.stdout.decode().split("\0") if name}


def classify(relative: Path, tracked: set[str]) -> str:
    parts = relative.parts
    if any(part in RECREATE_DIRS for part in parts) or relative.suffix in RECREATE_SUFFIXES:
        return "recreate"
    if parts and parts[0] == ".firecrawl":
        return "firecrawl"
    lowered_name = relative.name.lower()
    if (
        lowered_name in SECRET_NAMES
        or lowered_name.startswith(".env.")
        or lowered_name.startswith("id_rsa")
        or relative.suffix.lower() in SECRET_SUFFIXES
        or any(part in SECRET_DIRS for part in parts)
        or any(fragment in lowered_name for fragment in SECRET_NAME_FRAGMENTS)
    ):
        return "secret"
    if str(relative) in tracked:
        return "repo"
    if relative.suffix in DATABASE_SUFFIXES:
        return "database"
    return "data"


def walk(source: Path) -> Iterable[Path]:
    for root, dirnames, filenames in os.walk(source):
        dirnames[:] = [name for name in dirnames if name not in SKIP_DIRS]
        for filename in filenames:
            yield Path(root) / filename


class MigrationError(RuntimeError):
    """Stops the run. Never raised after deleting anything."""


def destination_conflicts(source_file: Path, destination: Path) -> bool:
    """True when the destination exists and holds different bytes."""
    return destination.exists() and digest(destination) != digest(source_file)


def copy_verified(source_file: Path, destination: Path) -> None:
    """Copy, fsync, atomically rename, then prove the bytes match.

    An existing destination with the right digest is left alone, which is what
    makes a rerun idempotent. An existing destination with the WRONG digest is
    an error: it is either a corrupted copy or a different file that happens to
    share a name, and overwriting it silently would destroy whichever one
    mattered.
    """
    expected = digest(source_file)
    if destination.exists():
        if digest(destination) == expected:
            return
        raise MigrationError(
            f"destination already exists and does not match source: {destination}"
        )

    destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(dir=str(destination.parent), prefix=".migrate-")
    os.close(handle)
    temporary_path = Path(temporary)
    try:
        with source_file.open("rb") as reader, temporary_path.open("wb") as writer:
            shutil.copyfileobj(reader, writer, CHUNK)
            writer.flush()
            os.fsync(writer.fileno())
        if digest(temporary_path) != expected:
            raise MigrationError(f"copy did not match source while writing {destination}")
        os.replace(temporary_path, destination)
    except BaseException:
        temporary_path.unlink(missing_ok=True)
        raise

    if digest(destination) != expected:
        raise MigrationError(f"destination does not match source after rename: {destination}")


def check_sqlite(path: Path) -> None:
    connection = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        result = connection.execute("PRAGMA integrity_check").fetchone()
    finally:
        connection.close()
    if not result or result[0] != "ok":
        raise MigrationError(f"integrity check failed for {path}: {result}")


def destination_for(
    relative: Path, category: str, roots: dict[str, Path], source: Path
) -> Optional[Path]:
    if category in ("repo", "recreate"):
        return None
    if category == "secret":
        return roots["secrets"] / relative
    if category == "firecrawl":
        # Rooted at the .firecrawl directory itself, not beside it.
        return roots["firecrawl"] / Path(*relative.parts[1:])
    if category == "database" and relative == Path("tradingbot.db"):
        return roots["ledgers"] / "tradingbot.db"
    return roots["legacy"] / relative


def plan(source: Path, roots: dict[str, Path]) -> list[Entry]:
    tracked = tracked_paths(source)
    entries: list[Entry] = []
    for path in sorted(walk(source)):
        relative = path.relative_to(source)
        category = classify(relative, tracked)
        target = destination_for(relative, category, roots, source)
        entries.append(
            Entry(
                relative_path=str(relative),
                size=path.stat().st_size,
                sha256=digest(path),
                category=category,
                destination=(str(target) if target else None),
            )
        )
    return entries


def research_entries(
    database: Optional[Path],
    snapshots: Optional[Path],
    roots: dict[str, Path],
    name_prefixes: tuple[str, ...] = (),
) -> list[Entry]:
    """Inventory the research database and, optionally, a subset of snapshots.

    name_prefixes exists because the snapshot directory is shared. It was
    this system's alone when the plan was written and has since accumulated
    other projects' working sets, which have no business in the trading
    archive. An empty tuple keeps the original behaviour of taking everything,
    so the narrowing is always an explicit choice at the call site.
    """
    entries: list[Entry] = []
    if database and database.is_file():
        entries.append(
            Entry(
                relative_path=f"<research-db>/{database.name}",
                size=database.stat().st_size,
                sha256=digest(database),
                category="database",
                destination=str(
                    roots["research"] / "prediction-market-edge-snapshots.sqlite"
                ),
            )
        )
    if snapshots and snapshots.is_dir():
        for path in sorted(p for p in snapshots.rglob("*") if p.is_file()):
            if database and path.resolve() == database.resolve():
                continue
            relative = path.relative_to(snapshots)
            if name_prefixes and not str(relative).startswith(name_prefixes):
                continue
            # The snapshot tree goes through the same classifier as the source
            # tree. It is a shared directory, and hardcoding "data" here routed
            # any .env or key sitting in it into the live snapshot root instead
            # of backups/secrets -- bypassing the one rule that exists to stop
            # exactly that.
            category = classify(relative, set())
            if category in ("repo", "recreate"):
                # Nothing in the snapshot tree is Git-tracked or rebuildable
                # from this repository, so those verdicts do not apply here.
                category = "data"
            # Namespaced by origin. The source tree and the snapshot tree are
            # independent and both routinely contain a file called ".env";
            # flattening them into one secrets/ directory makes the second copy
            # collide with the first and abort the whole run.
            if category == "secret":
                destination = roots["secrets"] / "research-snapshots" / relative
            elif category == "firecrawl":
                destination = roots["firecrawl"] / "research-snapshots" / relative
            else:
                destination = roots["snapshots"] / relative
            entries.append(
                Entry(
                    relative_path=f"<research-snapshots>/{relative}",
                    size=path.stat().st_size,
                    sha256=digest(path),
                    category=category,
                    destination=str(destination),
                )
            )
    return entries


def source_path_for(entry: Entry, source: Path, database: Path, snapshots: Path) -> Path:
    if entry.relative_path.startswith("<research-db>/"):
        return database
    if entry.relative_path.startswith("<research-snapshots>/"):
        return snapshots / entry.relative_path.split("/", 1)[1]
    return source / entry.relative_path


def summarize(entries: list[Entry]) -> str:
    counts: dict[str, int] = {}
    total: dict[str, int] = {}
    for entry in entries:
        counts[entry.category] = counts.get(entry.category, 0) + 1
        total[entry.category] = total.get(entry.category, 0) + entry.size
    lines = ["category        files        bytes"]
    for category in sorted(counts):
        lines.append(f"{category:<14} {counts[category]:>5} {total[category]:>12}")
    return "\n".join(lines)


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--research-db-source", required=True, type=Path)
    parser.add_argument("--research-snapshot-source", required=True, type=Path)
    parser.add_argument("--archive-root", required=True, type=Path)
    parser.add_argument(
        "--snapshot-name-prefix",
        action="append",
        default=[],
        metavar="PREFIX",
        help=(
            "Only migrate snapshot entries whose path starts with PREFIX. "
            "Repeatable. Omit to migrate every snapshot."
        ),
    )
    parser.add_argument(
        "--on-existing-mismatch",
        choices=("fail", "preserve-as-legacy"),
        default="fail",
        help=(
            "What to do when a destination already holds different bytes. "
            "'fail' stops the run (the default, because the usual cause is a "
            "corrupt copy). 'preserve-as-legacy' diverts the source into "
            "data/legacy/ instead, for the case where the destination is a "
            "LIVE descendant that must not be overwritten."
        ),
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)

    source: Path = args.source
    if not source.is_dir():
        print(f"source is not a directory: {source}", file=sys.stderr)
        return 2

    archive_root: Path = args.archive_root
    roots = {
        "legacy": archive_root / "data" / "legacy",
        "ledgers": archive_root / "data" / "ledgers",
        "research": archive_root / "data" / "research",
        "snapshots": archive_root / "data" / "research" / "snapshots",
        "secrets": archive_root / "backups" / "secrets",
        "firecrawl": archive_root / "backups" / "firecrawl",
    }

    entries = plan(source, roots)
    entries += research_entries(
        args.research_db_source,
        args.research_snapshot_source,
        roots,
        tuple(args.snapshot_name_prefix),
    )

    print(summarize(entries))

    if args.dry_run:
        # Nothing is created, including the destination tree itself: an empty
        # archive root left behind would make a later "did this run?" check lie.
        print("\ndry run: no files written")
        return 0

    copied = 0
    for entry in entries:
        if entry.destination is None:
            continue
        origin = source_path_for(
            entry, source, args.research_db_source, args.research_snapshot_source
        )
        target = Path(entry.destination)
        if (
            args.on_existing_mismatch == "preserve-as-legacy"
            and destination_conflicts(origin, target)
        ):
            # The destination is in use and ahead of this source. Divert rather
            # than overwrite, and say so in the manifest: a migration that
            # silently replaced a live ledger with its own predecessor would
            # destroy exactly the history it exists to protect.
            diverted = roots["legacy"] / entry.relative_path.replace("<", "").replace(">", "")
            entry.diverted_from = entry.destination
            entry.destination = str(diverted)
            target = diverted
        try:
            copy_verified(origin, target)
        except MigrationError as error:
            print(f"ERROR: {error}", file=sys.stderr)
            return 1
        if entry.category == "secret":
            os.chmod(target, 0o600)
        if target.suffix in DATABASE_SUFFIXES:
            try:
                check_sqlite(target)
            except (MigrationError, sqlite3.DatabaseError) as error:
                print(f"ERROR: {error}", file=sys.stderr)
                return 1
        copied += 1

    roots["snapshots"].mkdir(parents=True, exist_ok=True)

    manifest_path = archive_root / "backups" / "migration-manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    # Sizes and digests only. No file contents reach this document, which is
    # why a secret can be inventoried here without being exposed.
    manifest_path.write_text(
        json.dumps(
            {
                "source": str(source),
                "archive_root": str(archive_root),
                "entries": [asdict(entry) for entry in entries],
            },
            indent=2,
            sort_keys=True,
        )
    )
    os.chmod(manifest_path, 0o600)

    print(f"\napplied: {copied} files copied and verified")
    print(f"manifest: {manifest_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
