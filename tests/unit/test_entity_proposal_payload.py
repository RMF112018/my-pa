"""The proposal payload: what it must carry, and what it may never carry.

WP-RI-B-05 replaced an untyped mapping with a per-kind schema, and the reason
was not tidiness: `entities.proposals.create` makes the payload a remote
caller's input, so the field set is a caller-controlled surface. Every refusal
below is a route by which a caller could otherwise have named a value the server
owns -- its own Principal, its own review result, its own proposal method -- and
had it stored as if the server had accepted it.

The last test in this file is the load-bearing one: it reads the *actual*
dataclass fields of the canonical `entities.*` commands and proves each schema
names a subset of them. Without it the schemas are seventeen hand-written lists
that agree with the commands on the day they were written.
"""

from __future__ import annotations

import dataclasses
from typing import Final

import pytest

from my_pa.application import commands
from my_pa.domain.identity.operation import Capability
from my_pa.domain.relationship.authoring import (
    MAX_ENTITY_NAME_CHARACTERS,
    MAX_IDENTIFIER_VALUE_CHARACTERS,
)
from my_pa.domain.relationship.governance import (
    ENTITY_CHANGE_REASON_LIMIT,
    OPEN_EQUIVALENT_PROPOSAL_STATES,
    EntityProposalMethod,
    EntityProposalState,
    ReviewRequirement,
    requirement_for,
)
from my_pa.domain.relationship.proposal_payload import (
    FORBIDDEN_PAYLOAD_FIELDS,
    PROPOSAL_PAYLOAD_VALUE_LIMIT,
    EntityProposalKind,
    EntityProposalPayload,
    ProposalPayloadError,
    dedupe_digest,
    schema_for,
)

ALICE: Final = "ent_aaaa0001aaaa0001"
ALICE_TWO: Final = "ent_bbbb0002bbbb0002"

#: One valid payload per kind, so every test below can reach every kind without
#: each of them restating seventeen mappings.
VALID: Final[dict[EntityProposalKind, dict[str, str | bool]]] = {
    EntityProposalKind.CREATE_ENTITY: {"entity_type": "person", "display_name": "Alice Chen"},
    EntityProposalKind.UPDATE_ENTITY: {"entity_id": ALICE, "reason": "spelling"},
    EntityProposalKind.BIND_IDENTIFIER: {
        "entity_id": ALICE,
        "namespace": "email",
        "display_value": "alice@example.invalid",
    },
    EntityProposalKind.RETIRE_IDENTIFIER: {
        "entity_id": ALICE,
        "identifier_id": "xid_aaaa0001aaaa0001",
        "reason": "left the company",
    },
    EntityProposalKind.SUPERSEDE_IDENTIFIER: {
        "entity_id": ALICE,
        "identifier_id": "xid_aaaa0001aaaa0001",
        "namespace": "email",
        "display_value": "a.chen@example.invalid",
        "reason": "address changed",
    },
    EntityProposalKind.RECORD_ALIAS: {
        "entity_id": ALICE,
        "alias_type": "nickname",
        "display_value": "Ali",
    },
    EntityProposalKind.RETIRE_ALIAS: {
        "entity_id": ALICE,
        "alias_id": "eals_aaaa0001aaaa0001",
        "reason": "never used",
    },
    EntityProposalKind.SUPERSEDE_ALIAS: {
        "entity_id": ALICE,
        "alias_id": "eals_aaaa0001aaaa0001",
        "alias_type": "preferred_name",
        "display_value": "A. Chen",
        "reason": "prefers initials",
    },
    EntityProposalKind.RECORD_ASSIGNMENT: {
        "entity_id": ALICE,
        "assignment_type": "employment",
    },
    EntityProposalKind.REVISE_ASSIGNMENT: {
        "assignment_id": "asn_aaaa0001aaaa0001",
        "role": "principal",
    },
    EntityProposalKind.END_ASSIGNMENT: {
        "assignment_id": "asn_aaaa0001aaaa0001",
        "reason": "role ended",
        "end_now": True,
    },
    EntityProposalKind.RECORD_RELATIONSHIP: {
        "from_entity_id": ALICE,
        "relationship_type": "works_for",
        "to_entity_id": ALICE_TWO,
    },
    EntityProposalKind.REVISE_RELATIONSHIP: {
        "relationship_id": "erel_aaaa0001aaaa0001",
        "effective_from": "2026-01-01T00:00:00+00:00",
    },
    EntityProposalKind.END_RELATIONSHIP: {
        "relationship_id": "erel_aaaa0001aaaa0001",
        "reason": "edge no longer holds",
    },
    EntityProposalKind.RESOLVE_MENTION: {
        "observation_id": "eobs_aaaa0001aaaa0001",
        "disposition": "link_existing",
        "entity_id": ALICE,
    },
    EntityProposalKind.MERGE_ENTITIES: {
        "retained_entity_id": ALICE,
        "merged_entity_id": ALICE_TWO,
    },
    EntityProposalKind.SPLIT_IDENTITY: {"entity_id": ALICE},
}


