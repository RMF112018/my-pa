"""Operator command for project reports (WP3P-S4, S5; rulings D5-D9, D12, D14, D16, D19).

```text
python apps/cli/project_reports.py <assertions> bindings check --file F
python apps/cli/project_reports.py <assertions> bindings apply --file F
python apps/cli/project_reports.py <assertions> run-once --source isrc_...
python apps/cli/project_reports.py <assertions> backfill --source isrc_... \\
    [--file NAME ... | --glob PATTERN] [--dry-run]
python apps/cli/project_reports.py <assertions> rederive [--source isrc_...] [--dry-run]
python apps/cli/project_reports.py <assertions> coverage [--source isrc_...]
python apps/cli/project_reports.py <assertions> aggregate --source isrc_... [--source ...] \\
    [--expect EXPECTED.json]
```

`<assertions>` is `--expected-database NAME --expected-alembic-head REVISION`,
both required on every invocation (the WP3a ruling m7 shape). They are
compared to the parsed `MY_PA_DATABASE_URL` before an engine is built and
re-checked on the live connection (`current_database()` and the single
`alembic_version` row) before anything is read or written; a mismatch refuses
with `target_mismatch`. The database URL is never an argument and never
printed.

**Configuration, not a capability.** The command records no audit row (ruling
D6: the append-only binding revisions are the audit, `recorded_by =
operator_cli`; the lifecycle rows are the run evidence) and the Principal is
the fixed local operator (`bootstrap.gateway.local_principal`), never an
argument. The bindings service, the project-reports lifecycle (which alone
admits `pulse_csv_export`, with the export reader), the re-derivation sweep,
the read-only workspace stores (from `MY_PA_FILES_WORKSPACES`) and the poll
lock are composed by `bootstrap.project_reports`, as the cycles plane composes
them.

`F` is the operator's bindings file (`my_pa_project_report_bindings_v1`),
outside the repository. It is read whole, at most `MAX_FILE_BYTES`.

* `bindings check` validates the file against the database and the workspace
  and prints its diff -- adds, corrections, filter updates, retires and
  unchanged bindings -- and the number of CSV folders under `export_root` the
  file binds to nothing (`unbound_folders`), listed to the stated
  `unbound_folder_depth`. It writes nothing and takes no lock.
* `bindings apply` applies the whole file in one transaction under the
  project-reports poll lock (`PROJECT_REPORTS_POLL_LOCK_KEY`, not waited for:
  `lock_held`), or refuses it and writes nothing. Applying the same file twice
  writes nothing the second time. Each revision records the reason its own
  change kind names (`initial`, `add`, `correction`, `filter_update` or
  `retire`); there is no reason argument (Manager ruling on S4).
* `run-once` runs the poll step once over an enabled source (trigger
  `operator`); `backfill` reads the listed files (`--file`, names in the
  source's folder or workspace-relative paths under it), one `--glob` name
  pattern, or every candidate (trigger `backfill`). Each snapshot is its own
  transaction, so a stopped backfill leaves a consistent prefix and a rerun
  counts the digests already held `snapshots_already_known`. Both refuse
  `source_unbound` up front when the source has no active binding (no
  pointer, or a retired one; ruling D12 and the Manager ruling on S5): no run,
  no snapshot -- not even a rejected one -- is written, with or without
  `--dry-run`. The handler's own in-transaction `source_unbound` stays as
  defence in depth. `--dry-run` lists, reads, parses and counts and writes
  nothing.
* `rederive` runs the re-derivation sweep now, including an `operator_rebuild`
  of every current derivation not otherwise due, at most
  `DEFAULT_SWEEP_LIMIT` snapshots per call (the rest are counted
  `derivations_deferred`); `--dry-run` counts what is due and writes nothing.
* `coverage` prints, per source, its snapshots, rejected and quarantined
  counts and its report series (an index, never a slug): versions, earliest
  and latest date labels, first and last seen (UTC), freshness seconds,
  completeness classes, quarantine reasons and filter semantics.
* `aggregate` prints the PULSE-AC-17 figures of the given sources from stored
  rows (`infrastructure.project_reports.stored_aggregate`), under exactly the
  keys of the file-level `aggregate_cli`, so the two compare mechanically.
  `--expect` compares every key of an expected-figures file
  (`project_reports_evidence_aggregate_v1`, e.g.
  `tests/fixtures/project_reports/expected/evidence_aggregate_v1.json`) exactly
  and lists only the differing keys with both integers.

`run-once`, `backfill` and `rederive` (not `--dry-run`) hold the poll lock for
their whole run, the key the cycles-plane step takes; when it is held they
refuse `lock_held` and write nothing. The read commands take no lock.

**Output is one JSON object on standard output: identifiers, closed codes,
counts, UTC timestamps, ISO dates and project numbers only** -- never the
database URL, a path, a folder, a file name, a slug, a filter description, a
record number, a byte offset (ruling D16) or any file content. A refusal is
`{"command": ..., "refused": CODE}` with a closed `CODE`.

Exit status (closed):

| exit | meaning |
| --- | --- |
| `0` | done: a run `completed`, a sweep with no failure, an aggregate that matched |
| `1` | refused, with one closed code (below); nothing was written |
| `2` | usage error (argparse) |
| `3` | a run finished `partial` or `failed`, or `rederive` counted `derivations_failed` |
| `4` | `aggregate --expect`: a figure differs |

Refusal codes: the `BindingRefusal` values (`file_unreadable`,
`schema_invalid`, `unknown_key`, `duplicate_json_key`, `project_not_found`,
`project_number_mismatch`, `project_has_no_number`, `folder_duplicated`,
`folder_nested`, `project_duplicated`, `folder_outside_export_root`,
`folder_not_found`, `currency_invalid`, `filter_description_invalid`,
`lock_held`); the lifecycle's `IngestRefusalCode` values; and
`target_mismatch`, `settings_invalid`, `workspace_misconfigured`,
`source_not_found` (no project-report source of the operator has that id),
`source_unbound` (`run-once` or `backfill` of a source with no active binding),
`expect_invalid`, `transaction_conflict`, `write_refused` (a database guard
refused a write), `database_unreachable` and `database_unavailable`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterator, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

from my_pa.application.ingestion import IngestRefusedError, IngestRunReport
from my_pa.application.project_reports_bindings import BindingsReport
from my_pa.application.project_reports_coverage import project_reports_coverage
from my_pa.application.project_reports_ingest import (
    ProjectReportsSourceUnboundError,
    bound_revision,
)
from my_pa.application.project_reports_rederive import DEFAULT_SWEEP_LIMIT
from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.project_reports import (
    bindings_service,
    poll_lock,
    project_reports_lifecycle,
    project_reports_unit_of_work,
    rederiver,
)
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.contracts.ports import (
    FileWorkspaceRootError,
    IngestConsumer,
    IngestRunOutcome,
    IngestSourceRecord,
    ProjectReportsWriteRefusedError,
    TransactionConflictError,
)
from my_pa.domain.project_reports.bindings import BindingsRefusedError
from my_pa.domain.project_reports.model import BindingRefusal
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.project_reports.aggregate_cli import (
    ExpectFileError,
    compare_expected,
    load_expected,
)
from my_pa.infrastructure.project_reports.pulse_csv import READER_VERSION
from my_pa.infrastructure.project_reports.stored_aggregate import stored_counts

__all__ = [
    "EXIT_EXPECT_DIFFERS",
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_RUN_INCOMPLETE",
    "MAX_FILE_BYTES",
    "build_parser",
    "main",
]

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1
EXIT_RUN_INCOMPLETE: Final = 3
EXIT_EXPECT_DIFFERS: Final = 4

#: The statement bound every engine here runs under (the engine-bounded guard).
STATEMENT_TIMEOUT_MS: Final = 60_000
#: The largest bindings or expected-figures file read; a larger one is refused.
MAX_FILE_BYTES: Final = 1024 * 1024


class _RefusalError(Exception):
    """A refusal with a closed code; the code is the whole answer."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _emit(fields: dict[str, object]) -> None:
    print(json.dumps(fields, sort_keys=True), flush=True)


