"""The S5b-1 foundation domain: IDs, enums, records, names, digest, bounds, status.

FAST: no database. Contract `docs/architecture/cpm-workbench-foundation-contract.md`
sections 3.1, 4.10.4 and 5.1-5.3. Every value here is synthetic.
"""

from __future__ import annotations

import dataclasses
import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

import pytest

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError
from my_pa.domain.schedule import (
    ISSUE_SEVERITY,
    MAX_CELL_EVIDENCE_BYTES,
    ROW_CELL_FIELDS,
    SCHEDULE_IDEMPOTENCY_KEY_PATTERN,
    SCHEDULE_MEDIA_TYPE,
    TERMINAL_OUTCOMES,
    InvalidScheduleSeriesNameError,
    ParsedScheduleRow,
    ScheduleAdmission,
    ScheduleAdmissionOutcome,
    ScheduleAdmissionRefusal,
    ScheduleBaselineKind,
    ScheduleBox,
    ScheduleCanonicalizationProgress,
    ScheduleCellEvidence,
    ScheduleCellFragment,
    ScheduleCellState,
    ScheduleDateCell,
    ScheduleDurationCell,
    ScheduleFinalization,
    ScheduleImportIssue,
    ScheduleImportRequest,
    ScheduleIssueCode,
    ScheduleIssueSeverity,
    ScheduleLease,
    ScheduleParseEngine,
    ScheduleParseIssue,
    ScheduleParserIdentity,
    ScheduleParserRun,
    ScheduleParserRunStart,
    ScheduleParserRunStatus,
    SchedulePlan,
    SchedulePublication,
    SchedulePublicationRole,
    SchedulePublicationStatus,
    ScheduleRowBoundsError,
    ScheduleRowType,
    ScheduleSeries,
    ScheduleSeriesName,
    StableScheduleActivity,
    StoredScheduleRow,
    canonical_json_bytes,
    cell_evidence_bytes,
    cell_evidence_object,
    effective_publication_status,
    model,
    normalize_series_name,
    schedule_import_request_digest,
    validate_row_for_persistence,
)
from tests.unit.test_schedule_model import _result

VALUE = ScheduleCellState.PUBLISHED_VALUE
BLANK = ScheduleCellState.PUBLISHED_BLANK
P = "prn_s5bdomain0001"
PRJ = "prj_s5bdomain0001"
SER = "sser_s5bdomain0001"
PUB = "spub_s5bdomain0001"
RUN = "sprun_s5bdomain0001"
OP = "op_s5bdomain0001"
ENR = "enr_s5bdomain0001"
OBJ = "obj_s5bdomain0001"
VER = "ver_s5bdomain0001"
WHEN = datetime(2026, 10, 27, 12, tzinfo=UTC)
DIGEST = "a" * 64


# --- builders ----------------------------------------------------------------


def _cells(**texts: str | None) -> tuple[ScheduleCellEvidence, ...]:
    cells = []
    for fld in ROW_CELL_FIELDS:
        text = texts.get(fld.value)
        if text is None:
            cells.append(ScheduleCellEvidence(fld, BLANK, None, ()))
        else:
            fragment = ScheduleCellFragment(
                raw=text,
                box=ScheduleBox(1_000, 1_000, 2_000, 2_000),
                font_base_name="Arial",
                font_size_mpt=7_000,
            )
            cells.append(ScheduleCellEvidence(fld, VALUE, text, (fragment,)))
    return tuple(cells)


def _row(**overrides: object) -> ParsedScheduleRow:
    fields: dict[str, Any] = {
        "row_ordinal": 2,
        "page_number": 1,
        "physical_line_ordinal": 2,
        "row_type": ScheduleRowType.ACTIVITY,
        "indent_level": 1,
        "parent_row_ordinal": None,
        "hierarchy_path": ("Synthetic WBS",),
        "published_activity_id": "SYN-1000",
        "activity_name": "Synthetic activity",
        "original_duration": ScheduleDurationCell(VALUE, Decimal("10.000")),
        "remaining_duration": ScheduleDurationCell(VALUE, Decimal("5.000")),
        "start": ScheduleDateCell(VALUE, date(2026, 5, 4), None),
        "finish": ScheduleDateCell(VALUE, date(2026, 5, 15), "*"),
        "box": ScheduleBox(52_570, 598_600, 593_500, 604_900),
        "page_width_mpt": 1_224_000,
        "page_height_mpt": 792_000,
        "cells": _cells(activity_id="SYN-1000", activity_name="Synthetic activity"),
        "warning_codes": (),
    }
    fields.update(overrides)
    return ParsedScheduleRow(**fields)


