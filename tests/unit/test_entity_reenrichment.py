"""Re-enrichment: bounded, idempotent, and never a guess.

The interesting assertions here are the ones about what a pass *declines* to do.
Re-enrichment runs with nobody watching, which makes it the worst possible place
for a doubtful identity join — so a mention that resolves ambiguously must come
out of a pass exactly as it went in.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.application.entity_governance import EntityGovernanceService
from my_pa.application.entity_reenrichment import (
    REENRICHMENT_BOUND,
    EntityReenrichmentService,
    ReenrichmentOutcome,
    ReenrichmentTrigger,
)
from my_pa.domain.relationship.entity import (
    AliasType,
    Entity,
    EntityAlias,
    EntityStatus,
    EntityType,
)
from my_pa.domain.relationship.governance import (
    EntityMergeRecord,
    EntityObservation,
    EntityProposalKind,
    ObservationKind,
)
from my_pa.domain.relationship.normalization import normalize_name
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
ALICE = "ent_aaaa0001aaaa0001"
ALICE_TWO = "ent_bbbb0002bbbb0002"
BOB = "ent_cccc0003cccc0003"

SOURCE = "src_aaaa0001aaaa0001"
OBJECT = "obj_aaaa0001aaaa0001"
VERSION = "ver_aaaa0001aaaa0001"
WHEN = datetime(2026, 8, 18, 12, tzinfo=UTC)


def _entities(world: World):  # noqa: ANN202
    return FakeUnitOfWork(world).entities


@pytest.fixture
def enriching(world: World) -> EntityReenrichmentService:
    return EntityReenrichmentService(_entities(world))


def _entity(entity_id: str, name: str = "Alice Chen") -> Entity:
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


def _observation(
    observation_id: str, entity_id: str | None = None, name: str = "Alice Chen"
) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=PRINCIPAL,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value=name,
        normalized_value=normalize_name(name),
        source_id=SOURCE,
        source_object_id=OBJECT,
        source_version_id=VERSION,
        observed_at=WHEN,
        recorded_at=WHEN,
        entity_id=entity_id,
    )


def _alias(alias_id: str, entity_id: str, name: str) -> EntityAlias:
    return EntityAlias(
        alias_id=alias_id,
        entity_id=entity_id,
        alias_type=AliasType.NICKNAME,
        normalized_value=normalize_name(name),
        display_value=name,
        principal_id=PRINCIPAL,
    )


def _record_merge(entities, merged: str = ALICE_TWO, retained: str = ALICE) -> None:  # noqa: ANN001
    """Write the lineage row `after_merge` requires before it will move anything.

    Called by every pass below, because `after_merge`'s authority to re-point
    someone's evidence comes from an operator's merge decision and from nothing
    else. A test that skipped this would be exercising the method in a state the
    product cannot reach.
    """
    entities.record_merge(
        PRINCIPAL,
        EntityMergeRecord(
            merge_id="emrg_aaaa0001aaaa0001",
            principal_id=PRINCIPAL,
            retained_entity_id=retained,
            merged_entity_id=merged,
            proposal_id="eprp_aaaa0001aaaa0001",
            decided_by="operator",
            reason="the same person, recorded twice",
            decided_at=WHEN,
        ),
    )


# --- after a merge ----------------------------------------------------------


def test_a_merge_repoints_the_stranded_observations(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """What makes a merge finished rather than merely recorded."""
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE))
    entities.create(PRINCIPAL, _entity(ALICE_TWO))
    for index in range(3):
        entities.record_observation(
            PRINCIPAL, _observation(f"eobs_{index:04d}aaaa0001aaaa", ALICE_TWO)
        )
    _record_merge(entities)
    outcome = enriching.after_merge(PRINCIPAL, ALICE_TWO, ALICE)

    assert outcome.trigger is ReenrichmentTrigger.IDENTITY_MERGED
    assert outcome.observations_repointed == 3
    assert outcome.changed_anything is True
    assert entities.observations(PRINCIPAL, ALICE_TWO) == []
    assert len(entities.observations(PRINCIPAL, ALICE)) == 3


def test_repointing_twice_changes_nothing_the_second_time(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """Section 27.2: a retry must not duplicate."""
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE))
    entities.create(PRINCIPAL, _entity(ALICE_TWO))
    entities.record_observation(PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", ALICE_TWO))
    _record_merge(entities)

    enriching.after_merge(PRINCIPAL, ALICE_TWO, ALICE)
    second = enriching.after_merge(PRINCIPAL, ALICE_TWO, ALICE)

    assert second.observations_repointed == 0
    assert len(entities.observations(PRINCIPAL, ALICE)) == 1


def test_a_merge_does_not_touch_another_entitys_observations(
    world: World, enriching: EntityReenrichmentService
) -> None:
    entities = _entities(world)
    for entity_id in (ALICE, ALICE_TWO, BOB):
        entities.create(PRINCIPAL, _entity(entity_id))
    entities.record_observation(PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", BOB))
    _record_merge(entities)
    enriching.after_merge(PRINCIPAL, ALICE_TWO, ALICE)
    assert len(entities.observations(PRINCIPAL, BOB)) == 1


def test_a_merge_re_enrichment_names_two_distinct_entities(
    enriching: EntityReenrichmentService,
) -> None:
    with pytest.raises(ValueError, match="two distinct entities"):
        enriching.after_merge(PRINCIPAL, ALICE, ALICE)


def test_a_merge_pass_is_bounded_and_says_so(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """More work than one pass carries is reported, not silently dropped."""
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE))
    entities.create(PRINCIPAL, _entity(ALICE_TWO))
    for index in range(REENRICHMENT_BOUND + 5):
        entities.record_observation(
            PRINCIPAL, _observation(f"eobs_{index:05d}aaaa0001aaa", ALICE_TWO)
        )
    _record_merge(entities)
    outcome = enriching.after_merge(PRINCIPAL, ALICE_TWO, ALICE)
    assert outcome.observations_repointed == REENRICHMENT_BOUND
    assert outcome.more_remains is True
    assert len(entities.observations(PRINCIPAL, ALICE_TWO)) == 5


def test_looping_a_bounded_pass_finishes_the_work(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """The bound is a pacing device, not a ceiling on what can be done."""
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE))
    entities.create(PRINCIPAL, _entity(ALICE_TWO))
    for index in range(REENRICHMENT_BOUND + 5):
        entities.record_observation(
            PRINCIPAL, _observation(f"eobs_{index:05d}aaaa0001aaa", ALICE_TWO)
        )
    _record_merge(entities)
    while enriching.after_merge(PRINCIPAL, ALICE_TWO, ALICE).more_remains:
        pass
    assert entities.observations(PRINCIPAL, ALICE_TWO) == []


# --- after an alias ---------------------------------------------------------


def test_a_new_alias_links_a_mention_it_now_resolves(
    world: World, enriching: EntityReenrichmentService
) -> None:
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE, "Alice Chen"))
    entities.record_observation(PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", name="Ali"))
    assert len(entities.observations(PRINCIPAL, unresolved_only=True)) == 1

    entities.record_alias(PRINCIPAL, _alias("eals_aaaa0001aaaa0001", ALICE, "Ali"))
    outcome = enriching.after_alias(PRINCIPAL)

    assert outcome.trigger is ReenrichmentTrigger.ALIAS_RECORDED
    assert outcome.mentions_linked == 1
    assert entities.observations(PRINCIPAL, unresolved_only=True) == []
    assert entities.observations(PRINCIPAL, ALICE)[0].entity_id == ALICE


def test_an_ambiguous_mention_is_left_exactly_where_it_was(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """The refusal that matters most here.

    Two people answer to the alias. A background pass with nobody watching is
    the last place to pick one, so the mention comes out of the pass exactly as
    it went in — and is counted, so the pass is honest about having looked.
    """
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE, "Alice Chen"))
    entities.create(PRINCIPAL, _entity(ALICE_TWO, "Alicia Chen"))
    entities.record_alias(PRINCIPAL, _alias("eals_aaaa0001aaaa0001", ALICE, "Ali"))
    entities.record_alias(PRINCIPAL, _alias("eals_bbbb0002bbbb0002", ALICE_TWO, "Ali"))
    entities.record_observation(PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", name="Ali"))

    outcome = enriching.after_alias(PRINCIPAL)

    assert outcome.mentions_linked == 0
    assert outcome.mentions_left_unresolved == 1
    assert outcome.changed_anything is False
    assert len(entities.observations(PRINCIPAL, unresolved_only=True)) == 1


def test_a_bare_name_match_does_not_link_a_mention(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """One entity carries the name and no alias. Still not enough.

    The same rule the resolver applies interactively, applied to the background
    pass — where it matters more, because nobody is reading the answer.
    """
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE, "Alice Chen"))
    entities.record_observation(PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", name="Alice Chen"))
    outcome = enriching.after_alias(PRINCIPAL)
    assert outcome.mentions_linked == 0
    assert outcome.mentions_left_unresolved == 1


def test_a_mention_matching_nothing_stays_unresolved(
    world: World, enriching: EntityReenrichmentService
) -> None:
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE, "Alice Chen"))
    entities.record_observation(
        PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", name="Nobody Whatsoever")
    )
    outcome = enriching.after_alias(PRINCIPAL)
    assert outcome.mentions_linked == 0
    assert outcome.mentions_left_unresolved == 1


def test_running_the_alias_pass_twice_links_nothing_new(
    world: World, enriching: EntityReenrichmentService
) -> None:
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE, "Alice Chen"))
    entities.record_alias(PRINCIPAL, _alias("eals_aaaa0001aaaa0001", ALICE, "Ali"))
    entities.record_observation(PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", name="Ali"))

    first = enriching.after_alias(PRINCIPAL)
    second = enriching.after_alias(PRINCIPAL)

    assert first.mentions_linked == 1
    assert second.mentions_linked == 0
    assert len(entities.observations(PRINCIPAL, ALICE)) == 1


def test_a_pass_over_an_empty_queue_reports_nothing_and_changes_nothing(
    enriching: EntityReenrichmentService,
) -> None:
    outcome = enriching.after_alias(PRINCIPAL)
    assert outcome == ReenrichmentOutcome(trigger=ReenrichmentTrigger.ALIAS_RECORDED)
    assert outcome.changed_anything is False


# --- the outcome record itself ----------------------------------------------


def test_an_outcome_cannot_report_a_negative_count() -> None:
    with pytest.raises(ValueError, match="counts what it did"):
        ReenrichmentOutcome(trigger=ReenrichmentTrigger.ALIAS_RECORDED, mentions_linked=-1)


def test_an_outcome_names_a_closed_trigger() -> None:
    with pytest.raises(ValueError, match="closed trigger"):
        ReenrichmentOutcome(trigger="identity_merged")  # type: ignore[arg-type]


# --- the merge and its re-enrichment, together ------------------------------


def test_an_accepted_merge_followed_by_re_enrichment_moves_the_evidence(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """The two halves of section 15.3, in the order a caller performs them.

    The merge decides; re-enrichment carries the consequence. Kept separate
    because the first needs an operator and the second needs nobody — folding
    them together would put a bounded background walk inside a decision.
    """
    entities = _entities(world)
    governing = EntityGovernanceService(entities)
    entities.create(PRINCIPAL, _entity(ALICE))
    entities.create(PRINCIPAL, _entity(ALICE_TWO))
    entities.record_observation(PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", ALICE_TWO))
    governing.propose(
        PRINCIPAL,
        proposal_id="eprp_aaaa0001aaaa0001",
        kind=EntityProposalKind.MERGE_ENTITIES,
        payload={"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
        observation_ids=(),
        proposed_by="resolver",
        proposed_at=WHEN,
    )
    governing.accept(
        PRINCIPAL,
        "eprp_aaaa0001aaaa0001",
        decided_by="the operator",
        decided_at=WHEN,
        reason="confirmed",
        has_operator_authority=True,
        merge_id="emrg_aaaa0001aaaa0001",
    )
    outcome = enriching.after_merge(PRINCIPAL, ALICE_TWO, ALICE)

    assert outcome.observations_repointed == 1
    assert len(entities.observations(PRINCIPAL, ALICE)) == 1
    merged = entities.get(PRINCIPAL, ALICE_TWO)
    assert merged is not None
    assert merged.status is EntityStatus.MERGED_REDIRECT


# --- the guards -------------------------------------------------------------


def test_a_merge_pass_refuses_a_pair_no_decision_connects(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """The pass's whole authority is the merge record; without one it declines.

    Before this refusal, `after_merge` would move every observation off one
    entity onto another purely because a caller named the two together — the
    exact false join `RI-RISK-001` describes, performed in the background with
    no proposal, no operator and no lineage row to find it by afterwards.
    """
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE))
    entities.create(PRINCIPAL, _entity(BOB, "Bob Nguyen"))
    entities.record_observation(PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", BOB))

    with pytest.raises(ValueError, match="recorded merge"):
        enriching.after_merge(PRINCIPAL, BOB, ALICE)
    assert len(entities.observations(PRINCIPAL, BOB)) == 1


def test_a_merge_pass_refuses_a_recorded_merge_run_backwards(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """Direction is part of the decision, not an argument order the caller picks.

    A record saying "ALICE_TWO was merged into ALICE" does not authorise moving
    ALICE's evidence onto ALICE_TWO. Asserted separately because a membership
    test that ignored direction would pass every test above.
    """
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE))
    entities.create(PRINCIPAL, _entity(ALICE_TWO))
    _record_merge(entities)

    with pytest.raises(ValueError, match="recorded merge"):
        enriching.after_merge(PRINCIPAL, ALICE, ALICE_TWO)


def test_a_merge_pass_refuses_another_principals_lineage(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """`merges` is partitioned, so the lookup finds nothing and the pass stops."""
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE))
    entities.create(PRINCIPAL, _entity(ALICE_TWO))
    _record_merge(entities)

    other = "prn_ffff0009ffff0009ffff0009"
    with pytest.raises(ValueError, match="recorded merge"):
        enriching.after_merge(other, ALICE_TWO, ALICE)


def test_an_alias_pass_will_not_link_a_person_mention_to_a_project(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """The constraint the kind implies, asserted where it would otherwise bind.

    A calendar attendee and a project can carry the same text. Without the
    `entity_type` the kind implies, the pass answers `RESOLVED_EXACT` on the
    project and links a person's mention to it — unwatched, and afterwards
    indistinguishable from a link someone meant.
    """
    entities = _entities(world)
    tower = Entity(
        entity_id=BOB,
        principal_id=PRINCIPAL,
        entity_type=EntityType.PROJECT,
        canonical_name=normalize_name("Harbour Tower"),
        display_name="Harbour Tower",
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )
    entities.create(PRINCIPAL, tower)
    entities.record_alias(PRINCIPAL, _alias("eals_bbbb0002bbbb0002", BOB, "Harbour Tower"))
    entities.record_observation(
        PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", name="Harbour Tower")
    )

    outcome = enriching.after_alias(PRINCIPAL)

    assert outcome.mentions_linked == 0
    assert outcome.mentions_left_unresolved == 1
    assert len(entities.observations(PRINCIPAL, unresolved_only=True)) == 1


def test_an_alias_pass_still_links_a_person_mention_to_a_person(
    world: World, enriching: EntityReenrichmentService
) -> None:
    """The constraint narrows the answer; it does not suppress it.

    The pair with the test above: a guard that refused everything would satisfy
    that one and be useless.
    """
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE, "Alice Chen"))
    entities.record_alias(PRINCIPAL, _alias("eals_bbbb0002bbbb0002", ALICE, "Ali"))
    entities.record_observation(PRINCIPAL, _observation("eobs_aaaa0001aaaa0001", name="Ali"))

    outcome = enriching.after_alias(PRINCIPAL)

    assert outcome.mentions_linked == 1
    assert entities.observations(PRINCIPAL, unresolved_only=True) == []


def test_a_pass_asks_the_repository_for_a_bounded_read(world: World) -> None:
    """The bound is on the query, not on a slice of everything.

    `more_remains` was already asserted above, and it holds either way — an
    in-memory double returns the same outcome whether the cap reached the query
    or a slice was taken after every row had been fetched. Which one it is
    decides whether "bounded" means anything for an entity with fifty thousand
    stranded observations, so it is asserted at the call.
    """
    asked: list[int | None] = []
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity(ALICE))
    entities.create(PRINCIPAL, _entity(ALICE_TWO))
    _record_merge(entities)

    class _Recording:
        def __getattr__(self, name: str) -> object:
            return getattr(entities, name)

        def observations(self, *args: object, **kwargs: object) -> object:
            asked.append(kwargs.get("limit"))
            return entities.observations(*args, **kwargs)  # type: ignore[arg-type]

    enriching = EntityReenrichmentService(_Recording())  # type: ignore[arg-type]
    enriching.after_merge(PRINCIPAL, ALICE_TWO, ALICE)
    enriching.after_alias(PRINCIPAL)

    assert asked == [REENRICHMENT_BOUND + 1, REENRICHMENT_BOUND + 1]
