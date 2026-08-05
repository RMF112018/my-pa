"""The extraction revision round-trips, and no revision creates more than it names.

Two claims live here, and the second is the reason the first can be trusted.

The **structural guard** is `test_each_revision_creates_exactly_the_tables_it_declares`.
Every revision that creates a table in the `knowledge` schema does it from one
shared `MetaData`, declared in `my_pa.infrastructure.persistence.tables`. A
revision that called `create_all(bind)` without naming its tables would create
whatever that module happens to declare *now*, so declaring a new table would
silently change what an already-landed revision does and the revision would stop
being a record of what was applied. That is not hypothetical: it is what the
knowledge revision did before this work package pinned it. The guard compares the
DDL each revision actually emits against a list restated here, so removing a pin
turns the suite red instead of quietly widening history.

The **table and constraint names are restated**, not imported, following the same
discipline as `tests/schema/test_foundation_migration.py`: a test that imports the
list it is checking proves only that a loop ran.

Every database test runs against a disposable database created and dropped by its
fixture, never against the configured one. `downgrade base` deletes schemas, and
pointing that at the canonical `my_pa` database would destroy the migrated
corpus. Nothing here reads the legacy SQLite source, and every value inserted is
synthetic — the "documents" below are two sentences written for this file.
"""

from __future__ import annotations

import io
import re
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, NamedTuple

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Connection, Engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import IntegrityError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.extraction.coverage import LimitationReason, SnapshotState
from my_pa.domain.extraction.quarantine import QuarantineReason, QuarantineReviewState
from my_pa.domain.extraction.text import ExtractionOutcome, ExtractionStatus, extract_text
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.enrollment import EnrollmentRequest, EnrollmentScope
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import SourceProviderKind, issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.enrollment import accept_enrollment, record_scope
from my_pa.infrastructure.persistence.extraction import (
    UnauthorizedObjectError,
    coverage_for,
    quarantine_object,
    record_limitation,
    record_outcome,
)
from my_pa.infrastructure.persistence.knowledge import pending_objects
from my_pa.infrastructure.persistence.registry import observe_object, register_source
from my_pa.infrastructure.persistence.tables import METADATA

ROOT = Path(__file__).resolve().parents[2]

EXPECTED_SCHEMA = "knowledge"

#: Restated, not imported. The knowledge revision's five, this revision's three,
#: the audit revision's one, the enrollment-objects revision's one, the capture
#: revision's five, and the proposal revision's seven, each against the revision
#: that must create them and no other.
KNOWLEDGE_TABLES_BY_REVISION: Final[dict[str, frozenset[str]]] = {
    "7e5a1fb93d62": frozenset(
        {
            "sources",
            "source_objects",
            "source_object_versions",
            "enrollments",
            "jobs",
        }
    ),
    "8b3f5c17d904": frozenset(
        {
            "extractions",
            "quarantine_records",
            "coverage_limitations",
        }
    ),
    "9c6b4a18ed72": frozenset({"audit_events"}),
    "af3d35efb9c0": frozenset({"enrollment_objects"}),
    "1a4c9e77b2d5": frozenset(
        {
            "captures",
            "capture_versions",
            "capture_receipts",
            "capture_submissions",
            "capture_jobs",
        }
    ),
    "2b7e9f4c1a83": frozenset(
        {
            "capture_processing_text",
            "capture_stage_results",
            "capture_spans",
            "capture_proposals",
            "capture_proposal_spans",
            "capture_classifications",
            "capture_entity_mentions",
        }
    ),
    "3c8f1e2a5b74": frozenset(
        {
            "capture_review_cases",
            "capture_review_decisions",
            "capture_assertions",
            "capture_assertion_spans",
            "capture_promotion_receipts",
            "capture_context_links",
            "capture_conversations",
        }
    ),
    "7f2a9d6c4e18": frozenset(
        {
            "relationship_people",
            "relationship_organizations",
            "relationship_identity_observations",
            "relationship_unresolved_mentions",
            "relationship_duplicate_sets",
            "relationship_duplicate_members",
            "relationship_identity_review_cases",
            "relationship_identity_review_decisions",
            "relationship_identity_resolutions",
            "relationship_resolution_observations",
            "relationship_observation_links",
            "relationship_aliases",
            "relationship_affiliations",
            "relationship_evidence",
            "relationship_evidence_observations",
            "relationship_conversation_participants",
            "relationship_conversation_observations",
        }
    ),
    "8c4d1e7a2b90": frozenset(
        {
            "source_version_evidence",
            "native_bridges",
            "native_bridge_observations",
            "native_source_accounts",
            "native_source_buckets",
            "native_discovery_snapshots",
            "native_configuration_revisions",
            "native_configuration_buckets",
            "native_sync_runs",
            "native_bucket_runs",
            "native_sync_jobs",
            "native_checkpoints",
            "source_observations",
            "source_memberships",
            "native_watcher_simulations",
            "native_simulation_receipts",
            "native_live_activation_gates",
        }
    ),
}

#: The union of the two lists above. Stated as a name because two tests compare
#: the whole schema against it.
ALL_KNOWLEDGE_TABLES: Final[frozenset[str]] = frozenset(
    name for tables in KNOWLEDGE_TABLES_BY_REVISION.values() for name in tables
)

EXTRACTION_REVISION = "8b3f5c17d904"
KNOWLEDGE_REVISION = "7e5a1fb93d62"
FOUNDATION_HEAD = "6c4d3ea82f10"

