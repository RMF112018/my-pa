"""Run the labelled resolution corpus and emit a calibration record.

**What "calibrated" means here.** Specification section 22.3 admits a numeric
"only when calibrated and explained". A weight somebody chose is neither. Every
number this module emits is an *observed frequency over a labelled corpus* —
how often an answer of a given kind was the right answer, counted. The record it
writes is the explanation, and `RESOLUTION_CALIBRATION.md` is where a reader
looks up what a `RESOLVED_EXACT` on a verified identifier has actually been
worth.

That is also why no number reaches `domain/relationship`. The plane carries the
*basis* an answer rests on; the reliability of each basis is measured here and
published there, so nothing in the durable model has to hold an opinion about a
person (`D-RI-02`).

**The two metrics that matter, and why both.** `false_resolution_count` must be
zero: a resolver that names the wrong person has done the one thing this whole
plane exists to prevent. But zero is trivially achievable by never resolving
anything, so `resolution_recall` is measured over `MUST_RESOLVE_FAMILIES` and
floored. A resolver has to clear both or it fails — recklessness and uselessness
are both failures, and only measuring both distinguishes them.

Nothing here opens a connection. The corpus is synthetic and in memory.
"""

from __future__ import annotations

import json
import re
from collections import Counter
from pathlib import Path
from typing import Final

from my_pa.application.entity_resolution import EntityResolutionService, ResolutionRequest
from my_pa.contracts.ports import (
    AssignmentWriteRequest,
    DirectedReceipt,
    EntitiesRepository,
    EntityChildPage,
    EntityMutationAdmission,
    EntityMutationReceipt,
    EntitySummary,
    EntityWriteRequest,
    RelationshipWriteRequest,
)
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Assignment,
    Entity,
    EntityAlias,
    EntityOrganizationProfile,
    EntityRelationship,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    IdentifierState,
)
from my_pa.domain.relationship.governance import (
    EntityFactEvidenceLink,
    EntityMergeRecord,
    EntityMutationEvent,
    EntityObservation,
    EntityProposal,
    EntityProposalState,
    EntityResolutionDecision,
    EvidenceRole,
    MutationRecordFamily,
    ObservationState,
)
from my_pa.domain.relationship.resolution import (
    EntityResolution,
    ResolutionBasis,
    ResolutionOutcome,
)
from tests.evaluation.fixtures.resolution_cases import (
    MUST_RESOLVE_FAMILIES,
    RESOLUTION_CASES,
    ResolutionCase,
)
from tests.evaluation.fixtures.resolution_corpus import (
    CORPUS_ALIASES,
    CORPUS_ASSIGNMENTS,
    CORPUS_ENTITIES,
    CORPUS_IDENTIFIERS,
    CORPUS_RELATIONSHIPS,
)

__all__ = [
    "REPORT_PATH",
    "CaseResult",
    "build_repository",
    "compute_calibration_record",
    "load_frozen_record",
    "render_report",
    "run_cases",
]

REPORT_PATH: Final = Path(__file__).resolve().parent / "RESOLUTION_CALIBRATION.md"

#: The floor `resolution_recall` must clear. Set from measurement rather than
#: aspiration: the corpus is deliberately hostile, and the point of the floor is
#: to refuse a resolver that bought its zero false joins by answering nothing.
#: Raising it is a decision; lowering it is a regression.
RECALL_FLOOR: Final = 0.9

#: The disposition vocabulary, in the shape `SEMANTIC_GATE.md` established.
RESOLUTION_SAFE: Final = "RESOLUTION_PRECISION_HELD"
RESOLUTION_UNSAFE: Final = "RESOLUTION_PRECISION_LOST"


