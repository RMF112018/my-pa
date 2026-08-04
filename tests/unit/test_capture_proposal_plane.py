"""The deterministic units of the proposal plane, without a database.

Four subjects, and every one of them is a place where a wrong answer is silent
rather than loud: span arithmetic that quotes the wrong characters, a
line/column pair that disagrees with the offsets beside it, a replay key that
does not change when the configuration does, and a "missing required fields"
list that reports a partial proposal as complete.

**Every assertion here is on a non-empty result.** Where the subject is an
absence — no missing fields, no fault — the same test produces a non-empty case
beside it, because a zero with nothing to compare it against is satisfied by a
function that returns nothing at all.
"""

from __future__ import annotations

import hashlib

import pytest

from my_pa.domain.capture.classification import (
    CaptureClassification,
    CaptureEntityMention,
    CaptureLabel,
    ClassificationError,
    EntityType,
    ResolutionState,
)
from my_pa.domain.capture.pipeline import (
    PIPELINE_VERSION,
    PipelineError,
    PipelineStage,
    ProcessingState,
    stage_config_digest,
    stage_identity,
)
from my_pa.domain.capture.proposal import (
    Proposal,
    ProposalError,
    ProposalField,
    ProposalMethod,
    ProposalQuarantineReason,
    ProposalState,
    ProposalType,
    RiskClass,
    missing_required_fields,
    required_fields_for,
)
from my_pa.domain.capture.span import (
    OffsetBasis,
    SourceSpan,
    SpanError,
    SpanRole,
    line_column_of,
    quote_of,
    quoted_digest_of,
)
from my_pa.infrastructure.persistence.proposals import OffsetMapping

VERSION = "capver_wp7span0001aa"
OTHER_VERSION = "capver_wp7span0002bb"
PROPOSAL = "prop_wp7prop0001aaaa"
SPAN = "span_wp7span0001aaaa"
CLASSIFICATION = "ccls_wp7class001aaa"
MENTION = "men_wp7mention01aaa"

TEXT = "Send the RFI-0421 response by Friday.\nThe buyout ran to $12,500.00."


def test_a_quote_is_the_code_points_between_the_offsets() -> None:
    assert quote_of(TEXT, start_offset=9, end_offset=17) == "RFI-0421"


def test_a_quote_past_the_end_is_refused_rather_than_shortened() -> None:
    """A Python slice clamps; a span that clamped would quote whatever was there.

    The control is in the same test: the in-range slice one character shorter
    returns text, so the refusal is about the bound rather than about the call
    failing generally.
    """
    assert quote_of(TEXT, start_offset=len(TEXT) - 1, end_offset=len(TEXT)) == "."
    with pytest.raises(SpanError):
        quote_of(TEXT, start_offset=len(TEXT) - 1, end_offset=len(TEXT) + 1)


@pytest.mark.parametrize(
    ("start", "end"),
    [(-1, 4), (4, 4), (5, 4)],
)
def test_a_span_that_covers_nothing_is_refused(start: int, end: int) -> None:
    with pytest.raises(SpanError):
        quote_of(TEXT, start_offset=start, end_offset=end)


def test_a_quoted_digest_is_the_sha256_of_the_quote() -> None:
    digest = quoted_digest_of(TEXT, start_offset=9, end_offset=17)
    assert digest == hashlib.sha256(b"RFI-0421").hexdigest()
    assert len(digest) == 64


def test_line_and_column_are_one_based_and_count_lines() -> None:
    assert line_column_of(TEXT, 0) == (1, 1)
    assert line_column_of(TEXT, 9) == (1, 10)
    # The character after the newline opens line two at column one.
    assert line_column_of(TEXT, TEXT.index("The buyout")) == (2, 1)


def test_an_offset_outside_the_text_has_no_line_or_column() -> None:
    assert line_column_of(TEXT, len(TEXT)) == (2, 30)
    with pytest.raises(SpanError):
        line_column_of(TEXT, len(TEXT) + 1)