def a_payload(kind: EntityProposalKind) -> EntityProposalPayload:
    return EntityProposalPayload.of(kind, VALID[kind])


# --- the closed vocabularies -------------------------------------------------


def test_the_seventeen_kinds_are_exactly_the_frozen_set() -> None:
    """`MYPA-RI-COMP-03`'s list, and nothing a producer invented beside it."""
    assert {kind.value for kind in EntityProposalKind} == {
        "create_entity",
        "update_entity",
        "bind_identifier",
        "retire_identifier",
        "supersede_identifier",
        "record_alias",
        "retire_alias",
        "supersede_alias",
        "record_assignment",
        "revise_assignment",
        "end_assignment",
        "record_relationship",
        "revise_relationship",
        "end_relationship",
        "resolve_mention",
        "merge_entities",
        "split_identity",
    }


def test_the_eight_states_are_exactly_the_frozen_set() -> None:
    assert {state.value for state in EntityProposalState} == {
        "proposed",
        "needs_review",
        "accepted",
        "corrected_accepted",
        "rejected",
        "deferred",
        "superseded",
        "invalidated",
    }


def test_no_method_names_a_cloud_model_or_a_hybrid() -> None:
    """The absence is the point: a named method is a method a caller may ask for."""
    assert {method.value for method in EntityProposalMethod} == {
        "deterministic",
        "rule",
        "local_model",
    }


def test_every_kind_carries_a_review_requirement() -> None:
    """A kind with no entry would raise at read time rather than refuse at write."""
    for kind in EntityProposalKind:
        assert isinstance(requirement_for(kind), ReviewRequirement)


def test_identity_correction_kinds_require_the_operator() -> None:
    """Section 8.4: a merge is never eligible for whatever clears an alias."""
    assert requirement_for(EntityProposalKind.MERGE_ENTITIES) is ReviewRequirement.REQUIRES_OPERATOR
    assert requirement_for(EntityProposalKind.SPLIT_IDENTITY) is ReviewRequirement.REQUIRES_OPERATOR


def test_a_subtractive_kind_is_never_automatically_acceptable() -> None:
    """Adding an alias may clear a threshold; removing a resolution path may not."""
    subtractive = (
        EntityProposalKind.RETIRE_IDENTIFIER,
        EntityProposalKind.SUPERSEDE_IDENTIFIER,
        EntityProposalKind.RETIRE_ALIAS,
        EntityProposalKind.SUPERSEDE_ALIAS,
        EntityProposalKind.END_ASSIGNMENT,
        EntityProposalKind.END_RELATIONSHIP,
    )
    for kind in subtractive:
        assert requirement_for(kind) is not ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY


def test_open_equivalent_states_include_a_deferral() -> None:
    """Otherwise re-filing an identical proposal would clear a reviewer's deferral."""
    assert set(OPEN_EQUIVALENT_PROPOSAL_STATES) == {
        EntityProposalState.PROPOSED,
        EntityProposalState.NEEDS_REVIEW,
        EntityProposalState.DEFERRED,
    }


