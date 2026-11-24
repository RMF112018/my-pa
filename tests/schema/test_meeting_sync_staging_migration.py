"""Communications intelligence WP3b-S1: the meeting sync revision, `61fafdfd2986`.

`61fafdfd2986` is additive on `52a829ef718a` (WP3a) and creates the five meeting
sync staging and reconciliation tables, keys `ingest_snapshots` by its digest,
gives `meeting_provider_bindings` its two snapshot columns (Manager ruling D10)
and restates the audit capability vocabulary 310 -> 312 (D9). This module
proves:

* **the graph** -- this revision, directly on `52a829ef718a`, on the one chain;
  no test here names the chain head;
* **the freeze** -- the revision imports nothing from the package it migrates
  and names every column, constraint and index `tables.py` declares for it; on
  a live server the catalog it builds equals the catalog `tables.py` builds;
* **the audit vocabulary** -- the before text is a byte copy of `6418b57081c3`'s
  set, the at text adds exactly the `meetings.provider.*` names, which the domain
  declares in WP3b-S4 (the schema-ahead gap, measured here);
* **offline SQL** for both directions, without a server;
* on disposable databases: the round trip; the upgrade refusal while a binding
  records a legacy observation; the downgrade refusals; every CHECK, UNIQUE,
  FOREIGN KEY and trigger case.

**Every guard case is isolated** (the `52a829ef718a` suite's method): each
refused case is refused with its own named constraint (or by its trigger), and
then -- inside a transaction that is rolled back -- the same statement is
accepted once exactly that one constraint is dropped or that one trigger
disabled. A green run proves each guard is the one holding its case (the
prove-red, kept permanently).

The file name routes every test here to migration-edge (`tests/db/fixtures.py`);
the tests with no `database` marker also run in FAST. Every value is synthetic.
"""

from __future__ import annotations

import ast
import io
import re
from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import ColumnElement, Engine, Table, delete, insert, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError
from tests.schema.meeting_sync_vocabulary_contract import MEETING_SYNC_CAPABILITIES

from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import (
    MEETING_SYNC_TABLES,
    METADATA,
    audit_events,
    ingest_snapshots,
    ingest_sources,
    meeting_history,
    meeting_provider_bindings,
    meeting_provider_key_tombstones,
    meeting_provider_reconciliation_passes,
    meeting_provider_review_marks,
    meeting_series,
    meeting_sync_events,
    meeting_sync_publications,
    meetings,
)

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "61fafdfd2986"
PREVIOUS: Final = "52a829ef718a"
MIGRATIONS: Final = ROOT / "migrations" / "versions"
MIGRATION: Final = MIGRATIONS / "20261123_61fafdfd2986_meeting_sync_staging.py"
PRIOR_AUDIT_MIGRATION: Final = MIGRATIONS / "20261121_6418b57081c3_meeting_provider_bindings.py"

TABLES: Final = tuple(table.name for table in MEETING_SYNC_TABLES)
INDEXES: Final = frozenset(
    {
        "meeting_sync_publications_by_source",
        "meeting_sync_events_by_key",
        "meeting_provider_key_tombstones_by_key",
    }
)
APPEND_ONLY_TABLES: Final = (
    "meeting_sync_events",
    "meeting_provider_review_marks",
    "meeting_provider_reconciliation_passes",
    "meeting_provider_key_tombstones",
)
PUBLICATION_TRIGGER: Final = "meeting_sync_publications_apply_once"
ORIGIN_TRIGGER: Final = "meeting_provider_binding_origin_is_immutable"
TRIGGERS: Final = frozenset(
    {PUBLICATION_TRIGGER, ORIGIN_TRIGGER}
    | {f"{table}_are_append_only" for table in APPEND_ONLY_TABLES}
    | {f"{table}_refuse_truncate" for table in TABLES}
)
FUNCTIONS: Final = frozenset(
    {
        PUBLICATION_TRIGGER,
        "meeting_sync_rows_are_append_only",
        "meeting_sync_refuses_truncate",
        "meeting_provider_bindings_keep_their_origin",
    }
)
#: What the revision adds to the two tables that existed before it.
SNAPSHOT_DIGEST_UNIQUE: Final = "an_ingest_snapshot_is_identified_with_its_digest"
BINDING_COLUMNS: Final = frozenset({"origin_snapshot_id", "last_seen_snapshot_id"})
BINDING_CONSTRAINTS: Final = frozenset(
    {
        "origin_snapshot_id_is_an_opaque_identifier",
        "last_seen_snapshot_id_is_an_opaque_identifier",
        "a_provider_binding_last_seen_names_its_snapshot",
        "a_provider_binding_last_seen_names_a_snapshot_of_its_digest",
        "a_provider_binding_origin_names_a_snapshot_of_its_principal",
    }
)
NEW_CAPABILITIES: Final = MEETING_SYNC_CAPABILITIES

P: Final = "prn_msyncmig0001aaaa"
OTHER: Final = "prn_msyncmig0002bbbb"
WHEN: Final = datetime(2026, 11, 23, 12, tzinfo=UTC)
SHA_A: Final = "a" * 64
SHA_B: Final = "b" * 64
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


def _namespace(path: Path) -> dict[str, object]:
    namespace: dict[str, object] = {}
    exec(compile(path.read_text(encoding="utf-8"), str(path), "exec"), namespace)  # noqa: S102
    return namespace


def _literals(expression: object) -> list[str]:
    assert isinstance(expression, str)
    return re.findall(r"'([^']+)'", expression)


# ---- the graph --------------------------------------------------------------


def test_the_revision_is_directly_on_the_ingestion_revision_on_the_one_chain() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(PREVIOUS).down_revision == "6418b57081c3"
    heads = script.get_heads()
    assert len(heads) == 1
    # This revision is the head or an ancestor of it; the head itself is not named.
    assert REVISION in {revision.revision for revision in script.walk_revisions(heads[0])}


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


def test_the_declared_tables_are_exactly_the_revisions_five() -> None:
    created = re.findall(r"CREATE TABLE knowledge\.(\w+) \(", _source())
    assert tuple(created) == TABLES
    assert len(TABLES) == 5


@pytest.mark.parametrize("table", MEETING_SYNC_TABLES, ids=lambda t: t.name)
def test_the_frozen_ddl_names_every_declared_column_constraint_and_index(table: Table) -> None:
    source = _source()
    flat = _WHITESPACE.sub(" ", source)
    assert f"CREATE TABLE knowledge.{table.name} (" in source
    for column in table.c:
        assert re.search(rf"\b{column.name}\b", source), column.name
    for constraint in table.constraints:
        if constraint.name is not None:
            assert str(constraint.name) in source, constraint.name
    for index in table.indexes:
        assert f"INDEX {index.name} ON knowledge.{table.name}" in flat, index.name


