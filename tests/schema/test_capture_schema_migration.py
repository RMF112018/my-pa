"""The capture revision round-trips, and the frozen vocabulary stays frozen.

This module is the guard on the mechanism `D-69` chose, and it exists because
that mechanism deliberately broke something. Until WP-6, `audit_events`'
`capability_is_known` and `purpose_is_known` were *derived* from the domain
enums, so the database and the domain could not drift — at the cost of an
already-merged revision emitting different DDL every time a member was added,
which is the `D-48` hazard in a new shape and was measured rather than argued.
The derivation is now frozen inside `9c6b4a18ed72` and widened forward by an
explicit `ALTER` here. What that costs is the coupling, and `_IDENTIFIER_SUFFIX` in `tables.py` is
the precedent for what replaces it: **a restatement is acceptable when it is
a checked claim rather than a copy that can drift.** These are the checks.

Six claims, separated because they fail for different reasons.

**The revision is in the chain.** Deliberately not "is the head", for the reason
`test_the_audit_revision_is_in_the_chain_on_the_extraction_revision` in
`test_audit_schema_migration.py` records: that property is true only until the
next revision is written, and asserting it makes every later work package edit
this file.

**Empty to head and head to empty.** What `AGENTS.md` section 6 requires of a
schema change, plus the two things this revision adds that a table drop does not
take with it — a trigger function in the `knowledge` schema, and two constraints
on a table it did not create. `7e5a1fb93d62` drops the schema with `RESTRICT`,
so a function left behind fails `downgrade base` at a revision that has no idea
this one exists.

**Stopping at `9c6b4a18ed72` emits the frozen eight and seven.** This is the
whole argument for editing a merged migration: after the edit that revision
emits what it emitted on the day it merged, with twelve capabilities and nine
purposes now declared in the domain. If this reddens, the freeze has been undone
and every database at that revision has stopped agreeing with what the chain
says it should hold.

**Head admits exactly the domain's vocabulary.** The checked claim that replaces
the coupling — and it covers **all eleven** enum-backed closed sets the chain
emits, not the two WP-6 widened. Checking `capability` and `purpose` alone, which
is where the first pass left it, replaced the coupling on two constraints and
replaced it with nothing on the other nine: `audit_outcome_is_known` and
`denial_reason_is_known` sit on the same table in the same revision, and the
independent reviewer measured a planted `DenialReason` member changing what that
already-merged revision emits with nothing reddening anywhere. A member added
without an `ALTER` — the failure `D-69` exists to prevent, and the one no other
test could catch because every test builds its database from scratch — now fails
here for any of them.

**The two nullable error-code sets.** `jobs.last_error_code` and
`capture_jobs.last_error_code` are `... IS NULL OR ... IN (…)`, so they need
their own read; they track the eleven public `v1` codes.

The database is disposable, created and dropped by its fixture, and never the
configured one: `downgrade base` deletes schemas, and pointing that at the
canonical `my_pa` database would destroy the migrated corpus. Every value here is
synthetic; no path exists and none is opened.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from pathlib import Path
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, text
from sqlalchemy.engine import make_url

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.audit.events import AuditOutcome
from my_pa.domain.capture.submission import (
    AdmissionResult,
    CaptureMethod,
    CaptureTransport,
    TrustState,
)
from my_pa.domain.capture.version import ProcessingPolicy
from my_pa.domain.common.classification import Classification
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import DenialReason
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.tables import JobState

ROOT = Path(__file__).resolve().parents[2]

SCHEMA = "knowledge"

CAPTURE_REVISION = "1a4c9e77b2d5"
ENROLLMENT_OBJECTS_REVISION = "af3d35efb9c0"
AUDIT_REVISION = "9c6b4a18ed72"

#: Fixed name so a run interrupted before teardown is cleaned up by the next
#: one. Distinct from every other suite's disposable database, so they cannot
#: collide — the database tier runs serially and these names are server-global.
DISPOSABLE_DATABASE = "my_pa_capture_test"

#: The five tables this revision creates, restated. A table added to the
#: revision has to be acknowledged here, which is the point.
CAPTURE_TABLES: Final[frozenset[str]] = frozenset(
    {
        "captures",
        "capture_versions",
        "capture_receipts",
        "capture_submissions",
        "capture_jobs",
    }
)

#: The vocabulary `9c6b4a18ed72` emitted on the day it merged. Written out here
#: as well as in the revision, and that duplication is deliberate: a test that
#: imported the revision's own literal would pass however that literal changed,
#: which is the one thing this module exists to notice.
FROZEN_CAPABILITIES: Final[frozenset[str]] = frozenset(
    {
        "capabilities.get",
        "knowledge.read",
        "knowledge.search",
        "sources.enroll",
        "sources.fetch",
        "sources.list",
        "sources.metadata",
        "sources.status",
    }
)

FROZEN_PURPOSES: Final[frozenset[str]] = frozenset(
    {
        "bounded_enrollment",
        "content_extraction",
        "knowledge_read",
        "knowledge_search",
        "security_validation",
        "source_inspection",
        "status_observation",
    }
)

#: The other two closed sets `9c6b4a18ed72` emits. Unchanged since it merged, so
#: these are equal to the live enums today — which is exactly why they were the
#: two the first pass at this freeze left derived, and why the strict-subset
#: guard below cannot be extended to them. They are held by
#: `test_no_revision_derives_a_closed_set_from_an_enum.py`, which reads the
#: revision's frozen declaration structurally rather than by value.
FROZEN_AUDIT_OUTCOMES: Final[frozenset[str]] = frozenset({"allowed", "denied", "failed"})

FROZEN_DENIAL_REASONS: Final[frozenset[str]] = frozenset(
    {
        "destination_not_eligible",
        "operator_required",
        "principal_may_not_hold_authority",
        "principal_not_authenticated",
        "purpose_not_permitted_for_capability",
        "scope_not_authorized",
    }
)

#: The function and the trigger that make `capture_versions` append only.
IMMUTABILITY_FUNCTION = "capture_versions_stay_as_written"
IMMUTABILITY_TRIGGER = "capture_versions_are_append_only"

_CONSTRAINT = text(
    "SELECT pg_get_constraintdef(con.oid) FROM pg_constraint con "
    "JOIN pg_class rel ON rel.oid = con.conrelid "
    "JOIN pg_namespace n ON n.oid = rel.relnamespace "
    "WHERE n.nspname = :schema AND rel.relname = :table AND con.conname = :name"
)

#: Every closed-set constraint this chain emits from a declaration that a domain
#: enum also feeds, with the enum head must agree with. Checking two of these —
#: which is where the first pass left it — replaced the enum-to-CHECK coupling on
#: `capability` and `purpose` and replaced it with *nothing* on the other ten.
#: `audit_outcome_is_known` and `denial_reason_is_known` were the two the
#: independent reviewer measured as still live; the eight on the capture tables
#: are this package's own, and are frozen in `1a4c9e77b2d5` for the same reason.
#:
#: The `last_error_code` constraints are excluded deliberately: their column is
#: nullable, so `_admitted` cannot read a bare value set out of
#: `last_error_code IS NULL OR last_error_code IN (…)` without also parsing the
#: null branch. `test_the_public_error_codes_are_admitted_at_head` below covers
#: them by asking the server directly instead.
CHECKED_VOCABULARY: Final[tuple[tuple[str, str, frozenset[str]], ...]] = (
    ("audit_events", "capability_is_known", frozenset(c.value for c in Capability)),
    ("audit_events", "purpose_is_known", frozenset(p.value for p in Purpose)),
    ("audit_events", "audit_outcome_is_known", frozenset(o.value for o in AuditOutcome)),
    ("audit_events", "denial_reason_is_known", frozenset(d.value for d in DenialReason)),
    (
        "capture_versions",
        "capture_classification_is_known",
        frozenset(c.value for c in Classification),
    ),
    (
        "capture_versions",
        "processing_policy_is_known",
        frozenset(p.value for p in ProcessingPolicy),
    ),
    (
        "capture_submissions",
        "capture_transport_is_known",
        frozenset(t.value for t in CaptureTransport),
    ),
    ("capture_submissions", "capture_method_is_known", frozenset(m.value for m in CaptureMethod)),
    ("capture_submissions", "capture_trust_state_is_known", frozenset(t.value for t in TrustState)),
    (
        "capture_submissions",
        "admission_result_is_known",
        frozenset(a.value for a in AdmissionResult),
    ),
    ("capture_jobs", "capture_job_state_is_known", frozenset(s.value for s in JobState)),
)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def test_the_capture_revision_is_in_the_chain_on_the_enrollment_objects_revision() -> None:
    """Guards the rest of this module: an absent revision would create nothing."""
    script = ScriptDirectory.from_config(_config())
    assert len(list(script.get_heads())) == 1
    assert CAPTURE_REVISION in {entry.revision for entry in script.walk_revisions()}
    assert script.get_revision(CAPTURE_REVISION).down_revision == ENROLLMENT_OBJECTS_REVISION


def test_the_frozen_vocabulary_is_a_strict_subset_of_the_domains() -> None:
    """Guard the two literals above: equal sets would make the stop-at test vacuous.

    If the domain ever shrank back to the historical eight, "the revision emits
    the frozen eight" and "the revision emits whatever the enum says" would be
    the same assertion, and the test below would pass on a re-coupled revision.
    This is what says the two are distinguishable at all.
    """
    assert {c.value for c in Capability} > FROZEN_CAPABILITIES
    assert {p.value for p in Purpose} > FROZEN_PURPOSES
    assert len(FROZEN_CAPABILITIES) == 8
    assert len(FROZEN_PURPOSES) == 7


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


def _admitted(engine: Engine, constraint: str, table: str = "audit_events") -> frozenset[str]:
    """The values one closed-set constraint admits.

    Read out of the *server* rather than out of the revision, and parsed from
    `pg_get_constraintdef`, so this is what a row would actually be checked
    against rather than what the file that wrote it says.
    """
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


@pytest.mark.database
def test_stopping_at_the_audit_revision_emits_the_frozen_vocabulary(
    disposable_database: str,
) -> None:
    """The whole argument for editing a merged migration, as an assertion.

    A database taken to `9c6b4a18ed72` and no further receives the eight
    capabilities and seven purposes that revision emitted when it merged — not
    the twelve and nine the domain declares today. Reddening here means an
    already-merged revision has started denoting a second schema, which is what
    `D-48` refuses and what the standing rule in that file forbids.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), AUDIT_REVISION)

        assert _admitted(engine, "capability_is_known") == FROZEN_CAPABILITIES
        assert _admitted(engine, "purpose_is_known") == FROZEN_PURPOSES
        # The other two closed sets on the same table, in the same revision.
        # These are the ones the independent reviewer measured as still derived
        # after the first pass at this freeze: a planted `DenialReason` member
        # changed what an already-merged revision emitted, and nothing reddened.
        # They are frozen literals now, and this is what says so against a
        # server rather than against the file that wrote them.
        assert _admitted(engine, "audit_outcome_is_known") == FROZEN_AUDIT_OUTCOMES
        assert _admitted(engine, "denial_reason_is_known") == FROZEN_DENIAL_REASONS
        # The control: the capture tables do not exist yet, so the four sets
        # above are the state of a database that stopped short of this package
        # rather than one that ran it and was then narrowed.
        assert not CAPTURE_TABLES & _tables(engine)

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_head_admits_exactly_the_vocabulary_the_domain_declares(
    disposable_database: str,
) -> None:
    """The checked claim that replaces the coupling `D-69` broke.

    Equality in both directions and against both enums. A capability added to
    the domain without an `ALTER` fails the first half; an `ALTER` that widened
    the constraint past the domain fails the second. No existing test could
    catch the first, because every test builds its database from scratch and a
    fresh database used to receive whatever the enum said.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        for table, constraint, expected in CHECKED_VOCABULARY:
            assert _admitted(engine, constraint, table) == expected, f"{table}.{constraint}"
        # The control, in the same test: the four `audit_events` sets are not all
        # equal to each other, so eleven passing equalities cannot be one
        # equality repeated eleven times against a `_admitted` that returned the
        # same thing every time.
        assert len({values for _, _, values in CHECKED_VOCABULARY}) >= 8

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_public_error_codes_are_admitted_at_head(
    disposable_database: str,
) -> None:
    """The two nullable closed sets, which `_admitted` cannot read plainly.

    `jobs.last_error_code` and `capture_jobs.last_error_code` are constrained by
    `... IS NULL OR ... IN (…)`, and both track `ErrorCode`. The capture one is
    frozen in `1a4c9e77b2d5`; the `jobs` one is `D-81` allowlist row 5, still
    derived and deliberately not edited here. Both must admit the eleven public
    codes at head, and this asserts it against the server so that a twelfth code
    added without a migration is caught rather than assumed.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        codes = {code.value for code in ErrorCode}
        assert len(codes) == 11
        assert _admitted(engine, "last_error_code_is_a_public_error_code", "jobs") == codes
        assert (
            _admitted(engine, "capture_job_error_code_is_a_public_error_code", "capture_jobs")
            == codes
        )

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()