# --- what a payload may never carry -----------------------------------------


@pytest.mark.parametrize("forbidden", sorted(FORBIDDEN_PAYLOAD_FIELDS))
def test_no_payload_carries_a_server_owned_field(forbidden: str) -> None:
    """Every name in the forbidden set, on a payload that is otherwise valid.

    Parametrized over the set itself rather than over a sample, so a name added
    to it without a refusal behind it cannot pass unnoticed.
    """
    values = dict(VALID[EntityProposalKind.RECORD_ALIAS])
    values[forbidden] = "smuggled"
    with pytest.raises(ProposalPayloadError, match="server-owned field"):
        EntityProposalPayload.of(EntityProposalKind.RECORD_ALIAS, values)


def test_the_forbidden_set_names_each_category_the_contract_lists() -> None:
    """Operator prompt section 11's eight categories, each with a member present."""
    assert "principal_id" in FORBIDDEN_PAYLOAD_FIELDS
    assert "decided_by" in FORBIDDEN_PAYLOAD_FIELDS
    assert "authority" in FORBIDDEN_PAYLOAD_FIELDS
    assert "proposed_at" in FORBIDDEN_PAYLOAD_FIELDS
    assert "superseded_by_entity_id" in FORBIDDEN_PAYLOAD_FIELDS
    assert "expected_version" in FORBIDDEN_PAYLOAD_FIELDS
    assert "idempotency_key" in FORBIDDEN_PAYLOAD_FIELDS
    assert "capability" in FORBIDDEN_PAYLOAD_FIELDS
    assert "purpose" in FORBIDDEN_PAYLOAD_FIELDS


def test_no_schema_admits_a_forbidden_field() -> None:
    """The two guards agree: nothing a schema lists is something the set refuses."""
    for kind in EntityProposalKind:
        assert not schema_for(kind).admitted & FORBIDDEN_PAYLOAD_FIELDS


def test_a_payload_cannot_propose_a_merged_redirect_status() -> None:
    """`merged_redirect` is server-owned; a schema admitting `status` admits the word."""
    with pytest.raises(ProposalPayloadError, match="status a caller may ask for"):
        EntityProposalPayload.of(
            EntityProposalKind.UPDATE_ENTITY,
            {"entity_id": ALICE, "reason": "correcting", "status": "merged_redirect"},
        )


def test_a_payload_may_propose_a_status_a_caller_could_have_set() -> None:
    payload = EntityProposalPayload.of(
        EntityProposalKind.UPDATE_ENTITY,
        {"entity_id": ALICE, "reason": "left", "status": "inactive"},
    )
    assert payload.as_mapping()["status"] == "inactive"


def test_no_payload_carries_evidence_references() -> None:
    """Evidence lives in `entity_proposal_evidence_links`, which is Principal-scoped."""
    for name in ("evidence", "evidence_refs", "observation_ids"):
        values = dict(VALID[EntityProposalKind.RECORD_ALIAS])
        values[name] = "span_aaaa0001aaaa0001"
        with pytest.raises(ProposalPayloadError):
            EntityProposalPayload.of(EntityProposalKind.RECORD_ALIAS, values)


# --- the per-kind schema ------------------------------------------------------


@pytest.mark.parametrize("kind", list(EntityProposalKind))
def test_every_kind_accepts_its_own_valid_payload(kind: EntityProposalKind) -> None:
    assert a_payload(kind).kind is kind


@pytest.mark.parametrize("kind", list(EntityProposalKind))
def test_no_kind_accepts_a_field_its_command_does_not_take(kind: EntityProposalKind) -> None:
    values = dict(VALID[kind])
    values["invented_field"] = "anything"
    with pytest.raises(ProposalPayloadError, match="only fields its kind's command takes"):
        EntityProposalPayload.of(kind, values)


