"""The generalized entity model's invariants, without persistence.

Every rule asserted here is also a CHECK constraint in `9def3c2e63bb`. That is
deliberate duplication rather than drift: the dataclass refuses the value before
it is written and the server refuses it however it arrives, and a plane whose
only guard is the one the application remembers to call is a plane a migration,
a fixture, or a future writer can put a bad row into.

The database half of each pair lives in `tests/schema`, against a server that
actually refuses. This module proves only what a dataclass can prove.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
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

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
OTHER_PRINCIPAL = "prn_bbbb0002bbbb0002bbbb0002"
ENTITY = "ent_aaaa0001aaaa0001"
OTHER_ENTITY = "ent_bbbb0002bbbb0002"
SCOPE = "ent_cccc0003cccc0003"
IDENTIFIER = "xid_aaaa0001aaaa0001"
ASSIGNMENT = "asn_aaaa0001aaaa0001"
RELATIONSHIP = "erel_aaaa0001aaaa0001"

WHEN = datetime(2026, 8, 17, 12, tzinfo=UTC)
LATER = WHEN + timedelta(days=1)


def an_entity(**overrides: object) -> Entity:
    """One valid entity, so each test states only the field it is about."""
    fields: dict[str, object] = {
        "entity_id": ENTITY,
        "principal_id": PRINCIPAL,
        "entity_type": EntityType.PERSON,
        "canonical_name": "synthetic person",
        "display_name": "Synthetic Person",
        "status": EntityStatus.ACTIVE,
        "created_at": WHEN,
        "updated_at": WHEN,
        "version": 1,
    }
    return Entity(**{**fields, **overrides})  # type: ignore[arg-type]


# --- Entity -----------------------------------------------------------------


def test_an_entity_carries_both_clocks() -> None:
    """Section 12.1 asks for created *and* updated times, so both are required."""
    entity = an_entity(updated_at=LATER)
    assert entity.created_at == WHEN
    assert entity.updated_at == LATER


def test_an_entity_cannot_be_updated_before_it_was_created() -> None:
    with pytest.raises(ValueError, match="updated before it is created"):
        an_entity(updated_at=WHEN - timedelta(seconds=1))


@pytest.mark.parametrize("moment", [datetime(2026, 8, 17, 12), None])
def test_an_entity_refuses_a_moment_without_a_zone(moment: object) -> None:
    with pytest.raises((ValueError, TypeError, AttributeError)):
        an_entity(created_at=moment)


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_an_entity_name_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        an_entity(canonical_name=blank)
    with pytest.raises(ValueError, match="not blank"):
        an_entity(display_name=blank)


def test_an_entity_version_starts_at_one() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        an_entity(version=0)


@pytest.mark.parametrize("identifier", ["", "per_aaaa0001aaaa0001", "ent_short", ENTITY.upper()])
def test_an_entity_identifier_carries_its_own_prefix(identifier: str) -> None:
    """A `per_` identifier is the WP-9 plane's; this plane refuses it by shape."""
    with pytest.raises(InvalidIdentifierError):
        an_entity(entity_id=identifier)


def test_a_merged_entity_names_what_superseded_it() -> None:
    entity = an_entity(status=EntityStatus.MERGED_REDIRECT, superseded_by_entity_id=OTHER_ENTITY)
    assert entity.superseded_by_entity_id == OTHER_ENTITY


def test_a_merged_entity_with_no_target_is_a_dangling_redirect() -> None:
    """Half of the biconditional: MERGED_REDIRECT without a target resolves to nothing."""
    with pytest.raises(ValueError, match="redirects exactly when it is merged away"):
        an_entity(status=EntityStatus.MERGED_REDIRECT)


@pytest.mark.parametrize(
    "status",
    [EntityStatus.ACTIVE, EntityStatus.INACTIVE, EntityStatus.HISTORICAL, EntityStatus.ARCHIVED],
)
def test_an_unmerged_entity_may_not_name_a_successor(status: EntityStatus) -> None:
    """The other half: a redirect on a live entity is a redirect nothing follows."""
    with pytest.raises(ValueError, match="redirects exactly when it is merged away"):
        an_entity(status=status, superseded_by_entity_id=OTHER_ENTITY)


def test_an_entity_cannot_supersede_itself() -> None:
    with pytest.raises(ValueError, match="cannot supersede itself"):
        an_entity(status=EntityStatus.MERGED_REDIRECT, superseded_by_entity_id=ENTITY)


def test_an_entity_type_is_closed() -> None:
    with pytest.raises(ValueError, match="closed entity type"):
        an_entity(entity_type="person")


def test_an_entity_status_is_closed() -> None:
    with pytest.raises(ValueError, match="closed status"):
        an_entity(status="active")


# --- ExternalIdentifier -----------------------------------------------------


def an_identifier(**overrides: object) -> ExternalIdentifier:
    fields: dict[str, object] = {
        "identifier_id": IDENTIFIER,
        "entity_id": ENTITY,
        "namespace": ExternalIdentifierNamespace.EMAIL,
        "normalized_value": "person@example.test",
        "display_value": "Person@Example.test",
        "principal_id": PRINCIPAL,
    }
    return ExternalIdentifier(**{**fields, **overrides})  # type: ignore[arg-type]


def test_an_external_identifier_is_unverified_until_something_verifies_it() -> None:
    assert an_identifier().verified is False


