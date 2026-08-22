"""Controlled-handwriting evaluator binding keeps public and private identities apart."""

from __future__ import annotations

import copy
import json
from collections.abc import Callable, Mapping
from dataclasses import replace
from pathlib import Path

import pytest

from my_pa.application.goodnotes_gsqs import (
    MEASURED_B0_NOT_YET_ESTABLISHED,
    CorpusPartition,
    evaluator_code_identity,
)
from my_pa.application.goodnotes_gsqs_corpus import (
    EVALUATOR_PLANE_SCHEMA,
    FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING,
    LABEL_PROVENANCE_OPERATOR,
    CorpusManifest,
    ReviewState,
    SourceLayer,
    case_digest,
    dump_evaluator_plane_cases,
    gold_region_from_payload,
)
from my_pa.application.goodnotes_gsqs_evaluator_binding import (
    HANDWRITING_EVALUATOR_PLANE_SCHEMA,
    HANDWRITING_EVALUATOR_RENDERER_NAME,
    AdmittedEvaluatorPlane,
    admit_handwriting_evaluator_plane,
    derived_public_counts,
    load_and_admit_evaluator_plane,
    materialize_handwriting_evaluator_plane,
    revalidate_admitted_evaluator_plane,
)
from my_pa.application.goodnotes_gsqs_harness import gold_as_output
from my_pa.application.goodnotes_gsqs_hw_corpus import (
    HANDWRITING_CORPUS_VERSION,
    PublicHandwritingCase,
    load_public_catalog,
    private_label_digest,
    public_case_dict,
    with_bound_digest,
)
from my_pa.application.goodnotes_gsqs_live_b0 import (
    APPROVED_COMBINED_IDENTITY,
    APPROVED_MANIFEST_DIGEST,
    EXPECTED_SCOREABLE_B,
    B0Census,
    B0CensusMember,
    B0RunState,
    RecordingFakeAdapter,
    catalog_path,
    execute_measured_b0,
    frozen_incumbent_config,
    partition_b_census,
    validate_evaluator_plane,
    write_public_evidence,
)
from tests.unit.test_goodnotes_gsqs_live_b0 import (
    _build_fixture,
    _catalog,
    _clean_repo,
    _document,
    _fixture_auth,
)


def _region(
    *,
    text: str,
    region_id: str,
    tags: list[str] | None = None,
    primary_class: str = "PROJECT",
    transcription_status: str = "CLEAR",
    y_min: float = 0.1,
    ranked: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "candidate_tags": list(tags or ["note"]),
        "contains_embedded_instructions": False,
        "geometry": {"height": 0.1, "width": 0.2, "x_min": 0.1, "y_min": y_min},
        "kind": "NOTE_UNIT",
        "no_association_correct": not ranked,
        "primary_class": primary_class,
        "ranked_candidates": list(ranked or []),
        "reference_confidence": None,
        "region_id": region_id,
        "transcription": text,
        "transcription_status": transcription_status,
    }


def _private_label(
    *,
    text: str = "alpha-note",
    region_id: str = "r-1",
    regions: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "excluded": False,
        "exclusion_reason": None,
        "geometry_quality": "INSPECTION_ESTIMATED",
        "label_provenance": LABEL_PROVENANCE_OPERATOR,
        "regions": list(regions or [_region(text=text, region_id=region_id)]),
    }


def _public_case(
    *,
    case_id: str,
    label: Mapping[str, object],
    primary_class: str | None = "PROJECT",
    transcription_status: str | None = "CLEAR",
    **overrides: object,
) -> dict[str, object]:
    from hashlib import sha256

    regions = tuple(gold_region_from_payload(item) for item in label["regions"])  # type: ignore[arg-type]
    counts = derived_public_counts(regions)
    raster = sha256(f"raster-{case_id}".encode()).hexdigest()
    file_sha = sha256(f"file-{case_id}".encode()).hexdigest()
    base = PublicHandwritingCase(
        case_id=case_id,
        source_id=f"src-{case_id}",
        page_index=1,
        file_sha256=file_sha,
        raster_sha256=raster,
        label_sha256=private_label_digest(label),
        case_digest="",
        leakage_group_id=f"lg-{case_id}",
        partition=CorpusPartition.B,
        review_state=ReviewState.APPROVED,
        fixture_classification=FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING,
        source_layer=SourceLayer.CONTROLLED_HANDWRITING,
        scenario="daily-planner",
        style="mixed-print-cursive",
        primary_class=primary_class,
        transcription_status=transcription_status,
        note_unit_count=counts["note_unit_count"],
        excluded=False,
        exclusion_reason=None,
        candidate_tag_count=counts["candidate_tag_count"],
        ranked_candidate_count=counts["ranked_candidate_count"],
        source_cohort="Moss",
        label_provenance=LABEL_PROVENANCE_OPERATOR,
    )
    bound = with_bound_digest(replace(base, **overrides) if overrides else base)  # type: ignore[arg-type]
    return public_case_dict(bound)


