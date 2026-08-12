"""Revision `7a1e5f3c9d24`: the client table, and the two vocabularies it widens.

WP-10. Four claims, separated because they fail for different reasons.

**The revision is in the chain**, and deliberately not "is the head": that
property is true only until the next revision is written, and asserting it would
make every later work package edit this file
(`test_audit_schema_migration.py` records the same reasoning).

**Empty to head and back to the revision below.** `AGENTS.md` section 6 asks for
a migration tested from an empty schema to head, and for the preceding supported
revision where relevant. Both halves are here, and the downgrade is asserted to
put the two widened `CHECK`s back to the vocabulary `1a4c9e77b2d5` denotes rather
than to whatever the domain says on the day it runs.

**The created table matches the live declaration.** This revision writes its DDL
out rather than copying `tables.py` — `d2e3f4a5b6c7`'s shape, and the one that
keeps a merged revision from changing meaning when the declaration is next edited
— so the cost is that the two could drift. This is where that cost is paid: the
columns, the constraint definitions and the index are read out of `pg_catalog`
and compared against what `METADATA` emits. A hand-written `CREATE TABLE` that
disagreed with the declaration by one `NOT NULL` fails here.

**The client plane is principal-partitioned**, which is what admits it to the
`knowledge` schema at all: it carries `principal_id` with the same
`principal_id_is_an_opaque_identifier` CHECK every other partitioned table
carries, and a `by_principal` index.

The database is disposable, created and dropped by this module's fixture, and is
never the configured one: `downgrade base` deletes schemas. Every value is
synthetic.
"""

from __future__ import annotations

import io
import os
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.engine import make_url
from sqlalchemy.schema import CreateTable

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.capture.client import ClientState
from my_pa.domain.capture.submission import CaptureTransport, TrustState
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import capture_clients

ROOT: Final = Path(__file__).resolve().parents[2]

DISPOSABLE_DATABASE: Final = "my_pa_capture_client_migration_test"

SCHEMA: Final = "knowledge"

#: This revision and the one it revises.
CLIENT_REVISION: Final = "7a1e5f3c9d24"
PREVIOUS_REVISION: Final = "5e2c7b0a94f6"

#: What the two widened constraints admitted before this revision. Written out
#: rather than derived, because the point of the assertion is that a downgraded
#: database holds the vocabulary the revision below denotes and not the domain's.
_TRANSPORT_BEFORE: Final = frozenset({"local"})
_TRUST_STATE_BEFORE: Final = frozenset({"local_principal"})

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


@pytest.fixture
def disposable_database() -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')
    variable = f"{ENV_PREFIX}DATABASE_URL"
    previous = os.environ.get(variable)
    try:
        _administer(maintenance, drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        os.environ[variable] = url
        yield url
    finally:
        if previous is None:
            os.environ.pop(variable, None)
        else:
            os.environ[variable] = previous
        _administer(maintenance, drop)
        maintenance.dispose()


def _admitted(engine: Engine, table: str, constraint: str) -> frozenset[str]:
    """The values one closed-set constraint admits, read out of the server."""
    import re

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
            str(row[0]): (row[1], row[2], row[3])
            for row in connection.execute(
                text(
                    "SELECT column_name, data_type, is_nullable, column_default "
                    "FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": SCHEMA, "table": table},
            )
        }


