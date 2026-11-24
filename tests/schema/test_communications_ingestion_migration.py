"""Communications intelligence WP3a: the one ingestion revision, `52a829ef718a`.

`52a829ef718a` is additive on `6418b57081c3` (WP2 provider bindings) and
creates the twelve tables of the consumer-neutral ingestion lifecycle and the
communications evidence (contract sections 1.2, 1.3, 5.1 and 5.2 as amended by
the WP3a Manager rulings), their indexes and their guards. This module proves:

* **the graph** -- exactly one head, this revision, directly on `6418b57081c3`;
* **the freeze** -- the revision imports nothing from the package it migrates
  and names every column, constraint and index `tables.py` declares; on a live
  server the catalog the revision builds (columns, types, defaults, generated
  expression, every constraint definition and every index definition) equals the
  catalog `tables.py` builds, byte for byte;
* **offline SQL** for both directions, without a server;
* on disposable databases: empty to head; the round trip; the downgrade refusal
  while any row exists; every trigger (named-mutable columns allowed and
  refused, from-NULL-only, terminal-snapshot immutability, append-only, TRUNCATE
  refusal); every CHECK, UNIQUE and FOREIGN KEY case.

**Every guard case is isolated.** Each refused case is refused with its own
named constraint (or by its trigger), and then -- inside a transaction that is
rolled back -- the same statement is accepted once exactly that one constraint
is dropped or that one trigger disabled. A case another guard would also refuse
could not pass the second half, so a green run proves each guard is the one
holding its case (the prove-red, kept permanently).

The file name routes every test here to migration-edge (`tests/db/fixtures.py`);
the tests with no `database` marker also run in FAST. Every value is synthetic.
"""

from __future__ import annotations

import ast
import io
import re
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from itertools import count
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import ColumnElement, Engine, Table, delete, insert, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence import tables as declarations
from my_pa.infrastructure.persistence.tables import (
    COMMUNICATIONS_INGESTION_TABLES,
    METADATA,
    communication_identifiers,
    communication_mailbox_items,
    communication_messages,
    communication_observations,
    communication_participants,
    communication_quarantine,
    ingest_coverage_windows,
    ingest_run_snapshots,
    ingest_runs,
    ingest_snapshot_paths,
    ingest_snapshots,
    ingest_sources,
)

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "52a829ef718a"
PREVIOUS: Final = "6418b57081c3"
MIGRATION: Final = (
    ROOT / "migrations" / "versions" / "20261122_52a829ef718a_communications_ingestion.py"
)

TABLES: Final = tuple(table.name for table in COMMUNICATIONS_INGESTION_TABLES)
INDEXES: Final = frozenset(
    {
        "one_current_ingest_snapshot_per_path",
        "ingest_snapshot_paths_by_source",
        "ingest_runs_by_source",
        "ingest_run_snapshots_by_snapshot",
        "ingest_coverage_windows_by_source",
        "communication_messages_search_document",
        "communication_messages_by_time",
        "communication_messages_by_conversation",
        "communication_mailbox_items_by_message",
        "communication_observations_by_item",
        "communication_participants_by_address",
        "communication_identifiers_by_value",
    }
)
MUTABLE_TRIGGERS: Final = {
    "ingest_sources": "ingest_sources_change_only_enabled",
    "ingest_snapshots": "ingest_snapshots_finalize_once",
    "ingest_snapshot_paths": "ingest_snapshot_paths_supersede_once",
    "ingest_runs": "ingest_runs_finish_once",
    "communication_messages": "communication_messages_change_only_their_projection",
}
APPEND_ONLY_TABLES: Final = (
    "ingest_run_snapshots",
    "ingest_coverage_windows",
    "communication_mailbox_items",
    "communication_observations",
    "communication_participants",
    "communication_identifiers",
    "communication_quarantine",
)
TRIGGERS: Final = frozenset(
    {*MUTABLE_TRIGGERS.values()}
    | {f"{table}_are_append_only" for table in APPEND_ONLY_TABLES}
    | {f"{table}_refuse_truncate" for table in TABLES}
)
FUNCTIONS: Final = frozenset(
    {*MUTABLE_TRIGGERS.values()}
    | {
        "communications_ingestion_rows_are_append_only",
        "communications_ingestion_refuses_truncate",
    }
)

P: Final = "prn_cmsingest0001aaaa"
OTHER: Final = "prn_cmsingest0002bbbb"
WHEN: Final = datetime(2026, 11, 22, 12, tzinfo=UTC)
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


# ---- the graph --------------------------------------------------------------


def test_the_revision_is_the_single_head_directly_on_the_provider_binding_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_revision(REVISION).down_revision == PREVIOUS


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
    source = _source()
    created = re.findall(r"CREATE TABLE knowledge\.(\w+) \(", source)
    assert tuple(created) == TABLES
    assert len(TABLES) == 12


@pytest.mark.parametrize("table", COMMUNICATIONS_INGESTION_TABLES, ids=lambda t: t.name)
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


def test_the_declared_indexes_are_exactly_the_revisions() -> None:
    declared = {index.name for table in COMMUNICATIONS_INGESTION_TABLES for index in table.indexes}
    assert declared == INDEXES


def test_every_new_name_fits_a_postgresql_identifier() -> None:
    """A longer name would be truncated silently by the server in raw SQL."""
    names = {
        str(constraint.name)
        for table in COMMUNICATIONS_INGESTION_TABLES
        for constraint in table.constraints
        if constraint.name is not None
    }
    names |= INDEXES | TRIGGERS | FUNCTIONS
    assert max(len(name) for name in names) <= 63, sorted(n for n in names if len(n) > 63)


def test_the_frozen_literals() -> None:
    source = _WHITESPACE.sub(" ", _source())
    for prefix in ("isrc", "isnp", "irun", "icov", "cmsg", "cmitm", "cobs", "cqrn"):
        assert f"'^{prefix}_[A-Za-z0-9]{{8,64}}$'" in source, prefix
    assert "('communications_evidence_v2', 'meeting_sync_v1', 'pulse_csv_export')" in source  # M4
    assert "admitted_by = 'operator_cli'" in source  # m8
    assert "status IN ('ingested', 'pending', 'rejected')" in source  # M3
    assert "length(search_text) <= 262144" in source
    namespace: dict[str, object] = {}
    exec(compile(_source(), str(MIGRATION), "exec"), namespace)  # noqa: S102
    assert namespace["_SEARCH_DOCUMENT"] == (
        "setweight(to_tsvector('english'::regconfig, coalesce(subject, '')), 'A') || "
        "setweight(to_tsvector('english'::regconfig, coalesce(search_text, '')), 'B')"
    )
    assert namespace["_SEARCH_DOCUMENT"] == declarations.COMMUNICATION_SEARCH_DOCUMENT
    assert "SET LOCAL lock_timeout = '10s'" in source
    # Ruling M1: no trigram index in WP3a.
    assert "gin_trgm_ops" not in source
    assert "pg_trgm" not in source


def test_the_offline_upgrade_emits_the_whole_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{PREVIOUS}:{REVISION}")
    assert rendered.index("SET LOCAL lock_timeout") < rendered.index("CREATE TABLE")
    for table in TABLES:
        assert f"CREATE TABLE knowledge.{table} (" in rendered
    for index in INDEXES:
        assert re.search(rf"CREATE (UNIQUE )?INDEX {index} ON", rendered), index
    for function in FUNCTIONS:
        assert f"CREATE FUNCTION knowledge.{function}()" in rendered
    for trigger in TRIGGERS:
        assert f"CREATE TRIGGER {trigger}" in rendered
    # Additive only: no existing table is altered, nothing is granted.
    assert "ALTER TABLE" not in rendered
    assert "GRANT" not in rendered
    assert f"SET version_num='{REVISION}'" in rendered


