"""Operator command: verify, back up, and restore the managed-document plane.

    MY_PA_MANAGED_DOCUMENT_ROOT=/path/to/managed \\
        .venv/bin/python apps/cli/managed_documents.py verify --principal prn_...
    MY_PA_MANAGED_DOCUMENT_ROOT=/path/to/managed \\
        .venv/bin/python apps/cli/managed_documents.py backup \\
            --principal prn_... --destination /path/to/backup
    MY_PA_MANAGED_DOCUMENT_ROOT=/path/to/managed \\
        .venv/bin/python apps/cli/managed_documents.py restore \\
            --principal prn_... --source /path/to/backup

`AGENTS.md` section 6 and the operating brief's section 32 both make operations
part of completion: a write plane with no backup, no restore and no way to check
that its two halves agree is not finished, whatever its tests say. These are the
three, and there is deliberately no fourth — nothing here deletes a document,
reclaims an orphan, or repairs a row.

**It is an operator command and not a capability.** It builds no
`ApplicationService`, resolves no `Principal` from a credential, and names no
member of `Capability`; the Principal is an argument the operator supplies,
because the operator is the authority here. `apps/cli/sources.py` records the
same reasoning for source registration.

**Two roots, both operator-designated, both proved before anything is written.**
The managed root comes from `MY_PA_MANAGED_DOCUMENT_ROOT` and the backup root
from `--destination`/`--source`. Both are handed to a
`FilesystemManagedByteStore`, whose constructor is where containment is
established: each must already exist, must be a real directory rather than a
symbolic link, and must not be, contain, or lie inside a configured read-only
source root. The destination of a backup is additionally refused if it overlaps
the live managed root, so "back up in place" cannot silently mix a manifest into
the object tree.

That two paths appear on this command line and none appears on a request is the
whole shape of the boundary: designating a root is an operator act, and the byte
store takes no path from anything else.

**Reclaiming an orphan is reported and never performed.** `verify` names the
version identifiers whose bytes belong to no row and stops there. Deleting bytes
is irreversible, `AGENTS.md` section 8.2 reserves irreversible destruction of
canonical data to the operator, and an orphan is by construction indistinguishable
from bytes whose transaction has not committed yet in another process. The
operations document says how to reclaim one deliberately.

**No path is echoed on any exit path.** A refusal names the defect, exactly as
`sources.py` and `migration.py` do. Exit `0` on success, `1` on refusal, `2` when
`verify` finds the plane inconsistent — a third status because "the command ran
and the answer is bad" is a different fact from "the command could not run", and
an operator scripting a nightly check needs to tell them apart.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import Connection, Engine

from my_pa.application.managed_documents import ManagedDocumentService
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.managed_document_stores.filesystem.store import (
    FilesystemManagedByteStore,
    ManagedStoreError,
)
from my_pa.infrastructure.persistence.managed_documents import SqlManagedDocumentRepository
from my_pa.infrastructure.persistence.registry import configured_source_roots

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_INCONSISTENT = 2


def _engine() -> Engine:
    return create_database_engine(load_settings().parsed_database_url())


def _managed_root() -> Path:
    """The configured managed root, or a refusal naming the setting.

    Empty means the managed plane is not composed in this process, which is the
    fail-closed default `bootstrap.settings` documents. Refused here rather than
    defaulted, because choosing where a user's documents live is not a decision
    this command may make.
    """
    configured = load_settings().managed_document_root.strip()
    if not configured:
        raise ManagedStoreError(
            f"{ENV_PREFIX}MANAGED_DOCUMENT_ROOT is unset; there is no managed "
            "document plane in this process to operate on"
        )
    return Path(configured)


def _verify(args: argparse.Namespace) -> int:
    """Compare the rows against the bytes and report both directions."""
    engine = _engine()
    try:
        with engine.begin() as connection:
            store = FilesystemManagedByteStore(
                _managed_root(), source_roots=_source_roots(connection)
            )
            report = ManagedDocumentService().verify(
                SqlManagedDocumentRepository(connection), store, principal_id=args.principal
            )
    finally:
        engine.dispose()

    print(f"versions_checked {report.versions_checked}")
    print(f"missing_bytes {len(report.missing_bytes)}")
    print(f"digest_mismatches {len(report.digest_mismatches)}")
    print(f"orphaned_objects {len(report.orphaned_version_ids)}")
    print(f"unreadable_entries {len(report.unreadable_entries)}")
    for version_id in report.missing_bytes:
        print(f"missing {version_id}")
    for version_id in report.digest_mismatches:
        print(f"mismatch {version_id}")
    for version_id in report.orphaned_version_ids:
        print(f"orphan {version_id}")
    if not report.is_consistent:
        return EXIT_INCONSISTENT
    return EXIT_OK


def _backup(args: argparse.Namespace) -> int:
    """Copy one Principal's versions and bytes into a second managed root."""
    engine = _engine()
    try:
        with engine.begin() as connection:
            roots = _source_roots(connection)
            managed_root = _managed_root()
            store = FilesystemManagedByteStore(managed_root, source_roots=roots)
            destination = FilesystemManagedByteStore(
                Path(args.destination), source_roots=(*roots, store.root)
            )
            summary = ManagedDocumentService().back_up(
                SqlManagedDocumentRepository(connection),
                store,
                destination,
                principal_id=args.principal,
            )
    finally:
        engine.dispose()
    print(f"documents {summary.documents}")
    print(f"versions {summary.versions}")
    print(f"bytes_copied {summary.bytes_copied}")
    print(f"manifest_sha256 {summary.manifest_sha256}")
    return EXIT_OK


