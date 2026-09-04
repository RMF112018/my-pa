"""Revision `8f2b6c4d1a37`: the continuity objects, and the vocabulary it widens.

WP-11, in the shape `tests/schema/test_capture_client_migration.py` set.

**The revision is in the chain**, and deliberately not "is the head": that
property is true only until the next revision is written, and asserting it would
make every later work package edit this file.

**Empty to head, prior revision to head, and a full round trip.** `AGENTS.md`
section 6 asks for a migration tested from an empty schema to head and for the
preceding supported revision where relevant; all three are here, and the
downgrade is asserted to restore exactly the vocabulary `7a1e5f3c9d24` denotes —
twenty-seven of them — rather than whatever the domain says on the day it runs.

**The created tables match the live declaration.** The revision writes its DDL
out rather than importing `tables.py`, so it cannot change meaning when the
declaration is next edited (`D-48`); the price is drift, and this is where it is
paid — columns, named constraints and indexes read out of `pg_catalog` and
compared against `METADATA`.

**The four new tables are principal-partitioned**, which is what admits them to
the `knowledge` schema at all.

The database is disposable, created and dropped by this module's fixture, and is
never the configured one: `downgrade base` deletes schemas. Every value is
synthetic.
"""

from __future__ import annotations

import io
import re
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, Table, text

from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.situation.situation import PulseReasonCode
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import (
    METADATA,
    commitments,
    continuity_lifecycle_events,
    decisions,
    tasks,
)

ROOT: Final = Path(__file__).resolve().parents[2]

DISPOSABLE_DATABASE: Final = "my_pa_continuity_migration_test"

SCHEMA: Final = "knowledge"

#: This revision and the one it revises.
CONTINUITY_REVISION: Final = "8f2b6c4d1a37"
PREVIOUS_REVISION: Final = "7a1e5f3c9d24"

#: The four tables this revision creates, and the two it alters.
NEW_TABLES: Final = ("commitments", "decisions", "tasks", "continuity_lifecycle_events")

#: What `audit_events.capability_is_known` admitted before this revision. Written
#: out rather than derived, because the point of the downgrade assertion is that
#: the database holds the vocabulary the revision below denotes and not the
#: domain's.
CAPABILITIES_BEFORE: Final[frozenset[str]] = frozenset(
    {
        "capabilities.get",
        "capture.create",
        "capture.list",
        "capture.read",
        "capture.revise",
        "capture.search",
        "knowledge.read",
        "knowledge.reveal",
        "knowledge.search",
        "native_sources.backfill",
        "native_sources.configure",
        "native_sources.disable",
        "native_sources.discover",
        "native_sources.pause",
        "native_sources.preflight",
        "native_sources.reconcile",
        "native_sources.resume",
        "native_sources.retry",
        "native_sources.status",
        "native_sources.sync",
        "review.decide",
        "review.list",
        "sources.enroll",
        "sources.fetch",
        "sources.list",
        "sources.metadata",
        "sources.status",
    }
)

#: The three this revision admits.
CAPABILITIES_ADDED: Final[frozenset[str]] = frozenset(
    {"continuity.pulse", "continuity.situations", "continuity.projects"}
)

_CONSTRAINT: Final = text(
    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
    "JOIN pg_class t ON t.oid = c.conrelid "
    "JOIN pg_namespace n ON n.oid = t.relnamespace "
    "WHERE n.nspname = :schema AND t.relname = :table AND c.conname = :name"
)


def _administer(maintenance: Engine, *statements: object) -> None:
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for statement in statements:
            connection.execute(statement)  # type: ignore[arg-type]


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=io.StringIO())


def _admitted(engine: Engine, table: str, constraint: str) -> frozenset[str]:
    """The values one closed-set constraint admits, read out of the server."""
    with engine.connect() as connection:
        definition = connection.execute(
            _CONSTRAINT, {"schema": SCHEMA, "table": table, "name": constraint}
        ).scalar_one()
    return frozenset(re.findall(r"'([^']+)'::text", str(definition)))


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": SCHEMA},
            ).scalars()
        )


