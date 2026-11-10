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
    MY_PA_REPORT_CONTENT_ROOT=/path/to/report-content \\
        .venv/bin/python apps/cli/report_content.py transfer-gc [--limit N] [--discard-orphans]

The shape of `apps/cli/managed_documents.py`, for the same reason: a write plane
with no reconciliation, backup and restore is not finished. Nothing here
deletes a content or preservation object, reclaims a content orphan or repairs
a row; the one removal is `transfer-gc`'s, of transient transfer staging only.

**`transfer-gc` (WP06 T19)** collects transfer sessions
(`collect_report_transfers`): up to `--limit` (1..1000, default 100) open or
finalized sessions past their `expires_at` move to `expired`; the staging of
consumed, aborted and expired sessions is discarded (at most `--limit`);
staging directories with no session row are orphans, reported, and discarded
only with `--discard-orphans`. It removes nothing but staging under the root's
`transfer` directory (the staging port admits only `grxfr_` ids and has no
path parameter; the content and preservation namespaces are never touched).
It prints one JSON object of counts (`expired`, `discarded`, `orphans_found`,
`orphans_discarded`, `orphans_remaining`, `unreadable`, `more_remaining`), no
identifier, path or byte. Exit `0` when clean; `3` when a bound left more to
do, orphans remain unremoved, or unreadable staging entries exist (run again,
or inspect); `1` on refusal (usage, no report content root, a staging failure).

**`preservation-verify` (WP05b B5)** scans the `preservation` namespace: every
legal hold's sealed preservation copy, across Principals (the orphan direction
cannot be partitioned), re-verified seal and parts, plus orphaned preservation
objects and unreadable entries (`scan_report_preservation`). It takes no
`--principal`. Integrity findings (a missing or mismatched part or seal of a
copy a hold references, a malformed seal or a wrong object count, an
unreadable entry) are kept apart from orphans (preservation objects no hold
seal references, e.g. left by a failed placement; informational, never
deleted), which are printed in their own section. **Stale temporaries**
(WP08) -- the store's own `.decoded.tmp` / `.original.tmp` left in an object
directory by a process killed mid-put -- are informational in the same way:
counted as `stale_temporaries`, listed in their own section, never an
unreadable entry or an integrity finding, and never removed (the runbook gives
the manual procedure). `verify` reports them the same way (`stale_temporaries`,
apart from `unreadable_entries`).

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

**No path, body or digest is printed.** Exit codes:

* `verify`, `backup`, `restore`: `0` on success, `1` on refusal (usage or
  operational error), `2` when `verify` finds the plane inconsistent (a
  missing or mismatched part, an orphan, an unreadable entry or a stale
  temporary).
* `preservation-verify`: `0` when there is no integrity finding (orphans and
  stale temporaries may be present and are reported); `2` on any integrity
  finding; `3` when `--fail-on-orphans` is given, there is no integrity
  finding and at least one orphan or stale temporary exists (an integrity
  finding takes precedence: `2`); `1` on refusal (usage or operational error,
  e.g. no report content root). Only when `preservation-verify` (or
  `transfer-gc`) is the subcommand are argparse's usage errors (`2`) answered
  `1`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import Engine

