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
    ConflictChoice,
    MergeCommand,
    _ledger_order,
    _request_digest,
    plan_aliases,
    plan_assignments,
    plan_entities,
    plan_identifiers,
    plan_observations,
    plan_proposals,
    plan_relationships,
)
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Assignment,
    AssignmentState,
    AssignmentType,
    Entity,
    EntityAlias,
    EntityRelationship,
    EntityRelationshipType,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    IdentifierState,
    RelationshipState,
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
        "version": 1,
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
    changes, conflicts = plan_proposals([_proposal("eprp_aaaa0001aaaa01", MERGED_ONE)])
    assert conflicts == ()
    assert [change.kind for change in changes] == [IdentityEffectKind.DEPENDENT_INVALIDATED]
    assert changes[0].before_state == {"state": "proposed"}
    assert changes[0].after_state == {"state": "invalidated"}


def test_a_proposal_bound_to_a_review_case_blocks_the_merge() -> None:
    """Invalidating a Review case is WP-RI-05's disposition and does not exist yet."""
    _, conflicts = plan_proposals(
        [_proposal("eprp_aaaa0001aaaa01", MERGED_ONE, review_case_id="rvw_aaaa0001aaaa0001")]
    )
    assert [conflict.kind for conflict in conflicts] == [IdentityConflictKind.UNSUPPORTED_FAMILY]
    assert conflicts[0].family is IdentityEffectFamily.REVIEW_CASE
    assert conflicts[0].blocks


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
