"""Operator command: scan, back up, and restore the report content store (WP05 C7, WP05b).

    MY_PA_REPORT_CONTENT_ROOT=/path/to/report-content \\
        .venv/bin/python apps/cli/report_content.py verify --principal prn_...
    MY_PA_REPORT_CONTENT_ROOT=/path/to/report-content \\
        .venv/bin/python apps/cli/report_content.py backup \\
            --principal prn_... --destination /path/to/backup
    MY_PA_REPORT_CONTENT_ROOT=/path/to/report-content \\
        .venv/bin/python apps/cli/report_content.py restore \\
            --principal prn_... --source /path/to/backup
    MY_PA_REPORT_CONTENT_ROOT=/path/to/report-content \\
        .venv/bin/python apps/cli/report_content.py preservation-verify

The shape of `apps/cli/managed_documents.py`, for the same reason: a write plane
with no reconciliation, backup and restore is not finished. Four subcommands
and no fifth -- nothing here deletes an object, reclaims an orphan or repairs a
row.

**`preservation-verify` (WP05b B5)** scans the `preservation` namespace: every
legal hold's sealed preservation copy, across Principals (the orphan direction
cannot be partitioned), re-verified seal and parts, plus orphaned preservation
objects and unreadable entries (`scan_report_preservation`). It takes no
`--principal`.

**Backups do not include the preservation namespace.** `backup` and `restore`
copy only the `content` objects `managed_blob` rows name (operator decision:
backups need not honor holds). After a restore, `preservation-verify` reports
any preservation copy the restored store lacks as missing parts.

**An operator command, not a capability.** It builds no `ApplicationService`,
resolves no `Principal` from a credential and names no `Capability`; the
Principal is an argument the operator supplies.

**Both roots go through the store's constructor.** The live store and the
backup store are built by `bootstrap.gateway` (`report_content_store`,
`report_content_backup_store`) exactly as the served process builds the live
one: each root must exist, be a real directory, and be clear of every
configured source root and the managed document root, and a backup root must
also be clear of the live root.

**The database is backed up separately** (`pg_dump`); a restore restores the
database first, then this command copies each row's object back, verified
against the restored rows.

**No path, body or digest is printed.** Exit `0` on success, `1` on refusal,
`2` when `verify` or `preservation-verify` finds the plane inconsistent.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import Engine

from my_pa.application.report_content import (
    back_up_report_content,
    restore_report_content,
    scan_report_content,
)
from my_pa.application.report_preservation import scan_report_preservation
from my_pa.bootstrap.gateway import (
    report_content_backup_store,
    report_content_store,
    report_preservation_store,
)
from my_pa.bootstrap.settings import load_settings
from my_pa.contracts.ports import ReportContentStore, ReportContentStoreError
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from my_pa.infrastructure.report_content_stores.filesystem import ReportContentRootError

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_INCONSISTENT = 2


def _engine() -> Engine:
    return create_database_engine(
        load_settings().parsed_database_url(), statement_timeout_ms=30_000
    )


def _live(engine: Engine) -> ReportContentStore:
    store = report_content_store(load_settings(), engine)
    if store is None:
        raise ReportContentRootError(
            "MY_PA_REPORT_CONTENT_ROOT is unset; there is no report content store "
            "in this process to operate on"
        )
    return store


def _verify(args: argparse.Namespace) -> int:
    engine = _engine()
    try:
        store = _live(engine)
        with engine.begin() as connection:
            scan = scan_report_content(
                SqlGeneralReportRepository(connection), store, principal_id=args.principal
            )
    finally:
        engine.dispose()
    print(f"objects_checked {scan.checked}")
    print(f"missing_parts {len(scan.missing)}")
    print(f"mismatched_parts {len(scan.mismatched)}")
    print(f"orphaned_objects {len(scan.orphans)}")
    print(f"unreadable_entries {len(scan.unreadable)}")
    for content_id, part in scan.missing:
        print(f"missing {content_id} {part.value}")
    for item in scan.mismatched:
        print(f"mismatch {item.content_id} {item.part.value} {item.mismatch}")
    for content_id in scan.orphans:
        print(f"orphan {content_id}")
    return EXIT_OK if scan.consistent else EXIT_INCONSISTENT


def _preservation_verify(args: argparse.Namespace) -> int:
    del args
    engine = _engine()
    try:
        store = report_preservation_store(load_settings(), engine)
        if store is None:
            raise ReportContentRootError(
                "MY_PA_REPORT_CONTENT_ROOT is unset; there is no report content store "
                "in this process to operate on"
            )
        with engine.begin() as connection:
            scan = scan_report_preservation(SqlGeneralReportRepository(connection), store)
    finally:
        engine.dispose()
    print(f"holds_checked {scan.checked}")
    print(f"missing_parts {len(scan.missing)}")
    print(f"mismatched_parts {len(scan.mismatched)}")
    print(f"orphaned_objects {len(scan.orphans)}")
    print(f"unreadable_entries {len(scan.unreadable)}")
    for object_id, part in scan.missing:
        print(f"missing {object_id} {part.value}")
    for item in scan.mismatched:
        print(f"mismatch {item.object_id} {item.part.value} {item.mismatch}")
    for object_id in scan.orphans:
        print(f"orphan {object_id}")
    return EXIT_OK if scan.consistent else EXIT_INCONSISTENT


def _backup(args: argparse.Namespace) -> int:
    engine = _engine()
    try:
        store = _live(engine)
        destination = report_content_backup_store(load_settings(), engine, Path(args.destination))
        with engine.begin() as connection:
            summary = back_up_report_content(
                SqlGeneralReportRepository(connection),
                store,
                destination,
                principal_id=args.principal,
            )
    finally:
        engine.dispose()
    print(f"objects {summary.objects}")
    print(f"copied {summary.copied}")
    print(f"already_present {summary.already_present}")
    print(f"bytes_copied {summary.bytes_copied}")
    return EXIT_OK


def _restore(args: argparse.Namespace) -> int:
    engine = _engine()
    try:
        store = _live(engine)
        backup = report_content_backup_store(load_settings(), engine, Path(args.source))
        with engine.begin() as connection:
            summary = restore_report_content(
                SqlGeneralReportRepository(connection),
                backup,
                store,
                principal_id=args.principal,
            )
    finally:
        engine.dispose()
    print(f"objects {summary.objects}")
    print(f"copied {summary.copied}")
    print(f"already_present {summary.already_present}")
    print(f"bytes_copied {summary.bytes_copied}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="report-content",
        description="Scan, back up, and restore the report content store.",
    )
    subcommands = parser.add_subparsers(dest="command", required=True)
    verify = subcommands.add_parser("verify", help="compare managed_blob rows against the store")
    verify.add_argument("--principal", required=True, help="the prn_... whose rows are checked")
    verify.set_defaults(handler=_verify)
    preservation = subcommands.add_parser(
        "preservation-verify",
        help="re-verify every legal hold's sealed preservation copy and find orphans",
    )
    preservation.set_defaults(handler=_preservation_verify)
    backup = subcommands.add_parser("backup", help="copy verified objects to a backup root")
    backup.add_argument("--principal", required=True, help="the prn_... whose objects are copied")
    backup.add_argument("--destination", required=True, help="an existing directory to copy into")
    backup.set_defaults(handler=_backup)
    restore = subcommands.add_parser("restore", help="copy objects back from a backup root")
    restore.add_argument("--principal", required=True, help="the prn_... the backup was taken for")
    restore.add_argument("--source", required=True, help="the backup root to read")
    restore.set_defaults(handler=_restore)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        return int(args.handler(args))
    except (ReportContentRootError, ReportContentStoreError, ValueError) as error:
        # The rule, never the value: the store's refusals name no path.
        print(str(error), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
