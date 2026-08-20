"""Gate B v2 corpus: group isolation, unreadable fixtures, handwriting admission."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs import (
    AnalyzerOutput,
    CorpusPartition,
    CriticalErrorKind,
    GoldRegion,
    evaluate_gsqs,
)
from my_pa.application.goodnotes_gsqs_corpus import (
    FIXTURE_PRODUCTION_GOODNOTES,
    FIXTURE_SYNTHETIC_NON_PERSONAL_HANDWRITING,
    CorpusCase,
    LabelProvenance,
    ReviewState,
    SourceLayer,
    assign_partitions_by_group,
    box,
    freeze_manifest,
    operator_review_payload,
    prevent_partition_leakage,
    refuse_production_fixture,
)
from my_pa.application.goodnotes_gsqs_handwriting import (
    ALLOWED_SAMPLE_PHRASES,
    HANDWRITING_STATE,
    HandwritingAdmission,
    admit_handwriting,
    handwriting_catalog,
)
from my_pa.application.goodnotes_gsqs_harness import gold_as_output
from my_pa.application.goodnotes_gsqs_pages import synthetic_labeled_page_pdf
from my_pa.application.goodnotes_gsqs_v2 import v2_drafts
from my_pa.application.goodnotes_gsqs_v2_freeze import freeze_v2_corpus
from my_pa.domain.goodnotes.models import (
    GoodNotesNoteClass,
    GoodNotesSegmentKind,
    GoodNotesTranscriptionStatus,
)


def _case(
    case_id: str,
    partition: CorpusPartition,
    *,
    leakage_group_id: str,
    transcription: str = "same layout text",
) -> CorpusCase:
    region = GoldRegion(
        region_id="n",
        kind=GoodNotesSegmentKind.NOTE_UNIT,
        geometry=box(0.1, 0.2, 0.3, 0.1),
        transcription=transcription,
        transcription_status=GoodNotesTranscriptionStatus.CLEAR,
        primary_class=GoodNotesNoteClass.GENERAL,
    )
    return CorpusCase(
        case_id=case_id,
        corpus_version="gsqs-v2",
        content_sha256="a" * 64,
        renderer_name="gsqs-synthetic-pdf",
        renderer_version="1",
        render_profile_version="helvetica-times-italic-v1",
        fixture_classification="SYNTHETIC_NON_PERSONAL",
        provenance="t",
        regions=(region,),
        difficulty=("nominal",),
        scenario="single-note",
        adversarial=False,
        label_provenance=LabelProvenance.SYNTHETIC_DETERMINISTIC,
        review_state=ReviewState.APPROVED,
        partition=partition,
        page_bytes=b"%PDF",
        leakage_group_id=leakage_group_id,
    )


def test_v2_drafts_are_distinct_templates() -> None:
    drafts = v2_drafts()
    assert 60 <= len(drafts) <= 100
    notes = sum(
        1
        for draft in drafts
        for region in draft.regions
        if region.kind is GoodNotesSegmentKind.NOTE_UNIT
    )
    assert 100 <= notes <= 180
    assert len({draft.leakage_group_id for draft in drafts}) == len(drafts)
    scenarios = {draft.scenario for draft in drafts}
    for required in (
        "single-note",
        "multiple-notes",
        "context-only",
        "prompt-injection",
        "obscured-trap",
        "agenda-table",
        "visually-close",
        "one-candidate",
        "multi-tag",
        "no-tag",
    ):
        assert required in scenarios
    assert "UNREADABLE" not in " ".join(draft.case_id for draft in drafts).upper()


def test_group_level_partition_refuses_sibling_split() -> None:
    with pytest.raises(ValueError, match="leakage group"):
        prevent_partition_leakage(
            (
                _case("r1", CorpusPartition.B, leakage_group_id="lg-same"),
                _case("r2", CorpusPartition.C, leakage_group_id="lg-same"),
            )
        )
    prevent_partition_leakage(
        (
            _case("r1", CorpusPartition.B, leakage_group_id="lg-a"),
            _case("r2", CorpusPartition.C, leakage_group_id="lg-b"),
        )
    )


def test_transcription_or_case_id_does_not_change_leakage_group() -> None:
    left = _case("copy-1", CorpusPartition.B, leakage_group_id="lg-family", transcription="alpha")
    right = _case("copy-2", CorpusPartition.B, leakage_group_id="lg-family", transcription="beta")
    assert left.leakage_group_id == right.leakage_group_id
    prevent_partition_leakage((left, right))
    with pytest.raises(ValueError, match="leakage group"):
        prevent_partition_leakage(
            (
                left,
                _case(
                    "copy-2",
                    CorpusPartition.C,
                    leakage_group_id="lg-family",
                    transcription="beta",
                ),
            )
        )


def test_assign_partitions_by_group_covers_b_and_c() -> None:
    drafts = v2_drafts()
    assigned = assign_partitions_by_group(drafts)
    by_group: dict[str, set[CorpusPartition]] = {}
    for draft in drafts:
        if not draft.scoreable:
            continue
        by_group.setdefault(draft.leakage_group_id, set()).add(assigned[draft.case_id])
    assert all(len(parts) == 1 for parts in by_group.values())
    for partition in (CorpusPartition.B, CorpusPartition.C):
        selected = [draft for draft in drafts if assigned[draft.case_id] is partition]
        classes = {
            region.primary_class
            for draft in selected
            if draft.scoreable
            for region in draft.regions
            if region.kind is GoodNotesSegmentKind.NOTE_UNIT
        }
        statuses = {
            region.transcription_status
            for draft in selected
            if draft.scoreable
            for region in draft.regions
            if region.kind is GoodNotesSegmentKind.NOTE_UNIT
        }
        assert GoodNotesNoteClass.MEETING in classes
        assert GoodNotesTranscriptionStatus.UNREADABLE in statuses


def test_identical_region_geometry_does_not_span_partitions() -> None:
    drafts = v2_drafts()
    assigned = assign_partitions_by_group(drafts)
    by_signature: dict[tuple[object, ...], set[CorpusPartition]] = {}
    for draft in drafts:
        if not draft.scoreable:
            continue
        signature = tuple(
            (
                region.kind.value,
                region.geometry.x_min,
                region.geometry.y_min,
                region.geometry.width,
                region.geometry.height,
            )
            for region in draft.regions
        )
        by_signature.setdefault(signature, set()).add(assigned[draft.case_id])
    leaked = {sig: parts for sig, parts in by_signature.items() if len(parts) > 1}
    assert not leaked
    context_boxes = {
        draft.regions[0].geometry for draft in drafts if draft.scenario == "context-only"
    }
    assert len(context_boxes) == 3


def test_unreadable_pdf_has_no_status_label_and_is_deterministic() -> None:
    drafts = [draft for draft in v2_drafts() if draft.scenario == "obscured-trap"]
    assert drafts
    for draft in drafts:
        pdf = synthetic_labeled_page_pdf(
            case_id=draft.case_id,
            title=draft.title,
            regions=draft.regions,
            contrast=draft.contrast,
            style=draft.style,
        )
        assert b"UNREADABLE" not in pdf.upper()
        assert b"[UNREADABLE]" not in pdf
        note = next(
            region for region in draft.regions if region.kind is GoodNotesSegmentKind.NOTE_UNIT
        )
        assert note.transcription == ""
        assert note.transcription_status is GoodNotesTranscriptionStatus.UNREADABLE
        again = synthetic_labeled_page_pdf(
            case_id=draft.case_id,
            title=draft.title,
            regions=draft.regions,
            contrast=draft.contrast,
            style=draft.style,
        )
        assert pdf == again


def test_freeze_v2_is_reproducible_and_group_isolated() -> None:
    first_cases, first_manifest = freeze_v2_corpus()
    second_cases, second_manifest = freeze_v2_corpus()
    assert first_manifest.manifest_digest == second_manifest.manifest_digest
    assert first_manifest.corpus_version == "gsqs-v2"
    assert first_manifest.approval_status == "READY_FOR_OPERATOR_REVIEW"
    payload = operator_review_payload(first_cases, first_manifest)
    assert payload["FIXED_LABELED_CORPUS_APPROVED"] is False
    assert payload["b0_suitable"] is False
    assert payload["controlled_handwriting_present"] is False
    assert payload["leakage_group_intersections_empty"] is True
    groups = first_manifest.leakage_groups
    assert _group_intersections_empty(groups)
    freeze_manifest(first_cases, generator_version="x", approval_status="READY_FOR_OPERATOR_REVIEW")
    assert {case.content_sha256 for case in first_cases} == {
        case.content_sha256 for case in second_cases
    }


def _group_intersections_empty(groups: dict[str, object]) -> bool:
    buckets: dict[str, set[str]] = {"A": set(), "B": set(), "C": set()}
    for group_id, body in groups.items():
        assert isinstance(body, dict)
        buckets[str(body["partition"])].add(group_id)
    return (
        not (buckets["A"] & buckets["B"])
        and not (buckets["A"] & buckets["C"])
        and not (buckets["B"] & buckets["C"])
    )


def test_committed_v2_operator_package_matches_freeze() -> None:
    cases, manifest = freeze_v2_corpus()
    review = json.loads(Path("ops/goodnotes/gsqs/v2/operator_review.json").read_text())
    payload = operator_review_payload(cases, manifest)
    assert review["manifest_digest"] == manifest.manifest_digest
    assert review["page_count"] == payload["page_count"]
    assert review["NOTE_UNIT_count"] == payload["NOTE_UNIT_count"]
    assert review["partitions"] == payload["partitions"]
    assert review["controlled_handwriting_present"] is False
    review_md = Path("ops/goodnotes/gsqs/v2/OPERATOR_REVIEW.md").read_text()
    assert manifest.manifest_digest in review_md
    index = json.loads(Path("ops/goodnotes/gsqs/v2/case_index.json").read_text())
    assert index["manifest_digest"] == manifest.manifest_digest
    assert {item["case_id"] for item in index["cases"]} == {case.case_id for case in cases}


def test_handwriting_admission_refuses_production_and_stores_no_samples() -> None:
    assert handwriting_catalog() == ()
    assert HANDWRITING_STATE == "READY_FOR_OPERATOR_INPUT"
    assert "Review agenda Monday" in ALLOWED_SAMPLE_PHRASES
    with pytest.raises(ValueError, match="production/live"):
        refuse_production_fixture(FIXTURE_PRODUCTION_GOODNOTES)
    with pytest.raises(ValueError, match="production/live"):
        admit_handwriting(
            HandwritingAdmission(
                case_id="hw-1",
                artifact_sha256="a" * 64,
                external_ref="private://sample",
                fixture_classification=FIXTURE_PRODUCTION_GOODNOTES,
                phrases=ALLOWED_SAMPLE_PHRASES[:1],
                style="print",
                leakage_group_id="lg-hw-print",
                review_state=ReviewState.PENDING,
                partition=None,
            )
        )
    admitted = admit_handwriting(
        HandwritingAdmission(
            case_id="hw-1",
            artifact_sha256="ab" * 32,
            external_ref="private://sample",
            fixture_classification=FIXTURE_SYNTHETIC_NON_PERSONAL_HANDWRITING,
            phrases=ALLOWED_SAMPLE_PHRASES[:1],
            style="print",
            leakage_group_id="lg-hw-print",
            review_state=ReviewState.PENDING,
            partition=None,
        )
    )
    assert admitted.source_layer is SourceLayer.CONTROLLED_HANDWRITING
    assert admitted.artifact_sha256


def test_v2_unreadable_perfect_output_and_fabrication_gate() -> None:
    cases, _manifest = freeze_v2_corpus()
    case = next(item for item in cases if item.scenario == "obscured-trap" and item.scoreable)
    perfect = gold_as_output(case, analyzer_name="gold-replay", analyzer_version="1")
    ok = evaluate_gsqs(((case.case_id, case.regions),), (perfect,))
    assert ok.measurement_valid is True
    assert not any(
        item.kind is CriticalErrorKind.FABRICATED_UNREADABLE for item in ok.critical_errors
    )
    guessed = tuple(
        replace(segment, transcription="guessed the scribble")
        if segment.kind is GoodNotesSegmentKind.NOTE_UNIT
        else segment
        for segment in perfect.segments
    )
    bad = evaluate_gsqs(
        ((case.case_id, case.regions),),
        (
            AnalyzerOutput(
                case_id=case.case_id,
                schema_version=perfect.schema_version,
                analyzer_name=perfect.analyzer_name,
                analyzer_version=perfect.analyzer_version,
                segments=guessed,
                corpus_version=case.corpus_version,
            ),
        ),
    )
    assert any(item.kind is CriticalErrorKind.FABRICATED_UNREADABLE for item in bad.critical_errors)
