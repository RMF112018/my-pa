"""The two producer capabilities, answered end to end through `invoke`.

`WP-RI-B-05` publishes `entities.proposals.create` and
`relationship_memory.propose`, and every other file that touches them checks a
registry, a schema or a refusal. This one drives each of them through
`ApplicationService.invoke` — the same entry point every transport reaches — and
reads the receipt, because operator section 37 makes "it works" the acceptance
criterion and a manifest entry is not that.

Three things are asserted that nothing else can assert from a registry:

* **what the receipt carries, and what it does not.** The entity producer is
  handed a proposal identifier, its state, what it will need before it can be
  accepted, the digest that makes a repeat a refusal rather than a second row,
  the server-minted review case and its initial version, the digest that makes a
  repeat a refusal rather than a second row, and the audit reference. The memory
  producer is also handed a case identifier — a candidate written without one
  would be invisible to every reviewer — and **no statement**, because
  a `sensitivity` candidate floors at `restricted_local` and the read plane
  withholds restricted statements from search.
* **that a repeat is answered rather than multiplied.** Operator section 11
  requires open-equivalent dedupe, and the admission's `created` flag is how a
  producer tells "recorded" from "already open" without the two being one answer.
* **that neither path can promote what it proposed.** A proposal lands in a state
  that awaits a decision, and the producer's own receipt says so.

The plane is composed here and the composition is the point of the file it is
*not* in: `tests/contract/test_entity_write_gate.py` proves the switches withhold
these names, and this proves that a build with the switches on answers.
"""

from __future__ import annotations

from typing import Any, Final

import pytest
from tests.conftest import Scene, build_service, metadata_for
from tests.contract.test_transport_parity import staged_entities, staged_mention

from my_pa.application.commands import (
    Command,
    CreateEntityProposal,
    ProposeRelationshipMemory,
)
from my_pa.application.entity_promotion import requires_expected_target_version
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.proposal import ProposalState
from my_pa.domain.common.identifiers import IdKind, parse_identifier
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.relationship.governance import EntityProposalMethod, ReviewRequirement
from my_pa.domain.relationship.memory import MemoryKind, MemoryProposalState
from my_pa.domain.relationship.proposal_payload import EntityProposalKind

#: The alias a producer proposes. `record_alias` on purpose: it is the one kind
#: `requirement_for` admits to a configured threshold, so a receipt that reported
#: `requires_review` for it would be reporting the requirement map wrongly rather
#: than reporting a conservative default.
ALIAS_VALUE: Final = "PP"


def _result(scene: Scene, capability: Capability, purpose: Purpose, command: Command) -> Any:  # noqa: ANN401 - a canonical envelope payload
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(capability, purpose, scene.principal),
        command,
        principal=scene.principal,
    )
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    return envelope.result


def _proposal(scene: Scene, *, kind: EntityProposalKind, payload: dict[str, str | bool]) -> Any:  # noqa: ANN401 - a canonical envelope payload
    expected = 1 if requires_expected_target_version(kind) else None
    return _result(
        scene,
        Capability.ENTITIES_PROPOSALS_CREATE,
        Purpose.ENTITY_PROPOSAL,
        CreateEntityProposal(
            kind=kind,
            payload=payload,
            evidence=({"role": "direct", "entity_observation_id": staged_mention(scene)},),
            expected_target_version=expected,
        ),
    )


def _alias_payload(scene: Scene) -> dict[str, str | bool]:
    person, _organization = staged_entities(scene)
    return {
        "entity_id": person.entity_id,
        "alias_type": "initials",
        "display_value": ALIAS_VALUE,
    }


def test_a_producer_raises_an_entity_proposal_and_is_told_what_it_will_need(
    scene: Scene,
) -> None:
    """`entities.proposals.create`, answered, with the receipt read field by field."""
    result = _proposal(scene, kind=EntityProposalKind.RECORD_ALIAS, payload=_alias_payload(scene))

    assert parse_identifier(str(result["proposal_id"]))[0] is IdKind.ENTITY_PROPOSAL
    assert result["kind"] == EntityProposalKind.RECORD_ALIAS.value
    assert result["created"] is True
    assert result["review_requirement"] == ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY.value
    assert result["evidence_refs"] == [
        {"role": "direct", "entity_observation_id": staged_mention(scene)}
    ]
    assert result["audit_id"]
    # The digest is the server's, and it is disclosed because a producer has to
    # be able to see that a repeat will be recognised as one.
    assert isinstance(result["dedupe_sha256"], str)
    assert len(result["dedupe_sha256"]) == 64


def test_the_entity_receipt_names_its_canonical_review_case(scene: Scene) -> None:
    result = _proposal(scene, kind=EntityProposalKind.RECORD_ALIAS, payload=_alias_payload(scene))
    assert parse_identifier(str(result["review_case_id"]))[0] is IdKind.REVIEW_CASE
    assert result["review_version"] == 0
    assert result["proposal_version"] == 1
    for absent in (
        "principal_id",
        "method",
        "method_version",
        "model_id",
        "model_version",
        "authority",
        "capability",
        "purpose",
    ):
        assert absent not in result, f"the producer's receipt discloses {absent}"


