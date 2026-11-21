"""Corpus v2 shapes: lane observations of one mailbox item, participant reconciliation,
lane verification, null participants, empty subjects, null sent times, weekend/DST windows."""

from __future__ import annotations

import copy
import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from my_pa.domain.communications.corpus import Interval, summarize_corpus
from my_pa.domain.communications.diagnostics import DiagnosticCode, ReasonCode
from my_pa.domain.communications.model import (
    FolderRole,
    ItemFlag,
    LaneVerification,
    MailboxItem,
    MessageTimeBasis,
    ParticipantState,
    Publication,
    RecordClassification,
    TimestampState,
    WindowRule,
)
from my_pa.domain.communications.search_text import derive_search_text
from my_pa.infrastructure.communications.aggregate_cli import summarize_files
from my_pa.infrastructure.communications.evidence_v2 import PublicationParse, parse_publication
from tests.fixtures.communications_evidence import synthetic as s

C = RecordClassification
R = ReasonCode


def parse(document: dict[str, Any]) -> PublicationParse:
    return parse_publication(s.encode(document))


def accepted(document: dict[str, Any]) -> Publication:
    publication = parse(document).publication
    assert publication is not None
    return publication


def weekday(*messages: dict[str, Any]) -> dict[str, Any]:
    return s.publication(
        list(messages),
        s.window("2026-11-17T05:00:00Z", "2026-11-18T04:59:59Z", 24, "weekday_prior_24h"),
    )


def item_of(publication: Publication, provider_n: int) -> MailboxItem:
    (item,) = [
        i for i in publication.items if i.provider_id == f"SYNTHETIC-PROVIDER-ID-{provider_n:04d}"
    ]
    return item


def pair(
    *,
    inbox_cc: list[str] | None = None,
    sent_cc: list[str] | None = None,
    bcc: list[str] | None = None,
) -> list[dict[str, Any]]:
    return s.lane_pair(
        1,
        selected_received="2026-11-17T12:00:05Z",
        selected_sent="2026-11-17T12:00:00Z",
        inbox_cc=inbox_cc,
        sent_cc=sent_cc,
        bcc=bcc,
    )


# --- the backfill folder-attribution shape ----------------------------------------


def test_one_provider_id_in_two_lanes_is_one_item_with_two_observations() -> None:
    publication = accepted(s.weekend_49h_publication())
    records = publication.records
    # ordinals 0/1: inbox then sent copy of item 300; 2/3: item 301.
    assert [records[i].classification for i in range(4)] == [
        C.LANE_OBSERVATION_MERGED,
        C.ACCEPTED,
        C.LANE_OBSERVATION_MERGED,
        C.ACCEPTED,
    ]
    item = item_of(publication, 300)
    assert item.primary_ordinal == 1  # the sent-lane copy
    assert [(o.ordinal, o.role) for o in item.observations] == [
        (0, FolderRole.INBOX),
        (1, FolderRole.SENT),
    ]
    assert ItemFlag.MULTI_LANE in item.flags
    assert R.IDENTITY_CONFLICT not in records[0].reasons


def test_the_sent_copy_is_primary_even_when_it_comes_first() -> None:
    inbox, sent = pair()
    publication = accepted(weekday(sent, inbox))
    assert [r.classification for r in publication.records] == [
        C.ACCEPTED,
        C.LANE_OBSERVATION_MERGED,
    ]
    assert publication.items[0].primary_ordinal == 0


def test_lane_observations_are_reported_as_diagnostics() -> None:
    result = parse(s.weekend_49h_publication())
    assert result.diagnostics.code_counts[DiagnosticCode.MULTI_LANE_ITEM] == 2


def test_identical_participants_reconcile_without_disagreement() -> None:
    item = item_of(accepted(s.weekend_49h_publication()), 300)
    assert ItemFlag.PARTICIPANTS_RECONCILED in item.flags
    assert ItemFlag.PARTICIPANTS_DISAGREED not in item.flags
    (cc,) = item.participants["cc"]
    assert cc.address == "charlie@example.invalid"
    assert cc.ordinals == (0, 1)
    assert cc.lanes == (FolderRole.INBOX, FolderRole.SENT)


