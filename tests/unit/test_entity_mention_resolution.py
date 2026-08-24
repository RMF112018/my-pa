"""Deciding what one unresolved mention refers to, and refusing to.

Three of the five dispositions are refusals, and that ratio is the design rather
than an omission: section 15.2 requires an ambiguous mention to stay unresolved
rather than be forced into the nearest person, so *not* resolving has to be an
ordinary recorded decision. Every test here names a route by which this plane
could decide an identity nobody chose, and asserts it is closed.

**Nothing here picks a candidate.** `link_existing` binds the entity the caller
named and no other; `create_new` is admitted only on a fresh `not_found`. There
is no branch that reads a candidate list and takes the first, the best, or the
only one — and the tests below drive the arrangements where each of those would
be tempting.

**A refusal has a durable effect.** A `reject` naming an entity writes
counterevidence, and the next resolution of that mention withholds the refused
pairing. That is the whole of "a known-bad pairing is not repeatedly proposed",
and it is asserted here against the resolver rather than against a comment.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.entity_governance import (
    EntityGovernanceService,
    MentionResolution,
    QuarantinedObservationError,
    ResolutionNotPermittedError,
    ResolveMentionCommand,
    UnknownObservationError,
)
from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.domain.relationship.entity import (
    Entity,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.governance import (
    NEGATIVE_IDENTITY_EVIDENCE_ROLE,
    ActorClass,
    EntityMutationConflictError,
    EntityObservation,
    EvidenceRole,
    ObservationKind,
    ObservationState,
    ResolutionDisposition,
    StaleResolutionVersionError,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.resolution import EntityResolution, ResolutionOutcome
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER = "prn_bbbb0002bbbb0002bbbb0002"
ALICE = "ent_aaaa0001aaaa0001"
ALICE_TWO = "ent_bbbb0002bbbb0002"

MENTION = "eobs_aaaa0001aaaa01"
FOREIGN_MENTION = "eobs_ffff0009ffff09"

SOURCE = "src_aaaa0001aaaa0001"
OBJECT = "obj_aaaa0001aaaa0001"
VERSION = "ver_aaaa0001aaaa0001"

CORRELATION = "corr_aaaa0001aaaa0001"
AUDIT = "audit_aaaa0001aaaa01"

WHEN = datetime(2026, 8, 18, 12, tzinfo=UTC)
LATER = WHEN + timedelta(hours=1)

REFERENCE = "Alice Chen"


def an_entity(entity_id: str, principal_id: str = PRINCIPAL, name: str = REFERENCE) -> Entity:
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


def a_mention(
    observation_id: str = MENTION,
    principal_id: str = PRINCIPAL,
    *,
    state: ObservationState = ObservationState.CURRENT,
    state_reason: str | None = None,
) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=principal_id,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value=REFERENCE,
        normalized_value=normalize_name(REFERENCE),
        mention_display_name=REFERENCE,
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
        state=state,
        state_reason=state_reason,
    )


@pytest.fixture
def staged(world: World) -> World:
    """One entity the caller owns, and one mention nothing has placed."""
    entities = FakeUnitOfWork(world).entities
    entities.create(PRINCIPAL, an_entity(ALICE))
    entities.record_observation(PRINCIPAL, a_mention())
    return world


def _service(world: World) -> EntityGovernanceService:
    return EntityGovernanceService(FakeUnitOfWork(world).entities)


def _resolver(world: World):  # noqa: ANN202
    """The fresh in-transaction resolution the use case is handed.

    Built here exactly as `ApplicationService` builds it, so what these tests
    exercise is the resolution the capability actually runs rather than a
    convenient stand-in.
    """
    service = EntityResolutionService(FakeUnitOfWork(world).entities)

    def resolve(
        observation: EntityObservation, refused: frozenset[str], at: datetime
    ) -> EntityResolution:
        return service.resolve(
            observation.principal_id,
            ResolutionRequest(
                raw_reference=observation.observed_value, at=at, refused_entity_ids=refused
            ),
        )

    return resolve


def a_command(**overrides: object) -> ResolveMentionCommand:
    fields: dict[str, object] = {
        "principal_id": PRINCIPAL,
        "observation_id": MENTION,
        "expected_resolution_version": 0,
        "disposition": ResolutionDisposition.DEFER,
        "idempotency_key": "resolve-0001",
        "reason": "there is not enough identity evidence yet",
    }
    fields.update(overrides)
    return ResolveMentionCommand(**fields)  # type: ignore[arg-type]


def _decide(
    world: World,
    command: ResolveMentionCommand,
    *,
    at: datetime = WHEN,
    actor_class: ActorClass = ActorClass.USER,
) -> MentionResolution:
    return _service(world).resolve_mention(
        command,
        resolve=_resolver(world),
        at=at,
        correlation_id=CORRELATION,
        audit_id=AUDIT,
        decided_by=command.principal_id,
        actor_class=actor_class,
    )


# --- the vocabulary -----------------------------------------------------------


def test_the_disposition_vocabulary_is_the_five_the_contract_freezes() -> None:
    assert {member.value for member in ResolutionDisposition} == {
        "link_existing",
        "create_new",
        "reject",
        "defer",
        "quarantine",
    }


@pytest.mark.parametrize(
    "disposition",
    [ResolutionDisposition.REJECT, ResolutionDisposition.DEFER, ResolutionDisposition.QUARANTINE],
)
def test_every_refusal_is_recorded_as_a_decision_rather_than_as_an_absence(
    staged: World, disposition: ResolutionDisposition
) -> None:
    """A refusal is a recorded decision, not the absence of one.

    "We looked and declined" has to be distinguishable from "nobody looked".
    """
    decided = _decide(staged, a_command(disposition=disposition))
    assert decided.entity_id is None
    assert decided.disposition is disposition
    assert decided.resolution_version == 1
    held = staged.entity_resolution_decisions
    assert [row.disposition for row in held] == [disposition]
    assert held[0].sequence == 1
    assert held[0].expected_resolution_version == 0


def test_a_quarantine_moves_the_observation_out_of_current_and_says_why(
    staged: World,
) -> None:
    _decide(staged, a_command(disposition=ResolutionDisposition.QUARANTINE))
    held = FakeUnitOfWork(staged).entities.observation(PRINCIPAL, MENTION)
    assert held is not None
    assert held.state is ObservationState.QUARANTINED
    assert held.state_reason == "there is not enough identity evidence yet"


def test_a_quarantined_observation_does_not_bind_an_entity(world: World) -> None:
    """Untrusted input must not end up behind a canonical fact."""
    entities = FakeUnitOfWork(world).entities
    entities.create(PRINCIPAL, an_entity(ALICE))
    entities.record_observation(
        PRINCIPAL,
        a_mention(state=ObservationState.QUARANTINED, state_reason="not trustworthy input"),
    )
    with pytest.raises(QuarantinedObservationError):
        _decide(
            world,
            a_command(
                disposition=ResolutionDisposition.LINK_EXISTING,
                entity_id=ALICE,
                expected_entity_version=1,
                reason=None,
            ),
        )
    assert world.entity_resolution_decisions == []


# --- link_existing ------------------------------------------------------------


def test_link_existing_binds_the_entity_the_caller_named(staged: World) -> None:
    decided = _decide(
        staged,
        a_command(
            disposition=ResolutionDisposition.LINK_EXISTING,
            entity_id=ALICE,
            expected_entity_version=1,
            reason=None,
        ),
    )
    assert decided.entity_id == ALICE
    held = FakeUnitOfWork(staged).entities.observation(PRINCIPAL, MENTION)
    assert held is not None
    assert held.entity_id == ALICE
    assert held.resolution_version == 1


def test_link_existing_refuses_a_stale_entity_version(staged: World) -> None:
    with pytest.raises(ResolutionNotPermittedError) as refused:
        _decide(
            staged,
            a_command(
                disposition=ResolutionDisposition.LINK_EXISTING,
                entity_id=ALICE,
                expected_entity_version=7,
                reason=None,
            ),
        )
    assert refused.value.detail == "stale_version"
    assert staged.entity_resolution_decisions == []


def test_link_existing_refuses_an_entity_that_is_no_longer_current(world: World) -> None:
    entities = FakeUnitOfWork(world).entities
    entities.create(
        PRINCIPAL,
        Entity(
            entity_id=ALICE,
            principal_id=PRINCIPAL,
            entity_type=EntityType.PERSON,
            canonical_name=normalize_name(REFERENCE),
            display_name=REFERENCE,
            status=EntityStatus.HISTORICAL,
            created_at=WHEN,
            updated_at=WHEN,
            version=1,
        ),
    )
    entities.record_observation(PRINCIPAL, a_mention())
    with pytest.raises(ResolutionNotPermittedError) as refused:
        _decide(
            world,
            a_command(
                disposition=ResolutionDisposition.LINK_EXISTING,
                entity_id=ALICE,
                expected_entity_version=1,
                reason=None,
            ),
        )
    assert refused.value.detail == "historical_entity"


def test_link_existing_refuses_while_the_identifier_is_conflicted(world: World) -> None:
    """A conflict is a data defect. Choosing between the claimants is not a fix.

    Stated with a resolution the use case is handed rather than by staging a
    reissued mailbox, because what is under test is that a `conflicted_identifier`
    answer *vetoes* the binding — not how the resolver reaches one, which
    `tests/unit/test_entity_resolution.py` already holds.
    """
    entities = FakeUnitOfWork(world).entities
    entities.create(PRINCIPAL, an_entity(ALICE))
    entities.record_observation(PRINCIPAL, a_mention())

    def conflicted(*_: object) -> EntityResolution:
        return EntityResolution(
            outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
            candidates=(),
            warnings=(),
        )

    with pytest.raises(Exception, match=r"conflicted|candidate"):
        _service(world).resolve_mention(
            a_command(
                disposition=ResolutionDisposition.LINK_EXISTING,
                entity_id=ALICE,
                expected_entity_version=1,
                reason=None,
            ),
            resolve=conflicted,  # type: ignore[arg-type]
            at=WHEN,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            decided_by=PRINCIPAL,
            actor_class=ActorClass.USER,
        )


# --- create_new ---------------------------------------------------------------


def test_create_new_succeeds_on_a_fresh_not_found(world: World) -> None:
    """Nothing this reference matches, so a new record is not a duplicate."""
    FakeUnitOfWork(world).entities.record_observation(PRINCIPAL, a_mention())
    decided = _decide(
        world,
        a_command(
            disposition=ResolutionDisposition.CREATE_NEW,
            entity_type=EntityType.PERSON,
            canonical_name=REFERENCE,
            reason=None,
        ),
    )
    assert decided.entity_id is not None
    created = FakeUnitOfWork(world).entities.get(PRINCIPAL, decided.entity_id)
    assert created is not None
    assert created.canonical_name == normalize_name(REFERENCE)
    assert created.version == 1


def test_create_new_is_refused_when_the_reference_already_matches_something(
    staged: World,
) -> None:
    """Ambiguity is a review's job. A second record for one person is the defect."""
    with pytest.raises(ResolutionNotPermittedError) as refused:
        _decide(
            staged,
            a_command(
                disposition=ResolutionDisposition.CREATE_NEW,
                entity_type=EntityType.PERSON,
                canonical_name=REFERENCE,
                reason=None,
            ),
        )
    assert refused.value.detail == "ambiguous_identity"
    assert len(staged.entities) == 1