def test_the_altered_tables_declare_exactly_what_the_revision_adds() -> None:
    source = _source()
    for column in BINDING_COLUMNS:
        assert column in meeting_provider_bindings.c
        assert f'"{column}"' in source
    declared = {str(c.name) for c in meeting_provider_bindings.constraints if c.name}
    assert declared >= BINDING_CONSTRAINTS
    for name in BINDING_CONSTRAINTS | {SNAPSHOT_DIGEST_UNIQUE}:
        assert f'"{name}"' in source, name
    assert SNAPSHOT_DIGEST_UNIQUE in {str(c.name) for c in ingest_snapshots.constraints}


def test_the_declared_indexes_are_exactly_the_revisions() -> None:
    declared = {index.name for table in MEETING_SYNC_TABLES for index in table.indexes}
    assert declared == INDEXES


def test_every_new_name_fits_a_postgresql_identifier() -> None:
    """A longer name would be truncated silently by the server in raw SQL."""
    names = {
        str(constraint.name)
        for table in MEETING_SYNC_TABLES
        for constraint in table.constraints
        if constraint.name is not None
    }
    names |= INDEXES | TRIGGERS | FUNCTIONS | BINDING_CONSTRAINTS | {SNAPSHOT_DIGEST_UNIQUE}
    assert max(len(name) for name in names) <= 63, sorted(n for n in names if len(n) > 63)


def test_the_frozen_literals() -> None:
    source = _WHITESPACE.sub(" ", _source())
    assert "'^msevt_[A-Za-z0-9]{8,64}$'" in source
    assert "('applied', 'skipped_ordering_conflict', 'skipped_stale')" in source  # D8
    assert "('cancelled', 'confirmed', 'tentative')" in source
    assert "SET LOCAL lock_timeout = '10s'" in source
    # D9: no write-request vocabulary change and no purpose restatement.
    code = _source().split('"""', 2)[2]
    assert "meeting_write_requests" not in code
    assert "purpose_is_known" not in code
    # D2: no attendee, body or description column is staged.
    for word in ("attendee", "description", "body"):
        assert all(word not in column.name for t in MEETING_SYNC_TABLES for column in t.c)


# ---- the audit vocabulary ------------------------------------------------------


def test_the_audit_before_text_is_a_byte_copy_and_at_adds_exactly_two() -> None:
    mine = _namespace(MIGRATION)
    prior = _namespace(PRIOR_AUDIT_MIGRATION)
    assert mine["_CAPABILITIES_BEFORE_THIS_REVISION"] == prior["_CAPABILITIES_AT_THIS_REVISION"]
    before = _literals(mine["_CAPABILITIES_BEFORE_THIS_REVISION"])
    at = _literals(mine["_CAPABILITIES_AT_THIS_REVISION"])
    assert (len(before), len(at)) == (310, 312)
    assert at == sorted(at)
    assert set(at) - set(before) == NEW_CAPABILITIES
    assert set(mine["_NEW_CAPABILITIES"]) == NEW_CAPABILITIES  # type: ignore[call-overload]


def test_the_audit_at_set_is_the_live_enums_plus_the_schema_ahead_gap() -> None:
    """The two names are admitted ahead of the domain (WP3b-S4 declares them).

    The gap is measured, not trusted: it is exactly the new names the domain
    does not yet declare, and it shrinks to nothing once S4 lands.
    """
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    at = set(_literals(_namespace(MIGRATION)["_CAPABILITIES_AT_THIS_REVISION"]))
    gap = at - declared
    assert gap == NEW_CAPABILITIES - declared
    assert declared <= at


# ---- offline SQL ---------------------------------------------------------------


