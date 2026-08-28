"""Which record each `entities.` write may cite as evidence, and why they differ.

`knowledge.entity_fact_evidence_links` admits three kinds of cited record — an
entity observation, a capture span, or a knowledge record — and exactly one per
row. The write half of the entity plane does **not** admit all three from every
capability, and the three work packages that built it each admitted a different
subset. This module is the reconciliation: it states which capability admits
which kind, derives the answer from the commands rather than restating it, and
binds the argument for the split so a later widening reddens here instead of
arriving silently.

**The split is by what the schema can prove, not by preference.**

* The four directed writes classified by `OBSERVATION_CITERS` carry
  `evidence_refs` and admit `eobs_…` only. `entity_fact_evidence_links` carries
  a composite `(entity_observation_id, principal_id)` foreign key to `entity_observations`,
  so an observation belonging to another Principal is refused by the database.
  Nothing rests on an application check.
* The four identifier and alias writes that carry `evidence` admit `span_…`
  only. `capture_spans` carries no Principal column at all, so ownership is
  proven by an application join through `capture_versions` to
  `captures.owner_principal_id` — the check `_record_evidence` makes and says it
  makes. That is a weaker mechanism than the one above, and it is the reason
  those two families were not merged into one field during integration:
  admitting spans everywhere would spread the weaker proof across the plane, and
  admitting observations everywhere would silently drop a citation form one
  capability already accepts.
* `entities.proposals.create` is the typed producer surface: each bounded entry
  names a role and exactly one observation, span, or knowledge record. It is
  classified separately because it intentionally admits all three kinds rather
  than one of the directed-write subsets.
* `knowledge_id` is admitted only by that proposal producer. No canonical
  directed write can cite it directly.
* The four governed identity-correction capabilities also cite observations,
  through their operator-only merge/split preview/execution shapes rather than a
  directed-write command.

**`entities.unresolved_mentions.resolve` cites nothing a caller names.** Its
evidence links are minted server-side — a rejected pairing is recorded as
counterevidence so the resolver does not offer it again — so there is no field
here to bind and the capability is asserted to have none.
"""

from __future__ import annotations

import dataclasses
from collections.abc import Mapping
from typing import Final, get_args

import pytest

