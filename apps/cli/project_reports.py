"""Operator command for project-report bindings (WP3P-S4; rulings D5-D8, D19; plan 6.4).

```text
python apps/cli/project_reports.py <assertions> bindings check --file F
python apps/cli/project_reports.py <assertions> bindings apply --file F --reason CODE
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
operator_cli`) and the Principal is the fixed local operator
(`bootstrap.gateway.local_principal`), never an argument. The bindings service,
the project-reports lifecycle (which alone admits `pulse_csv_export`), the
read-only workspace stores (from `MY_PA_FILES_WORKSPACES`) and the poll lock
are composed by `bootstrap.project_reports`.

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
  writes nothing the second time. `--reason` is the operator's closed code for
  the change set (the `BindingReason` vocabulary). It is checked and echoed;
  each revision records the reason its own change kind names (`initial`,
  `add`, `correction`, `filter_update` or `retire`), so a file mixing an add
  and a retire cannot record either one under the other's reason.

**Output is one JSON object on standard output: closed codes, counts and
project numbers only** -- never the database URL, a path, a folder, a file
name, a slug, a filter description or any file content. A refusal is
`{"command": ..., "refused": CODE}` with a closed `CODE`.

Exit status (closed):

| exit | meaning |
| --- | --- |
| `0` | done: `check` validated the file; `apply` applied it or found nothing to change |
| `1` | refused, with one closed code (below); nothing was written |
| `2` | usage error (argparse) |
| `3` | reserved for the S5 run commands (`partial` or `failed`); never a bindings exit |

Refusal codes: the `BindingRefusal` values (`file_unreadable`,
`schema_invalid`, `unknown_key`, `duplicate_json_key`, `project_not_found`,
`project_number_mismatch`, `project_has_no_number`, `folder_duplicated`,
`folder_nested`, `project_duplicated`, `folder_outside_export_root`,
`folder_not_found`, `currency_invalid`, `filter_description_invalid`,
`lock_held`); the lifecycle's `IngestRefusalCode` values; and
`target_mismatch`, `settings_invalid`, `workspace_misconfigured`,
`transaction_conflict`, `write_refused` (a database guard refused a write),
`database_unreachable` and `database_unavailable`.

**Extension points (slice S5).** `run-once`, `backfill`, `rederive`, `coverage`
and `aggregate` join as further top-level commands beside `bindings` in
`build_parser` and `_dispatch`, with the exit `3` meaning above; they reuse the
same assertions, engine and refusal mapping.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Final

from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import OperationalError, ProgrammingError, SQLAlchemyError

from my_pa.application.ingestion import IngestRefusedError
from my_pa.application.project_reports_bindings import BindingsReport
from my_pa.bootstrap.gateway import local_principal
from my_pa.bootstrap.project_reports import bindings_service
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.contracts.ports import (
    FileWorkspaceRootError,
    ProjectReportsWriteRefusedError,
    TransactionConflictError,
)
from my_pa.domain.project_reports.bindings import BindingsRefusedError
from my_pa.domain.project_reports.model import BindingReason, BindingRefusal
from my_pa.infrastructure.database.engine import create_database_engine

__all__ = [
    "EXIT_OK",
    "EXIT_REFUSED",
    "EXIT_RUN_INCOMPLETE",
    "MAX_FILE_BYTES",
    "build_parser",
    "main",
]

EXIT_OK: Final = 0
EXIT_REFUSED: Final = 1
#: Reserved for the S5 run commands; no bindings command returns it.
EXIT_RUN_INCOMPLETE: Final = 3

#: The statement bound every engine here runs under (the engine-bounded guard).
STATEMENT_TIMEOUT_MS: Final = 60_000
#: The largest bindings file read; a larger one is `file_unreadable`.
MAX_FILE_BYTES: Final = 1024 * 1024


class _RefusalError(Exception):
    """A refusal with a closed code; the code is the whole answer."""

    def __init__(self, code: str) -> None:
        super().__init__(code)
        self.code = code


def _emit(fields: dict[str, object]) -> None:
    print(json.dumps(fields, sort_keys=True), flush=True)


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


def _read_file(path: str) -> bytes:
    """The bindings file's bytes, or `file_unreadable` (the path is never printed)."""
    try:
        with Path(path).open("rb") as handle:
            data = handle.read(MAX_FILE_BYTES + 1)
    except OSError:
        raise _RefusalError(BindingRefusal.FILE_UNREADABLE.value) from None
    if len(data) > MAX_FILE_BYTES:
        raise _RefusalError(BindingRefusal.FILE_UNREADABLE.value)
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


def _dispatch(engine: Engine, settings: Settings, args: argparse.Namespace) -> int:
    principal_id = local_principal().principal_id
    data = _read_file(args.file)
    service = bindings_service(settings, engine)
    command = _command(args)
    match args.action:
        case "check":
            _emit(_report_fields(command, service.check(principal_id, data)))
        case "apply":
            fields = _report_fields(command, service.apply(principal_id, data))
            fields["reason"] = args.reason
            _emit(fields)
        case unknown:  # pragma: no cover - argparse rejects an unknown action first
            raise SystemExit(f"unhandled action {unknown!r}")
    return EXIT_OK


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
        description="Check and apply the operator's project-report bindings file.",
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
    apply.add_argument("--reason", required=True, choices=[r.value for r in BindingReason])
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
