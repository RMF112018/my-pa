"""Operator command for the communications ingestion lifecycle (contract sections 10, 11, 19).

```text
python apps/cli/communications_ingest.py <assertions> admit \\
    --consumer communications_evidence_v2 --workspace mcp \\
    --path-prefix "My PA/Daily Intelligence/communications/" --file-pattern "*-comms.json" \\
    [--disabled]
python apps/cli/communications_ingest.py <assertions> enable  --source isrc_...
python apps/cli/communications_ingest.py <assertions> disable --source isrc_...
python apps/cli/communications_ingest.py <assertions> run-once --source isrc_...
python apps/cli/communications_ingest.py <assertions> backfill --source isrc_... \\
    [--file NAME ... | --glob PATTERN] [--dry-run]
python apps/cli/communications_ingest.py <assertions> coverage --source isrc_... \\
    [--from ISO8601 --to ISO8601]
python apps/cli/communications_ingest.py <assertions> aggregate --source isrc_... [--source ...]
python apps/cli/communications_ingest.py <assertions> rederive [--source isrc_...] \\
    [--limit N] [--dry-run]
python apps/cli/communications_ingest.py <assertions> measure-fts [--source isrc_...] [--limit N]
```

`<assertions>` is `--expected-database NAME --expected-alembic-head REVISION`,
both required on every invocation (WP3a ruling m7). They are compared to the
parsed `MY_PA_DATABASE_URL` before an engine is built and re-checked on the
live connection (`current_database()` and the single `alembic_version` row)
before anything is read or written; a mismatch refuses with `target_mismatch`.

**Configuration, not a capability.** The command builds no application service
and records no audit row (ruling m8: `admitted_by='operator_cli'`); its
evidence is the lifecycle rows. The Principal is the fixed local operator
(`bootstrap.gateway.local_principal`), never an argument. The lifecycle, the
workspace stores (from `MY_PA_FILES_WORKSPACES`) and the coverage reader are
composed by `bootstrap.communications_ingest`, exactly as the cycles plane
composes them.

**Output is one JSON object on standard output, counts only.** Source ids, run
ids, closed codes, counts and UTC timestamps; never the database URL, a path, a
file name, a digest, a subject, an address or a provider id. A refusal is
`{"command": ..., "refused": CODE}` with a closed `CODE`.

Exit status (closed):

| exit | meaning |
| --- | --- |
| `0` | done; for `run-once` and `backfill`, the run's outcome is `completed` |
| `1` | refused, with one closed code (below) |
| `2` | usage error (argparse) |
| `3` | `run-once` or `backfill` finished `partial` or `failed`, or a publication failed to apply |

Refusal codes: the lifecycle's `IngestRefusalCode` values, plus
`target_mismatch`, `settings_invalid`, `workspace_misconfigured`,
`invalid_range`, `lock_held`, `database_unreachable` and `database_unavailable`.
`coverage` and `aggregate` refuse `source_not_found` for a source id that names
no admitted source of the operator.

**One writer at a time.** `run-once` and `backfill` (not `--dry-run`, and not
the read commands) hold the poll's session advisory lock,
`COMMS_INGEST_LOCK_KEY` (`pg_try_advisory_lock`, on a dedicated connection,
for the whole run) -- the same key the cycles plane's poll step takes. When
another session holds it (a poll in progress, or a second operator run) the
command does not wait: it refuses `lock_held` (exit 1) and writes nothing.

`backfill` takes either explicit `--file` names (each a name in the source's
folder, or a workspace-relative path under it) or one `--glob` name pattern, or
neither for every candidate. Files are applied oldest window first, each in its
own transaction, so a stopped backfill leaves a consistent prefix and a rerun
skips the SHA-256 values already ingested (`snapshots_already_known`).
`--dry-run` lists, reads, parses and counts and writes nothing at all.

**Rederive (WP4-S3, rulings D2, D3, R4, R9).** `rederive` brings stored
messages to the current search-text and identifier versions
(`application.communications_rederive`): at most `--limit` due messages
(default 1,000, at most 20,000), the rest counted `messages_deferred` for the
next run, optionally only those whose text pointer names a snapshot of
`--source`. Each snapshot's file is re-read through the read-only workspace
store and accepted only when its SHA-256 equals the snapshot's; a missing or
changed file keeps the stored text and flags the message `source_unavailable`.
It holds `COMMS_INGEST_LOCK_KEY` for the run (refusing `lock_held`); `--dry-run`
counts the due set, reads no file, writes nothing and takes no lock. Its
counts are the closed `REDERIVE_COUNT_KEYS`; any `messages_failed` makes the
exit `3`. There is no prune (ruling R4): earlier versions' identifier rows
stay, and reads filter by version.

**The FTS measurement (WP4 ruling D4).** `measure-fts` is read-only:
per-class counts (`identifier`, `name`) of probe terms over stored messages,
`english` against `simple`, and whether the `english` misses no index covers
are material (`communications_fts_measurement`). No term, address or id is
printed.

**Applying the meeting sync (WP3b-S3).** After `run-once` and `backfill` (not
`--dry-run`), still under `COMMS_INGEST_LOCK_KEY`, the staged `meeting_sync_v1`
publications are applied (`MeetingSyncApplier.apply_pending`): nothing applies
until the reconciliation latch exists. Its counts are printed under
`meeting_sync_apply`, closed names and integers only; a publication that failed
to apply (`publications_failed`) makes the exit `3`.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from datetime import UTC, datetime
from typing import Final, Protocol

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

from my_pa.application.ingestion import IngestRefusedError, IngestRunReport
from my_pa.bootstrap.communications_ingest import (
    DEFAULT_REDERIVE_LIMIT,
    IDENTIFIER_VERSION,
    MAX_REDERIVE_LIMIT,
    communications_rederiver,
    coverage_reader,
    ingest_unit_of_work,
    ingestion_lifecycle,
    meeting_sync_applier,
)
from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.contracts.ports import (
    FileWorkspaceRootError,
    IngestConsumer,
    IngestRunOutcome,
    IngestSourceRecord,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs.cycle_scheduler import COMMS_INGEST_LOCK_KEY, single_flight
from my_pa.infrastructure.persistence.communications import (
    communications_aggregate,
    communications_fts_measurement,
)
from my_pa.infrastructure.persistence.ingestion import ingest_aggregate

__all__ = ["EXIT_OK", "EXIT_REFUSED", "EXIT_RUN_INCOMPLETE", "build_parser", "main"]

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1
EXIT_RUN_INCOMPLETE: Final = 3

#: The statement bound every engine here runs under (the engine-bounded guard).
STATEMENT_TIMEOUT_MS: Final = 60_000
#: `measure-fts` measures at most this many messages per invocation.
DEFAULT_MEASURE_LIMIT: Final = 20_000
MAX_MEASURE_LIMIT: Final = 100_000


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


def _instant(value: str) -> datetime:
    """An ISO 8601 instant with an offset, as a UTC datetime (refused `invalid_range`)."""
    try:
        moment = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        raise _RefusalError("invalid_range") from None
    if moment.tzinfo is None:
        raise _RefusalError("invalid_range")
    return moment.astimezone(UTC)


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


def _run_report(command: str, report: IngestRunReport, applied: _Applied | None = None) -> int:
    fields: dict[str, object] = {
        "command": command,
        "ingest_source_id": report.ingest_source_id,
        "trigger": report.trigger.value,
        "dry_run": report.dry_run,
        "run_id": report.run_id,
        "outcome": report.outcome.value,
        "counts": dict(report.counts),
    }
    if applied is not None:
        fields["meeting_sync_apply"] = dict(sorted(applied.counts.items()))
    _emit(fields)
    complete = report.outcome is IngestRunOutcome.COMPLETED and not (
        applied is not None and applied.counts.get("publications_failed")
    )
    return EXIT_OK if complete else EXIT_RUN_INCOMPLETE


def _run_and_apply(engine: Engine, command: str, principal_id: str, run: _Run) -> int:
    """Run under the poll lock, then apply the staged meeting sync (WP3b-S3), still under it."""
    with _poll_lock(engine):
        report = run()
        applied = meeting_sync_applier(engine).apply_pending(principal_id)
    return _run_report(command, report, applied)


def _backfill_paths(prefix: str, names: Sequence[str]) -> list[str]:
    directory = prefix.removesuffix("/")
    return [name if "/" in name or not directory else f"{directory}/{name}" for name in names]


class _Applied(Protocol):
    """The applier's report (`MeetingSyncApplyReport`), named without importing the slice."""

    @property
    def counts(self) -> Mapping[str, int]: ...