def _iso(moment: datetime | None) -> str | None:
    if moment is None:
        return None
    return moment.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _command(args: argparse.Namespace) -> str:
    return f"{args.command}_{args.action}" if args.command == "bindings" else str(args.command)


# --- the target -------------------------------------------------------------


def _assert_configured(settings: Settings, args: argparse.Namespace) -> None:
    if settings.parsed_database_url().database != args.expected_database:
        raise _RefusalError("target_mismatch")


def _assert_connected(connection: Connection, args: argparse.Namespace) -> None:
    database = connection.execute(text("SELECT current_database()")).scalar_one()
    try:
        revisions = (
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars().all()
        )
    except ProgrammingError:
        raise _RefusalError("target_mismatch") from None
    if (
        database != args.expected_database
        or len(revisions) != 1
        or revisions[0] != args.expected_alembic_head
    ):
        raise _RefusalError("target_mismatch")


# --- the commands -----------------------------------------------------------


def _read_file(path: str, refusal: str) -> bytes:
    """A file's bytes, or the closed `refusal` (the path is never printed)."""
    try:
        with Path(path).open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise _RefusalError(refusal) from None
    if len(data) > MAX_FILE_BYTES:
        raise _RefusalError(refusal)
    return data


def _report_fields(command: str, report: BindingsReport) -> dict[str, object]:
    fields: dict[str, object] = {
        "command": command,
        "applied": report.applied,
        "counts": report.counts,
        "project_numbers": {key: list(value) for key, value in report.project_numbers.items()},
    }
    if report.writes:
        fields["writes"] = dict(report.writes)
    if report.unbound_folders is not None:
        fields["unbound_folders"] = report.unbound_folders
        fields["unbound_folder_depth"] = report.unbound_folder_depth
        fields["unbound_listing_truncated"] = report.unbound_listing_truncated
    return fields


