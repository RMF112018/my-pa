"""Relationship Memory promotion through the Review plane, against a real PostgreSQL server.

Beside `tests/database/test_relationship_memory_repository.py`, which proves the
public write path, and asserting the half that path is *not allowed to reach*: a
source-, rule- or model-derived candidate becomes memory only when a reviewer
decides so (`RM-AC-005`, `RM-AC-016`, `RM-API-AC-011`, `RM-API-AC-012`,
`RM-P-AC-008`).

Five claims carry this path and each is asserted against the server rather than
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

Everything is synthetic: two invented Principals, invented entities, invented
notes. The database is created and dropped by this module's own fixture and is
never the configured one.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import Connection, Engine, Row, insert, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.contracts.ports import MemoryWriteRequest, ReviewDecisionRequest
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import (
    Disposition,
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewUnsupportedError,
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
    MemoryProposalMethod,
    MemoryProposalState,
    classification_floor_for,
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
    relationship_memory_proposal_evidence,
    relationship_memory_proposals,
)
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

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
# Written as direct inserts rather than through a producer, because no producer
# exists yet and inventing one here would make this suite a test of the
# invention. The rows are exactly what a deterministic, rule or local-model
# producer would have to write, and the schema's own CHECKs police that.


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
            proposed_kind=kind.value,
            proposed_statement=statement,
            proposed_statement_sha256=statement_digest(statement),
            structured_value=None,
            state=MemoryProposalState.NEEDS_REVIEW.value,
            method=MemoryProposalMethod.RULE.value,
            method_version="synthetic-rule-v1",
            model_id=None,
            model_version=None,
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
    at: datetime = LATER,
) -> ReviewDecisionRequest:
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


@pytest.mark.parametrize(
    "disposition",
    [Disposition.REPROCESS, Disposition.ESCALATE],
)
def test_a_disposition_with_no_route_is_unsupported(
    two_principals: Engine, disposition: Disposition
) -> None:
    with two_principals.begin() as connection:
        _, review_case_id, _, _ = _open_proposal(connection)
        before = _counts(connection)

    with two_principals.begin() as connection, pytest.raises(ReviewUnsupportedError):
        decide_relationship_memory_review(connection, _decision(review_case_id, disposition))

    with two_principals.connect() as connection:
        assert _counts(connection) == before


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