@pytest.mark.parametrize("kind", list(EntityProposalKind))
def test_no_kind_accepts_a_payload_missing_a_required_field(kind: EntityProposalKind) -> None:
    required = sorted(schema_for(kind).required)
    values = {name: value for name, value in VALID[kind].items() if name != required[0]}
    with pytest.raises(ProposalPayloadError, match="every field its kind requires"):
        EntityProposalPayload.of(kind, values)


def test_a_payload_value_is_a_string_or_a_flag() -> None:
    values: dict[str, object] = dict(VALID[EntityProposalKind.RECORD_ALIAS])
    values["display_value"] = 7
    with pytest.raises(ProposalPayloadError, match="string or a flag"):
        EntityProposalPayload.of(EntityProposalKind.RECORD_ALIAS, values)  # type: ignore[arg-type]


def test_a_payload_value_is_bounded() -> None:
    values = dict(VALID[EntityProposalKind.RECORD_ALIAS])
    values["display_value"] = "a" * (PROPOSAL_PAYLOAD_VALUE_LIMIT + 1)
    with pytest.raises(ProposalPayloadError, match="bounded"):
        EntityProposalPayload.of(EntityProposalKind.RECORD_ALIAS, values)


def test_a_payload_value_is_not_blank() -> None:
    values = dict(VALID[EntityProposalKind.RECORD_ALIAS])
    values["display_value"] = "   "
    with pytest.raises(ProposalPayloadError, match="blank"):
        EntityProposalPayload.of(EntityProposalKind.RECORD_ALIAS, values)


def test_the_value_bound_clears_every_field_the_schemas_admit() -> None:
    """The ceiling is stated in its own module; this proves it is wide enough.

    A name, an external identity's display value and a bounded reason are the
    three widest things any admitted field carries, and each has its own rule in
    the command that takes it.
    """
    assert PROPOSAL_PAYLOAD_VALUE_LIMIT >= MAX_ENTITY_NAME_CHARACTERS
    assert PROPOSAL_PAYLOAD_VALUE_LIMIT >= MAX_IDENTIFIER_VALUE_CHARACTERS
    assert PROPOSAL_PAYLOAD_VALUE_LIMIT >= ENTITY_CHANGE_REASON_LIMIT


def test_a_payload_is_stored_in_name_order() -> None:
    """Out of order the digest would depend on a producer's iteration order."""
    with pytest.raises(ProposalPayloadError, match="name order"):
        EntityProposalPayload(
            kind=EntityProposalKind.MERGE_ENTITIES,
            values=(("retained_entity_id", ALICE), ("merged_entity_id", ALICE_TWO)),
        )


def test_a_payload_names_each_field_once() -> None:
    with pytest.raises(ProposalPayloadError, match="each field once"):
        EntityProposalPayload(
            kind=EntityProposalKind.SPLIT_IDENTITY,
            values=(("entity_id", ALICE), ("entity_id", ALICE_TWO)),
        )


def test_a_flag_survives_the_round_trip_as_a_flag() -> None:
    payload = a_payload(EntityProposalKind.END_ASSIGNMENT)
    assert payload.as_mapping()["end_now"] is True


# --- the dedupe digest --------------------------------------------------------


