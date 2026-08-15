"""The audit revision round-trips, and the table has nowhere to put a payload.

Three claims, and they are separated because they fail for different reasons.

**The revision is reversible.** Empty to head and head to empty against a
disposable database, which is what `AGENTS.md` section 6 requires of a schema
change, plus one step back to the revision below so that a downgrade of *this*
revision is shown to leave the eight tables it did not create alone.

**The columns are closed.** Every column of `audit_events` is restated here, so
adding one has to be acknowledged in this list. That is the payload claim in the
same form `tests/schema/test_extraction_schema_migration.py` states it for
`quarantine_records`: an audit event records that something was decided and how,
and there must be nowhere in the row for what it was about.

**The constraints are the redaction.** `AuditEvent` already has no field a
payload fits in, but a table is written to by more than one thing over its life —
a later revision, a hand-run statement, a repair script. So the shapes are
asserted against the *server*: a path, a host, a database URL, a credential, and
a query string are each offered to every column that is not a closed enumeration,
and each is refused. That is the difference between redaction as a property of
the schema and redaction as a property of the current writer.

The database is disposable, created and dropped by its fixture, and never the
configured one: `downgrade base` deletes schemas, and pointing that at the
canonical `my_pa` database would destroy the migrated corpus. Every value here is
synthetic; no path exists and none is opened.
"""

from __future__ import annotations

import io
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
from my_pa.domain.common import identifiers as identifier_module
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import _IDENTIFIER_SUFFIX

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "knowledge"

AUDIT_REVISION = "9c6b4a18ed72"
EXTRACTION_REVISION = "8b3f5c17d904"

#: Fixed name so a run interrupted before teardown is cleaned up by the next one.
#: Distinct from every other suite's disposable database, so they cannot collide.
DISPOSABLE_DATABASE = "my_pa_audit_test"

#: Every column of `audit_events`, restated. This is the payload claim: a column
#: added here has to be acknowledged in this list, which is the point.
EXPECTED_AUDIT_COLUMNS: Final[frozenset[str]] = frozenset(
    {
        "audit_id",
        "correlation_id",
        "principal_id",
        "capability",
        "purpose",
        "outcome",
        "policy_version",
        "denial_reason",
        "scope_source_id_count",
        "recorded_at",
    }
)

EXPECTED_AUDIT_CHECKS: Final[frozenset[str]] = frozenset(
    {
        "audit_id_is_an_opaque_identifier",
        "correlation_id_is_an_opaque_identifier",
        "principal_id_is_an_opaque_identifier",
        "capability_is_known",
        "purpose_is_known",
        "audit_outcome_is_known",
        "denial_reason_is_known",
        "audit_policy_version_is_a_known_shape",
        "a_denial_records_its_reason_and_nothing_else_does",
        "audit_counts_are_not_negative",
    }
)

#: The tables the revisions *above* this one create, which a downgrade to this
#: revision therefore also removes. Stated explicitly rather than derived, in the
#: style this suite already uses for the same claim: an extra table left behind
#: by any of those downgrades is exactly what these equalities exist to see, and
#: a set computed from the chain would absorb one.
TABLES_ABOVE: Final[frozenset[str]] = frozenset(
    {
        "captures",
        "capture_versions",
        "capture_receipts",
        "capture_submissions",
        "capture_jobs",
        "capture_processing_text",
        "capture_stage_results",
        "capture_spans",
        "capture_proposals",
        "capture_proposal_spans",
        "capture_classifications",
        "capture_entity_mentions",
        "capture_review_cases",
        "capture_review_decisions",
        "capture_assertions",
        "capture_assertion_spans",
        "capture_promotion_receipts",
        "capture_context_links",
        "capture_conversations",
        "capture_clients",
        "commitments",
        "decisions",
        "tasks",
        "continuity_lifecycle_events",
        "situations",
        "frames",
        "traces",
        "projects",
        "project_situations",
        "relationship_events",
        "pulse_items",
        "goodnotes_pages",
        "goodnotes_page_versions",
        "goodnotes_region_proposals",
        "goodnotes_review_decisions",
        "goodnotes_reconciliation_receipts",
        "worker_heartbeats",
        # WP-27's managed-document plane.
        "managed_documents",
        "managed_document_versions",
        "managed_document_submissions",
        "managed_document_receipts",
        "managed_document_lifecycle_events",
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
        "native_admission_authorities",
        "native_preflight_observations",
        "native_source_review_routes",
        "native_apple_bridge_credentials",
        "native_apple_read_grants",
        "continuity_authoring_submissions",
        # Context-prepare run tables (`9b2d5f8c3e01`) and preference tables
        # (`c6f1a8d3e204`).
        "context_runs",
        "context_run_items",
        "context_preference_events",
        "context_preference_current",
    }
)

