"""Relationship Memory promotion through the Review plane, against a real PostgreSQL server.

Beside `tests/database/test_relationship_memory_repository.py`, which proves the
public write path, and asserting the half that path is *not allowed to reach*: a
source-, rule- or model-derived candidate becomes memory only when a reviewer
decides so (`RM-AC-005`, `RM-AC-016`, `RM-API-AC-011`, `RM-API-AC-012`,
`RM-P-AC-008`).

Eight claims carry this path and each is asserted against the server rather than
against the code that usually calls it:

* **A proposal is not memory.** Its invisibility to `page_for_entity` and
  `search` is asserted *before* any decision, against a database that holds the
  proposal, its evidence and its review case — so an empty page is evidence
  about the two record sets being different tables rather than about an empty
  fixture.
* **Acceptance writes the memory, the version and the copied basis in one
  transaction**, with an authority that is never the public path's
  `user_authored_private_note` and an actor class that is never `user`.
* **Refusal writes nothing at all.** Reject, defer and mark-unresolved are
  counted across the three memory tables before and after; a refused promotion
  is counted across the decision ledger too, because a decision row explaining a
  promotion that did not happen would be worse than either outcome.
* **A second acceptance is a conflict, never a duplicate.** Asserted as a row
  count rather than only as a raised exception, since "it raised" and "it wrote
  nothing" are different claims.
* **A foreign proposal is invisible and undecidable**, and the two answers are
  the same one an absent identifier gets.
* **Every disposition writes exactly the memory-plane tables its branch is
  declared to write**, measured from the SQL the server is actually sent rather
  than from a count of rows or from a reading of the source. This is the only
  claim in the memory plane that is checked against the wire, and it exists
  because the check next to it is not: `RM-API-AC-002`'s per-branch sentences
  are held by an AST walk in
  `tests/architecture/test_every_capability_reaching_a_memory_row_is_declared.py`,
  and an AST walk can be confidently *wrong* about a branch without going quiet.
  An independent review demonstrated that — two plausible lines in
  `decide_relationship_memory_review` made `mark_unresolved` issue the proposal
  UPDATE while every one of that module's forty tests, and every one of the
  twenty-four here, stayed green. The population is `Disposition`'s own members,
  so a disposition the router grows arrives here unstated.
* **An invalidation is not a rejection.** The eighth claim, and the newest
  (Manager ruling R-8, `WP-RI-B-05`). `invalidate` says the basis went away and
  `reject` says the reviewer judged the claim wrong, so the two are driven side
  by side and every trace a later suppression rule could key on — the stored
  state, the candidate's `invalidated_reason`, the disposition on the decision
  chain, the state the case presents — is asserted to differ. The structural half
  is driven rather than read: every disposition with a route is decided against
  the server on a candidate of its own, and exactly one is allowed to leave
  `rejected` behind. The reason column's own CHECKs are asked directly, including
  the two that were already there, because the change is additive and "it takes
  what it took before" is a claim about the server.
* **The producer writes a row this database takes.** The seventh claim:
  `RelationshipMemoryProposalService` fills the proposal columns, and the
  last section drives it through an insert-only adapter so the conditional
  pairings the schema enforces — the model triple, the sensitivity floor — are
  checked against the service that fills them rather than against a fixture
  written to match them.

Everything is synthetic: two invented Principals, invented entities, invented
notes. The database is created and dropped by this module's own fixture and is
never the configured one.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, Row, event, func, insert, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from my_pa.application.relationship_memory import (
    MemoryProposalOrigin,
    MemoryProposalReceipt,
    ProposedEvidence,
    ProposeMemoryCommand,
    RelationshipMemoryProposalService,
)
from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import (
    MemoryWriteRequest,
    ReviewDecisionRequest,
    WriteRequestConflictError,
    WriteRequestEvidence,
    WriteRequestResult,
)
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import (
    Disposition,
    ReviewConflictError,
    ReviewNotFoundError,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.memory import (
    EvidenceLinkRole,
    MemoryActorClass,
    MemoryAuthority,
    MemoryKind,
    MemoryOperation,
    MemoryProposalEvidence,
    MemoryProposalMethod,
    MemoryProposalState,
    RelationshipMemoryProposal,
    classification_floor_for,
    memory_proposal_dedupe_digest,
    statement_digest,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.entity import SqlEntityRepository
from my_pa.infrastructure.persistence.relationship_memory import SqlRelationshipMemoryRepository
from my_pa.infrastructure.persistence.relationship_memory_review import (
    decide_relationship_memory_review,
    is_relationship_memory_review_case,
    relationship_memory_review_cases,
)
from my_pa.infrastructure.persistence.tables import (
    entities,
    relationship_memories,
    relationship_memory_proposal_evidence,
    relationship_memory_proposals,
    relationship_memory_review_decisions,
    relationship_write_request_evidence,
    relationship_write_requests,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.persistence.write_requests import SqlWriteRequestRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"

#: A name distinct from every other database-tier fixture's disposable database,
#: so this suite can run alongside them without one dropping the database
#: another is mid-transaction against.
DISPOSABLE_DATABASE: Final = "my_pa_relationship_memory_review_test"

#: What a promotion writes, counted together whenever the claim is "nothing was
#: promoted". The decision ledger is counted beside them because a refused
#: promotion must leave no decision either.
PROMOTION_TABLES: Final = (
    "relationship_memories",
    "relationship_memory_versions",
    "relationship_memory_evidence_links",
    "relationship_memory_review_decisions",
)

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"

#: A's synthetic person, A's merged-away identity, and B's own person so every
#: read of A's has a foreign decoy that really exists.
DANA: Final = "ent_aaaa0001aaaa0001"
OLD_DANA: Final = "ent_eeee0005eeee0005"
FOREIGN_PERSON: Final = "ent_bbbb0002bbbb0002"

PROPOSED_NOTE: Final = "Synthetic subject asked for closeout updates in writing."
CORRECTED_NOTE: Final = "Synthetic subject asked for weekly closeout updates in writing."

#: A note the user writes themselves, sharing the proposal's search term so one
#: `search` matches both and the two rows differ in nothing but authority.
OWN_NOTE: Final = "Synthetic subject reads closeout mail on Fridays."

#: The reason an invalidation states, and it is a statement about the *basis*
#: rather than about the claim. A rejection's reason would be the opposite kind
#: of sentence, which is the distinction `WP-RI-B-05` exists to keep.
MOOT_BASIS: Final = "the source capture was retracted, so the basis no longer stands"

#: The dispositions `ReviewDecisionRequest` refuses to be built without a reason
#: for. Restated rather than imported from the request's own private class
#: attribute, on `tests/unit/test_entity_proposal_review.py`'s precedent: a
#: constant read out of the object under test agrees with it by construction.
_REASON_REQUIRED: Final = frozenset({Disposition.ESCALATE, Disposition.INVALIDATE})

WHEN: Final = datetime(2026, 8, 22, 12, tzinfo=UTC)
LATER: Final = datetime(2026, 8, 22, 13, tzinfo=UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def disposable_database(monkeypatch: pytest.MonkeyPatch) -> Iterator[str]:
    """Create an empty database, point the settings at it, drop it afterwards.

    Copied rather than shared, as every other database-tier module copies it:
    the fixture names a database of its own so two suites cannot drop each
    other's, and the canonical database is never migrated or opened.
    """
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DISPOSABLE_DATABASE}" WITH (FORCE)')

    def _administer(*statements: object) -> None:
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
def migrated_engine(disposable_database: str) -> Iterator[Engine]:
    """The disposable database, upgraded to head and disposed afterwards."""
    engine = create_database_engine(disposable_database)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()


def an_entity(entity_id: str, principal_id: str, display_name: str) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def two_principals(migrated_engine: Engine) -> Engine:
    """A holds Dana and an identity merged into her; B holds one person of its own."""
    with migrated_engine.begin() as connection:
        repository = SqlEntityRepository(connection)
        repository.create(PRINCIPAL_A, an_entity(DANA, PRINCIPAL_A, "Dana Synthetic"))
        repository.create(PRINCIPAL_A, an_entity(OLD_DANA, PRINCIPAL_A, "Dana Old Synthetic"))
        repository.create(PRINCIPAL_B, an_entity(FOREIGN_PERSON, PRINCIPAL_B, "Bo Synthetic"))
        repository.redirect_entity(PRINCIPAL_A, OLD_DANA, DANA)
    return migrated_engine


# --- fixtures that put a candidate in front of a reviewer ---------------------
#
# Written as direct inserts, and *still* direct inserts now that
# `RelationshipMemoryProposalService` exists. The earlier reason recorded here —
# "no producer exists yet" — has expired, and this is the reason that replaced
# it: this fixture has to be able to write rows a producer refuses, and several
# tests below depend on that. It seeds candidates for a foreign Principal and
# candidates whose classification is stated rather than taken from the kind's
# floor; the producer refuses both by construction. A fixture that could only
# write well-formed candidates could not set up the refusals this suite is about.
#
# The producer is not thereby left unchecked against the schema. The last
# section of this module drives `RelationshipMemoryProposalService` through an
# insert-only adapter and asserts the row it writes survives every CHECK and
# arrives on the canonical Review surface — the claim these hand-written rows
# cannot make, because they were written to match the columns rather than
# derived from the service that has to fill them.


def _open_proposal(
    connection: Connection,
    *,
    principal_id: str = PRINCIPAL_A,
    subject_entity_id: str = DANA,
    kind: MemoryKind = MemoryKind.WORKING_PREFERENCE,
    statement: str = PROPOSED_NOTE,
    evidence: int = 1,
    capture_spans: int = 0,
    classification: Classification | None = None,
    method: MemoryProposalMethod = MemoryProposalMethod.RULE,
    model_id: str | None = None,
    model_version: str | None = None,
    expected_subject_version: int = 1,
) -> tuple[str, str, tuple[str, ...], tuple[str, ...]]:
    """One routed proposal, its review case, and the evidence it rests on.

    Two evidence families rather than one, because they are the two the contract
    names and they are not interchangeable: an entity observation is a source the
    resolution plane already holds, and a capture span is the user's own words at
    an exact offset in an immutable Quick Capture version. `RM-AC-022` is about
    the second — a capture can be *evidence* for a memory without becoming the
    memory — and no test exercised it until one asked for a span.
    """
    memory_proposal_id = issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL)
    review_case_id = issue_identifier(IdKind.REVIEW_CASE)
    spans: list[str] = []
    connection.execute(
        insert(relationship_memory_proposals).values(
            memory_proposal_id=memory_proposal_id,
            principal_id=principal_id,
            subject_entity_id=subject_entity_id,
            expected_subject_version=expected_subject_version,
            proposed_kind=kind.value,
            proposed_statement=statement,
            proposed_statement_sha256=statement_digest(statement),
            dedupe_sha256=memory_proposal_dedupe_digest(
                principal_id=principal_id,
                subject_entity_id=subject_entity_id,
                proposed_kind=kind,
                proposed_statement_sha256=statement_digest(statement),
                structured_value=None,
            ),
            structured_value=None,
            state=MemoryProposalState.NEEDS_REVIEW.value,
            method=method.value,
            method_version="synthetic-rule-v1",
            model_id=model_id,
            model_version=model_version,
            classification=(classification or classification_floor_for(kind)).value,
            proposed_at=WHEN,
            review_case_id=review_case_id,
            accepted_memory_id=None,
            accepted_memory_version_id=None,
            invalidated_reason=None,
        )
    )
    observations: list[str] = []
    for _ in range(evidence):
        observation_id = issue_identifier(IdKind.ENTITY_OBSERVATION)
        observations.append(observation_id)
        connection.execute(
            insert(relationship_memory_proposal_evidence).values(
                proposal_evidence_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL_EVIDENCE),
                memory_proposal_id=memory_proposal_id,
                principal_id=principal_id,
                role=EvidenceLinkRole.DIRECT.value,
                entity_observation_id=observation_id,
                capture_span_id=None,
                knowledge_id=None,
                created_at=WHEN,
            )
        )
    for _ in range(capture_spans):
        span_id = issue_identifier(IdKind.SPAN)
        spans.append(span_id)
        connection.execute(
            insert(relationship_memory_proposal_evidence).values(
                proposal_evidence_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL_EVIDENCE),
                memory_proposal_id=memory_proposal_id,
                principal_id=principal_id,
                role=EvidenceLinkRole.DIRECT.value,
                entity_observation_id=None,
                capture_span_id=span_id,
                knowledge_id=None,
                created_at=WHEN,
            )
        )
    return memory_proposal_id, review_case_id, tuple(observations), tuple(spans)


def _decision(
    review_case_id: str,
    disposition: Disposition,
    *,
    expected_review_version: int = 0,
    principal_id: str = PRINCIPAL_A,
    corrected_value: str | None = None,
    reason: str | None = None,
    at: datetime = LATER,
) -> ReviewDecisionRequest:
    """One request, with the reason the *request* refuses to be built without.

    `ReviewDecisionRequest` requires a reason on `escalate` and `invalidate` and
    refuses one on `accept`, `correct_and_accept` and `reprocess`, so a helper
    that took no reason could not build half of `Disposition` and a helper that
    always supplied one could not build the other half. `_REASON_REQUIRED`
    restates the two, in the shape `tests/unit/test_entity_proposal_review.py`
    restates its own: a test that imported the request's private class attribute
    would agree with it by construction and prove nothing about it.
    """
    if reason is None and disposition in _REASON_REQUIRED:
        reason = MOOT_BASIS
    return ReviewDecisionRequest(
        review_case_id=review_case_id,
        expected_review_version=expected_review_version,
        disposition=disposition,
        principal_id=principal_id,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        policy_version="policy-v1",
        decided_at=at,
        corrected_value=corrected_value,
        reason=reason,
    )


def _counts(connection: Connection) -> dict[str, int]:
    """How many rows each promotion table holds, read on the given connection."""
    return {
        table: int(
            connection.execute(text(f"SELECT count(*) FROM {SCHEMA}.{table}")).scalar_one()  # noqa: S608
        )
        for table in PROMOTION_TABLES
    }


def _version_of(connection: Connection, memory_id: str) -> Row[Any]:
    return connection.execute(
        text(
            f"SELECT * FROM {SCHEMA}.relationship_memory_versions "  # noqa: S608
            "WHERE memory_id = :memory_id"
        ),
        {"memory_id": memory_id},
    ).one()


def _proposal_row(connection: Connection, memory_proposal_id: str) -> Row[Any]:
    return connection.execute(
        select(relationship_memory_proposals).where(
            relationship_memory_proposals.c.memory_proposal_id == memory_proposal_id
        )
    ).one()


def _ledger_rows(connection: Connection, review_case_id: str) -> list[Row[Any]]:
    """One case's decision chain, oldest first."""
    return list(
        connection.execute(
            select(relationship_memory_review_decisions)
            .where(relationship_memory_review_decisions.c.review_case_id == review_case_id)
            .order_by(relationship_memory_review_decisions.c.sequence)
        ).all()
    )