@pytest.mark.database
def test_the_capture_revision_runs_empty_to_head_and_head_to_empty(
    disposable_database: str,
) -> None:
    """Reversible, and reversible including what a table drop does not take.

    The trigger goes with its table. The trigger *function* does not, and
    `7e5a1fb93d62` drops the schema with `RESTRICT`, so a function left behind
    makes `downgrade base` fail at a revision written before this one existed.
    The residue check is therefore on routines and schemas, not only on tables.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")

        assert _tables(engine) >= CAPTURE_TABLES
        with engine.connect() as connection:
            triggers = set(
                connection.execute(
                    text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
                ).scalars()
            )
            routines = set(
                connection.execute(
                    text(
                        "SELECT p.proname FROM pg_proc p JOIN pg_namespace n "
                        "ON n.oid = p.pronamespace WHERE n.nspname = :schema"
                    ),
                    {"schema": SCHEMA},
                ).scalars()
            )
        assert IMMUTABILITY_TRIGGER in triggers
        assert IMMUTABILITY_FUNCTION in routines

        command.downgrade(_config(), "base")

        with engine.connect() as connection:
            remaining = set(connection.execute(text("SELECT nspname FROM pg_namespace")).scalars())
            left = set(
                connection.execute(
                    text("SELECT tgname FROM pg_trigger WHERE NOT tgisinternal")
                ).scalars()
            )
        assert SCHEMA not in remaining
        assert left == set()
    finally:
        engine.dispose()


@pytest.mark.database
def test_downgrading_this_revision_restores_the_previous_vocabulary(
    disposable_database: str,
) -> None:
    """A downgrade puts the constraint back to what the revision below denotes.

    Not to what the domain says today, which is the trap: reading the enum on
    the way down would leave a database at `af3d35efb9c0` holding a constraint
    that revision never described, which is the same defect as the one this
    package fixed, pointed the other way.
    """
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        assert _admitted(engine, "capability_is_known") == {c.value for c in Capability}

        command.downgrade(_config(), ENROLLMENT_OBJECTS_REVISION)

        assert _admitted(engine, "capability_is_known") == FROZEN_CAPABILITIES
        assert _admitted(engine, "purpose_is_known") == FROZEN_PURPOSES
        assert not CAPTURE_TABLES & _tables(engine)
        # The control: the tables the revisions below created are still there, so
        # the downgrade removed this revision's work and not the schema.
        assert len(_tables(engine)) == 10

        command.upgrade(_config(), "head")
        assert _tables(engine) >= CAPTURE_TABLES

        command.downgrade(_config(), "base")
    finally:
        engine.dispose()
