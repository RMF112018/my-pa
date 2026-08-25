"""What acceptance does now that it executes: the promotion path, end to end.

`WP-RI-B-05` split promotion in two. `application.entity_promotion` answers
*which* canonical command an accepted proposal becomes and which record it
changes, and imports nothing that could write; `EntityGovernanceService.accept`
is where the write happens, through the same canonical services a user's own
request reaches. This module is about the second half — the part
`tests/unit/test_entity_promotion.py` deliberately cannot exercise, because that
module's subject performs no write at all.

Section 14 and section 27 in six properties:

1. **An accepted ordinary proposal reaches the canonical service**, the record
   it produced exists, and the proposal names it. That is section 37's
   "ordinary accepted Entity proposals promote through Phase A services".
2. **No promotion context, no canonical record.** Recording a decision and
   carrying it out are two acts, and a caller that wants only the first still
   gets only the first.
3. **A stale target version prevents promotion** (section 27), and prevents it
   by naming the proposal's own expectation rather than by letting a version
   the reviewer never chose reach a guarded `UPDATE`.
4. **Accepting an identity correction promotes nothing** — with a promotion
   context in hand. Section 15's division is a property of the kind, not of
   what the caller asked for, and a reviewer holding a context is exactly the
   caller that must not reach a merge.
5. **Evidence survives promotion.** The observations a producer cited are
   linked to the record the acceptance produced.
6. **A mention resolution needs its fresh resolution**, and is refused rather
   than performed unchecked when the context carries none.

Nothing here opens a connection. The authority the ledger *stores* is a
database-tier property and is proved in `tests/database/`.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.entity_governance import (
    EntityGovernanceService,
    InvalidPromotionError,
    PromotionContext,
    ProposalAdmission,
    ProposedEvidence,
)
from my_pa.application.entity_promotion import StaleTargetVersionError
from my_pa.contracts.ports import EntityWriteRequest
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.authoring import EntityWriteOperation
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Entity,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.governance import (
    ActorClass,
    EntityObservation,
    EntityProposal,
    EntityProposalKind,
    EntityProposalMethod,
    EntityProposalState,
    EvidenceRole,
    MutationAuthority,
    MutationRecordFamily,
    ObservationKind,
    ObservationState,
)
from my_pa.domain.relationship.normalization import normalize_name
from tests.conftest import World
from tests.conftest import _Entities as FakeEntities

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
ALICE: Final = "ent_aaaa0001aaaa0001"
BOB: Final = "ent_bbbb0002bbbb0002"
OBSERVATION: Final = "eobs_aaaa0001aaaa0001"
AUDIT: Final = "audit_aaaa0001aaaa0001"
CORRELATION: Final = "corr_aaaa0001aaaa0001"

SOURCE: Final = "src_aaaa0001aaaa0001"
OBJECT: Final = "obj_aaaa0001aaaa0001"
VERSION: Final = "ver_aaaa0001aaaa0001"

WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)

ALIAS_PAYLOAD: Final[dict[str, str | bool]] = {
    "entity_id": ALICE,
    "alias_type": "nickname",
    "display_value": "Ali",
}
MERGE_PAYLOAD: Final[dict[str, str | bool]] = {
    "retained_entity_id": ALICE,
    "merged_entity_id": BOB,
}


def _entities(world: World) -> FakeEntities:
    return FakeEntities(world)


@pytest.fixture
def governing(world: World) -> EntityGovernanceService:
    return EntityGovernanceService(_entities(world))


def an_entity(entity_id: str = ALICE, name: str = "Alice Chen") -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def an_observation(observation_id: str = OBSERVATION) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=PRINCIPAL,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Chen <a.chen@acme.invalid>",
        normalized_value=normalize_name("Alice Chen"),
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
        state=ObservationState.CURRENT,
    )


def a_context(key: str = "idem-promote-1") -> PromotionContext:
    return PromotionContext(
        correlation_id=CORRELATION, audit_id=AUDIT, idempotency_key=key, at=LATER
    )


def _propose(
    governing: EntityGovernanceService,
    *,
    kind: EntityProposalKind = EntityProposalKind.RECORD_ALIAS,
    payload: dict[str, str | bool] | None = None,
    observation_ids: tuple[str, ...] = (),
    evidence: tuple[ProposedEvidence, ...] = (),
    expected_target_version: int | None = None,
) -> ProposalAdmission:
    return governing.propose(
        PRINCIPAL,
        kind=kind,
        payload=ALIAS_PAYLOAD if payload is None else payload,
        observation_ids=observation_ids,
        proposed_by="extractor",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
        at=WHEN,
        evidence=evidence,
        expected_target_version=expected_target_version,
    )


def _accept(
    governing: EntityGovernanceService,
    proposal_id: str,
    *,
    promotion: PromotionContext | None,
    has_operator_authority: bool = False,
) -> EntityProposal:
    return governing.accept(
        PRINCIPAL,
        proposal_id,
        decided_by="reviewer",
        decided_at=LATER,
        reason="looks right",
        has_operator_authority=has_operator_authority,
        promotion=promotion,
    )


# --- property 1: an accepted proposal reaches the canonical service -----------


def test_an_accepted_alias_proposal_writes_the_alias(
    world: World, governing: EntityGovernanceService
) -> None:
    """Section 37: ordinary accepted Entity proposals promote through Phase A services."""
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    admitted = _propose(governing)

    _accept(governing, admitted.proposal_id, promotion=a_context())

    written = entities.aliases(PRINCIPAL, ALICE)
    assert [alias.display_value for alias in written] == ["Ali"]
    assert written[0].state is AliasState.ACTIVE


def test_the_accepted_proposal_names_the_record_it_became(
    world: World, governing: EntityGovernanceService
) -> None:
    """`accepted_record_*`, all three of them, and read back off the stored row.

    Read from the repository rather than from the returned record, because the
    return is what the service says happened and the row is what a later reader
    will see; a promotion that filled one and not the other would be invisible
    to an assertion over the return alone.
    """
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    admitted = _propose(governing)

    returned = _accept(governing, admitted.proposal_id, promotion=a_context())

    stored = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert stored is not None
    assert stored.state is EntityProposalState.ACCEPTED
    assert stored.accepted_record_type is MutationRecordFamily.ALIAS
    assert stored.accepted_record_id == entities.aliases(PRINCIPAL, ALICE)[0].alias_id
    assert stored.accepted_record_version == 1
    assert returned.accepted_record_id == stored.accepted_record_id
    assert returned.accepted_record_version == stored.accepted_record_version
    validate_identifier(str(stored.accepted_record_id), IdKind.ENTITY_ALIAS)


def test_the_promotion_advances_the_entity_the_canonical_service_would_have(
    world: World, governing: EntityGovernanceService
) -> None:
    """The aggregate moved, which is what proves the canonical path ran.

    An alias write advances the entity's version because the entity is the
    aggregate. A promotion that wrote the alias row directly -- the second copy
    of the mutation section 14 forbids -- would leave this at one.
    """
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    admitted = _propose(governing)

    _accept(governing, admitted.proposal_id, promotion=a_context())

    entity = entities.get(PRINCIPAL, ALICE)
    assert entity is not None
    assert entity.version == 2


def test_a_promotion_reads_the_entity_version_now_rather_than_at_proposal_time(
    world: World, governing: EntityGovernanceService
) -> None:
    """The parent version is read fresh, so an unrelated change does not block promotion.

    An alias proposal states no `expected_target_version` -- it creates a record
    rather than changing one -- and the entity it hangs off may legitimately
    move between the proposal and the review. Replaying a version read at
    proposal time would refuse every promotion of an entity anybody touched in
    between, which is a stale-write check that has stopped checking anything and
    started refusing everything.
    """
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    admitted = _propose(governing)
    # Somebody else changes the entity between the proposal and the review, so
    # any version read at proposal time is now three behind.
    world.entities[0] = replace(world.entities[0], version=4, display_name="Alice Chen-Ruiz")

    _accept(governing, admitted.proposal_id, promotion=a_context())

    assert entities.aliases(PRINCIPAL, ALICE)[0].display_value == "Ali"
    entity = entities.get(PRINCIPAL, ALICE)
    assert entity is not None
    assert entity.version == 5


# --- property 2: no context, no canonical record ------------------------------


def test_accepting_an_ordinary_proposal_without_promotion_is_refused(
    world: World, governing: EntityGovernanceService
) -> None:
    """An ordinary acceptance and its canonical mutation are one transaction."""
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    admitted = _propose(governing)

    with pytest.raises(InvalidPromotionError, match="requires canonical promotion"):
        _accept(governing, admitted.proposal_id, promotion=None)

    decided = entities.proposal(PRINCIPAL, admitted.proposal_id)
    assert decided is not None
    assert decided.state is EntityProposalState.NEEDS_REVIEW
    assert decided.decided_by is None
    assert entities.aliases(PRINCIPAL, ALICE) == []
    entity = entities.get(PRINCIPAL, ALICE)
    assert entity is not None
    assert entity.version == 1


# --- property 3: a stale target version prevents promotion --------------------


def test_a_stale_target_version_prevents_promotion(
    world: World, governing: EntityGovernanceService
) -> None:
    """Section 27, over the record the proposal's kind actually changes."""
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    admitted = _propose(governing)
    _accept(governing, admitted.proposal_id, promotion=a_context())
    alias = entities.aliases(PRINCIPAL, ALICE)[0]

    retire = _propose(
        governing,
        kind=EntityProposalKind.RETIRE_ALIAS,
        payload={"entity_id": ALICE, "alias_id": alias.alias_id, "reason": "wrong person"},
        # The alias is at version one; this proposal claims it read version two.
        expected_target_version=2,
    )
    with pytest.raises(StaleTargetVersionError):
        _accept(governing, retire.proposal_id, promotion=a_context("idem-promote-2"))


