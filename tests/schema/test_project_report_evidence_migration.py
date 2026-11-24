"""Project reports WP3P-S3: the project report evidence revision, `0d4e247d03cb`.

`0d4e247d03cb` is additive on `61fafdfd2986` (WP3b) and creates the twelve
project-report tables (Manager rulings D1, D2, D6, D10, D11), their indexes,
the `project_report_current_derivations` view and their guards. It alters
nothing that existed before it. This module proves:

* **the graph** -- this revision, directly on `61fafdfd2986`, on the one chain;
* **the freeze** -- the revision imports nothing from the package it migrates
  and names every column, constraint and index `tables.py` declares; its closed
  sets are frozen literals equal to the live domain vocabularies; on a live
  server the catalog it builds equals the catalog `tables.py` builds;
* **offline SQL** for both directions: every lock taken up front in one fixed
  order, the downgrade refusal before any drop;
* on disposable databases: the upgrade from empty and from `61fafdfd2986`; the
  round trip on empty; the downgrade refusal while any row exists; every
  CHECK, UNIQUE, FOREIGN KEY and trigger case; the binding pointer's named
  mutable columns; the view's current-derivation semantics; the NUMERIC(20,4)
  round trip;
* the WP3P-F1 insert guards: a supersedes 2-cycle in one multi-row INSERT is
  refused on both chained tables (B1) while a first-then-successor chain in
  one statement is accepted, so the binding pointer cannot oscillate; a new
  pointer names only an unsuperseded revision (N2); a cross-check keeps its
  sides in their roles (N1); each `group_path` step is `[level, key, header]`.

**Every guard case is isolated** (the `52a829ef718a` suite's method): each
refused case is refused with its own named constraint (or by its trigger), and
then -- inside a transaction that is rolled back -- the same statement is
accepted once exactly that one constraint is dropped or that one trigger
disabled. A green run proves each guard is the one holding its case. An
identifier CHECK on a column a foreign key also holds is proved to refuse its
case first instead.

The file name routes every test here to migration-edge (`tests/db/fixtures.py`);
the tests with no `database` marker also run in FAST. Every value is synthetic.
"""

from __future__ import annotations

import ast
import io
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from enum import StrEnum
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, Table, delete, insert, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from my_pa.domain.project_reports import model
from my_pa.domain.project_reports.reconciliation import CROSS_CHECK_KIND
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import (
    METADATA,
    PROJECT_REPORT_TABLES,
    ingest_snapshots,
    ingest_sources,
    project_report_binding_revisions,
    project_report_bindings,
    project_report_current_derivations,
    project_report_derivations,
    project_report_line_values,
    projects,
)
from my_pa.infrastructure.project_reports.pulse_csv import Terminator

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "0d4e247d03cb"
PREVIOUS: Final = "61fafdfd2986"
MIGRATION: Final = (
    ROOT / "migrations" / "versions" / "20261124_0d4e247d03cb_project_report_evidence.py"
)

TABLES: Final = tuple(table.name for table in PROJECT_REPORT_TABLES)
VIEW: Final = "project_report_current_derivations"
POINTER: Final = "project_report_bindings"
APPEND_ONLY_TABLES: Final = tuple(name for name in TABLES if name != POINTER)
POINTER_TRIGGER: Final = "project_report_bindings_move_only_forward"
#: B1: a row supersedes only a row that already exists (trigger = function name).
REVISION_SUPERSEDES: Final = "project_report_binding_revisions_supersede_an_existing_one"
DERIVATION_SUPERSEDES: Final = "project_report_derivations_supersede_an_existing_one"
#: N2: a new pointer names an unsuperseded revision.
POINTER_INSERT: Final = "project_report_bindings_name_an_unsuperseded_revision"
#: N1: a cross-check's sides keep their roles (left buyout, right reconciliation).
CROSS_CHECK_ROLES: Final = "project_report_cross_checks_keep_their_roles"
#: `(table, trigger)` of each BEFORE INSERT guard, which is also its function.
INSERT_GUARDS: Final = (
    ("project_report_binding_revisions", REVISION_SUPERSEDES),
    ("project_report_derivations", DERIVATION_SUPERSEDES),
    (POINTER, POINTER_INSERT),
    ("project_report_cross_checks", CROSS_CHECK_ROLES),
)
TRIGGERS: Final = frozenset(
    {f"{t}_are_append_only" for t in APPEND_ONLY_TABLES}
    | {f"{t}_refuse_truncate" for t in TABLES}
    | {POINTER_TRIGGER}
    | {trigger for _table, trigger in INSERT_GUARDS}
)
FUNCTIONS: Final = frozenset(
    {
        POINTER_TRIGGER,
        "project_reports_rows_are_append_only",
        "project_reports_refuse_truncate",
    }
    | {trigger for _table, trigger in INSERT_GUARDS}
)
INDEXES: Final = frozenset(index.name for table in PROJECT_REPORT_TABLES for index in table.indexes)
#: The existing tables the revision touches, only as foreign-key targets.
REFERENCED: Final = ("ingest_sources", "ingest_snapshots", "projects")

P: Final = "prn_prmigprincipal01"
OTHER: Final = "prn_prmigprincipal02"
WHEN: Final = datetime(2026, 11, 24, 12, tzinfo=UTC)
SHA_A: Final = "a" * 64
SHA_B: Final = "b" * 64
SHA_C: Final = "c" * 64
SHA_D: Final = "d" * 64
SHA_E: Final = "f" * 64
SHA_F: Final = "1" * 64
SIGNATURE: Final = "e" * 64
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


def _flat() -> str:
    return _WHITESPACE.sub(" ", _source())


def _in_list(check: str) -> set[str]:
    """The literals of the `<check> CHECK (... IN (...))` the revision writes."""
    match = re.search(rf"CONSTRAINT {check} CHECK \((.*?)\),? (?:CONSTRAINT|\))", _flat())
    assert match is not None, check
    body = match.group(1)
    inner = body[body.rindex(" IN (") :]
    return set(re.findall(r"'([^']+)'", inner))


def _values(enum: type[StrEnum]) -> set[str]:
    return {member.value for member in enum}


# ---- the graph --------------------------------------------------------------


def test_the_revision_is_directly_on_the_meeting_sync_revision_on_the_one_chain() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(PREVIOUS).down_revision == "52a829ef718a"
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


def test_the_declared_tables_are_exactly_the_revisions_twelve() -> None:
    created = re.findall(r"CREATE TABLE knowledge\.(\w+) \(", _source())
    assert tuple(created) == TABLES
    assert len(TABLES) == 12
    assert all(name.startswith("project_report_") for name in TABLES)


@pytest.mark.parametrize("table", PROJECT_REPORT_TABLES, ids=lambda t: t.name)
def test_the_frozen_ddl_names_every_declared_column_constraint_and_index(table: Table) -> None:
    source = _source()
    flat = _flat()
    assert f"CREATE TABLE knowledge.{table.name} (" in source
    for column in table.c:
        assert re.search(rf"\b{column.name}\b", source), column.name
    for constraint in table.constraints:
        if constraint.name is not None:
            assert str(constraint.name) in source, constraint.name
    for index in table.indexes:
        assert f"INDEX {index.name} ON knowledge.{table.name}" in flat, index.name


def test_the_declared_indexes_are_exactly_the_revisions() -> None:
    created = set(re.findall(r"CREATE (?:UNIQUE )?INDEX (\w+) ON", _flat()))
    assert created == INDEXES


def test_every_new_name_fits_a_postgresql_identifier() -> None:
    """A longer name would be truncated silently by the server in raw SQL."""
    names = {
        str(constraint.name)
        for table in PROJECT_REPORT_TABLES
        for constraint in table.constraints
        if constraint.name is not None
    }
    names |= INDEXES | TRIGGERS | FUNCTIONS | {VIEW}
    assert max(len(name) for name in names) <= 63, sorted(n for n in names if len(n) > 63)


#: `(constraint, live closed set)`: each frozen IN-list equals the domain's set,
#: so a member added on either side is a reviewed change on both.
_FROZEN_SETS: Final = (
    ("a_binding_revision_state_is_known", _values(model.BindingState)),
    ("a_binding_state_is_known", _values(model.BindingState)),
    ("a_binding_revision_reason_is_known", _values(model.BindingReason)),
    ("a_report_snapshot_header_terminator_is_known", _values(Terminator)),
    ("a_report_row_terminator_is_known", _values(Terminator)),
    ("a_derivation_state_is_known", _values(model.DerivationState)),
    ("a_derivation_quarantine_reason_is_known", _values(model.QuarantineReason)),
    ("a_derivation_family_is_known", _values(model.RecordFamily)),
    ("a_derivation_view_is_known", _values(model.FamilyView)),
    ("a_derivation_completeness_is_known", _values(model.CompletenessClass)),
    ("a_derivation_trigger_is_known", _values(model.DerivationTrigger)),
    ("a_row_role_is_known", _values(model.RowRole)),
    ("a_report_record_family_is_known", _values(model.RecordFamily)),
    ("a_report_record_identity_basis_is_known", _values(model.IdentityBasis)),
    ("a_report_line_family_is_known", _values(model.RecordFamily)),
    ("a_report_line_view_is_known", _values(model.FamilyView)),
    ("a_report_line_kind_is_known", _values(model.LineKind)),
    ("a_report_line_identity_state_is_known", _values(model.IdentityState)),
    ("a_report_line_observation_state_is_known", _values(model.ObservationState)),
    ("a_report_line_status_class_is_known", _values(model.StatusClass)),
    ("a_line_value_kind_is_known", _values(model.ValueKind)),
    ("a_stated_total_scope_is_known", _values(model.TotalScope)),
    ("a_stated_total_additivity_is_known", _values(model.Additivity)),
    ("a_stated_total_outcome_is_known", _values(model.ReconciliationOutcome)),
    ("a_cross_check_outcome_is_known", _values(model.ReconciliationOutcome)),
    ("a_cross_check_kind_is_known", {CROSS_CHECK_KIND}),
)


@pytest.mark.parametrize(("check", "members"), _FROZEN_SETS, ids=[c for c, _ in _FROZEN_SETS])
def test_each_frozen_closed_set_equals_the_live_vocabulary(check: str, members: set[str]) -> None:
    assert _in_list(check) == members


def test_the_frozen_literals() -> None:
    flat = _flat()
    for prefix in ("prbnd", "prrec", "prdrv"):
        assert f"'^{prefix}_[A-Za-z0-9]{{8,64}}$'" in flat
    assert "SET LOCAL lock_timeout = '10s'" in flat
    # The view pairs are exactly the domain's view-to-family map.
    pairs = set(re.findall(r"\('([a-z_]+)', '([a-z_]+)'\)", flat))
    assert {(f.value, v.value) for v, f in model.FAMILY_OF_VIEW.items()} <= pairs
    # Money and numbers at four decimal places.
    assert flat.count("NUMERIC(20, 4)") == 5
    # The cross-check role guard names the kind and the two views by their values.
    assert f"NEW.check_kind = '{CROSS_CHECK_KIND}'" in flat
    for view in (model.FamilyView.BUYOUT_SUMMARY, model.FamilyView.RECONCILIATION):
        assert f"d.family_view IS DISTINCT FROM '{view.value}'" in flat
    # No capability, purpose or audit restatement; no lifecycle vocabulary change.
    code = _source().split('"""', 2)[2]
    for word in ("audit_events", "capability_is_known", "purpose_is_known", "GRANT"):
        assert word not in code, word
    assert "ALTER TABLE" not in code


