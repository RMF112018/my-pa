"""Quarantine records carry identifiers and codes, and have nowhere to put a payload.

`docs/specs` section 12 constrains what a quarantine may keep: "IDs, safe reason
codes, and review state—not unsafe payloads". The tests here are about the record
*shape*, because that is the level at which the constraint can actually hold: a
test that only checked the fields today's writers happen to set would pass
against a record type that had grown a `text` column nobody filled in yet.
"""

from __future__ import annotations

from dataclasses import fields
from datetime import UTC, datetime

import pytest

from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError
from my_pa.domain.common.time import NaiveDatetimeError
from my_pa.domain.extraction.quarantine import (
    QuarantineReason,
    QuarantineRecord,
    QuarantineReviewState,
)
from my_pa.domain.source.registry import issue_identifier

QUARANTINED_AT = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)

#: Restated, not imported: the triggers of `docs/specs` section 12, with the two
#: foldings the module documents. A trigger that disappeared from the enum would
#: otherwise disappear from the test with it.
EXPECTED_REASONS = frozenset(
    {
        "containment_unproven",
        "media_type_conflicts_with_signature",
        "parser_failed",
        "parser_timed_out",
        "resource_limit_exceeded",
        "malformed_input",
        "source_version_changed",
        "output_not_attributable_to_version",
    }
)

#: Every field a quarantine record has. Restated so that adding one is a change
#: to this list as well as to the type.
EXPECTED_FIELDS = frozenset(
    {
        "quarantine_id",
        "enrollment_id",
        "source_object_id",
        "version_id",
        "reason",
        "review_state",
        "quarantined_at",
    }
)

#: Names a payload would plausibly arrive under. Not the guard — `EXPECTED_FIELDS`
#: is — but a second, differently-shaped check, so a field added *and* added to
#: the list above still trips something.
PAYLOAD_SHAPED_NAMES = frozenset(
    {
        "text",
        "content",
        "body",
        "payload",
        "bytes",
        "excerpt",
        "snippet",
        "sample",
        "message",
        "detail",
        "details",
        "note",
        "path",
        "locator",
        "filename",
        "native_locator",
    }
)


def _record(**overrides: object) -> QuarantineRecord:
    values: dict[str, object] = {
        "quarantine_id": issue_identifier(IdKind.KNOWLEDGE),
        "enrollment_id": issue_identifier(IdKind.ENROLLMENT),
        "source_object_id": issue_identifier(IdKind.SOURCE_OBJECT),
        "version_id": issue_identifier(IdKind.VERSION),
        "reason": QuarantineReason.MALFORMED_INPUT,
        "review_state": QuarantineReviewState.PENDING_REVIEW,
        "quarantined_at": QUARANTINED_AT,
    }
    values.update(overrides)
    return QuarantineRecord(**values)  # type: ignore[arg-type]


def test_the_record_has_exactly_these_fields() -> None:
    assert {field.name for field in fields(QuarantineRecord)} == EXPECTED_FIELDS


def test_no_field_of_a_quarantine_record_could_hold_the_thing_that_failed() -> None:
    """The structural claim, checked a second way.

    Every field is an opaque identifier, an enumerated code, or a timestamp. If
    one of these names ever appears, the record has become the payload channel
    section 12 forbids, whether or not anything writes to it yet.
    """
    present = {field.name for field in fields(QuarantineRecord)} & PAYLOAD_SHAPED_NAMES
    assert not present, f"a quarantine record could carry {sorted(present)}"


def test_every_section_twelve_trigger_has_a_code() -> None:
    assert {reason.value for reason in QuarantineReason} == EXPECTED_REASONS


def test_a_reason_is_a_closed_code_and_not_free_text() -> None:
    """The reason is what a reviewer reads, and a free-text reason is where the
    rejected value would end up."""
    with pytest.raises(ValueError, match="not a valid QuarantineReason"):
        QuarantineReason("the file /synthetic/x.txt could not be parsed")


def test_a_record_binds_the_object_the_enrollment_and_the_version() -> None:
    record = _record()

    assert record.quarantine_id.startswith("kn_")
    assert record.enrollment_id.startswith("enr_")
    assert record.source_object_id.startswith("obj_")
    assert record.review_state is QuarantineReviewState.PENDING_REVIEW


def test_a_quarantine_may_predate_any_proven_version() -> None:
    """Containment can fail before a version was observed.

    Recording a version that was never proven would attribute the quarantine to
    bytes nobody saw, so the absence has to be representable.
    """
    record = _record(version_id=None, reason=QuarantineReason.CONTAINMENT_UNPROVEN)

    assert record.version_id is None


@pytest.mark.parametrize(
    "field",
    ["quarantine_id", "enrollment_id", "source_object_id", "version_id"],
)
def test_every_identifier_is_validated_for_its_own_kind(field: str) -> None:
    """A `ver_…` in the object slot would misfile the record silently."""
    with pytest.raises(InvalidIdentifierError):
        _record(**{field: "/synthetic/fixtures/corpus/note.md"})


def test_an_identifier_of_the_wrong_kind_is_refused() -> None:
    with pytest.raises(InvalidIdentifierError, match="expected 'obj'"):
        _record(source_object_id=issue_identifier(IdKind.VERSION))


def test_a_naive_timestamp_is_refused_rather_than_assumed_to_be_utc() -> None:
    with pytest.raises(NaiveDatetimeError):
        _record(quarantined_at=datetime(2026, 8, 1, 12, 0))


def test_the_review_state_is_the_one_that_is_reachable() -> None:
    """Section 12 requires a review state; nothing yet can set a second one.

    Reprocessing is "explicit bounded recovery and new operation/audit", which
    does not exist, so a `released` member would be a state no code path could
    reach — a promise the record cannot keep.
    """
    assert [state.value for state in QuarantineReviewState] == ["pending_review"]
