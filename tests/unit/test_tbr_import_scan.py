"""PC-CM-IMP-WP13 T13-02, T13-05, T13-06, T13-07: classification, codes, digests.

Everything here runs against the synthetic OOXML register and against
`plan_import`, which is pure — it reads no database and writes nothing, and
takes what the database would contribute as arguments. That is what makes the
A/B/C rule, the code rule and the digest rule provable in the FAST tier rather
than only against a server.

The classification claim is deliberately four-valued and not three. A row that
is neither a complete record, an intentionally incomplete one, nor a blank or
template row is *unsupported*: it is reported by row and by stable issue code
and it is imported by nothing. Nothing anywhere below is repaired, defaulted or
inferred, and the assertions are written so that a build that started guessing a
missing status, party, category or date would fail here rather than pass more
quietly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest

from my_pa.application.constraint_legacy_import import (
    AUTHORITATIVE_CATEGORY_NAMES,
    ISSUE_CATEGORY_UNKNOWN,
    ISSUE_CODE_COLLIDES_WITH_CANONICAL,
    ISSUE_CODE_DUPLICATE,
    ISSUE_CODE_NUMERIC_CELL,
    ISSUE_CODE_PREFIX_MISMATCH,
    ISSUE_CODE_WITHIN_ISSUED_RANGE,
    ISSUE_DATE_SYSTEM_1904,
    ISSUE_FORMULA_UNCOMPUTED,
    ISSUE_STATUS_UNKNOWN,
    ISSUE_VOID_FIELDS_UNAVAILABLE,
    WORKBOOK_STATUS_VOCABULARY,
    CategoryPlan,
    ImportDisposition,
    ImportPlan,
    RowClass,
    SourceScan,
    row_idempotency_key,
    row_request_digest,
    scan_source,
)
from my_pa.application.constraint_legacy_import import plan_import as _plan_import
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintRecordQuality,
)
from my_pa.domain.project_controls.history import CONSTRAINT_IDEMPOTENCY_KEY_PATTERN
from my_pa.infrastructure.ooxml_worksheet_reader import OoxmlWorkbookSource
from tests.fixtures.tbr_workbook import (
    BLANK,
    DESIGN,
    PERMITS,
    SHEET_NAME,
    formula,
    register_rows,
    text,
    write_register,
    write_workbook,
)

REGISTER: Final = "synthetic-register-01"
PROJECT: Final = "prj_svcaaaa0001aaaa"
NOW: Final = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)


def _scan(path: Path, *, sheet: str = SHEET_NAME) -> SourceScan:
    source = OoxmlWorkbookSource(path, sheet_name=sheet)
    return scan_source(source, register_id=REGISTER, project_id=PROJECT)


@pytest.fixture
def plan(tmp_path: Path) -> ImportPlan:
    return _plan_import(
        _scan(write_register(tmp_path / "register.xlsm", with_vba=True)),
        mode="dry-run",
        generated_at=NOW,
    )


def test_the_seven_authoritative_category_names_are_the_ones_this_build_carries() -> None:
    """T13-07, CM-BE-AC-097. The names are authoritative; nothing else is claimed."""
    assert AUTHORITATIVE_CATEGORY_NAMES == (
        "PERMITS - OPEN",
        "AHJ COORDINATION - OPEN",
        "DESIGN DEVELOPMENT - OPEN",
        "UTILITY SERVICE PROVIDERS - OPEN",
        "MOSS INTERNAL COORDINATION ITEMS",
        "PRECONSTRUCTION PROGRESS - OPEN",
        "BUYOUT & PROCUREMENT - OPEN",
    )
    assert len(set(AUTHORITATIVE_CATEGORY_NAMES)) == 7


def test_the_workbook_status_vocabulary_is_the_one_the_definition_observed() -> None:
    """T13-07, CM-BE-AC-096. Six names; two are renamed and four map directly."""
    assert set(WORKBOOK_STATUS_VOCABULARY) == {
        "IDENTIFIED",
        "PENDING",
        "IN PROGRESS",
        "ON HOLD",
        "CLOSED",
        "VOID",
    }
    assert WORKBOOK_STATUS_VOCABULARY["IN PROGRESS"] is ConstraintLifecycleState.IN_PROGRESS
    assert WORKBOOK_STATUS_VOCABULARY["ON HOLD"] is ConstraintLifecycleState.ON_HOLD
    assert ConstraintLifecycleState.DRAFT not in WORKBOOK_STATUS_VOCABULARY.values()


def test_a_prefix_is_read_from_the_source_and_never_invented(plan: ImportPlan) -> None:
    """T13-07, finding N-05. No accepted source enumerates a prefix, so the source does."""
    prefixes = {entry.name: entry.prefix for entry in plan.report.category_plans}
    assert prefixes == {PERMITS: "1", DESIGN: "3"}


def test_the_classification_is_four_valued_and_nothing_is_repaired(plan: ImportPlan) -> None:
    """T13-05, CM-BE-AC-100/101/126. A, B, C and an explicit unsupported class."""
    counts = plan.report.class_counts
    assert counts[RowClass.A_COMPLETE.value] == 6
    assert counts[RowClass.B_LEGACY_INCOMPLETE.value] == 1
    assert counts[RowClass.C_IGNORED.value] == 2
    assert counts[RowClass.UNSUPPORTED.value] == 4


def test_an_intentionally_incomplete_row_is_legacy_incomplete_and_keeps_its_gaps(
    plan: ImportPlan,
) -> None:
    """T13-05, CM-BE-AC-101/125. No description and no BIC are preserved as absent."""
    row = next(row for row in plan.rows if row.constraint_code == "1.02")
    assert row.classification is RowClass.B_LEGACY_INCOMPLETE
    assert row.record_quality is ConstraintRecordQuality.LEGACY_INCOMPLETE
    assert row.description is None
    assert row.bic == ()
    assert row.lifecycle_state is ConstraintLifecycleState.PENDING


def test_every_unsupported_row_is_reported_by_a_stable_code(plan: ImportPlan) -> None:
    """T13-05. Four unsupported rows, each named by what was wrong with it."""
    found = {issue.issue for issue in plan.report.issues}
    assert {
        ISSUE_STATUS_UNKNOWN,
        ISSUE_VOID_FIELDS_UNAVAILABLE,
        ISSUE_CODE_DUPLICATE,
        ISSUE_CODE_NUMERIC_CELL,
        ISSUE_FORMULA_UNCOMPUTED,
    } <= found


def test_a_void_row_is_reported_rather_than_given_an_invented_reason(plan: ImportPlan) -> None:
    """The source carries no void date and no void reason, so no VOID record is made."""
    assert all(row.lifecycle_state is not ConstraintLifecycleState.VOID for row in plan.rows)
    issue = next(
        issue for issue in plan.report.issues if issue.issue == ISSUE_VOID_FIELDS_UNAVAILABLE
    )
    assert issue.constraint_code == "1.04"


def test_four_codes_that_differ_only_in_their_digits_stay_four_records(plan: ImportPlan) -> None:
    """T13-06, CM-BE-AC-124. `3.01`, `3.1`, `3.10` and `3.100` are four codes."""
    codes = [row.constraint_code for row in plan.rows]
    assert {"3.01", "3.1", "3.10", "3.100"} <= set(codes)
    assert len(codes) == len(set(codes))
    assert all(isinstance(code, str) for code in codes)


def test_the_allocator_seed_sits_above_the_highest_imported_sequence(plan: ImportPlan) -> None:
    """T13-06, CM-BE-AC-127. `3.100` seeds 101, not 11 and not 2."""
    design = next(entry for entry in plan.report.category_plans if entry.name == DESIGN)
    assert design.max_imported_sequence == 100
    assert design.proposed_next_sequence == 101
    assert design.proposed_issued_count == 5


def test_a_code_already_canonical_is_a_collision_and_blocks_the_run(tmp_path: Path) -> None:
    """T13-06. A preserved code that is already in the register is never overwritten."""
    result = _plan_import(
        _scan(write_register(tmp_path / "register.xlsm")),
        existing_codes=frozenset({"3.10"}),
        mode="dry-run",
        generated_at=NOW,
    )
    codes = {issue.constraint_code for issue in result.report.issues}
    assert "3.10" in codes
    assert ISSUE_CODE_COLLIDES_WITH_CANONICAL in result.report.blockers
    assert result.report.disposition is ImportDisposition.BLOCKED


def test_a_code_inside_an_existing_issued_range_blocks_rather_than_overwrites(
    tmp_path: Path,
) -> None:
    """T13-06. The allocator's own counter is the authority on what has been issued."""
    existing = CategoryPlan(
        name=PERMITS,
        prefix="1",
        row_count=0,
        max_imported_sequence=None,
        proposed_next_sequence=9,
        proposed_issued_count=8,
        existing_category_id="ccat_svcaaaa0001aaaa",
        existing_next_sequence=9,
        existing_version=1,
    )
    result = _plan_import(
        _scan(write_register(tmp_path / "register.xlsm")),
        existing_categories=(existing,),
        mode="dry-run",
        generated_at=NOW,
    )
    assert ISSUE_CODE_WITHIN_ISSUED_RANGE in result.report.blockers