class _Run(Protocol):
    def __call__(self) -> IngestRunReport: ...


class _Span(Protocol):
    @property
    def inclusive_seconds(self) -> int: ...


class _Range(Protocol):
    """The shape of a range read (`RangeCoverage`), named here without importing the slice."""

    @property
    def start(self) -> datetime: ...
    @property
    def end(self) -> datetime: ...
    @property
    def state(self) -> str: ...
    @property
    def covered_seconds(self) -> int: ...
    @property
    def gaps(self) -> Sequence[_Span]: ...


def _range_fields(coverage: _Range | None) -> dict[str, object]:
    if coverage is None:  # nothing covered: the rolling read has no anchor
        return {
            "start": None,
            "end": None,
            "state": "none",
            "covered_seconds": 0,
            "gap_count": 0,
            "gap_seconds": 0,
        }
    return {
        "start": _iso(coverage.start),
        "end": _iso(coverage.end),
        "state": str(coverage.state),
        "covered_seconds": coverage.covered_seconds,
        "gap_count": len(coverage.gaps),
        "gap_seconds": sum(gap.inclusive_seconds for gap in coverage.gaps),
    }


def _coverage(engine: Engine, principal_id: str, args: argparse.Namespace) -> int:
    _require_source(engine, principal_id, args.source)
    reader = coverage_reader(engine)
    summary = reader.summary(principal_id, args.source)
    rolling = reader.rolling(principal_id, args.source)
    fields: dict[str, object] = {
        "command": "coverage",
        "ingest_source_id": args.source,
        "snapshots": summary.snapshots,
        "complete_snapshots": summary.complete_snapshots,
        "interval_count": len(summary.intervals),
        "intervals": [
            {"start": _iso(i.start), "end": _iso(i.end), "seconds": i.inclusive_seconds}
            for i in summary.intervals
        ],
        "gap_count": len(summary.gaps),
        "gap_seconds": sum(gap.inclusive_seconds for gap in summary.gaps),
        "latest_covered": _iso(summary.latest_covered),
        "freshness_seconds": summary.freshness_seconds,
        "lanes": [
            {
                "key_kind": lane.key_kind,
                "role": lane.role,
                "lane": lane.lane,
                "states": dict(lane.states),
                "latest_state": lane.latest_state,
                "latest_authorized": lane.latest_authorized,
                "complete_interval_count": len(lane.intervals),
            }
            for lane in summary.lanes
        ],
        "rolling_30d": _range_fields(rolling),
    }
    if args.range_from is not None:
        start, end = _instant(args.range_from), _instant(args.range_to)
        if end < start:
            raise _RefusalError("invalid_range")
        fields["range"] = _range_fields(
            reader.range(principal_id, args.source, start=start, end=end)
        )
    _emit(fields)
    return EXIT_OK


