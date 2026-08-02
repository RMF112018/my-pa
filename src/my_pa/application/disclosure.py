"""Assembling the mandatory envelope out of what was actually measured.

`docs/specs` section 8.3 makes the envelope mandatory on every success and
partial result, and section 12 says coverage "is for a stated enrollment/snapshot
and never inferred globally". So nothing here invents a number. The counts come
from `KnowledgeRepository.coverage`, which reads the rows WP-3 persists; the
limitations come from `KnowledgeRepository.limitations`, which reads the
omissions the last enumeration pass recorded; and the only arithmetic in this
module decides which of those a caller may safely believe.

**The denominator is the hard part, and it is the same hard part twice.** An
enrollment that named its objects has an eligible total that is stored and
authoritative — the size of the array is the authorization. An enrollment that
named a root plus a depth has one that only an enumeration knows and that
nothing persists, so `eligible_total` answers `None` there, which is how
`coverage_for` is told that the denominator was never measured rather than being
handed a plausible integer. `infrastructure.persistence.extraction` records why
that distinction exists and what it cost when it was got wrong.

**A total derived from the outcomes divides out to all of them.** With no
measured denominator, whichever outcome an enrollment happens to hold becomes
the whole of its scope, so "every eligible object here was processed" — or
quarantined, or unsupported, or unavailable — is available and unearned.
`_claims_the_whole_scope` is that partition, written out member by member and
exhaustively, and a state that escaped it would escape the clamp silently. The
same rule is applied by `infrastructure.persistence.search` for the same reason.
It is stated twice rather than shared because the two layers may not import each
other; the partition is written the same way in both, and `assert_never` makes a
newly added `CoverageState` a type error in each rather than a state nobody
classified.

**Limitations are closed tokens.** `Disclosure.limitations` is a tuple of bare
strings, which is exactly the shape a free-text channel takes, so every token
this layer can emit is a member of `Limitation` below and every token it passes
through comes from `AggregateLimitation.disclosure`, whose two components are
themselves closed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final, assert_never

from my_pa.contracts.v1.disclosure import (
    Coverage,
    Disclosure,
    Freshness,
    FreshnessState,
    Scope,
    SourceReference,
    Truncation,
    Trust,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.source.enrollment import Enrollment

__all__ = [
    "Limitation",
    "disclosure_for",
    "eligible_total",
    "unenrolled_disclosure",
]


class Limitation(StrEnum):
    """Every limitation token this layer may disclose.

    Closed for the same reason `errors.SafeDetail` is: the field it lands in
    accepts any string, so the constraint has to come from the values that can
    reach it. Each names something a caller can act on, and none names a value.
    """

    #: The enrollment named a root, so no eligible total was ever measured.
    ELIGIBLE_TOTAL_NOT_PERSISTED = "eligible_total_not_persisted"
    #: A root selector authorizes its whole source; nothing persists the object
    #: set under the root, so the scope reported is wider than the root.
    SCOPE_IS_SOURCE_WIDE = "scope_is_source_wide_not_root_bounded"
    #: A listing stopped at the page size and this build issues no cursor.
    LISTING_HAS_NO_CONTINUATION = "listing_has_no_continuation_cursor"
    #: Returned text was cut to the maximum the request asked for.
    TEXT_TRUNCATED_TO_REQUESTED_MAXIMUM = "text_truncated_to_requested_maximum"
    #: Bytes were cut at the configured fetch ceiling.
    CONTENT_TRUNCATED_AT_FETCH_LIMIT = "content_truncated_at_fetch_limit"
    #: Nothing in the stated scope has been extracted.
    NO_EXTRACTED_TEXT_IN_SCOPE = "no_extracted_text_in_scope"
    #: Part of the stated scope has not reached an outcome.
    SCOPE_NOT_FULLY_EXTRACTED = "scope_not_fully_extracted"
    #: A result label is derived from a media type; no title is stored.
    LABEL_IS_MEDIA_TYPE_ONLY = "result_label_is_media_type_only"

    # `AUDIT_IS_NOT_DURABLE` was published here on every disclosure until
    # WP-4B2a. It said "audit events are emitted but no durable audit store
    # exists", which stopped being true when WP-4B1 built one and stayed on the
    # wire because nothing connected the sentence to the condition. It was inert
    # while no process served a disclosure and became a false statement to a
    # client the moment one did. Removed rather than reworded: a limitation names
    # something a caller can act on, and there is nothing left here to act on.


#: The absence of truncation, as one shared immutable value. A default argument
#: may not be a constructor call, and a frozen contract model is safe to share.
_NO_TRUNCATION: Final = Truncation()

#: Coverage states that mean the answer is incomplete. `Disclosure` refuses to
#: report one of these without `partial_result`, so this is the same partition
#: seen from the envelope's side.
_PARTIAL_STATES: frozenset[CoverageState] = frozenset(
    {
        CoverageState.PARTIALLY_PROCESSED,
        CoverageState.QUARANTINED,
        CoverageState.UNSUPPORTED,
        CoverageState.UNAVAILABLE,
        CoverageState.STALE,
    }
)


def _claims_the_whole_scope(state: CoverageState) -> bool:
    """Whether `state` asserts that every eligible object reached an outcome.

    The four in the first case each say "the whole scope ended this way", and
    all four are unsayable without a denominator somebody measured. The six in
    the second assert nothing of the kind: two say work has not finished, one
    says there is no scope, two are about the snapshot rather than the counts,
    and `partially_processed` is the honest reading this exists to fall back to.
    """
    match state:
        case (
            CoverageState.PROCESSED
            | CoverageState.QUARANTINED
            | CoverageState.UNSUPPORTED
            | CoverageState.UNAVAILABLE
        ):
            return True
        case (
            CoverageState.NOT_ENROLLED
            | CoverageState.ELIGIBLE
            | CoverageState.QUEUED
            | CoverageState.PARTIALLY_PROCESSED
            | CoverageState.STALE
            | CoverageState.SUPERSEDED
        ):
            return False
    assert_never(state)


def eligible_total(enrollment: Enrollment) -> int | None:
    """The measured size of `enrollment`'s scope, or `None` when nothing measured it.

    An explicit object list *is* the authorized scope, so its length is the
    denominator. A root selector's object set was known to the enumeration that
    walked it and nothing persists it, and `None` is how that is stated rather
    than guessed.
    """
    return None if enrollment.scope.root_object_id is not None else len(enrollment.scope.object_ids)


def _coverage_limitations(counts: CoverageCounts) -> tuple[Limitation, ...]:
    """What the counts themselves oblige the envelope to say."""
    if counts.processed == 0:
        return (Limitation.NO_EXTRACTED_TEXT_IN_SCOPE,)
    if counts.processed != counts.eligible:
        return (Limitation.SCOPE_NOT_FULLY_EXTRACTED,)
    return ()


def disclosure_for(
    *,
    enrollment: Enrollment,
    counts: CoverageCounts,
    limitations: tuple[AggregateLimitation, ...],
    classification: Classification,
    observed_at: datetime,
    trust_level: TrustLevel,
    trust_basis: tuple[str, ...],
    source_references: tuple[SourceReference, ...] = (),
    truncation: Truncation = _NO_TRUNCATION,
    extra_limitations: tuple[Limitation, ...] = (),
) -> Disclosure:
    """Build the envelope for a result produced inside one enrollment's grant.

    The coverage state is clamped where the denominator was never measured, and
    the two facts that make the clamp necessary are disclosed beside it: the
    total is unmeasured, and a root selector's numerator was gathered from the
    enrollment's whole source rather than from the subtree under its root. A
    caller told only the first would read the counts as a partial measurement of
    the right scope.
    """
    measured = eligible_total(enrollment) is not None
    state = counts.state()
    tokens: list[Limitation] = [*extra_limitations, *_coverage_limitations(counts)]
    if not measured:
        state = CoverageState.PARTIALLY_PROCESSED if _claims_the_whole_scope(state) else state
        tokens.append(Limitation.ELIGIBLE_TOTAL_NOT_PERSISTED)
        tokens.append(Limitation.SCOPE_IS_SOURCE_WIDE)
    # Every disclosure also carried `AUDIT_IS_NOT_DURABLE` from this line until
    # WP-4B2a, unconditionally. WP-4B1 built the durable store and the token
    # became a false statement made on every successful request; see the note on
    # `Limitation` for why it was removed rather than reworded.
    return Disclosure(
        scope=Scope(source_ids=(enrollment.source_id,), enrollment_ids=(enrollment.enrollment_id,)),
        coverage=Coverage(
            state=state,
            eligible=counts.eligible,
            processed=counts.processed,
            quarantined=counts.quarantined,
            unsupported=counts.unsupported,
        ),
        freshness=Freshness(
            observed_at=observed_at,
            # Each result binds the exact version it was produced from, so it is
            # current *for that version*. Whether the source has moved on since
            # is a question this layer cannot answer and does not claim to.
            state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION,
        ),
        trust=Trust(level=trust_level, basis=trust_basis),
        truncation=truncation,
        limitations=(
            *sorted(token.value for token in dict.fromkeys(tokens)),
            *sorted(limitation.disclosure for limitation in limitations),
        ),
        source_references=source_references,
        partial_result=state in _PARTIAL_STATES or truncation.is_truncated,
        classification=classification,
        # Never true from any capability here. Eligibility is a field-level
        # decision requiring a separate approval `P00-OD-006` has not given.
        cloud_eligible=False,
    )


def unenrolled_disclosure(observed_at: datetime) -> Disclosure:
    """The envelope for a result that describes the interface rather than a scope.

    `capabilities.get` reads no source and no enrollment, so its coverage is
    `not_enrolled` with every count zero — which `CoverageCounts` permits only
    for a scope no grant covers, and which is the truthful answer here rather
    than a shape borrowed from a result that measured something.

    It states no limitation at all. The one it used to carry was the audit
    claim removed above; a capability description has nothing else to qualify,
    and an empty tuple says so more honestly than a token kept for company.
    """
    counts = CoverageCounts(observed_at=observed_at)
    return Disclosure(
        scope=Scope(),
        coverage=Coverage(state=counts.state()),
        freshness=Freshness(
            observed_at=observed_at, state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION
        ),
        trust=Trust(level=TrustLevel.SOURCE_ORIGINAL, basis=("configured_interface",)),
        classification=Classification.PRIVATE_LOCAL,
        cloud_eligible=False,
    )