class CaseResult:
    """One case, its labelled expectation, and what the resolver actually said."""

    __slots__ = ("case", "resolution")

    def __init__(self, case: ResolutionCase, resolution: EntityResolution) -> None:
        self.case = case
        self.resolution = resolution

    @property
    def candidate_ids(self) -> frozenset[str]:
        return frozenset(candidate.entity_id for candidate in self.resolution.candidates)

    @property
    def is_false_resolution(self) -> bool:
        """The resolver named an entity, and it was not the one the label names.

        Covers both halves of the failure: naming the wrong person, and naming
        anyone at all in a case labelled as one that must not resolve.
        """
        resolved = self.resolution.resolved_entity_id
        if resolved is None:
            return False
        return resolved != self.case.expected_entity_id

    @property
    def is_missed_resolution(self) -> bool:
        """The label names an entity and the resolver declined to."""
        return (
            self.case.expected_entity_id is not None and self.resolution.resolved_entity_id is None
        )

    @property
    def leaked_ids(self) -> frozenset[str]:
        return self.candidate_ids & self.case.must_not_include

    @property
    def missing_required_ids(self) -> frozenset[str]:
        return self.case.must_include - self.candidate_ids

    @property
    def outcome_matches(self) -> bool:
        return self.resolution.outcome is self.case.expected_outcome


