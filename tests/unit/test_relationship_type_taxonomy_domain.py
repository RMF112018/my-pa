"""`RelationshipTypeTaxonomyEntry` invariants (RI-ENT-WP-06a).

Every rule asserted here is also a CHECK constraint in the `8dc3619891bb`
migration; `tests/schema/test_entity_relationship_types_migration.py` proves
the server enforces the same rules this proves the dataclass enforces.
"""

from __future__ import annotations

import pytest

from my_pa.domain.relationship.entity import (
    EntityType,
    RelationshipTypeTaxonomyEntry,
    TaxonomyEntryStatus,
)


def a_relationship_type(**overrides: object) -> RelationshipTypeTaxonomyEntry:
    fields: dict[str, object] = {
        "relationship_type_code": "parent_of",
        "label": "Parent Of",
        "directed": True,
    }
    return RelationshipTypeTaxonomyEntry(**{**fields, **overrides})  # type: ignore[arg-type]


# --- defaults and construction -----------------------------------------------


def test_a_relationship_type_defaults_to_active_and_undirected_fields_unset() -> None:
    relationship_type = a_relationship_type()
    assert relationship_type.status is TaxonomyEntryStatus.ACTIVE
    assert relationship_type.inverse_type_code is None
    assert relationship_type.source_entity_type is None
    assert relationship_type.target_entity_type is None
    assert relationship_type.allows_project_scope is False
    assert relationship_type.cardinality_rule is None


def test_a_relationship_type_constructs_with_only_required_fields_set() -> None:
    relationship_type = RelationshipTypeTaxonomyEntry(
        relationship_type_code="brand_of", label="Brand Of", directed=True
    )
    assert relationship_type.relationship_type_code == "brand_of"
    assert relationship_type.label == "Brand Of"
    assert relationship_type.directed is True


def test_a_relationship_type_constructs_with_every_field_set() -> None:
    relationship_type = a_relationship_type(
        relationship_type_code="subsidiary_of",
        label="Subsidiary Of",
        directed=True,
        inverse_type_code="parent_of",
        source_entity_type=EntityType.ORGANIZATION,
        target_entity_type=EntityType.ORGANIZATION,
        allows_project_scope=False,
        cardinality_rule="at most one active parent per organization",
        status=TaxonomyEntryStatus.DEPRECATED,
    )
    assert relationship_type.inverse_type_code == "parent_of"
    assert relationship_type.source_entity_type is EntityType.ORGANIZATION
    assert relationship_type.target_entity_type is EntityType.ORGANIZATION
    assert relationship_type.cardinality_rule == "at most one active parent per organization"
    assert relationship_type.status is TaxonomyEntryStatus.DEPRECATED


# --- blank-string checks ------------------------------------------------------


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_relationship_type_code_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        a_relationship_type(relationship_type_code=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_relationship_type_label_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        a_relationship_type(label=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_relationship_type_inverse_code_is_not_blank_when_present(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank when present"):
        a_relationship_type(inverse_type_code=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_relationship_type_cardinality_rule_is_not_blank_when_present(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank when present"):
        a_relationship_type(cardinality_rule=blank)


# --- directed flag -------------------------------------------------------------


def test_a_relationship_type_directed_flag_is_a_boolean() -> None:
    with pytest.raises(ValueError, match="boolean"):
        a_relationship_type(directed="true")  # type: ignore[arg-type]


def test_a_relationship_type_allows_project_scope_flag_is_a_boolean() -> None:
    with pytest.raises(ValueError, match="boolean"):
        a_relationship_type(allows_project_scope="true")  # type: ignore[arg-type]


# --- inverse pairing rule -------------------------------------------------------


def test_a_relationship_type_does_not_invert_itself() -> None:
    with pytest.raises(ValueError, match="does not invert itself"):
        a_relationship_type(relationship_type_code="parent_of", inverse_type_code="parent_of")


def test_a_relationship_type_accepts_a_declared_inverse_pair() -> None:
    parent_of = a_relationship_type(
        relationship_type_code="parent_of", inverse_type_code="subsidiary_of"
    )
    subsidiary_of = a_relationship_type(
        relationship_type_code="subsidiary_of",
        label="Subsidiary Of",
        inverse_type_code="parent_of",
    )
    assert parent_of.inverse_type_code == "subsidiary_of"
    assert subsidiary_of.inverse_type_code == "parent_of"


# --- source/target entity type -------------------------------------------------


def test_a_relationship_type_source_entity_type_is_person_or_organization() -> None:
    with pytest.raises(ValueError, match="person or organization"):
        a_relationship_type(source_entity_type=EntityType.PROJECT)


def test_a_relationship_type_target_entity_type_is_person_or_organization() -> None:
    with pytest.raises(ValueError, match="person or organization"):
        a_relationship_type(target_entity_type=EntityType.PROJECT)


@pytest.mark.parametrize("entity_type", [EntityType.PERSON, EntityType.ORGANIZATION])
def test_a_relationship_type_accepts_either_admitted_source_entity_type(
    entity_type: EntityType,
) -> None:
    relationship_type = a_relationship_type(source_entity_type=entity_type)
    assert relationship_type.source_entity_type is entity_type


@pytest.mark.parametrize("entity_type", [EntityType.PERSON, EntityType.ORGANIZATION])
def test_a_relationship_type_accepts_either_admitted_target_entity_type(
    entity_type: EntityType,
) -> None:
    relationship_type = a_relationship_type(target_entity_type=entity_type)
    assert relationship_type.target_entity_type is entity_type


# --- status --------------------------------------------------------------------


def test_a_relationship_type_has_a_closed_status() -> None:
    with pytest.raises(ValueError, match="closed status"):
        a_relationship_type(status="pending")  # type: ignore[arg-type]


@pytest.mark.parametrize("status", list(TaxonomyEntryStatus))
def test_a_relationship_type_constructs_for_every_closed_status(
    status: TaxonomyEntryStatus,
) -> None:
    relationship_type = a_relationship_type(status=status)
    assert relationship_type.status is status