def test_the_offline_downgrade_refuses_first_and_unwinds_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    refusal = rendered.index("refusing to downgrade 52a829ef718a")
    assert rendered.index("LOCK TABLE knowledge.ingest_sources") < refusal
    for table in TABLES:
        assert f"knowledge.{table}" in rendered[: rendered.index("IN ACCESS EXCLUSIVE MODE")]
        assert f"EXISTS (SELECT 1 FROM knowledge.{table})" in rendered  # noqa: S608
    for trigger in TRIGGERS:
        assert rendered.index(f"DROP TRIGGER {trigger}") > refusal
    for function in FUNCTIONS:
        assert rendered.index(f"DROP FUNCTION knowledge.{function}()") > refusal
    for index in INDEXES:
        assert rendered.index(f"DROP INDEX knowledge.{index}") > refusal
    drops = [rendered.index(f"DROP TABLE knowledge.{table} RESTRICT") for table in TABLES]
    assert min(drops) > refusal
    assert drops == sorted(drops, reverse=True)  # child before parent
    assert f"SET version_num='{PREVIOUS}'" in rendered


# ---- disposable databases -------------------------------------------------------


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """An empty catalog: the graph tests here drive Alembic themselves."""
    return empty_database_url


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        yield built
    finally:
        built.dispose()


_CATALOG_QUERIES: Final = {
    "columns": (
        "SELECT c.relname, a.attname, format_type(a.atttypid, a.atttypmod), a.attnotnull, "
        "pg_get_expr(d.adbin, d.adrelid), a.attgenerated FROM pg_attribute a "
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
    assert catalog["indexes"] >= INDEXES
    assert catalog["triggers"] >= TRIGGERS
    assert catalog["functions"] >= FUNCTIONS


def _assert_absent(engine: Engine) -> None:
    catalog = _catalog(engine)
    assert catalog["version"] == {PREVIOUS}
    assert not catalog["tables"] & set(TABLES)
    assert not catalog["indexes"] & INDEXES
    assert not catalog["triggers"] & TRIGGERS
    assert not catalog["functions"] & FUNCTIONS


@pytest.mark.database
def test_the_revision_builds_exactly_the_catalog_tables_py_declares(
    disposable_database: str, engine: Engine
) -> None:
    """The freeze, on the server: revision-built and `tables.py`-built are identical."""
    del disposable_database
    command.upgrade(_config(), "head")
    migrated = _shape(engine)
    command.downgrade(_config(), PREVIOUS)
    METADATA.create_all(engine, tables=list(COMMUNICATIONS_INGESTION_TABLES))
    try:
        declared = _shape(engine)
    finally:
        METADATA.drop_all(engine, tables=list(COMMUNICATIONS_INGESTION_TABLES))
    for key in _CATALOG_QUERIES:
        assert migrated[key] == declared[key], (
            key,
            sorted(migrated[key] - declared[key]),
            sorted(declared[key] - migrated[key]),
        )
    assert len(migrated["columns"]) == sum(len(t.c) for t in COMMUNICATIONS_INGESTION_TABLES)


@pytest.mark.database
def test_the_revision_round_trips_from_the_provider_binding_head(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), "head")
    _assert_present(engine)
    command.downgrade(_config(), PREVIOUS)
    _assert_absent(engine)
    command.upgrade(_config(), "head")
    _assert_present(engine)


@pytest.mark.database
def test_every_foreign_key_is_composite_with_the_principal_and_restricts(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), "head")
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
    assert len(rows) == 18
    for table, name, deltype, columns in rows:
        assert deltype == "r", (table, name)
        assert "principal_id" in columns, (table, name)


@pytest.mark.database
def test_the_search_document_is_generated_in_english(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), "head")
    seed = _Seed()
    with engine.begin() as connection:
        seed.plant(connection)
        hits = connection.execute(
            text(
                "SELECT message_id FROM knowledge.communication_messages "
                "WHERE search_document @@ to_tsquery('english', :q)"
            ),
            {"q": "pouring & schedules"},
        ).scalars()
        assert seed.m1 in set(hits)
        assert not connection.execute(
            text(
                "SELECT 1 FROM knowledge.communication_messages "
                "WHERE search_document @@ to_tsquery('english', 'gypsum')"
            )
        ).first()
        weights = connection.execute(
            text(
                "SELECT search_document::text FROM knowledge.communication_messages "
                "WHERE message_id = :m"
            ),
            {"m": seed.m1},
        ).scalar_one()
    assert "'pour':1A" in weights
    assert "'concret':" in weights


# ---- the seed ----------------------------------------------------------------------


_COUNTER = count(1000)


def _n() -> str:
    return f"{next(_COUNTER):08d}"


