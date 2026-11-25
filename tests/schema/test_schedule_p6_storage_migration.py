"""P6 XER import S7-2: the schedule P6 storage revision, `d8383150cf72`.

`d8383150cf72` is additive on `0d4e247d03cb` (project reports WP3P-S3) and is
the one migration of the P6 XER import (schedule XER import contract sections
6, 7.3, 7.4, 8, 11.1 and 13; ADR-023). This module proves:

* **the graph** -- this revision, directly on `0d4e247d03cb`, on the one chain;
* **the freeze** -- the revision imports nothing from the package it migrates;
  its typed column lists are the S7-1 catalogue's R and T fields (types, NOT
  NULL, bounds); its issue-code blocks are the domain's; its F3/F6/F9 BEFORE
  bodies are byte copies of `6c2306330ceb`'s; on a live server the catalog it
  builds equals the catalog `tables.py` builds for every new and altered table;
* **the audit vocabulary** -- the BEFORE texts are byte copies of the latest
  prior restatements and the AT texts add exactly the S7-4 capability and purpose
  names of contract section 10.1, admitted ahead of the domain;
* **offline SQL** for both directions, without a server;
* on disposable databases: up/down/up; an existing PDF publication survives
  the upgrade unchanged; the publication CHECK matrix; every new foreign key
  restricts; append-only, TRUNCATE, per-run insert, activity link and capture
  chain triggers; a P6 publication reaches `complete`, `review_required` and
  `failed` through the restated F3/F6/F9 and nowhere else; the downgrade
  refusals, each clause alone.

The file name routes every test here to migration-edge (`tests/db/fixtures.py`);
the tests with no `database` marker also run in FAST. Every value is synthetic.
"""

from __future__ import annotations

import ast
import hashlib
import io
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, MetaData, Table, insert, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from tests.schema.vocabulary_admissions import admitted_ahead_of_the_domain

from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.schedule import ScheduleIssueCode
from my_pa.domain.schedule.p6.catalogue import ValueType
from my_pa.domain.schedule.p6.model import FATAL_CODES, P6IssueCode
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence import tables
from my_pa.infrastructure.persistence.tables import audit_events, p6_typed_fields

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "d8383150cf72"
PREVIOUS: Final = "0d4e247d03cb"
MIGRATIONS: Final = ROOT / "migrations" / "versions"
MIGRATION: Final = MIGRATIONS / "20261125_d8383150cf72_schedule_p6_xer_storage.py"
FOUNDATION: Final = MIGRATIONS / "20261027_6c2306330ceb_cpm_workbench_foundation.py"
PRIOR_CAPABILITIES: Final = MIGRATIONS / "20261123_61fafdfd2986_meeting_sync_staging.py"
PRIOR_PURPOSES: Final = MIGRATIONS / "20261113_640aaacc78e8_files_workspace.py"

NEW_TABLES: Final = (
    "schedule_p6_snapshots",
    "schedule_p6_capture_events",
    "schedule_p6_projects",
    "schedule_p6_wbs",
    "schedule_p6_activities",
    "schedule_p6_relationships",
    "schedule_p6_calendars",
    "schedule_p6_field_values",
    "schedule_p6_observed_fields",
)
PER_RUN_TABLES: Final = NEW_TABLES[2:]
ALTERED_TABLES: Final = ("schedule_publications", "schedule_parser_runs", "schedule_import_issues")
NEW_CAPABILITIES: Final = frozenset(
    {
        "schedule_publications.import_p6",
        "schedule_p6_fields.available",
        "schedule_p6_fields.set_captured",
        "schedule_p6_activities.list",
        "schedule_p6_relationships.list",
        "schedule_p6_calendars.list",
        "schedule_p6_field_values.list",
    }
)
NEW_PURPOSES: Final = frozenset({"schedule_p6_import", "schedule_p6_configuration"})

P: Final = "prn_sp6mig0001aaaa"
PROJECT: Final = "prj_sp6mig0001aaaa"
SERIES: Final = "sser_sp6mig0001aaaa"
CONTENT: Final = b"ERMHDR\t26.4\t2026-11-25\n%T\tPROJECT\n%E\n"
SHA: Final = hashlib.sha256(CONTENT).hexdigest()
FRAME: Final = "f" * 64
WHEN: Final = datetime(2026, 11, 25, 12, tzinfo=UTC)
_WHITESPACE: Final = re.compile(r"\s+")

RESTRICT_VIOLATION: Final = "23001"
CHECK, UNIQUE, FOREIGN = "23514", "23505", "23503"


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def _offline(target: str, *, down: bool = False) -> str:
    buffer = io.StringIO()
    action = command.downgrade if down else command.upgrade
    action(_config(buffer), target, sql=True)
    return _WHITESPACE.sub(" ", buffer.getvalue())


def _source() -> str:
    return MIGRATION.read_text(encoding="utf-8")


def _namespace(path: Path) -> dict[str, Any]:
    namespace: dict[str, Any] = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)  # noqa: S102
    return namespace


def _literals(expression: object) -> list[str]:
    assert isinstance(expression, str)
    return re.findall(r"'([^']+)'", expression)


# ---- the graph --------------------------------------------------------------


def test_the_revision_is_directly_on_the_project_report_revision_on_the_one_chain() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    heads = script.get_heads()
    assert len(heads) == 1
    assert REVISION in {revision.revision for revision in script.walk_revisions("base", heads[0])}


# ---- the freeze -------------------------------------------------------------


def test_revision_imports_no_domain_or_persistence_modules() -> None:
    source = _source()
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__", "typing"}
    assert "my_pa" not in source
    assert "create_all" not in source


def test_the_revision_creates_exactly_the_nine_tables_in_order() -> None:
    created = re.findall(r"CREATE TABLE knowledge\.(\w+) \(", _source())
    assert tuple(created) == NEW_TABLES
    assert {f"{SCHEMA}.{name}" for name in NEW_TABLES} <= set(tables.METADATA.tables)


_SQL_TYPES: Final = {
    ValueType.ID: "BIGINT",
    ValueType.INT: "BIGINT",
    ValueType.HOURS: "NUMERIC(21, 6)",
    ValueType.NUM: "NUMERIC(21, 6)",
    ValueType.FLAG: "BOOLEAN",
    ValueType.TS: "TIMESTAMP WITHOUT TIME ZONE",
    ValueType.TEXT: "TEXT",
    ValueType.NAME: "TEXT",
    ValueType.ENUM: "TEXT",
}


@pytest.mark.parametrize(
    ("constant", "xer_tables"),
    [
        ("_PROJECT_COLUMNS", ("PROJECT", "SCHEDOPTIONS")),
        ("_WBS_COLUMNS", ("PROJWBS",)),
        ("_ACTIVITY_COLUMNS", ("TASK",)),
        ("_RELATIONSHIP_COLUMNS", ("TASKPRED",)),
        ("_CALENDAR_COLUMNS", ("CALENDAR",)),
    ],
)
def test_the_frozen_typed_columns_are_the_catalogues(
    constant: str, xer_tables: tuple[str, ...]
) -> None:
    """Contract section 6, row for row: S7-1 is the typed source of the columns."""
    frozen = _namespace(MIGRATION)[constant]
    expected = tuple(
        (
            field.typed_column,
            _SQL_TYPES[field.value_type],
            field.required and not field.empty_allowed,
            "token"
            if field.value_type is ValueType.ENUM
            else field.max_characters
            if field.value_type in {ValueType.TEXT, ValueType.NAME}
            else None,
        )
        for field in p6_typed_fields(*xer_tables)
    )
    assert frozen == expected


def test_the_frozen_issue_codes_are_the_domains() -> None:
    module = _namespace(MIGRATION)
    p6 = sorted(code.value for code in P6IssueCode)
    assert _literals(module["_PDF_ISSUE_CODES"]) == sorted(c.value for c in ScheduleIssueCode)
    assert _literals(module["_P6_ISSUE_CODES"]) == p6
    assert len(p6) == 24
    fatal = sorted(code.value for code in FATAL_CODES)
    either = sorted({P6IssueCode.UNKNOWN_ENUM_VALUE.value, P6IssueCode.VALUE_INVALID.value})
    assert _literals(module["_P6_FATAL_CODES"]) == fatal
    assert _literals(module["_P6_EITHER_CODES"]) == either
    assert _literals(module["_P6_WARNING_CODES"]) == sorted(set(p6) - set(fatal) - set(either))