def test_the_same_request_digests_the_same_however_it_was_built() -> None:
    """Two producers building the same mapping in different orders collide."""
    first = EntityProposalPayload.of(
        EntityProposalKind.MERGE_ENTITIES,
        {"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
    )
    second = EntityProposalPayload.of(
        EntityProposalKind.MERGE_ENTITIES,
        {"merged_entity_id": ALICE_TWO, "retained_entity_id": ALICE},
    )
    assert dedupe_digest(first) == dedupe_digest(second)
    assert first == second


def test_the_same_payload_under_a_different_kind_digests_differently() -> None:
    """Otherwise a split proposal would dedupe against the merge it reverses."""
    merge = EntityProposalPayload.of(
        EntityProposalKind.MERGE_ENTITIES,
        {"retained_entity_id": ALICE, "merged_entity_id": ALICE_TWO},
    )
    split = EntityProposalPayload.of(EntityProposalKind.SPLIT_IDENTITY, {"entity_id": ALICE})
    assert dedupe_digest(merge) != dedupe_digest(split)


def test_a_different_request_digests_differently() -> None:
    first = a_payload(EntityProposalKind.RECORD_ALIAS)
    second = EntityProposalPayload.of(
        EntityProposalKind.RECORD_ALIAS,
        {"entity_id": ALICE, "alias_type": "nickname", "display_value": "Alicia"},
    )
    assert dedupe_digest(first) != dedupe_digest(second)


def test_the_digest_is_a_sha256_digest() -> None:
    digest = dedupe_digest(a_payload(EntityProposalKind.RECORD_ALIAS))
    assert len(digest) == 64
    assert set(digest) <= set("0123456789abcdef")


# --- the schemas are the commands' own field names ---------------------------

#: Which canonical capability would carry out each kind. Fifteen of the
#: seventeen; `merge_entities` and `split_identity` are absent because WP-06 and
#: WP-07 own them and neither capability exists at this revision, which is
#: asserted below rather than assumed.
_CAPABILITY_BY_KIND: Final[dict[EntityProposalKind, str]] = {
    EntityProposalKind.CREATE_ENTITY: "entities.create",
    EntityProposalKind.UPDATE_ENTITY: "entities.update",
    EntityProposalKind.BIND_IDENTIFIER: "entities.identifiers.bind",
    EntityProposalKind.RETIRE_IDENTIFIER: "entities.identifiers.retire",
    EntityProposalKind.SUPERSEDE_IDENTIFIER: "entities.identifiers.supersede",
    EntityProposalKind.RECORD_ALIAS: "entities.aliases.add",
    EntityProposalKind.RETIRE_ALIAS: "entities.aliases.retire",
    EntityProposalKind.SUPERSEDE_ALIAS: "entities.aliases.supersede",
    EntityProposalKind.RECORD_ASSIGNMENT: "entities.assignments.create",
    EntityProposalKind.REVISE_ASSIGNMENT: "entities.assignments.revise",
    EntityProposalKind.END_ASSIGNMENT: "entities.assignments.end",
    EntityProposalKind.RECORD_RELATIONSHIP: "entities.relationships.create",
    EntityProposalKind.REVISE_RELATIONSHIP: "entities.relationships.revise",
    EntityProposalKind.END_RELATIONSHIP: "entities.relationships.end",
    EntityProposalKind.RESOLVE_MENTION: "entities.unresolved_mentions.resolve",
}


def _command_fields(capability_value: str) -> frozenset[str]:
    capability = Capability(capability_value)
    for value in vars(commands).values():
        if (
            isinstance(value, type)
            and dataclasses.is_dataclass(value)
            and getattr(value, "capability", None) is capability
        ):
            return frozenset(field.name for field in dataclasses.fields(value))
    raise AssertionError(f"no command carries {capability_value}")


@pytest.mark.parametrize("kind", sorted(_CAPABILITY_BY_KIND, key=lambda item: item.value))
def test_each_schema_names_only_fields_its_canonical_command_takes(
    kind: EntityProposalKind,
) -> None:
    """The binding that makes promotion a construction rather than a translation.

    Read from `dataclasses.fields` of the live command, so a command that
    renames a field reddens here rather than at the moment a reviewer accepts a
    proposal and the promoter passes a keyword nothing takes.
    """
    admitted = schema_for(kind).admitted
    taken = _command_fields(_CAPABILITY_BY_KIND[kind])
    assert admitted <= taken, f"{sorted(admitted - taken)} is not taken by {kind.value}'s command"


def test_the_two_identity_correction_kinds_have_no_canonical_command_yet() -> None:
    """Stated rather than left implicit: their absence above is a fact, not a gap.

    `entities.merge` arrives with WP-06 and `entities.split` with WP-07. If
    either name appears in `Capability`, this kind's schema has a command to be
    read against and belongs in the mapping above.
    """
    published = {capability.value for capability in Capability}
    assert "entities.merge" not in published
    assert "entities.split" not in published
