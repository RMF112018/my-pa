"""WP5-S3: the `meetings.context.read` assembler over the FAST fakes.

`MeetingContextReads` over `IngestUnitOfWork`: the Meeting plane is the conftest
fake (Meetings made through `MeetingApplication.create_meeting`), the
communications plane `FakeCommunications`, whose candidate statement is canned
(the statement itself is the database tier's,
`tests/database/test_meeting_context_communications.py`). Proved here:

* the request bounds and their SafeDetail tokens; duplicates dropped;
* what the one candidate query asks: the owner's keys excluded, the bridged
  non-ASCII spellings added under their attendee key, `gmp` never asked, a
  Meeting with nothing to ask not asked at all, one call for the whole batch;
* how a returned row is rendered: `matched_by`, the matched attendees and
  identifiers in the Meeting's own order, the limit, `matched_total` and
  `truncated`, and **never a snippet of a withheld or truncated body** (the
  assembler's own guard, whatever the statement returns);
* the provider binding states and `not_found`.

Every value is synthetic.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.meeting_context import (
    MeetingContextReads,
    MeetingContextRequest,
    context_payload,
)
from my_pa.application.meetings import MeetingApplication
from my_pa.contracts.ports import (
    CommunicationMailboxItemRecord,
    CommunicationMessageRecord,
    CommunicationObservationRecord,
    CommunicationParticipantRecord,
    CommunicationProjection,
    MeetingContextCandidateRow,
    MeetingProviderReviewMarkRecord,
)
from my_pa.domain.meeting.model import MeetingCreateRequest, normalize_attendee
from tests.conftest import World
from tests.unit.communications_ingest_fakes import IngestUnitOfWork, IngestWorld

P: Final = "prn_ctxassembly0001"
NOW: Final = datetime(2026, 11, 21, 12, tzinfo=UTC)
START: Final = NOW - timedelta(hours=3)
APP: Final = MeetingApplication()
A: Final = "alpha.ctx@example.test"
B: Final = "bravo.ctx@example.test"
SELF: Final = "owner.ctx@example.test"
#: Stored `lower`, attendee `casefold` (ruling D11).
SHARP_STORED: Final = "straße.ctx@example.test"
SHARP_KEY: Final = "strasse.ctx@example.test"


class Fixture:
    def __init__(self) -> None:
        self.meetings = World()
        self.mail = IngestWorld()
        self.unit = IngestUnitOfWork(self.mail, meetings=self.meetings)
        self._n = 0

    def meeting(
        self, *, title: str = "Coordination", emails: tuple[str, ...] = (), **fields: object
    ) -> str:
        self._n += 1
        request = MeetingCreateRequest(
            title=title,
            start_at=START,
            timezone_name="UTC",
            attendees=tuple(normalize_attendee(email=email) for email in emails),
            **fields,  # type: ignore[arg-type]
        )
        created = APP.create_meeting(self.unit, P, request, f"ctx-{self._n}", NOW)
        return created.meeting.meeting_id

    def participant(self, n: int, address: str, *, sent: bool = False) -> None:
        """One synthetic message whose `from` is `address` (in the sent lane when `sent`)."""
        message_id, item_id, observation_id = (
            f"cmsg_ctxfast{n:06d}",
            f"cmitm_ctxfast{n:06d}",
            f"cobs_ctxfast{n:06d}",
        )
        communications = self.unit.communications
        communications.insert_message(
            P,
            CommunicationMessageRecord(
                message_id=message_id,
                mailbox_ref="mbx-synthetic",
                identity_kind="provider_returned",
                identity_value=f"<{n}@example.invalid>",
                conversation_id=None,
                subject="Plain",
                sender_address=address,
                message_time=START - timedelta(days=1),
                message_time_basis="sent",
                has_attachments=False,
                projection=CommunicationProjection(
                    body_state="present",
                    body_sha256="0" * 64,
                    body_utf8_bytes=1,
                    content_type="text",
                    search_text="x",
                    search_text_sha256="1" * 64,
                    search_text_version="comms_search_text_v2",
                    search_text_basis="body_content",
                    search_text_flags=(),
                    text_snapshot_id="isnp_ctxfast000001",
                    text_record_ordinal=n,
                ),
                first_snapshot_id="isnp_ctxfast000001",
                latest_snapshot_id="isnp_ctxfast000001",
            ),
        )
        communications.insert_item(
            P,
            CommunicationMailboxItemRecord(
                item_id=item_id,
                message_id=message_id,
                mailbox_ref="mbx-synthetic",
                provider_id=f"AAMk-{n}",
                provider_id_format="mutable",
                first_snapshot_id="isnp_ctxfast000001",
            ),
        )
        communications.insert_observation(
            P,
            CommunicationObservationRecord(
                observation_id=observation_id,
                item_id=item_id,
                snapshot_id="isnp_ctxfast000001",
                record_ordinal=n,
                classification="accepted",
                reasons=(),
                folder_role="sent" if sent else "inbox",
                lane_verification="verified",
                selected_field="sent",
                selected_utc=START,
                received_utc=None,
                received_state="absent",
                sent_utc=START,
                sent_state="present",
                body_sha256="0" * 64,
                unique_body_sha256=None,
                participants={"from": (address,)},
            ),
        )
        communications.insert_participants(
            P,
            [CommunicationParticipantRecord(message_id, "from", address, observation_id)],
        )

    def reads(self) -> MeetingContextReads:
        return MeetingContextReads(unit_of_work=lambda: self.unit, clock=lambda: NOW)

    def read(self, ids: list[str], **fields: object) -> object:
        return self.reads().read(P, MeetingContextRequest(meeting_ids=ids, **fields))  # type: ignore[arg-type]


def _row(ordinal: int, n: int, **fields: object) -> MeetingContextCandidateRow:
    values: dict[str, object] = {
        "ordinal": ordinal,
        "message_id": f"cmsg_ctxrow{n:06d}",
        "conversation_id": None,
        "message_time": START - timedelta(hours=n),
        "subject": "Synthetic subject",
        "sender_address": A,
        "has_attachments": False,
        "body_state": "present",
        "search_text_version": "comms_search_text_v2",
        "search_text_flags": (),
        "identity_conflict": False,
        "participants_reconciled": False,
        "participants_disagreed": False,
        "source_unavailable": False,
        "tier": 3,
        "overlap": 1,
        "rank": 0,
        "matched_keys": (A,),
        "matched_identifiers": (),
        "title_hit": False,
        "project_number_hit": False,
        "conversation_hits": 1,
        "matched_total": 1,
        "snippet": "synthetic snippet",
    }
    values.update(fields)
    return MeetingContextCandidateRow(**values)  # type: ignore[arg-type]


# ---- the request ------------------------------------------------------------------


@pytest.mark.parametrize(
    ("fields", "token"),
    [
        ({"meeting_ids": []}, SafeDetail.MEETING_IDS),
        ({"meeting_ids": "mtg_" + "0" * 26}, SafeDetail.MEETING_IDS),
        ({"meeting_ids": ["mtg_" + "0" * 26] * 11}, SafeDetail.MEETING_IDS),
        ({"meeting_ids": ["mser_" + "0" * 26]}, SafeDetail.MEETING_IDS),
        ({"lookback_days": 0}, SafeDetail.LOOKBACK_DAYS),
        ({"lookback_days": 91}, SafeDetail.LOOKBACK_DAYS),
        ({"lookback_days": True}, SafeDetail.LOOKBACK_DAYS),
        ({"per_meeting_limit": 0}, SafeDetail.PER_MEETING_LIMIT),
        ({"per_meeting_limit": 51}, SafeDetail.PER_MEETING_LIMIT),
    ],
)
def test_the_request_bounds(fields: dict[str, object], token: SafeDetail) -> None:
    values: dict[str, object] = {"meeting_ids": ["mtg_" + "0" * 26]}
    values.update(fields)
    with pytest.raises(InvalidRequestError) as refused:
        Fixture().reads().read(P, MeetingContextRequest(**values))  # type: ignore[arg-type]
    assert refused.value.safe_details == (token,)


# ---- what is asked ----------------------------------------------------------------


def test_one_query_for_the_batch_with_self_excluded_and_the_bridge_added() -> None:
    f = Fixture()
    f.participant(1, SELF, sent=True)
    f.participant(2, SHARP_STORED)
    asking = f.meeting(emails=(A, SELF, "Straße.ctx@example.test"), description="RFI 7 and GMP")
    nothing = f.meeting(title="Weekly sync")
    third = f.meeting(emails=(B,))
    answer = f.read([asking, nothing, third, asking])
    assert len(f.mail.context_calls) == 1
    (query,) = f.mail.context_calls
    assert [m.ordinal for m in query.meetings] == [0, 2]
    first = query.meetings[0]
    assert set(first.addresses) == {(A, A), (SHARP_KEY, SHARP_KEY), (SHARP_STORED, SHARP_KEY)}
    assert first.identifiers == (("rfi", "7"),)
    assert first.title_terms == ("coordination",)
    assert (query.limit, query.identifier_version) == (15, "comms_identifiers_v2")
    contexts = answer.meetings  # type: ignore[attr-defined]
    assert [c.meeting.meeting_id for c in contexts] == [asking, nothing, third]
    assert contexts[1].communications.state.value == "no_inputs"
    assert [a.is_self for a in contexts[0].attendees].count(True) == 1


def test_nothing_to_ask_issues_no_candidate_statement() -> None:
    f = Fixture()
    answer = f.read([f.meeting(title="Weekly sync")])
    assert f.mail.context_calls == []
    assert answer.meetings[0].communications.messages == ()  # type: ignore[attr-defined]


# ---- how rows are rendered --------------------------------------------------------------


def test_a_withheld_or_truncated_body_never_has_a_snippet() -> None:
    """The assembler's own guard (prove-red m10): the statement's row is not trusted."""
    f = Fixture()
    meeting = f.meeting(emails=(A,))
    f.mail.context_rows = [
        _row(0, 1, body_state="withheld", snippet="leaked withheld text", matched_total=3),
        _row(0, 2, body_state="truncated", snippet="leaked truncated text", matched_total=3),
        _row(0, 3, snippet="s" * 400, matched_total=3),
    ]
    (context,) = f.read([meeting]).meetings  # type: ignore[attr-defined]
    assert [m.snippet for m in context.communications.messages] == [None, None, "s" * 300]
    assert "leaked" not in repr(context_payload(f.read([meeting])))  # type: ignore[arg-type]


def test_reasons_attendees_identifiers_limit_and_total() -> None:
    f = Fixture()
    meeting = f.meeting(title="RFI 9 slab", emails=(A, B), description="CO 2")
    f.mail.context_rows = [
        _row(
            0,
            n,
            tier=1,
            overlap=2,
            matched_keys=(A, B),
            matched_identifiers=(("co", "2"), ("rfi", "9")),
            title_hit=True,
            project_number_hit=True,
            matched_total=4,
        )
        for n in range(1, 5)
    ]
    answer = f.read([meeting], per_meeting_limit=2)
    (context,) = answer.meetings  # type: ignore[attr-defined]
    section = context.communications
    assert len(section.messages) == 2
    assert (section.matched_total, section.truncated) == (4, True)
    first = section.messages[0]
    assert [r.value for r in first.matched_by] == [
        "participants",
        "identifiers",
        "project_number",
        "title_terms",
    ]
    ids = {a.email: a.attendee_id for a in context.attendees}
    assert set(first.matched_attendee_ids) == {ids[A], ids[B]}
    # The Meeting's order: the title's RFI 9 before the description's CO 2.
    assert first.matched_identifiers == ("rfi:9", "co:2")


def test_the_binding_states_and_not_found() -> None:
    f = Fixture()
    meeting = f.meeting(emails=(A,))
    unknown = "mtg_" + "0" * 26
    answer = f.read([unknown, meeting])
    (context,) = answer.meetings  # type: ignore[attr-defined]
    assert context.provider_binding_state.value == "unbound"
    assert "provider_unbound" in [c.value for c in context.communications.missing]
    assert answer.not_found == (unknown,)  # type: ignore[attr-defined]
    f.meetings.meeting_provider_review_marks[(P, meeting)] = MeetingProviderReviewMarkRecord(
        meeting_id=meeting, marked_at=NOW
    )
    (marked,) = f.read([meeting]).meetings  # type: ignore[attr-defined]
    assert marked.provider_binding_state.value == "no_provider_event"


def test_the_payload_has_no_input_address_or_term() -> None:
    f = Fixture()
    f.participant(1, SELF, sent=True)
    meeting = f.meeting(title="Curtain wall", emails=(A, SELF))
    f.mail.context_rows = [replace(_row(0, 1), subject=None)]
    payload = context_payload(f.read([meeting]))  # type: ignore[arg-type]
    rendered = repr(payload["self_addresses"]) + repr(payload["versions"])
    assert SELF not in rendered
    (entry,) = payload["meetings"]  # type: ignore[misc]
    assert "curtain" not in repr(entry["communications"]["inputs"]).lower()  # type: ignore[index]