def test_the_offline_upgrade_refuses_first_and_emits_the_whole_revision(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{PREVIOUS}:{REVISION}")
    refusal = rendered.index("refusing to upgrade to 61fafdfd2986")
    assert rendered.index("SET LOCAL lock_timeout") < refusal
    assert rendered.index("LOCK TABLE knowledge.meeting_provider_bindings") < refusal
    assert refusal < rendered.index("CREATE TABLE")
    for table in TABLES:
        assert f"CREATE TABLE knowledge.{table} (" in rendered
    for index in INDEXES:
        assert f"CREATE INDEX {index} ON" in rendered, index
    for function in FUNCTIONS:
        assert f"CREATE FUNCTION knowledge.{function}()" in rendered
    for trigger in TRIGGERS:
        assert f"CREATE TRIGGER {trigger}" in rendered
    for column in BINDING_COLUMNS:
        assert f"ALTER TABLE knowledge.meeting_provider_bindings ADD COLUMN {column}" in rendered
    assert f"ADD CONSTRAINT {SNAPSHOT_DIGEST_UNIQUE} UNIQUE" in rendered
    assert "GRANT" not in rendered
    assert "'meetings.provider.review'" in rendered
    assert f"SET version_num='{REVISION}'" in rendered


def test_the_offline_downgrade_refuses_first_and_unwinds_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    refusal = rendered.index("refusing to downgrade 61fafdfd2986")
    lock = rendered.index("LOCK TABLE knowledge.meeting_sync_publications")
    assert lock < refusal
    for table in (*TABLES, "meeting_provider_bindings", "ingest_snapshots", "audit_events"):
        assert f"knowledge.{table}" in rendered[lock : rendered.index("IN ACCESS EXCLUSIVE MODE")]
    for table in TABLES:
        assert f"EXISTS (SELECT 1 FROM knowledge.{table})" in rendered  # noqa: S608
    for trigger in TRIGGERS:
        assert rendered.index(f"DROP TRIGGER {trigger}") > refusal
    for function in FUNCTIONS:
        assert rendered.index(f"DROP FUNCTION knowledge.{function}()") > refusal
    for index in INDEXES:
        assert rendered.index(f"DROP INDEX knowledge.{index}") > refusal
    for name in BINDING_CONSTRAINTS | {SNAPSHOT_DIGEST_UNIQUE}:
        assert rendered.index(f"DROP CONSTRAINT {name}") > refusal
    drops = [rendered.index(f"DROP TABLE knowledge.{table} RESTRICT") for table in TABLES]
    assert min(drops) > refusal
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


def _shape(engine: Engine, tables: tuple[str, ...]) -> dict[str, set[tuple[Any, ...]]]:
    with engine.connect() as connection:
        return {
            key: {tuple(row) for row in connection.execute(text(sql), {"tables": list(tables)})}
            for key, sql in _CATALOG_QUERIES.items()
        }


def _catalog(engine: Engine) -> dict[str, set[str]]:
    queries = {
        "tables": "SELECT tablename FROM pg_tables WHERE schemaname = :schema",
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
        "constraints": (
            "SELECT c.conname FROM pg_constraint c "
            "JOIN pg_namespace n ON n.oid = c.connamespace WHERE n.nspname = :schema"
        ),
        "binding_columns": (
            "SELECT column_name FROM information_schema.columns WHERE table_schema = :schema "
            "AND table_name = 'meeting_provider_bindings'"
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
        catalog["audit"] = set(
            connection.execute(
                text(
                    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
                    "JOIN pg_class r ON r.oid = c.conrelid "
                    "WHERE r.relname = 'audit_events' AND c.conname = 'capability_is_known'"
                )
            ).scalars()
        )
    return catalog


def _assert_present(engine: Engine) -> None:
    catalog = _catalog(engine)
    assert catalog["version"] == {REVISION}
    assert catalog["tables"] >= set(TABLES)
    assert catalog["indexes"] >= INDEXES
    assert catalog["triggers"] >= TRIGGERS
    assert catalog["functions"] >= FUNCTIONS
    assert catalog["constraints"] >= BINDING_CONSTRAINTS | {SNAPSHOT_DIGEST_UNIQUE}
    assert catalog["binding_columns"] >= BINDING_COLUMNS
    for name in NEW_CAPABILITIES:
        assert f"'{name}'" in next(iter(catalog["audit"]))


def _assert_absent(engine: Engine) -> None:
    catalog = _catalog(engine)
    assert catalog["version"] == {PREVIOUS}
    assert not catalog["tables"] & set(TABLES)
    assert not catalog["indexes"] & INDEXES
    assert not catalog["triggers"] & TRIGGERS
    assert not catalog["functions"] & FUNCTIONS
    assert not catalog["constraints"] & (BINDING_CONSTRAINTS | {SNAPSHOT_DIGEST_UNIQUE})
    assert not catalog["binding_columns"] & BINDING_COLUMNS
    for name in NEW_CAPABILITIES:
        assert f"'{name}'" not in next(iter(catalog["audit"]))


@pytest.mark.database
def test_the_revision_builds_exactly_the_catalog_tables_py_declares(engine: Engine) -> None:
    """The freeze, on the server: revision-built and `tables.py`-built are identical."""
    altered = ("meeting_provider_bindings", "ingest_snapshots")
    migrated = _shape(engine, TABLES)
    altered_shape = _shape(engine, altered)
    command.downgrade(_config(), PREVIOUS)
    METADATA.create_all(engine, tables=list(MEETING_SYNC_TABLES))
    try:
        declared = _shape(engine, TABLES)
    finally:
        METADATA.drop_all(engine, tables=list(MEETING_SYNC_TABLES))
    for key in _CATALOG_QUERIES:
        assert migrated[key] == declared[key], (
            key,
            sorted(migrated[key] - declared[key]),
            sorted(declared[key] - migrated[key]),
        )
    assert len(migrated["columns"]) == sum(len(t.c) for t in MEETING_SYNC_TABLES)
    # The two altered tables: every column and constraint `tables.py` declares.
    for table in (meeting_provider_bindings, ingest_snapshots):
        columns = {row[1] for row in altered_shape["columns"] if row[0] == table.name}
        assert columns == {column.name for column in table.c}, table.name
        named = {row[1] for row in altered_shape["constraints"] if row[0] == table.name}
        assert {str(c.name) for c in table.constraints if c.name} <= named, table.name


@pytest.mark.database
def test_the_revision_round_trips_from_the_ingestion_revision(engine: Engine) -> None:
    _assert_present(engine)
    command.downgrade(_config(), PREVIOUS)
    _assert_absent(engine)
    command.upgrade(_config(), REVISION)
    _assert_present(engine)


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
                "WHERE c.contype = 'f' AND n.nspname = 'knowledge' "
                "AND (r.relname = ANY(:t) OR c.conname = ANY(:b))"
            ),
            {"t": list(TABLES), "b": list(BINDING_CONSTRAINTS)},
        ).all()
    assert len(rows) == 7
    for table, name, deltype, columns in rows:
        assert deltype == "r", (table, name)
        assert "principal_id" in columns, (table, name)


# ---- the seed ----------------------------------------------------------------------


class _Seed:
    """Sources, snapshots, Meetings, a receipt, a staged publication and one of
    each reconciliation row for `P`, a little of `OTHER`."""

    source = "isrc_msyncmig0001"
    source2 = "isrc_msyncmig0002"
    source_other = "isrc_msyncmig0009"
    snap_a = "isnp_msyncmig000a"
    snap_b = "isnp_msyncmig000b"
    snap_a2 = "isnp_msyncmig00a2"
    snap_other = "isnp_msyncmig0009"
    series = "mser_msyncmig0001"
    m1 = "mtg_msyncmig00001"
    m2 = "mtg_msyncmig00002"
    m3 = "mtg_msyncmig00003"
    m_other = "mtg_msyncmig00009"
    h1 = "mhst_msyncmig0001"
    e1 = "msevt_msyncmig0001"
    b1 = "mpbnd_msyncmig0001"
    t1 = "mpbnd_msyncmig0t01"

    def publication(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "snapshot_id": self.snap_b,
            "ingest_source_id": self.source,
            "generated_at_utc": WHEN,
            "record_count": 2,
            "accepted_count": 1,
            "quarantined_count": 1,
            "staged_at": WHEN,
        }
        row.update(o)
        return row

    def event(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "event_id": "msevt_msyncmignew1",
            "principal_id": P,
            "snapshot_id": self.snap_a,
            "record_ordinal": 7,
            "calendar_ref": "cal-1",
            "ical_uid": "uid-new@example.invalid",
            "start_utc": WHEN,
            "end_utc": WHEN + timedelta(hours=1),
            "timezone_name": "America/New_York",
            "status": "confirmed",
            "title": "A synthetic sync",
            "provider_event_id_format": "unknown",
            "staged_at": WHEN,
        }
        row.update(o)
        return row

    def tombstone(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "binding_id": "mpbnd_msyncmignew1",
            "meeting_id": self.m1,
            "calendar_ref": "cal-1",
            "ical_uid": "uid-gone@example.invalid",
            "unbound_at": WHEN,
            "meeting_history_id": self.h1,
        }
        row.update(o)
        return row

    def binding(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "binding_id": "mpbnd_msyncmignew1",
            "principal_id": P,
            "meeting_id": self.m3,
            "calendar_ref": "cal-1",
            "ical_uid": "uid-three@example.invalid",
            "provider_event_id_format": "unknown",
            "provider_state": "active",
            "version": 1,
            "created_at": WHEN,
            "updated_at": WHEN,
        }
        row.update(o)
        return row

    def plant(self, connection: Connection) -> None:
        def put(table: Table, **row: object) -> None:
            connection.execute(insert(table).values(**row))

        for principal, source in ((P, self.source), (P, self.source2), (OTHER, self.source_other)):
            put(
                ingest_sources,
                ingest_source_id=source,
                principal_id=principal,
                consumer="meeting_sync_v1",
                workspace_id="mcp",
                path_prefix=f"meetings/{source}/",
                file_pattern="*-meetings.json",
                enabled=True,
                admitted_at=WHEN,
                admitted_by="operator_cli",
            )
        for principal, source, snapshot, sha in (
            (P, self.source, self.snap_a, SHA_A),
            (P, self.source, self.snap_b, SHA_B),
            (P, self.source2, self.snap_a2, SHA_A),
            (OTHER, self.source_other, self.snap_other, SHA_A),
        ):
            put(
                ingest_snapshots,
                snapshot_id=snapshot,
                principal_id=principal,
                ingest_source_id=source,
                file_sha256=sha,
                byte_count=10,
                first_seen_at=WHEN,
                status="pending",
            )
        put(
            meeting_series,
            meeting_series_id=self.series,
            principal_id=P,
            title="A synthetic series",
            version=1,
            created_at=WHEN,
            updated_at=WHEN,
        )
        for principal, meeting in ((P, self.m1), (P, self.m2), (P, self.m3), (OTHER, self.m_other)):
            put(
                meetings,
                meeting_id=meeting,
                principal_id=principal,
                title="A synthetic meeting",
                start_at=WHEN,
                timezone_name="UTC",
                status="scheduled",
                version=1,
                created_at=WHEN,
                updated_at=WHEN,
            )
        put(
            meeting_history,
            history_id=self.h1,
            principal_id=P,
            meeting_id=self.m1,
            action="create",
            actor="principal",
            outcome="applied",
            before_version=0,
            after_version=1,
            idempotency_key="msync-mig-0001",
            request_digest=SHA_A,
            occurred_at=WHEN,
            recorded_at=WHEN,
        )
        # One unapplied publication of snapshot A with one event; B is planted
        # by the cases that need a fresh publication.
        put(meeting_sync_publications, **self.publication(snapshot_id=self.snap_a))
        put(meeting_sync_events, **self.event(event_id=self.e1, record_ordinal=0))
        # One publication with no event (of the second source), to delete.
        put(
            meeting_sync_publications,
            **self.publication(snapshot_id=self.snap_a2, ingest_source_id=self.source2),
        )
        put(meeting_provider_review_marks, principal_id=P, meeting_id=self.m1, marked_at=WHEN)
        put(
            meeting_provider_reconciliation_passes,
            principal_id=P,
            completed_at=WHEN,
            reviewed_meetings=3,
            reconcile_correlation_id="corr_msyncmig0001",
        )
        put(meeting_provider_key_tombstones, **self.tombstone(binding_id=self.t1))
        put(
            meeting_provider_bindings,
            **self.binding(
                binding_id=self.b1,
                meeting_id=self.m2,
                ical_uid="uid-two@example.invalid",
                last_seen_source_sha256=SHA_A,
                last_seen_record_ordinal=0,
                last_seen_at=WHEN,
                last_seen_snapshot_id=self.snap_a,
                origin_snapshot_id=self.snap_a,
            ),
        )


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
) -> str | None:
    """`None` when `statement` is refused with `sqlstate` (and `constraint`) and
    accepted once `lift` runs first; otherwise what went wrong."""
    refused = _attempt(engine, statement)
    if refused is None:
        return "accepted, expected a refusal"
    if _sqlstate(refused) != sqlstate:
        return f"refused with {_sqlstate(refused)} ({_constraint(refused)}), expected {sqlstate}"
    if constraint is not None and _constraint(refused) != constraint:
        return f"refused by {_constraint(refused)}, expected {constraint}"
    lifted = _attempt(engine, statement, prelude=lift)
    if lifted is not None:
        return f"still refused once lifted: {_sqlstate(lifted)} ({_constraint(lifted)})"
    return None