def _columns(engine: Engine, table: str) -> dict[str, tuple[Any, ...]]:
    with engine.connect() as connection:
        return {
            str(row[0]): (row[1], row[2])
            for row in connection.execute(
                text(
                    "SELECT column_name, data_type, is_nullable "
                    "FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": SCHEMA, "table": table},
            )
        }


def _indexes(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT indexname FROM pg_indexes "
                    "WHERE schemaname = :schema AND tablename = :table"
                ),
                {"schema": SCHEMA, "table": table},
            ).scalars()
        )


def test_the_continuity_revision_is_in_the_chain_on_the_client_revision() -> None:
    """One head, and this revision revises the one the campaign left at head."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert CONTINUITY_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(CONTINUITY_REVISION).down_revision == PREVIOUS_REVISION


def test_the_widened_vocabulary_is_a_strict_superset_of_the_frozen_one() -> None:
    """Guards the downgrade assertion below: equal sets would make it vacuous."""
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    assert declared > CAPABILITIES_BEFORE
    # A superset and not an equality any more, and the change is the point rather
    # than a loosening: `2d9f4a7c1e58` widened the vocabulary again, so what the
    # *domain* declares is no longer what *this* revision admits. The frozen half
    # is what this file is about and it stays an exact set; what this revision
    # itself adds stays an exact set; and the live vocabulary is only required to
    # contain them, because a later revision widening it further is exactly what
    # `D-69` expects to happen.
    assert declared - CAPABILITIES_BEFORE >= CAPABILITIES_ADDED
    assert len(CAPABILITIES_BEFORE) == 27
    assert len(CAPABILITIES_BEFORE | CAPABILITIES_ADDED) == 30


@pytest.mark.database
def test_the_continuity_revision_runs_empty_to_head_and_head_to_empty(
    disposable_database: str,
) -> None:
    """Reversible, and nothing of this revision survives `downgrade base`."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert set(NEW_TABLES) <= _tables(engine)

        command.downgrade(_config(), "base")
        assert _tables(engine) == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_this_revision_restores_exactly_the_previous_vocabulary(
    disposable_database: str,
) -> None:
    """The prior-revision half, and a round trip rather than a one-way observation.

    At head the constraint admits exactly what the two domain enums declare; one
    revision down it admits exactly the twenty-seven `7a1e5f3c9d24` denotes, the
    four tables are gone, and the two altered tables have lost their new columns.
    A downgrade that left any of it standing would make "the database is at
    `7a1e5f3c9d24`" name two different schemas.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        declared = {member.value for member in Capability} | {
            member.value for member in NativeSourceCapability
        }
        assert _admitted(engine, "audit_events", "capability_is_known") == declared

        command.downgrade(_config(), PREVIOUS_REVISION)
        assert _admitted(engine, "audit_events", "capability_is_known") == CAPABILITIES_BEFORE
        assert len(CAPABILITIES_BEFORE) == 27
        assert set(NEW_TABLES) & _tables(engine) == set()
        assert "reason_code" not in _columns(engine, "pulse_items")
        assert "basis_refs" not in _columns(engine, "pulse_items")
        assert "association_evidence_ref" not in _columns(engine, "project_situations")

        # And back up again, so the pair is a round trip. A downgrade that left
        # residue fails the second upgrade.
        command.upgrade(_config(), "head")
        assert set(NEW_TABLES) <= _tables(engine)
        assert "reason_code" in _columns(engine, "pulse_items")
        assert "association_evidence_ref" in _columns(engine, "project_situations")

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
@pytest.mark.parametrize(
    "table",
    [commitments, decisions, tasks, continuity_lifecycle_events],
    ids=lambda table: str(table.name),
)
def test_each_created_table_matches_the_live_declaration(
    disposable_database: str, table: Table
) -> None:
    """The cost of writing the DDL out, paid rather than described."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        declared_columns = {
            column.name: (
                {
                    "Text": "text",
                    "DateTime": "timestamp with time zone",
                    "JSONB": "jsonb",
                    "Integer": "integer",
                }[column.type.__class__.__name__],
                "NO" if not column.nullable else "YES",
            )
            for column in table.columns
        }
        assert _columns(engine, str(table.name)) == declared_columns

        named = {
            constraint.name
            for constraint in table.constraints
            if constraint.name is not None and not constraint.name.startswith("_")
        }
        with engine.connect() as connection:
            live = set(
                connection.execute(
                    text(
                        "SELECT c.conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = :table"
                    ),
                    {"schema": SCHEMA, "table": str(table.name)},
                ).scalars()
            )
        assert named <= live, f"the declaration names {sorted(named - live)}, the server does not"

        declared_indexes = {index.name for index in table.indexes}
        assert declared_indexes <= _indexes(engine, str(table.name))

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_every_new_table_is_principal_partitioned(disposable_database: str) -> None:
    """What admits the four to `knowledge` at all: a partition and its index."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        for table in NEW_TABLES:
            assert "principal_id" in _columns(engine, table)
            with engine.connect() as connection:
                definition = str(
                    connection.execute(
                        _CONSTRAINT,
                        {
                            "schema": SCHEMA,
                            "table": table,
                            "name": "principal_id_is_an_opaque_identifier",
                        },
                    ).scalar_one()
                )
            assert "^prn_[A-Za-z0-9]{8,64}$" in definition, definition
            assert f"{table}_by_principal" in _indexes(engine, table)
        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_head_admits_exactly_the_capability_vocabulary_the_domain_declares(
    disposable_database: str,
) -> None:
    """The assertion that catches a capability added without a forward `ALTER`.

    Every test builds its database from scratch, so a further member with no
    `ALTER` leaves every other one green and is refused by the stored constraint
    on the first audited request in the field.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _admitted(engine, "audit_events", "capability_is_known") == (
            {member.value for member in Capability}
            | {member.value for member in NativeSourceCapability}
        )
        # And the Pulse reason vocabulary, which the revision also freezes.
        assert _admitted(engine, "pulse_items", "a_pulse_reason_code_is_known") == {
            member.value for member in PulseReasonCode
        }
        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_upgrade_refuses_rather_than_fabricating_a_basis_for_an_existing_row(
    disposable_database: str,
) -> None:
    """The documented choice, executed rather than described.

    A `pulse_items` holding rows written before `reason_code` and `basis_refs`
    existed has no honest value for either, so the upgrade stops with a message
    naming the remedy instead of inventing a why-now nobody derived. This drives
    exactly that: upgrade to the revision below, write one legacy row, and
    observe the refusal — then empty the table and observe the upgrade succeed,
    so the refusal is about the rows and not about the revision.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    f"INSERT INTO {SCHEMA}.pulse_items (pulse_id, principal_id, item_type, "  # noqa: S608
                    "item_ref, reason, priority, accepted_only, generated_at) VALUES "
                    "('puls_legacy001legacy001a', 'prn_aaaa0001aaaa0001aaaa0001', "
                    "'commitment', 'cmt_legacy001legacy001a', 'a legacy row', 5, true, now())"
                )
            )
        with pytest.raises(Exception, match="will not invent"):
            command.upgrade(_config(), "head")

        with engine.begin() as connection:
            connection.execute(text(f"DELETE FROM {SCHEMA}.pulse_items"))  # noqa: S608
        command.upgrade(_config(), "head")
        assert "basis_refs" in _columns(engine, "pulse_items")

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


def test_the_declaration_holds_the_four_tables_this_module_reads() -> None:
    """Guards every database test above against a renamed declaration."""
    declared = {str(table.name) for table in METADATA.tables.values()}
    assert set(NEW_TABLES) <= declared


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