def test_the_restated_functions_restore_byte_copies_of_the_foundation() -> None:
    mine = _namespace(MIGRATION)
    foundation = {name: body for name, _sig, body in _namespace(FOUNDATION)["_FUNCTIONS"]}
    for constant, name in (
        ("_F3_BEFORE", "a_schedule_publication_follows_its_lifecycle"),
        ("_F6_BEFORE", "a_schedule_parser_run_follows_its_lifecycle"),
        ("_F9_BEFORE", "schedule_run_outcome"),
    ):
        assert mine[constant] == foundation[name].replace(
            "CREATE FUNCTION", "CREATE OR REPLACE FUNCTION"
        ), constant


def test_the_audit_before_texts_are_byte_copies_and_at_adds_exactly_the_new_names() -> None:
    mine = _namespace(MIGRATION)
    assert (
        mine["_CAPABILITIES_BEFORE_THIS_REVISION"]
        == _namespace(PRIOR_CAPABILITIES)["_CAPABILITIES_AT_THIS_REVISION"]
    )
    assert (
        mine["_PURPOSES_BEFORE_THIS_REVISION"]
        == _namespace(PRIOR_PURPOSES)["_PURPOSES_AT_THIS_REVISION"]
    )
    for before, at, new, counts in (
        (
            "_CAPABILITIES_BEFORE_THIS_REVISION",
            "_CAPABILITIES_AT_THIS_REVISION",
            NEW_CAPABILITIES,
            (312, 319),
        ),
        ("_PURPOSES_BEFORE_THIS_REVISION", "_PURPOSES_AT_THIS_REVISION", NEW_PURPOSES, (70, 72)),
    ):
        before_names = _literals(mine[before])
        at_names = _literals(mine[at])
        assert (len(before_names), len(at_names)) == counts
        assert at_names == sorted(at_names)
        assert set(at_names) - set(before_names) == new
    assert set(mine["_NEW_CAPABILITIES"]) == NEW_CAPABILITIES
    assert set(mine["_NEW_PURPOSES"]) == NEW_PURPOSES


def test_the_new_names_are_admitted_ahead_of_the_domain() -> None:
    """S7-2 admits the S7-4 names; the domain declares none of them yet."""
    assert admitted_ahead_of_the_domain("capability") == NEW_CAPABILITIES
    assert admitted_ahead_of_the_domain("purpose") == NEW_PURPOSES
    assert not NEW_CAPABILITIES & {member.value for member in Capability}
    assert not NEW_PURPOSES & {member.value for member in Purpose}


def test_every_new_name_fits_a_postgresql_identifier() -> None:
    module = _namespace(MIGRATION)
    names = set(re.findall(r"CONSTRAINT (\w+)", _source()))
    names |= {name for name, _expression in module["_PUBLICATION_CHECKS"]}
    names |= {name for name, _expression in module["_ISSUE_CHECKS"]}
    names |= {trigger for trigger, _table, _definition in module["_triggers"]()}
    names |= {name for name, _definition in module["_FUNCTIONS"]}
    names |= set(re.findall(r"INDEX (\w+) ON", _source()))
    assert max(len(name) for name in names) <= 63, sorted(n for n in names if len(n) > 63)


# ---- offline SQL --------------------------------------------------------------


def test_the_offline_upgrade_locks_first_and_restates_the_vocabulary_last(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{PREVIOUS}:{REVISION}")
    timeout = rendered.index("SET LOCAL lock_timeout = '10s'")
    altered = rendered.index(
        "LOCK TABLE knowledge.schedule_publications, knowledge.schedule_parser_runs, "
        "knowledge.schedule_import_issues, knowledge.audit_events IN ACCESS EXCLUSIVE MODE"
    )
    referenced = rendered.index(
        "LOCK TABLE knowledge.schedule_series, knowledge.schedule_activities IN SHARE ROW "
        "EXCLUSIVE MODE"
    )
    first_ddl = rendered.index("CREATE TABLE knowledge.schedule_p6_snapshots")
    vocabulary = rendered.index("ADD CONSTRAINT capability_is_known")
    assert timeout < altered < referenced < first_ddl < vocabulary
    for table in NEW_TABLES:
        assert f"CREATE TABLE knowledge.{table} (" in rendered
    assert "GRANT" not in rendered and "REVOKE" not in rendered


def test_the_offline_downgrade_refuses_first_and_unwinds_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    refusal = rendered.index("refusing to downgrade d8383150cf72")
    first_drop = rendered.index("DROP CONSTRAINT purpose_is_known")
    assert rendered.index("SET LOCAL lock_timeout") < refusal < first_drop
    for table in NEW_TABLES:
        assert f"DROP TABLE knowledge.{table} RESTRICT" in rendered


# ---- disposable databases --------------------------------------------------------


@pytest.fixture
def engine(cloned_database_url: str) -> Iterator[Engine]:
    """A current-head clone, downgraded to this revision (a later one is unwound empty)."""
    built = create_database_engine(cloned_database_url)
    command.downgrade(_config(), REVISION)
    try:
        yield built
    finally:
        built.dispose()


_CATALOG: Final = {
    "columns": (
        "SELECT a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
        "pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a "
        "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
        "WHERE n.nspname = :schema AND c.relname = :table AND a.attnum > 0 "
        "AND NOT a.attisdropped"
    ),
    "constraints": (
        "SELECT c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace "
        "WHERE n.nspname = :schema AND r.relname = :table AND c.contype <> 't'"
    ),
    "indexes": (
        "SELECT indexname, indexdef FROM pg_indexes WHERE schemaname = :schema "
        "AND tablename = :table"
    ),
}


def _definitions(engine: Engine, schema: str, table: str) -> dict[str, list[tuple[str, ...]]]:
    with engine.connect() as connection:
        return {
            kind: sorted(
                tuple(
                    str(value).replace(f"{schema}.", "<schema>.").replace(f"{SCHEMA}.", "<schema>.")
                    for value in row
                )
                for row in connection.execute(text(query), {"schema": schema, "table": table})
            )
            for kind, query in _CATALOG.items()
        }


@pytest.mark.database
def test_the_revision_builds_exactly_the_catalog_tables_py_declares(engine: Engine) -> None:
    """Every column, constraint and index of the 9 new and 3 altered tables."""
    copies = MetaData()
    for live in ("projects", "enrollments", "enrollment_objects", "source_object_versions"):
        tables.METADATA.tables[f"{SCHEMA}.{live}"].to_metadata(copies)
    for live in ("sources", "source_objects"):
        tables.METADATA.tables[f"{SCHEMA}.{live}"].to_metadata(copies)
    declared = (
        *NEW_TABLES,
        *ALTERED_TABLES,
        "schedule_series",
        "schedule_activities",
        "schedule_jobs",
        "schedule_rows",
    )
    built = [
        tables.METADATA.tables[f"{SCHEMA}.{name}"].to_metadata(
            copies,
            schema="p6_parity",
            referred_schema_fn=lambda _t, _s, constraint, referred: (
                "p6_parity"
                if constraint.elements[0].target_fullname.split(".")[1].startswith("schedule_")
                else referred
            ),
        )
        for name in declared
    ]
    with engine.begin() as connection:
        connection.execute(text("CREATE SCHEMA p6_parity"))
        copies.create_all(connection, tables=built)
    try:
        for table in (*NEW_TABLES, *ALTERED_TABLES):
            migrated = _definitions(engine, SCHEMA, table)
            mirrored = _definitions(engine, "p6_parity", table)
            for kind in _CATALOG:
                assert migrated[kind] == mirrored[kind], (table, kind)
            assert migrated["constraints"], table
    finally:
        with engine.begin() as connection:
            connection.execute(text("DROP SCHEMA p6_parity CASCADE"))


def _present(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT tablename FROM pg_tables WHERE schemaname = 'knowledge' "
                    "AND tablename LIKE 'schedule_p6_%'"
                )
            ).scalars()
        )


@pytest.mark.database
def test_the_revision_round_trips_up_down_up(engine: Engine) -> None:
    assert _present(engine) == set(NEW_TABLES)
    command.downgrade(_config(), PREVIOUS)
    assert _present(engine) == set()
    with engine.connect() as connection:
        columns = set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns WHERE table_schema = "
                    "'knowledge' AND table_name = 'schedule_publications'"
                )
            ).scalars()
        )
        nullable = connection.execute(
            text(
                "SELECT is_nullable FROM information_schema.columns WHERE table_schema = "
                "'knowledge' AND table_name = 'schedule_parser_runs' AND column_name = "
                "'pdfium_version'"
            )
        ).scalar_one()
    assert "source_format" not in columns and "enrollment_id" in columns
    assert nullable == "NO"
    command.upgrade(_config(), REVISION)
    assert _present(engine) == set(NEW_TABLES)


