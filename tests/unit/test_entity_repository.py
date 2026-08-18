"""Entity-plane row hydration and partition semantics, without a database.

Two halves, and the split is the point.

The **hydration** half drives `persistence.entity`'s own row mappers against
stub rows. It proves the translation from a server row to a domain record --
which enum a column becomes, which nullable column becomes `None` rather than
`""`, which integer is cast. No database can be reached from the FAST tier, and
none is needed: a mapper is a pure function of a row.

The **partition** half drives the in-memory `_Entities` fake through
`FakeUnitOfWork`. It proves the contract every method of the port states -- a
record another Principal holds is answered exactly as an absent one, and a write
naming another Principal's entity is refused before it is written. The fake
repeats those rules deliberately, so a test written against it cannot pass
against behaviour the SQL repository would not reproduce. What it cannot prove
is that PostgreSQL enforces any of it; that is `tests/database`'s claim, and
this module does not make it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

import pytest

from my_pa.contracts.ports import UnknownScopeError
from my_pa.domain.relationship.entity import (
    Assignment,
    AssignmentType,
    Entity,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.infrastructure.persistence.entity import (
    _contains,
    _row_to_assignment,
    _row_to_entity,
    _row_to_external_identifier,
    _row_to_relationship,
)
from tests.conftest import FakeUnitOfWork, World

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY = "ent_aaaa0001aaaa0001"
SECOND = "ent_bbbb0002bbbb0002"
THIRD = "ent_cccc0003cccc0003"
WHEN = datetime(2026, 8, 17, 12, tzinfo=UTC)


# --- hydration --------------------------------------------------------------


def test_an_entity_row_becomes_its_closed_vocabularies() -> None:
    entity = _row_to_entity(
        SimpleNamespace(
            entity_id=ENTITY,
            principal_id=PRINCIPAL,
            entity_type="work_package",
            canonical_name="wp ri 01",
            display_name="WP-RI-01",
            status="historical",
            created_at=WHEN,
            updated_at=WHEN,
            version=3,
            superseded_by_entity_id=None,
        )
    )
    assert entity.entity_type is EntityType.WORK_PACKAGE
    assert entity.status is EntityStatus.HISTORICAL
    assert entity.version == 3
    assert entity.superseded_by_entity_id is None


def test_a_merged_entity_row_keeps_the_identifier_it_redirects_to() -> None:
    entity = _row_to_entity(
        SimpleNamespace(
            entity_id=ENTITY,
            principal_id=PRINCIPAL,
            entity_type="person",
            canonical_name="synthetic person",
            display_name="Synthetic Person",
            status="merged_redirect",
            created_at=WHEN,
            updated_at=WHEN,
            version=1,
            superseded_by_entity_id=SECOND,
        )
    )
    assert entity.status is EntityStatus.MERGED_REDIRECT
    assert entity.superseded_by_entity_id == SECOND


def test_an_external_identifier_row_keeps_both_forms_and_its_verification() -> None:
    identifier = _row_to_external_identifier(
        SimpleNamespace(
            identifier_id="xid_aaaa0001aaaa0001",
            entity_id=ENTITY,
            namespace="entra_object_id",
            normalized_value="00000000-0000-4000-8000-000000000001",
            display_value="00000000-0000-4000-8000-000000000001",
            principal_id=PRINCIPAL,
            verified=True,
            effective_from=WHEN,
            effective_to=None,
        )
    )
    assert identifier.namespace is ExternalIdentifierNamespace.ENTRA_OBJECT_ID
    assert identifier.verified is True
    assert identifier.effective_to is None


def test_an_assignment_row_distinguishes_an_absent_field_from_an_empty_one() -> None:
    """`role=""` and `role=None` are different facts, so the mapper keeps both.

    A `str(value) if value else None` mapper would collapse them, and the row
    would come back saying "no role recorded" for a row that recorded one.
    """
    assignment = _row_to_assignment(
        SimpleNamespace(
            assignment_id="asn_aaaa0001aaaa0001",
            entity_id=ENTITY,
            principal_id=PRINCIPAL,
            scope_entity_id=None,
            assignment_type="team_membership",
            role="",
            discipline=None,
            responsibility_class="approver",
            effective_from=None,
            effective_to=None,
            status="active",
        )
    )
    assert assignment.assignment_type is AssignmentType.TEAM_MEMBERSHIP
    assert assignment.role == ""
    assert assignment.discipline is None
    assert assignment.scope_entity_id is None


def test_a_relationship_row_keeps_its_direction_and_scope() -> None:
    relationship = _row_to_relationship(
        SimpleNamespace(
            relationship_id="erel_aaaa0001aaaa0001",
            from_entity_id=ENTITY,
            to_entity_id=SECOND,
            relationship_type="subcontractor_to",
            principal_id=PRINCIPAL,
            scope_entity_id=THIRD,
            effective_from=None,
            effective_to=None,
            state="active",
            version=2,
        )
    )
    assert relationship.relationship_type is EntityRelationshipType.SUBCONTRACTOR_TO
    assert (relationship.from_entity_id, relationship.to_entity_id) == (ENTITY, SECOND)
    assert relationship.scope_entity_id == THIRD
    assert relationship.version == 2


@pytest.mark.parametrize(
    ("query", "pattern"),
    [
        ("Acme", "%Acme%"),
        ("100%", "%100\\%%"),
        ("a_b", "%a\\_b%"),
        ("back\\slash", "%back\\\\slash%"),
        ("", "%%"),
    ],
)
def test_a_search_term_is_escaped_into_a_literal_like_pattern(query: str, pattern: str) -> None:
    """A `%` a caller typed is a character, not "every entity I hold"."""
    assert _contains(query) == pattern


# --- partition semantics, against the in-memory port ------------------------


def an_entity(entity_id: str, principal_id: str, name: str = "Synthetic Person") -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=EntityType.PERSON,
        canonical_name=name.casefold(),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


@pytest.fixture
def two_principals(world: World) -> World:
    """One entity for each of two Principals, so every read below has a decoy."""
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create(an_entity(ENTITY, PRINCIPAL, "Alice Synthetic"))
        unit_of_work.entities.create(an_entity(SECOND, OTHER, "Bob Synthetic"))
    return world


def test_a_get_answers_a_foreign_entity_exactly_as_an_absent_one(two_principals: World) -> None:
    with FakeUnitOfWork(two_principals) as unit_of_work:
        held = unit_of_work.entities.get(PRINCIPAL, ENTITY)
        foreign = unit_of_work.entities.get(PRINCIPAL, SECOND)
        absent = unit_of_work.entities.get(PRINCIPAL, THIRD)
    assert held is not None
    assert foreign is None
    assert absent is None
    assert foreign == absent


def test_a_search_does_not_reach_another_principals_entity(two_principals: World) -> None:
    with FakeUnitOfWork(two_principals) as unit_of_work:
        mine = unit_of_work.entities.search(PRINCIPAL, "synthetic")
        theirs = unit_of_work.entities.search(OTHER, "synthetic")
    assert [summary.entity_id for summary in mine] == [ENTITY]
    assert [summary.entity_id for summary in theirs] == [SECOND]


def test_a_search_matches_the_display_name_as_well_as_the_canonical_one(
    two_principals: World,
) -> None:
    with FakeUnitOfWork(two_principals) as unit_of_work:
        assert [s.entity_id for s in unit_of_work.entities.search(PRINCIPAL, "Alice")] == [ENTITY]


def test_a_search_filters_by_entity_type(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create(an_entity(ENTITY, PRINCIPAL, "Alice Synthetic"))
        project = Entity(
            entity_id=SECOND,
            principal_id=PRINCIPAL,
            entity_type=EntityType.PROJECT,
            canonical_name="alice tower",
            display_name="Alice Tower",
            status=EntityStatus.ACTIVE,
            created_at=WHEN,
            updated_at=WHEN,
            version=1,
        )
        unit_of_work.entities.create(project)
        people = unit_of_work.entities.search(PRINCIPAL, "alice", entity_type=EntityType.PERSON)
        projects = unit_of_work.entities.search(PRINCIPAL, "alice", entity_type=EntityType.PROJECT)
    assert [summary.entity_id for summary in people] == [ENTITY]
    assert [summary.entity_id for summary in projects] == [SECOND]


def test_creating_the_same_entity_twice_returns_the_stored_one(world: World) -> None:
    entity = an_entity(ENTITY, PRINCIPAL)
    with FakeUnitOfWork(world) as unit_of_work:
        first = unit_of_work.entities.create(entity)
        second = unit_of_work.entities.create(entity)
    assert first == second
    assert len(world.entities) == 1


def test_reusing_an_entity_identifier_for_different_values_is_refused(world: World) -> None:
    """Retry-safe, not overwrite-safe: the same identifier cannot mean two things."""
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create(an_entity(ENTITY, PRINCIPAL, "Alice Synthetic"))
        with pytest.raises(ValueError, match="cannot be rebound"):
            unit_of_work.entities.create(an_entity(ENTITY, PRINCIPAL, "Someone Else"))


def test_binding_an_identifier_to_another_principals_entity_is_refused(
    two_principals: World,
) -> None:
    """The false join the plane exists to avoid, at the smallest write that can make one."""
    identifier = ExternalIdentifier(
        identifier_id="xid_aaaa0001aaaa0001",
        entity_id=SECOND,
        namespace=ExternalIdentifierNamespace.EMAIL,
        normalized_value="bob@example.test",
        display_value="bob@example.test",
        principal_id=PRINCIPAL,
    )
    with (
        FakeUnitOfWork(two_principals) as unit_of_work,
        pytest.raises(UnknownScopeError),
    ):
        unit_of_work.entities.bind_identifier(PRINCIPAL, SECOND, identifier)
    assert two_principals.entity_identifiers == []


def test_binding_the_same_external_identity_twice_writes_one_row(world: World) -> None:
    """Idempotent against the natural key, not against the identifier the caller minted."""
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create(an_entity(ENTITY, PRINCIPAL))
        for identifier_id in ("xid_aaaa0001aaaa0001", "xid_bbbb0002bbbb0002"):
            unit_of_work.entities.bind_identifier(
                PRINCIPAL,
                ENTITY,
                ExternalIdentifier(
                    identifier_id=identifier_id,
                    entity_id=ENTITY,
                    namespace=ExternalIdentifierNamespace.EMAIL,
                    normalized_value="alice@example.test",
                    display_value="alice@example.test",
                    principal_id=PRINCIPAL,
                ),
            )
    assert len(world.entity_identifiers) == 1


def test_an_assignment_scope_in_another_partition_is_refused(two_principals: World) -> None:
    """The scope is checked too: a foreign key spans every Principal, a partition does not."""
    assignment = Assignment(
        assignment_id="asn_aaaa0001aaaa0001",
        entity_id=ENTITY,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL,
        scope_entity_id=SECOND,
    )
    with (
        FakeUnitOfWork(two_principals) as unit_of_work,
        pytest.raises(UnknownScopeError),
    ):
        unit_of_work.entities.record_assignment(PRINCIPAL, assignment)
    assert two_principals.entity_assignments == []


def test_a_relationship_reaching_into_another_partition_is_refused(two_principals: World) -> None:
    relationship = EntityRelationship(
        relationship_id="erel_aaaa0001aaaa0001",
        from_entity_id=ENTITY,
        relationship_type=EntityRelationshipType.WORKS_FOR,
        to_entity_id=SECOND,
        principal_id=PRINCIPAL,
    )
    with (
        FakeUnitOfWork(two_principals) as unit_of_work,
        pytest.raises(UnknownScopeError),
    ):
        unit_of_work.entities.record_relationship(PRINCIPAL, relationship)
    assert two_principals.entity_relationships == []


def test_a_write_stamped_with_another_principal_is_refused(two_principals: World) -> None:
    """The record's own `principal_id` is checked, never trusted."""
    assignment = Assignment(
        assignment_id="asn_aaaa0001aaaa0001",
        entity_id=ENTITY,
        assignment_type=AssignmentType.EMPLOYMENT,
        principal_id=OTHER,
    )
    with (
        FakeUnitOfWork(two_principals) as unit_of_work,
        pytest.raises(ValueError, match="belongs to the acting Principal"),
    ):
        unit_of_work.entities.record_assignment(PRINCIPAL, assignment)


