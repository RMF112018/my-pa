"""Stats-only conformance profile of an XER export (S7-1, contract section 12).

The report is built from the same parser front end and catalogue as the
worker and holds **no value from the file**: only table and field names that
match the section 5.2 name pattern (others by position), counts, lengths,
shape histograms, issue codes with line numbers, and, for enumerated fields,
unknown tokens that match the P6 vocabulary pattern
`[A-Za-z]{1,8}_[A-Za-z0-9_]{1,40}` (anything else is counted, not shown).
The export version itself is not shown, only whether it is in the tested
range. Pure, standard library only; the operator script
`ops/schedule/p6_export_profile.py` does the file reading and printing.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Final

from my_pa.domain.schedule.p6.catalogue import CATALOGUE_VERSION, TESTED_VERSION_PREFIX, Tier
from my_pa.domain.schedule.p6.model import (
    P6_LIMITS,
    PROFILE_ID,
    P6IssueCode,
    P6Limits,
    P6Outcome,
    P6ParseResult,
)
from my_pa.domain.schedule.p6.parser import parse_xer

__all__ = ["PROFILE_SCHEMA", "Verdict", "export_profile", "profile_report", "verdict"]

PROFILE_SCHEMA: Final = "p6-export-profile-v1"

_FINDINGS: Final = frozenset(
    {
        P6IssueCode.UNKNOWN_TABLE,
        P6IssueCode.UNKNOWN_FIELD,
        P6IssueCode.UNKNOWN_FIELD_UNNAMED,
        P6IssueCode.EXPORT_VERSION_UNTESTED,
        P6IssueCode.UNKNOWN_ENUM_VALUE,
    }
)
_TYPED_TIERS: Final = frozenset({Tier.REQUIRED.value, Tier.TOLERATED.value})

type _Json = bool | int | str | list[_Json] | dict[str, _Json] | None


class Verdict(StrEnum):
    """Section 12 verdicts; `fail` exits 1, the others 0."""

    FAIL = "fail"
    PASS_WITH_FINDINGS = "pass_with_findings"  # noqa: S105 - a verdict
    PASS = "pass"  # noqa: S105 - a verdict


def verdict(result: P6ParseResult) -> Verdict:
    """Section 12: fail, pass with findings, or pass."""
    if result.outcome is P6Outcome.FAILED:
        return Verdict.FAIL
    if any(field.over_length and field.tier in _TYPED_TIERS for field in result.observed_fields):
        return Verdict.FAIL
    # The counts, not the listed issues: the list stops at MAX_LISTED_ISSUES. Without a
    # fatal issue every `p6_unknown_enum_value` is a T/O finding.
    counted = {code for code, count in result.issue_counts if count}
    if counted & {code.value for code in _FINDINGS}:
        return Verdict.PASS_WITH_FINDINGS
    # An optional enumerated field that is not captured raises no issue, but its unknown
    # tokens are still a section 12 finding.
    if any(field.unknown_enum for field in result.observed_fields):
        return Verdict.PASS_WITH_FINDINGS
    return Verdict.PASS


def profile_report(result: P6ParseResult) -> dict[str, _Json]:
    """The stats-only report object of `result` (never a value)."""
    header = result.header
    tested: bool | None = None
    if header is not None:
        tested = header.export_version.startswith(TESTED_VERSION_PREFIX)
    return {
        "catalogue_version": CATALOGUE_VERSION,
        "encoding": None if header is None else header.encoding,
        "export_version_tested": tested,
        "fields": [
            {
                "captured": field.captured,
                "catalogued": field.catalogued,
                "field": field.field,
                "max_length": field.max_length,
                "min_length": field.min_length,
                "nonempty": field.nonempty,
                "over_length": field.over_length,
                "position": field.position,
                "records": field.records,
                "shapes": dict(field.shapes),
                "table": field.table,
                "table_position": field.table_position,
                "tier": field.tier,
                "unknown_enum": field.unknown_enum,
                "unknown_enum_tokens": list(field.unknown_enum_tokens),
            }
            for field in result.observed_fields
        ],
        "issue_counts": dict(result.issue_counts),
        "issues": [
            {
                "bound": None if issue.bound is None else issue.bound.value,
                "code": issue.code.value,
                "field": issue.field,
                "line": issue.line,
                "severity": issue.severity.value,
                "table": issue.table,
            }
            for issue in result.issues
        ],
        "profile_id": PROFILE_ID,
        "schema": PROFILE_SCHEMA,
        "tables": [
            {
                "catalogued": table.catalogued,
                "name": table.name,
                "position": table.position,
                "records": table.records,
            }
            for table in result.tables
        ],
        "verdict": verdict(result).value,
    }


def export_profile(data: bytes, *, limits: P6Limits = P6_LIMITS) -> dict[str, _Json]:
    """Parse `data` with the default capture selection and return its stats-only report."""
    return profile_report(parse_xer(data, limits=limits))