def _ledger_insert(
    memory_proposal_id: str,
    review_case_id: str,
    disposition: Disposition,
    *,
    reason: str | None = None,
    corrected_statement: str | None = None,
    sequence: int = 1,
) -> Any:  # noqa: ANN401 - a SQLAlchemy Insert
    """One ledger row built by hand, so the CHECKs are asked and not the writer.

    `decide_relationship_memory_review` refuses several of these shapes before
    the server sees them, and that refusal is the application's. What a CHECK
    claims is that no row of that shape can exist at all, which is only checkable
    by trying to insert one.
    """
    return insert(relationship_memory_review_decisions).values(
        decision_id=issue_identifier(IdKind.REVIEW_DECISION),
        memory_proposal_id=memory_proposal_id,
        review_case_id=review_case_id,
        principal_id=PRINCIPAL_A,
        sequence=sequence,
        disposition=disposition.value,
        corrected_statement=corrected_statement,
        reason=reason,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        decided_at=LATER,
    )


# --- a proposal is not memory -------------------------------------------------


def test_a_proposal_is_invisible_to_every_memory_read_until_it_is_accepted(
    two_principals: Engine,
) -> None:
    """`RM-AC-005`: the two record sets are different tables, so no filter can forget."""
    with two_principals.begin() as connection:
        _open_proposal(connection)

    with two_principals.begin() as connection:
        memories = SqlRelationshipMemoryRepository(connection)
        page = memories.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        found = memories.search("closeout", principal_id=PRINCIPAL_A, limit=10)
        cases = relationship_memory_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)

    assert page.memories == ()
    assert page.withheld_by_policy == 0, "a withheld count would disclose the candidate"
    assert found.memories == ()
    # The candidate is nonetheless in front of a reviewer, which is what makes
    # the two empty answers above evidence rather than an empty fixture.
    assert len(cases) == 1
    assert cases[0].proposal_state is ProposalState.NEEDS_REVIEW
    assert cases[0].review_version == 0
    assert cases[0].latest_disposition is None
    assert cases[0].accepted_memory_id is None
    assert cases[0].subject_entity_id == DANA
    assert cases[0].proposed_kind is MemoryKind.WORKING_PREFERENCE


def test_a_review_case_carries_no_statement_text_for_a_reviewer_to_leak(
    two_principals: Engine,
) -> None:
    """The disclosure control is the absent field, not a filter someone may edit.

    A `sensitivity` candidate is the sharpest case: its accepted form floors at
    `RESTRICTED_LOCAL`, which `search` excludes by predicate. If the review
    listing carried the proposed words, the same sentence would be readable
    through a capability that makes no eligibility decision at all.
    """
    with two_principals.begin() as connection:
        _open_proposal(
            connection,
            kind=MemoryKind.SENSITIVITY,
            statement="Synthetic subject: do not raise the synthetic dispute.",
        )

    with two_principals.begin() as connection:
        cases = relationship_memory_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)

    assert len(cases) == 1
    exposed = vars(cases[0]) if hasattr(cases[0], "__dict__") else {}
    assert exposed == {}, "a slotted case has no instance dictionary to carry text"
    assert not hasattr(cases[0], "proposed_statement")
    assert not hasattr(cases[0], "statement")
    assert "dispute" not in repr(cases[0])


# --- acceptance promotes ------------------------------------------------------


def test_a_capture_span_backed_proposal_carries_its_span_onto_the_memory(
    two_principals: Engine,
) -> None:
    """`RM-AC-022`: a Quick Capture is evidence for a memory, never the memory.

    The promoted record is a memory in `relationship_memories` with its own
    immutable version; what it keeps of the capture is a span reference, so the
    basis stays checkable against the exact offsets in the immutable capture
    version. Two things are asserted because either alone would pass a wrong
    implementation: that the span reached the accepted version's evidence, and
    that the promotion wrote the span into the `capture_span_id` column rather
    than smuggling it into the observation column, which would make a capture
    indistinguishable from a source observation on every later read.

    The matrix claimed this row was already exercised and it was not — the whole
    memory corpus mentioned `capture_span_id` once, as `None`.
    """
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, spans = _open_proposal(
            connection, evidence=0, capture_spans=2
        )

    with two_principals.begin() as connection:
        decide_relationship_memory_review(connection, _decision(review_case_id, Disposition.ACCEPT))

    with two_principals.connect() as connection:
        stamped = _proposal_row(connection, proposal_id)
        carried = connection.execute(
            text(
                f"SELECT capture_span_id, entity_observation_id, knowledge_id FROM "  # noqa: S608
                f"{SCHEMA}.relationship_memory_evidence_links "
                "WHERE memory_version_id = :version_id ORDER BY capture_span_id"
            ),
            {"version_id": stamped.accepted_memory_version_id},
        ).all()
    assert [row.capture_span_id for row in carried] == sorted(spans)
    assert all(row.entity_observation_id is None for row in carried)
    assert all(row.knowledge_id is None for row in carried)