# ---- offline SQL ---------------------------------------------------------------


def test_the_offline_upgrade_takes_its_locks_first_and_emits_the_whole_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{PREVIOUS}:{REVISION}")
    timeout = rendered.index("SET LOCAL lock_timeout")
    lock = rendered.index(
        "LOCK TABLE knowledge.ingest_sources, knowledge.ingest_snapshots, knowledge.projects "
        "IN SHARE ROW EXCLUSIVE MODE"
    )
    first_ddl = min(
        rendered.index(statement)
        for statement in ("CREATE TABLE", "CREATE INDEX", "CREATE FUNCTION", "CREATE VIEW")
    )
    assert timeout < lock < first_ddl
    assert rendered.count("LOCK TABLE") == 1
    # The upgrade's order is the downgrade's order for the tables both lock.
    down_lock = _offline_downgrade_lock(monkeypatch)
    assert sorted(REFERENCED, key=down_lock.index) == list(REFERENCED)
    for table in TABLES:
        assert f"CREATE TABLE knowledge.{table} (" in rendered
    for index in INDEXES:
        assert re.search(rf"CREATE (UNIQUE )?INDEX {index} ON", rendered), index
    for function in FUNCTIONS:
        assert f"CREATE FUNCTION knowledge.{function}()" in rendered
    for trigger in TRIGGERS:
        assert f"CREATE TRIGGER {trigger}" in rendered
    assert f"CREATE VIEW knowledge.{VIEW} AS" in rendered
    assert "GRANT" not in rendered
    assert f"SET version_num='{REVISION}'" in rendered


def _offline_downgrade_lock(monkeypatch: pytest.MonkeyPatch) -> str:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    start = rendered.index("LOCK TABLE")
    return rendered[start : rendered.index("IN ACCESS EXCLUSIVE MODE", start)]


def test_the_offline_downgrade_locks_refuses_first_and_unwinds_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    timeout = rendered.index("SET LOCAL lock_timeout")
    lock = rendered.index("LOCK TABLE knowledge.project_report_cross_checks")
    refusal = rendered.index("refusing to downgrade 0d4e247d03cb")
    assert timeout < lock < refusal
    assert rendered.count("LOCK TABLE") == 1
    locked = re.findall(r"knowledge\.(\w+)", _offline_downgrade_lock(monkeypatch))
    # Child before parent, then the referenced tables in the upgrade's order.
    assert locked == [*reversed(TABLES), *REFERENCED]
    for table in TABLES:
        assert f"EXISTS (SELECT 1 FROM knowledge.{table})" in rendered  # noqa: S608
    for trigger in TRIGGERS:
        assert rendered.index(f"DROP TRIGGER {trigger}") > refusal
    for function in FUNCTIONS:
        assert rendered.index(f"DROP FUNCTION knowledge.{function}()") > refusal
    for index in INDEXES:
        assert rendered.index(f"DROP INDEX knowledge.{index}") > refusal
    view = rendered.index(f"DROP VIEW knowledge.{VIEW} RESTRICT")
    drops = [rendered.index(f"DROP TABLE knowledge.{table} RESTRICT") for table in TABLES]
    assert refusal < view < min(drops)
    assert drops == sorted(drops, reverse=True)  # child before parent
    assert f"SET version_num='{PREVIOUS}'" in rendered


# ---- disposable databases -------------------------------------------------------


@pytest.fixture
def engine(cloned_database_url: str) -> Iterator[Engine]:
    """A current-head clone, which carries this revision."""
    built = create_database_engine(cloned_database_url)
    try:
        yield built
    finally:
        built.dispose()


_CATALOG_QUERIES: Final = {
    "columns": (
        "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
        "pg_get_expr(d.adbin, d.adrelid) FROM pg_attribute a "
        "JOIN pg_class c ON c.oid = a.attrelid JOIN pg_namespace n ON n.oid = c.relnamespace "
        "LEFT JOIN pg_attrdef d ON d.adrelid = a.attrelid AND d.adnum = a.attnum "
        "WHERE n.nspname = 'knowledge' AND c.relname = ANY(:tables) AND a.attnum > 0 "
        "AND NOT a.attisdropped"
    ),
    "constraints": (
        "SELECT r.relname, c.conname, pg_get_constraintdef(c.oid) FROM pg_constraint c "
        "JOIN pg_class r ON r.oid = c.conrelid JOIN pg_namespace n ON n.oid = r.relnamespace "
        "WHERE n.nspname = 'knowledge' AND r.relname = ANY(:tables)"
    ),
    "indexes": (
        "SELECT tablename, indexname, indexdef FROM pg_indexes "
        "WHERE schemaname = 'knowledge' AND tablename = ANY(:tables)"
    ),
}


def _shape(engine: Engine) -> dict[str, set[tuple[Any, ...]]]:
    with engine.connect() as connection:
        return {
            key: {tuple(row) for row in connection.execute(text(sql), {"tables": list(TABLES)})}
            for key, sql in _CATALOG_QUERIES.items()
        }


def _catalog(engine: Engine) -> dict[str, set[str]]:
    queries = {
        "tables": "SELECT tablename FROM pg_tables WHERE schemaname = :schema",
        "views": "SELECT viewname FROM pg_views WHERE schemaname = :schema",
        "indexes": "SELECT indexname FROM pg_indexes WHERE schemaname = :schema",
        "triggers": (
            "SELECT t.tgname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
            "JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE NOT t.tgisinternal AND n.nspname = :schema"
        ),
        "functions": (
            "SELECT p.proname FROM pg_proc p "
            "JOIN pg_namespace n ON n.oid = p.pronamespace WHERE n.nspname = :schema"
        ),
    }
    with engine.connect() as connection:
        catalog = {
            key: set(connection.execute(text(sql), {"schema": SCHEMA}).scalars())
            for key, sql in queries.items()
        }
        catalog["version"] = set(
            connection.execute(text("SELECT version_num FROM alembic_version")).scalars()
        )
    return catalog


def _assert_present(engine: Engine) -> None:
    catalog = _catalog(engine)
    assert catalog["version"] == {REVISION}
    assert catalog["tables"] >= set(TABLES)
    assert VIEW in catalog["views"]
    assert catalog["indexes"] >= INDEXES
    assert catalog["triggers"] >= TRIGGERS
    assert catalog["functions"] >= FUNCTIONS


def _assert_absent(engine: Engine) -> None:
    catalog = _catalog(engine)
    assert catalog["version"] == {PREVIOUS}
    assert not catalog["tables"] & set(TABLES)
    assert VIEW not in catalog["views"]
    assert not catalog["indexes"] & INDEXES
    assert not catalog["triggers"] & TRIGGERS
    assert not catalog["functions"] & FUNCTIONS


@pytest.mark.database
def test_the_revision_builds_exactly_the_catalog_tables_py_declares(engine: Engine) -> None:
    """The freeze, on the server: revision-built and `tables.py`-built are identical."""
    migrated = _shape(engine)
    command.downgrade(_config(), PREVIOUS)
    METADATA.create_all(engine, tables=list(PROJECT_REPORT_TABLES))
    try:
        declared = _shape(engine)
    finally:
        METADATA.drop_all(engine, tables=list(PROJECT_REPORT_TABLES))
    for key in _CATALOG_QUERIES:
        assert migrated[key] == declared[key], (
            key,
            sorted(migrated[key] - declared[key]),
            sorted(declared[key] - migrated[key]),
        )
    assert len(migrated["columns"]) == sum(len(t.c) for t in PROJECT_REPORT_TABLES)


@pytest.mark.database
def test_the_view_exposes_exactly_the_derivation_columns(engine: Engine) -> None:
    with engine.connect() as connection:
        columns = connection.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'knowledge' AND table_name = :name ORDER BY ordinal_position"
            ),
            {"name": VIEW},
        ).all()
        table = connection.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_schema = 'knowledge' AND table_name = :name ORDER BY ordinal_position"
            ),
            {"name": "project_report_derivations"},
        ).all()
    assert columns == table
    assert [c.name for c in project_report_current_derivations.c] == [row[0] for row in columns]


@pytest.mark.database
def test_the_revision_round_trips_from_the_meeting_sync_revision(engine: Engine) -> None:
    _assert_present(engine)
    command.downgrade(_config(), PREVIOUS)
    _assert_absent(engine)
    command.upgrade(_config(), REVISION)
    _assert_present(engine)


@pytest.mark.database
def test_the_revision_upgrades_from_an_empty_database(empty_database_url: str) -> None:
    built = create_database_engine(empty_database_url)
    try:
        command.upgrade(_config(), REVISION)
        _assert_present(built)
        command.downgrade(_config(), PREVIOUS)
        _assert_absent(built)
    finally:
        built.dispose()


@pytest.mark.database
def test_every_foreign_key_is_composite_with_the_principal_and_restricts(engine: Engine) -> None:
    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT r.relname, c.conname, c.confdeltype, "
                "(SELECT array_agg(a.attname::text) FROM pg_attribute a "
                " WHERE a.attrelid = c.conrelid AND a.attnum = ANY(c.conkey)) "
                "FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid "
                "JOIN pg_namespace n ON n.oid = r.relnamespace "
                "WHERE c.contype = 'f' AND n.nspname = 'knowledge' AND r.relname = ANY(:t)"
            ),
            {"t": list(TABLES)},
        ).all()
    declared = sum(
        1
        for table in PROJECT_REPORT_TABLES
        for constraint in table.constraints
        if type(constraint).__name__ == "ForeignKeyConstraint"
    )
    assert len(rows) == declared == 24
    for table, name, deltype, columns in rows:
        assert deltype == "r", (table, name)
        assert "principal_id" in columns, (table, name)


# ---- the seed ----------------------------------------------------------------------


def _id(prefix: str, tag: str) -> str:
    return f"{prefix}_prmig{tag}"