def _aggregate(engine: Engine, principal_id: str, args: argparse.Namespace) -> int:
    sources = sorted(set(args.source))
    for source_id in sources:
        _require_source(engine, principal_id, source_id)
    with engine.connect() as connection:
        lifecycle = ingest_aggregate(connection, principal_id, sources)
        communications = communications_aggregate(connection, principal_id, sources)
    combined = coverage_reader(engine).combined(principal_id, sources)
    _emit(
        {
            "command": "aggregate",
            "ingest_source_ids": sources,
            **lifecycle,
            **communications,
            "coverage": {
                "snapshots": combined.snapshots,
                "complete_snapshots": combined.complete_snapshots,
                "interval_count": len(combined.intervals),
                "gap_count": len(combined.gaps),
                "gap_seconds": sum(gap.inclusive_seconds for gap in combined.gaps),
                "earliest_covered": _iso(combined.intervals[0].start)
                if combined.intervals
                else None,
                "latest_covered": _iso(combined.latest_covered),
                "freshness_seconds": combined.freshness_seconds,
            },
        }
    )
    return EXIT_OK


def _rederive(
    engine: Engine, settings: Settings, principal_id: str, args: argparse.Namespace
) -> int:
    if args.source is not None:
        _require_source(engine, principal_id, args.source)
    rederiver = communications_rederiver(settings, engine)

    def run() -> int:
        report = rederiver.rederive(
            principal_id, limit=args.limit, ingest_source_id=args.source, dry_run=args.dry_run
        )
        _emit(
            {
                "command": "rederive",
                "ingest_source_id": args.source,
                "dry_run": report.dry_run,
                "search_text_version": report.search_text_version,
                "identifier_version": report.identifier_version,
                "counts": dict(report.counts),
            }
        )
        return EXIT_RUN_INCOMPLETE if report.counts.get("messages_failed") else EXIT_OK

    if args.dry_run:  # reads and writes nothing but the due set, so it takes no lock
        return run()
    with _poll_lock(engine):
        return run()