WHEN = datetime(2026, 8, 2, 12, 0, tzinfo=UTC)

#: One well-formed row, as keyword parameters. Each refusal below is this row
#: with exactly one field replaced, so a test that fails proves the replacement
#: was refused rather than that the row was malformed to begin with.
GOOD_ROW: Final[dict[str, object]] = {
    "audit_id": "audit_0123456789abcdef",
    "correlation_id": "corr_0123456789abcdef",
    "principal_id": "prn_0123456789abcdef",
    "capability": "sources.list",
    "purpose": "source_inspection",
    "outcome": "allowed",
    "policy_version": "policy-v1",
    "denial_reason": None,
    "scope_source_id_count": 0,
    "recorded_at": WHEN,
}

_INSERT = text(
    "INSERT INTO knowledge.audit_events (audit_id, correlation_id, principal_id, "
    " capability, purpose, outcome, policy_version, denial_reason, "
    " scope_source_id_count, recorded_at) "
    "VALUES (:audit_id, :correlation_id, :principal_id, :capability, :purpose, "
    " :outcome, :policy_version, :denial_reason, :scope_source_id_count, :recorded_at)"
)

#: The five things `AGENTS.md` section 5 and `module-boundaries.md` section 5.6
#: name, as values somebody might try to store. Synthetic: no such path, host,
#: or account exists.
FORBIDDEN_VALUES: Final[tuple[tuple[str, str], ...]] = (
    ("path", "/synthetic/corpus/quarterly-notes.md"),
    ("host", "nas.invalid"),
    ("database_url", "postgresql+psycopg://someone@db.invalid:5432/my_pa"),
    ("credential", "hunter2-not-a-real-secret"),
    ("query", "quarterly revenue review"),
)

#: The columns that are not constrained to a closed enumerated set. These are the
#: ones a free value could otherwise be stored in, so these are the ones the
#: shape constraints have to hold.
UNENUMERATED_COLUMNS: Final[tuple[str, ...]] = (
    "audit_id",
    "correlation_id",
    "principal_id",
    "policy_version",
)


def _config(output_buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=output_buffer)


def test_the_audit_revision_is_in_the_chain_on_the_extraction_revision() -> None:
    """Guards the rest of this module: an absent revision would create nothing.

    Deliberately not "is the head", for the reason
    `test_extraction_schema_migration.py` gives: that property is true only until
    the next revision is written, and asserting it makes every later work package
    edit this file.
    """
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert AUDIT_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(AUDIT_REVISION).down_revision == EXTRACTION_REVISION


def test_the_restated_identifier_suffix_equals_the_domain_rule() -> None:
    """`tables.py` restates a private domain pattern; this is what pins it.

    The table constrains an identifier column with a POSIX regular expression
    written out in `tables.py`, because the domain's own pattern is private to
    `domain.common.identifiers`. A restatement that drifted would leave the
    server enforcing a different rule from the value object, and the direction
    that matters is the loose one: a server rule wider than the domain's would
    admit exactly the values the constraint exists to refuse.
    """
    domain_pattern = identifier_module._SUFFIX_PATTERN.pattern
    assert domain_pattern == rf"\A{_IDENTIFIER_SUFFIX}\Z", (
        "the suffix rule in tables.py no longer matches the one domain.common.identifiers enforces"
    )


