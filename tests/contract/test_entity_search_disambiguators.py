"""`entities.search` carries disambiguators, and the five old keys are untouched.

`RI-AC-038` recorded the gap as "`entities.search` returns
ID/type/canonical/display/status only -- no disambiguators": two people
genuinely called the same thing came back as two identical rows, and nothing in
the answer let a caller tell them apart. `EntitySummary` now carries the
entity's current affiliated organizations and current project roles, and
`application/service.py::_entity_summary_view` -- the single choke point every
`entities.search` response passes through -- publishes both.

**Backwards compatibility is the obligation this file discharges (`RULING-M7`).**
Adding a key to a response is only safe if every key that was there before is
still there, still spelled the same, and still means the same thing. The
existing contract tests happen to read by key rather than by exact dict
equality, so they would not have noticed a break in the other direction -- a
renamed or dropped key would have failed them, but nothing asserted the
*positive* claim that the old five survive intact. That claim is asserted here,
against the exact set of keys the response carried before this change, written
out rather than derived from the code it is checking.

The bound matters as much as the content. A browse row is not a profile: each
collection is cut at `EntitySummary.DISAMBIGUATOR_CEILING` on a deterministic
order, so one person with many affiliations cannot turn a search page into a
dossier or make one row cost many times another.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Final

import pytest
from tests.conftest import FakeUnitOfWork, Scene, build_service, metadata_for

from my_pa.application.commands import SearchEntities
from my_pa.contracts.ports import EntitySummary
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.entity import (
    AffiliationTypeCode,
    Entity,
    EntityProjectParticipation,
    EntityProjectParticipationState,
    EntityStatus,
    EntityType,
    ParticipationStatusCode,
    PersonOrganizationAffiliation,
    PersonOrganizationAffiliationState,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
)
from my_pa.domain.relationship.normalization import normalize_name

#: The keys one `entities.search` row carried before `RI-AC-038`, written out
#: rather than read from `_entity_summary_view`. A compatibility claim derived
#: from the code it is checking is not a claim at all: renaming a key would
#: rename it here too and the assertion would still pass.
KEYS_BEFORE: Final = frozenset(
    {"entity_id", "entity_type", "canonical_name", "display_name", "status"}
)

ONE = "ent_alice0001alice001"
TWO = "ent_alice0002alice002"
ACME = "ent_acme0003acme00003"
NORTHWIND = "ent_nrth0004nrth0004"
HARBOUR = "ent_hrbr0005hrbr0005"
CROWDED = "ent_crwd0006crwd0006"
FOURTH_ORG = "ent_frth0007frth0007"
FIFTH_ORG = "ent_ffth0008ffth0008"
SIXTH_ORG = "ent_sxth0009sxth0009"

WHEN = datetime(2026, 9, 1, 12, tzinfo=UTC)


def _entity(
    entity_id: str,
    display_name: str,
    principal_id: str,
    entity_type: EntityType = EntityType.PERSON,
) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=principal_id,
        entity_type=entity_type,
        canonical_name=normalize_name(display_name),
        display_name=display_name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=1,
    )


def _affiliation(
    affiliation_id: str,
    person_entity_id: str,
    organization_entity_id: str,
    principal_id: str,
    *,
    state: PersonOrganizationAffiliationState = PersonOrganizationAffiliationState.ACTIVE,
) -> PersonOrganizationAffiliation:
    return PersonOrganizationAffiliation(
        affiliation_id=affiliation_id,
        principal_id=principal_id,
        person_entity_id=person_entity_id,
        affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
        organization_entity_id=organization_entity_id,
        job_title="structural engineer",
        state=state,
        superseded_by_affiliation_id=(
            "poaf_success01success1"
            if state is PersonOrganizationAffiliationState.SUPERSEDED
            else None
        ),
    )


def _participation(
    participation_id: str,
    participant_entity_id: str,
    principal_id: str,
    *,
    role_text: str | None,
    project_display_name: str,
) -> EntityProjectParticipation:
    return EntityProjectParticipation(
        participation_id=participation_id,
        principal_id=principal_id,
        project_entity_id=HARBOUR,
        participant_entity_id=participant_entity_id,
        project_display_name=project_display_name,
        role_basis_code=RoleBasisCode.CONTRACTUAL,
        stakeholder_side_code=StakeholderSideCode.DESIGN,
        stakeholder_class_code=StakeholderClassCode.CORE,
        relationship_status_code=ParticipationStatusCode.ACTIVE,
        role_text=role_text,
        state=EntityProjectParticipationState.ACTIVE,
    )


@pytest.fixture
def staged(scene: Scene) -> Scene:
    """Two people called the same thing, told apart only by their context.

    Deliberately the collision shape `RI-AC-038` is about: identical display
    names, identical canonical names, identical status. Everything that
    separates them lives in the two families this response now carries.
    """
    principal_id = scene.principal.principal_id
    with FakeUnitOfWork(scene.world) as unit_of_work:
        entities = unit_of_work.entities
        for entity in (
            _entity(ONE, "Alice Chen", principal_id),
            _entity(TWO, "Alice Chen", principal_id),
            _entity(CROWDED, "Alice Chen", principal_id),
            _entity(ACME, "Acme Construction", principal_id, EntityType.ORGANIZATION),
            _entity(NORTHWIND, "Northwind Legal", principal_id, EntityType.ORGANIZATION),
            _entity(FOURTH_ORG, "Delta Works", principal_id, EntityType.ORGANIZATION),
            _entity(FIFTH_ORG, "Everest Survey", principal_id, EntityType.ORGANIZATION),
            _entity(SIXTH_ORG, "Foundry Group", principal_id, EntityType.ORGANIZATION),
            _entity(HARBOUR, "Harbour Tower", principal_id, EntityType.PROJECT),
        ):
            entities.create(principal_id, entity)
        entities.record_person_organization_affiliation(
            principal_id, _affiliation("poaf_one00001one000001", ONE, ACME, principal_id)
        )
        entities.record_person_organization_affiliation(
            principal_id, _affiliation("poaf_two00002two000002", TWO, NORTHWIND, principal_id)
        )
        # A corrected-away employer, which must not appear beside the current
        # one: a browse row that offered it as a way of telling two people
        # apart would offer an answer that is no longer true.
        entities.record_person_organization_affiliation(
            principal_id,
            _affiliation(
                "poaf_one00003stale001",
                ONE,
                NORTHWIND,
                principal_id,
                state=PersonOrganizationAffiliationState.SUPERSEDED,
            ),
        )
        # Five current employers on one person, so the ceiling has something to
        # cut rather than being asserted against a collection that never
        # reached it.
        for index, organization in enumerate(
            (ACME, NORTHWIND, FOURTH_ORG, FIFTH_ORG, SIXTH_ORG), start=1
        ):
            entities.record_person_organization_affiliation(
                principal_id,
                _affiliation(f"poaf_crowd000{index}crowd1", CROWDED, organization, principal_id),
            )
        entities.record_project_participation(
            principal_id,
            _participation(
                "eppt_one00001one000001",
                ONE,
                principal_id,
                role_text="commissioning lead",
                project_display_name="Harbour Tower",
            ),
        )
        # A participation with no recorded role: nullable in the schema, so the
        # composition has to answer with the project alone rather than with
        # "None on Harbour Tower".
        entities.record_project_participation(
            principal_id,
            _participation(
                "eppt_two00002two000002",
                TWO,
                principal_id,
                role_text=None,
                project_display_name="Saltmarsh Depot",
            ),
        )
    return scene


def _rows(scene: Scene, query: str = "Alice") -> dict[str, dict[str, object]]:
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(Capability.ENTITIES_SEARCH, Purpose.ENTITY_READ, scene.principal),
        SearchEntities(query=query),
        principal=scene.principal,
    )
    body = envelope.to_canonical_dict()
    assert body.get("error") is None, body.get("error")
    result = body["result"]
    assert isinstance(result, dict)
    found = result["entities"]
    assert isinstance(found, list)
    return {str(row["entity_id"]): dict(row) for row in found}  # type: ignore[index,arg-type]


# --- the compatibility obligation (RULING-M7) --------------------------------


def test_every_key_the_response_carried_before_is_still_present(staged: Scene) -> None:
    """The positive half of backwards compatibility, which nothing asserted before.

    Existing contract tests read `entry["entity_id"]` and friends, so a *dropped*
    key would have failed them. None of them said that the five together are
    still the five, which is the claim a caller written against the old shape
    actually depends on.
    """
    rows = _rows(staged)
    assert rows, "the fixture staged no matching entity; the claim below would be vacuous"
    for entity_id, row in rows.items():
        assert set(row) >= KEYS_BEFORE, f"{entity_id} lost {sorted(KEYS_BEFORE - set(row))}"


def test_every_old_key_still_means_what_it_meant(staged: Scene) -> None:
    """Present is not enough: a key that survived with a different value is a break.

    Each of the five is checked against the stored entity it describes, so a
    change that kept the names and moved the meanings -- `display_name`
    answering with the canonical form, say -- fails here.
    """
    rows = _rows(staged)
    held = {entity.entity_id: entity for entity in staged.world.entities}
    for entity_id, row in rows.items():
        entity = held[entity_id]
        assert row["entity_id"] == entity.entity_id
        assert row["entity_type"] == entity.entity_type.value
        assert row["canonical_name"] == entity.canonical_name
        assert row["display_name"] == entity.display_name
        assert row["status"] == entity.status.value


def test_the_response_gained_exactly_the_two_disambiguators_and_nothing_else(
    staged: Scene,
) -> None:
    """The set equality, so a third key arrives as a decision rather than a diff."""
    rows = _rows(staged)
    for row in rows.values():
        assert set(row) == KEYS_BEFORE | {"affiliated_organizations", "project_roles"}


# --- what the disambiguators actually say ------------------------------------


def test_two_people_who_share_a_name_are_now_told_apart(staged: Scene) -> None:
    """`RI-AC-038` itself: identical rows before, distinguishable rows now."""
    rows = _rows(staged)
    assert rows[ONE]["affiliated_organizations"] == ["Acme Construction"]
    assert rows[TWO]["affiliated_organizations"] == ["Northwind Legal"]
    assert rows[ONE]["canonical_name"] == rows[TWO]["canonical_name"]
    assert rows[ONE]["display_name"] == rows[TWO]["display_name"]
    assert rows[ONE] != rows[TWO]


def test_a_project_role_carries_the_role_and_the_project(staged: Scene) -> None:
    assert _rows(staged)[ONE]["project_roles"] == ["commissioning lead on Harbour Tower"]


def test_a_participation_with_no_role_answers_with_the_project_alone(staged: Scene) -> None:
    """`role_text` is nullable, and a row without one is ordinary rather than broken."""
    assert _rows(staged)[TWO]["project_roles"] == ["Saltmarsh Depot"]


def test_a_superseded_affiliation_is_not_offered_as_a_disambiguator(staged: Scene) -> None:
    """Only `active` rows: a corrected-away employer is no longer true of anyone."""
    assert "Northwind Legal" not in _rows(staged)[ONE]["affiliated_organizations"]  # type: ignore[operator]


def test_the_collections_are_cut_at_the_ceiling_and_cut_deterministically(
    staged: Scene,
) -> None:
    """A browse row, not a profile -- and the same page always cuts the same way.

    Five current employers, a ceiling of three, and the three that come back are
    the first three by the organization's display name. Asserting the *content*
    rather than only the length is what makes the order a promise: a cut that
    varied run to run would give a caller a different answer to the same
    question.
    """
    row = _rows(staged)[CROWDED]
    carried = row["affiliated_organizations"]
    assert isinstance(carried, list)
    assert len(carried) == EntitySummary.DISAMBIGUATOR_CEILING
    assert carried == ["Acme Construction", "Delta Works", "Everest Survey"]


def test_an_entity_with_no_context_answers_with_two_empty_lists(staged: Scene) -> None:
    """An organization has neither family, and that is a fact rather than a gap.

    Empty rather than absent, so a caller reading the key does not have to
    distinguish "no affiliation" from "this row did not carry the field".
    """
    row = _rows(staged, "Harbour Tower")[HARBOUR]
    assert row["affiliated_organizations"] == []
    assert row["project_roles"] == []
