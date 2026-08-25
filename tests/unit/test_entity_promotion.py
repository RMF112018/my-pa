"""What an accepted proposal promotes to, and what it must never promote to.

Two properties carry this file.

**Promotion routes; it does not reimplement.** Section 14 of the Phase B
contract requires an accepted ordinary proposal to execute through the canonical
Phase A service, and the way that is proved here is constructive: for every one
of the fifteen ordinary kinds, the fields `promotion_for` produces are combined
with the fields only the promoting transaction can supply and the *real*
canonical command is constructed from them. A field this module renamed, dropped
or converted wrongly cannot survive that, because the command's own
`__post_init__` is the thing checking it.

**Acceptance of an identity correction promotes nothing.** `merge_entities` and
`split_identity` have no canonical command and are refused. That refusal is the
promotion-side half of `WP-RI-B-05`: `EntityGovernanceService` no longer merges
on acceptance, and this makes sure the mutation does not reappear by being
routed to instead.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Final

import pytest

from my_pa.adapters.mcp.tools import payload_schema_for
from my_pa.adapters.normalization import normalize
from my_pa.application.commands import CreateEntityProposal
from my_pa.application.entity_promotion import (
    UnpromotableProposalError,
    evidence_links_for,
    promotion_for,
    requires_expected_target_version,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.relationship.entity import AliasType, EntityStatus, EntityType
from my_pa.domain.relationship.governance import (
    IDENTITY_CORRECTION_PROPOSAL_KINDS,
    EntityProposal,
    EntityProposalEvidenceLink,
    EntityProposalKind,
    EntityProposalMethod,
    EntityProposalState,
    EvidenceRole,
    MutationAuthority,
    MutationRecordFamily,
    ResolutionDisposition,
)
from my_pa.domain.relationship.proposal_payload import (
    EntityProposalPayload,
    dedupe_digest,
    schema_for,
)

PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
PROPOSAL: Final = "eprp_aaaa0001aaaa0001"
ALICE: Final = "ent_aaaa0001aaaa0001"
ACME: Final = "ent_bbbb0002bbbb0002"
ALIAS: Final = "eals_aaaa0001aaaa0001"
IDENTIFIER: Final = "xid_aaaa0001aaaa0001"
ASSIGNMENT: Final = "asn_aaaa0001aaaa0001"
RELATIONSHIP: Final = "erel_aaaa0001aaaa0001"
OBSERVATION: Final = "eobs_aaaa0001aaaa0001"

WHEN: Final = datetime(2026, 8, 18, 12, tzinfo=UTC)
LATER: Final = datetime(2026, 8, 18, 13, tzinfo=UTC)


def exact_evidence(
    *observation_ids: str, role: EvidenceRole = EvidenceRole.SUPPORTING
) -> tuple[EntityProposalEvidenceLink, ...]:
    return tuple(
        EntityProposalEvidenceLink(
            proposal_id=PROPOSAL,
            principal_id=PRINCIPAL,
            sequence=sequence,
            role=role,
            created_at=WHEN,
            entity_observation_id=observation_id,
        )
        for sequence, observation_id in enumerate(observation_ids, start=1)
    )


PUBLIC_EVIDENCE: Final = ({"role": "supporting", "entity_observation_id": OBSERVATION},)

#: One well-formed payload per ordinary kind.
#:
#: Written out rather than generated from `schema_for`, because two of the
#: schemas admit fields that are mutually exclusive at the command --
#: `end_assignment` and `end_relationship` take an effective end *or* "as of
#: now", and a generator filling every admitted field would build a request the
#: command is right to refuse. A generated table would therefore have had to
#: carry exceptions for the two kinds whose rules are most worth exercising.
PAYLOADS: Final[dict[EntityProposalKind, dict[str, str | bool]]] = {
    EntityProposalKind.CREATE_ENTITY: {
        "entity_type": "person",
        "display_name": "Alice Chen",
        "reason": "named in three contact records",
    },
    EntityProposalKind.UPDATE_ENTITY: {
        "entity_id": ALICE,
        "reason": "she has left the company",
        "status": "inactive",
    },
    EntityProposalKind.BIND_IDENTIFIER: {
        "entity_id": ALICE,
        "namespace": "email",
        "display_value": "a.chen@acme.invalid",
        "effective_from": "2026-01-01T00:00:00+00:00",
    },
    EntityProposalKind.RETIRE_IDENTIFIER: {
        "entity_id": ALICE,
        "identifier_id": IDENTIFIER,
        "reason": "the address bounced for a month",
    },
    EntityProposalKind.SUPERSEDE_IDENTIFIER: {
        "entity_id": ALICE,
        "identifier_id": IDENTIFIER,
        "namespace": "email",
        "display_value": "alice.chen@acme.invalid",
        "reason": "the domain was renamed",
    },
    EntityProposalKind.RECORD_ALIAS: {
        "entity_id": ALICE,
        "alias_type": "nickname",
        "display_value": "Ali",
        "reason": "signed off that way in four messages",
    },
    EntityProposalKind.RETIRE_ALIAS: {
        "entity_id": ALICE,
        "alias_id": ALIAS,
        "reason": "she asked for it to stop being used",
    },
    EntityProposalKind.SUPERSEDE_ALIAS: {
        "entity_id": ALICE,
        "alias_id": ALIAS,
        "alias_type": "former_name",
        "display_value": "Alice Okonkwo",
        "reason": "corrected spelling",
    },
    EntityProposalKind.RECORD_ASSIGNMENT: {
        "entity_id": ALICE,
        "assignment_type": "employment",
        "scope_entity_id": ACME,
        "role": "Structural lead",
        "effective_from": "2026-02-01T00:00:00+00:00",
    },
    EntityProposalKind.REVISE_ASSIGNMENT: {
        "assignment_id": ASSIGNMENT,
        "role": "Principal structural engineer",
    },
    EntityProposalKind.END_ASSIGNMENT: {
        "assignment_id": ASSIGNMENT,
        "reason": "the secondment finished",
        "effective_end": "2026-06-30T00:00:00+00:00",
    },
    EntityProposalKind.RECORD_RELATIONSHIP: {
        "from_entity_id": ALICE,
        "relationship_type": "works_for",
        "to_entity_id": ACME,
    },
    EntityProposalKind.REVISE_RELATIONSHIP: {
        "relationship_id": RELATIONSHIP,
        "effective_from": "2026-03-01T00:00:00+00:00",
    },
    EntityProposalKind.END_RELATIONSHIP: {
        "relationship_id": RELATIONSHIP,
        "reason": "the contract ended",
        "end_now": True,
    },
    EntityProposalKind.RESOLVE_MENTION: {
        "observation_id": OBSERVATION,
        "disposition": "link_existing",
        "entity_id": ALICE,
    },
}

ORDINARY_KINDS: Final = tuple(
    kind for kind in EntityProposalKind if kind not in IDENTITY_CORRECTION_PROPOSAL_KINDS
)


def public_payload(kind: EntityProposalKind) -> dict[str, str | bool]:
    if kind in PAYLOADS:
        return PAYLOADS[kind]
    if kind is EntityProposalKind.MERGE_ENTITIES:
        return {"retained_entity_id": ALICE, "merged_entity_id": ACME, "reason": "duplicate"}
    return {"entity_id": ALICE, "reason": "incorrect prior merge"}


@pytest.mark.parametrize("kind", tuple(EntityProposalKind), ids=lambda kind: kind.value)
def test_public_expected_target_version_is_required_exactly_for_existing_targets(
    kind: EntityProposalKind,
) -> None:
    expected = 0 if kind is EntityProposalKind.RESOLVE_MENTION else 1
    if requires_expected_target_version(kind):
        with pytest.raises(InvalidRequestError):
            CreateEntityProposal(kind=kind, payload=public_payload(kind), evidence=PUBLIC_EVIDENCE)
        CreateEntityProposal(
            kind=kind,
            payload=public_payload(kind),
            evidence=PUBLIC_EVIDENCE,
            expected_target_version=expected,
        )
    else:
        CreateEntityProposal(kind=kind, payload=public_payload(kind), evidence=PUBLIC_EVIDENCE)
        with pytest.raises(InvalidRequestError):
            CreateEntityProposal(
                kind=kind,
                payload=public_payload(kind),
                evidence=PUBLIC_EVIDENCE,
                expected_target_version=1,
            )


def test_public_proposal_requires_typed_exact_evidence_and_has_no_proposed_by_field() -> None:
    with pytest.raises(InvalidRequestError):
        CreateEntityProposal(
            kind=EntityProposalKind.RECORD_ALIAS,
            payload=PAYLOADS[EntityProposalKind.RECORD_ALIAS],
            evidence=(),
        )
    assert "proposed_by" not in {field.name for field in dataclasses.fields(CreateEntityProposal)}


def test_public_proposal_schema_publishes_bounded_typed_evidence() -> None:
    schema = payload_schema_for(CreateEntityProposal)
    assert "evidence" in schema["required"]
    assert "proposed_by" not in schema["properties"]
    evidence = schema["properties"]["evidence"]
    assert evidence["minItems"] == 1
    assert evidence["maxItems"] == 8
    assert evidence["items"]["required"] == ["role"]
    assert len(evidence["items"]["oneOf"]) == 3


def test_public_normalization_refuses_caller_controlled_proposed_by() -> None:
    with pytest.raises(InvalidRequestError):
        normalize(
            "entities.proposals.create",
            {
                "request_id": "req-entity-proposal",
                "purpose": "entity_proposal",
                "principal_id": PRINCIPAL,
                "requested_at": WHEN.isoformat(),
                "payload": {
                    "kind": "record_alias",
                    "payload": PAYLOADS[EntityProposalKind.RECORD_ALIAS],
                    "evidence": list(PUBLIC_EVIDENCE),
                    "proposed_by": "caller-controlled",
                },
            },
        )


def a_proposal(
    kind: EntityProposalKind,
    *,
    state: EntityProposalState = EntityProposalState.ACCEPTED,
    observation_ids: tuple[str, ...] = (),
) -> EntityProposal:
    payload = EntityProposalPayload.of(kind, PAYLOADS[kind])
    decided = state in (EntityProposalState.ACCEPTED, EntityProposalState.CORRECTED_ACCEPTED)
    return EntityProposal(
        proposal_id=PROPOSAL,
        principal_id=PRINCIPAL,
        kind=kind,
        state=state,
        payload=payload,
        observation_ids=observation_ids,
        proposed_at=WHEN,
        proposed_by="extractor",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
        dedupe_sha256=dedupe_digest(payload),
        decided_by="a reviewer" if decided else None,
        decided_at=LATER if decided else None,
        decision_reason="accepted" if decided else None,
    )


def _corrupted_payload(
    kind: EntityProposalKind, values: tuple[tuple[str, str | bool], ...]
) -> EntityProposalPayload:
    """Simulate a corrupt persisted row without weakening payload admission."""
    payload = object.__new__(EntityProposalPayload)
    object.__setattr__(payload, "kind", kind)
    object.__setattr__(payload, "values", values)
    return payload


# --- the table is complete, and complete in both directions ------------------


def test_every_ordinary_kind_promotes_to_exactly_one_canonical_command() -> None:
    """Fifteen kinds, fifteen commands, and no two kinds sharing one.

    A shared entry would mean two different proposals producing the same
    mutation, which is either a duplicate kind or a promotion pointed at the
    wrong command; both are worth reddening on.
    """
    commands = [promotion_for(a_proposal(kind)).command for kind in ORDINARY_KINDS]
    assert len(commands) == 15
    assert len(set(commands)) == 15


@pytest.mark.parametrize("kind", IDENTITY_CORRECTION_PROPOSAL_KINDS, ids=lambda kind: kind.value)
def test_an_accepted_identity_correction_promotes_nothing(kind: EntityProposalKind) -> None:
    """Section 15, held on the promotion side. See the module docstring.

    Constructed by hand rather than through `a_proposal`, because `PAYLOADS`
    deliberately holds no entry for these two: a fixture that could build one
    would be a fixture that believed they promote.
    """
    payload = EntityProposalPayload.of(
        kind,
        {"retained_entity_id": ALICE, "merged_entity_id": ACME}
        if kind is EntityProposalKind.MERGE_ENTITIES
        else {"entity_id": ALICE},
    )
    accepted = EntityProposal(
        proposal_id=PROPOSAL,
        principal_id=PRINCIPAL,
        kind=kind,
        state=EntityProposalState.ACCEPTED,
        payload=payload,
        observation_ids=(),
        proposed_at=WHEN,
        proposed_by="resolver",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
        dedupe_sha256=dedupe_digest(payload),
        decided_by="the operator",
        decided_at=LATER,
        decision_reason="confirmed",
    )
    with pytest.raises(UnpromotableProposalError, match="promotes nothing"):
        promotion_for(accepted)


@pytest.mark.parametrize(
    "state",
    [
        EntityProposalState.PROPOSED,
        EntityProposalState.NEEDS_REVIEW,
        EntityProposalState.REJECTED,
        EntityProposalState.DEFERRED,
        EntityProposalState.INVALIDATED,
        EntityProposalState.SUPERSEDED,
    ],
    ids=lambda state: state.value,
)
def test_only_an_accepted_proposal_promotes(state: EntityProposalState) -> None:
    """A promotion is the execution of a decision, so an undecided one has none."""
    kind = EntityProposalKind.RECORD_ALIAS
    payload = EntityProposalPayload.of(kind, PAYLOADS[kind])
    decided = state in (
        EntityProposalState.REJECTED,
        EntityProposalState.DEFERRED,
        EntityProposalState.INVALIDATED,
    )
    proposal = EntityProposal(
        proposal_id=PROPOSAL,
        principal_id=PRINCIPAL,
        kind=kind,
        state=state,
        payload=payload,
        observation_ids=(),
        proposed_at=WHEN,
        proposed_by="extractor",
        method=EntityProposalMethod.DETERMINISTIC,
        method_version="1",
        dedupe_sha256=dedupe_digest(payload),
        decided_by="a reviewer" if decided else None,
        decided_at=LATER if decided else None,
        decision_reason="no" if decided else None,
        invalidated_reason=(
            "the source record was withdrawn" if state is EntityProposalState.INVALIDATED else None
        ),
        superseded_at=LATER if state is EntityProposalState.SUPERSEDED else None,
    )
    with pytest.raises(UnpromotableProposalError, match="has been accepted"):
        promotion_for(proposal)


def test_a_corrected_acceptance_promotes_like_an_acceptance() -> None:
    """`correct_and_accept` is an acceptance of a corrected payload, not a third thing."""
    call = promotion_for(
        a_proposal(EntityProposalKind.RECORD_ALIAS, state=EntityProposalState.CORRECTED_ACCEPTED)
    )
    assert call.fields["display_value"] == "Ali"


# --- the fields are the command's fields --------------------------------------


@pytest.mark.parametrize("kind", ORDINARY_KINDS, ids=lambda kind: kind.value)
def test_every_field_a_kind_may_propose_is_a_field_of_its_command(
    kind: EntityProposalKind,
) -> None:
    """The promise `proposal_payload` makes, checked against the command itself.

    This is what lets promotion rename nothing. If a schema ever admits a name
    the command does not take, the payload would be storable and unpromotable —
    a proposal a reviewer could accept and nothing could carry out.
    """
    call = promotion_for(a_proposal(kind))
    admitted = schema_for(kind).admitted
    taken = {item.name for item in dataclasses.fields(call.command)}
    assert admitted <= taken, sorted(admitted - taken)


@pytest.mark.parametrize("kind", ORDINARY_KINDS, ids=lambda kind: kind.value)
def test_a_promotion_produces_no_version_and_no_idempotency_key(
    kind: EntityProposalKind,
) -> None:
    """Both belong to the moment of promotion. See the module docstring of the source.

    A stale expected version carried from proposal time is a version check that
    has stopped checking, and a key derived from the proposal would make a
    reviewer's second decision replay the first one's receipt.
    """
    produced = set(promotion_for(a_proposal(kind)).fields)
    assert "idempotency_key" not in produced
    assert not any(name.startswith("expected_") for name in produced), sorted(produced)


@pytest.mark.parametrize("kind", ORDINARY_KINDS, ids=lambda kind: kind.value)
def test_every_promotion_constructs_the_real_canonical_command(
    kind: EntityProposalKind,
) -> None:
    """The load-bearing test in this file, and the one that cannot go vacuous.

    The command's own `__post_init__` validates every identifier, every closed
    vocabulary member, every bound and every mutually-exclusive pair. So a
    promotion that produced an unconverted `"nickname"` where `AliasType` is
    required, an ISO string where a `datetime` is required, or a field name the
    command does not take is refused here by the canonical constructor rather
    than by an expectation this file wrote down.

    The context fields are derived rather than listed: every expected version the
    command carries plus its idempotency key is exactly the set the promoting
    transaction owns, and each is filled by what its name says it is. Derived
    over *all* the command's fields rather than only its required ones, because
    two of these commands make an expected version required by the presence of
    another field -- an `entity_id` on a `link_existing` obliges its version --
    and a required-only derivation would silently stop supplying it.
    """
    call = promotion_for(a_proposal(kind))
    context = {
        item.name
        for item in dataclasses.fields(call.command)
        if item.name == "idempotency_key" or item.name.startswith("expected_")
    } - set(call.fields)
    if "scope_entity_id" not in call.fields:
        # An expected version is stated exactly when the thing it is about is.
        # Two commands take an optional scope, and supplying a version for a
        # scope nobody named is a request they are right to refuse.
        context.discard("expected_scope_version")
    assert context, "every canonical command needs something only the transaction can supply"
    supplied: dict[str, object] = {
        name: "idem-promotion-0001" if name == "idempotency_key" else 1 for name in context
    }
    required = {
        item.name
        for item in dataclasses.fields(call.command)
        if item.default is dataclasses.MISSING and item.default_factory is dataclasses.MISSING
    }
    assert required <= set(call.fields) | context, sorted(required - set(call.fields) - context)
    built = call.command(**call.fields, **supplied)
    assert built.capability is call.capability


# --- the conversions ----------------------------------------------------------


def test_a_closed_vocabulary_field_arrives_as_its_member() -> None:
    call = promotion_for(a_proposal(EntityProposalKind.RECORD_ALIAS))
    assert call.fields["alias_type"] is AliasType.NICKNAME
    assert call.fields["display_value"] == "Ali"


def test_an_instant_arrives_as_an_aware_datetime() -> None:
    call = promotion_for(a_proposal(EntityProposalKind.BIND_IDENTIFIER))
    effective_from = call.fields["effective_from"]
    assert isinstance(effective_from, datetime)
    assert effective_from.tzinfo is not None
    assert effective_from == datetime(2026, 1, 1, tzinfo=UTC)


def test_a_flag_arrives_as_a_boolean() -> None:
    call = promotion_for(a_proposal(EntityProposalKind.END_RELATIONSHIP))
    assert call.fields["end_now"] is True


def test_other_vocabularies_arrive_as_their_members() -> None:
    """One assertion each for the five remaining closed vocabularies.

    Together with the alias case above this covers every entry in the
    conversion table, so an entry silently dropped from it reddens.
    """
    assert (
        promotion_for(a_proposal(EntityProposalKind.CREATE_ENTITY)).fields["entity_type"]
        is EntityType.PERSON
    )
    assert (
        promotion_for(a_proposal(EntityProposalKind.UPDATE_ENTITY)).fields["status"]
        is EntityStatus.INACTIVE
    )
    assert (
        promotion_for(a_proposal(EntityProposalKind.RESOLVE_MENTION)).fields["disposition"]
        is ResolutionDisposition.LINK_EXISTING
    )
    namespace = promotion_for(a_proposal(EntityProposalKind.BIND_IDENTIFIER)).fields["namespace"]
    assert namespace is not None
    assert str(namespace) == "email"
    assignment_type = promotion_for(a_proposal(EntityProposalKind.RECORD_ASSIGNMENT)).fields[
        "assignment_type"
    ]
    assert str(assignment_type) == "employment"
    relationship_type = promotion_for(a_proposal(EntityProposalKind.RECORD_RELATIONSHIP)).fields[
        "relationship_type"
    ]
    assert str(relationship_type) == "works_for"


def test_a_stored_value_outside_its_vocabulary_is_refused_at_promotion() -> None:
    """A row written around the payload record still cannot promote.

    `EntityProposalPayload` refuses the value on the way in, so this is defence
    in depth over the same rule — and it is the layer that matters for a row
    that reached the table by some other route, which is the case the plane's
    other read-side re-checks exist for.
    """
    proposal = a_proposal(EntityProposalKind.RECORD_ALIAS)
    smuggled = dataclasses.replace(
        proposal,
        payload=_corrupted_payload(
            EntityProposalKind.RECORD_ALIAS,
            (
                ("alias_type", "endearment"),
                ("display_value", "Ali"),
                ("entity_id", ALICE),
            ),
        ),
    )
    with pytest.raises(UnpromotableProposalError, match="outside its vocabulary"):
        promotion_for(smuggled)


def test_a_stored_instant_that_is_not_iso_8601_is_refused_at_promotion() -> None:
    proposal = a_proposal(EntityProposalKind.BIND_IDENTIFIER)
    smuggled = dataclasses.replace(
        proposal,
        payload=_corrupted_payload(
            EntityProposalKind.BIND_IDENTIFIER,
            (
                ("display_value", "a.chen@acme.invalid"),
                ("effective_from", "last Tuesday"),
                ("entity_id", ALICE),
                ("namespace", "email"),
            ),
        ),
    )
    with pytest.raises(UnpromotableProposalError, match="ISO-8601"):
        promotion_for(smuggled)


# --- evidence survives promotion ----------------------------------------------


def test_promoted_evidence_links_cite_the_observations_and_carry_review_authority() -> None:
    """Section 14: evidence links must survive promotion, under the right authority.

    The canonical command's own `evidence` tuple cannot carry these — it takes
    capture spans — so the observations a producer cited would otherwise be lost
    at exactly the moment the fact becomes canonical.
    """
    links = evidence_links_for(
        exact_evidence(OBSERVATION, "eobs_bbbb0002bbbb0002"),
        principal_id=PRINCIPAL,
        record_family=MutationRecordFamily.ALIAS,
        record_id=ALIAS,
        at=LATER,
    )
    assert [link.entity_observation_id for link in links] == [
        OBSERVATION,
        "eobs_bbbb0002bbbb0002",
    ]
    assert {link.alias_id for link in links} == {ALIAS}
    assert {link.principal_id for link in links} == {PRINCIPAL}
    assert {link.role for link in links} == {EvidenceRole.SUPPORTING}
    assert {link.authority for link in links} == {MutationAuthority.REVIEW_ACCEPTED}
    assert len({link.link_id for link in links}) == 2


def test_promotion_preserves_span_knowledge_and_counterevidence_roles() -> None:
    evidence = (
        EntityProposalEvidenceLink(
            proposal_id=PROPOSAL,
            principal_id=PRINCIPAL,
            sequence=1,
            role=EvidenceRole.DIRECT,
            created_at=WHEN,
            capture_span_id="span_aaaa0001aaaa0001",
        ),
        EntityProposalEvidenceLink(
            proposal_id=PROPOSAL,
            principal_id=PRINCIPAL,
            sequence=2,
            role=EvidenceRole.COUNTEREVIDENCE,
            created_at=WHEN,
            knowledge_id="kn_aaaa0001aaaa0001",
        ),
    )
    links = evidence_links_for(
        evidence,
        principal_id=PRINCIPAL,
        record_family=MutationRecordFamily.ALIAS,
        record_id=ALIAS,
        at=LATER,
    )
    assert links[0].capture_span_id == "span_aaaa0001aaaa0001"
    assert links[0].role is EvidenceRole.DIRECT
    assert links[1].knowledge_id == "kn_aaaa0001aaaa0001"
    assert links[1].role is EvidenceRole.COUNTEREVIDENCE


def test_a_promotion_authority_is_review_acceptance_and_not_the_users_own() -> None:
    """The value section 14 names, and the two it must not be.

    A promoted fact recorded as `user_confirmed_assertion` claims the user
    asserted what a source or a model asserted; one recorded as
    `system_deterministic` claims it could be recomputed from what is already
    held. Neither is what happened, and `MutationAuthority` already holds the
    member that is.
    """
    links = evidence_links_for(
        exact_evidence(OBSERVATION),
        principal_id=PRINCIPAL,
        record_family=MutationRecordFamily.ALIAS,
        record_id=ALIAS,
        at=LATER,
    )
    assert links[0].authority is MutationAuthority.REVIEW_ACCEPTED
    assert links[0].authority is not MutationAuthority.USER_CONFIRMED_ASSERTION
    assert links[0].authority is not MutationAuthority.SYSTEM_DETERMINISTIC


@pytest.mark.parametrize(
    ("family", "record_id", "attribute"),
    [
        (MutationRecordFamily.ENTITY, ALICE, "entity_id"),
        (MutationRecordFamily.IDENTIFIER, IDENTIFIER, "identifier_id"),
        (MutationRecordFamily.ALIAS, ALIAS, "alias_id"),
        (MutationRecordFamily.ASSIGNMENT, ASSIGNMENT, "assignment_id"),
        (MutationRecordFamily.RELATIONSHIP, RELATIONSHIP, "relationship_id"),
    ],
    ids=lambda value: str(value),
)
def test_each_promoted_family_fills_its_own_fact_column(
    family: MutationRecordFamily, record_id: str, attribute: str
) -> None:
    """`EntityFactEvidenceLink` refuses a row naming two facts, so the column matters."""
    (link,) = evidence_links_for(
        exact_evidence(OBSERVATION),
        principal_id=PRINCIPAL,
        record_family=family,
        record_id=record_id,
        at=LATER,
    )
    assert getattr(link, attribute) == record_id


def test_an_observation_promotion_writes_no_evidence_link() -> None:
    """A `resolve_mention` promotion's subject is the observation. See the source."""
    with pytest.raises(UnpromotableProposalError, match="no promoted evidence link"):
        evidence_links_for(
            exact_evidence(OBSERVATION),
            principal_id=PRINCIPAL,
            record_family=MutationRecordFamily.OBSERVATION,
            record_id=OBSERVATION,
            at=LATER,
        )


def test_an_empty_exact_evidence_set_produces_no_links() -> None:
    assert (
        evidence_links_for(
            (),
            principal_id=PRINCIPAL,
            record_family=MutationRecordFamily.ALIAS,
            record_id=ALIAS,
            at=LATER,
        )
        == ()
    )