def _request(**overrides: object) -> ScheduleImportRequest:
    fields: dict[str, Any] = {
        "project_id": PRJ,
        "series_id": None,
        "series_name": normalize_series_name("Synthetic Master Schedule"),
        "enrollment_id": ENR,
        "source_object_id": OBJ,
        "source_version_id": VER,
        "publication_role": SchedulePublicationRole.UPDATE,
        "baseline_kind": None,
        "expected_data_date": date(2026, 5, 4),
        "supersedes_publication_id": None,
        "idempotency_key": "synthetic-key-0001",
    }
    fields.update(overrides)
    return ScheduleImportRequest(**fields)


def _publication(**overrides: object) -> SchedulePublication:
    fields: dict[str, Any] = {
        "publication_id": PUB,
        "principal_id": P,
        "project_id": PRJ,
        "series_id": SER,
        "enrollment_id": ENR,
        "source_object_id": OBJ,
        "source_version_id": VER,
        "idempotency_key": "synthetic-key-0001",
        "request_digest": DIGEST,
        "publication_role": SchedulePublicationRole.UPDATE,
        "baseline_kind": None,
        "expected_data_date": None,
        "supersedes_publication_id": None,
        "status": SchedulePublicationStatus.QUEUED,
        "document_sha256": None,
        "document_size_bytes": None,
        "published_schedule_title": None,
        "data_date": None,
        "run_date": None,
        "accepted_parser_run_id": None,
        "page_count": None,
        "row_count": None,
        "activity_count": None,
        "ambiguous_row_count": None,
        "issue_count": None,
        "admitted_at": WHEN,
        "processing_started_at": None,
        "completed_at": None,
        "updated_at": WHEN,
    }
    fields.update(overrides)
    return SchedulePublication(**fields)


_ACCEPTED = {
    "processing_started_at": WHEN,
    "completed_at": WHEN,
    "accepted_parser_run_id": RUN,
    "document_sha256": DIGEST,
    "document_size_bytes": 100,
    "page_count": 1,
    "row_count": 2,
    "activity_count": 1,
    "ambiguous_row_count": 0,
    "issue_count": 0,
}


def _run(**overrides: object) -> ScheduleParserRun:
    fields: dict[str, Any] = {
        "parser_run_id": RUN,
        "principal_id": P,
        "project_id": PRJ,
        "series_id": SER,
        "publication_id": PUB,
        "operation_id": OP,
        "attempt_number": 1,
        "parser_name": "cpm-workbench-full-parser",
        "parser_version": "1",
        "profile_id": "p6_full_v1",
        "profile_version": 1,
        "pypdfium2_version": "5.13.0",
        "pdfium_version": "153.0.7999.0",
        "document_sha256": DIGEST,
        "status": ScheduleParserRunStatus.RUNNING,
        "page_count": None,
        "row_count": None,
        "issue_count": None,
        "warning_count": None,
        "parse_result_sha256": None,
        "failure_code": None,
        "started_at": WHEN,
        "completed_at": None,
    }
    fields.update(overrides)
    return ScheduleParserRun(**fields)


# --- IDs and enums -----------------------------------------------------------


def test_schedule_id_kinds_have_their_prefixes() -> None:
    assert {kind: kind.value for kind in IdKind if kind.name.startswith("SCHEDULE_")} == {
        IdKind.SCHEDULE_SERIES: "sser",
        IdKind.SCHEDULE_PUBLICATION: "spub",
        IdKind.SCHEDULE_PARSER_RUN: "sprun",
        IdKind.SCHEDULE_ROW: "srow",
        IdKind.SCHEDULE_ACTIVITY: "sact",
        IdKind.SCHEDULE_IMPORT_ISSUE: "siss",
    }
    others = [kind.value for kind in IdKind if not kind.name.startswith("SCHEDULE_")]
    for kind in IdKind:
        if not kind.name.startswith("SCHEDULE_"):
            continue
        assert not any(
            other.startswith(kind.value) or kind.value.startswith(other) for other in others
        ), kind