def _restore(args: argparse.Namespace) -> int:
    """Rebuild one Principal's rows and bytes from a backup root."""
    engine = _engine()
    try:
        with engine.begin() as connection:
            roots = _source_roots(connection)
            managed_root = _managed_root()
            store = FilesystemManagedByteStore(managed_root, source_roots=roots)
            backup = FilesystemManagedByteStore(
                Path(args.source), source_roots=(*roots, store.root)
            )
            summary = ManagedDocumentService().restore_from_backup(
                SqlManagedDocumentRepository(connection),
                store,
                backup,
                principal_id=args.principal,
            )
    finally:
        engine.dispose()
    print(f"documents {summary.documents}")
    print(f"versions {summary.versions}")
    print(f"bytes_restored {summary.bytes_restored}")
    print(f"versions_already_present {summary.versions_already_present}")
    return EXIT_OK


def _source_roots(connection: Connection) -> tuple[Path, ...]:
    """The configured read-only source roots, for the store's refusal.

    Read here and passed straight into the two constructors. Nothing prints
    them, and the store's refusal names the rule rather than the path.
    """
    return tuple(Path(root) for root in configured_source_roots(connection))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="managed-documents",
        description="Verify, back up, and restore the managed-document plane.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)

    verify = subcommands.add_parser("verify", help="compare stored rows against stored bytes")
    verify.add_argument("--principal", required=True, help="the prn_... whose rows are checked")
    verify.set_defaults(handler=_verify)

    backup = subcommands.add_parser("backup", help="copy versions and bytes to a backup root")
    backup.add_argument("--principal", required=True, help="the prn_... whose plane is copied")
    backup.add_argument(
        "--destination", required=True, help="an existing empty directory to write the backup into"
    )
    backup.set_defaults(handler=_backup)

    restore = subcommands.add_parser("restore", help="rebuild rows and bytes from a backup root")
    restore.add_argument("--principal", required=True, help="the prn_... the backup was taken for")
    restore.add_argument("--source", required=True, help="the backup root to read")
    restore.set_defaults(handler=_restore)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (ManagedStoreError, ValueError) as error:
        # The message, and never the value that produced it. A managed root and a
        # backup root are filesystem paths, and the store's own refusals are
        # written to name the rule rather than the location.
        print(str(error), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
