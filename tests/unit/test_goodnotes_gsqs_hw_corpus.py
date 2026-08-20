"""Controlled real-handwriting corpus: inventory, digests, partitions, privacy."""

from __future__ import annotations

import ast
import json
from hashlib import sha256
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs import (
    CONTROLLED_HANDWRITING_INSUFFICIENT_EVIDENCE,
    CONTROLLED_HANDWRITING_READY_FOR_REVIEW,
    GATE_B_STATE,
    CorpusPartition,
    evaluator_code_identity,
)
from my_pa.application.goodnotes_gsqs_corpus import (
    FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING,
    FIXTURE_PRODUCTION_GOODNOTES,
    FIXTURE_SYNTHETIC_NON_PERSONAL_HANDWRITING,
    LABEL_PROVENANCE_OPERATOR,
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
    AUTHORIZED_SOURCE_ROOTS,
    HANDWRITING_CORPUS_VERSION,
    HANDWRITING_CORPUS_VERSION_MOSS_V1,
    LABEL_PROVENANCE_FIRST_PASS,
    UNREADABLE_REAL_WORLD_COVERAGE_NOT_OBSERVED,
    PageCounter,
    PublicHandwritingCase,
    authorized_source_root,
    authorized_source_roots,
    freeze_public_manifest,
    inventory_page_rasters,
    inventory_pdfs,
    inventory_pdfs_across_roots,
    limited_population_b0_suitable,
    load_public_catalog,
    prevent_admitted_raster_holdout_isolation,
    prevent_handwriting_partition_leakage,
    private_label_digest,
    public_case_digest,
    public_source_record,
    unreadable_real_world_coverage,
    with_bound_digest,
)
from my_pa.application.goodnotes_gsqs_pages import synthetic_labeled_page_pdf
from my_pa.application.goodnotes_gsqs_v2_freeze import freeze_v2_corpus