def test_a_current_target_version_promotes(
    world: World, governing: EntityGovernanceService
) -> None:
    """The control for the test above: the refusal is about staleness, not about the kind."""
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    first = _propose(governing)
    _accept(governing, first.proposal_id, promotion=a_context())
    alias = entities.aliases(PRINCIPAL, ALICE)[0]

    retire = _propose(
        governing,
        kind=EntityProposalKind.RETIRE_ALIAS,
        payload={"entity_id": ALICE, "alias_id": alias.alias_id, "reason": "wrong person"},
        expected_target_version=alias.version,
    )
    _accept(governing, retire.proposal_id, promotion=a_context("idem-promote-2"))

    assert entities.aliases(PRINCIPAL, ALICE)[0].state is AliasState.RETIRED


# --- property 4: an identity correction promotes nothing ----------------------


def test_accepting_a_merge_with_a_promotion_context_promotes_nothing(
    world: World, governing: EntityGovernanceService
) -> None:
    """Section 15, attacked from the direction that matters after `WP-RI-B-05`.

    Before promotion executed, "acceptance does not merge" was a property of a
    module that could not write. It can write now, so the assertion is that the
    caller most able to reach a merge -- a reviewer holding a promotion context
    -- still reaches nothing, and that both entities are untouched afterwards.
    """
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    entities.create(PRINCIPAL, an_entity(BOB, "Bob Ruiz"))
    admitted = _propose(governing, kind=EntityProposalKind.MERGE_ENTITIES, payload=MERGE_PAYLOAD)

    decided = _accept(
        governing,
        admitted.proposal_id,
        promotion=a_context(),
        has_operator_authority=True,
    )

    assert decided.state is EntityProposalState.ACCEPTED
    assert decided.accepted_record_id is None
    for entity_id in (ALICE, BOB):
        entity = entities.get(PRINCIPAL, entity_id)
        assert entity is not None
        assert entity.status is EntityStatus.ACTIVE
        assert entity.superseded_by_entity_id is None
        assert entity.version == 1
    assert entities.merges(PRINCIPAL) == []


