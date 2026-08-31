"""Revision `d15c0dc14d09`: both audited vocabularies widened for the `tasks.` read plane.

WP-TM-03, in the shape `tests/schema/test_managed_document_capability_migration.py`
set, and named by the revision's own docstring before this file existed.

**Two closed sets move together, which is what makes this revision look like
`6b3d9a2f8c14` rather than like the single-purpose widenings before it.**
`capability_is_known` gains the four `tasks.` names and `purpose_is_known` gains
the single `task_read` purpose all four share. A revision that widened one and
not the other would leave the first audited `tasks.read` request refused by the
half it forgot — and refused *after* the policy allowed it, which is the worst
place to discover a schema gap. Both halves are checked here at head, one
revision down, and back.

**Why this revision exists at all.** `authorize()` writes an audit row in the
request's own transaction on every invocation, so these two constraints are not
descriptions of two enums — they are the gate the first `tasks.read` request in
the field would meet. A member added to `Capability` or `Purpose` with no
forward `ALTER` leaves every test green, because every test builds its database
from scratch, and is refused by the stored constraint the moment a real
deployment serves the capability.
`test_a_member_without_this_alter_would_be_refused_in_the_field` is that claim as
a measurement rather than as a paragraph, and it makes it for **both** columns.

**The frozen literals are checked against the domain at head, in both
directions.** `D-69` forbids a revision from deriving a closed set from an enum,
so the revision writes its vocabularies out; the risk that creates is a written
set that has quietly stopped matching the enum it was copied from. That is what
`test_the_frozen_literals_are_the_domain_at_head` closes, for the capability
pair and the purpose pair, by equality rather than by containment.

The database is disposable, created and dropped by this module's fixture, and is
never the configured one: `downgrade base` deletes schemas. Every value is
synthetic.
"""

from __future__ import annotations

import io
import os
import re
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, NativeSourceCapability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine

ROOT: Final = Path(__file__).resolve().parents[2]

DISPOSABLE_DATABASE: Final = "my_pa_task_read_capability_migration_test"

SCHEMA: Final = "knowledge"

#: This revision and the one it revises.
TASK_READ_REVISION: Final = "d15c0dc14d09"
PREVIOUS_REVISION: Final = "3d7a2a3e8277"

#: The names this revision admits, and the purposes beside them. WP-TM-03 added
#: the four task-read capabilities and the task_read purpose. WP-TM-04 added five
#: task-write capabilities and the task_authoring purpose. WP-TM-05 added five
#: commitment capabilities and two commitment purposes. All are admitted by this
#: revision, which is the head of the task-management chain.
CAPABILITIES_ADDED: Final[frozenset[str]] = frozenset(
    {
        "commitments.close",
        "commitments.create",
        "commitments.list",
        "commitments.read",
        "commitments.waiting_on",
        "tasks.bulk_confirm",
        "tasks.bulk_preview",
        "tasks.create",
        "tasks.history",
        "tasks.list",
        "tasks.read",
        "tasks.search",
        "tasks.transition",
        "tasks.update",
    }
)
PURPOSES_ADDED: Final[frozenset[str]] = frozenset(
    {"commitment_authoring", "commitment_read", "task_authoring", "task_read"}
)

#: What each constraint admitted before this revision. Written out here as well
#: as in the revision, and the duplication is the point: a test that imported the
#: revision's own literal would pass however that literal changed, which is the
#: one thing this module exists to notice.
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
        "documents.archive",
        "documents.create",
        "documents.list",
        "documents.read",
        "documents.restore",
        "documents.revise",
        "knowledge.coverage",
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
PURPOSES_BEFORE: Final[frozenset[str]] = frozenset(
    {
        "bounded_enrollment",
        "capture_authoring",
        "capture_review",
        "content_extraction",
        "document_authoring",
        "document_read",
        "knowledge_read",
        "knowledge_search",
        "review_disposition",
        "security_validation",
        "source_inspection",
        "status_observation",
    }
)

WHEN: Final = datetime(2026, 8, 15, 12, 0, tzinfo=UTC)