_TABLE: Final = {table.name: table for table in (*MEETING_SYNC_TABLES, meeting_provider_bindings)}


def _inserting(table: str, row: dict[str, object]) -> Callable[[Connection], Any]:
    return lambda connection: connection.execute(insert(_TABLE[table]).values(**row))


def _set(table: Table, where: ColumnElement[bool], **values: object) -> Callable[[Connection], Any]:
    return lambda connection: connection.execute(update(table).where(where).values(**values))


def _remove(table: Table, where: ColumnElement[bool]) -> Callable[[Connection], Any]:
    return lambda connection: connection.execute(delete(table).where(where))


def _drop(table: str, constraint: str) -> str:
    return f"ALTER TABLE knowledge.{table} DROP CONSTRAINT {constraint} CASCADE"


# ---- CHECK constraints -----------------------------------------------------------------


def _check_cases(s: _Seed) -> list[tuple[str, str, Callable[[Connection], Any]]]:
    """`(table, constraint, statement)`: each violates exactly that one CHECK."""
    pub, evt, tomb = (
        "meeting_sync_publications",
        "meeting_sync_events",
        "meeting_provider_key_tombstones",
    )
    applied = {"applied_at": WHEN, "apply_outcome": "applied", "apply_counts": {"records": 1}}
    covered = {
        "coverage_start_utc": WHEN,
        "coverage_end_utc": WHEN + timedelta(days=1),
        "coverage_calendar_refs": ["cal-1"],
    }
    original = WHEN - timedelta(days=7)
    b = meeting_provider_bindings
    cases: list[tuple[str, str, dict[str, object]]] = [
        (
            pub,
            "a_meeting_sync_publication_coverage_is_whole",
            s.publication(coverage_start_utc=WHEN),
        ),
        (
            pub,
            "a_meeting_sync_publication_coverage_ends_after_it_starts",
            s.publication(**{**covered, "coverage_end_utc": WHEN - timedelta(seconds=1)}),
        ),
        (
            pub,
            "a_meeting_sync_publication_coverage_names_its_calendars",
            s.publication(**{**covered, "coverage_calendar_refs": []}),
        ),
        (
            pub,
            "a_meeting_sync_publication_count_is_non_negative",
            s.publication(record_count=-1, accepted_count=-1, quarantined_count=0),
        ),
        (
            pub,
            "a_meeting_sync_publication_counts_reconcile",
            s.publication(record_count=3),
        ),
        (
            pub,
            "a_meeting_sync_publication_apply_is_whole",
            s.publication(applied_at=WHEN),
        ),
        (
            pub,
            "a_meeting_sync_publication_apply_outcome_is_known",
            s.publication(**{**applied, "apply_outcome": "replayed"}),
        ),
        (
            pub,
            "a_meeting_sync_publication_apply_counts_is_an_object",
            s.publication(**{**applied, "apply_counts": [1]}),
        ),
        (evt, "event_id_is_an_opaque_identifier", s.event(event_id="msevt_x")),
        (evt, "a_meeting_sync_event_ordinal_is_non_negative", s.event(record_ordinal=-1)),
        (evt, "a_meeting_sync_event_calendar_ref_is_bounded", s.event(calendar_ref="")),
        (evt, "a_meeting_sync_event_uid_is_bounded", s.event(ical_uid="x" * 1025)),
        (
            evt,
            "a_meeting_sync_event_series_uid_is_bounded",
            s.event(series_ical_uid="", occurrence_original_start_utc=original),
        ),
        (
            evt,
            "a_meeting_sync_event_names_its_series_and_original_start",
            s.event(series_ical_uid="series@example.invalid"),
        ),
        (
            evt,
            "a_meeting_sync_event_does_not_end_before_it_starts",
            s.event(end_utc=WHEN - timedelta(minutes=1)),
        ),
        (evt, "a_meeting_sync_event_timezone_name_is_bounded", s.event(timezone_name=" ")),
        (evt, "a_meeting_sync_event_status_is_known", s.event(status="scheduled")),
        (evt, "a_meeting_sync_event_title_is_bounded", s.event(title=" ")),
        (evt, "a_meeting_sync_event_location_is_bounded", s.event(location_text="x" * 501)),
        (evt, "a_meeting_sync_event_virtual_url_is_bounded", s.event(virtual_meeting_url="")),
        (
            evt,
            "a_meeting_sync_event_provider_event_id_is_bounded",
            s.event(provider_event_id=""),
        ),
        (
            evt,
            "a_meeting_sync_event_provider_event_id_format_is_known",
            s.event(provider_event_id_format="stable"),
        ),
        (
            "meeting_provider_reconciliation_passes",
            "a_reconciliation_pass_count_is_non_negative",
            {
                "principal_id": OTHER,
                "completed_at": WHEN,
                "reviewed_meetings": -1,
                "reconcile_correlation_id": "corr_msyncmig0002",
            },
        ),
        (
            "meeting_provider_reconciliation_passes",
            "reconcile_correlation_id_is_an_opaque_identifier",
            {
                "principal_id": OTHER,
                "completed_at": WHEN,
                "reviewed_meetings": 0,
                "reconcile_correlation_id": "audit-1",
            },
        ),
        (
            "meeting_provider_reconciliation_passes",
            "principal_id_is_an_opaque_identifier",
            {
                "principal_id": "principal-2",
                "completed_at": WHEN,
                "reviewed_meetings": 0,
                "reconcile_correlation_id": "corr_msyncmig0002",
            },
        ),
        (tomb, "binding_id_is_an_opaque_identifier", s.tombstone(binding_id="binding-1")),
        (tomb, "a_key_tombstone_calendar_ref_is_bounded", s.tombstone(calendar_ref="")),
        (tomb, "a_key_tombstone_uid_is_bounded", s.tombstone(ical_uid="")),
        (
            tomb,
            "a_key_tombstone_series_uid_is_bounded",
            s.tombstone(series_ical_uid="", occurrence_original_start_utc=original),
        ),
        (
            tomb,
            "a_key_tombstone_names_its_series_and_original_start",
            s.tombstone(occurrence_original_start_utc=original),
        ),
    ]
    statements = [(table, name, _inserting(table, row)) for table, name, row in cases]
    # The binding pairing (D10): a `last_seen_*` observation names its snapshot.
    statements.append(
        (
            "meeting_provider_bindings",
            "a_provider_binding_last_seen_names_its_snapshot",
            _set(b, b.c.binding_id == s.b1, last_seen_snapshot_id=None),
        )
    )
    return statements