def test_the_offline_ddl_emits_the_audit_table_and_its_constraints(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`--sql` has to work with no server: it is how the DDL gets reviewed."""
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", "postgresql+psycopg://nobody@nowhere/nothing")
    buffer = io.StringIO()
    command.upgrade(
        _config(output_buffer=buffer), f"{EXTRACTION_REVISION}:{AUDIT_REVISION}", sql=True
    )
    emitted = buffer.getvalue()

    assert f"CREATE TABLE {SCHEMA}.audit_events" in emitted
    for constraint in EXPECTED_AUDIT_CHECKS:
        assert constraint in emitted, f"{constraint} is not in the emitted DDL"
    assert "FOREIGN KEY" not in emitted, (
        "audit_events declared a foreign key. It commits before the work it "
        "describes, so a reference to that work would make its durability "
        "depend on the durability of the thing it exists to outlive."
    )


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
def audit_engine(disposable_database: str) -> Iterator[Engine]:
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
                {"schema": SCHEMA},
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
                {"schema": SCHEMA, "table": table},
            ).scalars()
        )


def _checks(engine: Engine) -> set[str]:
    with engine.connect() as connection:
        return set(
            connection.execute(
                text(
                    "SELECT con.conname FROM pg_constraint con "
                    "JOIN pg_namespace n ON n.oid = con.connamespace "
                    "WHERE n.nspname = :schema AND con.contype = 'c'"
                ),
                {"schema": SCHEMA},
            ).scalars()
        )


@pytest.mark.database
def test_the_audit_revision_runs_empty_to_head_and_head_to_empty(
    disposable_database: str,
) -> None:
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        assert "audit_events" in _tables(engine)
        assert _checks(engine) >= EXPECTED_AUDIT_CHECKS

        command.downgrade(_config(), "base")

        with engine.connect() as connection:
            remaining = set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars())
        assert SCHEMA not in remaining
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_this_revision_leaves_the_other_knowledge_tables_alone(
    disposable_database: str,
) -> None:
    """This revision added one table to a schema it did not create.

    Its downgrade therefore removes tables and not the schema, and not the eight
    rows of evidence the revisions below the extraction revision own.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        before = _tables(engine)

        command.downgrade(_config(), EXTRACTION_REVISION)

        # Downgrading to the extraction revision unwinds every revision above it
        # and drops every table they added. Stated as an equality against an
        # explicit set rather than a subset: an extra table left behind by any of
        # those downgrades is exactly what this test exists to see.
        assert _tables(engine) == before - {
            "audit_events",
            "enrollment_objects",
            *TABLES_ABOVE,
        }
        assert len(_tables(engine)) == 8

        command.upgrade(_config(), "head")
        assert _tables(engine) == before

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_an_audit_row_has_nowhere_to_put_a_payload(audit_engine: Engine) -> None:
    """The structural half of section 11, asserted against the server."""
    assert _columns(audit_engine, "audit_events") == EXPECTED_AUDIT_COLUMNS


@pytest.mark.database
def test_the_reference_row_is_accepted(audit_engine: Engine) -> None:
    """Positive control. Without it every refusal below could be the row itself."""
    with audit_engine.begin() as connection:
        connection.execute(_INSERT, GOOD_ROW)
        stored = connection.execute(
            text("SELECT count(*) FROM knowledge.audit_events")
        ).scalar_one()
    assert stored == 1


@pytest.mark.database
@pytest.mark.parametrize("column", UNENUMERATED_COLUMNS)
@pytest.mark.parametrize(("kind", "value"), FORBIDDEN_VALUES, ids=lambda v: str(v)[:24])
def test_no_unenumerated_column_accepts_a_path_host_url_credential_or_query(
    audit_engine: Engine, column: str, kind: str, value: str
) -> None:
    """`AGENTS.md` section 5, as a constraint rather than as a convention.

    Every column that is not a closed enumeration is offered each of the five
    forbidden value classes, and each is refused by the server. This is what makes
    the redaction a property of the schema: `AuditEvent` cannot carry one of these
    today, and this is what stops a later writer from storing one anyway.
    """
    row = {**GOOD_ROW, column: value}
    with pytest.raises(IntegrityError), audit_engine.begin() as connection:
        connection.execute(_INSERT, row)


@pytest.mark.database
@pytest.mark.parametrize(
    ("column", "value"),
    [
        ("capability", "sources.delete"),
        ("purpose", "whatever_the_caller_said"),
        ("outcome", "probably_fine"),
        ("denial_reason", "because_i_said_so"),
    ],
)
def test_an_enumerated_column_refuses_a_value_outside_its_closed_set(
    audit_engine: Engine, column: str, value: str
) -> None:
    row = {**GOOD_ROW, column: value}
    if column == "denial_reason":
        row["outcome"] = "denied"
    with pytest.raises(IntegrityError), audit_engine.begin() as connection:
        connection.execute(_INSERT, row)


@pytest.mark.database
@pytest.mark.parametrize(
    ("outcome", "reason"),
    [("denied", None), ("allowed", "scope_not_authorized"), ("failed", "scope_not_authorized")],
    ids=["denial_without_a_reason", "allowed_with_a_reason", "failed_with_a_reason"],
)
def test_only_a_denial_records_a_denial_reason(
    audit_engine: Engine, outcome: str, reason: str | None
) -> None:
    """The rule `AuditEvent.__post_init__` enforces, restated where a hand-run
    statement also meets it.

    A denial with no reason records that authority was insufficient without
    recording why; a non-denial with one attributes a refusal to a request that
    was not refused.
    """
    row = {**GOOD_ROW, "outcome": outcome, "denial_reason": reason}
    with pytest.raises(IntegrityError), audit_engine.begin() as connection:
        connection.execute(_INSERT, row)


@pytest.mark.database
def test_a_negative_count_is_refused(audit_engine: Engine) -> None:
    """`scope_source_id_count` is the only count stored, because it is the only
    one anything writes. `AuditEvent` also carries `item_count` and
    `duration_ms`; nothing sets either, so a column for them would be a
    permanently zero value indistinguishable from a measured one.
    """
    with pytest.raises(IntegrityError), audit_engine.begin() as connection:
        connection.execute(_INSERT, {**GOOD_ROW, "scope_source_id_count": -1})


@pytest.mark.database
def test_an_audit_id_is_recorded_once(audit_engine: Engine) -> None:
    """Append-only, and the primary key is what makes a re-record a refusal.

    An audit event is issued one identifier by the layer that builds it, so a
    second row under the same identifier would be one decision recorded twice.
    """
    with pytest.raises(IntegrityError), audit_engine.begin() as connection:
        connection.execute(_INSERT, GOOD_ROW)
        connection.execute(_INSERT, GOOD_ROW)


def test_the_forbidden_values_are_actually_forbidden_shapes() -> None:
    """Guard the fixtures: a "path" that happened to be a valid identifier
    suffix would make every refusal above pass for the wrong reason.

    Each planted value has to violate the shape, so the refusal is evidence about
    the constraint rather than about the fixture.
    """
    shape = re.compile(rf"\A(?:audit|corr|prn)_{_IDENTIFIER_SUFFIX}\Z")
    for kind, value in FORBIDDEN_VALUES:
        assert not shape.fullmatch(value), f"the planted {kind} is a well-formed identifier"
        assert not re.fullmatch(r"policy-v[0-9]{1,4}", value), (
            f"the planted {kind} is a well-formed policy version"
        )


def test_every_forbidden_class_named_by_policy_is_planted() -> None:
    """The five classes `AGENTS.md` section 5 names, each present as a fixture.

    Without this the parametrisation could quietly shrink to one value and the
    suite would still be green.
    """
    assert {kind for kind, _ in FORBIDDEN_VALUES} == {
        "path",
        "host",
        "database_url",
        "credential",
        "query",
    }
    assert len(UNENUMERATED_COLUMNS) == 4
