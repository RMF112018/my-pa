"""Full gold-truth digest binding: every score-relevant field changes identity."""

from __future__ import annotations

from my_pa.application.goodnotes_gsqs import Confidence, CorpusPartition, GoldRegion
from my_pa.application.goodnotes_gsqs_corpus import (
    CorpusCase,
    LabelProvenance,
    ReviewState,
    SourceLayer,
    box,
    candidate,
    canonical_dumps,
    case_digest,
    freeze_manifest,
    gold_region_payload,
    mutate_case,
    mutate_confidence,
    mutate_geometry,
    mutate_region,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesNoteClass,
    GoodNotesSegmentKind,
    GoodNotesTranscriptionStatus,
)


def _gold(**overrides: object) -> GoldRegion:
    base = GoldRegion(
        region_id="note-a",
        kind=GoodNotesSegmentKind.NOTE_UNIT,
        geometry=box(0.10, 0.40, 0.40, 0.12),
        transcription="synthetic follow up monday",
        transcription_status=GoodNotesTranscriptionStatus.CLEAR,
        primary_class=GoodNotesNoteClass.MEETING,
        candidate_tags=("FOLLOW_UP_CANDIDATE",),
        ranked_candidates=(candidate(1, "alpha"), candidate(2, "beta")),
        no_association_correct=False,
        reference_confidence=Confidence(0.9, 0.9, 0.85, 0.8),
        contains_embedded_instructions=False,
    )
    return mutate_region(base, **overrides)


def _case(**overrides: object) -> CorpusCase:
    base = CorpusCase(
        case_id="case-a",
        corpus_version="gsqs-v2",
        content_sha256="a" * 64,
        renderer_name="gsqs-synthetic-pdf",
        renderer_version="1",
        render_profile_version="helvetica-times-italic-v1",
        fixture_classification="SYNTHETIC_NON_PERSONAL",
        provenance="deterministic:case-a",
        regions=(_gold(),),
        difficulty=("nominal",),
        scenario="single-note",
        adversarial=False,
        label_provenance=LabelProvenance.SYNTHETIC_DETERMINISTIC,
        review_state=ReviewState.APPROVED,
        partition=CorpusPartition.B,
        page_bytes=b"%PDF",
        leakage_group_id="lg-single-general-clear-block",
        source_layer=SourceLayer.SYNTHETIC_REGRESSION,
    )
    return mutate_case(base, **overrides)


def _digest_pair(before: CorpusCase, after: CorpusCase) -> tuple[str, str, str, str]:
    first = freeze_manifest(
        (before,), generator_version="test", approval_status="READY_FOR_OPERATOR_REVIEW"
    )
    second = freeze_manifest(
        (after,), generator_version="test", approval_status="READY_FOR_OPERATOR_REVIEW"
    )
    return case_digest(before), case_digest(after), first.manifest_digest, second.manifest_digest


def test_canonical_serialization_is_order_stable() -> None:
    region = _gold()
    left = gold_region_payload(region)
    right = dict(reversed(list(left.items())))
    assert canonical_dumps(left) == canonical_dumps(right)
    assert case_digest(_case()) == case_digest(_case())


def test_score_relevant_field_mutations_change_case_and_manifest_digest() -> None:
    original = _case()
    region = original.regions[0]
    assert region.reference_confidence is not None
    mutations = {
        "x_min": mutate_case(
            original,
            regions=(mutate_region(region, geometry=mutate_geometry(region.geometry, x_min=0.11)),),
        ),
        "y_min": mutate_case(
            original,
            regions=(mutate_region(region, geometry=mutate_geometry(region.geometry, y_min=0.41)),),
        ),
        "width": mutate_case(
            original,
            regions=(mutate_region(region, geometry=mutate_geometry(region.geometry, width=0.41)),),
        ),
        "height": mutate_case(
            original,
            regions=(
                mutate_region(region, geometry=mutate_geometry(region.geometry, height=0.13)),
            ),
        ),
        "transcription": mutate_case(
            original, regions=(mutate_region(region, transcription="different text"),)
        ),
        "transcription_status": mutate_case(
            original,
            regions=(
                mutate_region(region, transcription_status=GoodNotesTranscriptionStatus.UNCERTAIN),
            ),
        ),
        "primary_class": mutate_case(
            original, regions=(mutate_region(region, primary_class=GoodNotesNoteClass.PROJECT),)
        ),
        "candidate_tags": mutate_case(
            original, regions=(mutate_region(region, candidate_tags=("TASK_CANDIDATE",)),)
        ),
        "ranked_candidates": mutate_case(
            original,
            regions=(
                mutate_region(
                    region, ranked_candidates=(candidate(1, "beta"), candidate(2, "alpha"))
                ),
            ),
        ),
        "no_association_correct": mutate_case(
            original, regions=(mutate_region(region, no_association_correct=True),)
        ),
        "reference_confidence": mutate_case(
            original,
            regions=(
                mutate_region(
                    region,
                    reference_confidence=mutate_confidence(
                        region.reference_confidence, transcription=0.1
                    ),
                ),
            ),
        ),
        "contains_embedded_instructions": mutate_case(
            original, regions=(mutate_region(region, contains_embedded_instructions=True),)
        ),
        "adversarial": mutate_case(original, adversarial=True),
        "difficulty": mutate_case(original, difficulty=("dense",)),
        "review_state": mutate_case(original, review_state=ReviewState.PENDING),
        "label_provenance": mutate_case(
            original, label_provenance=LabelProvenance.OPERATOR_ADJUDICATED
        ),
        "scenario": mutate_case(original, scenario="dense"),
        "leakage_group_id": mutate_case(original, leakage_group_id="lg-other"),
    }
    for name, mutated in mutations.items():
        case_before, case_after, manifest_before, manifest_after = _digest_pair(original, mutated)
        assert case_before != case_after, name
        assert manifest_before != manifest_after, name
        assert mutated.content_sha256 == original.content_sha256