#: CHECKs whose violating value the composite foreign key on the same column
#: also refuses, so they cannot be isolated: an identifier-shape CHECK on a
#: column that names another row. They are refused by their CHECK first
#: (asserted below), and by the foreign key alone.
_IDENTIFIER_HELD_ALSO_BY_A_FOREIGN_KEY: Final = frozenset(
    {
        ("meeting_sync_publications", "principal_id_is_an_opaque_identifier"),
        ("meeting_sync_publications", "snapshot_id_is_an_opaque_identifier"),
        ("meeting_sync_publications", "ingest_source_id_is_an_opaque_identifier"),
        ("meeting_sync_events", "principal_id_is_an_opaque_identifier"),
        ("meeting_sync_events", "snapshot_id_is_an_opaque_identifier"),
        ("meeting_provider_review_marks", "principal_id_is_an_opaque_identifier"),
        ("meeting_provider_review_marks", "meeting_id_is_an_opaque_identifier"),
        ("meeting_provider_key_tombstones", "principal_id_is_an_opaque_identifier"),
        ("meeting_provider_key_tombstones", "meeting_id_is_an_opaque_identifier"),
        ("meeting_provider_key_tombstones", "meeting_history_id_is_an_opaque_identifier"),
    }
)


@pytest.mark.database
def test_every_check_refuses_its_case_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _check_cases(seed)
    failures = [
        (table, constraint, problem)
        for table, constraint, statement in cases
        if (
            problem := _isolated(
                engine,
                statement,
                sqlstate=CHECK,
                constraint=constraint,
                lift=_drop(table, constraint),
            )
        )
        is not None
    ]
    assert failures == []
    covered = {(table, constraint) for table, constraint, _statement in cases}
    declared = {
        (table.name, str(constraint.name))
        for table in MEETING_SYNC_TABLES
        for constraint in table.constraints
        if type(constraint).__name__ == "CheckConstraint"
    }
    assert declared - covered == _IDENTIFIER_HELD_ALSO_BY_A_FOREIGN_KEY
    tomb = seed.tombstone(meeting_history_id="history-1")
    refused = _attempt(engine, _inserting("meeting_provider_key_tombstones", tomb))
    assert refused is not None
    assert (_sqlstate(refused), _constraint(refused)) == (
        CHECK,
        "meeting_history_id_is_an_opaque_identifier",
    )