def _fixture() -> tuple[
    dict[str, object], B0Census, dict[str, dict[str, object]], dict[str, object]
]:
    labels = {
        "hw-syn-1": _private_label(text="alpha-note", region_id="r-1"),
        "hw-syn-2": _private_label(text="beta-note", region_id="r-2"),
    }
    cases = [
        _public_case(case_id="hw-syn-1", label=labels["hw-syn-1"]),
        _public_case(case_id="hw-syn-2", label=labels["hw-syn-2"]),
    ]
    catalog = {
        "cases": cases,
        "corpus_version": HANDWRITING_CORPUS_VERSION,
        "manifest_digest": APPROVED_MANIFEST_DIGEST,
        "combined_identity": APPROVED_COMBINED_IDENTITY,
    }
    members = tuple(
        B0CensusMember(
            case_id=str(item["case_id"]),
            raster_sha256=str(item["raster_sha256"]),
            case_digest=str(item["case_digest"]),
            file_sha256=str(item["file_sha256"]),
        )
        for item in cases
    )
    census = B0Census(
        corpus_version=HANDWRITING_CORPUS_VERSION,
        manifest_digest=APPROVED_MANIFEST_DIGEST,
        combined_identity=APPROVED_COMBINED_IDENTITY,
        partition="B",
        members=members,
        census_digest="ee" * 32,
    )
    plane = materialize_handwriting_evaluator_plane(
        catalog=catalog, census=census, labels_by_case_id=labels
    )
    return catalog, census, labels, plane


def _admit(
    plane: dict[str, object], catalog: Mapping[str, object], census: B0Census
) -> AdmittedEvaluatorPlane:
    return admit_handwriting_evaluator_plane(plane, catalog=catalog, census=census)


def test_handwriting_binding_admits_without_forging_digest_equality() -> None:
    catalog, census, labels, plane = _fixture()
    admitted = _admit(plane, catalog, census)
    assert admitted.schema_version == HANDWRITING_EVALUATOR_PLANE_SCHEMA
    assert len(admitted.cases) == 2
    for case, member, record in zip(admitted.cases, census.members, admitted.records, strict=True):
        public = next(item for item in catalog["cases"] if item["case_id"] == member.case_id)
        assert case_digest(case) != member.case_digest
        assert case_digest(case) != record.public_case_digest
        assert record.public_case_digest == member.case_digest
        assert record.label_sha256 == public["label_sha256"]
        assert record.label_sha256 == private_label_digest(labels[member.case_id])
        assert case.content_sha256 == member.raster_sha256
        assert (
            case.regions[0].transcription == labels[member.case_id]["regions"][0]["transcription"]
        )
        assert case.renderer_name == HANDWRITING_EVALUATOR_RENDERER_NAME
        assert case.scoreable
    first = admitted.cases[0]
    mutated_renderer = replace(first, renderer_name="other-renderer")
    gold = gold_as_output(first, analyzer_name="fixture", analyzer_version="1")
    other = gold_as_output(mutated_renderer, analyzer_name="fixture", analyzer_version="1")
    assert gold.segments[0].transcription == other.segments[0].transcription
    assert case_digest(mutated_renderer) != case_digest(first)
    assert MEASURED_B0_NOT_YET_ESTABLISHED == "NOT_YET_ESTABLISHED"