def test_a_span_built_over_a_text_re_derives_against_it() -> None:
    span = SourceSpan.over(TEXT, version_id=VERSION, start_offset=9, end_offset=17)
    assert span.character_count == 8
    assert span.offset_basis is OffsetBasis.UNICODE_CODE_POINT_V1
    assert span.span_role is SpanRole.DIRECT
    assert span.re_derives_against(TEXT)


def test_a_span_does_not_re_derive_against_different_text() -> None:
    """The `QC-AC-011` failure, and its control in the same test."""
    span = SourceSpan.over(TEXT, version_id=VERSION, start_offset=9, end_offset=17)
    assert span.re_derives_against(TEXT)
    assert not span.re_derives_against(TEXT.replace("RFI-0421", "RFI-9999"))


def test_a_span_whose_offsets_leave_the_text_does_not_re_derive() -> None:
    span = SourceSpan.over(TEXT, version_id=VERSION, start_offset=9, end_offset=17)
    assert not span.re_derives_against("short")


def test_a_span_spanning_a_newline_carries_both_lines() -> None:
    start = TEXT.index("Friday")
    end = TEXT.index("buyout") + len("buyout")
    span = SourceSpan.over(TEXT, version_id=VERSION, start_offset=start, end_offset=end)
    assert span.line_start == 1
    assert span.line_end == 2
    assert span.re_derives_against(TEXT)


def test_a_hand_built_span_with_a_wrong_digest_is_storable_and_fails_validation() -> None:
    """The fault the persistence layer must be able to represent.

    A constructor that recomputed the digest would make the `QC-AC-011` failure
    unreachable and the criterion unprovable, so it does not.
    """
    span = SourceSpan(
        version_id=VERSION,
        start_offset=9,
        end_offset=17,
        offset_basis=OffsetBasis.UNICODE_CODE_POINT_V1,
        line_start=1,
        column_start=10,
        line_end=1,
        column_end=18,
        quoted_text_sha256="0" * 64,
        span_role=SpanRole.DIRECT,
    )
    assert span.quoted_text_sha256 == "0" * 64
    assert not span.re_derives_against(TEXT)


def test_a_span_with_a_line_that_ends_before_it_starts_is_refused() -> None:
    with pytest.raises(SpanError):
        SourceSpan(
            version_id=VERSION,
            start_offset=0,
            end_offset=4,
            offset_basis=OffsetBasis.UNICODE_CODE_POINT_V1,
            line_start=2,
            column_start=5,
            line_end=1,
            column_end=1,
            quoted_text_sha256="0" * 64,
            span_role=SpanRole.DIRECT,
        )


def test_a_span_names_a_capture_version_and_not_a_source_version() -> None:
    with pytest.raises(Exception, match="capver"):
        SourceSpan.over(TEXT, version_id="ver_sourceversion01", start_offset=0, end_offset=4)


def test_a_stage_identity_is_the_specifications_own_four_part_digest() -> None:
    config = stage_config_digest("matchers-v1")
    identity = stage_identity(
        version_id=VERSION, stage=PipelineStage.SEGMENT, stage_config_hash=config
    )
    expected = hashlib.sha256(
        "|".join((VERSION, "segment", PIPELINE_VERSION, config)).encode("utf-8")
    ).hexdigest()
    assert identity == expected


@pytest.mark.parametrize("stage", list(PipelineStage))
def test_every_stage_has_its_own_identity_for_one_version(stage: PipelineStage) -> None:
    config = stage_config_digest("matchers-v1")
    identity = stage_identity(version_id=VERSION, stage=stage, stage_config_hash=config)
    others = {
        stage_identity(version_id=VERSION, stage=other, stage_config_hash=config)
        for other in PipelineStage
        if other is not stage
    }
    assert len(others) == len(PipelineStage) - 1
    assert identity not in others


def test_a_changed_pipeline_version_creates_a_new_attempt() -> None:
    config = stage_config_digest("matchers-v1")
    first = stage_identity(
        version_id=VERSION, stage=PipelineStage.VALIDATE, stage_config_hash=config
    )
    second = stage_identity(
        version_id=VERSION,
        stage=PipelineStage.VALIDATE,
        pipeline_version="capture-pipeline-v2",
        stage_config_hash=config,
    )
    assert first != second


