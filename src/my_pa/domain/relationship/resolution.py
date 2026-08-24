"""What resolving a reference to an entity answers.

**The core rule this module exists to make structural.** The specification says
ambiguous mentions "remain unresolved rather than forced into the nearest
person" (section 15.2), that "ambiguous identity matches remain unresolved"
(section 10.3), and that "names alone are insufficient" and "conflicting
immutable identifiers prevent automatic merge" (section 15.2). `RI-RISK-001`
asks for precision-first metrics because a false join contaminates profile,
timeline, commitments and briefings at once.

A convention cannot carry that. `EntityResolution.resolved_entity_id` is
therefore a *derived* property that returns an identifier only for the two
resolved outcomes, and the constructor refuses a resolution whose outcome and
candidate set disagree. An `AMBIGUOUS` answer cannot be made to yield an entity
identifier by any caller, however it is read -- there is no field to read.

**Why this is an addition rather than a requirement.** The specification has no
per-query resolution outcome vocabulary. It has a *record lifecycle* state
machine (section 13.1: `unresolved_mention`, `candidate_match`,
`provisionally_linked`, `confirmed_person`, `duplicate_candidate`,
`merge_proposed`, `merged`, `split_proposed`, `split`, `disputed`,
`superseded`), which describes what a stored identity link *is*, not what a
lookup *returned*. The two are different questions, and answering the second one
with the first's vocabulary would say `unresolved_mention` for a query that
found four excellent candidates. So this vocabulary is a decision recorded in
`docs/plans/relationship-intelligence-implementation-plan.md` as `D-RI-07`.

**Why there is no numeric here.** Specification section 22.3 admits a numeric
"only when calibrated and explained", and
`tests/architecture/test_relationship_scoring_surface_is_denied` refuses the
vocabulary of graded judgement on this surface outright. Nothing in exact
resolution is calibrated, so nothing here is numeric: a candidate carries the
*basis* it matched on, which is what makes the answer explainable, and a basis
is a fact about the evidence rather than an opinion about the person.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.relationship.entity import EntityStatus, EntityType

__all__ = [
    "RESOLUTION_CANDIDATE_LIMIT",
    "ContextualSignal",
    "EntityResolution",
    "ResolutionBasis",
    "ResolutionCandidate",
    "ResolutionEvidence",
    "ResolutionOutcome",
    "ResolutionWarning",
]

#: The most candidates one answer carries. A bound rather than everything,
#: because an unbounded candidate list is an unbounded response, and a caller
#: choosing between four hundred people is not being helped by the extra three
#: hundred and ninety. Truncation is *disclosed* rather than silent
#: (`EntityResolution.candidates_were_truncated`), which is section 26.4's rule:
#: a partial answer must not read as a complete one.
RESOLUTION_CANDIDATE_LIMIT: int = 10


class ResolutionOutcome(StrEnum):
    """What a resolution attempt found, as a closed answer.

    Six outcomes rather than "found" and "not found", because the four in
    between are the ones a caller must not treat as either. `AMBIGUOUS` and
    `CONFLICTED_IDENTIFIER` are the safety outcomes: both mean candidates were
    found and none may be acted on.
    """

    #: One entity matched an identifier or an alias unambiguously.
    RESOLVED_EXACT = "resolved_exact"
    #: One entity remained after a supplied scope narrowed several candidates.
    RESOLVED_CONTEXTUAL = "resolved_contextual"
    #: Candidates were found and none may be acted on. Not an error, and not a
    #: licence to pick the first: this is the answer.
    #:
    #: **One candidate is enough for this outcome.** A single entity whose only
    #: evidence is that its name matches is ambiguous in the sense that matters
    #: -- section 15.2 says "names alone are insufficient", and there is no
    #: number of name matches at which a name becomes an identifier. Reserving
    #: this outcome for two-or-more would mean a lone name match had to be
    #: reported as resolved, which is the false join the plane exists to avoid.
    AMBIGUOUS = "ambiguous"
    #: Nothing matched. Distinct from `AMBIGUOUS` because "I know of no such
    #: person" and "I know of four" call for opposite next steps.
    NOT_FOUND = "not_found"
    #: One identifier is claimed by more than one entity. Section 15.2 makes
    #: this a hard stop: conflicting identifiers prevent automatic merge, and a
    #: lookup that resolved through one anyway would perform the join the merge
    #: rule refuses.
    CONFLICTED_IDENTIFIER = "conflicted_identifier"
    #: One entity matched, but it is not current -- inactive, archived, or
    #: merged away. The caller is told which, rather than being handed a stale
    #: record as though it were live (`RI-AC-014`).
    HISTORICAL_MATCH = "historical_match"


class ResolutionBasis(StrEnum):
    """What a candidate matched on. The explainability half of an answer.

    Ordered from strongest to weakest evidence in `_BASIS_ORDER` below, which is
    the ordering `EntityResolution.candidates` is presented in. An order over
    *kinds of evidence* rather than a number per candidate: section 15.2 says an
    exact identifier is strong evidence and a name alone is insufficient, which
    is a statement about kinds.
    """

    #: An external identifier something verified. The strongest evidence here.
    VERIFIED_EXTERNAL_IDENTIFIER = "verified_external_identifier"
    #: An external identifier nothing has verified yet.
    EXTERNAL_IDENTIFIER = "external_identifier"
    #: A recorded alias of the entity.
    ALIAS = "alias"
    #: The entity's own canonical name. Weakest: section 15.2's "names alone are
    #: insufficient" applies exactly here.
    CANONICAL_NAME = "canonical_name"


_BASIS_ORDER: dict[ResolutionBasis, int] = {
    ResolutionBasis.VERIFIED_EXTERNAL_IDENTIFIER: 0,
    ResolutionBasis.EXTERNAL_IDENTIFIER: 1,
    ResolutionBasis.ALIAS: 2,
    ResolutionBasis.CANONICAL_NAME: 3,
}


class ContextualSignal(StrEnum):
    """What the surrounding context corroborated, beyond what the reference matched.

    Distinct from `ResolutionBasis` on purpose. A *basis* is what the reference
    matched -- an identifier, an alias, a name. A *signal* is something true of
    the candidate that the reference did not say: that they are on the project
    the caller named. Collapsing the two would let a corroborating detail read as
    though the reference had named it.

    Section 15.1 admits "organization and role overlap" and "project-team
    membership" as resolution evidence, and both of those are here. It also
    admits calendar attendees, email participants, introduction chains and
    negative evidence -- none of which this product observes yet. They arrive
    with the observation record, and with them the question of whether a signal
    may *select* a candidate or only support one; today every signal here is a
    recorded assignment or a typed edge, and both are specific enough to select.
    """

    #: The candidate holds an assignment whose scope is the entity the caller
    #: named. The strongest contextual evidence available here: someone being on
    #: the project asked about is a recorded fact about them and the project.
    ASSIGNED_TO_THE_NAMED_SCOPE = "assigned_to_the_named_scope"
    #: A typed relationship of the candidate reaches the named scope -- works
    #: for that organization, is a contractor on that project.
    RELATED_TO_THE_NAMED_SCOPE = "related_to_the_named_scope"


class ResolutionWarning(StrEnum):
    """What was true about an answer that a caller must not have to infer.

    Warnings are carried on the resolution rather than folded into the outcome,
    because several can be true at once and collapsing them would lose the one
    the caller needed. Section 26.4 requires a search or synthesis to disclose
    unresolved identity; these are that disclosure in a closed vocabulary.
    """

    #: More than one entity carries this name. Present even on a resolved
    #: answer, when the resolution came from an identifier rather than the name.
    SEVERAL_ENTITIES_SHARE_THIS_NAME = "several_entities_share_this_name"
    #: The identifier searched for is recorded against more than one entity.
    IDENTIFIER_CLAIMED_BY_SEVERAL_ENTITIES = "identifier_claimed_by_several_entities"
    #: The evidence that matched was outside its effective dates at the moment
    #: asked about, and was excluded.
    EVIDENCE_WAS_NOT_EFFECTIVE_AT_THAT_MOMENT = "evidence_was_not_effective_at_that_moment"
    #: The matched entity has been merged into another. Its successor is on the
    #: candidate as `superseded_by_entity_id`.
    ENTITY_HAS_BEEN_MERGED_AWAY = "entity_has_been_merged_away"
    #: The matched entity is inactive, historical, or archived.
    ENTITY_IS_NOT_CURRENT = "entity_is_not_current"
    #: The identifier that matched is unverified. Section 15.2 keeps exact
    #: identifiers "source- and time-aware" rather than absolute.
    MATCHED_IDENTIFIER_IS_UNVERIFIED = "matched_identifier_is_unverified"
    #: A supplied scope narrowed the candidate set. Disclosed because the answer
    #: would have been `AMBIGUOUS` without it.
    NARROWED_BY_SUPPLIED_SCOPE = "narrowed_by_supplied_scope"
    #: More candidates matched than the answer carries. Disclosed because a
    #: truncated list that reads as complete is the failure section 26.4 names.
    MORE_CANDIDATES_THAN_THIS_ANSWER_CARRIES = "more_candidates_than_this_answer_carries"
    #: The supplied context was true of every candidate, so it distinguished
    #: none of them. Said out loud so a reader can see that the system consulted
    #: the context and it did not help, rather than never having looked.
    CONTEXT_DID_NOT_DISTINGUISH_THE_CANDIDATES = "context_did_not_distinguish_the_candidates"
    #: A candidate this answer would otherwise have carried was withheld
    #: because the user has already refused that pairing. Disclosed because the
    #: alternative is an answer that quietly differs from the same question
    #: asked before the refusal, with nothing on it saying why.
    A_REFUSED_PAIRING_WAS_WITHHELD = "a_refused_pairing_was_withheld"


@dataclass(frozen=True, slots=True)
class ResolutionEvidence:
    """One reason a candidate is a candidate.

    `matched_value` is `repr=False` for the reason `CreateCapture.text` is: it
    is a normalized email address or personal name, and a dataclass `repr`
    reaches a traceback, a log record, and a pytest assertion message without
    anyone deciding it should (`AGENTS.md` section 5).
    """

    basis: ResolutionBasis
    matched_value: str = field(repr=False)
    verified: bool = False
    source_record_id: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.basis, ResolutionBasis):
            raise ValueError("resolution evidence has a closed basis")
        if not self.matched_value.strip():
            raise ValueError("resolution evidence names the value it matched")
        if self.verified and self.basis is not ResolutionBasis.VERIFIED_EXTERNAL_IDENTIFIER:
            raise ValueError("only an external identifier basis carries verification")


@dataclass(frozen=True, slots=True)
class ResolutionCandidate:
    """One entity a reference could name, with why.

    `evidence` is non-empty by construction. A candidate with no evidence would
    be an entity the system is proposing for no stated reason, which is the
    unexplainable answer sections 6.2 and 11.6 exist to refuse.
    """

    entity_id: str
    entity_type: EntityType
    display_name: str
    status: EntityStatus
    evidence: tuple[ResolutionEvidence, ...]
    superseded_by_entity_id: str | None = None
    signals: tuple[ContextualSignal, ...] = ()

    def __post_init__(self) -> None:
        validate_identifier(self.entity_id, IdKind.ENTITY)
        if not isinstance(self.entity_type, EntityType):
            raise ValueError("a resolution candidate has a closed entity type")
        if not isinstance(self.status, EntityStatus):
            raise ValueError("a resolution candidate has a closed status")
        if not self.evidence:
            raise ValueError("a resolution candidate states why it is a candidate")
        if self.superseded_by_entity_id is not None:
            validate_identifier(self.superseded_by_entity_id, IdKind.ENTITY)
        for signal in self.signals:
            if not isinstance(signal, ContextualSignal):
                raise ValueError("a contextual signal is from the closed vocabulary")
        if len(set(self.signals)) != len(self.signals):
            raise ValueError("a resolution candidate states each signal once")

    @property
    def strongest_basis(self) -> ResolutionBasis:
        """The best evidence this candidate has, for ordering."""
        return min(
            (item.basis for item in self.evidence),
            key=lambda basis: _BASIS_ORDER[basis],
        )

    @property
    def is_current(self) -> bool:
        return self.status is EntityStatus.ACTIVE

    @property
    def is_corroborated(self) -> bool:
        """Whether the surrounding context said anything about this candidate."""
        return bool(self.signals)


@dataclass(frozen=True, slots=True)
class EntityResolution:
    """The whole answer to one resolution attempt.

    The constructor refuses any combination of outcome and candidates that would
    let a caller read an identifier out of an unresolved answer, or read an
    unexplained one out of a resolved answer. Those refusals are the safety
    rule; everything else here is presentation.
    """

    outcome: ResolutionOutcome
    candidates: tuple[ResolutionCandidate, ...] = ()
    warnings: tuple[ResolutionWarning, ...] = ()
    candidates_were_truncated: bool = False

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ResolutionOutcome):
            raise ValueError("a resolution has a closed outcome")
        if len(self.candidates) > RESOLUTION_CANDIDATE_LIMIT:
            raise ValueError("a resolution carries a bounded candidate list")
        if self.candidates_were_truncated and (
            ResolutionWarning.MORE_CANDIDATES_THAN_THIS_ANSWER_CARRIES not in self.warnings
        ):
            raise ValueError("a truncated resolution says so in its warnings")
        for warning in self.warnings:
            if not isinstance(warning, ResolutionWarning):
                raise ValueError("a resolution warning is from the closed vocabulary")
        if len(set(self.warnings)) != len(self.warnings):
            raise ValueError("a resolution states each warning once")
        seen: set[str] = set()
        for candidate in self.candidates:
            if candidate.entity_id in seen:
                raise ValueError("a resolution lists each candidate once")
            seen.add(candidate.entity_id)
        self._check_candidate_count()
        self._check_outcome_agrees_with_candidates()

    def _check_candidate_count(self) -> None:
        single = {
            ResolutionOutcome.RESOLVED_EXACT,
            ResolutionOutcome.RESOLVED_CONTEXTUAL,
            ResolutionOutcome.HISTORICAL_MATCH,
        }
        if self.outcome in single and len(self.candidates) != 1:
            raise ValueError("a resolved outcome names exactly one entity")
        if self.outcome is ResolutionOutcome.AMBIGUOUS and not self.candidates:
            raise ValueError("an ambiguous outcome names the entities it could not choose between")
        if self.outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER and len(self.candidates) < 2:
            raise ValueError("a conflicted identifier is claimed by more than one entity")
        if self.outcome is ResolutionOutcome.NOT_FOUND and self.candidates:
            raise ValueError("a not-found outcome names no entity")

    def _check_outcome_agrees_with_candidates(self) -> None:
        if self.outcome is ResolutionOutcome.HISTORICAL_MATCH and self.candidates[0].is_current:
            raise ValueError("a historical match names an entity that is not current")
        if (
            self.outcome
            in {ResolutionOutcome.RESOLVED_EXACT, ResolutionOutcome.RESOLVED_CONTEXTUAL}
            and not self.candidates[0].is_current
        ):
            raise ValueError("a resolved outcome names a current entity")
        if (
            self.outcome is ResolutionOutcome.CONFLICTED_IDENTIFIER
            and ResolutionWarning.IDENTIFIER_CLAIMED_BY_SEVERAL_ENTITIES not in self.warnings
        ):
            raise ValueError("a conflicted identifier outcome says the identifier is conflicted")
        if self.candidates_were_truncated and self.is_resolved:
            raise ValueError("a resolved outcome is not one candidate out of an unknown many")
        named_only = {ResolutionOutcome.RESOLVED_EXACT, ResolutionOutcome.HISTORICAL_MATCH}
        if (
            self.outcome in named_only
            and self.candidates[0].strongest_basis is ResolutionBasis.CANONICAL_NAME
        ):
            raise ValueError("a name alone does not resolve an entity")

    @property
    def resolved_entity_id(self) -> str | None:
        """The entity this resolved to, or `None` if it did not resolve.

        A property rather than a field, so there is nothing for an `AMBIGUOUS`
        or `CONFLICTED_IDENTIFIER` answer to carry and nothing for a caller to
        read past. `HISTORICAL_MATCH` returns `None` too: it named an entity,
        but not one that is current, and a caller that wants it can read
        `candidates[0]` deliberately.
        """
        if self.outcome in {
            ResolutionOutcome.RESOLVED_EXACT,
            ResolutionOutcome.RESOLVED_CONTEXTUAL,
        }:
            return self.candidates[0].entity_id
        return None

    @property
    def is_resolved(self) -> bool:
        return self.resolved_entity_id is not None


def order_candidates(
    candidates: tuple[ResolutionCandidate, ...],
) -> tuple[ResolutionCandidate, ...]:
    """Candidates strongest evidence first, then by identifier.

    The identifier tiebreak is there so the order is total and stable: two
    candidates with the same basis would otherwise be presented in whatever
    order the database returned them, and a list that reorders between two
    identical queries reads as though the answer changed.

    Ordering is *presentation*, and does not make the first candidate the
    answer. `resolved_entity_id` is the only thing that names an answer, and it
    is `None` whenever there is more than one candidate.
    """
    return tuple(
        sorted(
            candidates,
            key=lambda candidate: (_BASIS_ORDER[candidate.strongest_basis], candidate.entity_id),
        )
    )
