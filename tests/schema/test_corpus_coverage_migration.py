"""Revision `2d9f4a7c1e58`: the audited vocabulary widened for `knowledge.coverage`.

WP-23, in the shape `tests/schema/test_continuity_migration.py` set.

**The revision is in the chain**, and deliberately not "is the head": that
property is true only until the next revision is written, and asserting it would
make every later work package edit this file.

**Empty to head, and prior revision to head and back.** `AGENTS.md` section 6
asks for a migration tested from an empty schema to head and for the preceding
supported revision where relevant. Both are here, and the downgrade is asserted
to restore exactly the thirty names `8f2b6c4d1a37` denotes — not whatever the
domain declares on the day the downgrade runs, which is the whole of what `D-69`
means by a frozen vocabulary.

**Why this revision exists at all.** `authorize()` writes an audit row in the
request's own transaction on every invocation, so `capability_is_known` is not a
description of the capability set — it is the gate the first `knowledge.coverage`
request in the field would meet. A member added to `Capability` with no forward
`ALTER` leaves every test green, because every test builds its database from
scratch, and is refused by the stored constraint the moment a real deployment
serves the capability. `test_the_member_without_this_alter_would_be_refused` is
that claim as a measurement rather than as a paragraph: it inserts an audit row
naming the new capability at the *previous* revision and watches the server
refuse it.

The database is disposable, created and dropped by this module's fixture, and is
never the configured one: `downgrade base` deletes schemas. Every value is
synthetic.
"""

from __future__ import annotations

import io
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]

DISPOSABLE_DATABASE: Final = "my_pa_corpus_coverage_migration_test"

SCHEMA: Final = "knowledge"

#: This revision and the one it revises.
CORPUS_REVISION: Final = "2d9f4a7c1e58"
PREVIOUS_REVISION: Final = "8f2b6c4d1a37"

#: The one name this revision admits.
CAPABILITY_ADDED: Final = "knowledge.coverage"

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
        "continuity.projects",
        "continuity.pulse",
        "continuity.situations",
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

WHEN: Final = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

_CONSTRAINT: Final = text(
    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
    "JOIN pg_class t ON t.oid = c.conrelid "
    "JOIN pg_namespace n ON n.oid = t.relnamespace "
    "WHERE n.nspname = :schema AND t.relname = :table AND c.conname = :name"
)