#: The revision that creates the migrated corpus's tables, and how many. Used as
#: a positive control for the DDL parser: those statements are schema-qualified
#: and quoted, so a parser that only understood unquoted names would report every
#: revision as creating nothing and this module's equality checks would then be
#: comparing two empty sets.
TARGET_TABLES_REVISION = "1e6c0a94f3b7"
TARGET_TABLE_COUNT = 484

EXPECTED_EXTRACTION_CHECKS = frozenset(
    {
        "extraction_status_is_known",
        "derived_text_is_never_source_original",
        "text_exists_exactly_when_something_was_extracted",
        "only_a_supported_media_type_is_extracted",
        "extraction_follows_its_observation",
        "quarantine_reason_is_known",
        "quarantine_review_state_is_known",
        "limitation_reason_is_known",
        "a_limitation_affects_at_least_one_object",
    }
)
EXPECTED_EXTRACTION_UNIQUES = frozenset(
    {
        "one_extraction_per_version_per_enrollment",
        "one_limitation_per_reason_per_snapshot",
    }
)

#: Every column of `quarantine_records`, restated. This is the payload claim: a
#: quarantine stores identifiers, two enumerated codes, and a timestamp, and
#: there is nowhere in the row for the content that failed. A column added here
#: has to be acknowledged in this list, which is the point.
EXPECTED_QUARANTINE_COLUMNS = frozenset(
    {
        "quarantine_id",
        "enrollment_id",
        "source_object_id",
        "version_id",
        "reason",
        "review_state",
        "quarantined_at",
    }
)

#: Likewise for the aggregate limitation: a reason and a count, and nothing that
#: could say which objects were affected.
EXPECTED_LIMITATION_COLUMNS = frozenset(
    {
        "limitation_id",
        "enrollment_id",
        "observed_at",
        "reason",
        "affected_count",
        "recorded_at",
    }
)

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
#: Distinct from every other suite's disposable database, so they cannot collide.
DISPOSABLE_DATABASE = "my_pa_extraction_test"

#: Synthetic throughout. No such path exists and none is opened.
NATIVE_ROOT = "/synthetic/fixtures/corpus"
NATIVE_LOCATOR = "/synthetic/fixtures/corpus/note.md"

#: Written for this file. Not drawn from any real document.
SYNTHETIC_MARKDOWN = "# Synthetic note\n\nTwo lines of invented text.\n"

OBSERVED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: A quoted or unquoted schema-qualified `CREATE TABLE`, as PostgreSQL DDL emits
#: it. Both spellings appear in this repository's revisions.
_CREATE_TABLE = re.compile(
    r'CREATE TABLE (?:IF NOT EXISTS )?"?([A-Za-z0-9_]+)"?\."?([A-Za-z0-9_]+)"?'
)


def _config(output_buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=output_buffer)


def _tables_created_by(revision: str, down_revision: str | None) -> set[tuple[str, str]]:
    """Every `(schema, table)` one revision emits a `CREATE TABLE` for.

    Offline, so it needs no server and stays in the fast tier, and it reads the
    SQL the revision actually produces rather than the list it was written from.
    """
    buffer = io.StringIO()
    start = down_revision or "base"
    command.upgrade(_config(output_buffer=buffer), f"{start}:{revision}", sql=True)
    return set(_CREATE_TABLE.findall(buffer.getvalue()))


def _revisions() -> list[tuple[str, str | None]]:
    """Every revision in the chain, paired with the one it follows."""
    script = ScriptDirectory.from_config(_config())
    chain: list[tuple[str, str | None]] = []
    for revision in script.walk_revisions():
        down = revision.down_revision
        parent = down if down is None or isinstance(down, str) else down[0]
        chain.append((revision.revision, parent))
    return chain


def test_the_extraction_revision_is_in_the_chain_on_the_knowledge_revision() -> None:
    """Guards the rest of this module: an absent revision would collect nothing.

    Deliberately not "is the head". That property is true only until the next
    revision is written, and asserting it would make every later work package
    edit this file — which is exactly what the knowledge suite had to do when
    this revision landed. A single unbranched chain containing this revision is
    the property the tables below actually depend on.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert EXTRACTION_REVISION in {entry.revision for entry in script.walk_revisions()}
    revision = script.get_revision(EXTRACTION_REVISION)
    assert revision.down_revision == KNOWLEDGE_REVISION
    assert len(_revisions()) >= 8


def test_the_ddl_parser_sees_a_revision_that_creates_tables(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Positive control for the guard below.

    Without this, a `_CREATE_TABLE` pattern that matched nothing would make every
    revision look like it creates no table, and the guard would only be
    comparing empty sets against the two entries that are supposed to be empty.
    """
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", "postgresql+psycopg://nobody@nowhere/nothing")
    created = _tables_created_by(TARGET_TABLES_REVISION, "5d75f23847c9")
    assert len(created) == TARGET_TABLE_COUNT
    assert all(schema != EXPECTED_SCHEMA for schema, _ in created)


