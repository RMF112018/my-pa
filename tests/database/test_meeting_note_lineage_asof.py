"""AT-002: Meeting note evidence is pinned to the exact version it cites (S1).

S1 contract sections 3.1, 5.2 and 7.2 against PostgreSQL. A later note
version -- `replace` or `append` -- never moves an origin anchor; the two
note-history reads return the original body and digest (only
`meetings.notes.read_version`, and the body only on request) and the version
list carries neither; and a digest of the newer note is refused for the older
version. Every body is synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Iterator

import pytest

from my_pa.application.commands import (
    ListMeetingNoteVersions,
    ReadMeetingNoteVersion,
    ReadRecordLineage,
)
from my_pa.domain.meeting.model import MeetingNotesMode
from tests.database.lineage_issue_harness import LineageRuntime
from tests.database.lineage_record_harness import (
    GATEWAY,
    NOTE_BODY,
    all_lineage_counts,
    commitment,
    meeting,
    note,
    note_anchor,
    originated_from,
    revise_notes,
)

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[LineageRuntime]:
    composed = LineageRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _origin_survives(runtime: LineageRuntime, mode: MeetingNotesMode) -> None:
    key = f"asof-{mode.value}"
    m1, n1 = meeting(runtime, key)
    c1 = commitment(runtime, key)
    written = runtime.ok(
        originated_from(
            "commitment", c1, "meeting_note_version", n1, key, (note_anchor(m1, n1, NOTE_BODY),)
        ),
        surface=GATEWAY,
    )
    original = written["association"]
    n2 = revise_notes(runtime, m1, key, body="A later synthetic note.", mode=mode)
    assert n2 != n1
    answer = runtime.ok(ReadRecordLineage(origin={"family": "commitment", "record_id": c1}))
    (edge,) = answer["typed_edges"]
    assert edge == original
    assert edge["to"]["record_id"] == n1
    assert edge["evidence"][0]["version_id"] == n1
    assert edge["evidence"][0]["source_version_no"] == 1


def test_origin_anchor_survives_a_later_note_replace(runtime: LineageRuntime) -> None:
    _origin_survives(runtime, MeetingNotesMode.REPLACE)


def test_origin_anchor_survives_a_later_note_append(runtime: LineageRuntime) -> None:
    _origin_survives(runtime, MeetingNotesMode.APPEND)


def test_read_version_returns_the_original_body_and_digest(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "read-version")
    n2 = revise_notes(runtime, m1, "read-version", body="Appended.", mode=MeetingNotesMode.APPEND)
    older = note(runtime, m1, n1)
    assert older["body_markdown"] == NOTE_BODY
    assert older["content_sha256"] == hashlib.sha256(NOTE_BODY.encode("utf-8")).hexdigest()
    assert older["version_number"] == 1 and older["is_current"] is False
    assert older["character_count"] == len(NOTE_BODY)
    newer = note(runtime, m1, n2)
    assert newer["body_markdown"] == NOTE_BODY + "\n\nAppended."
    assert newer["supersedes_note_version_id"] == n1 and newer["is_current"] is True
    # Without `include_body` the digest is still returned and the body is not.
    bare = runtime.ok(ReadMeetingNoteVersion(meeting_id=m1, note_version_id=n1))
    assert "body_markdown" not in bare["note"]
    assert bare["note"]["content_sha256"] == older["content_sha256"]
    assert bare["evidence_availability"] == "available"


def test_versions_list_carries_no_body_or_digest(runtime: LineageRuntime) -> None:
    m1, n1 = meeting(runtime, "versions")
    n2 = revise_notes(runtime, m1, "versions-2", body="Second synthetic note.")
    n3 = revise_notes(runtime, m1, "versions-3", body="Third synthetic note.")
    first = runtime.ok(ListMeetingNoteVersions(meeting_id=m1, page_size=2))
    assert first["meeting_id"] == m1
    assert [row["note_version_id"] for row in first["versions"]] == [n3, n2]
    assert first["next_cursor"] == n2
    for row in first["versions"]:
        assert set(row) == {
            "note_version_id",
            "version_number",
            "supersedes_note_version_id",
            "character_count",
            "recorded_at",
            "is_current",
        }
    assert [row["is_current"] for row in first["versions"]] == [True, False]
    second = runtime.ok(ListMeetingNoteVersions(meeting_id=m1, page_size=2, after=n2))
    assert [row["note_version_id"] for row in second["versions"]] == [n1]
    assert second["next_cursor"] is None
    other, other_note = meeting(runtime, "versions-other")
    cursor = runtime.refused(ListMeetingNoteVersions(meeting_id=m1, after=other_note))
    assert cursor["code"] == "invalid_request" and cursor["safe_details"] == ["cursor"]
    assert other


def test_a_digest_of_the_newer_note_is_refused_for_the_older_version(
    runtime: LineageRuntime,
) -> None:
    m1, n1 = meeting(runtime, "spoof-newer")
    newer_body = "Ana will send the façade survey on Monday instead."
    revise_notes(runtime, m1, "spoof-newer", body=newer_body)
    c1 = commitment(runtime, "spoof-newer")
    newer_digest = hashlib.sha256(newer_body.encode("utf-8")).hexdigest()
    before = all_lineage_counts(runtime.engine)
    error = runtime.refused(
        originated_from(
            "commitment",
            c1,
            "meeting_note_version",
            n1,
            "spoof-newer",
            (note_anchor(m1, n1, NOTE_BODY, source_sha256=newer_digest),),
        ),
        surface=GATEWAY,
    )
    assert error["code"] == "invalid_request"
    assert error["safe_details"] == ["evidence_anchors"]
    assert all_lineage_counts(runtime.engine) == before


def test_versions_list_defaults_to_twenty_five_per_page(runtime: LineageRuntime) -> None:
    """Section 7.2: `page_size` defaults to 25 (as published), not the process default.

    The harness's process default page size is 50, so a list without
    `page_size` over 26 versions shows whether the S1 default or the
    process-wide one applies.
    """
    m1, n1 = meeting(runtime, "versions-default")
    for index in range(2, 27):
        revise_notes(runtime, m1, f"versions-default-{index}", body=f"Synthetic note {index}.")
    first = runtime.ok(ListMeetingNoteVersions(meeting_id=m1))
    assert len(first["versions"]) == 25
    assert [row["version_number"] for row in first["versions"]] == list(range(26, 1, -1))
    assert first["next_cursor"] == first["versions"][-1]["note_version_id"]
    rest = runtime.ok(ListMeetingNoteVersions(meeting_id=m1, after=first["next_cursor"]))
    assert [row["note_version_id"] for row in rest["versions"]] == [n1]
    assert rest["next_cursor"] is None
    whole = runtime.ok(ListMeetingNoteVersions(meeting_id=m1, page_size=100))
    assert len(whole["versions"]) == 26 and whole["next_cursor"] is None