def _bindings(engine: Engine, settings: Settings, args: argparse.Namespace) -> int:
    principal_id = local_principal().principal_id
    data = _read_file(args.file, BindingRefusal.FILE_UNREADABLE.value)
    service = bindings_service(settings, engine)
    command = _command(args)
    match args.action:
        case "check":
            _emit(_report_fields(command, service.check(principal_id, data)))
        case "apply":
            _emit(_report_fields(command, service.apply(principal_id, data)))
        case unknown:  # pragma: no cover - argparse rejects an unknown action first
            raise SystemExit(f"unhandled action {unknown!r}")
    return EXIT_OK


def _require_source(engine: Engine, principal_id: str, source_id: str) -> IngestSourceRecord:
    """The project-report source, or `source_not_found` (its prefix is never printed)."""
    with project_reports_unit_of_work(engine)() as unit:
        source = unit.ingestion.get_source(principal_id, source_id)
    if source is None or source.consumer is not IngestConsumer.PULSE_CSV_EXPORT:
        raise _RefusalError("source_not_found")
    return source


def _require_bound(engine: Engine, principal_id: str, source_id: str) -> None:
    """The source is a project-report source with an active binding, or a refusal.

    `source_not_found` first, then `source_unbound` (ruling D12, the Manager
    ruling on S5): refused before the lifecycle runs, so nothing -- no run, no
    snapshot, not even a rejected one -- is written.
    """
    _require_source(engine, principal_id, source_id)
    with project_reports_unit_of_work(engine)() as unit:
        try:
            bound_revision(unit, principal_id, source_id)
        except ProjectReportsSourceUnboundError:
            raise _RefusalError(ProjectReportsSourceUnboundError.code) from None


@contextmanager
def _locked(engine: Engine) -> Iterator[None]:
    """Hold the project-reports poll lock, or refuse `lock_held` without waiting."""
    with poll_lock(engine)() as held:
        if not held:
            raise _RefusalError(BindingRefusal.LOCK_HELD.value)
        yield


def _run_report(command: str, report: IngestRunReport) -> int:
    _emit(
        {
            "command": command,
            "ingest_source_id": report.ingest_source_id,
            "trigger": report.trigger.value,
            "dry_run": report.dry_run,
            "run_id": report.run_id,
            "outcome": report.outcome.value,
            "counts": dict(report.counts),
        }
    )
    return EXIT_OK if report.outcome is IngestRunOutcome.COMPLETED else EXIT_RUN_INCOMPLETE