def _measure_fts(engine: Engine, principal_id: str, args: argparse.Namespace) -> int:
    if args.source is not None:
        _require_source(engine, principal_id, args.source)
    with engine.connect() as connection:
        measured = communications_fts_measurement(
            connection,
            principal_id,
            identifiers_version=IDENTIFIER_VERSION,
            ingest_source_id=args.source,
            limit=args.limit,
        )
    _emit({"command": "measure-fts", "ingest_source_id": args.source, **measured})
    return EXIT_OK


def _dispatch(engine: Engine, settings: Settings, args: argparse.Namespace) -> int:
    principal_id = local_principal().principal_id
    match args.command:
        case "coverage":
            return _coverage(engine, principal_id, args)
        case "aggregate":
            return _aggregate(engine, principal_id, args)
        case "rederive":
            return _rederive(engine, settings, principal_id, args)
        case "measure-fts":
            return _measure_fts(engine, principal_id, args)
    lifecycle = ingestion_lifecycle(settings, engine)
    match args.command:
        case "admit":
            source = lifecycle.admit(
                principal_id,
                consumer=IngestConsumer(args.consumer),
                workspace_id=args.workspace,
                path_prefix=args.path_prefix,
                file_pattern=args.file_pattern,
                enabled=not args.disabled,
            )
            _emit(
                {
                    "command": "admit",
                    "ingest_source_id": source.ingest_source_id,
                    "consumer": source.consumer.value,
                    "enabled": source.enabled,
                }
            )
            return EXIT_OK
        case "enable" | "disable":
            lifecycle.set_enabled(principal_id, args.source, args.command == "enable")
            _emit(
                {
                    "command": args.command,
                    "ingest_source_id": args.source,
                    "enabled": args.command == "enable",
                }
            )
            return EXIT_OK
        case "run-once":
            return _run_and_apply(
                engine,
                "run-once",
                principal_id,
                lambda: lifecycle.run_once(principal_id, args.source),
            )
        case "backfill":
            paths = None
            if args.file is not None:
                paths = _backfill_paths(
                    _require_source(engine, principal_id, args.source).path_prefix, args.file
                )
            if args.dry_run:  # writes nothing, so it takes no lock
                return _run_report(
                    "backfill",
                    lifecycle.backfill(
                        principal_id, args.source, paths=paths, name_pattern=args.glob, dry_run=True
                    ),
                )
            return _run_and_apply(
                engine,
                "backfill",
                principal_id,
                lambda: lifecycle.backfill(
                    principal_id, args.source, paths=paths, name_pattern=args.glob
                ),
            )
        case unknown:  # pragma: no cover - argparse rejects an unknown command first
            raise SystemExit(f"unhandled command {unknown!r}")