def test_new_enums_have_exact_members_and_order() -> None:
    expected: dict[type[Any], list[tuple[str, str]]] = {
        SchedulePublicationRole: [
            ("UPDATE", "update"),
            ("BASELINE", "baseline"),
            ("REFERENCE", "reference"),
        ],
        ScheduleBaselineKind: [("WORKING", "working"), ("CONTRACT", "contract")],
        ScheduleParserRunStatus: [
            ("RUNNING", "running"),
            ("PARSED", "parsed"),
            ("FAILED", "failed"),
        ],
        ScheduleAdmissionOutcome: [("CREATED", "created"), ("REPLAYED", "replayed")],
    }
    for enum, members in expected.items():
        assert [(m.name, m.value) for m in enum] == members, enum
    assert [m.name for m in ScheduleAdmissionRefusal] == [
        "PROJECT_NOT_FOUND",
        "SERIES_NOT_FOUND",
        "ENROLLMENT_NOT_FOUND",
        "SOURCE_OBJECT_NOT_ENROLLED",
        "SOURCE_VERSION_NOT_FOUND",
        "UNSUPPORTED_MEDIA_TYPE",
        "MEDIA_TYPE_NOT_ENROLLED",
        "SOURCE_TOO_LARGE",
        "SUPERSEDED_PUBLICATION_NOT_FOUND",
        "SUPERSEDED_PUBLICATION_NOT_TERMINAL",
        "SUPERSEDED_PUBLICATION_SAME_SOURCE_VERSION",
        "SUPERSEDED_PUBLICATION_HAS_SUCCESSOR",
        "IDEMPOTENCY_KEY_CONFLICT",
        "SOURCE_VERSION_CONFLICT",
    ]
    assert all(m.value == m.name.lower() for m in ScheduleAdmissionRefusal)
    assert SCHEDULE_MEDIA_TYPE == "application/pdf"


def test_outcome_ladder_sets_partition_the_issue_codes() -> None:
    """The three ladder sets, the two warnings and the fetch-time code: all 23, once."""
    warnings = {c for c, s in ISSUE_SEVERITY.items() if s is ScheduleIssueSeverity.WARNING}
    parts = [
        model._FAILED_CODES,
        model._REVIEW_CODES,
        model._PARTIAL_CODES,
        frozenset(warnings),
        frozenset({ScheduleIssueCode.SOURCE_VERSION_CHANGED}),
    ]
    assert sum(len(part) for part in parts) == len(ScheduleIssueCode) == 23
    assert frozenset().union(*parts) == frozenset(ScheduleIssueCode)
    assert warnings == {
        ScheduleIssueCode.HEADER_OD_OCCLUDED,
        ScheduleIssueCode.DUPLICATE_TEXT_OBJECT_COLLAPSED,
    }


# --- Series names (R2 section 10.1) --------------------------------------------


@pytest.mark.parametrize(
    ("raw", "name", "key"),
    [
        ("Master Schedule", "Master Schedule", "master schedule"),
        ("  Master\t\tSchedule \n", "Master Schedule", "master schedule"),
        (f"Master{chr(0xA0)}{chr(0x2003)}Schedule", "Master Schedule", "master schedule"),
        (f"Cafe{chr(0x301)} Phase", f"Caf{chr(0xE9)} Phase", f"caf{chr(0xE9)} phase"),
        ("STRASSE", "STRASSE", "strasse"),
        (f"Stra{chr(0xDF)}e", f"Stra{chr(0xDF)}e", "strasse"),
        ("x" * 200, "x" * 200, "x" * 200),
    ],
)
def test_series_name_normalization_vectors(raw: str, name: str, key: str) -> None:
    normalized = normalize_series_name(raw)
    assert (normalized.name, normalized.key) == (name, key)
    assert ScheduleSeriesName(name=name, key=key) == normalized


@pytest.mark.parametrize(
    "raw",
    [
        f"Bad{chr(0x07)}Name",  # Cc
        f"Bad{chr(0x200B)}Name",  # Cf
        f"Bad{chr(0x200D)}Name",  # Cf
        f"Bad{chr(0xD800)}Name",  # Cs
        f"Bad{chr(0xE000)}Name",  # Co
        f"Bad{chr(0xE01F0)}Name",  # Cn (unassigned)
        "",
        "   ",
        "x" * 201,
    ],
)
def test_series_name_rejects_each_category(raw: str) -> None:
    with pytest.raises(InvalidScheduleSeriesNameError):
        normalize_series_name(raw)


def test_series_name_record_refuses_an_unnormalized_pair() -> None:
    with pytest.raises(InvalidScheduleSeriesNameError):
        ScheduleSeriesName(name=" Master", key=" master")
    with pytest.raises(InvalidScheduleSeriesNameError):
        ScheduleSeriesName(name="Master", key="Master")
    with pytest.raises(InvalidScheduleSeriesNameError):
        ScheduleSeries(SER, P, PRJ, "Master  Schedule", "master  schedule", WHEN)
    ScheduleSeries(SER, P, PRJ, "Master Schedule", "master schedule", WHEN)


