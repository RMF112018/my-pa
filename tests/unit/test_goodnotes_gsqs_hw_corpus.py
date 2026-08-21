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
    APPROVE_FOR_BOUNDED_B0,
    AUTHORIZED_SOURCE_ROOT,
    AUTHORIZED_SOURCE_ROOTS,
    HANDWRITING_CORPUS_VERSION,
    HANDWRITING_CORPUS_VERSION_MOSS_V1,
    LABEL_PROVENANCE_FIRST_PASS,
    UNREADABLE_REAL_WORLD_COVERAGE_NOT_OBSERVED,
    OperatorHandwritingDecision,
    PageCounter,
    PublicHandwritingCase,
    authorized_source_root,
    authorized_source_roots,
    execute_operator_approval_rebind,
    freeze_public_manifest,
    inventory_page_rasters,
    inventory_pdfs,
    inventory_pdfs_across_roots,
    limited_population_b0_suitable,
    load_public_catalog,
    prevent_admitted_raster_holdout_isolation,
    prevent_handwriting_partition_leakage,
    private_label_digest,
    public_case_dict,
    public_case_digest,
    public_source_record,
    rebind_private_label,
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
    assert manifest["FIXED_LABELED_CORPUS_APPROVED"] is False
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


def test_committed_combined_catalog_is_repository_safe_and_operator_approved() -> None:
    catalog = load_public_catalog(COMBINED_CATALOG)
    blob = COMBINED_CATALOG.read_text().lower()
    assert 'transcription":' not in blob
    assert "goodnotes-inbox" not in blob
    assert "/volume1/" not in blob
    assert catalog["corpus_version"] == HANDWRITING_CORPUS_VERSION
    assert catalog["historical_moss_corpus_version"] == HANDWRITING_CORPUS_VERSION_MOSS_V1
    assert catalog["CONTROLLED_HANDWRITING_CORPUS"] == "APPROVED"
    assert catalog["unreadable_real_world_coverage"] == (
        UNREADABLE_REAL_WORLD_COVERAGE_NOT_OBSERVED
    )
    assert catalog["scoreable_page_count"] == 239
    assert catalog["admitted_handwriting_pages"] == 239
    assert catalog["excluded_page_count"] == 1995
    assert catalog["case_count"] == 2234
    assert catalog["pdf_count"] == 86
    assert catalog["total_pages"] == 2234
    assert catalog["unreadable_pdf_count"] == 0
    assert catalog["label_review_counts"]["PENDING"] == 0
    assert catalog["label_review_counts"]["APPROVED"] == 239
    assert catalog["label_review_counts"]["REJECTED"] == 1995
    assert catalog["partition_counts"]["A"] == 101
    assert catalog["partition_counts"]["B"] == 73
    assert catalog["partition_counts"]["C"] == 65
    assert catalog["b0_suitable"] is True
    assert catalog["FIXED_LABELED_CORPUS_APPROVED"] is True
    assert catalog["synthetic_manifest_digest"] == SYNTHETIC_DIGEST
    rasters: dict[str, tuple[str, str]] = {}
    admitted = [case for case in catalog["cases"] if not case["excluded"]]
    excluded_cases = [case for case in catalog["cases"] if case["excluded"]]
    assert len(excluded_cases) == 1995
    for case in excluded_cases:
        assert case["review_state"] == "REJECTED"
        assert case["label_provenance"] == LABEL_PROVENANCE_FIRST_PASS
        assert case["excluded"] is True
    buckets: dict[str, set[str]] = {"A": set(), "B": set(), "C": set()}
    scoreable_parts = {"A": 0, "B": 0, "C": 0}
    for case in admitted:
        buckets[case["partition"]].add(case["leakage_group_id"])
        assert case["review_state"] == "APPROVED"
        assert case["label_provenance"] == LABEL_PROVENANCE_OPERATOR
        assert case["transcription_status"] != "UNREADABLE"
        assert (
            case["fixture_classification"] == FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING
        )
        scoreable_parts[case["partition"]] += 1
        prior = rasters.get(case["raster_sha256"])
        identity = (case["leakage_group_id"], case["partition"])
        if prior is not None:
            assert prior == identity
        rasters[case["raster_sha256"]] = identity
    assert scoreable_parts == {"A": 101, "B": 73, "C": 65}
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
    assert review["CONTROLLED_HANDWRITING_CORPUS"] == "APPROVED"
    assert review["b0_suitable"] is True
    assert review["FIXED_LABELED_CORPUS_APPROVED"] is True
    assert review["label_provenance"] == LABEL_PROVENANCE_OPERATOR
    assert review["MEASURED_B0"] == "NOT_YET_ESTABLISHED"
    assert review["EXTERNAL_MODEL_DISCLOSURE"] == "NONE"
    assert review["pre_rebind_manifest_digest"] == (
        "238c22aa5b51fee3993a8e72e0b2ce9d696fb9f7b164a2853d1ddc3f59eabaed"
    )
    assert review["pre_rebind_combined_identity"] == (
        "bda6e66bbaf5ac068e5b2cf64a52f1e6c06975b5dd86294591de82fe8afdeb8b"
    )
    assert catalog["manifest_digest"] != review["pre_rebind_manifest_digest"]
    assert catalog["combined_identity"] != review["pre_rebind_combined_identity"]
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


