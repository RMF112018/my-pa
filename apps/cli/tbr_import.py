"""Command line for the legacy TBR Constraints register import.

    .venv/bin/python apps/cli/tbr_import.py dry-run \
        --source <path> --sheet <name> --project-id prj_… --principal prn_… \
        --register-id <token> --output <dir>
    .venv/bin/python apps/cli/tbr_import.py apply-disposable \
        --source <path> --sheet <name> --project-id prj_… --principal prn_… \
        --register-id <token> --output <dir> --confirm-disposable-target <database>

Argparse, like every other operational script in this repository.

**There are two subcommands and there will not be a third here.** A real TBR
apply and a cutover are not authorised, so no code path, flag, constant or
default in this program names a real target, a live workbook, a SharePoint
location or a connector. `apply-disposable` refuses any database whose name is
not one the test provisioning vocabulary produces, and refuses even that unless
the operator repeats the name back in `--confirm-disposable-target`.
`tests/architecture/test_tbr_import_has_no_cutover_path.py` is what holds that,
because a rule stated only in a docstring is not a control.

Two rules this obeys, from `AGENTS.md` section 5. Targets are always explicit:
`--source`, `--sheet`, `--project-id`, `--principal` and `--register-id` are all
required, there is no default for any of them, and the database comes from
`MY_PA_DATABASE_URL`, so none of them can be inferred. And output carries
counts, identifiers, codes, prefixes and stable issue codes — never a workbook
value, never a description, comment, party label, closure note or void reason,
and never the source path in a form that would end up in an evidence file.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from sqlalchemy import URL

from my_pa.application.constraint_legacy_import import (
    ConstraintLegacyImportService,
    ImportDisposition,
    ImportReport,
    LegacyImportError,
    render_markdown,
    report_as_dict,
)
from my_pa.bootstrap.settings import load_settings
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.ooxml_worksheet_reader import OoxmlWorkbookSource, WorkbookSourceError
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)

EXIT_OK: Final = 0
EXIT_FAILED: Final = 1

#: The disposable catalog vocabulary, restated rather than imported: the test
#: provisioning helper that produces these names is test code, and an operator
#: program that imported it would put the test tree on the runtime import path.
#: `test_tbr_import_has_no_cutover_path.py` proves the two agree by generating a
#: name with that helper and matching it here.
DISPOSABLE_DATABASE_PATTERN: Final = re.compile(
    r"^my_pa_p_[tce]_[a-z0-9]{1,16}_[a-z0-9]{1,16}(_[0-9]{1,8})?$"
)

#: A register identity is an operator-chosen bounded token, not a path and not a
#: file name: it is composed into a stored idempotency key, so it must be stable
#: across runs and must carry nothing personal.
REGISTER_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{2,63}$")


def is_disposable_database(name: str | None) -> bool:
    """Whether `name` is a catalog the disposable provisioning vocabulary makes."""
    return name is not None and DISPOSABLE_DATABASE_PATTERN.fullmatch(name) is not None


#: The bound one import batch runs under. Explicit, and a bound rather than an
#: exemption: this program reads and writes a synthetic register of bounded size,
#: so nothing here is sized to a corpus the way the legacy migration loader is.
STATEMENT_TIMEOUT_MS: Final = 30_000


def _service(url: URL) -> ConstraintLegacyImportService:
    engine = create_database_engine(url, statement_timeout_ms=STATEMENT_TIMEOUT_MS)
    return ConstraintLegacyImportService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(engine),
        clock=lambda: datetime.now(UTC),
    )


def _reader(args: argparse.Namespace) -> OoxmlWorkbookSource:
    return OoxmlWorkbookSource(Path(args.source), sheet_name=args.sheet)


def _party_map(path: Path | None) -> dict[str, str]:
    """The operator's explicit source-wording to `ent_` map, or an empty one.

    Explicit and exact. There is no fuzzy match, no substring rule and no name
    or address heuristic anywhere in this program: a party the operator has not
    named stays UNRESOLVED, carrying its own source wording.
    """
    if path is None:
        return {}
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise LegacyImportError("party_map_shape", "a party map is an object of wording to ent_ id")
    mapping: dict[str, str] = {}
    for wording, entity_id in document.items():
        if not isinstance(wording, str) or not isinstance(entity_id, str):
            raise LegacyImportError("party_map_shape", "a party map maps text to an ent_ id")
        validate_identifier(entity_id, IdKind.ENTITY)
        mapping[wording] = entity_id
    return mapping


def _write(report: ImportReport, output: Path) -> None:
    output.mkdir(parents=True, exist_ok=True)
    (output / "tbr-import.json").write_text(
        json.dumps(report_as_dict(report), indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    (output / "TBR-IMPORT.md").write_text(render_markdown(report), encoding="utf-8")


def _summarise(report: ImportReport) -> None:
    print(f"mode         {report.mode}")
    print(f"source       {report.source_digest}")
    print(f"rows         {report.total_source_rows}")
    for name, count in sorted(report.class_counts.items()):
        print(f"class        {name:<24s} {count}")
    print(f"inserts      {report.planned_inserts}")
    print(f"applied      {report.applied}")
    print(f"replayed     {report.replayed}")
    for blocker in report.blockers:
        print(f"blocker      {blocker}")
    print(f"disposition  {report.disposition.value}")


def _dry_run(args: argparse.Namespace) -> int:
    """Read everything, decide everything, write nothing to the database."""
    _check_identifiers(args)
    settings = load_settings()
    outcome = _service(settings.parsed_database_url()).dry_run(
        principal_id=args.principal,
        project_id=args.project_id,
        register_id=args.register_id,
        reader=_reader(args),
        party_map=_party_map(args.party_map),
    )
    _write(outcome.report, Path(args.output))
    _summarise(outcome.report)
    return EXIT_OK if outcome.report.disposition is ImportDisposition.READY else EXIT_FAILED


def _apply_disposable(args: argparse.Namespace) -> int:
    """Write the import, and only ever into a database the vocabulary calls disposable."""
    _check_identifiers(args)
    settings = load_settings()
    url = settings.parsed_database_url()
    name = url.database
    if not is_disposable_database(name):
        print("refusing: the configured database is not a disposable target", file=sys.stderr)
        return EXIT_FAILED
    if args.confirm_disposable_target != name:
        print(
            "refusing: --confirm-disposable-target does not match the configured database",
            file=sys.stderr,
        )
        return EXIT_FAILED
    outcome = _service(url).apply_disposable(
        principal_id=args.principal,
        project_id=args.project_id,
        register_id=args.register_id,
        reader=_reader(args),
        party_map=_party_map(args.party_map),
    )
    _write(outcome.report, Path(args.output))
    _summarise(outcome.report)
    return EXIT_OK


def _check_identifiers(args: argparse.Namespace) -> None:
    validate_identifier(args.principal, IdKind.PRINCIPAL)
    validate_identifier(args.project_id, IdKind.PROJECT)
    if REGISTER_ID_PATTERN.fullmatch(args.register_id) is None:
        raise LegacyImportError(
            "register_id_shape", "a register identity is 3-64 characters of [A-Za-z0-9_-]"
        )


def _common(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--source", required=True, help="path to the source workbook package")
    parser.add_argument("--sheet", required=True, help="the worksheet to read, by name")
    parser.add_argument("--project-id", required=True, help="the canonical prj_ identity")
    parser.add_argument("--principal", required=True, help="the owning prn_ identity")
    parser.add_argument("--register-id", required=True, help="a stable source register token")
    parser.add_argument("--output", required=True, type=Path, help="directory for the report")
    parser.add_argument(
        "--party-map",
        type=Path,
        default=None,
        help="optional JSON map of exact source wording to an ent_ identity",
    )


def build_parser() -> argparse.ArgumentParser:
    """The two subcommands. No default source, no default target, no third mode."""
    parser = argparse.ArgumentParser(
        prog="tbr_import", description="Legacy TBR Constraint register import (dry run and apply)"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    _common(subparsers.add_parser("dry-run", help="report only; writes nothing"))
    apply_parser = subparsers.add_parser(
        "apply-disposable", help="write into a disposable database, named twice"
    )
    _common(apply_parser)
    apply_parser.add_argument(
        "--confirm-disposable-target",
        required=True,
        help="repeat the configured disposable database name",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    handlers = {"dry-run": _dry_run, "apply-disposable": _apply_disposable}
    try:
        return handlers[args.command](args)
    except (LegacyImportError, WorkbookSourceError) as error:
        print(f"failed: {error.code}", file=sys.stderr)
        return EXIT_FAILED
    except InvalidIdentifierError:
        print("failed: identifier_invalid", file=sys.stderr)
        return EXIT_FAILED


if __name__ == "__main__":
    raise SystemExit(main())
