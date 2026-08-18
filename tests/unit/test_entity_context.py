"""The context card: what it carries, what it counts, and what it admits.

A card is the surface a reader trusts. Its `coverage` is the claim "these
sources contributed, this recently", and every assertion here is about that
claim being *honest* rather than merely present:

* coverage is counted from more observations than the card displays, so a
  crowded entity does not report one source when it has four;
* and it is counted from a **bounded** read, so the card says when the number it
  gives is a floor rather than a total.

Those two pull against each other, which is why both are asserted. A card that
counted only what it showed would understate exactly when it mattered; one that
counted without limit would pull an unbounded result set to answer a read.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.entity_context import EntityContextService
from my_pa.domain.relationship.context_card import (
    CONTEXT_CARD_COLLECTION_LIMIT,
    CONTEXT_CARD_COVERAGE_LIMIT,
    ContextCardLimitation,
)
from my_pa.domain.relationship.entity import Entity, EntityStatus, EntityType
from my_pa.domain.relationship.governance import EntityObservation, ObservationKind
from my_pa.domain.relationship.normalization import normalize_name
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
OTHER: Final = "prn_ffff0009ffff0009ffff0009"
ALICE: Final = "ent_aaaa0001aaaa0001"

MAILBOX: Final = "src_aaaa0001aaaa0001"
CALENDAR: Final = "src_bbbb0002bbbb0002"

WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)


def _entities(world: World):  # noqa: ANN202
    return FakeUnitOfWork(world).entities


@pytest.fixture
def carding(world: World) -> EntityContextService:
    return EntityContextService(_entities(world))


def _entity(entity_id: str = ALICE, principal_id: str = PRINCIPAL) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name("Alice Chen"),
        display_name="Alice Chen",
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def _observe(
    world: World,
    index: int,
    *,
    source_id: str = MAILBOX,
    observed_at: datetime = WHEN,
    entity_id: str = ALICE,
    principal_id: str = PRINCIPAL,
) -> None:
    _entities(world).record_observation(
        principal_id,
        EntityObservation(
            observation_id=f"eobs_{index:05d}aaaa0001aaa",
            principal_id=principal_id,
            kind=ObservationKind.MESSAGE_PARTICIPANT,
            observed_value="Alice Chen",
            normalized_value=normalize_name("Alice Chen"),
            source_id=source_id,
            source_object_id="obj_aaaa0001aaaa0001",
            source_version_id="ver_aaaa0001aaaa0001",
            observed_at=observed_at,
            recorded_at=observed_at,
            entity_id=entity_id,
        ),
    )


# --- the card exists, or honestly does not ----------------------------------


def test_a_card_for_an_entity_the_principal_does_not_hold_is_none(
    world: World, carding: EntityContextService
) -> None:
    """`None` rather than an empty card: an empty card asserts the entity exists."""
    _entities(world).create(OTHER, _entity(principal_id=OTHER))
    assert carding.card(PRINCIPAL, ALICE, assembled_at=WHEN) is None


def test_a_card_carries_the_moment_it_was_given(
    world: World, carding: EntityContextService
) -> None:
    """Section 26.3: a generated artefact carries its generation identity, and
    the moment comes from the caller rather than from a clock in this module."""
    _entities(world).create(PRINCIPAL, _entity())
    later = WHEN + timedelta(days=1)
    card = carding.card(PRINCIPAL, ALICE, assembled_at=later)
    assert card is not None
    assert card.assembled_at == later


# --- coverage -----------------------------------------------------------------


def test_an_entity_nothing_has_observed_says_so(
    world: World, carding: EntityContextService
) -> None:
    """ "Nothing observed this person" and "nothing looked" are different facts."""
    _entities(world).create(PRINCIPAL, _entity())
    card = carding.card(PRINCIPAL, ALICE, assembled_at=WHEN)
    assert card is not None
    assert card.coverage == ()
    assert ContextCardLimitation.NO_SOURCE_HAS_BEEN_OBSERVED in card.limitations


def test_coverage_counts_each_source_and_leads_with_the_freshest(
    world: World, carding: EntityContextService
) -> None:
    _entities(world).create(PRINCIPAL, _entity())
    _observe(world, 1, source_id=MAILBOX, observed_at=WHEN)
    _observe(world, 2, source_id=MAILBOX, observed_at=WHEN)
    _observe(world, 3, source_id=CALENDAR, observed_at=WHEN + timedelta(days=1))

    card = carding.card(PRINCIPAL, ALICE, assembled_at=WHEN)
    assert card is not None
    assert [(entry.source_id, entry.observation_count) for entry in card.coverage] == [
        (CALENDAR, 1),
        (MAILBOX, 2),
    ]
    assert ContextCardLimitation.NO_SOURCE_HAS_BEEN_OBSERVED not in card.limitations


def test_coverage_counts_past_the_page_the_card_displays(
    world: World, carding: EntityContextService
) -> None:
    """The claim the card exists to make: "four sources" is about the evidence.

    The mailbox fills the displayed page on its own. A card that counted only
    what it showed would report the mailbox and never mention the calendar --
    understating coverage exactly when the entity is most heavily observed.
    """
    _entities(world).create(PRINCIPAL, _entity())
    for index in range(CONTEXT_CARD_COLLECTION_LIMIT + 5):
        _observe(world, index, source_id=MAILBOX)
    _observe(world, 9000, source_id=CALENDAR)

    card = carding.card(PRINCIPAL, ALICE, assembled_at=WHEN)
    assert card is not None
    assert len(card.observations) == CONTEXT_CARD_COLLECTION_LIMIT
    assert ContextCardLimitation.MORE_OBSERVATIONS_THAN_THIS_CARD_CARRIES in card.limitations
    assert {entry.source_id for entry in card.coverage} == {MAILBOX, CALENDAR}
    assert ContextCardLimitation.COVERAGE_COUNTED_A_BOUNDED_SAMPLE not in card.limitations


def test_coverage_beyond_the_ceiling_is_disclosed_as_a_sample(
    world: World, carding: EntityContextService
) -> None:
    """And the other side: past the ceiling the counts are floors, and it says so.

    A coverage figure a reader takes for complete is worse than none. Without
    this limitation the card would present a partial count in the same shape as
    a total, with nothing to tell them apart.
    """
    _entities(world).create(PRINCIPAL, _entity())
    for index in range(CONTEXT_CARD_COVERAGE_LIMIT + 1):
        _observe(world, index)

    card = carding.card(PRINCIPAL, ALICE, assembled_at=WHEN)
    assert card is not None
    assert ContextCardLimitation.COVERAGE_COUNTED_A_BOUNDED_SAMPLE in card.limitations
    assert card.coverage[0].observation_count == CONTEXT_CARD_COVERAGE_LIMIT


def test_a_card_exactly_at_the_ceiling_is_not_called_a_sample(
    world: World, carding: EntityContextService
) -> None:
    """The off-by-one, asserted: at the ceiling the count *is* the total."""
    _entities(world).create(PRINCIPAL, _entity())
    for index in range(CONTEXT_CARD_COVERAGE_LIMIT):
        _observe(world, index)

    card = carding.card(PRINCIPAL, ALICE, assembled_at=WHEN)
    assert card is not None
    assert ContextCardLimitation.COVERAGE_COUNTED_A_BOUNDED_SAMPLE not in card.limitations
    assert card.coverage[0].observation_count == CONTEXT_CARD_COVERAGE_LIMIT


def test_coverage_never_counts_another_principals_observation(
    world: World, carding: EntityContextService
) -> None:
    """The partition, at the one place a count could leak it without naming it."""
    _entities(world).create(PRINCIPAL, _entity())
    _entities(world).create(OTHER, _entity(principal_id=OTHER))
    _observe(world, 1, source_id=MAILBOX)
    _observe(world, 2, source_id=CALENDAR, principal_id=OTHER)

    card = carding.card(PRINCIPAL, ALICE, assembled_at=WHEN)
    assert card is not None
    assert [entry.source_id for entry in card.coverage] == [MAILBOX]


def test_the_card_asks_the_repository_for_a_bounded_read(world: World) -> None:
    """The ceiling is an IO property, so it is asserted at the call.

    The two tests above hold whether the cap is a `LIMIT` or a slice taken after
    every row has already been fetched — an in-memory double cannot tell them
    apart, and slicing afterwards would have paid for the unbounded read the
    ceiling exists to prevent. What the cap actually is gets asserted here, and
    that `SqlEntityRepository` turns it into a `LIMIT` is asserted against a
    server in `tests/database/test_entity_governance.py`.
    """
    asked: list[int | None] = []
    entities = _entities(world)
    entities.create(PRINCIPAL, _entity())
    _observe(world, 1)

    class _Recording:
        def __getattr__(self, name: str) -> object:
            return getattr(entities, name)

        def observations(self, *args: object, **kwargs: object) -> object:
            asked.append(kwargs.get("limit"))
            return entities.observations(*args, **kwargs)  # type: ignore[arg-type]

    card = EntityContextService(_Recording()).card(  # type: ignore[arg-type]
        PRINCIPAL, ALICE, assembled_at=WHEN
    )
    assert card is not None
    assert asked == [CONTEXT_CARD_COVERAGE_LIMIT + 1]
