"""Exact resolution: which entity, if any, a reference names.

The whole of this module is one decision made repeatedly — **when is the
evidence enough to say "this is them"?** — and the answer it gives is
deliberately narrow. Specification section 15.2:

> Exact identifiers are strong evidence but remain source- and time-aware.
> Names alone are insufficient for automatic merge.
> Conflicting immutable identifiers prevent automatic merge.
> Ambiguous mentions remain unresolved rather than forced into the nearest
> person.

Those four lines are the algorithm. Everything below is them, applied in order,
with the reason each step refuses recorded next to the refusal.

**The order is by kind of evidence, not by how many rows matched.** A verified
external identifier resolves; an unverified one resolves with a warning; an
alias resolves; a canonical name never resolves on its own, however unique it
is. Uniqueness is not evidence: a person can be the only Smith in a small
database and still not be the Smith who was meant, and the database's being
small is not a fact about them.

**What this module does not do.** It does not merge, propose, or write anything
— `RI-AC-039` reserves identity merges from autonomous action and section 21.4
forbids a model creating a canonical person. It reads, and it returns an answer
whose type cannot be read as a resolution when it is not one. Contextual
ranking, calibration, and the false-resolution evaluation are WP-RI-04.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from my_pa.contracts.ports import EntitiesRepository
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.entity import (
    Entity,
    EntityAlias,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
)
from my_pa.domain.relationship.normalization import (
    NormalizationError,
    normalize_identifier,
    normalize_name,
)
from my_pa.domain.relationship.resolution import (
    RESOLUTION_CANDIDATE_LIMIT,
    ContextualSignal,
    EntityResolution,
    ResolutionBasis,
    ResolutionCandidate,
    ResolutionEvidence,
    ResolutionOutcome,
    ResolutionWarning,
    order_candidates,
)

__all__ = ["EntityResolutionService", "ResolutionRequest"]


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    """One question about who a reference names.

    `namespace` is stated rather than sniffed. A reference containing an `@` is
    *probably* an email, but resolving on a guess means a person whose recorded
    display name happens to contain one is matched as a mailbox — so a caller
    that knows says so, and a caller that does not gets name resolution, which
    is the outcome that cannot false-join on its own.
    """

    raw_reference: str
    namespace: ExternalIdentifierNamespace | None = None
    entity_type: EntityType | None = None
    scope_entity_id: str | None = None
    as_of: datetime | None = None

    def __post_init__(self) -> None:
        if not self.raw_reference.strip():
            raise ValueError("a resolution request names something to resolve")
        if self.namespace is not None and not isinstance(
            self.namespace, ExternalIdentifierNamespace
        ):
            raise ValueError("a resolution request names a closed namespace")
        if self.entity_type is not None and not isinstance(self.entity_type, EntityType):
            raise ValueError("a resolution request names a closed entity type")
        if self.scope_entity_id is not None:
            validate_identifier(self.scope_entity_id, IdKind.ENTITY)
        if self.as_of is not None:
            ensure_utc(self.as_of)


def _is_effective(
    effective_from: datetime | None, effective_to: datetime | None, as_of: datetime | None
) -> bool:
    """Whether a time-bounded record applies at `as_of`.

    `as_of` of `None` means "do not filter by time" rather than "now": a caller
    that did not ask a temporal question should not silently get one answered,
    and `RI-AC-014` is about not presenting stale evidence *as current*, which
    is a disclosure duty rather than a reason to hide it.

    An open bound is open in that direction. Both open is the ordinary case for
    a record nobody has dated.
    """
    if as_of is None:
        return True
    if effective_from is not None and as_of < effective_from:
        return False
    return not (effective_to is not None and as_of > effective_to)


class EntityResolutionService:
    """Resolves a reference against one Principal's entities.

    Takes the repository rather than a unit of work, because resolving reads and
    writes nothing: a service that held a transaction would be claiming an
    authority it does not use.
    """

    def __init__(self, entities: EntitiesRepository) -> None:
        self._entities = entities

    def resolve(self, principal_id: str, request: ResolutionRequest) -> EntityResolution:
        """The one entry point. Never raises for "not found"; that is an answer."""
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        warnings: list[ResolutionWarning] = []

        if request.namespace is not None:
            resolved = self._by_identifier(principal_id, request, warnings)
            if resolved is not None:
                return resolved

        return self._by_name(principal_id, request, warnings)

    # --- identifier resolution ------------------------------------------

    def _by_identifier(
        self,
        principal_id: str,
        request: ResolutionRequest,
        warnings: list[ResolutionWarning],
    ) -> EntityResolution | None:
        """Resolve through an external identifier, or return `None` to fall through.

        Falling through rather than answering `NOT_FOUND` is deliberate: an
        identifier that matches nothing has not ruled out the reference also
        being a name, and answering "no such person" while a name match was
        available would be the least informative honest answer available.
        """
        assert request.namespace is not None  # noqa: S101 — narrowed by the caller
        try:
            normalized = normalize_identifier(request.namespace, request.raw_reference)
        except NormalizationError:
            return None

        matched = self._entities.entities_by_identifier(principal_id, request.namespace, normalized)
        matched = [
            (entity, identifier) for entity, identifier in matched if self._admits(entity, request)
        ]
        if not matched:
            return None

        effective = [
            (entity, identifier)
            for entity, identifier in matched
            if _is_effective(identifier.effective_from, identifier.effective_to, request.as_of)
        ]
        if len(effective) < len(matched):
            warnings.append(ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT)
        if not effective:
            return None

        candidates = tuple(
            _candidate_from_identifier(entity, identifier) for entity, identifier in effective
        )

        # Section 15.2: conflicting identifiers prevent an automatic join. More
        # than one entity holding one identity is exactly that conflict, and it
        # is a stop rather than a tiebreak — picking either would be performing
        # the merge the rule refuses.
        if len({entity.entity_id for entity, _ in effective}) > 1:
            warnings.append(ResolutionWarning.IDENTIFIER_CLAIMED_BY_SEVERAL_ENTITIES)
            return EntityResolution(
                outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
                candidates=order_candidates(candidates),
                warnings=tuple(dict.fromkeys(warnings)),
            )

        entity, identifier = effective[0]
        if not identifier.verified:
            warnings.append(ResolutionWarning.MATCHED_IDENTIFIER_IS_UNVERIFIED)
        warnings.extend(_currency_warnings(entity))
        outcome = (
            ResolutionOutcome.RESOLVED_EXACT
            if entity.status is EntityStatus.ACTIVE
            else ResolutionOutcome.HISTORICAL_MATCH
        )
        return EntityResolution(
            outcome=outcome,
            candidates=(candidates[0],),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    # --- name resolution -------------------------------------------------

    def _by_name(
        self,
        principal_id: str,
        request: ResolutionRequest,
        warnings: list[ResolutionWarning],
    ) -> EntityResolution:
        try:
            normalized = normalize_name(request.raw_reference)
        except NormalizationError:
            return EntityResolution(outcome=ResolutionOutcome.NOT_FOUND, warnings=tuple(warnings))

        by_entity: dict[str, tuple[Entity, list[ResolutionEvidence]]] = {}

        for entity, alias in self._entities.entities_by_alias(principal_id, normalized):
            if not self._admits(entity, request):
                continue
            if not _is_effective(alias.effective_from, alias.effective_to, request.as_of):
                warnings.append(ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT)
                continue
            _collect(by_entity, entity, _alias_evidence(alias))

        for entity in self._entities.entities_by_canonical_name(principal_id, normalized):
            if not self._admits(entity, request):
                continue
            _collect(by_entity, entity, _name_evidence(entity))

        if not by_entity:
            return EntityResolution(
                outcome=ResolutionOutcome.NOT_FOUND, warnings=tuple(dict.fromkeys(warnings))
            )

        if len(by_entity) > 1:
            warnings.append(ResolutionWarning.SEVERAL_ENTITIES_SHARE_THIS_NAME)

        signals = {
            entity_id: self._signals_for(principal_id, entity_id, request)
            for entity_id in by_entity
        }
        narrowed = _narrow_by_signals(by_entity, signals)
        was_narrowed = narrowed is not by_entity
        if was_narrowed:
            warnings.append(ResolutionWarning.NARROWED_BY_SUPPLIED_SCOPE)
        elif any(signals.values()) and len(by_entity) > 1:
            # Something corroborated, and it corroborated everyone. Said out
            # loud: "we noticed and it did not help" is a different disclosure
            # from silence, and only one of them lets a reader tell whether the
            # context was consulted at all.
            warnings.append(ResolutionWarning.CONTEXT_DID_NOT_DISTINGUISH_THE_CANDIDATES)

        candidates = order_candidates(
            tuple(
                ResolutionCandidate(
                    entity_id=entity.entity_id,
                    entity_type=entity.entity_type,
                    display_name=entity.display_name,
                    status=entity.status,
                    evidence=tuple(evidence),
                    superseded_by_entity_id=entity.superseded_by_entity_id,
                    signals=signals[entity.entity_id],
                )
                for entity, evidence in narrowed.values()
            )
        )
        if not candidates:
            return EntityResolution(
                outcome=ResolutionOutcome.NOT_FOUND, warnings=tuple(dict.fromkeys(warnings))
            )

        bounded = candidates[:RESOLUTION_CANDIDATE_LIMIT]
        truncated = len(bounded) < len(candidates)
        if truncated:
            warnings.append(ResolutionWarning.MORE_CANDIDATES_THAN_THIS_ANSWER_CARRIES)

        return self._name_outcome(bounded, was_narrowed, truncated, warnings)

    def _name_outcome(
        self,
        candidates: tuple[ResolutionCandidate, ...],
        was_narrowed: bool,
        truncated: bool,
        warnings: list[ResolutionWarning],
    ) -> EntityResolution:
        """The decision. One candidate is not by itself a resolution.

        `AMBIGUOUS` covers the lone weak match as well as the crowd, for the
        reason `ResolutionOutcome.AMBIGUOUS` states: there is no count at which
        a name becomes an identifier.
        """

        def unresolved(outcome: ResolutionOutcome) -> EntityResolution:
            return EntityResolution(
                outcome=outcome,
                candidates=candidates,
                warnings=tuple(dict.fromkeys(warnings)),
                candidates_were_truncated=truncated,
            )

        if len(candidates) > 1 or truncated:
            # Truncated means candidates were dropped, and a resolution drawn
            # from a list that dropped someone is a resolution that never saw
            # the person it might have been.
            return unresolved(ResolutionOutcome.AMBIGUOUS)

        only = candidates[0]
        resolves = only.strongest_basis is ResolutionBasis.ALIAS or was_narrowed
        if not resolves:
            return unresolved(ResolutionOutcome.AMBIGUOUS)

        warnings.extend(_currency_warnings(only.status))
        if only.status is not EntityStatus.ACTIVE:
            if only.strongest_basis is ResolutionBasis.CANONICAL_NAME:
                return unresolved(ResolutionOutcome.AMBIGUOUS)
            return unresolved(ResolutionOutcome.HISTORICAL_MATCH)

        outcome = (
            ResolutionOutcome.RESOLVED_CONTEXTUAL
            if was_narrowed
            else ResolutionOutcome.RESOLVED_EXACT
        )
        return EntityResolution(
            outcome=outcome,
            candidates=candidates,
            warnings=tuple(dict.fromkeys(warnings)),
        )

    # --- filters ---------------------------------------------------------

    def _admits(self, entity: Entity, request: ResolutionRequest) -> bool:
        """Whether the request's structural filters admit this entity.

        Entity type is an exact structural filter rather than a hint: a caller
        that asked for a project does not want a person who shares its name, and
        returning one as a candidate would be offering evidence of the wrong
        kind.
        """
        return request.entity_type is None or entity.entity_type is request.entity_type

    def _signals_for(
        self, principal_id: str, entity_id: str, request: ResolutionRequest
    ) -> tuple[ContextualSignal, ...]:
        """Everything the surrounding context corroborates about one candidate.

        Computed for every candidate, including when it cannot change the
        answer, because a signal is evidence a reader is entitled to see even
        when it did not decide anything -- and because computing it only for the
        winner would mean the signals on an `AMBIGUOUS` answer were absent
        rather than false.
        """
        found: list[ContextualSignal] = []
        if request.scope_entity_id is not None:
            if self._assigned_to(principal_id, entity_id, request.scope_entity_id, request.as_of):
                found.append(ContextualSignal.ASSIGNED_TO_THE_NAMED_SCOPE)
            if self._related_to(principal_id, entity_id, request.scope_entity_id, request.as_of):
                found.append(ContextualSignal.RELATED_TO_THE_NAMED_SCOPE)
        return tuple(found)

    def _assigned_to(
        self, principal_id: str, entity_id: str, scope_entity_id: str, as_of: datetime | None
    ) -> bool:
        return any(
            assignment.scope_entity_id == scope_entity_id
            and _is_effective(assignment.effective_from, assignment.effective_to, as_of)
            for assignment in self._entities.assignments(principal_id, entity_id, active_only=True)
        )

    def _related_to(
        self, principal_id: str, entity_id: str, scope_entity_id: str, as_of: datetime | None
    ) -> bool:
        return any(
            scope_entity_id in (relationship.to_entity_id, relationship.scope_entity_id)
            and _is_effective(relationship.effective_from, relationship.effective_to, as_of)
            for relationship in self._entities.relationships(
                principal_id, entity_id, direction="outgoing"
            )
        )


def _narrow_by_signals(
    by_entity: dict[str, tuple[Entity, list[ResolutionEvidence]]],
    signals: dict[str, tuple[ContextualSignal, ...]],
) -> dict[str, tuple[Entity, list[ResolutionEvidence]]]:
    """Keep only the candidates the surrounding context said something about.

    Returns the *same object* when nothing was narrowed -- no signal, no
    candidate carrying one, or every candidate carrying one -- so the caller can
    tell by identity whether the context did any work. A signal true of everyone
    has distinguished nobody, and reporting `RESOLVED_CONTEXTUAL` for it would
    credit the caller's hint with a decision the evidence never made.

    Narrowing to nothing is also no narrowing. A scope that excluded every
    candidate is more likely to be a scope the caller got wrong than proof that
    none of these people is the one they meant.
    """
    if len(by_entity) < 2:
        return by_entity
    kept = {entity_id: pair for entity_id, pair in by_entity.items() if signals.get(entity_id)}
    if not kept or len(kept) == len(by_entity):
        return by_entity
    return kept


# --- evidence construction --------------------------------------------------


def _collect(
    by_entity: dict[str, tuple[Entity, list[ResolutionEvidence]]],
    entity: Entity,
    evidence: ResolutionEvidence,
) -> None:
    """Add one piece of evidence to an entity's candidacy, keeping all of it.

    All of it rather than the strongest: section 6.2 requires a material
    statement to retain its source references, and "matched on two aliases and
    the canonical name" is a different fact from "matched on an alias".
    """
    held = by_entity.get(entity.entity_id)
    if held is None:
        by_entity[entity.entity_id] = (entity, [evidence])
    else:
        held[1].append(evidence)


def _alias_evidence(alias: EntityAlias) -> ResolutionEvidence:
    return ResolutionEvidence(
        basis=ResolutionBasis.ALIAS,
        matched_value=alias.normalized_value,
        source_record_id=alias.alias_id,
    )


def _name_evidence(entity: Entity) -> ResolutionEvidence:
    return ResolutionEvidence(
        basis=ResolutionBasis.CANONICAL_NAME,
        matched_value=entity.canonical_name,
        source_record_id=entity.entity_id,
    )


def _candidate_from_identifier(
    entity: Entity, identifier: ExternalIdentifier
) -> ResolutionCandidate:
    basis = (
        ResolutionBasis.VERIFIED_EXTERNAL_IDENTIFIER
        if identifier.verified
        else ResolutionBasis.EXTERNAL_IDENTIFIER
    )
    return ResolutionCandidate(
        entity_id=entity.entity_id,
        entity_type=entity.entity_type,
        display_name=entity.display_name,
        status=entity.status,
        evidence=(
            ResolutionEvidence(
                basis=basis,
                matched_value=identifier.normalized_value,
                verified=identifier.verified,
                source_record_id=identifier.identifier_id,
            ),
        ),
        superseded_by_entity_id=entity.superseded_by_entity_id,
    )


def _currency_warnings(subject: Entity | EntityStatus) -> list[ResolutionWarning]:
    """What a caller must be told about an entity that is not current."""
    status = subject if isinstance(subject, EntityStatus) else subject.status
    if status is EntityStatus.ACTIVE:
        return []
    if status is EntityStatus.MERGED_REDIRECT:
        return [
            ResolutionWarning.ENTITY_HAS_BEEN_MERGED_AWAY,
            ResolutionWarning.ENTITY_IS_NOT_CURRENT,
        ]
    return [ResolutionWarning.ENTITY_IS_NOT_CURRENT]