def test_each_revision_creates_exactly_the_tables_it_declares(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No revision may create a `knowledge` table it does not name.

    The structural guard. `METADATA` is shared across revisions, so an
    unqualified `create_all` in any of them would create every table declared in
    `tables.py` — including tables added by later work — and a landed revision
    would silently change what it does. Pinning each revision to its own tables
    is the fix; this is what makes removing the pin fail.
    """
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", "postgresql+psycopg://nobody@nowhere/nothing")
    for revision, down_revision in _revisions():
        created = {
            table
            for schema, table in _tables_created_by(revision, down_revision)
            if schema == EXPECTED_SCHEMA
        }
        expected = KNOWLEDGE_TABLES_BY_REVISION.get(revision, frozenset())
        assert created == expected, (
            f"revision {revision} creates {sorted(created)} in {EXPECTED_SCHEMA}, "
            f"but declares {sorted(expected)}"
        )


def test_every_declared_table_is_created_by_exactly_one_revision() -> None:
    """A table in `tables.py` that no revision creates would never exist.

    The other half of the guard. Pinning revisions to explicit lists makes it
    possible to declare a table that nothing creates, and the writers would then
    fail against a database migrated to head. Summing the restated lists and
    comparing against the declaration catches both that and a table created
    twice.
    """
    declared = {table.name for table in METADATA.tables.values()}
    pinned = [name for tables in KNOWLEDGE_TABLES_BY_REVISION.values() for name in tables]

    assert len(pinned) == len(set(pinned)), "a table is created by more than one revision"
    assert set(pinned) == declared


def test_offline_mode_emits_the_extraction_ddl_without_connecting(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--sql` has to work with no server: it is how the DDL gets reviewed."""
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", "postgresql+psycopg://nobody@nowhere/nothing")
    buffer = io.StringIO()

    command.upgrade(_config(output_buffer=buffer), "head", sql=True)

    emitted = buffer.getvalue()
    for table in KNOWLEDGE_TABLES_BY_REVISION[EXTRACTION_REVISION]:
        assert f"CREATE TABLE {EXPECTED_SCHEMA}.{table}" in emitted
    for constraint in EXPECTED_EXTRACTION_CHECKS | EXPECTED_EXTRACTION_UNIQUES:
        assert constraint in emitted


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards."""
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
        # CREATE and DROP DATABASE cannot run inside a transaction block.
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            for statement in statements:
                connection.execute(statement)  # type: ignore[arg-type]

    try:
        _administer(drop, text(f'CREATE DATABASE "{DISPOSABLE_DATABASE}"'))
        url = configured.set(database=DISPOSABLE_DATABASE).render_as_string(hide_password=False)
        monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
        yield url
    finally:
        _administer(drop)
        maintenance.dispose()


@pytest.fixture
def extraction_engine(disposable_database: str) -> Iterator[Engine]:
    """A disposable database upgraded to head, disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def _tables(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = :schema AND table_type = 'BASE TABLE'"
                ),
                {"schema": EXPECTED_SCHEMA},
            ).scalars()
        )


def _columns(engine: Engine, table: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = :schema AND table_name = :table"
                ),
                {"schema": EXPECTED_SCHEMA, "table": table},
            ).scalars()
        )


def _constraints(engine: Engine, kind: str) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT con.conname FROM pg_constraint con "
                    "JOIN pg_namespace n ON n.oid = con.connamespace "
                    "WHERE n.nspname = :schema AND con.contype = :kind"
                ),
                {"schema": EXPECTED_SCHEMA, "kind": kind},
            ).scalars()
        )


