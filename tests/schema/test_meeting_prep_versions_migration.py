"""ADR-020 C1: the one Meeting prep revision, `4d1069a7d84f`.

`4d1069a7d84f` is additive on `640aaacc78e8` (files workspace WP4) and creates
`knowledge.meeting_prep_versions`, its two indexes and its append-only guard.
This module proves:

* **the graph** -- exactly one head, this revision, directly on `640aaacc78e8`;
* **the freeze** -- the revision imports nothing from the package it migrates,
  names every column, constraint and index `tables.py` declares for the table,
  and spells the body bound as the frozen literal `MAX_MEETING_PREP_CHARACTERS`
  holds;
* **offline SQL** for both directions, without a server;
* on disposable databases: empty to head; the round trip down to
  `640aaacc78e8` and back, which removes and restores exactly the table, its
  indexes, its function and its trigger; the downgrade refusal while a prep
  version exists; the append-only guard; and every CHECK, unique and foreign
  key the chain relies on (the first version supersedes nothing, a later
  version supersedes something, the body bound, the digest shape, the
  Principal partition, and a chain rather than a tree).

The file name routes every test here to migration-edge (`tests/db/fixtures.py`);
the tests with no `database` marker also run in FAST. Every value is synthetic.
"""

from __future__ import annotations

import ast
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
from sqlalchemy import Engine, insert, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.domain.meeting.model import MAX_MEETING_PREP_CHARACTERS
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import (
    meeting_history,
    meeting_prep_versions,
    meetings,
)

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
REVISION: Final = "4d1069a7d84f"
PREVIOUS: Final = "640aaacc78e8"
MIGRATIONS: Final = ROOT / "migrations" / "versions"
MIGRATION: Final = MIGRATIONS / "20261120_4d1069a7d84f_meeting_prep_versions.py"

TABLE: Final = "meeting_prep_versions"
INDEXES: Final = frozenset(
    {"meeting_prep_versions_by_principal_meeting", "meeting_prep_versions_text"}
)
TRIGGER: Final = "meeting_prep_versions_are_append_only"
FUNCTION: Final = "meeting_prep_versions_stay_append_only"

PRINCIPAL: Final = "prn_mprepmig0001mprepmig"
OTHER_PRINCIPAL: Final = "prn_mprepmig0002mprepmig"
WHEN: Final = datetime(2026, 11, 20, 12, tzinfo=UTC)
DIGEST: Final = "a" * 64
_WHITESPACE: Final = re.compile(r"\s+")

#: PostgreSQL's `restrict_violation`, which the append-only guard raises.
RESTRICT_VIOLATION: Final = "23001"


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def _offline(target: str, *, down: bool = False) -> str:
    buffer = io.StringIO()
    action = command.downgrade if down else command.upgrade
    action(_config(buffer), target, sql=True)
    return _WHITESPACE.sub(" ", buffer.getvalue())


# ---- the graph --------------------------------------------------------------


def test_the_revision_is_directly_on_the_files_workspace_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_revision(REVISION).down_revision == PREVIOUS


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


def test_the_frozen_ddl_names_every_declared_column_constraint_and_index() -> None:
    """The revision's text and `tables.py` name the same schema objects.

    Parity of the definitions is proved on a server by
    `test_every_revision_denotes_one_schema.py`; this is the static half.
    """
    source = MIGRATION.read_text(encoding="utf-8")
    flat = _WHITESPACE.sub(" ", source)
    assert f"CREATE TABLE knowledge.{TABLE} (" in source
    for column in meeting_prep_versions.c:
        assert re.search(rf"\b{column.name}\b", source), column.name
    names = [
        str(constraint.name)
        for constraint in meeting_prep_versions.constraints
        if constraint.name is not None and not str(constraint.name).startswith("_")
    ]
    assert len(names) >= 15
    for name in names:
        assert name in source, name
    assert {index.name for index in meeting_prep_versions.indexes} == INDEXES
    for index in INDEXES:
        assert f"INDEX {index} ON knowledge.{TABLE}" in flat, index
    assert TRIGGER in source
    assert FUNCTION in source


def test_the_frozen_body_bound_is_the_domain_cap() -> None:
    source = _WHITESPACE.sub(" ", MIGRATION.read_text(encoding="utf-8"))
    assert MAX_MEETING_PREP_CHARACTERS == 400_000
    assert (
        f"a_meeting_prep_body_is_bounded CHECK (length(content_markdown) BETWEEN 1 AND "
        f"{MAX_MEETING_PREP_CHARACTERS})"
    ) in source
    assert "'^mprep_[A-Za-z0-9]{8,64}$'" in source