def test_the_server_refuses_proposal_evidence_naming_two_records(
    two_principals: Engine,
) -> None:
    """The exclusive-target CHECK, asked of the server rather than of the writer.

    A row naming both an observation and a capture span is a basis nobody can
    read: the two are different families with different re-validation rules, and
    a reader would have to guess which one the assertion rests on. The
    constraint says so, and until this test nothing did — deleting it from
    `tables.py` failed nothing, and because the migration copies the live table
    objects rather than restating them, that deletion would silently change what
    an already-merged revision builds on a fresh database.
    """
    with two_principals.begin() as connection:
        proposal_id, _, _, _ = _open_proposal(connection, evidence=0)

    with two_principals.connect() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(
            insert(relationship_memory_proposal_evidence).values(
                proposal_evidence_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL_EVIDENCE),
                memory_proposal_id=proposal_id,
                principal_id=PRINCIPAL_A,
                role=EvidenceLinkRole.DIRECT.value,
                entity_observation_id=issue_identifier(IdKind.ENTITY_OBSERVATION),
                capture_span_id=issue_identifier(IdKind.SPAN),
                knowledge_id=None,
                created_at=WHEN,
            )
        )
    assert "memory_proposal_evidence_names_exactly_one_record" in str(refused.value)


def test_the_server_refuses_proposal_evidence_naming_no_record(
    two_principals: Engine,
) -> None:
    """The other half of exactly-one, so the constraint is not merely at-most-one.

    An evidence row naming nothing is evidence of nothing, and a promotion that
    wrote one would satisfy "the accepted memory has evidence links" while
    resting on air.
    """
    with two_principals.begin() as connection:
        proposal_id, _, _, _ = _open_proposal(connection, evidence=0)

    with two_principals.connect() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(
            insert(relationship_memory_proposal_evidence).values(
                proposal_evidence_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_PROPOSAL_EVIDENCE),
                memory_proposal_id=proposal_id,
                principal_id=PRINCIPAL_A,
                role=EvidenceLinkRole.DIRECT.value,
                entity_observation_id=None,
                capture_span_id=None,
                knowledge_id=None,
                created_at=WHEN,
            )
        )
    assert "memory_proposal_evidence_names_exactly_one_record" in str(refused.value)


def test_accepting_an_evidence_backed_proposal_writes_a_source_backed_memory(
    two_principals: Engine,
) -> None:
    """`RM-AC-015`/`RM-AC-016`: the memory, its v1 and the exact copied basis."""
    with two_principals.begin() as connection:
        proposal_id, review_case_id, observations, _ = _open_proposal(connection, evidence=2)

    with two_principals.begin() as connection:
        decision = decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.ACCEPT)
        )

    assert decision.sequence == 1
    assert decision.proposal_state is ProposalState.ACCEPTED

    with two_principals.connect() as connection:
        stamped = _proposal_row(connection, proposal_id)
        version = _version_of(connection, stamped.accepted_memory_id)
        links = connection.execute(
            text(
                f"SELECT role, entity_observation_id FROM "  # noqa: S608
                f"{SCHEMA}.relationship_memory_evidence_links "
                "WHERE memory_version_id = :version_id ORDER BY entity_observation_id"
            ),
            {"version_id": stamped.accepted_memory_version_id},
        ).all()

    assert stamped.state == MemoryProposalState.ACCEPTED.value
    assert stamped.accepted_memory_version_id == version.memory_version_id
    assert version.version_number == 1
    assert version.statement_text == PROPOSED_NOTE
    assert version.statement_sha256 == statement_digest(PROPOSED_NOTE)
    # The two decisions this path exists to make.
    assert version.authority == MemoryAuthority.SOURCE_BACKED_ASSERTION.value
    assert version.created_by_actor == MemoryActorClass.REVIEW_PROMOTION.value
    assert version.authority != MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE.value
    assert version.proposal_id == proposal_id
    assert version.review_case_id == review_case_id
    assert version.idempotency_key == decision.decision_id
    assert not version.cloud_eligible
    # The basis is the proposal's own, exactly, and both records survived.
    assert [row.entity_observation_id for row in links] == sorted(observations)
    assert {row.role for row in links} == {EvidenceLinkRole.DIRECT.value}


def test_the_promoted_memory_is_then_an_ordinary_readable_memory(
    two_principals: Engine,
) -> None:
    """Promotion joins the current set; it does not create a second, parallel one."""
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)
    with two_principals.begin() as connection:
        decide_relationship_memory_review(connection, _decision(review_case_id, Disposition.ACCEPT))

    with two_principals.begin() as connection:
        memories = SqlRelationshipMemoryRepository(connection)
        page = memories.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        found = memories.search("closeout", principal_id=PRINCIPAL_A, limit=10)
        detail = memories.detail(page.memories[0].memory_id, principal_id=PRINCIPAL_A)
        cases = relationship_memory_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)

    assert len(page.memories) == 1
    assert page.listing_facts[page.memories[0].memory_id].statement == PROPOSED_NOTE
    assert [memory.memory_id for memory in found.memories] == [page.memories[0].memory_id]
    assert detail is not None
    assert detail.evidence_count == 1
    assert cases[0].proposal_state is ProposalState.ACCEPTED
    assert cases[0].accepted_memory_id == page.memories[0].memory_id
    assert cases[0].review_version == 1
    assert cases[0].latest_disposition is Disposition.ACCEPT


def _a_user_authored_note(connection: Connection, statement: str, key: str) -> str:
    """One note written the way a user writes one, on the same subject.

    Built here rather than borrowed from the repository suite because this test
    needs the *other* half of the comparison and nothing else: the public write
    path may claim exactly one authority, so a note admitted through `admit` is
    the only thing a promoted assertion can be told apart from.
    """
    request = MemoryWriteRequest(
        operation=MemoryOperation.CREATE,
        memory_id=None,
        memory_version_id=issue_identifier(IdKind.RELATIONSHIP_MEMORY_VERSION),
        expected_version=None,
        principal_id=PRINCIPAL_A,
        subject_entity_id=DANA,
        memory_kind=MemoryKind.WORKING_PREFERENCE,
        statement=statement,
        statement_sha256=statement_digest(statement),
        structured_value=None,
        authority=MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE,
        classification=classification_floor_for(MemoryKind.WORKING_PREFERENCE),
        created_by_actor=MemoryActorClass.USER,
        context_links=(),
        pinned=False,
        observed_at=None,
        effective_from=None,
        effective_to=None,
        correction_reason=None,
        idempotency_key=key,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        server_received_at=WHEN,
    )
    return SqlRelationshipMemoryRepository(connection).admit(request).receipt.memory_id


def test_a_listing_tells_a_promoted_assertion_apart_from_the_users_own_note(
    two_principals: Engine,
) -> None:
    """`RM-AC-019`: the two rows a listing must never render identically.

    Both memories are on one subject, of one kind, with one lifecycle, both
    unpinned, so *every* other field a listing publishes is equal between them
    and `authority` is the only thing that can separate them. That arrangement is
    the test: with authority absent from the page, a reader — an assistant
    deciding whether it may present a line as something it knows or only as
    something the user once wrote — has nothing left to tell a reviewer-promoted
    `source_backed_assertion` from a private note, which is the distinction
    ADR-003 exists to preserve.

    Asserted through `page_for_entity` and `search`, because they are two
    statements and each could carry the column the other dropped.
    """
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)
    with two_principals.begin() as connection:
        decide_relationship_memory_review(connection, _decision(review_case_id, Disposition.ACCEPT))
    with two_principals.begin() as connection:
        own = _a_user_authored_note(connection, OWN_NOTE, "listing-authority-0001")

    with two_principals.connect() as connection:
        memories = SqlRelationshipMemoryRepository(connection)
        page = memories.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        found = memories.search("closeout", principal_id=PRINCIPAL_A, limit=10)

    promoted = next(memory.memory_id for memory in page.memories if memory.memory_id != own)
    # The listing really does hold two otherwise-identical rows; if it did not,
    # the inequality below would be a claim about one memory and a missing one.
    assert {memory.memory_id for memory in page.memories} == {own, promoted}
    assert len({memory.memory_kind for memory in page.memories}) == 1
    assert {memory.pinned for memory in page.memories} == {False}

    assert page.listing_facts[promoted].authority is MemoryAuthority.SOURCE_BACKED_ASSERTION
    assert page.listing_facts[own].authority is MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE
    assert page.listing_facts[promoted].authority is not page.listing_facts[own].authority
    # Both notes share the search term, so the same distinction has to survive
    # the second statement as well.
    assert {memory.memory_id for memory in found.memories} == {own, promoted}
    assert found.listing_facts[promoted].authority is MemoryAuthority.SOURCE_BACKED_ASSERTION
    assert found.listing_facts[own].authority is MemoryAuthority.USER_AUTHORED_PRIVATE_NOTE


def test_a_corrected_acceptance_is_user_confirmed_and_commits_the_reviewers_words(
    two_principals: Engine,
) -> None:
    """A correction is the reviewer saying the proposal was wrong, so no source backs it."""
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection)

    with two_principals.begin() as connection:
        decide_relationship_memory_review(
            connection,
            _decision(
                review_case_id,
                Disposition.CORRECT_AND_ACCEPT,
                corrected_value=CORRECTED_NOTE,
            ),
        )

    with two_principals.connect() as connection:
        stamped = _proposal_row(connection, proposal_id)
        version = _version_of(connection, stamped.accepted_memory_id)
        evidence = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.relationship_memory_evidence_links "  # noqa: S608
                "WHERE memory_version_id = :version_id"
            ),
            {"version_id": version.memory_version_id},
        ).scalar_one()

    assert stamped.state == MemoryProposalState.CORRECTED_ACCEPTED.value
    assert version.statement_text == CORRECTED_NOTE
    assert version.statement_sha256 == statement_digest(CORRECTED_NOTE)
    assert version.authority == MemoryAuthority.USER_CONFIRMED_ASSERTION.value
    # The basis still travels: it is what the reviewer read before correcting.
    assert evidence == 1


