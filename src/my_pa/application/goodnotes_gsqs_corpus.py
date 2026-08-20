"""Versioned labeled Gate B semantic corpus: identity, freeze, partitions."""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import dataclass
from enum import StrEnum
from hashlib import sha256
from typing import Any

from my_pa.application.goodnotes_gsqs import (
    CorpusPartition,
    Geometry,
    GoldRegion,
    RankedCandidate,
)
from my_pa.domain.goodnotes.models import GoodNotesSegmentKind

CORPUS_VERSION_V1 = "gsqs-v1"
LABEL_PROVENANCE_SYNTHETIC = "SYNTHETIC_DETERMINISTIC"
LABEL_PROVENANCE_OPERATOR = "OPERATOR_ADJUDICATED"
REVIEW_APPROVED = "APPROVED"
REVIEW_PENDING = "PENDING"
REVIEW_REJECTED = "REJECTED"
REVIEW_AMBIGUOUS_EXCLUDE = "AMBIGUOUS_EXCLUDE"
FIXTURE_CLASSIFICATION = "SYNTHETIC_NON_PERSONAL"


class LabelProvenance(StrEnum):
    SYNTHETIC_DETERMINISTIC = LABEL_PROVENANCE_SYNTHETIC
    OPERATOR_ADJUDICATED = LABEL_PROVENANCE_OPERATOR


class ReviewState(StrEnum):
    APPROVED = REVIEW_APPROVED
    PENDING = REVIEW_PENDING
    REJECTED = REVIEW_REJECTED
    AMBIGUOUS_EXCLUDE = REVIEW_AMBIGUOUS_EXCLUDE


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
    contrast: str = "normal"
    style: str = "typed-and-italic"

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
        return (
            self.review_state is ReviewState.APPROVED
            and self.label_provenance is LabelProvenance.SYNTHETIC_DETERMINISTIC
        )


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

    @property
    def note_unit_count(self) -> int:
        return sum(1 for region in self.regions if region.kind is GoodNotesSegmentKind.NOTE_UNIT)

    @property
    def scoreable(self) -> bool:
        return (
            self.review_state is ReviewState.APPROVED
            and self.label_provenance is LabelProvenance.SYNTHETIC_DETERMINISTIC
        )


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


def case_signature(regions: Sequence[GoldRegion], scenario: str) -> str:
    payload = {
        "scenario": scenario,
        "regions": [
            {
                "kind": region.kind.value,
                "box": [
                    round(region.geometry.x_min, 4),
                    round(region.geometry.y_min, 4),
                    round(region.geometry.width, 4),
                    round(region.geometry.height, 4),
                ],
                "transcription": region.transcription,
            }
            for region in regions
        ],
    }
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return sha256(encoded.encode()).hexdigest()


def prevent_partition_leakage(cases: Sequence[CorpusCase]) -> None:
    by_sig: dict[str, set[CorpusPartition]] = {}
    for case in cases:
        if not case.scoreable:
            continue
        signature = case_signature(case.regions, case.scenario)
        by_sig.setdefault(signature, set()).add(case.partition)
    leaked = {digest: parts for digest, parts in by_sig.items() if len(parts) > 1}
    if leaked:
        raise ValueError("near-duplicate cases leak across partitions")


def assign_partitions(
    drafts: Sequence[CaseDraft],
    *,
    ratios: tuple[float, float, float] = (0.50, 0.30, 0.20),
) -> dict[str, CorpusPartition]:
    """Stratified A/B/C assignment. B and C receive the first two of each stratum."""
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