def _private_label(*, excluded: bool = False, text: str = "alpha") -> dict[str, object]:
    return {
        "excluded": excluded,
        "exclusion_reason": "blank-template" if excluded else None,
        "geometry_quality": "INSPECTION_ESTIMATED",
        "label_provenance": LABEL_PROVENANCE_FIRST_PASS,
        "regions": (
            []
            if excluded
            else [
                {
                    "candidate_tags": ["note"],
                    "kind": "NOTE_UNIT",
                    "ranked_candidates": [],
                    "transcription": text,
                }
            ]
        ),
    }


def _limited_pending_cases() -> tuple[PublicHandwritingCase, ...]:
    cases = []
    for index, (cohort, part, group) in enumerate(
        (
            ("Moss", CorpusPartition.A, "lg-a"),
            ("Kast", CorpusPartition.C, "lg-c"),
            ("Altman", CorpusPartition.B, "lg-b"),
        ),
        start=1,
    ):
        label = _private_label(text=f"note-{cohort}")
        cases.append(
            with_bound_digest(
                _case(
                    case_id=f"hw-{cohort.lower()}",
                    source_id=f"s-{index:03d}",
                    page_index=1,
                    leakage_group_id=group,
                    partition=part,
                    review_state=ReviewState.PENDING,
                    label_provenance=LABEL_PROVENANCE_FIRST_PASS,
                    source_cohort=cohort,
                    label_sha256=private_label_digest(label),
                )
            )
        )
    excluded_label = _private_label(excluded=True)
    cases.append(
        with_bound_digest(
            _case(
                case_id="hw-excluded",
                source_id="s-004",
                page_index=2,
                leakage_group_id="lg-x",
                partition=CorpusPartition.A,
                source_cohort="Moss",
                excluded=True,
                exclusion_reason="blank-template",
                review_state=ReviewState.REJECTED,
                note_unit_count=0,
                transcription_status=None,
                primary_class=None,
                candidate_tag_count=0,
                ranked_candidate_count=0,
                label_sha256=private_label_digest(excluded_label),
            )
        )
    )
    return tuple(cases)


def _decision(manifest_digest: str, combined_identity: str) -> OperatorHandwritingDecision:
    return OperatorHandwritingDecision(
        decision=APPROVE_FOR_BOUNDED_B0,
        corpus_version=HANDWRITING_CORPUS_VERSION,
        approved_pre_rebind_manifest_digest=manifest_digest,
        approved_pre_rebind_combined_identity=combined_identity,
        decided_at="2026-08-21T02:31:00-04:00",
        drive_artifact_id="1uaQ2lShnR6BY77CaOOD3grjmIotib3dJNMzjZaL5tIM",
    )


def test_review_and_provenance_change_private_and_public_digests() -> None:
    pending_label = _private_label()
    approved_label = rebind_private_label(pending_label)
    assert pending_label["regions"] == approved_label["regions"]
    assert pending_label["label_provenance"] == LABEL_PROVENANCE_FIRST_PASS
    assert approved_label["label_provenance"] == LABEL_PROVENANCE_OPERATOR
    assert private_label_digest(pending_label) != private_label_digest(approved_label)
    pending = with_bound_digest(_case(label_sha256=private_label_digest(pending_label)))
    approved = with_bound_digest(
        _case(
            review_state=ReviewState.APPROVED,
            label_provenance=LABEL_PROVENANCE_OPERATOR,
            label_sha256=private_label_digest(approved_label),
        )
    )
    assert public_case_digest(pending) != public_case_digest(approved)
    excluded_pending = _private_label(excluded=True)
    assert rebind_private_label(excluded_pending) == excluded_pending
    assert private_label_digest(rebind_private_label(excluded_pending)) == private_label_digest(
        excluded_pending
    )