@dataclass
class _Seed:
    """A valid row of every table, synthetic, under `P` (plus `OTHER`'s parents)."""

    s: str = _id("isrc", "src0001")
    s2: str = _id("isrc", "src0002")
    s3: str = _id("isrc", "src0003")
    other_source: str = _id("isrc", "src0009")
    pj: str = _id("prj", "prj0001")
    pj2: str = _id("prj", "prj0002")
    pj3: str = _id("prj", "prj0003")
    other_project: str = _id("prj", "prj0009")
    sn: str = _id("isnp", "snp0001")
    sn2: str = _id("isnp", "snp0002")
    sn3: str = _id("isnp", "snp0003")
    sn4: str = _id("isnp", "snp0004")
    sn5: str = _id("isnp", "snp0005")
    sn6: str = _id("isnp", "snp0006")
    other_snapshot: str = _id("isnp", "snp0009")
    r1: str = _id("prbnd", "rev0001")
    r2: str = _id("prbnd", "rev0002")
    r3: str = _id("prbnd", "rev0003")
    r5: str = _id("prbnd", "rev0005")
    other_revision: str = _id("prbnd", "rev0009")
    d1: str = _id("prdrv", "drv0001")
    d2: str = _id("prdrv", "drv0002")
    #: The cross-check sides: a buyout summary and a reconciliation (and its successor).
    d_buy: str = _id("prdrv", "buy0001")
    d_rec: str = _id("prdrv", "rec0001")
    d_rec2: str = _id("prdrv", "rec0002")
    rec: str = _id("prrec", "rec0001")
    rec_buyout: str = _id("prrec", "rec0002")
    counter: list[int] = field(default_factory=lambda: [100])

    def fresh(self, prefix: str) -> str:
        self.counter[0] += 1
        return _id(prefix, f"new{self.counter[0]:04d}")

    # --- existing parents ---------------------------------------------------

    def source(self, source_id: str, principal: str = P) -> dict[str, object]:
        return {
            "ingest_source_id": source_id,
            "principal_id": principal,
            "consumer": "pulse_csv_export",
            "workspace_id": "mcp",
            "path_prefix": f"exports/{source_id[-4:]}/",
            "file_pattern": "*.csv",
            "enabled": True,
            "admitted_at": WHEN,
            "admitted_by": "operator_cli",
        }

    def lifecycle(
        self, snapshot_id: str, source_id: str, sha: str, principal: str = P
    ) -> dict[str, object]:
        return {
            "snapshot_id": snapshot_id,
            "principal_id": principal,
            "ingest_source_id": source_id,
            "file_sha256": sha,
            "byte_count": 10,
            "observed_version_token": None,
            "first_seen_at": WHEN,
            "status": "pending",
            "rejection_code": None,
            "parser_version": None,
        }

    def project(self, project_id: str, principal: str = P) -> dict[str, object]:
        return {
            "project_id": project_id,
            "principal_id": principal,
            "name": f"Synthetic project {project_id[-4:]}",
            "opened_at": WHEN,
            "created_at": WHEN,
            "updated_at": WHEN,
            "project_number": f"SYN-{project_id[-4:]}",
        }

    # --- the twelve tables --------------------------------------------------

    def revision(self, revision_id: str, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "binding_revision_id": revision_id,
            "principal_id": P,
            "ingest_source_id": self.s,
            "project_id": self.pj,
            "declared_project_number": "SYN-0001",
            "state": "active",
            "supersedes_revision_id": None,
            "currency": "USD",
            "recorded_at": WHEN,
            "recorded_by": "operator_cli",
            "change_set_sha256": SHA_A,
            "reason_code": "initial",
        }
        return {**row, **overrides}

    def declaration(self, slug: str = "open-rfis", **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "binding_revision_id": self.r1,
            "slug_label": slug,
            "description": "Synthetic filter: open items only",
            "declared_at": WHEN,
        }
        return {**row, **overrides}

    def binding(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "ingest_source_id": self.s3,
            "binding_revision_id": self.r5,
            "project_id": self.pj3,
            "state": "active",
        }
        return {**row, **overrides}

    def snapshot(self, snapshot_id: str, sha: str, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "snapshot_id": snapshot_id,
            "ingest_source_id": self.s,
            "file_sha256": sha,
            "bom_present": False,
            "header_raw_record": "A,B,C",
            "header_terminator": "lf",
            "header_cells": ["A", "B", "C"],
            "header_signature": SIGNATURE,
            "signature_version": "pulse_header_signature_v1",
            "reader_version": "pulse_csv_reader_v1",
            "data_row_count": 8,
            "embedded_line_break_count": 0,
            "reconstruction_sha256": sha,
        }
        return {**row, **overrides}

    def raw_row(self, ordinal: int, snapshot_id: str | None = None, **overrides: object) -> dict:
        row: dict[str, object] = {
            "principal_id": P,
            "snapshot_id": snapshot_id or self.sn,
            "row_ordinal": ordinal,
            "raw_record": f"x{ordinal},y,z",
            "terminator": "lf",
            "cells": [f"x{ordinal}", "y", "z"],
            "width_matches": True,
        }
        return {**row, **overrides}

    def derivation(self, derivation_id: str, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "derivation_id": derivation_id,
            "principal_id": P,
            "snapshot_id": self.sn,
            "ingest_source_id": self.s,
            "binding_revision_id": self.r1,
            "project_id": self.pj,
            "state": "classified",
            "quarantine_reason": None,
            "record_family": "rfis",
            "family_view": "open_outstanding",
            "adapter_version": "pulse_adapter_v1",
            "identity_version": "project_report_identity_v1",
            "status_map_version": "status_map_v1",
            "completeness_class": "populated",
            "role_counts": {"detail": 2, "group_header": 1, "grand_total": 1},
            "reconciliation": {"group_columns": {"match": 1}},
            "trigger": "ingest",
            "supersedes_derivation_id": None,
            "derived_at": WHEN,
        }
        return {**row, **overrides}

    def quarantined(self, derivation_id: str, **overrides: object) -> dict[str, object]:
        row = self.derivation(
            derivation_id,
            state="quarantined",
            quarantine_reason="malformed_ratio_exceeded",
            completeness_class=None,
            role_counts={"unclassified": 8},
        )
        del row["reconciliation"]
        return {**row, **overrides}

    def role(self, ordinal: int, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "derivation_id": self.d1,
            "row_ordinal": ordinal,
            "snapshot_id": self.sn,
            "row_role": "spacer",
            "row_reason": None,
            "group_level": None,
            "group_key": None,
            "group_path": [],
            "parent_header_ordinal": None,
        }
        return {**row, **overrides}

    def record(self, record_id: str, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "record_id": record_id,
            "principal_id": P,
            "project_id": self.pj,
            "record_family": "rfis",
            "identity_key": f"rfi:{record_id[-4:]}",
            "identity_version": "project_report_identity_v1",
            "identity_basis": "exported_number",
            "created_by_derivation_id": self.d1,
        }
        return {**row, **overrides}

    def line(self, ordinal: int, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "derivation_id": self.d1,
            "row_ordinal": ordinal,
            "row_role": "detail",
            "project_id": self.pj,
            "record_family": "rfis",
            "family_view": "open_outstanding",
            "line_kind": "rfi_row",
            "record_id": self.rec,
            "identity_state": "identified",
            "identity_reason": None,
            "observation_state": "typed",
            "degraded_reasons": [],
            "status_raw": "Open",
            "status_class": "open",
            "identifier_prefix": "RFI",
            "identifier_numeric_suffix": 7,
        }
        return {**row, **overrides}

    def value(self, field_key: str = "rfi.subject", **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "derivation_id": self.d1,
            "row_ordinal": 2,
            "field_key": field_key,
            "value_kind": "text",
            "raw_text": "Synthetic subject",
            "value_reason": None,
            "value_decimal": None,
            "value_date": None,
            "value_boolean": None,
            "value_text": "Synthetic subject",
        }
        return {**row, **overrides}

    def total(self, column: int = 6, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "derivation_id": self.d1,
            "row_ordinal": 1,
            "column_index": column,
            "row_role": "group_header",
            "scope": "group",
            "group_level": 1,
            "group_key": "Group A",
            "field_key": "rfi.count",
            "raw_text": "",
            "value": None,
            "additivity": "non_additive",
            "computed_value": None,
            "outcome": "not_checked",
        }
        return {**row, **overrides}

    def cross_check(self, **overrides: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "check_kind": CROSS_CHECK_KIND,
            "left_derivation_id": self.d_buy,
            "right_derivation_id": self.d_rec,
            "project_id": self.pj,
            "date_label": "20261124",
            "left_value": None,
            "right_value": None,
            "outcome": "not_checked",
            "checked_at": WHEN,
        }
        return {**row, **overrides}

    # --- planting -------------------------------------------------------------

    def plant_parents(self, connection: Connection) -> None:
        for source in (self.s, self.s2, self.s3):
            connection.execute(insert(ingest_sources).values(**self.source(source)))
        connection.execute(insert(ingest_sources).values(**self.source(self.other_source, OTHER)))
        for project in (self.pj, self.pj2, self.pj3):
            connection.execute(insert(projects).values(**self.project(project)))
        connection.execute(insert(projects).values(**self.project(self.other_project, OTHER)))
        for snapshot, sha in ((self.sn, SHA_A), (self.sn2, SHA_B), (self.sn3, SHA_C)):
            connection.execute(
                insert(ingest_snapshots).values(**self.lifecycle(snapshot, self.s, sha))
            )
        for snapshot, sha in ((self.sn4, SHA_D), (self.sn5, SHA_E), (self.sn6, SHA_F)):
            connection.execute(
                insert(ingest_snapshots).values(**self.lifecycle(snapshot, self.s, sha))
            )
        connection.execute(
            insert(ingest_snapshots).values(
                **self.lifecycle(self.other_snapshot, self.other_source, SHA_A, OTHER)
            )
        )

    def plant(self, connection: Connection) -> None:
        self.plant_parents(connection)
        t = _TABLE
        rev = t["project_report_binding_revisions"]
        connection.execute(insert(rev).values(**self.revision(self.r1)))
        pointer = t[POINTER]
        # The pointer is planted on `r1` before `r2` supersedes it (N2).
        connection.execute(
            insert(pointer).values(
                **self.binding(
                    ingest_source_id=self.s, binding_revision_id=self.r1, project_id=self.pj
                )
            )
        )
        connection.execute(
            insert(rev).values(
                **self.revision(self.r2, supersedes_revision_id=self.r1, reason_code="correction")
            )
        )
        connection.execute(
            insert(rev).values(
                **self.revision(self.r3, ingest_source_id=self.s2, project_id=self.pj2)
            )
        )
        connection.execute(
            insert(rev).values(
                **self.revision(self.r5, ingest_source_id=self.s3, project_id=self.pj3)
            )
        )
        connection.execute(
            insert(rev).values(
                **self.revision(
                    self.other_revision,
                    principal_id=OTHER,
                    ingest_source_id=self.other_source,
                    project_id=self.other_project,
                )
            )
        )
        connection.execute(
            insert(t["project_report_filter_declarations"]).values(**self.declaration())
        )
        connection.execute(
            insert(pointer).values(
                **self.binding(
                    ingest_source_id=self.s2, binding_revision_id=self.r3, project_id=self.pj2
                )
            )
        )
        snapshots, rows = t["project_report_snapshots"], t["project_report_rows"]
        connection.execute(insert(snapshots).values(**self.snapshot(self.sn, SHA_A)))
        for ordinal in range(1, 9):
            connection.execute(insert(rows).values(**self.raw_row(ordinal)))
        connection.execute(
            insert(snapshots).values(
                **self.snapshot(self.sn2, SHA_B, header_terminator="none", data_row_count=0)
            )
        )
        connection.execute(
            insert(snapshots).values(**self.snapshot(self.sn4, SHA_D, data_row_count=1))
        )
        connection.execute(insert(rows).values(**self.raw_row(1, self.sn4)))
        derivations = t["project_report_derivations"]
        connection.execute(insert(derivations).values(**self.derivation(self.d1)))
        quarantine = self.derivation(
            self.d2,
            snapshot_id=self.sn2,
            state="quarantined",
            quarantine_reason="unknown_header_signature",
            record_family=None,
            family_view=None,
            adapter_version=None,
            completeness_class=None,
            role_counts={"unclassified": 0},
        )
        del quarantine["reconciliation"]
        connection.execute(insert(derivations).values(**quarantine))
        # The cross-check sides, each on its own report snapshot.
        for snapshot, sha in ((self.sn5, SHA_E), (self.sn6, SHA_F)):
            connection.execute(
                insert(snapshots).values(**self.snapshot(snapshot, sha, data_row_count=0))
            )
        connection.execute(
            insert(derivations).values(
                **self.derivation(
                    self.d_buy,
                    snapshot_id=self.sn5,
                    record_family="buyout",
                    family_view="buyout_summary",
                )
            )
        )
        reconciliation = {
            "snapshot_id": self.sn6,
            "record_family": "change_order_reconciliation",
            "family_view": "reconciliation",
        }
        connection.execute(
            insert(derivations).values(**self.derivation(self.d_rec, **reconciliation))
        )
        connection.execute(
            insert(derivations).values(
                **self.derivation(
                    self.d_rec2,
                    trigger="rederive_adapter",
                    supersedes_derivation_id=self.d_rec,
                    **reconciliation,
                )
            )
        )
        roles = t["project_report_row_roles"]
        header = [[1, "Group A", 1]]
        connection.execute(
            insert(roles).values(
                **self.role(
                    1,
                    row_role="group_header",
                    group_level=1,
                    group_key="Group A",
                    group_path=header,
                )
            )
        )
        for ordinal in (2, 3):
            connection.execute(
                insert(roles).values(
                    **self.role(
                        ordinal, row_role="detail", group_path=header, parent_header_ordinal=1
                    )
                )
            )
        connection.execute(insert(roles).values(**self.role(4, row_role="grand_total")))
        records = t["project_report_records"]
        connection.execute(insert(records).values(**self.record(self.rec)))
        connection.execute(
            insert(records).values(
                **self.record(
                    self.rec_buyout, record_family="buyout", identity_key="commitment:1@a"
                )
            )
        )
        connection.execute(insert(t["project_report_lines"]).values(**self.line(2)))
        values = t["project_report_line_values"]
        connection.execute(insert(values).values(**self.value()))
        connection.execute(
            insert(values).values(
                **self.value(
                    "rfi.count",
                    value_kind="number",
                    raw_text="3",
                    value_text=None,
                    value_decimal=Decimal(3),
                )
            )
        )
        connection.execute(
            insert(values).values(
                **self.value(
                    "rfi.due_date",
                    value_kind="date",
                    raw_text="1/2/2026",
                    value_text=None,
                    value_date=date(2026, 1, 2),
                )
            )
        )
        connection.execute(
            insert(t["project_report_stated_totals"]).values(
                **self.total(
                    5,
                    raw_text="3",
                    value=Decimal(3),
                    additivity="additive",
                    computed_value=Decimal(3),
                    outcome="match",
                )
            )
        )
        connection.execute(insert(t["project_report_cross_checks"]).values(**self.cross_check()))