from my_pa.application.commands import (
    AddEntityAlias,
    BindEntityIdentifier,
    Command,
    CreateEntityAssignment,
    CreateEntityProposal,
    CreateEntityRelationship,
    ReviseEntityAssignment,
    ReviseEntityRelationship,
    SupersedeEntityAlias,
    SupersedeEntityIdentifier,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.relationship.authoring import CallerNamespace
from my_pa.domain.relationship.entity import (
    AliasType,
    AssignmentType,
    EntityRelationshipType,
)
from my_pa.domain.relationship.proposal_payload import EntityProposalKind
from my_pa.domain.source.registry import issue_identifier

ENTITY: Final = issue_identifier(IdKind.ENTITY)
SCOPE: Final = issue_identifier(IdKind.ENTITY)
ASSIGNMENT: Final = issue_identifier(IdKind.ASSIGNMENT)
RELATIONSHIP: Final = issue_identifier(IdKind.ENTITY_RELATIONSHIP)
IDENTIFIER: Final = issue_identifier(IdKind.EXTERNAL_IDENTIFIER)
ALIAS: Final = issue_identifier(IdKind.ENTITY_ALIAS)

#: The three kinds `entity_fact_evidence_links` can cite, and one well-formed
#: identifier of each. Minted rather than spelled, so a change to a prefix moves
#: this module with the domain instead of leaving it asserting an old shape.
CITED_KINDS: Final[dict[str, str]] = {
    "observation": issue_identifier(IdKind.ENTITY_OBSERVATION),
    "capture_span": issue_identifier(IdKind.SPAN),
    "knowledge": issue_identifier(IdKind.KNOWLEDGE),
}


def _with_observation_refs(capability: Capability, references: tuple[str, ...]) -> Command:
    """One directed write carrying the references, and nothing else out of shape."""
    match capability:
        case Capability.ENTITIES_ASSIGNMENTS_CREATE:
            return CreateEntityAssignment(
                entity_id=ENTITY,
                expected_entity_version=1,
                assignment_type=AssignmentType.PROJECT_ASSIGNMENT,
                idempotency_key="evidence-scope-assignment-create",
                evidence_refs=references,
            )
        case Capability.ENTITIES_ASSIGNMENTS_REVISE:
            return ReviseEntityAssignment(
                assignment_id=ASSIGNMENT,
                expected_version=1,
                idempotency_key="evidence-scope-assignment-revise",
                evidence_refs=references,
            )
        case Capability.ENTITIES_RELATIONSHIPS_CREATE:
            return CreateEntityRelationship(
                from_entity_id=ENTITY,
                expected_from_version=1,
                relationship_type=EntityRelationshipType.WORKS_FOR,
                to_entity_id=SCOPE,
                expected_to_version=1,
                idempotency_key="evidence-scope-relationship-create",
                evidence_refs=references,
            )
        case Capability.ENTITIES_RELATIONSHIPS_REVISE:
            return ReviseEntityRelationship(
                relationship_id=RELATIONSHIP,
                expected_version=1,
                idempotency_key="evidence-scope-relationship-revise",
                evidence_refs=references,
            )
        case _:  # pragma: no cover - the parametrisation below is closed
            raise AssertionError(capability)


def _with_span_evidence(capability: Capability, references: tuple[str, ...]) -> Command:
    """One identifier or alias write carrying the references."""
    match capability:
        case Capability.ENTITIES_IDENTIFIERS_BIND:
            return BindEntityIdentifier(
                entity_id=ENTITY,
                expected_version=1,
                namespace=CallerNamespace.EMAIL,
                display_value="evidence.scope@example.invalid",
                idempotency_key="evidence-scope-bind",
                evidence=references,
            )
        case Capability.ENTITIES_IDENTIFIERS_SUPERSEDE:
            return SupersedeEntityIdentifier(
                entity_id=ENTITY,
                expected_version=1,
                identifier_id=IDENTIFIER,
                expected_identifier_version=1,
                namespace=CallerNamespace.EMAIL,
                display_value="evidence.scope.new@example.invalid",
                reason="A synthetic replacement.",
                idempotency_key="evidence-scope-supersede-identifier",
                evidence=references,
            )
        case Capability.ENTITIES_ALIASES_ADD:
            return AddEntityAlias(
                entity_id=ENTITY,
                expected_version=1,
                alias_type=AliasType.NICKNAME,
                display_value="Ev",
                idempotency_key="evidence-scope-add-alias",
                evidence=references,
            )
        case Capability.ENTITIES_ALIASES_SUPERSEDE:
            return SupersedeEntityAlias(
                entity_id=ENTITY,
                expected_version=1,
                alias_id=ALIAS,
                expected_alias_version=1,
                alias_type=AliasType.NICKNAME,
                display_value="Evie",
                reason="A synthetic correction.",
                idempotency_key="evidence-scope-supersede-alias",
                evidence=references,
            )
        case _:  # pragma: no cover - the parametrisation below is closed
            raise AssertionError(capability)


OBSERVATION_CITERS: Final[tuple[Capability, ...]] = (
    Capability.ENTITIES_ASSIGNMENTS_CREATE,
    Capability.ENTITIES_ASSIGNMENTS_REVISE,
    Capability.ENTITIES_RELATIONSHIPS_CREATE,
    Capability.ENTITIES_RELATIONSHIPS_REVISE,
)


def _commands() -> Mapping[Capability, type]:
    """Every command there is, by the capability it serves.

    Read off the `Command` union the way `adapters/mcp/tools.py` reads it, so
    the population this module sweeps is the plane's own rather than a list
    written here.
    """
    return {member.capability: member for member in get_args(Command.__value__)}


SPAN_CITERS: Final[tuple[Capability, ...]] = (
    Capability.ENTITIES_IDENTIFIERS_BIND,
    Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
    Capability.ENTITIES_ALIASES_ADD,
    Capability.ENTITIES_ALIASES_SUPERSEDE,
)

MULTI_SOURCE_CITERS: Final[frozenset[Capability]] = frozenset(
    {Capability.ENTITIES_PROPOSALS_CREATE}
)


def _with_proposal_evidence(kind: str, reference: str) -> CreateEntityProposal:
    target = {
        "observation": "entity_observation_id",
        "capture_span": "capture_span_id",
        "knowledge": "knowledge_id",
    }[kind]
    return CreateEntityProposal(
        kind=EntityProposalKind.RECORD_ALIAS,
        payload={
            "entity_id": ENTITY,
            "alias_type": "nickname",
            "display_value": "Ev",
        },
        evidence=({"role": "supporting", target: reference},),
    )


#: The four governed identity-correction capabilities, which cite observations
#: and are not in the producer or directed-write classifications above.
#:
#: A separate classification because governed merge and split cite observations
#: through operator-only preview/execution shapes. Folding them into
#: `OBSERVATION_CITERS` would put it through a directed-write constructor sweep
#: that cannot build it and would prove nothing about its actual contract.
IDENTITY_CITERS: Final[frozenset[Capability]] = frozenset(
    {
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
    }
)


@pytest.mark.parametrize("capability", OBSERVATION_CITERS)
@pytest.mark.parametrize("kind", sorted(CITED_KINDS))
def test_a_directed_write_cites_an_observation_and_refuses_the_other_two(
    capability: Capability, kind: str
) -> None:
    """Derived by construction, so a widened validator reddens here."""
    reference = CITED_KINDS[kind]
    if kind == "observation":
        assert _with_observation_refs(capability, (reference,)) is not None
        return
    with pytest.raises(InvalidRequestError):
        _with_observation_refs(capability, (reference,))


@pytest.mark.parametrize("capability", SPAN_CITERS)
@pytest.mark.parametrize("kind", sorted(CITED_KINDS))
def test_an_identifier_or_alias_write_cites_a_span_and_refuses_the_other_two(
    capability: Capability, kind: str
) -> None:
    """The other half of the split, asserted the same way."""
    reference = CITED_KINDS[kind]
    if kind == "capture_span":
        assert _with_span_evidence(capability, (reference,)) is not None
        return
    with pytest.raises(InvalidRequestError):
        _with_span_evidence(capability, (reference,))


@pytest.mark.parametrize(("kind", "reference"), tuple(CITED_KINDS.items()))
def test_the_proposal_producer_admits_each_typed_evidence_source(kind: str, reference: str) -> None:
    assert _with_proposal_evidence(kind, reference) is not None


def test_only_the_proposal_producer_admits_a_knowledge_record() -> None:
    """The third column is producer-only, stated once rather than eight times.

    A guard rather than a comment: `entity_fact_evidence_links.knowledge_id`
    exists, so which caller can fill it is a property of the write surface that
    can stop being true, and this is where it would.
    """
    knowledge = CITED_KINDS["knowledge"]
    for capability in OBSERVATION_CITERS:
        with pytest.raises(InvalidRequestError):
            _with_observation_refs(capability, (knowledge,))
    for capability in SPAN_CITERS:
        with pytest.raises(InvalidRequestError):
            _with_span_evidence(capability, (knowledge,))
    assert _with_proposal_evidence("knowledge", knowledge) is not None


def test_every_entity_citing_shape_is_exhaustively_classified() -> None:
    """The population, read off the commands rather than off this file.

    Every write capability whose command declares an `evidence` or
    `evidence_refs` field is in exactly one classification above. A new citing
    write added to the plane and not to this module reddens, which is the failure
    this guard exists for: the subsets above are only meaningful if exhaustive.
    """
    citing = {
        capability
        for capability, shape in _commands().items()
        if capability.value.startswith("entities.")
        and ({"evidence", "evidence_refs"} & {f.name for f in dataclasses.fields(shape)})
    }
    assert citing == (
        set(OBSERVATION_CITERS) | set(SPAN_CITERS) | MULTI_SOURCE_CITERS | IDENTITY_CITERS
    )


def test_the_resolution_write_names_no_evidence_a_caller_supplied() -> None:
    """Its links are minted server-side, so there is no field to bind."""
    shape = _commands()[Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE]
    named = {field.name for field in dataclasses.fields(shape)}
    assert "evidence" not in named
    assert "evidence_refs" not in named