@pytest.mark.database
def test_the_binding_snapshot_identifiers_are_refused_by_their_check_first(
    seeded: tuple[Engine, _Seed],
) -> None:
    engine, seed = seeded
    for column in ("origin_snapshot_id", "last_seen_snapshot_id"):
        row = seed.binding(**{column: "snapshot-1"})
        if column == "last_seen_snapshot_id":
            row |= {
                "last_seen_source_sha256": SHA_A,
                "last_seen_record_ordinal": 0,
                "last_seen_at": WHEN,
            }
        refused = _attempt(engine, _inserting("meeting_provider_bindings", row))
        assert refused is not None
        assert (_sqlstate(refused), _constraint(refused)) == (
            CHECK,
            f"{column}_is_an_opaque_identifier",
        )


# ---- UNIQUE keys -------------------------------------------------------------------------


def _unique_cases(s: _Seed) -> list[tuple[str, str, Callable[[Connection], Any]]]:
    return [
        (
            "meeting_sync_publications",
            "meeting_sync_publications_pkey",
            _inserting("meeting_sync_publications", s.publication(snapshot_id=s.snap_a)),
        ),
        (
            "meeting_sync_events",
            "meeting_sync_events_pkey",
            _inserting("meeting_sync_events", s.event(event_id=s.e1, record_ordinal=9)),
        ),
        (
            "meeting_sync_events",
            "one_meeting_sync_event_per_record",
            _inserting("meeting_sync_events", s.event(record_ordinal=0)),
        ),
        (
            "meeting_provider_review_marks",
            "meeting_provider_review_marks_pkey",
            _inserting(
                "meeting_provider_review_marks",
                {"principal_id": P, "meeting_id": s.m1, "marked_at": WHEN},
            ),
        ),
        (
            "meeting_provider_reconciliation_passes",
            "meeting_provider_reconciliation_passes_pkey",
            _inserting(
                "meeting_provider_reconciliation_passes",
                {
                    "principal_id": P,
                    "completed_at": WHEN,
                    "reviewed_meetings": 0,
                    "reconcile_correlation_id": "corr_msyncmig0003",
                },
            ),
        ),
        (
            "meeting_provider_key_tombstones",
            "meeting_provider_key_tombstones_pkey",
            _inserting("meeting_provider_key_tombstones", s.tombstone(binding_id=s.t1)),
        ),
    ]


@pytest.mark.database
def test_every_unique_key_refuses_its_duplicate_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _unique_cases(seed)
    failures = [
        (constraint, problem)
        for table, constraint, statement in cases
        if (
            problem := _isolated(
                engine,
                statement,
                sqlstate=UNIQUE,
                constraint=constraint,
                lift=_drop(table, constraint),
            )
        )
        is not None
    ]
    assert failures == []
    declared = {
        str(constraint.name) if constraint.name else f"{table.name}_pkey"
        for table in MEETING_SYNC_TABLES
        for constraint in table.constraints
        if type(constraint).__name__ in {"UniqueConstraint", "PrimaryKeyConstraint"}
    }
    assert declared == {constraint for _t, constraint, _s in cases}


@pytest.mark.database
def test_the_snapshot_digest_key_is_the_foreign_key_target_and_implied_by_the_primary_key(
    seeded: tuple[Engine, _Seed],
) -> None:
    """`an_ingest_snapshot_is_identified_with_its_digest` cannot refuse a row alone:
    `snapshot_id` is already the primary key. It exists to be the target of the
    binding `last_seen_*` foreign key, which PostgreSQL requires to be a key."""
    engine, _seed = seeded
    lifted = _attempt(
        engine,
        lambda connection: connection.execute(text("SELECT 1")),
        prelude=f"ALTER TABLE knowledge.ingest_snapshots DROP CONSTRAINT {SNAPSHOT_DIGEST_UNIQUE}",
    )
    assert lifted is not None
    assert "a_provider_binding_last_seen_names_a_snapshot_of_its_digest" in str(lifted)


# ---- FOREIGN keys ------------------------------------------------------------------------


def _foreign_cases(s: _Seed) -> list[tuple[str, str, Callable[[Connection], Any]]]:
    b = meeting_provider_bindings
    return [
        (
            "meeting_sync_publications",
            "a_meeting_sync_publication_names_a_snapshot_of_its_source",
            # Snapshot B is of the first source, not the second the row names.
            _inserting(
                "meeting_sync_publications",
                s.publication(snapshot_id=s.snap_b, ingest_source_id=s.source2),
            ),
        ),
        (
            "meeting_sync_events",
            "a_meeting_sync_event_names_a_publication_of_its_principal",
            # Snapshot B has no staged publication.
            _inserting("meeting_sync_events", s.event(snapshot_id=s.snap_b)),
        ),
        (
            "meeting_provider_review_marks",
            "a_review_mark_names_a_meeting_of_its_principal",
            _inserting(
                "meeting_provider_review_marks",
                {"principal_id": P, "meeting_id": s.m_other, "marked_at": WHEN},
            ),
        ),
        (
            "meeting_provider_key_tombstones",
            "a_key_tombstone_names_a_receipt_of_its_meeting",
            # The receipt is of m1; the tombstone names m2.
            _inserting("meeting_provider_key_tombstones", s.tombstone(meeting_id=s.m2)),
        ),
        (
            "meeting_provider_bindings",
            "a_provider_binding_last_seen_names_a_snapshot_of_its_digest",
            # D10: snapshot A has digest A; the row claims digest B.
            _set(b, b.c.binding_id == s.b1, last_seen_source_sha256=SHA_B),
        ),
        (
            "meeting_provider_bindings",
            "a_provider_binding_origin_names_a_snapshot_of_its_principal",
            _inserting("meeting_provider_bindings", s.binding(origin_snapshot_id=s.snap_other)),
        ),
    ]


@pytest.mark.database
def test_every_foreign_key_refuses_a_crossing_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _foreign_cases(seed)
    failures = [
        (constraint, problem)
        for table, constraint, statement in cases
        if (
            problem := _isolated(
                engine,
                statement,
                sqlstate=FOREIGN,
                constraint=constraint,
                lift=_drop(table, constraint),
            )
        )
        is not None
    ]
    assert failures == []
    declared = {
        str(constraint.name)
        for table in MEETING_SYNC_TABLES
        for constraint in table.constraints
        if type(constraint).__name__ == "ForeignKeyConstraint"
    } | {name for name in BINDING_CONSTRAINTS if "names_a_snapshot" in name}
    covered = {constraint for _t, constraint, _s in cases}
    assert declared - covered == {_TOMBSTONE_MEETING_FOREIGN_KEY}
    # Held also by the receipt key: a tombstone's receipt is of its own Meeting
    # of its own Principal, so a crossing Meeting always crosses the receipt too.
    # The Meeting key is defence in depth, reported, not claimed.
    crossing = seed.tombstone(meeting_id=seed.m_other)
    refused = _attempt(engine, _inserting("meeting_provider_key_tombstones", crossing))
    assert refused is not None
    assert _sqlstate(refused) == FOREIGN
    assert _constraint(refused) in {
        _TOMBSTONE_MEETING_FOREIGN_KEY,
        "a_key_tombstone_names_a_receipt_of_its_meeting",
    }