@pytest.mark.database
def test_every_new_foreign_key_restricts(engine: Engine) -> None:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT r.relname, c.conname, c.confdeltype, c.confupdtype FROM pg_constraint c "
                "JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON "
                "n.oid = r.relnamespace WHERE n.nspname = 'knowledge' AND c.contype = 'f' AND "
                "(r.relname LIKE 'schedule_p6_%' OR c.conname IN "
                "('a_schedule_publication_names_a_snapshot_of_its_principal', "
                "'a_schedule_publication_names_a_capture_event_of_its_series'))"
            )
        ).all()
    assert len(rows) == 15
    for table, name, on_delete, on_update in rows:
        assert (on_delete, on_update) == ("r", "a"), (table, name)


# ---- seeding --------------------------------------------------------------------


def _base(
    c: Connection, *, principal: str = P, project: str = PROJECT, series: str = SERIES
) -> None:
    c.execute(
        text(
            "INSERT INTO knowledge.projects (project_id, principal_id, name, opened_at, "
            "created_at, updated_at) VALUES (:project, :p, 'Synthetic Project', now(), now(), "
            "now())"
        ),
        {"project": project, "p": principal},
    )
    c.execute(
        text(
            "INSERT INTO knowledge.schedule_series (series_id, principal_id, project_id, name, "
            "name_key) VALUES (:series, :p, :project, 'Synthetic', 'synthetic')"
        ),
        {"series": series, "p": principal, "project": project},
    )


def _snapshot(c: Connection, n: int = 1, content: bytes = CONTENT) -> str:
    snapshot = f"sp6n_sp6mig{n:04d}aaaa"
    c.execute(
        text(
            "INSERT INTO knowledge.schedule_p6_snapshots (snapshot_id, principal_id, format, "
            "size_bytes, sha256, content) VALUES (:s, :p, 'p6_xer', :size, :sha, :content)"
        ),
        {
            "s": snapshot,
            "p": P,
            "size": len(content),
            "sha": hashlib.sha256(content).hexdigest(),
            "content": content,
        },
    )
    return snapshot


def _p6_publication(n: int, snapshot: str, **overrides: object) -> dict[str, object]:
    values: dict[str, object] = {
        "publication_id": f"spub_sp6mig{n:04d}aaaa",
        "principal_id": P,
        "project_id": PROJECT,
        "series_id": SERIES,
        "idempotency_key": f"sp6-key-{n:04d}",
        "request_digest": SHA,
        "publication_role": "update",
        "source_format": "p6_xer",
        "p6_snapshot_id": snapshot,
        "p6_workspace_id": "projects",
        "p6_workspace_path": "schedules/synthetic.xer",
        "p6_workspace_version": "fv1_" + "0" * 64,
    }
    values.update(overrides)
    return values


def _admit(c: Connection, n: int = 1, *, snapshot: str | None = None, **overrides: object) -> str:
    values = _p6_publication(n, snapshot or _snapshot(c, n), **overrides)
    c.execute(insert(tables.schedule_publications).values(**values))
    c.execute(
        insert(tables.schedule_jobs).values(
            operation_id=f"op_sp6mig{n:04d}aaaa",
            publication_id=values["publication_id"],
            principal_id=P,
        )
    )
    return str(values["publication_id"])


def _process(c: Connection, publication: str, *, sha: str = SHA, size: int = len(CONTENT)) -> None:
    c.execute(
        text(
            "UPDATE knowledge.schedule_publications SET status = 'processing', "
            "processing_started_at = now() WHERE publication_id = :pub"
        ),
        {"pub": publication},
    )
    c.execute(
        text(
            "UPDATE knowledge.schedule_publications SET document_sha256 = :sha, "
            "document_size_bytes = :size WHERE publication_id = :pub"
        ),
        {"pub": publication, "sha": sha, "size": size},
    )


def _run(c: Connection, publication: str, n: int = 1) -> str:
    run = f"sprun_sp6mig{n:04d}aaaa"
    c.execute(
        insert(tables.schedule_parser_runs).values(
            parser_run_id=run,
            principal_id=P,
            project_id=PROJECT,
            series_id=SERIES,
            publication_id=publication,
            operation_id=f"op_sp6mig{n:04d}aaaa",
            attempt_number=1,
            parser_name="my-pa-p6-xer-parser",
            parser_version="1",
            profile_id="p6_xer_v1",
            profile_version=1,
            document_sha256=SHA,
        )
    )
    return run


def _key(publication: str, run: str) -> dict[str, object]:
    return {"parser_run_id": run, "principal_id": P, "publication_id": publication}


def _rows(publication: str, run: str) -> dict[str, dict[str, object]]:
    """One CHECK-valid row per per-run table (the activity unlinked)."""
    key = _key(publication, run)
    series = {"project_id": PROJECT, "series_id": SERIES}
    return {
        "schedule_p6_projects": {
            **key,
            "p6_project_id": 1,
            "project_short_name": "SYN-1",
            "data_date": datetime(2026, 11, 2, 8),
            "project_name": "Synthetic",
            "export_version": "26.4",
            "encoding": "utf-8",
            "catalogue_version": "p6-field-catalogue-v1",
            "record_line": 4,
        },
        "schedule_p6_wbs": {
            **key,
            "p6_wbs_id": 10,
            "is_project_node": True,
            "short_name": "SYN",
            "name": "Synthetic",
            "parent_p6_wbs_id": 9,
            "depth": 0,
            "wbs_path": [],
            "record_line": 6,
        },
        "schedule_p6_activities": {
            **key,
            **series,
            "p6_task_id": 100,
            "p6_wbs_id": 10,
            "p6_calendar_id": 7,
            "task_type": "TT_Task",
            "status_code": "TK_NotStart",
            "activity_id": "A1000",
            "activity_name": "Synthetic activity",
            "remaining_hours": 8,
            "original_hours": 8,
            "early_start": datetime(2026, 11, 2, 8),
            "early_finish": datetime(2026, 11, 2, 16),
            "start_at": datetime(2026, 11, 2, 8),
            "finish_at": datetime(2026, 11, 2, 16),
            "wbs_path": [],
            "kind": "task",
            "record_line": 8,
        },
        "schedule_p6_relationships": {
            **key,
            "p6_relationship_id": 500,
            "succ_p6_task_id": 100,
            "pred_p6_task_id": 99,
            "relationship_type": "PR_FS",
            "lag_hours": 0,
            "pred_activity_id": None,
            "succ_activity_id": "A1000",
            "is_external": True,
            "record_line": 10,
        },
        "schedule_p6_calendars": {
            **key,
            "p6_calendar_id": 7,
            "calendar_type": "CA_Base",
            "week": [[], [[480, 960]], [[480, 960]], [[480, 960]], [[480, 960]], [[480, 960]], []],
            "exceptions": [],
            "exception_count": 0,
            "data_sha256": "c" * 64,
            "record_line": 12,
        },
        "schedule_p6_field_values": {
            **key,
            **series,
            "entity_kind": "activity",
            "entity_p6_id": 100,
            "field_key": "xer:TASK.expect_end_date",
            "ordinal": 0,
            "activity_id": "A1000",
            "value_ts": datetime(2026, 11, 3, 16),
            "source_table": "TASK",
            "record_line": 8,
        },
        "schedule_p6_observed_fields": {
            **key,
            "table_position": 3,
            "field_position": 0,
            "source_table": "TASK",
            "field_name": "task_id",
            "field_key": "xer:TASK.task_id",
            "catalogued": True,
            "tier": "R",
            "present": True,
            "record_count": 1,
            "nonempty_count": 1,
            "min_length": 3,
            "max_length": 3,
            "shape_integer": 1,
            "shape_decimal": 0,
            "shape_date": 0,
            "shape_flag": 0,
            "shape_token": 0,
            "shape_text": 0,
            "unknown_enum_count": 0,
            "over_length_count": 0,
            "captured": True,
        },
    }


def _table(name: str) -> Table:
    return tables.METADATA.tables[f"{SCHEMA}.{name}"]


def _store(c: Connection, publication: str, run: str) -> None:
    for name, row in _rows(publication, run).items():
        c.execute(insert(_table(name)).values(**row))