def test_create_new_is_refused_when_every_visible_candidate_was_merely_refused(
    world: World,
) -> None:
    """`not_found` and "we refused everybody we could see" are different facts.

    The second is reachable: a truncated answer whose every carried candidate
    has been refused answers `NOT_FOUND` while more candidates existed behind
    the truncation. Only the first licenses a creation.
    """
    FakeUnitOfWork(world).entities.record_observation(PRINCIPAL, a_mention())

    def truncated_not_found(*_: object) -> EntityResolution:
        from my_pa.domain.relationship.resolution import ResolutionWarning

        return EntityResolution(
            outcome=ResolutionOutcome.NOT_FOUND,
            warnings=(
                ResolutionWarning.MORE_CANDIDATES_THAN_THIS_ANSWER_CARRIES,
                ResolutionWarning.A_REFUSED_PAIRING_WAS_WITHHELD,
            ),
            candidates_were_truncated=True,
        )

    with pytest.raises(ResolutionNotPermittedError) as refused:
        _service(world).resolve_mention(
            a_command(
                disposition=ResolutionDisposition.CREATE_NEW,
                entity_type=EntityType.PERSON,
                canonical_name=REFERENCE,
                reason=None,
            ),
            resolve=truncated_not_found,  # type: ignore[arg-type]
            at=WHEN,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
            decided_by=PRINCIPAL,
            actor_class=ActorClass.USER,
        )
    assert refused.value.detail == "review_required"
    assert world.entities == []


