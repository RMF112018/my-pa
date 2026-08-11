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
from my_pa.domain.extraction.corpus import CorpusCoverage
from my_pa.domain.extraction.coverage import AggregateLimitation, CoverageCounts
from my_pa.domain.source.enrollment import Enrollment

__all__ = [
    "Limitation",
    "corpus_disclosure",
    "disclosure_for",
    "unavailable_disclosure",
    "unenrolled_disclosure",
    "with_corpus_caveat",
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
    #: A reveal returns the *locator* of each citation and never the text it
    #: covers. Unconditional on that capability because the property is: there
    #: is no field a quote could go in. A caller acts on it by reading the
    #: version through `capture.read`, under that capability's own audit event.
    EVIDENCE_SPANS_CARRY_NO_QUOTED_TEXT = "evidence_spans_carry_offsets_and_digests_only"
    #: A corpus answer's totals are sums of what each enrollment stated, so an
    #: object two enrollments both enumerate is counted once per enrollment.
    #: Published only when there is more than one enrollment to sum, because with
    #: one the sum *is* that enrollment's own statement. The alternative —
    #: deduplicating into a distinct-object total — would report a number nobody
    #: measured, which is the global inference `docs/specs` section 12 forbids.
    CORPUS_TOTALS_ARE_PER_ENROLLMENT_SUMS = "corpus_totals_are_sums_of_per_enrollment_statements"
    #: A corpus answer covers the sources this Principal has enrolled and no
    #: others. Unconditional on that capability, because the property is: a source
    #: nobody enrolled is not in `enrollments`, `knowledge.sources` carries no
    #: `principal_id` to bound a wider count by, and counting the operator's whole
    #: registry would disclose another Principal's enrollments in aggregate. The
    #: token is what stops the answer reading as "this is everything that exists".
    CORPUS_COVERS_ONLY_ENROLLED_SOURCES = "corpus_covers_only_sources_this_principal_enrolled"
    #: **A search answered inside one enrollment while the Principal holds scope
    #: outside it.** The result is correct for the enrollment it names and is not
    #: an answer about the corpus, and without this token a caller has no way to
    #: tell those apart — which is section 23's named failure: a search that
    #: silently omits unindexed scope and returns a confident answer. Emitted from
    #: a measurement, never from a constant, and beside `partial_result=True`.
    #: It says *that* there is scope outside the question and never how much or
    #: what, so it is not a channel for the size of a scope the request did not
    #: name.
    SEARCH_DOES_NOT_SPAN_THE_CORPUS = "search_does_not_span_this_principals_corpus"
    #: **The token that makes "unavailable" different from "empty".** The scope
    #: was not searched — a subject kind this evidence model does not cover, or
    #: a version whose derivation has not completed — so the absence of results
    #: is an absence of *searching*, and `INV-PKL-007` forbids reporting it as an
    #: absence of evidence. Emitted only beside `CoverageState.UNAVAILABLE`, and
    #: `Disclosure` refuses that state without `partial_result`, so a caller
    #: that reads neither field still cannot receive a complete-looking answer.
    EVIDENCE_SCOPE_WAS_NOT_SEARCHED = "evidence_scope_was_not_searched"

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


def corpus_disclosure(
    corpus: CorpusCoverage,
    *,
    trust_basis: tuple[str, ...] = ("composed_enrollment_coverage",),
) -> Disclosure:
    """The envelope for a Principal-wide corpus coverage answer.

    **Every number in it is a sum of statements, and the envelope says so.** The
    coverage block carries the summed counts because `Coverage` requires
    integers and a caller rendering the envelope should see the same figures the
    payload does; `CORPUS_TOTALS_ARE_PER_ENROLLMENT_SUMS` is what stops those
    figures being read as a distinct-object corpus total, and the per-enrollment
    breakdown in the payload is where the unmerged statements are.

    **The state is `CorpusCoverage`'s and is not recomputed here.** That type
    refuses to be constructed claiming a complete corpus while anything lies
    outside the enrollments, anything awaits an outcome, or any enrollment is
    less than processed — so `partial_result` follows from a value that could not
    have lied about it, rather than from arithmetic this function performs a
    second time.

    `Scope` names the enrollments and no source. A corpus answer is about
    everything the Principal holds, and listing the sources would say which
    sources those are in a field a caller may treat as the authorized scope of
    the *result*; the enrollments are the grants the answer is composed from, and
    each of them is one the Principal already holds.
    """
    state = corpus.state()
    tokens: list[Limitation] = [Limitation.CORPUS_COVERS_ONLY_ENROLLED_SOURCES]
    if corpus.totals_are_per_enrollment_sums:
        tokens.append(Limitation.CORPUS_TOTALS_ARE_PER_ENROLLMENT_SUMS)
    return Disclosure(
        scope=Scope(
            enrollment_ids=tuple(
                sorted(
                    counts.enrollment_id
                    for counts in corpus.enrollments
                    if counts.enrollment_id is not None
                )
            )
        ),
        coverage=Coverage(
            state=state,
            eligible=corpus.stated_eligible,
            processed=corpus.stated_processed,
            quarantined=corpus.stated_quarantined,
            unsupported=corpus.stated_unsupported,
        ),
        freshness=Freshness(
            observed_at=corpus.observed_at, state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION
        ),
        trust=Trust(level=TrustLevel.SOURCE_BOUND_DERIVED, basis=trust_basis),
        limitations=(
            *sorted(token.value for token in dict.fromkeys(tokens)),
            *corpus.disclosed_limitations,
        ),
        partial_result=state in _PARTIAL_STATES,
        classification=Classification.PRIVATE_LOCAL,
        cloud_eligible=False,
    )


def with_corpus_caveat(disclosure: Disclosure) -> Disclosure:
    """The same envelope, saying that the answer does not span the Principal's corpus.

    **Additive, and additive in exactly two places.** One limitation token and
    `partial_result=True`. Nothing else moves: the coverage block still states
    what the enrollment's own coverage read measured, the scope still names only
    the enrollment the request named, and no count changes — because nothing here
    measured a wider scope and a number that appeared to would be an answer about
    rows the request never authorized.

    **Rebuilt through the constructor rather than copied.** `model_copy` skips
    validation, and the whole point of the change is to set `partial_result`
    truthfully; a copy that could carry a state and a flag which contradict each
    other would defeat `Disclosure._check_partial_is_truthful`, the one rule in
    the envelope that makes a complete-looking partial answer unconstructible.
    Every field is forwarded explicitly, and
    `test_the_caveat_forwards_every_field_the_envelope_has` compares the forwarded
    set against `Disclosure`'s own so that a field added later cannot be dropped
    here in silence.
    """
    return Disclosure(
        scope=disclosure.scope,
        coverage=disclosure.coverage,
        freshness=disclosure.freshness,
        trust=disclosure.trust,
        truncation=disclosure.truncation,
        limitations=tuple(
            sorted({*disclosure.limitations, Limitation.SEARCH_DOES_NOT_SPAN_THE_CORPUS.value})
        ),
        source_references=disclosure.source_references,
        unavailable_evidence=disclosure.unavailable_evidence,
        partial_result=True,
        classification=disclosure.classification,
        cloud_eligible=disclosure.cloud_eligible,
    )


def unavailable_disclosure(
    observed_at: datetime,
    *,
    unavailable_evidence: tuple[str, ...],
    trust_basis: tuple[str, ...],
    extra_limitations: tuple[Limitation, ...] = (),
) -> Disclosure:
    """The envelope for an answer whose scope could not be searched.

    **This is the envelope's half of "no empty-success for unavailable scope".**
    A capability that could not search returns rows it does not have, so the
    only thing distinguishing it from a genuine nothing is what the envelope
    says — and three fields say it here rather than one, because a caller that
    reads only one of them still cannot be misled:

    * `coverage.state` is `UNAVAILABLE`, which `domain.common.coverage` puts in
      the partition `INV-PKL-007` forbids collapsing into empty or complete;
    * `partial_result` is `True`, which `Disclosure` *requires* for that state —
      so an unavailable envelope claiming completeness is unconstructible rather
      than merely discouraged;
    * `unavailable_evidence` names what was not reached, from the caller's own
      closed vocabulary. The field is `tuple[str, ...]` and so is exactly the
      free-text shape `Limitation` exists to close, which is why every value
      that reaches it comes from a closed enum in the layer above and never from
      a message.

    `EVIDENCE_SCOPE_WAS_NOT_SEARCHED` is added unconditionally, so the same fact
    is also in the limitations a caller may already be rendering.
    """
    return Disclosure(
        scope=Scope(),
        coverage=Coverage(state=CoverageState.UNAVAILABLE),
        freshness=Freshness(
            observed_at=observed_at, state=FreshnessState.CURRENT_FOR_OBSERVED_VERSION
        ),
        trust=Trust(level=TrustLevel.SOURCE_ORIGINAL, basis=trust_basis),
        limitations=tuple(
            sorted(
                token.value
                for token in dict.fromkeys(
                    (*extra_limitations, Limitation.EVIDENCE_SCOPE_WAS_NOT_SEARCHED)
                )
            )
        ),
        unavailable_evidence=tuple(sorted(dict.fromkeys(unavailable_evidence))),
        partial_result=True,
        classification=Classification.PRIVATE_LOCAL,
        cloud_eligible=False,
    )