@dataclass
class _Seed:
    """One full chain for `P`, a few leaves to delete, and a little of `OTHER`."""

    s1: str = "isrc_seedsrc0001"
    s2: str = "isrc_seedsrc0002"
    s3: str = "isrc_seedsrc0003"
    so: str = "isrc_seedsrc0009"
    n1: str = "isnp_seedsnp0001"
    n2: str = "isnp_seedsnp0002"
    n3: str = "isnp_seedsnp0003"
    ns2: str = "isnp_seedsnp0004"
    no: str = "isnp_seedsnp0009"
    r1: str = "irun_seedrun0001"
    r2: str = "irun_seedrun0002"
    ro: str = "irun_seedrun0009"
    c1: str = "icov_seedcov0001"
    m1: str = "cmsg_seedmsg0001"
    m2: str = "cmsg_seedmsg0002"
    mo: str = "cmsg_seedmsg0009"
    i1: str = "cmitm_seeditm0001"
    i2: str = "cmitm_seeditm0002"
    io_: str = "cmitm_seeditm0009"
    o1: str = "cobs_seedobs0001"
    o2: str = "cobs_seedobs0002"
    oo: str = "cobs_seedobs0009"
    q1: str = "cqrn_seedqrn0001"

    # -- fresh, valid rows (unique keys drawn from the counter) --------------

    def source(self, **o: object) -> dict[str, object]:
        n = _n()
        row: dict[str, object] = {
            "ingest_source_id": f"isrc_new{n}",
            "principal_id": P,
            "consumer": "communications_evidence_v2",
            "workspace_id": "mcp",
            "path_prefix": f"My PA/Daily Intelligence/c{n}/",
            "file_pattern": "*-comms.json",
            "enabled": True,
            "admitted_at": WHEN,
            "admitted_by": "operator_cli",
        }
        return {**row, **o}

    def snapshot(self, **o: object) -> dict[str, object]:
        n = _n()
        row: dict[str, object] = {
            "snapshot_id": f"isnp_new{n}",
            "principal_id": P,
            "ingest_source_id": self.s1,
            "file_sha256": f"{int(n):064x}",
            "byte_count": 10,
            "observed_version_token": "v1",
            "first_seen_at": WHEN,
            "status": "pending",
            "rejection_code": None,
            "parser_version": None,
        }
        return {**row, **o}

    def path(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "snapshot_id": self.n1,
            "ingest_source_id": self.s1,
            "relative_path": f"p{_n()}.json",
            "first_seen_at": WHEN,
            "superseded_by_snapshot_id": None,
            "superseded_at": None,
        }
        return {**row, **o}

    def run(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "run_id": f"irun_new{_n()}",
            "principal_id": P,
            "ingest_source_id": self.s1,
            "trigger": "backfill",
            "started_at": WHEN,
            "finished_at": None,
            "outcome": None,
            "counts": None,
        }
        merged = {**row, **o}
        if merged["counts"] is None:
            # Bare JSONB binds `None` as a JSON null, not SQL NULL: omit the key.
            del merged["counts"]
        return merged

    def run_snapshot(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "run_id": self.r2,
            "snapshot_id": self.n2,
            "ingest_source_id": self.s1,
            "outcome": "ingested",
            "recorded_at": WHEN,
        }
        return {**row, **o}

    def coverage(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "coverage_window_id": f"icov_new{_n()}",
            "principal_id": P,
            "ingest_source_id": self.s1,
            "snapshot_id": self.n2,
            "start_utc": WHEN,
            "end_utc": WHEN + timedelta(hours=24),
            "coverage_state": "complete",
            "lane_states": [
                {
                    "key_kind": "inbox",
                    "role": "inbox",
                    "lane": "mail",
                    "authorized": True,
                    "state": "complete",
                }
            ],
            "recorded_at": WHEN,
        }
        return {**row, **o}

    def message(self, **o: object) -> dict[str, object]:
        n = _n()
        row: dict[str, object] = {
            "message_id": f"cmsg_new{n}",
            "principal_id": P,
            "mailbox_ref": "mbx-synthetic",
            "identity_kind": "provider_returned",
            "identity_value": f"<m{n}@example.invalid>",
            "conversation_id": "conv-1",
            "subject": "Pour schedule",
            "sender_address": "a@example.invalid",
            "message_time": WHEN,
            "message_time_basis": "sent",
            "has_attachments": False,
            "body_state": "present",
            "body_sha256": "d" * 64,
            "body_utf8_bytes": 100,
            "content_type": "text",
            "search_text": "The concrete pouring for RFI 174 is in two schedules",
            "search_text_sha256": "e" * 64,
            "search_text_version": "comms_search_text_v1",
            "search_text_basis": "body_content",
            "search_text_flags": [],
            "text_snapshot_id": self.n1,
            "text_record_ordinal": 0,
            "first_snapshot_id": self.n1,
            "latest_snapshot_id": self.n1,
            "identity_conflict": False,
            "participants_reconciled": False,
            "participants_disagreed": False,
        }
        return {**row, **o}

    def item(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "item_id": f"cmitm_new{_n()}",
            "principal_id": P,
            "message_id": self.m1,
            "mailbox_ref": "mbx-synthetic",
            "provider_id": f"AAMk-{_n()}",
            "provider_id_format": "mutable",
            "first_snapshot_id": self.n1,
        }
        return {**row, **o}

    def observation(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "observation_id": f"cobs_new{_n()}",
            "principal_id": P,
            "item_id": self.i1,
            "snapshot_id": self.n1,
            "record_ordinal": int(_n()),
            "classification": "accepted",
            "reasons": [],
            "folder_role": "inbox",
            "lane_verification": "verified",
            "selected_field": "received",
            "selected_utc": WHEN,
            "received_utc": WHEN,
            "received_state": "present",
            "sent_utc": None,
            "sent_state": "absent",
            "body_sha256": "d" * 64,
            "unique_body_sha256": None,
            "participants": {"from": ["a@example.invalid"], "to": ["b@example.invalid"]},
        }
        return {**row, **o}

    def participant(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "message_id": self.m1,
            "field": "to",
            "address": f"p{_n()}@example.invalid",
            "first_observation_id": self.o1,
        }
        return {**row, **o}

    def identifier(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "principal_id": P,
            "message_id": self.m1,
            "kind": "rfi",
            "value": _n(),
            "extractor_version": "comms_identifiers_v1",
        }
        return {**row, **o}

    def quarantine(self, **o: object) -> dict[str, object]:
        row: dict[str, object] = {
            "quarantine_id": f"cqrn_new{_n()}",
            "principal_id": P,
            "snapshot_id": self.n1,
            "record_ordinal": int(_n()),
            "reasons": ["missing_required_field"],
        }
        return {**row, **o}

    # -- the planted chain ----------------------------------------------------

    def plant(self, connection: Connection) -> None:
        def put(table: Table, **row: object) -> None:
            connection.execute(insert(table).values(**row))

        put(ingest_sources, **self.source(ingest_source_id=self.s1))
        put(ingest_sources, **self.source(ingest_source_id=self.s2))
        put(ingest_sources, **self.source(ingest_source_id=self.s3))
        put(ingest_sources, **self.source(ingest_source_id=self.so, principal_id=OTHER))
        put(
            ingest_snapshots,
            **self.snapshot(
                snapshot_id=self.n1,
                file_sha256="a" * 64,
                status="ingested",
                parser_version="evidence_v2-1.0",
            ),
        )
        put(ingest_snapshots, **self.snapshot(snapshot_id=self.n2, file_sha256="b" * 64))
        put(ingest_snapshots, **self.snapshot(snapshot_id=self.n3, file_sha256="c" * 64))
        put(ingest_snapshots, **self.snapshot(snapshot_id=self.ns2, ingest_source_id=self.s2))
        put(
            ingest_snapshots,
            **self.snapshot(snapshot_id=self.no, principal_id=OTHER, ingest_source_id=self.so),
        )
        put(ingest_snapshot_paths, **self.path(relative_path="a.json"))
        put(ingest_snapshot_paths, **self.path(snapshot_id=self.n2, relative_path="b.json"))
        put(ingest_runs, **self.run(run_id=self.r1))
        put(ingest_runs, **self.run(run_id=self.r2))
        put(
            ingest_runs,
            **self.run(run_id=self.ro, principal_id=OTHER, ingest_source_id=self.so),
        )
        put(ingest_run_snapshots, **self.run_snapshot(run_id=self.r1, snapshot_id=self.n1))
        put(
            ingest_coverage_windows,
            **self.coverage(coverage_window_id=self.c1, snapshot_id=self.n1),
        )
        put(communication_messages, **self.message(message_id=self.m1))
        put(communication_messages, **self.message(message_id=self.m2, subject="Another"))
        put(
            communication_messages,
            **self.message(
                message_id=self.mo,
                principal_id=OTHER,
                text_snapshot_id=self.no,
                first_snapshot_id=self.no,
                latest_snapshot_id=self.no,
            ),
        )
        put(communication_mailbox_items, **self.item(item_id=self.i1))
        put(communication_mailbox_items, **self.item(item_id=self.i2))
        put(
            communication_mailbox_items,
            **self.item(
                item_id=self.io_, principal_id=OTHER, message_id=self.mo, first_snapshot_id=self.no
            ),
        )
        put(communication_observations, **self.observation(observation_id=self.o1))
        put(communication_observations, **self.observation(observation_id=self.o2))
        put(
            communication_observations,
            **self.observation(
                observation_id=self.oo, principal_id=OTHER, item_id=self.io_, snapshot_id=self.no
            ),
        )
        put(
            communication_participants,
            **self.participant(field="from", address="a@example.invalid"),
        )
        put(communication_identifiers, **self.identifier(value="174"))
        put(communication_quarantine, **self.quarantine(quarantine_id=self.q1))


