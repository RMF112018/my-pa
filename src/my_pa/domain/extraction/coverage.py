"""Coverage for one stated enrollment at one stated snapshot, and what it missed.

Two jobs, and they are the same job seen from two sides.

**How much was covered.** `docs/specs` section 12 fixes ten coverage states and
says they are distinct, that none of them collapses into "empty", and that
coverage "is for a stated enrollment/snapshot and never inferred globally". So
`CoverageCounts` names the enrollment and the snapshot it is for and cannot be
constructed without them, and `eligible` is supplied by whoever enumerated the
scope rather than inferred from what happened to have been processed — a
denominator derived from the numerator would report full coverage of a scope
nobody measured.

**What was left out.** `docs/plans/mcv-completion-plan.md` section 10 records a
finding this module exists to answer: an object the provider refuses is omitted
from a listing with no signal at all, which turns present evidence into "not
there" and is what `INV-PKL-007` forbids. Section 9.2 permits the remedy and
bounds it — "Hidden/denied/unavailable/out-of-scope objects do not leak through
side channels; safe aggregate limitations may be disclosed."

`AggregateLimitation` is that remedy and nothing wider. It carries a count and a
reason code. It has no field for an identifier, a name, a locator, a media type,
or a time, so it cannot say *which* object was omitted, which is precisely the
existence disclosure the same sentence forbids. "Three objects in this enrollment
could not be proven contained" is true, useful, and tells a reader nothing about
what those three are.

`state` returns the `CoverageState` member itself. It briefly returned the
member's *value* instead, because the enum lived beside the envelope in
`contracts.v1.disclosure` and `tests/architecture/test_dependency_direction.py`
holds domain code to importing only domain code. The workaround pinned the
correspondence with tests, which made it checked but still asserted. The enum
has since moved to `my_pa.domain.common.coverage`, beside the two envelope
siblings it belongs with — `TrustLevel` and `Classification` are both domain
types that contracts imports — so the return type is now honest by construction
rather than by a test that could be deleted.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "AggregateLimitation",
    "CoverageCounts",
    "LimitationReason",
    "SnapshotState",
]


class LimitationReason(StrEnum):
    """Why a count of objects is missing from a result, as a safe code.

    One member, because one aggregate limitation is real today: the listing
    omission of `docs/plans/mcv-completion-plan.md` section 10. A second arrives
    with the code that can raise it, not before — a reason nothing can report is
    a disclosure the layer cannot make.

    The code deliberately does not distinguish a refused hard link from a
    resolution that failed or from an entry that is not a regular file. The
    provider cannot tell those apart without disclosing what it found, and a
    finer code would be an existence side channel with extra steps.
    """

    OBJECTS_OMITTED_CONTAINMENT_UNPROVEN = "objects_omitted_containment_unproven"


class SnapshotState(StrEnum):
    """How the snapshot the counts were taken at stands against the source now.

    Not derivable from counts, which is why it is an input. `STALE` means the
    source has moved on since the snapshot; `SUPERSEDED` means a later snapshot
    for the same enrollment has replaced this one. Both outrank what the counts
    say, because a complete count of a snapshot that no longer describes the
    source is not a complete answer about the source.
    """

    CURRENT = "current"
    STALE = "stale"
    SUPERSEDED = "superseded"


@dataclass(frozen=True, slots=True)
class AggregateLimitation:
    """A count of objects a result does not account for, and a safe reason.

    Deliberately not a list of what was omitted. See the module docstring.
    """

    reason: LimitationReason
    affected_count: int

    def __post_init__(self) -> None:
        if isinstance(self.affected_count, bool) or not isinstance(self.affected_count, int):
            raise ValueError("affected_count must be an integer")
        if self.affected_count < 1:
            # A limitation affecting nothing is not a limitation. Permitting a
            # zero would let a caller disclose "nothing was omitted for this
            # reason", which is a claim about the source it cannot support.
            raise ValueError("an aggregate limitation affects at least one object")

    @property
    def disclosure(self) -> str:
        """The limitation as one bounded token for the disclosure envelope.

        A reason code and a count joined by a colon, and nothing else can appear
        in it: both components are closed values, so the string cannot become a
        free-text channel.
        """
        return f"{self.reason.value}:{self.affected_count}"


@dataclass(frozen=True, slots=True)
class CoverageCounts:
    """What is known about one enrollment's scope at one observation.

    `enrollment_id` is `None` only for a scope that is not enrolled at all, and
    then every count must be zero: nothing is known about content no grant
    covers, and a count beside a missing enrollment would be a claim made
    outside any authorized scope.
    """

    observed_at: datetime
    enrollment_id: str | None = None
    eligible: int = 0
    queued: int = 0
    processed: int = 0
    quarantined: int = 0
    unsupported: int = 0
    unavailable: int = 0
    limitations: tuple[AggregateLimitation, ...] = ()
    snapshot: SnapshotState = SnapshotState.CURRENT

    def __post_init__(self) -> None:
        if self.enrollment_id is not None:
            validate_identifier(self.enrollment_id, IdKind.ENROLLMENT)
        for field, value in (
            ("eligible", self.eligible),
            ("queued", self.queued),
            ("processed", self.processed),
            ("quarantined", self.quarantined),
            ("unsupported", self.unsupported),
            ("unavailable", self.unavailable),
        ):
            if isinstance(value, bool) or not isinstance(value, int):
                raise ValueError(f"{field} must be an integer")
            if value < 0:
                raise ValueError(f"{field} cannot be negative")
        if self.accounted + self.queued > self.eligible:
            raise ValueError("outcomes and queued work cannot exceed the eligible count")
        if self.enrollment_id is None and (self.eligible or self.limitations):
            raise ValueError("an unenrolled scope has no eligible objects and no limitations")
        object.__setattr__(self, "observed_at", ensure_utc(self.observed_at))

    @property
    def accounted(self) -> int:
        """Eligible objects that reached an outcome, of any kind."""
        return self.processed + self.quarantined + self.unsupported + self.unavailable

    def state(self) -> CoverageState:
        """The `CoverageState` this coverage is in.

        The order of the tests is the precedence: enrollment first,
        because an unenrolled scope has no coverage to report; then the snapshot,
        because counts taken at a snapshot that no longer holds cannot be
        reported as current; then the counts.

        A single outcome that accounts for the whole scope reports itself, so
        "every eligible object was quarantined" is `quarantined` and not
        `partially_processed`. Anything mixed, or anything with work still
        outstanding beside a result, is `partially_processed` — the state that
        says explicitly that the answer is incomplete.
        """
        if self.enrollment_id is None:
            return CoverageState.NOT_ENROLLED
        if self.snapshot is SnapshotState.SUPERSEDED:
            return CoverageState.SUPERSEDED
        if self.snapshot is SnapshotState.STALE:
            return CoverageState.STALE
        if self.accounted == 0:
            # Nothing has an outcome yet. With an empty scope this is `eligible`
            # with every count zero, which is the honest answer for an
            # enrollment whose scope holds nothing: it is not "processed", and
            # section 12 forbids collapsing it into "empty".
            return CoverageState.QUEUED if self.queued else CoverageState.ELIGIBLE
        if self.processed == self.eligible:
            return CoverageState.PROCESSED
        if self.quarantined == self.eligible:
            return CoverageState.QUARANTINED
        if self.unsupported == self.eligible:
            return CoverageState.UNSUPPORTED
        if self.unavailable == self.eligible:
            return CoverageState.UNAVAILABLE
        return CoverageState.PARTIALLY_PROCESSED

    @property
    def disclosed_limitations(self) -> tuple[str, ...]:
        """Every limitation as a bounded token, in a stable order."""
        return tuple(sorted(limitation.disclosure for limitation in self.limitations))