from my_pa.application.report_content import (
    back_up_report_content,
    restore_report_content,
    scan_report_content,
)
from my_pa.application.report_preservation import scan_report_preservation
from my_pa.application.report_transfer_gc import (
    DEFAULT_TRANSFER_GC_LIMIT,
    collect_report_transfers,
)
from my_pa.bootstrap.gateway import (
    report_content_backup_store,
    report_content_store,
    report_preservation_store,
    report_transfer_staging,
)
from my_pa.bootstrap.settings import load_settings
from my_pa.contracts.ports import (
    ReportContentStore,
    ReportContentStoreError,
    ReportTransferStagingError,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.report_transfers import SqlReportTransferRepository
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from my_pa.infrastructure.report_content_stores.filesystem import ReportContentRootError

EXIT_OK = 0
EXIT_REFUSED = 1
EXIT_INCONSISTENT = 2
#: `preservation-verify --fail-on-orphans` only: orphans and no integrity finding.
EXIT_ORPHANS = 3
#: `transfer-gc` only: a bound left more to do, or orphans/unreadable entries remain.
EXIT_MORE_REMAINING = 3


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
    print(f"stale_temporaries {len(scan.stale_temporaries)}")
    for content_id, part in scan.missing:
        print(f"missing {content_id} {part.value}")
    for item in scan.mismatched:
        print(f"mismatch {item.content_id} {item.part.value} {item.mismatch}")
    for content_id in scan.orphans:
        print(f"orphan {content_id}")
    return EXIT_OK if scan.consistent else EXIT_INCONSISTENT


def _preservation_verify(args: argparse.Namespace) -> int:
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
    print(f"integrity_findings {scan.integrity_findings}")
    print(f"orphans {len(scan.orphans)}")
    print(f"stale_temporaries {len(scan.stale_temporaries)}")
    for object_id, part in scan.missing:
        print(f"missing {object_id} {part.value}")
    for item in scan.mismatched:
        print(f"mismatch {item.object_id} {item.part.value} {item.mismatch}")
    if scan.orphans:
        # Their own section: informational, never deleted, not an integrity finding.
        print("orphans_informational (referenced by no hold seal; never deleted)")
        for object_id in scan.orphans:
            print(f"orphan {object_id}")
    if scan.stale_temporaries:
        # Informational like orphans: a killed put's own temporaries, never removed.
        print(
            "stale_temporaries_informational "
            f"{len(scan.stale_temporaries)} (left by a killed put; never deleted)"
        )
    if not scan.intact:
        return EXIT_INCONSISTENT
    if (scan.orphans or scan.stale_temporaries) and args.fail_on_orphans:
        return EXIT_ORPHANS
    return EXIT_OK


@dataclass(frozen=True, slots=True)
class _TransferTransaction:
    report_transfers: SqlReportTransferRepository


def _transfer_gc(args: argparse.Namespace) -> int:
    engine = _engine()

    @contextmanager
    def transaction() -> Iterator[_TransferTransaction]:
        with engine.begin() as connection:
            yield _TransferTransaction(SqlReportTransferRepository(connection))

    try:
        staging = report_transfer_staging(load_settings(), engine)
        if staging is None:
            raise ReportContentRootError(
                "MY_PA_REPORT_CONTENT_ROOT is unset; there is no transfer staging "
                "in this process to operate on"
            )
        collection = collect_report_transfers(
            transaction,
            staging,
            now=datetime.now(UTC),
            limit=args.limit,
            discard_orphans=args.discard_orphans,
        )
    finally:
        engine.dispose()
    print(json.dumps(collection.summary(), sort_keys=True))
    return EXIT_OK if collection.clean else EXIT_MORE_REMAINING


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
        help=(
            "re-verify every legal hold's sealed preservation copy and find orphans; "
            "exit 0 with no integrity finding (orphans and stale temporaries are "
            "reported), 2 on any integrity finding, 3 with --fail-on-orphans and "
            "only orphans or stale temporaries, 1 on refusal"
        ),
    )
    preservation.add_argument(
        "--fail-on-orphans",
        action="store_true",
        help=(
            "exit 3 when orphans or stale temporaries exist and there is no "
            "integrity finding (which exits 2)"
        ),
    )
    preservation.set_defaults(handler=_preservation_verify)
    transfer = subcommands.add_parser(
        "transfer-gc",
        help=(
            "expire due transfer sessions and discard terminal (and with "
            "--discard-orphans orphaned) transfer staging; prints JSON counts; "
            "exit 0 clean, 3 if more remains, 1 on refusal"
        ),
    )
    transfer.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_TRANSFER_GC_LIMIT,
        help="at most this many sessions expired and directories discarded per step (1..1000)",
    )
    transfer.add_argument(
        "--discard-orphans",
        action="store_true",
        help="also discard staging directories that have no session row",
    )
    transfer.set_defaults(handler=_transfer_gc)
    backup = subcommands.add_parser("backup", help="copy verified objects to a backup root")
    backup.add_argument("--principal", required=True, help="the prn_... whose objects are copied")
    backup.add_argument("--destination", required=True, help="an existing directory to copy into")
    backup.set_defaults(handler=_backup)
    restore = subcommands.add_parser("restore", help="copy objects back from a backup root")
    restore.add_argument("--principal", required=True, help="the prn_... the backup was taken for")
    restore.add_argument("--source", required=True, help="the backup root to read")
    restore.set_defaults(handler=_restore)
    return parser


#: The subcommands whose argparse usage errors are answered `EXIT_REFUSED`.
_REFUSING_USAGE_SUBCOMMANDS = frozenset({"preservation-verify", "transfer-gc"})


def _subcommand(arguments: list[str]) -> str | None:
    """The subcommand argparse selects: the first argument not an option."""
    return next((argument for argument in arguments if not argument.startswith("-")), None)


def main(argv: list[str] | None = None) -> int:
    arguments = sys.argv[1:] if argv is None else argv
    try:
        args = build_parser().parse_args(arguments)
    except SystemExit as stop:
        # argparse exits 2 on a usage error; for `preservation-verify` 2 means an
        # integrity finding, so its usage errors are refusals (1). The other
        # subcommands keep argparse's behaviour. The subcommand is the first
        # positional argument (the top-level parser has no other), never a
        # value elsewhere in argv (WP08, WP05b corrective n3).
        if stop.code == 2 and _subcommand(arguments) in _REFUSING_USAGE_SUBCOMMANDS:
            return EXIT_REFUSED
        raise
    try:
        return int(args.handler(args))
    except (
        ReportContentRootError,
        ReportContentStoreError,
        ReportTransferStagingError,
        ValueError,
    ) as error:
        # The rule, never the value: the store's refusals name no path.
        print(str(error), file=sys.stderr)
        return EXIT_REFUSED


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
