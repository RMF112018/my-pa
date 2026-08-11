"""Coverage of everything one Principal holds, composed from stated facts.

`domain.extraction.coverage` answers for **one stated enrollment**, because
`docs/specs` section 12 says coverage "is for a stated enrollment/snapshot and
never inferred globally". That rule is right and this module does not weaken it.
What the rule leaves open is the failure it does not name: a Principal holding
three enrollments and objects outside all of them can issue a search, receive a
confident answer with a clean disclosure, and never learn that most of what they
hold was outside the question. Section 23 names that failure explicitly — *a
search that silently omits unindexed sources and returns a confident answer*.

**This is a composition, not a new denominator.** `CorpusCoverage` holds the
`CoverageCounts` each enrollment stated, unmerged, and every total it exposes is
a plain sum over those statements. It computes no coverage of its own and reads
no rows: whoever builds one has already asked `coverage_for` per enrollment, so
there is exactly one definition of what "processed" means and this module is not
a second one. The sums are named `stated_*` for that reason, and
`totals_are_per_enrollment_sums` says out loud what a caller must not assume:
two enrollments over one source can enumerate the same object, so the sum of
`eligible` counts objects once per enrollment rather than once. A distinct-object
corpus denominator would be a different measurement, and inventing one here — out
of numbers that were measured for a different scope — is precisely the inference
section 12 forbids.

**Unknown territory is counted and never named.** `CorpusLimitation` is
`AggregateLimitation`'s shape and its discipline: a closed reason code and a
count, with no field for an identifier, a name, a locator, a media type or a
time. "Fifteen objects lie outside every enrollment you hold" is true, useful,
and tells a reader nothing about which fifteen — which is the whole of what
`docs/plans/mcv-completion-plan.md` section 9.2 permits ("safe aggregate
limitations may be disclosed") and the whole of what the same sentence forbids
("hidden/denied/unavailable/out-of-scope objects do not leak through side
channels").

It is a **separate enum from `LimitationReason`** rather than three new members
of it, and that is structural rather than tidiness. `LimitationReason` is
frozen into `knowledge.coverage_limitations.limitation_reason_is_known` at the
server: its members are a *stored* vocabulary written by an enumeration pass, and
widening it is a migration. Every reason here is derived at read time from rows
that already exist and is stored nowhere, so putting them in that enum would
oblige a schema change for a value no writer can ever write.

**What this answer is bounded by, stated rather than left to be discovered.** The
corpus is the sources the acting Principal holds an enrollment over, and nothing
else. `knowledge.sources` carries no `principal_id` — a Principal holds a source
by enrolling it — so "a source the Principal holds with no enrollment at all" is
not a state this schema can represent, and a count of *configured* sources the
Principal has not enrolled would be a fact about the operator's registry and, in
a multi-Principal deployment, about another Principal's enrollments. That is the
side channel above with extra steps, so it is not counted. What is counted is the
territory inside the held sources that no grant of this Principal's reaches, and
`CORPUS_IS_BOUNDED_TO_HELD_SOURCES` is published unconditionally so the answer
cannot be read as "this is everything that exists".
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.extraction.coverage import CoverageCounts

__all__ = [
    "CorpusCoverage",
    "CorpusLimitation",
    "CorpusLimitationReason",
]


class CorpusLimitationReason(StrEnum):
    """Why part of a Principal's corpus is not accounted for, as a safe code.

    Three members, and each arrives with the read that can raise it — the rule
    `LimitationReason` states and this follows. None distinguishes *which*
    objects, for the reason that module gives: a finer code is an existence side
    channel with extra steps.
    """

    #: Objects inside the sources this Principal holds that no enrollment of
    #: theirs enumerates. They are outside every question this Principal can ask.
    OBJECTS_OUTSIDE_EVERY_ENROLLMENT = "objects_outside_every_enrollment"
    #: Objects an enrollment enumerated that have reached no outcome at all —
    #: neither an extraction, an unsupported record, nor a quarantine. Not
    #: processed, not missing, and section 12 forbids reporting them as either.
    OBJECTS_AWAITING_AN_OUTCOME = "objects_awaiting_an_outcome"
    #: Enrollments whose own stated coverage is something other than `processed`.
    #: A count of enrollments rather than of objects, which is why it is a
    #: separate code: summing their shortfalls would be arithmetic across scopes.
    ENROLLMENTS_NOT_FULLY_PROCESSED = "enrollments_not_fully_processed"


@dataclass(frozen=True, slots=True)
class CorpusLimitation:
    """A count of things a corpus answer does not account for, and a safe reason.

    Deliberately not a list of what they are. See the module docstring, and
    `AggregateLimitation`, whose shape and refusals this repeats rather than
    reinvents.
    """

    reason: CorpusLimitationReason
    affected_count: int

    def __post_init__(self) -> None:
        if isinstance(self.affected_count, bool) or not isinstance(self.affected_count, int):
            raise ValueError("affected_count must be an integer")
        if self.affected_count < 1:
            # A limitation affecting nothing is not a limitation, and permitting
            # a zero would let a caller publish "nothing is outside your
            # enrollments", which is a stronger claim than this layer measured.
            raise ValueError("a corpus limitation affects at least one thing")

    @property
    def disclosure(self) -> str:
        """The limitation as one bounded token for the disclosure envelope.

        A closed reason code and a count joined by a colon, exactly as
        `AggregateLimitation.disclosure` is, so the two kinds of token read the
        same way to a consumer and neither can become a free-text channel.
        """
        return f"{self.reason.value}:{self.affected_count}"


@dataclass(frozen=True, slots=True)
class CorpusCoverage:
    """What one Principal holds, what was covered, and what was never in scope.

    Every field is a measurement someone else took. This type composes them,
    states the composition's limits, and refuses to describe an incomplete
    corpus as a complete one.
    """

    observed_at: datetime
    principal_id: str
    #: One stated coverage per enrollment this Principal holds, unmerged, in a
    #: stable order. Each is the very value `sources.status` and `knowledge.search`
    #: report for that enrollment, so no reader has to reconcile two definitions.
    enrollments: tuple[CoverageCounts, ...] = ()
    #: Distinct sources those enrollments cover.
    held_sources: int = 0
    #: Objects observed in those sources, whether enrolled or not. The
    #: denominator `objects_outside_every_enrollment` is a shortfall against.
    objects_in_held_sources: int = 0
    #: Objects in those sources that no enrollment of this Principal enumerates.
    objects_outside_every_enrollment: int = 0
    #: Enumerated objects that have reached no outcome yet, across every
    #: enrollment this Principal holds.
    objects_awaiting_an_outcome: int = 0

    def __post_init__(self) -> None:
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        for field, value in (
            ("held_sources", self.held_sources),
            ("objects_in_held_sources", self.objects_in_held_sources),
            ("objects_outside_every_enrollment", self.objects_outside_every_enrollment),
            ("objects_awaiting_an_outcome", self.objects_awaiting_an_outcome),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field} must be an integer")
            if value < 0:
                raise ValueError(f"{field} cannot be negative")
        for counts in self.enrollments:
            if counts.enrollment_id is None:
                # A corpus is a composition of *stated* coverages, and
                # `CoverageCounts` uses a missing enrollment to mean a scope no
                # grant covers. Admitting one here would put a non-statement in
                # the list of statements this answer is built from.
                raise ValueError("every corpus member states the enrollment it is for")
        identifiers = [counts.enrollment_id for counts in self.enrollments]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("an enrollment states its coverage once")
        if self.objects_outside_every_enrollment > self.objects_in_held_sources:
            raise ValueError("more objects lie outside every enrollment than the sources hold")
        if not self.enrollments and (
            self.held_sources
            or self.objects_in_held_sources
            or self.objects_outside_every_enrollment
            or self.objects_awaiting_an_outcome
        ):
            # No enrollment means no held source, and every count above is
            # derived from the held sources. A count beside an empty enrollment
            # set would be a measurement taken outside any authorized scope.
            raise ValueError("a Principal holding no enrollment holds no measured corpus")
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))
        self._refuse_a_complete_looking_answer()

    def _refuse_a_complete_looking_answer(self) -> None:
        """The invariant, checked at construction rather than trusted to `state`.

        `state` derives the answer and so cannot currently lie. This exists
        because that is a property of one function body, and the failure this
        package closes is exactly a confident-looking answer over partial
        coverage: an edit that made `state` return `PROCESSED` too readily would
        be a one-line change with no test of its own necessarily red. Here it
        makes the value **unconstructible**, which is a stronger claim than a
        convention and than a test that has to remember to look.
        """
        if self.state() is not CoverageState.PROCESSED:
            return
        unaccounted = self.objects_outside_every_enrollment + self.objects_awaiting_an_outcome
        unprocessed = tuple(
            counts for counts in self.enrollments if counts.state() is not CoverageState.PROCESSED
        )
        if unaccounted or unprocessed or not self.enrollments:
            raise ValueError(
                "a corpus with unenrolled objects, work awaiting an outcome, or an "
                "enrollment that is not fully processed cannot report as processed"
            )

    @property
    def enrollment_count(self) -> int:
        """How many enrollments this answer is composed from."""
        return len(self.enrollments)

    @property
    def stated_eligible(self) -> int:
        """The sum of the eligible totals the enrollments stated.

        A sum of statements, not a corpus denominator: see
        `totals_are_per_enrollment_sums`.
        """
        return sum(counts.eligible for counts in self.enrollments)

    @property
    def stated_processed(self) -> int:
        """The sum of the processed counts the enrollments stated."""
        return sum(counts.processed for counts in self.enrollments)

    @property
    def stated_quarantined(self) -> int:
        """The sum of the quarantined counts the enrollments stated."""
        return sum(counts.quarantined for counts in self.enrollments)

    @property
    def stated_unsupported(self) -> int:
        """The sum of the unsupported counts the enrollments stated."""
        return sum(counts.unsupported for counts in self.enrollments)

    @property
    def totals_are_per_enrollment_sums(self) -> bool:
        """Whether a total above can count one object more than once.

        True from the second enrollment onward, and it is a property rather than
        a constant because with one enrollment the sum *is* that enrollment's
        own statement and a caveat would be noise. Two enrollments over one
        source can enumerate the same object; nothing here deduplicates them,
        and a corpus answer that quietly did would be reporting a number nobody
        measured.
        """
        return self.enrollment_count > 1

    def state(self) -> CoverageState:
        """The corpus's coverage state, which can never overstate what was done.

        Three of the ten states are reachable and the order of the tests is the
        precedence:

        * `not_enrolled` when the Principal holds no enrollment at all. That is
          the honest answer and not "empty": nothing was searched because there
          was no grant to search inside, which section 12 forbids collapsing.
        * `partially_processed` while anything is outside every enrollment, while
          anything awaits an outcome, or while any single enrollment states
          anything other than `processed`. `Disclosure` refuses that state
          without `partial_result`, so the envelope cannot present it as
          complete either.
        * `processed` only when every enrollment states `processed`, nothing is
          pending, and nothing in the held sources lies outside them all.

        The other seven are deliberately unreachable. `quarantined`,
        `unsupported`, `stale` and the rest describe *one* scope's outcome, and
        promoting one enrollment's state to the corpus would be the global
        inference this module exists to avoid; each is still stated, per
        enrollment, in `enrollments`.
        """
        if not self.enrollments:
            return CoverageState.NOT_ENROLLED
        if self.objects_outside_every_enrollment or self.objects_awaiting_an_outcome:
            return CoverageState.PARTIALLY_PROCESSED
        if all(counts.state() is CoverageState.PROCESSED for counts in self.enrollments):
            return CoverageState.PROCESSED
        return CoverageState.PARTIALLY_PROCESSED

    @property
    def limitations(self) -> tuple[CorpusLimitation, ...]:
        """Every unknown-territory limitation this corpus has to declare.

        Built from the counts rather than from a flag, so a limitation exists
        exactly when something it could be about exists. Nothing with a zero
        count is emitted, because `CorpusLimitation` refuses one.
        """
        unprocessed = sum(
            1 for counts in self.enrollments if counts.state() is not CoverageState.PROCESSED
        )
        found = (
            (
                CorpusLimitationReason.OBJECTS_OUTSIDE_EVERY_ENROLLMENT,
                self.objects_outside_every_enrollment,
            ),
            (
                CorpusLimitationReason.OBJECTS_AWAITING_AN_OUTCOME,
                self.objects_awaiting_an_outcome,
            ),
            (CorpusLimitationReason.ENROLLMENTS_NOT_FULLY_PROCESSED, unprocessed),
        )
        return tuple(
            CorpusLimitation(reason=reason, affected_count=count)
            for reason, count in found
            if count
        )

    @property
    def disclosed_limitations(self) -> tuple[str, ...]:
        """Every limitation as a bounded token, in a stable order."""
        return tuple(sorted(limitation.disclosure for limitation in self.limitations))
