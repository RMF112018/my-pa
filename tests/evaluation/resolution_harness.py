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
    UnknownScopeError,
)
from my_pa.domain.relationship.entity import (
    AliasState,
    AliasType,
    Assignment,
    Entity,
    EntityAlias,
    EntityCommunicationMethod,
    EntityCommunicationMethodState,
    EntityName,
    EntityNameState,
    EntityOrganizationProfile,
    EntityProjectParticipation,
    EntityProjectParticipationState,
    EntityRelationship,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    IdentifierState,
    NameTypeCode,
    PersonOrganizationAffiliation,
    PersonOrganizationAffiliationState,
    RelationshipState,
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
    CORPUS_AFFILIATIONS,
    CORPUS_ALIASES,
    CORPUS_ASSIGNMENTS,
    CORPUS_COMMUNICATION_METHODS,
    CORPUS_ENTITIES,
    CORPUS_IDENTIFIERS,
    CORPUS_NAMES,
    CORPUS_PARTICIPATIONS,
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

    def _bounded[Row](self, rows: list[Row], limit: int | None) -> list[Row]:
        """`limit` rows of an already-ordered read, refusing a limit below one.

        The in-memory counterpart of `_require_row_limit`/`_limited` on the SQL
        plane, and it refuses rather than clamps for that method's own reason: a
        caller that asked for zero rows asked a question this port does not
        answer, and quietly handing back one row -- or none -- would let the
        mistake reach a resolution answer as a silently short read.
        """
        if limit is not None and limit < 1:
            raise ValueError("a row limit is at least one")
        return rows if limit is None else rows[:limit]

    _entities: Final = {entity.entity_id: entity for entity in CORPUS_ENTITIES}

    # --- reads -----------------------------------------------------------

    def search(
        self,
        principal_id: str,
        query: str,
        entity_type: EntityType | None = None,
        limit: int = 50,
        *,
        after_entity_id: str | None = None,
    ) -> list[EntitySummary]:
        """The port's search over the corpus, on `SqlEntityRepository.search`' terms.

        **Three pre-existing divergences from the port were closed here
        (`RI-ENT-WP-09`), and saying which is the point.** This method took no
        `after_entity_id` while the port and the other two implementations all
        did, ordered by `entity_id` while the port orders by `(canonical_name,
        entity_id)`, and matched `canonical_name` alone while the port matches
        `display_name` too. A cursor keyword absent from one implementation of
        an `ABC` is a keyword no test of that implementation can exercise, and a
        keyset over an order the port does not use is a page nobody could walk.

        Nothing in `EntityResolutionService` reads this method -- resolution
        asks "who is called this", not "what should I list" -- so no number in
        `RESOLUTION_CALIBRATION.md` moves with it. It is aligned anyway, because
        a double that answers a question differently from the server is a
        licence to assert a search the server does not perform.

        **One divergence remains, and it cannot be closed here.** The server
        matches the relationship type's *label* out of `entity_relationship_types`,
        a taxonomy seeded by migration. The corpus carries no taxonomy rows, so
        this matches the relationship type's *code*.
        """
        needle = query.casefold()

        def hit(value: str | None) -> bool:
            """One substring test, with no metacharacter of its own.

            The server's `ILIKE '%…%'` is escaped by `_contains`, so a `%` or
            `_` in the query is literal there; `in` over a casefolded string is
            literal here for free. `None` answers no, as `NULL ILIKE …` does.
            """
            return value is not None and needle in value.casefold()

        organization_names = {
            organization.entity_id: (organization.canonical_name, organization.display_name)
            for organization in CORPUS_ENTITIES
            if organization.principal_id == principal_id
        }

        def matches_context(entity_id: str) -> bool:
            """The five match paths `RI-ENT-WP-09` added, active rows only."""
            return (
                any(
                    name.entity_id == entity_id
                    and name.principal_id == principal_id
                    and name.state is EntityNameState.ACTIVE
                    # `WP09-DECISION-1`: an alias and a historical name stay out
                    # of a browse result, derived from the enum.
                    and name.name_type_code
                    not in (NameTypeCode.ALIAS, NameTypeCode.HISTORICAL_NAME)
                    and (hit(name.display_value) or hit(name.normalized_value))
                    for name in CORPUS_NAMES
                )
                or any(
                    method.entity_id == entity_id
                    and method.principal_id == principal_id
                    and method.state is EntityCommunicationMethodState.ACTIVE
                    and hit(method.normalized_value)
                    for method in CORPUS_COMMUNICATION_METHODS
                )
                or any(
                    affiliation.person_entity_id == entity_id
                    and affiliation.principal_id == principal_id
                    and affiliation.state is PersonOrganizationAffiliationState.ACTIVE
                    and (
                        hit(affiliation.job_title)
                        or any(
                            hit(value)
                            for value in organization_names.get(
                                affiliation.organization_entity_id or "", ()
                            )
                        )
                    )
                    for affiliation in CORPUS_AFFILIATIONS
                )
                or any(
                    participation.participant_entity_id == entity_id
                    and participation.principal_id == principal_id
                    and participation.state is EntityProjectParticipationState.ACTIVE
                    and (hit(participation.role_text) or hit(participation.project_display_name))
                    for participation in CORPUS_PARTICIPATIONS
                )
                or any(
                    entity_id in (edge.from_entity_id, edge.to_entity_id)
                    and edge.principal_id == principal_id
                    and edge.state is RelationshipState.ACTIVE
                    and hit(edge.relationship_type.value)
                    for edge in CORPUS_RELATIONSHIPS
                )
            )

        matched = [
            entity
            for entity in CORPUS_ENTITIES
            if entity.principal_id == principal_id
            and (entity_type is None or entity.entity_type is entity_type)
            and (
                hit(entity.canonical_name)
                or hit(entity.display_name)
                or matches_context(entity.entity_id)
            )
        ]
        matched.sort(key=lambda item: (item.canonical_name, item.entity_id))
        if after_entity_id is not None:
            position = next(
                (
                    (entity.canonical_name, entity.entity_id)
                    for entity in CORPUS_ENTITIES
                    if entity.principal_id == principal_id and entity.entity_id == after_entity_id
                ),
                None,
            )
            # Refused rather than silently restarted, as the server does: a
            # cursor naming an entity outside the partition is not a position in
            # this Principal's ordering.
            if position is None:
                raise UnknownScopeError("a search cursor names an entity in this scope")
            matched = [
                entity for entity in matched if (entity.canonical_name, entity.entity_id) > position
            ]
        return [
            EntitySummary(
                entity_id=entity.entity_id,
                entity_type=entity.entity_type,
                canonical_name=entity.canonical_name,
                display_name=entity.display_name,
                status=entity.status,
            )
            for entity in matched[:limit]
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

    # --- RI-ENT-WP-09: the two normalized-value reads over record families ----
    #
    # `entities_by_alias`' shape rather than `names`'/`communication_methods`',
    # because the question is theirs -- not "what is this entity called" but
    # "who, if anyone, is called this" -- so they sit beside it here exactly as
    # they do in `SqlEntityRepository`.
    #
    # **These two are implemented over real corpus rows rather than refused, and
    # that is the whole point of the pair.** Every other six-family accessor on
    # this class raises, because resolution reads none of them and a corpus that
    # answered `[]` would let a resolver consult an empty world and be reported
    # as precise. Once resolution *does* read a family, the same argument runs
    # the other way: an empty answer would be indistinguishable from a corpus
    # that carries no claimant of a contested value, and the calibration figures
    # would silently stop measuring the basis they name.

    def entities_by_typed_name(
        self, principal_id: str, normalized_value: str
    ) -> list[tuple[Entity, EntityName]]:
        """Every entity carrying this normalized name form, with the name that matched.

        `SqlEntityRepository.entities_by_typed_name`'s contract, term for term:
        the partition applied to the name row and to the entity before anything
        else, **equality** on the already-normalized value and never a substring
        or a fuzzy match, only `EntityNameState.ACTIVE` rows, and the collection
        read whole so no claimant of a contested name can fall off an end.

        The state filter is derived from the enum rather than spelled as a
        literal, matching the server, and it is what makes
        `enam_halvard0009supers` and `enam_halvard0010retird` unmatchable: a
        superseded row holds a spelling the Principal already corrected away and
        a retired one holds a spelling they withdrew.

        Effective dating is deliberately absent here, as it is on the server and
        on the alias path: `effective_from`/`effective_to` are judged by the
        service against the caller's `as_of`, which is the only layer that knows
        that moment, and a row excluded there is disclosed rather than missing.
        """
        matched: list[tuple[Entity, EntityName]] = []
        for name in CORPUS_NAMES:
            if name.principal_id != principal_id or name.normalized_value != normalized_value:
                continue
            if name.state is not EntityNameState.ACTIVE:
                continue
            entity = self._mine(principal_id, name.entity_id)
            if entity is not None:
                matched.append((entity, name))
        return sorted(matched, key=lambda pair: (pair[0].entity_id, pair[1].entity_name_id))

    def entities_by_communication_value(
        self, principal_id: str, normalized_value: str
    ) -> list[tuple[Entity, EntityCommunicationMethod]]:
        """Every entity carrying this normalized communication value, with the row that matched.

        `entities_by_typed_name`'s scan over `CORPUS_COMMUNICATION_METHODS`, on
        every one of its terms including the `ACTIVE`-only filter, which is what
        keeps `ecmm_halvard0005retird` -- a withdrawn mailbox -- from producing
        a candidate.

        More than one result is not an error: `ecmm_halvard0001phone` and
        `ecmm_halvard0002phone` are one switchboard answered by two juristic
        entities of one corporate family, which is what a corporate family is.
        Deciding what to do about that is the resolution service's, and audit
        section M's answer is candidates and never a merge.
        """
        matched: list[tuple[Entity, EntityCommunicationMethod]] = []
        for method in CORPUS_COMMUNICATION_METHODS:
            if method.principal_id != principal_id or method.normalized_value != normalized_value:
                continue
            if method.state is not EntityCommunicationMethodState.ACTIVE:
                continue
            entity = self._mine(principal_id, method.entity_id)
            if entity is not None:
                matched.append((entity, method))
        return sorted(
            matched, key=lambda pair: (pair[0].entity_id, pair[1].communication_method_id)
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

    # RI-ENT-WP-06b's six Entity-bound families. Four of the eight accessors
    # below still raise, on this class's own established terms and for the
    # reason `observations` gives: resolution reads none of those four, the
    # corpus carries nothing for them, and an empty answer would let a resolver
    # that started consulting one be measured against nothing and reported fine.
    #
    # The two RI-ENT-WP-09 *does* read -- affiliations as the person, and
    # participations as the participant -- answer over real corpus rows instead,
    # because for a family resolution reads the same argument inverts: refusing
    # would break the run, and answering `[]` would make the corroboration
    # signals vacuous. They are read whole and unfiltered by state or date,
    # matching `SqlEntityRepository`: currency is the service's judgement
    # against `at`/`as_of` through `is_in_force`, and a row excluded there sets
    # `withheld` rather than vanishing from the read.

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
    ) -> list[EntityProjectParticipation]:
        """Participations naming `entity_id` as `participant_entity_id`.

        The partition applied first, then the participant column, then
        `SqlEntityRepository`'s own `ORDER BY participation_id`. No state or
        date filter, deliberately: `eppt_leo0003superseded` is open-ended and in
        force by every date rule and only `state` excludes it, so filtering here
        would move the currency judgement out of the layer that knows the
        moment and hide the exclusion from the answer's `withheld` disclosure.
        """
        matched = [
            participation
            for participation in CORPUS_PARTICIPATIONS
            if participation.principal_id == principal_id
            and participation.participant_entity_id == entity_id
        ]
        ordered = sorted(matched, key=lambda row: row.participation_id)
        return self._bounded(ordered, limit)

    def person_organization_affiliations_as_person(
        self, principal_id: str, entity_id: str, *, limit: int | None = None
    ) -> list[PersonOrganizationAffiliation]:
        """Affiliations naming `entity_id` as `person_entity_id`.

        `project_participations_as_participant`'s scan on every term, ordered by
        `affiliation_id` as the server orders it, and unfiltered by state or
        date for the same reason: `poaf_leo0004superseded` is open-ended and
        excluded by nothing but `state`, and `poaf_priya0003ended00` is `ACTIVE`
        and excluded by nothing but its dates. Both exclusions belong to
        `is_in_force`, not to this read.
        """
        matched = [
            affiliation
            for affiliation in CORPUS_AFFILIATIONS
            if affiliation.principal_id == principal_id
            and affiliation.person_entity_id == entity_id
        ]
        ordered = sorted(matched, key=lambda row: row.affiliation_id)
        return self._bounded(ordered, limit)

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

    # RI-ENT-WP-07's assertion surface, which RI-ENT-WP-08 declared on the
    # port: resolution writes none of it, and reads none of it either. The
    # reads refuse rather than answer `[]`/`None` -- unlike a corpus-backed
    # read such as `assignments` -- for the reason the governance block below
    # already gives for `fact_evidence_links` and `observations`: this corpus
    # holds no assertion, so an empty answer would be indistinguishable from
    # a resolver that consulted the assertion plane and correctly found
    # nothing, and the calibration figures would silently stop measuring the
    # basis they name. Refusing makes any such consultation a failure the run
    # cannot miss.

    def record_assertion(self, principal_id: str, assertion: object) -> None:
        raise NotImplementedError("resolution writes no assertion")

    def assertion(self, principal_id: str, assertion_id: str) -> object:
        raise NotImplementedError("resolution reads no assertion")

    def assertions_targeting(self, principal_id: str, **arguments: object) -> list:
        raise NotImplementedError("resolution reads no assertion")

    def supersede_assertion(self, principal_id: str, **arguments: object) -> None:
        raise NotImplementedError("resolution writes no assertion")

    def record_assertion_evidence(self, principal_id: str, evidence: object) -> None:
        raise NotImplementedError("resolution writes no assertion evidence")

    def assertion_evidence(self, principal_id: str, assertion_id: str, **arguments: object) -> list:
        raise NotImplementedError("resolution reads no assertion evidence")

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