def test_an_external_identifier_keeps_the_value_as_shown_and_as_matched() -> None:
    """Both halves, because normalizing is lossy and the display form is evidence."""
    identifier = an_identifier()
    assert identifier.normalized_value == "person@example.test"
    assert identifier.display_value == "Person@Example.test"


def test_an_external_identifier_namespace_is_closed() -> None:
    with pytest.raises(ValueError, match="closed namespace"):
        an_identifier(namespace="email")


def test_an_external_identifier_cannot_end_before_it_begins() -> None:
    with pytest.raises(ValueError, match="cannot end before it begins"):
        an_identifier(effective_from=LATER, effective_to=WHEN)


def test_an_open_ended_external_identifier_is_allowed() -> None:
    """An identifier held from a date with no end is the ordinary case, not an error."""
    assert an_identifier(effective_from=WHEN).effective_to is None


# --- Assignment -------------------------------------------------------------


def an_assignment(**overrides: object) -> Assignment:
    fields: dict[str, object] = {
        "assignment_id": ASSIGNMENT,
        "entity_id": ENTITY,
        "assignment_type": AssignmentType.PROJECT_ASSIGNMENT,
        "principal_id": PRINCIPAL,
    }
    return Assignment(**{**fields, **overrides})  # type: ignore[arg-type]


def test_an_assignment_may_have_no_resolved_scope_yet() -> None:
    """Section 15's rule that an unresolved reference stays unresolved, in the schema."""
    assert an_assignment().scope_entity_id is None


def test_an_assignment_type_is_closed() -> None:
    with pytest.raises(ValueError, match="closed assignment type"):
        an_assignment(assignment_type="employment")


def test_an_assignment_cannot_end_before_it_begins() -> None:
    with pytest.raises(ValueError, match="cannot end before it begins"):
        an_assignment(effective_from=LATER, effective_to=WHEN)


def test_an_assignment_scope_is_an_entity_identifier() -> None:
    with pytest.raises(InvalidIdentifierError):
        an_assignment(scope_entity_id="prj_aaaa0001aaaa0001")


def test_an_assignment_carries_no_confidence_field() -> None:
    """The deny rule in `tests/architecture` refuses the name on this surface.

    Asserted here rather than left to that scan alone, because a field removed
    for a reason should have the reason recorded where the model is read.
    """
    assert "confidence" not in set(Assignment.__dataclass_fields__)


# --- EntityRelationship -----------------------------------------------------


def a_relationship(**overrides: object) -> EntityRelationship:
    fields: dict[str, object] = {
        "relationship_id": RELATIONSHIP,
        "from_entity_id": ENTITY,
        "relationship_type": EntityRelationshipType.WORKS_FOR,
        "to_entity_id": OTHER_ENTITY,
        "principal_id": PRINCIPAL,
    }
    return EntityRelationship(**{**fields, **overrides})  # type: ignore[arg-type]


def test_a_relationship_connects_two_distinct_entities() -> None:
    with pytest.raises(ValueError, match="two distinct entities"):
        a_relationship(to_entity_id=ENTITY)


def test_a_relationship_may_be_scoped_by_a_third_entity() -> None:
    assert a_relationship(scope_entity_id=SCOPE).scope_entity_id == SCOPE


def test_a_relationship_type_is_closed() -> None:
    with pytest.raises(ValueError, match="closed relationship type"):
        a_relationship(relationship_type="works_for")


def test_a_relationship_cannot_end_before_it_begins() -> None:
    with pytest.raises(ValueError, match="cannot end before it begins"):
        a_relationship(effective_from=LATER, effective_to=WHEN)


def test_a_relationship_version_starts_at_one() -> None:
    with pytest.raises(ValueError, match="positive integer"):
        a_relationship(version=0)


def test_the_same_pair_may_be_related_in_both_directions() -> None:
    """Directed, so `A works_for B` and `B manages A` are two facts, not a conflict."""
    outward = a_relationship()
    inward = a_relationship(
        relationship_id="erel_bbbb0002bbbb0002",
        from_entity_id=OTHER_ENTITY,
        to_entity_id=ENTITY,
        relationship_type=EntityRelationshipType.MANAGES,
    )
    assert outward.from_entity_id == inward.to_entity_id
    assert outward.to_entity_id == inward.from_entity_id


def test_a_relationship_carries_no_confidence_field() -> None:
    assert "confidence" not in set(EntityRelationship.__dataclass_fields__)


# --- the plane as a whole ---------------------------------------------------


def test_every_record_on_this_plane_names_a_principal() -> None:
    """No record here is unowned; the partition is a field, not a convention."""
    for record in (an_entity(), an_identifier(), an_assignment(), a_relationship()):
        assert record.principal_id == PRINCIPAL


@pytest.mark.parametrize(
    "factory", [an_entity, an_identifier, an_assignment, a_relationship], ids=lambda f: f.__name__
)
def test_every_record_refuses_a_malformed_principal(factory: object) -> None:
    with pytest.raises(InvalidIdentifierError):
        factory(principal_id="not-a-principal")  # type: ignore[operator]


def test_a_foreign_principal_is_a_different_record_not_a_refused_one() -> None:
    """The domain does not know whose request this is; the repository does.

    Stated here so the division is explicit: constructing a record for another
    Principal is legal, and refusing to *write* it is the repository's job.
    """
    assert an_entity(principal_id=OTHER_PRINCIPAL).principal_id == OTHER_PRINCIPAL
