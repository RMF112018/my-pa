"""The WP3b meeting sync tables stage no attendee, body or description (Manager rulings D2, D12).

A staged `meeting_sync_v1` event holds its provider key and exactly the
provider-owned Meeting fields of ruling D2 -- the fields the review capability
may return to the operator's own clients (D12) -- and nothing else: no attendee
address or name, no body, no description, no notes. Read off the declarations
in `tables.py`, which `tests/schema/test_meeting_sync_staging_migration.py`
proves equal to the revision.
"""

from __future__ import annotations

import re
from typing import Final

from my_pa.infrastructure.persistence.tables import MEETING_SYNC_TABLES, meeting_sync_events

_CONTENT_WORD: Final = re.compile(
    r"(^|_)(attendee|attendees|email|address|body|html|description|notes|display|raw)($|_)"
)

#: The D2 provider-owned fields, under the staging column names, plus the key.
_STAGED_EVENT_COLUMNS: Final = frozenset(
    {
        "event_id",
        "principal_id",
        "snapshot_id",
        "record_ordinal",
        "calendar_ref",
        "ical_uid",
        "series_ical_uid",
        "occurrence_original_start_utc",
        "start_utc",
        "end_utc",
        "timezone_name",
        "status",
        "title",
        "location_text",
        "virtual_meeting_url",
        "provider_event_id",
        "provider_event_id_format",
        "staged_at",
    }
)


def test_the_five_tables_are_the_ones_checked() -> None:
    assert len(MEETING_SYNC_TABLES) == 5


def test_no_column_holds_an_attendee_a_body_or_a_description() -> None:
    flagged = {
        (table.name, column.name)
        for table in MEETING_SYNC_TABLES
        for column in table.c
        if _CONTENT_WORD.search(column.name)
    }
    assert flagged == set()


def test_a_staged_event_holds_exactly_its_key_and_the_provider_owned_fields() -> None:
    assert {column.name for column in meeting_sync_events.c} == _STAGED_EVENT_COLUMNS


def test_the_planted_content_column_would_be_caught() -> None:
    """Prove-red for the matcher."""
    for name in ("attendees", "attendee_email", "body", "description", "notes", "display_name"):
        assert _CONTENT_WORD.search(name), name
    for name in ("title", "location_text", "virtual_meeting_url", "calendar_ref"):
        assert not _CONTENT_WORD.search(name), name