def _stable(c: Connection, n: int = 1, activity: str = "A1000") -> str:
    stable = f"sact_sp6mig{n:04d}aaaa"
    c.execute(
        insert(tables.schedule_activities).values(
            schedule_activity_id=stable,
            principal_id=P,
            project_id=PROJECT,
            series_id=SERIES,
            published_activity_id=activity,
        )
    )
    return stable


def _issue(
    c: Connection, publication: str, run: str | None, n: int, code: str, severity: str
) -> None:
    c.execute(
        insert(tables.schedule_import_issues).values(
            issue_id=f"siss_sp6mig{n:04d}aaaa",
            principal_id=P,
            project_id=PROJECT,
            series_id=SERIES,
            publication_id=publication,
            parser_run_id=run,
            severity=severity,
            code=code,
            source_table="TASK",
            record_line=8,
            field="task_code",
        )
    )


def _parse(c: Connection, run: str, *, rows: int = 1, issues: int = 0, warnings: int = 0) -> None:
    c.execute(
        text(
            "UPDATE knowledge.schedule_parser_runs SET status = 'parsed', completed_at = now(), "
            "page_count = 0, row_count = :rows, issue_count = :issues, warning_count = "
            ":warnings, parse_result_sha256 = :frame WHERE parser_run_id = :run"
        ),
        {"run": run, "rows": rows, "issues": issues, "warnings": warnings, "frame": FRAME},
    )


def _finish(
    c: Connection, publication: str, run: str, status: str, *, rows: int = 1, issues: int = 0
) -> None:
    c.execute(
        text(
            "UPDATE knowledge.schedule_publications SET status = :status, completed_at = now(), "
            "accepted_parser_run_id = :run, page_count = 0, row_count = :rows, activity_count = "
            ":rows, ambiguous_row_count = 0, issue_count = :issues WHERE publication_id = :pub"
        ),
        {"pub": publication, "run": run, "status": status, "rows": rows, "issues": issues},
    )


def _link(c: Connection, run: str, stable: str) -> None:
    c.execute(
        text(
            "UPDATE knowledge.schedule_p6_activities SET schedule_activity_id = :stable "
            "WHERE parser_run_id = :run"
        ),
        {"run": run, "stable": stable},
    )


@pytest.fixture
def running(engine: Engine) -> tuple[Engine, str, str]:
    """A processing P6 publication with its running run and one row per per-run table."""
    with engine.begin() as c:
        _base(c)
        publication = _admit(c)
        _process(c, publication)
        run = _run(c, publication)
        _store(c, publication, run)
    return engine, publication, run


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


def _refused(
    engine: Engine,
    write: Callable[[Connection], object],
    *,
    sqlstate: str,
    names: str,
    replica: bool = False,
) -> None:
    with pytest.raises(DBAPIError) as refused, engine.begin() as c:
        if replica:
            c.execute(text("SET LOCAL session_replication_role = replica"))
        write(c)
    assert _sqlstate(refused.value) == sqlstate, str(refused.value)
    assert names in str(refused.value), str(refused.value)


def _accepted_then_undone(engine: Engine, write: Callable[[Connection], object]) -> None:
    connection = engine.connect()
    transaction = connection.begin()
    try:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        write(connection)
    finally:
        transaction.rollback()
        connection.close()


# ---- an existing PDF publication survives -------------------------------------------


def _seed_pdf(engine: Engine) -> None:
    with engine.begin() as c:
        _base(c)
        c.execute(
            text(
                "INSERT INTO knowledge.sources (source_id, provider_kind, label, classification, "
                "native_root) VALUES ('src_sp6mig0001aaaa', 'fixture', 'Synthetic', "
                "'synthetic_test', '/synthetic/p6')"
            )
        )
        c.execute(
            text(
                "INSERT INTO knowledge.source_objects (source_object_id, source_id, kind, "
                "native_locator) VALUES ('obj_sp6mig0001aaaa', 'src_sp6mig0001aaaa', 'file', "
                "'/synthetic/p6/schedule.pdf')"
            )
        )
        c.execute(
            text(
                "INSERT INTO knowledge.source_object_versions (version_id, source_object_id, "
                "fingerprint, media_type, size_bytes, modified_at) VALUES ('ver_sp6mig0001aaaa', "
                "'obj_sp6mig0001aaaa', 'synthetic-fingerprint', 'application/pdf', 1024, now())"
            )
        )
        c.execute(
            text(
                "INSERT INTO knowledge.enrollments (enrollment_id, source_id, principal_id, "
                "purpose, policy_version, idempotency_key, request_fingerprint, object_ids, "
                "depth, media_types, max_items, max_bytes) VALUES ('enr_sp6mig0001aaaa', "
                "'src_sp6mig0001aaaa', :p, 'schedule_import', 'policy-v1', 'sp6-enrol', "
                "'synthetic-fingerprint', ARRAY['obj_sp6mig0001aaaa'], 0, "
                "ARRAY['application/pdf'], 10, 1048576)"
            ),
            {"p": P},
        )
        c.execute(
            text(
                "INSERT INTO knowledge.enrollment_objects (enrollment_id, source_object_id) "
                "VALUES ('enr_sp6mig0001aaaa', 'obj_sp6mig0001aaaa')"
            )
        )
        c.execute(
            text(
                "INSERT INTO knowledge.schedule_publications (publication_id, principal_id, "
                "project_id, series_id, enrollment_id, source_object_id, source_version_id, "
                "idempotency_key, request_digest, publication_role) VALUES "
                "('spub_sp6migpdf1aaaa', :p, :project, :series, 'enr_sp6mig0001aaaa', "
                "'obj_sp6mig0001aaaa', 'ver_sp6mig0001aaaa', 'sp6-pdf-0001', :sha, 'update')"
            ),
            {"p": P, "project": PROJECT, "series": SERIES, "sha": SHA},
        )
        c.execute(
            text(
                "INSERT INTO knowledge.schedule_jobs (operation_id, publication_id, principal_id) "
                "VALUES ('op_sp6migpdf1aaaa', 'spub_sp6migpdf1aaaa', :p)"
            ),
            {"p": P},
        )


def _publication_rows(engine: Engine) -> list[dict[str, object]]:
    with engine.connect() as c:
        return [
            dict(row)
            for row in c.execute(
                text("SELECT * FROM knowledge.schedule_publications ORDER BY publication_id")
            ).mappings()
        ]


@pytest.mark.database
def test_an_existing_pdf_publication_survives_the_upgrade_unchanged(engine: Engine) -> None:
    command.downgrade(_config(), PREVIOUS)
    _seed_pdf(engine)
    before = _publication_rows(engine)
    assert len(before) == 1
    command.upgrade(_config(), REVISION)
    after = _publication_rows(engine)
    assert len(after) == 1
    added = {
        "source_format": "pdf",
        "p6_snapshot_id": None,
        "p6_workspace_id": None,
        "p6_workspace_path": None,
        "p6_workspace_version": None,
        "p6_capture_event_id": None,
        "accept_project_identity_change": False,
    }
    assert after[0] == {**before[0], **added}
    # And it still moves through its PDF lifecycle under the restated F3.
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE knowledge.schedule_publications SET status = 'processing', "
                "processing_started_at = now() WHERE publication_id = 'spub_sp6migpdf1aaaa'"
            )
        )


# ---- the publication CHECK matrix (replica: the CHECK alone answers) -----------------


def _publication(**overrides: object) -> Callable[[Connection], object]:
    values = _p6_publication(9, "sp6n_sp6mig0009aaaa", **overrides)
    return lambda c: c.execute(insert(tables.schedule_publications).values(**values))


_PDF: Final = {
    "source_format": "pdf",
    "p6_snapshot_id": None,
    "p6_workspace_id": None,
    "p6_workspace_path": None,
    "p6_workspace_version": None,
    "enrollment_id": "enr_sp6mig0009aaaa",
    "source_object_id": "obj_sp6mig0009aaaa",
    "source_version_id": "ver_sp6mig0009aaaa",
}
_FORMAT: Final = "a_schedule_publication_source_matches_its_format"