def test_bcc_is_taken_from_the_sent_lane() -> None:
    item = item_of(accepted(s.weekend_49h_publication()), 300)
    assert ItemFlag.BCC_FROM_SENT_LANE in item.flags
    (bcc,) = item.participants["bcc"]
    assert (bcc.address, bcc.ordinals, bcc.lanes) == (
        "delta@example.invalid",
        (1,),
        (FolderRole.SENT,),
    )


def test_the_sent_lane_bcc_wins_over_an_inbox_lane_claim() -> None:
    inbox, sent = pair(bcc=["delta@example.invalid"])
    inbox["bcc"] = s.field([s.person("hotel@example.invalid")])
    (item,) = accepted(weekday(inbox, sent)).items
    assert [p.address for p in item.participants["bcc"]] == ["delta@example.invalid"]


def test_without_a_sent_lane_bcc_the_union_is_kept() -> None:
    inbox, sent = pair()
    inbox["bcc"] = s.field([s.person("hotel@example.invalid")])
    (item,) = accepted(weekday(inbox, sent)).items
    assert [p.address for p in item.participants["bcc"]] == ["hotel@example.invalid"]
    assert ItemFlag.BCC_FROM_SENT_LANE not in item.flags


def test_a_cc_disagreement_is_kept_as_a_union_with_provenance() -> None:
    publication = accepted(s.weekend_49h_publication())
    item = item_of(publication, 301)
    assert {ItemFlag.PARTICIPANTS_RECONCILED, ItemFlag.PARTICIPANTS_DISAGREED} <= item.flags
    cc = {p.address: p for p in item.participants["cc"]}
    assert cc["charlie@example.invalid"].ordinals == (2, 3)
    assert cc["echo@example.invalid"].ordinals == (3,)
    assert cc["echo@example.invalid"].lanes == (FolderRole.SENT,)
    # Each observation keeps its own participant set as evidence.
    inbox, sent = publication.records[2].message, publication.records[3].message
    assert inbox is not None
    assert sent is not None
    assert inbox.participants["cc"].addresses == ("charlie@example.invalid",)
    assert sent.participants["cc"].addresses == ("charlie@example.invalid", "echo@example.invalid")


def test_a_to_disagreement_also_counts() -> None:
    inbox, sent = pair()
    sent["to"] = s.field([s.person("bravo@example.invalid"), s.person("foxtrot@example.invalid")])
    (item,) = accepted(weekday(inbox, sent)).items
    assert ItemFlag.PARTICIPANTS_DISAGREED in item.flags


def test_a_bcc_only_difference_is_not_a_disagreement() -> None:
    inbox, sent = pair(bcc=["delta@example.invalid"])
    (item,) = accepted(weekday(inbox, sent)).items
    assert ItemFlag.PARTICIPANTS_DISAGREED not in item.flags
    assert ItemFlag.BCC_FROM_SENT_LANE in item.flags


def test_both_raw_times_are_kept_and_the_canonical_time_follows_the_lane() -> None:
    publication = accepted(s.weekend_49h_publication())
    inbox, sent = publication.records[0].message, publication.records[1].message
    assert inbox is not None
    assert sent is not None
    for message in (inbox, sent):
        assert message.timestamps.received_utc == datetime(2026, 10, 31, 14, 0, 5, tzinfo=UTC)
        assert message.timestamps.sent_utc == datetime(2026, 10, 31, 14, tzinfo=UTC)
    item = item_of(publication, 300)
    assert item.message_time_basis is MessageTimeBasis.SENT
    assert item.message_time == datetime(2026, 10, 31, 14, tzinfo=UTC)
    inbox_only = item_of(publication, 304)
    assert inbox_only.message_time_basis is MessageTimeBasis.RECEIVED


def test_a_sent_item_without_a_sent_time_falls_back_to_the_selected_time() -> None:
    record = s.message(1, folder="sent", selected_field="sentDateTime")
    record["timestamps"]["sent_raw"] = None
    (item,) = accepted(weekday(record)).items
    assert item.message_time_basis is MessageTimeBasis.SELECTED_FALLBACK


def test_an_exact_repeat_in_one_lane_stays_a_duplicate_observation() -> None:
    publication = accepted(s.weekend_49h_publication())
    assert publication.records[6].classification is C.ACCEPTED
    assert publication.records[7].classification is C.DUPLICATE_OBSERVATION
    item = item_of(publication, 304)
    assert [o.ordinal for o in item.observations] == [6]
    assert ItemFlag.MULTI_LANE not in item.flags