def test_an_acceptance_with_no_evidence_is_confirmed_rather_than_source_backed(
    two_principals: Engine,
) -> None:
    """There is nothing to be backed by, so the honest authority is the weaker one."""
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection, evidence=0)
    with two_principals.begin() as connection:
        decide_relationship_memory_review(connection, _decision(review_case_id, Disposition.ACCEPT))

    with two_principals.connect() as connection:
        stamped = _proposal_row(connection, proposal_id)
        version = _version_of(connection, stamped.accepted_memory_id)

    assert version.authority == MemoryAuthority.USER_CONFIRMED_ASSERTION.value


def test_a_sensitivity_promotion_keeps_the_classification_the_kind_requires(
    two_principals: Engine,
) -> None:
    """The floor is a floor on the promoted version too, and the read plane honours it."""
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(
            connection,
            kind=MemoryKind.SENSITIVITY,
            statement="Synthetic subject: do not raise the synthetic dispute.",
        )
    with two_principals.begin() as connection:
        decide_relationship_memory_review(connection, _decision(review_case_id, Disposition.ACCEPT))

    with two_principals.begin() as connection:
        stamped = _proposal_row(connection, proposal_id)
        version = _version_of(connection, stamped.accepted_memory_id)
        found = SqlRelationshipMemoryRepository(connection).search(
            "dispute", principal_id=PRINCIPAL_A, limit=10
        )

    assert version.classification == Classification.RESTRICTED_LOCAL.value
    assert found.memories == (), "a restricted memory is never selected by search"


# --- refusal writes nothing ---------------------------------------------------


@pytest.mark.parametrize(
    "disposition",
    [Disposition.REJECT, Disposition.DEFER, Disposition.MARK_UNRESOLVED],
)
def test_a_non_accepting_disposition_leaves_no_memory(
    two_principals: Engine, disposition: Disposition
) -> None:
    """Only the decision row is written; the three memory tables are untouched."""
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection)
        before = _counts(connection)

    with two_principals.begin() as connection:
        decision = decide_relationship_memory_review(
            connection, _decision(review_case_id, disposition)
        )

    with two_principals.connect() as connection:
        after = _counts(connection)
        stamped = _proposal_row(connection, proposal_id)
        page = SqlRelationshipMemoryRepository(connection).page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10
        )

    assert decision.disposition is disposition
    assert after == {
        **before,
        "relationship_memory_review_decisions": before["relationship_memory_review_decisions"] + 1,
    }
    assert stamped.accepted_memory_id is None
    assert stamped.accepted_memory_version_id is None
    assert page.memories == ()


def test_mark_unresolved_leaves_the_stored_state_alone_and_says_so_on_the_case(
    two_principals: Engine,
) -> None:
    """`MemoryProposalState` names no `unresolved`, so the decision chain carries it.

    Asserted rather than left implicit: the stored state staying `needs_review`
    is a deliberate consequence of a closed vocabulary this work package may not
    widen, and the review surface still reports `unresolved` because it derives
    the case's state from the latest disposition.
    """
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection)
    with two_principals.begin() as connection:
        decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.MARK_UNRESOLVED)
        )

    with two_principals.begin() as connection:
        stamped = _proposal_row(connection, proposal_id)
        cases = relationship_memory_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)

    assert stamped.state == MemoryProposalState.NEEDS_REVIEW.value
    assert cases[0].proposal_state is ProposalState.UNRESOLVED
    assert cases[0].latest_disposition is Disposition.MARK_UNRESOLVED


def test_reprocess_supersedes_and_copies_a_successor_at_current_subject_version(
    two_principals: Engine,
) -> None:
    with two_principals.begin() as connection:
        proposal_id, review_case_id, observations, _ = _open_proposal(
            connection,
            evidence=2,
            method=MemoryProposalMethod.LOCAL_MODEL,
            model_id="synthetic-local-model",
            model_version="2026-08-22",
        )
        connection.execute(
            update(entities)
            .where(entities.c.entity_id == DANA, entities.c.principal_id == PRINCIPAL_A)
            .values(version=2)
        )
        decision = decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.REPROCESS)
        )

    with two_principals.connect() as connection:
        predecessor = _proposal_row(connection, proposal_id)
        successor = _proposal_row(connection, predecessor.superseded_by_memory_proposal_id)
        copied = connection.execute(
            select(relationship_memory_proposal_evidence.c.entity_observation_id)
            .where(
                relationship_memory_proposal_evidence.c.memory_proposal_id
                == successor.memory_proposal_id
            )
            .order_by(relationship_memory_proposal_evidence.c.entity_observation_id)
        ).scalars().all()
        cases = relationship_memory_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)

    assert decision.proposal_state is ProposalState.SUPERSEDED
    assert predecessor.state == MemoryProposalState.SUPERSEDED.value
    assert predecessor.superseded_at == LATER
    assert successor.expected_subject_version == 2
    assert successor.dedupe_sha256 == memory_proposal_dedupe_digest(
        principal_id=PRINCIPAL_A,
        subject_entity_id=successor.subject_entity_id,
        proposed_kind=successor.proposed_kind,
        proposed_statement_sha256=successor.proposed_statement_sha256,
        structured_value=successor.structured_value,
    )
    assert successor.dedupe_sha256 == predecessor.dedupe_sha256
    assert successor.review_case_id != review_case_id
    assert successor.method == predecessor.method
    assert successor.method_version == predecessor.method_version
    assert successor.model_id == predecessor.model_id
    assert successor.model_version == predecessor.model_version
    assert successor.proposed_statement == predecessor.proposed_statement
    assert successor.structured_value == predecessor.structured_value
    assert successor.classification == predecessor.classification
    assert copied == sorted(observations)
    old_case = next(case for case in cases if case.review_case_id == review_case_id)
    assert old_case.superseded_by_proposal_id == successor.memory_proposal_id


def test_a_stale_reprocess_writes_nothing(two_principals: Engine) -> None:
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)
        decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.DEFER)
        )
        before = _counts(connection)
        proposals_before = connection.execute(
            select(func.count()).select_from(relationship_memory_proposals)
        ).scalar_one()

    with (
        pytest.raises(ReviewConflictError, match="review version is stale"),
        two_principals.begin() as connection,
    ):
        decide_relationship_memory_review(
            connection,
            _decision(review_case_id, Disposition.REPROCESS, expected_review_version=0),
        )

    with two_principals.connect() as connection:
        assert _counts(connection) == before
        assert connection.execute(
            select(func.count()).select_from(relationship_memory_proposals)
        ).scalar_one() == proposals_before


# --- server replay reservation invariants -----------------------------------


def _replay_result(*, evidence: bool = False) -> WriteRequestResult:
    return WriteRequestResult(
        result_family="memory_proposal",
        result_id="mprp_aaaa0001aaaa0001",
        result_state="needs_review",
        result_digest="d" * 64,
        result_count=1,
        result_created=True,
        evidence=(
            WriteRequestEvidence(sequence=1, role="direct", knowledge_id="knw_aaaa0001aaaa0001"),
        )
        if evidence
        else (),
    )


def test_concurrent_same_request_reads_back_the_exact_committed_result(
    two_principals: Engine,
) -> None:
    capability = "relationship_memory.propose"
    request_id = "corr_concurrent_replay"
    digest = "a" * 64

    def lose() -> WriteRequestResult | None:
        with two_principals.begin() as connection:
            return SqlWriteRequestRepository(connection).reserve(
                PRINCIPAL_A, capability, request_id, digest
            )

    with ThreadPoolExecutor(max_workers=1) as executor:
        with two_principals.begin() as connection:
            winner = SqlWriteRequestRepository(connection)
            assert winner.reserve(PRINCIPAL_A, capability, request_id, digest) is None
            future = executor.submit(lose)
            winner.complete(PRINCIPAL_A, capability, request_id, digest, _replay_result())
        replayed = future.result(timeout=10)

    assert replayed == _replay_result()


def test_same_request_with_changed_material_conflicts(two_principals: Engine) -> None:
    with two_principals.begin() as connection:
        repository = SqlWriteRequestRepository(connection)
        assert repository.reserve(PRINCIPAL_A, "review.decide", "corr_digest", "a" * 64) is None
        repository.complete(
            PRINCIPAL_A, "review.decide", "corr_digest", "a" * 64, _replay_result()
        )

    with pytest.raises(WriteRequestConflictError), two_principals.begin() as connection:
        SqlWriteRequestRepository(connection).reserve(
            PRINCIPAL_A, "review.decide", "corr_digest", "b" * 64
        )


def test_rolled_back_reservation_does_not_claim_the_request(two_principals: Engine) -> None:
    transaction = two_principals.connect()
    try:
        held = transaction.begin()
        assert SqlWriteRequestRepository(transaction).reserve(
            PRINCIPAL_A, "review.decide", "corr_rollback", "a" * 64
        ) is None
        held.rollback()
    finally:
        transaction.close()

    with two_principals.begin() as connection:
        assert SqlWriteRequestRepository(connection).reserve(
            PRINCIPAL_A, "review.decide", "corr_rollback", "a" * 64
        ) is None
        SqlWriteRequestRepository(connection).complete(
            PRINCIPAL_A, "review.decide", "corr_rollback", "a" * 64, _replay_result()
        )


def test_a_pending_reservation_cannot_commit(two_principals: Engine) -> None:
    with (
        pytest.raises(DBAPIError, match="remained pending at commit"),
        two_principals.begin() as connection,
    ):
        assert SqlWriteRequestRepository(connection).reserve(
            PRINCIPAL_A, "review.decide", "corr_pending", "a" * 64
        ) is None


def test_completed_request_and_replay_evidence_are_immutable(two_principals: Engine) -> None:
    with two_principals.begin() as connection:
        repository = SqlWriteRequestRepository(connection)
        assert repository.reserve(
            PRINCIPAL_A, "relationship_memory.propose", "corr_immutable", "a" * 64
        ) is None
        repository.complete(
            PRINCIPAL_A,
            "relationship_memory.propose",
            "corr_immutable",
            "a" * 64,
            _replay_result(evidence=True),
        )

    with (
        pytest.raises(DBAPIError, match="transition is immutable"),
        two_principals.begin() as connection,
    ):
        connection.execute(
            update(relationship_write_requests)
            .where(relationship_write_requests.c.request_id == "corr_immutable")
            .values(result_count=2)
        )
    with (
        pytest.raises(DBAPIError, match="evidence is immutable"),
        two_principals.begin() as connection,
    ):
        connection.execute(
            update(relationship_write_request_evidence)
            .where(relationship_write_request_evidence.c.request_id == "corr_immutable")
            .values(role="supporting")
        )