@pytest.mark.database
@pytest.mark.parametrize(
    ("case", "overrides", "constraint"),
    [
        ("pdf without its enrollment", {**_PDF, "enrollment_id": None}, _FORMAT),
        ("pdf without its version", {**_PDF, "source_version_id": None}, _FORMAT),
        ("pdf with a snapshot", {**_PDF, "p6_snapshot_id": "sp6n_sp6mig0009aaaa"}, _FORMAT),
        ("pdf with a workspace", {**_PDF, "p6_workspace_id": "projects"}, _FORMAT),
        (
            "pdf accepting an identity change",
            {**_PDF, "accept_project_identity_change": True},
            _FORMAT,
        ),
        ("p6 with an enrollment", {"enrollment_id": "enr_sp6mig0009aaaa"}, _FORMAT),
        ("p6 with a source object", {"source_object_id": "obj_sp6mig0009aaaa"}, _FORMAT),
        ("p6 with a source version", {"source_version_id": "ver_sp6mig0009aaaa"}, _FORMAT),
        ("p6 without a snapshot", {"p6_snapshot_id": None}, _FORMAT),
        ("p6 without its workspace", {"p6_workspace_id": None}, _FORMAT),
        ("p6 without its path", {"p6_workspace_path": None}, _FORMAT),
        ("p6 without its version", {"p6_workspace_version": None}, _FORMAT),
        (
            "p6 baseline",
            {"publication_role": "baseline", "baseline_kind": "contract"},
            "a_p6_schedule_publication_is_an_update",
        ),
        ("workspace alias", {"p6_workspace_id": "Projects"}, "a_schedule_workspace_is_an_alias"),
        (
            "absolute path",
            {"p6_workspace_path": "/etc/x.xer"},
            "a_schedule_workspace_path_is_bounded",
        ),
        ("long path", {"p6_workspace_path": "a" * 4097}, "a_schedule_workspace_path_is_bounded"),
        (
            "version token",
            {"p6_workspace_version": "fv1_x"},
            "a_schedule_workspace_version_is_a_token",
        ),
        (
            "snapshot id",
            {"p6_snapshot_id": "sp6e_sp6mig0009aaaa"},
            "p6_snapshot_id_is_an_opaque_identifier",
        ),
        (
            "capture event id",
            {"p6_capture_event_id": "sp6n_sp6mig0009aaaa"},
            "p6_capture_event_id_is_an_opaque_identifier",
        ),
    ],
    ids=lambda value: value if isinstance(value, str) and " " in value else None,
)
def test_the_publication_check_matrix_refuses_each_case(
    engine: Engine, case: str, overrides: dict[str, object], constraint: str
) -> None:
    del case
    _refused(engine, _publication(**overrides), sqlstate=CHECK, names=constraint, replica=True)


@pytest.mark.database
def test_an_unknown_format_is_refused_by_its_own_check(engine: Engine) -> None:
    """An unknown format also fails the format matrix, so that one is lifted first."""

    def write(c: Connection) -> None:
        c.execute(text(f"ALTER TABLE knowledge.schedule_publications DROP CONSTRAINT {_FORMAT}"))
        _publication(source_format="p6_mpp")(c)

    _refused(engine, write, sqlstate=CHECK, names="a_schedule_source_format_is_known", replica=True)
    _refused(
        engine, _publication(source_format="p6_mpp"), sqlstate=CHECK, names=_FORMAT, replica=True
    )


@pytest.mark.database
def test_the_publication_check_matrix_accepts_both_formats(engine: Engine) -> None:
    _accepted_then_undone(engine, _publication())
    _accepted_then_undone(engine, _publication(**_PDF))
    _accepted_then_undone(engine, _publication(p6_capture_event_id="sp6e_sp6mig0009aaaa"))


# ---- the altered parser runs and issues ------------------------------------------------


@pytest.mark.database
def test_a_pdf_run_needs_its_engine_and_a_p6_run_needs_none(
    running: tuple[Engine, str, str],
) -> None:
    engine, publication, _run_id = running
    base = {
        "principal_id": P,
        "project_id": PROJECT,
        "series_id": SERIES,
        "publication_id": publication,
        "operation_id": "op_sp6mig0001aaaa",
        "attempt_number": 2,
        "parser_name": "cpm-workbench-full-parser",
        "parser_version": "1",
        "profile_version": 1,
        "document_sha256": SHA,
        "parser_run_id": "sprun_sp6mig0002aaaa",
    }
    _refused(
        engine,
        lambda c: c.execute(
            insert(tables.schedule_parser_runs).values(**base, profile_id="p6_full_v1")
        ),
        sqlstate=CHECK,
        names="a_schedule_parser_engine_matches_its_profile",
        replica=True,
    )
    _accepted_then_undone(
        engine,
        lambda c: c.execute(
            insert(tables.schedule_parser_runs).values(
                **base, profile_id="p6_full_v1", pypdfium2_version="5", pdfium_version="1"
            )
        ),
    )
    _accepted_then_undone(
        engine,
        lambda c: c.execute(
            insert(tables.schedule_parser_runs).values(**base, profile_id="p6_xer_v1")
        ),
    )


@pytest.mark.database
@pytest.mark.parametrize(
    ("code", "severity", "extra", "constraint"),
    [
        ("p6_wbs_cycle", "warning", {}, "a_schedule_issue_severity_matches_its_code"),
        ("p6_unknown_table", "error", {}, "a_schedule_issue_severity_matches_its_code"),
        ("p6_not_a_code", "error", {}, "a_schedule_issue_code_is_known"),
        ("p6_unknown_field", "warning", {"field": "bad name"}, "a_schedule_issue_field_is_known"),
        (
            "invalid_date",
            "error",
            {"source_table": None, "record_line": None, "field": "task_code"},
            "a_schedule_issue_field_is_known",
        ),
        (
            "p6_unknown_table",
            "warning",
            {"source_table": "lower"},
            "a_schedule_issue_source_table_is_a_name",
        ),
        (
            "p6_unknown_table",
            "warning",
            {"record_line": 0},
            "a_schedule_issue_record_line_is_positive",
        ),
        (
            "p6_unknown_table",
            "warning",
            {"page_number": 1},
            "a_schedule_issue_is_positioned_by_its_format",
        ),
        ("invalid_date", "error", {"field": None}, "a_schedule_issue_is_positioned_by_its_format"),
    ],
)
def test_the_issue_checks_refuse_each_case(
    running: tuple[Engine, str, str],
    code: str,
    severity: str,
    extra: dict[str, object],
    constraint: str,
) -> None:
    engine, publication, run = running
    values: dict[str, object] = {
        "issue_id": "siss_sp6mig0009aaaa",
        "principal_id": P,
        "project_id": PROJECT,
        "series_id": SERIES,
        "publication_id": publication,
        "parser_run_id": run,
        "severity": severity,
        "code": code,
        "source_table": "TASK",
        "record_line": 8,
        "field": "task_code",
        **extra,
    }
    _refused(
        engine,
        lambda c: c.execute(insert(tables.schedule_import_issues).values(**values)),
        sqlstate=CHECK,
        names=constraint,
        replica=True,
    )


@pytest.mark.database
@pytest.mark.parametrize(
    ("code", "severity"),
    [
        ("p6_wbs_cycle", "error"),
        ("p6_value_invalid", "error"),
        ("p6_value_invalid", "warning"),
        ("p6_unknown_enum_value", "warning"),
        ("p6_tolerated_field_missing", "warning"),
        ("p6_project_identity_changed", "warning"),
    ],
)
def test_the_issue_checks_accept_each_p6_severity(
    running: tuple[Engine, str, str], code: str, severity: str
) -> None:
    engine, publication, run = running
    _accepted_then_undone(engine, lambda c: _issue(c, publication, run, 9, code, severity))


# ---- new-table CHECKs and UNIQUEs -----------------------------------------------------


