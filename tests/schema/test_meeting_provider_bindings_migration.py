"""Communications intelligence WP2: the one provider-binding revision, `6418b57081c3`.

`6418b57081c3` is additive on `4d1069a7d84f` (ADR-020 meeting prep) and creates
`knowledge.meeting_series_provider_bindings`, `knowledge.meeting_provider_bindings`,
their two partial unique indexes and four guards. This module proves:

* **the graph** -- exactly one head, this revision, directly on `4d1069a7d84f`;
* **the freeze** -- the revision imports nothing from the package it migrates and
  names every column, constraint and index `tables.py` declares for both tables;
* **offline SQL** for both directions, without a server;
* on disposable databases: empty to head; the round trip down to
  `4d1069a7d84f` and back; the downgrade refusal while a binding exists; the
  identity-immutability, one-kind-per-UID, append-only and TRUNCATE guards; and
  the CHECK, unique and foreign keys the bindings rely on (one binding per
  Meeting and per occurrence key, one series binding per series both ways, the
  Principal partition, and `ON DELETE RESTRICT`).

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
from sqlalchemy import Engine, Table, delete, insert, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import (
    meeting_provider_bindings,
    meeting_series,
    meeting_series_provider_bindings,
    meetings,
)

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "6418b57081c3"
PREVIOUS: Final = "4d1069a7d84f"
MIGRATION: Final = (
    ROOT / "migrations" / "versions" / "20261121_6418b57081c3_meeting_provider_bindings.py"
)

TABLES: Final = frozenset({"meeting_provider_bindings", "meeting_series_provider_bindings"})
INDEXES: Final = frozenset(
    {"one_provider_binding_per_occurrence", "one_provider_binding_per_single_meeting"}
)
TRIGGERS: Final = frozenset(
    {
        "meeting_provider_binding_identity_is_immutable",
        "meeting_provider_binding_kind_is_exclusive",
        "meeting_series_provider_bindings_are_append_only",
        "meeting_series_provider_bindings_refuse_truncate",
        "meeting_provider_bindings_refuse_truncate",
    }
)
FUNCTIONS: Final = frozenset(
    {
        "meeting_provider_bindings_keep_their_identity",
        "meeting_provider_bindings_bind_one_kind_per_uid",
        "meeting_series_provider_bindings_stay_append_only",
        "meeting_provider_bindings_refuse_truncate",
    }
)

PRINCIPAL: Final = "prn_mpbndmig0001mpbndmig"
OTHER_PRINCIPAL: Final = "prn_mpbndmig0002mpbndmig"
WHEN: Final = datetime(2026, 11, 21, 12, tzinfo=UTC)
ORIGINAL: Final = datetime(2026, 12, 2, 14, tzinfo=UTC)
CALENDAR: Final = "cal-synthetic"
SERIES_UID: Final = "uid-series@example.invalid"
_WHITESPACE: Final = re.compile(r"\s+")

RESTRICT_VIOLATION: Final = "23001"
EXCLUSION_VIOLATION: Final = "23P01"
CHECK, UNIQUE, FOREIGN = "23514", "23505", "23503"


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def _offline(target: str, *, down: bool = False) -> str:
    buffer = io.StringIO()
    action = command.downgrade if down else command.upgrade
    action(_config(buffer), target, sql=True)
    return _WHITESPACE.sub(" ", buffer.getvalue())


# ---- the graph --------------------------------------------------------------


def test_the_revision_is_the_single_head_directly_on_the_meeting_prep_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert script.get_revision(PREVIOUS).down_revision == "640aaacc78e8"


# ---- the freeze -------------------------------------------------------------


def test_revision_imports_no_domain_or_persistence_modules() -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    imported: set[str] = set()
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.ImportFrom) and node.module is not None:
            imported.add(node.module)
        elif isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
    assert imported <= {"alembic", "__future__", "typing"}
    assert "my_pa" not in source
    assert "create_all" not in source


@pytest.mark.parametrize("table", [meeting_provider_bindings, meeting_series_provider_bindings])
def test_the_frozen_ddl_names_every_declared_column_constraint_and_index(table: Table) -> None:
    source = MIGRATION.read_text(encoding="utf-8")
    flat = _WHITESPACE.sub(" ", source)
    assert f"CREATE TABLE knowledge.{table.name} (" in source
    for column in table.c:
        assert re.search(rf"\b{column.name}\b", source), column.name
    names = [
        str(constraint.name)
        for constraint in table.constraints
        if constraint.name is not None and not str(constraint.name).startswith("_")
    ]
    assert len(names) >= 8
    for name in names:
        assert name in source, name
    for index in table.indexes:
        assert f"UNIQUE INDEX {index.name} ON knowledge.{table.name}" in flat, index.name
    assert {index.name for index in meeting_provider_bindings.indexes} == INDEXES
    for name in TRIGGERS | FUNCTIONS:
        assert name in source, name


def test_the_frozen_literals() -> None:
    source = _WHITESPACE.sub(" ", MIGRATION.read_text(encoding="utf-8"))
    assert "'^mpbnd_[A-Za-z0-9]{8,64}$'" in source
    assert "'^msbnd_[A-Za-z0-9]{8,64}$'" in source
    assert "length(calendar_ref) BETWEEN 1 AND 320" in source
    assert "length(ical_uid) BETWEEN 1 AND 1024" in source
    assert "('immutable_verified', 'mutable', 'unknown')" in source
    assert "('active', 'cancelled', 'not_seen')" in source
    assert "SET LOCAL lock_timeout = '10s'" in source


def test_the_offline_upgrade_emits_the_whole_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{PREVIOUS}:{REVISION}")
    assert rendered.index("SET LOCAL lock_timeout") < rendered.index("CREATE TABLE")
    for table in TABLES:
        assert f"CREATE TABLE knowledge.{table} (" in rendered
    for index in INDEXES:
        assert f"CREATE UNIQUE INDEX {index} ON" in rendered
    for function in FUNCTIONS:
        assert f"CREATE FUNCTION knowledge.{function}()" in rendered
    for trigger in TRIGGERS:
        assert f"CREATE TRIGGER {trigger}" in rendered
    # No existing object changes: no vocabulary restatement, no grant.
    assert "capability_is_known" not in rendered
    assert "GRANT" not in rendered
    assert f"SET version_num='{REVISION}'" in rendered


def test_the_offline_downgrade_refuses_first_and_unwinds_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    refusal = rendered.index("refusing to downgrade 6418b57081c3")
    assert rendered.index("LOCK TABLE knowledge.meeting_provider_bindings") < refusal
    for trigger in TRIGGERS:
        assert rendered.index(f"DROP TRIGGER {trigger}") > refusal
    for function in FUNCTIONS:
        assert rendered.index(f"DROP FUNCTION knowledge.{function}()") > refusal
    for index in INDEXES:
        assert rendered.index(f"DROP INDEX knowledge.{index}") > refusal
    occurrence = rendered.index("DROP TABLE knowledge.meeting_provider_bindings RESTRICT")
    assert occurrence > refusal
    assert rendered.index("DROP TABLE knowledge.meeting_series_provider_bindings RESTRICT") > (
        occurrence
    )
    assert f"SET version_num='{PREVIOUS}'" in rendered


# ---- disposable databases -------------------------------------------------------


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """An empty catalog: this module drives Alembic itself."""
    return empty_database_url


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    built = create_database_engine(disposable_database)
    try:
        yield built
    finally:
        built.dispose()


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
            "SELECT c.conname FROM pg_constraint c JOIN pg_class r ON r.oid = c.conrelid "
            "JOIN pg_namespace n ON n.oid = r.relnamespace "
            "WHERE n.nspname = :schema AND r.relname IN "
            "('meeting_provider_bindings', 'meeting_series_provider_bindings')"
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
    assert catalog["tables"] >= TABLES
    assert catalog["indexes"] >= INDEXES
    assert catalog["triggers"] >= TRIGGERS
    assert catalog["functions"] >= FUNCTIONS


def _assert_absent(engine: Engine) -> None:
    catalog = _catalog(engine)
    assert catalog["version"] == {PREVIOUS}
    assert not catalog["tables"] & TABLES
    assert not catalog["indexes"] & INDEXES
    assert not catalog["triggers"] & TRIGGERS
    assert not catalog["functions"] & FUNCTIONS


def _seed(connection: Connection, *, principal: str, suffix: str) -> dict[str, str]:
    """A series and three Meetings of `principal`."""
    ids = {
        "series": f"mser_mpbndmig{suffix}series",
        "meeting": f"mtg_mpbndmig{suffix}meeting1",
        "meeting2": f"mtg_mpbndmig{suffix}meeting2",
        "meeting3": f"mtg_mpbndmig{suffix}meeting3",
    }
    connection.execute(
        insert(meeting_series).values(
            meeting_series_id=ids["series"],
            principal_id=principal,
            title="A synthetic series",
            version=1,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    for key in ("meeting", "meeting2", "meeting3"):
        connection.execute(
            insert(meetings).values(
                meeting_id=ids[key],
                principal_id=principal,
                meeting_series_id=ids["series"],
                title="A synthetic meeting",
                start_at=WHEN,
                timezone_name="UTC",
                status="scheduled",
                version=1,
                created_at=WHEN,
                updated_at=WHEN,
            )
        )
    return ids


def _series_row(ids: dict[str, str], **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "series_binding_id": "msbnd_mpbndmig0001s001",
        "principal_id": PRINCIPAL,
        "meeting_series_id": ids["series"],
        "calendar_ref": CALENDAR,
        "series_ical_uid": SERIES_UID,
        "created_at": WHEN,
    }
    row.update(overrides)
    return row


def _binding_row(ids: dict[str, str], **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "binding_id": "mpbnd_mpbndmig0001b001",
        "principal_id": PRINCIPAL,
        "meeting_id": ids["meeting"],
        "calendar_ref": CALENDAR,
        "ical_uid": SERIES_UID,
        "occurrence_original_start_utc": ORIGINAL,
        "series_ical_uid": SERIES_UID,
        "provider_event_id": "evt-0001",
        "provider_event_id_format": "mutable",
        "provider_state": "active",
        "last_seen_source_sha256": "a" * 64,
        "last_seen_record_ordinal": 0,
        "last_seen_at": WHEN,
        "version": 1,
        "created_at": WHEN,
        "updated_at": WHEN,
    }
    row.update(overrides)
    return row


def _refused(
    engine: Engine,
    table: Table,
    row: dict[str, object],
    constraint: str,
    sqlstate: str,
) -> None:
    with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
        connection.execute(insert(table).values(**row))
    diag = refused.value.orig.diag  # type: ignore[union-attr]
    assert refused.value.orig.sqlstate == sqlstate, refused.value  # type: ignore[union-attr]
    assert diag.constraint_name == constraint, refused.value


def _refused_by_trigger(
    engine: Engine, statement: Callable[[Connection], Any], sqlstate: str = RESTRICT_VIOLATION
) -> None:
    with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
        statement(connection)
    assert getattr(refused.value.orig, "sqlstate", None) == sqlstate, refused.value


@pytest.fixture
def seeded(disposable_database: str, engine: Engine) -> dict[str, str]:
    """Head, the seed per Principal, one series binding and one occurrence binding."""
    del disposable_database
    command.upgrade(_config(), "head")
    with engine.begin() as connection:
        ids = _seed(connection, principal=PRINCIPAL, suffix="0001")
        other = _seed(connection, principal=OTHER_PRINCIPAL, suffix="0002")
        connection.execute(insert(meeting_series_provider_bindings).values(**_series_row(ids)))
        connection.execute(insert(meeting_provider_bindings).values(**_binding_row(ids)))
    return {**ids, **{f"other_{key}": value for key, value in other.items()}}


@pytest.mark.database
def test_the_revision_round_trips_from_the_meeting_prep_head(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), "head")
    _assert_present(engine)
    declared = {
        str(constraint.name)
        for table in (meeting_provider_bindings, meeting_series_provider_bindings)
        for constraint in table.constraints
        if constraint.name is not None
    }
    assert declared - {"meeting_provider_bindings_pkey"} <= _catalog(engine)["constraints"]
    command.downgrade(_config(), PREVIOUS)
    _assert_absent(engine)
    command.upgrade(_config(), "head")
    _assert_present(engine)


@pytest.mark.database
def test_a_downgrade_refuses_while_a_binding_exists(seeded: dict[str, str], engine: Engine) -> None:
    del seeded
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert "refusing to downgrade 6418b57081c3" in str(refused.value)
    _assert_present(engine)


@pytest.mark.database
def test_a_downgrade_refuses_while_only_a_series_binding_exists(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), "head")
    with engine.begin() as connection:
        ids = _seed(connection, principal=PRINCIPAL, suffix="0001")
        connection.execute(insert(meeting_series_provider_bindings).values(**_series_row(ids)))
    with pytest.raises(DBAPIError):
        command.downgrade(_config(), PREVIOUS)
    _assert_present(engine)


@pytest.mark.database
def test_binding_identity_is_immutable_and_attributes_are_mutable(
    seeded: dict[str, str], engine: Engine
) -> None:
    table = meeting_provider_bindings
    mine = table.c.binding_id == "mpbnd_mpbndmig0001b001"
    for column, value in (
        ("binding_id", "mpbnd_mpbndmig0001b999"),
        ("meeting_id", seeded["meeting2"]),
        ("calendar_ref", "cal-other"),
        ("ical_uid", "uid-other"),
        ("occurrence_original_start_utc", ORIGINAL + timedelta(days=1)),
        ("principal_id", OTHER_PRINCIPAL),
    ):
        _refused_by_trigger(
            engine,
            lambda c, column=column, value=value: c.execute(
                update(table).where(mine).values({column: value})
            ),
        )
    with engine.begin() as connection:
        connection.execute(
            update(table)
            .where(mine)
            .values(
                provider_event_id="evt-renamed",
                provider_event_id_format="immutable_verified",
                provider_state="cancelled",
                version=2,
                updated_at=WHEN + timedelta(hours=1),
            )
        )


@pytest.mark.database
def test_series_bindings_are_append_only(seeded: dict[str, str], engine: Engine) -> None:
    table = meeting_series_provider_bindings
    mine = table.c.series_binding_id == "msbnd_mpbndmig0001s001"
    _refused_by_trigger(
        engine, lambda c: c.execute(update(table).where(mine).values(series_ical_uid="x"))
    )
    _refused_by_trigger(engine, lambda c: c.execute(delete(table).where(mine)))
    del seeded


@pytest.mark.database
def test_truncate_is_refused_on_both_tables(seeded: dict[str, str], engine: Engine) -> None:
    for table in sorted(TABLES):
        _refused_by_trigger(
            engine, lambda c, table=table: c.execute(text(f"TRUNCATE knowledge.{table} CASCADE"))
        )
    del seeded


@pytest.mark.database
def test_an_occurrence_binding_may_be_deleted_for_the_w3_unbind(
    seeded: dict[str, str], engine: Engine
) -> None:
    del seeded
    with engine.begin() as connection:
        deleted = connection.execute(
            delete(meeting_provider_bindings).where(
                meeting_provider_bindings.c.binding_id == "mpbnd_mpbndmig0001b001"
            )
        )
        assert deleted.rowcount == 1


@pytest.mark.database
def test_one_uid_binds_one_kind(seeded: dict[str, str], engine: Engine) -> None:
    # The occurrence UID bound as a single meeting too: refused (D9).
    single = _binding_row(
        seeded,
        binding_id="mpbnd_mpbndmig0001b002",
        meeting_id=seeded["meeting2"],
        occurrence_original_start_utc=None,
        series_ical_uid=None,
    )
    _refused_by_trigger(
        engine,
        lambda c: c.execute(insert(meeting_provider_bindings).values(**single)),
        EXCLUSION_VIOLATION,
    )
    # And the reverse: a single-meeting UID gaining an occurrence.
    with engine.begin() as connection:
        connection.execute(
            insert(meeting_provider_bindings).values(
                **{**single, "ical_uid": "uid-single@example.invalid"}
            )
        )
    _refused_by_trigger(
        engine,
        lambda c: c.execute(
            insert(meeting_provider_bindings).values(
                **_binding_row(
                    seeded,
                    binding_id="mpbnd_mpbndmig0001b003",
                    meeting_id=seeded["meeting3"],
                    ical_uid="uid-single@example.invalid",
                )
            )
        ),
        EXCLUSION_VIOLATION,
    )
    # Another Principal's same UID is its own key space.
    with engine.begin() as connection:
        connection.execute(
            insert(meeting_series_provider_bindings).values(
                **_series_row(
                    seeded,
                    series_binding_id="msbnd_mpbndmig0002s001",
                    principal_id=OTHER_PRINCIPAL,
                    meeting_series_id=seeded["other_series"],
                )
            )
        )
        connection.execute(
            insert(meeting_provider_bindings).values(
                **_binding_row(
                    seeded,
                    binding_id="mpbnd_mpbndmig0002b001",
                    principal_id=OTHER_PRINCIPAL,
                    meeting_id=seeded["other_meeting"],
                )
            )
        )


@pytest.mark.database
def test_the_binding_constraints(seeded: dict[str, str], engine: Engine) -> None:
    table = meeting_provider_bindings
    second = {"binding_id": "mpbnd_mpbndmig0001b002", "meeting_id": seeded["meeting2"]}
    # The same occurrence key twice; a moved occurrence keeps its original start.
    _refused(
        engine, table, _binding_row(seeded, **second), "one_provider_binding_per_occurrence", UNIQUE
    )
    # A second binding of one Meeting.
    _refused(
        engine,
        table,
        _binding_row(
            seeded,
            binding_id="mpbnd_mpbndmig0001b002",
            occurrence_original_start_utc=ORIGINAL + timedelta(days=7),
        ),
        "one_provider_binding_per_meeting",
        UNIQUE,
    )
    later = {**second, "occurrence_original_start_utc": ORIGINAL + timedelta(days=7)}
    for overrides, constraint in (
        ({"series_ical_uid": None}, "an_occurrence_binding_names_its_series_and_original_start"),
        ({"binding_id": "mtg_mpbndmig0001b002"}, "binding_id_is_an_opaque_identifier"),
        ({"calendar_ref": "c" * 321}, "a_provider_binding_calendar_ref_is_bounded"),
        ({"calendar_ref": ""}, "a_provider_binding_calendar_ref_is_bounded"),
        ({"provider_event_id": "e" * 1025}, "a_provider_event_id_is_bounded"),
        ({"provider_event_id_format": "stable"}, "a_provider_event_id_format_is_known"),
        ({"provider_state": "gone"}, "a_provider_binding_state_is_known"),
        ({"last_seen_at": None}, "a_provider_binding_last_seen_is_whole"),
        ({"last_seen_source_sha256": "A" * 64}, "a_provider_binding_last_seen_digest_is_sha256"),
        ({"last_seen_record_ordinal": -1}, "a_provider_binding_last_seen_ordinal_is_non_negative"),
        ({"version": 0}, "a_provider_binding_version_is_positive"),
    ):
        _refused(engine, table, _binding_row(seeded, **{**later, **overrides}), constraint, CHECK)
    # The series UID must be bound for this Principal and calendar.
    _refused(
        engine,
        table,
        _binding_row(seeded, **{**later, "series_ical_uid": "uid-unbound"}),
        "an_occurrence_binding_names_a_bound_series",
        FOREIGN,
    )
    # The Principal partition: another Principal's Meeting.
    _refused(
        engine,
        table,
        _binding_row(seeded, **{**later, "meeting_id": seeded["other_meeting"]}),
        "a_provider_binding_names_a_meeting_of_its_principal",
        FOREIGN,
    )
    # A later occurrence of the same series is legal.
    with engine.begin() as connection:
        connection.execute(insert(table).values(**_binding_row(seeded, **later)))


@pytest.mark.database
def test_the_series_binding_constraints(seeded: dict[str, str], engine: Engine) -> None:
    table = meeting_series_provider_bindings
    _refused(
        engine,
        table,
        _series_row(seeded, series_binding_id="msbnd_mpbndmig0001s002"),
        "one_series_provider_binding_per_provider_series",
        UNIQUE,
    )
    _refused(
        engine,
        table,
        _series_row(
            seeded, series_binding_id="msbnd_mpbndmig0001s002", series_ical_uid="uid-another"
        ),
        "one_provider_binding_per_meeting_series",
        UNIQUE,
    )
    _refused(
        engine,
        table,
        _series_row(
            seeded,
            series_binding_id="msbnd_mpbndmig0001s002",
            series_ical_uid="uid-another",
            meeting_series_id=seeded["other_series"],
        ),
        "a_series_provider_binding_names_a_series_of_its_principal",
        FOREIGN,
    )
    _refused(
        engine,
        table,
        _series_row(seeded, series_binding_id="msbnd_mpbndmig0001s002", series_ical_uid=""),
        "a_series_provider_binding_uid_is_bounded",
        CHECK,
    )


@pytest.mark.database
def test_bound_meetings_and_series_cannot_be_deleted(
    seeded: dict[str, str], engine: Engine
) -> None:
    with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
        connection.execute(delete(meetings).where(meetings.c.meeting_id == seeded["meeting"]))
    assert refused.value.orig.diag.constraint_name == (  # type: ignore[union-attr]
        "a_provider_binding_names_a_meeting_of_its_principal"
    )
    with pytest.raises(DBAPIError), engine.begin() as connection:
        connection.execute(
            delete(meeting_series).where(meeting_series.c.meeting_series_id == seeded["series"])
        )
