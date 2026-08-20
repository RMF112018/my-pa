"""Controlled real-handwriting corpus: inventory, public identity, no page bytes.

Source PDFs and private gold transcriptions live outside the repository.
This module hashes, deduplicates, and binds public metadata only. It does not
import PDF rasterizers or call external models.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from hashlib import sha256
from pathlib import Path
from typing import Any

from my_pa.application.goodnotes_gsqs import (
    CONTROLLED_HANDWRITING_INSUFFICIENT_EVIDENCE,
    CONTROLLED_HANDWRITING_READY_FOR_REVIEW,
    CorpusPartition,
)
from my_pa.application.goodnotes_gsqs_corpus import (
    LABEL_PROVENANCE_OPERATOR,
    ReviewState,
    SourceLayer,
    canonical_dumps,
)

HANDWRITING_CORPUS_VERSION_MOSS_V1 = "gsqs-hw-moss-v1"
HANDWRITING_CORPUS_VERSION = "gsqs-hw-combined-v1"
AUTHORIZED_SOURCE_COHORTS = ("Moss", "Kast", "Altman")
AUTHORIZED_SOURCE_ROOTS: Mapping[str, str] = {
    "Altman": "/volume1/Goodnotes-Inbox/GoodNotes/Altman/",
    "Kast": "/volume1/Goodnotes-Inbox/GoodNotes/Kast/",
    "Moss": "/volume1/Goodnotes-Inbox/GoodNotes/Moss/",
}
AUTHORIZED_SOURCE_ROOT = AUTHORIZED_SOURCE_ROOTS["Moss"]
HANDWRITING_STATE = CONTROLLED_HANDWRITING_READY_FOR_REVIEW
LABEL_PROVENANCE_FIRST_PASS = "FIRST_PASS_LOCAL_INSPECTION"  # noqa: S105
UNREADABLE_REAL_WORLD_COVERAGE_NOT_OBSERVED = "NOT_OBSERVED"
UNREADABLE_REAL_WORLD_COVERAGE_OBSERVED = "OBSERVED"
_SOURCE_ID_PREFIX = {"Altman": "a", "Kast": "k", "Moss": "m"}


def authorized_source_root() -> str:
    return AUTHORIZED_SOURCE_ROOT


def authorized_source_roots() -> dict[str, str]:
    return dict(AUTHORIZED_SOURCE_ROOTS)


B0_HANDWRITING_PAGE_FLOOR = 75
B0_HANDWRITING_NOTE_FLOOR = 125
SYNTHETIC_CORPUS_VERSION = "gsqs-v2"
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")
_FORBIDDEN_PUBLIC_KEYS = frozenset(
    {
        "page_bytes",
        "pdf_bytes",
        "png_bytes",
        "relative_path",
        "relpath",
        "source_path",
        "transcription",
    }
)
PageCounter = Callable[[Path], tuple[int, str | None]]


@dataclass(frozen=True, slots=True)
class SourcePdfRecord:
    source_id: str
    relative_path: str
    file_sha256: str
    byte_size: int
    page_count: int
    parse_status: str
    failure_reason: str | None
    exact_file_duplicate_ids: tuple[str, ...]
    source_cohort: str = ""


@dataclass(frozen=True, slots=True)
class PageRasterRecord:
    page_id: str
    raster_sha256: str
    byte_size: int
    exact_page_duplicate_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class PublicHandwritingCase:
    case_id: str
    source_id: str
    page_index: int
    file_sha256: str
    raster_sha256: str
    label_sha256: str
    case_digest: str
    leakage_group_id: str
    partition: CorpusPartition
    review_state: ReviewState
    fixture_classification: str
    source_layer: SourceLayer
    scenario: str
    style: str
    primary_class: str | None
    transcription_status: str | None
    note_unit_count: int
    excluded: bool
    exclusion_reason: str | None
    candidate_tag_count: int
    ranked_candidate_count: int
    source_cohort: str = ""
    label_provenance: str = LABEL_PROVENANCE_FIRST_PASS


def sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def inventory_pdfs(
    root: Path,
    *,
    page_counter: PageCounter,
    cohort: str = "",
    source_id_prefix: str = "src",
) -> tuple[SourcePdfRecord, ...]:
    files = sorted(path for path in root.rglob("*") if path.suffix.lower() == ".pdf")
    rows: list[SourcePdfRecord] = []
    for index, path in enumerate(files, start=1):
        source_id = f"{source_id_prefix}-{index:03d}"
        digest = sha256_file(path)
        pages, reason = page_counter(path)
        status = "ok" if reason is None else "unreadable"
        rows.append(
            SourcePdfRecord(
                source_id=source_id,
                relative_path=str(path.relative_to(root)),
                file_sha256=digest,
                byte_size=path.stat().st_size,
                page_count=pages,
                parse_status=status,
                failure_reason=reason,
                exact_file_duplicate_ids=(),
                source_cohort=cohort,
            )
        )
    return mark_exact_file_duplicates(rows)


def inventory_pdfs_across_roots(
    roots: Mapping[str, Path],
    *,
    page_counter: PageCounter,
) -> tuple[SourcePdfRecord, ...]:
    rows: list[SourcePdfRecord] = []
    for cohort in AUTHORIZED_SOURCE_COHORTS:
        root = roots.get(cohort)
        if root is None:
            continue
        prefix = _SOURCE_ID_PREFIX.get(cohort, cohort[:1].lower() or "s")
        rows.extend(
            inventory_pdfs(
                root,
                page_counter=page_counter,
                cohort=cohort,
                source_id_prefix=prefix,
            )
        )
    missing = [name for name in AUTHORIZED_SOURCE_COHORTS if name not in roots]
    if missing:
        raise ValueError(f"authorized source roots missing: {', '.join(missing)}")
    return mark_exact_file_duplicates(rows)


def mark_exact_file_duplicates(rows: Sequence[SourcePdfRecord]) -> tuple[SourcePdfRecord, ...]:
    by_hash: dict[str, list[str]] = {}
    for row in rows:
        by_hash.setdefault(row.file_sha256, []).append(row.source_id)
    return tuple(
        SourcePdfRecord(
            source_id=row.source_id,
            relative_path=row.relative_path,
            file_sha256=row.file_sha256,
            byte_size=row.byte_size,
            page_count=row.page_count,
            parse_status=row.parse_status,
            failure_reason=row.failure_reason,
            exact_file_duplicate_ids=tuple(
                sid for sid in by_hash[row.file_sha256] if sid != row.source_id
            ),
            source_cohort=row.source_cohort,
        )
        for row in rows
    )


def inventory_page_rasters(paths: Sequence[Path]) -> tuple[PageRasterRecord, ...]:
    rows: list[PageRasterRecord] = []
    by_hash: dict[str, list[str]] = {}
    for path in sorted(paths):
        digest = sha256_file(path)
        page_id = path.stem
        rows.append(
            PageRasterRecord(
                page_id=page_id,
                raster_sha256=digest,
                byte_size=path.stat().st_size,
                exact_page_duplicate_ids=(),
            )
        )
        by_hash.setdefault(digest, []).append(page_id)
    return tuple(
        PageRasterRecord(
            page_id=row.page_id,
            raster_sha256=row.raster_sha256,
            byte_size=row.byte_size,
            exact_page_duplicate_ids=tuple(
                pid for pid in by_hash[row.raster_sha256] if pid != row.page_id
            ),
        )
        for row in rows
    )


def public_source_record(row: SourcePdfRecord) -> dict[str, object]:
    return {
        "byte_size": row.byte_size,
        "exact_file_duplicate_ids": list(row.exact_file_duplicate_ids),
        "failure_reason": row.failure_reason,
        "file_sha256": row.file_sha256,
        "page_count": row.page_count,
        "parse_status": row.parse_status,
        "source_cohort": row.source_cohort,
        "source_id": row.source_id,
    }


def private_label_digest(label: Mapping[str, Any]) -> str:
    return sha256(canonical_dumps(label).encode()).hexdigest()


def bind_case(*, raster_sha256: str, label_sha256: str, public_fields: Mapping[str, Any]) -> str:
    payload = {
        "label_sha256": label_sha256,
        "public_fields": public_fields,
        "raster_sha256": raster_sha256,
    }
    return sha256(canonical_dumps(payload).encode()).hexdigest()


def public_case_digest(case: PublicHandwritingCase) -> str:
    payload = {
        "candidate_tag_count": case.candidate_tag_count,
        "case_id": case.case_id,
        "excluded": case.excluded,
        "exclusion_reason": case.exclusion_reason,
        "file_sha256": case.file_sha256,
        "fixture_classification": case.fixture_classification,
        "label_provenance": case.label_provenance,
        "label_sha256": case.label_sha256,
        "leakage_group_id": case.leakage_group_id,
        "note_unit_count": case.note_unit_count,
        "page_index": case.page_index,
        "partition": case.partition.value,
        "primary_class": case.primary_class,
        "ranked_candidate_count": case.ranked_candidate_count,
        "raster_sha256": case.raster_sha256,
        "review_state": case.review_state.value,
        "scenario": case.scenario,
        "source_cohort": case.source_cohort,
        "source_id": case.source_id,
        "source_layer": case.source_layer.value,
        "style": case.style,
        "transcription_status": case.transcription_status,
    }
    return sha256(canonical_dumps(payload).encode()).hexdigest()


def with_bound_digest(case: PublicHandwritingCase) -> PublicHandwritingCase:
    digest = public_case_digest(case)
    if case.case_digest and case.case_digest != digest:
        raise ValueError("case_digest does not match bound public fields")
    return PublicHandwritingCase(
        case_id=case.case_id,
        source_id=case.source_id,
        page_index=case.page_index,
        file_sha256=case.file_sha256,
        raster_sha256=case.raster_sha256,
        label_sha256=case.label_sha256,
        case_digest=digest,
        leakage_group_id=case.leakage_group_id,
        partition=case.partition,
        review_state=case.review_state,
        fixture_classification=case.fixture_classification,
        source_layer=case.source_layer,
        scenario=case.scenario,
        style=case.style,
        primary_class=case.primary_class,
        transcription_status=case.transcription_status,
        note_unit_count=case.note_unit_count,
        excluded=case.excluded,
        exclusion_reason=case.exclusion_reason,
        candidate_tag_count=case.candidate_tag_count,
        ranked_candidate_count=case.ranked_candidate_count,
        source_cohort=case.source_cohort,
        label_provenance=case.label_provenance,
    )


def freeze_public_manifest(
    cases: Sequence[PublicHandwritingCase],
    *,
    corpus_version: str = HANDWRITING_CORPUS_VERSION,
    synthetic_manifest_digest: str | None = None,
    exhaustive_authorized_roots: bool = False,
) -> dict[str, Any]:
    bound = tuple(with_bound_digest(case) for case in cases)
    prevent_handwriting_partition_leakage(bound)
    case_digests = {case.case_id: case.case_digest for case in bound}
    groups = _leakage_groups(bound)
    admitted = [case for case in bound if not case.excluded]
    unreadable = sum(1 for case in admitted if case.transcription_status == "UNREADABLE")
    uncertain = sum(1 for case in admitted if case.transcription_status == "UNCERTAIN")
    limitations = handwriting_b0_limitations(
        admitted_pages=len(admitted),
        note_units=sum(case.note_unit_count for case in admitted),
        unreadable=unreadable,
        uncertain=uncertain,
        source_cohorts=tuple(sorted({case.source_cohort for case in bound if case.source_cohort})),
    )
    suitable = limited_population_b0_suitable(
        bound,
        exhaustive_authorized_roots=exhaustive_authorized_roots,
    )
    state = (
        CONTROLLED_HANDWRITING_READY_FOR_REVIEW
        if suitable
        else CONTROLLED_HANDWRITING_INSUFFICIENT_EVIDENCE
    )
    body = {
        "case_digests": case_digests,
        "corpus_version": corpus_version,
        "leakage_groups": groups,
    }
    manifest_digest = sha256(canonical_dumps(body).encode()).hexdigest()
    payload = {
        "CONTROLLED_HANDWRITING_CORPUS": state,
        "FIXED_LABELED_CORPUS_APPROVED": False,
        "NOTE_UNIT_count": sum(case.note_unit_count for case in admitted),
        "admitted_handwriting_pages": len(admitted),
        "b0_limitations": list(limitations),
        "b0_suitable": suitable,
        "case_count": len(bound),
        "case_digests": case_digests,
        "combined_identity": combined_gate_b_identity(synthetic_manifest_digest, manifest_digest)
        if synthetic_manifest_digest
        else None,
        "corpus_version": corpus_version,
        "excluded_page_count": sum(1 for case in bound if case.excluded),
        "exhaustive_authorized_roots": exhaustive_authorized_roots,
        "label_review_counts": _review_counts(bound),
        "leakage_groups": groups,
        "manifest_digest": manifest_digest,
        "measurement_policy": combined_measurement_policy(),
        "partition_counts": {
            member.value: sum(1 for case in admitted if case.partition is member)
            for member in CorpusPartition
        },
        "scoreable_page_count": sum(1 for case in bound if _scoreable(case)),
        "source_cohort_counts": _cohort_counts(bound),
        "source_layer": SourceLayer.CONTROLLED_HANDWRITING.value,
        "unreadable_real_world_coverage": unreadable_real_world_coverage(unreadable),
    }
    assert_repository_safe_public_payload(payload)
    return payload


def prevent_handwriting_partition_leakage(cases: Sequence[PublicHandwritingCase]) -> None:
    by_group: dict[str, set[CorpusPartition]] = {}
    for case in cases:
        if case.excluded:
            continue
        by_group.setdefault(case.leakage_group_id, set()).add(case.partition)
    leaked = {group: parts for group, parts in by_group.items() if len(parts) > 1}
    if leaked:
        raise ValueError("leakage group spans partitions")


def account_complete_census(cases: Sequence[PublicHandwritingCase]) -> None:
    if not cases:
        raise ValueError("census is empty")
    seen: set[tuple[str, int]] = set()
    for case in cases:
        key = (case.source_id, case.page_index)
        if key in seen:
            raise ValueError("census repeats a source page")
        seen.add(key)


def limited_population_b0_suitable(
    cases: Sequence[PublicHandwritingCase],
    *,
    exhaustive_authorized_roots: bool,
) -> bool:
    if not exhaustive_authorized_roots:
        return False
    prevent_handwriting_partition_leakage(cases)
    if any(case.source_cohort not in AUTHORIZED_SOURCE_COHORTS for case in cases):
        return False
    if {case.source_cohort for case in cases} != set(AUTHORIZED_SOURCE_COHORTS):
        return False
    if any((not case.excluded) and case.review_state is ReviewState.PENDING for case in cases):
        return False
    scoreable = [case for case in cases if _scoreable(case)]
    parts = {case.partition for case in scoreable}
    return CorpusPartition.B in parts and CorpusPartition.C in parts


def unreadable_real_world_coverage(unreadable: int) -> str:
    if unreadable:
        return UNREADABLE_REAL_WORLD_COVERAGE_OBSERVED
    return UNREADABLE_REAL_WORLD_COVERAGE_NOT_OBSERVED


def handwriting_b0_limitations(
    admitted_pages: int,
    note_units: int,
    *,
    unreadable: int,
    uncertain: int,
    source_cohorts: Sequence[str] = (),
) -> tuple[str, ...]:
    limits: list[str] = []
    if admitted_pages < B0_HANDWRITING_PAGE_FLOOR:
        limits.append(
            "admitted handwriting pages below former 75-150 target; "
            "using complete authorized census"
        )
    if note_units < B0_HANDWRITING_NOTE_FLOOR:
        limits.append(
            "NOTE_UNIT count below former 125-250 target; using complete authorized census"
        )
    if unreadable == 0:
        limits.append("UNREADABLE_REAL_WORLD_COVERAGE = NOT_OBSERVED")
    if uncertain == 0:
        limits.append("no UNCERTAIN handwriting pages")
    if set(source_cohorts) and set(source_cohorts) != set(AUTHORIZED_SOURCE_COHORTS):
        limits.append("authorized source cohorts are incomplete")
    limits.append("writer concentration is high; do not claim universal handwriting accuracy")
    limits.append("B0 measures the available authorized GoodNotes handwriting corpus only")
    return tuple(limits)


def combined_measurement_policy() -> dict[str, str]:
    return {
        "aggregation": (
            "Do not pool layers into one GSQS. Report synthetic and handwriting "
            "GSQS separately. Transcription and transcription-status B0 use the "
            "handwriting layer only."
        ),
        "handwriting_layer": (
            "gsqs-hw-combined-v1 production-relevant transcription/status; "
            "gsqs-hw-moss-v1 remains historical"
        ),
        "holdout_C": "hidden from future optimizer prompts and config tuning",
        "synthetic_layer": "gsqs-v2 regression, evaluator, adversarial, schema",
        "unreadable_policy": (
            "Real-handwriting UNREADABLE is reported only when observed. "
            "Synthetic gsqs-v2 continues to test fabricated-unreadable traps."
        ),
    }


def combined_gate_b_identity(
    synthetic_manifest_digest: str | None, handwriting_manifest_digest: str
) -> str:
    return sha256(
        canonical_dumps(
            {
                "handwriting_corpus_version": HANDWRITING_CORPUS_VERSION,
                "handwriting_manifest_digest": handwriting_manifest_digest,
                "synthetic_corpus_version": SYNTHETIC_CORPUS_VERSION,
                "synthetic_manifest_digest": synthetic_manifest_digest,
            }
        ).encode()
    ).hexdigest()


def load_public_catalog(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text())
    if not isinstance(payload, dict):
        raise ValueError("public catalog must be an object")
    assert_repository_safe_public_payload(payload)
    return payload


def assert_repository_safe_public_payload(payload: Mapping[str, Any]) -> None:
    _assert_safe_node(payload)


def public_case_dict(case: PublicHandwritingCase) -> dict[str, object]:
    bound = with_bound_digest(case)
    return {
        "candidate_tag_count": bound.candidate_tag_count,
        "case_digest": bound.case_digest,
        "case_id": bound.case_id,
        "excluded": bound.excluded,
        "exclusion_reason": bound.exclusion_reason,
        "file_sha256": bound.file_sha256,
        "fixture_classification": bound.fixture_classification,
        "label_sha256": bound.label_sha256,
        "leakage_group_id": bound.leakage_group_id,
        "note_unit_count": bound.note_unit_count,
        "page_index": bound.page_index,
        "partition": bound.partition.value,
        "primary_class": bound.primary_class,
        "ranked_candidate_count": bound.ranked_candidate_count,
        "raster_sha256": bound.raster_sha256,
        "review_state": bound.review_state.value,
        "scenario": bound.scenario,
        "source_id": bound.source_id,
        "source_layer": bound.source_layer.value,
        "style": bound.style,
        "transcription_status": bound.transcription_status,
        "source_cohort": bound.source_cohort,
        "label_provenance": bound.label_provenance,
    }


def _scoreable(case: PublicHandwritingCase) -> bool:
    return (
        not case.excluded
        and case.review_state is ReviewState.APPROVED
        and case.label_provenance == LABEL_PROVENANCE_OPERATOR
        and case.source_layer is SourceLayer.CONTROLLED_HANDWRITING
    )


def _review_counts(cases: Sequence[PublicHandwritingCase]) -> dict[str, int]:
    counts = {
        "AMBIGUOUS_EXCLUDE": 0,
        "APPROVED": 0,
        "PENDING": 0,
        "REJECTED": 0,
    }
    for case in cases:
        counts[case.review_state.value] = counts.get(case.review_state.value, 0) + 1
    return counts


def _cohort_counts(cases: Sequence[PublicHandwritingCase]) -> dict[str, dict[str, int]]:
    tallies: dict[str, dict[str, int]] = {}
    for case in cases:
        bucket = tallies.setdefault(
            case.source_cohort or "unspecified",
            {"admitted": 0, "excluded": 0, "pages": 0, "scoreable": 0},
        )
        bucket["pages"] += 1
        if case.excluded:
            bucket["excluded"] += 1
        else:
            bucket["admitted"] += 1
        if _scoreable(case):
            bucket["scoreable"] += 1
    return tallies


def _leakage_groups(cases: Sequence[PublicHandwritingCase]) -> dict[str, dict[str, object]]:
    grouped: dict[str, list[PublicHandwritingCase]] = {}
    for case in cases:
        grouped.setdefault(case.leakage_group_id, []).append(case)
    manifest: dict[str, dict[str, object]] = {}
    for group_id, members in sorted(grouped.items()):
        admitted = [item for item in members if not item.excluded]
        partitions = {item.partition for item in admitted}
        if not admitted:
            partition = members[0].partition.value
        elif len(partitions) == 1:
            partition = next(iter(partitions)).value
        else:
            partition = "LEAK"
        manifest[group_id] = {
            "admitted_page_count": len(admitted),
            "case_ids": [item.case_id for item in sorted(members, key=lambda item: item.case_id)],
            "partition": partition,
        }
    return manifest


def _assert_safe_node(node: object) -> None:
    if isinstance(node, Mapping):
        for key, value in node.items():
            if not isinstance(key, str):
                raise ValueError("public catalog keys must be strings")
            if key in _FORBIDDEN_PUBLIC_KEYS:
                raise ValueError(f"private key {key} is not repository-safe")
            _assert_safe_node(value)
        return
    if isinstance(node, (list, tuple)):
        for item in node:
            _assert_safe_node(item)
        return
    if isinstance(node, str):
        lowered = node.lower()
        if "goodnotes-inbox" in lowered or "/volume1/" in lowered:
            raise ValueError("private source path is not repository-safe")
        if _EMAIL.search(node):
            raise ValueError("email is not repository-safe")
        if lowered.endswith(".png") or lowered.endswith(".pdf"):
            raise ValueError("private artifact filename is not repository-safe")