@pytest.mark.database
@pytest.mark.parametrize(
    ("table", "change", "constraint"),
    [
        ("schedule_p6_activities", {"kind": "start_milestone"}, "a_p6_activity_kind_is_its_type"),
        (
            "schedule_p6_activities",
            {"start_at": datetime(2026, 1, 1)},
            "a_p6_activity_dates_are_derived",
        ),
        (
            "schedule_p6_activities",
            {"task_type": "TT Task"},
            "a_p6_activity_enumeration_is_a_token",
        ),
        ("schedule_p6_activities", {"activity_id": "A" * 41}, "a_p6_activity_text_is_bounded"),
        ("schedule_p6_activities", {"record_line": 0}, "a_p6_activity_record_line_is_positive"),
        ("schedule_p6_wbs", {"depth": 1}, "a_p6_wbs_depth_is_its_path"),
        (
            "schedule_p6_relationships",
            {"is_external": False},
            "a_p6_relationship_names_both_ends_unless_external",
        ),
        ("schedule_p6_calendars", {"exception_count": 1}, "a_p6_calendar_data_is_shaped"),
        ("schedule_p6_calendars", {"data_sha256": None}, "a_p6_calendar_digest_is_its_data"),
        ("schedule_p6_projects", {"encoding": "latin-1"}, "a_p6_project_header_is_known"),
        ("schedule_p6_field_values", {"value_text": "x"}, "a_p6_field_value_has_one_value"),
        (
            "schedule_p6_field_values",
            {"field_key": "xer:task.x"},
            "a_p6_field_value_key_follows_its_grammar",
        ),
        (
            "schedule_p6_field_values",
            {"entity_kind": "wbs"},
            "a_p6_field_value_activity_is_an_activity",
        ),
        (
            "schedule_p6_field_values",
            {"code_path": ["a"] * 9},
            "a_p6_field_value_code_path_is_bounded",
        ),
        (
            "schedule_p6_observed_fields",
            {"shape_text": 1},
            "a_p6_observed_field_counts_are_consistent",
        ),
        (
            "schedule_p6_observed_fields",
            {"min_length": None},
            "a_p6_observed_field_lengths_are_ordered",
        ),
        ("schedule_p6_observed_fields", {"tier": "X"}, "a_p6_observed_field_is_named"),
    ],
)
def test_each_new_table_check_refuses_its_case(
    engine: Engine, table: str, change: dict[str, object], constraint: str
) -> None:
    row = {**_rows("spub_sp6mig0009aaaa", "sprun_sp6mig0009aaaa")[table], **change}
    _refused(
        engine,
        lambda c: c.execute(insert(_table(table)).values(**row)),
        sqlstate=CHECK,
        names=constraint,
        replica=True,
    )


@pytest.mark.database
def test_each_per_run_row_is_check_valid_alone(engine: Engine) -> None:
    for table, row in _rows("spub_sp6mig0009aaaa", "sprun_sp6mig0009aaaa").items():
        _accepted_then_undone(
            engine, lambda c, t=table, r=row: c.execute(insert(_table(t)).values(**r))
        )


@pytest.mark.database
def test_the_snapshot_checks_its_digest_size_and_uniqueness(engine: Engine) -> None:
    def snapshot(**overrides: object) -> Callable[[Connection], object]:
        values: dict[str, object] = {
            "snapshot_id": "sp6n_sp6mig0009aaaa",
            "principal_id": P,
            "format": "p6_xer",
            "size_bytes": len(CONTENT),
            "sha256": SHA,
            "content": CONTENT,
            **overrides,
        }
        return lambda c: c.execute(insert(tables.schedule_p6_snapshots).values(**values))

    _refused(engine, snapshot(sha256="0" * 64), sqlstate=CHECK, names="a_p6_snapshot_is_its_digest")
    _refused(engine, snapshot(size_bytes=1), sqlstate=CHECK, names="a_p6_snapshot_is_its_size")
    _refused(engine, snapshot(format="pdf"), sqlstate=CHECK, names="a_p6_snapshot_format_is_known")
    _refused(
        engine,
        lambda c: (snapshot()(c), snapshot(snapshot_id="sp6n_sp6mig0010aaaa")(c)),
        sqlstate=UNIQUE,
        names="a_p6_snapshot_is_stored_once_per_principal",
    )
    _accepted_then_undone(engine, snapshot())


@pytest.mark.database
def test_a_snapshot_is_published_once_per_series(engine: Engine) -> None:
    def twice(c: Connection) -> None:
        _base(c)
        snapshot = _snapshot(c)
        _admit(c, 1, snapshot=snapshot)
        _admit(c, 2, snapshot=snapshot)

    _refused(
        engine, twice, sqlstate=UNIQUE, names="a_schedule_snapshot_is_published_once_per_series"
    )


# ---- triggers ----------------------------------------------------------------------


@pytest.mark.database
@pytest.mark.parametrize("table", [t for t in NEW_TABLES if t != "schedule_p6_activities"])
def test_every_new_table_but_activities_is_append_only(
    running: tuple[Engine, str, str], table: str
) -> None:
    engine, _publication_id, _run_id = running
    with engine.begin() as c:
        c.execute(
            insert(tables.schedule_p6_capture_events).values(
                event_id="sp6e_sp6mig0001aaaa",
                principal_id=P,
                project_id=PROJECT,
                series_id=SERIES,
                sequence=1,
                field_keys=[],
                catalogue_version="p6-field-catalogue-v1",
                authority_class="local_operator",
                decision_channel="local_cli",
                acceptance_basis="user_confirmed",
            )
        )
    for statement in (
        f"UPDATE knowledge.{table} SET created_at = created_at",  # noqa: S608 - fixed names
        f"DELETE FROM knowledge.{table}",  # noqa: S608 - fixed names
    ):
        _refused(
            engine,
            lambda c, s=statement: c.execute(text(s)),
            sqlstate=RESTRICT_VIOLATION,
            names=f"{table} is append-only",
        )


@pytest.mark.database
@pytest.mark.parametrize("table", NEW_TABLES)
def test_truncate_is_refused_on_every_new_table_holding_a_row(
    running: tuple[Engine, str, str], table: str
) -> None:
    engine, _publication_id, _run_id = running
    if table == "schedule_p6_capture_events":
        with engine.begin() as c:
            c.execute(
                insert(tables.schedule_p6_capture_events).values(
                    event_id="sp6e_sp6mig0001aaaa",
                    principal_id=P,
                    project_id=PROJECT,
                    series_id=SERIES,
                    sequence=1,
                    field_keys=[],
                    catalogue_version="p6-field-catalogue-v1",
                    authority_class="local_operator",
                    decision_channel="local_cli",
                    acceptance_basis="user_confirmed",
                )
            )

    def truncate(c: Connection) -> None:
        # A referenced table refuses TRUNCATE for its foreign keys first; they
        # are lifted (rolled back) so the trigger alone answers.
        for referencing, name in c.execute(
            text(
                "SELECT r.relname, c.conname FROM pg_constraint c JOIN pg_class r ON "
                "r.oid = c.conrelid WHERE c.contype = 'f' AND c.confrelid = "
                "(:table)::regclass AND c.conrelid <> c.confrelid"
            ),
            {"table": f"knowledge.{table}"},
        ).all():
            c.execute(text(f"ALTER TABLE knowledge.{referencing} DROP CONSTRAINT {name}"))
        c.execute(text(f"TRUNCATE knowledge.{table}"))

    _refused(engine, truncate, sqlstate=RESTRICT_VIOLATION, names=f"{table} refuses TRUNCATE")


@pytest.mark.database
@pytest.mark.parametrize("table", PER_RUN_TABLES)
def test_a_per_run_row_is_stored_only_while_its_run_runs(
    running: tuple[Engine, str, str], table: str
) -> None:
    engine, publication, run = running
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE knowledge.schedule_parser_runs SET status = 'failed', completed_at = now() "
                "WHERE parser_run_id = :run"
            ),
            {"run": run},
        )
    row = dict(_rows(publication, run)[table])
    # A second row of the same table: only the run guard can refuse it.
    for column, value in (
        ("p6_wbs_id", 11),
        ("p6_task_id", 101),
        ("p6_relationship_id", 501),
        ("p6_calendar_id", 8),
        ("ordinal", 1),
        ("field_position", 1),
    ):
        if column in row:
            row[column] = value
    if table == "schedule_p6_activities":
        row["activity_id"] = "A1001"
    if table == "schedule_p6_observed_fields":
        row["field_name"] = "task_code"
    _refused(
        engine,
        lambda c: c.execute(insert(_table(table)).values(**row)),
        sqlstate=RESTRICT_VIOLATION,
        names="stored by a running parser run",
    )


@pytest.mark.database
def test_a_per_run_row_belongs_to_a_p6_publication(engine: Engine) -> None:
    """A PDF publication's run can store no P6 row (the guard reads the format)."""
    _seed_pdf_running = _pdf_running(engine)
    publication, run = _seed_pdf_running
    for table, row in _rows(publication, run).items():
        _refused(
            engine,
            lambda c, t=table, r=row: c.execute(insert(_table(t)).values(**r)),
            sqlstate=RESTRICT_VIOLATION,
            names="belongs to a p6 publication",
        )