# --- negative identity evidence ------------------------------------------------


def test_a_reject_naming_an_entity_preserves_the_refused_pairing(staged: World) -> None:
    """The decision cannot name it, so the evidence link does.

    `entity_resolution_decisions` reserves `entity_id` for the two dispositions
    that *bind* one, so a rejection would otherwise be a refusal of nothing in
    particular.
    """
    decided = _decide(
        staged,
        a_command(
            disposition=ResolutionDisposition.REJECT,
            rejected_entity_id=ALICE,
            reason="this mention is somebody else",
        ),
    )
    (link,) = staged.entity_fact_evidence_links
    assert decided.evidence_link_ids == (link.link_id,)
    assert link.role is NEGATIVE_IDENTITY_EVIDENCE_ROLE
    assert link.role is EvidenceRole.COUNTEREVIDENCE
    assert link.entity_id == ALICE
    assert link.entity_observation_id == MENTION
    assert link.is_negative_identity_evidence


def test_a_reject_erases_neither_the_observation_nor_its_text(staged: World) -> None:
    """Section 10.11: rejected evidence is kept, because a reviewer needs it."""
    _decide(
        staged,
        a_command(
            disposition=ResolutionDisposition.REJECT,
            rejected_entity_id=ALICE,
            reason="this mention is somebody else",
        ),
    )
    held = FakeUnitOfWork(staged).entities.observation(PRINCIPAL, MENTION)
    assert held is not None
    assert held.observed_value == REFERENCE
    assert held.entity_id is None