def test_the_client_revision_is_in_the_chain_on_the_reveal_revision() -> None:
    """One head, and this revision revises the one the campaign left at head."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert CLIENT_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(CLIENT_REVISION).down_revision == PREVIOUS_REVISION


def test_the_widened_vocabularies_are_strict_supersets_of_the_frozen_ones() -> None:
    """Guards the downgrade assertion: equal sets would make it vacuous.

    If `CaptureTransport` ever shrank back to one member, "the downgrade restores
    `('local')`" and "the downgrade restores whatever the enum says" would be the
    same assertion, and the test below would pass against a downgrade that did
    nothing at all.
    """
    assert {t.value for t in CaptureTransport} > _TRANSPORT_BEFORE
    assert {t.value for t in TrustState} > _TRUST_STATE_BEFORE


@pytest.mark.database
def test_the_client_revision_runs_empty_to_head_and_head_to_empty(
    disposable_database: str,
) -> None:
    """Reversible, and reversible including the index the table does not take with it.

    `DROP TABLE` takes its own indexes, so the explicit `DROP INDEX` in the
    downgrade is belt and braces rather than load-bearing — but the assertion
    that matters is at the `base` end: nothing of this revision survives
    `downgrade base`, which `7e5a1fb93d62` performs with `RESTRICT`.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert "capture_clients" in _tables(engine)

        command.downgrade(_config(), "base")
        assert _tables(engine) == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_this_revision_restores_the_previous_vocabulary(
    disposable_database: str,
) -> None:
    """The prior-revision half of `AGENTS.md` section 6, on both widened CHECKs.

    At head the two constraints admit exactly what the domain declares; one
    revision down they admit exactly what `1a4c9e77b2d5` froze, and the client
    table is gone. A downgrade that left the widened vocabulary standing would
    make "the database is at `5e2c7b0a94f6`" name two different schemas.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _admitted(engine, "capture_submissions", "capture_transport_is_known") == {
            member.value for member in CaptureTransport
        }
        assert _admitted(engine, "capture_submissions", "capture_trust_state_is_known") == {
            member.value for member in TrustState
        }
        assert _admitted(engine, "capture_clients", "capture_client_state_is_known") == {
            member.value for member in ClientState
        }

        command.downgrade(_config(), PREVIOUS_REVISION)
        assert (
            _admitted(engine, "capture_submissions", "capture_transport_is_known")
            == _TRANSPORT_BEFORE
        )
        assert (
            _admitted(engine, "capture_submissions", "capture_trust_state_is_known")
            == _TRUST_STATE_BEFORE
        )
        assert "capture_clients" not in _tables(engine)

        # And back up again, so the pair is a round trip rather than a one-way
        # observation. A downgrade that left residue fails the second upgrade.
        command.upgrade(_config(), "head")
        assert "capture_clients" in _tables(engine)

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_created_table_matches_the_live_declaration(disposable_database: str) -> None:
    """The cost of writing the DDL out, paid rather than described.

    The revision emits raw SQL so that it cannot change meaning when `tables.py`
    is next edited (`D-48`). The price is drift, and this is the check that
    collects it: every column of the created table, with its type, nullability
    and default, has to equal what the declaration emits — and every named
    constraint on the declaration has to exist on the server.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        emitted = str(CreateTable(capture_clients).compile(dialect=postgresql.dialect()))
        declared_columns = {
            column.name: (
                "text" if column.type.__class__.__name__ == "Text" else "timestamp with time zone",
                "NO" if not column.nullable else "YES",
                None,
            )
            for column in capture_clients.columns
        }
        assert _columns(engine, "capture_clients") == declared_columns, (
            "the created table's columns differ from the declaration's. The "
            f"declaration emits:\n{emitted}"
        )

        named = {
            constraint.name
            for constraint in capture_clients.constraints
            if constraint.name is not None and not constraint.name.startswith("_")
        }
        with engine.connect() as connection:
            live = set(
                connection.execute(
                    text(
                        "SELECT c.conname FROM pg_constraint c "
                        "JOIN pg_class t ON t.oid = c.conrelid "
                        "JOIN pg_namespace n ON n.oid = t.relnamespace "
                        "WHERE n.nspname = :schema AND t.relname = 'capture_clients'"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
        assert named <= live, f"the declaration names {sorted(named - live)}, the server does not"

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_client_plane_is_principal_partitioned(disposable_database: str) -> None:
    """What admits the table to `knowledge` at all: a partition and its index.

    Every user-owned table here carries `principal_id` with the same opaque-identifier
    CHECK and a `by_principal` index, and
    `tests/architecture/test_user_owned_tables_are_partitioned.py` fails the build
    for one that does not. This is the same claim read off the server rather than
    off the declaration.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        assert "principal_id" in _columns(engine, "capture_clients")
        # The exact CHECK every other partitioned table carries, read off the
        # server rather than compared against the declaration that produced it.
        with engine.connect() as connection:
            definition = str(
                connection.execute(
                    _CONSTRAINT,
                    {
                        "schema": SCHEMA,
                        "table": "capture_clients",
                        "name": "principal_id_is_an_opaque_identifier",
                    },
                ).scalar_one()
            )
        assert "^prn_[A-Za-z0-9]{8,64}$" in definition, definition

        with engine.connect() as connection:
            indexes = set(
                connection.execute(
                    text(
                        "SELECT indexname FROM pg_indexes "
                        "WHERE schemaname = :schema AND tablename = 'capture_clients'"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
        assert "capture_clients_by_principal" in indexes

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()