# --- the admission request and its digest --------------------------------------


def test_import_request_invariants() -> None:
    _request()
    _request(series_id=SER, series_name=None)
    for overrides in (
        {"series_id": SER},
        {"series_name": None},
        {"publication_role": SchedulePublicationRole.BASELINE},
        {"baseline_kind": ScheduleBaselineKind.WORKING},
        {"idempotency_key": "short"},
        {"idempotency_key": "has space key"},
        {"idempotency_key": "k" * 129},
        {"expected_data_date": WHEN},
    ):
        with pytest.raises(ValueError, match=r"."):
            _request(**overrides)
    with pytest.raises(InvalidIdentifierError):
        _request(source_version_id=OBJ)
    _request(
        publication_role=SchedulePublicationRole.BASELINE,
        baseline_kind=ScheduleBaselineKind.CONTRACT,
    )
    assert SCHEDULE_IDEMPOTENCY_KEY_PATTERN.fullmatch("A" * 128)


#: Golden vectors: the digest of a fixed request, pinned (contract 5.3, D-14).
_GOLDEN_BY_NAME = "f70986a38ede215036c64dbe2c4600c7a1d2ae77557f6c4a567c932c9f457101"
_GOLDEN_BY_ID = "c46f340a7ee8f40b8209f6dd95ca89479363b36330ceaaf4f19d445ecc6162e9"


def test_request_digest_golden_vectors() -> None:
    by_name = _request()
    expected_body = (
        b'{"principal_id":"prn_s5bdomain0001","request":{"baseline_kind":null,'
        b'"enrollment_id":"enr_s5bdomain0001","expected_data_date":"2026-05-04",'
        b'"project_id":"prj_s5bdomain0001","publication_role":"update",'
        b'"series_id":null,"series_name_key":"synthetic master schedule",'
        b'"source_object_id":"obj_s5bdomain0001","source_version_id":"ver_s5bdomain0001",'
        b'"supersedes_publication_id":null}}'
    )
    assert (
        schedule_import_request_digest(P, by_name)
        == hashlib.sha256(b"cpm-schedule-import-v1\n" + expected_body).hexdigest()
        == _GOLDEN_BY_NAME
    )
    by_id = _request(series_id=SER, series_name=None)
    assert schedule_import_request_digest(P, by_id) == _GOLDEN_BY_ID


def test_request_digest_excludes_the_key_and_folds_the_name() -> None:
    base = schedule_import_request_digest(P, _request())
    assert schedule_import_request_digest(P, _request(idempotency_key="another-key-0002")) == base
    folded = _request(series_name=normalize_series_name("  SYNTHETIC   master schedule "))
    assert schedule_import_request_digest(P, folded) == base
    for changed in (
        _request(expected_data_date=None),
        _request(supersedes_publication_id="spub_s5bdomain0009"),
        _request(
            publication_role=SchedulePublicationRole.BASELINE,
            baseline_kind=ScheduleBaselineKind.WORKING,
        ),
        _request(source_version_id="ver_s5bdomain0002"),
        _request(series_id=SER, series_name=None),
    ):
        assert schedule_import_request_digest(P, changed) != base
    assert schedule_import_request_digest("prn_s5bdomain0002", _request()) != base


# --- records ---------------------------------------------------------------------


def test_publication_progress_follows_status() -> None:
    _publication()
    _publication(status=SchedulePublicationStatus.PROCESSING, processing_started_at=WHEN)
    _publication(
        status=SchedulePublicationStatus.PROCESSING,
        processing_started_at=WHEN,
        document_sha256=DIGEST,
        document_size_bytes=10,
    )
    for status in (
        SchedulePublicationStatus.COMPLETE,
        SchedulePublicationStatus.PARTIAL,
        SchedulePublicationStatus.REVIEW_REQUIRED,
    ):
        _publication(status=status, **_ACCEPTED)
    _publication(
        status=SchedulePublicationStatus.FAILED,
        processing_started_at=WHEN,
        completed_at=WHEN,
        issue_count=1,
    )
    refused: list[dict[str, Any]] = [
        {"processing_started_at": WHEN},
        {"status": SchedulePublicationStatus.PROCESSING},
        {
            "status": SchedulePublicationStatus.PROCESSING,
            "processing_started_at": WHEN,
            "row_count": 1,
        },
        {"status": SchedulePublicationStatus.COMPLETE, **{**_ACCEPTED, "row_count": None}},
        {
            "status": SchedulePublicationStatus.FAILED,
            "processing_started_at": WHEN,
            "completed_at": WHEN,
            "issue_count": 0,
        },
        {
            "status": SchedulePublicationStatus.FAILED,
            "processing_started_at": WHEN,
            "completed_at": WHEN,
            "issue_count": 1,
            "accepted_parser_run_id": RUN,
        },
        {"document_sha256": DIGEST},
        {"publication_role": SchedulePublicationRole.BASELINE},
        {"supersedes_publication_id": PUB},
        {"request_digest": "A" * 64},
    ]
    for overrides in refused:
        with pytest.raises(ValueError, match=r"."):
            _publication(**overrides)