def test_a_changed_stage_configuration_creates_a_new_attempt() -> None:
    first = stage_identity(
        version_id=VERSION,
        stage=PipelineStage.VALIDATE,
        stage_config_hash=stage_config_digest("matchers-v1"),
    )
    second = stage_identity(
        version_id=VERSION,
        stage=PipelineStage.VALIDATE,
        stage_config_hash=stage_config_digest("matchers-v2"),
    )
    assert first != second


def test_a_stage_configuration_cannot_be_forged_by_running_parts_together() -> None:
    assert stage_config_digest("ab", "c") != stage_config_digest("a", "bc")


def test_a_stage_identity_refuses_an_unversioned_configuration() -> None:
    with pytest.raises(PipelineError):
        stage_identity(
            version_id=VERSION, stage=PipelineStage.VALIDATE, stage_config_hash="not-a-digest"
        )


def test_a_stage_identity_refuses_a_version_of_another_plane() -> None:
    with pytest.raises(Exception, match="capver"):
        stage_identity(
            version_id="enr_enrollment0001a",
            stage=PipelineStage.VALIDATE,
            stage_config_hash=stage_config_digest("matchers-v1"),
        )


def test_the_processing_states_are_the_canonical_seven() -> None:
    assert {state.value for state in ProcessingState} == {
        "waiting",
        "running",
        "partial",
        "retryable_failure",
        "permanent_failure",
        "policy_denied",
        "complete",
    }


def test_the_proposal_states_are_the_canonical_nine() -> None:
    assert {state.value for state in ProposalState} == {
        "proposed",
        "needs_review",
        "accepted",
        "corrected_accepted",
        "rejected",
        "deferred",
        "unresolved",
        "superseded",
        "invalidated",
    }


def test_a_deterministic_cue_proposal_names_the_fields_it_could_not_fill() -> None:
    """The honesty requirement, with its control beside it.

    A proposal that filled every required field reports none missing; the one a
    cue extractor actually produces reports three. The first assertion alone
    would pass against a function that always returned the empty tuple.
    """
    complete = missing_required_fields(ProposalType.COMMITMENT, frozenset(ProposalField))
    partial = missing_required_fields(
        ProposalType.COMMITMENT,
        frozenset({ProposalField.ACTION, ProposalField.DUE_CONDITION}),
    )
    assert complete == ()
    assert partial == (ProposalField.ACTOR, ProposalField.COUNTERPARTY, ProposalField.STATUS)


@pytest.mark.parametrize("proposal_type", list(ProposalType))
def test_every_proposal_type_requires_the_same_five_fields(proposal_type: ProposalType) -> None:
    assert required_fields_for(proposal_type) == frozenset(ProposalField)


def test_missing_fields_are_sorted_so_two_runs_record_one_array() -> None:
    first = missing_required_fields(ProposalType.TASK, frozenset({ProposalField.ACTION}))
    second = missing_required_fields(ProposalType.TASK, frozenset({ProposalField.ACTION}))
    assert first == second
    assert [field.value for field in first] == sorted(field.value for field in first)


def _proposal(**overrides: object) -> Proposal:
    values: dict[str, object] = {
        "proposal_id": PROPOSAL,
        "version_id": VERSION,
        "proposal_type": ProposalType.COMMITMENT,
        "state": ProposalState.PROPOSED,
        "risk_class": RiskClass.LOW,
        "method": ProposalMethod.DETERMINISTIC_RULE,
        "method_version": "cues-v1",
        "schema_version": "commitment-v1",
    }
    values.update(overrides)
    return Proposal(**values)  # type: ignore[arg-type]


def test_a_proposal_carries_its_method_and_its_versions() -> None:
    proposal = _proposal(missing_fields=(ProposalField.ACTOR,))
    assert proposal.method is ProposalMethod.DETERMINISTIC_RULE
    assert proposal.missing_fields == (ProposalField.ACTOR,)
    assert proposal.quarantine_reason is None


def test_an_invalidated_proposal_must_record_why() -> None:
    with pytest.raises(ProposalError):
        _proposal(state=ProposalState.INVALIDATED)


