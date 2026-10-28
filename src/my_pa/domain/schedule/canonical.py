"""CPM Workbench S5a: canonical bytes for Full-Schedule parse results.

Contract: `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 6.2-6.5. Pure and standard-library only. No `float` reaches a
canonical object: geometry is integer millipoints written as fixed 3-decimal
strings, derived ratios are `Decimal` quantized to 6 places, durations are the
quantized `Decimal`'s string. `ScheduleParseResult.engine` is deliberately not
a key, so the digest never varies with the installed PDFium build.

The S5b-1 foundation (`docs/architecture/cpm-workbench-foundation-contract.md`
section 5.3) adds the admission request digest and the persistence bound
check; both reuse the one canonical encoder below.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Final

from my_pa.domain.schedule.model import (
    MAX_ACTIVITY_NAME_CHARACTERS,
    MAX_CELL_EVIDENCE_BYTES,
    MAX_HIERARCHY_LABEL_CHARACTERS,
    MAX_HIERARCHY_PATH,
    MAX_PUBLISHED_ACTIVITY_ID_CHARACTERS,
    ParsedScheduleRow,
    ScheduleBox,
    ScheduleCellEvidence,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleImportRequest,
    ScheduleParseIssue,
    ScheduleParseResult,
    ScheduleRowBoundsError,
)

__all__ = [
    "CELLS_SCHEMA",
    "RESULT_SCHEMA",
    "canonical_json_bytes",
    "cell_evidence_bytes",
    "cell_evidence_object",
    "format_millipoints",
    "normalized_box_strings",
    "parse_result_object",
    "parse_result_sha256",
    "schedule_import_request_digest",
    "validate_row_for_persistence",
]

CELLS_SCHEMA: Final = "cpm-full-cells-v1"
RESULT_SCHEMA: Final = "cpm-full-parse-result-v1"

_RATIO_QUANTUM: Final = Decimal("0.000001")

_COUNT_KEYS: Final = (
    "pages",
    "rows",
    "project_summaries",
    "wbs_summaries",
    "activities",
    "milestones",
    "ambiguous",
    "chart_objects_excluded",
    "watermark_objects_excluded",
    "suppressed_objects",
    "duplicate_objects_collapsed",
    "non_embedded_font_objects",
    "issues",
    "warnings",
)


def format_millipoints(value: int) -> str:
    """`598600` -> `"598.600"`; a sign only when negative."""
    sign = "-" if value < 0 else ""
    whole, part = divmod(abs(value), 1000)
    return f"{sign}{whole}.{part:03d}"


def _ratio(numerator: int, denominator: int) -> str:
    with localcontext() as context:
        context.prec = 28
        quantized = (Decimal(numerator) / Decimal(denominator)).quantize(
            _RATIO_QUANTUM, rounding=ROUND_HALF_EVEN
        )
    if quantized.is_zero():
        quantized = Decimal(0).quantize(_RATIO_QUANTUM)
    return str(quantized)


def normalized_box_strings(box: ScheduleBox, width_mpt: int, height_mpt: int) -> list[str]:
    """R2 section 12.3: `x0/W, (H - y1)/H, x1/W, (H - y0)/H` as 6-place strings."""
    return [
        _ratio(box.x0, width_mpt),
        _ratio(height_mpt - box.y1, height_mpt),
        _ratio(box.x1, width_mpt),
        _ratio(height_mpt - box.y0, height_mpt),
    ]


def _bbox(box: ScheduleBox) -> list[str]:
    return [format_millipoints(v) for v in (box.x0, box.y0, box.x1, box.y1)]


def _cell(cell: ScheduleCellEvidence) -> dict[str, object]:
    return {
        "state": cell.state.value,
        "text": cell.text,
        "fragments": [
            {
                "raw": fragment.raw,
                "bbox": _bbox(fragment.box),
                "font": fragment.font_base_name,
                "font_size": format_millipoints(fragment.font_size_mpt),
            }
            for fragment in cell.fragments
        ],
    }


def cell_evidence_object(row: ParsedScheduleRow) -> dict[str, object]:
    """The `cpm-full-cells-v1` object for one row (contract 6.3)."""
    return {
        "schema": CELLS_SCHEMA,
        "cells": {cell.field.value: _cell(cell) for cell in row.cells},
    }


def cell_evidence_bytes(row: ParsedScheduleRow) -> bytes:
    """Canonical bytes of the row's `cpm-full-cells-v1` object.

    The parser compares their length to `max_cell_evidence_bytes`.
    """
    return canonical_json_bytes(cell_evidence_object(row))


def _duration(cell: ScheduleDurationCell) -> dict[str, object]:
    return {
        "state": cell.state.value,
        "value": None if cell.value is None else str(cell.value),
    }


def _date(cell: ScheduleDateCell) -> dict[str, object]:
    return {
        "state": cell.state.value,
        "value": None if cell.value is None else cell.value.isoformat(),
        "marker": cell.marker,
    }


def _row(row: ParsedScheduleRow) -> dict[str, object]:
    return {
        "row_ordinal": row.row_ordinal,
        "page_number": row.page_number,
        "physical_line_ordinal": row.physical_line_ordinal,
        "row_type": row.row_type.value,
        "indent_level": row.indent_level,
        "parent_row_ordinal": row.parent_row_ordinal,
        "hierarchy_path": None if row.hierarchy_path is None else list(row.hierarchy_path),
        "published_activity_id": row.published_activity_id,
        "activity_name": row.activity_name,
        "original_duration": _duration(row.original_duration),
        "remaining_duration": _duration(row.remaining_duration),
        "start": _date(row.start),
        "finish": _date(row.finish),
        "bbox_pdf": _bbox(row.box),
        "bbox_normalized": normalized_box_strings(row.box, row.page_width_mpt, row.page_height_mpt),
        "cell_evidence": cell_evidence_object(row),
        "warning_codes": [code.value for code in row.warning_codes],
    }


def _issue(issue: ScheduleParseIssue) -> dict[str, object]:
    return {
        "code": issue.code.value,
        "severity": issue.severity.value,
        "page_number": issue.page_number,
        "row_ordinal": issue.row_ordinal,
        "field": None if issue.field is None else issue.field.value,
    }


def parse_result_object(result: ScheduleParseResult) -> dict[str, object]:
    """The canonical result object (contract 6.4); `engine` is not a key."""
    return {
        "schema": RESULT_SCHEMA,
        "parser_name": result.parser_name,
        "parser_version": result.parser_version,
        "profile_id": result.profile_id,
        "profile_version": result.profile_version,
        "document_sha256": result.document_sha256,
        "document_size_bytes": result.document_size_bytes,
        "outcome": result.outcome.value,
        "published_schedule_title": result.published_schedule_title,
        "data_date": None if result.data_date is None else result.data_date.isoformat(),
        "run_date": None if result.run_date is None else result.run_date.isoformat(),
        "counts": {key: getattr(result.counts, key) for key in _COUNT_KEYS},
        "rows": [_row(row) for row in result.rows],
        "issues": [_issue(issue) for issue in result.issues],
    }


def canonical_json_bytes(obj: object) -> bytes:
    """Sorted keys, compact separators, ASCII only, no NaN, no trailing newline."""
    return json.dumps(
        obj, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("ascii")


def parse_result_sha256(result: ScheduleParseResult) -> str:
    """Lowercase hex SHA-256 of the canonical result bytes."""
    return hashlib.sha256(canonical_json_bytes(parse_result_object(result))).hexdigest()


#: Domain separation for the admission digest (contract section 5.3, D-14).
_IMPORT_REQUEST_DOMAIN: Final = b"cpm-schedule-import-v1\n"


def schedule_import_request_digest(principal_id: str, request: ScheduleImportRequest) -> str:
    """The admission request digest: everything but the idempotency key.

    The Series is named by id or by its casefold key, so two requests whose
    names differ only in case or whitespace digest equal.
    """
    expected = request.expected_data_date
    body = {
        "principal_id": principal_id,
        "request": {
            "project_id": request.project_id,
            "series_id": request.series_id,
            "series_name_key": None if request.series_name is None else request.series_name.key,
            "enrollment_id": request.enrollment_id,
            "source_object_id": request.source_object_id,
            "source_version_id": request.source_version_id,
            "publication_role": request.publication_role.value,
            "baseline_kind": None if request.baseline_kind is None else request.baseline_kind.value,
            "expected_data_date": None if expected is None else expected.isoformat(),
            "supersedes_publication_id": request.supersedes_publication_id,
        },
    }
    return hashlib.sha256(_IMPORT_REQUEST_DOMAIN + canonical_json_bytes(body)).hexdigest()


def validate_row_for_persistence(row: ParsedScheduleRow) -> None:
    """Refuse a row a stored row cannot hold, before any insert (contract 5.3).

    The per-label hierarchy bound is enforced here only: the database checks
    the path's cardinality, not each element.
    """
    if len(cell_evidence_bytes(row)) > MAX_CELL_EVIDENCE_BYTES:
        raise ScheduleRowBoundsError("a row's cell evidence exceeds 16384 canonical bytes")
    published = row.published_activity_id
    if published is not None and len(published) > MAX_PUBLISHED_ACTIVITY_ID_CHARACTERS:
        raise ScheduleRowBoundsError("a published activity id exceeds 256 characters")
    if row.activity_name is not None and len(row.activity_name) > MAX_ACTIVITY_NAME_CHARACTERS:
        raise ScheduleRowBoundsError("an activity name exceeds 2000 characters")
    path = row.hierarchy_path
    if path is not None:
        if len(path) > MAX_HIERARCHY_PATH:
            raise ScheduleRowBoundsError("a hierarchy path exceeds 32 labels")
        if any(not 1 <= len(label) <= MAX_HIERARCHY_LABEL_CHARACTERS for label in path):
            raise ScheduleRowBoundsError("a hierarchy label is 1 to 2000 characters")