@pytest.mark.database
def test_upgrade_from_empty_and_downgrade_back_to_empty(disposable_database: str) -> None:
    engine = create_database_engine(disposable_database)
    all_tables = ALL_KNOWLEDGE_TABLES
    try:
        command.upgrade(_config(), "head")

        assert _tables(engine) == all_tables
        assert _constraints(engine, "c") >= EXPECTED_EXTRACTION_CHECKS
        assert _constraints(engine, "u") >= EXPECTED_EXTRACTION_UNIQUES

        command.downgrade(_config(), "base")

        with engine.connect() as connection:
            remaining = set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars())
        assert EXPECTED_SCHEMA not in remaining
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_one_revision_leaves_the_knowledge_tables_alone(
    disposable_database: str,
) -> None:
    """This revision added three tables to a schema it did not create.

    Its downgrade therefore removes three tables and not the schema. Dropping the
    schema here would take the enrollment and job records with it, which is how a
    downgrade destroys evidence it never owned.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        command.downgrade(_config(), KNOWLEDGE_REVISION)

        assert _tables(engine) == KNOWLEDGE_TABLES_BY_REVISION[KNOWLEDGE_REVISION]

        command.upgrade(_config(), "head")
        assert _tables(engine) == ALL_KNOWLEDGE_TABLES

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_a_quarantine_row_has_nowhere_to_put_a_payload(extraction_engine: Engine) -> None:
    """The structural half of section 12, asserted against the server.

    A quarantine stores identifiers, codes, and a time. If a column were added
    that could hold the bytes or text that failed, the record would become the
    payload channel the specification forbids, and this is where that shows up.
    """
    assert _columns(extraction_engine, "quarantine_records") == EXPECTED_QUARANTINE_COLUMNS
    assert _columns(extraction_engine, "coverage_limitations") == EXPECTED_LIMITATION_COLUMNS


class Enrolled(NamedTuple):
    """One configured source, one accepted enrollment, and the objects it names.

    `also_named` holds the `(source_object_id, version_id)` of any further
    objects the enrollment authorized beyond the first. It exists because an
    enrollment's named `object_ids` are an authorization boundary that
    `coverage_for` and `record_outcome` enforce: a test that observes a second
    object and records an outcome for it under this enrollment has to have that
    object named here, or the outcome is refused and would never have been
    counted anyway.
    """

    source_id: str
    enrollment_id: str
    source_object_id: str
    version_id: str
    also_named: tuple[tuple[str, str], ...] = ()


def _enrolled(connection: Connection, *, also_named: int = 0) -> Enrolled:
    """A source, an enrollment, and `1 + also_named` observed objects it authorizes."""
    source = register_source(
        connection,
        provider_kind=SourceProviderKind.FIXTURE,
        label="Fixture corpus",
        classification=Classification.SYNTHETIC_TEST,
        native_root=NATIVE_ROOT,
    )
    observed = observe_object(
        connection,
        source_id=source.source_id,
        native_locator=NATIVE_LOCATOR,
        kind=ObjectKind.FILE,
        fingerprint="fingerprint-one",
        modified_at=OBSERVED_AT,
        media_type="text/markdown",
        size_bytes=len(SYNTHETIC_MARKDOWN),
    )
    others = [
        observe_object(
            connection,
            source_id=source.source_id,
            native_locator=f"{NATIVE_ROOT}/other-{index}.md",
            kind=ObjectKind.FILE,
            fingerprint=f"fingerprint-other-{index}",
            modified_at=OBSERVED_AT,
            media_type="text/markdown",
            size_bytes=8,
        )
        for index in range(also_named)
    ]
    accepted = accept_enrollment(
        connection,
        EnrollmentRequest(
            source_id=source.source_id,
            principal_id=issue_identifier(IdKind.PRINCIPAL),
            purpose=Purpose.BOUNDED_ENROLLMENT,
            scope=EnrollmentScope(
                object_ids=(
                    observed.source_object_id,
                    *(other.source_object_id for other in others),
                )
            ),
            media_types=("text/markdown",),
            policy_version="mcv-1",
            idempotency_key="enroll-extraction-1",
            max_items=10,
            max_bytes=4096,
        ),
    )
    # The enumerated object set: what `authorized_object` tests membership of and
    # what `coverage_for` counts for its denominator. `sources.enroll` writes it
    # inside the accepting transaction, so an enrollment built without one here
    # would authorize nothing and every assertion below would be about that.
    record_scope(
        connection,
        accepted.enrollment.enrollment_id,
        [observed.source_object_id, *(other.source_object_id for other in others)],
    )
    return Enrolled(
        source_id=source.source_id,
        enrollment_id=accepted.enrollment.enrollment_id,
        source_object_id=observed.source_object_id,
        version_id=observed.version_id,
        also_named=tuple((other.source_object_id, other.version_id) for other in others),
    )


def _enrolled_under_a_root(connection: Connection) -> Enrolled:
    """An enrollment that names a *root*, with one object under it and one beside it.

    The shape the containment gap lived in. Both objects belong to the same
    source, so the source half of `authorized_object` cannot account for a
    refusal and only membership of the enumerated set can — the single-condition
    variation this test needs. `record_scope` records only the object under the
    root, which is what the walk would have found.
    """
    source = register_source(
        connection,
        provider_kind=SourceProviderKind.FIXTURE,
        label="Rooted corpus",
        classification=Classification.SYNTHETIC_TEST,
        native_root=f"{NATIVE_ROOT}/rooted",
    )
    root = observe_object(
        connection,
        source_id=source.source_id,
        native_locator=f"{NATIVE_ROOT}/rooted/tree",
        kind=ObjectKind.CONTAINER,
        fingerprint="fingerprint-rooted-tree",
        modified_at=OBSERVED_AT,
    )
    inside = observe_object(
        connection,
        source_id=source.source_id,
        native_locator=f"{NATIVE_ROOT}/rooted/tree/inside.md",
        kind=ObjectKind.FILE,
        fingerprint="fingerprint-rooted-inside",
        modified_at=OBSERVED_AT,
        media_type="text/markdown",
        size_bytes=len(SYNTHETIC_MARKDOWN),
    )
    beside = observe_object(
        connection,
        source_id=source.source_id,
        native_locator=f"{NATIVE_ROOT}/rooted/sibling.md",
        kind=ObjectKind.FILE,
        fingerprint="fingerprint-rooted-beside",
        modified_at=OBSERVED_AT,
        media_type="text/markdown",
        size_bytes=len(SYNTHETIC_MARKDOWN),
    )
    accepted = accept_enrollment(
        connection,
        EnrollmentRequest(
            source_id=source.source_id,
            principal_id=issue_identifier(IdKind.PRINCIPAL),
            purpose=Purpose.BOUNDED_ENROLLMENT,
            scope=EnrollmentScope(root_object_id=root.source_object_id, depth=0),
            media_types=("text/markdown",),
            policy_version="mcv-1",
            idempotency_key="enroll-extraction-rooted",
            max_items=10,
            max_bytes=4096,
        ),
    )
    record_scope(connection, accepted.enrollment.enrollment_id, [inside.source_object_id])
    return Enrolled(
        source_id=source.source_id,
        enrollment_id=accepted.enrollment.enrollment_id,
        source_object_id=inside.source_object_id,
        version_id=inside.version_id,
        also_named=((beside.source_object_id, beside.version_id),),
    )


def _outcome(
    enrolled: Enrolled,
    *,
    content: bytes = SYNTHETIC_MARKDOWN.encode("utf-8"),
    media_type: str | None = "text/markdown",
    source_object_id: str | None = None,
    version_id: str | None = None,
    content_version_id: str | None = None,
) -> ExtractionOutcome:
    observed_version = enrolled.version_id if version_id is None else version_id
    observed_object = enrolled.source_object_id if source_object_id is None else source_object_id
    return extract_text(
        source_id=enrolled.source_id,
        source_object_id=observed_object,
        observed_version_id=observed_version,
        content_version_id=observed_version if content_version_id is None else content_version_id,
        media_type=media_type,
        content=content,
        observed_at=OBSERVED_AT,
        processed_at=OBSERVED_AT,
    )


@pytest.mark.database
def test_an_extraction_is_stored_once_however_often_it_is_retried(
    extraction_engine: Engine,
) -> None:
    """A retry over unchanged bytes is not new evidence and must not accumulate."""
    with extraction_engine.begin() as connection:
        enrolled = _enrolled(connection)
        outcome = _outcome(enrolled)

        first = record_outcome(connection, enrollment_id=enrolled.enrollment_id, outcome=outcome)
        second = record_outcome(connection, enrollment_id=enrolled.enrollment_id, outcome=outcome)

        assert first == second
        stored = connection.execute(
            text(
                "SELECT status, text, trust_level FROM knowledge.extractions "
                "WHERE extraction_id = :id"
            ),
            {"id": first},
        ).one()
    assert stored[0] == "extracted"
    assert stored[1] == SYNTHETIC_MARKDOWN
    assert stored[2] == "source_bound_derived"


@pytest.mark.database
def test_an_unsupported_object_is_recorded_rather_than_skipped(
    extraction_engine: Engine,
) -> None:
    """A PDF leaves a row saying so. A skip would leave nothing at all."""
    with extraction_engine.begin() as connection:
        enrolled = _enrolled(connection)
        outcome = _outcome(enrolled, media_type="application/pdf", content=b"%PDF-1.7")

        extraction_id = record_outcome(
            connection, enrollment_id=enrolled.enrollment_id, outcome=outcome
        )
        stored = connection.execute(
            text(
                "SELECT status, text, media_type FROM knowledge.extractions "
                "WHERE extraction_id = :id"
            ),
            {"id": extraction_id},
        ).one()
    assert tuple(stored) == ("unsupported", None, "application/pdf")


@pytest.mark.database
def test_the_schema_refuses_extracted_text_filed_as_source_original(
    extraction_engine: Engine,
) -> None:
    """`INV-PKL-003` as a constraint, not only as a docstring."""
    with pytest.raises(IntegrityError), extraction_engine.begin() as connection:
        enrolled = _enrolled(connection)
        connection.execute(
            text(
                "INSERT INTO knowledge.extractions (extraction_id, enrollment_id, "
                " source_object_id, version_id, status, media_type, extractor, "
                " extractor_version, trust_level, text, observed_at, processed_at) "
                "VALUES (:kn, :enr, :obj, :ver, 'extracted', 'text/plain', 'my_pa.text', "
                " '1', 'source_original', 'synthetic', :at, :at)"
            ),
            {
                "kn": issue_identifier(IdKind.KNOWLEDGE),
                "enr": enrolled.enrollment_id,
                "obj": enrolled.source_object_id,
                "ver": enrolled.version_id,
                "at": OBSERVED_AT,
            },
        )


@pytest.mark.database
def test_the_schema_refuses_an_extracted_row_without_text(extraction_engine: Engine) -> None:
    """ "Extracted" and "empty" must not be the same row.

    Section 12 forbids reporting unsupported or malformed media as empty text,
    and the way that would happen in storage is a row marked extracted with a
    null body.
    """
    with pytest.raises(IntegrityError), extraction_engine.begin() as connection:
        enrolled = _enrolled(connection)
        connection.execute(
            text(
                "INSERT INTO knowledge.extractions (extraction_id, enrollment_id, "
                " source_object_id, version_id, status, media_type, extractor, "
                " extractor_version, observed_at, processed_at) "
                "VALUES (:kn, :enr, :obj, :ver, 'extracted', 'text/plain', 'my_pa.text', "
                " '1', :at, :at)"
            ),
            {
                "kn": issue_identifier(IdKind.KNOWLEDGE),
                "enr": enrolled.enrollment_id,
                "obj": enrolled.source_object_id,
                "ver": enrolled.version_id,
                "at": OBSERVED_AT,
            },
        )


@pytest.mark.database
def test_the_schema_refuses_a_decision_gated_media_type_stored_as_extracted(
    extraction_engine: Engine,
) -> None:
    """`P00-OD-003` is open, and the table is one of the places that holds."""
    with pytest.raises(IntegrityError), extraction_engine.begin() as connection:
        enrolled = _enrolled(connection)
        connection.execute(
            text(
                "INSERT INTO knowledge.extractions (extraction_id, enrollment_id, "
                " source_object_id, version_id, status, media_type, extractor, "
                " extractor_version, text, observed_at, processed_at) "
                "VALUES (:kn, :enr, :obj, :ver, 'extracted', 'application/pdf', "
                " 'my_pa.text', '1', 'synthetic', :at, :at)"
            ),
            {
                "kn": issue_identifier(IdKind.KNOWLEDGE),
                "enr": enrolled.enrollment_id,
                "obj": enrolled.source_object_id,
                "ver": enrolled.version_id,
                "at": OBSERVED_AT,
            },
        )


@pytest.mark.database
def test_a_quarantine_is_recorded_with_identifiers_and_a_reason(
    extraction_engine: Engine,
) -> None:
    with extraction_engine.begin() as connection:
        enrolled = _enrolled(connection)

        record = quarantine_object(
            connection,
            enrollment_id=enrolled.enrollment_id,
            source_object_id=enrolled.source_object_id,
            version_id=enrolled.version_id,
            reason=QuarantineReason.MEDIA_TYPE_CONFLICTS_WITH_SIGNATURE,
        )
        # Containment can fail before any version was proven.
        unversioned = quarantine_object(
            connection,
            enrollment_id=enrolled.enrollment_id,
            source_object_id=enrolled.source_object_id,
            version_id=None,
            reason=QuarantineReason.CONTAINMENT_UNPROVEN,
        )

        rows = connection.execute(
            text(
                "SELECT reason, review_state, version_id FROM knowledge.quarantine_records "
                "WHERE enrollment_id = :enr ORDER BY reason"
            ),
            {"enr": enrolled.enrollment_id},
        ).all()

    assert record.review_state is QuarantineReviewState.PENDING_REVIEW
    assert unversioned.version_id is None
    assert [(row[0], row[1], row[2]) for row in rows] == [
        ("containment_unproven", "pending_review", None),
        ("media_type_conflicts_with_signature", "pending_review", enrolled.version_id),
    ]


@pytest.mark.database
def test_a_limitation_accumulates_across_the_pages_of_one_pass(
    extraction_engine: Engine,
) -> None:
    """The finding this work package carries, as stored state.

    A listing that refuses two entries on one page and one on the next has
    omitted three objects from that pass, and the enrollment's disclosure has to
    say three rather than one.
    """
    with extraction_engine.begin() as connection:
        enrolled = _enrolled(connection)

        first = record_limitation(
            connection,
            enrollment_id=enrolled.enrollment_id,
            observed_at=OBSERVED_AT,
            reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
            affected_count=2,
        )
        second = record_limitation(
            connection,
            enrollment_id=enrolled.enrollment_id,
            observed_at=OBSERVED_AT,
            reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
            affected_count=1,
        )
        # A later pass is its own snapshot and does not edit the first.
        later = record_limitation(
            connection,
            enrollment_id=enrolled.enrollment_id,
            observed_at=OBSERVED_AT + timedelta(hours=1),
            reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
            affected_count=5,
        )

        rows = connection.execute(
            text("SELECT count(*) FROM knowledge.coverage_limitations WHERE enrollment_id = :enr"),
            {"enr": enrolled.enrollment_id},
        ).scalar_one()

    assert first.affected_count == 2
    assert second.affected_count == 3
    assert later.affected_count == 5
    assert rows == 2


@pytest.mark.database
def test_the_schema_refuses_a_limitation_that_affects_nothing(
    extraction_engine: Engine,
) -> None:
    """A zero would disclose "nothing was omitted", which is a claim, not a count."""
    with pytest.raises(IntegrityError), extraction_engine.begin() as connection:
        enrolled = _enrolled(connection)
        connection.execute(
            text(
                "INSERT INTO knowledge.coverage_limitations (limitation_id, enrollment_id, "
                " observed_at, reason, affected_count) "
                "VALUES (:kn, :enr, :at, 'objects_omitted_containment_unproven', 0)"
            ),
            {
                "kn": issue_identifier(IdKind.KNOWLEDGE),
                "enr": enrolled.enrollment_id,
                "at": OBSERVED_AT,
            },
        )


@pytest.mark.database
def test_coverage_reports_the_enrollment_the_snapshot_and_what_was_left_out(
    extraction_engine: Engine,
) -> None:
    """Coverage is partial when part of the scope did not become text.

    Two eligible objects, one extracted and one quarantined, with one further
    object omitted from the listing entirely: the state is
    `partially_processed`, and the omission is disclosed as a count with a reason
    and no identifier.
    """
    with extraction_engine.begin() as connection:
        enrolled = _enrolled(connection, also_named=1)
        second_object_id, second_version_id = enrolled.also_named[0]

        record_outcome(connection, enrollment_id=enrolled.enrollment_id, outcome=_outcome(enrolled))
        quarantine_object(
            connection,
            enrollment_id=enrolled.enrollment_id,
            source_object_id=second_object_id,
            version_id=second_version_id,
            reason=QuarantineReason.MALFORMED_INPUT,
        )
        record_limitation(
            connection,
            enrollment_id=enrolled.enrollment_id,
            observed_at=OBSERVED_AT,
            reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
            affected_count=1,
        )

        coverage = coverage_for(
            connection,
            enrolled.enrollment_id,
            observed_at=OBSERVED_AT,
            snapshot=SnapshotState.CURRENT,
        )

    assert coverage.enrollment_id == enrolled.enrollment_id
    assert coverage.observed_at == OBSERVED_AT
    assert (coverage.processed, coverage.quarantined, coverage.unsupported) == (1, 1, 0)
    assert coverage.state() is CoverageState.PARTIALLY_PROCESSED
    assert coverage.disclosed_limitations == ("objects_omitted_containment_unproven:1",)


@pytest.mark.database
def test_coverage_reports_only_the_limitations_of_the_snapshot_it_was_asked_for(
    extraction_engine: Engine,
) -> None:
    """A limitation belongs to the pass that observed it.

    Two passes over the same tree that each refused one entry omitted one object
    each, not two. Summing them would inflate the disclosure, and reporting the
    latest for every snapshot would misattribute it.
    """
    later = OBSERVED_AT + timedelta(hours=1)
    with extraction_engine.begin() as connection:
        enrolled = _enrolled(connection)
        record_outcome(connection, enrollment_id=enrolled.enrollment_id, outcome=_outcome(enrolled))
        for moment, affected in ((OBSERVED_AT, 1), (later, 4)):
            record_limitation(
                connection,
                enrollment_id=enrolled.enrollment_id,
                observed_at=moment,
                reason=LimitationReason.OBJECTS_OMITTED_CONTAINMENT_UNPROVEN,
                affected_count=affected,
            )

        first_pass = coverage_for(connection, enrolled.enrollment_id, observed_at=OBSERVED_AT)
        second_pass = coverage_for(connection, enrolled.enrollment_id, observed_at=later)

    assert first_pass.disclosed_limitations == ("objects_omitted_containment_unproven:1",)
    assert second_pass.disclosed_limitations == ("objects_omitted_containment_unproven:4",)
    # The outcome is the enrollment's, not the pass's, so both passes see it.
    assert first_pass.processed == second_pass.processed == 1
    assert first_pass.state() is CoverageState.PROCESSED


@pytest.mark.database
def test_the_denominator_is_the_enumerated_set_and_not_the_outcomes(
    extraction_engine: Engine,
) -> None:
    """`coverage_for` reads its own eligible total, and the number proves which.

    Until WP-4B3 the denominator was a caller's argument, and a caller with no
    enumeration passed `None` and got the outcomes back as their own total —
    which every whole-scope state then divided out of. Three objects are
    enumerated here and one reaches an outcome, so `eligible` is **3**: a number
    no arithmetic over the counts beside it produces, which is what makes this an
    assertion about `knowledge.enrollment_objects` rather than about the counts.

    Asserted twice over the same rows, before and after an outcome lands, because
    a denominator that moved with the numerator is exactly the defect: the total
    is the same 3 both times while `processed` goes from 0 to 1.
    """
    with extraction_engine.begin() as connection:
        enrolled = _enrolled(connection, also_named=2)

        empty = coverage_for(connection, enrolled.enrollment_id, observed_at=OBSERVED_AT)
        record_outcome(connection, enrollment_id=enrolled.enrollment_id, outcome=_outcome(enrolled))
        one = coverage_for(connection, enrolled.enrollment_id, observed_at=OBSERVED_AT)

    assert (empty.eligible, empty.processed) == (3, 0)
    assert empty.state() is CoverageState.ELIGIBLE
    assert (one.eligible, one.processed) == (3, 1)
    assert one.state() is CoverageState.PARTIALLY_PROCESSED


@pytest.mark.database
@pytest.mark.parametrize(
    ("queued", "unavailable"),
    [(4, 0), (0, 4), (2, 3)],
    ids=["queued", "unavailable", "both"],
)
def test_work_declared_beyond_the_enumerated_scope_is_refused(
    extraction_engine: Engine, queued: int, unavailable: int
) -> None:
    """The two terms a caller still contributes, and the failure they can cause.

    `queued` and `unavailable` are the caller's: work in flight and work it could
    not reach are facts about the job plane and the provider, not about the
    stored scope, so they stay parameters. What they can no longer do is enlarge
    the denominator to fit themselves. Declaring more outstanding work than the
    enumerated set holds is a claim that cannot be true, and `CoverageCounts`
    refuses it rather than reporting a coverage figure derived from it.

    Parametrized over each term separately as well as together, because one term
    present and the other missing is exactly the shape that passes a test written
    only for the sum.

    The control is in the same test: the same call with the declaration inside
    the scope returns counts, so the refusal is about the arithmetic and not
    about the fixture.
    """
    with extraction_engine.begin() as connection:
        enrolled = _enrolled(connection, also_named=2)
        record_outcome(connection, enrollment_id=enrolled.enrollment_id, outcome=_outcome(enrolled))

        honest = coverage_for(
            connection, enrolled.enrollment_id, observed_at=OBSERVED_AT, queued=1, unavailable=1
        )
        with pytest.raises(ValueError, match="cannot exceed the eligible count"):
            coverage_for(
                connection,
                enrolled.enrollment_id,
                observed_at=OBSERVED_AT,
                queued=queued,
                unavailable=unavailable,
            )

    assert honest.eligible == 3
    assert honest.accounted + honest.queued == 3


@pytest.mark.database
def test_pending_objects_excludes_both_kinds_of_outcome(extraction_engine: Engine) -> None:
    """The executor's work list, and the one idempotency that is a predicate.

    Three objects are enumerated. One is extracted, one is quarantined, and one
    has reached nothing — so exactly one is pending, and the two exclusions are
    separated by construction rather than asserted together. Dropping the
    `extractions` exclusion makes the answer two; dropping the
    `quarantine_records` exclusion makes it two as well, and that is the one that
    matters: `quarantine_records` is append-only by design, so a second pass over
    a quarantined object writes a **second** quarantine. There is no constraint
    to lean on and this predicate is the whole of the protection.

    Asserted as an exact tuple rather than by length, so a right count of the
    wrong objects fails, and the empty case sits beside it as the second
    assertion: once the last object reaches an outcome the list is empty, which
    is what makes the non-empty answer above mean "this one and no other" rather
    than "the query returned something".
    """
    with extraction_engine.begin() as connection:
        enrolled = _enrolled(connection, also_named=2)
        quarantined_id, quarantined_version = enrolled.also_named[0]
        untouched_id, untouched_version = enrolled.also_named[1]

        record_outcome(connection, enrollment_id=enrolled.enrollment_id, outcome=_outcome(enrolled))
        quarantine_object(
            connection,
            enrollment_id=enrolled.enrollment_id,
            source_object_id=quarantined_id,
            version_id=quarantined_version,
            reason=QuarantineReason.MALFORMED_INPUT,
        )
        pending = pending_objects(connection, enrolled.enrollment_id)

        record_outcome(
            connection,
            enrollment_id=enrolled.enrollment_id,
            outcome=_outcome(enrolled, source_object_id=untouched_id, version_id=untouched_version),
        )
        finished = pending_objects(connection, enrolled.enrollment_id)

    assert pending == (untouched_id,)
    assert finished == ()


@pytest.mark.database
def test_pending_objects_offers_only_what_the_enumeration_recorded(
    extraction_engine: Engine,
) -> None:
    """A work list, not a diff: an object nothing enumerated is not work.

    An object of the enrollment's own source that the enumeration did not record
    is not offered, because `authorized_object` would refuse the outcome the
    executor then tried to write — and a work list that handed out objects the
    writer refuses is the disagreement `docs/specs` section 12 calls a broken
    store, arriving one layer earlier.

    The control is in the same test: the enumerated object *is* offered, so the
    absence of the other one is about membership rather than about the read
    returning nothing.
    """
    with extraction_engine.begin() as connection:
        rooted = _enrolled_under_a_root(connection)
        outside_id, _outside_version = rooted.also_named[0]
        pending = pending_objects(connection, rooted.enrollment_id)

    assert pending == (rooted.source_object_id,)
    assert outside_id not in pending


@pytest.mark.database
def test_an_object_of_the_same_source_outside_the_enumerated_set_is_not_authorized(
    extraction_engine: Engine,
) -> None:
    """Containment, for a **root** selector, which is where it used to be absent.

    `authorized_object` restricted a root-selector enrollment to its `source_id`
    and no further, because nothing persisted the objects under a root: a sibling
    of the root was writable under the enrollment, counted by `coverage_for`, and
    returned by a search. `knowledge.enrollment_objects` is the fact that closes
    it, and the membership test is now identical for both selectors.

    Three assertions, because the boundary has three faces and a fix applied to
    one is this campaign's recurring defect: the write path refuses, the
    quarantine path refuses, and the count excludes. The control is the enrolled
    object in the same test, which passes all three — a refusal that refused
    everything would prove nothing.
    """
    with extraction_engine.begin() as connection:
        rooted = _enrolled_under_a_root(connection)

        # The control: an object the enumeration recorded is writable and counted.
        record_outcome(
            connection,
            enrollment_id=rooted.enrollment_id,
            outcome=_outcome(rooted),
        )
        counted = coverage_for(connection, rooted.enrollment_id, observed_at=OBSERVED_AT)
        assert counted.eligible == 1
        assert counted.processed == 1

        outside_id, outside_version = rooted.also_named[0]
        with pytest.raises(UnauthorizedObjectError):
            record_outcome(
                connection,
                enrollment_id=rooted.enrollment_id,
                outcome=_outcome(rooted, source_object_id=outside_id, version_id=outside_version),
            )
        with pytest.raises(UnauthorizedObjectError):
            quarantine_object(
                connection,
                enrollment_id=rooted.enrollment_id,
                source_object_id=outside_id,
                version_id=outside_version,
                reason=QuarantineReason.MALFORMED_INPUT,
            )

    # The denominator did not grow to admit the object the boundary refused.
    assert counted.eligible == 1


@pytest.mark.database
def test_an_outcome_that_cannot_be_attributed_to_its_version_is_quarantined_not_stored(
    extraction_engine: Engine,
) -> None:
    """The last trigger of section 12, end to end.

    The bytes came back bound to a different version than the one observed, so
    there is no version the text could honestly be filed under. `record_outcome`
    routes it to the quarantine ledger, and nothing lands in `extractions`.
    """
    with extraction_engine.begin() as connection:
        enrolled = _enrolled(connection)
        drifted = observe_object(
            connection,
            source_id=enrolled.source_id,
            native_locator=NATIVE_LOCATOR,
            kind=ObjectKind.FILE,
            fingerprint="fingerprint-changed",
            modified_at=OBSERVED_AT,
            media_type="text/markdown",
            size_bytes=9,
        )
        outcome = _outcome(enrolled, content_version_id=drifted.version_id)
        assert outcome.status is ExtractionStatus.QUARANTINED

        record_outcome(connection, enrollment_id=enrolled.enrollment_id, outcome=outcome)

        extracted = connection.execute(
            text("SELECT count(*) FROM knowledge.extractions WHERE enrollment_id = :enr"),
            {"enr": enrolled.enrollment_id},
        ).scalar_one()
        reasons = (
            connection.execute(
                text("SELECT reason FROM knowledge.quarantine_records WHERE enrollment_id = :enr"),
                {"enr": enrolled.enrollment_id},
            )
            .scalars()
            .all()
        )

    assert extracted == 0
    assert reasons == ["output_not_attributable_to_version"]