def test_a_proposal_that_is_not_invalidated_may_not_carry_a_reason() -> None:
    with pytest.raises(ProposalError):
        _proposal(quarantine_reason=ProposalQuarantineReason.SPAN_TEXT_DOES_NOT_RE_DERIVE)


def test_an_invalidated_proposal_with_a_reason_is_representable() -> None:
    proposal = _proposal(
        state=ProposalState.INVALIDATED,
        quarantine_reason=ProposalQuarantineReason.SPAN_CITES_ANOTHER_VERSION,
    )
    assert proposal.quarantine_reason is ProposalQuarantineReason.SPAN_CITES_ANOTHER_VERSION


def test_a_proposal_cannot_report_a_field_its_type_does_not_require() -> None:
    with pytest.raises(ProposalError):
        _proposal(missing_fields=(ProposalField.ACTOR, ProposalField.ACTOR))


def test_an_accepted_record_is_named_by_both_halves_or_neither() -> None:
    with pytest.raises(ProposalError):
        _proposal(accepted_record_type="assertion")
    attached = _proposal(accepted_record_type="assertion", accepted_record_id="kn_abcd12345678")
    assert attached.accepted_record_id == "kn_abcd12345678"


def test_a_proposals_repr_does_not_carry_its_normalized_value() -> None:
    proposal = _proposal(normalized_value="12500.00")
    assert "12500.00" not in repr(proposal)


def test_a_classification_carries_the_span_it_was_derived_from() -> None:
    classification = CaptureClassification(
        classification_id=CLASSIFICATION,
        version_id=VERSION,
        span_id=SPAN,
        scheme="deterministic_cues",
        scheme_version="v1",
        label=CaptureLabel.FINANCIAL_MENTION,
        rule="currency_amount",
        rule_version="v1",
    )
    assert classification.label is CaptureLabel.FINANCIAL_MENTION
    assert classification.span_id == SPAN


def test_a_classification_refuses_an_unbounded_rule_name() -> None:
    with pytest.raises(ClassificationError):
        CaptureClassification(
            classification_id=CLASSIFICATION,
            version_id=VERSION,
            span_id=SPAN,
            scheme="deterministic_cues",
            scheme_version="v1",
            label=CaptureLabel.DATE_MENTION,
            rule="r" * 65,
            rule_version="v1",
        )


@pytest.mark.parametrize("entity_type", list(EntityType))
def test_a_mention_is_always_unresolved(entity_type: EntityType) -> None:
    mention = CaptureEntityMention(
        mention_id=MENTION, version_id=VERSION, span_id=SPAN, entity_type=entity_type
    )
    assert mention.resolution_state is ResolutionState.UNRESOLVED


def test_the_deterministic_entity_types_exclude_people_and_organisations() -> None:
    assert {entity.value for entity in EntityType} == {"document", "project", "url"}


def test_an_offset_mapping_reverses_every_offset_it_covers() -> None:
    """A `\\r\\n` document normalized to `\\n`: two runs, one shift.

    "a\\r\\nb" becomes "a\\nb", so normalized offset 2 is original offset 3.
    """
    mapping = OffsetMapping(normalized_starts=(0, 2), original_starts=(0, 3), lengths=(2, 1))
    assert [mapping.original_offset_of(offset) for offset in range(3)] == [0, 1, 3]


def test_an_offset_mapping_refuses_an_offset_it_does_not_cover() -> None:
    mapping = OffsetMapping(normalized_starts=(0,), original_starts=(0,), lengths=(3,))
    assert mapping.original_offset_of(2) == 2
    with pytest.raises(ValueError, match="outside this mapping"):
        mapping.original_offset_of(3)


@pytest.mark.parametrize(
    ("starts", "origins", "lengths"),
    [
        ((0, 2), (0, 3), (2,)),
        ((), (), ()),
        ((0, 1), (0, 1), (3, 1)),
        ((0,), (0,), (0,)),
    ],
)
def test_a_partial_or_overlapping_offset_mapping_is_not_representable(
    starts: tuple[int, ...], origins: tuple[int, ...], lengths: tuple[int, ...]
) -> None:
    with pytest.raises(ValueError, match="mapping"):
        OffsetMapping(normalized_starts=starts, original_starts=origins, lengths=lengths)
