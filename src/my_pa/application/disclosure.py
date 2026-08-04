"""Assembling the mandatory envelope out of what was actually measured.

`docs/specs` section 8.3 makes the envelope mandatory on every success and
partial result, and section 12 says coverage "is for a stated enrollment/snapshot
and never inferred globally". So nothing here invents a number. The counts come
from `KnowledgeRepository.coverage`, which reads the rows WP-3 persists; the
limitations come from `KnowledgeRepository.limitations`, which reads the
omissions the last enumeration pass recorded; and the only arithmetic in this
module decides which of those a caller may safely believe.

**The denominator is no longer this layer's problem, and that is a deletion.**
An enrollment records the object set its enumeration found, in
`knowledge.enrollment_objects`, for a root selector exactly as for a named list;
`KnowledgeRepository.coverage` reads that count beside the outcomes it counts. So
this module states no eligible total, holds no coverage state down, and emits no
token about an unmeasured scope. `eligible_total`, `_claims_the_whole_scope`, and
the `ELIGIBLE_TOTAL_NOT_PERSISTED` and `SCOPE_IS_SOURCE_WIDE` tokens are gone
from the emittable vocabulary rather than left unreachable, because a token
nothing can emit is a claim nobody can act on and a guard nothing can fire.

The same logic was written out a second time in
`infrastructure.persistence.search`, because the two layers may not import each
other, and it is deleted there in the same change. Fixing one copy and not the
other is this package's signature defect; deletion is the only form of the fix
that cannot leave a divergence behind. `Disclosure.limitations` is
`tuple[str, ...]`, so removing tokens narrows what can appear and is not a v1
contract break — `eligible` stays a required integer and is now always a true
one, which is what `P00-OD-004` asks of it.

**Limitations are closed tokens.** `Disclosure.limitations` is a tuple of bare
strings, which is exactly the shape a free-text channel takes, so every token
this layer can emit is a member of `Limitation` below and every token it passes
through comes from `AggregateLimitation.disclosure`, whose two components are
themselves closed.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Final

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
    "unenrolled_disclosure",
]


class Limitation(StrEnum):
    """Every limitation token this layer may disclose.

    Closed for the same reason `errors.SafeDetail` is: the field it lands in
    accepts any string, so the constraint has to come from the values that can
    reach it. Each names something a caller can act on, and none names a value.
    """

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
    #: Capture search matches words as written and does not stem them, so
    #: `meetings` does not find `meeting`. **`D-90`'s stated cost, published
    #: rather than left for a caller to discover.** The capture plane is indexed
    #: with the `simple` text-search configuration precisely because
    #: `QC-AC-050` asks for *exact* original text to be searchable, and `english`
    #: fails that in two measured ways — it stems, and it produces an empty index
    #: entry for a capture of nothing but stop words. Exactness is what was
    #: bought; the absence of stemming is what it cost, and a limitation is
    #: where a cost that a caller can act on belongs.
    CAPTURE_SEARCH_DOES_NOT_STEM = "capture_search_matches_words_as_written"
    #: Some stored capture versions were outside the searched scope — a revised
    #: capture's superseded predecessor, or a version no receipt names. It is
    #: still readable through `capture.read`, which is `QC-AC-010`'s
    #: "independently retrievable"; it is not *found*. Emitted from the two
    #: counts the search itself measured, never from a constant.
    CAPTURE_SEARCH_EXCLUDES_SUPERSEDED = "capture_search_covers_current_versions_only"

    # A truncated capture-search page emits `LISTING_HAS_NO_CONTINUATION` rather
    # than a token of its own. The fact is identical — this build issues no
    # continuation cursor — and a further token restating it per capability
    # would give one absence more than one name.

    # `AUDIT_IS_NOT_DURABLE` was published here on every disclosure until
    # WP-4B2a. It said "audit events are emitted but no durable audit store
    # exists", which stopped being true when WP-4B1 built one and stayed on the
    # wire because nothing connected the sentence to the condition. It was inert
    # while no process served a disclosure and became a false statement to a
    # client the moment one did. Removed rather than reworded: a limitation names
    # something a caller can act on, and there is nothing left here to act on.
    #
    # `ELIGIBLE_TOTAL_NOT_PERSISTED` and `SCOPE_IS_SOURCE_WIDE` were published on
    # every root-selector disclosure until WP-4B3, and both said the same missing
    # fact twice: nothing persisted the object set under a root, so the
    # denominator was unmeasured and the numerator was gathered from the whole
    # source. `knowledge.enrollment_objects` is that fact. Removed rather than
    # left unreachable, for the reason above and one more: a token still in this
    # enum is a token a later branch can reach, and the guard in
    # `tests/architecture/test_transport_adds_no_behaviour.py` that named
    # `eligible_total` had to be removed with the function or it would have gone
    # on listing something that does not exist.


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

    The coverage state is the counts' own. Nothing is clamped and nothing is
    qualified about the denominator, because the denominator was measured: the
    counts arrive from a repository that read them beside the enumerated object
    set, and an enrollment with no such set does not exist.
    """
    state = counts.state()
    tokens: list[Limitation] = [*extra_limitations, *_coverage_limitations(counts)]
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


def unenrolled_disclosure(
    observed_at: datetime,
    *,
    trust_basis: tuple[str, ...] = ("configured_interface",),
    truncation: Truncation = _NO_TRUNCATION,
    extra_limitations: tuple[Limitation, ...] = (),
) -> Disclosure:
    """The envelope for a result produced outside any enrollment's grant.

    Two kinds of result are: `capabilities.get`, which describes the interface,
    and the capture capabilities, which read a product-owned record rather than
    a source. Neither reads a source or an enrollment, so coverage is
    `not_enrolled` with every count zero — which `CoverageCounts` permits only
    for a scope no grant covers, and which is the truthful answer here rather
    than a shape borrowed from a result that measured something. `Scope` is
    empty for the same reason: a capture belongs to no `src_…` and no `enr_…`,
    and naming one would be inventing a grant.

    **`trust_basis` is the caller's because the two answers rest on different
    things.** A capability description rests on configuration; a capture rests
    on the person who typed it, which `TrustLevel.SOURCE_ORIGINAL` is the
    correct level for — `ADR-003` makes a user-authored record an authority in
    its own right rather than something derived from one.

    `capabilities.get` states no limitation and passes none. A capture listing
    stops at the page size like every other listing in this build, so it passes
    the same token `sources.list` does.
    """
    counts = CoverageCounts(observed_at=observed_at)
    return Disclosure(
        scope=Scope(),
        coverage=Coverage(state=counts.state()),
        freshness=Freshness(
            observed_at=observed_at, state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION
        ),
        trust=Trust(level=TrustLevel.SOURCE_ORIGINAL, basis=trust_basis),
        truncation=truncation,
        limitations=tuple(sorted(token.value for token in dict.fromkeys(extra_limitations))),
        partial_result=truncation.is_truncated,
        classification=Classification.PRIVATE_LOCAL,
        cloud_eligible=False,
    )