def test_relationship_memory_review_replays_its_durable_exact_decision(
    two_principals: Engine,
) -> None:
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)
        repository = SqlWriteRequestRepository(connection)
        assert repository.reserve(
            PRINCIPAL_A, "review.decide", "corr_rm_review", "a" * 64
        ) is None
        decision = decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.ACCEPT)
        )
        original = WriteRequestResult(
            result_family="review_decision",
            result_id=decision.decision_id,
            result_secondary_id=decision.review_case_id,
            result_version=decision.sequence,
            result_state=decision.proposal_state.value,
            result_disposition=decision.disposition.value,
            result_assertion_id=decision.assertion_id,
            receipt_id=decision.receipt_id,
        )
        repository.complete(
            PRINCIPAL_A, "review.decide", "corr_rm_review", "a" * 64, original
        )

    with two_principals.begin() as connection:
        replayed = SqlWriteRequestRepository(connection).reserve(
            PRINCIPAL_A, "review.decide", "corr_rm_review", "a" * 64
        )
        decision_count = connection.execute(
            select(func.count())
            .select_from(relationship_memory_review_decisions)
            .where(relationship_memory_review_decisions.c.review_case_id == review_case_id)
        ).scalar_one()

    assert replayed == original
    assert decision_count == 1


def test_escalation_is_sticky_and_acceptance_requires_operator_authority(
    two_principals: Engine,
) -> None:
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)
        escalated = decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.ESCALATE)
        )
        decide_relationship_memory_review(
            connection,
            _decision(
                review_case_id,
                Disposition.DEFER,
                expected_review_version=1,
                reason="awaiting operator review",
            ),
        )

    with two_principals.connect() as connection:
        case = next(
            case
            for case in relationship_memory_review_cases(
                connection, principal_id=PRINCIPAL_A, limit=10
            )
            if case.review_case_id == review_case_id
        )
    assert escalated.proposal_state is ProposalState.NEEDS_REVIEW
    assert case.latest_disposition is Disposition.DEFER
    assert case.requires_operator_authority

    with (
        pytest.raises(ReviewConflictError, match="requires operator authority"),
        two_principals.begin() as connection,
    ):
        decide_relationship_memory_review(
            connection,
            _decision(review_case_id, Disposition.ACCEPT, expected_review_version=2),
        )

    with two_principals.begin() as connection:
        accepted = decide_relationship_memory_review(
            connection,
            _decision(review_case_id, Disposition.ACCEPT, expected_review_version=2),
            has_operator_authority=True,
        )
    assert accepted.proposal_state is ProposalState.ACCEPTED


def test_expected_subject_version_is_proposal_metadata_only() -> None:
    assert "expected_subject_version" in relationship_memory_proposals.c
    assert "expected_subject_version" not in relationship_memories.c
    lineage = next(
        constraint
        for constraint in relationship_memory_proposals.foreign_key_constraints
        if constraint.name == "a_memory_proposal_is_superseded_within_its_principal"
    )
    assert lineage.deferrable is True
    assert lineage.initially == "DEFERRED"


def test_a_stale_subject_version_refuses_promotion_before_any_canonical_write(
    two_principals: Engine,
) -> None:
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(
            connection, expected_subject_version=1
        )
        connection.execute(
            update(entities)
            .where(entities.c.entity_id == DANA, entities.c.principal_id == PRINCIPAL_A)
            .values(version=2)
        )
        before = _counts(connection)

    with (
        pytest.raises(ReviewConflictError, match="subject version is stale"),
        two_principals.begin() as connection,
    ):
        decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.ACCEPT)
        )

    with two_principals.connect() as connection:
        assert _counts(connection) == before


# --- invalidate: the basis went away, and it is not a rejection ---------------
#
# Manager ruling R-8. `invalidate` is a disposition `review.decide` publishes and
# `relationship_memory.propose` is a subject kind this phase creates, so an
# unreachable disposition here was a hole in this phase's own surface. The four
# properties the ruling names are asserted separately below because they fail for
# different reasons: the reason is recorded; no canonical record is created; the
# lineage is retained; and — the one the ruling turns on — the act is *not* a
# rejection and files no negative finding a later suppression rule could read.


def test_an_invalidation_records_why_and_creates_no_canonical_record(
    two_principals: Engine,
) -> None:
    """State, reason, and the three promotion tables untouched.

    The reason is written twice and to two different records, which is deliberate
    rather than duplication: `relationship_memory_review_decisions.reason` is the
    reviewer's act, and `relationship_memory_proposals.invalidated_reason` is the
    candidate's own record of why it stopped standing — the column
    `RelationshipMemoryProposal` has always declared and that nothing wrote until
    `WP-RI-B-05`. A state written with the reason dropped would record that a
    basis failed without recording how.
    """
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection)
        before = _counts(connection)

    with two_principals.begin() as connection:
        decision = decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.INVALIDATE)
        )

    with two_principals.connect() as connection:
        after = _counts(connection)
        stamped = _proposal_row(connection, proposal_id)
        ledger = _ledger_rows(connection, review_case_id)
        page = SqlRelationshipMemoryRepository(connection).page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10
        )

    assert decision.disposition is Disposition.INVALIDATE
    assert decision.proposal_state is ProposalState.INVALIDATED
    assert after == {
        **before,
        "relationship_memory_review_decisions": before["relationship_memory_review_decisions"] + 1,
    }
    assert page.memories == (), "an invalidation creates no memory"
    assert stamped.state == MemoryProposalState.INVALIDATED.value
    assert stamped.invalidated_reason == MOOT_BASIS
    assert stamped.accepted_memory_id is None
    assert stamped.accepted_memory_version_id is None
    assert [(row.disposition, row.reason) for row in ledger] == [
        (Disposition.INVALIDATE.value, MOOT_BASIS)
    ]


def test_an_invalidation_is_not_a_rejection_and_leaves_no_negative_finding(
    two_principals: Engine,
) -> None:
    """The distinction Manager ruling R-8 turns on, asserted rather than argued.

    `reject` means "I looked and judged this wrong" and is this plane's negative
    finding about the claim: it is the signal a suppression rule reads back to
    stop re-offering a known-bad candidate. `invalidate` means the basis went
    away and judges the claim not at all. If a reviewer had to spend `reject` on
    a moot candidate, the row left behind would be a negative finding nobody
    made — so the two are compared side by side here, against a real server, and
    every readable trace a suppression rule could key on is asserted to differ.

    The last assertion is the structural one: exactly one disposition leaves
    `rejected` behind. It is derived from the router's own map by driving every
    member that has a route, so a later change sending `invalidate` to `rejected`
    reddens here rather than quietly turning invalidations into refusals.
    """
    with two_principals.begin() as connection:
        invalidated_id, invalidated_case, _, _ = _open_proposal(connection)
        rejected_id, rejected_case, _, _ = _open_proposal(connection)

    with two_principals.begin() as connection:
        decide_relationship_memory_review(
            connection, _decision(invalidated_case, Disposition.INVALIDATE)
        )
        decide_relationship_memory_review(
            connection, _decision(rejected_case, Disposition.REJECT, reason="the claim is wrong")
        )

    with two_principals.connect() as connection:
        invalidated = _proposal_row(connection, invalidated_id)
        rejected = _proposal_row(connection, rejected_id)
        invalidated_ledger = _ledger_rows(connection, invalidated_case)
        rejected_ledger = _ledger_rows(connection, rejected_case)
        cases = {
            case.review_case_id: case
            for case in relationship_memory_review_cases(
                connection, principal_id=PRINCIPAL_A, limit=10
            )
        }

    assert invalidated.state == MemoryProposalState.INVALIDATED.value
    assert rejected.state == MemoryProposalState.REJECTED.value
    assert invalidated.state != rejected.state, (
        "an invalidated candidate and a rejected one are indistinguishable on the "
        "column every later read of the proposal keys on"
    )
    assert invalidated.invalidated_reason == MOOT_BASIS
    assert rejected.invalidated_reason is None, (
        "a rejection is a finding about the claim and records no invalidation reason"
    )
    assert [row.disposition for row in invalidated_ledger] == [Disposition.INVALIDATE.value]
    assert Disposition.REJECT.value not in {row.disposition for row in invalidated_ledger}, (
        "an invalidation files a `reject` row, which is the false negative-evidence "
        "signal this disposition exists to avoid"
    )
    assert [row.disposition for row in rejected_ledger] == [Disposition.REJECT.value]
    assert cases[invalidated_case].proposal_state is ProposalState.INVALIDATED
    assert cases[rejected_case].proposal_state is ProposalState.REJECTED


def test_exactly_one_disposition_leaves_a_rejected_candidate_behind(
    two_principals: Engine,
) -> None:
    """The structural half of the distinction, driven rather than read off a map.

    `rejected` is the stored state a suppression rule would key on to stop
    re-offering a known-bad candidate. Every disposition with a route is driven
    against the server on a candidate of its own and the stored state is read
    back, so the claim is about what the router *does* and not about what
    `_STORED_STATE` says it does. If a later change sent `invalidate` to
    `rejected` — the substitution Manager ruling R-8 refuses — this is what goes
    red, and it goes red whether the change is made in the map or anywhere else
    on the path.
    """
    stored: dict[str, set[str]] = {}
    for disposition in Disposition:
        with two_principals.begin() as connection:
            proposal_id, review_case_id, _, _ = _open_proposal(connection)
        with two_principals.begin() as connection:
            decide_relationship_memory_review(
                connection,
                _decision(
                    review_case_id,
                    disposition,
                    corrected_value=(
                        CORRECTED_NOTE
                        if disposition is Disposition.CORRECT_AND_ACCEPT
                        else None
                    ),
                ),
            )
        with two_principals.connect() as connection:
            state = str(_proposal_row(connection, proposal_id).state)
        stored.setdefault(state, set()).add(disposition.value)

    assert stored[MemoryProposalState.REJECTED.value] == {Disposition.REJECT.value}, (
        f"{sorted(stored[MemoryProposalState.REJECTED.value])} leave a `rejected` "
        "candidate behind. Only a rejection may: `rejected` is this plane's negative "
        "finding about the claim, and a second disposition arriving there makes a moot "
        "basis indistinguishable from a refusal on every later read"
    )
    assert stored[MemoryProposalState.INVALIDATED.value] == {Disposition.INVALIDATE.value}