def test_materialize_round_trip_and_file_load(tmp_path: Path) -> None:
    catalog, census, labels, plane = _fixture()
    wrapped = {
        case_id: {"label": label, "label_sha256": private_label_digest(label)}
        for case_id, label in labels.items()
    }
    materialized = materialize_handwriting_evaluator_plane(
        catalog=catalog, census=census, labels_by_case_id=wrapped
    )
    assert materialized == plane
    path = tmp_path / "evaluator-v2.json"
    path.write_text(json.dumps(plane), encoding="utf-8")
    loaded = load_and_admit_evaluator_plane(path, census=census, catalog=catalog)
    assert [item.case_id for item in loaded.cases] == [item.case_id for item in census.members]


def test_v1_synthetic_path_still_validates() -> None:
    cases, _manifest, census, _config = _build_fixture()
    validate_evaluator_plane(cases, census)
    plane = dump_evaluator_plane_cases(cases)
    assert plane["schema_version"] == EVALUATOR_PLANE_SCHEMA


def test_v1_against_handwriting_census_fails_closed(tmp_path: Path) -> None:
    cases, _manifest, _synthetic_census, _config = _build_fixture()
    census = partition_b_census(_catalog())
    path = tmp_path / "evaluator-v1.json"
    path.write_text(json.dumps(dump_evaluator_plane_cases(cases)), encoding="utf-8")
    with pytest.raises(ValueError, match="handwriting census requires gsqs-evaluator-plane-v2"):
        load_and_admit_evaluator_plane(path, census=census, catalog=_catalog())
    with pytest.raises(ValueError, match="handwriting census requires gsqs-evaluator-plane-v2"):
        validate_evaluator_plane(cases, census)


def test_short_v2_against_real_73_census_fails_count() -> None:
    catalog, _mini, _labels, plane = _fixture()
    real = partition_b_census(_catalog())
    with pytest.raises(ValueError, match="evaluator cases do not match Partition B census"):
        _admit(plane, catalog, real)


def test_revalidate_discards_mutated_evaluator_cases() -> None:
    catalog, census, _labels, plane = _fixture()
    admitted = _admit(plane, catalog, census)
    mutated_case = replace(
        admitted.cases[0],
        regions=(replace(admitted.cases[0].regions[0], transcription="tampered"),),
    )
    tampered = replace(admitted, cases=(mutated_case, *admitted.cases[1:]))
    restored = revalidate_admitted_evaluator_plane(tampered, census=census, catalog=catalog)
    assert restored.cases[0].regions[0].transcription == "alpha-note"


def test_public_evidence_omits_private_gold(tmp_path: Path) -> None:
    catalog, census, labels, plane = _fixture()
    admitted = _admit(plane, catalog, census)
    from my_pa.application.goodnotes_gsqs_live_b0 import B0RunState, PreflightReport

    report = PreflightReport(
        go=True,
        state=B0RunState.PREPARED,
        reasons=(),
        corpus_version=census.corpus_version,
        manifest_digest=census.manifest_digest,
        combined_identity=census.combined_identity,
        scoreable_b=len(census.members),
        census_digest=census.census_digest,
        analyzer_name="fixture",
        analyzer_version="1",
        prompt_config_identity="ff" * 32,
        evaluator_behavior_identity=evaluator_code_identity(),
        repository_commit="aa" * 20,
        repository_tree="bb" * 20,
        disclosure_would_occur=False,
    )
    write_public_evidence(tmp_path, report=report)
    blob = "\n".join(path.read_text(encoding="utf-8") for path in tmp_path.glob("*"))
    assert "alpha-note" not in blob
    assert "beta-note" not in blob
    assert "private_label" not in blob
    assert (
        admitted.cases[0].regions[0].transcription
        == labels["hw-syn-1"]["regions"][0]["transcription"]
    )
    control = json.loads((tmp_path / "RUN_CONTROL.json").read_text())
    assert control["MEASURED_B0"] == MEASURED_B0_NOT_YET_ESTABLISHED


def _tamper(
    plane: dict[str, object], mutator: Callable[[dict[str, object]], object]
) -> dict[str, object]:
    cloned = copy.deepcopy(plane)
    mutator(cloned)
    return cloned