_TABLE: Final = {table.name: table for table in PROJECT_REPORT_TABLES}


@pytest.fixture
def seeded(engine: Engine) -> tuple[Engine, _Seed]:
    seed = _Seed()
    with engine.begin() as connection:
        seed.plant(connection)
    return engine, seed


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


def _constraint(error: DBAPIError) -> str | None:
    diag = getattr(error.orig, "diag", None)
    return None if diag is None else diag.constraint_name


def _attempt(
    engine: Engine, statement: Callable[[Connection], Any], *, prelude: str = ""
) -> DBAPIError | None:
    """Run `statement` in a transaction that is always rolled back; return its error."""
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            if prelude:
                connection.execute(text(prelude))
            statement(connection)
        except DBAPIError as error:
            return error
        finally:
            transaction.rollback()
    return None


def _isolated(
    engine: Engine,
    statement: Callable[[Connection], Any],
    *,
    sqlstate: str,
    constraint: str | None,
    lift: str,
    prelude: str = "",
) -> str | None:
    """`None` when `statement` is refused with `sqlstate` (and `constraint`) and
    accepted once `lift` runs first; otherwise what went wrong."""
    refused = _attempt(engine, statement, prelude=prelude)
    if refused is None:
        return "accepted, expected a refusal"
    if _sqlstate(refused) != sqlstate:
        return f"refused with {_sqlstate(refused)} ({_constraint(refused)}), expected {sqlstate}"
    if constraint is not None and _constraint(refused) != constraint:
        return f"refused by {_constraint(refused)}, expected {constraint}"
    lifted = _attempt(engine, statement, prelude="; ".join(p for p in (prelude, lift) if p))
    if lifted is not None:
        return f"still refused once lifted: {_sqlstate(lifted)} ({_constraint(lifted)})"
    return None


def _inserting(table: str, *rows: dict[str, object]) -> Callable[[Connection], Any]:
    def run(connection: Connection) -> None:
        for row in rows:
            connection.execute(insert(_TABLE[table]).values(**row))

    return run


_INSERT_GUARD_NAMES: Final = frozenset(trigger for _table, trigger in INSERT_GUARDS)


def _drop(table: str, *constraints: str) -> str:
    """DROP each named constraint; DISABLE each named BEFORE INSERT guard trigger."""
    return "; ".join(
        f"ALTER TABLE knowledge.{table} DISABLE TRIGGER {constraint}"
        if constraint in _INSERT_GUARD_NAMES
        else f"ALTER TABLE knowledge.{table} DROP CONSTRAINT {constraint} CASCADE"
        for constraint in constraints
    )


# ---- CHECK constraints -----------------------------------------------------------------

#: `(table, constraint, row, also_dropped)`: the row violates exactly that CHECK
#: once the `also_dropped` constraints (which the same value necessarily breaks
#: too) are dropped first.
_CheckCase = tuple[str, str, dict[str, object], tuple[str, ...]]


