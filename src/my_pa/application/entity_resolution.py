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
whose type cannot be read as a resolution when it is not one.

Contextual ranking *is* here, and this paragraph said it was not until the ninth
review read it against the code. The sentence was written for WP-RI-03, when
ranking was still ahead; WP-RI-04 then put `_signals_for`, `_assigned_to`,
`_related_to`, `_narrow_by_signals`, `ContextualSignal` and the
`RESOLVED_CONTEXTUAL` outcome into this module and did not revise the paragraph
that promised otherwise. What remains elsewhere is the calibration corpus and
the false-resolution evaluation, in `tests/evaluation/`.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime

from my_pa.contracts.ports import EntitiesRepository
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.entity import (
    AssignmentState,
    Entity,
    EntityAlias,
    EntityCommunicationMethod,
    EntityName,
    EntityProjectParticipationState,
    EntityStatus,
    EntityType,
    ExternalIdentifier,
    ExternalIdentifierNamespace,
    PersonOrganizationAffiliationState,
    RelationshipState,
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

__all__ = [
    "ACTIVE_ASSIGNMENT_STATUS",
    "ACTIVE_RELATIONSHIP_STATE",
    "EntityResolutionService",
    "ResolutionRequest",
    "is_in_force",
]


@dataclass(frozen=True, slots=True)
class ResolutionRequest:
    """One question about who a reference names.

    `namespace` is stated rather than sniffed. A reference containing an `@` is
    *probably* an email, but resolving on a guess means a person whose recorded
    display name happens to contain one is matched as a mailbox — so a caller
    that knows says so, and a caller that does not gets name resolution, which
    is the outcome that cannot false-join on its own.

    `at` is the moment the question is being asked and `as_of` is the moment it
    is being asked *about*. They are separate because the plane treats them
    differently: matched evidence is deliberately not date-filtered without an
    `as_of` (an alias somebody stopped using is still a name they were called),
    while a *corroborating* record has to be current to corroborate. Signals are
    therefore judged at `as_of` when one is given and at `at` otherwise.

    Before `at` existed, "current" was inferred from `effective_to is None` --
    "nobody wrote down an end date" -- which is neither necessary nor
    sufficient. A contract running to 2030 read as over, and a role beginning in
    2030 read as in force today, so an ordinary dated employment corroborated
    nothing and an unstarted one corroborated a bare name. The residual recorded
    against this ("detecting it needs a clock this module does not have") was
    wrong on its own terms: the only caller holds `authorization.at` and was
    passing it nowhere.
    """

    raw_reference: str
    namespace: ExternalIdentifierNamespace | None = None
    entity_type: EntityType | None = None
    scope_entity_id: str | None = None
    as_of: datetime | None = None
    at: datetime | None = None
    #: Entities the user has already decided this reference does *not* name.
    #:
    #: Empty by default and never inferred: this is persisted negative identity
    #: evidence, read out of `entity_fact_evidence_links` by the caller that
    #: holds the observation, and a request that supplied it from anywhere else
    #: would be a guess wearing a decision's clothes. What it does to the answer
    #: is deliberately narrow -- see `_without_refused` -- because a refusal is
    #: evidence against one pairing and evidence for nothing.
    refused_entity_ids: frozenset[str] = frozenset()

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
        if self.at is not None:
            ensure_utc(self.at)
        for entity_id in self.refused_entity_ids:
            validate_identifier(entity_id, IdKind.ENTITY)


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


def is_in_force(
    effective_from: datetime | None, effective_to: datetime | None, moment: datetime | None
) -> bool:
    """Whether a *corroborating* record is in force. Stricter than `_is_effective`.

    The two differ only at `as_of=None`, and the difference is the whole reason
    this function exists. `_is_effective` declines to filter without a moment,
    which is right for the evidence the reference itself matched: the caller
    asked "who is this", not "who was this", and an alias somebody stopped using
    is still a name they were called.

    A signal is the other kind of claim. It does not say what the reference
    matched; it says the candidate **is** on the project the caller named, and
    that is the whole of why a bare name is allowed to resolve at all
    (`_name_outcome`). A record whose author wrote down the day it ended does not
    say that. So an ended record corroborates only when the caller named a moment
    it covers, and a record nobody has closed corroborates always.

    Without this, a contractor who left in 2024 still corroborated in 2026 on
    every request that did not happen to ask a temporal question -- which is the
    default request -- and a bare canonical name resolved to her with no warning
    at all.

    **It is an ordinary point-in-time test, and that took two goes.** The first
    version inferred "current" from `effective_to is None` when no moment was
    named -- "nobody wrote down an end date" -- which is neither necessary nor
    sufficient for being in force. A contract running to 2030 was read as over,
    so an ordinary dated employment corroborated nothing; a role beginning in
    2030 was read as in force, so an unstarted assignment lifted a bare name to a
    confident answer. Both were reproduced. The residual recorded against the
    second failure claimed detecting it "needs a clock this module does not
    have"; the clock was `authorization.at`, which the only caller already held
    and passed nowhere. `ResolutionRequest.at` carries it now, and `moment` below
    is `as_of` when the caller asked about one and `at` otherwise.

    A request carrying neither falls back to the old open-ended rule, which is
    the most this function can say with no moment at all. **That fallback fails
    in the resolving direction, not the refusing one**, which inverts this
    module's stated preference, so where it is reachable matters.

    `entities.resolve` always supplies `at`. The other production construction
    is `EntityReenrichmentService.after_alias`, which supplies neither -- and is
    safe only because it supplies no `scope_entity_id` either, so no signal is
    consulted and this function is never called on its path. That is a load
    bearing condition rather than an incidental one, and
    `tests/unit/test_entity_reenrichment.py` pins it: adding a scope to that
    request without adding a moment would hand a background pass with nobody
    watching the one behaviour this rule exists to prevent.
    """
    if moment is not None:
        return _is_effective(effective_from, effective_to, moment)
    return effective_to is None


#: The one `Assignment.state` that means the assignment still stands, matching
#: the value `SqlEntityRepository.assignments` filters on for `active_only`.
#:
#: Derived from the vocabulary rather than spelled, now that there is one to
#: derive from. Until WP-RI-A-01 closed `state`, this constant was the *only*
#: statement anywhere that `'active'` was the live value while the column
#: admitted any text, so a row written around the repository with `'Active'`
#: was silently excluded from every corroborating read. The column refuses that
#: row now, and this stays because two readers still have to agree on which
#: member means live.
ACTIVE_ASSIGNMENT_STATUS: str = AssignmentState.ACTIVE.value

#: The one `EntityRelationship.state` that means the edge still stands, on the
#: same argument and with the same history: an unrecognised state reads as *not*
#: live, which is the direction a corroborating signal should fail in, and the
#: column is now closed so an unrecognised one cannot be stored at all.
ACTIVE_RELATIONSHIP_STATE: str = RelationshipState.ACTIVE.value


@dataclass(frozen=True, slots=True)
class _Reach:
    """Whether any record reached the scope, and whether a stale one was passed over."""

    found: bool = False
    withheld: bool = False


def _reach(
    records: Iterable[tuple[datetime | None, datetime | None, bool]], moment: datetime | None
) -> _Reach:
    """Fold every record that reaches the scope into "any live" and "any stale".

    Reports the two facts separately, because a record that reaches the scope and
    is over is not the same as no record at all: the first is something the
    caller is owed a warning about (`RI-AC-014`), and the second is silence.

    **Each record carries its own liveness rather than having it encoded into its
    dates.** A row can be stale two ways -- its status or state says so, or its
    window says so -- and the third element is the first of those, asked of the
    record by the caller that knows which column holds it.

    The first attempt instead mapped a status-excluded row onto a sentinel window
    (`effective_to = datetime.min`) meaning "over however you date it". It was
    not: `_is_effective` closes its end bound with `moment > effective_to`, which
    is false when `moment` is itself `datetime.min` -- so a caller passing
    `as_of="0001-01-01T00:00:00Z"`, which the transport accepts, made a
    *cancelled* assignment read as in force, corroborate a bare canonical name,
    narrow away the rival, and name an entity with no staleness warning. An
    encoding that has to be impossible is a claim; a flag is a fact.
    """
    found = False
    withheld = False
    for effective_from, effective_to, recorded_live in records:
        if recorded_live and is_in_force(effective_from, effective_to, moment):
            found = True
        else:
            withheld = True
    return _Reach(found=found, withheld=withheld)


@dataclass(frozen=True, slots=True)
class _ScopeSignals:
    """What the named scope said about one candidate, and what it declined to say.

    `withheld` is carried separately rather than folded into an empty `found`,
    because "nothing connects them" and "what connected them is over" are
    different facts and only the second one is a disclosure the caller is owed.
    """

    found: tuple[ContextualSignal, ...] = ()
    withheld: bool = False


class EntityResolutionService:
    """Resolves a reference against one Principal's entities.

    Takes the repository rather than a unit of work, because resolving reads and
    writes nothing: a service that held a transaction would be claiming an
    authority it does not use.
    """

    def __init__(self, entities: EntitiesRepository) -> None:
        self._entities = entities

    def resolve(self, principal_id: str, request: ResolutionRequest) -> EntityResolution:
        """The one entry point. Never raises for "not found"; that is an answer.

        **The refusal filter is applied to the finished answer and to nothing
        else.** The decision below it -- `_by_identifier`, `_by_name` and
        `_name_outcome` -- is untouched by what the user has previously
        refused, because folding a refusal into it would make a rejection into
        a *positive* signal: exclude one of two same-named candidates before the
        count is taken, and the survivor is suddenly a lone match that the
        contextual rule can lift out of `AMBIGUOUS`. The user said who somebody
        is not; that is not evidence of who they are.

        So the answer is computed exactly as it would have been, and then the
        refused pairings are removed from what it carries. See
        `_without_refused` for what that can and cannot change.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        warnings: list[ResolutionWarning] = []

        if request.namespace is not None:
            resolved = self._by_identifier(principal_id, request, warnings)
            if resolved is not None:
                return _without_refused(resolved, request.refused_entity_ids)

        return _without_refused(
            self._by_name(principal_id, request, warnings), request.refused_entity_ids
        )

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

        held = self._entities.entities_by_identifier(principal_id, request.namespace, normalized)
        if not held:
            # The reference is not an identifier in this namespace at all, which
            # is the one case this method is allowed to enrich: no row matched,
            # so nothing here is being discarded. A recorded *contact channel*
            # carrying the same value is a weaker fact than an identity binding
            # and is read only here, where the stronger one had nothing to say.
            return self._by_communication_value(principal_id, request, normalized, warnings)

        # Effective dating first, and *before* any caller filter: an identifier
        # that was not in force at the moment asked about is not evidence of
        # anything, so it neither resolves nor conflicts.
        effective = [
            (entity, identifier)
            for entity, identifier in held
            if _is_effective(identifier.effective_from, identifier.effective_to, request.as_of)
        ]
        if len(effective) < len(held):
            warnings.append(ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT)
        if not effective:
            # **The identifier matched, and every row it matched is out of
            # date.** That is an answer, not a miss, and it must not fall
            # through to `_by_name` -- which re-reads the identifier string as a
            # *name*, so an expired `source_participant_id` of "Smith, John"
            # resolved `RESOLVED_EXACT` to a *different* entity holding the
            # alias "Smith John". `RI-I-003` puts stable external identifiers
            # above lexical matching; discarding the identifier evidence to try
            # the weaker one inverts that.
            #
            # This is the same defect as the `entity_type` case below, on the
            # branch above it. The rule the two share, stated once so a third
            # branch cannot be added without meeting it: **this method falls
            # through to name matching only when the reference is not an
            # identifier in this namespace at all, or matches no row.** Once a
            # row matched, every exit here is an answer.
            return EntityResolution(
                outcome=ResolutionOutcome.NOT_FOUND,
                warnings=tuple(dict.fromkeys(warnings)),
            )

        # Section 15.2: conflicting identifiers prevent an automatic join. More
        # than one entity holding one identity is exactly that conflict, and it
        # is a stop rather than a tiebreak — picking either would be performing
        # the merge the rule refuses.
        #
        # **Decided before the caller's `entity_type` filter, and that ordering
        # is the whole point.** A conflict is a property of the recorded data,
        # not of the question asked about it. Filtering first meant a shared
        # mailbox recorded against a person and an organization resolved
        # *exactly* — to the person for one caller and to the organization for
        # the next — with no warning at all, because each filtered view saw one
        # claimant. The filter narrows what is *offered*; it cannot un-conflict
        # the identifier.
        if len({entity.entity_id for entity, _ in effective}) > 1:
            warnings.append(ResolutionWarning.IDENTIFIER_CLAIMED_BY_SEVERAL_ENTITIES)
            # Bounded on the same terms the name path is bounded, and for a
            # sharper reason. `EntityResolution` refuses more candidates than
            # `RESOLUTION_CANDIDATE_LIMIT`, so an identifier held by eleven
            # entities -- a shared mailbox, a distribution list, a room resource
            # recorded against every team that books it -- raised `ValueError`
            # here and reached the caller as `internal_error`. The safety
            # outcome failed exactly when the data was most conflicted, which is
            # the one moment it exists for. Truncating discloses less than the
            # full list and refuses just as hard: `CONFLICTED_IDENTIFIER`
            # resolves nothing either way, so a caller cannot act on a claimant
            # that is missing from the page.
            conflicted = order_candidates(
                tuple(
                    _candidate_from_identifier(entity, identifier)
                    for entity, identifier in effective
                )
            )
            bounded = conflicted[:RESOLUTION_CANDIDATE_LIMIT]
            truncated = len(bounded) < len(conflicted)
            if truncated:
                warnings.append(ResolutionWarning.MORE_CANDIDATES_THAN_THIS_ANSWER_CARRIES)
            return EntityResolution(
                outcome=ResolutionOutcome.CONFLICTED_IDENTIFIER,
                candidates=bounded,
                candidates_were_truncated=truncated,
                warnings=tuple(dict.fromkeys(warnings)),
            )

        admitted = [
            (entity, identifier)
            for entity, identifier in effective
            if self._admits(entity, request)
        ]
        if not admitted:
            # The identifier named somebody, and the caller asked for a
            # different kind of thing. That is an answer -- "no project holds
            # this address" -- and it is *not* the fall-through case above.
            # Falling through here re-read the address as a **name**: an email
            # lookup constrained to a project answered `RESOLVED_EXACT` naming a
            # project whose alias happened to be spelled the way
            # `normalize_name` spells that address, discarding identifier
            # evidence that pointed at a person to do it.
            return EntityResolution(
                outcome=ResolutionOutcome.NOT_FOUND,
                warnings=tuple(dict.fromkeys(warnings)),
            )
        candidates = tuple(
            _candidate_from_identifier(entity, identifier) for entity, identifier in admitted
        )

        entity, identifier = admitted[0]
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

    def _by_communication_value(
        self,
        principal_id: str,
        request: ResolutionRequest,
        normalized: str,
        warnings: list[ResolutionWarning],
    ) -> EntityResolution | None:
        """Who, if anyone, records this value as a way to reach them.

        Reached only from `_by_identifier`'s no-row-matched fall-through, and
        that placement is the whole of its safety. `EntityCommunicationMethod`'s
        own docstring says `entity_external_identifiers` "remains the sole
        authority for identity resolution"; a contact channel answers a
        different question -- "is this a way to reach this entity" rather than
        "which entity does this identify" -- so it is consulted only where the
        identity plane held no claim on the value at all, and it never
        overrides, weakens or duplicates one that did.

        **It never resolves, however few claimants there are.** A recorded
        address is not a verified identifier: a shared mailbox, a switchboard
        number and a company domain are each reachable by many people, and
        section 15.2's "ambiguous mentions remain unresolved rather than forced
        into the nearest person" is exactly the rule for a value whose owner is
        not established. So a match here is `AMBIGUOUS` with its claimants shown
        -- retrieval candidates, which is audit section M's ceiling for evidence
        that does not name an entity -- and `COMMUNICATION_VALUE`'s absence from
        `_BASES_THAT_NAME_AN_ENTITY` is the structural half of the same refusal.

        `None` means no row matched this value either, which returns the method
        to its fall-through: the reference may still be a name, and answering
        "no such person" while a name match was available is the least
        informative honest answer there is.
        """
        held = self._entities.entities_by_communication_value(principal_id, normalized)
        if not held:
            return None

        # Effective dating on `_by_identifier`'s own terms: a channel that was
        # not in force at the moment asked about is not evidence of anything,
        # and the exclusion is disclosed rather than silent (`RI-AC-014`).
        effective = [
            (entity, method)
            for entity, method in held
            if _is_effective(method.effective_from, method.effective_to, request.as_of)
        ]
        if len(effective) < len(held):
            warnings.append(ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT)

        admitted = [
            (entity, method) for entity, method in effective if self._admits(entity, request)
        ]
        if not admitted:
            # A row matched and nothing survived -- every claimant is out of
            # date, or the caller asked for a different kind of thing. That is
            # an answer for the reason the identical branch above it is one:
            # falling through re-reads the address as a **name**, which would
            # discard channel evidence pointing at a person in order to match a
            # project whose alias is spelled the way `normalize_name` spells
            # that address.
            return EntityResolution(
                outcome=ResolutionOutcome.NOT_FOUND,
                warnings=tuple(dict.fromkeys(warnings)),
            )

        by_entity: dict[str, tuple[Entity, list[ResolutionEvidence]]] = {}
        for entity, method in admitted:
            _collect(by_entity, entity, _communication_value_evidence(method))
        candidates = order_candidates(
            tuple(
                ResolutionCandidate(
                    entity_id=entity.entity_id,
                    entity_type=entity.entity_type,
                    display_name=entity.display_name,
                    status=entity.status,
                    evidence=tuple(evidence),
                    superseded_by_entity_id=entity.superseded_by_entity_id,
                )
                for entity, evidence in by_entity.values()
            )
        )
        # Bounded on `CONFLICTED_IDENTIFIER`'s terms and for its reason:
        # `EntityResolution` raises on an over-long candidate list, so an
        # unbounded one would turn the safety answer into `internal_error`
        # precisely when a value is most contested. A shared mailbox or a
        # company domain recorded against every team that uses it is exactly
        # how a claimant list gets past the bound.
        bounded = candidates[:RESOLUTION_CANDIDATE_LIMIT]
        truncated = len(bounded) < len(candidates)
        if truncated:
            warnings.append(ResolutionWarning.MORE_CANDIDATES_THAN_THIS_ANSWER_CARRIES)
        return EntityResolution(
            outcome=ResolutionOutcome.AMBIGUOUS,
            candidates=bounded,
            candidates_were_truncated=truncated,
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

        # The same read asked of `entity_names`, and dated on exactly the alias
        # read's terms because it is the same kind of claim: a recorded name
        # form of the entity, typed rather than untyped. It is *not* the same
        # kind of evidence as an alias for the purpose of resolving --
        # `TYPED_NAME` is absent from `_BASES_THAT_NAME_AN_ENTITY`, so a
        # candidate whose only evidence is one is refused by `_name_outcome`
        # however unique the name is. An entity matching both keeps both pieces
        # of evidence, which is `_collect`'s rule and section 6.2's.
        for entity, name in self._entities.entities_by_typed_name(principal_id, normalized):
            if not self._admits(entity, request):
                continue
            if not _is_effective(name.effective_from, name.effective_to, request.as_of):
                warnings.append(ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT)
                continue
            _collect(by_entity, entity, _typed_name_evidence(name))

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

        scoped = {
            entity_id: self._signals_for(principal_id, entity_id, request)
            for entity_id in by_entity
        }
        signals = {entity_id: found.found for entity_id, found in scoped.items()}
        narrowed = _narrow_by_signals(by_entity, signals)
        if any(scoped[entity_id].withheld for entity_id in narrowed):
            # Something did connect a candidate to the named scope, and it is
            # over. Said out loud on the same terms `_by_identifier` says it: a
            # caller who is not told cannot tell this answer apart from one where
            # the context simply had nothing to say.
            #
            # **Asked of the candidates that survive narrowing, not of everyone
            # considered.** Computed over the whole set, the warning described a
            # candidate the scope then removed: two people share a name, the
            # winner's assignment is live and the rival's is cancelled, and the
            # answer named the winner while telling the reader their evidence
            # was stale. It was not, and the record that was is not on the
            # answer to look at.
            warnings.append(ResolutionWarning.EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT)
        was_narrowed = narrowed is not by_entity
        if was_narrowed:
            warnings.append(ResolutionWarning.NARROWED_BY_SUPPLIED_SCOPE)
        elif request.scope_entity_id is not None and len(by_entity) > 1:
            # A scope was given and it changed nothing — true of everyone, or of
            # nobody. Both are said out loud: "we consulted the context and it
            # did not help" is a different disclosure from silence, and the
            # nobody case used to be silent because no candidate carried a
            # signal to notice.
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
        # Corroboration resolves on its own, and a rival is not a prerequisite
        # for it. Keying this on `was_narrowed` alone meant that adding a
        # *duplicate* row upgraded a refusal into a resolution: one person named
        # Alice on the named project answered `AMBIGUOUS`, and the same person
        # with a same-named stranger beside her answered `RESOLVED_CONTEXTUAL`.
        # Strictly more evidence produced a strictly weaker answer, and
        # non-uniqueness licensed the join — the inverse of this plane's own
        # rule that uniqueness is a fact about the database rather than about
        # the person.
        corroborated = bool(only.signals)
        # **Asked of the evidence rather than of its presentation order.** This
        # read `strongest_basis is ResolutionBasis.ALIAS`, which was correct
        # only for as long as `ALIAS` was the weakest basis that may name an
        # entity: `strongest_basis` is the minimum of `_BASIS_ORDER`, so any
        # basis appended below `ALIAS` would have gone on satisfying the old
        # test and any inserted above it would have silently stopped. Appending
        # `TYPED_NAME` does exactly the first of those -- a typed-name-only
        # candidate has `strongest_basis is TYPED_NAME`, not `ALIAS`, so the old
        # form happened to refuse it, and a candidate matching *both* an alias
        # and a typed name would have kept `ALIAS` and resolved. Both answers
        # are right by accident of a dictionary's contents. `names_the_entity`
        # asks the question the safety rule means -- does any evidence here say
        # the reference named this entity -- and it is the same answer for all
        # four pre-existing bases, which `test_entity_resolution.py` pins.
        names_itself = only.names_the_entity
        resolves = names_itself or was_narrowed or corroborated
        if not resolves:
            return unresolved(ResolutionOutcome.AMBIGUOUS)

        warnings.extend(_currency_warnings(only.status))
        if only.status is not EntityStatus.ACTIVE:
            # `HISTORICAL_MATCH` is a *named* entity that is not current, and
            # `EntityResolution` refuses it for a candidate that names nothing
            # ("a name alone does not resolve an entity"). So the same question
            # is asked here, in the same words, rather than through the
            # presentation order: a candidate matched only by a canonical name,
            # a typed name, or a communication value is `AMBIGUOUS` whatever its
            # status, and reaching for the ordering to say so would re-couple
            # this refusal to `_BASIS_ORDER`'s contents.
            if not only.names_the_entity:
                return unresolved(ResolutionOutcome.AMBIGUOUS)
            return unresolved(ResolutionOutcome.HISTORICAL_MATCH)

        if corroborated and not was_narrowed and not names_itself:
            # The scope excluded no rival -- there was none -- but it is still
            # the entire reason this is a resolution rather than a refusal, and
            # `NARROWED_BY_SUPPLIED_SCOPE` is the disclosure whose own definition
            # is "the answer would have been `AMBIGUOUS` without it". Without
            # this the one outcome that most needs the disclosure was the one
            # that carried no warning at all: a lone bare-name match lifted to
            # `RESOLVED_CONTEXTUAL` by the caller's own hint, reported as though
            # the reference had named the entity.
            #
            # **Appended after the currency branch above, not before it.** A
            # non-current entity matched by canonical name returns `AMBIGUOUS`
            # from that branch, and this warning was already on it -- claiming a
            # scope had lifted an answer that was refused anyway, when both
            # halves of its own definition were false.
            warnings.append(ResolutionWarning.NARROWED_BY_SUPPLIED_SCOPE)

        # Contextual whenever the surrounding context did any of the deciding,
        # whether by excluding a rival or by being the only thing that lifted a
        # bare name above `AMBIGUOUS`. A caller reading `RESOLVED_EXACT` should
        # be able to take it that the reference itself named this entity.
        outcome = (
            ResolutionOutcome.RESOLVED_CONTEXTUAL
            if was_narrowed or corroborated
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
    ) -> _ScopeSignals:
        """Everything the surrounding context corroborates about one candidate.

        Computed for every candidate, including when it cannot change the
        answer, because a signal is evidence a reader is entitled to see even
        when it did not decide anything -- and because computing it only for the
        winner would mean the signals on an `AMBIGUOUS` answer were absent
        rather than false.
        """
        if request.scope_entity_id is None:
            return _ScopeSignals()
        # `as_of` when the caller asked about a moment, `at` otherwise. See
        # `_is_in_force`: a corroborating record has to be current, and "current"
        # needs a clock rather than an inference from a missing end date.
        moment = request.as_of if request.as_of is not None else request.at
        assigned = self._assigned_to(principal_id, entity_id, request.scope_entity_id, moment)
        related = self._related_to(principal_id, entity_id, request.scope_entity_id, moment)
        affiliated = self._affiliated_to(principal_id, entity_id, request.scope_entity_id, moment)
        participates = self._participates_in(
            principal_id, entity_id, request.scope_entity_id, moment
        )
        found: list[ContextualSignal] = []
        if assigned.found:
            found.append(ContextualSignal.ASSIGNED_TO_THE_NAMED_SCOPE)
        if related.found:
            found.append(ContextualSignal.RELATED_TO_THE_NAMED_SCOPE)
        if affiliated.found:
            found.append(ContextualSignal.AFFILIATED_WITH_THE_NAMED_SCOPE)
        if participates.found:
            found.append(ContextualSignal.PARTICIPATES_IN_THE_NAMED_SCOPE)
        return _ScopeSignals(
            found=tuple(found),
            withheld=(
                assigned.withheld
                or related.withheld
                or affiliated.withheld
                or participates.withheld
            ),
        )

    def _assigned_to(
        self, principal_id: str, entity_id: str, scope_entity_id: str, moment: datetime | None
    ) -> _Reach:
        """Whether a *current* assignment of this candidate names the scope.

        A status nobody updated and an end date nobody honoured are two ways for
        the same assignment to be stale, and both are checked.

        **Both are also disclosed, which took a correction.** `active_only=True`
        excluded ended assignments in the *query*, so they never reached the fold
        and never set `withheld` -- an assignment recorded as ended produced an
        `AMBIGUOUS` answer with no warning at all, while the same assignment left
        active but date-expired produced one. The exclusion is done here instead,
        so every row that reaches the scope is classified rather than some being
        invisible. `RI-AC-014`'s duty is to say the evidence was not current, and
        it does not care which column recorded that.
        """
        return _reach(
            (
                (
                    assignment.effective_from,
                    assignment.effective_to,
                    assignment.state.value == ACTIVE_ASSIGNMENT_STATUS,
                )
                for assignment in self._entities.assignments(
                    principal_id, entity_id, active_only=False
                )
                if assignment.scope_entity_id == scope_entity_id
            ),
            moment,
        )

    def _related_to(
        self, principal_id: str, entity_id: str, scope_entity_id: str, moment: datetime | None
    ) -> _Reach:
        """Whether a *current* outgoing edge of this candidate reaches the scope.

        `state == "active"` is the edge plane's equivalent of `active_only`, and
        it was the half this module used to be missing: `relationships()` takes
        no `active_only` argument, so an edge recorded as ended came back
        indistinguishable from a live one and corroborated exactly as strongly.
        An assignment somebody ended stopped counting and a relationship somebody
        ended did not, which made the answer depend on which table the same fact
        had been written to.
        """
        return _reach(
            (
                (
                    relationship.effective_from,
                    relationship.effective_to,
                    relationship.state.value == ACTIVE_RELATIONSHIP_STATE,
                )
                for relationship in self._entities.relationships(
                    principal_id, entity_id, direction="outgoing"
                )
                if scope_entity_id in (relationship.to_entity_id, relationship.scope_entity_id)
            ),
            moment,
        )

    def _affiliated_to(
        self, principal_id: str, entity_id: str, scope_entity_id: str, moment: datetime | None
    ) -> _Reach:
        """Whether a *current* recorded affiliation of this candidate names the scope.

        Section 15.1's "organization and role overlap", read off
        `entity_person_organization_affiliations` rather than inferred from a
        job title someone typed. Folded through `_reach` on `_assigned_to`'s
        own terms, so the two ways a row can be stale -- a `state` saying it is
        no longer the authoritative record, and a window that has closed -- are
        both excluded *and both disclosed*. `RI-AC-014`'s duty is to say the
        evidence was not current, and it does not care which column recorded
        that: an affiliation somebody ended must not corroborate silently, or a
        bare name is lifted to a confident answer by a person's former employer.

        `state` is compared against `PersonOrganizationAffiliationState`'s own
        member rather than a spelled `'active'`, for the reason
        `ACTIVE_ASSIGNMENT_STATUS` exists: two readers of the same column have
        to agree on which member means live. No module constant is minted for
        it because this family's `state` is a closed enum on the record itself,
        so there is no free-text column for a second reader to disagree with.

        **`state = ACTIVE` is not the same claim as "this affiliation is
        current".** `PersonOrganizationAffiliationState`'s docstring is explicit
        that an `ACTIVE` row with a closed `effective_to` is the ordinary way to
        record a *past* affiliation, not a contradiction. `is_in_force` inside
        `_reach` is what answers the second question, from the dates.
        """
        return _reach(
            (
                (
                    affiliation.effective_from,
                    affiliation.effective_to,
                    affiliation.state is PersonOrganizationAffiliationState.ACTIVE,
                )
                for affiliation in self._entities.person_organization_affiliations_as_person(
                    principal_id, entity_id
                )
                if affiliation.organization_entity_id == scope_entity_id
            ),
            moment,
        )

    def _participates_in(
        self, principal_id: str, entity_id: str, scope_entity_id: str, moment: datetime | None
    ) -> _Reach:
        """Whether a *current* recorded participation of this candidate names the scope.

        Section 15.1's "project-team membership", and deliberately not folded
        into `_assigned_to` even though both can be true of the same person and
        the same project. A participation and an assignment are different
        records making different claims, and reporting one signal for both would
        name a corroboration the reader could not go and check -- which is the
        distinction `ContextualSignal.PARTICIPATES_IN_THE_NAMED_SCOPE` states.

        The row is kept when its `project_entity_id` is the named scope: the
        candidate is the *participant*, which is why the read is
        `project_participations_as_participant` and not its sibling. Reading the
        other column would let a project corroborate itself as a participant in
        the entity somebody named.

        Stale rows are excluded and disclosed on `_affiliated_to`'s terms and
        for `RI-AC-014`'s reason, with `state` read from
        `EntityProjectParticipationState`.
        """
        return _reach(
            (
                (
                    participation.effective_from,
                    participation.effective_to,
                    participation.state is EntityProjectParticipationState.ACTIVE,
                )
                for participation in self._entities.project_participations_as_participant(
                    principal_id, entity_id
                )
                if participation.project_entity_id == scope_entity_id
            ),
            moment,
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


def _typed_name_evidence(name: EntityName) -> ResolutionEvidence:
    """`_alias_evidence`'s shape, over `entity_names`.

    The basis stays coarse: `name.name_type_code` says whether this was a legal,
    trading, former or document name, and that is a fact on the row a reader can
    follow through `source_record_id` -- it is deliberately not a member of
    `ResolutionBasis`, which would multiply that vocabulary and invite the
    graded reading it refuses.
    """
    return ResolutionEvidence(
        basis=ResolutionBasis.TYPED_NAME,
        matched_value=name.normalized_value,
        source_record_id=name.entity_name_id,
    )


def _communication_value_evidence(method: EntityCommunicationMethod) -> ResolutionEvidence:
    """The channel that matched, named so a reader can go and look at it.

    `verified` stays `False` whatever `method.verification_status_code` says,
    and `ResolutionEvidence` enforces that: only an external identifier basis
    may carry verification, because that flag means "this identity binding was
    verified" and a confirmed *contact channel* is not an identity binding.
    """
    return ResolutionEvidence(
        basis=ResolutionBasis.COMMUNICATION_VALUE,
        matched_value=method.normalized_value,
        source_record_id=method.communication_method_id,
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


def _without_refused(answer: EntityResolution, refused: frozenset[str]) -> EntityResolution:
    """The same answer with pairings the user has already refused taken out of it.

    **What this may do.** Remove refused candidates, so a known-bad pairing is
    not offered again; turn an answer whose every candidate was refused into
    `NOT_FOUND`; and turn a `CONFLICTED_IDENTIFIER` whose refusals leave fewer
    than two claimants into `AMBIGUOUS`, because a conflict between one entity
    and nobody is not a conflict and is certainly not a resolution.

    **What this may not do, and the reason is the whole design.** It never
    *improves* an outcome. Two same-named candidates with one refused stay
    `AMBIGUOUS` on the survivor rather than becoming a resolution: the
    refusal said who this is not, and `_name_outcome`'s rule is that a name is
    never an identifier however few people carry it. Removing a rival is not
    the caller supplying scope, so it does not narrow, and it never reaches
    `RESOLVED_CONTEXTUAL` through the back door.

    **Truncation is preserved rather than resolved away.** A `NOT_FOUND`
    produced here can still carry `candidates_were_truncated`, and it means
    exactly what it says: everything this answer could see was refused, and
    there was more it could not see. The one caller that treats `NOT_FOUND` as
    permission to create a new entity checks that flag as well, because "we
    found nobody" and "we refused everybody we could look at" are different
    facts and only the first one licenses a creation.
    """
    if not refused or not answer.candidates:
        return answer
    remaining = tuple(
        candidate for candidate in answer.candidates if candidate.entity_id not in refused
    )
    if len(remaining) == len(answer.candidates):
        return answer
    warnings = (*answer.warnings, ResolutionWarning.A_REFUSED_PAIRING_WAS_WITHHELD)
    if not remaining:
        return EntityResolution(
            outcome=ResolutionOutcome.NOT_FOUND,
            warnings=warnings,
            candidates_were_truncated=answer.candidates_were_truncated,
        )
    outcome = answer.outcome
    if outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER and len(remaining) < 2:
        outcome = ResolutionOutcome.AMBIGUOUS
    return EntityResolution(
        outcome=outcome,
        candidates=remaining,
        warnings=warnings,
        candidates_were_truncated=answer.candidates_were_truncated,
    )
