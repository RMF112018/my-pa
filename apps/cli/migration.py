"""Command line for the legacy-SQLite to PostgreSQL migration.

    .venv/bin/python apps/cli/migration.py init-run --source <path>
    .venv/bin/python apps/cli/migration.py status   --run-id <id>
    .venv/bin/python apps/cli/migration.py load     --run-id <id> --source <path> --phase PHASE-03
    .venv/bin/python apps/cli/migration.py resume   --run-id <id> --source <path>
    .venv/bin/python apps/cli/migration.py dry-run  --run-id <id> --source <path> --phase PHASE-03
    .venv/bin/python apps/cli/migration.py validate-foreign-keys

Argparse, like every other operational script in this repository. A second CLI
framework would be a dependency bought to save a dozen lines.

Two rules this obeys, from `AGENTS.md` section 5. Targets are always explicit:
`--source` is required wherever the source is read, and the database comes from
`MY_PA_DATABASE_URL`, so neither can be inferred. And output carries counts,
table names, states, and codes — never a row value, and never the source path
in a form that would end up in an evidence file.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from sqlalchemy import Engine

from my_pa.bootstrap.settings import load_settings
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.migration import binding, constraints, loader, runs
from my_pa.infrastructure.migration.reader import DEFAULT_BATCH_SIZE
from my_pa.infrastructure.migration.source import load_registry

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_REGISTRY = REPOSITORY_ROOT / "migrations" / "data" / "disposition_registry.json"

#: OD-007. The domain schemas the migration owns.
DOMAIN_SCHEMAS = (
    "core",
    "procore",
    "email",
    "calendar",
    "contacts",
    "financial",
    "schedule",
    "construction",
)


def _engine() -> Engine:
    """The engine every subcommand here runs on.

    **No `statement_timeout`, deliberately.** This CLI loads and verifies a
    4.37 GB legacy corpus: a batch insert, a `COUNT(*)` over a fully populated
    domain table, and the constraint checks that follow one are statements sized
    to the corpus rather than to a request. Bounding them would convert a slow
    load into a failed one. The gateway, the source CLI, the health probe and the
    worker all pass `MY_PA_STATEMENT_TIMEOUT_MS`; this is one of the three places
    that must not.
    """
    # statement-timeout-exempt: bulk corpus load, sized to the corpus.
    return create_database_engine(load_settings().database_url)


def _init_run(args: argparse.Namespace) -> int:
    engine = _engine()
    try:
        with engine.begin() as connection:
            observed = binding.observe(args.source, connection)
            run_id = runs.create_run(connection, observed, dry_run=args.dry_run)
    finally:
        engine.dispose()
    print(f"run_id                 {run_id}")
    print(f"source_sha256          {observed.source_sha256}")
    print(f"source_bytes           {observed.source_bytes}")
    print(f"source_schema_version  {observed.source_schema_version}")
    print(f"target_revision        {observed.target_alembic_revision}")
    print(f"dry_run                {args.dry_run}")
    return 0


def _status(args: argparse.Namespace) -> int:
    engine = _engine()
    try:
        with engine.connect() as connection:
            summary = runs.summarise(connection, args.run_id)
    finally:
        engine.dispose()

    print(f"run_id      {summary.run.run_id}")
    print(f"status      {summary.run.status.value}")
    print(f"dry_run     {summary.run.dry_run}")
    print(f"source_sha  {summary.run.binding_sha256}")
    print(f"schema      {summary.run.binding_schema_version}")
    print(f"revision    {summary.run.binding_revision}")
    print(f"rows loaded {summary.rows_loaded}")
    for state, count in summary.tables_by_state:
        print(f"  tables {state:<10s} {count}")
    for phase in summary.phases:
        print(
            f"  {phase.phase:<10s} {phase.status.value:<10s} "
            f"tables {phase.tables_completed}/{phase.tables_total} "
            f"rows {phase.rows_ok} quarantined {phase.rows_quarantined}"
        )
    for code, count in summary.quarantine_by_code:
        print(f"  quarantine {code:<24s} {count}")
    return 0


def _report(outcome: loader.LoadOutcome) -> int:
    for table in outcome.tables:
        state = "skipped" if table.skipped else f"{table.loaded}/{table.source_rows}"
        print(
            f"  {table.phase:<10s} {table.legacy_table:<60s} {state:>18s} "
            f"quarantined {table.quarantined}"
        )
    print(f"tables      {len(outcome.tables)}")
    print(f"rows loaded {outcome.loaded}")
    print(f"quarantined {outcome.quarantined}")
    for code, count in sorted(outcome.quarantine_by_code.items()):
        print(f"  {code:<24s} {count}")
    if outcome.dry_run:
        print("dry run: nothing was committed")
    return 0


def _load(args: argparse.Namespace, *, dry_run: bool) -> int:
    registry = load_registry(args.registry)
    engine = _engine()
    try:
        outcome = loader.load(
            engine,
            args.source,
            registry,
            args.run_id,
            phases=args.phase or None,
            tables=args.table or None,
            batch_size=args.batch_size,
            dry_run=dry_run,
        )
    finally:
        engine.dispose()
    return _report(outcome)


def _resume(args: argparse.Namespace) -> int:
    registry = load_registry(args.registry)
    engine = _engine()
    try:
        with engine.connect() as connection:
            phases = runs.open_phases(connection, args.run_id)
        if not phases:
            print("nothing to resume: every started phase is complete")
            return 0
        print(f"resuming {', '.join(phases)}")
        outcome = loader.load(
            engine,
            args.source,
            registry,
            args.run_id,
            phases=phases,
            batch_size=args.batch_size,
        )
    finally:
        engine.dispose()
    return _report(outcome)


def _validate_foreign_keys(args: argparse.Namespace) -> int:
    engine = _engine()
    try:
        outcomes = constraints.validate_foreign_keys(engine, DOMAIN_SCHEMAS)
    finally:
        engine.dispose()

    failed = [outcome for outcome in outcomes if not outcome.validated]
    for outcome in failed:
        print(
            f"  NOT VALID {outcome.schema}.{outcome.table} {outcome.constraint} "
            f"-> {outcome.referenced} orphans {outcome.orphan_rows} ({outcome.error_class})"
        )
    print(f"foreign keys  {len(outcomes)}")
    print(f"validated     {len(outcomes) - len(failed)}")
    print(f"left NOT VALID {len(failed)}")
    print(f"orphan rows   {sum(outcome.orphan_rows for outcome in failed)}")
    # A left-unenforced constraint is a reported fact about the source, not a
    # failure of this command.
    return 0


def _source_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--source", type=Path, required=True, help="path to the legacy SQLite database"
    )


def _run_argument(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--run-id", required=True, help="the run to act on")


def _load_arguments(parser: argparse.ArgumentParser) -> None:
    _run_argument(parser)
    _source_argument(parser)
    parser.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="migration", description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)

    init = commands.add_parser("init-run", help="bind a new run to the source and target")
    _source_argument(init)
    init.add_argument("--dry-run", action="store_true", help="record the run as a dry run")

    status = commands.add_parser("status", help="report a run's progress")
    _run_argument(status)

    load = commands.add_parser("load", help="load one or more phases")
    _load_arguments(load)
    load.add_argument("--phase", action="append", help="repeatable; defaults to every phase")
    load.add_argument("--table", action="append", help="repeatable; restricts to named tables")

    resume = commands.add_parser("resume", help="continue every phase that is not complete")
    _run_argument(resume)
    _source_argument(resume)
    resume.add_argument("--registry", type=Path, default=DEFAULT_REGISTRY)
    resume.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)

    dry = commands.add_parser("dry-run", help="transform and count, committing nothing")
    _load_arguments(dry)
    dry.add_argument("--phase", action="append", help="repeatable; defaults to every phase")
    dry.add_argument("--table", action="append", help="repeatable; restricts to named tables")

    commands.add_parser(
        "validate-foreign-keys",
        help="validate the NOT VALID foreign keys, reporting orphan counts (OD-017)",
    )

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    match args.command:
        case "init-run":
            return _init_run(args)
        case "status":
            return _status(args)
        case "load":
            return _load(args, dry_run=False)
        case "dry-run":
            return _load(args, dry_run=True)
        case "resume":
            return _resume(args)
        case "validate-foreign-keys":
            return _validate_foreign_keys(args)
        case unknown:  # pragma: no cover - argparse rejects an unknown command first
            raise SystemExit(f"unhandled command {unknown!r}")


if __name__ == "__main__":
    sys.exit(main())