def test_a_repeat_with_another_lane_is_both_merged_and_duplicated() -> None:
    inbox, sent = pair()
    records = accepted(weekday(inbox, sent, copy.deepcopy(inbox))).records
    assert [r.classification for r in records] == [
        C.LANE_OBSERVATION_MERGED,
        C.ACCEPTED,
        C.DUPLICATE_OBSERVATION,
    ]


def test_one_provider_id_with_a_different_imid_across_lanes_is_quarantined() -> None:
    inbox, sent = pair()
    sent["internet_message_id"] = "<synthetic-other@example.invalid>"
    publication = accepted(weekday(inbox, sent))
    assert [r.classification for r in publication.records] == [C.QUARANTINED, C.QUARANTINED]
    assert all(R.PROVIDER_ID_CONFLICT in r.reasons for r in publication.records)
    assert publication.items == ()


def test_one_provider_id_with_a_different_body_across_lanes_is_quarantined() -> None:
    inbox, sent = pair()
    sent["body"] = s.body("<p>Other body.</p>")
    records = accepted(weekday(inbox, sent)).records
    assert all(R.PROVIDER_ID_CONFLICT in r.reasons for r in records)


def test_an_identity_conflict_quarantines_the_merged_lane_siblings_too() -> None:
    inbox, sent = pair()
    other = s.message(2, imid=sent["internet_message_id"], sender="golf@example.invalid")
    publication = accepted(weekday(inbox, sent, other))
    assert [r.classification for r in publication.records] == [C.QUARANTINED] * 3
    assert all(R.IDENTITY_CONFLICT in r.reasons for r in publication.records)


def test_a_lane_pair_and_a_two_item_identity_coexist() -> None:
    publication = accepted(s.weekend_49h_publication())
    self_inbox, self_sent = item_of(publication, 302), item_of(publication, 303)
    assert self_inbox.canonical_key == self_sent.canonical_key
    assert self_inbox.provider_id != self_sent.provider_id
    assert ItemFlag.MULTI_LANE not in self_inbox.flags | self_sent.flags
    summary = summarize_corpus([publication])
    assert summary.inbox_sent_identity_pairs == 1
    assert summary.multi_lane_items == 2
    assert summary.participant_disagreements == 1


# --- lane verification --------------------------------------------------------------


def test_a_lean_folder_role_is_an_unverified_lane_claim() -> None:
    publication = accepted(s.weekend_49h_publication())
    assert {
        r.message.folder_verification for r in publication.records if r.message is not None
    } == {LaneVerification.UNVERIFIED_LANE_CLAIM}


def test_a_returned_folder_id_or_parent_id_verifies_the_role() -> None:
    by_folder, by_parent = s.message(1), s.message(2)
    by_folder["source_folder"]["folder_id"] = "SYNTHETIC-FOLDER"
    by_parent["source_folder"]["parent_folder_id_returned"] = "SYNTHETIC-PARENT"
    records = accepted(weekday(by_folder, by_parent)).records
    for record in records:
        assert record.message is not None
        assert record.message.folder_verification is LaneVerification.VERIFIED


# --- null participants, empty subjects, null sent times -------------------------------


def test_a_null_from_and_sender_is_accepted_degraded() -> None:
    publication = accepted(s.weekend_49h_publication())
    record = publication.records[8]
    assert record.classification is C.ACCEPTED_DEGRADED
    assert record.reasons == (R.PARTICIPANT_FROM_ABSENT,)
    message = record.message
    assert message is not None
    assert message.participants["from"].state is ParticipantState.NOT_RETURNED
    assert message.participants["sender"].addresses == ()
    assert message.sender_address is None
    assert derive_search_text(message).text == "Synthetic body."
    item = item_of(publication, 305)
    assert item.participants["from"] == ()


def test_an_empty_subject_is_accepted_and_flagged() -> None:
    record = accepted(s.weekend_49h_publication()).records[9]
    assert record.classification is C.ACCEPTED_DEGRADED
    assert record.reasons == (R.SUBJECT_EMPTY,)


