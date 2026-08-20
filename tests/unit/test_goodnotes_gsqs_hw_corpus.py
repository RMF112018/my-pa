"""Controlled real-handwriting corpus: inventory, digests, partitions, privacy."""

from __future__ import annotations

import ast
import json
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs import (
    CONTROLLED_HANDWRITING_INSUFFICIENT_EVIDENCE,
    GATE_B_STATE,
    CorpusPartition,
    evaluator_code_identity,
)
from my_pa.application.goodnotes_gsqs_corpus import (
    FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING,
    FIXTURE_PRODUCTION_GOODNOTES,
    FIXTURE_SYNTHETIC_NON_PERSONAL_HANDWRITING,
    ReviewState,
    SourceLayer,
)
from my_pa.application.goodnotes_gsqs_handwriting import (
    HANDWRITING_STATE,
    HandwritingAdmission,
    admit_handwriting,
)
from my_pa.application.goodnotes_gsqs_hw_corpus import (
    AUTHORIZED_SOURCE_ROOT,
    HANDWRITING_CORPUS_VERSION,
    PageCounter,
    PublicHandwritingCase,
    authorized_source_root,
    freeze_public_manifest,
    inventory_page_rasters,
    inventory_pdfs,
    load_public_catalog,
    prevent_handwriting_partition_leakage,
    private_label_digest,
    public_case_digest,
    public_source_record,
    with_bound_digest,
)
from my_pa.application.goodnotes_gsqs_pages import synthetic_labeled_page_pdf
from my_pa.application.goodnotes_gsqs_v2_freeze import freeze_v2_corpus

REPO = Path(__file__).resolve().parents[2]
PUBLIC_CATALOG = REPO / "ops/goodnotes/gsqs/hw-moss-v1/public_catalog.json"
HW_MODULE = REPO / "src/my_pa/application/goodnotes_gsqs_hw_corpus.py"
EVALUATOR_IDENTITY = "4ba262fcd32f3a8e2801db9029a85d1a6d4844ab8aff868f33cc70caf3940f0e"


def _pdf(name: str) -> bytes:
    from my_pa.application.goodnotes_gsqs import GoldRegion
    from my_pa.application.goodnotes_gsqs_corpus import box
    from my_pa.domain.goodnotes.models import GoodNotesSegmentKind

    region = GoldRegion(
        region_id=name,
        kind=GoodNotesSegmentKind.NOTE_UNIT,
        geometry=box(0.2, 0.2, 0.4, 0.2),
        transcription="Review agenda Monday",
    )
    return synthetic_labeled_page_pdf(case_id=name, title=name, regions=(region,))


def _counter(pages: int, reason: str | None = None) -> PageCounter:
    def _count(_path: Path) -> tuple[int, str | None]:
        return pages, reason

    return _count


def _case(**overrides: object) -> PublicHandwritingCase:
    base: dict[str, object] = {
        "case_id": "hw-test-1",
        "source_id": "src-001",
        "page_index": 1,
        "file_sha256": "ab" * 32,
        "raster_sha256": "cd" * 32,
        "label_sha256": "ef" * 32,
        "case_digest": "",
        "leakage_group_id": "lg-a",
        "partition": CorpusPartition.A,
        "review_state": ReviewState.PENDING,
        "fixture_classification": FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING,
        "source_layer": SourceLayer.CONTROLLED_HANDWRITING,
        "scenario": "lined-notebook",
        "style": "mixed-print-cursive",
        "primary_class": "PROJECT",
        "transcription_status": "CLEAR",
        "note_unit_count": 1,
        "excluded": False,
        "exclusion_reason": None,
        "candidate_tag_count": 1,
        "ranked_candidate_count": 1,
    }
    base.update(overrides)
    return PublicHandwritingCase(**base)  # type: ignore[arg-type]