REPO = Path(__file__).resolve().parents[2]
PUBLIC_CATALOG = REPO / "ops/goodnotes/gsqs/hw-moss-v1/public_catalog.json"
COMBINED_CATALOG = REPO / "ops/goodnotes/gsqs/hw-combined-v1/public_catalog.json"
HW_MODULE = REPO / "src/my_pa/application/goodnotes_gsqs_hw_corpus.py"
SYNTHETIC_DIGEST = "e5f7222b0d1ba4a624e94060a9a2386fa68c716025464287ca80d0eecb23e7dd"


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
        "source_cohort": "Moss",
        "label_provenance": LABEL_PROVENANCE_FIRST_PASS,
    }
    base.update(overrides)
    if "raster_sha256" not in overrides:
        base["raster_sha256"] = sha256(str(base["case_id"]).encode()).hexdigest()
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
    assert catalog["corpus_version"] == HANDWRITING_CORPUS_VERSION_MOSS_V1
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
    assert len(evaluator_code_identity()) == 64


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
            label_provenance=LABEL_PROVENANCE_OPERATOR,
            page_index=2,
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
    assert GATE_B_STATE["CONTROLLED_HANDWRITING_CORPUS"] == "READY_FOR_REVIEW"
    assert HANDWRITING_STATE == CONTROLLED_HANDWRITING_READY_FOR_REVIEW
    assert authorized_source_root() == AUTHORIZED_SOURCE_ROOT
    assert authorized_source_roots() == dict(AUTHORIZED_SOURCE_ROOTS)
    tree = ast.parse(HW_MODULE.read_text())
    names: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            names.update(alias.name.split(".", 1)[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            names.add(node.module.split(".", 1)[0])
    forbidden = {"httpx", "openai", "urllib", "requests", "aiohttp", "pypdfium2"}
    assert names.isdisjoint(forbidden)


def test_combined_corpus_version_is_distinct_from_moss() -> None:
    assert HANDWRITING_CORPUS_VERSION == "gsqs-hw-combined-v1"
    assert HANDWRITING_CORPUS_VERSION != HANDWRITING_CORPUS_VERSION_MOSS_V1


def test_multi_root_inventory_and_cross_root_file_duplicates(tmp_path: Path) -> None:
    moss = tmp_path / "Moss"
    kast = tmp_path / "Kast"
    altman = tmp_path / "Altman" / "nested"
    moss.mkdir()
    kast.mkdir()
    altman.mkdir(parents=True)
    shared = _pdf("shared")
    (moss / "note.pdf").write_bytes(shared)
    (kast / "copy.pdf").write_bytes(shared)
    (altman / "other.pdf").write_bytes(_pdf("other"))
    rows = inventory_pdfs_across_roots(
        {"Moss": moss, "Kast": kast, "Altman": altman.parent},
        page_counter=_counter(2),
    )
    by_id = {row.source_id: row for row in rows}
    assert set(by_id) == {"m-001", "k-001", "a-001"}
    assert by_id["m-001"].source_cohort == "Moss"
    assert by_id["k-001"].source_cohort == "Kast"
    assert by_id["a-001"].source_cohort == "Altman"
    assert "k-001" in by_id["m-001"].exact_file_duplicate_ids
    assert "m-001" in by_id["k-001"].exact_file_duplicate_ids
    assert by_id["a-001"].exact_file_duplicate_ids == ()
    with pytest.raises(ValueError, match="authorized source roots missing"):
        inventory_pdfs_across_roots({"Moss": moss}, page_counter=_counter(1))


def test_pending_and_ambiguous_are_not_scoreable() -> None:
    pending = with_bound_digest(_case(case_id="p", review_state=ReviewState.PENDING))
    ambiguous = with_bound_digest(
        _case(
            case_id="x",
            page_index=2,
            leakage_group_id="lg-x",
            review_state=ReviewState.AMBIGUOUS_EXCLUDE,
            excluded=True,
            exclusion_reason="ambiguous-intent",
            note_unit_count=0,
            transcription_status=None,
            primary_class=None,
        )
    )
    first_pass = with_bound_digest(
        _case(
            case_id="fp",
            page_index=3,
            leakage_group_id="lg-fp",
            partition=CorpusPartition.B,
            review_state=ReviewState.APPROVED,
            label_provenance=LABEL_PROVENANCE_FIRST_PASS,
        )
    )
    manifest = freeze_public_manifest((pending, ambiguous, first_pass))
    assert manifest["scoreable_page_count"] == 0
    assert manifest["label_review_counts"]["PENDING"] == 1
    assert manifest["label_review_counts"]["AMBIGUOUS_EXCLUDE"] == 1


def test_limited_population_b0_does_not_require_quota_or_unreadable() -> None:
    cases = []
    for index, (cohort, part, group) in enumerate(
        (
            ("Moss", CorpusPartition.A, "lg-a"),
            ("Kast", CorpusPartition.C, "lg-c"),
            ("Altman", CorpusPartition.B, "lg-b"),
        ),
        start=1,
    ):
        cases.append(
            with_bound_digest(
                _case(
                    case_id=f"hw-{cohort.lower()}",
                    source_id=f"s-{index:03d}",
                    page_index=1,
                    leakage_group_id=group,
                    partition=part,
                    review_state=ReviewState.APPROVED,
                    label_provenance=LABEL_PROVENANCE_OPERATOR,
                    source_cohort=cohort,
                    transcription_status="CLEAR" if cohort != "Kast" else "UNCERTAIN",
                )
            )
        )
    assert unreadable_real_world_coverage(0) == UNREADABLE_REAL_WORLD_COVERAGE_NOT_OBSERVED
    assert limited_population_b0_suitable(cases, exhaustive_authorized_roots=True) is True
    manifest = freeze_public_manifest(
        cases,
        synthetic_manifest_digest="aa" * 32,
        exhaustive_authorized_roots=True,
    )
    assert manifest["b0_suitable"] is True
    assert manifest["CONTROLLED_HANDWRITING_CORPUS"] == CONTROLLED_HANDWRITING_READY_FOR_REVIEW
    assert manifest["unreadable_real_world_coverage"] == UNREADABLE_REAL_WORLD_COVERAGE_NOT_OBSERVED
    assert manifest["scoreable_page_count"] == 3
    assert any("former 75-150" in item for item in manifest["b0_limitations"])
    pending = with_bound_digest(
        _case(
            case_id="hw-pending",
            source_id="s-004",
            page_index=2,
            leakage_group_id="lg-a",
            partition=CorpusPartition.A,
            source_cohort="Moss",
            review_state=ReviewState.PENDING,
        )
    )
    assert (
        limited_population_b0_suitable((*cases, pending), exhaustive_authorized_roots=True) is False
    )


def test_committed_combined_catalog_is_repository_safe_and_not_scoreable() -> None:
    catalog = load_public_catalog(COMBINED_CATALOG)
    blob = COMBINED_CATALOG.read_text().lower()
    assert 'transcription":' not in blob
    assert "goodnotes-inbox" not in blob
    assert "/volume1/" not in blob
    assert catalog["corpus_version"] == HANDWRITING_CORPUS_VERSION
    assert catalog["historical_moss_corpus_version"] == HANDWRITING_CORPUS_VERSION_MOSS_V1
    assert catalog["b0_suitable"] is False
    assert catalog["CONTROLLED_HANDWRITING_CORPUS"] == CONTROLLED_HANDWRITING_READY_FOR_REVIEW
    assert catalog["unreadable_real_world_coverage"] == (
        UNREADABLE_REAL_WORLD_COVERAGE_NOT_OBSERVED
    )
    assert catalog["scoreable_page_count"] == 0
    assert catalog["admitted_handwriting_pages"] == 239
    assert catalog["excluded_page_count"] == 1995
    assert catalog["case_count"] == 2234
    assert catalog["pdf_count"] == 86
    assert catalog["total_pages"] == 2234
    assert catalog["unreadable_pdf_count"] == 0
    assert catalog["label_review_counts"]["PENDING"] == 239
    assert catalog["label_review_counts"]["APPROVED"] == 0
    assert catalog["partition_counts"]["B"] > 0
    assert catalog["partition_counts"]["C"] > 0
    assert catalog["synthetic_manifest_digest"] == SYNTHETIC_DIGEST
    rasters: dict[str, tuple[str, str]] = {}
    admitted = [case for case in catalog["cases"] if not case["excluded"]]
    buckets: dict[str, set[str]] = {"A": set(), "B": set(), "C": set()}
    for case in admitted:
        buckets[case["partition"]].add(case["leakage_group_id"])
        assert case["review_state"] == "PENDING"
        assert case["label_provenance"] == LABEL_PROVENANCE_FIRST_PASS
        assert case["transcription_status"] != "UNREADABLE"
        assert (
            case["fixture_classification"] == FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING
        )
        prior = rasters.get(case["raster_sha256"])
        identity = (case["leakage_group_id"], case["partition"])
        if prior is not None:
            assert prior == identity
        rasters[case["raster_sha256"]] = identity
    assert buckets["A"] and buckets["B"] and buckets["C"]
    assert not (buckets["A"] & buckets["B"])
    assert not (buckets["A"] & buckets["C"])
    assert not (buckets["B"] & buckets["C"])
    moss = load_public_catalog(PUBLIC_CATALOG)
    assert moss["corpus_version"] == HANDWRITING_CORPUS_VERSION_MOSS_V1
    assert moss["b0_suitable"] is False
    assert moss["scoreable_page_count"] == 0
    freeze_v2, _manifest = freeze_v2_corpus()
    assert freeze_v2
    review = json.loads((COMBINED_CATALOG.parent / "operator_review.json").read_text())
    assert review["manifest_digest"] == catalog["manifest_digest"]
    assert review["CONTROLLED_HANDWRITING_CORPUS"] == "READY_FOR_REVIEW"
    assert review["b0_suitable"] is False
    assert review["label_provenance"] == LABEL_PROVENANCE_FIRST_PASS
    assert len(evaluator_code_identity()) == 64


def test_admitted_raster_cannot_span_groups_or_partitions() -> None:
    twin_partition = with_bound_digest(
        _case(
            case_id="hw-raster-b",
            leakage_group_id="lg-b",
            partition=CorpusPartition.B,
            raster_sha256="cd" * 32,
        )
    )
    with pytest.raises(ValueError, match="admitted raster spans"):
        prevent_admitted_raster_holdout_isolation(
            (
                with_bound_digest(_case(raster_sha256="cd" * 32)),
                twin_partition,
            )
        )
    twin_group = with_bound_digest(
        _case(
            case_id="hw-raster-g",
            leakage_group_id="lg-other",
            partition=CorpusPartition.A,
            raster_sha256="cd" * 32,
        )
    )
    with pytest.raises(ValueError, match="admitted raster spans"):
        freeze_public_manifest((with_bound_digest(_case(raster_sha256="cd" * 32)), twin_group))
    excluded = with_bound_digest(
        _case(
            case_id="hw-dup",
            leakage_group_id="lg-dup",
            partition=CorpusPartition.C,
            excluded=True,
            exclusion_reason="exact-page-duplicate",
            review_state=ReviewState.REJECTED,
            note_unit_count=0,
            transcription_status=None,
            primary_class=None,
            raster_sha256="cd" * 32,
        )
    )
    prevent_admitted_raster_holdout_isolation(
        (with_bound_digest(_case(raster_sha256="cd" * 32)), excluded)
    )