def test_a_null_sent_time_is_accepted_with_its_state() -> None:
    record = accepted(s.weekend_49h_publication()).records[10]
    assert record.classification is C.ACCEPTED
    assert record.message is not None
    assert record.message.timestamps.sent_utc is None
    assert record.message.timestamps.sent_state is TimestampState.ABSENT
    assert record.message.timestamps.received_state is TimestampState.PRESENT


def test_an_unparseable_sent_time_has_its_own_state() -> None:
    record = s.message(1)
    record["timestamps"]["sent_raw"] = "soon"
    (outcome,) = accepted(weekday(record)).records
    assert outcome.message is not None
    assert outcome.message.timestamps.sent_state is TimestampState.UNPARSEABLE


# --- weekend and DST windows ---------------------------------------------------------


def test_the_dst_fall_back_weekend_is_49_hours() -> None:
    result = parse(s.weekend_49h_publication())
    assert result.publication is not None
    window = result.publication.window
    assert window.rule is WindowRule.WEEKEND_PRIOR_49H
    assert window.actual_hours == 49.0
    assert window.actual_seconds == 49 * 3600 - 1  # inclusive end at :59:59
    assert window.dst_change_declared is True
    assert window.dst_change_computed is True
    for code in (DiagnosticCode.WINDOW_HOURS_MISMATCH, DiagnosticCode.DST_FLAG_DISAGREEMENT):
        assert code not in result.diagnostics.code_counts


def test_an_ordinary_weekend_is_48_hours() -> None:
    result = parse(s.weekend_48h_publication())
    assert result.publication is not None
    window = result.publication.window
    assert window.rule is WindowRule.WEEKEND_PRIOR_48H
    assert window.actual_hours == 48.0
    assert window.dst_change_computed is False
    assert DiagnosticCode.WINDOW_HOURS_MISMATCH not in result.diagnostics.code_counts


def test_actual_hours_come_from_the_bounds_not_the_label() -> None:
    document = s.weekend_48h_publication()
    document["window"]["hours"] = 24
    result = parse(document)
    assert result.publication is not None
    assert result.publication.window.actual_hours == 48.0
    assert result.diagnostics.code_counts[DiagnosticCode.WINDOW_HOURS_MISMATCH] == 1


def test_adjacent_inclusive_windows_merge_and_a_real_gap_remains() -> None:
    weekend = accepted(s.weekend_48h_publication())  # ends 2026-10-19T03:59:59Z
    monday = s.publication(
        [s.message(500, selected="2026-10-19T12:00:00Z")],
        s.window("2026-10-19T04:00:00Z", "2026-10-20T03:59:59Z", 24, "weekday_prior_24h"),
    )
    later = s.publication(
        [s.message(501, selected="2026-10-21T12:00:00Z")],
        s.window("2026-10-21T04:00:00Z", "2026-10-22T03:59:59Z", 24, "weekday_prior_24h"),
    )
    summary = summarize_corpus([weekend, accepted(monday), accepted(later)])
    start, end = (
        datetime(2026, 10, 17, 4, tzinfo=UTC),
        datetime(2026, 10, 20, 3, 59, 59, tzinfo=UTC),
    )
    assert summary.coverage_intervals[0] == Interval(start, end)
    assert summary.coverage_gaps == (Interval(end, datetime(2026, 10, 21, 4, tzinfo=UTC)),)
    assert summary.window_rules == {"weekday_prior_24h": 2, "weekend_prior_48h": 1}


# --- aggregate-only output for the new shapes -----------------------------------------


def test_the_cli_reports_lane_shapes_without_content(tmp_path: Path) -> None:
    inbox, sent = pair(inbox_cc=["canary-cc@example.invalid"], bcc=["canary-bcc@example.invalid"])
    for record in (inbox, sent):
        record["subject"] = "CANARY-SUBJECT-lane"
    path = tmp_path / "lanes.json"
    path.write_bytes(s.encode(weekday(inbox, sent)))
    document, all_accepted = summarize_files([path])
    assert all_accepted
    report = document["files"][0]  # type: ignore[index]
    assert report["items"]["multi_lane_pairs"] == 1
    assert report["items"]["bcc_from_sent_lane"] == 1
    assert report["records"]["by_classification"] == {"accepted": 1, "lane_observation_merged": 1}
    rendered = json.dumps(document).lower()
    for canary in ("canary", "example.invalid", "synthetic-provider", "synthetic-0001"):
        assert canary not in rendered, canary