def _pdf_running(engine: Engine) -> tuple[str, str]:
    command.downgrade(_config(), PREVIOUS)
    _seed_pdf(engine)
    command.upgrade(_config(), REVISION)
    with engine.begin() as c:
        c.execute(
            text(
                "UPDATE knowledge.schedule_publications SET status = 'processing', "
                "processing_started_at = now() WHERE publication_id = 'spub_sp6migpdf1aaaa'"
            )
        )
        c.execute(
            text(
                "UPDATE knowledge.schedule_publications SET document_sha256 = :sha, "
                "document_size_bytes = 10 WHERE publication_id = 'spub_sp6migpdf1aaaa'"
            ),
            {"sha": SHA},
        )
        c.execute(
            insert(tables.schedule_parser_runs).values(
                parser_run_id="sprun_sp6migpdf1aaaa",
                principal_id=P,
                project_id=PROJECT,
                series_id=SERIES,
                publication_id="spub_sp6migpdf1aaaa",
                operation_id="op_sp6migpdf1aaaa",
                attempt_number=1,
                parser_name="cpm-workbench-full-parser",
                parser_version="1",
                profile_id="p6_full_v1",
                profile_version=1,
                pypdfium2_version="5",
                pdfium_version="1",
                document_sha256=SHA,
            )
        )
    return "spub_sp6migpdf1aaaa", "sprun_sp6migpdf1aaaa"