def test_parser_identity_and_run_invariants() -> None:
    run = _run()
    assert run.identity == ScheduleParserIdentity(
        "cpm-workbench-full-parser", "1", "p6_full_v1", 1, "5.13.0", "153.0.7999.0"
    )
    _run(
        status=ScheduleParserRunStatus.PARSED,
        completed_at=WHEN,
        page_count=1,
        row_count=2,
        issue_count=1,
        warning_count=1,
        parse_result_sha256=DIGEST,
    )
    _run(status=ScheduleParserRunStatus.FAILED, completed_at=WHEN)
    _run(
        status=ScheduleParserRunStatus.FAILED,
        completed_at=WHEN,
        failure_code=ScheduleIssueCode.CORRUPT_PDF,
    )
    for overrides in (
        {"completed_at": WHEN},
        {"status": ScheduleParserRunStatus.PARSED, "completed_at": WHEN},
        {"status": ScheduleParserRunStatus.FAILED, "completed_at": WHEN, "row_count": 1},
        {"attempt_number": 0},
        {"profile_version": 0},
        {"parser_name": "x" * 65},
        {
            "status": ScheduleParserRunStatus.PARSED,
            "completed_at": WHEN,
            "page_count": 1,
            "row_count": 2,
            "issue_count": 0,
            "warning_count": 1,
            "parse_result_sha256": DIGEST,
        },
    ):
        with pytest.raises(ValueError, match=r"."):
            _run(**overrides)
    engine = ScheduleParseEngine("5.13.0", "153.0.7999.0")
    assert ScheduleParserIdentity.from_parse_result(_result(engine=engine)) == run.identity


def test_stored_row_issue_and_activity_invariants() -> None:
    StoredScheduleRow("srow_s5bdomain0001", RUN, PUB, None, None, _row())
    StoredScheduleRow("srow_s5bdomain0001", RUN, PUB, "sact_s5bdomain0001", None, _row())
    summary = _row(
        row_type=ScheduleRowType.WBS_SUMMARY,
        published_activity_id=None,
        cells=_cells(activity_name="Synthetic activity"),
    )
    with pytest.raises(ValueError, match="only an activity or milestone"):
        StoredScheduleRow("srow_s5bdomain0001", RUN, PUB, "sact_s5bdomain0001", None, summary)
    with pytest.raises(ValueError, match="names its parent"):
        StoredScheduleRow("srow_s5bdomain0001", RUN, PUB, None, None, _row(parent_row_ordinal=1))
    StoredScheduleRow(
        "srow_s5bdomain0002", RUN, PUB, None, "srow_s5bdomain0001", _row(parent_row_ordinal=1)
    )
    issue = ScheduleParseIssue(
        ScheduleIssueCode.INVALID_DATE, ScheduleIssueSeverity.ERROR, 1, 2, None
    )
    ScheduleImportIssue("siss_s5bdomain0001", PUB, RUN, issue)
    with pytest.raises(ValueError, match="names its parser run"):
        ScheduleImportIssue("siss_s5bdomain0001", PUB, None, issue)
    StableScheduleActivity("sact_s5bdomain0001", P, PRJ, SER, "SYN-1000", WHEN)
    for published in ("", " SYN-1000", "x" * 257):
        with pytest.raises(ValueError, match="published activity id"):
            StableScheduleActivity("sact_s5bdomain0001", P, PRJ, SER, published, WHEN)