def _backfill_paths(prefix: str, names: Sequence[str]) -> list[str]:
    directory = prefix.removesuffix("/")
    return [name if "/" in name or not directory else f"{directory}/{name}" for name in names]


def _runs(engine: Engine, settings: Settings, args: argparse.Namespace) -> int:
    principal_id = local_principal().principal_id
    lifecycle = project_reports_lifecycle(settings, engine)
    run: Callable[[], IngestRunReport]
    if args.command == "run-once":
        run = lambda: lifecycle.run_once(principal_id, args.source)  # noqa: E731
    else:
        paths = None
        if args.file is not None:
            paths = _backfill_paths(
                _require_source(engine, principal_id, args.source).path_prefix, args.file
            )
        if args.dry_run:  # writes nothing, so it takes no lock
            _require_bound(engine, principal_id, args.source)
            return _run_report(
                "backfill",
                lifecycle.backfill(
                    principal_id, args.source, paths=paths, name_pattern=args.glob, dry_run=True
                ),
            )
        run = lambda: lifecycle.backfill(  # noqa: E731
            principal_id, args.source, paths=paths, name_pattern=args.glob
        )
    with _locked(engine):  # bindings apply takes the same lock: the check holds for the run
        _require_bound(engine, principal_id, args.source)
        report = run()
    return _run_report(args.command, report)


def _rederive(engine: Engine, args: argparse.Namespace) -> int:
    principal_id = local_principal().principal_id
    if args.source is not None:
        _require_source(engine, principal_id, args.source)
    sweep = rederiver(engine)

    def run() -> dict[str, int]:
        report = sweep.sweep(
            principal_id,
            limit=DEFAULT_SWEEP_LIMIT,
            ingest_source_id=args.source,
            dry_run=args.dry_run,
            rebuild=True,
        )
        return dict(report.counts)

    if args.dry_run:
        counts = run()
    else:
        with _locked(engine):
            counts = run()
    _emit(
        {
            "command": "rederive",
            "ingest_source_id": args.source,
            "dry_run": args.dry_run,
            "counts": counts,
        }
    )
    return EXIT_RUN_INCOMPLETE if counts.get("derivations_failed") else EXIT_OK


def _coverage(engine: Engine, args: argparse.Namespace) -> int:
    principal_id = local_principal().principal_id
    if args.source is not None:
        _require_source(engine, principal_id, args.source)
    now = datetime.now(UTC)
    with project_reports_unit_of_work(engine)() as unit:
        sources = project_reports_coverage(
            unit, principal_id, None if args.source is None else [args.source], now=now
        )
    _emit(
        {
            "command": "coverage",
            "as_of": _iso(now),
            "sources": [
                {
                    "ingest_source_id": source.ingest_source_id,
                    "enabled": source.enabled,
                    "binding_state": source.binding_state,
                    "project_number": source.project_number,
                    "snapshots": source.snapshots,
                    "ingested": source.ingested,
                    "rejected": source.rejected,
                    "quarantined": source.quarantined,
                    "series": [
                        {
                            "series": index,
                            "family_view": series.family_view,
                            "versions": series.versions,
                            "earliest_date_label": series.earliest_date_label,
                            "latest_date_label": series.latest_date_label,
                            "first_seen": _iso(series.first_seen),
                            "last_seen": _iso(series.last_seen),
                            "freshness_seconds": series.freshness_seconds,
                            "filter_semantics": series.filter_semantics.value,
                            "completeness": series.completeness,
                            "quarantined": series.quarantined,
                        }
                        for index, series in enumerate(source.series, start=1)
                    ],
                }
                for source in sources
            ],
        }
    )
    return EXIT_OK


