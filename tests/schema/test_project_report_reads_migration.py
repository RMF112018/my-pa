"""Project-report reads WP4P-S4: the read vocabulary revision, `3b3373d8268e`.

`3b3373d8268e` is additive on `fa18ef3d9bc0` (communications search WP4) and
vocabulary only: it restates the audit vocabulary, 322 -> 327 capabilities
(the five `project_reports.*` reads) and 73 -> 74 purposes
(`project_reports_read`), and creates no table, column, index, view, trigger
or grant (WP4P-W1 design report section 3). This module proves:

* **the graph** -- this revision is directly on `fa18ef3d9bc0`; no test here
  names the chain head;
* **the freeze** -- the revision imports nothing from the package it migrates;
  its before texts are byte copies of the revision that last stated them, and
  its at texts add exactly the new names;
* **offline SQL** for both directions, without a server;
* on a disposable database: the round trip restoring the previous catalog
  exactly; the audit vocabulary admitting exactly the new names; each
  downgrade refusal alone; and a downgrade over only unrelated audit rows
  succeeding and keeping them (ruling R3-03).

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
from sqlalchemy import Engine, insert, text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import audit_events

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "3b3373d8268e"
PREVIOUS: Final = "fa18ef3d9bc0"
MIGRATIONS: Final = ROOT / "migrations" / "versions"
MIGRATION: Final = MIGRATIONS / "20261125_3b3373d8268e_project_report_reads.py"
PRIOR_MIGRATION: Final = MIGRATIONS / "20261125_fa18ef3d9bc0_communications_search.py"

NEW_CAPABILITIES: Final = frozenset(
    {
        "project_reports.catalog",
        "project_reports.compare",
        "project_reports.coverage",
        "project_reports.query",
        "project_reports.record_history",
    }
)
NEW_PURPOSES: Final = frozenset({"project_reports_read"})

P: Final = "prn_prreadsmig0001aa"
WHEN: Final = datetime(2026, 11, 25, 12, tzinfo=UTC)
_WHITESPACE: Final = re.compile(r"\s+")


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


# ---- the graph and the freeze ------------------------------------------------------


def test_the_revision_is_directly_on_the_communications_search_revision() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_revision(REVISION).down_revision == PREVIOUS


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


def test_the_revision_is_vocabulary_only() -> None:
    """No table, column, index, view, trigger, grant or backfill (design section 3)."""
    code = _source().split('"""', 2)[2]
    assert "SET LOCAL lock_timeout = '10s'" in code
    for absent in (
        "CREATE TABLE",
        "ADD COLUMN",
        "CREATE INDEX",
        "CREATE VIEW",
        "CREATE TRIGGER",
        "CREATE OR REPLACE",
        "GRANT",
        "REVOKE",
        "INSERT INTO",
        "UPDATE ",
        "DELETE FROM",
        "create_table",
        "add_column",
        "create_index",
    ):
        assert absent not in code, absent


def test_the_audit_before_texts_are_byte_copies_and_the_at_texts_add_exactly_the_new() -> None:
    mine = _namespace(MIGRATION)
    prior = _namespace(PRIOR_MIGRATION)
    assert mine["_CAPABILITIES_BEFORE_THIS_REVISION"] == prior["_CAPABILITIES_AT_THIS_REVISION"]
    assert mine["_PURPOSES_BEFORE_THIS_REVISION"] == prior["_PURPOSES_AT_THIS_REVISION"]
    before = _literals(mine["_CAPABILITIES_BEFORE_THIS_REVISION"])
    at = _literals(mine["_CAPABILITIES_AT_THIS_REVISION"])
    assert (len(before), len(at)) == (322, 327)
    assert at == sorted(at)
    assert set(at) - set(before) == NEW_CAPABILITIES
    assert set(before) <= set(at)
    purposes_before = _literals(mine["_PURPOSES_BEFORE_THIS_REVISION"])
    purposes_at = _literals(mine["_PURPOSES_AT_THIS_REVISION"])
    assert (len(purposes_before), len(purposes_at)) == (73, 74)
    assert purposes_at == sorted(purposes_at)
    assert set(purposes_at) - set(purposes_before) == NEW_PURPOSES
    assert set(purposes_before) <= set(purposes_at)
    assert set(mine["_NEW_CAPABILITIES"]) == NEW_CAPABILITIES  # type: ignore[call-overload]
    assert set(mine["_NEW_PURPOSES"]) == NEW_PURPOSES  # type: ignore[call-overload]