def test_a_code_whose_prefix_disagrees_with_its_section_is_reported(tmp_path: Path) -> None:
    """T13-06. A row filed under the wrong section is never quietly re-filed."""
    rows = register_rows()
    rows.append(
        [text("9.01"), text("A row under the wrong section."), text("2026-01-20"), text("PENDING")]
    )
    path = write_workbook(tmp_path / "mismatch.xlsx", {SHEET_NAME: rows})
    result = _plan_import(_scan(path), mode="dry-run", generated_at=NOW)
    assert any(issue.issue == ISSUE_CODE_PREFIX_MISMATCH for issue in result.report.issues)


def test_a_section_heading_outside_the_seven_names_is_reported_and_adopted_by_nothing(
    tmp_path: Path,
) -> None:
    """T13-07. A Category this build does not recognise is never invented into one."""
    rows = [
        register_rows()[0],
        [text("NOT AN AUTHORITATIVE SECTION")],
        [
            text("8.01"),
            text("A row under an unknown section."),
            text("2026-01-21"),
            text("PENDING"),
        ],
    ]
    path = write_workbook(tmp_path / "unknown.xlsx", {SHEET_NAME: rows})
    result = _plan_import(_scan(path), mode="dry-run", generated_at=NOW)
    assert any(issue.issue == ISSUE_CATEGORY_UNKNOWN for issue in result.report.issues)
    assert result.report.category_plans == ()
    assert result.rows == ()


