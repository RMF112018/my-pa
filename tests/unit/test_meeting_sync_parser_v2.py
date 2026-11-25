"""WP3b-S2: `meeting_sync_v1` parser v2 and the contract 1.1.0 `coverage` (Manager ruling D7).

A 1.1.0 publication may declare `coverage {start_utc, end_utc, calendar_refs}`:
complete for those calendars over the inclusive window. Proved here, over
synthetic fixtures only: the committed 1.0 and 1.1 fixtures parse; a 1.0.x
publication keeps the parser v1 outcome (a `coverage` key there is an unknown
top-level key, ignored); a well-formed coverage is read exactly (references
sorted); each malformed coverage rejects the publication `invalid_coverage`
with its closed `CoverageDefect`, and no diagnostic carries a calendar
reference; the minor gate moved to 1.1.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.domain.meeting_sync.diagnostics import (
    CoverageDefect,
    DiagnosticCode,
    PublicationRejection,
)
from my_pa.domain.meeting_sync.model import (
    COLLECTOR_LOOKBACK,
    MAX_COVERAGE_CALENDAR_REFS,
    SUPPORTED_MINOR,
    PublicationCoverage,
)
from my_pa.infrastructure.meeting_sync.parser import (
    PARSER_VERSION,
    PublicationStatus,
    parse_publication,
)

FIXTURES: Final = Path(__file__).resolve().parents[1] / "fixtures" / "meeting_sync"
PRIVATE_REF: Final = "cal-synthetic-private-reference"


def _coverage(**overrides: object) -> dict[str, object]:
    coverage: dict[str, object] = {
        "start_utc": "2026-10-22T06:00:00Z",
        "end_utc": "2027-01-20T06:00:00Z",
        "calendar_refs": [PRIVATE_REF, "cal-synthetic-a"],
    }
    coverage.update(overrides)
    return coverage


def _publication(coverage: object, *, version: str = "1.1.0", **top: object) -> bytes:
    document: dict[str, Any] = {
        "schema": "meeting_sync_v1",
        "schema_version": version,
        "generated_at_utc": "2026-11-21T06:00:00Z",
        "events": [],
        "coverage": coverage,
    }
    document.update(top)
    return json.dumps(document).encode("utf-8")


def test_parser_v2_and_its_constants() -> None:
    assert PARSER_VERSION == "meeting_sync_v1_parser_v2"
    assert SUPPORTED_MINOR == 1
    assert MAX_COVERAGE_CALENDAR_REFS == 100
    assert COLLECTOR_LOOKBACK.days == 30


def test_the_committed_1_0_fixture_keeps_its_v1_outcome() -> None:
    parsed = parse_publication((FIXTURES / "sync_publication.json").read_bytes())
    assert parsed.status is PublicationStatus.ACCEPTED
    publication = parsed.publication
    assert publication is not None
    assert (publication.record_count, len(publication.events), len(publication.quarantined)) == (
        5,
        4,
        1,
    )
    assert publication.coverage is None
    assert dict(parsed.diagnostics.code_counts) == {
        "all_day_unsupported": 1,
        "content_field_ignored": 1,
        "timezone_not_iana": 1,
    }


def test_the_committed_1_1_fixture_declares_its_coverage() -> None:
    parsed = parse_publication((FIXTURES / "sync_publication_v1_1.json").read_bytes())
    assert parsed.status is PublicationStatus.ACCEPTED
    publication = parsed.publication
    assert publication is not None
    assert str(publication.schema_version) == "1.1.0"
    assert publication.coverage == PublicationCoverage(
        start_utc=datetime(2026, 10, 23, 6, tzinfo=UTC),
        end_utc=datetime(2027, 1, 21, 6, tzinfo=UTC),
        calendar_refs=("cal-synthetic-primary", "cal-synthetic-secondary"),
    )
    # Same events as the 1.0 fixture: coverage changes no record outcome.
    assert (len(publication.events), len(publication.quarantined)) == (4, 1)
    assert DiagnosticCode.SCHEMA_MINOR_NEWER.value not in parsed.diagnostics.code_counts
    assert DiagnosticCode.UNKNOWN_TOP_LEVEL_KEYS.value not in parsed.diagnostics.code_counts


def test_coverage_is_optional_in_1_1() -> None:
    document = json.loads(_publication(_coverage()))
    del document["coverage"]
    parsed = parse_publication(json.dumps(document).encode())
    assert parsed.publication is not None
    assert parsed.publication.coverage is None
    assert dict(parsed.diagnostics.code_counts) == {}


@pytest.mark.parametrize("coverage", [_coverage(), "not even an object", None])
def test_a_coverage_key_in_1_0_is_an_ignored_unknown_key(coverage: object) -> None:
    parsed = parse_publication(_publication(coverage, version="1.0.3"))
    assert parsed.status is PublicationStatus.ACCEPTED
    assert parsed.publication is not None
    assert parsed.publication.coverage is None
    assert dict(parsed.diagnostics.code_counts) == {DiagnosticCode.UNKNOWN_TOP_LEVEL_KEYS.value: 1}


def test_a_newer_minor_still_reads_coverage_and_is_reported() -> None:
    parsed = parse_publication(_publication(_coverage(), version="1.2.0"))
    assert parsed.publication is not None
    assert parsed.publication.coverage is not None
    assert parsed.diagnostics.code_counts[DiagnosticCode.SCHEMA_MINOR_NEWER.value] == 1


def test_a_single_instant_window_and_offset_spelling_are_accepted() -> None:
    parsed = parse_publication(
        _publication(
            _coverage(
                start_utc="2026-11-21T06:00:00+00:00",
                end_utc="2026-11-21T06:00:00.000000Z",
                calendar_refs=["x"],
            )
        )
    )
    assert parsed.publication is not None
    coverage = parsed.publication.coverage
    assert coverage is not None
    assert coverage.start_utc == coverage.end_utc == datetime(2026, 11, 21, 6, tzinfo=UTC)
    assert coverage.calendar_refs == ("x",)


def test_the_most_calendar_refs_are_accepted() -> None:
    refs = [f"cal-{index:03d}" for index in range(MAX_COVERAGE_CALENDAR_REFS)]
    parsed = parse_publication(_publication(_coverage(calendar_refs=refs)))
    assert parsed.publication is not None
    assert parsed.publication.coverage is not None
    assert len(parsed.publication.coverage.calendar_refs) == MAX_COVERAGE_CALENDAR_REFS


def _without(key: str) -> dict[str, object]:
    coverage = _coverage()
    del coverage[key]
    return coverage


MALFORMED: Final[list[tuple[str, object, CoverageDefect]]] = [
    ("null", None, CoverageDefect.NOT_AN_OBJECT),
    ("list", [], CoverageDefect.NOT_AN_OBJECT),
    ("no_start", _without("start_utc"), CoverageDefect.INCOMPLETE),
    ("no_end", _without("end_utc"), CoverageDefect.INCOMPLETE),
    ("no_refs", _without("calendar_refs"), CoverageDefect.INCOMPLETE),
    ("empty_object", {}, CoverageDefect.INCOMPLETE),
    ("extra_key", _coverage(excluded=[]), CoverageDefect.UNKNOWN_KEY),
    ("naive_start", _coverage(start_utc="2026-10-22T06:00:00"), CoverageDefect.INVALID_TIMESTAMP),
    ("bad_end", _coverage(end_utc="tomorrow"), CoverageDefect.INVALID_TIMESTAMP),
    ("numeric_start", _coverage(start_utc=0), CoverageDefect.INVALID_TIMESTAMP),
    ("offset_start", _coverage(start_utc="2026-10-22T01:00:00-05:00"), CoverageDefect.NOT_UTC),
    ("offset_end", _coverage(end_utc="2027-01-20T07:00:00+01:00"), CoverageDefect.NOT_UTC),
    ("negative_zero", _coverage(end_utc="2027-01-20T06:00:00-00:00"), CoverageDefect.NOT_UTC),
    (
        "end_before_start",
        _coverage(start_utc="2026-11-21T06:00:01Z", end_utc="2026-11-21T06:00:00Z"),
        CoverageDefect.END_BEFORE_START,
    ),
    ("refs_string", _coverage(calendar_refs=PRIVATE_REF), CoverageDefect.CALENDAR_REFS_NOT_A_LIST),
    ("refs_empty", _coverage(calendar_refs=[]), CoverageDefect.CALENDAR_REFS_EMPTY),
    (
        "refs_too_many",
        _coverage(calendar_refs=[f"c{i}" for i in range(MAX_COVERAGE_CALENDAR_REFS + 1)]),
        CoverageDefect.CALENDAR_REFS_TOO_MANY,
    ),
    ("ref_number", _coverage(calendar_refs=[7]), CoverageDefect.CALENDAR_REF_UNREPRESENTABLE),
    ("ref_empty", _coverage(calendar_refs=[""]), CoverageDefect.CALENDAR_REF_UNREPRESENTABLE),
    ("ref_blank", _coverage(calendar_refs=["   "]), CoverageDefect.CALENDAR_REF_UNREPRESENTABLE),
    ("ref_null", _coverage(calendar_refs=[None]), CoverageDefect.CALENDAR_REF_UNREPRESENTABLE),
    (
        "ref_too_long",
        _coverage(calendar_refs=["c" * 321]),
        CoverageDefect.CALENDAR_REF_UNREPRESENTABLE,
    ),
    (
        "ref_duplicate",
        _coverage(calendar_refs=[PRIVATE_REF, "cal-synthetic-a", PRIVATE_REF]),
        CoverageDefect.DUPLICATE_CALENDAR_REF,
    ),
]


@pytest.mark.parametrize(
    ("coverage", "defect"),
    [(coverage, defect) for _, coverage, defect in MALFORMED],
    ids=[name for name, _, _ in MALFORMED],
)
def test_a_malformed_coverage_rejects_with_its_defect(
    coverage: object, defect: CoverageDefect
) -> None:
    parsed = parse_publication(_publication(coverage))
    assert parsed.status is PublicationStatus.REJECTED
    assert parsed.rejection is PublicationRejection.INVALID_COVERAGE
    assert parsed.publication is None
    (entry,) = parsed.diagnostics.entries
    assert (entry.code, entry.path, entry.detail) == (
        PublicationRejection.INVALID_COVERAGE,
        "coverage",
        (("defect", defect),),
    )
    assert PRIVATE_REF not in repr(parsed.diagnostics)


def test_every_defect_is_exercised() -> None:
    assert {defect for _, _, defect in MALFORMED} == set(CoverageDefect)


def test_a_ref_at_the_binding_bound_is_accepted() -> None:
    parsed = parse_publication(_publication(_coverage(calendar_refs=["c" * 320])))
    assert parsed.publication is not None


def test_coverage_is_checked_after_the_envelope() -> None:
    # A malformed envelope field decides before the coverage is looked at.
    parsed = parse_publication(_publication(None, cycle_run_id=""))
    assert parsed.rejection is PublicationRejection.INVALID_TOP_LEVEL_FIELD