def _check_cases(s: _Seed) -> list[_CheckCase]:
    rev, decl, snap, row = (
        "project_report_binding_revisions",
        "project_report_filter_declarations",
        "project_report_snapshots",
        "project_report_rows",
    )
    drv, role, rec, line = (
        "project_report_derivations",
        "project_report_row_roles",
        "project_report_records",
        "project_report_lines",
    )
    val, tot, cc = (
        "project_report_line_values",
        "project_report_stated_totals",
        "project_report_cross_checks",
    )
    # A first revision of a fresh source of `P` would collide with nothing; the
    # binding-revision cases supersede `r2` so the first-per-source index holds.
    fresh_revision = lambda **o: s.revision(  # noqa: E731
        s.fresh("prbnd"), **{"supersedes_revision_id": s.r2, "reason_code": "correction", **o}
    )
    fresh_snapshot = lambda **o: s.snapshot(s.sn3, SHA_C, **o)  # noqa: E731
    fresh_derivation = lambda **o: s.derivation(  # noqa: E731
        s.fresh("prdrv"), snapshot_id=s.sn4, **o
    )
    fresh_quarantine = lambda **o: s.quarantined(  # noqa: E731
        s.fresh("prdrv"), snapshot_id=s.sn4, **o
    )
    fresh_record = lambda **o: s.record(s.fresh("prrec"), **o)  # noqa: E731
    fresh_value = lambda **o: s.value("rfi.title", **o)  # noqa: E731
    unclassifiable = ("a_derivation_role_counts_name_its_roles",)
    return [
        (
            rev,
            "a_binding_revision_project_number_is_bounded",
            fresh_revision(declared_project_number="  "),
            (),
        ),
        (rev, "a_binding_revision_state_is_known", fresh_revision(state="paused"), ()),
        (
            rev,
            "a_binding_revision_does_not_supersede_itself",
            s.revision(_id("prbnd", "self0001"), supersedes_revision_id=_id("prbnd", "self0001")),
            (REVISION_SUPERSEDES,),
        ),
        (
            rev,
            "a_retired_binding_revision_supersedes_one",
            s.revision(s.fresh("prbnd"), ingest_source_id=s.s3, state="retired", project_id=s.pj3),
            ("one_first_binding_revision_per_source",),
        ),
        (rev, "a_binding_revision_currency_is_a_code", fresh_revision(currency="usd"), ()),
        (
            rev,
            "a_binding_revision_is_recorded_by_the_operator_cli",
            fresh_revision(recorded_by="worker"),
            (),
        ),
        (rev, "a_binding_revision_change_set_is_sha256", fresh_revision(change_set_sha256="x"), ()),
        (rev, "a_binding_revision_reason_is_known", fresh_revision(reason_code="bogus"), ()),
        (
            POINTER,
            "a_binding_state_is_known",
            s.binding(state="paused"),
            ("a_binding_equals_the_revision_it_names",),
        ),
        (decl, "a_filter_declaration_slug_is_bounded", s.declaration("a/b"), ()),
        (
            decl,
            "a_filter_declaration_description_is_bounded",
            s.declaration("blank", description="   "),
            (),
        ),
        (
            snap,
            "a_report_snapshot_digest_is_sha256",
            fresh_snapshot(file_sha256="x", reconstruction_sha256="x"),
            (
                "a_report_snapshot_reconstruction_is_sha256",
                "a_report_snapshot_names_a_lifecycle_snapshot_of_its_digest",
            ),
        ),
        (snap, "a_report_snapshot_signature_is_sha256", fresh_snapshot(header_signature="x"), ()),
        (
            snap,
            "a_report_snapshot_reconstruction_is_sha256",
            fresh_snapshot(reconstruction_sha256="x"),
            ("a_report_snapshot_reconstructs_its_file",),
        ),
        (
            snap,
            "a_report_snapshot_reconstructs_its_file",
            fresh_snapshot(reconstruction_sha256=SHA_D),
            (),
        ),
        (snap, "a_report_snapshot_header_is_not_empty", fresh_snapshot(header_raw_record=""), ()),
        (
            snap,
            "a_report_snapshot_header_terminator_is_known",
            fresh_snapshot(header_terminator="lflf"),
            (),
        ),
        (
            snap,
            "only_a_header_only_report_snapshot_lacks_a_terminator",
            fresh_snapshot(header_terminator="none"),
            (),
        ),
        (
            snap,
            "a_report_snapshot_header_cells_is_a_non_empty_array",
            fresh_snapshot(header_cells=[]),
            (),
        ),
        (
            snap,
            "a_report_snapshot_signature_version_is_a_token",
            fresh_snapshot(signature_version="Bad Version"),
            (),
        ),
        (
            snap,
            "a_report_snapshot_reader_version_is_a_token",
            fresh_snapshot(reader_version="Bad"),
            (),
        ),
        (
            snap,
            "a_report_snapshot_count_is_non_negative",
            fresh_snapshot(embedded_line_break_count=-1),
            (),
        ),
        (row, "a_report_row_ordinal_is_positive", s.raw_row(0), ()),
        (row, "a_report_row_terminator_is_known", s.raw_row(9, terminator="x"), ()),
        (row, "a_report_row_cells_is_a_non_empty_array", s.raw_row(9, cells=[]), ()),
        (drv, "a_derivation_state_is_known", fresh_derivation(state="x"), unclassifiable),
        (
            drv,
            "a_derivation_quarantine_reason_is_known",
            fresh_quarantine(quarantine_reason="x"),
            (),
        ),
        (
            drv,
            "a_quarantined_derivation_names_its_reason",
            fresh_derivation(quarantine_reason="malformed_ratio_exceeded"),
            (),
        ),
        (
            drv,
            "a_derivation_family_is_known",
            fresh_derivation(record_family="x"),
            ("a_derivation_view_belongs_to_its_family",),
        ),
        (
            drv,
            "a_derivation_view_is_known",
            fresh_derivation(family_view="x"),
            ("a_derivation_view_belongs_to_its_family",),
        ),
        (
            drv,
            "a_derivation_view_belongs_to_its_family",
            fresh_derivation(record_family="buyout"),
            (),
        ),
        (drv, "a_derivation_adapter_is_whole", fresh_derivation(adapter_version=None), ()),
        (
            drv,
            "a_derivation_names_its_adapter_unless_its_signature_is_unknown",
            fresh_derivation(record_family=None, family_view=None, adapter_version=None),
            (),
        ),
        (
            drv,
            "a_derivation_adapter_version_is_a_token",
            fresh_derivation(adapter_version="Bad"),
            (),
        ),
        (
            drv,
            "a_derivation_identity_version_is_a_token",
            fresh_derivation(identity_version="Bad"),
            (),
        ),
        (
            drv,
            "a_derivation_status_map_version_is_a_token",
            fresh_derivation(status_map_version="Bad"),
            (),
        ),
        (drv, "a_derivation_completeness_is_known", fresh_derivation(completeness_class="x"), ()),
        (
            drv,
            "a_classified_derivation_names_its_completeness",
            fresh_derivation(completeness_class=None),
            (),
        ),
        (
            drv,
            "a_derivation_role_counts_are_counts",
            fresh_derivation(role_counts={"detail": -1}),
            (),
        ),
        (
            drv,
            "a_derivation_role_counts_name_its_roles",
            fresh_derivation(role_counts={"bogus": 1}),
            (),
        ),
        (
            drv,
            "a_derivation_reconciliation_is_an_object_when_classified",
            fresh_derivation(reconciliation=["not", "an", "object"]),
            (),
        ),
        (
            drv,
            "a_derivation_trigger_is_known",
            fresh_derivation(trigger="x"),
            ("only_a_first_derivation_is_an_ingest",),
        ),
        (
            drv,
            "only_a_first_derivation_is_an_ingest",
            fresh_derivation(trigger="rederive_adapter"),
            ("one_first_derivation_per_report_snapshot",),
        ),
        (
            drv,
            "a_derivation_does_not_supersede_itself",
            s.derivation(
                _id("prdrv", "self0001"),
                snapshot_id=s.sn4,
                trigger="rederive_adapter",
                supersedes_derivation_id=_id("prdrv", "self0001"),
            ),
            (DERIVATION_SUPERSEDES,),
        ),
        (
            role,
            "a_row_role_ordinal_is_positive",
            s.role(0),
            ("a_row_role_names_a_raw_row_of_its_snapshot",),
        ),
        (role, "a_row_role_is_known", s.role(5, row_role="x"), ()),
        (
            role,
            "a_row_role_reason_is_a_malformed_width",
            s.role(5, row_reason="width_mismatch"),
            (),
        ),
        (
            role,
            "a_row_role_group_level_is_one_or_two",
            s.role(5, row_role="group_header", group_level=3, group_key="Group B"),
            (),
        ),
        (role, "a_row_role_header_names_its_level_and_key", s.role(5, row_role="group_header"), ()),
        (
            role,
            "a_row_role_group_path_is_an_array",
            s.role(5, group_path={"level": 1}),
            (),
        ),
        (
            role,
            "a_row_role_group_path_steps_are_level_key_and_header",
            s.role(5, group_path=[[1, "Group A"]]),
            (),
        ),
        (role, "a_row_role_parent_header_precedes_it", s.role(5, parent_header_ordinal=9), ()),
        (rec, "a_report_record_family_is_known", fresh_record(record_family="x"), ()),
        (rec, "a_report_record_identity_key_is_bounded", fresh_record(identity_key="nocolon"), ()),
        (
            rec,
            "a_report_record_identity_version_is_a_token",
            fresh_record(identity_version="Bad"),
            (),
        ),
        (rec, "a_report_record_identity_basis_is_known", fresh_record(identity_basis="x"), ()),
        (
            line,
            "a_report_line_is_a_detail_row",
            s.line(3, row_role="spacer"),
            ("a_report_line_names_a_detail_row_of_its_derivation",),
        ),
        (
            line,
            "a_report_line_family_is_known",
            s.line(3, record_family="x", record_id=None, identity_state="identity_missing"),
            ("a_report_line_names_a_derivation_of_its_view",),
        ),
        (
            line,
            "a_report_line_view_is_known",
            s.line(3, family_view="x"),
            ("a_report_line_names_a_derivation_of_its_view",),
        ),
        (line, "a_report_line_kind_is_known", s.line(3, line_kind="x"), ()),
        (
            line,
            "a_report_line_identity_state_is_known",
            s.line(3, identity_state="x", record_id=None),
            (),
        ),
        (line, "a_report_line_identity_reason_is_known", s.line(3, identity_reason="x"), ()),
        (
            line,
            "an_identified_report_line_names_its_record",
            s.line(3, identity_state="snapshot_scoped"),
            (),
        ),
        (line, "a_report_line_observation_state_is_known", s.line(3, observation_state="x"), ()),
        (
            line,
            "a_report_line_degraded_reason_is_known",
            s.line(3, observation_state="degraded", degraded_reasons=["width_mismatch"]),
            (),
        ),
        (
            line,
            "a_degraded_report_line_names_its_reasons",
            s.line(3, observation_state="degraded"),
            (),
        ),
        (line, "a_report_line_status_class_is_known", s.line(3, status_class="x"), ()),
        (line, "a_report_line_status_text_has_a_class", s.line(3, status_class=None), ()),
        (
            line,
            "a_report_line_identifier_suffix_is_non_negative",
            s.line(3, identifier_numeric_suffix=-1),
            (),
        ),
        (
            line,
            "a_report_line_identifier_prefix_has_a_suffix",
            s.line(3, identifier_numeric_suffix=None),
            (),
        ),
        (val, "a_line_value_field_key_is_a_catalogue_key", s.value("nodot"), ()),
        (
            val,
            "a_line_value_kind_is_known",
            fresh_value(value_kind="x"),
            ("a_line_value_is_held_only_by_its_kinds_column",),
        ),
        (val, "a_line_value_reason_is_known", fresh_value(value_reason="x", value_text=None), ()),
        (
            val,
            "a_line_value_reason_needs_its_text",
            fresh_value(raw_text="", value_reason="type_error", value_text=None),
            (),
        ),
        (val, "a_line_value_is_held_only_by_its_kinds_column", fresh_value(value_kind="money"), ()),
        (
            val,
            "a_line_value_is_typed_exactly_when_its_text_parses",
            fresh_value(value_text=None),
            (),
        ),
        (val, "a_line_text_value_is_its_raw_text", fresh_value(value_text="Another subject"), ()),
        (
            tot,
            "a_stated_total_row_is_a_total_row",
            s.total(row_role="detail", row_ordinal=2, scope="group"),
            (
                "a_stated_total_names_a_total_row_of_its_derivation",
                "a_stated_total_scope_matches_its_row",
            ),
        ),
        (
            tot,
            "a_stated_total_scope_is_known",
            s.total(scope="x"),
            ("a_stated_total_names_its_group_exactly_in_group_scope",),
        ),
        (
            tot,
            "a_stated_total_scope_matches_its_row",
            s.total(scope="grand", group_level=None, group_key=None),
            (),
        ),
        (
            tot,
            "a_stated_total_names_its_group_exactly_in_group_scope",
            s.total(group_level=None),
            (),
        ),
        (tot, "a_stated_total_column_is_non_negative", s.total(-1), ()),
        (tot, "a_stated_total_field_key_is_a_catalogue_key", s.total(field_key="nodot"), ()),
        (tot, "a_stated_total_additivity_is_known", s.total(additivity="x"), ()),
        (
            tot,
            "a_stated_total_outcome_is_known",
            s.total(outcome="x"),
            ("a_stated_total_is_checked_exactly_when_additive",),
        ),
        (
            tot,
            "a_stated_total_is_checked_exactly_when_additive",
            s.total(additivity="additive"),
            (),
        ),
        (
            tot,
            "a_matched_stated_total_equals_its_sum",
            s.total(
                additivity="additive", outcome="match", value=Decimal(3), computed_value=Decimal(4)
            ),
            (),
        ),
        (
            tot,
            "a_both_empty_stated_total_holds_no_value",
            s.total(additivity="additive", outcome="both_empty", value=Decimal(3)),
            (),
        ),
        (tot, "an_unchecked_stated_total_holds_no_sum", s.total(computed_value=Decimal(3)), ()),
        (cc, "a_cross_check_kind_is_known", s.cross_check(check_kind="x"), ()),
        (
            cc,
            "a_cross_check_date_label_is_a_date_prefix",
            s.cross_check(right_derivation_id=s.d_rec2, date_label="2026-11"),
            (),
        ),
        (
            cc,
            "a_cross_check_outcome_is_known",
            s.cross_check(right_derivation_id=s.d_rec2, outcome="x"),
            (),
        ),
        (
            cc,
            "a_cross_check_names_two_derivations",
            s.cross_check(right_derivation_id=s.d_buy),
            (CROSS_CHECK_ROLES,),
        ),
        (
            cc,
            "a_matched_cross_check_agrees",
            s.cross_check(
                right_derivation_id=s.d_rec2,
                outcome="match",
                left_value=Decimal(1),
                right_value=Decimal(2),
            ),
            (),
        ),
        (
            cc,
            "an_unchecked_cross_check_holds_no_value",
            s.cross_check(right_derivation_id=s.d_rec2, left_value=Decimal(1)),
            (),
        ),
    ]


def _dropping(table: str, constraint: str) -> str:
    """DROP for a constraint or (a partial unique) index."""
    if constraint.startswith("one_first_") or constraint.startswith("one_active_"):
        return f"DROP INDEX knowledge.{constraint}"
    return _drop(table, constraint)


@pytest.mark.database
def test_every_check_refuses_its_case_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _check_cases(seed)
    failures = [
        (table, constraint, problem)
        for table, constraint, row, also in cases
        if (
            problem := _isolated(
                engine,
                _inserting(table, row),
                sqlstate=CHECK,
                constraint=constraint,
                lift=_drop(table, constraint),
                prelude="; ".join(_dropping(table, other) for other in also),
            )
        )
        is not None
    ]
    assert failures == []
    covered = {(table, constraint) for table, constraint, _row, _also in cases}
    declared = {
        (table.name, str(constraint.name))
        for table in PROJECT_REPORT_TABLES
        for constraint in table.constraints
        if type(constraint).__name__ == "CheckConstraint"
        and not str(constraint.name).endswith("_is_an_opaque_identifier")
    }
    assert declared - covered == set()