def test_the_1904_date_system_blocks_rather_than_shifting_every_date(tmp_path: Path) -> None:
    """A misread epoch would move every date by four years, silently. It blocks instead."""
    result = _plan_import(
        _scan(write_register(tmp_path / "1904.xlsx", date1904=True)),
        mode="dry-run",
        generated_at=NOW,
    )
    assert ISSUE_DATE_SYSTEM_1904 in result.report.blockers


def test_the_import_identity_is_stable_and_well_formed(tmp_path: Path) -> None:
    """T13-02. The composed key survives a rerun and satisfies the stored pattern."""
    first = row_idempotency_key(REGISTER, PROJECT, f"{SHEET_NAME}!3")
    again = row_idempotency_key(REGISTER, PROJECT, f"{SHEET_NAME}!3")
    assert first == again
    assert CONSTRAINT_IDEMPOTENCY_KEY_PATTERN.fullmatch(first)
    assert first != row_idempotency_key(REGISTER, PROJECT, f"{SHEET_NAME}!4")
    assert first != row_idempotency_key("another-register", PROJECT, f"{SHEET_NAME}!3")
    assert first != row_idempotency_key(REGISTER, "prj_svcbbbb0002bbbb", f"{SHEET_NAME}!3")


def test_the_row_digest_is_deterministic_and_moves_with_the_content() -> None:
    """T13-02. Same content, same digest; changed content, different digest."""
    values = {"code": "1.01", "description": "A thing.", "status": "IDENTIFIED"}
    first = row_request_digest(values, PERMITS)
    assert first == row_request_digest(dict(reversed(list(values.items()))), PERMITS)
    assert len(first) == 64
    assert first != row_request_digest({**values, "status": "PENDING"}, PERMITS)
    assert first != row_request_digest(values, DESIGN)


def test_the_workbook_last_updated_stamp_can_never_act_as_a_cursor(tmp_path: Path) -> None:
    """T13-02 negative, CM-BE-AC-103. A derived column moves no digest."""
    original = _plan_import(
        _scan(write_register(tmp_path / "a.xlsx")),
        mode="dry-run",
        generated_at=NOW,
    )
    rows = register_rows()
    touched = list(rows[2])
    touched[4] = formula("NETWORKDAYS(C3,TODAY())", "9999")
    touched[11] = text("2099-12-31")
    rows[2] = touched
    stamped = _plan_import(
        _scan(write_workbook(tmp_path / "b.xlsx", {SHEET_NAME: rows})),
        mode="dry-run",
        generated_at=NOW,
    )
    assert [row.request_digest for row in original.rows] == [
        row.request_digest for row in stamped.rows
    ]


def test_a_blank_and_a_template_row_are_ignored_with_counts_and_no_finding(
    tmp_path: Path,
) -> None:
    """T13-05, CM-BE-AC-100/102/126. Ignored, counted, and not reported as defects."""
    rows = [
        register_rows()[0],
        [BLANK],
        [BLANK, BLANK, BLANK, BLANK, formula("NETWORKDAYS()", "0")],
    ]
    path = write_workbook(tmp_path / "empty.xlsx", {SHEET_NAME: rows})
    result = _plan_import(_scan(path), mode="dry-run", generated_at=NOW)
    assert result.report.class_counts[RowClass.C_IGNORED.value] == 2
    assert result.report.issues == ()
    assert result.rows == ()