def test_an_invalidated_case_keeps_its_candidate_evidence_and_decision_chain(
    two_principals: Engine,
) -> None:
    """Retain lineage: nothing is deleted and the case stays readable.

    The candidate row, the exact evidence it rested on and the decision that
    closed it are all still there afterwards, and the case is still on the
    canonical Review listing carrying the disposition and the review version. An
    invalidation that removed the candidate would destroy the record of what was
    proposed and on what, which is the opposite of what "the basis is moot"
    means.
    """
    with two_principals.begin() as connection:
        proposal_id, review_case_id, observations, _ = _open_proposal(connection, evidence=2)

    with two_principals.begin() as connection:
        decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.INVALIDATE)
        )

    with two_principals.connect() as connection:
        held = _proposal_row(connection, proposal_id)
        evidence = connection.execute(
            select(relationship_memory_proposal_evidence.c.entity_observation_id)
            .where(relationship_memory_proposal_evidence.c.memory_proposal_id == proposal_id)
            .order_by(relationship_memory_proposal_evidence.c.entity_observation_id)
        ).scalars()
        cases = relationship_memory_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)

    assert held.memory_proposal_id == proposal_id
    assert held.proposed_statement == PROPOSED_NOTE
    assert list(evidence) == sorted(observations)
    assert [case.review_case_id for case in cases] == [review_case_id]
    assert cases[0].latest_disposition is Disposition.INVALIDATE
    assert cases[0].review_version == 1


def test_an_accepted_case_cannot_then_be_invalidated(two_principals: Engine) -> None:
    """The terminal-acceptance guard covers the new disposition too.

    Worth asserting rather than assuming: an invalidation stamps the proposal's
    state, and stamping `invalidated` over an accepted candidate would leave a
    promoted memory whose proposal denies having produced it — and would have to
    strip `accepted_memory_id` to satisfy the schema. The case is terminal, so
    nothing of the sort happens.
    """
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection)
    with two_principals.begin() as connection:
        decide_relationship_memory_review(connection, _decision(review_case_id, Disposition.ACCEPT))
    with two_principals.connect() as connection:
        after_acceptance = _counts(connection)

    with two_principals.begin() as connection, pytest.raises(ReviewConflictError):
        decide_relationship_memory_review(
            connection,
            _decision(review_case_id, Disposition.INVALIDATE, expected_review_version=1),
        )

    with two_principals.connect() as connection:
        stamped = _proposal_row(connection, proposal_id)
        assert _counts(connection) == after_acceptance
    assert stamped.state == MemoryProposalState.ACCEPTED.value
    assert stamped.accepted_memory_id is not None
    assert stamped.invalidated_reason is None


# --- the reason column's own constraints --------------------------------------


def test_the_ledger_refuses_an_invalidation_that_states_no_reason(
    two_principals: Engine,
) -> None:
    """Asked of the server, not of the request that would have refused first.

    `ReviewDecisionRequest` will not build an invalidation without a reason, but
    a request object is not what a database enforces. The CHECK is what makes
    "an invalidated candidate says why" true of every row that exists, including
    rows a later writer inserts by some other route.
    """
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection)

    with two_principals.connect() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(_ledger_insert(proposal_id, review_case_id, Disposition.INVALIDATE))
    assert "a_memory_invalidation_states_why" in str(refused.value)


def test_the_ledger_refuses_a_reason_on_a_disposition_that_explains_nothing(
    two_principals: Engine,
) -> None:
    """A reason explains a departure; an acceptance is not one.

    The same sentence `entity_proposal_review_decisions` makes, and the reason it
    matters here: a reason attached to an acceptance would attribute a refusal to
    a decision nobody refused, which is the class of false record this ledger's
    other CHECKs exist to refuse.
    """
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection)

    with two_principals.connect() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(
            _ledger_insert(proposal_id, review_case_id, Disposition.ACCEPT, reason=MOOT_BASIS)
        )
    assert "a_memory_review_reason_explains_a_departure" in str(refused.value)


@pytest.mark.parametrize(("reason", "label"), [("   ", "blank"), ("m" * 501, "over the bound")])
def test_the_ledger_refuses_a_reason_that_is_blank_or_unbounded(
    two_principals: Engine, reason: str, label: str
) -> None:
    """`REVIEW_REASON_LIMIT` is 500, and a whitespace reason says nothing.

    Both halves, because a bound that admitted `'   '` would let an invalidation
    satisfy "states why" with no statement in it — which is the failure the
    column was added to prevent, arrived at from the other side.
    """
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection)

    with two_principals.connect() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(
            _ledger_insert(proposal_id, review_case_id, Disposition.INVALIDATE, reason=reason)
        )
    assert "a_memory_review_reason_is_bounded" in str(refused.value), label


@pytest.mark.parametrize(
    "disposition",
    [Disposition.REJECT, Disposition.DEFER, Disposition.MARK_UNRESOLVED],
)
def test_the_reason_column_admits_and_still_permits_an_omitted_reason(
    two_principals: Engine, disposition: Disposition
) -> None:
    """The additive half: what the ledger took before, it still takes.

    The three dispositions section 13 gives a reason may state one and may leave
    it out, exactly as they could before the column existed — every capture and
    GoodNotes reviewer that ships today sends no reason on any of them, and a
    column that made one mandatory would have been a regression dressed as a
    constraint. Both rows are written and read back.
    """
    with two_principals.begin() as connection:
        first_id, first_case, _, _ = _open_proposal(connection)
        second_id, second_case, _, _ = _open_proposal(connection)

    with two_principals.begin() as connection:
        connection.execute(_ledger_insert(first_id, first_case, disposition, reason="stated"))
        connection.execute(_ledger_insert(second_id, second_case, disposition))

    with two_principals.connect() as connection:
        stated = _ledger_rows(connection, first_case)
        silent = _ledger_rows(connection, second_case)

    assert [row.reason for row in stated] == ["stated"]
    assert [row.reason for row in silent] == [None]


def test_a_correction_still_matches_its_disposition_beside_the_new_column(
    two_principals: Engine,
) -> None:
    """The CHECK that was already here is untouched, proved by asking it again.

    `WP-RI-B-05` adds a column and three constraints to this table and relaxes
    none. `a_memory_correction_matches_its_disposition` still refuses a
    corrected statement on any disposition but `correct_and_accept`, including
    the new one, so the additive claim is measured rather than asserted.
    """
    with two_principals.begin() as connection:
        proposal_id, review_case_id, _, _ = _open_proposal(connection)

    with two_principals.connect() as connection, pytest.raises(DBAPIError) as refused:
        connection.execute(
            _ledger_insert(
                proposal_id,
                review_case_id,
                Disposition.INVALIDATE,
                reason=MOOT_BASIS,
                corrected_statement=CORRECTED_NOTE,
            )
        )
    assert "a_memory_correction_matches_its_disposition" in str(refused.value)


# --- what each disposition sends to the server --------------------------------
#
# The claim `RM-API-AC-002` makes per branch — "`review.decide` on
# `mark_unresolved` writes one of the eight" — is derived by an AST walk in
# `tests/architecture/test_every_capability_reaching_a_memory_row_is_declared.py`,
# and that walk binds the row to itself. What it cannot do is notice that it is
# wrong: it evaluates a guard on a value pulled out of a member-keyed mapping by
# remembering which members the mapping sends to `None`, and it does not
# invalidate that memory when the local is reassigned. Two lines —
#
#     stored_state = _STORED_STATE[request.disposition]
#     if stored_state is None:
#         stored_state = MemoryProposalState.NEEDS_REVIEW
#     if stored_state is not None:        # always true at runtime
#
# — leave the walk deciding the second guard `False` for `mark_unresolved`, so
# the derived itinerary still says one table while the server is sent an UPDATE
# on a second. Every architecture test stayed green under exactly that edit, and
# so did every test in this module, because the stray UPDATE writes
# `needs_review` and the assertion that reads the stored state back accepts it.
#
# So the itinerary is measured once where nothing is parsed and nothing is
# inferred: from the statements PostgreSQL is handed.


@contextmanager
def _statements_sent_to(engine: Engine) -> Iterator[list[str]]:
    """Every SQL statement the server is sent over `engine` inside the block.

    `before_cursor_execute` fires on the compiled statement on its way out, so
    what is collected is what the driver sends and not what a reading of the
    persistence module predicts it will send. The listener is removed on the way
    out, because an engine here is shared with the fixtures that seeded it.
    """
    seen: list[str] = []

    def record(
        _connection: object,
        _cursor: object,
        statement: str,
        _parameters: object,
        _context: object,
        _executemany: bool,
    ) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    try:
        yield seen
    finally:
        event.remove(engine, "before_cursor_execute", record)


#: `INSERT INTO knowledge.relationship_memory_versions (…)`, and the two other
#: verbs that change a row. Matched on the plane's shared table prefix rather
#: than on a list of the eight, and stopping a letter short of
#: `relationship_memory_` so `relationship_memories` is included: the assertion
#: below is an equality, so a name outside the expectation fails by appearing.
_WRITE_STATEMENT: Final = re.compile(
    r"\b(?:INSERT\s+INTO|UPDATE|DELETE\s+FROM)\s+(?:\w+\.)?(relationship_memor\w*)",
    re.IGNORECASE,
)


def _memory_tables_written(statements: list[str]) -> frozenset[str]:
    """The memory-plane tables `statements` change, read off the SQL itself."""
    return frozenset(
        name.lower() for statement in statements for name in _WRITE_STATEMENT.findall(statement)
    )