@pytest.mark.parametrize(
    ("mutator", "match"),
    [
        (
            lambda plane: plane["cases"][0].__setitem__("label_sha256", "00" * 32),
            "private label_sha256 mismatch",
        ),
        (
            lambda plane: (
                plane["cases"][0].__setitem__(
                    "private_label",
                    _private_label(text="beta-note", region_id="r-2"),
                ),
                plane["cases"][0].__setitem__(
                    "label_sha256",
                    private_label_digest(_private_label(text="beta-note", region_id="r-2")),
                ),
            ),
            "substituted private gold",
        ),
        (
            lambda plane: plane["cases"][0]["private_label"]["regions"][0].__setitem__(
                "transcription", "mutated-note"
            ),
            "private label_sha256 mismatch",
        ),
        (
            lambda plane: plane["cases"][0].__setitem__("content_sha256", "00" * 32),
            "evaluator raster binding mismatch",
        ),
        (
            lambda plane: plane["cases"][0].__setitem__("public_case_digest", "00" * 32),
            "wrong public case digest",
        ),
        (
            lambda plane: plane["cases"][0].__setitem__("case_id", "hw-syn-9"),
            "wrong case id|evaluator cases do not match",
        ),
        (
            lambda plane: plane["cases"].__setitem__(1, copy.deepcopy(plane["cases"][0])),
            "duplicate case identity",
        ),
        (
            lambda plane: plane["cases"].pop(),
            "evaluator cases do not match Partition B census",
        ),
        (
            lambda plane: plane["cases"].append(
                {
                    **copy.deepcopy(plane["cases"][0]),
                    "case_id": "hw-syn-extra",
                }
            ),
            "evaluator cases do not match Partition B census",
        ),
        (
            lambda plane: plane.__setitem__("schema_version", "gsqs-evaluator-plane-v1"),
            "malformed evaluator-plane binding",
        ),
        (
            lambda plane: plane.__setitem__("binding_kind", "synthetic_evaluator_plane_v1"),
            "malformed evaluator-plane binding",
        ),
        (
            lambda plane: plane.__setitem__("cases", "not-a-list"),
            "malformed evaluator-plane binding",
        ),
    ],
)
def test_handwriting_binding_tamper_matrix(
    mutator: Callable[[dict[str, object]], object], match: str
) -> None:
    catalog, census, _labels, plane = _fixture()
    with pytest.raises(ValueError, match=match):
        _admit(_tamper(plane, mutator), catalog, census)


def test_wrong_partition_review_provenance_and_unscoreable() -> None:
    catalog, census, labels, plane = _fixture()

    def _rebind(index: int, **changes: object) -> dict[str, object]:
        row = dict(catalog["cases"][index])  # type: ignore[index]
        row.update(changes)
        if "partition" in changes and not isinstance(changes["partition"], str):
            row["partition"] = changes["partition"].value  # type: ignore[union-attr]
        if "review_state" in changes and not isinstance(changes["review_state"], str):
            row["review_state"] = changes["review_state"].value  # type: ignore[union-attr]
        rebound = with_bound_digest(
            PublicHandwritingCase(
                **{
                    **row,
                    "partition": CorpusPartition(row["partition"]),
                    "review_state": ReviewState(row["review_state"]),
                    "source_layer": SourceLayer(row["source_layer"]),
                    "case_digest": "",
                }
            )  # type: ignore[arg-type]
        )
        mutated = copy.deepcopy(catalog)
        mutated["cases"][index] = public_case_dict(rebound)
        return mutated

    with pytest.raises(ValueError, match="wrong partition"):
        _admit(plane, _rebind(0, partition=CorpusPartition.A), census)
    with pytest.raises(ValueError, match="wrong partition"):
        _admit(plane, _rebind(0, partition=CorpusPartition.C), census)
    with pytest.raises(ValueError, match="wrong review state"):
        _admit(plane, _rebind(0, review_state=ReviewState.PENDING), census)
    with pytest.raises(ValueError, match="wrong label provenance"):
        _admit(plane, _rebind(0, label_provenance="FIRST_PASS_LOCAL_INSPECTION"), census)
    excluded_label = dict(labels["hw-syn-1"])
    excluded_label["excluded"] = True
    excluded_catalog = _rebind(0, excluded=True, exclusion_reason="blank")
    excluded_catalog["cases"][0]["label_sha256"] = private_label_digest(excluded_label)
    excluded_catalog["cases"][0] = public_case_dict(
        with_bound_digest(
            PublicHandwritingCase(
                **{
                    **excluded_catalog["cases"][0],
                    "partition": CorpusPartition.B,
                    "review_state": ReviewState.APPROVED,
                    "source_layer": SourceLayer.CONTROLLED_HANDWRITING,
                    "case_digest": "",
                    "label_sha256": private_label_digest(excluded_label),
                }
            )  # type: ignore[arg-type]
        )
    )
    excluded_plane = copy.deepcopy(plane)
    excluded_plane["cases"][0]["private_label"] = excluded_label
    excluded_plane["cases"][0]["label_sha256"] = private_label_digest(excluded_label)
    excluded_plane["cases"][0]["public_case_digest"] = excluded_catalog["cases"][0]["case_digest"]
    excluded_census = B0Census(
        corpus_version=census.corpus_version,
        manifest_digest=census.manifest_digest,
        combined_identity=census.combined_identity,
        partition=census.partition,
        members=(
            B0CensusMember(
                case_id=census.members[0].case_id,
                raster_sha256=census.members[0].raster_sha256,
                case_digest=str(excluded_catalog["cases"][0]["case_digest"]),
                file_sha256=census.members[0].file_sha256,
            ),
            census.members[1],
        ),
        census_digest=census.census_digest,
    )
    with pytest.raises(ValueError, match="unscoreable evaluator case"):
        _admit(excluded_plane, excluded_catalog, excluded_census)