# --- property 5: evidence survives promotion ----------------------------------


def test_the_cited_observations_are_linked_to_the_record_the_promotion_produced(
    world: World, governing: EntityGovernanceService
) -> None:
    """Section 14: evidence links must survive promotion."""
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    entities.record_observation(PRINCIPAL, an_observation())
    admitted = _propose(governing, observation_ids=(OBSERVATION,))

    _accept(governing, admitted.proposal_id, promotion=a_context())

    alias = entities.aliases(PRINCIPAL, ALICE)[0]
    linked = [
        link
        for link in entities.fact_evidence_links(PRINCIPAL, entity_observation_id=OBSERVATION)
        if link.alias_id == alias.alias_id
    ]
    assert len(linked) == 1
    assert linked[0].role is EvidenceRole.DIRECT
    assert linked[0].authority is MutationAuthority.REVIEW_ACCEPTED


def test_exact_span_and_knowledge_evidence_survive_canonical_promotion(
    world: World, governing: EntityGovernanceService
) -> None:
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    admitted = _propose(
        governing,
        evidence=(
            ProposedEvidence(
                role=EvidenceRole.SUPPORTING,
                capture_span_id="span_cccc0003cccc0003",
            ),
            ProposedEvidence(
                role=EvidenceRole.COUNTEREVIDENCE,
                knowledge_id="kn_cccc0003cccc0003",
            ),
        ),
    )

    _accept(governing, admitted.proposal_id, promotion=a_context())

    alias = entities.aliases(PRINCIPAL, ALICE)[0]
    links = [
        link for link in entities.fact_evidence_links(PRINCIPAL) if link.alias_id == alias.alias_id
    ]
    assert {(link.capture_span_id, link.knowledge_id, link.role) for link in links} == {
        ("span_cccc0003cccc0003", None, EvidenceRole.SUPPORTING),
        (None, "kn_cccc0003cccc0003", EvidenceRole.COUNTEREVIDENCE),
    }
    assert all(link.authority is MutationAuthority.REVIEW_ACCEPTED for link in links)