def test_relationships_are_enumerated_by_direction(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        entities = unit_of_work.entities
        entities.create(an_entity(ENTITY, PRINCIPAL, "Alice Synthetic"))
        entities.create(an_entity(SECOND, PRINCIPAL, "Acme Synthetic"))
        entities.record_relationship(
            PRINCIPAL,
            EntityRelationship(
                relationship_id="erel_aaaa0001aaaa0001",
                from_entity_id=ENTITY,
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=SECOND,
                principal_id=PRINCIPAL,
            ),
        )
        outgoing = entities.relationships(PRINCIPAL, ENTITY, direction="outgoing")
        incoming = entities.relationships(PRINCIPAL, ENTITY, direction="incoming")
        either = entities.relationships(PRINCIPAL, ENTITY)
    assert len(outgoing) == 1
    assert incoming == []
    assert len(either) == 1


def test_an_unknown_direction_is_refused_rather_than_treated_as_any(world: World) -> None:
    """A caller who asked for outgoing edges must not silently receive every edge."""
    with FakeUnitOfWork(world) as unit_of_work:
        unit_of_work.entities.create(an_entity(ENTITY, PRINCIPAL))
        with pytest.raises(ValueError, match="any, outgoing, or incoming"):
            unit_of_work.entities.relationships(PRINCIPAL, ENTITY, direction="both")


def test_assignments_default_to_the_active_ones_and_can_include_the_rest(world: World) -> None:
    with FakeUnitOfWork(world) as unit_of_work:
        entities = unit_of_work.entities
        entities.create(an_entity(ENTITY, PRINCIPAL))
        for assignment_id, status in (
            ("asn_aaaa0001aaaa0001", "active"),
            ("asn_bbbb0002bbbb0002", "ended"),
        ):
            entities.record_assignment(
                PRINCIPAL,
                Assignment(
                    assignment_id=assignment_id,
                    entity_id=ENTITY,
                    assignment_type=AssignmentType.EMPLOYMENT,
                    principal_id=PRINCIPAL,
                    status=status,
                ),
            )
        active = entities.assignments(PRINCIPAL, ENTITY)
        every = entities.assignments(PRINCIPAL, ENTITY, active_only=False)
    assert [assignment.status for assignment in active] == ["active"]
    assert len(every) == 2