def _identifier_cases(s: _Seed) -> list[tuple[str, str, dict[str, object]]]:
    """Every opaque-identifier CHECK, with a valid fresh row of its table."""
    base: dict[str, dict[str, object]] = {
        "project_report_binding_revisions": s.revision(
            s.fresh("prbnd"), supersedes_revision_id=s.r2, reason_code="correction"
        ),
        "project_report_filter_declarations": s.declaration("fresh-slug"),
        "project_report_bindings": s.binding(),
        "project_report_snapshots": s.snapshot(s.sn3, SHA_C),
        "project_report_rows": s.raw_row(9),
        "project_report_derivations": s.derivation(s.fresh("prdrv"), snapshot_id=s.sn4),
        "project_report_row_roles": s.role(5),
        "project_report_records": s.record(s.fresh("prrec")),
        "project_report_lines": s.line(3),
        "project_report_line_values": s.value("rfi.title"),
        "project_report_stated_totals": s.total(),
        "project_report_cross_checks": s.cross_check(right_derivation_id=s.d_rec2),
    }
    cases = []
    for table in PROJECT_REPORT_TABLES:
        for constraint in table.constraints:
            name = str(constraint.name)
            if type(constraint).__name__ == "CheckConstraint" and name.endswith(
                "_is_an_opaque_identifier"
            ):
                column = name.removesuffix("_is_an_opaque_identifier")
                row = {**base[table.name], column: "bad-id"}
                if column == "supersedes_derivation_id":
                    row["trigger"] = "rederive_adapter"  # a successor, not an ingest
                cases.append((table.name, name, row))
    return cases


@pytest.mark.database
def test_every_identifier_check_refuses_its_case_first(seeded: tuple[Engine, _Seed]) -> None:
    """Identifier columns a foreign key also holds: the CHECK is the one that refuses."""
    engine, seed = seeded
    cases = _identifier_cases(seed)
    assert len(cases) == 42

    # A row whose `supersedes_*` (or, for a revision, whose Principal or source)
    # is malformed names no existing row, which the B1 guard refuses before any
    # CHECK runs (BEFORE triggers precede constraints): the guard is disabled
    # there so the CHECK is the one proved.
    def prelude_of(table: str, constraint: str) -> str:
        if table == "project_report_binding_revisions":
            return _drop(table, REVISION_SUPERSEDES)
        if constraint == "supersedes_derivation_id_is_an_opaque_identifier":
            return _drop(table, DERIVATION_SUPERSEDES)
        return ""

    failures = []
    for table, constraint, row in cases:
        prelude = prelude_of(table, constraint)
        refused = _attempt(engine, _inserting(table, row), prelude=prelude)
        if refused is None or (_sqlstate(refused), _constraint(refused)) != (CHECK, constraint):
            failures.append((table, constraint, None if refused is None else _constraint(refused)))
    assert failures == []


# ---- UNIQUE keys ---------------------------------------------------------------------


def _unique_cases(s: _Seed) -> list[tuple[str, str, Callable[[Connection], Any]]]:
    rev = "project_report_binding_revisions"
    drv = "project_report_derivations"
    six = _id("prbnd", "rev0006")
    return [
        (
            rev,
            "one_binding_revision_supersedes_each",
            _inserting(
                rev,
                s.revision(s.fresh("prbnd"), supersedes_revision_id=s.r1, reason_code="correction"),
            ),
        ),
        (
            rev,
            "one_first_binding_revision_per_source",
            _inserting(rev, s.revision(s.fresh("prbnd"))),
        ),
        (
            "project_report_bindings",
            "one_active_project_report_binding_per_project",
            # A second folder bound, active, to the Project `s` is already bound to.
            lambda connection: (
                _inserting(
                    rev,
                    s.revision(
                        six,
                        ingest_source_id=s.s3,
                        supersedes_revision_id=s.r5,
                        reason_code="correction",
                    ),
                )(connection),
                _inserting(POINTER, s.binding(binding_revision_id=six, project_id=s.pj))(
                    connection
                ),
            ),
        ),
        (
            drv,
            "one_derivation_supersedes_each",
            _inserting(
                drv,
                s.derivation(
                    _id("prdrv", "sup0001"),
                    trigger="rederive_adapter",
                    supersedes_derivation_id=s.d1,
                ),
                s.derivation(
                    _id("prdrv", "sup0002"),
                    trigger="rederive_adapter",
                    supersedes_derivation_id=s.d1,
                ),
            ),
        ),
        (
            drv,
            "one_first_derivation_per_report_snapshot",
            _inserting(drv, s.derivation(s.fresh("prdrv"))),
        ),
        (
            "project_report_records",
            "one_report_record_per_identity",
            _inserting(
                "project_report_records", s.record(s.fresh("prrec"), identity_key="rfi:0001")
            ),
        ),
    ]


@pytest.mark.database
def test_every_unique_key_refuses_its_duplicate_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _unique_cases(seed)
    failures = [
        (table, constraint, problem)
        for table, constraint, statement in cases
        if (
            problem := _isolated(
                engine,
                statement,
                sqlstate=UNIQUE,
                constraint=constraint,
                lift=_dropping(table, constraint),
            )
        )
        is not None
    ]
    assert failures == []
    declared = {
        str(constraint.name)
        for table in PROJECT_REPORT_TABLES
        for constraint in table.constraints
        if type(constraint).__name__ == "UniqueConstraint"
    } | {
        str(index.name)
        for table in PROJECT_REPORT_TABLES
        for index in table.indexes
        if index.unique
    }
    covered = {constraint for _table, constraint, _statement in cases}
    # The `..._is_identified_..._` keys exist to be foreign-key targets.
    assert {name for name in declared - covered if "_is_identified_" not in name} == set()


@pytest.mark.database
def test_a_second_active_binding_for_one_project_is_refused(seeded: tuple[Engine, _Seed]) -> None:
    """D-OQ-06 v1: one folder per Project; a retired second binding is accepted."""
    engine, seed = seeded
    six = _id("prbnd", "rev0006")

    def bind(state: str) -> Callable[[Connection], Any]:
        def run(connection: Connection) -> None:
            connection.execute(
                insert(project_report_binding_revisions).values(
                    **seed.revision(
                        six,
                        ingest_source_id=seed.s3,
                        supersedes_revision_id=seed.r5,
                        reason_code="correction",
                        state=state,
                    )
                )
            )
            connection.execute(
                insert(project_report_bindings).values(
                    **seed.binding(binding_revision_id=six, project_id=seed.pj, state=state)
                )
            )

        return run

    refused = _attempt(engine, bind("active"))
    assert refused is not None
    assert (_sqlstate(refused), _constraint(refused)) == (
        UNIQUE,
        "one_active_project_report_binding_per_project",
    )
    assert _attempt(engine, bind("retired")) is None


# ---- FOREIGN KEY constraints -------------------------------------------------------------


def _foreign_cases(s: _Seed) -> list[tuple[str, str, dict[str, object], tuple[str, ...]]]:
    rev, decl, ptr = (
        "project_report_binding_revisions",
        "project_report_filter_declarations",
        POINTER,
    )
    snap, row, drv = (
        "project_report_snapshots",
        "project_report_rows",
        "project_report_derivations",
    )
    role, rec, line = (
        "project_report_row_roles",
        "project_report_records",
        "project_report_lines",
    )
    val, tot, cc = (
        "project_report_line_values",
        "project_report_stated_totals",
        "project_report_cross_checks",
    )
    missing = _id("prdrv", "missing01")
    superseding = {"supersedes_revision_id": s.r2, "reason_code": "correction"}
    return [
        (
            rev,
            "a_binding_revision_names_a_source_of_its_principal",
            s.revision(s.fresh("prbnd"), ingest_source_id=s.other_source),
            (),
        ),
        (
            rev,
            "a_binding_revision_names_a_project_of_its_principal",
            s.revision(s.fresh("prbnd"), project_id=s.other_project, **superseding),
            (),
        ),
        (
            rev,
            "a_binding_revision_supersedes_a_revision_of_its_source",
            s.revision(s.fresh("prbnd"), supersedes_revision_id=s.r3, reason_code="correction"),
            (REVISION_SUPERSEDES,),
        ),
        (
            decl,
            "a_filter_declaration_names_a_revision_of_its_principal",
            s.declaration(binding_revision_id=s.other_revision),
            (),
        ),
        (
            ptr,
            "a_binding_names_a_source_of_its_principal",
            s.binding(ingest_source_id=s.other_source),
            ("a_binding_equals_the_revision_it_names",),
        ),
        (
            ptr,
            "a_binding_names_a_project_of_its_principal",
            s.binding(project_id=s.other_project),
            ("a_binding_equals_the_revision_it_names",),
        ),
        (ptr, "a_binding_equals_the_revision_it_names", s.binding(state="retired"), ()),
        # The digest key: the head names the lifecycle snapshot with another digest.
        (
            snap,
            "a_report_snapshot_names_a_lifecycle_snapshot_of_its_digest",
            s.snapshot(s.sn3, SHA_B),
            (),
        ),
        (
            snap,
            "a_report_snapshot_names_a_lifecycle_snapshot_of_its_source",
            s.snapshot(s.sn3, SHA_C, ingest_source_id=s.s2),
            (),
        ),
        (row, "a_report_row_names_a_snapshot_of_its_principal", s.raw_row(1, s.sn3), ()),
        (
            drv,
            "a_derivation_names_a_report_snapshot_of_its_source",
            s.derivation(s.fresh("prdrv"), snapshot_id=s.sn3),
            (),
        ),
        (
            drv,
            "a_derivation_names_a_binding_revision_of_its_source",
            s.derivation(
                s.fresh("prdrv"), snapshot_id=s.sn4, binding_revision_id=s.r3, project_id=s.pj2
            ),
            (),
        ),
        (
            drv,
            "a_derivation_supersedes_a_derivation_of_its_snapshot",
            s.derivation(
                s.fresh("prdrv"),
                snapshot_id=s.sn4,
                trigger="rederive_adapter",
                supersedes_derivation_id=s.d1,
            ),
            (DERIVATION_SUPERSEDES,),
        ),
        (
            role,
            "a_row_role_names_a_derivation_of_its_snapshot",
            s.role(1, derivation_id=s.d2, snapshot_id=s.sn4),
            (),
        ),
        (role, "a_row_role_names_a_raw_row_of_its_snapshot", s.role(9), ()),
        (
            rec,
            "a_report_record_names_a_project_of_its_principal",
            s.record(s.fresh("prrec"), project_id=s.other_project),
            ("a_report_record_names_a_derivation_of_its_project",),
        ),
        (
            rec,
            "a_report_record_names_a_derivation_of_its_project",
            s.record(s.fresh("prrec"), project_id=s.pj2),
            (),
        ),
        (line, "a_report_line_names_a_detail_row_of_its_derivation", s.line(4), ()),
        (
            line,
            "a_report_line_names_a_derivation_of_its_view",
            s.line(3, family_view="recently_closed"),
            (),
        ),
        (
            line,
            "a_report_line_names_a_record_of_its_project",
            s.line(3, record_id=s.rec_buyout),
            (),
        ),
        (val, "a_line_value_names_a_line_of_its_derivation", s.value(row_ordinal=3), ()),
        (tot, "a_stated_total_names_a_total_row_of_its_derivation", s.total(row_ordinal=2), ()),
        (
            cc,
            "a_cross_check_left_names_a_derivation_of_its_project",
            s.cross_check(left_derivation_id=missing),
            (),
        ),
        (
            cc,
            "a_cross_check_right_names_a_derivation_of_its_project",
            s.cross_check(right_derivation_id=missing),
            (),
        ),
    ]