def _require_source(engine: Engine, principal_id: str, source_id: str) -> IngestSourceRecord:
    """The admitted source, or the refusal `source_not_found` (its prefix is never printed)."""
    with ingest_unit_of_work(engine)() as unit:
        source = unit.ingestion.get_source(principal_id, source_id)
    if source is None:
        raise _RefusalError("source_not_found")
    return source


@contextmanager
def _poll_lock(engine: Engine) -> Iterator[None]:
    """Hold the poll's advisory lock for the run, or refuse `lock_held` without waiting."""
    with single_flight(engine, key=COMMS_INGEST_LOCK_KEY) as held:
        if not held:
            raise _RefusalError("lock_held")
        yield


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


def _bounded(maximum: int) -> Callable[[str], int]:
    def parse(value: str) -> int:
        try:
            number = int(value)
        except ValueError:
            raise argparse.ArgumentTypeError("an integer") from None
        if not 1 <= number <= maximum:
            raise argparse.ArgumentTypeError(f"between 1 and {maximum}")
        return number

    return parse


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="communications_ingest",
        description="Admit, run, backfill and monitor communications ingest sources.",
    )
    parser.add_argument("--expected-database", required=True)
    parser.add_argument("--expected-alembic-head", required=True)
    commands = parser.add_subparsers(dest="command", required=True)

    admit = commands.add_parser("admit", help="admit one ingest source")
    admit.add_argument("--consumer", required=True, choices=[c.value for c in IngestConsumer])
    admit.add_argument("--workspace", required=True)
    admit.add_argument("--path-prefix", required=True)
    admit.add_argument("--file-pattern", required=True)
    admit.add_argument("--disabled", action="store_true", help="admit with polling off")

    for name, text_help in (
        ("enable", "turn a source's scheduled polling on"),
        ("disable", "turn a source's scheduled polling off"),
        ("run-once", "run the poll step once over an enabled source (trigger operator)"),
    ):
        command = commands.add_parser(name, help=text_help)
        command.add_argument("--source", required=True)

    backfill = commands.add_parser("backfill", help="backfill files (trigger backfill)")
    backfill.add_argument("--source", required=True)
    chosen = backfill.add_mutually_exclusive_group()
    chosen.add_argument("--file", action="append", metavar="NAME")
    chosen.add_argument("--glob", metavar="PATTERN")
    backfill.add_argument("--dry-run", action="store_true")

    coverage = commands.add_parser("coverage", help="coverage, gaps, freshness, rolling 30 days")
    coverage.add_argument("--source", required=True)
    coverage.add_argument("--from", dest="range_from", metavar="ISO8601")
    coverage.add_argument("--to", dest="range_to", metavar="ISO8601")

    aggregate = commands.add_parser("aggregate", help="corpus counts over one or more sources")
    aggregate.add_argument("--source", required=True, action="append")

    rederive = commands.add_parser(
        "rederive", help="re-derive stored messages to the current text and identifier versions"
    )
    rederive.add_argument("--source")
    rederive.add_argument(
        "--limit", type=_bounded(MAX_REDERIVE_LIMIT), default=DEFAULT_REDERIVE_LIMIT
    )
    rederive.add_argument("--dry-run", action="store_true")

    measure = commands.add_parser(
        "measure-fts", help="counts only: english against simple over stored messages"
    )
    measure.add_argument("--source")
    measure.add_argument("--limit", type=_bounded(MAX_MEASURE_LIMIT), default=DEFAULT_MEASURE_LIMIT)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "coverage" and (args.range_from is None) != (args.range_to is None):
        parser.error("--from and --to go together")
    try:
        return _run(args)
    except _RefusalError as refusal:
        _emit({"command": args.command, "refused": refusal.code})
    except IngestRefusedError as refusal:
        _emit({"command": args.command, "refused": refusal.code.value})
    except FileWorkspaceRootError:
        _emit({"command": args.command, "refused": "workspace_misconfigured"})
    except OperationalError:
        _emit({"command": args.command, "refused": "database_unreachable"})
    except SQLAlchemyError:
        _emit({"command": args.command, "refused": "database_unavailable"})
    return EXIT_REFUSED


if __name__ == "__main__":
    sys.exit(main())