class _CorpusRepository(EntitiesRepository):
    """The corpus behind the port, read-only.

    Subclasses the real `EntitiesRepository` rather than duck-typing it, so the
    evaluation cannot pass against a shape the production service could not
    actually be given. The write methods raise: a corpus that could be written
    to could drift mid-run, and every number here depends on the corpus being
    the one the report names.
    """

    def _mine(self, principal_id: str, entity_id: str) -> Entity | None:
        entity = self._entities.get(entity_id)
        return entity if entity is not None and entity.principal_id == principal_id else None

    _entities: Final = {entity.entity_id: entity for entity in CORPUS_ENTITIES}

    # --- reads -----------------------------------------------------------

    def search(
        self,
        principal_id: str,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 50,
    ) -> list[EntitySummary]:
        needle = query.casefold()
        matched = [
            entity
            for entity in CORPUS_ENTITIES
            if entity.principal_id == principal_id
            and (entity_type is None or entity.entity_type is entity_type)
            and needle in entity.canonical_name
        ]
        return [
            EntitySummary(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                canonical_name=entity.canonical_name,
                display_name=entity.display_name,
                status=entity.status,
            )
            for entity in sorted(matched, key=lambda item: item.entity_id)[:limit]
        ]

    def get(self, principal_id: str, entity_id: str) -> Entity | None:
        return self._mine(principal_id, entity_id)

    def entities_by_identifier(
        self,
        principal_id: str,
        namespace: ExternalIdentifierNamespace,
        normalized_value: str,
    ) -> list[tuple[Entity, ExternalIdentifier]]:
        matched: list[tuple[Entity, ExternalIdentifier]] = []
        for identifier in CORPUS_IDENTIFIERS:
            if identifier.principal_id != principal_id:
                continue
            if identifier.namespace is not namespace:
                continue
            if identifier.normalized_value != normalized_value:
                continue
            entity = self._mine(principal_id, identifier.entity_id)
            if entity is not None:
                matched.append((entity, identifier))
        return sorted(matched, key=lambda pair: (pair[0].entity_id, pair[1].identifier_id))

    def entities_by_alias(
        self, principal_id: str, normalized_value: str
    ) -> list[tuple[Entity, EntityAlias]]:
        matched: list[tuple[Entity, EntityAlias]] = []
        for alias in CORPUS_ALIASES:
            if alias.principal_id != principal_id or alias.normalized_value != normalized_value:
                continue
            entity = self._mine(principal_id, alias.entity_id)
            if entity is not None:
                matched.append((entity, alias))
        return sorted(matched, key=lambda pair: (pair[0].entity_id, pair[1].alias_id))

    def entities_by_canonical_name(self, principal_id: str, normalized_value: str) -> list[Entity]:
        return sorted(
            (
                entity
                for entity in CORPUS_ENTITIES
                if entity.principal_id == principal_id and entity.canonical_name == normalized_value
            ),
            key=lambda entity: entity.entity_id,
        )

    def external_identifiers(self, principal_id: str, entity_id: str) -> list[ExternalIdentifier]:
        return [
            identifier
            for identifier in CORPUS_IDENTIFIERS
            if identifier.principal_id == principal_id and identifier.entity_id == entity_id
        ]

    def aliases(self, principal_id: str, entity_id: str) -> list[EntityAlias]:
        return [
            alias
            for alias in CORPUS_ALIASES
            if alias.principal_id == principal_id and alias.entity_id == entity_id
        ]

    # RI-ENT-WP-06b's six Entity-bound families: resolution never reads any
    # of them, and the corpus carries no fixture data for them, so every
    # accessor below follows this class's own established pattern for a
    # family it does not need -- raise, on the same terms as `observations`.

    def names(self, principal_id: str, entity_id: str, *, limit: int | None = None) -> list:
        raise NotImplementedError("resolution reads no name form")

    def organization_profile(
        self, principal_id: str, entity_id: str
    ) -> EntityOrganizationProfile | None:
        raise NotImplementedError("resolution reads no organization profile")

    def addresses(self, principal_id: str, entity_id: str, *, limit: int | None = None) -> list:
        raise NotImplementedError("resolution reads no address")

    def communication_methods(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list:
        raise NotImplementedError("resolution reads no communication method")

    def project_participations_as_project(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list:
        raise NotImplementedError("resolution reads no project participation")

    def project_participations_as_participant(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list:
        raise NotImplementedError("resolution reads no project participation")

    def person_organization_affiliations_as_person(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list:
        raise NotImplementedError("resolution reads no person affiliation")

    def person_organization_affiliations_as_organization(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list:
        raise NotImplementedError("resolution reads no person affiliation")

    # RI-ENT-WP-08's write path for the same six families: resolution writes
    # to none of them, so each raises on this class's own established terms.
    # Declared rather than inherited because the port makes them abstract --
    # which is the point of declaring them there: an implementer has to say
    # what it does about the write path, even when the answer is "nothing".

    def record_entity_name(self, principal_id: str, entity_name: object) -> None:
        raise NotImplementedError("resolution writes no name form")

    def supersede_entity_name(self, principal_id: str, **arguments: object) -> None:
        raise NotImplementedError("resolution writes no name form")

    def retire_entity_name(self, principal_id: str, **arguments: object) -> None:
        raise NotImplementedError("resolution writes no name form")

    def record_organization_profile(self, principal_id: str, profile: object) -> None:
        raise NotImplementedError("resolution writes no organization profile")

    def revise_organization_profile(self, principal_id: str, **arguments: object) -> None:
        raise NotImplementedError("resolution writes no organization profile")

    def record_entity_address(self, principal_id: str, address: object) -> None:
        raise NotImplementedError("resolution writes no address")

    def supersede_entity_address(self, principal_id: str, **arguments: object) -> None:
        raise NotImplementedError("resolution writes no address")

    def retire_entity_address(self, principal_id: str, **arguments: object) -> None:
        raise NotImplementedError("resolution writes no address")

    def record_communication_method(self, principal_id: str, method: object) -> None:
        raise NotImplementedError("resolution writes no communication method")

    def supersede_communication_method(self, principal_id: str, **arguments: object) -> None:
        raise NotImplementedError("resolution writes no communication method")

    def retire_communication_method(self, principal_id: str, **arguments: object) -> None:
        raise NotImplementedError("resolution writes no communication method")

    def record_project_participation(self, principal_id: str, participation: object) -> None:
        raise NotImplementedError("resolution writes no project participation")

    def supersede_project_participation(self, principal_id: str, **arguments: object) -> None:
        raise NotImplementedError("resolution writes no project participation")

    def retire_project_participation(self, principal_id: str, **arguments: object) -> None:
        raise NotImplementedError("resolution writes no project participation")

    def record_person_organization_affiliation(
        self, principal_id: str, affiliation: object
    ) -> None:
        raise NotImplementedError("resolution writes no person affiliation")

    def supersede_person_organization_affiliation(
        self, principal_id: str, **arguments: object
    ) -> None:
        raise NotImplementedError("resolution writes no person affiliation")

    def retire_person_organization_affiliation(
        self, principal_id: str, **arguments: object
    ) -> None:
        raise NotImplementedError("resolution writes no person affiliation")

    def assignments(
        self, principal_id: str, entity_id: str, active_only: bool = True
    ) -> list[Assignment]:
        return [
            assignment
            for assignment in CORPUS_ASSIGNMENTS
            if assignment.principal_id == principal_id
            and assignment.entity_id == entity_id
            and (not active_only or assignment.status == "active")
        ]

    def relationships(
        self, principal_id: str, entity_id: str, direction: str = "any"
    ) -> list[EntityRelationship]:
        def touches(relationship: EntityRelationship) -> bool:
            if direction == "outgoing":
                return relationship.from_entity_id == entity_id
            if direction == "incoming":
                return relationship.to_entity_id == entity_id
            return entity_id in (relationship.from_entity_id, relationship.to_entity_id)

        return [
            relationship
            for relationship in CORPUS_RELATIONSHIPS
            if relationship.principal_id == principal_id and touches(relationship)
        ]

    # --- writes, refused --------------------------------------------------

    def create(self, principal_id: str, entity: Entity) -> Entity:
        raise NotImplementedError("the evaluation corpus is frozen")

    def record_alias(self, principal_id: str, alias: EntityAlias) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def bind_identifier(
        self, principal_id: str, entity_id: str, identifier: ExternalIdentifier
    ) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def record_assignment(self, principal_id: str, assignment: Assignment) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def record_relationship(self, principal_id: str, rel: EntityRelationship) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    # --- the directed-relationship write path, which resolution does not use --
    #
    # Present because the port declares them, and refusing rather than
    # answering for the reason the governance block below states: a corpus that
    # could be written to could drift mid-run, and every figure in the report
    # depends on the corpus being the one it names. The two *reads* refuse too,
    # because resolution corroborates through `assignments`, not through the
    # paged read the capability uses, and a harness that answered both would let
    # a change in which one the resolver calls pass unnoticed.

    def assignment(self, principal_id: str, assignment_id: str) -> Assignment | None:
        raise NotImplementedError("resolution reads no assignment by identifier")

    def relationship(self, principal_id: str, relationship_id: str) -> EntityRelationship | None:
        raise NotImplementedError("resolution reads no edge by identifier")

    def assignments_page(
        self,
        principal_id: str,
        entity_id: str,
        *,
        active_only: bool,
        limit: int,
        after_assignment_id: str | None = None,
    ) -> list[Assignment]:
        raise NotImplementedError("resolution reads the assignment collection whole")

    def directed_replay(
        self,
        capability: str,
        idempotency_key: str,
        payload_digest: str,
        *,
        principal_id: str,
    ) -> DirectedReceipt | None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def create_assignment(self, request: AssignmentWriteRequest) -> DirectedReceipt:
        raise NotImplementedError("the evaluation corpus is frozen")

    def revise_assignment(self, request: AssignmentWriteRequest) -> DirectedReceipt:
        raise NotImplementedError("the evaluation corpus is frozen")

    def end_assignment(self, request: AssignmentWriteRequest) -> DirectedReceipt:
        raise NotImplementedError("the evaluation corpus is frozen")

    def create_relationship(self, request: RelationshipWriteRequest) -> DirectedReceipt:
        raise NotImplementedError("the evaluation corpus is frozen")

    def revise_relationship(self, request: RelationshipWriteRequest) -> DirectedReceipt:
        raise NotImplementedError("the evaluation corpus is frozen")

    def end_relationship(self, request: RelationshipWriteRequest) -> DirectedReceipt:
        raise NotImplementedError("the evaluation corpus is frozen")

    # --- governance, which resolution does not use -------------------------
    #
    # Present because the port declares them and absent in substance because
    # resolving reads no observation and decides no proposal. Raising rather
    # than returning empty: a resolver that started consulting these would be
    # silently measured against nothing, and this corpus would say it was fine.

    def record_observation(self, principal_id: str, observation: EntityObservation) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def observations(
        self,
        principal_id: str,
        entity_id: str | None = None,
        *,
        unresolved_only: bool = False,
        limit: int | None = None,
    ) -> list[EntityObservation]:
        raise NotImplementedError("resolution reads no observation")

    def observation(self, principal_id: str, observation_id: str) -> EntityObservation | None:
        raise NotImplementedError("resolution reads no observation")

    def link_observation(self, principal_id: str, observation_id: str, entity_id: str) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    # WP-RI-A-04's three ledgers refuse here for the reason every other write
    # does: this corpus is frozen, and a resolver that started consulting the
    # negative-evidence table would be silently measured against nothing.
    # `refused_entity_ids` reaches the service on the *request* rather than
    # through a read, so the calibration still exercises the withholding rule
    # without this repository answering for it.

    def record_mutation_event(self, principal_id: str, event: EntityMutationEvent) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def mutation_event(
        self, principal_id: str, *, capability: str, idempotency_key: str
    ) -> EntityMutationEvent | None:
        raise NotImplementedError("resolution replays no write")

    def record_resolution_decision(
        self, principal_id: str, decision: EntityResolutionDecision
    ) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def resolution_decisions(
        self,
        principal_id: str,
        observation_id: str | None = None,
        *,
        limit: int | None = None,
    ) -> list[EntityResolutionDecision]:
        raise NotImplementedError("resolution reads no decision")

    def decide_observation(
        self,
        principal_id: str,
        observation_id: str,
        *,
        expected_resolution_version: int,
        entity_id: str | None = None,
        state: ObservationState | None = None,
        state_reason: str | None = None,
    ) -> bool:
        raise NotImplementedError("the evaluation corpus is frozen")

    def record_fact_evidence_link(self, principal_id: str, link: EntityFactEvidenceLink) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def fact_evidence_links(
        self,
        principal_id: str,
        *,
        entity_observation_id: str | None = None,
        role: EvidenceRole | None = None,
        limit: int | None = None,
    ) -> list[EntityFactEvidenceLink]:
        raise NotImplementedError("resolution reads no evidence link")

    def record_proposal(self, principal_id: str, proposal: EntityProposal) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def proposal(self, principal_id: str, proposal_id: str) -> EntityProposal | None:
        raise NotImplementedError("resolution decides no proposal")

    def proposal_target_version(
        self,
        principal_id: str,
        family: MutationRecordFamily,
        record_id: str,
    ) -> int | None:
        raise NotImplementedError("resolution reads no proposal target version")

    def proposals(
        self, principal_id: str, state: EntityProposalState | None = None
    ) -> list[EntityProposal]:
        raise NotImplementedError("resolution decides no proposal")

    def decide_proposal(self, principal_id: str, proposal: EntityProposal) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def record_merge(self, principal_id: str, record: EntityMergeRecord) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def merges(self, principal_id: str, entity_id: str | None = None) -> list[EntityMergeRecord]:
        raise NotImplementedError("resolution reads no merge lineage")

    def redirect_entity(
        self,
        principal_id: str,
        merged_entity_id: str,
        retained_entity_id: str,
        *,
        expected_version: int | None = None,
    ) -> None:
        raise NotImplementedError("the evaluation corpus is frozen")

    # --- the governed write path (WP-RI-A-02), which resolution does not use --
    #
    # Refused rather than answered, on the argument the governance methods above
    # make: a resolver that started writing, or that started paging identifiers
    # and aliases instead of reading them whole, would be measured against
    # nothing here and this corpus would report it fine. The two paged reads are
    # deliberately among them: resolution reads each collection *whole* to
    # decide whether an identifier is conflicted, and a page is the one shape
    # that could let a conflict fall off the end and read as a clean match.

    def admit_mutation(self, request: EntityWriteRequest) -> EntityMutationAdmission:
        raise NotImplementedError("the evaluation corpus is frozen")

    def mutation_replay_for(
        self,
        idempotency_key: str,
        request_digest: str,
        *,
        principal_id: str,
        capability: str,
    ) -> EntityMutationReceipt | None:
        raise NotImplementedError("the evaluation corpus is frozen")

    def identifier_page(
        self,
        entity_id: str,
        *,
        principal_id: str,
        limit: int,
        states: frozenset[IdentifierState] | None = None,
        namespaces: frozenset[ExternalIdentifierNamespace] | None = None,
        after_identifier_id: str | None = None,
    ) -> EntityChildPage[ExternalIdentifier]:
        raise NotImplementedError("resolution reads external identifiers whole")

    def alias_page(
        self,
        entity_id: str,
        *,
        principal_id: str,
        limit: int,
        states: frozenset[AliasState] | None = None,
        alias_types: frozenset[AliasType] | None = None,
        after_alias_id: str | None = None,
    ) -> EntityChildPage[EntityAlias]:
        raise NotImplementedError("resolution reads aliases whole")


def build_repository() -> EntitiesRepository:
    """The corpus, behind the port the service takes."""
    return _CorpusRepository()


def run_cases() -> tuple[CaseResult, ...]:
    """Every labelled case, answered by the production resolver."""
    service = EntityResolutionService(build_repository())
    results: list[CaseResult] = []
    for case in RESOLUTION_CASES:
        request = ResolutionRequest(
            raw_reference=case.reference,
            namespace=case.namespace,
            entity_type=case.entity_type,
            scope_entity_id=case.scope_entity_id,
            as_of=case.as_of,
            # The moment the corpus is evaluated at, as the capability supplies
            # `authorization.at`. Omitted until now, so every case was answered
            # under the no-moment fallback rather than the rule production runs —
            # which is why removing the currency fix entirely left this gate
            # green while unit tests caught it.
            at=case.at,
        )
        results.append(CaseResult(case, service.resolve(case.principal_id, request)))
    return tuple(results)


def _rate(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 0.0


def _basis_calibration(results: tuple[CaseResult, ...]) -> dict[str, dict[str, float | int]]:
    """How often a resolution of each kind was the labelled answer.

    Keyed by `outcome:basis` rather than by basis alone, and the distinction is
    load-bearing. A bare canonical name never resolves on its own -- the domain
    type refuses it -- so the only answers resting on one are
    `resolved_contextual`, where a discriminating signal did the selecting. A
    table keyed by basis alone would report `canonical_name: 1.0` and read as
    though a name were sufficient, which is the exact claim this plane spends
    its whole design refusing.
    """
    attempted: Counter[str] = Counter()
    correct: Counter[str] = Counter()
    for result in results:
        if result.resolution.resolved_entity_id is None:
            continue
        candidate = result.resolution.candidates[0]
        key = f"{result.resolution.outcome.value}:{candidate.strongest_basis.value}"
        attempted[key] += 1
        if not result.is_false_resolution:
            correct[key] += 1
    return {
        key: {
            "resolutions": attempted[key],
            "correct": correct[key],
            "observed_precision": _rate(correct[key], attempted[key]),
        }
        for key in sorted(attempted)
    }


#: Every basis a `resolved_exact` answer is allowed to rest on. `canonical_name`
#: is absent, and the harness asserts the absence: a name alone resolving is the
#: regression the calibration exists to catch, and it must fail here as loudly
#: as it fails in the domain type.
BASES_THAT_MAY_RESOLVE_EXACTLY: Final[frozenset[str]] = frozenset(
    {
        ResolutionBasis.VERIFIED_EXTERNAL_IDENTIFIER.value,
        ResolutionBasis.EXTERNAL_IDENTIFIER.value,
        ResolutionBasis.ALIAS.value,
    }
)


def exact_resolutions_on_a_bare_name(results: tuple[CaseResult, ...]) -> tuple[str, ...]:
    """Cases that resolved exactly on evidence no stronger than a canonical name."""
    return tuple(
        result.case.name
        for result in results
        if result.resolution.outcome is ResolutionOutcome.RESOLVED_EXACT
        and result.resolution.candidates[0].strongest_basis.value
        not in BASES_THAT_MAY_RESOLVE_EXACTLY
    )


def _outcome_counts(results: tuple[CaseResult, ...]) -> dict[str, int]:
    counts = Counter(result.resolution.outcome.value for result in results)
    return {outcome.value: counts.get(outcome.value, 0) for outcome in ResolutionOutcome}


def compute_calibration_record() -> dict[str, object]:
    """The whole measurement, as the record the frozen report must equal."""
    results = run_cases()
    must_resolve = [result for result in results if result.case.family in MUST_RESOLVE_FAMILIES]
    must_not_resolve = [result for result in results if result.case.expected_entity_id is None]

    false_resolutions = [result for result in results if result.is_false_resolution]
    # Two different measurements, and they were one under the wrong name. A
    # forbidden candidate is any entity a case says must never be offered — most
    # of them same-Principal collisions. Cross-Principal leakage is the subset
    # that crossed a partition, which is a different severity and deserves its
    # own number rather than being reported as whichever one a reader assumes.
    forbidden = [result for result in results if result.leaked_ids]
    leaked = [result for result in forbidden if result.case.family == "cross_principal"]
    missing = [result for result in results if result.missing_required_ids]
    mismatched = [result for result in results if not result.outcome_matches]
    resolved_correctly = [
        result
        for result in must_resolve
        if result.resolution.resolved_entity_id == result.case.expected_entity_id
    ]
    withheld_correctly = [
        result for result in must_not_resolve if result.resolution.resolved_entity_id is None
    ]

    recall = _rate(len(resolved_correctly), len(must_resolve))
    record: dict[str, object] = {
        "cases": len(results),
        "case_families": len({result.case.family for result in results}),
        "must_resolve_cases": len(must_resolve),
        "must_not_resolve_cases": len(must_not_resolve),
        "false_resolution_count": len(false_resolutions),
        "false_resolution_rate": _rate(len(false_resolutions), len(results)),
        "forbidden_candidate_cases": len(forbidden),
        "cross_principal_leakage": len(leaked),
        "missing_required_candidate_cases": len(missing),
        "outcome_mismatch_count": len(mismatched),
        "resolution_recall": recall,
        "withholding_precision": _rate(len(withheld_correctly), len(must_not_resolve)),
        "recall_floor": RECALL_FLOOR,
        "outcomes": _outcome_counts(results),
        "calibration_by_outcome_and_basis": _basis_calibration(results),
        "exact_resolutions_on_a_bare_name": len(exact_resolutions_on_a_bare_name(results)),
        "candidate_limit": _candidate_limit(),
        "disposition": (
            RESOLUTION_SAFE
            if not false_resolutions
            and not forbidden
            and not exact_resolutions_on_a_bare_name(results)
            and recall >= RECALL_FLOOR
            else RESOLUTION_UNSAFE
        ),
    }
    return record


def _candidate_limit() -> int:
    from my_pa.domain.relationship.resolution import RESOLUTION_CANDIDATE_LIMIT

    return RESOLUTION_CANDIDATE_LIMIT


def render_report(record: dict[str, object]) -> str:
    """The frozen report, in the shape `SEMANTIC_GATE.md` established."""
    body = json.dumps(record, indent=2, sort_keys=True)
    return (
        "# Entity resolution calibration\n"
        "\n"
        f"Disposition: `{record['disposition']}`\n"
        "\n"
        "Measured by `tests/evaluation/resolution_harness.py` over the labelled,\n"
        "collision-biased corpus in `tests/evaluation/fixtures/`. Every number below is\n"
        "an observed frequency on that corpus, not a chosen weight — which is what\n"
        'specification section 22.3 means by a numeric that is "calibrated and\n'
        'explained". Re-run the harness to recompute; the JSON below must match it\n'
        "exactly, and `tests/unit/test_entity_resolution_calibration.py` fails if it\n"
        "does not.\n"
        "\n"
        "`calibration_by_outcome_and_basis` is the table a reader consults: a `RESOLVED_*`\n"
        "answer names the basis it rests on, and this says what that combination has\n"
        "been worth against a corpus built to break it. Note that `canonical_name`\n"
        "appears only under `resolved_contextual` — a bare name never resolves on its\n"
        "own, and `exact_resolutions_on_a_bare_name` is the count that must stay zero.\n"
        "\n"
        "**What this does not measure.** The corpus is synthetic and small. It is\n"
        "evidence that the stated refusals hold and that the resolver still answers\n"
        "the questions it should; it is not a population estimate, and no number here\n"
        "should be read as a probability about a real person.\n"
        "\n"
        "```json\n"
        f"{body}\n"
        "```\n"
    )


def load_frozen_record(path: Path = REPORT_PATH) -> dict[str, object]:
    """The record embedded in the frozen report."""
    text = path.read_text(encoding="utf-8")
    match = re.search(r"```json\n(.*?)\n```", text, re.DOTALL)
    if match is None:
        raise ValueError("the frozen calibration report carries no JSON record")
    loaded: dict[str, object] = json.loads(match.group(1))
    return loaded