@pytest.mark.database
def test_every_foreign_key_refuses_a_crossing_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _foreign_cases(seed)
    failures = [
        (table, constraint, problem)
        for table, constraint, row, also in cases
        if (
            problem := _isolated(
                engine,
                _inserting(table, row),
                sqlstate=FOREIGN,
                constraint=constraint,
                lift=_drop(table, constraint),
                prelude="; ".join(_drop(table, other) for other in also),
            )
        )
        is not None
    ]
    assert failures == []
    declared = {
        str(constraint.name)
        for table in PROJECT_REPORT_TABLES
        for constraint in table.constraints
        if type(constraint).__name__ == "ForeignKeyConstraint"
    }
    assert declared - {constraint for _t, constraint, _r, _a in cases} == set()


@pytest.mark.database
def test_a_report_snapshot_carries_the_lifecycle_digest(seeded: tuple[Engine, _Seed]) -> None:
    """The head's `file_sha256` is the digest of the lifecycle snapshot it names."""
    engine, seed = seeded
    refused = _attempt(
        engine, _inserting("project_report_snapshots", seed.snapshot(seed.sn3, SHA_B))
    )
    assert refused is not None
    assert (_sqlstate(refused), _constraint(refused)) == (
        FOREIGN,
        "a_report_snapshot_names_a_lifecycle_snapshot_of_its_digest",
    )
    assert (
        _attempt(engine, _inserting("project_report_snapshots", seed.snapshot(seed.sn3, SHA_C)))
        is None
    )


@pytest.mark.database
def test_a_snapshot_whose_records_do_not_reconstruct_its_file_is_refused(
    seeded: tuple[Engine, _Seed],
) -> None:
    engine, seed = seeded
    refused = _attempt(
        engine,
        _inserting(
            "project_report_snapshots", seed.snapshot(seed.sn3, SHA_C, reconstruction_sha256=SHA_A)
        ),
    )
    assert refused is not None
    assert _constraint(refused) == "a_report_snapshot_reconstructs_its_file"


@pytest.mark.database
@pytest.mark.parametrize("kind", sorted(_values(model.ValueKind)))
def test_a_line_value_is_held_only_by_its_kinds_column(
    seeded: tuple[Engine, _Seed], kind: str
) -> None:
    engine, seed = seeded
    held = {
        "value_decimal": Decimal(1),
        "value_date": date(2026, 1, 2),
        "value_boolean": True,
        "value_text": "1",
    }
    own = {"money": "value_decimal", "number": "value_decimal", "date": "value_date"}
    own |= {"boolean": "value_boolean", "text": "value_text", "identifier": "value_text"}
    for column, value in held.items():
        row = seed.value(
            f"rfi.k{column[6:]}",
            **{"value_kind": kind, "raw_text": "1", "value_text": None, column: value},
        )
        refused = _attempt(engine, _inserting("project_report_line_values", row))
        if column == own[kind]:
            assert refused is None, (kind, column)
        else:
            assert refused is not None, (kind, column)
            assert _constraint(refused) == "a_line_value_is_held_only_by_its_kinds_column"
    # An empty cell holds no value of any kind.
    empty = seed.value("rfi.empty", value_kind=kind, raw_text="", value_text=None)
    assert _attempt(engine, _inserting("project_report_line_values", empty)) is None