#: Per disposition, the memory-plane tables a decision on a memory case makes
#: the server change.
#:
#: Stated here and compared to the wire, which is the whole point: this is the
#: one place the per-branch claim is not derived from the same source the claim
#: is about. The test parametrizes over `Disposition` itself and asserts this
#: mapping covers it, so a disposition added to the router arrives unstated
#: rather than unmeasured.
#:
#: An empty set means the router refuses the disposition before its first
#: statement, and the test requires the refusal and the emptiness together —
#: writing nothing because the request raised and writing nothing because the
#: branch had nothing to write are different facts, and one standing in for the
#: other is how a route could be removed without notice.
_TABLES_WRITTEN_PER_DISPOSITION: Final[dict[Disposition, frozenset[str]]] = {
    Disposition.ACCEPT: frozenset(
        {
            "relationship_memories",
            "relationship_memory_versions",
            "relationship_memory_evidence_links",
            "relationship_memory_review_decisions",
            "relationship_memory_proposals",
        }
    ),
    Disposition.CORRECT_AND_ACCEPT: frozenset(
        {
            "relationship_memories",
            "relationship_memory_versions",
            "relationship_memory_evidence_links",
            "relationship_memory_review_decisions",
            "relationship_memory_proposals",
        }
    ),
    Disposition.REJECT: frozenset(
        {"relationship_memory_review_decisions", "relationship_memory_proposals"}
    ),
    Disposition.DEFER: frozenset(
        {"relationship_memory_review_decisions", "relationship_memory_proposals"}
    ),
    Disposition.MARK_UNRESOLVED: frozenset({"relationship_memory_review_decisions"}),
    #: `WP-RI-B-05`, Manager ruling R-8. `reject`'s two tables and none of the
    #: three promotion tables, which is "invalidate creates no canonical record"
    #: read off the wire. That it is not *the same act* as a reject is a claim
    #: about the values written and is held next door.
    Disposition.INVALIDATE: frozenset(
        {"relationship_memory_review_decisions", "relationship_memory_proposals"}
    ),
    Disposition.REPROCESS: frozenset(
        {
            "relationship_memory_review_decisions",
            "relationship_memory_proposal_evidence",
            "relationship_memory_proposals",
        }
    ),
    Disposition.ESCALATE: frozenset({"relationship_memory_review_decisions"}),
}


@pytest.mark.parametrize("disposition", list(Disposition), ids=lambda member: member.value)
def test_every_disposition_writes_exactly_the_memory_tables_it_is_declared_to(
    two_principals: Engine, disposition: Disposition
) -> None:
    """One decision, and the tables its statements actually change.

    The proposal carries one piece of evidence, which is what puts
    `relationship_memory_evidence_links` in the two accepting branches; an
    evidence-free acceptance writes four of these five and is held next door by
    `test_an_acceptance_with_no_evidence_is_confirmed_rather_than_source_backed`.

    Statements rather than row counts, because a row count cannot tell an UPDATE
    that changes nothing from an UPDATE that was never sent — and the branch this
    exists to hold, `mark_unresolved`, is exactly the one whose escape looks like
    a no-op UPDATE stamping the state it already had.
    """
    assert set(_TABLES_WRITTEN_PER_DISPOSITION) == set(Disposition), (
        f"{sorted(set(Disposition) ^ set(_TABLES_WRITTEN_PER_DISPOSITION))} is a "
        "disposition the router publishes with no declared write set here, or a write "
        "set for a disposition that no longer exists. `RM-API-AC-002` states one "
        "sentence per member and this is the measurement behind them"
    )
    expected = _TABLES_WRITTEN_PER_DISPOSITION[disposition]

    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)

    with (
        _statements_sent_to(two_principals) as statements,
        two_principals.begin() as connection,
    ):
        decide_relationship_memory_review(
            connection,
            _decision(
                review_case_id,
                disposition,
                corrected_value=(
                    CORRECTED_NOTE
                    if disposition is Disposition.CORRECT_AND_ACCEPT
                    else None
                ),
            ),
        )

    assert statements, (
        "no statement reached the server at all; the listener is not attached and this "
        "test is measuring nothing"
    )
    written = _memory_tables_written(statements)
    assert written == expected, (
        f"deciding `{disposition.value}` sends the server statements that write "
        f"{sorted(written)}; it is declared to write {sorted(expected)}. If the router "
        "moved, `RM-API-AC-002`'s sentence for this branch and the architecture guard's "
        "`DECLARED_BRANCH_WRITES` move with it"
    )


# --- conflict, staleness, and a subject that moved ----------------------------


def test_a_second_acceptance_is_refused_and_creates_no_second_memory(
    two_principals: Engine,
) -> None:
    """Terminal, and asserted as a row count as well as as a raised conflict."""
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)
    with two_principals.begin() as connection:
        decide_relationship_memory_review(connection, _decision(review_case_id, Disposition.ACCEPT))
    with two_principals.connect() as connection:
        after_first = _counts(connection)

    with two_principals.begin() as connection, pytest.raises(ReviewConflictError):
        decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.ACCEPT, expected_review_version=1)
        )

    with two_principals.connect() as connection:
        assert _counts(connection) == after_first
        assert after_first["relationship_memories"] == 1


def test_a_stale_expected_review_version_is_refused(two_principals: Engine) -> None:
    """One decision stands; a writer holding the version before it writes nothing."""
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)
    with two_principals.begin() as connection:
        decide_relationship_memory_review(connection, _decision(review_case_id, Disposition.DEFER))
    with two_principals.connect() as connection:
        after_first = _counts(connection)

    with two_principals.begin() as connection, pytest.raises(ReviewConflictError):
        decide_relationship_memory_review(
            connection, _decision(review_case_id, Disposition.ACCEPT, expected_review_version=0)
        )

    with two_principals.connect() as connection:
        assert _counts(connection) == after_first


def test_a_merged_away_subject_is_refused_rather_than_promoted_onto_its_successor(
    two_principals: Engine,
) -> None:
    """Following the redirect would bind a reviewed candidate to a different person."""
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection, subject_entity_id=OLD_DANA)
        before = _counts(connection)

    with two_principals.begin() as connection, pytest.raises(ReviewConflictError):
        decide_relationship_memory_review(connection, _decision(review_case_id, Disposition.ACCEPT))

    with two_principals.connect() as connection:
        # No memory, and no decision row either: a stored acceptance whose
        # promotion did not happen would be the worse of the two outcomes.
        assert _counts(connection) == before
        dana = SqlRelationshipMemoryRepository(connection).page_for_entity(
            DANA, principal_id=PRINCIPAL_A, limit=10
        )
    assert dana.memories == ()


def test_a_person_only_kind_is_refused_for_a_subject_that_is_not_a_person(
    two_principals: Engine,
) -> None:
    """The kind rule holds on the promotion path, not only on the public one."""
    project = "ent_dddd0004dddd0004"
    with two_principals.begin() as connection:
        SqlEntityRepository(connection).create(
            PRINCIPAL_A,
            Entity(
                entity_id=project,
                principal_id=PRINCIPAL_A,
                entity_type=EntityType.PROJECT,
                canonical_name=normalize_name("Riverside Synthetic"),
                display_name="Riverside Synthetic",
                status=EntityStatus.ACTIVE,
                created_at=WHEN,
                updated_at=WHEN,
                version=1,
            ),
        )
        _, review_case_id, _, _ = _open_proposal(
            connection,
            subject_entity_id=project,
            kind=MemoryKind.INTEREST,
            statement="Synthetic subject enjoys synthetic sailing.",
        )
        before = _counts(connection)

    with two_principals.begin() as connection, pytest.raises(ReviewConflictError):
        decide_relationship_memory_review(connection, _decision(review_case_id, Disposition.ACCEPT))

    with two_principals.connect() as connection:
        assert _counts(connection) == before


# --- the partition ------------------------------------------------------------


def test_another_principals_proposal_is_invisible_and_undecidable(
    two_principals: Engine,
) -> None:
    """The same answer an absent identifier gets, asserted as an equality."""
    with two_principals.begin() as connection:
        _, foreign_case, _, _ = _open_proposal(
            connection, principal_id=PRINCIPAL_B, subject_entity_id=FOREIGN_PERSON
        )
    absent_case = issue_identifier(IdKind.REVIEW_CASE)

    with two_principals.begin() as connection:
        mine = relationship_memory_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)
        theirs = relationship_memory_review_cases(connection, principal_id=PRINCIPAL_B, limit=10)
        routed_foreign = is_relationship_memory_review_case(
            connection, review_case_id=foreign_case, principal_id=PRINCIPAL_A
        )
        routed_absent = is_relationship_memory_review_case(
            connection, review_case_id=absent_case, principal_id=PRINCIPAL_A
        )
        before = _counts(connection)

    assert mine == ()
    assert len(theirs) == 1, "B's own proposal really exists, so A's empty page means something"
    assert routed_foreign == routed_absent

    with two_principals.begin() as connection, pytest.raises(ReviewNotFoundError):
        decide_relationship_memory_review(connection, _decision(foreign_case, Disposition.ACCEPT))

    with two_principals.connect() as connection:
        assert _counts(connection) == before


# --- the plane is composed, or it is not reached ------------------------------
#
# Everything above calls `relationship_memory_review.py` directly, which is the
# right scope for asserting what a promotion does. It cannot say whether a
# composed build reaches that code at all, and `_Reviews` used to reach it
# unconditionally: a process that had never enabled Relationship Memory still ran
# the memory query on every `review.list` and still routed every `review.decide`
# through the memory case test. These two tests are about the route rather than
# the promotion, so they go through `SqlAlchemyUnitOfWork` — the object the
# composition root actually builds.


def _reviews_of(engine: Engine, *, composed: bool) -> SqlAlchemyUnitOfWork:
    """One unit of work built the way `bootstrap.gateway` builds it."""
    return SqlAlchemyUnitOfWork(
        engine, audit=SqlAlchemyAuditSink(engine), relationship_memory_enabled=composed
    )