def test_operator_decision_is_required_and_must_bind_pre_rebind_identity() -> None:
    cases = _limited_pending_cases()
    baseline = freeze_public_manifest(
        cases,
        synthetic_manifest_digest=SYNTHETIC_DIGEST,
        exhaustive_authorized_roots=True,
    )
    assert baseline["scoreable_page_count"] == 0
    assert baseline["FIXED_LABELED_CORPUS_APPROVED"] is False
    gold = {
        "classification": FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING,
        "corpus_version": HANDWRITING_CORPUS_VERSION,
        "geometry_quality": "INSPECTION_ESTIMATED",
        "label_provenance": LABEL_PROVENANCE_FIRST_PASS,
        "pages": {
            "hw-moss": {
                "label": _private_label(text="note-Moss"),
                "label_sha256": private_label_digest(_private_label(text="note-Moss")),
            },
            "hw-kast": {
                "label": _private_label(text="note-Kast"),
                "label_sha256": private_label_digest(_private_label(text="note-Kast")),
            },
            "hw-altman": {
                "label": _private_label(text="note-Altman"),
                "label_sha256": private_label_digest(_private_label(text="note-Altman")),
            },
            "hw-excluded": {
                "label": _private_label(excluded=True),
                "label_sha256": private_label_digest(_private_label(excluded=True)),
            },
        },
    }
    catalog = {
        **baseline,
        "authorized_source_roots_declared": True,
        "cases": [public_case_dict(case) for case in cases],
        "historical_moss_corpus_version": HANDWRITING_CORPUS_VERSION_MOSS_V1,
        "pdf_count": 3,
        "sources": [],
        "supersedes": ["gsqs-hw-moss-v1"],
        "synthetic_corpus_version": "gsqs-v2",
        "synthetic_manifest_digest": SYNTHETIC_DIGEST,
        "total_pages": 4,
        "unique_file_sha256_count": 3,
        "unreadable_pdf_count": 0,
    }
    wrong = _decision("00" * 32, baseline["combined_identity"])
    with pytest.raises(ValueError, match="does not bind the pre-rebind manifest"):
        execute_operator_approval_rebind(catalog, gold, decision=wrong)
    decision = _decision(baseline["manifest_digest"], baseline["combined_identity"])
    rebound, rebound_gold, stats = execute_operator_approval_rebind(
        catalog, gold, decision=decision
    )
    assert rebound["FIXED_LABELED_CORPUS_APPROVED"] is True
    assert rebound["CONTROLLED_HANDWRITING_CORPUS"] == "APPROVED"
    assert rebound["b0_suitable"] is True
    assert rebound["scoreable_page_count"] == 3
    assert rebound["admitted_handwriting_pages"] == 3
    assert rebound["excluded_page_count"] == 1
    assert rebound["partition_counts"] == {"A": 1, "B": 1, "C": 1}
    assert rebound["manifest_digest"] != baseline["manifest_digest"]
    assert rebound["combined_identity"] != baseline["combined_identity"]
    assert rebound["corpus_version"] == HANDWRITING_CORPUS_VERSION
    assert stats["label_sha256_changed"] == 3
    assert stats["public_case_digest_changed"] == 3
    admitted = [case for case in rebound["cases"] if not case["excluded"]]
    excluded = [case for case in rebound["cases"] if case["excluded"]]
    assert {case["review_state"] for case in admitted} == {"APPROVED"}
    assert {case["label_provenance"] for case in admitted} == {LABEL_PROVENANCE_OPERATOR}
    assert excluded[0]["review_state"] == "REJECTED"
    assert excluded[0]["label_provenance"] == LABEL_PROVENANCE_FIRST_PASS
    assert excluded[0]["label_sha256"] == gold["pages"]["hw-excluded"]["label_sha256"]
    assert (
        rebound_gold["pages"]["hw-excluded"]["label"]["regions"]
        == gold["pages"]["hw-excluded"]["label"]["regions"]
    )
    assert (
        rebound_gold["pages"]["hw-moss"]["label"]["regions"]
        == gold["pages"]["hw-moss"]["label"]["regions"]
    )
    freeze_without_decision = freeze_public_manifest(
        tuple(
            with_bound_digest(
                _case(
                    case_id=case["case_id"],
                    source_id=case["source_id"],
                    page_index=case["page_index"],
                    leakage_group_id=case["leakage_group_id"],
                    partition=CorpusPartition(case["partition"]),
                    review_state=ReviewState(case["review_state"]),
                    label_provenance=case["label_provenance"],
                    source_cohort=case["source_cohort"],
                    label_sha256=case["label_sha256"],
                    excluded=case["excluded"],
                    exclusion_reason=case["exclusion_reason"],
                    note_unit_count=case["note_unit_count"],
                    transcription_status=case["transcription_status"],
                    primary_class=case["primary_class"],
                    candidate_tag_count=case["candidate_tag_count"],
                    ranked_candidate_count=case["ranked_candidate_count"],
                )
            )
            for case in rebound["cases"]
        ),
        synthetic_manifest_digest=SYNTHETIC_DIGEST,
        exhaustive_authorized_roots=True,
    )
    assert freeze_without_decision["FIXED_LABELED_CORPUS_APPROVED"] is False
    assert freeze_without_decision["b0_suitable"] is True