_TOMBSTONE_MEETING_FOREIGN_KEY: Final = "a_key_tombstone_names_a_meeting_of_its_principal"


@pytest.mark.database
def test_a_binding_observation_of_the_same_digest_from_another_snapshot_is_accepted(
    seeded: tuple[Engine, _Seed],
) -> None:
    """The digest key is the content, not the source: A2 has digest A too."""
    engine, seed = seeded
    b = meeting_provider_bindings
    with engine.begin() as connection:
        connection.execute(
            update(b).where(b.c.binding_id == seed.b1).values(last_seen_snapshot_id=seed.snap_a2)
        )


# ---- triggers --------------------------------------------------------------------------------


def _refused_trigger_cases(s: _Seed) -> list[tuple[str, str, str, Callable[[Connection], Any]]]:
    """`(label, table, trigger, statement)`: each statement is refused by that one trigger."""
    p, b = meeting_sync_publications, meeting_provider_bindings
    mine_a = (p.c.principal_id == P) & (p.c.snapshot_id == s.snap_a)
    cases: list[tuple[str, str, str, Callable[[Connection], Any]]] = [
        (
            "publication: a non-apply column",
            p.name,
            PUBLICATION_TRIGGER,
            _set(p, mine_a, generated_at_utc=WHEN + timedelta(seconds=1)),
        ),
        (
            "publication: delete",
            p.name,
            PUBLICATION_TRIGGER,
            _remove(p, (p.c.principal_id == P) & (p.c.snapshot_id == s.snap_a2)),
        ),
        (
            "binding: origin changed",
            b.name,
            ORIGIN_TRIGGER,
            _set(b, b.c.binding_id == s.b1, origin_snapshot_id=s.snap_a2),
        ),
        (
            "binding: origin cleared",
            b.name,
            ORIGIN_TRIGGER,
            _set(b, b.c.binding_id == s.b1, origin_snapshot_id=None),
        ),
    ]
    leaves: dict[str, tuple[ColumnElement[bool], dict[str, object]]] = {
        "meeting_sync_events": (
            meeting_sync_events.c.event_id == s.e1,
            {"title": "A changed title"},
        ),
        "meeting_provider_review_marks": (
            meeting_provider_review_marks.c.meeting_id == s.m1,
            {"marked_at": WHEN + timedelta(days=1)},
        ),
        "meeting_provider_reconciliation_passes": (
            meeting_provider_reconciliation_passes.c.principal_id == P,
            {"reviewed_meetings": 4},
        ),
        "meeting_provider_key_tombstones": (
            meeting_provider_key_tombstones.c.binding_id == s.t1,
            {"unbound_at": WHEN + timedelta(days=1)},
        ),
    }
    for name, (where, values) in leaves.items():
        trigger = f"{name}_are_append_only"
        cases.append((f"{name}: update", name, trigger, _set(_TABLE[name], where, **values)))
        cases.append((f"{name}: delete", name, trigger, _remove(_TABLE[name], where)))
    return cases


@pytest.mark.database
def test_every_trigger_refuses_its_case_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _refused_trigger_cases(seed)
    failures = [
        (label, problem)
        for label, table, trigger, statement in cases
        if (
            problem := _isolated(
                engine,
                statement,
                sqlstate=RESTRICT_VIOLATION,
                constraint=None,
                lift=f"ALTER TABLE knowledge.{table} DISABLE TRIGGER {trigger}",
            )
        )
        is not None
    ]
    assert failures == []
    assert {trigger for _l, _t, trigger, _s in cases} == TRIGGERS - {
        f"{table}_refuse_truncate" for table in TABLES
    }