def test_recursive_inventory_hashes_and_exact_file_duplicates(tmp_path: Path) -> None:
    root = tmp_path / "moss"
    (root / "a").mkdir(parents=True)
    (root / "b" / "c").mkdir(parents=True)
    pdf = _pdf("one")
    (root / "a" / "note.pdf").write_bytes(pdf)
    (root / "b" / "c" / "copy.pdf").write_bytes(pdf)
    (root / "b" / "other.pdf").write_bytes(_pdf("two"))
    rows = inventory_pdfs(root, page_counter=_counter(2))
    assert [row.source_id for row in rows] == ["src-001", "src-002", "src-003"]
    assert {row.page_count for row in rows} == {2}
    hashed = {row.file_sha256: row.exact_file_duplicate_ids for row in rows}
    dupes = [row for row in rows if row.exact_file_duplicate_ids]
    assert len(dupes) == 2
    assert all(row.file_sha256 in hashed for row in dupes)


def test_inventory_records_unreadable_pdfs(tmp_path: Path) -> None:
    root = tmp_path / "moss"
    root.mkdir()
    (root / "bad.pdf").write_bytes(_pdf("bad"))
    rows = inventory_pdfs(root, page_counter=_counter(0, "PdfError"))
    assert rows[0].parse_status == "unreadable"
    assert rows[0].failure_reason == "PdfError"
    assert rows[0].page_count == 0


def test_page_raster_exact_duplicates(tmp_path: Path) -> None:
    (tmp_path / "p1.png").write_bytes(b"\x89PNG same")
    (tmp_path / "p2.png").write_bytes(b"\x89PNG same")
    (tmp_path / "p3.png").write_bytes(b"\x89PNG other")
    rows = inventory_page_rasters(tuple(tmp_path.glob("*.png")))
    twins = [row for row in rows if row.exact_page_duplicate_ids]
    unique = [row for row in rows if not row.exact_page_duplicate_ids]
    assert len(twins) == 2
    assert len(unique) == 1


def test_private_label_digest_is_bound_into_case_identity() -> None:
    label = {"regions": [{"transcription": "alpha"}], "review_state": "PENDING"}
    other = {"regions": [{"transcription": "beta"}], "review_state": "PENDING"}
    first = _case(label_sha256=private_label_digest(label))
    second = _case(label_sha256=private_label_digest(other))
    assert private_label_digest(label) != private_label_digest(other)
    assert public_case_digest(first) != public_case_digest(second)


def test_leakage_groups_cannot_span_partitions() -> None:
    cases = (
        with_bound_digest(_case(case_id="a", partition=CorpusPartition.A)),
        with_bound_digest(_case(case_id="b", partition=CorpusPartition.B, leakage_group_id="lg-a")),
    )
    with pytest.raises(ValueError, match="leakage group spans partitions"):
        prevent_handwriting_partition_leakage(cases)


def test_abc_isolation_and_b0_suitable_false() -> None:
    cases = (
        with_bound_digest(_case(case_id="a", leakage_group_id="lg-a", partition=CorpusPartition.A)),
        with_bound_digest(_case(case_id="b", leakage_group_id="lg-b", partition=CorpusPartition.B)),
        with_bound_digest(_case(case_id="c", leakage_group_id="lg-c", partition=CorpusPartition.C)),
    )
    prevent_handwriting_partition_leakage(cases)
    manifest = freeze_public_manifest(cases, synthetic_manifest_digest="aa" * 32)
    assert manifest["b0_suitable"] is False
    assert manifest["CONTROLLED_HANDWRITING_CORPUS"] == CONTROLLED_HANDWRITING_INSUFFICIENT_EVIDENCE
    assert manifest["scoreable_page_count"] == 0
    groups = manifest["leakage_groups"]
    parts = {str(body["partition"]) for body in groups.values()}
    assert parts == {"A", "B", "C"}


def test_public_source_record_omits_relative_path(tmp_path: Path) -> None:
    root = tmp_path / "moss"
    root.mkdir()
    (root / "secret-name.pdf").write_bytes(_pdf("one"))
    row = inventory_pdfs(root, page_counter=_counter(1))[0]
    assert "secret-name" in row.relative_path
    public = public_source_record(row)
    blob = json.dumps(public)
    assert "secret-name" not in blob
    assert "relative_path" not in public


