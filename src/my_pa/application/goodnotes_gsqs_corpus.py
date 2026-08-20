"""Versioned labeled Gate B semantic corpus: identity, freeze, partitions."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from hashlib import sha256
from typing import Any

from my_pa.application.goodnotes_gsqs import (
    AUTOMATIC_PROMOTION_DISABLED,
    CONTROLLED_HANDWRITING_READY_FOR_OPERATOR_INPUT,
    CONTROLLED_HANDWRITING_READY_FOR_REVIEW,
    EVALUATOR_NAME,
    EVALUATOR_VERSION,
    GATE_B_STATE,
    MEASURED_B0_NOT_YET_ESTABLISHED,
    SELF_IMPROVEMENT_NOT_YET_ACTIVATED,
    Confidence,
    CorpusPartition,
    Geometry,
    GoldRegion,
    RankedCandidate,
    evaluator_code_identity,
)
from my_pa.domain.goodnotes.models import GoodNotesSegmentKind

CORPUS_VERSION_V1 = "gsqs-v1"
CORPUS_VERSION_V2 = "gsqs-v2"
LABEL_PROVENANCE_SYNTHETIC = "SYNTHETIC_DETERMINISTIC"
LABEL_PROVENANCE_OPERATOR = "OPERATOR_ADJUDICATED"
REVIEW_APPROVED = "APPROVED"
REVIEW_PENDING = "PENDING"
REVIEW_REJECTED = "REJECTED"
REVIEW_AMBIGUOUS_EXCLUDE = "AMBIGUOUS_EXCLUDE"
FIXTURE_SYNTHETIC_NON_PERSONAL = "SYNTHETIC_NON_PERSONAL"
FIXTURE_SYNTHETIC_NON_PERSONAL_HANDWRITING = "SYNTHETIC_NON_PERSONAL_HANDWRITING"
FIXTURE_PRODUCTION_GOODNOTES = "PRODUCTION_GOODNOTES"
FIXTURE_CLASSIFICATION = FIXTURE_SYNTHETIC_NON_PERSONAL
V1_B0_DISPOSITION = "REJECT_FOR_B0"


class LabelProvenance(StrEnum):
    SYNTHETIC_DETERMINISTIC = LABEL_PROVENANCE_SYNTHETIC
    OPERATOR_ADJUDICATED = LABEL_PROVENANCE_OPERATOR


class ReviewState(StrEnum):
    APPROVED = REVIEW_APPROVED
    PENDING = REVIEW_PENDING
    REJECTED = REVIEW_REJECTED
    AMBIGUOUS_EXCLUDE = REVIEW_AMBIGUOUS_EXCLUDE


class SourceLayer(StrEnum):
    SYNTHETIC_REGRESSION = "SYNTHETIC_REGRESSION"
    CONTROLLED_HANDWRITING = "CONTROLLED_HANDWRITING"


_FORBIDDEN_FIXTURE_CLASSES = frozenset(
    {
        FIXTURE_PRODUCTION_GOODNOTES,
        "LIVE_GOODNOTES",
        "PERSONAL_HANDWRITING",
        "ORDINARY_PRODUCTION_GOODNOTES",
    }
)


@dataclass(frozen=True, slots=True)
class CaseDraft:
    case_id: str
    scenario: str
    family: str
    difficulty: tuple[str, ...]
    adversarial: bool
    label_provenance: LabelProvenance
    review_state: ReviewState
    regions: tuple[GoldRegion, ...]
    title: str
    leakage_group_id: str
    contrast: str = "normal"
    style: str = "typed-and-italic"
    source_layer: SourceLayer = SourceLayer.SYNTHETIC_REGRESSION
    fixture_classification: str = FIXTURE_SYNTHETIC_NON_PERSONAL

    @property
    def class_key(self) -> str:
        for region in self.regions:
            if region.kind is GoodNotesSegmentKind.NOTE_UNIT and region.primary_class is not None:
                return region.primary_class.value
        return "NONE"

    @property
    def status_key(self) -> str:
        for region in self.regions:
            if (
                region.kind is GoodNotesSegmentKind.NOTE_UNIT
                and region.transcription_status is not None
            ):
                return region.transcription_status.value
        return "NONE"

    @property
    def scoreable(self) -> bool:
        if self.review_state is not ReviewState.APPROVED:
            return False
        if self.source_layer is SourceLayer.SYNTHETIC_REGRESSION:
            return self.label_provenance is LabelProvenance.SYNTHETIC_DETERMINISTIC
        return self.label_provenance is LabelProvenance.OPERATOR_ADJUDICATED


@dataclass(frozen=True, slots=True)
class CorpusCase:
    case_id: str
    corpus_version: str
    content_sha256: str
    renderer_name: str
    renderer_version: str
    render_profile_version: str
    fixture_classification: str
    provenance: str
    regions: tuple[GoldRegion, ...]
    difficulty: tuple[str, ...]
    scenario: str
    adversarial: bool
    label_provenance: LabelProvenance
    review_state: ReviewState
    partition: CorpusPartition
    page_bytes: bytes
    leakage_group_id: str
    source_layer: SourceLayer = SourceLayer.SYNTHETIC_REGRESSION

    @property
    def note_unit_count(self) -> int:
        return sum(1 for region in self.regions if region.kind is GoodNotesSegmentKind.NOTE_UNIT)

    @property
    def scoreable(self) -> bool:
        if self.review_state is not ReviewState.APPROVED:
            return False
        if self.source_layer is SourceLayer.SYNTHETIC_REGRESSION:
            return self.label_provenance is LabelProvenance.SYNTHETIC_DETERMINISTIC
        return self.label_provenance is LabelProvenance.OPERATOR_ADJUDICATED


@dataclass(frozen=True, slots=True)
class CorpusManifest:
    corpus_version: str
    generator_version: str
    manifest_digest: str
    case_count: int
    note_unit_count: int
    partition_counts: Mapping[str, int]
    case_digests: Mapping[str, str]
    approval_status: str
    frozen: bool
    leakage_groups: Mapping[str, Mapping[str, object]]


def canonical_dumps(value: object) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def gold_region_payload(region: GoldRegion) -> dict[str, object]:
    confidence = region.reference_confidence
    return {
        "candidate_tags": list(region.candidate_tags),
        "contains_embedded_instructions": region.contains_embedded_instructions,
        "geometry": {
            "height": region.geometry.height,
            "width": region.geometry.width,
            "x_min": region.geometry.x_min,
            "y_min": region.geometry.y_min,
        },
        "kind": region.kind.value,
        "no_association_correct": region.no_association_correct,
        "primary_class": None if region.primary_class is None else region.primary_class.value,
        "ranked_candidates": [
            {"candidate": item.candidate, "rank": item.rank} for item in region.ranked_candidates
        ],
        "reference_confidence": None
        if confidence is None
        else {
            "classification": confidence.classification,
            "linking": confidence.linking,
            "segmentation": confidence.segmentation,
            "transcription": confidence.transcription,
            "uncertainty": confidence.uncertainty,
        },
        "region_id": region.region_id,
        "transcription": region.transcription,
        "transcription_status": None
        if region.transcription_status is None
        else region.transcription_status.value,
    }


def case_digest_payload(case: CorpusCase) -> dict[str, object]:
    return {
        "adversarial": case.adversarial,
        "case_id": case.case_id,
        "content_sha256": case.content_sha256,
        "corpus_version": case.corpus_version,
        "difficulty": list(case.difficulty),
        "fixture_classification": case.fixture_classification,
        "label_provenance": case.label_provenance.value,
        "leakage_group_id": case.leakage_group_id,
        "partition": case.partition.value,
        "provenance": case.provenance,
        "regions": [gold_region_payload(region) for region in case.regions],
        "render_profile_version": case.render_profile_version,
        "renderer_name": case.renderer_name,
        "renderer_version": case.renderer_version,
        "review_state": case.review_state.value,
        "scenario": case.scenario,
        "source_layer": case.source_layer.value,
    }


def case_digest(case: CorpusCase) -> str:
    return sha256(canonical_dumps(case_digest_payload(case)).encode()).hexdigest()


def case_signature(regions: Sequence[GoldRegion], scenario: str) -> str:
    payload = {"regions": [gold_region_payload(region) for region in regions], "scenario": scenario}
    return sha256(canonical_dumps(payload).encode()).hexdigest()


def prevent_partition_leakage(cases: Sequence[CorpusCase]) -> None:
    by_group: dict[str, set[CorpusPartition]] = {}
    for case in cases:
        if not case.scoreable:
            continue
        if not case.leakage_group_id:
            raise ValueError("scoreable cases require leakage_group_id")
        by_group.setdefault(case.leakage_group_id, set()).add(case.partition)
    leaked = {group: parts for group, parts in by_group.items() if len(parts) > 1}
    if leaked:
        raise ValueError("leakage group spans partitions")


def assign_partitions(
    drafts: Sequence[CaseDraft],
    *,
    ratios: tuple[float, float, float] = (0.50, 0.30, 0.20),
) -> dict[str, CorpusPartition]:
    """v1 canary assignment. Replica siblings can split; v1 is REJECT_FOR_B0."""
    del ratios
    assigned: dict[str, CorpusPartition] = {}
    strata: dict[str, list[str]] = {}
    for draft in drafts:
        if not draft.scoreable:
            assigned[draft.case_id] = CorpusPartition.A
            continue
        key = f"{draft.family}|{draft.class_key}|{draft.status_key}"
        strata.setdefault(key, []).append(draft.case_id)
    for case_ids in strata.values():
        for index, case_id in enumerate(sorted(case_ids)):
            if index == 0:
                assigned[case_id] = CorpusPartition.B
            elif index == 1:
                assigned[case_id] = CorpusPartition.C
            else:
                assigned[case_id] = CorpusPartition.A
    records = tuple(
        (draft.case_id, draft.family, draft.class_key, draft.status_key, draft.scoreable)
        for draft in drafts
    )
    _assert_bc_coverage(records, assigned)
    return assigned


def assign_partitions_by_group(
    drafts: Sequence[CaseDraft],
) -> dict[str, CorpusPartition]:
    """Group-level A/B/C: every leakage_group_id occupies exactly one partition.

    Scoreable groups are stratified by scenario|class|status. Within each
    stratum, sorted group ids assign first → B, second → C, remainder → A.
    Non-scoreable groups go to A and are not scored.
    """
    grouped: dict[str, list[CaseDraft]] = {}
    for draft in drafts:
        if not draft.leakage_group_id:
            raise ValueError("drafts require leakage_group_id")
        grouped.setdefault(draft.leakage_group_id, []).append(draft)
    assigned: dict[str, CorpusPartition] = {}
    strata: dict[str, list[str]] = {}
    for group_id, members in grouped.items():
        if not any(item.scoreable for item in members):
            for item in members:
                assigned[item.case_id] = CorpusPartition.A
            continue
        representative = sorted(members, key=lambda item: item.case_id)[0]
        key = f"{representative.scenario}|{representative.class_key}|{representative.status_key}"
        strata.setdefault(key, []).append(group_id)
    group_partition: dict[str, CorpusPartition] = {}
    for group_ids in strata.values():
        for index, group_id in enumerate(sorted(group_ids)):
            if index == 0:
                group_partition[group_id] = CorpusPartition.B
            elif index == 1:
                group_partition[group_id] = CorpusPartition.C
            else:
                group_partition[group_id] = CorpusPartition.A
    for group_id, members in grouped.items():
        if group_id not in group_partition:
            continue
        partition = group_partition[group_id]
        for item in members:
            assigned[item.case_id] = partition
    records = tuple(
        (draft.case_id, draft.family, draft.class_key, draft.status_key, draft.scoreable)
        for draft in drafts
    )
    _assert_bc_coverage(records, assigned)
    _assert_group_isolation(drafts, assigned)
    _assert_bc_scenario_coverage(drafts, assigned)
    return assigned


def materialize_cases(
    drafts: Sequence[CaseDraft],
    partitions: Mapping[str, CorpusPartition],
    *,
    pdf_for: Callable[[CaseDraft], bytes],
    page_digest: Callable[[bytes], str],
    renderer_name: str,
    renderer_version: str,
    render_profile_version: str,
    corpus_version: str,
) -> tuple[CorpusCase, ...]:
    cases: list[CorpusCase] = []
    for draft in drafts:
        pdf = pdf_for(draft)
        cases.append(
            CorpusCase(
                case_id=draft.case_id,
                corpus_version=corpus_version,
                content_sha256=page_digest(pdf),
                renderer_name=renderer_name,
                renderer_version=renderer_version,
                render_profile_version=render_profile_version,
                fixture_classification=draft.fixture_classification,
                provenance=f"deterministic:{draft.case_id}",
                regions=draft.regions,
                difficulty=draft.difficulty,
                scenario=draft.scenario,
                adversarial=draft.adversarial,
                label_provenance=draft.label_provenance,
                review_state=draft.review_state,
                partition=partitions[draft.case_id],
                page_bytes=pdf,
                leakage_group_id=draft.leakage_group_id,
                source_layer=draft.source_layer,
            )
        )
    return tuple(cases)


def freeze_manifest(
    cases: Sequence[CorpusCase],
    *,
    generator_version: str,
    approval_status: str,
) -> CorpusManifest:
    prevent_partition_leakage(cases)
    case_digests = {case.case_id: case_digest(case) for case in cases}
    partition_counts = {
        member.value: sum(1 for case in cases if case.partition is member and case.scoreable)
        for member in CorpusPartition
    }
    leakage_groups = _leakage_group_manifest(cases)
    body = {
        "cases": case_digests,
        "corpus_version": cases[0].corpus_version if cases else CORPUS_VERSION_V2,
        "generator_version": generator_version,
        "leakage_groups": leakage_groups,
        "partition_counts": partition_counts,
    }
    digest = sha256(canonical_dumps(body).encode()).hexdigest()
    return CorpusManifest(
        corpus_version=cases[0].corpus_version if cases else CORPUS_VERSION_V2,
        generator_version=generator_version,
        manifest_digest=digest,
        case_count=len(cases),
        note_unit_count=sum(case.note_unit_count for case in cases),
        partition_counts=partition_counts,
        case_digests=case_digests,
        approval_status=approval_status,
        frozen=True,
        leakage_groups=leakage_groups,
    )


def operator_review_payload(
    cases: Sequence[CorpusCase], manifest: CorpusManifest
) -> dict[str, Any]:
    scoreable = [case for case in cases if case.scoreable]
    excluded = [case for case in cases if not case.scoreable]
    handwriting = [
        case for case in cases if case.source_layer is SourceLayer.CONTROLLED_HANDWRITING
    ]
    synthetic = [case for case in cases if case.source_layer is SourceLayer.SYNTHETIC_REGRESSION]
    group_partitions = {
        group_id: str(body["partition"]) for group_id, body in manifest.leakage_groups.items()
    }
    return {
        "AUTOMATIC_PROMOTION": AUTOMATIC_PROMOTION_DISABLED,
        "CONTROLLED_HANDWRITING_CORPUS": (
            CONTROLLED_HANDWRITING_READY_FOR_REVIEW
            if handwriting
            else CONTROLLED_HANDWRITING_READY_FOR_OPERATOR_INPUT
        ),
        "FIXED_LABELED_CORPUS": "READY_FOR_OPERATOR_REVIEW",
        "FIXED_LABELED_CORPUS_APPROVED": False,
        "GATE_B_STATE": dict(GATE_B_STATE),
        "GSQS_V1_B0_DISPOSITION": V1_B0_DISPOSITION
        if manifest.corpus_version == CORPUS_VERSION_V1
        else "NOT_APPLICABLE",
        "MEASURED_B0": MEASURED_B0_NOT_YET_ESTABLISHED,
        "NOTE_UNIT_count": sum(case.note_unit_count for case in cases),
        "adversarial_cases": [case.case_id for case in cases if case.adversarial],
        "approval_status": manifest.approval_status,
        "b0_suitable": False,
        "controlled_handwriting_count": len(handwriting),
        "controlled_handwriting_present": bool(handwriting),
        "corpus_version": manifest.corpus_version,
        "evaluator_code_identity": evaluator_code_identity(),
        "evaluator_name": EVALUATOR_NAME,
        "evaluator_version": EVALUATOR_VERSION,
        "excluded_or_ambiguous": [case.case_id for case in excluded],
        "label_provenance": _counts(case.label_provenance.value for case in cases),
        "leakage_group_counts": {
            member.value: sum(
                1 for partition in group_partitions.values() if partition == member.value
            )
            for member in CorpusPartition
        },
        "leakage_group_intersections_empty": _group_intersections_empty(group_partitions),
        "manifest_digest": manifest.manifest_digest,
        "operator_actions": ["approve", "correct", "reject", "mark_ambiguous_exclude"],
        "page_count": len(cases),
        "partition_distributions": _partition_distributions(scoreable),
        "partitions": dict(manifest.partition_counts),
        "primary_class": _counts(
            region.primary_class.value
            for case in scoreable
            for region in case.regions
            if region.kind is GoodNotesSegmentKind.NOTE_UNIT and region.primary_class is not None
        ),
        "ranking": {
            "one_candidate": sum(_ranking_kind(case, 1) for case in scoreable),
            "multi_candidate": sum(_ranking_kind(case, 2) for case in scoreable),
            "no_candidate": sum(_ranking_kind(case, 0) for case in scoreable),
        },
        "personal_data": False,
        "regression_only_until_handwriting_admitted": not handwriting,
        "review_state": _counts(case.review_state.value for case in cases),
        "SELF_IMPROVEMENT_EVALUATION": SELF_IMPROVEMENT_NOT_YET_ACTIVATED,
        "scenarios": _counts(case.scenario for case in scoreable),
        "scoreable_page_count": len(scoreable),
        "source_layer": _counts(case.source_layer.value for case in cases),
        "synthetic_regression_count": len(synthetic),
        "tag_presence": {
            "with_tags": sum(
                1
                for case in scoreable
                for region in case.regions
                if region.kind is GoodNotesSegmentKind.NOTE_UNIT and region.candidate_tags
            ),
            "without_tags": sum(
                1
                for case in scoreable
                for region in case.regions
                if region.kind is GoodNotesSegmentKind.NOTE_UNIT and not region.candidate_tags
            ),
        },
        "transcription_status": _counts(
            region.transcription_status.value
            for case in scoreable
            for region in case.regions
            if region.kind is GoodNotesSegmentKind.NOTE_UNIT
            and region.transcription_status is not None
        ),
        "unresolved_ground_truth_questions": [
            case.case_id for case in cases if case.review_state is ReviewState.AMBIGUOUS_EXCLUDE
        ],
    }


def case_index_payload(cases: Sequence[CorpusCase], manifest: CorpusManifest) -> dict[str, Any]:
    rows: list[dict[str, object]] = []
    for case in cases:
        notes = [region for region in case.regions if region.kind is GoodNotesSegmentKind.NOTE_UNIT]
        rows.append(
            {
                "NOTE_UNIT_count": case.note_unit_count,
                "adversarial": case.adversarial,
                "case_id": case.case_id,
                "content_sha256": case.content_sha256,
                "difficulty": list(case.difficulty),
                "fixture_classification": case.fixture_classification,
                "label_provenance": case.label_provenance.value,
                "leakage_group_id": case.leakage_group_id,
                "partition": case.partition.value,
                "primary_classes": [
                    region.primary_class.value
                    for region in notes
                    if region.primary_class is not None
                ],
                "review_state": case.review_state.value,
                "scenario": case.scenario,
                "scoreable": case.scoreable,
                "source_layer": case.source_layer.value,
                "transcription_statuses": [
                    region.transcription_status.value
                    for region in notes
                    if region.transcription_status is not None
                ],
            }
        )
    return {
        "approval_status": manifest.approval_status,
        "cases": rows,
        "corpus_version": manifest.corpus_version,
        "generator_version": manifest.generator_version,
        "leakage_groups": dict(manifest.leakage_groups),
        "manifest_digest": manifest.manifest_digest,
    }


def candidate(rank: int, text: str) -> RankedCandidate:
    return RankedCandidate(rank=rank, candidate=text)


def gold_for_partition(
    cases: Sequence[CorpusCase], partition: CorpusPartition
) -> tuple[tuple[str, tuple[GoldRegion, ...]], ...]:
    selected = tuple(
        (case.case_id, case.regions)
        for case in cases
        if case.partition is partition and case.scoreable
    )
    if not selected:
        raise ValueError("partition has no scoreable cases")
    return selected


def mutate_case(case: CorpusCase, **changes: object) -> CorpusCase:
    return replace(case, **changes)  # type: ignore[arg-type]


def mutate_region(region: GoldRegion, **changes: object) -> GoldRegion:
    return replace(region, **changes)  # type: ignore[arg-type]


def mutate_geometry(geometry: Geometry, **changes: float) -> Geometry:
    return replace(geometry, **changes)


def mutate_confidence(confidence: Confidence, **changes: object) -> Confidence:
    return replace(confidence, **changes)  # type: ignore[arg-type]


def _leakage_group_manifest(cases: Sequence[CorpusCase]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[CorpusCase]] = {}
    for case in cases:
        grouped.setdefault(case.leakage_group_id, []).append(case)
    manifest: dict[str, dict[str, object]] = {}
    for group_id, members in sorted(grouped.items()):
        partitions = {item.partition for item in members}
        partition = next(iter(partitions)).value if len(partitions) == 1 else "LEAK"
        manifest[group_id] = {
            "case_ids": [item.case_id for item in sorted(members, key=lambda item: item.case_id)],
            "partition": partition,
            "scoreable": any(item.scoreable for item in members),
        }
    return manifest


def _group_intersections_empty(group_partitions: Mapping[str, str]) -> bool:
    buckets: dict[str, set[str]] = {member.value: set() for member in CorpusPartition}
    for group_id, partition in group_partitions.items():
        buckets[partition].add(group_id)
    return (
        not (buckets["A"] & buckets["B"])
        and not (buckets["A"] & buckets["C"])
        and not (buckets["B"] & buckets["C"])
    )


def _partition_distributions(scoreable: Sequence[CorpusCase]) -> dict[str, dict[str, object]]:
    result: dict[str, dict[str, object]] = {}
    for member in CorpusPartition:
        selected = [case for case in scoreable if case.partition is member]
        result[member.value] = {
            "NOTE_UNIT_count": sum(case.note_unit_count for case in selected),
            "page_count": len(selected),
            "primary_class": _counts(
                region.primary_class.value
                for case in selected
                for region in case.regions
                if region.kind is GoodNotesSegmentKind.NOTE_UNIT
                and region.primary_class is not None
            ),
            "scenarios": _counts(case.scenario for case in selected),
            "transcription_status": _counts(
                region.transcription_status.value
                for case in selected
                for region in case.regions
                if region.kind is GoodNotesSegmentKind.NOTE_UNIT
                and region.transcription_status is not None
            ),
        }
    return result


def _counts(values: Iterable[object]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for value in values:
        counts[str(value)] = counts.get(str(value), 0) + 1
    return dict(sorted(counts.items()))


def _ranking_kind(case: CorpusCase, kind: int) -> int:
    total = 0
    for region in case.regions:
        if region.kind is not GoodNotesSegmentKind.NOTE_UNIT:
            continue
        count = len(region.ranked_candidates)
        if (
            (kind == 0 and (region.no_association_correct or count == 0))
            or (kind == 1 and count == 1)
            or (kind == 2 and count >= 2)
        ):
            total += 1
    return total


def _assert_group_isolation(
    drafts: Sequence[CaseDraft], assigned: Mapping[str, CorpusPartition]
) -> None:
    by_group: dict[str, set[CorpusPartition]] = {}
    for draft in drafts:
        if not draft.scoreable:
            continue
        by_group.setdefault(draft.leakage_group_id, set()).add(assigned[draft.case_id])
    leaked = {group: parts for group, parts in by_group.items() if len(parts) > 1}
    if leaked:
        raise ValueError("leakage group spans partitions")


def _assert_bc_scenario_coverage(
    drafts: Sequence[CaseDraft], assigned: Mapping[str, CorpusPartition]
) -> None:
    required = {
        "context-only",
        "prompt-injection",
        "obscured-trap",
        "one-candidate",
        "multi-tag",
        "no-tag",
    }
    for partition in (CorpusPartition.B, CorpusPartition.C):
        scenarios = {
            draft.scenario
            for draft in drafts
            if draft.scoreable and assigned[draft.case_id] is partition
        }
        missing = required - scenarios
        if missing:
            raise ValueError(f"partition {partition.value} missing scenarios {sorted(missing)}")


def _assert_bc_coverage(
    records: Sequence[tuple[str, str, str, str, bool]],
    assigned: Mapping[str, CorpusPartition],
) -> None:
    for partition in (CorpusPartition.B, CorpusPartition.C):
        class_keys = {
            class_key
            for case_id, _family, class_key, _status, scoreable in records
            if scoreable and assigned[case_id] is partition and class_key != "NONE"
        }
        status_keys = {
            status_key
            for case_id, _family, _class_key, status_key, scoreable in records
            if scoreable and assigned[case_id] is partition and status_key != "NONE"
        }
        if {"MEETING", "PROJECT", "RELATIONSHIP", "GENERAL"} - class_keys:
            raise ValueError(f"partition {partition.value} missing a primary class")
        if {"CLEAR", "UNCERTAIN", "UNREADABLE"} - status_keys:
            raise ValueError(f"partition {partition.value} missing a transcription status")
        context_only = {
            case_id
            for case_id, _family, class_key, _status, scoreable in records
            if scoreable and assigned[case_id] is partition and class_key == "NONE"
        }
        corpus_has_context = any(
            scoreable and class_key == "NONE" for _cid, _f, class_key, _s, scoreable in records
        )
        if corpus_has_context and not context_only:
            raise ValueError(f"partition {partition.value} missing a context-only page")


def box(x_min: float, y_min: float, width: float, height: float) -> Geometry:
    return Geometry(x_min=x_min, y_min=y_min, width=width, height=height)


def refuse_production_fixture(classification: str) -> None:
    if classification in _FORBIDDEN_FIXTURE_CLASSES:
        raise ValueError("production/live GoodNotes cannot be admitted through evaluation fixtures")