def test_a_build_without_the_memory_plane_composed_never_reaches_a_memory_case(
    two_principals: Engine,
) -> None:
    """`review.list` in a build that does not have the plane discloses nothing from it.

    The proposal, its evidence and its review case are all in the database, so an
    empty answer is the composition refusing to look rather than an empty
    fixture. The composed unit of work is asked the same question in the same
    test and answers with the case — which is what stops the uncomposed empty
    result being read as "this query never returns anything".

    What the case would have carried is named rather than left implicit: a
    `subject_entity_id` and a `proposed_kind` about a person, in front of a
    reviewer of a product whose eight `relationship_memory.` capability names
    `available_capabilities` withholds.
    """
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)

    with _reviews_of(two_principals, composed=False) as uncomposed:
        withheld = uncomposed.reviews.cases(limit=10, principal_id=PRINCIPAL_A)
    with _reviews_of(two_principals, composed=True) as composed:
        disclosed = composed.reviews.cases(limit=10, principal_id=PRINCIPAL_A)

    assert withheld == ()
    assert [case.review_case_id for case in disclosed] == [review_case_id]
    assert [getattr(case, "subject_entity_id", None) for case in disclosed] == [DANA]


def test_deciding_a_memory_case_in_an_uncomposed_build_answers_as_an_absent_one(
    two_principals: Engine,
) -> None:
    """`review.decide` must not let the router disclose what the listing withheld.

    Both directions, because either alone is satisfiable by the wrong fix. The
    refusal has to be the *same* refusal an invented identifier gets, or a
    reviewer could learn that an identifier names a memory case by watching the
    two behave differently; and the promotion tables have to be unchanged, or the
    plane was reached after all. The composed build then accepts the same case,
    so the refusal is the composition and not a broken fixture.
    """
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)
        before = _counts(connection)
    absent_case = issue_identifier(IdKind.REVIEW_CASE)

    with _reviews_of(two_principals, composed=False) as uncomposed:
        with pytest.raises(ReviewNotFoundError) as refused:
            uncomposed.reviews.decide(_decision(review_case_id, Disposition.ACCEPT))
        with pytest.raises(ReviewNotFoundError) as absent:
            uncomposed.reviews.decide(_decision(absent_case, Disposition.ACCEPT))
    assert str(refused.value) == str(absent.value)

    with two_principals.connect() as connection:
        assert _counts(connection) == before

    with _reviews_of(two_principals, composed=True) as composed:
        decision = composed.reviews.decide(_decision(review_case_id, Disposition.ACCEPT))
    assert decision is not None
    assert decision.proposal_state is ProposalState.ACCEPTED


# --- the producer, against the schema it has to satisfy -----------------------
#
# Every other test in this module seeds its candidate by hand. That is the right
# fixture for a suite about *decisions*, and it is the wrong evidence for one
# claim: that the record `RelationshipMemoryProposalService` builds is a record
# this database will actually take. A hand-written row proves the columns accept
# some value; it cannot prove the service fills them, because the service was not
# involved in writing it.
#
# `_InsertOnlyProposals` is the producer's whole persistence surface — one
# insert, exactly as `RelationshipMemoryProposalRepository` declares it — and it
# lives here rather than in `src/` because the infrastructure implementation
# lands with the capability that routes to it. It is also the reference shape for
# that implementation: an insert of the domain records, unaltered.


class _InsertOnlyProposals:
    """`RelationshipMemoryProposalRepository`, over the two tables PR #147 created."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def record_proposal(
        self,
        proposal: RelationshipMemoryProposal,
        evidence: tuple[MemoryProposalEvidence, ...],
    ) -> None:
        self._connection.execute(
            insert(relationship_memory_proposals).values(
                memory_proposal_id=proposal.memory_proposal_id,
                principal_id=proposal.principal_id,
                subject_entity_id=proposal.subject_entity_id,
                expected_subject_version=proposal.expected_subject_version,
                proposed_kind=proposal.proposed_kind.value,
                proposed_statement=proposal.proposed_statement,
                proposed_statement_sha256=proposal.proposed_statement_sha256,
                structured_value=proposal.structured_value,
                state=proposal.state.value,
                method=proposal.method.value,
                method_version=proposal.method_version,
                model_id=proposal.model_id,
                model_version=proposal.model_version,
                classification=proposal.classification.value,
                proposed_at=proposal.proposed_at,
                review_case_id=proposal.review_case_id,
                accepted_memory_id=proposal.accepted_memory_id,
                accepted_memory_version_id=proposal.accepted_memory_version_id,
                invalidated_reason=proposal.invalidated_reason,
                superseded_at=proposal.superseded_at,
                superseded_by_memory_proposal_id=(
                    proposal.superseded_by_memory_proposal_id
                ),
            )
        )
        for link in evidence:
            self._connection.execute(
                insert(relationship_memory_proposal_evidence).values(
                    proposal_evidence_id=link.proposal_evidence_id,
                    memory_proposal_id=link.memory_proposal_id,
                    principal_id=link.principal_id,
                    role=link.role.value,
                    entity_observation_id=link.entity_observation_id,
                    capture_span_id=link.capture_span_id,
                    knowledge_id=link.knowledge_id,
                    created_at=link.created_at,
                )
            )


def _produce(
    connection: Connection,
    *,
    kind: MemoryKind = MemoryKind.WORKING_PREFERENCE,
    statement: str = PROPOSED_NOTE,
    origin: MemoryProposalOrigin | None = None,
) -> MemoryProposalReceipt:
    """One candidate, written the way a producer writes it and nowhere else."""
    return RelationshipMemoryProposalService().propose(
        _InsertOnlyProposals(connection),
        ProposeMemoryCommand(
            principal_id=PRINCIPAL_A,
            subject_entity_id=DANA,
            expected_subject_version=1,
            memory_kind=kind,
            statement=statement,
            structured_value=None,
            evidence=(
                ProposedEvidence(
                    role=EvidenceLinkRole.DIRECT,
                    entity_observation_id=issue_identifier(IdKind.ENTITY_OBSERVATION),
                ),
                ProposedEvidence(
                    role=EvidenceLinkRole.SUPPORTING,
                    capture_span_id=issue_identifier(IdKind.SPAN),
                ),
            ),
        ),
        subject=an_entity(DANA, PRINCIPAL_A, "Dana Synthetic"),
        origin=origin
        or MemoryProposalOrigin(
            method=MemoryProposalMethod.LOCAL_MODEL,
            method_version="synthetic-extractor-v1",
            model_id="synthetic-local-model",
            model_version="2026.08",
        ),
        at=WHEN,
    )


def test_a_candidate_the_producer_writes_is_accepted_by_every_schema_check(
    two_principals: Engine,
) -> None:
    """The columns the service fills are the columns the CHECKs police.

    A local-model origin is used rather than a rule, because it is the shape with
    the most to get wrong: `a_model_proposal_names_its_model` and
    `a_named_proposal_model_states_its_version` are conditional pairings between
    three columns, and a producer that filled two of them would be refused here
    rather than in a later review.
    """
    with two_principals.begin() as connection:
        receipt = _produce(connection)

    with two_principals.connect() as connection:
        row = _proposal_row(connection, receipt.memory_proposal_id)
        links = connection.execute(
            select(relationship_memory_proposal_evidence).where(
                relationship_memory_proposal_evidence.c.memory_proposal_id
                == receipt.memory_proposal_id
            )
        ).all()

    assert row.state == MemoryProposalState.NEEDS_REVIEW.value
    assert row.method == MemoryProposalMethod.LOCAL_MODEL.value
    assert row.model_id == "synthetic-local-model"
    assert row.model_version == "2026.08"
    assert row.classification == Classification.PRIVATE_LOCAL.value
    assert row.accepted_memory_id is None
    assert row.review_case_id == receipt.review_case_id
    assert len(links) == 2
    assert {link.role for link in links} == {
        EvidenceLinkRole.DIRECT.value,
        EvidenceLinkRole.SUPPORTING.value,
    }


def test_a_produced_candidate_reaches_review_and_no_memory_read(
    two_principals: Engine,
) -> None:
    """The producer's whole purpose, end to end: reviewable, and not yet memory.

    `search` is asked for a term the candidate's own statement contains, so the
    empty answer is the two record sets being different tables rather than a
    query that matches nothing.
    """
    with two_principals.begin() as connection:
        receipt = _produce(connection)

    with two_principals.connect() as connection:
        cases = relationship_memory_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)
        memories = SqlRelationshipMemoryRepository(connection)
        page = memories.page_for_entity(DANA, principal_id=PRINCIPAL_A, limit=10)
        found = memories.search("closeout", principal_id=PRINCIPAL_A, limit=10)

    assert [case.review_case_id for case in cases] == [receipt.review_case_id]
    assert cases[0].proposal_state is ProposalState.NEEDS_REVIEW
    assert cases[0].subject_entity_id == DANA
    assert cases[0].accepted_memory_id is None
    assert page.memories == ()
    assert page.withheld_by_policy == 0
    assert found.memories == ()


def test_a_produced_sensitivity_candidate_meets_the_floor_the_schema_demands(
    two_principals: Engine,
) -> None:
    """`a_sensitivity_proposal_is_at_least_restricted` and `classification_floor_for`
    are two statements of one rule, in two layers. This is where they are compared.

    The service chooses the classification; the CHECK decides whether the choice
    was right. If the floor were computed anywhere but from the kind, the insert
    would be refused here rather than at a review.
    """
    with two_principals.begin() as connection:
        receipt = _produce(
            connection,
            kind=MemoryKind.SENSITIVITY,
            statement="Synthetic subject declines evening closeout calls.",
        )

    with two_principals.connect() as connection:
        row = _proposal_row(connection, receipt.memory_proposal_id)
        cases = relationship_memory_review_cases(connection, principal_id=PRINCIPAL_A, limit=10)

    assert row.classification == Classification.RESTRICTED_LOCAL.value
    assert receipt.classification is Classification.RESTRICTED_LOCAL
    # And the reviewer still gets no statement to leak, which is the disclosure
    # control this candidate is the sharpest case of.
    assert not hasattr(cases[0], "proposed_statement")