def test_lease_plan_admission_and_progress_invariants() -> None:
    ScheduleLease(OP, "worker-1", 1)
    for args in ((OP, "", 1), (OP, "worker-1", 0)):
        with pytest.raises(ValueError, match=r"."):
            ScheduleLease(*args)
    queued = _publication()
    SchedulePlan(queued, 1, False, 1024)
    with pytest.raises(ValueError, match="terminal exactly"):
        SchedulePlan(queued, 1, True, None)
    with pytest.raises(ValueError, match="fetches 0 to"):
        SchedulePlan(queued, 1, False, None)
    complete = _publication(status=SchedulePublicationStatus.COMPLETE, **_ACCEPTED)
    SchedulePlan(complete, 2, True, None)
    with pytest.raises(ValueError, match="fetches nothing"):
        SchedulePlan(complete, 2, True, 10)
    series = ScheduleSeries(SER, P, PRJ, "Master Schedule", "master schedule", WHEN)
    ScheduleAdmission(series, queued, OP, ScheduleAdmissionOutcome.CREATED, True)
    with pytest.raises(ValueError, match="creates no series"):
        ScheduleAdmission(series, queued, OP, ScheduleAdmissionOutcome.REPLAYED, True)
    other = dataclasses.replace(series, series_id="sser_s5bdomain0002")
    with pytest.raises(ValueError, match="belongs to its series"):
        ScheduleAdmission(other, queued, OP, ScheduleAdmissionOutcome.CREATED, False)
    ScheduleParserRunStart(_run(), reused=False)
    with pytest.raises(ValueError, match="never reused"):
        ScheduleParserRunStart(
            _run(status=ScheduleParserRunStatus.FAILED, completed_at=WHEN), reused=True
        )
    ScheduleCanonicalizationProgress(0, 0, 0)
    with pytest.raises(ValueError, match="non-negative"):
        ScheduleCanonicalizationProgress(-1, 0, 0)
    ScheduleFinalization(RUN, "Synthetic Project Schedule", date(2026, 5, 4), None)
    with pytest.raises(ValueError, match="title"):
        ScheduleFinalization(RUN, "", None, None)
    assert "status" not in {f.name for f in dataclasses.fields(ScheduleFinalization)}


# --- persistence bounds (R2 section 36, ruling (c)) -------------------------------


def _bypass(row: ParsedScheduleRow, **values: object) -> ParsedScheduleRow:
    """A row with a field set past its own record invariant (frozen, so forced)."""
    for name, value in values.items():
        object.__setattr__(row, name, value)
    return row


def test_row_bounds_are_enforced_before_persistence() -> None:
    validate_row_for_persistence(_row())
    validate_row_for_persistence(
        _row(
            published_activity_id="I" * 256,
            activity_name="N" * 2000,
            hierarchy_path=("L" * 2000,) * 32,
            cells=_cells(activity_id="I" * 256, activity_name="N"),
        )
    )
    oversized = _row(cells=_cells(activity_id="SYN-1000", activity_name="N" * 17_000))
    assert len(cell_evidence_bytes(oversized)) > MAX_CELL_EVIDENCE_BYTES
    cases = {
        "cell evidence": oversized,
        "published activity id": _row(
            published_activity_id="I" * 257, cells=_cells(activity_id="I", activity_name="N")
        ),
        "activity name": _row(activity_name="N" * 2001, cells=_cells(activity_id="I")),
        "hierarchy label": _row(hierarchy_path=("L" * 2001,)),
        "empty label": _row(hierarchy_path=("ok", "")),
        "hierarchy path": _bypass(_row(), hierarchy_path=("L",) * 33),
    }
    for case, row in cases.items():
        with pytest.raises(ScheduleRowBoundsError):
            validate_row_for_persistence(row)
        assert issubclass(ScheduleRowBoundsError, ValueError), case


def test_cell_evidence_bound_is_on_canonical_bytes() -> None:
    row = _row()
    assert cell_evidence_bytes(row) == canonical_json_bytes(
        {"schema": "cpm-full-cells-v1", "cells": model_cells(row)}
    )


def model_cells(row: ParsedScheduleRow) -> dict[str, object]:
    cells = cell_evidence_object(row)["cells"]
    assert isinstance(cells, dict)
    return cells


# --- effective status (R2 section 10.6) -------------------------------------------


def test_effective_status_derivation() -> None:
    for status in SchedulePublicationStatus:
        assert effective_publication_status(status, job_failed=False) is status
        expected = (
            SchedulePublicationStatus.FAILED
            if status in (SchedulePublicationStatus.QUEUED, SchedulePublicationStatus.PROCESSING)
            else status
        )
        assert effective_publication_status(status, job_failed=True) is expected
    assert SchedulePublicationStatus.FAILED in TERMINAL_OUTCOMES
