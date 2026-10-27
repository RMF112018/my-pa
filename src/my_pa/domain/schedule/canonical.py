"""CPM Workbench S5a: canonical bytes for Full-Schedule parse results.

Contract: `docs/architecture/cpm-workbench-p6-full-v1-parser-contract.md`
sections 6.2-6.5. Pure and standard-library only. No `float` reaches a
canonical object: geometry is integer millipoints written as fixed 3-decimal
strings, derived ratios are `Decimal` quantized to 6 places, durations are the
quantized `Decimal`'s string. `ScheduleParseResult.engine` is deliberately not
a key, so the digest never varies with the installed PDFium build.
"""

from __future__ import annotations

import hashlib
import json
from decimal import ROUND_HALF_EVEN, Decimal, localcontext
from typing import Final

from my_pa.domain.schedule.model import (
    ParsedScheduleRow,
    ScheduleBox,
    ScheduleCellEvidence,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleParseIssue,
    ScheduleParseResult,
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