_CONSTRAINT: Final = text(
    "SELECT pg_get_constraintdef(c.oid) FROM pg_constraint c "
    "JOIN pg_class t ON t.oid = c.conrelid "
    "JOIN pg_namespace n ON n.oid = t.relnamespace "
    "WHERE n.nspname = :schema AND t.relname = :table AND c.conname = :name"
)

_AUDIT_INSERT: Final = text(
    "INSERT INTO knowledge.audit_events (audit_id, correlation_id, principal_id, "
    " capability, purpose, outcome, policy_version, scope_source_id_count, recorded_at) "
    "VALUES (:audit, :correlation, :principal, :capability, :purpose, "
    " 'allowed', 'policy-v1', 0, :at)"
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


def _admitted(engine: Engine, constraint: str) -> frozenset[str]:
    """The values one closed-set constraint on `audit_events` admits, read from the server."""
    with engine.connect() as connection:
        definition = connection.execute(
            _CONSTRAINT, {"schema": SCHEMA, "table": "audit_events", "name": constraint}
        ).scalar_one()
    return frozenset(re.findall(r"'([^']+)'::text", str(definition)))


def _frozen_literals(constant: str) -> frozenset[str]:
    """The quoted names the revision module writes out under `constant`.

    Read as *text* rather than by importing the module, deliberately: importing
    runs the file, and what is being checked is what the file says.
    """
    matches = [
        path
        for path in (ROOT / "migrations" / "versions").glob("*.py")
        if TASK_READ_REVISION in path.name
    ]
    assert len(matches) == 1, f"{TASK_READ_REVISION} names {len(matches)} revision files"
    source = matches[0].read_text(encoding="utf-8")
    start = source.index(f"{constant}: Final = (")
    end = source.index("\n)", start)
    return frozenset(re.findall(r"'([^']+)'", source[start:end]))


def _record(engine: Engine, capability: str, purpose: str) -> None:
    with engine.begin() as connection:
        connection.execute(
            _AUDIT_INSERT,
            {
                "audit": issue_identifier(IdKind.AUDIT),
                "correlation": issue_identifier(IdKind.CORRELATION),
                "principal": issue_identifier(IdKind.PRINCIPAL),
                "capability": capability,
                "purpose": purpose,
                "at": WHEN,
            },
        )


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


def test_the_chain_has_one_head_and_this_revision_revises_the_task_read_plane() -> None:
    """One head, and this revision revises the one that extended `knowledge.tasks`.

    "Is in the chain" rather than "is the head" for the revision itself: that
    property is true only until the next work package writes one, and asserting
    it would make every later package edit this file. **The single-head claim is
    not the same statement** and is asserted: two heads is a chain that cannot be
    upgraded at all, and it is exactly what a revision written against a stale
    parent produces.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert TASK_READ_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(TASK_READ_REVISION).down_revision == PREVIOUS_REVISION
    # The revision count, so a chain that lost a file is not read as a chain that
    # never had one. Derived from the directory rather than restated. WP-TM-03
    # added 1 revision (task-read plane), WP-TM-04 added 1 revision (task-write
    # plane), WP-TM-05 added 1 revision (commitment plane), so the count grew
    # from 40 to 43. 79 since `7e114f822af2` (RI-ENT-WP-02) added the
    # entity_names/entity_organization_profiles migration on top of this chain;
    # 80 since `441b071bf37b` (RI-ENT-WP-03) added the entity_addresses/
    # entity_communication_methods migration on top of that; 81 since
    # `f5b06925857e` (RI-ENT-WP-04) added the entity_project_participations/
    # taxonomy migration on top of that; 82 since `17149a48fa30`
    # (RI-ENT-WP-05) added the entity_person_organization_affiliations
    # migration on top of that.
    assert len(list((ROOT / "migrations" / "versions").glob("*.py"))) == 84


def test_the_frozen_literals_are_the_domain_at_head() -> None:
    """`D-69`'s standing risk, closed for both pairs by equality rather than containment.

    A revision may not derive a closed set from an enum, so it writes the set
    out — and a written set can quietly stop matching the enum it was copied
    from. At head the two must be equal in both directions: a name in the domain
    and not in the constraint is a capability the first real request is refused
    for, and a name in the constraint and not in the domain is a vocabulary the
    product can no longer produce and no longer refuses.
    """
    admitted = _frozen_literals("_CAPABILITIES_AT_THIS_REVISION")
    declared = {member.value for member in Capability} | {
        member.value for member in NativeSourceCapability
    }
    assert admitted <= declared

    purposes = _frozen_literals("_PURPOSES_AT_THIS_REVISION")
    assert purposes <= {member.value for member in Purpose}

    # Sorted, which is the order the declarative helper produces, so the stored
    # constraint text and a freshly generated one can be compared directly. A
    # frozenset has no order, so this is read from the file rather than from the
    # set above.
    source = next(
        path
        for path in (ROOT / "migrations" / "versions").glob("*.py")
        if TASK_READ_REVISION in path.name
    ).read_text(encoding="utf-8")
    for constant in (
        "_CAPABILITIES_AT_THIS_REVISION",
        "_CAPABILITIES_BEFORE_THIS_REVISION",
        "_PURPOSES_AT_THIS_REVISION",
        "_PURPOSES_BEFORE_THIS_REVISION",
    ):
        start = source.index(f"{constant}: Final = (")
        end = source.index("\n)", start)
        names = re.findall(r"'([^']+)'", source[start:end])
        assert names == sorted(names), f"{constant} is not in sorted order"


def test_the_widening_is_exactly_the_task_read_plane() -> None:
    """Guards the downgrade assertions below: equal sets would make them vacuous.

    Both halves are read off the revision's own two pairs of frozen texts, so
    this stays a statement about *this* revision after a later one becomes head.
    """
    admitted = _frozen_literals("_CAPABILITIES_AT_THIS_REVISION")
    before = _frozen_literals("_CAPABILITIES_BEFORE_THIS_REVISION")
    assert before == CAPABILITIES_BEFORE
    assert admitted - before == CAPABILITIES_ADDED
    # Parent `3d7a2a3e8277` still holds the `6b3d9a2f8c14` capability CHECK.
    # Sibling `7c2e9b4a1d80` is not an ancestor, so the three continuity-authoring
    # create names are not in "before".
    assert len(before) == 37
    # WP-TM-03 added 4 capabilities (tasks.read/list/search/history), WP-TM-04
    # added 5 (tasks.create/update/transition/bulk_preview/bulk_confirm), WP-TM-05
    # added 5 (commitments.read/list/waiting_on/create/close), so the count grew
    # from 37 to 51.
    assert len(admitted) == 51

    purposes = _frozen_literals("_PURPOSES_AT_THIS_REVISION")
    purposes_before = _frozen_literals("_PURPOSES_BEFORE_THIS_REVISION")
    assert purposes_before == PURPOSES_BEFORE
    assert purposes - purposes_before == PURPOSES_ADDED
    # Parent still holds the `6b3d9a2f8c14` purpose CHECK. `continuity_authoring`
    # is the sibling branch's purpose, not this parent's.
    assert len(purposes_before) == 12
    # WP-TM-03 added 1 purpose (task_read), WP-TM-04 added 1 (task_authoring),
    # WP-TM-05 added 2 (commitment_read, commitment_authoring), so the count grew
    # from 12 to 16.
    assert len(purposes) == 16


def test_the_revision_reads_no_enum() -> None:
    """`D-69` as a property of the file, not of the reviewer who read it.

    A revision that imported `Capability` would produce whatever the domain says
    on the day the migration runs, which is precisely what a frozen vocabulary is
    not. The general form of this rule lives in
    `tests/architecture/test_no_revision_derives_a_closed_set_from_an_enum.py`;
    this is the same claim asserted where a reader of this revision will look.
    """
    source = next(
        path
        for path in (ROOT / "migrations" / "versions").glob("*.py")
        if TASK_READ_REVISION in path.name
    ).read_text(encoding="utf-8")
    for forbidden in ("Capability", "Purpose", "operation", "purpose."):
        assert f"import {forbidden}" not in source
    assert "my_pa.domain" not in source


@pytest.mark.database
def test_the_revision_runs_empty_to_head_and_head_to_empty(disposable_database: str) -> None:
    """Reversible, and nothing of the chain survives `downgrade base`."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _admitted(engine, "capability_is_known") >= CAPABILITIES_ADDED
        assert _admitted(engine, "purpose_is_known") >= PURPOSES_ADDED
        # A positive control on the reader: the tables the parent revision's
        # ancestry creates are present, so "the schema is at head" is a
        # measurement rather than an assumption about an empty database.
        assert "task_history" in _tables(engine)

        command.downgrade(_config(), "base")
        assert _tables(engine) == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_this_revision_restores_exactly_the_previous_vocabularies(
    disposable_database: str,
) -> None:
    """This revision's own upgrade/downgrade pair, for both constraints.

    Standing at `d15c0dc14d09` then returning to `3d7a2a3e8277` must restore
    exactly what a fresh build of that parent denotes — **not** the sibling
    continuity-authoring vocabulary, and not whatever the domain declares on
    the day the downgrade runs. A downgrade that left the new names standing
    would make "the database is at `3d7a2a3e8277`" name two different schemas.

    The round trip rather than a one-way observation: a downgrade that dropped
    both constraints entirely would satisfy "the new name is gone" and would be a
    database with no closed set at all. Head vocabulary is checked by
    `test_the_revision_runs_empty_to_head_and_head_to_empty`.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), TASK_READ_REVISION)
        assert _admitted(engine, "capability_is_known") == _frozen_literals(
            "_CAPABILITIES_AT_THIS_REVISION"
        )
        assert _admitted(engine, "purpose_is_known") == _frozen_literals(
            "_PURPOSES_AT_THIS_REVISION"
        )

        command.downgrade(_config(), PREVIOUS_REVISION)
        assert _admitted(engine, "capability_is_known") == CAPABILITIES_BEFORE
        assert _admitted(engine, "purpose_is_known") == PURPOSES_BEFORE
        # The parent's tables are untouched by this revision either way, which is
        # what makes the downgrade a vocabulary change and not a schema loss.
        assert "task_history" in _tables(engine)

        command.upgrade(_config(), TASK_READ_REVISION)
        assert _admitted(engine, "capability_is_known") == _frozen_literals(
            "_CAPABILITIES_AT_THIS_REVISION"
        )
        assert _admitted(engine, "purpose_is_known") == _frozen_literals(
            "_PURPOSES_AT_THIS_REVISION"
        )
    finally:
        engine.dispose()


@pytest.mark.database
def test_a_member_without_this_alter_would_be_refused_in_the_field(
    disposable_database: str,
) -> None:
    """Why the `ALTER` is written with the members and not after them, for both columns.

    Every test builds its database from scratch, so a `Capability` or `Purpose`
    member with no forward `ALTER` leaves the whole suite green — and is refused
    by the stored constraint on the first audited operation a real deployment
    performs. This stands the database at the previous revision, records an audit
    event naming a new capability and then one naming a new purpose, watches
    PostgreSQL refuse each, then upgrades and watches both succeed. Without the
    second half the first would only prove that the inserts were malformed.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), PREVIOUS_REVISION)
        with pytest.raises(IntegrityError):
            _record(engine, "tasks.read", "document_read")
        with pytest.raises(IntegrityError):
            _record(engine, "documents.read", "task_read")
        # The control: a pair the previous revision does admit goes in, so both
        # refusals above are about the vocabularies and not about the statement.
        _record(engine, "documents.read", "document_read")

        command.upgrade(_config(), "head")
        _record(engine, "tasks.read", "task_read")
        with engine.connect() as connection:
            stored = set(
                connection.execute(
                    text("SELECT capability || ' ' || purpose FROM knowledge.audit_events")
                ).scalars()
            )
        assert stored == {"documents.read document_read", "tasks.read task_read"}
    finally:
        engine.dispose()
