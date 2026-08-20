"""Gate B corpus freeze, partitions, leakage, and operator-review payload."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs import CorpusPartition, GoldRegion
from my_pa.application.goodnotes_gsqs_corpus import (
    LabelProvenance,
    ReviewState,
    assign_partitions,
    box,
    case_signature,
    freeze_manifest,
    operator_review_payload,
    prevent_partition_leakage,
)
from my_pa.application.goodnotes_gsqs_v1 import v1_drafts
from my_pa.application.goodnotes_gsqs_v1_freeze import (
    SYNTHETIC_RENDERER_NAME,
    freeze_v1_corpus,
)
from my_pa.domain.goodnotes.models import (
    GoodNotesNoteClass,
    GoodNotesSegmentKind,
    GoodNotesTranscriptionStatus,
)


def test_v1_drafts_cover_required_scenarios_and_size() -> None:
    drafts = v1_drafts()
    assert 60 <= len(drafts) <= 100
    notes = sum(
        1
        for draft in drafts
        for region in draft.regions
        if region.kind is GoodNotesSegmentKind.NOTE_UNIT
    )
    assert 100 <= notes <= 180
    scenarios = {draft.scenario for draft in drafts}
    for required in (
        "single-note",
        "multiple-notes",
        "context-only",
        "prompt-injection",
        "unreadable-trap",
        "agenda-table",
        "visually-close",
        "dense",
        "arrow-leader",
        "crossed-out",
        "low-contrast",
        "ambiguous-grouping",
    ):
        assert required in scenarios
    assert any(draft.review_state is ReviewState.AMBIGUOUS_EXCLUDE for draft in drafts)
    assert all(
        draft.label_provenance is LabelProvenance.SYNTHETIC_DETERMINISTIC for draft in drafts
    )


def test_assign_partitions_puts_classes_and_statuses_in_b_and_c() -> None:
    drafts = v1_drafts()
    assigned = assign_partitions(drafts)
    assert set(assigned) == {draft.case_id for draft in drafts}


def test_partition_leakage_is_refused() -> None:
    region = GoldRegion(
        region_id="n",
        kind=GoodNotesSegmentKind.NOTE_UNIT,
        geometry=box(0.1, 0.2, 0.3, 0.1),
        transcription="same",
        transcription_status=GoodNotesTranscriptionStatus.CLEAR,
        primary_class=GoodNotesNoteClass.GENERAL,
    )
    from my_pa.application.goodnotes_gsqs_corpus import CorpusCase

    def _case(case_id: str, partition: CorpusPartition) -> CorpusCase:
        return CorpusCase(
            case_id=case_id,
            corpus_version="gsqs-v1",
            content_sha256="a" * 64,
            renderer_name="pypdfium2",
            renderer_version="1",
            render_profile_version="pdfium-normalized-v1",
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
            leakage_group_id="lg-same-template",
        )

    with pytest.raises(ValueError, match="leakage group"):
        prevent_partition_leakage((_case("a", CorpusPartition.A), _case("b", CorpusPartition.B)))
    assert case_signature((region,), "single-note") == case_signature((region,), "single-note")


def test_freeze_v1_is_reproducible_and_digest_bound() -> None:
    first_cases, first_manifest = freeze_v1_corpus()
    second_cases, second_manifest = freeze_v1_corpus()
    assert first_manifest.manifest_digest == second_manifest.manifest_digest
    assert first_manifest.frozen is True
    assert first_manifest.approval_status == "REJECT_FOR_B0"
    assert first_manifest.corpus_version == "gsqs-v1"
    assert {case.content_sha256 for case in first_cases} == {
        case.content_sha256 for case in second_cases
    }
    assert all(len(case.content_sha256) == 64 for case in first_cases)
    assert all(case.page_bytes.startswith(b"%PDF") for case in first_cases)
    assert all(case.renderer_name == SYNTHETIC_RENDERER_NAME for case in first_cases)
    assert first_manifest.note_unit_count >= 100
    review = operator_review_payload(first_cases, first_manifest)
    assert review["FIXED_LABELED_CORPUS_APPROVED"] is False
    assert review["page_count"] == len(first_cases)
    assert "approve" in review["operator_actions"]
    freeze_manifest(first_cases, generator_version="x", approval_status="READY_FOR_OPERATOR_REVIEW")


def test_committed_operator_package_matches_freeze() -> None:
    cases, manifest = freeze_v1_corpus()
    review = json.loads(Path("ops/goodnotes/gsqs/v1/operator_review.json").read_text())
    index = json.loads(Path("ops/goodnotes/gsqs/v1/case_index.json").read_text())
    payload = operator_review_payload(cases, manifest)
    assert review["manifest_digest"] == manifest.manifest_digest
    assert index["manifest_digest"] == manifest.manifest_digest
    review_md = Path("ops/goodnotes/gsqs/v1/OPERATOR_REVIEW.md").read_text()
    assert manifest.manifest_digest in review_md
    assert review["FIXED_LABELED_CORPUS_APPROVED"] is False
    assert review["approval_status"] == "REJECT_FOR_B0"
    assert review["GSQS_V1_B0_DISPOSITION"] == "REJECT_FOR_B0"
    assert review["b0_suitable"] is False
    assert review["page_count"] == payload["page_count"]
    assert review["NOTE_UNIT_count"] == payload["NOTE_UNIT_count"]
    assert review["partitions"] == payload["partitions"]
    assert {item["case_id"] for item in index["cases"]} == {case.case_id for case in cases}


def test_v1_unreadable_pdf_has_no_status_label() -> None:
    cases, _manifest = freeze_v1_corpus()
    selected = [
        case
        for case in cases
        for region in case.regions
        if region.kind is GoodNotesSegmentKind.NOTE_UNIT
        and region.transcription_status is GoodNotesTranscriptionStatus.UNREADABLE
    ]
    assert selected
    for case in selected:
        assert b"UNREADABLE" not in case.page_bytes.upper()
        note = next(
            region for region in case.regions if region.kind is GoodNotesSegmentKind.NOTE_UNIT
        )
        assert note.transcription == ""