def test_real_catalog_identities_unchanged() -> None:
    catalog = load_public_catalog(catalog_path())
    census = partition_b_census(catalog)
    assert catalog["manifest_digest"] == APPROVED_MANIFEST_DIGEST
    assert catalog["combined_identity"] == APPROVED_COMBINED_IDENTITY
    assert len(census.members) == 73
    assert (
        census.census_digest == "2ea2f769f480b501703679c0259cfcc12d6736b7bc7033b931668165a96862cb"
    )


def test_derived_public_counts_allow_mixed_class_and_status() -> None:
    regions = tuple(
        gold_region_from_payload(item)
        for item in (
            _region(text="one", region_id="r-a", primary_class="PROJECT", y_min=0.1),
            _region(
                text="two",
                region_id="r-b",
                primary_class="MEETING",
                transcription_status="UNCERTAIN",
                y_min=0.4,
            ),
        )
    )
    counts = derived_public_counts(regions)
    assert counts == {
        "candidate_tag_count": 2,
        "note_unit_count": 2,
        "ranked_candidate_count": 0,
    }


def _mixed_class_fixture() -> tuple[
    dict[str, object], B0Census, dict[str, dict[str, object]], dict[str, object]
]:
    labels = {
        "hw-syn-1": _private_label(
            regions=[
                _region(text="alpha-note", region_id="r-1", primary_class="PROJECT", y_min=0.1),
                _region(text="alpha-meet", region_id="r-1b", primary_class="MEETING", y_min=0.4),
            ]
        ),
        "hw-syn-2": _private_label(text="beta-note", region_id="r-2"),
    }
    cases = [
        _public_case(case_id="hw-syn-1", label=labels["hw-syn-1"], primary_class="MEETING"),
        _public_case(case_id="hw-syn-2", label=labels["hw-syn-2"]),
    ]
    return _catalog_from_cases(cases, labels)


def _mixed_status_fixture() -> tuple[
    dict[str, object], B0Census, dict[str, dict[str, object]], dict[str, object]
]:
    labels = {
        "hw-syn-1": _private_label(
            regions=[
                _region(
                    text="alpha-note", region_id="r-1", transcription_status="CLEAR", y_min=0.1
                ),
                _region(
                    text="alpha-blur",
                    region_id="r-1b",
                    transcription_status="UNCERTAIN",
                    y_min=0.4,
                ),
            ]
        ),
        "hw-syn-2": _private_label(text="beta-note", region_id="r-2"),
    }
    cases = [
        _public_case(
            case_id="hw-syn-1",
            label=labels["hw-syn-1"],
            transcription_status="UNCERTAIN",
        ),
        _public_case(case_id="hw-syn-2", label=labels["hw-syn-2"]),
    ]
    return _catalog_from_cases(cases, labels)


