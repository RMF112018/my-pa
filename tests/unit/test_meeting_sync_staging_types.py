"""WP3b-S1: the meeting sync staging port types (FAST).

The closed apply vocabulary (Manager ruling D8) is exactly the three values the
revision's CHECK freezes; a staged publication is unapplied and coverage-free
unless stated; a binding names no snapshot unless stated (an explicit bind,
ruling D10); the `msevt` identifier kind is the staged event's reference.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from my_pa.contracts.ports import (
    MeetingProviderBindingRecord,
    MeetingProviderKeyTombstoneRecord,
    MeetingProviderReconciliationPassRecord,
    MeetingProviderReviewMarkRecord,
    MeetingSyncApplyOutcome,
    MeetingSyncEventRecord,
    MeetingSyncPublicationRecord,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.meeting_sync.model import ProviderBindingState, ProviderEventIdFormat
from my_pa.domain.source.registry import issue_identifier

WHEN = datetime(2026, 11, 23, 12, tzinfo=UTC)


def test_the_apply_vocabulary_is_closed() -> None:
    assert [member.value for member in MeetingSyncApplyOutcome] == [
        "applied",
        "skipped_stale",
        "skipped_ordering_conflict",
    ]


def test_a_publication_is_unapplied_and_coverage_free_by_default() -> None:
    publication = MeetingSyncPublicationRecord(
        snapshot_id="isnp_types0001",
        ingest_source_id="isrc_types0001",
        generated_at_utc=WHEN,
        record_count=1,
        accepted_count=1,
        quarantined_count=0,
        staged_at=WHEN,
    )
    assert (publication.applied_at, publication.apply_outcome, publication.apply_counts) == (
        None,
        None,
        None,
    )
    assert (
        publication.coverage_start_utc,
        publication.coverage_end_utc,
        publication.coverage_calendar_refs,
    ) == (None, None, None)


def test_a_binding_names_no_snapshot_unless_stated() -> None:
    binding = MeetingProviderBindingRecord(
        binding_id="mpbnd_types0001",
        meeting_id="mtg_types0001",
        calendar_ref="cal",
        ical_uid="uid@example.invalid",
        occurrence_original_start_utc=None,
        series_ical_uid=None,
        provider_event_id=None,
        provider_event_id_format=ProviderEventIdFormat.UNKNOWN,
        provider_state=ProviderBindingState.ACTIVE,
        last_seen_source_sha256=None,
        last_seen_record_ordinal=None,
        last_seen_at=None,
        version=1,
        created_at=WHEN,
        updated_at=WHEN,
    )
    assert (binding.origin_snapshot_id, binding.last_seen_snapshot_id) == (None, None)


@pytest.mark.parametrize(
    "record",
    [
        MeetingSyncPublicationRecord,
        MeetingSyncEventRecord,
        MeetingProviderReviewMarkRecord,
        MeetingProviderReconciliationPassRecord,
        MeetingProviderKeyTombstoneRecord,
    ],
)
def test_the_records_are_frozen_and_carry_no_principal(record: type) -> None:
    """The Principal is a repository parameter, never a record field."""
    assert record.__dataclass_params__.frozen  # type: ignore[attr-defined]
    assert "principal_id" not in {field.name for field in dataclasses.fields(record)}


def test_a_staged_event_holds_no_attendee_or_body() -> None:
    names = {field.name for field in dataclasses.fields(MeetingSyncEventRecord)}
    assert not {"attendees", "description", "body", "notes"} & names


def test_the_staged_event_reference_is_an_msevt_identifier() -> None:
    reference = issue_identifier(IdKind.MEETING_SYNC_EVENT)
    assert reference.startswith("msevt_")
    validate_identifier(reference, IdKind.MEETING_SYNC_EVENT)
