"""Handwriting evaluator-plane binding: public census, private label, scorer case.

Public case identity and private evaluator-case identity stay separate. This
module does not compare ``public_case_digest`` to ``case_digest(CorpusCase)``.
It does not sit on the RouteLLM HTTP or live NAS MCP paths.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from my_pa.application.goodnotes_gsqs import CorpusPartition, GoldRegion
from my_pa.application.goodnotes_gsqs_corpus import (
    EVALUATOR_PLANE_SCHEMA,
    FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING,
    LABEL_PROVENANCE_OPERATOR,
    CorpusCase,
    LabelProvenance,
    ReviewState,
    SourceLayer,
    canonical_dumps,
    case_digest,
    gold_region_from_payload,
    load_evaluator_plane_cases,
)
from my_pa.application.goodnotes_gsqs_hw_corpus import (
    HANDWRITING_CORPUS_VERSION,
    PublicHandwritingCase,
    private_label_digest,
    public_case_from_dict,
    with_bound_digest,
)
from my_pa.domain.goodnotes.models import GoodNotesSegmentKind

HANDWRITING_EVALUATOR_PLANE_SCHEMA = "gsqs-evaluator-plane-v2"
BINDING_KIND_CONTROLLED_HANDWRITING = "controlled_handwriting"
BINDING_KIND_SYNTHETIC_V1 = "synthetic_evaluator_plane_v1"
HANDWRITING_EVALUATOR_RENDERER_NAME = "unspecified-handwriting-evaluator"
HANDWRITING_EVALUATOR_RENDERER_VERSION = "unspecified"
HANDWRITING_EVALUATOR_RENDER_PROFILE = "unspecified"
HANDWRITING_EVALUATOR_PROVENANCE = "private-label-derived"
HANDWRITING_EVALUATOR_DIFFICULTY = ("unspecified",)
REQUIRED_V2_CASE_KEYS = (
    "case_id",
    "public_case_digest",
    "label_sha256",
    "content_sha256",
    "private_label",
)


class CensusMemberView(Protocol):
    @property
    def case_id(self) -> str: ...

    @property
    def raster_sha256(self) -> str: ...

    @property
    def case_digest(self) -> str: ...


class CensusView(Protocol):
    @property
    def corpus_version(self) -> str: ...

    @property
    def members(self) -> Sequence[CensusMemberView]: ...


@dataclass(frozen=True, slots=True)
class HandwritingBindingRecord:
    case_id: str
    public_case_digest: str
    label_sha256: str
    content_sha256: str
    private_label: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class AdmittedEvaluatorPlane:
    schema_version: str
    binding_kind: str
    corpus_version: str
    cases: tuple[CorpusCase, ...]
    records: tuple[HandwritingBindingRecord, ...]


def derived_public_summary(regions: Sequence[GoldRegion]) -> dict[str, object]:
    note_units = [region for region in regions if region.kind is GoodNotesSegmentKind.NOTE_UNIT]
    classes = {
        None if item.primary_class is None else item.primary_class.value for item in note_units
    }
    statuses = {
        None if item.transcription_status is None else item.transcription_status.value
        for item in note_units
    }
    if len(classes) > 1:
        raise ValueError("derived public summary mismatch")
    if len(statuses) > 1:
        raise ValueError("derived public summary mismatch")
    return {
        "candidate_tag_count": sum(len(region.candidate_tags) for region in regions),
        "note_unit_count": len(note_units),
        "primary_class": next(iter(classes)) if classes else None,
        "ranked_candidate_count": sum(len(region.ranked_candidates) for region in regions),
        "transcription_status": next(iter(statuses)) if statuses else None,
    }


def dump_handwriting_evaluator_plane(
    records: Sequence[HandwritingBindingRecord],
) -> dict[str, object]:
    versions = {item.case_id for item in records}
    if len(versions) != len(records):
        raise ValueError("duplicate case identity")
    return {
        "binding_kind": BINDING_KIND_CONTROLLED_HANDWRITING,
        "cases": [
            {
                "case_id": item.case_id,
                "content_sha256": item.content_sha256,
                "label_sha256": item.label_sha256,
                "private_label": dict(item.private_label),
                "public_case_digest": item.public_case_digest,
            }
            for item in records
        ],
        "corpus_version": HANDWRITING_CORPUS_VERSION,
        "schema_version": HANDWRITING_EVALUATOR_PLANE_SCHEMA,
    }


def dump_admitted_handwriting_plane(plane: AdmittedEvaluatorPlane) -> dict[str, object]:
    if plane.binding_kind != BINDING_KIND_CONTROLLED_HANDWRITING:
        raise ValueError("malformed evaluator-plane binding")
    return dump_handwriting_evaluator_plane(plane.records)


def materialize_handwriting_evaluator_plane(
    *,
    catalog: Mapping[str, object],
    census: CensusView,
    labels_by_case_id: Mapping[str, object],
) -> dict[str, object]:
    if census.corpus_version != HANDWRITING_CORPUS_VERSION:
        raise ValueError("wrong corpus version")
    by_id = _catalog_by_id(catalog)
    records: list[HandwritingBindingRecord] = []
    for member in census.members:
        raw_label = labels_by_case_id.get(member.case_id)
        if raw_label is None:
            raise ValueError("missing case")
        label = _unwrap_private_label(raw_label)
        public = _bound_catalog_case(by_id, member.case_id)
        computed = private_label_digest(label)
        records.append(
            HandwritingBindingRecord(
                case_id=member.case_id,
                public_case_digest=public.case_digest,
                label_sha256=computed,
                content_sha256=public.raster_sha256,
                private_label=label,
            )
        )
    return dump_handwriting_evaluator_plane(records)


def admit_handwriting_evaluator_plane(
    payload: Mapping[str, object],
    *,
    catalog: Mapping[str, object],
    census: CensusView,
) -> AdmittedEvaluatorPlane:
    if payload.get("schema_version") != HANDWRITING_EVALUATOR_PLANE_SCHEMA:
        raise ValueError("malformed evaluator-plane binding")
    if payload.get("binding_kind") != BINDING_KIND_CONTROLLED_HANDWRITING:
        raise ValueError("malformed evaluator-plane binding")
    if payload.get("corpus_version") != HANDWRITING_CORPUS_VERSION:
        raise ValueError("wrong corpus version")
    if census.corpus_version != HANDWRITING_CORPUS_VERSION:
        raise ValueError("wrong corpus version")
    raw_cases = payload.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("malformed evaluator-plane binding")
    ids = []
    for item in raw_cases:
        if not isinstance(item, Mapping):
            raise ValueError("malformed evaluator-plane binding")
        case_id = item.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("wrong case id")
        ids.append(case_id)
    if len(ids) != len(set(ids)):
        raise ValueError("duplicate case identity")
    if len(raw_cases) != len(census.members):
        raise ValueError("evaluator cases do not match Partition B census")
    if ids != [member.case_id for member in census.members]:
        raise ValueError("evaluator cases do not match Partition B census")
    by_id = _catalog_by_id(catalog)
    records: list[HandwritingBindingRecord] = []
    cases: list[CorpusCase] = []
    for raw, member in zip(raw_cases, census.members, strict=True):
        if not isinstance(raw, Mapping):
            raise ValueError("malformed evaluator-plane binding")
        missing = [key for key in REQUIRED_V2_CASE_KEYS if key not in raw]
        if missing:
            raise ValueError("malformed evaluator-plane binding")
        public = _bound_catalog_case(by_id, member.case_id)
        _require_scoreable_handwriting(public)
        declared_public = _required_token(raw, "public_case_digest")
        declared_label = _required_token(raw, "label_sha256")
        declared_content = _required_token(raw, "content_sha256")
        if public.case_digest != member.case_digest or declared_public != public.case_digest:
            raise ValueError("wrong public case digest")
        if declared_content != public.raster_sha256 or member.raster_sha256 != public.raster_sha256:
            raise ValueError("evaluator raster binding mismatch")
        label = _json_object(raw.get("private_label"), what="private_label")
        computed_label = private_label_digest(label)
        if declared_label != computed_label:
            raise ValueError("private label_sha256 mismatch")
        if computed_label != public.label_sha256:
            raise ValueError("substituted private gold")
        if label.get("excluded") is not False:
            raise ValueError("unscoreable evaluator case")
        if label.get("label_provenance") != LABEL_PROVENANCE_OPERATOR:
            raise ValueError("wrong label provenance")
        regions_raw = label.get("regions")
        if not isinstance(regions_raw, list) or any(
            not isinstance(item, Mapping) for item in regions_raw
        ):
            raise ValueError("malformed evaluator-plane binding")
        regions = tuple(gold_region_from_payload(item) for item in regions_raw)
        summary = derived_public_summary(regions)
        if (
            summary["note_unit_count"] != public.note_unit_count
            or summary["candidate_tag_count"] != public.candidate_tag_count
            or summary["ranked_candidate_count"] != public.ranked_candidate_count
            or summary["primary_class"] != public.primary_class
            or summary["transcription_status"] != public.transcription_status
        ):
            raise ValueError("derived public summary mismatch")
        case = _corpus_case_from_handwriting(public, regions)
        if case_digest(case) == public.case_digest:
            raise ValueError("public and private case digests must remain distinct")
        records.append(
            HandwritingBindingRecord(
                case_id=member.case_id,
                public_case_digest=public.case_digest,
                label_sha256=computed_label,
                content_sha256=public.raster_sha256,
                private_label=label,
            )
        )
        cases.append(case)
    return AdmittedEvaluatorPlane(
        schema_version=HANDWRITING_EVALUATOR_PLANE_SCHEMA,
        binding_kind=BINDING_KIND_CONTROLLED_HANDWRITING,
        corpus_version=HANDWRITING_CORPUS_VERSION,
        cases=tuple(cases),
        records=tuple(records),
    )


def admit_synthetic_evaluator_plane(
    cases: Sequence[CorpusCase],
    census: CensusView,
) -> AdmittedEvaluatorPlane:
    if census.corpus_version == HANDWRITING_CORPUS_VERSION:
        raise ValueError("handwriting census requires gsqs-evaluator-plane-v2 binding")
    from my_pa.application.goodnotes_gsqs_live_b0 import validate_evaluator_plane

    validate_evaluator_plane(cases, census)  # type: ignore[arg-type]
    return AdmittedEvaluatorPlane(
        schema_version=EVALUATOR_PLANE_SCHEMA,
        binding_kind=BINDING_KIND_SYNTHETIC_V1,
        corpus_version=census.corpus_version,
        cases=tuple(cases),
        records=(),
    )


def load_and_admit_evaluator_plane(
    path: Path,
    *,
    census: CensusView,
    catalog: Mapping[str, object] | None = None,
) -> AdmittedEvaluatorPlane:
    if path.is_symlink() or not path.is_file():
        raise ValueError("evaluator corpus is missing")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("malformed evaluator-plane binding")
    schema = payload.get("schema_version")
    if schema == EVALUATOR_PLANE_SCHEMA:
        if census.corpus_version == HANDWRITING_CORPUS_VERSION:
            raise ValueError("handwriting census requires gsqs-evaluator-plane-v2 binding")
        cases = load_evaluator_plane_cases(path)
        return admit_synthetic_evaluator_plane(cases, census)
    if schema == HANDWRITING_EVALUATOR_PLANE_SCHEMA:
        if catalog is None:
            raise ValueError("handwriting evaluator binding requires the public catalog")
        return admit_handwriting_evaluator_plane(payload, catalog=catalog, census=census)
    raise ValueError("malformed evaluator-plane binding")


def revalidate_admitted_evaluator_plane(
    plane: AdmittedEvaluatorPlane,
    *,
    census: CensusView,
    catalog: Mapping[str, object] | None = None,
) -> AdmittedEvaluatorPlane:
    if plane.binding_kind == BINDING_KIND_SYNTHETIC_V1:
        return admit_synthetic_evaluator_plane(plane.cases, census)
    if plane.binding_kind != BINDING_KIND_CONTROLLED_HANDWRITING:
        raise ValueError("malformed evaluator-plane binding")
    if catalog is None:
        raise ValueError("handwriting evaluator binding requires the public catalog")
    return admit_handwriting_evaluator_plane(
        dump_admitted_handwriting_plane(plane),
        catalog=catalog,
        census=census,
    )


def handwriting_evaluator_constants() -> dict[str, object]:
    return {
        "adversarial": False,
        "difficulty": list(HANDWRITING_EVALUATOR_DIFFICULTY),
        "provenance": HANDWRITING_EVALUATOR_PROVENANCE,
        "render_profile_version": HANDWRITING_EVALUATOR_RENDER_PROFILE,
        "renderer_name": HANDWRITING_EVALUATOR_RENDERER_NAME,
        "renderer_version": HANDWRITING_EVALUATOR_RENDERER_VERSION,
    }


def _catalog_by_id(catalog: Mapping[str, object]) -> dict[str, Mapping[str, object]]:
    raw_cases = catalog.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("catalog cases missing")
    by_id: dict[str, Mapping[str, object]] = {}
    for raw in raw_cases:
        if not isinstance(raw, Mapping):
            raise ValueError("catalog case is not an object")
        case_id = raw.get("case_id")
        if not isinstance(case_id, str) or not case_id:
            raise ValueError("wrong case id")
        if case_id in by_id:
            raise ValueError("duplicate case identity")
        by_id[case_id] = raw
    return by_id


def _bound_catalog_case(
    by_id: Mapping[str, Mapping[str, object]], case_id: str
) -> PublicHandwritingCase:
    raw = by_id.get(case_id)
    if raw is None:
        raise ValueError("missing case")
    try:
        return with_bound_digest(public_case_from_dict(raw))
    except ValueError as error:
        message = str(error)
        if "case_digest" in message:
            raise ValueError("wrong public case digest") from error
        raise


def _require_scoreable_handwriting(public: PublicHandwritingCase) -> None:
    if public.partition is not CorpusPartition.B:
        raise ValueError("wrong partition")
    if public.excluded:
        raise ValueError("unscoreable evaluator case")
    if public.review_state is not ReviewState.APPROVED:
        raise ValueError("wrong review state")
    if public.label_provenance != LABEL_PROVENANCE_OPERATOR:
        raise ValueError("wrong label provenance")
    if public.source_layer is not SourceLayer.CONTROLLED_HANDWRITING:
        raise ValueError("unscoreable evaluator case")
    if public.fixture_classification != FIXTURE_PRIVATE_OPERATOR_AUTHORIZED_REAL_HANDWRITING:
        raise ValueError("unscoreable evaluator case")


def _corpus_case_from_handwriting(
    public: PublicHandwritingCase, regions: tuple[GoldRegion, ...]
) -> CorpusCase:
    return CorpusCase(
        case_id=public.case_id,
        corpus_version=HANDWRITING_CORPUS_VERSION,
        content_sha256=public.raster_sha256,
        renderer_name=HANDWRITING_EVALUATOR_RENDERER_NAME,
        renderer_version=HANDWRITING_EVALUATOR_RENDERER_VERSION,
        render_profile_version=HANDWRITING_EVALUATOR_RENDER_PROFILE,
        fixture_classification=public.fixture_classification,
        provenance=HANDWRITING_EVALUATOR_PROVENANCE,
        regions=regions,
        difficulty=HANDWRITING_EVALUATOR_DIFFICULTY,
        scenario=public.scenario,
        adversarial=False,
        label_provenance=LabelProvenance.OPERATOR_ADJUDICATED,
        review_state=public.review_state,
        partition=public.partition,
        page_bytes=b"",
        leakage_group_id=public.leakage_group_id,
        source_layer=public.source_layer,
    )


def _unwrap_private_label(raw: object) -> dict[str, object]:
    if not isinstance(raw, Mapping):
        raise ValueError("malformed evaluator-plane binding")
    if "label" in raw:
        label = _json_object(raw.get("label"), what="private_label")
        declared = raw.get("label_sha256")
        computed = private_label_digest(label)
        if isinstance(declared, str) and declared and declared != computed:
            raise ValueError("private label_sha256 mismatch")
        return label
    return _json_object(raw, what="private_label")


def _json_object(value: object, *, what: str) -> dict[str, object]:
    if not isinstance(value, Mapping):
        raise ValueError(f"malformed evaluator-plane binding: {what}")
    loaded = json.loads(canonical_dumps(dict(value)))
    if not isinstance(loaded, dict):
        raise ValueError(f"malformed evaluator-plane binding: {what}")
    return loaded


def _required_token(payload: Mapping[str, object], key: str) -> str:
    value = payload.get(key)
    if not isinstance(value, str) or not value:
        raise ValueError("malformed evaluator-plane binding")
    return value