_AUDIT_INSERT: Final = text(
    "INSERT INTO knowledge.audit_events (audit_id, correlation_id, principal_id, "
    " capability, purpose, outcome, policy_version, scope_source_id_count, recorded_at) "
    "VALUES (:audit, :correlation, :principal, :capability, 'status_observation', "
    " 'allowed', 'policy-v1', 0, :at)"
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


def _frozen_literals(revision: str, constant: str) -> frozenset[str]:
    """The quoted names one revision module writes out under `constant`.

    Read as *text* rather than by importing the module, deliberately: importing
    would run the file, and what is being checked is what the file says. The
    revision is located by its identifier appearing in the filename, which is the
    naming every revision in `migrations/versions/` follows.
    """
    matches = [
        path for path in (ROOT / "migrations" / "versions").glob("*.py") if revision in path.name
    ]
    assert len(matches) == 1, f"{revision} names {len(matches)} revision files"
    text_of = matches[0].read_text(encoding="utf-8")
    start = text_of.index(f"{constant}: Final = (")
    end = text_of.index("\n)", start)
    return frozenset(re.findall(r"'([^']+)'", text_of[start:end]))


def _record(engine: Engine, capability: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            _AUDIT_INSERT,
            {
                "audit": issue_identifier(IdKind.AUDIT),
                "correlation": issue_identifier(IdKind.CORRELATION),
                "principal": issue_identifier(IdKind.PRINCIPAL),
                "capability": capability,
                "at": WHEN,
            },
        )


def test_the_corpus_revision_is_in_the_chain_on_the_continuity_revision() -> None:
    """One head, and this revision revises the one the campaign left at head."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert CORPUS_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(CORPUS_REVISION).down_revision == PREVIOUS_REVISION


def test_the_widened_vocabulary_is_the_frozen_one_plus_exactly_this_capability() -> None:
    """Guards the downgrade assertion below: equal sets would make it vacuous.

    **Read off this revision's own frozen literals, not off the live domain.**
    Until WP-28 this revision was the head, so "what the domain declares" and
    "what this revision installs" were the same set and the test compared the
    domain. They are no longer the same set — `6b3d9a2f8c14` widened both closed
    sets again — and continuing to compare the domain would have made this test
    a statement about whichever revision happens to be head rather than about
    this one. What it is *for* is that `2d9f4a7c1e58` admits exactly one name
    more than the revision below it, which is a property of the two frozen texts
    in the revision file and of nothing else, and is therefore true forever.
    """
    admitted = _frozen_literals(CORPUS_REVISION, "_CAPABILITIES_AT_THIS_REVISION")
    before = _frozen_literals(CORPUS_REVISION, "_CAPABILITIES_BEFORE_THIS_REVISION")
    assert before == CAPABILITIES_BEFORE
    assert admitted > before
    assert admitted - before == {CAPABILITY_ADDED}
    assert len(before) == 30
    assert len(admitted) == 31
    # The live domain is still checked, one direction only: this revision's names
    # must all still exist. It may hold more — WP-28's six do — and a name that
    # vanished from the enum while the constraint still admitted it would be the
    # drift this says nothing else about.
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    assert admitted <= declared


@pytest.mark.database
def test_the_corpus_revision_runs_empty_to_head_and_head_to_empty(
    disposable_database: str,
) -> None:
    """Reversible, and nothing of the chain survives `downgrade base`."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert CAPABILITY_ADDED in _admitted(engine, "audit_events", "capability_is_known")

        command.downgrade(_config(), "base")
        with engine.connect() as connection:
            remaining = set(
                connection.execute(
                    text(
                        "SELECT table_name FROM information_schema.tables "
                        "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
        assert remaining == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_this_revision_restores_exactly_the_previous_vocabulary(
    disposable_database: str,
) -> None:
    """The prior-revision half, and a round trip rather than a one-way observation.

    At head the constraint admits exactly what the two domain enums declare; one
    revision down it admits exactly the thirty `8f2b6c4d1a37` denotes. A downgrade
    that left the new name standing would make "the database is at
    `8f2b6c4d1a37`" name two different schemas.
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

        command.upgrade(_config(), "head")
        assert _admitted(engine, "audit_events", "capability_is_known") == declared
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_member_without_this_alter_would_be_refused_in_the_field(
    disposable_database: str,
) -> None:
    """Why the `ALTER` is written with the member and not after it.

    Every test builds its database from scratch, so a `Capability` member with no
    forward `ALTER` leaves the whole suite green — and is refused by the stored
    constraint on the first audited operation a real deployment performs. This
    stands the database at the previous revision, records an audit event naming
    the new capability, and watches PostgreSQL refuse it; then upgrades and
    watches the same insert succeed. Without the second half the first would only
    prove that the insert was malformed.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        with pytest.raises(IntegrityError):
            _record(engine, CAPABILITY_ADDED)
        # The control: a name the previous revision does admit goes in, so the
        # refusal above is about the vocabulary and not about the statement.
        _record(engine, "knowledge.search")

        command.upgrade(_config(), "head")
        _record(engine, CAPABILITY_ADDED)
        with engine.connect() as connection:
            stored = set(
                connection.execute(text("SELECT capability FROM knowledge.audit_events")).scalars()
            )
        assert stored == {"knowledge.search", CAPABILITY_ADDED}
    finally:
        engine.dispose()


@pytest.fixture
def disposable_database(empty_database_url: str) -> str:
    """Empty disposable catalog; migration tests still drive Alembic themselves."""
    return empty_database_url
