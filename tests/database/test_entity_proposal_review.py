"""The Entity plane's review case and decision ledger against a real server.

The unit suite proves the ordering of a decision. This proves the half a fake
cannot: the CHECKs the ledger actually enforces, the unique sequence two racing
reviewers collide on, the composite foreign key that keeps a decision inside its
Principal, the partial unique index that makes a case name one proposal, and —
the property most worth a real transaction — that a refused decision leaves no
ledger row at all.

Five subjects:

1. **The case a proposal opens, read back out of SQL.** `review_version`,
   `escalated` and `latest_disposition` are derived from the ledger rather than
   stored, so a database is the only place to see that the derivation agrees
   with the rows.
2. **The ledger's own refusals.** A correction on a disposition that corrects
   nothing, a reason on a disposition that departs from nothing, an escalation
   with no reason, a sequence reused. Each is a CHECK or a unique, and each is
   reached through SQL because the record refuses first.
3. **Principal isolation.** A decision cannot name another Principal's proposal,
   a case in another partition is not listed, and deciding one is the same
   refusal an invented identifier gets.
4. **The filters run in SQL**, so a narrowed page is a page and not the remains
   of one.
5. **A refused acceptance leaves nothing** — no ledger row, no canonical record,
   and no decision on the proposal.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Connection, Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.application.entity_governance import (
    EntityGovernanceService,
    EntityProposalReviewService,
    ProposalAdmission,
)
from my_pa.application.entity_promotion import StaleTargetVersionError
from my_pa.bootstrap.gateway import GatewayRuntime, build_gateway_runtime
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.ports import ReviewDecisionRequest, WriteRequestResult
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.capture.review import (
    CorrectionPatch,
    Disposition,
    EntityProposalReviewCase,
    ReviewConflictError,
    ReviewDecision,
    ReviewNotFoundError,
    ReviewSubjectKind,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    EntityObservation,
    EntityProposalKind,
    EntityProposalMethod,
    EntityProposalState,
    ObservationKind,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.entity import SqlEntityRepository

# The composed router rather than a test adapter of the same shape. A second
# implementation of `cases`/`decide` in this file would be a second place the
# dispatch could be right, and the thing under test here is the one the server
# actually runs.
from my_pa.infrastructure.persistence.unit_of_work import _Reviews
from my_pa.infrastructure.persistence.write_requests import SqlWriteRequestRepository

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
SCHEMA: Final = "knowledge"
DISPOSABLE_DATABASE: Final = "my_pa_entity_proposal_review_test"

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
ALICE: Final = "ent_aaaa0001aaaa0001"
BOB: Final = "ent_cccc0003cccc0003"
OBSERVATION_A: Final = "eobs_aaaa0001aaaa0001"

SOURCE: Final = "src_aaaa0001aaaa0001"
OBJECT: Final = "obj_aaaa0001aaaa0001"
VERSION: Final = "ver_aaaa0001aaaa0001"
POLICY: Final = "policy-v1"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)

UPDATE_PAYLOAD: Final[dict[str, str | bool]] = {
    "entity_id": ALICE,
    "display_name": "Alice Chen-Okafor",
    "reason": "she married",
}


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _entity(entity_id: str, principal_id: str = PRINCIPAL_A, name: str = "Alice Chen") -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def _observation(observation_id: str, principal_id: str = PRINCIPAL_A) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=principal_id,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Chen <a.chen@example.invalid>",
        normalized_value=normalize_name("Alice Chen"),
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
    )


@pytest.fixture
def staged(disposable_database: str) -> Iterator[Engine]:
    """A migrated database holding two Principals, their entities and one observation."""
    engine = create_database_engine(disposable_database)
    try:
        with engine.begin() as connection:
            repository = SqlEntityRepository(connection)
            repository.create(PRINCIPAL_A, _entity(ALICE))
            repository.create(PRINCIPAL_B, _entity(BOB, PRINCIPAL_B, "Bob Chen"))
            repository.record_observation(PRINCIPAL_A, _observation(OBSERVATION_A))
        yield engine
    finally:
        engine.dispose()


def _reviews(connection: Connection) -> _Reviews:
    return _Reviews(
        connection, relationship_memory_enabled=False, relationship_intelligence_enabled=True
    )


def _propose(
    connection: Connection,
    *,
    principal_id: str = PRINCIPAL_A,
    kind: EntityProposalKind = EntityProposalKind.UPDATE_ENTITY,
    payload: dict[str, str | bool] | None = None,
    expected_target_version: int | None = None,
) -> ProposalAdmission:
    return EntityGovernanceService(SqlEntityRepository(connection)).propose(
        principal_id,
        kind=kind,
        payload=UPDATE_PAYLOAD if payload is None else payload,
        observation_ids=(),
        proposed_by="extractor",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
        at=WHEN,
        expected_target_version=expected_target_version,
    )


def _request(
    review_case_id: str,
    disposition: Disposition,
    *,
    expected_review_version: int = 0,
    reason: str | None = None,
    correction_patch: CorrectionPatch | None = None,
    principal_id: str = PRINCIPAL_A,
) -> ReviewDecisionRequest:
    return ReviewDecisionRequest(
        review_case_id=review_case_id,
        expected_review_version=expected_review_version,
        disposition=disposition,
        principal_id=principal_id,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        policy_version=POLICY,
        decided_at=LATER,
        reason=reason,
        correction_patch=correction_patch,
    )


def _decide(
    connection: Connection,
    request: ReviewDecisionRequest,
    *,
    has_operator_authority: bool = False,
) -> ReviewDecision:
    service = EntityProposalReviewService(SqlEntityRepository(connection), _reviews(connection))
    return service.decide(
        request, decided_by="reviewer", has_operator_authority=has_operator_authority
    )


def _case_id(connection: Connection, proposal_id: str) -> str:
    stored = connection.execute(
        text(f"SELECT review_case_id FROM {SCHEMA}.entity_proposals WHERE proposal_id = :id"),  # noqa: S608
        {"id": proposal_id},
    ).scalar_one()
    return str(stored)


def _ledger_rows(connection: Connection) -> int:
    return int(
        connection.execute(
            text(f"SELECT count(*) FROM {SCHEMA}.entity_proposal_review_decisions")  # noqa: S608
        ).scalar_one()
    )


# --- subject 1: the case, derived from the ledger ----------------------------


def test_a_review_requiring_proposal_opens_a_case_and_lists_on_the_shared_surface(
    staged: Engine,
) -> None:
    with staged.begin() as connection:
        admitted = _propose(connection)

        listed = _reviews(connection).cases(limit=10, principal_id=PRINCIPAL_A)

        assert len(listed) == 1
        case = listed[0]
        assert case.proposal_id == admitted.proposal_id
        assert case.proposal_state is ProposalState.NEEDS_REVIEW
        assert case.review_version == 0
        assert case.latest_disposition is None
        assert case.escalated is False
        assert case.target_entity_id == ALICE


def test_a_threshold_eligible_producer_kind_still_opens_a_case(staged: Engine) -> None:
    """Threshold eligibility does not let a producer bypass canonical Review."""
    with staged.begin() as connection:
        admitted = _propose(
            connection,
            kind=EntityProposalKind.RECORD_ALIAS,
            payload={"entity_id": ALICE, "alias_type": "nickname", "display_value": "Ali"},
        )

        cases = _reviews(connection).cases(limit=10, principal_id=PRINCIPAL_A)

    assert len(cases) == 1
    assert cases[0].proposal_id == admitted.proposal_id
    assert cases[0].proposal_state is ProposalState.NEEDS_REVIEW


def test_the_case_reads_its_version_and_escalation_out_of_the_ledger(staged: Engine) -> None:
    with staged.begin() as connection:
        admitted = _propose(connection)
        case_id = _case_id(connection, admitted.proposal_id)

        _decide(connection, _request(case_id, Disposition.ESCALATE, reason="the operator, please"))

        case = _reviews(connection).entity_proposal_case(PRINCIPAL_A, case_id)
        assert case is not None
        assert case.review_version == 1
        assert case.escalated is True
        assert case.latest_disposition is Disposition.ESCALATE
        assert case.proposal_state is ProposalState.NEEDS_REVIEW


def test_an_accepted_proposal_promotes_and_the_case_names_the_record(staged: Engine) -> None:
    with staged.begin() as connection:
        admitted = _propose(connection)
        case_id = _case_id(connection, admitted.proposal_id)

        _decide(connection, _request(case_id, Disposition.ACCEPT))

        case = _reviews(connection).entity_proposal_case(PRINCIPAL_A, case_id)
        entity = SqlEntityRepository(connection).get(PRINCIPAL_A, ALICE)
        assert case is not None
        assert case.proposal_state is ProposalState.ACCEPTED
        assert case.accepted_record_id == ALICE
        assert entity is not None
        assert entity.display_name == "Alice Chen-Okafor"
        assert entity.version == 2


def test_a_typed_correction_is_stored_on_the_decision_and_not_on_the_proposal(
    staged: Engine,
) -> None:
    """The proposal keeps what a producer asserted; the ledger holds the correction."""
    with staged.begin() as connection:
        admitted = _propose(connection)
        case_id = _case_id(connection, admitted.proposal_id)
        patch = CorrectionPatch.of(
            {"entity_id": ALICE, "display_name": "Alice Okafor", "reason": "she married"}
        )

        _decide(
            connection,
            _request(case_id, Disposition.CORRECT_AND_ACCEPT, correction_patch=patch),
        )

        stored = connection.execute(
            text(
                f"SELECT corrected_payload FROM {SCHEMA}.entity_proposal_review_decisions "  # noqa: S608
                "WHERE review_case_id = :case"
            ),
            {"case": case_id},
        ).scalar_one()
        proposed = connection.execute(
            text(f"SELECT payload FROM {SCHEMA}.entity_proposals WHERE proposal_id = :id"),  # noqa: S608
            {"id": admitted.proposal_id},
        ).scalar_one()
        entity = SqlEntityRepository(connection).get(PRINCIPAL_A, ALICE)
        assert stored["display_name"] == "Alice Okafor"
        assert proposed["display_name"] == "Alice Chen-Okafor"
        assert entity is not None
        assert entity.display_name == "Alice Okafor"


def test_a_reprocess_supersedes_the_predecessor_and_points_at_the_successor(
    staged: Engine,
) -> None:
    """The three statements, in the only order the schema admits."""
    with staged.begin() as connection:
        admitted = _propose(connection)
        case_id = _case_id(connection, admitted.proposal_id)

        _decide(connection, _request(case_id, Disposition.REPROCESS))

        repository = SqlEntityRepository(connection)
        held = repository.proposal(PRINCIPAL_A, admitted.proposal_id)
        assert held is not None
        assert held.state is EntityProposalState.SUPERSEDED
        assert held.superseded_at is not None
        assert held.superseded_by_proposal_id is not None
        successor = repository.proposal(PRINCIPAL_A, held.superseded_by_proposal_id)
        assert successor is not None
        assert successor.state is EntityProposalState.NEEDS_REVIEW
        assert successor.dedupe_sha256 == held.dedupe_sha256
        assert successor.review_case_id not in (None, case_id)


# --- subject 2: what the ledger itself refuses -------------------------------


def _insert_decision(
    connection: Connection, case_id: str, proposal_id: str, **overrides: object
) -> None:
    values: dict[str, object] = {
        "decision_id": issue_identifier(IdKind.REVIEW_DECISION),
        "proposal_id": proposal_id,
        "review_case_id": case_id,
        "principal_id": PRINCIPAL_A,
        "sequence": 1,
        "disposition": Disposition.REJECT.value,
        "reason": "not this one",
        "corrected_payload": None,
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
    }
    values.update(overrides)
    connection.execute(
        text(
            f"INSERT INTO {SCHEMA}.entity_proposal_review_decisions "  # noqa: S608
            "(decision_id, proposal_id, review_case_id, principal_id, sequence, disposition, "
            "reason, corrected_payload, correlation_id, audit_id, decided_at) VALUES "
            "(:decision_id, :proposal_id, :review_case_id, :principal_id, :sequence, "
            ":disposition, :reason, :corrected_payload, :correlation_id, :audit_id, now())"
        ),
        values,
    )


@pytest.mark.parametrize(
    ("overrides", "constraint"),
    [
        (
            {"disposition": "accept", "reason": "why not"},
            "an_entity_review_reason_explains_a_departure",
        ),
        ({"disposition": "escalate", "reason": None}, "an_escalation_or_invalidation_states_why"),
        ({"disposition": "invalidate", "reason": None}, "an_escalation_or_invalidation_states_why"),
        (
            {"disposition": "reject", "corrected_payload": '{"a": "b"}'},
            "an_entity_correction_matches_its_disposition",
        ),
        (
            {"disposition": "correct_and_accept", "reason": None, "corrected_payload": None},
            "an_entity_correction_matches_its_disposition",
        ),
        ({"disposition": "shipped"}, "an_entity_review_disposition_is_known"),
        ({"sequence": 0}, "an_entity_review_sequence_is_positive"),
        ({"reason": "   "}, "an_entity_review_reason_is_bounded"),
    ],
)
def test_the_decision_ledger_refuses_a_row_that_contradicts_itself(
    staged: Engine, overrides: dict[str, object], constraint: str
) -> None:
    """Reached through SQL because the record refuses first, and both should."""
    with staged.begin() as connection:
        admitted = _propose(connection)
        case_id = _case_id(connection, admitted.proposal_id)

        with pytest.raises(IntegrityError, match=constraint):
            _insert_decision(connection, case_id, admitted.proposal_id, **overrides)


def test_two_decisions_cannot_share_one_review_sequence(staged: Engine) -> None:
    """What makes two reviewers who both read version 0 produce one decision."""
    with staged.begin() as connection:
        admitted = _propose(connection)
        case_id = _case_id(connection, admitted.proposal_id)
        _insert_decision(connection, case_id, admitted.proposal_id)

        with pytest.raises(IntegrityError, match="one_entity_decision_per_review_sequence"):
            _insert_decision(connection, case_id, admitted.proposal_id)


def test_a_review_case_names_one_proposal(staged: Engine) -> None:
    """`capture_review_cases` says this with a UNIQUE; this plane says it with an index."""
    with staged.begin() as connection:
        first = _propose(connection)
        case_id = _case_id(connection, first.proposal_id)
        second = _propose(
            connection,
            payload={"entity_id": ALICE, "display_name": "Alicia Chen", "reason": "a nickname"},
        )

        with pytest.raises(IntegrityError, match="a_review_case_names_one_entity_proposal"):
            connection.execute(
                text(
                    f"UPDATE {SCHEMA}.entity_proposals SET review_case_id = :case "  # noqa: S608
                    "WHERE proposal_id = :id"
                ),
                {"case": case_id, "id": second.proposal_id},
            )


# --- subject 3: Principal isolation ------------------------------------------


def test_a_decision_cannot_name_another_principals_proposal(staged: Engine) -> None:
    with staged.begin() as connection:
        admitted = _propose(connection)
        case_id = _case_id(connection, admitted.proposal_id)

        with pytest.raises(
            IntegrityError, match="an_entity_review_decision_names_its_proposals_own_case"
        ):
            _insert_decision(connection, case_id, admitted.proposal_id, principal_id=PRINCIPAL_B)


def test_a_decision_cannot_pair_a_proposal_with_another_proposals_case(staged: Engine) -> None:
    with staged.begin() as connection:
        first = _propose(connection)
        second = _propose(
            connection,
            payload={"entity_id": ALICE, "display_name": "Alicia Chen", "reason": "variant"},
        )
        with pytest.raises(
            IntegrityError, match="an_entity_review_decision_names_its_proposals_own_case"
        ):
            _insert_decision(
                connection, _case_id(connection, second.proposal_id), first.proposal_id
            )


def test_another_principals_case_is_neither_listed_nor_decidable(staged: Engine) -> None:
    """Absent and foreign answer alike, which is what stops a decision probe."""
    with staged.begin() as connection:
        admitted = _propose(connection)
        case_id = _case_id(connection, admitted.proposal_id)

        assert _reviews(connection).cases(limit=10, principal_id=PRINCIPAL_B) == ()
        assert _reviews(connection).entity_proposal_case(PRINCIPAL_B, case_id) is None
        with pytest.raises(ReviewNotFoundError):
            _decide(connection, _request(case_id, Disposition.ACCEPT, principal_id=PRINCIPAL_B))


# --- subject 4: the filters run in SQL ---------------------------------------


def test_the_listing_filters_run_against_the_rows(staged: Engine) -> None:
    with staged.begin() as connection:
        admitted = _propose(connection)
        reviews = _reviews(connection)

        assert (
            reviews.cases(
                limit=10,
                principal_id=PRINCIPAL_A,
                subject_kind=ReviewSubjectKind.ENTITY_PROPOSAL,
            )[0].proposal_id
            == admitted.proposal_id
        )
        assert (
            reviews.cases(
                limit=10,
                principal_id=PRINCIPAL_A,
                subject_kind=ReviewSubjectKind.CAPTURE_PROPOSAL,
            )
            == ()
        )
        assert reviews.cases(limit=10, principal_id=PRINCIPAL_A, state=ProposalState.NEEDS_REVIEW)
        assert reviews.cases(limit=10, principal_id=PRINCIPAL_A, state=ProposalState.ACCEPTED) == ()
        assert reviews.cases(limit=10, principal_id=PRINCIPAL_A, entity_id=ALICE)
        assert reviews.cases(limit=10, principal_id=PRINCIPAL_A, entity_id=BOB) == ()


def test_the_entity_filter_finds_a_merge_proposal_by_the_identity_it_would_remove(
    staged: Engine,
) -> None:
    """A reviewer asking what is outstanding about somebody means every proposal
    that would touch them, including the one that would merge them away."""
    with staged.begin() as connection:
        SqlEntityRepository(connection).create(PRINCIPAL_A, _entity("ent_dddd0004dddd0004"))
        _propose(
            connection,
            kind=EntityProposalKind.MERGE_ENTITIES,
            payload={"retained_entity_id": ALICE, "merged_entity_id": "ent_dddd0004dddd0004"},
        )

        found = _reviews(connection).cases(
            limit=10, principal_id=PRINCIPAL_A, entity_id="ent_dddd0004dddd0004"
        )

        assert len(found) == 1
        assert found[0].proposed_kind is EntityProposalKind.MERGE_ENTITIES


# --- subject 5: a refused decision leaves nothing ----------------------------


def test_a_refused_acceptance_leaves_no_ledger_row_and_no_decision(staged: Engine) -> None:
    """The decision is claimed before the write, so a refusal takes it back.

    This is the property a fake cannot have: `_decide`'s guarded `UPDATE` has
    already run when the promotion refuses, and what puts it back is the
    transaction rather than any code in the review path.
    """
    with staged.begin() as connection:
        admitted = _propose(connection, expected_target_version=1)
        connection.execute(
            text(f"UPDATE {SCHEMA}.entities SET version = 2 WHERE entity_id = :id"),  # noqa: S608
            {"id": ALICE},
        )
    with staged.begin() as connection:
        case_id = _case_id(connection, admitted.proposal_id)

    # The refusal has to leave the *transaction*, not be caught inside it: an
    # exception swallowed in the block would let the block commit, and what is
    # being proved here is that the decision `_decide` already claimed goes back.
    with pytest.raises(StaleTargetVersionError), staged.begin() as connection:
        _decide(connection, _request(case_id, Disposition.ACCEPT))

    with staged.begin() as connection:
        held = SqlEntityRepository(connection).proposal(PRINCIPAL_A, admitted.proposal_id)
        assert _ledger_rows(connection) == 0
        assert held is not None
        assert held.state is EntityProposalState.NEEDS_REVIEW
        assert held.decided_by is None


def test_a_stale_review_version_writes_no_ledger_row(staged: Engine) -> None:
    with staged.begin() as connection:
        admitted = _propose(connection)
        case_id = _case_id(connection, admitted.proposal_id)

        with pytest.raises(ReviewConflictError, match="stale"):
            _decide(
                connection,
                _request(case_id, Disposition.REJECT, expected_review_version=4, reason="no"),
            )

        assert _ledger_rows(connection) == 0
        held = SqlEntityRepository(connection).proposal(PRINCIPAL_A, admitted.proposal_id)
        assert held is not None
        assert held.is_open


def test_an_invalidation_records_its_reason_and_creates_no_canonical_record(
    staged: Engine,
) -> None:
    with staged.begin() as connection:
        admitted = _propose(connection)
        case_id = _case_id(connection, admitted.proposal_id)

        _decide(
            connection,
            _request(case_id, Disposition.INVALIDATE, reason="the subject was merged away"),
        )

        repository = SqlEntityRepository(connection)
        held = repository.proposal(PRINCIPAL_A, admitted.proposal_id)
        entity = repository.get(PRINCIPAL_A, ALICE)
        case = _reviews(connection).entity_proposal_case(PRINCIPAL_A, case_id)
        assert held is not None
        assert held.state is EntityProposalState.INVALIDATED
        assert held.invalidated_reason == "the subject was merged away"
        assert held.accepted_record_id is None
        assert entity is not None
        assert entity.version == 1
        # The case is the proposal, so it presents as invalidated on the shared
        # surface in the same statement rather than standing open behind it.
        assert case is not None
        assert case.proposal_state is ProposalState.INVALIDATED


# --- the composition root, which is where this plane was dark ----------------


def _composed(database_url: str, *, plane: bool) -> GatewayRuntime:
    """One gateway runtime, built the way `apps/gateway.py` builds it."""
    return build_gateway_runtime(
        Settings(
            database_url=database_url,
            relationship_intelligence_enabled=plane,
            relationship_intelligence_writes_enabled=plane,
        )
    )


def test_a_real_build_reaches_the_entity_branch_of_the_shared_review_surface(
    staged: Engine, disposable_database: str
) -> None:
    """`WP-RI-B-07`'s composition-root wiring, proved end to end and not by reading it.

    **This is the failure this test exists for, and it was silent.**
    `SqlAlchemyUnitOfWork.__init__` takes `relationship_intelligence_enabled` and
    passes it to `_Reviews`; the composition root passed nothing, so it defaulted
    closed and no Entity case reached `review.list` in any real build however the
    flag was set. Nothing went red: every existing test of the Entity branch
    constructs `_Reviews` directly with the switch on, which is exactly the shape
    that cannot notice a composition root that never sets it.

    So the unit of work here comes from `build_gateway_runtime`'s own factory,
    through `ApplicationService`, and the assertion is that a staged case *is
    listed* rather than that a field holds `True`. Reading the constructor would
    reproduce the defect rather than catch it.
    """
    with staged.begin() as connection:
        admitted = _propose(connection)

    runtime = _composed(disposable_database, plane=True)
    try:
        with runtime.service._unit_of_work() as unit_of_work:
            listed = unit_of_work.reviews.cases(limit=10, principal_id=PRINCIPAL_A)
    finally:
        runtime.close()

    assert [case.proposal_id for case in listed] == [admitted.proposal_id]
    # And it is the Entity branch's own case type rather than a capture case
    # that happens to carry a matching identifier: `_Reviews.cases` unions four
    # planes, and the type is what says which one answered.
    assert isinstance(listed[0], EntityProposalReviewCase)
    assert listed[0].proposed_kind is EntityProposalKind.UPDATE_ENTITY


def test_a_real_build_without_the_plane_lists_no_entity_case(
    staged: Engine, disposable_database: str
) -> None:
    """The control, and the reason the default is `False` rather than `True`.

    An unwired switch defaulting *open* would put Entity cases in front of a
    reviewer of a build that does not have the plane, which is the defect
    `_Reviews`' own docstring records about the memory branch. So the direction
    matters as much as the wiring: with the plane off, the same staged proposal
    produces no case at all.
    """
    with staged.begin() as connection:
        _propose(connection)

    runtime = _composed(disposable_database, plane=False)
    try:
        with runtime.service._unit_of_work() as unit_of_work:
            listed = unit_of_work.reviews.cases(limit=10, principal_id=PRINCIPAL_A)
    finally:
        runtime.close()

    assert listed == ()


def test_entity_review_replays_its_durable_exact_decision(staged: Engine) -> None:
    with staged.begin() as connection:
        admitted = _propose(connection, expected_target_version=1)
        review_case_id = _case_id(connection, admitted.proposal_id)
        repository = SqlWriteRequestRepository(connection)
        assert (
            repository.reserve(PRINCIPAL_A, "review.decide", "corr_entity_review", "a" * 64) is None
        )
        decision = _decide(connection, _request(review_case_id, Disposition.ACCEPT))
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
        repository.complete(PRINCIPAL_A, "review.decide", "corr_entity_review", "a" * 64, original)

    with staged.begin() as connection:
        replayed = SqlWriteRequestRepository(connection).reserve(
            PRINCIPAL_A, "review.decide", "corr_entity_review", "a" * 64
        )
        count = connection.execute(
            text(
                f"SELECT count(*) FROM {SCHEMA}.entity_proposal_review_decisions "  # noqa: S608
                "WHERE review_case_id = :case_id"
            ),
            {"case_id": review_case_id},
        ).scalar_one()

    assert replayed == original
    assert count == 1