def _catalog_from_cases(
    cases: list[dict[str, object]], labels: dict[str, dict[str, object]]
) -> tuple[dict[str, object], B0Census, dict[str, dict[str, object]], dict[str, object]]:
    catalog = {
        "cases": cases,
        "corpus_version": HANDWRITING_CORPUS_VERSION,
        "manifest_digest": APPROVED_MANIFEST_DIGEST,
        "combined_identity": APPROVED_COMBINED_IDENTITY,
    }
    members = tuple(
        B0CensusMember(
            case_id=str(item["case_id"]),
            raster_sha256=str(item["raster_sha256"]),
            case_digest=str(item["case_digest"]),
            file_sha256=str(item["file_sha256"]),
        )
        for item in cases
    )
    census = B0Census(
        corpus_version=HANDWRITING_CORPUS_VERSION,
        manifest_digest=APPROVED_MANIFEST_DIGEST,
        combined_identity=APPROVED_COMBINED_IDENTITY,
        partition="B",
        members=members,
        census_digest="ee" * 32,
    )
    plane = materialize_handwriting_evaluator_plane(
        catalog=catalog, census=census, labels_by_case_id=labels
    )
    return catalog, census, labels, plane


def test_mixed_class_page_admits_without_aggregation_rule() -> None:
    catalog, census, labels, plane = _mixed_class_fixture()
    admitted = _admit(plane, catalog, census)
    first = admitted.cases[0]
    classes = {region.primary_class.value for region in first.regions if region.primary_class}
    assert classes == {"PROJECT", "MEETING"}
    assert catalog["cases"][0]["primary_class"] == "MEETING"
    assert labels["hw-syn-1"]["regions"][0]["primary_class"] == "PROJECT"
    restored = revalidate_admitted_evaluator_plane(admitted, census=census, catalog=catalog)
    assert [item.case_id for item in restored.cases] == [
        member.case_id for member in census.members
    ]


def test_mixed_status_page_admits() -> None:
    catalog, census, _labels, plane = _mixed_status_fixture()
    admitted = _admit(plane, catalog, census)
    statuses = {
        region.transcription_status.value
        for region in admitted.cases[0].regions
        if region.transcription_status
    }
    assert statuses == {"CLEAR", "UNCERTAIN"}
    assert catalog["cases"][0]["transcription_status"] == "UNCERTAIN"


def test_count_mismatch_still_fails_closed() -> None:
    catalog, census, _labels, plane = _fixture()
    mutated = copy.deepcopy(catalog)
    mutated["cases"][0]["note_unit_count"] = 99
    rebound = with_bound_digest(
        PublicHandwritingCase(
            **{
                **mutated["cases"][0],
                "partition": CorpusPartition.B,
                "review_state": ReviewState.APPROVED,
                "source_layer": SourceLayer.CONTROLLED_HANDWRITING,
                "case_digest": "",
            }
        )  # type: ignore[arg-type]
    )
    mutated["cases"][0] = public_case_dict(rebound)
    aligned = B0Census(
        corpus_version=census.corpus_version,
        manifest_digest=census.manifest_digest,
        combined_identity=census.combined_identity,
        partition=census.partition,
        members=(
            B0CensusMember(
                case_id=census.members[0].case_id,
                raster_sha256=census.members[0].raster_sha256,
                case_digest=rebound.case_digest,
                file_sha256=census.members[0].file_sha256,
            ),
            census.members[1],
        ),
        census_digest=census.census_digest,
    )
    aligned_plane = copy.deepcopy(plane)
    aligned_plane["cases"][0]["public_case_digest"] = rebound.case_digest
    with pytest.raises(ValueError, match="derived public summary mismatch"):
        _admit(aligned_plane, mutated, aligned)


def test_page_level_class_tamper_is_caught_by_public_digest() -> None:
    catalog, census, _labels, plane = _fixture()
    mutated = copy.deepcopy(catalog)
    mutated["cases"][0]["primary_class"] = "GENERAL"
    rebound = with_bound_digest(
        PublicHandwritingCase(
            **{
                **mutated["cases"][0],
                "partition": CorpusPartition.B,
                "review_state": ReviewState.APPROVED,
                "source_layer": SourceLayer.CONTROLLED_HANDWRITING,
                "case_digest": "",
            }
        )  # type: ignore[arg-type]
    )
    mutated["cases"][0] = public_case_dict(rebound)
    with pytest.raises(ValueError, match="wrong public case digest"):
        _admit(plane, mutated, census)