def test_the_offline_upgrade_emits_the_whole_revision(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{PREVIOUS}:{REVISION}")
    assert f"CREATE TABLE knowledge.{TABLE} (" in rendered
    for index in INDEXES:
        assert f"CREATE INDEX {index} ON knowledge.{TABLE}" in rendered
    assert f"CREATE FUNCTION knowledge.{FUNCTION}()" in rendered
    assert f"CREATE TRIGGER {TRIGGER}" in rendered
    # No existing object changes: no vocabulary restatement, no grant.
    assert "capability_is_known" not in rendered
    assert "GRANT" not in rendered
    assert f"SET version_num='{REVISION}'" in rendered


def test_the_offline_downgrade_refuses_first_and_unwinds_everything(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    refusal = rendered.index("refusing to downgrade")
    assert rendered.index(f"LOCK TABLE knowledge.{TABLE}") < refusal
    assert rendered.index(f"DROP TRIGGER {TRIGGER}") > refusal
    assert rendered.index(f"DROP FUNCTION knowledge.{FUNCTION}()") > refusal
    for index in INDEXES:
        assert rendered.index(f"DROP INDEX knowledge.{index}") > refusal
    assert rendered.index(f"DROP TABLE knowledge.{TABLE} RESTRICT") > refusal
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
    assert TABLE in catalog["tables"]
    assert catalog["indexes"] >= INDEXES
    assert TRIGGER in catalog["triggers"]
    assert FUNCTION in catalog["functions"]


def _assert_absent(engine: Engine) -> None:
    catalog = _catalog(engine)
    assert catalog["version"] == {PREVIOUS}
    assert TABLE not in catalog["tables"]
    assert not catalog["indexes"] & INDEXES
    assert TRIGGER not in catalog["triggers"]
    assert FUNCTION not in catalog["functions"]


def _seed_meeting(connection: Connection, *, principal: str, suffix: str) -> dict[str, str]:
    """One standalone Meeting of `principal` and its create receipt."""
    ids = {
        "meeting": f"mtg_mprepmig{suffix}meeting",
        "history": f"mhst_mprepmig{suffix}history",
    }
    connection.execute(
        insert(meetings).values(
            meeting_id=ids["meeting"],
            principal_id=principal,
            title="A synthetic meeting",
            start_at=WHEN,
            timezone_name="UTC",
            status="scheduled",
            version=1,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    connection.execute(
        insert(meeting_history).values(
            history_id=ids["history"],
            principal_id=principal,
            meeting_id=ids["meeting"],
            action="create",
            actor="principal",
            outcome="applied",
            before_version=0,
            after_version=1,
            idempotency_key=f"mprep-{suffix}",
            request_digest=DIGEST,
            occurred_at=WHEN,
            recorded_at=WHEN,
        )
    )
    return ids


def _prep_row(ids: dict[str, str], **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "prep_version_id": "mprep_mprepmig0001v0001",
        "principal_id": PRINCIPAL,
        "meeting_id": ids["meeting"],
        "version_number": 1,
        "supersedes_prep_version_id": None,
        "content_markdown": "Synthetic agenda.",
        "content_sha256": "c" * 64,
        "meeting_history_id": ids["history"],
        "recorded_at": WHEN,
    }
    row.update(overrides)
    return row


def _refused(engine: Engine, row: dict[str, object], constraint: str, sqlstate: str) -> None:
    """Inserting `row` is refused by exactly `constraint`."""
    with pytest.raises(IntegrityError) as refused, engine.begin() as connection:
        connection.execute(insert(meeting_prep_versions).values(**row))
    diag = refused.value.orig.diag  # type: ignore[union-attr]
    assert refused.value.orig.sqlstate == sqlstate, refused.value  # type: ignore[union-attr]
    assert diag.constraint_name == constraint, refused.value


def _refused_by_trigger(engine: Engine, statement: Callable[[Connection], Any]) -> None:
    with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
        statement(connection)
    assert getattr(refused.value.orig, "sqlstate", None) == RESTRICT_VIOLATION, refused.value


@pytest.fixture
def seeded(disposable_database: str, engine: Engine) -> dict[str, str]:
    """Head, one Meeting per Principal, and the first prep version of the first."""
    del disposable_database
    command.upgrade(_config(), REVISION)
    with engine.begin() as connection:
        ids = _seed_meeting(connection, principal=PRINCIPAL, suffix="0001")
        other = _seed_meeting(connection, principal=OTHER_PRINCIPAL, suffix="0002")
        connection.execute(insert(meeting_prep_versions).values(**_prep_row(ids)))
    return {**ids, "other_meeting": other["meeting"], "other_history": other["history"]}


@pytest.mark.database
def test_the_revision_round_trips_from_the_files_workspace_head(
    disposable_database: str, engine: Engine
) -> None:
    del disposable_database
    command.upgrade(_config(), REVISION)
    _assert_present(engine)
    command.downgrade(_config(), PREVIOUS)
    _assert_absent(engine)
    command.upgrade(_config(), REVISION)
    _assert_present(engine)


@pytest.mark.database
def test_a_downgrade_refuses_while_a_prep_version_exists(
    seeded: dict[str, str], engine: Engine
) -> None:
    del seeded
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert "refusing to downgrade 4d1069a7d84f" in str(refused.value)
    _assert_present(engine)


@pytest.mark.database
def test_prep_versions_are_append_only(seeded: dict[str, str], engine: Engine) -> None:
    version = "mprep_mprepmig0001v0001"
    _refused_by_trigger(
        engine,
        lambda c: c.execute(
            update(meeting_prep_versions)
            .where(meeting_prep_versions.c.prep_version_id == version)
            .values(content_markdown="Rewritten.")
        ),
    )
    _refused_by_trigger(
        engine,
        lambda c: c.execute(
            meeting_prep_versions.delete().where(meeting_prep_versions.c.prep_version_id == version)
        ),
    )
    del seeded


@pytest.mark.database
def test_the_chain_constraints_refuse_malformed_versions(
    seeded: dict[str, str], engine: Engine
) -> None:
    first = "mprep_mprepmig0001v0001"
    check, unique, foreign = "23514", "23505", "23503"
    # A first version that supersedes something.
    _refused(
        engine,
        _prep_row(
            seeded,
            prep_version_id="mprep_mprepmig0001v0009",
            version_number=1,
            supersedes_prep_version_id=first,
        ),
        "only_the_first_meeting_prep_supersedes_nothing",
        check,
    )
    # A later version that supersedes nothing.
    _refused(
        engine,
        _prep_row(seeded, prep_version_id="mprep_mprepmig0001v0002", version_number=2),
        "only_the_first_meeting_prep_supersedes_nothing",
        check,
    )
    # A version number below one.
    _refused(
        engine,
        _prep_row(
            seeded,
            prep_version_id="mprep_mprepmig0001v0000",
            version_number=0,
            supersedes_prep_version_id=first,
        ),
        "a_meeting_prep_version_number_is_positive",
        check,
    )
    # A body one character over the cap, and an empty body.
    for body in ("x" * (MAX_MEETING_PREP_CHARACTERS + 1), ""):
        _refused(
            engine,
            _prep_row(
                seeded,
                prep_version_id="mprep_mprepmig0001v0002",
                version_number=2,
                supersedes_prep_version_id=first,
                content_markdown=body,
            ),
            "a_meeting_prep_body_is_bounded",
            check,
        )
    # A digest that is not lowercase SHA-256 hex.
    for digest in ("C" * 64, "c" * 63):
        _refused(
            engine,
            _prep_row(
                seeded,
                prep_version_id="mprep_mprepmig0001v0002",
                version_number=2,
                supersedes_prep_version_id=first,
                content_sha256=digest,
            ),
            "a_meeting_prep_digest_is_sha256",
            check,
        )
    # A version of another kind's identifier.
    _refused(
        engine,
        _prep_row(
            seeded,
            prep_version_id="mnote_mprepmig0001v0002",
            version_number=2,
            supersedes_prep_version_id=first,
        ),
        "prep_version_id_is_an_opaque_identifier",
        check,
    )
    # The Principal partition: a row of this Principal naming another
    # Principal's Meeting (and that Meeting's receipt).
    _refused(
        engine,
        _prep_row(
            seeded,
            prep_version_id="mprep_mprepmig0002v0001",
            meeting_id=seeded["other_meeting"],
            meeting_history_id=seeded["other_history"],
        ),
        "a_meeting_prep_belongs_to_a_meeting_of_its_principal",
        foreign,
    )
    # A receipt of another Meeting.
    _refused(
        engine,
        _prep_row(
            seeded,
            prep_version_id="mprep_mprepmig0001v0002",
            version_number=2,
            supersedes_prep_version_id=first,
            meeting_history_id=seeded["other_history"],
        ),
        "a_meeting_prep_names_a_receipt_of_its_meeting",
        foreign,
    )
    # Superseding a version of another Meeting (the other Principal's first).
    with engine.begin() as connection:
        connection.execute(
            insert(meeting_prep_versions).values(
                **_prep_row(
                    seeded,
                    prep_version_id="mprep_mprepmig0002v0001",
                    principal_id=OTHER_PRINCIPAL,
                    meeting_id=seeded["other_meeting"],
                    meeting_history_id=seeded["other_history"],
                )
            )
        )
    _refused(
        engine,
        _prep_row(
            seeded,
            prep_version_id="mprep_mprepmig0001v0002",
            version_number=2,
            supersedes_prep_version_id="mprep_mprepmig0002v0001",
        ),
        "a_meeting_prep_supersedes_a_prep_of_its_meeting",
        foreign,
    )
    # A second version 1 of the same Meeting.
    _refused(
        engine,
        _prep_row(seeded, prep_version_id="mprep_mprepmig0001v0003"),
        "one_meeting_prep_version_number_per_meeting",
        unique,
    )
    # A chain, not a tree: the second version is legal, a sibling is not.
    with engine.begin() as connection:
        connection.execute(
            insert(meeting_prep_versions).values(
                **_prep_row(
                    seeded,
                    prep_version_id="mprep_mprepmig0001v0002",
                    version_number=2,
                    supersedes_prep_version_id=first,
                    content_markdown="x" * MAX_MEETING_PREP_CHARACTERS,
                )
            )
        )
    _refused(
        engine,
        _prep_row(
            seeded,
            prep_version_id="mprep_mprepmig0001v0003",
            version_number=3,
            supersedes_prep_version_id=first,
        ),
        "a_meeting_prep_version_is_superseded_once",
        unique,
    )
