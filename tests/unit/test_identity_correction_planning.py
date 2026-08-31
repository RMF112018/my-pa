"""What a governed merge decides, decided over records rather than over a database.

`tests/database/test_identity_correction_merge.py` drives the whole service
against real statements and real constraints. This drives the six planning
functions the service composes, which take domain records and return the row
changes and conflicts a preview reports -- so every branch is reachable here,
including the two the schema itself makes unreachable in the database tier.

That last point is the reason this file exists rather than being folded into the
database suite. `an_active_external_identifier_binding_is_unique` means one
address is the current identity of at most one entity per Principal, so a
survivor and a merged-away entity cannot *both* hold one actively -- and the
classifier still has to refuse that arrangement, because the index is the only
thing preventing it and a merge that assumed the index would be the write that
broke it if the index were ever narrowed to be per entity.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime
from typing import Final

import pytest

from my_pa.application.identity_correction import (
    INVALIDATED_BY_MERGE,
    ConflictChoice,
    IdentityCorrectionService,
    MergeCommand,
    MergePreviewCommand,
    _ledger_order,
    _materialize_effect_states,
    _request_digest,
    plan_addresses,
    plan_aliases,
    plan_assignments,
    plan_communication_methods,
    plan_entities,
    plan_identifiers,
    plan_names,
    plan_observations,
    plan_organization_profiles,
    plan_person_organization_affiliations,
    plan_project_participations,
    plan_proposals,
    plan_relationships,
)
from my_pa.domain.relationship.entity import (
    AddressTypeCode,
    AffiliationTypeCode,
    AliasState,
    AliasType,
    Assignment,
    AssignmentState,
    AssignmentType,
    CommunicationMethodTypeCode,
    CommunicationUsageContextCode,
    Entity,
    EntityAddress,
    EntityAddressState,
    EntityAlias,
    EntityCommunicationMethod,
    EntityCommunicationMethodState,
    EntityName,
    EntityNameState,
    EntityOrganizationProfile,
    EntityProjectParticipation,
    EntityProjectParticipationState,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    IdentifierState,
    LegalIdentityStatusCode,
    NameTypeCode,
    OrganizationKindCode,
    ParticipationStatusCode,
    PersonOrganizationAffiliation,
    PersonOrganizationAffiliationState,
    RelationshipState,
    RoleBasisCode,
    StakeholderClassCode,
    StakeholderSideCode,
    normalize_address,
    normalize_communication_value,
)
from my_pa.domain.relationship.governance import (
    EntityObservation,
    EntityProposal,
    EntityProposalMethod,
    EntityProposalState,
    ObservationKind,
)
from my_pa.domain.relationship.identity_correction import (
    IdentityConflictKind,
    IdentityEffectFamily,
    IdentityEffectKind,
    sequence_effects,
)
from my_pa.domain.relationship.normalization import normalize_name
from my_pa.domain.relationship.proposal_payload import (
    EntityProposalKind,
    EntityProposalPayload,
    dedupe_digest,
)

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED_ONE: Final = "ent_bbbb0002bbbb0002"
MERGED_TWO: Final = "ent_cccc0003cccc0003"
OUTSIDER: Final = "ent_dddd0004dddd0004"

MERGED: Final = frozenset({MERGED_ONE, MERGED_TWO})
WHEN: Final = datetime(2026, 8, 24, 12, tzinfo=UTC)


def _entity(entity_id: str, *, name: str = "Alice Synthetic", version: int = 1) -> Entity:
    return Entity(
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        entity_type=EntityType.PERSON,
        canonical_name=normalize_name(name),
        display_name=name,
        status=EntityStatus.ACTIVE,
        created_at=WHEN,
        updated_at=WHEN,
        version=version,
    )


def _alias(
    alias_id: str,
    entity_id: str,
    name: str = "Ali",
    *,
    state: AliasState = AliasState.ACTIVE,
    alias_type: AliasType = AliasType.NICKNAME,
) -> EntityAlias:
    return EntityAlias(
        alias_id=alias_id,
        entity_id=entity_id,
        alias_type=alias_type,
        normalized_value=normalize_name(name),
        display_value=name,
        principal_id=PRINCIPAL,
        state=state,
    )


def _identifier(
    identifier_id: str,
    entity_id: str,
    value: str = "alice@example.invalid",
    *,
    state: IdentifierState = IdentifierState.ACTIVE,
) -> ExternalIdentifier:
    return ExternalIdentifier(
        identifier_id=identifier_id,
        entity_id=entity_id,
        namespace=ExternalIdentifierNamespace.EMAIL,
        normalized_value=value,
        display_value=value,
        principal_id=PRINCIPAL,
        state=state,
    )


def _assignment(
    assignment_id: str,
    entity_id: str,
    *,
    scope_entity_id: str | None = None,
    role: str | None = "Project Manager",
    state: AssignmentState = AssignmentState.ACTIVE,
) -> Assignment:
    return Assignment(
        assignment_id=assignment_id,
        entity_id=entity_id,
        assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
        principal_id=PRINCIPAL,
        scope_entity_id=scope_entity_id,
        role=role,
        state=state,
    )


def _edge(
    relationship_id: str,
    from_entity_id: str,
    to_entity_id: str,
    *,
    scope_entity_id: str | None = None,
    state: RelationshipState = RelationshipState.ACTIVE,
) -> EntityRelationship:
    return EntityRelationship(
        relationship_id=relationship_id,
        from_entity_id=from_entity_id,
        relationship_type=EntityRelationshipType.AFFILIATED_WITH,
        to_entity_id=to_entity_id,
        principal_id=PRINCIPAL,
        scope_entity_id=scope_entity_id,
        state=state,
    )


def _name(
    entity_name_id: str,
    entity_id: str,
    value: str = "Alice Synthetic",
    *,
    name_type_code: NameTypeCode = NameTypeCode.DISPLAY,
    is_preferred: bool = False,
    state: EntityNameState = EntityNameState.ACTIVE,
) -> EntityName:
    return EntityName(
        entity_name_id=entity_name_id,
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        name_type_code=name_type_code,
        display_value=value,
        normalized_value=normalize_name(value),
        is_preferred=is_preferred,
        state=state,
    )


def _profile(
    entity_id: str,
    *,
    organization_kind_code: OrganizationKindCode = OrganizationKindCode.COMPANY,
) -> EntityOrganizationProfile:
    return EntityOrganizationProfile(
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        organization_kind_code=organization_kind_code,
        legal_identity_status_code=LegalIdentityStatusCode.UNRESOLVED,
    )


def _address(
    entity_address_id: str,
    entity_id: str,
    raw_value: str = "123 Main St",
    *,
    address_type_code: AddressTypeCode = AddressTypeCode.OFFICE,
    is_preferred: bool = False,
    state: EntityAddressState = EntityAddressState.ACTIVE,
) -> EntityAddress:
    normalized = normalize_address(
        line1=None,
        line2=None,
        city=None,
        region=None,
        postal_code=None,
        country=None,
        raw_value=raw_value,
    )
    return EntityAddress(
        entity_address_id=entity_address_id,
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        address_type_code=address_type_code,
        raw_value=raw_value,
        normalized_address_value=normalized,
        is_preferred=is_preferred,
        state=state,
    )


def _communication_method(
    communication_method_id: str,
    entity_id: str,
    value: str = "alice@example.invalid",
    *,
    method_type_code: CommunicationMethodTypeCode = CommunicationMethodTypeCode.EMAIL,
    is_preferred: bool = False,
    state: EntityCommunicationMethodState = EntityCommunicationMethodState.ACTIVE,
) -> EntityCommunicationMethod:
    normalized = normalize_communication_value(method_type_code, value)
    return EntityCommunicationMethod(
        communication_method_id=communication_method_id,
        entity_id=entity_id,
        principal_id=PRINCIPAL,
        method_type_code=method_type_code,
        usage_context_code=CommunicationUsageContextCode.GENERIC,
        normalized_value=normalized,
        display_value=value,
        is_preferred=is_preferred,
        state=state,
    )


def _participation(
    participation_id: str,
    project_entity_id: str,
    participant_entity_id: str,
    *,
    role_code: str | None = "CONSULTANT",
    state: EntityProjectParticipationState = EntityProjectParticipationState.ACTIVE,
) -> EntityProjectParticipation:
    return EntityProjectParticipation(
        participation_id=participation_id,
        principal_id=PRINCIPAL,
        project_entity_id=project_entity_id,
        participant_entity_id=participant_entity_id,
        project_display_name="Synthetic Participant",
        role_basis_code=RoleBasisCode.CONTRACTUAL,
        stakeholder_side_code=StakeholderSideCode.CONSULTANT,
        stakeholder_class_code=StakeholderClassCode.CORE,
        relationship_status_code=ParticipationStatusCode.ACTIVE,
        role_code=role_code,
        state=state,
    )


def _affiliation(
    affiliation_id: str,
    person_entity_id: str,
    organization_entity_id: str | None,
    *,
    state: PersonOrganizationAffiliationState = PersonOrganizationAffiliationState.ACTIVE,
    effective_to: datetime | None = None,
) -> PersonOrganizationAffiliation:
    return PersonOrganizationAffiliation(
        affiliation_id=affiliation_id,
        principal_id=PRINCIPAL,
        person_entity_id=person_entity_id,
        organization_entity_id=organization_entity_id,
        affiliation_type_code=AffiliationTypeCode.EMPLOYMENT,
        state=state,
        effective_to=effective_to,
    )


def _observation(
    observation_id: str, entity_id: str, *, resolution_version: int = 2
) -> EntityObservation:
    return EntityObservation(
        observation_id=observation_id,
        principal_id=PRINCIPAL,
        kind=ObservationKind.MESSAGE_PARTICIPANT,
        observed_value="Alice Synthetic <alice@example.invalid>",
        normalized_value=normalize_name("Alice Synthetic"),
        source_id="src_aaaa0001aaaa0001",
        source_object_id="obj_aaaa0001aaaa0001",
        source_version_id="ver_aaaa0001aaaa0001",
        observed_at=WHEN,
        recorded_at=WHEN,
        entity_id=entity_id,
        resolution_version=resolution_version,
    )


def _proposal(
    proposal_id: str, entity_id: str, *, review_case_id: str | None = None
) -> EntityProposal:
    payload = EntityProposalPayload.of(
        EntityProposalKind.RECORD_ALIAS,
        {"entity_id": entity_id, "alias_type": "nickname", "display_value": "Ali"},
    )
    return EntityProposal(
        proposal_id=proposal_id,
        principal_id=PRINCIPAL,
        kind=EntityProposalKind.RECORD_ALIAS,
        state=EntityProposalState.PROPOSED,
        payload=payload,
        observation_ids=(),
        proposed_at=WHEN,
        proposed_by="synthetic-producer",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="v1",
        dedupe_sha256=dedupe_digest(payload),
        review_case_id=review_case_id,
    )


# --- entities ---------------------------------------------------------------


def test_every_merged_away_entity_is_redirected_and_the_survivor_is_not() -> None:
    changes = plan_entities(SURVIVOR, [_entity(MERGED_TWO), _entity(MERGED_ONE)])
    assert [change.record_id for change in changes] == [MERGED_ONE, MERGED_TWO]
    assert {change.kind for change in changes} == {IdentityEffectKind.ENTITY_REDIRECTED}
    assert SURVIVOR not in {change.record_id for change in changes}
    first = changes[0]
    assert first.before_state == {
        "status": "active",
        "superseded_by_entity_id": None,
        "version": 1,
    }
    assert first.after_state == {
        "status": "merged_redirect",
        "superseded_by_entity_id": SURVIVOR,
        "version": 2,
    }


# --- aliases ----------------------------------------------------------------


def test_an_alias_the_survivor_does_not_hold_is_reparented() -> None:
    changes, conflicts = plan_aliases(
        survivor_entity_id=SURVIVOR,
        survivor_aliases=[],
        merged_aliases=[_alias("eals_aaaa0001aaaa01", MERGED_ONE)],
        choices={},
    )
    assert conflicts == ()
    assert [change.kind for change in changes] == [IdentityEffectKind.OWNER_REPARENTED]
    assert changes[0].after_state["entity_id"] == SURVIVOR
    assert changes[0].after_state["version"] == 2


def test_a_current_name_form_the_survivor_already_holds_currently_coalesces() -> None:
    changes, conflicts = plan_aliases(
        survivor_entity_id=SURVIVOR,
        survivor_aliases=[_alias("eals_ssss0001ssss01", SURVIVOR)],
        merged_aliases=[_alias("eals_aaaa0001aaaa01", MERGED_ONE)],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED
    assert changes[0].coalesced_into == "eals_ssss0001ssss01"
    assert changes[0].after_state["state"] == "superseded"
    assert changes[0].after_state["superseded_by_alias_id"] == "eals_ssss0001ssss01"
    # The row stays on the entity that held it. Nothing is deleted and the
    # merged-away identity keeps the record that it was once known by this name.
    assert changes[0].after_state["entity_id"] == MERGED_ONE


def test_a_current_name_form_the_survivor_holds_only_as_a_former_one_needs_a_choice() -> None:
    survivor_alias = _alias("eals_ssss0001ssss01", SURVIVOR, state=AliasState.RETIRED)
    merged_alias = _alias("eals_aaaa0001aaaa01", MERGED_ONE)
    changes, conflicts = plan_aliases(
        survivor_entity_id=SURVIVOR,
        survivor_aliases=[survivor_alias],
        merged_aliases=[merged_alias],
        choices={},
    )
    assert [conflict.kind for conflict in conflicts] == [IdentityConflictKind.AMBIGUOUS_DISPOSITION]
    assert conflicts[0].family is IdentityEffectFamily.ALIAS
    assert conflicts[0].record_id == "eals_aaaa0001aaaa01"
    assert not conflicts[0].blocks
    # Nothing is planned until the operator has decided it. A preview that
    # projected one of the two outcomes would be showing a decision it has not
    # been given.
    assert changes == ()


@pytest.mark.parametrize(
    ("choice", "expected"),
    [
        (ConflictChoice.REPARENT, IdentityEffectKind.OWNER_REPARENTED),
        (ConflictChoice.COALESCE, IdentityEffectKind.ROW_COALESCED),
    ],
)
def test_the_operators_choice_decides_the_ambiguous_alias(
    choice: ConflictChoice, expected: IdentityEffectKind
) -> None:
    changes, conflicts = plan_aliases(
        survivor_entity_id=SURVIVOR,
        survivor_aliases=[_alias("eals_ssss0001ssss01", SURVIVOR, state=AliasState.RETIRED)],
        merged_aliases=[_alias("eals_aaaa0001aaaa01", MERGED_ONE)],
        choices={"eals_aaaa0001aaaa01": choice},
    )
    # The conflict is reported either way: what the operator chose does not
    # change what the preview found, which is what lets the conflict digest be
    # compared between a preview and an apply that carries dispositions.
    assert len(conflicts) == 1
    assert [change.kind for change in changes] == [expected]


def test_two_merged_entities_holding_one_current_name_form_do_not_both_reparent() -> None:
    """The second collides with a row that did not exist when the walk began."""
    changes, conflicts = plan_aliases(
        survivor_entity_id=SURVIVOR,
        survivor_aliases=[],
        merged_aliases=[
            _alias("eals_aaaa0001aaaa01", MERGED_ONE),
            _alias("eals_bbbb0002bbbb02", MERGED_TWO),
        ],
        choices={},
    )
    assert conflicts == ()
    assert [change.kind for change in changes] == [
        IdentityEffectKind.OWNER_REPARENTED,
        IdentityEffectKind.ROW_COALESCED,
    ]
    assert changes[1].coalesced_into == "eals_aaaa0001aaaa01"


def test_a_former_name_form_the_survivor_already_holds_coalesces() -> None:
    changes, conflicts = plan_aliases(
        survivor_entity_id=SURVIVOR,
        survivor_aliases=[_alias("eals_ssss0001ssss01", SURVIVOR)],
        merged_aliases=[_alias("eals_aaaa0001aaaa01", MERGED_ONE, state=AliasState.RETIRED)],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED


def test_a_different_alias_type_of_the_same_spelling_is_a_different_name_form() -> None:
    changes, conflicts = plan_aliases(
        survivor_entity_id=SURVIVOR,
        survivor_aliases=[_alias("eals_ssss0001ssss01", SURVIVOR, alias_type=AliasType.NICKNAME)],
        merged_aliases=[
            _alias("eals_aaaa0001aaaa01", MERGED_ONE, alias_type=AliasType.FORMER_NAME)
        ],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].kind is IdentityEffectKind.OWNER_REPARENTED


# --- identifiers ------------------------------------------------------------


def test_an_address_the_survivor_does_not_hold_is_reparented() -> None:
    changes, conflicts = plan_identifiers(
        survivor_entity_id=SURVIVOR,
        survivor_identifiers=[],
        merged_identifiers=[_identifier("xid_aaaa0001aaaa01", MERGED_ONE)],
    )
    assert conflicts == ()
    assert changes[0].kind is IdentityEffectKind.OWNER_REPARENTED
    assert changes[0].after_state["entity_id"] == SURVIVOR


def test_a_current_address_the_survivor_holds_at_all_blocks_the_merge() -> None:
    """Section 21: a conflicting active identifier blocks merge."""
    changes, conflicts = plan_identifiers(
        survivor_entity_id=SURVIVOR,
        survivor_identifiers=[
            _identifier("xid_ssss0001ssss01", SURVIVOR, state=IdentifierState.RETIRED)
        ],
        merged_identifiers=[_identifier("xid_aaaa0001aaaa01", MERGED_ONE)],
    )
    assert [conflict.kind for conflict in conflicts] == [
        IdentityConflictKind.ACTIVE_IDENTIFIER_CONFLICT
    ]
    assert conflicts[0].blocks
    assert conflicts[0].family is IdentityEffectFamily.IDENTIFIER
    assert changes == ()


def test_two_current_claims_on_one_address_block_even_though_the_index_forbids_them() -> None:
    """The classifier does not lean on `an_active_external_identifier_binding_is_unique`."""
    _, conflicts = plan_identifiers(
        survivor_entity_id=SURVIVOR,
        survivor_identifiers=[_identifier("xid_ssss0001ssss01", SURVIVOR)],
        merged_identifiers=[_identifier("xid_aaaa0001aaaa01", MERGED_ONE)],
    )
    assert [conflict.kind for conflict in conflicts] == [
        IdentityConflictKind.ACTIVE_IDENTIFIER_CONFLICT
    ]


def test_a_retired_address_the_survivor_already_holds_coalesces() -> None:
    changes, conflicts = plan_identifiers(
        survivor_entity_id=SURVIVOR,
        survivor_identifiers=[_identifier("xid_ssss0001ssss01", SURVIVOR)],
        merged_identifiers=[
            _identifier("xid_aaaa0001aaaa01", MERGED_ONE, state=IdentifierState.RETIRED)
        ],
    )
    assert conflicts == ()
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED
    assert changes[0].coalesced_into == "xid_ssss0001ssss01"


# --- assignments ------------------------------------------------------------


def test_an_assignment_of_a_merged_entity_is_reparented() -> None:
    changes = plan_assignments(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_assignment("asn_aaaa0001aaaa01", MERGED_ONE, scope_entity_id=OUTSIDER)],
        existing_active=[],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.OWNER_REPARENTED]
    assert changes[0].after_state["entity_id"] == SURVIVOR
    assert changes[0].after_state["scope_entity_id"] == OUTSIDER


def test_an_assignment_scoped_to_a_merged_entity_keeps_its_holder() -> None:
    """A merge that rewrote only the subject would leave somebody else's role
    scoped to an identity that no longer stands on its own."""
    changes = plan_assignments(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_assignment("asn_aaaa0001aaaa01", OUTSIDER, scope_entity_id=MERGED_ONE)],
        existing_active=[],
    )
    assert changes[0].after_state["entity_id"] == OUTSIDER
    assert changes[0].after_state["scope_entity_id"] == SURVIVOR


def test_a_current_assignment_the_survivor_already_holds_deduplicates() -> None:
    changes = plan_assignments(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_assignment("asn_aaaa0001aaaa01", MERGED_ONE, scope_entity_id=OUTSIDER)],
        existing_active=[_assignment("asn_ssss0001ssss01", SURVIVOR, scope_entity_id=OUTSIDER)],
    )
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED
    assert changes[0].coalesced_into == "asn_ssss0001ssss01"


def test_the_assignment_key_folds_case_and_whitespace_exactly_as_the_index_does() -> None:
    changes = plan_assignments(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[
            _assignment(
                "asn_aaaa0001aaaa01",
                MERGED_ONE,
                scope_entity_id=OUTSIDER,
                role="  project manager ",
            )
        ],
        existing_active=[
            _assignment(
                "asn_ssss0001ssss01", SURVIVOR, scope_entity_id=OUTSIDER, role="Project Manager"
            )
        ],
    )
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED


def test_an_ended_assignment_reparents_rather_than_deduplicating() -> None:
    """Two ended rows with one descriptive key are two periods, not one fact twice."""
    changes = plan_assignments(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[
            _assignment(
                "asn_aaaa0001aaaa01",
                MERGED_ONE,
                scope_entity_id=OUTSIDER,
                state=AssignmentState.ENDED,
            )
        ],
        existing_active=[_assignment("asn_ssss0001ssss01", SURVIVOR, scope_entity_id=OUTSIDER)],
    )
    assert changes[0].kind is IdentityEffectKind.OWNER_REPARENTED


def test_an_assignment_naming_no_merged_entity_is_left_alone() -> None:
    changes = plan_assignments(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_assignment("asn_aaaa0001aaaa01", OUTSIDER, scope_entity_id=SURVIVOR)],
        existing_active=[],
    )
    assert changes == ()


# --- relationships ----------------------------------------------------------


def test_an_edge_whose_two_ends_became_one_entity_is_superseded() -> None:
    changes = plan_relationships(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_edge("erel_aaaa0001aaaa01", MERGED_ONE, SURVIVOR)],
        existing_active=[],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.SELF_EDGE_SUPERSEDED]
    assert changes[0].after_state["state"] == "superseded"
    assert changes[0].after_state["superseded_by_relationship_id"] is None
    # Not reparented: the row's own `from <> to` CHECK has no reparented form to
    # store, and the endpoints are recorded as they stood.
    assert changes[0].after_state["from_entity_id"] == MERGED_ONE
    assert changes[0].after_state["to_entity_id"] == SURVIVOR


def test_an_edge_between_two_merged_entities_is_superseded() -> None:
    changes = plan_relationships(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_edge("erel_aaaa0001aaaa01", MERGED_ONE, MERGED_TWO)],
        existing_active=[],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.SELF_EDGE_SUPERSEDED]


def test_an_already_superseded_self_edge_produces_no_effect() -> None:
    """A ledger entry recording no change is not evidence of anything."""
    changes = plan_relationships(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[
            _edge(
                "erel_aaaa0001aaaa01",
                MERGED_ONE,
                SURVIVOR,
                state=RelationshipState.SUPERSEDED,
            )
        ],
        existing_active=[],
    )
    assert changes == ()


def test_an_edge_is_reparented_at_whichever_end_the_merge_moved() -> None:
    changes = plan_relationships(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_edge("erel_aaaa0001aaaa01", MERGED_ONE, OUTSIDER, scope_entity_id=MERGED_TWO)],
        existing_active=[],
    )
    assert changes[0].kind is IdentityEffectKind.OWNER_REPARENTED
    assert changes[0].after_state["from_entity_id"] == SURVIVOR
    assert changes[0].after_state["to_entity_id"] == OUTSIDER
    assert changes[0].after_state["scope_entity_id"] == SURVIVOR


def test_a_current_edge_the_survivor_already_holds_deduplicates() -> None:
    changes = plan_relationships(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_edge("erel_aaaa0001aaaa01", MERGED_ONE, OUTSIDER)],
        existing_active=[_edge("erel_ssss0001ssss01", SURVIVOR, OUTSIDER)],
    )
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED
    assert changes[0].coalesced_into == "erel_ssss0001ssss01"


def test_the_opposite_direction_of_one_pair_is_not_a_duplicate() -> None:
    changes = plan_relationships(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_edge("erel_aaaa0001aaaa01", OUTSIDER, MERGED_ONE)],
        existing_active=[_edge("erel_ssss0001ssss01", SURVIVOR, OUTSIDER)],
    )
    assert changes[0].kind is IdentityEffectKind.OWNER_REPARENTED


# --- RI-ENT-WP-06b: names ----------------------------------------------------


def test_a_name_the_survivor_does_not_hold_is_reparented() -> None:
    changes, conflicts = plan_names(
        survivor_entity_id=SURVIVOR,
        survivor_names=[],
        merged_names=[_name("enam_aaaa0001aaaa01", MERGED_ONE)],
        choices={},
    )
    assert conflicts == ()
    assert [change.kind for change in changes] == [IdentityEffectKind.OWNER_REPARENTED]
    assert changes[0].after_state["entity_id"] == SURVIVOR


def test_a_current_name_the_survivor_already_holds_currently_coalesces() -> None:
    changes, conflicts = plan_names(
        survivor_entity_id=SURVIVOR,
        survivor_names=[_name("enam_ssss0001ssss01", SURVIVOR)],
        merged_names=[_name("enam_aaaa0001aaaa01", MERGED_ONE)],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED
    assert changes[0].coalesced_into == "enam_ssss0001ssss01"


def test_a_current_name_the_survivor_holds_only_as_a_former_one_needs_a_choice() -> None:
    changes, conflicts = plan_names(
        survivor_entity_id=SURVIVOR,
        survivor_names=[_name("enam_ssss0001ssss01", SURVIVOR, state=EntityNameState.RETIRED)],
        merged_names=[_name("enam_aaaa0001aaaa01", MERGED_ONE)],
        choices={},
    )
    assert [conflict.kind for conflict in conflicts] == [IdentityConflictKind.AMBIGUOUS_DISPOSITION]
    assert conflicts[0].family is IdentityEffectFamily.NAME
    assert changes == ()


def test_a_preferred_name_colliding_with_the_survivors_preferred_one_is_demoted() -> None:
    """The value differs, so this never reaches the value-key collision dimension --
    the second, `is_preferred`-governed index is the one it collides on."""
    changes, conflicts = plan_names(
        survivor_entity_id=SURVIVOR,
        survivor_names=[
            _name("enam_ssss0001ssss01", SURVIVOR, "Alice Preferred", is_preferred=True)
        ],
        merged_names=[
            _name("enam_aaaa0001aaaa01", MERGED_ONE, "Ali Also Preferred", is_preferred=True)
        ],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].kind is IdentityEffectKind.OWNER_REPARENTED
    assert changes[0].after_state["entity_id"] == SURVIVOR
    assert changes[0].after_state["is_preferred"] is False


def test_a_preferred_name_with_no_existing_preferred_of_that_type_stays_preferred() -> None:
    changes, conflicts = plan_names(
        survivor_entity_id=SURVIVOR,
        survivor_names=[],
        merged_names=[_name("enam_aaaa0001aaaa01", MERGED_ONE, is_preferred=True)],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].after_state["is_preferred"] is True


def test_two_merged_preferred_names_of_one_type_only_one_stays_preferred() -> None:
    """The index is built as the plan is made: the second collides with the first."""
    changes, conflicts = plan_names(
        survivor_entity_id=SURVIVOR,
        survivor_names=[],
        merged_names=[
            _name("enam_aaaa0001aaaa01", MERGED_ONE, "Alice One", is_preferred=True),
            _name("enam_bbbb0002bbbb02", MERGED_TWO, "Alice Two", is_preferred=True),
        ],
        choices={},
    )
    assert conflicts == ()
    preferred_flags = sorted(change.after_state["is_preferred"] for change in changes)
    assert preferred_flags == [False, True]


def test_a_different_name_type_of_the_same_spelling_is_a_different_name_form() -> None:
    changes, conflicts = plan_names(
        survivor_entity_id=SURVIVOR,
        survivor_names=[_name("enam_ssss0001ssss01", SURVIVOR, name_type_code=NameTypeCode.LEGAL)],
        merged_names=[_name("enam_aaaa0001aaaa01", MERGED_ONE, name_type_code=NameTypeCode.BRAND)],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].kind is IdentityEffectKind.OWNER_REPARENTED


# --- RI-ENT-WP-06b: organization profiles ------------------------------------


def test_an_organization_profile_the_survivor_does_not_hold_is_reparented() -> None:
    changes, conflicts = plan_organization_profiles(
        survivor_entity_id=SURVIVOR,
        survivor_profile=None,
        merged_profiles=[_profile(MERGED_ONE)],
    )
    assert conflicts == ()
    assert [change.kind for change in changes] == [IdentityEffectKind.OWNER_REPARENTED]
    assert changes[0].after_state["entity_id"] == SURVIVOR
    assert changes[0].record_id == MERGED_ONE


def test_no_merged_profile_produces_no_change() -> None:
    changes, conflicts = plan_organization_profiles(
        survivor_entity_id=SURVIVOR, survivor_profile=_profile(SURVIVOR), merged_profiles=[]
    )
    assert changes == () and conflicts == ()


def test_a_profile_on_both_sides_blocks_as_a_singleton_conflict() -> None:
    changes, conflicts = plan_organization_profiles(
        survivor_entity_id=SURVIVOR,
        survivor_profile=_profile(SURVIVOR),
        merged_profiles=[_profile(MERGED_ONE)],
    )
    assert changes == ()
    assert [conflict.kind for conflict in conflicts] == [
        IdentityConflictKind.SINGLETON_RECORD_CONFLICT
    ]
    assert conflicts[0].blocks
    assert conflicts[0].family is IdentityEffectFamily.ORGANIZATION_PROFILE
    assert conflicts[0].record_id == MERGED_ONE


def test_two_merged_profiles_competing_for_an_empty_survivor_slot_also_block() -> None:
    """Even with no survivor profile, two challengers cannot both take one primary key."""
    changes, conflicts = plan_organization_profiles(
        survivor_entity_id=SURVIVOR,
        survivor_profile=None,
        merged_profiles=[_profile(MERGED_ONE), _profile(MERGED_TWO)],
    )
    assert changes == ()
    assert len(conflicts) == 2
    assert all(
        conflict.kind is IdentityConflictKind.SINGLETON_RECORD_CONFLICT for conflict in conflicts
    )


# --- RI-ENT-WP-06b: addresses -------------------------------------------------


def test_an_entity_address_the_survivor_does_not_hold_is_reparented() -> None:
    changes, conflicts = plan_addresses(
        survivor_entity_id=SURVIVOR,
        survivor_addresses=[],
        merged_addresses=[_address("eadr_aaaa0001aaaa01", MERGED_ONE)],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].after_state["entity_id"] == SURVIVOR


def test_a_current_address_the_survivor_already_holds_currently_coalesces() -> None:
    changes, conflicts = plan_addresses(
        survivor_entity_id=SURVIVOR,
        survivor_addresses=[_address("eadr_ssss0001ssss01", SURVIVOR)],
        merged_addresses=[_address("eadr_aaaa0001aaaa01", MERGED_ONE)],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED


def test_a_preferred_address_colliding_with_the_survivors_own_preferred_is_demoted() -> None:
    changes, conflicts = plan_addresses(
        survivor_entity_id=SURVIVOR,
        survivor_addresses=[
            _address("eadr_ssss0001ssss01", SURVIVOR, "1 Survivor Ave", is_preferred=True)
        ],
        merged_addresses=[
            _address("eadr_aaaa0001aaaa01", MERGED_ONE, "2 Merged Blvd", is_preferred=True)
        ],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].after_state["is_preferred"] is False


# --- RI-ENT-WP-06b: communication methods ------------------------------------


def test_a_communication_method_the_survivor_does_not_hold_is_reparented() -> None:
    changes, conflicts = plan_communication_methods(
        survivor_entity_id=SURVIVOR,
        survivor_communication_methods=[],
        merged_communication_methods=[_communication_method("ecmm_aaaa0001aaaa01", MERGED_ONE)],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].after_state["entity_id"] == SURVIVOR


def test_a_current_communication_method_the_survivor_already_holds_coalesces() -> None:
    changes, conflicts = plan_communication_methods(
        survivor_entity_id=SURVIVOR,
        survivor_communication_methods=[_communication_method("ecmm_ssss0001ssss01", SURVIVOR)],
        merged_communication_methods=[_communication_method("ecmm_aaaa0001aaaa01", MERGED_ONE)],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED


def test_a_preferred_communication_method_colliding_with_the_survivors_own_is_demoted() -> None:
    changes, conflicts = plan_communication_methods(
        survivor_entity_id=SURVIVOR,
        survivor_communication_methods=[
            _communication_method(
                "ecmm_ssss0001ssss01", SURVIVOR, "survivor@example.invalid", is_preferred=True
            )
        ],
        merged_communication_methods=[
            _communication_method(
                "ecmm_aaaa0001aaaa01", MERGED_ONE, "merged@example.invalid", is_preferred=True
            )
        ],
        choices={},
    )
    assert conflicts == ()
    assert changes[0].after_state["is_preferred"] is False


# --- RI-ENT-WP-06b: project participations -----------------------------------


def test_a_participation_of_a_merged_project_is_reparented() -> None:
    changes = plan_project_participations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_participation("eppt_aaaa0001aaaa01", MERGED_ONE, OUTSIDER)],
        existing_active=[],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.OWNER_REPARENTED]
    assert changes[0].after_state["project_entity_id"] == SURVIVOR
    assert changes[0].after_state["participant_entity_id"] == OUTSIDER


def test_a_participation_of_a_merged_participant_is_reparented() -> None:
    changes = plan_project_participations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_participation("eppt_aaaa0001aaaa01", OUTSIDER, MERGED_ONE)],
        existing_active=[],
    )
    assert changes[0].after_state["project_entity_id"] == OUTSIDER
    assert changes[0].after_state["participant_entity_id"] == SURVIVOR


def test_a_participation_where_project_and_participant_both_become_survivor_is_superseded() -> None:
    changes = plan_project_participations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_participation("eppt_aaaa0001aaaa01", MERGED_ONE, MERGED_TWO)],
        existing_active=[],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.SELF_EDGE_SUPERSEDED]
    assert changes[0].coalesced_into is None
    assert changes[0].after_state["superseded_by_participation_id"] is None


def test_a_current_participation_the_survivor_already_holds_deduplicates() -> None:
    changes = plan_project_participations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[
            _participation("eppt_aaaa0001aaaa01", MERGED_ONE, OUTSIDER, role_code="CONSULTANT")
        ],
        existing_active=[
            _participation("eppt_ssss0001ssss01", SURVIVOR, OUTSIDER, role_code="CONSULTANT")
        ],
    )
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED
    assert changes[0].coalesced_into == "eppt_ssss0001ssss01"


def test_a_null_role_code_participation_never_collides() -> None:
    """`an_active_project_participation_is_unique_per_project_and_role` has no
    `COALESCE` over `role_code`, so two `NULL`-role rows never violate it."""
    changes = plan_project_participations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_participation("eppt_aaaa0001aaaa01", MERGED_ONE, OUTSIDER, role_code=None)],
        existing_active=[_participation("eppt_ssss0001ssss01", SURVIVOR, OUTSIDER, role_code=None)],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.OWNER_REPARENTED]


def test_both_project_and_participant_columns_reparent_independently_in_one_merge() -> None:
    """A multi-entity merge where the project and one of its participants are
    both merged-away entities at once -- both columns of the one row move."""
    project_and_participant_merged = frozenset({MERGED_ONE, MERGED_TWO})
    changes = plan_project_participations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=project_and_participant_merged,
        affected=[_participation("eppt_aaaa0001aaaa01", MERGED_ONE, MERGED_TWO)],
        existing_active=[],
    )
    # Both columns reach the survivor at once, making this a self-participation
    # rather than an ordinary reparenting -- superseded, not owner-reparented.
    assert [change.kind for change in changes] == [IdentityEffectKind.SELF_EDGE_SUPERSEDED]


def test_an_unaffected_participation_is_left_alone() -> None:
    changes = plan_project_participations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_participation("eppt_aaaa0001aaaa01", OUTSIDER, SURVIVOR)],
        existing_active=[],
    )
    assert changes == ()


# --- RI-ENT-WP-06b: person-organization affiliations -------------------------


def test_an_affiliation_of_a_merged_person_is_reparented() -> None:
    changes = plan_person_organization_affiliations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_affiliation("poaf_aaaa0001aaaa01", MERGED_ONE, OUTSIDER)],
        existing_active_open=[],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.OWNER_REPARENTED]
    assert changes[0].after_state["person_entity_id"] == SURVIVOR
    assert changes[0].after_state["organization_entity_id"] == OUTSIDER


def test_an_affiliation_of_a_merged_organization_is_reparented() -> None:
    changes = plan_person_organization_affiliations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_affiliation("poaf_aaaa0001aaaa01", OUTSIDER, MERGED_ONE)],
        existing_active_open=[],
    )
    assert changes[0].after_state["person_entity_id"] == OUTSIDER
    assert changes[0].after_state["organization_entity_id"] == SURVIVOR


def test_an_independent_consultants_affiliation_has_no_organization_to_substitute() -> None:
    changes = plan_person_organization_affiliations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_affiliation("poaf_aaaa0001aaaa01", MERGED_ONE, None)],
        existing_active_open=[],
    )
    assert changes[0].after_state["organization_entity_id"] is None


def test_a_self_affiliation_after_substitution_is_superseded() -> None:
    changes = plan_person_organization_affiliations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_affiliation("poaf_aaaa0001aaaa01", SURVIVOR, MERGED_ONE)],
        existing_active_open=[],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.SELF_EDGE_SUPERSEDED]
    assert changes[0].after_state["superseded_by_affiliation_id"] is None


def test_an_open_affiliation_colliding_with_the_survivors_own_open_affiliation_coalesces() -> None:
    changes = plan_person_organization_affiliations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_affiliation("poaf_aaaa0001aaaa01", MERGED_ONE, OUTSIDER)],
        existing_active_open=[_affiliation("poaf_ssss0001ssss01", SURVIVOR, OUTSIDER)],
    )
    assert changes[0].kind is IdentityEffectKind.ROW_COALESCED
    assert changes[0].coalesced_into == "poaf_ssss0001ssss01"
    # Nothing is deleted: the merged-away person's own row stays parented to
    # its own (now-redirected) entity_id, marked superseded with lineage.
    assert changes[0].after_state["person_entity_id"] == MERGED_ONE


def test_a_closed_affiliation_never_collides_with_the_survivors_open_one() -> None:
    closed = _affiliation(
        "poaf_aaaa0001aaaa01",
        MERGED_ONE,
        OUTSIDER,
        state=PersonOrganizationAffiliationState.RETIRED,
        effective_to=WHEN,
    )
    changes = plan_person_organization_affiliations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[closed],
        existing_active_open=[_affiliation("poaf_ssss0001ssss01", SURVIVOR, OUTSIDER)],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.OWNER_REPARENTED]


def test_both_person_and_organization_merging_onto_one_survivor_is_the_degenerate_self_edge() -> (
    None
):
    """The degenerate case the campaign document names explicitly: both entity
    references of one row are merged away in the same operation. Since a merge
    has exactly one survivor, both substitutions land on the same identity --
    so "both sides change" and "the row becomes self-affiliated" are the same
    event here, not two different outcomes to distinguish."""
    changes = plan_person_organization_affiliations(
        survivor_entity_id=SURVIVOR,
        merged_entity_ids=MERGED,
        affected=[_affiliation("poaf_aaaa0001aaaa01", MERGED_ONE, MERGED_TWO)],
        existing_active_open=[],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.SELF_EDGE_SUPERSEDED]
    assert changes[0].before_state["person_entity_id"] == MERGED_ONE
    assert changes[0].before_state["organization_entity_id"] == MERGED_TWO


# --- observations -----------------------------------------------------------


def test_a_mention_is_rebound_without_its_resolution_version_advancing() -> None:
    changes = plan_observations(
        survivor_entity_id=SURVIVOR,
        observations=[_observation("eobs_aaaa0001aaaa01", MERGED_ONE)],
    )
    assert [change.kind for change in changes] == [IdentityEffectKind.OWNER_REPARENTED]
    assert changes[0].before_state == {"entity_id": MERGED_ONE, "resolution_version": 2}
    assert changes[0].after_state == {"entity_id": SURVIVOR, "resolution_version": 2}
    assert changes[0].expected_version == 2


# --- proposals and review cases ---------------------------------------------


def test_an_open_proposal_naming_a_merged_entity_is_invalidated() -> None:
    changes = plan_proposals([_proposal("eprp_aaaa0001aaaa01", MERGED_ONE)])
    assert [change.kind for change in changes] == [IdentityEffectKind.DEPENDENT_INVALIDATED]
    assert changes[0].before_state == {
        "state": "proposed",
        "invalidated_reason": None,
        "decided_by": None,
        "decided_at": None,
    }
    assert changes[0].after_state == {
        "state": "invalidated",
        "invalidated_reason": INVALIDATED_BY_MERGE,
        "decided_by": None,
        "decided_at": None,
    }


def test_apply_materializes_every_server_written_effect_column() -> None:
    alias_changes, conflicts = plan_aliases(
        survivor_entity_id=SURVIVOR,
        survivor_aliases=[],
        merged_aliases=[_alias("eals_aaaa0001aaaa01", MERGED_ONE)],
        choices={},
    )
    assert conflicts == ()
    proposal_changes = plan_proposals([_proposal("eprp_aaaa0001aaaa01", MERGED_ONE)])

    materialized = _materialize_effect_states(
        (*alias_changes, *proposal_changes), at=WHEN, performed_by=PRINCIPAL
    )
    alias = materialized[0]
    proposal = materialized[1]
    assert alias.after_state == {
        **alias_changes[0].after_state,
        "updated_at": "2026-08-24T12:00:00Z",
    }
    assert proposal.after_state == {
        "state": "invalidated",
        "invalidated_reason": INVALIDATED_BY_MERGE,
        "decided_by": PRINCIPAL,
        "decided_at": "2026-08-24T12:00:00Z",
    }


def test_a_proposal_that_opened_no_review_case_records_no_review_case_effect() -> None:
    """`review_case_id` is what says a reviewer holds this one, and it is absent."""
    changes = plan_proposals([_proposal("eprp_aaaa0001aaaa01", MERGED_ONE)])
    assert [change.family for change in changes] == [IdentityEffectFamily.PROPOSAL]


def test_a_proposal_bound_to_a_review_case_records_the_case_as_well() -> None:
    """No longer a blocker, and the second effect is what lets it stop being one.

    The case is derived from the proposal row, so invalidating the proposal is
    what invalidates the case; the `REVIEW_CASE` effect writes nothing and exists
    so `WP-RI-07` knows which case a split would put back on the surface.
    """
    changes = plan_proposals(
        [_proposal("eprp_aaaa0001aaaa01", MERGED_ONE, review_case_id="rvw_aaaa0001aaaa0001")]
    )
    assert [(change.family, change.record_id) for change in changes] == [
        (IdentityEffectFamily.PROPOSAL, "eprp_aaaa0001aaaa01"),
        (IdentityEffectFamily.REVIEW_CASE, "rvw_aaaa0001aaaa0001"),
    ]
    assert {change.kind for change in changes} == {IdentityEffectKind.DEPENDENT_INVALIDATED}
    case = changes[1]
    assert case.before_state == {"state": "proposed"}
    assert case.after_state == {"state": "invalidated"}
    assert case.expected_version is None
    assert case.coalesced_into is None


# --- determinism -------------------------------------------------------------


def test_the_write_order_is_the_order_the_ledger_numbers_the_effects_in() -> None:
    """`_write` sorts by this key and `sequence_effects` numbers by its own.

    Proved rather than assumed: the two live in different modules, and a write
    order that drifted from the ledger's would leave a failure part-way through
    holding a prefix of the wrong sequence.
    """
    changes = [
        *plan_observations(
            survivor_entity_id=SURVIVOR,
            observations=[_observation("eobs_aaaa0001aaaa01", MERGED_ONE)],
        ),
        *plan_entities(SURVIVOR, [_entity(MERGED_ONE)]),
        *plan_aliases(
            survivor_entity_id=SURVIVOR,
            survivor_aliases=[],
            merged_aliases=[_alias("eals_aaaa0001aaaa01", MERGED_ONE)],
            choices={},
        )[0],
    ]
    effects = sequence_effects(
        (change.draft for change in changes),
        identity_operation_id="eiop_aaaa0001aaaa0001",
        principal_id=PRINCIPAL,
        recorded_at=WHEN,
    )
    assert [change.record_id for change in sorted(changes, key=_ledger_order)] == [
        effect.record_id for effect in effects
    ]
    assert effects[0].family is IdentityEffectFamily.ENTITY


def test_a_review_case_effect_takes_its_place_in_the_one_deterministic_order() -> None:
    """The ledger gained a row family, and the sequence it lands in is still fixed.

    `WP-RI-07` reads the sequence, so a family added to it has to be numbered the
    same way twice. Shuffled input, the same numbers; the write order and the
    ledger order still agree; the `REVIEW_CASE` row sits after the `PROPOSAL` row
    it is a consequence of, because `IdentityEffectFamily` declares it there.
    """
    changes = [
        *plan_proposals(
            [
                _proposal("eprp_bbbb0002bbbb02", MERGED_ONE, review_case_id="rvw_bbbb0002bbbb0002"),
                _proposal("eprp_aaaa0001aaaa01", MERGED_ONE, review_case_id="rvw_aaaa0001aaaa0001"),
            ]
        ),
        *plan_entities(SURVIVOR, [_entity(MERGED_ONE)]),
    ]
    ordered = [
        (effect.sequence, effect.family, effect.record_id)
        for effect in sequence_effects(
            (change.draft for change in changes),
            identity_operation_id="eiop_aaaa0001aaaa0001",
            principal_id=PRINCIPAL,
            recorded_at=WHEN,
        )
    ]
    assert ordered == [
        (1, IdentityEffectFamily.ENTITY, MERGED_ONE),
        (2, IdentityEffectFamily.PROPOSAL, "eprp_aaaa0001aaaa01"),
        (3, IdentityEffectFamily.PROPOSAL, "eprp_bbbb0002bbbb02"),
        (4, IdentityEffectFamily.REVIEW_CASE, "rvw_aaaa0001aaaa0001"),
        (5, IdentityEffectFamily.REVIEW_CASE, "rvw_bbbb0002bbbb0002"),
    ]
    shuffled = sequence_effects(
        (change.draft for change in reversed(changes)),
        identity_operation_id="eiop_aaaa0001aaaa0001",
        principal_id=PRINCIPAL,
        recorded_at=WHEN,
    )
    assert [(effect.sequence, effect.family, effect.record_id) for effect in shuffled] == ordered
    assert [change.record_id for change in sorted(changes, key=_ledger_order)] == [
        record_id for _, _, record_id in ordered
    ]


# --- the idempotency identity ------------------------------------------------


def _command(**overrides: object) -> MergeCommand:
    base = MergeCommand(
        principal_id=PRINCIPAL,
        preview_id="eipv_aaaa0001aaaa0001",
        preview_digest="a" * 64,
        idempotency_key="merge-one",
        reason="two synthetic records are one person",
        evidence_refs=("eobs_aaaa0001aaaa01", "eobs_bbbb0002bbbb02"),
        choices=(("eals_aaaa0001aaaa01", ConflictChoice.REPARENT),),
    )
    return replace(base, **overrides)  # type: ignore[arg-type]


def test_the_same_request_digests_the_same_however_its_sets_are_ordered() -> None:
    reversed_refs = _command(evidence_refs=("eobs_bbbb0002bbbb02", "eobs_aaaa0001aaaa01"))
    assert _request_digest(_command()) == _request_digest(reversed_refs)


def test_the_preview_normalizes_the_merged_away_set_before_persistence() -> None:
    service = IdentityCorrectionService(None, None)  # type: ignore[arg-type]
    command = MergePreviewCommand(
        principal_id=PRINCIPAL,
        survivor_entity_id=SURVIVOR,
        expected_survivor_version=1,
        merged_away=((MERGED_TWO, 2), (MERGED_ONE, 1)),
        reason="two synthetic records are one person",
    )
    assert service._validated_request(command) == ((MERGED_ONE, 1), (MERGED_TWO, 2))


def test_a_different_reason_is_a_different_request() -> None:
    assert _request_digest(_command()) != _request_digest(_command(reason="something else"))


def test_a_different_disposition_is_a_different_request() -> None:
    other = _command(choices=(("eals_aaaa0001aaaa01", ConflictChoice.COALESCE),))
    assert _request_digest(_command()) != _request_digest(other)


def test_re_previewing_the_same_binding_is_still_the_same_request() -> None:
    """The preview identifier is not in the digest; the binding it carries is."""
    assert _request_digest(_command()) == _request_digest(
        _command(preview_id="eipv_bbbb0002bbbb0002")
    )


def test_a_different_binding_is_a_different_request() -> None:
    assert _request_digest(_command()) != _request_digest(_command(preview_digest="b" * 64))