@pytest.mark.database
def test_a_publication_is_applied_once_from_null(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    p = meeting_sync_publications
    mine_a = (p.c.principal_id == P) & (p.c.snapshot_id == seed.snap_a)
    applied = {"applied_at": WHEN, "apply_outcome": "applied", "apply_counts": {"records": 1}}
    with engine.begin() as connection:
        connection.execute(update(p).where(mine_a).values(**applied))
    again = _set(p, mine_a, **{**applied, "apply_outcome": "skipped_stale"})
    problem = _isolated(
        engine,
        again,
        sqlstate=RESTRICT_VIOLATION,
        constraint=None,
        lift=f"ALTER TABLE knowledge.{p.name} DISABLE TRIGGER {PUBLICATION_TRIGGER}",
    )
    assert problem is None


@pytest.mark.database
def test_a_binding_keeps_its_last_seen_attributes_mutable(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    b = meeting_provider_bindings
    with engine.begin() as connection:
        connection.execute(
            update(b)
            .where(b.c.binding_id == seed.b1)
            .values(
                last_seen_snapshot_id=seed.snap_b,
                last_seen_source_sha256=SHA_B,
                last_seen_record_ordinal=3,
                last_seen_at=WHEN + timedelta(hours=1),
            )
        )
        connection.execute(
            update(b)
            .where(b.c.binding_id == seed.b1)
            .values(
                last_seen_snapshot_id=None,
                last_seen_source_sha256=None,
                last_seen_record_ordinal=None,
                last_seen_at=None,
            )
        )


@pytest.mark.database
def test_truncate_is_refused_on_every_table_by_its_own_trigger(
    seeded: tuple[Engine, _Seed],
) -> None:
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
        # With every TRUNCATE trigger lifted, the cascade still meets the
        # append-only row triggers of no table (TRUNCATE fires none of them).
        if _attempt(engine, statement, prelude="; ".join(every)) is not None:
            failures.append((table, "refused with every TRUNCATE trigger disabled"))
    assert failures == []


# ---- the upgrade and downgrade refusals ----------------------------------------------------


@pytest.mark.database
def test_the_upgrade_refuses_while_a_binding_records_a_legacy_observation(
    engine: Engine,
) -> None:
    seed = _Seed()
    command.downgrade(_config(), PREVIOUS)
    with engine.begin() as connection:
        connection.execute(
            insert(meeting_series).values(
                meeting_series_id=seed.series,
                principal_id=P,
                title="A synthetic series",
                version=1,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
        connection.execute(
            insert(meetings).values(
                meeting_id=seed.m1,
                principal_id=P,
                title="A synthetic meeting",
                start_at=WHEN,
                timezone_name="UTC",
                status="scheduled",
                version=1,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
        # A WP2-shaped row: an observation with no snapshot column to name.
        row = seed.binding(
            meeting_id=seed.m1,
            last_seen_source_sha256=SHA_A,
            last_seen_record_ordinal=0,
            last_seen_at=WHEN,
        )
        connection.execute(insert(meeting_provider_bindings).values(**row))
    with pytest.raises(DBAPIError) as refused:
        command.upgrade(_config(), REVISION)
    assert _sqlstate(refused.value) == RESTRICT_VIOLATION
    assert "refusing to upgrade to 61fafdfd2986" in str(refused.value)
    _assert_absent(engine)
    # Without the observation the same upgrade passes.
    b = meeting_provider_bindings
    with engine.begin() as connection:
        connection.execute(
            update(b)
            .where(b.c.binding_id == row["binding_id"])
            .values(last_seen_source_sha256=None, last_seen_record_ordinal=None, last_seen_at=None)
        )
    command.upgrade(_config(), REVISION)
    _assert_present(engine)


def _plant_publication(connection: Connection, seed: _Seed) -> None:
    connection.execute(
        insert(ingest_sources).values(
            ingest_source_id=seed.source,
            principal_id=P,
            consumer="meeting_sync_v1",
            workspace_id="mcp",
            path_prefix="meetings/",
            file_pattern="*-meetings.json",
            enabled=True,
            admitted_at=WHEN,
            admitted_by="operator_cli",
        )
    )
    connection.execute(
        insert(ingest_snapshots).values(
            snapshot_id=seed.snap_a,
            principal_id=P,
            ingest_source_id=seed.source,
            file_sha256=SHA_A,
            byte_count=10,
            first_seen_at=WHEN,
            status="pending",
        )
    )


def _plant_meeting(connection: Connection, meeting_id: str) -> None:
    connection.execute(
        insert(meetings).values(
            meeting_id=meeting_id,
            principal_id=P,
            title="A synthetic meeting",
            start_at=WHEN,
            timezone_name="UTC",
            status="scheduled",
            version=1,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )


def _only_a_publication(connection: Connection, seed: _Seed) -> None:
    _plant_publication(connection, seed)
    connection.execute(
        insert(meeting_sync_publications).values(**seed.publication(snapshot_id=seed.snap_a))
    )


def _only_a_mark(connection: Connection, seed: _Seed) -> None:
    _plant_meeting(connection, seed.m1)
    connection.execute(
        insert(meeting_provider_review_marks).values(
            principal_id=P, meeting_id=seed.m1, marked_at=WHEN
        )
    )


def _only_a_pass(connection: Connection, seed: _Seed) -> None:
    del seed
    connection.execute(
        insert(meeting_provider_reconciliation_passes).values(
            principal_id=P,
            completed_at=WHEN,
            reviewed_meetings=0,
            reconcile_correlation_id="corr_msyncmig0004",
        )
    )


def _only_a_tombstone(connection: Connection, seed: _Seed) -> None:
    _plant_meeting(connection, seed.m1)
    connection.execute(
        insert(meeting_history).values(
            history_id=seed.h1,
            principal_id=P,
            meeting_id=seed.m1,
            action="create",
            actor="principal",
            outcome="applied",
            before_version=0,
            after_version=1,
            idempotency_key="msync-mig-0002",
            request_digest=SHA_A,
            occurred_at=WHEN,
            recorded_at=WHEN,
        )
    )
    connection.execute(insert(meeting_provider_key_tombstones).values(**seed.tombstone()))


@pytest.mark.database
@pytest.mark.parametrize(
    "plant",
    [_only_a_publication, _only_a_mark, _only_a_pass, _only_a_tombstone],
    ids=lambda plant: plant.__name__,
)
def test_a_downgrade_refuses_while_one_staging_or_reconciliation_row_exists(
    engine: Engine, plant: Callable[[Connection, _Seed], None]
) -> None:
    """A staged event cannot exist without its publication, so it is covered by
    the full seed below rather than alone."""
    with engine.begin() as connection:
        plant(connection, _Seed())
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert "meeting sync rows exist; refusing to downgrade 61fafdfd2986" in str(refused.value)
    _assert_present(engine)


@pytest.mark.database
def test_a_downgrade_refuses_while_the_full_seed_exists(seeded: tuple[Engine, _Seed]) -> None:
    engine, _seed = seeded
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert "refusing to downgrade 61fafdfd2986" in str(refused.value)
    _assert_present(engine)


@pytest.mark.database
def test_a_downgrade_refuses_while_a_binding_names_a_snapshot(engine: Engine) -> None:
    seed = _Seed()
    with engine.begin() as connection:
        _plant_publication(connection, seed)
        _plant_meeting(connection, seed.m3)
        connection.execute(
            insert(meeting_provider_bindings).values(**seed.binding(origin_snapshot_id=seed.snap_a))
        )
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert "provider bindings name a snapshot; refusing to downgrade" in str(refused.value)
    _assert_present(engine)


@pytest.mark.database
@pytest.mark.parametrize("capability", sorted(NEW_CAPABILITIES))
def test_a_downgrade_refuses_while_a_new_capability_audit_event_exists(
    engine: Engine, capability: str
) -> None:
    with engine.begin() as connection:
        connection.execute(
            insert(audit_events).values(
                audit_id="audit_msyncmigaudit1",
                correlation_id="corr_msyncmigaudit1",
                principal_id=P,
                capability=capability,
                purpose="meeting_read",
                outcome="allowed",
                policy_version="policy-v1",
                scope_source_id_count=0,
                recorded_at=WHEN,
            )
        )
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert "audit history exists; refusing to downgrade 61fafdfd2986" in str(refused.value)
    _assert_present(engine)


@pytest.mark.database
def test_the_audit_vocabulary_admits_exactly_the_two_names_at_this_revision(
    engine: Engine,
) -> None:
    def audit(capability: str) -> Callable[[Connection], Any]:
        return lambda connection: connection.execute(
            insert(audit_events).values(
                audit_id="audit_msyncmigaudit2",
                correlation_id="corr_msyncmigaudit2",
                principal_id=P,
                capability=capability,
                purpose="meeting_authoring",
                outcome="allowed",
                policy_version="policy-v1",
                scope_source_id_count=0,
                recorded_at=WHEN,
            )
        )

    for name in sorted(NEW_CAPABILITIES):
        assert _attempt(engine, audit(name)) is None, name
    unknown = _attempt(engine, audit("meetings.provider.unknown"))
    assert unknown is not None
    assert _constraint(unknown) == "capability_is_known"
    command.downgrade(_config(), PREVIOUS)
    for name in sorted(NEW_CAPABILITIES):
        refused = _attempt(engine, audit(name))
        assert refused is not None
        assert _constraint(refused) == "capability_is_known"