def test_page_level_status_tamper_is_caught_by_public_digest() -> None:
    catalog, census, _labels, plane = _fixture()
    mutated = copy.deepcopy(catalog)
    mutated["cases"][0]["transcription_status"] = "UNREADABLE"
    rebound = with_bound_digest(
        PublicHandwritingCase(
            **{
                **mutated["cases"][0],
                "partition": CorpusPartition.B,
                "review_state": ReviewState.APPROVED,
                "source_layer": SourceLayer.CONTROLLED_HANDWRITING,
                "case_digest": "",
            }
        )  # type: ignore[arg-type]
    )
    mutated["cases"][0] = public_case_dict(rebound)
    with pytest.raises(ValueError, match="wrong public case digest"):
        _admit(plane, mutated, census)


def _seventy_three_handwriting_plane() -> tuple[
    dict[str, object], B0Census, AdmittedEvaluatorPlane, CorpusManifest
]:
    labels: dict[str, dict[str, object]] = {}
    cases: list[dict[str, object]] = []
    for index in range(EXPECTED_SCOREABLE_B):
        case_id = f"hw-syn-{index:03d}"
        if index == 0:
            label = _private_label(
                regions=[
                    _region(text="mix-project", region_id=f"{case_id}-a", primary_class="PROJECT"),
                    _region(
                        text="mix-meeting",
                        region_id=f"{case_id}-b",
                        primary_class="MEETING",
                        y_min=0.4,
                    ),
                ]
            )
            public = _public_case(case_id=case_id, label=label, primary_class="MEETING")
        elif index == 1:
            label = _private_label(
                regions=[
                    _region(
                        text="mix-clear",
                        region_id=f"{case_id}-a",
                        transcription_status="CLEAR",
                    ),
                    _region(
                        text="mix-uncertain",
                        region_id=f"{case_id}-b",
                        transcription_status="UNCERTAIN",
                        y_min=0.4,
                    ),
                ]
            )
            public = _public_case(case_id=case_id, label=label, transcription_status="UNCERTAIN")
        else:
            label = _private_label(text=f"note-{index:03d}", region_id=f"{case_id}-a")
            public = _public_case(case_id=case_id, label=label)
        labels[case_id] = label
        cases.append(public)
    catalog, census, _labels, plane = _catalog_from_cases(cases, labels)
    admitted = _admit(plane, catalog, census)
    manifest = CorpusManifest(
        corpus_version=HANDWRITING_CORPUS_VERSION,
        generator_version="gsqs-hw-combined-v1",
        manifest_digest=APPROVED_MANIFEST_DIGEST,
        case_count=EXPECTED_SCOREABLE_B,
        note_unit_count=sum(int(item["note_unit_count"]) for item in cases),
        partition_counts={"B": EXPECTED_SCOREABLE_B},
        case_digests={str(item["case_id"]): str(item["case_digest"]) for item in cases},
        approval_status="APPROVED",
        frozen=True,
        leakage_groups={},
    )
    return catalog, census, admitted, manifest


def test_mixed_class_v2_plane_scores_through_execute_measured_b0() -> None:
    catalog, census, admitted, manifest = _seventy_three_handwriting_plane()
    config = frozen_incumbent_config(model_identity="chatllm-model-fixture-not-live")
    documents = {
        case.case_id: _document(case, prompt=config.prompt_config_identity)
        for case in admitted.cases
    }
    records, state = execute_measured_b0(
        authorization=_fixture_auth(census, manifest, config),
        census=census,
        evaluator_cases=admitted,
        manifest=manifest,
        adapter=RecordingFakeAdapter(documents),
        config=config,
        repository=_clean_repo(),
        image_loader=None,
        catalog=catalog,
    )
    assert state is B0RunState.COMPLETE
    assert len(records) == 3
    assert all(item.measurement_valid for item in records)
    assert all(item.case_count == EXPECTED_SCOREABLE_B for item in records)
    assert {region.primary_class.value for region in admitted.cases[0].regions} == {
        "PROJECT",
        "MEETING",
    }
    assert {region.transcription_status.value for region in admitted.cases[1].regions} == {
        "CLEAR",
        "UNCERTAIN",
    }
    assert MEASURED_B0_NOT_YET_ESTABLISHED == "NOT_YET_ESTABLISHED"