def test_a_review_requiring_kind_says_so_rather_than_defaulting_to_it(scene: Scene) -> None:
    """The requirement is derived from the kind, and the receipt reports which.

    `record_alias` clears a threshold and `create_entity` does not, so a receipt
    that reported the same requirement for both would be reporting a constant.
    """
    person, _organization = staged_entities(scene)
    threshold = _proposal(
        scene, kind=EntityProposalKind.RECORD_ALIAS, payload=_alias_payload(scene)
    )
    reviewed = _proposal(
        scene,
        kind=EntityProposalKind.UPDATE_ENTITY,
        payload={
            "entity_id": person.entity_id,
            "display_name": "Parity Person Revised",
            "reason": "a synthetic correction",
        },
    )

    assert threshold["review_requirement"] == ReviewRequirement.MAY_BE_ACCEPTED_AUTOMATICALLY.value
    assert reviewed["review_requirement"] == ReviewRequirement.REQUIRES_REVIEW.value
    assert reviewed["state"] == ProposalState.NEEDS_REVIEW.value


def test_an_open_equivalent_repeat_is_answered_rather_than_multiplied(scene: Scene) -> None:
    """Operator section 11's dedupe, from the producer's side of it.

    Two producers reaching the same conclusion have proposed the change once, and
    a reviewer shown it twice has to decide the same thing twice. What comes back
    the second time is the *same* proposal with `created` false, so a caller can
    tell "recorded" from "already open" without the two being one answer.
    """
    payload = _alias_payload(scene)
    first = _proposal(scene, kind=EntityProposalKind.RECORD_ALIAS, payload=payload)
    again = _proposal(scene, kind=EntityProposalKind.RECORD_ALIAS, payload=payload)

    assert again["proposal_id"] == first["proposal_id"]
    assert again["dedupe_sha256"] == first["dedupe_sha256"]
    assert first["created"] is True
    assert again["created"] is False
    assert len(scene.world.entity_proposals) == 1


def test_the_recorded_method_is_the_servers_and_is_not_deterministic(scene: Scene) -> None:
    """What the server attests, read off the row rather than off the receipt.

    The receipt does not carry the method — it is not the producer's to know it
    was believed — so this reads the stored proposal. `rule` rather than
    `deterministic`, because filing a producer's work as an exact match is the
    record `EntityProposalMethod`'s own docstring names as the danger, and
    `local_model` is unreachable because nothing passes a model identity.
    """
    _proposal(scene, kind=EntityProposalKind.RECORD_ALIAS, payload=_alias_payload(scene))

    stored = scene.world.entity_proposals[-1]
    assert stored.method is EntityProposalMethod.RULE
    assert stored.method_version == "synthetic-rule-producer.1"
    assert stored.model_id is None
    assert stored.model_version is None


@pytest.mark.parametrize(
    "kind", [MemoryKind.PERSONAL_DETAIL, MemoryKind.SENSITIVITY], ids=lambda item: item.value
)
def test_a_producer_raises_a_candidate_memory_and_is_told_nothing_it_wrote(
    scene: Scene, kind: MemoryKind
) -> None:
    """`relationship_memory.propose`, answered, and the receipt carries no statement.

    Parametrised over an ordinary kind and the one whose classification floors at
    `restricted_local`, because the disclosure claim is only interesting for the
    second: handing the proposed words back through a producer's receipt would be
    a second channel for exactly the text the accepted form is withheld on, and a
    receipt that carried them for one kind and not the other would be a filter
    rather than an absence.
    """
    person, _organization = staged_entities(scene)
    statement = "Parity Person prefers written follow-ups"
    result = _result(
        scene,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Purpose.RELATIONSHIP_MEMORY_PROPOSAL,
        ProposeRelationshipMemory(
            entity_id=person.entity_id,
            expected_entity_version=person.version,
            statement=statement,
            evidence=({"role": "direct", "entity_observation_id": staged_mention(scene)},),
            kind=kind,
        ),
    )

    assert parse_identifier(str(result["memory_proposal_id"]))[0] is (
        IdKind.RELATIONSHIP_MEMORY_PROPOSAL
    )
    assert result["subject_entity_id"] == person.entity_id
    assert result["kind"] == kind.value
    assert result["state"] == MemoryProposalState.NEEDS_REVIEW.value
    assert result["evidence_count"] == 1
    assert result["audit_id"]
    assert statement not in str(result), "the producer's receipt echoed the candidate statement"
    for absent in ("statement", "proposed_statement", "structured_value"):
        assert absent not in result, f"the producer's receipt discloses {absent}"
    # The case identifier *is* disclosed here and is not on the entity plane, and
    # the asymmetry is the plane's rather than an inconsistency:
    # `relationship_memory_review_cases` selects on `review_case_id IS NOT NULL`,
    # so a candidate written without one is invisible to every reviewer.
    assert parse_identifier(str(result["review_case_id"]))[0] is IdKind.REVIEW_CASE