@pytest.mark.database
def test_an_activity_link_is_set_once_after_the_run_is_parsed(
    running: tuple[Engine, str, str],
) -> None:
    engine, _publication_id, run = running
    with engine.begin() as c:
        stable = _stable(c)
    _refused(
        engine,
        lambda c: _link(c, run, stable),
        sqlstate=RESTRICT_VIOLATION,
        names="linked after its run is parsed",
    )
    _refused(
        engine,
        lambda c: c.execute(
            text("UPDATE knowledge.schedule_p6_activities SET activity_name = 'other'")
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="p6 schedule activity content is immutable",
    )
    with engine.begin() as c:
        _parse(c, run)
        _link(c, run, stable)
    _refused(
        engine,
        lambda c: _link(c, run, stable),
        sqlstate=RESTRICT_VIOLATION,
        names="link is set once",
    )
    _refused(
        engine,
        lambda c: c.execute(text("DELETE FROM knowledge.schedule_p6_activities")),
        sqlstate=RESTRICT_VIOLATION,
        names="never deleted",
    )


@pytest.mark.database
def test_an_activity_link_names_its_exact_stable_activity(
    running: tuple[Engine, str, str],
) -> None:
    engine, _publication_id, run = running
    with engine.begin() as c:
        other = _stable(c, 2, "B2000")
        _parse(c, run)
    _refused(
        engine,
        lambda c: _link(c, run, other),
        sqlstate=FOREIGN,
        names="a_p6_activity_links_its_exact_activity",
    )


def _event(n: int, keys: list[str], **overrides: object) -> Callable[[Connection], object]:
    values: dict[str, object] = {
        "event_id": f"sp6e_sp6mig{n:04d}aaaa",
        "principal_id": P,
        "project_id": PROJECT,
        "series_id": SERIES,
        "sequence": n,
        "field_keys": keys,
        "catalogue_version": "p6-field-catalogue-v1",
        "authority_class": "local_operator",
        "decision_channel": "local_cli",
        "acceptance_basis": "user_confirmed",
        **overrides,
    }
    return lambda c: c.execute(insert(tables.schedule_p6_capture_events).values(**values))


@pytest.mark.database
def test_the_capture_chain_is_contiguous_sorted_distinct_and_grammatical(engine: Engine) -> None:
    with engine.begin() as c:
        _base(c)
    _refused(engine, _event(2, []), sqlstate=RESTRICT_VIOLATION, names="extends its chain by one")
    _refused(
        engine,
        _event(1, ["xer:TASK.b", "xer:TASK.a"]),
        sqlstate=CHECK,
        names="sorted and distinct",
    )
    _refused(
        engine,
        _event(1, ["xer:TASK.a", "xer:TASK.a"]),
        sqlstate=CHECK,
        names="sorted and distinct",
    )
    _refused(engine, _event(1, ["TASK.a"]), sqlstate=CHECK, names="follows its grammar")
    # Code-point order, not the database collation: upper case sorts before lower.
    keys = ["code:Phase", "code:area", "udf:TASK:Zone", "xer:TASK.expect_end_date"]
    with engine.begin() as c:
        _event(1, keys)(c)
        _event(2, [])(c)
    _refused(engine, _event(4, []), sqlstate=RESTRICT_VIOLATION, names="extends its chain by one")
    _refused(
        engine,
        _event(3, [], decision_channel="remote_interactive"),
        sqlstate=CHECK,
        names="a_p6_capture_event_creator_is_known",
    )


@pytest.mark.database
def test_a_publication_names_a_capture_event_of_its_own_series(engine: Engine) -> None:
    with engine.begin() as c:
        _base(c)
        _base(c, project="prj_sp6mig0002aaaa", series="sser_sp6mig0002aaaa")
        _event(1, [], project_id="prj_sp6mig0002aaaa", series_id="sser_sp6mig0002aaaa")(c)
    _refused(
        engine,
        lambda c: _admit(c, 1, p6_capture_event_id="sp6e_sp6mig0001aaaa"),
        sqlstate=FOREIGN,
        names="a_schedule_publication_names_a_capture_event_of_its_series",
    )


@pytest.mark.database
def test_a_publication_names_a_snapshot_of_its_own_principal(engine: Engine) -> None:
    other = "prn_sp6mig0002bbbb"
    with engine.begin() as c:
        _base(c)
        c.execute(
            text(
                "INSERT INTO knowledge.schedule_p6_snapshots (snapshot_id, principal_id, format, "
                "size_bytes, sha256, content) VALUES ('sp6n_sp6mig0007aaaa', :p, 'p6_xer', :size, "
                ":sha, :content)"
            ),
            {"p": other, "size": len(CONTENT), "sha": SHA, "content": CONTENT},
        )
    _refused(
        engine,
        lambda c: _admit(c, 1, snapshot="sp6n_sp6mig0007aaaa"),
        sqlstate=FOREIGN,
        names="a_schedule_publication_names_a_snapshot_of_its_principal",
    )


@pytest.mark.database
def test_a_p6_publication_names_a_snapshot_of_its_format_and_pins_it(engine: Engine) -> None:
    with engine.begin() as c:
        _base(c)
        c.execute(
            text(
                "INSERT INTO knowledge.schedule_p6_snapshots (snapshot_id, principal_id, format, "
                "size_bytes, sha256, content) VALUES ('sp6n_sp6mig0005aaaa', :p, 'p6_xml', :size, "
                ":sha, :content)"
            ),
            {
                "p": P,
                "size": len(CONTENT) + 1,
                "sha": hashlib.sha256(CONTENT + b"\n").hexdigest(),
                "content": CONTENT + b"\n",
            },
        )
    _refused(
        engine,
        lambda c: _admit(c, 1, snapshot="sp6n_sp6mig0005aaaa"),
        sqlstate=RESTRICT_VIOLATION,
        names="names a snapshot of its format",
    )
    with engine.begin() as c:
        publication = _admit(c, 1)
    _refused(
        engine,
        lambda c: _process(c, publication, sha="e" * 64),
        sqlstate=RESTRICT_VIOLATION,
        names="pins its snapshot",
    )
    _refused(
        engine,
        lambda c: _process(c, publication, size=len(CONTENT) + 1),
        sqlstate=RESTRICT_VIOLATION,
        names="pins its snapshot",
    )
    with engine.begin() as c:
        _process(c, publication)
    _refused(
        engine,
        lambda c: c.execute(
            text(
                "UPDATE knowledge.schedule_publications SET p6_workspace_path = 'moved.xer' "
                "WHERE publication_id = :pub"
            ),
            {"pub": publication},
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="admission columns are immutable",
    )


# ---- a P6 publication's outcomes through F3, F6 and F9 ----------------------------------


@pytest.mark.database
def test_a_p6_publication_completes_with_every_activity_linked(
    running: tuple[Engine, str, str],
) -> None:
    engine, publication, run = running
    with engine.begin() as c:
        _issue(c, publication, run, 1, "p6_tolerated_field_missing", "warning")
        _parse(c, run, issues=1, warnings=1)
        stable = _stable(c)
    _refused(
        engine,
        lambda c: _finish(c, publication, run, "complete", issues=1),
        sqlstate=RESTRICT_VIOLATION,
        names="a complete p6 schedule publication links every activity",
    )
    _refused(
        engine,
        lambda c: (
            _link(c, run, stable),
            _finish(c, publication, run, "complete", rows=2, issues=1),
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="counts its accepted run",
    )
    _refused(
        engine,
        lambda c: (
            _link(c, run, stable),
            _finish(c, publication, run, "review_required", issues=1),
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="status is its derived outcome",
    )
    with engine.begin() as c:
        _link(c, run, stable)
        _finish(c, publication, run, "complete", issues=1)
        status = c.execute(
            text("SELECT knowledge.schedule_run_outcome(:run)"), {"run": run}
        ).scalar_one()
    assert status == "complete"


@pytest.mark.database
def test_an_identity_change_makes_a_p6_publication_review_required_unlinked(
    running: tuple[Engine, str, str],
) -> None:
    engine, publication, run = running
    with engine.begin() as c:
        _issue(c, publication, run, 1, "p6_project_identity_changed", "warning")
        _parse(c, run, issues=1, warnings=1)
        stable = _stable(c)
    _refused(
        engine,
        lambda c: (
            _link(c, run, stable),
            _finish(c, publication, run, "review_required", issues=1),
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="a review-required p6 schedule publication links nothing",
    )
    with engine.begin() as c:
        _finish(c, publication, run, "review_required", issues=1)


@pytest.mark.database
def test_a_fatal_p6_issue_fails_the_run_and_the_publication(
    running: tuple[Engine, str, str],
) -> None:
    engine, publication, run = running
    with engine.begin() as c:
        _issue(c, publication, run, 1, "p6_value_invalid", "error")
    _refused(
        engine,
        lambda c: _parse(c, run, issues=1),
        sqlstate=RESTRICT_VIOLATION,
        names="carries no fatal p6 issue",
    )
    with engine.begin() as c:
        assert (
            c.execute(
                text("SELECT knowledge.schedule_run_outcome(:run)"), {"run": run}
            ).scalar_one()
            == "failed"
        )
        c.execute(
            text(
                "UPDATE knowledge.schedule_parser_runs SET status = 'failed', completed_at = "
                "now(), failure_code = 'p6_value_invalid' WHERE parser_run_id = :run"
            ),
            {"run": run},
        )
        c.execute(
            text(
                "UPDATE knowledge.schedule_publications SET status = 'failed', completed_at = "
                "now(), issue_count = 1 WHERE publication_id = :pub"
            ),
            {"pub": publication},
        )


@pytest.mark.database
def test_a_parsed_p6_run_counts_its_activities_and_no_page(
    running: tuple[Engine, str, str],
) -> None:
    engine, _publication_id, run = running
    _refused(
        engine,
        lambda c: _parse(c, run, rows=0),
        sqlstate=RESTRICT_VIOLATION,
        names="counts its rows",
    )
    _refused(
        engine,
        lambda c: c.execute(
            text(
                "UPDATE knowledge.schedule_parser_runs SET status = 'parsed', completed_at = "
                "now(), page_count = 1, row_count = 1, issue_count = 0, warning_count = 0, "
                "parse_result_sha256 = :frame WHERE parser_run_id = :run"
            ),
            {"run": run, "frame": FRAME},
        ),
        sqlstate=RESTRICT_VIOLATION,
        names="counts no page",
    )


# ---- downgrade refusals, each clause alone -------------------------------------------


def _refuses_downgrade(engine: Engine, message: str) -> None:
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION
    assert f"{message}; refusing to downgrade d8383150cf72" in str(refused.value)
    assert _present(engine) == set(NEW_TABLES)


def _lone(c: Connection, table: str) -> None:
    """One CHECK-valid row of `table` alone (replica: no FK or trigger)."""
    c.execute(text("SET LOCAL session_replication_role = replica"))
    if table == "schedule_p6_snapshots":
        _snapshot(c)
    elif table == "schedule_p6_capture_events":
        _event(1, [])(c)
    else:
        c.execute(
            insert(_table(table)).values(
                **_rows("spub_sp6mig0009aaaa", "sprun_sp6mig0009aaaa")[table]
            )
        )


@pytest.mark.database
@pytest.mark.parametrize("table", NEW_TABLES)
def test_a_downgrade_refuses_while_one_new_table_holds_a_row(engine: Engine, table: str) -> None:
    with engine.begin() as c:
        _lone(c, table)
    _refuses_downgrade(engine, "p6 schedule rows exist")


@pytest.mark.database
def test_a_downgrade_refuses_while_a_publication_is_not_pdf(engine: Engine) -> None:
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        _publication()(c)
    _refuses_downgrade(engine, "p6 schedule publications exist")


@pytest.mark.database
def test_a_downgrade_refuses_while_a_run_has_no_pdf_engine(engine: Engine) -> None:
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        c.execute(
            insert(tables.schedule_parser_runs).values(
                parser_run_id="sprun_sp6mig0009aaaa",
                principal_id=P,
                project_id=PROJECT,
                series_id=SERIES,
                publication_id="spub_sp6mig0009aaaa",
                operation_id="op_sp6mig0009aaaa",
                attempt_number=1,
                parser_name="other",
                parser_version="1",
                profile_id="other_v1",
                profile_version=1,
                document_sha256=SHA,
            )
        )
    _refuses_downgrade(engine, "engine-less schedule parser runs exist")


@pytest.mark.database
@pytest.mark.parametrize(
    ("capability", "purpose"),
    [
        *((name, "schedule_read") for name in sorted(NEW_CAPABILITIES)),
        ("schedule_publications.read", "schedule_p6_import"),
        ("schedule_publications.read", "schedule_p6_configuration"),
    ],
)
def test_a_downgrade_refuses_while_an_audit_event_names_a_new_name(
    engine: Engine, capability: str, purpose: str
) -> None:
    with engine.begin() as c:
        c.execute(
            insert(audit_events).values(
                audit_id="audit_sp6migaudit1",
                correlation_id="corr_sp6migaudit1",
                principal_id=P,
                capability=capability,
                purpose=purpose,
                outcome="allowed",
                policy_version="policy-v1",
                scope_source_id_count=0,
                recorded_at=WHEN,
            )
        )
    _refuses_downgrade(engine, "p6 schedule audit history exists")


@pytest.mark.database
def test_the_audit_vocabulary_admits_the_new_names_only_at_this_revision(engine: Engine) -> None:
    def audit(capability: str, purpose: str) -> Callable[[Connection], object]:
        return lambda c: c.execute(
            insert(audit_events).values(
                audit_id="audit_sp6migaudit2",
                correlation_id="corr_sp6migaudit2",
                principal_id=P,
                capability=capability,
                purpose=purpose,
                outcome="allowed",
                policy_version="policy-v1",
                scope_source_id_count=0,
                recorded_at=WHEN,
            )
        )

    _accepted_then_undone(engine, audit("schedule_publications.import_p6", "schedule_p6_import"))
    command.downgrade(_config(), PREVIOUS)
    _refused(
        engine,
        audit("schedule_publications.import_p6", "schedule_read"),
        sqlstate=CHECK,
        names="capability_is_known",
    )
    _refused(
        engine,
        audit("schedule_publications.read", "schedule_p6_import"),
        sqlstate=CHECK,
        names="purpose_is_known",
    )
    command.upgrade(_config(), REVISION)


# ---- the proven spec error: a whole `value_text` cannot be a B-tree key -------------


@pytest.mark.database
def test_a_whole_4000_character_value_cannot_be_a_btree_key_but_its_prefix_can(
    engine: Engine,
) -> None:
    """Why `schedule_p6_field_values_by_text` keys `left(value_text, 256)`.

    Contract section 7.3 listed `(principal_id, parser_run_id, field_key,
    value_text)`. A section 7.7-legal value of 4,000 characters that does not
    compress exceeds PostgreSQL's B-tree entry limit (about 2,704 bytes), so that
    index would refuse a valid value; the shipped index takes the first 256.
    """
    # 4,000 hexadecimal characters of digests: legal, and incompressible enough.
    value = "".join(hashlib.sha256(str(n).encode()).hexdigest()[:8] for n in range(500))
    assert len(value) == 4000
    with pytest.raises(DBAPIError) as refused, engine.begin() as c:
        c.execute(text("CREATE TEMPORARY TABLE whole_text (value_text TEXT)"))
        c.execute(text("CREATE INDEX whole_text_index ON whole_text (value_text)"))
        c.execute(text("INSERT INTO whole_text VALUES (:v)"), {"v": value})
    assert _sqlstate(refused.value) == "54000", str(refused.value)
    with engine.begin() as c:
        c.execute(text("SET LOCAL session_replication_role = replica"))
        row = _rows("spub_sp6mig0009aaaa", "sprun_sp6mig0009aaaa")["schedule_p6_field_values"]
        c.execute(
            insert(tables.schedule_p6_field_values).values(
                **{**row, "field_key": "xer:TASK.note", "value_ts": None, "value_text": value}
            )
        )