@pytest.mark.database
def test_money_round_trips_at_numeric_20_4(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    amounts = (
        Decimal("9999999999999999.9999"),
        Decimal("-9999999999999999.9999"),
        Decimal("-0.0001"),
        Decimal("1234.5000"),
    )
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            for index, amount in enumerate(amounts):
                connection.execute(
                    insert(project_report_line_values).values(
                        **seed.value(
                            f"buyout.amount_{index}",
                            value_kind="money",
                            raw_text=str(amount),
                            value_text=None,
                            value_decimal=amount,
                        )
                    )
                )
            stored = (
                connection.execute(
                    select(project_report_line_values.c.value_decimal)
                    .where(project_report_line_values.c.field_key.like("buyout.amount_%"))
                    .order_by(project_report_line_values.c.field_key)
                )
                .scalars()
                .all()
            )
        finally:
            transaction.rollback()
    assert stored == list(amounts)
    assert all(value.as_tuple().exponent == -4 for value in stored)
    overflow = seed.value(
        "buyout.overflow",
        value_kind="money",
        raw_text="1e16",
        value_text=None,
        value_decimal=Decimal("10000000000000000"),
    )
    refused = _attempt(engine, _inserting("project_report_line_values", overflow))
    assert refused is not None
    assert _sqlstate(refused) == "22003"


# ---- triggers ------------------------------------------------------------------------


@pytest.mark.database
@pytest.mark.parametrize("table", APPEND_ONLY_TABLES)
def test_every_append_only_table_refuses_update_and_delete_by_its_trigger(
    seeded: tuple[Engine, _Seed], table: str
) -> None:
    engine, _seed = seeded
    t = _TABLE[table]
    # The column every table has; rewriting it to itself is still an UPDATE.
    column = next(c.name for c in t.c if c.name not in ("principal_id",))
    trigger = f"{table}_are_append_only"
    lift = f"ALTER TABLE knowledge.{table} DISABLE TRIGGER {trigger}"
    statements: dict[str, Callable[[Connection], Any]] = {
        "update": lambda c: c.execute(
            update(t).where(t.c.principal_id == P).values({column: t.c[column]})
        ),
        # A real row: a DELETE that matches nothing fires no row trigger.
        "delete": lambda c: c.execute(
            text(
                f"DELETE FROM knowledge.{table} "  # noqa: S608
                f"WHERE ctid = (SELECT min(ctid) FROM knowledge.{table})"
            )
        ),
    }
    failures = []
    for kind, statement in statements.items():
        refused = _attempt(engine, statement)
        if refused is None or _sqlstate(refused) != RESTRICT_VIOLATION:
            failures.append((kind, "not refused"))
        elif f"{table} is append-only" not in str(refused):
            failures.append((kind, "refused by something else"))
    if _attempt(engine, statements["update"], prelude=lift) is not None:
        failures.append(("update", "still refused with the trigger disabled"))
    assert failures == []


@pytest.mark.database
def test_a_row_role_and_a_raw_row_cannot_be_rewritten(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    roles, rows = _TABLE["project_report_row_roles"], _TABLE["project_report_rows"]
    for statement in (
        lambda c: c.execute(
            update(roles)
            .where(roles.c.derivation_id == seed.d1, roles.c.row_ordinal == 3)
            .values(row_role="spacer")
        ),
        lambda c: c.execute(
            update(rows)
            .where(rows.c.snapshot_id == seed.sn, rows.c.row_ordinal == 1)
            .values(raw_record="edited,y,z", cells=["edited", "y", "z"])
        ),
    ):
        refused = _attempt(engine, statement)
        assert refused is not None
        assert _sqlstate(refused) == RESTRICT_VIOLATION
        assert "is append-only" in str(refused)


def _move(seed: _Seed, revision: str, **values: object) -> Callable[[Connection], Any]:
    p = project_report_bindings

    def run(connection: Connection) -> None:
        connection.execute(
            update(p)
            .where(p.c.principal_id == P, p.c.ingest_source_id == seed.s)
            .values(binding_revision_id=revision, **values)
        )

    return run


@pytest.mark.database
def test_the_binding_pointer_moves_only_to_the_revision_superseding_its_own(
    seeded: tuple[Engine, _Seed],
) -> None:
    engine, seed = seeded
    lift = f"ALTER TABLE knowledge.{POINTER} DISABLE TRIGGER {POINTER_TRIGGER}"
    # Forward, to `r2` (which supersedes `r1`): accepted.
    assert _attempt(engine, _move(seed, seed.r2)) is None

    # To `r7`, which supersedes `r2`, not `r1`: refused by the trigger alone.
    seven = _id("prbnd", "rev0007")

    def skip(connection: Connection) -> None:
        connection.execute(
            insert(project_report_binding_revisions).values(
                **seed.revision(seven, supersedes_revision_id=seed.r2, reason_code="correction")
            )
        )
        _move(seed, seven)(connection)

    problem = _isolated(engine, skip, sqlstate=RESTRICT_VIOLATION, constraint=None, lift=lift)
    assert problem is None
    # Back to a revision it superseded: refused.
    with engine.begin() as connection:
        _move(seed, seed.r2)(connection)
    back = _attempt(engine, _move(seed, seed.r1))
    assert back is not None
    assert _sqlstate(back) == RESTRICT_VIOLATION
    assert "moves only to the revision superseding its own" in str(back)


@pytest.mark.database
def test_the_binding_pointer_changes_only_its_named_mutable_columns(
    seeded: tuple[Engine, _Seed],
) -> None:
    engine, seed = seeded
    p = project_report_bindings
    lift = f"ALTER TABLE knowledge.{POINTER} DISABLE TRIGGER {POINTER_TRIGGER}"
    moved = _attempt(
        engine,
        lambda c: c.execute(
            update(p)
            .where(p.c.principal_id == P, p.c.ingest_source_id == seed.s2)
            .values(ingest_source_id=seed.s3, binding_revision_id=seed.r5, project_id=seed.pj3)
        ),
    )
    assert moved is not None
    assert _sqlstate(moved) == RESTRICT_VIOLATION
    assert "changes only its named mutable columns" in str(moved)
    deleted = _isolated(
        engine,
        lambda c: c.execute(
            delete(p).where(p.c.principal_id == P, p.c.ingest_source_id == seed.s2)
        ),
        sqlstate=RESTRICT_VIOLATION,
        constraint=None,
        lift=lift,
    )
    assert deleted is None
    # The three named columns move together to the superseding revision.
    assert _attempt(engine, _move(seed, seed.r2, project_id=seed.pj, state="active")) is None


# ---- the insert guards: supersedes cycles (B1), the pointer (N2), the roles (N1) ----


def _one_statement(table: str, *rows: dict[str, object]) -> Callable[[Connection], Any]:
    """Every row in ONE multi-row INSERT (a self-referencing key is checked at its end)."""

    def run(connection: Connection) -> None:
        connection.execute(insert(_TABLE[table]).values(list(rows)))

    return run


def _cycle_of_revisions(s: _Seed) -> tuple[str, dict[str, object], dict[str, object]]:
    x, y = _id("prbnd", "cycx0001"), _id("prbnd", "cycy0001")
    on_s3 = {"ingest_source_id": s.s3, "project_id": s.pj3, "reason_code": "correction"}
    return (
        x,
        s.revision(x, supersedes_revision_id=y, **on_s3),
        s.revision(y, supersedes_revision_id=x, **on_s3),
    )


@pytest.mark.database
def test_a_two_cycle_of_binding_revisions_in_one_statement_is_refused(
    seeded: tuple[Engine, _Seed],
) -> None:
    """`(X supersedes Y), (Y supersedes X)` in one INSERT passes every key; the guard alone
    refuses it."""
    engine, seed = seeded
    table = "project_report_binding_revisions"
    _x, first, second = _cycle_of_revisions(seed)
    problem = _isolated(
        engine,
        _one_statement(table, first, second),
        sqlstate=RESTRICT_VIOLATION,
        constraint=REVISION_SUPERSEDES,
        lift=_drop(table, REVISION_SUPERSEDES),
    )
    assert problem is None
    # A successor of a revision that does not exist, alone, is refused too.
    alone = _attempt(engine, _one_statement(table, first))
    assert alone is not None
    assert _constraint(alone) == REVISION_SUPERSEDES


@pytest.mark.database
def test_a_two_cycle_of_derivations_in_one_statement_is_refused(
    seeded: tuple[Engine, _Seed],
) -> None:
    """Unguarded, the cycle leaves its snapshot with no current derivation."""
    engine, seed = seeded
    table = "project_report_derivations"
    x, y = _id("prdrv", "cycx0001"), _id("prdrv", "cycy0001")
    successor = {"snapshot_id": seed.sn4, "trigger": "rederive_binding"}
    cycle = _one_statement(
        table,
        seed.derivation(x, supersedes_derivation_id=y, **successor),
        seed.derivation(y, supersedes_derivation_id=x, **successor),
    )
    problem = _isolated(
        engine,
        cycle,
        sqlstate=RESTRICT_VIOLATION,
        constraint=DERIVATION_SUPERSEDES,
        lift=_drop(table, DERIVATION_SUPERSEDES),
    )
    assert problem is None
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            connection.execute(text(_drop(table, DERIVATION_SUPERSEDES)))
            cycle(connection)
            assert _current(connection, seed.sn4) == []  # the hazard the guard closes
        finally:
            transaction.rollback()


@pytest.mark.database
def test_a_first_then_successor_chain_in_one_statement_is_accepted(
    seeded: tuple[Engine, _Seed],
) -> None:
    """Each row sees the rows its statement inserted before it; order is significant."""
    engine, seed = seeded
    a, b = _id("prbnd", "chna0001"), _id("prbnd", "chnb0001")
    on_s3 = {"ingest_source_id": seed.s3, "project_id": seed.pj3, "reason_code": "correction"}
    after_r5 = seed.revision(a, supersedes_revision_id=seed.r5, **on_s3)
    after_a = seed.revision(b, supersedes_revision_id=a, **on_s3)
    revisions = "project_report_binding_revisions"
    assert _attempt(engine, _one_statement(revisions, after_r5, after_a)) is None
    backwards = _attempt(engine, _one_statement(revisions, after_a, after_r5))
    assert backwards is not None
    assert _constraint(backwards) == REVISION_SUPERSEDES
    f, g = _id("prdrv", "chnf0001"), _id("prdrv", "chng0001")
    head = seed.derivation(f, snapshot_id=seed.sn4)
    successor = seed.derivation(
        g, snapshot_id=seed.sn4, trigger="rederive_adapter", supersedes_derivation_id=f
    )
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            _one_statement("project_report_derivations", head, successor)(connection)
            assert _current(connection, seed.sn4) == [g]
        finally:
            transaction.rollback()
    backwards = _attempt(engine, _one_statement("project_report_derivations", successor, head))
    assert backwards is not None
    assert _constraint(backwards) == DERIVATION_SUPERSEDES


@pytest.mark.database
def test_the_binding_pointer_cannot_oscillate(seeded: tuple[Engine, _Seed]) -> None:
    """Only a cycle lets a forward-only pointer return; with the guards there is none."""
    engine, seed = seeded
    x, first, second = _cycle_of_revisions(seed)
    p = project_report_bindings

    def oscillate(connection: Connection) -> None:
        _one_statement("project_report_binding_revisions", first, second)(connection)
        connection.execute(
            insert(p).values(
                **seed.binding(ingest_source_id=seed.s3, binding_revision_id=x, project_id=seed.pj3)
            )
        )
        for target in (str(second["binding_revision_id"]), x, str(second["binding_revision_id"])):
            connection.execute(
                update(p)
                .where(p.c.principal_id == P, p.c.ingest_source_id == seed.s3)
                .values(binding_revision_id=target)
            )

    refused = _attempt(engine, oscillate)
    assert refused is not None
    assert _constraint(refused) == REVISION_SUPERSEDES
    unguarded = "; ".join(
        (
            _drop("project_report_binding_revisions", REVISION_SUPERSEDES),
            _drop(POINTER, POINTER_INSERT),
        )
    )
    assert _attempt(engine, oscillate, prelude=unguarded) is None  # the hazard


@pytest.mark.database
def test_a_new_pointer_names_only_an_unsuperseded_revision(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    six = _id("prbnd", "rev0006")

    def bind(revision: str) -> Callable[[Connection], Any]:
        def run(connection: Connection) -> None:
            connection.execute(
                insert(project_report_binding_revisions).values(
                    **seed.revision(
                        six,
                        ingest_source_id=seed.s3,
                        project_id=seed.pj3,
                        supersedes_revision_id=seed.r5,
                        reason_code="correction",
                    )
                )
            )
            connection.execute(
                insert(project_report_bindings).values(**seed.binding(binding_revision_id=revision))
            )

        return run

    problem = _isolated(
        engine,
        bind(seed.r5),
        sqlstate=RESTRICT_VIOLATION,
        constraint=POINTER_INSERT,
        lift=_drop(POINTER, POINTER_INSERT),
    )
    assert problem is None
    assert _attempt(engine, bind(six)) is None


@pytest.mark.database
def test_a_cross_check_keeps_its_sides_in_their_roles(seeded: tuple[Engine, _Seed]) -> None:
    """Left is the buyout summary, right the reconciliation: `(B, A)` beside `(A, B)` is
    refused, and so is a side of any other view."""
    engine, seed = seeded
    table = "project_report_cross_checks"
    for row in (
        seed.cross_check(left_derivation_id=seed.d_rec, right_derivation_id=seed.d_buy),
        seed.cross_check(right_derivation_id=seed.d1),
        seed.cross_check(left_derivation_id=seed.d1, right_derivation_id=seed.d_rec2),
        seed.cross_check(right_derivation_id=seed.d2),  # a quarantine of no view
    ):
        problem = _isolated(
            engine,
            _inserting(table, row),
            sqlstate=RESTRICT_VIOLATION,
            constraint=CROSS_CHECK_ROLES,
            lift=_drop(table, CROSS_CHECK_ROLES),
        )
        assert problem is None, (row["left_derivation_id"], row["right_derivation_id"], problem)
    assert (
        _attempt(engine, _inserting(table, seed.cross_check(right_derivation_id=seed.d_rec2)))
        is None
    )


@pytest.mark.database
def test_truncate_is_refused_on_every_table_by_its_own_trigger(
    seeded: tuple[Engine, _Seed],
) -> None:
    """Each table's own trigger refuses TRUNCATE with the other eleven disabled,
    and with all twelve disabled the statement is accepted."""
    engine, _seed = seeded
    every = [f"ALTER TABLE knowledge.{t} DISABLE TRIGGER {t}_refuse_truncate" for t in TABLES]
    failures = []
    for table in TABLES:
        others = "; ".join(line for line in every if f"knowledge.{table} " not in line)

        def statement(connection: Connection, table: str = table) -> None:
            connection.execute(text(f"TRUNCATE knowledge.{table} CASCADE"))

        alone = _attempt(engine, statement, prelude=others)
        if alone is None or _sqlstate(alone) != RESTRICT_VIOLATION:
            failures.append((table, "not refused by its own trigger alone"))
        if _attempt(engine, statement, prelude="; ".join(every)) is not None:
            failures.append((table, "refused with every TRUNCATE trigger disabled"))
    assert failures == []


# ---- the current-derivations view ----------------------------------------------------


def _current(connection: Connection, snapshot_id: str) -> list[str]:
    view = project_report_current_derivations
    return list(
        connection.execute(
            select(view.c.derivation_id)
            .where(view.c.principal_id == P, view.c.snapshot_id == snapshot_id)
            .order_by(view.c.derivation_id)
        ).scalars()
    )


@pytest.mark.database
def test_the_view_excludes_every_superseded_derivation(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    d3, d4 = _id("prdrv", "drv0003"), _id("prdrv", "drv0004")
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            assert _current(connection, seed.sn) == [seed.d1]
            connection.execute(
                insert(project_report_derivations).values(
                    **seed.derivation(
                        d3, trigger="rederive_binding", supersedes_derivation_id=seed.d1
                    )
                )
            )
            assert _current(connection, seed.sn) == [d3]
            connection.execute(
                insert(project_report_derivations).values(
                    **seed.quarantined(d4, trigger="rederive_version", supersedes_derivation_id=d3)
                )
            )
            assert _current(connection, seed.sn) == [d4]
            # The superseded rows stay, append-only, in the table.
            kept = connection.execute(
                select(project_report_derivations.c.derivation_id).where(
                    project_report_derivations.c.snapshot_id == seed.sn
                )
            ).scalars()
            assert set(kept) == {seed.d1, d3, d4}
            # Another snapshot's current derivation is untouched.
            assert _current(connection, seed.sn2) == [seed.d2]
        finally:
            transaction.rollback()


# ---- the downgrade --------------------------------------------------------------------


@pytest.mark.database
def test_a_downgrade_refuses_while_one_binding_revision_exists(engine: Engine) -> None:
    seed = _Seed()
    with engine.begin() as connection:
        seed.plant_parents(connection)
        connection.execute(
            insert(project_report_binding_revisions).values(**seed.revision(seed.r1))
        )
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION
    assert "refusing to downgrade 0d4e247d03cb" in str(refused.value)
    _assert_present(engine)


@pytest.mark.database
def test_a_downgrade_refuses_while_the_full_seed_exists(seeded: tuple[Engine, _Seed]) -> None:
    engine, _seed = seeded
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION
    _assert_present(engine)


@pytest.mark.database
def test_the_round_trip_on_empty_tables_leaves_the_lifecycle_rows(engine: Engine) -> None:
    seed = _Seed()
    with engine.begin() as connection:
        seed.plant_parents(connection)
    command.downgrade(_config(), PREVIOUS)
    _assert_absent(engine)
    command.upgrade(_config(), REVISION)
    _assert_present(engine)
    with engine.connect() as connection:
        sources = connection.execute(
            select(ingest_sources.c.ingest_source_id).where(ingest_sources.c.principal_id == P)
        ).scalars()
        assert set(sources) == {seed.s, seed.s2, seed.s3}
