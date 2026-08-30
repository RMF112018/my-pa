"""`EntityRoleType`/`EntityDisciplineType`/`EntityProjectParticipation` invariants,
without persistence (RI-ENT-WP-04).

Every rule asserted here is also a CHECK constraint in `f5b06925857e`; the
database half lives in
`tests/schema/test_entity_project_participations_migration.py`. This module
proves only what a dataclass can prove, on the same argument
`tests/unit/test_entity_address_and_communication_method_domain.py` states for
`EntityAddress`/`EntityCommunicationMethod`.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.relationship.entity import (
    EntityDisciplineType,
    EntityProjectParticipation,
    EntityProjectParticipationState,
    EntityRoleType,
    ParticipationStatusCode,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
    TaxonomyEntryStatus,
)

PRINCIPAL = "prn_aaaa0001aaaa0001aaaa0001"
PROJECT_ENTITY = "ent_aaaa0001aaaa0001"
PARTICIPANT_ENTITY = "ent_bbbb0002bbbb0002"
OTHER_ENTITY = "ent_cccc0003cccc0003"

PARTICIPATION = "eppt_aaaa0001aaaa0001"
OTHER_PARTICIPATION = "eppt_bbbb0002bbbb0002"

WHEN = datetime(2026, 8, 17, 12, tzinfo=UTC)
LATER = WHEN + timedelta(days=1)


def a_participation(**overrides: object) -> EntityProjectParticipation:
    fields: dict[str, object] = {
        "participation_id": PARTICIPATION,
        "principal_id": PRINCIPAL,
        "project_entity_id": PROJECT_ENTITY,
        "participant_entity_id": PARTICIPANT_ENTITY,
        "project_display_name": "Meridian Point Redevelopment",
        "role_basis_code": RoleBasisCode.CONTRACTUAL,
        "stakeholder_side_code": StakeholderSideCode.CONTRACTOR,
        "stakeholder_class_code": StakeholderClassCode.CORE,
        "relationship_status_code": ParticipationStatusCode.ACTIVE,
    }
    return EntityProjectParticipation(**{**fields, **overrides})  # type: ignore[arg-type]


def a_role_type(**overrides: object) -> EntityRoleType:
    fields: dict[str, object] = {
        "role_code": "SITE_SUPERVISOR",
        "label": "Site Supervisor",
        "category": "construction",
    }
    return EntityRoleType(**{**fields, **overrides})  # type: ignore[arg-type]


def a_discipline_type(**overrides: object) -> EntityDisciplineType:
    fields: dict[str, object] = {
        "discipline_code": "ACOUSTICAL_ENGINEERING",
        "label": "Acoustical Engineering",
        "broader_family": "engineering",
    }
    return EntityDisciplineType(**{**fields, **overrides})  # type: ignore[arg-type]


# --- EntityProjectParticipation: construction and defaults --------------------


def test_a_participation_defaults_to_active_and_version_one() -> None:
    participation = a_participation()
    assert participation.state is EntityProjectParticipationState.ACTIVE
    assert participation.version == 1
    assert participation.role_code is None
    assert participation.discipline_code is None


def test_a_participation_constructs_with_only_required_fields_set() -> None:
    participation = a_participation()
    assert participation.role_text is None
    assert participation.discipline_text is None
    assert participation.scope_text is None
    assert participation.effective_from is None
    assert participation.effective_to is None
    assert participation.updated_at is None
    assert participation.retired_at is None
    assert participation.superseded_by_participation_id is None


@pytest.mark.parametrize("role_basis", list(RoleBasisCode))
def test_a_participation_constructs_for_every_closed_role_basis(
    role_basis: RoleBasisCode,
) -> None:
    participation = a_participation(role_basis_code=role_basis)
    assert participation.role_basis_code is role_basis


@pytest.mark.parametrize("stakeholder_side", list(StakeholderSideCode))
def test_a_participation_constructs_for_every_closed_stakeholder_side(
    stakeholder_side: StakeholderSideCode,
) -> None:
    participation = a_participation(stakeholder_side_code=stakeholder_side)
    assert participation.stakeholder_side_code is stakeholder_side


@pytest.mark.parametrize("stakeholder_class", list(StakeholderClassCode))
def test_a_participation_constructs_for_every_closed_stakeholder_class(
    stakeholder_class: StakeholderClassCode,
) -> None:
    participation = a_participation(stakeholder_class_code=stakeholder_class)
    assert participation.stakeholder_class_code is stakeholder_class


@pytest.mark.parametrize("status", list(ParticipationStatusCode))
def test_a_participation_constructs_for_every_closed_relationship_status(
    status: ParticipationStatusCode,
) -> None:
    participation = a_participation(relationship_status_code=status)
    assert participation.relationship_status_code is status


@pytest.mark.parametrize("state", list(EntityProjectParticipationState))
def test_a_participation_constructs_for_every_closed_state(
    state: EntityProjectParticipationState,
) -> None:
    kwargs: dict[str, object] = {"state": state}
    if state is EntityProjectParticipationState.SUPERSEDED:
        kwargs["superseded_by_participation_id"] = OTHER_PARTICIPATION
    participation = a_participation(**kwargs)
    assert participation.state is state


# --- EntityProjectParticipation: IdKind validation for every identifier -------


def test_a_participation_rejects_an_unknown_identifier_kind_for_participation_id() -> None:
    with pytest.raises(InvalidIdentifierError):
        a_participation(participation_id="ent_aaaa0001aaaa0001")


def test_a_participation_rejects_an_unknown_identifier_kind_for_principal_id() -> None:
    with pytest.raises(InvalidIdentifierError):
        a_participation(principal_id="ent_aaaa0001aaaa0001")


def test_a_participation_rejects_an_unknown_identifier_kind_for_project_entity_id() -> None:
    with pytest.raises(InvalidIdentifierError):
        a_participation(project_entity_id="prn_aaaa0001aaaa0001aaaa0001")


def test_a_participation_rejects_an_unknown_identifier_kind_for_participant_entity_id() -> None:
    with pytest.raises(InvalidIdentifierError):
        a_participation(participant_entity_id="prn_aaaa0001aaaa0001aaaa0001")


def test_a_participation_rejects_an_unknown_identifier_kind_for_superseded_by() -> None:
    with pytest.raises(InvalidIdentifierError):
        a_participation(
            state=EntityProjectParticipationState.SUPERSEDED,
            superseded_by_participation_id="ent_aaaa0001aaaa0001",
        )


# --- EntityProjectParticipation: blank-string rejection ------------------------


@pytest.mark.parametrize("blank", ["", "   ", "\t\n"])
def test_a_participation_project_display_name_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        a_participation(project_display_name=blank)


@pytest.mark.parametrize("field_name", ["role_text", "discipline_text", "scope_text"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_a_participation_optional_text_field_is_not_blank_when_present(
    field_name: str, blank: str
) -> None:
    with pytest.raises(ValueError, match="not blank when present"):
        a_participation(**{field_name: blank})


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_participation_role_code_is_not_blank_when_present(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank when present"):
        a_participation(role_code=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_participation_discipline_code_is_not_blank_when_present(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank when present"):
        a_participation(discipline_code=blank)


# --- EntityProjectParticipation: closed-vocabulary rejection -------------------


def test_a_participation_has_a_closed_role_basis() -> None:
    with pytest.raises(ValueError, match="closed role basis"):
        a_participation(role_basis_code="guessed")


def test_a_participation_has_a_closed_stakeholder_side() -> None:
    with pytest.raises(ValueError, match="closed stakeholder side"):
        a_participation(stakeholder_side_code="bystander")


def test_a_participation_has_a_closed_stakeholder_class() -> None:
    with pytest.raises(ValueError, match="closed stakeholder class"):
        a_participation(stakeholder_class_code="tier_one")


def test_a_participation_has_a_closed_relationship_status() -> None:
    with pytest.raises(ValueError, match="closed relationship status"):
        a_participation(relationship_status_code="pending")


def test_a_participation_has_a_closed_state() -> None:
    with pytest.raises(ValueError, match="closed state"):
        a_participation(state="pending")


# --- EntityProjectParticipation: distinct entities -----------------------------


def test_a_participation_project_cannot_be_its_own_participant() -> None:
    with pytest.raises(ValueError, match="cannot participate in itself"):
        a_participation(project_entity_id=PROJECT_ENTITY, participant_entity_id=PROJECT_ENTITY)


# --- EntityProjectParticipation: effective window ------------------------------


def test_a_participation_cannot_end_before_it_begins() -> None:
    with pytest.raises(ValueError, match="cannot end before it begins"):
        a_participation(effective_from=LATER, effective_to=WHEN)


# --- EntityProjectParticipation: version ---------------------------------------


def test_a_participation_version_starts_at_one() -> None:
    with pytest.raises(ValueError, match="positive"):
        a_participation(version=0)


@pytest.mark.parametrize("bad_version", [0, -1])
def test_a_participation_version_below_one_is_refused(bad_version: int) -> None:
    with pytest.raises(ValueError, match="positive"):
        a_participation(version=bad_version)


# --- EntityProjectParticipation: retirement/supersession lifecycle ------------


def test_a_participation_is_retired_only_once_it_leaves_service() -> None:
    with pytest.raises(ValueError, match="retired only once it leaves service"):
        a_participation(retired_at=WHEN, state=EntityProjectParticipationState.ACTIVE)
    retired = a_participation(retired_at=WHEN, state=EntityProjectParticipationState.RETIRED)
    assert retired.retired_at == WHEN


def test_a_participation_cannot_supersede_itself() -> None:
    with pytest.raises(ValueError, match="cannot supersede itself"):
        a_participation(
            participation_id=PARTICIPATION,
            state=EntityProjectParticipationState.SUPERSEDED,
            superseded_by_participation_id=PARTICIPATION,
        )


def test_a_participation_names_a_successor_only_when_superseded() -> None:
    with pytest.raises(ValueError, match="names a successor only when superseded"):
        a_participation(
            state=EntityProjectParticipationState.ACTIVE,
            superseded_by_participation_id=OTHER_PARTICIPATION,
        )
    superseded = a_participation(
        state=EntityProjectParticipationState.SUPERSEDED,
        superseded_by_participation_id=OTHER_PARTICIPATION,
    )
    assert superseded.superseded_by_participation_id == OTHER_PARTICIPATION


# --- EntityRoleType -------------------------------------------------------------


def test_a_role_type_defaults_to_active() -> None:
    role_type = a_role_type()
    assert role_type.status is TaxonomyEntryStatus.ACTIVE
    assert role_type.category == "construction"


def test_a_role_type_constructs_with_only_required_fields_set() -> None:
    role_type = EntityRoleType(role_code="OWNER", label="Owner")
    assert role_type.category is None
    assert role_type.status is TaxonomyEntryStatus.ACTIVE


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_role_type_code_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        a_role_type(role_code=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_role_type_label_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        a_role_type(label=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_role_type_category_is_not_blank_when_present(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank when present"):
        a_role_type(category=blank)


def test_a_role_type_has_a_closed_status() -> None:
    with pytest.raises(ValueError, match="closed status"):
        a_role_type(status="pending")


@pytest.mark.parametrize("status", list(TaxonomyEntryStatus))
def test_a_role_type_constructs_for_every_closed_status(status: TaxonomyEntryStatus) -> None:
    role_type = a_role_type(status=status)
    assert role_type.status is status


# --- EntityDisciplineType --------------------------------------------------------


def test_a_discipline_type_defaults_to_active() -> None:
    discipline_type = a_discipline_type()
    assert discipline_type.status is TaxonomyEntryStatus.ACTIVE
    assert discipline_type.broader_family == "engineering"


def test_a_discipline_type_constructs_with_only_required_fields_set() -> None:
    discipline_type = EntityDisciplineType(
        discipline_code="CIVIL_ENGINEERING", label="Civil Engineering"
    )
    assert discipline_type.broader_family is None
    assert discipline_type.status is TaxonomyEntryStatus.ACTIVE


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_discipline_type_code_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        a_discipline_type(discipline_code=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_discipline_type_label_is_not_blank(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank"):
        a_discipline_type(label=blank)


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_discipline_type_broader_family_is_not_blank_when_present(blank: str) -> None:
    with pytest.raises(ValueError, match="not blank when present"):
        a_discipline_type(broader_family=blank)


def test_a_discipline_type_has_a_closed_status() -> None:
    with pytest.raises(ValueError, match="closed status"):
        a_discipline_type(status="pending")


@pytest.mark.parametrize("status", list(TaxonomyEntryStatus))
def test_a_discipline_type_constructs_for_every_closed_status(status: TaxonomyEntryStatus) -> None:
    discipline_type = a_discipline_type(status=status)
    assert discipline_type.status is status


# --- Structural proof: no global-identity field on the participation record ---


def test_entity_project_participation_carries_no_global_identity_field() -> None:
    """A structural proof, distinct from the closed field allow-list test in
    `tests/relationship/test_relationship_domain.py`: this dataclass has no
    attribute, property, or field whose name contains `display_name` or
    `canonical_name` other than its own project-scoped `project_display_name`.

    This is the dataclass-level half of the single most important semantic
    boundary in this work package (see `EntityProjectParticipation`'s
    docstring): nothing here may ever read or write `Entity.display_name` or
    `Entity.canonical_name`, and the absence of any such field is what makes
    that impossible by construction rather than by convention.
    """
    field_names = {field.name for field in dataclasses.fields(EntityProjectParticipation)}
    assert "display_name" not in field_names
    assert "canonical_name" not in field_names
    suspect_fields = {
        name
        for name in field_names
        if ("display_name" in name or "canonical_name" in name) and name != "project_display_name"
    }
    assert suspect_fields == set()
    assert "project_display_name" in field_names

    # No property or method on the class exposes either global-identity name
    # either -- the class carries no computed accessor that could reintroduce
    # the same hazard through a non-field attribute.
    suspect_attrs = {
        name
        for name in dir(EntityProjectParticipation)
        if ("display_name" in name or "canonical_name" in name)
        and not name.startswith("__")
        and name != "project_display_name"
    }
    assert suspect_attrs == set()
