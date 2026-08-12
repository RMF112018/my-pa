"""The shapes `Reveal`'s constructor refuses — and the one it does not.

The three-way distinction WP-09 rests on is only worth having if it cannot be
faked, and the constructor makes most of it unfakeable: a reveal claiming
evidence cannot be built over nothing, a `no_evidence` reveal cannot carry rows,
and a gap cannot be attached to a scope that was in fact searched to completion.
Each rule below is one of those, and each test is written so that removing the
rule reddens it — which is the property a guard has to have to be worth its
lines.

**One shape is not refused here, and nothing in this file tests it:** an
unsearched scope with no spans *can* be built as `no_evidence`, because
`__post_init__` has no rule tying that state to completed derivation. The
invariant is enforced a layer out, by
`infrastructure.persistence.reveal._state_and_gap`, which every assembly path in
this build goes through; neither this file nor `RevealView` would catch a path
that did not.

Of the rules that *are* enforced here, the last listed above matters most and is
the least obvious: a `DERIVATION_HAS_NOT_COMPLETED`
gap must be a *measurement of the versions in hand*, not a label. Without it, a
future assembly path could attach the gap to a fully-derived scope and report
"we could not search" about something it had searched — the mirror image of the
empty-success defect, and just as dishonest.

Every value here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.domain.capture.pipeline import ProcessingState
from my_pa.domain.capture.reveal import (
    EvidenceGap,
    EvidenceState,
    Reveal,
    RevealedSpan,
    RevealedVersion,
    RevealError,
    RevealSubjectKind,
)
from my_pa.domain.capture.span import OffsetBasis, SpanRole

WHEN = datetime(2026, 8, 10, 12, 0, tzinfo=UTC)
CAPTURE = "cap_aaaa0001aaaa0001"
VERSION = "capver_aaaa0001aaaa0001"


def _version(*, derived: bool) -> RevealedVersion:
    return RevealedVersion(
        version_id=VERSION,
        capture_id=CAPTURE,
        version_number=1,
        is_current=True,
        content_sha256="a" * 64,
        recorded_at=WHEN,
        derivation_state=ProcessingState.COMPLETE if derived else None,
    )


def _span() -> RevealedSpan:
    return RevealedSpan(
        span_id="span_aaaa0001aaaa0001",
        version_id=VERSION,
        start_offset=0,
        end_offset=5,
        offset_basis=OffsetBasis.UNICODE_CODE_POINT_V1,
        line_start=1,
        column_start=1,
        line_end=1,
        column_end=6,
        quoted_text_sha256="b" * 64,
        span_role=SpanRole.DIRECT,
    )


def _reveal(**overrides: object) -> Reveal:
    fields: dict[str, object] = {
        "subject_id": CAPTURE,
        "subject_kind": RevealSubjectKind.CAPTURE,
        "state": EvidenceState.NO_EVIDENCE,
        "capture_id": CAPTURE,
        "versions": (_version(derived=True),),
    }
    fields.update(overrides)
    return Reveal(**fields)  # type: ignore[arg-type]


def test_a_searched_scope_that_found_nothing_is_constructible() -> None:
    """The control. Without it every refusal below could be refusing everything."""
    answer = _reveal()
    assert answer.state is EvidenceState.NO_EVIDENCE
    assert answer.gap is None
    assert answer.versions_with_completed_derivation == 1


def test_an_unavailable_reveal_states_a_gap_and_no_other_reveal_does() -> None:
    with pytest.raises(RevealError, match="states its gap"):
        _reveal(state=EvidenceState.UNAVAILABLE)
    with pytest.raises(RevealError, match="states its gap"):
        _reveal(gap=EvidenceGap.DERIVATION_HAS_NOT_COMPLETED)


def test_a_reveal_claiming_evidence_carries_at_least_one_span() -> None:
    with pytest.raises(RevealError, match="at least one span"):
        _reveal(state=EvidenceState.EVIDENCE)


def test_a_reveal_claiming_no_evidence_cannot_carry_any() -> None:
    with pytest.raises(RevealError, match="carries none"):
        _reveal(state=EvidenceState.NO_EVIDENCE, spans=(_span(),))


def test_an_uncovered_subject_kind_is_read_about_rather_than_read() -> None:
    """A plane this build cannot traverse yields no rows, so it may hold none."""
    with pytest.raises(RevealError, match="read about, not read"):
        Reveal(
            subject_id="kn_aaaa0001aaaa0001",
            subject_kind=None,
            state=EvidenceState.UNAVAILABLE,
            gap=EvidenceGap.SUBJECT_KIND_NOT_COVERED,
            versions=(_version(derived=True),),
        )


def test_an_incomplete_derivation_gap_names_a_version_that_is_incomplete() -> None:
    """**The mirror of the empty-success defect**, and it is refused too.

    A gap attached to a scope every version of which finished deriving would be
    "we could not search" said about something that was searched. The rule makes
    the gap a measurement of `versions`, so it cannot be a label a caller picks.
    """
    with pytest.raises(RevealError, match="names the version that is incomplete"):
        _reveal(
            state=EvidenceState.UNAVAILABLE,
            gap=EvidenceGap.DERIVATION_HAS_NOT_COMPLETED,
            versions=(_version(derived=True),),
        )
    # And the same gap over a version that genuinely did not finish is accepted,
    # so the rule refuses the false claim rather than the token.
    honest = _reveal(
        state=EvidenceState.UNAVAILABLE,
        gap=EvidenceGap.DERIVATION_HAS_NOT_COMPLETED,
        versions=(_version(derived=False),),
    )
    assert honest.versions_with_completed_derivation == 0