@pytest.fixture
def seeded(cloned_database_url: str) -> Iterator[tuple[Engine, _Seed]]:
    """A current-head clone with the planted chain."""
    built = create_database_engine(cloned_database_url)
    seed = _Seed()
    try:
        with built.begin() as connection:
            seed.plant(connection)
        yield built, seed
    finally:
        built.dispose()


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
    accepted once `lift` (dropping that one constraint or disabling that one
    trigger) runs first; otherwise a description of what went wrong."""
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


_TABLE: Final = {table.name: table for table in COMMUNICATIONS_INGESTION_TABLES}


def _inserting(table: str, row: dict[str, object]) -> Callable[[Connection], Any]:
    return lambda connection: connection.execute(insert(_TABLE[table]).values(**row))


# ---- CHECK constraints -----------------------------------------------------------------


def _check_cases(seed: _Seed) -> list[tuple[str, str, dict[str, object]]]:
    """`(table, constraint, row)`: each row violates exactly that one CHECK."""
    s = seed
    x = "x"
    return [
        # ingest_sources
        (
            "ingest_sources",
            "ingest_source_id_is_an_opaque_identifier",
            s.source(ingest_source_id="isrc_bad!"),
        ),
        ("ingest_sources", "principal_id_is_an_opaque_identifier", s.source(principal_id="prn_x")),
        ("ingest_sources", "an_ingest_source_consumer_is_known", s.source(consumer="gmail_v1")),
        ("ingest_sources", "an_ingest_source_workspace_is_an_alias", s.source(workspace_id="MCP")),
        (
            "ingest_sources",
            "an_ingest_source_path_prefix_is_relative_and_bounded",
            s.source(path_prefix="/abs/"),
        ),
        (
            "ingest_sources",
            "an_ingest_source_path_prefix_is_relative_and_bounded",
            s.source(path_prefix="a/../b/"),
        ),
        (
            "ingest_sources",
            "an_ingest_source_path_prefix_is_relative_and_bounded",
            s.source(path_prefix=x * 1025),
        ),
        (
            "ingest_sources",
            "an_ingest_source_file_pattern_is_one_bounded_name",
            s.source(file_pattern="a/*.json"),
        ),
        (
            "ingest_sources",
            "an_ingest_source_file_pattern_is_one_bounded_name",
            s.source(file_pattern=""),
        ),
        (
            "ingest_sources",
            "an_ingest_source_is_admitted_by_the_operator_cli",
            s.source(admitted_by="mcp"),
        ),
        # ingest_snapshots
        (
            "ingest_snapshots",
            "snapshot_id_is_an_opaque_identifier",
            s.snapshot(snapshot_id="isnp_bad!"),
        ),
        (
            "ingest_snapshots",
            "an_ingest_snapshot_digest_is_sha256",
            s.snapshot(file_sha256="A" * 64),
        ),
        (
            "ingest_snapshots",
            "an_ingest_snapshot_byte_count_is_non_negative",
            s.snapshot(byte_count=-1),
        ),
        (
            "ingest_snapshots",
            "an_ingest_snapshot_version_token_is_bounded",
            s.snapshot(observed_version_token=""),
        ),
        ("ingest_snapshots", "an_ingest_snapshot_status_is_known", s.snapshot(status="superseded")),
        (
            "ingest_snapshots",
            "an_ingest_snapshot_rejection_code_is_a_token",
            s.snapshot(status="rejected", rejection_code="Bad Code"),
        ),
        (
            "ingest_snapshots",
            "an_ingest_snapshot_parser_version_is_a_token",
            s.snapshot(status="ingested", parser_version="Bad Version"),
        ),
        (
            "ingest_snapshots",
            "a_rejected_ingest_snapshot_names_its_code",
            s.snapshot(status="rejected"),
        ),
        (
            "ingest_snapshots",
            "a_rejected_ingest_snapshot_names_its_code",
            s.snapshot(status="ingested", parser_version="p1", rejection_code="malformed_json"),
        ),
        (
            "ingest_snapshots",
            "a_pending_ingest_snapshot_names_no_parser",
            s.snapshot(parser_version="p1"),
        ),
        (
            "ingest_snapshots",
            "an_ingested_snapshot_names_its_parser",
            s.snapshot(status="ingested"),
        ),
        # ingest_snapshot_paths
        (
            "ingest_snapshot_paths",
            "an_ingest_snapshot_path_is_relative_and_bounded",
            s.path(relative_path="/a.json"),
        ),
        (
            "ingest_snapshot_paths",
            "an_ingest_snapshot_path_is_relative_and_bounded",
            s.path(relative_path="../a.json"),
        ),
        (
            "ingest_snapshot_paths",
            "an_ingest_snapshot_path_is_relative_and_bounded",
            s.path(relative_path=""),
        ),
        (
            "ingest_snapshot_paths",
            "an_ingest_snapshot_path_supersession_is_whole",
            s.path(superseded_by_snapshot_id=s.n2),
        ),
        (
            "ingest_snapshot_paths",
            "an_ingest_snapshot_path_supersession_is_whole",
            s.path(superseded_at=WHEN),
        ),
        (
            "ingest_snapshot_paths",
            "an_ingest_snapshot_path_is_not_superseded_by_itself",
            s.path(superseded_by_snapshot_id=s.n1, superseded_at=WHEN),
        ),
        # ingest_runs
        ("ingest_runs", "run_id_is_an_opaque_identifier", s.run(run_id="irun_bad!")),
        ("ingest_runs", "an_ingest_run_trigger_is_known", s.run(trigger="cron")),
        (
            "ingest_runs",
            "an_ingest_run_outcome_is_known",
            s.run(finished_at=WHEN, outcome="done", counts={}),
        ),
        ("ingest_runs", "an_ingest_run_finish_is_whole", s.run(finished_at=WHEN)),
        (
            "ingest_runs",
            "an_ingest_run_finish_is_whole",
            s.run(finished_at=WHEN, outcome="completed"),
        ),
        (
            "ingest_runs",
            "an_ingest_run_finishes_after_it_starts",
            s.run(finished_at=WHEN - timedelta(seconds=1), outcome="completed", counts={}),
        ),
        (
            "ingest_runs",
            "an_ingest_run_counts_is_an_object",
            s.run(finished_at=WHEN, outcome="completed", counts=[1]),
        ),
        # ingest_run_snapshots
        (
            "ingest_run_snapshots",
            "an_ingest_run_snapshot_outcome_is_known",
            s.run_snapshot(outcome="skipped"),
        ),
        # ingest_coverage_windows
        (
            "ingest_coverage_windows",
            "coverage_window_id_is_an_opaque_identifier",
            s.coverage(coverage_window_id="icov_bad!"),
        ),
        (
            "ingest_coverage_windows",
            "an_ingest_coverage_window_ends_at_or_after_its_start",
            s.coverage(end_utc=WHEN - timedelta(seconds=1)),
        ),
        (
            "ingest_coverage_windows",
            "an_ingest_coverage_state_is_known",
            s.coverage(coverage_state="great"),
        ),
        (
            "ingest_coverage_windows",
            "an_ingest_coverage_lane_states_is_an_array",
            s.coverage(lane_states={}),
        ),
        # communication_messages
        (
            "communication_messages",
            "message_id_is_an_opaque_identifier",
            s.message(message_id="cmsg_bad!"),
        ),
        (
            "communication_messages",
            "a_communication_mailbox_ref_is_bounded",
            s.message(mailbox_ref=""),
        ),
        (
            "communication_messages",
            "a_communication_identity_kind_is_known",
            s.message(identity_kind="dedup_key"),
        ),
        (
            "communication_messages",
            "a_communication_identity_value_is_bounded",
            s.message(identity_value=""),
        ),
        (
            "communication_messages",
            "a_communication_conversation_id_is_bounded",
            s.message(conversation_id=""),
        ),
        (
            "communication_messages",
            "a_communication_subject_is_bounded",
            s.message(subject=x * 16385),
        ),
        (
            "communication_messages",
            "a_communication_sender_is_a_normalized_address",
            s.message(sender_address="A@example.invalid"),
        ),
        (
            "communication_messages",
            "a_communication_sender_is_a_normalized_address",
            s.message(sender_address=""),
        ),
        (
            "communication_messages",
            "a_communication_message_time_basis_is_known",
            s.message(message_time_basis="header"),
        ),
        (
            "communication_messages",
            "a_communication_body_state_is_known",
            s.message(body_state="gone"),
        ),
        (
            "communication_messages",
            "a_communication_body_digest_is_sha256",
            s.message(body_sha256="z" * 64),
        ),
        (
            "communication_messages",
            "a_communication_body_byte_count_is_non_negative",
            s.message(body_utf8_bytes=-1),
        ),
        (
            "communication_messages",
            "a_communication_content_type_is_known",
            s.message(content_type="pdf"),
        ),
        (
            "communication_messages",
            "a_communication_search_text_is_bounded",
            s.message(search_text=x * 262145),
        ),
        (
            "communication_messages",
            "a_communication_search_text_digest_is_sha256",
            s.message(search_text_sha256="E" * 64),
        ),
        (
            "communication_messages",
            "a_communication_search_text_has_its_digest",
            s.message(search_text_sha256=None),
        ),
        (
            "communication_messages",
            "a_communication_search_text_version_is_a_token",
            s.message(search_text_version="V1"),
        ),
        (
            "communication_messages",
            "a_communication_search_text_basis_is_known",
            s.message(search_text_basis="quoted"),
        ),
        (
            "communication_messages",
            "a_communication_search_text_without_basis_is_null",
            s.message(search_text_basis="none"),
        ),
        (
            "communication_messages",
            "a_communication_search_text_without_basis_is_null",
            s.message(search_text=None, search_text_sha256=None),
        ),
        (
            "communication_messages",
            "a_communication_search_text_flag_is_known",
            s.message(search_text_flags=["bogus"]),
        ),
        (
            "communication_messages",
            "a_withheld_or_truncated_body_has_no_search_text",
            s.message(body_state="withheld"),
        ),
        (
            "communication_messages",
            "a_withheld_or_truncated_body_has_no_search_text",
            s.message(body_state="truncated"),
        ),
        (
            "communication_messages",
            "a_communication_text_ordinal_is_non_negative",
            s.message(text_record_ordinal=-1),
        ),
        # communication_mailbox_items
        (
            "communication_mailbox_items",
            "item_id_is_an_opaque_identifier",
            s.item(item_id="cmitm_bad!"),
        ),
        (
            "communication_mailbox_items",
            "a_mailbox_item_provider_id_is_bounded",
            s.item(provider_id=""),
        ),
        (
            "communication_mailbox_items",
            "a_mailbox_item_provider_id_format_is_known",
            s.item(provider_id_format="stable"),
        ),
        # communication_observations
        (
            "communication_observations",
            "observation_id_is_an_opaque_identifier",
            s.observation(observation_id="cobs_bad!"),
        ),
        (
            "communication_observations",
            "a_communication_observation_ordinal_is_non_negative",
            s.observation(record_ordinal=-1),
        ),
        (
            "communication_observations",
            "a_communication_observation_classification_is_known",
            s.observation(classification="quarantined"),
        ),
        (
            "communication_observations",
            "a_communication_observation_reason_is_a_degradation",
            s.observation(reasons=["missing_required_field"]),
        ),
        (
            "communication_observations",
            "a_communication_observation_reason_is_a_degradation",
            s.observation(reasons=["bogus"]),
        ),
        (
            "communication_observations",
            "a_communication_observation_folder_role_is_known",
            s.observation(folder_role="junk"),
        ),
        (
            "communication_observations",
            "a_communication_observation_lane_verification_is_known",
            s.observation(lane_verification="trusted"),
        ),
        (
            "communication_observations",
            "a_communication_observation_selected_field_is_known",
            s.observation(selected_field="created"),
        ),
        (
            "communication_observations",
            "a_communication_observation_received_state_is_known",
            s.observation(received_state="later", received_utc=None),
        ),
        (
            "communication_observations",
            "a_communication_observation_sent_state_is_known",
            s.observation(sent_state="later"),
        ),
        (
            "communication_observations",
            "a_communication_observation_received_time_matches_its_state",
            s.observation(received_utc=None),
        ),
        (
            "communication_observations",
            "a_communication_observation_sent_time_matches_its_state",
            s.observation(sent_utc=WHEN),
        ),
        (
            "communication_observations",
            "a_communication_observation_body_digest_is_sha256",
            s.observation(body_sha256="nothex"),
        ),
        (
            "communication_observations",
            "a_communication_observation_unique_body_digest_is_sha256",
            s.observation(unique_body_sha256="nothex"),
        ),
        (
            "communication_observations",
            "a_communication_observation_participants_is_an_object",
            s.observation(participants=[]),
        ),
        # communication_participants
        (
            "communication_participants",
            "a_communication_participant_field_is_known",
            s.participant(field="subject"),
        ),
        (
            "communication_participants",
            "a_communication_participant_is_a_normalized_address",
            s.participant(address="Upper@example.invalid"),
        ),
        (
            "communication_participants",
            "a_communication_participant_is_a_normalized_address",
            s.participant(address=""),
        ),
        # communication_identifiers
        (
            "communication_identifiers",
            "a_communication_identifier_kind_is_known",
            s.identifier(kind="pco"),
        ),
        (
            "communication_identifiers",
            "a_communication_identifier_value_is_bounded",
            s.identifier(value=""),
        ),
        (
            "communication_identifiers",
            "a_communication_identifier_extractor_version_is_a_token",
            s.identifier(extractor_version="V1"),
        ),
        # communication_quarantine
        (
            "communication_quarantine",
            "quarantine_id_is_an_opaque_identifier",
            s.quarantine(quarantine_id="cqrn_bad!"),
        ),
        (
            "communication_quarantine",
            "a_communication_quarantine_ordinal_is_non_negative",
            s.quarantine(record_ordinal=-1),
        ),
        (
            "communication_quarantine",
            "a_communication_quarantine_names_a_reason",
            s.quarantine(reasons=[]),
        ),
        (
            "communication_quarantine",
            "a_communication_quarantine_reason_is_known",
            s.quarantine(reasons=["bogus"]),
        ),
    ]


@pytest.mark.database
def test_every_check_refuses_its_case_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _check_cases(seed)
    failures = [
        (table, constraint, problem)
        for table, constraint, row in cases
        if (
            problem := _isolated(
                engine,
                _inserting(table, row),
                sqlstate=CHECK,
                constraint=constraint,
                lift=f"ALTER TABLE knowledge.{table} DROP CONSTRAINT {constraint}",
            )
        )
        is not None
    ]
    assert failures == []
    # Every CHECK the WP3a tables declare that is not a pure identifier-shape
    # CHECK on a foreign-key column has a case here (those are isolated by the
    # foreign key itself and covered by their primary-key siblings).
    covered = {(table, constraint) for table, constraint, _row in cases}
    declared = {
        (table.name, str(constraint.name))
        for table in COMMUNICATIONS_INGESTION_TABLES
        for constraint in table.constraints
        if type(constraint).__name__ == "CheckConstraint"
    }
    uncovered = {
        (table, name)
        for table, name in declared - covered
        if not name.endswith("_is_an_opaque_identifier")
    }
    assert uncovered == _HELD_ALSO_BY_A_FOREIGN_KEY
    # Those are refused by their CHECK first, but not by it alone.
    for table, constraint in sorted(_HELD_ALSO_BY_A_FOREIGN_KEY):
        refused = _attempt(engine, _inserting(table, seed.item(mailbox_ref="")))
        assert refused is not None
        assert (_sqlstate(refused), _constraint(refused)) == (CHECK, constraint)


#: A CHECK whose violating row the composite foreign key also refuses, so it
#: cannot be isolated: an item's `mailbox_ref` must equal its message's, which
#: is itself bounded. The bound is defence in depth, reported, not claimed.
_HELD_ALSO_BY_A_FOREIGN_KEY: Final = frozenset(
    {("communication_mailbox_items", "a_mailbox_item_mailbox_ref_is_bounded")}
)


# ---- UNIQUE constraints ------------------------------------------------------------------


def _copying(table: str, key: str, value: str, **overrides: object) -> Callable[[Connection], Any]:
    """Insert a copy of one stored row (all columns but the generated one) with `overrides`."""

    def statement(connection: Connection) -> None:
        target = _TABLE[table]
        stored = connection.execute(target.select().where(target.c[key] == value)).mappings().one()
        values = {name: stored[name] for name in stored if name != "search_document"}
        connection.execute(insert(target).values(**{**values, **overrides}))

    return statement


def _unique_cases(seed: _Seed) -> list[tuple[str, Callable[[Connection], Any], str]]:
    """`(constraint, statement, lift)`: each statement duplicates exactly one key."""
    s = seed

    def drop(table: str, name: str) -> str:
        return f"ALTER TABLE knowledge.{table} DROP CONSTRAINT {name} CASCADE"

    return [
        (
            "one_ingest_source_per_location",
            _copying(
                "ingest_sources", "ingest_source_id", s.s1, ingest_source_id=f"isrc_dup{_n()}"
            ),
            drop("ingest_sources", "one_ingest_source_per_location"),
        ),
        (
            "one_ingest_snapshot_per_source_content",
            _inserting("ingest_snapshots", s.snapshot(file_sha256="a" * 64)),
            drop("ingest_snapshots", "one_ingest_snapshot_per_source_content"),
        ),
        (
            "one_current_ingest_snapshot_per_path",
            _inserting("ingest_snapshot_paths", s.path(snapshot_id=s.n3, relative_path="a.json")),
            "DROP INDEX knowledge.one_current_ingest_snapshot_per_path",
        ),
        (
            "ingest_snapshot_paths_pkey",
            _inserting(
                "ingest_snapshot_paths",
                s.path(relative_path="a.json", superseded_by_snapshot_id=s.n2, superseded_at=WHEN),
            ),
            drop("ingest_snapshot_paths", "ingest_snapshot_paths_pkey"),
        ),
        (
            "ingest_run_snapshots_pkey",
            _inserting("ingest_run_snapshots", s.run_snapshot(run_id=s.r1, snapshot_id=s.n1)),
            drop("ingest_run_snapshots", "ingest_run_snapshots_pkey"),
        ),
        (
            "one_ingest_coverage_window_per_snapshot",
            _inserting("ingest_coverage_windows", s.coverage(snapshot_id=s.n1)),
            drop("ingest_coverage_windows", "one_ingest_coverage_window_per_snapshot"),
        ),
        (
            "one_communication_message_per_identity",
            _copying("communication_messages", "message_id", s.m1, message_id=f"cmsg_dup{_n()}"),
            drop("communication_messages", "one_communication_message_per_identity"),
        ),
        (
            "one_mailbox_item_per_provider_id",
            _copying("communication_mailbox_items", "item_id", s.i1, item_id=f"cmitm_dup{_n()}"),
            drop("communication_mailbox_items", "one_mailbox_item_per_provider_id"),
        ),
        (
            "one_communication_observation_per_record",
            _copying(
                "communication_observations",
                "observation_id",
                s.o1,
                observation_id=f"cobs_dup{_n()}",
                item_id=s.i2,
            ),
            drop("communication_observations", "one_communication_observation_per_record"),
        ),
        (
            "communication_participants_pkey",
            _inserting(
                "communication_participants",
                s.participant(field="from", address="a@example.invalid", first_observation_id=s.o2),
            ),
            drop("communication_participants", "communication_participants_pkey"),
        ),
        (
            "communication_identifiers_pkey",
            _inserting("communication_identifiers", s.identifier(value="174")),
            drop("communication_identifiers", "communication_identifiers_pkey"),
        ),
        (
            "one_communication_quarantine_per_record",
            _copying(
                "communication_quarantine", "quarantine_id", s.q1, quarantine_id=f"cqrn_dup{_n()}"
            ),
            drop("communication_quarantine", "one_communication_quarantine_per_record"),
        ),
    ]


@pytest.mark.database
def test_every_unique_key_refuses_its_duplicate_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _unique_cases(seed)
    failures = [
        (constraint, problem)
        for constraint, statement, lift in cases
        if (
            problem := _isolated(
                engine, statement, sqlstate=UNIQUE, constraint=constraint, lift=lift
            )
        )
        is not None
    ]
    assert failures == []
    declared = {
        str(constraint.name)
        for table in COMMUNICATIONS_INGESTION_TABLES
        for constraint in table.constraints
        if type(constraint).__name__ == "UniqueConstraint"
    } | {
        str(index.name)
        for table in COMMUNICATIONS_INGESTION_TABLES
        for index in table.indexes
        if index.unique
    }
    # The `..._is_identified_within_...` keys exist to be foreign-key targets;
    # every other unique key has a duplicate case.
    covered = {constraint for constraint, _statement, _lift in cases}
    assert {name for name in declared - covered if "_is_identified_within_" not in name} == set()


# ---- FOREIGN KEY constraints -------------------------------------------------------------


def _foreign_cases(seed: _Seed) -> list[tuple[str, str, dict[str, object]]]:
    """`(table, constraint, row)`: each row crosses exactly one partition or source."""
    s = seed
    return [
        (
            "ingest_snapshots",
            "an_ingest_snapshot_names_a_source_of_its_principal",
            s.snapshot(ingest_source_id=s.so),
        ),
        (
            "ingest_snapshot_paths",
            "an_ingest_snapshot_path_names_a_snapshot_of_its_source",
            s.path(ingest_source_id=s.s2),
        ),
        (
            "ingest_snapshot_paths",
            "an_ingest_snapshot_path_is_superseded_by_its_sources_snapshot",
            s.path(superseded_by_snapshot_id=s.ns2, superseded_at=WHEN),
        ),
        (
            "ingest_runs",
            "an_ingest_run_names_a_source_of_its_principal",
            s.run(ingest_source_id=s.so),
        ),
        (
            "ingest_run_snapshots",
            "an_ingest_run_snapshot_names_a_run_of_its_source",
            s.run_snapshot(run_id=s.ro),
        ),
        (
            "ingest_run_snapshots",
            "an_ingest_run_snapshot_names_a_snapshot_of_its_source",
            s.run_snapshot(snapshot_id=s.ns2),
        ),
        (
            "ingest_coverage_windows",
            "an_ingest_coverage_window_names_a_snapshot_of_its_source",
            s.coverage(snapshot_id=s.ns2),
        ),
        (
            "communication_messages",
            "a_communication_text_names_a_snapshot_of_its_principal",
            s.message(text_snapshot_id=s.no),
        ),
        (
            "communication_messages",
            "a_communication_first_snapshot_is_of_its_principal",
            s.message(first_snapshot_id=s.no),
        ),
        (
            "communication_messages",
            "a_communication_latest_snapshot_is_of_its_principal",
            s.message(latest_snapshot_id=s.no),
        ),
        (
            "communication_mailbox_items",
            "a_mailbox_item_names_a_message_of_its_mailbox",
            s.item(mailbox_ref="mbx-other"),
        ),
        (
            "communication_mailbox_items",
            "a_mailbox_item_names_a_message_of_its_mailbox",
            s.item(message_id=s.mo),
        ),
        (
            "communication_mailbox_items",
            "a_mailbox_item_first_snapshot_is_of_its_principal",
            s.item(first_snapshot_id=s.no),
        ),
        (
            "communication_observations",
            "a_communication_observation_names_an_item_of_its_principal",
            s.observation(item_id=s.io_),
        ),
        (
            "communication_observations",
            "a_communication_observation_names_a_snapshot_of_its_principal",
            s.observation(snapshot_id=s.no),
        ),
        (
            "communication_participants",
            "a_communication_participant_names_a_message_of_its_principal",
            s.participant(message_id=s.mo),
        ),
        (
            "communication_participants",
            "a_communication_participant_names_an_observation_of_its_owner",
            s.participant(first_observation_id=s.oo),
        ),
        (
            "communication_identifiers",
            "a_communication_identifier_names_a_message_of_its_principal",
            s.identifier(message_id=s.mo),
        ),
        (
            "communication_quarantine",
            "a_communication_quarantine_names_a_snapshot_of_its_principal",
            s.quarantine(snapshot_id=s.no),
        ),
    ]


@pytest.mark.database
def test_every_foreign_key_refuses_a_crossing_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _foreign_cases(seed)
    failures = [
        (table, constraint, problem)
        for table, constraint, row in cases
        if (
            problem := _isolated(
                engine,
                _inserting(table, row),
                sqlstate=FOREIGN,
                constraint=constraint,
                lift=f"ALTER TABLE knowledge.{table} DROP CONSTRAINT {constraint}",
            )
        )
        is not None
    ]
    assert failures == []
    declared = {
        str(constraint.name)
        for table in COMMUNICATIONS_INGESTION_TABLES
        for constraint in table.constraints
        if type(constraint).__name__ == "ForeignKeyConstraint"
    }
    # Every one of the 18 declared foreign keys has a crossing case.
    assert declared - {constraint for _t, constraint, _r in cases} == set()


# ---- triggers --------------------------------------------------------------------------------


def _set(table: Table, where: ColumnElement[bool], **values: object) -> Callable[[Connection], Any]:
    return lambda connection: connection.execute(update(table).where(where).values(**values))


def _remove(table: Table, where: ColumnElement[bool]) -> Callable[[Connection], Any]:
    return lambda connection: connection.execute(delete(table).where(where))


def _refused_trigger_cases(seed: _Seed) -> list[tuple[str, str, Callable[[Connection], Any]]]:
    """`(label, trigger, statement)`: each statement is refused by that one trigger."""
    s = seed
    src, snp, pth, run = ingest_sources, ingest_snapshots, ingest_snapshot_paths, ingest_runs
    msg = communication_messages
    m2 = msg.c.message_id == s.m2
    p1 = (pth.c.snapshot_id == s.n1) & (pth.c.relative_path == "a.json")
    cases: list[tuple[str, str, Callable[[Connection], Any]]] = [
        (
            "source: file_pattern",
            "ingest_sources_change_only_enabled",
            _set(src, src.c.ingest_source_id == s.s3, file_pattern="*.json"),
        ),
        (
            "source: admitted_at",
            "ingest_sources_change_only_enabled",
            _set(src, src.c.ingest_source_id == s.s3, admitted_at=WHEN + timedelta(days=1)),
        ),
        (
            "source: delete",
            "ingest_sources_change_only_enabled",
            _remove(src, src.c.ingest_source_id == s.s3),
        ),
        (
            "snapshot: terminal is immutable",
            "ingest_snapshots_finalize_once",
            _set(
                snp, snp.c.snapshot_id == s.n1, status="rejected", rejection_code="malformed_json"
            ),
        ),
        (
            "snapshot: terminal parser",
            "ingest_snapshots_finalize_once",
            _set(snp, snp.c.snapshot_id == s.n1, parser_version="evidence_v2-2.0"),
        ),
        (
            "snapshot: pending to pending",
            "ingest_snapshots_finalize_once",
            _set(snp, snp.c.snapshot_id == s.n3, status="pending"),
        ),
        (
            "snapshot: digest",
            "ingest_snapshots_finalize_once",
            _set(
                snp,
                snp.c.snapshot_id == s.n3,
                status="rejected",
                rejection_code="malformed_json",
                file_sha256="f" * 64,
            ),
        ),
        (
            "snapshot: byte count",
            "ingest_snapshots_finalize_once",
            _set(
                snp,
                snp.c.snapshot_id == s.n3,
                status="ingested",
                parser_version="p1",
                byte_count=11,
            ),
        ),
        (
            "snapshot: delete",
            "ingest_snapshots_finalize_once",
            _remove(snp, snp.c.snapshot_id == s.n3),
        ),
        (
            "path: relative_path",
            "ingest_snapshot_paths_supersede_once",
            _set(pth, p1, relative_path="z.json"),
        ),
        (
            "path: first_seen_at",
            "ingest_snapshot_paths_supersede_once",
            _set(pth, p1, first_seen_at=WHEN + timedelta(days=1)),
        ),
        ("path: delete", "ingest_snapshot_paths_supersede_once", _remove(pth, p1)),
        (
            "run: trigger",
            "ingest_runs_finish_once",
            _set(run, run.c.run_id == s.r2, trigger="operator"),
        ),
        (
            "run: started_at",
            "ingest_runs_finish_once",
            _set(run, run.c.run_id == s.r2, started_at=WHEN - timedelta(days=1)),
        ),
        ("run: delete", "ingest_runs_finish_once", _remove(run, run.c.run_id == s.r2)),
        (
            "message: delete",
            "communication_messages_change_only_their_projection",
            _remove(msg, m2),
        ),
    ]
    for column, value in (
        ("mailbox_ref", "mbx-moved"),
        ("identity_kind", "provider_id_only"),
        ("identity_value", "<other@example.invalid>"),
        ("conversation_id", "conv-2"),
        ("subject", "Rewritten"),
        ("sender_address", "z@example.invalid"),
        ("message_time", WHEN + timedelta(hours=1)),
        ("message_time_basis", "received"),
        ("has_attachments", True),
        ("first_snapshot_id", s.n2),
    ):
        cases.append(
            (
                f"message: {column}",
                "communication_messages_change_only_their_projection",
                _set(msg, m2, **{column: value}),
            )
        )
    leaves: dict[str, tuple[ColumnElement[bool], dict[str, object]]] = {
        "ingest_run_snapshots": (
            (ingest_run_snapshots.c.run_id == s.r1) & (ingest_run_snapshots.c.snapshot_id == s.n1),
            {"outcome": "failed"},
        ),
        "ingest_coverage_windows": (
            ingest_coverage_windows.c.coverage_window_id == s.c1,
            {"coverage_state": "partial"},
        ),
        "communication_mailbox_items": (
            communication_mailbox_items.c.item_id == s.i2,
            {"provider_id_format": "unknown"},
        ),
        "communication_observations": (
            communication_observations.c.observation_id == s.o2,
            {"classification": "accepted_degraded"},
        ),
        "communication_participants": (
            communication_participants.c.address == "a@example.invalid",
            {"first_observation_id": s.o2},
        ),
        "communication_identifiers": (
            communication_identifiers.c.value == "174",
            {"extractor_version": "comms_identifiers_v2"},
        ),
        "communication_quarantine": (
            communication_quarantine.c.quarantine_id == s.q1,
            {"reasons": ["integrity_mismatch"]},
        ),
    }
    for name, (where, values) in leaves.items():
        cases.append(
            (f"{name}: update", f"{name}_are_append_only", _set(_TABLE[name], where, **values))
        )
        cases.append((f"{name}: delete", f"{name}_are_append_only", _remove(_TABLE[name], where)))
    return cases


def _trigger_table(trigger: str) -> str:
    for table, name in MUTABLE_TRIGGERS.items():
        if name == trigger:
            return table
    return trigger.removesuffix("_are_append_only")


@pytest.mark.database
def test_every_trigger_refuses_its_case_alone(seeded: tuple[Engine, _Seed]) -> None:
    engine, seed = seeded
    cases = _refused_trigger_cases(seed)
    failures = [
        (label, problem)
        for label, trigger, statement in cases
        if (
            problem := _isolated(
                engine,
                statement,
                sqlstate=RESTRICT_VIOLATION,
                constraint=None,
                lift=f"ALTER TABLE knowledge.{_trigger_table(trigger)} DISABLE TRIGGER {trigger}",
            )
        )
        is not None
    ]
    assert failures == []
    assert {trigger for _label, trigger, _statement in cases} == TRIGGERS - {
        f"{table}_refuse_truncate" for table in TABLES
    }


def _accepted(engine: Engine, *statements: Callable[[Connection], Any]) -> None:
    with engine.begin() as connection:
        for statement in statements:
            statement(connection)


@pytest.mark.database
def test_the_named_mutable_columns_change(seeded: tuple[Engine, _Seed]) -> None:
    engine, s = seeded
    src, snp, pth, run = ingest_sources, ingest_snapshots, ingest_snapshot_paths, ingest_runs
    msg = communication_messages
    _accepted(
        engine,
        _set(src, src.c.ingest_source_id == s.s1, enabled=False),
        _set(
            snp,
            snp.c.snapshot_id == s.n2,
            status="rejected",
            rejection_code="malformed_json",
            parser_version="evidence_v2-1.0",
        ),
        _set(snp, snp.c.snapshot_id == s.n3, status="ingested", parser_version="evidence_v2-1.0"),
        _set(
            pth,
            (pth.c.snapshot_id == s.n1) & (pth.c.relative_path == "a.json"),
            superseded_by_snapshot_id=s.n3,
            superseded_at=WHEN + timedelta(hours=1),
        ),
        _set(
            run,
            run.c.run_id == s.r1,
            finished_at=WHEN + timedelta(hours=1),
            outcome="partial",
            counts={"seen": 3},
        ),
        _set(
            msg,
            msg.c.message_id == s.m1,
            body_state="withheld",
            body_sha256="f" * 64,
            body_utf8_bytes=7,
            content_type="html",
            search_text=None,
            search_text_sha256=None,
            search_text_version="comms_search_text_v1",
            search_text_basis="none",
            search_text_flags=["metadata_only", "withheld"],
            text_snapshot_id=s.n3,
            text_record_ordinal=4,
            latest_snapshot_id=s.n3,
            identity_conflict=True,
            participants_reconciled=True,
            participants_disagreed=True,
        ),
    )
    with engine.connect() as connection:
        document = connection.execute(
            text(
                "SELECT search_document::text FROM knowledge.communication_messages "
                "WHERE message_id = :m"
            ),
            {"m": s.m1},
        ).scalar_one()
    # The generated document followed the projection: the text is gone, the subject stays.
    assert "'concret'" not in document
    assert "'pour':1A" in document


@pytest.mark.database
def test_from_null_columns_change_only_once(seeded: tuple[Engine, _Seed]) -> None:
    """A superseded path, a finished run and a finalized snapshot are frozen."""
    engine, s = seeded
    pth, run, snp = ingest_snapshot_paths, ingest_runs, ingest_snapshots
    p1 = (pth.c.snapshot_id == s.n1) & (pth.c.relative_path == "a.json")
    _accepted(
        engine,
        _set(pth, p1, superseded_by_snapshot_id=s.n2, superseded_at=WHEN + timedelta(hours=1)),
        _set(
            run,
            run.c.run_id == s.r1,
            finished_at=WHEN + timedelta(hours=1),
            outcome="completed",
            counts={"seen": 1},
        ),
        _set(snp, snp.c.snapshot_id == s.n2, status="ingested", parser_version="evidence_v2-1.0"),
    )
    again = (
        (
            "path",
            "ingest_snapshot_paths",
            "ingest_snapshot_paths_supersede_once",
            _set(pth, p1, superseded_by_snapshot_id=s.n3, superseded_at=WHEN + timedelta(hours=2)),
        ),
        (
            "path back to NULL",
            "ingest_snapshot_paths",
            "ingest_snapshot_paths_supersede_once",
            _set(pth, p1, superseded_by_snapshot_id=None, superseded_at=None),
        ),
        (
            "run",
            "ingest_runs",
            "ingest_runs_finish_once",
            _set(
                run,
                run.c.run_id == s.r1,
                finished_at=WHEN + timedelta(hours=2),
                outcome="failed",
                counts={"seen": 2},
            ),
        ),
        (
            "snapshot",
            "ingest_snapshots",
            "ingest_snapshots_finalize_once",
            _set(
                snp, snp.c.snapshot_id == s.n2, status="rejected", rejection_code="malformed_json"
            ),
        ),
    )
    failures = [
        (label, problem)
        for label, table, trigger, statement in again
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


@pytest.mark.database
def test_truncate_is_refused_on_every_table_by_its_own_trigger(
    seeded: tuple[Engine, _Seed],
) -> None:
    """Each table's trigger alone refuses (every other TRUNCATE trigger disabled),
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


@pytest.mark.database
def test_a_downgrade_refuses_while_one_source_exists(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), "head")
    with engine.begin() as connection:
        connection.execute(insert(ingest_sources).values(**_Seed().source()))
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert "refusing to downgrade 52a829ef718a" in str(refused.value)
    _assert_present(engine)


@pytest.mark.database
def test_a_downgrade_refuses_while_the_full_chain_exists(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), "head")
    with engine.begin() as connection:
        _Seed().plant(connection)
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert "refusing to downgrade 52a829ef718a" in str(refused.value)
    _assert_present(engine)


def test_the_declarations_module_exports_the_twelve_tables() -> None:
    assert tuple(getattr(declarations, name).name for name in TABLES) == TABLES