def test_committed_public_catalog_is_repository_safe_and_not_scoreable() -> None:
    catalog = load_public_catalog(PUBLIC_CATALOG)
    blob = PUBLIC_CATALOG.read_text().lower()
    assert 'transcription":' not in blob
    assert "goodnotes-inbox" not in blob
    assert "/volume1/" not in blob
    assert catalog["corpus_version"] == HANDWRITING_CORPUS_VERSION
    assert catalog["b0_suitable"] is False
    assert catalog["scoreable_page_count"] == 0
    assert catalog["admitted_handwriting_pages"] == 27
    assert catalog["excluded_page_count"] == 13
    assert catalog["pdf_count"] == 10
    assert catalog["total_pages"] == 40
    assert catalog["unreadable_pdf_count"] == 0
    admitted = [case for case in catalog["cases"] if not case["excluded"]]
    buckets: dict[str, set[str]] = {"A": set(), "B": set(), "C": set()}
    for case in admitted:
        buckets[case["partition"]].add(case["leakage_group_id"])
        assert case["review_state"] == "PENDING"
        assert (
            case["fixture_classification"] == FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING
        )
    assert not (buckets["A"] & buckets["B"])
    assert not (buckets["A"] & buckets["C"])
    assert not (buckets["B"] & buckets["C"])
    freeze_v2, _manifest = freeze_v2_corpus()
    assert freeze_v2
    assert catalog["combined_identity"]
    review = json.loads((PUBLIC_CATALOG.parent / "operator_review.json").read_text())
    assert review["manifest_digest"] == catalog["manifest_digest"]
    assert review["CONTROLLED_HANDWRITING_CORPUS"] == "INSUFFICIENT_EVIDENCE"
    assert evaluator_code_identity() == EVALUATOR_IDENTITY


def test_excluded_cases_are_not_scoreable() -> None:
    excluded = with_bound_digest(
        _case(
            excluded=True,
            exclusion_reason="blank-template",
            review_state=ReviewState.REJECTED,
            note_unit_count=0,
            transcription_status=None,
            primary_class=None,
        )
    )
    approved = with_bound_digest(
        _case(
            case_id="hw-test-2",
            leakage_group_id="lg-b",
            partition=CorpusPartition.B,
            review_state=ReviewState.APPROVED,
        )
    )
    manifest = freeze_public_manifest((excluded, approved))
    assert manifest["scoreable_page_count"] == 1
    assert manifest["admitted_handwriting_pages"] == 1
    assert manifest["b0_suitable"] is False


def test_admit_authorized_real_handwriting_without_storing_phrases() -> None:
    admitted = admit_handwriting(
        HandwritingAdmission(
            case_id="hw-real-1",
            artifact_sha256="ab" * 32,
            external_ref="private://gsqs-hw-v1/gold.json#hw-real-1",
            fixture_classification=FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING,
            phrases=(),
            style="mixed-print-cursive",
            leakage_group_id="lg-real",
            review_state=ReviewState.PENDING,
            partition=CorpusPartition.B,
        )
    )
    assert admitted.phrases == ()
    with pytest.raises(ValueError, match="production/live"):
        admit_handwriting(
            HandwritingAdmission(
                case_id="hw-bad",
                artifact_sha256="ab" * 32,
                external_ref="private://x",
                fixture_classification=FIXTURE_PRODUCTION_GOODNOTES,
                phrases=(),
                style="print",
                leakage_group_id="lg-bad",
                review_state=ReviewState.PENDING,
                partition=None,
            )
        )
    still_ok = admit_handwriting(
        HandwritingAdmission(
            case_id="hw-syn",
            artifact_sha256="cd" * 32,
            external_ref="private://synthetic",
            fixture_classification=FIXTURE_SYNTHETIC_NON_PERSONAL_HANDWRITING,
            phrases=("Review agenda Monday",),
            style="print",
            leakage_group_id="lg-syn",
            review_state=ReviewState.PENDING,
            partition=None,
        )
    )
    assert still_ok.phrases == ("Review agenda Monday",)


def test_gate_b_state_and_no_external_model_imports() -> None:
    assert GATE_B_STATE["CONTROLLED_HANDWRITING_CORPUS"] == "INSUFFICIENT_EVIDENCE"
    assert HANDWRITING_STATE == CONTROLLED_HANDWRITING_INSUFFICIENT_EVIDENCE
    assert authorized_source_root() == AUTHORIZED_SOURCE_ROOT
    tree = ast.parse(HW_MODULE.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    forbidden = {"httpx", "openai", "urllib", "requests", "aiohttp", "pypdfium2"}
    assert names.isdisjoint(forbidden)
