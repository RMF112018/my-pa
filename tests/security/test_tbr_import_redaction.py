"""PC-CM-IMP-WP13 T13-15: the import report carries no workbook narrative.

`src/my_pa/infrastructure/migration/redaction.py` states the campaign's standing
rule — counts, table names, column names, type names, error codes and stable
identifiers may be written down and values may not — and
`tests/security/test_application_redaction.py` is the precedent family for
holding an application surface to it. This module holds the import report to it.

The check is not a keyword scan over a hand-written expectation. Every value the
synthetic workbook carries in a narrative column is collected from the fixture
itself and each one is required to be absent from both artefacts, so a report
that started printing a description, a comment, a party label, a closure note or
a void reason fails here whichever value it printed. The findings are then
required to be *present* — a report that redacted itself by reporting nothing
would satisfy an absence test and be useless.
"""

from __future__ import annotations

import dataclasses
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from tests.fixtures.tbr_workbook import SHEET_NAME, register_rows, write_register

from my_pa.application.constraint_legacy_import import (
    ImportPlan,
    RowIssue,
    plan_import,
    render_markdown,
    report_as_dict,
    scan_source,
)
from my_pa.infrastructure.migration import redaction
from my_pa.infrastructure.ooxml_worksheet_reader import OoxmlWorkbookSource

REGISTER: Final = "synthetic-register-01"
PROJECT: Final = "prj_svcaaaa0001aaaa"
NOW: Final = datetime(2026, 9, 7, 12, 0, tzinfo=UTC)

#: The columns whose contents are narrative. A report may never carry one.
NARRATIVE_COLUMNS: Final = (1, 5, 6, 7, 10)


@pytest.fixture
def plan(tmp_path: Path) -> ImportPlan:
    source = OoxmlWorkbookSource(
        write_register(tmp_path / "register.xlsm", with_vba=True), sheet_name=SHEET_NAME
    )
    scan = scan_source(source, register_id=REGISTER, project_id=PROJECT)
    return plan_import(scan, mode="dry-run", generated_at=NOW)


def _narrative_values() -> set[str]:
    """Every narrative value the synthetic register carries, from the fixture itself."""
    found: set[str] = set()
    for row in register_rows()[1:]:
        for index in NARRATIVE_COLUMNS:
            if index < len(row) and row[index].text:
                found.add(row[index].text)
    return found


def test_the_fixture_actually_carries_narrative_to_leak() -> None:
    """Guard the guard: an empty expectation would make every assertion vacuous."""
    values = _narrative_values()
    assert len(values) >= 5
    assert any("permit set" in value for value in values)


def test_no_workbook_narrative_reaches_either_artefact(plan: ImportPlan) -> None:
    """T13-15, CM-BE-AC-128/133. Descriptions, comments, references, party labels."""
    machine = json.dumps(report_as_dict(plan.report), sort_keys=True)
    human = render_markdown(plan.report)
    for value in _narrative_values():
        assert value not in machine, value
        assert value not in human, value


def test_the_report_still_says_something_a_reviewer_can_act_on(plan: ImportPlan) -> None:
    """T13-15, CM-BE-AC-134. Counts, identifiers, codes and stable issue codes."""
    document = report_as_dict(plan.report)
    assert document["totalSourceRows"] > 0
    assert document["classCounts"]
    assert document["lifecycleCounts"]
    assert document["categories"]
    assert document["issues"]
    assert document["sourceDigest"] == plan.report.source_digest
    assert len(str(document["sourceDigest"])) == 64


def test_a_collision_is_reported_by_code_and_row_and_by_nothing_else(
    plan: ImportPlan,
) -> None:
    """T13-15. A finding names where and what, never the content that collided."""
    assert {field.name for field in dataclasses.fields(RowIssue)} == {
        "row_identity",
        "issue",
        "constraint_code",
    }
    for issue in plan.report.issues:
        assert issue.row_identity
        assert issue.issue.replace("_", "").isalnum()
        if issue.constraint_code is not None:
            assert len(issue.constraint_code) <= 32


def test_the_artefacts_pass_the_repository_personal_data_scan(
    plan: ImportPlan, tmp_path: Path
) -> None:
    """T13-15, CM-BE-AC-133. The same scanner the migration evidence tree uses."""
    machine = tmp_path / "tbr-import.json"
    human = tmp_path / "TBR-IMPORT.md"
    machine.write_text(json.dumps(report_as_dict(plan.report), indent=2) + "\n", encoding="utf-8")
    human.write_text(render_markdown(plan.report), encoding="utf-8")
    report = redaction.scan((machine, human), base=tmp_path)
    assert report.findings == ()


def test_no_credential_or_connection_string_can_reach_the_report(
    plan: ImportPlan,
) -> None:
    """T13-15. The report is built from the plan, and the plan never sees a URL."""
    machine = json.dumps(report_as_dict(plan.report))
    for token in ("postgresql://", "password", "secret", "MY_PA_DATABASE_URL"):
        assert token not in machine


def test_the_source_path_never_appears_in_either_artefact(plan: ImportPlan, tmp_path: Path) -> None:
    """The operator's path is theirs. The report carries a digest and a register token."""
    machine = json.dumps(report_as_dict(plan.report))
    human = render_markdown(plan.report)
    assert str(tmp_path) not in machine
    assert str(tmp_path) not in human
    assert "register.xlsm" not in machine
    assert "register.xlsm" not in human