def test_the_refused_pairing_is_withheld_from_the_next_resolution(staged: World) -> None:
    """The operational effect, asserted against the resolver rather than a comment."""
    service = _service(staged)
    before = service.refused_pairings(PRINCIPAL, MENTION)
    assert before == frozenset()
    _decide(
        staged,
        a_command(
            disposition=ResolutionDisposition.REJECT,
            rejected_entity_id=ALICE,
            reason="this mention is somebody else",
        ),
    )
    refused = service.refused_pairings(PRINCIPAL, MENTION)
    assert refused == frozenset({ALICE})
    held = FakeUnitOfWork(staged).entities.observation(PRINCIPAL, MENTION)
    assert held is not None
    answer = _resolver(staged)(held, refused, WHEN)
    assert ALICE not in {candidate.entity_id for candidate in answer.candidates}


def test_a_refused_pairing_may_not_be_relinked_without_a_new_decision(
    staged: World,
) -> None:
    """Reversing a recorded refusal is not one of the five dispositions.

    So it is refused rather than absorbed: an append-only plane that quietly
    honoured the second of two contradictory decisions would keep both and act
    on neither predictably.
    """
    _decide(
        staged,
        a_command(
            disposition=ResolutionDisposition.REJECT,
            rejected_entity_id=ALICE,
            reason="this mention is somebody else",
        ),
    )
    with pytest.raises(ResolutionNotPermittedError) as refused:
        _decide(
            staged,
            a_command(
                expected_resolution_version=1,
                disposition=ResolutionDisposition.LINK_EXISTING,
                entity_id=ALICE,
                expected_entity_version=1,
                idempotency_key="resolve-0002",
                reason=None,
            ),
        )
    assert refused.value.detail == "evidence_invalid"