# ---- offline SQL ---------------------------------------------------------------


def test_the_offline_upgrade_locks_first_and_restates_both_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{PREVIOUS}:{REVISION}")
    timeout = rendered.index("SET LOCAL lock_timeout")
    lock = rendered.index("LOCK TABLE knowledge.audit_events IN ACCESS EXCLUSIVE MODE")
    assert timeout < lock < rendered.index("DROP CONSTRAINT capability_is_known")
    assert rendered.count("LOCK TABLE") == 1
    for name in (*NEW_CAPABILITIES, *NEW_PURPOSES):
        assert f"'{name}'" in rendered, name
    assert "ADD CONSTRAINT capability_is_known CHECK" in rendered
    assert "ADD CONSTRAINT purpose_is_known CHECK" in rendered
    assert "GRANT" not in rendered
    assert f"SET version_num='{REVISION}'" in rendered


def test_the_offline_downgrade_refuses_first_and_restores_both_checks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    rendered = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    lock = rendered.index("LOCK TABLE knowledge.audit_events")
    refusal = rendered.index(f"refusing to downgrade {REVISION}")
    assert lock < refusal
    for later in ("DROP CONSTRAINT capability_is_known", "DROP CONSTRAINT purpose_is_known"):
        assert rendered.index(later) > refusal, later
    assert f"SET version_num='{PREVIOUS}'" in rendered


# ---- disposable databases -------------------------------------------------------


@pytest.fixture
def engine(cloned_database_url: str) -> Iterator[Engine]:
    """A current-head clone, downgraded to this revision (a later one would be unwound)."""
    built = create_database_engine(cloned_database_url)
    command.downgrade(_config(), REVISION)
    try:
        yield built
    finally:
        built.dispose()


def _constraint(error: DBAPIError) -> str | None:
    diag = getattr(error.orig, "diag", None)
    return None if diag is None else diag.constraint_name


def _attempt(engine: Engine, statement: Callable[[Connection], Any]) -> DBAPIError | None:
    """Run `statement` in a transaction that is always rolled back; return its error."""
    with engine.connect() as connection:
        transaction = connection.begin()
        try:
            statement(connection)
        except DBAPIError as error:
            return error
        finally:
            transaction.rollback()
    return None


def _audit(capability: str, purpose: str, number: int = 1) -> Callable[[Connection], Any]:
    return lambda connection: connection.execute(
        insert(audit_events).values(
            audit_id=f"audit_prreadsmigaudit{number}",
            correlation_id=f"corr_prreadsmigaudit{number}",
            principal_id=P,
            capability=capability,
            purpose=purpose,
            outcome="allowed",
            policy_version="policy-v1",
            scope_source_id_count=0,
            recorded_at=WHEN,
        )
    )


def _version(engine: Engine) -> str:
    with engine.connect() as connection:
        return str(connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one())


@pytest.mark.database
def test_the_audit_vocabulary_admits_exactly_the_new_names_at_this_revision(
    engine: Engine,
) -> None:
    for name in sorted(NEW_CAPABILITIES):
        assert _attempt(engine, _audit(name, "project_reports_read")) is None, name
    unknown = _attempt(engine, _audit("project_reports.unknown", "project_reports_read"))
    assert unknown is not None
    assert _constraint(unknown) == "capability_is_known"
    unknown = _attempt(engine, _audit("project_reports.query", "project_reports_write"))
    assert unknown is not None
    assert _constraint(unknown) == "purpose_is_known"
    command.downgrade(_config(), PREVIOUS)
    for name in sorted(NEW_CAPABILITIES):
        refused = _attempt(engine, _audit(name, "meeting_read"))
        assert refused is not None
        assert _constraint(refused) == "capability_is_known"
    refused = _attempt(engine, _audit("meetings.read", "project_reports_read"))
    assert refused is not None
    assert _constraint(refused) == "purpose_is_known"
    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION


_REFUSALS: Final = {
    **{f"capability_{name}": _audit(name, "meeting_read") for name in sorted(NEW_CAPABILITIES)},
    "purpose": _audit("meetings.read", "project_reports_read"),
}


@pytest.mark.database
@pytest.mark.parametrize("case", sorted(_REFUSALS))
def test_a_downgrade_refuses_while_one_audit_event_names_the_new_vocabulary(
    engine: Engine, case: str
) -> None:
    with engine.begin() as connection:
        _REFUSALS[case](connection)
    with pytest.raises(DBAPIError) as refused:
        command.downgrade(_config(), PREVIOUS)
    assert f"refusing to downgrade {REVISION}" in str(refused.value)
    assert getattr(refused.value.orig, "sqlstate", None) == "23001"
    assert _version(engine) == REVISION


#: Audit rows the previous vocabulary already admits (ruling R3-03).
_UNRELATED: Final = (
    ("communications.read", "communications_read"),
    ("reports.read", "report_read"),
)


@pytest.mark.database
def test_a_downgrade_with_only_unrelated_audit_rows_succeeds_and_keeps_them(
    engine: Engine,
) -> None:
    """Ruling R3-03: the refusal names only the new vocabulary, never any audit row.

    The `fa18ef3d9bc0` precedent: every other downgrade here runs over an
    empty `audit_events`, so a refusal on any row at all (mutant M1) passed.
    """
    with engine.begin() as connection:
        for number, (capability, purpose) in enumerate(_UNRELATED, start=1):
            _audit(capability, purpose, number)(connection)
    command.downgrade(_config(), PREVIOUS)
    assert _version(engine) == PREVIOUS

    def kept() -> list[tuple[str, str]]:
        with engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT capability, purpose FROM knowledge.audit_events "
                    "WHERE principal_id = :p ORDER BY audit_id"
                ),
                {"p": P},
            )
            return [(row.capability, row.purpose) for row in rows]

    assert kept() == list(_UNRELATED)
    command.upgrade(_config(), REVISION)
    assert _version(engine) == REVISION
    assert kept() == list(_UNRELATED)


#: The catalog state the round trip must restore exactly: every CHECK and
#: every function body in the schema, each as the server renders it.
_STATE_QUERIES: Final = {
    "checks": (
        "SELECT c.conrelid::regclass::text, c.conname, pg_get_constraintdef(c.oid) "
        "FROM pg_constraint c JOIN pg_namespace n ON n.oid = c.connamespace "
        "WHERE n.nspname = 'knowledge' AND c.contype = 'c' ORDER BY 1, 2"
    ),
    "functions": (
        "SELECT p.proname, pg_get_functiondef(p.oid) FROM pg_proc p "
        "JOIN pg_namespace n ON n.oid = p.pronamespace "
        "WHERE n.nspname = 'knowledge' AND p.prokind = 'f' ORDER BY 1, 2"
    ),
    "relations": (
        "SELECT c.relname, c.relkind FROM pg_class c "
        "JOIN pg_namespace n ON n.oid = c.relnamespace "
        "WHERE n.nspname = 'knowledge' ORDER BY 1"
    ),
}


def _catalog_state(engine: Engine) -> dict[str, list[tuple[Any, ...]]]:
    with engine.connect() as connection:
        return {
            name: [tuple(row) for row in connection.execute(text(sql))]
            for name, sql in _STATE_QUERIES.items()
        }


@pytest.mark.database
def test_the_round_trip_restores_the_previous_catalog_exactly(empty_database_url: str) -> None:
    """Captured on a database built to `PREVIOUS`, before this revision ever ran."""
    command.upgrade(_config(), PREVIOUS)
    built = create_database_engine(empty_database_url)
    try:
        before = _catalog_state(built)
        assert before["checks"] and before["relations"]
        command.upgrade(_config(), REVISION)
        at = _catalog_state(built)
        assert at["checks"] != before["checks"]
        # Vocabulary only: no relation and no function is added.
        assert at["relations"] == before["relations"]
        assert at["functions"] == before["functions"]
        command.downgrade(_config(), PREVIOUS)
        after = _catalog_state(built)
        for name in _STATE_QUERIES:
            assert after[name] == before[name], name
        command.upgrade(_config(), REVISION)
        assert _catalog_state(built) == at
    finally:
        built.dispose()