def materialize_cases(
    drafts: Sequence[CaseDraft],
    partitions: Mapping[str, CorpusPartition],
    *,
    pdf_for: Callable[[CaseDraft], bytes],
    page_digest: Callable[[bytes], str],
    renderer_name: str,
    renderer_version: str,
    render_profile_version: str,
) -> tuple[CorpusCase, ...]:
    cases: list[CorpusCase] = []
    for draft in drafts:
        pdf = pdf_for(draft)
        cases.append(
            CorpusCase(
                case_id=draft.case_id,
                corpus_version=CORPUS_VERSION_V1,
                content_sha256=page_digest(pdf),
                renderer_name=renderer_name,
                renderer_version=renderer_version,
                render_profile_version=render_profile_version,
                fixture_classification=FIXTURE_CLASSIFICATION,
                provenance=f"deterministic:{draft.case_id}",
                regions=draft.regions,
                difficulty=draft.difficulty,
                scenario=draft.scenario,
                adversarial=draft.adversarial,
                label_provenance=draft.label_provenance,
                review_state=draft.review_state,
                partition=partitions[draft.case_id],
                page_bytes=pdf,
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
    case_digests = {case.case_id: _case_digest(case) for case in cases}
    partition_counts = {
        member.value: sum(1 for case in cases if case.partition is member and case.scoreable)
        for member in CorpusPartition
    }
    body = {
        "corpus_version": cases[0].corpus_version if cases else CORPUS_VERSION_V1,
        "generator_version": generator_version,
        "cases": case_digests,
        "partition_counts": partition_counts,
    }
    digest = sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    return CorpusManifest(
        corpus_version=cases[0].corpus_version if cases else CORPUS_VERSION_V1,
        generator_version=generator_version,
        manifest_digest=digest,
        case_count=len(cases),
        note_unit_count=sum(case.note_unit_count for case in cases),
        partition_counts=partition_counts,
        case_digests=case_digests,
        approval_status=approval_status,
        frozen=True,
    )


def operator_review_payload(
    cases: Sequence[CorpusCase], manifest: CorpusManifest
) -> dict[str, Any]:
    scoreable = [case for case in cases if case.scoreable]
    excluded = [case for case in cases if not case.scoreable]
    return {
        "corpus_version": manifest.corpus_version,
        "manifest_digest": manifest.manifest_digest,
        "approval_status": manifest.approval_status,
        "FIXED_LABELED_CORPUS": "READY_FOR_OPERATOR_REVIEW",
        "page_count": len(cases),
        "scoreable_page_count": len(scoreable),
        "NOTE_UNIT_count": sum(case.note_unit_count for case in cases),
        "partitions": dict(manifest.partition_counts),
        "scenarios": _counts(case.scenario for case in scoreable),
        "primary_class": _counts(
            region.primary_class.value
            for case in scoreable
            for region in case.regions
            if region.kind is GoodNotesSegmentKind.NOTE_UNIT and region.primary_class is not None
        ),
        "transcription_status": _counts(
            region.transcription_status.value
            for case in scoreable
            for region in case.regions
            if region.kind is GoodNotesSegmentKind.NOTE_UNIT
            and region.transcription_status is not None
        ),
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
        "ranking": {
            "one_candidate": sum(_ranking_kind(case, 1) for case in scoreable),
            "multi_candidate": sum(_ranking_kind(case, 2) for case in scoreable),
            "no_candidate": sum(_ranking_kind(case, 0) for case in scoreable),
        },
        "label_provenance": _counts(case.label_provenance.value for case in cases),
        "review_state": _counts(case.review_state.value for case in cases),
        "excluded_or_ambiguous": [case.case_id for case in excluded],
        "adversarial_cases": [case.case_id for case in cases if case.adversarial],
        "unresolved_ground_truth_questions": [
            case.case_id for case in cases if case.review_state is ReviewState.AMBIGUOUS_EXCLUDE
        ],
        "operator_actions": ["approve", "correct", "reject", "mark_ambiguous_exclude"],
        "FIXED_LABELED_CORPUS_APPROVED": False,
    }


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


def _case_digest(case: CorpusCase) -> str:
    payload = {
        "case_id": case.case_id,
        "content_sha256": case.content_sha256,
        "renderer_name": case.renderer_name,
        "renderer_version": case.renderer_version,
        "render_profile_version": case.render_profile_version,
        "partition": case.partition.value,
        "review_state": case.review_state.value,
        "label_digest": sha256(
            json.dumps(
                [
                    {
                        "id": region.region_id,
                        "kind": region.kind.value,
                        "transcription": region.transcription,
                    }
                    for region in case.regions
                ],
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
        ).hexdigest(),
    }
    return sha256(json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


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


def candidate(rank: int, text: str) -> RankedCandidate:
    return RankedCandidate(rank=rank, candidate=text)
