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
import re
from collections.abc import Mapping
from datetime import date
from decimal import ROUND_HALF_EVEN, Decimal, InvalidOperation, localcontext
from typing import Final

from my_pa.domain.schedule.model import (
    MAX_ACTIVITY_NAME_CHARACTERS,
    MAX_CELL_EVIDENCE_BYTES,
    MAX_HIERARCHY_LABEL_CHARACTERS,
    MAX_HIERARCHY_PATH,
    MAX_PUBLISHED_ACTIVITY_ID_CHARACTERS,
    ROW_CELL_FIELDS,
    ParsedScheduleRow,
    ScheduleBox,
    ScheduleCellEvidence,
    ScheduleCellFragment,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleFieldCode,
    ScheduleImportRequest,
    ScheduleIssueCode,
    ScheduleIssueSeverity,
    ScheduleParseCounts,
    ScheduleParseEngine,
    ScheduleParseIssue,
    ScheduleParseResult,
    SchedulePublicationStatus,
    ScheduleRowBoundsError,
    ScheduleRowType,
)

__all__ = [
    "CELLS_SCHEMA",
    "RESULT_SCHEMA",
    "ParseResultDecodeError",
    "canonical_json_bytes",
    "cell_evidence_bytes",
    "cell_evidence_object",
    "format_millipoints",
    "normalized_box_strings",
    "parse_result_from_object",
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


# --- S5b-2: rebuilding a result from its canonical object -----------------------
#
# Contract: `docs/architecture/cpm-workbench-worker-capabilities-contract.md`
# section 3.4.6. The parse runs in a contained child process that hands the
# parent the canonical object of section 6.4 (JSON, never `pickle`: a
# compromised child must not gain code execution here). The parent rebuilds a
# `ScheduleParseResult` through the domain constructors, with exact key sets
# and closed values, and then requires the rebuilt result to re-render to the
# very object it was read from, so nothing the canonical form does not fix can
# slip through. The page dimensions travel beside the object, as the engine
# does, because the canonical row carries only the derived normalized box.


class ParseResultDecodeError(ValueError):
    """The object is not a canonical parse result. The message carries no content."""


_MILLIPOINTS: Final = re.compile(r"-?(?:0|[1-9][0-9]*)\.[0-9]{3}")
_ROW_KEYS: Final = frozenset(
    {
        "row_ordinal",
        "page_number",
        "physical_line_ordinal",
        "row_type",
        "indent_level",
        "parent_row_ordinal",
        "hierarchy_path",
        "published_activity_id",
        "activity_name",
        "original_duration",
        "remaining_duration",
        "start",
        "finish",
        "bbox_pdf",
        "bbox_normalized",
        "cell_evidence",
        "warning_codes",
    }
)
_RESULT_KEYS: Final = frozenset(
    {
        "schema",
        "parser_name",
        "parser_version",
        "profile_id",
        "profile_version",
        "document_sha256",
        "document_size_bytes",
        "outcome",
        "published_schedule_title",
        "data_date",
        "run_date",
        "counts",
        "rows",
        "issues",
    }
)
_ISSUE_KEYS: Final = frozenset({"code", "severity", "page_number", "row_ordinal", "field"})
_FRAGMENT_KEYS: Final = frozenset({"raw", "bbox", "font", "font_size"})
_CELL_KEYS: Final = frozenset({"state", "text", "fragments"})


def _refuse_decode() -> ParseResultDecodeError:
    return ParseResultDecodeError("not a canonical parse result")


def _mapping(value: object, keys: frozenset[str]) -> Mapping[str, object]:
    if not isinstance(value, dict) or set(value) != keys:
        raise _refuse_decode()
    return value


def _sequence(value: object) -> list[object]:
    if not isinstance(value, list):
        raise _refuse_decode()
    return value


def _int(value: object) -> int:
    if type(value) is not int:
        raise _refuse_decode()
    return value


def _optional_int(value: object) -> int | None:
    return None if value is None else _int(value)


def _text(value: object) -> str:
    if not isinstance(value, str):
        raise _refuse_decode()
    return value


def _optional_text(value: object) -> str | None:
    return None if value is None else _text(value)


def _optional_iso_date(value: object) -> date | None:
    return None if value is None else date.fromisoformat(_text(value))


def _millipoints(value: object) -> int:
    text = _text(value)
    if _MILLIPOINTS.fullmatch(text) is None:
        raise _refuse_decode()
    return int(text.replace(".", ""))


def _box(value: object) -> ScheduleBox:
    edges = _sequence(value)
    if len(edges) != 4:
        raise _refuse_decode()
    x0, y0, x1, y1 = (_millipoints(edge) for edge in edges)
    return ScheduleBox(x0, y0, x1, y1)


def _decoded_duration(value: object) -> ScheduleDurationCell:
    cell = _mapping(value, frozenset({"state", "value"}))
    raw = _optional_text(cell["value"])
    return ScheduleDurationCell(
        state=ScheduleCellState(_text(cell["state"])),
        value=None if raw is None else Decimal(raw),
    )


def _decoded_date(value: object) -> ScheduleDateCell:
    cell = _mapping(value, frozenset({"state", "value", "marker"}))
    return ScheduleDateCell(
        state=ScheduleCellState(_text(cell["state"])),
        value=_optional_iso_date(cell["value"]),
        marker=_optional_text(cell["marker"]),
    )


def _decoded_cells(value: object) -> tuple[ScheduleCellEvidence, ...]:
    evidence = _mapping(value, frozenset({"schema", "cells"}))
    if evidence["schema"] != CELLS_SCHEMA:
        raise _refuse_decode()
    cells = _mapping(evidence["cells"], frozenset(code.value for code in ROW_CELL_FIELDS))
    decoded: list[ScheduleCellEvidence] = []
    for field_code in ROW_CELL_FIELDS:
        cell = _mapping(cells[field_code.value], _CELL_KEYS)
        fragments = tuple(
            ScheduleCellFragment(
                raw=_text(fragment["raw"]),
                box=_box(fragment["bbox"]),
                font_base_name=_text(fragment["font"]),
                font_size_mpt=_millipoints(fragment["font_size"]),
            )
            for fragment in (
                _mapping(item, _FRAGMENT_KEYS) for item in _sequence(cell["fragments"])
            )
        )
        decoded.append(
            ScheduleCellEvidence(
                field=field_code,
                state=ScheduleCellState(_text(cell["state"])),
                text=_optional_text(cell["text"]),
                fragments=fragments,
            )
        )
    return tuple(decoded)


def _decoded_row(
    value: object, page_dimensions: Mapping[int, tuple[int, int]]
) -> ParsedScheduleRow:
    row = _mapping(value, _ROW_KEYS)
    page_number = _int(row["page_number"])
    if page_number not in page_dimensions:
        raise _refuse_decode()
    width, height = page_dimensions[page_number]
    path = row["hierarchy_path"]
    return ParsedScheduleRow(
        row_ordinal=_int(row["row_ordinal"]),
        page_number=page_number,
        physical_line_ordinal=_int(row["physical_line_ordinal"]),
        row_type=ScheduleRowType(_text(row["row_type"])),
        indent_level=_optional_int(row["indent_level"]),
        parent_row_ordinal=_optional_int(row["parent_row_ordinal"]),
        hierarchy_path=None if path is None else tuple(_text(label) for label in _sequence(path)),
        published_activity_id=_optional_text(row["published_activity_id"]),
        activity_name=_optional_text(row["activity_name"]),
        original_duration=_decoded_duration(row["original_duration"]),
        remaining_duration=_decoded_duration(row["remaining_duration"]),
        start=_decoded_date(row["start"]),
        finish=_decoded_date(row["finish"]),
        box=_box(row["bbox_pdf"]),
        page_width_mpt=width,
        page_height_mpt=height,
        cells=_decoded_cells(row["cell_evidence"]),
        warning_codes=tuple(
            ScheduleIssueCode(_text(code)) for code in _sequence(row["warning_codes"])
        ),
    )


def _decoded_issue(value: object) -> ScheduleParseIssue:
    issue = _mapping(value, _ISSUE_KEYS)
    field_code = _optional_text(issue["field"])
    return ScheduleParseIssue(
        code=ScheduleIssueCode(_text(issue["code"])),
        severity=ScheduleIssueSeverity(_text(issue["severity"])),
        page_number=_optional_int(issue["page_number"]),
        row_ordinal=_optional_int(issue["row_ordinal"]),
        field=None if field_code is None else ScheduleFieldCode(field_code),
    )


def _decoded_result(
    obj: object,
    engine: ScheduleParseEngine,
    page_dimensions: Mapping[int, tuple[int, int]],
) -> ScheduleParseResult:
    result = _mapping(obj, _RESULT_KEYS)
    if result["schema"] != RESULT_SCHEMA:
        raise _refuse_decode()
    counts = _mapping(result["counts"], frozenset(_COUNT_KEYS))
    rows = tuple(_decoded_row(row, page_dimensions) for row in _sequence(result["rows"]))
    if {row.page_number for row in rows} != set(page_dimensions):
        raise _refuse_decode()
    return ScheduleParseResult(
        parser_name=_text(result["parser_name"]),
        parser_version=_text(result["parser_version"]),
        profile_id=_text(result["profile_id"]),
        profile_version=_int(result["profile_version"]),
        document_sha256=_text(result["document_sha256"]),
        document_size_bytes=_int(result["document_size_bytes"]),
        outcome=SchedulePublicationStatus(_text(result["outcome"])),
        published_schedule_title=_optional_text(result["published_schedule_title"]),
        data_date=_optional_iso_date(result["data_date"]),
        run_date=_optional_iso_date(result["run_date"]),
        counts=ScheduleParseCounts(**{key: _int(counts[key]) for key in _COUNT_KEYS}),
        rows=rows,
        issues=tuple(_decoded_issue(issue) for issue in _sequence(result["issues"])),
        engine=engine,
    )


def parse_result_from_object(
    obj: object,
    engine: ScheduleParseEngine,
    page_dimensions: Mapping[int, tuple[int, int]],
) -> ScheduleParseResult:
    """Rebuild the result whose canonical object is `obj`, or refuse.

    `page_dimensions` maps every page a row is on (and no other) to its
    measured `(width_mpt, height_mpt)`. Every value is rebuilt through the
    domain constructors, and the rebuilt result must re-render to exactly
    `obj`'s canonical bytes. Any refusal is `ParseResultDecodeError`, whose
    message carries nothing of the object.
    """
    try:
        rebuilt = _decoded_result(obj, engine, page_dimensions)
        if canonical_json_bytes(parse_result_object(rebuilt)) != canonical_json_bytes(obj):
            raise _refuse_decode()
    except ParseResultDecodeError:
        raise
    except (ValueError, TypeError, KeyError, InvalidOperation, OverflowError):
        raise _refuse_decode() from None
    return rebuilt