def test_the_classification_floor_is_applied_and_not_chosen(scene: Scene) -> None:
    """A `sensitivity` candidate is restricted whether the producer thought about it.

    The command has no `classification` field, so there is nothing to send; what
    this asserts is that the floor was *applied* rather than defaulted, by
    comparing the two kinds' answers.
    """
    person, _organization = staged_entities(scene)

    def _propose(kind: MemoryKind) -> Any:  # noqa: ANN401 - a canonical envelope payload
        return _result(
            scene,
            Capability.RELATIONSHIP_MEMORY_PROPOSE,
            Purpose.RELATIONSHIP_MEMORY_PROPOSAL,
            ProposeRelationshipMemory(
                entity_id=person.entity_id,
                expected_entity_version=person.version,
                statement=f"A synthetic {kind.value} candidate",
                evidence=({"role": "direct", "entity_observation_id": staged_mention(scene)},),
                kind=kind,
            ),
        )

    ordinary = _propose(MemoryKind.PERSONAL_DETAIL)
    sensitive = _propose(MemoryKind.SENSITIVITY)
    assert ordinary["classification"] != sensitive["classification"]
    assert sensitive["classification"] == "restricted_local"


def test_neither_producer_path_writes_the_thing_it_proposed(scene: Scene) -> None:
    """Operator sections 12 and 16, measured on the world rather than on a port.

    The strongest form of "a producer cannot self-promote" is structural — the
    memory producer holds a port with one insert on it and no memory write — and
    the observable form is this: after both proposals, there is no memory and no
    alias, only two candidate rows awaiting a decision.
    """
    person, _organization = staged_entities(scene)
    before_aliases = len(scene.world.entity_aliases)

    _proposal(scene, kind=EntityProposalKind.RECORD_ALIAS, payload=_alias_payload(scene))
    _result(
        scene,
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Purpose.RELATIONSHIP_MEMORY_PROPOSAL,
        ProposeRelationshipMemory(
            entity_id=person.entity_id,
            expected_entity_version=person.version,
            statement="A synthetic candidate nobody has accepted",
            evidence=({"role": "direct", "entity_observation_id": staged_mention(scene)},),
        ),
    )

    assert len(scene.world.entity_aliases) == before_aliases
    assert scene.world.relationship_memories == []
    assert len(scene.world.entity_proposals) == 1
    assert len(scene.world.relationship_memory_proposals) == 1
    assert len(scene.world.relationship_memory_proposal_evidence) == 1


@pytest.mark.parametrize(
    ("payload", "why"),
    [
        ({"entity_id": "ent_paritypersonparity"}, "a required field is missing"),
        (
            {"entity_id": "ent_paritypersonparity", "reason": "why", "nickname": "Ali"},
            "a field this kind's command does not take",
        ),
        (
            {"entity_id": "ent_paritypersonparity", "reason": "why", "status": "merged_redirect"},
            "a status no caller may ask for",
        ),
    ],
    ids=("missing", "unadmitted", "forbidden-status"),
)
def test_a_payload_its_kind_refuses_is_an_invalid_request_and_not_a_crash(
    scene: Scene, payload: dict[str, str | bool], why: str
) -> None:
    """`ProposalPayloadError` reaches a caller as `invalid_request`, under `payload`.

    **This was `internal_error` until `WP-RI-B-07`, and the defect is worth
    naming.** `EntityProposalPayload` raises `ProposalPayloadError` for every
    schema refusal, `_entity_governance_translated` did not classify it, and
    `invoke`'s terminal handler turned a caller's own correctable mistake into
    "the request could not be completed" — telling a producer the product is
    broken when the truth is that its payload named a field the kind does not
    take. Every one of the three rows here produced that answer.

    The token is `payload` and not the offending field name. A token per admitted
    name would restate seventeen schemas in `SafeDetail`, and it would tell a
    caller which of its fields the schema objected to — which is the one thing a
    closed disclosure vocabulary must not do.
    """
    service = build_service(scene.world, scene.providers)
    envelope = service.invoke(
        metadata_for(
            Capability.ENTITIES_PROPOSALS_CREATE, Purpose.ENTITY_PROPOSAL, scene.principal
        ),
        CreateEntityProposal(
            kind=EntityProposalKind.UPDATE_ENTITY,
            payload=payload,
            evidence=({"role": "direct", "entity_observation_id": staged_mention(scene)},),
            expected_target_version=1,
        ),
        principal=scene.principal,
    )

    assert envelope.result is None
    assert envelope.error is not None, why
    assert envelope.error.code is ErrorCode.INVALID_REQUEST, why
    assert envelope.error.safe_details == ("payload",), why
    assert scene.world.entity_proposals == []