def _aggregate(engine: Engine, args: argparse.Namespace) -> int:
    principal_id = local_principal().principal_id
    expected: dict[str, int] | None = None
    if args.expect is not None:
        try:
            expected = load_expected(_read_file(args.expect, "expect_invalid"))
        except ExpectFileError:
            raise _RefusalError("expect_invalid") from None
    sources = sorted(set(args.source))
    for source_id in sources:
        _require_source(engine, principal_id, source_id)
    with project_reports_unit_of_work(engine)() as unit:
        counts = stored_counts(unit, principal_id, sources)
    fields: dict[str, object] = {
        "command": "aggregate",
        "ingest_source_ids": sources,
        "reader_version": READER_VERSION,
        "counts": counts,
    }
    differs = False
    if expected is not None:
        comparison = compare_expected(counts, expected)
        fields["expect"] = comparison
        differs = bool(comparison["differing"])
    _emit(fields)
    return EXIT_EXPECT_DIFFERS if differs else EXIT_OK


def _dispatch(engine: Engine, settings: Settings, args: argparse.Namespace) -> int:
    match args.command:
        case "bindings":
            return _bindings(engine, settings, args)
        case "run-once" | "backfill":
            return _runs(engine, settings, args)
        case "rederive":
            return _rederive(engine, args)
        case "coverage":
            return _coverage(engine, args)
        case "aggregate":
            return _aggregate(engine, args)
        case unknown:  # pragma: no cover - argparse rejects an unknown command first
            raise SystemExit(f"unhandled command {unknown!r}")


def _run(args: argparse.Namespace) -> int:
    try:
        settings = load_settings()
    except Exception:  # the message may carry configuration; only the code leaves
        raise _RefusalError("settings_invalid") from None
    _assert_configured(settings, args)
    engine = create_database_engine(
        settings.parsed_database_url(), statement_timeout_ms=STATEMENT_TIMEOUT_MS
    )
    try:
        with engine.connect() as connection:
            _assert_connected(connection, args)
        return _dispatch(engine, settings, args)
    finally:
        engine.dispose()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="project_reports",
        description="Bind, ingest, re-derive and measure the project-report exports.",
    )
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--expected-alembic-head", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    bindings = commands.add_parser("bindings", help="the folder-to-Project bindings")
    actions = bindings.add_subparsers(dest="action", required=True)
    check = actions.add_parser("check", help="validate the file and print its diff; no write")
    check.add_argument("--file", required=True, metavar="F")
    apply = actions.add_parser("apply", help="apply the whole file in one transaction")
    apply.add_argument("--file", required=True, metavar="F")

    run_once = commands.add_parser("run-once", help="run the poll step once (trigger operator)")
    run_once.add_argument("--source", required=True)

    backfill = commands.add_parser("backfill", help="backfill files (trigger backfill)")
    backfill.add_argument("--source", required=True)
    chosen = backfill.add_mutually_exclusive_group()
    chosen.add_argument("--file", action="append", metavar="NAME")
    chosen.add_argument("--glob", metavar="PATTERN")
    backfill.add_argument("--dry-run", action="store_true")

    rederive = commands.add_parser("rederive", help="re-derive stored snapshots now")
    rederive.add_argument("--source")
    rederive.add_argument("--dry-run", action="store_true")

    coverage = commands.add_parser("coverage", help="series, versions and freshness per source")
    coverage.add_argument("--source")

    aggregate = commands.add_parser("aggregate", help="the AC-17 figures from stored rows")
    aggregate.add_argument("--source", required=True, action="append")
    aggregate.add_argument("--expect", metavar="EXPECTED_JSON")
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    command = _command(args)
    try:
        return _run(args)
    except _RefusalError as refusal:
        _emit({"command": command, "refused": refusal.code})
    except BindingsRefusedError as refusal:
        _emit({"command": command, "refused": refusal.code.value})
    except IngestRefusedError as refusal:
        _emit({"command": command, "refused": refusal.code.value})
    except FileWorkspaceRootError:
        _emit({"command": command, "refused": "workspace_misconfigured"})
    except TransactionConflictError:
        _emit({"command": command, "refused": "transaction_conflict"})
    except ProjectReportsWriteRefusedError:  # a guard refused a write; nothing committed
        _emit({"command": command, "refused": "write_refused"})
    except OperationalError:
        _emit({"command": command, "refused": "database_unreachable"})
    except SQLAlchemyError:
        _emit({"command": command, "refused": "database_unavailable"})
    return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