# --- concurrency ---------------------------------------------------------------


def test_a_stale_expected_resolution_version_writes_nothing(staged: World) -> None:
    """Two reviewers holding one mention open produce one decision and one refusal."""
    _decide(staged, a_command())
    with pytest.raises(StaleResolutionVersionError):
        _decide(staged, a_command(idempotency_key="resolve-0002"))
    assert len(staged.entity_resolution_decisions) == 1
    assert len(staged.entity_mutation_events) == 1
    held = FakeUnitOfWork(staged).entities.observation(PRINCIPAL, MENTION)
    assert held is not None
    assert held.resolution_version == 1


def test_the_version_advances_by_one_and_the_sequence_follows_it(staged: World) -> None:
    _decide(staged, a_command())
    second = _decide(
        staged, a_command(expected_resolution_version=1, idempotency_key="resolve-0002")
    )
    assert second.resolution_version == 2
    assert [row.sequence for row in staged.entity_resolution_decisions] == [1, 2]


# --- idempotency ---------------------------------------------------------------


def test_an_exact_replay_returns_the_same_decision(staged: World) -> None:
    first = _decide(staged, a_command())
    second = _decide(staged, a_command(), at=LATER)
    assert second.decision_id == first.decision_id
    assert second.disposition is first.disposition
    assert second.resolution_version == first.resolution_version
    assert second.created is False
    assert len(staged.entity_resolution_decisions) == 1


def test_one_key_bound_to_a_different_decision_is_a_conflict(staged: World) -> None:
    _decide(staged, a_command())
    with pytest.raises(EntityMutationConflictError):
        _decide(staged, a_command(disposition=ResolutionDisposition.QUARANTINE))
    assert len(staged.entity_resolution_decisions) == 1


# --- the partition --------------------------------------------------------------


def test_a_foreign_mention_is_answered_exactly_as_an_absent_one(world: World) -> None:
    entities = FakeUnitOfWork(world).entities
    entities.record_observation(OTHER, a_mention(FOREIGN_MENTION, OTHER))
    with pytest.raises(UnknownObservationError):
        _decide(world, a_command(observation_id=FOREIGN_MENTION))
    with pytest.raises(UnknownObservationError):
        _decide(world, a_command(observation_id="eobs_0000000000000000"))
    assert world.entity_resolution_decisions == []


def test_a_stale_create_new_writes_no_entity_before_it_is_refused(staged: World) -> None:
    """The version is read before the entity is inserted, not only after.

    `create_new` has to insert the entity *before* the guarded `UPDATE` that
    binds it, because the column is a foreign key — so a stale decision that
    reached the update would leave the insert to be taken back by the
    transaction. The cheap check runs first, and nothing is written at all.
    """
    _decide(staged, a_command())
    with pytest.raises(StaleResolutionVersionError):
        _decide(
            staged,
            a_command(
                disposition=ResolutionDisposition.CREATE_NEW,
                entity_type=EntityType.PERSON,
                canonical_name="Somebody Entirely New",
                idempotency_key="resolve-0002",
                reason=None,
            ),
        )
    assert [entity.entity_id for entity in staged.entities] == [ALICE]
    assert len(staged.entity_resolution_decisions) == 1