def test_the_proposals_own_evidence_is_written_when_it_is_proposed(
    world: World, governing: EntityGovernanceService
) -> None:
    """Section 17's table finally has a writer, and the role is the producer's to state."""
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    entities.record_observation(PRINCIPAL, an_observation())
    admitted = _propose(
        governing,
        observation_ids=(OBSERVATION,),
        evidence=(
            ProposedEvidence(
                role=EvidenceRole.COUNTEREVIDENCE, capture_span_id="span_cccc0003cccc0003"
            ),
        ),
    )

    links = entities.proposal_evidence_links(PRINCIPAL, admitted.proposal_id)
    assert [link.sequence for link in links] == [1, 2]
    assert links[0].entity_observation_id == OBSERVATION
    assert links[0].role is EvidenceRole.DIRECT
    assert links[1].capture_span_id == "span_cccc0003cccc0003"
    assert links[1].role is EvidenceRole.COUNTEREVIDENCE


# --- property 6: a mention resolution needs its fresh resolution ---------------


def test_promoting_a_mention_resolution_without_a_resolver_is_refused(
    world: World, governing: EntityGovernanceService
) -> None:
    """The veto runs against the state that exists now, so it cannot be skipped.

    Refused rather than performed unchecked: the fresh resolution is what stops
    a `link_existing` binding an entity a conflicted identifier or a redirect
    has since made wrong, and a promotion that ran without it would bind on a
    week-old queue rendering.
    """
    entities = _entities(world)
    entities.create(PRINCIPAL, an_entity())
    entities.record_observation(PRINCIPAL, an_observation())
    admitted = _propose(
        governing,
        kind=EntityProposalKind.RESOLVE_MENTION,
        payload={"observation_id": OBSERVATION, "disposition": "defer", "reason": "unclear"},
        expected_target_version=0,
    )

    with pytest.raises(InvalidPromotionError):
        _accept(governing, admitted.proposal_id, promotion=a_context())


# --- the field that made all of this honest ----------------------------------


def _an_entity_write(**overrides: object) -> EntityWriteRequest:
    fields: dict[str, object] = {
        "operation": EntityWriteOperation.ADD_ALIAS,
        "capability": "entities.aliases.add",
        "principal_id": PRINCIPAL,
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
        "idempotency_key": "idem-1",
        "server_received_at": WHEN,
        "event_id": "emut_aaaa0001aaaa0001",
        "entity_id": ALICE,
        "expected_version": 1,
        "minted_child_id": "eals_aaaa0001aaaa0001",
        "alias_type": AliasType.NICKNAME,
        "normalized_value": "ali",
        "display_value": "Ali",
    }
    fields.update(overrides)
    return EntityWriteRequest(**fields)  # type: ignore[arg-type]


def test_a_write_request_carries_the_direct_paths_pair_by_default() -> None:
    """Additive and default-compatible: every construction means what it meant."""
    request = _an_entity_write()
    assert request.authority is MutationAuthority.USER_CONFIRMED_ASSERTION
    assert request.actor_class is ActorClass.USER


def test_review_accepted_authority_is_carried_by_a_review_promotion() -> None:
    """The pair is checked against itself, because either half alone can lie.

    `review_accepted` under `user` would attribute a source's conclusion to the
    person who merely accepted it; `review_promotion` under
    `user_confirmed_assertion` would say the user asserted what a promotion
    carried out. Both halves move together or neither does.
    """
    promoted = _an_entity_write(
        authority=MutationAuthority.REVIEW_ACCEPTED, actor_class=ActorClass.REVIEW_PROMOTION
    )
    assert promoted.authority is MutationAuthority.REVIEW_ACCEPTED

    with pytest.raises(ValueError, match="carried by a review promotion"):
        _an_entity_write(authority=MutationAuthority.REVIEW_ACCEPTED)
    with pytest.raises(ValueError, match="carried by a review promotion"):
        _an_entity_write(actor_class=ActorClass.REVIEW_PROMOTION)


def test_a_governed_entity_write_is_never_system_deterministic() -> None:
    """`MutationAuthority`'s own rule: it "may never, by itself, create or merge an identity"."""
    with pytest.raises(ValueError, match="not system-deterministic"):
        _an_entity_write(authority=MutationAuthority.SYSTEM_DETERMINISTIC)
