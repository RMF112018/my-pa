"""WP3a-I2: the `communications_evidence_v2` consumer through the lifecycle, FAST tier.

The real WP1 parser (wired by `bootstrap.communications_ingest`) over synthetic
publications, the real lifecycle, and the in-memory repositories of
`communications_ingest_fakes`. Proved here: every record ordinal leaves exactly
one row and the totals reconcile; an exact repeat is an observation of its
provider id's item; every Manager ruling M6 branch (agree and attach, sender
disagreement, body disagreement, check c, check d, check e -- `provider_id_only`
and `provider_returned` never joined by provider id, in either arrival order --
a second item under one Message-ID);
participants with their first observation; the projection rule independent of
arrival order; identifiers; the coverage window's lanes; and a handler failure
or dry run leaving no communications row. Everything is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest

from my_pa.application.communications_ingest import CommunicationsCoverageReader, ParsedPublication
from my_pa.application.ingestion import IngestionLifecycle, IngestRunReport, StabilityMemory
from my_pa.bootstrap.communications_ingest import communications_handler
from my_pa.contracts.ports import (
    CommunicationMessageRecord,
    CommunicationSnapshotTally,
    FileWorkspaceStore,
    IngestConsumer,
    IngestRunOutcome,
)
from my_pa.domain.communications.coverage import RangeState
from tests.fixtures.communications_evidence import synthetic as s
from tests.unit.communications_ingest_fakes import (
    FakeCommunications,
    FakeStore,
    IngestWorld,
    unit_of_work_factory,
)

P: Final = "prn_commsingest0001"
DIRECTORY: Final = "My PA/Daily Intelligence/communications"
NOW: Final = datetime(2026, 11, 30, 12, tzinfo=UTC)


def day_window(day: int) -> dict[str, Any]:
    start = datetime(2026, 11, day, 5, tzinfo=UTC)
    end = start + timedelta(days=1) - timedelta(seconds=1)
    return s.window(
        start.isoformat().replace("+00:00", "Z"),
        end.isoformat().replace("+00:00", "Z"),
        24,
        "weekday_prior_24h",
    )


def at(day: int, hour: int = 12) -> str:
    return f"2026-11-{day:02d}T{hour:02d}:00:00Z"


def pub(day: int, messages: list[dict[str, Any]], *, rich: bool = False) -> bytes:
    return s.encode(s.publication(messages, day_window(day), rich=rich))


class Scene:
    def __init__(self) -> None:
        self.world = IngestWorld()
        self.store = FakeStore()
        self.lifecycle = IngestionLifecycle(
            unit_of_work=unit_of_work_factory(self.world),
            stores=self._stores,
            handlers=[communications_handler()],
            clock=self._clock,
            stability=StabilityMemory(),
        )
        self._now = NOW
        self.source_id = self.lifecycle.admit(
            P,
            consumer=IngestConsumer.COMMUNICATIONS_EVIDENCE_V2,
            workspace_id="mcp",
            path_prefix=DIRECTORY + "/",
            file_pattern="*-comms.json",
        ).ingest_source_id

    def _clock(self) -> datetime:
        self._now = getattr(self, "_now", NOW) + timedelta(seconds=1)
        return self._now

    def _stores(self, workspace_id: str) -> FileWorkspaceStore:
        return self.store

    def ingest(self, name: str, data: bytes) -> IngestRunReport:
        path = f"{DIRECTORY}/{name}"
        self.store.put(path, data)
        return self.lifecycle.backfill(P, self.source_id, paths=[path])

    def messages(self) -> list[CommunicationMessageRecord]:
        return sorted(self.world.messages.values(), key=lambda m: m.identity_value)

    def message(self) -> CommunicationMessageRecord:
        (only,) = self.world.messages.values()
        return only

    def snapshot_sha(self, snapshot_id: str) -> str:
        return self.world.snapshots[(P, snapshot_id)].file_sha256

    def rows_for(self, snapshot_id: str) -> int:
        return sum(
            1
            for table in (self.world.observations, self.world.quarantine)
            for row in table.values()
            if row.snapshot_id == snapshot_id
        )


def quarantine_reasons(scene: Scene) -> list[tuple[str, ...]]:
    return [q.reasons for q in scene.world.quarantine.values()]


# ---- one row per record, totals --------------------------------------------------------


@pytest.mark.parametrize("builder", sorted(s.COMMITTED), ids=str)
def test_every_record_ordinal_of_a_committed_fixture_leaves_exactly_one_row(builder: str) -> None:
    scene = Scene()
    document = s.COMMITTED[builder]()
    report = scene.ingest("20261117-comms.json", s.encode(document))
    assert report.outcome is IngestRunOutcome.COMPLETED
    assert report.counts["snapshots_ingested"] == 1
    (snapshot,) = scene.world.snapshots.values()
    total = len(document["messages"])
    assert scene.rows_for(snapshot.snapshot_id) == total
    assert report.counts["records_total"] == total
    classified = sum(
        value
        for key, value in report.counts.items()
        if key.startswith("records_")
        and key.removeprefix("records_")
        in {
            "accepted",
            "accepted_degraded",
            "duplicate_observation",
            "lane_observation_merged",
            "out_of_window",
            "quarantined",
        }
    )
    assert classified == total
    ordinals = sorted(
        row.record_ordinal
        for table in (scene.world.observations, scene.world.quarantine)
        for row in table.values()
    )
    assert ordinals == list(range(total))


def test_an_exact_repeat_is_an_observation_of_its_provider_ids_item() -> None:
    scene = Scene()
    scene.ingest("20261117-comms.json", s.encode(s.lean_publication()))
    by_ordinal = {o.record_ordinal: o for o in scene.world.observations.values()}
    assert by_ordinal[3].classification == "duplicate_observation"
    assert by_ordinal[3].item_id == by_ordinal[0].item_id


def test_a_withheld_body_has_no_search_text() -> None:
    scene = Scene()
    scene.ingest("20261116-comms.json", s.encode(s.rich_publication()))
    withheld = [m for m in scene.world.messages.values() if m.projection.body_state == "withheld"]
    assert withheld
    assert all(m.projection.search_text is None for m in withheld)
    assert all(m.projection.search_text_basis == "none" for m in withheld)


def test_identifiers_are_stored_with_their_extractor_version() -> None:
    scene = Scene()
    scene.ingest("20261117-comms.json", s.encode(s.lean_publication()))
    identifiers = {(i.kind, i.value, i.extractor_version) for i in scene.world.identifiers.values()}
    assert ("rfi", "174", "comms_identifiers_v1") in identifiers
    assert ("rfi", "999", "comms_identifiers_v1") not in identifiers  # quoted chain cut
    assert {kind for kind, _, _ in identifiers} >= {"rfi", "cb", "gmp", "fpl", "submittal"}


def test_participants_carry_their_first_observation_and_flags_are_raised() -> None:
    scene = Scene()
    scene.ingest("20261101-comms.json", s.encode(s.weekend_49h_publication()))
    observations = scene.world.observations
    for participant in scene.world.participants.values():
        assert (P, participant.first_observation_id) in observations
    flagged = [m for m in scene.world.messages.values() if m.participants_disagreed]
    assert len(flagged) == 1
    assert flagged[0].participants_reconciled
    cc = {
        p.address
        for p in scene.world.participants.values()
        if p.message_id == flagged[0].message_id and p.field == "cc"
    }
    assert cc == {"charlie@example.invalid", "echo@example.invalid"}


def test_the_coverage_window_and_its_lanes_are_recorded() -> None:
    scene = Scene()
    scene.ingest("20261117-comms.json", pub(17, [s.message(1, selected=at(17))]))
    (window,) = scene.world.coverage.values()
    assert window.coverage_state == "complete"
    assert window.start_utc == datetime(2026, 11, 17, 5, tzinfo=UTC)
    assert window.end_utc == datetime(2026, 11, 18, 4, 59, 59, tzinfo=UTC)
    assert {lane["key_kind"]: lane["state"] for lane in window.lane_states} == {
        "inbox": "complete",
        "sent": "complete",
        "procore_rfis": "not_authorized",
    }
    assert {lane["key_kind"]: lane["authorized"] for lane in window.lane_states}[
        "procore_rfis"
    ] is False


# ---- identity across publications (ruling M6) -------------------------------------------


def test_agreement_attaches_a_new_observation_to_the_stored_message() -> None:
    scene = Scene()
    scene.ingest("20261117-comms.json", pub(17, [s.message(1, selected=at(17))]))
    report = scene.ingest("20261118-comms.json", pub(18, [s.message(1, selected=at(17))]))
    message = scene.message()
    assert len(scene.world.items) == 1
    assert len(scene.world.observations) == 2
    assert not message.identity_conflict
    assert report.counts.get("records_identity_conflict_cross_publication", 0) == 0
    # Out of the second window, the repeat is stored but classified out_of_window.
    classes = sorted(o.classification for o in scene.world.observations.values())
    assert classes == ["accepted", "out_of_window"]


@pytest.mark.parametrize(
    "change",
    [
        {"sender": "mallory@example.invalid"},
        {"content": "<p>A different synthetic body.</p>"},
    ],
    ids=["sender", "body"],
)
def test_a_disagreeing_repeat_is_quarantined_and_flags_the_stored_message(
    change: dict[str, str],
) -> None:
    scene = Scene()
    scene.ingest("20261117-comms.json", pub(17, [s.message(1, selected=at(17))]))
    before = scene.message()
    report = scene.ingest("20261118-comms.json", pub(18, [s.message(1, selected=at(18), **change)]))
    after = scene.message()
    assert after.identity_conflict
    assert (after.sender_address, after.projection) == (before.sender_address, before.projection)
    assert report.counts["records_identity_conflict_cross_publication"] == 1
    assert report.counts["records_quarantined"] == 1
    assert quarantine_reasons(scene) == [("identity_conflict",)]
    assert len(scene.world.observations) == 1


def test_check_c_one_provider_id_with_two_message_ids_is_a_conflict() -> None:
    scene = Scene()
    scene.ingest("20261117-comms.json", pub(17, [s.message(1, selected=at(17))]))
    report = scene.ingest(
        "20261118-comms.json",
        pub(18, [s.message(1, selected=at(18), imid="<another-id@example.invalid>")]),
    )
    assert report.counts["records_provider_id_message_id_conflict"] == 1
    assert scene.message().identity_conflict
    assert len(scene.world.messages) == 1
    assert quarantine_reasons(scene) == [("identity_conflict",)]


MESSAGE_ID_ONE: Final = "<synthetic-0001@example.invalid>"


def _kind_split_publications() -> tuple[bytes, bytes]:
    """Finding F1's reproduction: D17 keys provider id 1 `provider_id_only`;
    D18 carries provider id 1 with Message-ID X and a Sent copy (provider id 2)
    under X."""
    d17 = pub(17, [s.message(1, selected=at(17), imid=None)])
    sent_copy = s.message(
        2, folder="sent", selected=at(18), selected_field="sentDateTime", imid=MESSAGE_ID_ONE
    )
    d18 = pub(18, [s.message(1, selected=at(18), imid=MESSAGE_ID_ONE), sent_copy])
    return d17, d18


@pytest.mark.parametrize("d17_first", [True, False], ids=["d17_then_d18", "d18_then_d17"])
def test_identity_kinds_never_merge_by_provider_id(d17_first: bool) -> None:
    """Check (e), ruling (a): a provider id whose stored message is keyed in the
    other identity kind is quarantined `identity_kind_mismatch`, never attached;
    nothing stored is touched and the Message-ID is never split by this path."""
    scene = Scene()
    d17, d18 = _kind_split_publications()
    order = [("20261117-comms.json", d17), ("20261118-comms.json", d18)]
    if not d17_first:
        order.reverse()
    scene.ingest(*order[0])
    (first_snapshot,) = (sid for _, sid in scene.world.snapshots)
    stored_before = dict(scene.world.messages)
    report = scene.ingest(*order[1])
    (second_snapshot,) = (sid for _, sid in scene.world.snapshots if sid != first_snapshot)
    d17_snapshot = first_snapshot if d17_first else second_snapshot

    # One quarantine row, closed reason and count; the totals reconcile.
    assert report.counts["records_identity_kind_mismatch"] == 1
    assert report.counts["records_quarantined"] == 1
    assert "records_identity_joined_by_provider_id" not in report.counts
    (quarantined,) = scene.world.quarantine.values()
    assert (quarantined.snapshot_id, quarantined.record_ordinal) == (second_snapshot, 0)
    assert "identity_kind_mismatch" in quarantined.reasons
    assert "identity_conflict" not in quarantined.reasons
    assert scene.rows_for(second_snapshot) == report.counts["records_total"]
    assert scene.rows_for(first_snapshot) == (1 if d17_first else 2)

    # The stored messages are untouched: not rewritten, not flagged.
    for message_id, before in stored_before.items():
        assert scene.world.messages[message_id] == before
    assert not any(m.identity_conflict for m in scene.world.messages.values())

    # Message-ID X is exactly one provider_returned message.
    kinds = {m.message_id: m.identity_kind for m in scene.world.messages.values()}
    returned = [
        m
        for m in scene.world.messages.values()
        if (m.identity_kind, m.identity_value) == ("provider_returned", MESSAGE_ID_ONE)
    ]
    assert len(returned) == 1

    # No message holds observations of both kinds: the D17 (no Message-ID)
    # observation is the provider_id_only message's alone, or quarantined.
    item_message = {i.item_id: i.message_id for i in scene.world.items.values()}
    snapshots_by_message: dict[str, set[str]] = {}
    for observation in scene.world.observations.values():
        snapshots_by_message.setdefault(item_message[observation.item_id], set()).add(
            observation.snapshot_id
        )
    for message_id, snapshots in snapshots_by_message.items():
        if kinds[message_id] == "provider_id_only":
            assert snapshots == {d17_snapshot}
        else:
            assert d17_snapshot not in snapshots
    assert len(scene.world.items) == 2
    assert len(scene.world.observations) == 2
    if d17_first:
        # pid1 stays provider_id_only; pid2 alone creates X's message.
        assert sorted(kinds.values()) == ["provider_id_only", "provider_returned"]
    else:
        # pid1 and pid2 under X; the later id-only record of pid1 writes nothing.
        assert list(kinds.values()) == ["provider_returned"]


def _kind_split_two_record_publications(d17_first: bool) -> list[tuple[str, bytes]]:
    """W1 nit (F1 multi-record): the second publication carries provider id 1
    in two records (the second in another folder), both in the other identity
    kind from the stored message."""
    d17, d18 = _kind_split_publications()
    if d17_first:
        sent_copy = s.message(
            2, folder="sent", selected=at(18), selected_field="sentDateTime", imid=MESSAGE_ID_ONE
        )
        twice = [
            s.message(1, selected=at(18), imid=MESSAGE_ID_ONE),
            s.message(1, folder="archive", selected=at(18), imid=MESSAGE_ID_ONE),
            sent_copy,
        ]
        return [("20261117-comms.json", d17), ("20261118-comms.json", pub(18, twice))]
    twice = [
        s.message(1, selected=at(17), imid=None),
        s.message(1, folder="archive", selected=at(17), imid=None),
    ]
    return [("20261118-comms.json", d18), ("20261117-comms.json", pub(17, twice))]


@pytest.mark.parametrize("d17_first", [True, False], ids=["d17_then_d18", "d18_then_d17"])
def test_identity_kinds_never_merge_when_one_provider_id_carries_two_records(
    d17_first: bool,
) -> None:
    """Check (e), ruling (a), per record: each of provider id 1's two records in
    the second publication is quarantined `identity_kind_mismatch`; the totals
    reconcile and the stored message is untouched."""
    scene = Scene()
    first, second = _kind_split_two_record_publications(d17_first)
    scene.ingest(*first)
    (first_snapshot,) = (sid for _, sid in scene.world.snapshots)
    stored_before = dict(scene.world.messages)
    report = scene.ingest(*second)
    (second_snapshot,) = (sid for _, sid in scene.world.snapshots if sid != first_snapshot)

    assert report.counts["records_identity_kind_mismatch"] == 2
    assert report.counts["records_quarantined"] == 2
    assert "records_identity_joined_by_provider_id" not in report.counts
    quarantined = sorted(scene.world.quarantine.values(), key=lambda q: q.record_ordinal)
    assert [(q.snapshot_id, q.record_ordinal) for q in quarantined] == [
        (second_snapshot, 0),
        (second_snapshot, 1),
    ]
    for row in quarantined:
        assert "identity_kind_mismatch" in row.reasons
        assert "identity_conflict" not in row.reasons
    assert report.counts["records_total"] == (3 if d17_first else 2)
    assert scene.rows_for(second_snapshot) == report.counts["records_total"]

    # The stored messages are untouched: not rewritten, not flagged.
    for message_id, before in stored_before.items():
        assert scene.world.messages[message_id] == before
    assert not any(m.identity_conflict for m in scene.world.messages.values())
    returned = [
        m
        for m in scene.world.messages.values()
        if (m.identity_kind, m.identity_value) == ("provider_returned", MESSAGE_ID_ONE)
    ]
    assert len(returned) == 1


def test_a_second_provider_id_under_one_message_id_is_a_second_item() -> None:
    scene = Scene()
    scene.ingest("20261117-comms.json", pub(17, [s.message(1, selected=at(17))]))
    sent_copy = s.message(
        2,
        folder="sent",
        selected=at(18),
        selected_field="sentDateTime",
        imid="<synthetic-0001@example.invalid>",
    )
    scene.ingest("20261118-comms.json", pub(18, [sent_copy]))
    assert len(scene.world.messages) == 1
    assert len(scene.world.items) == 2


def test_a_second_provider_id_disagreeing_under_one_message_id_is_a_conflict() -> None:
    scene = Scene()
    scene.ingest("20261117-comms.json", pub(17, [s.message(1, selected=at(17))]))
    other = s.message(
        2, selected=at(18), imid="<synthetic-0001@example.invalid>", content="<p>other</p>"
    )
    report = scene.ingest("20261118-comms.json", pub(18, [other]))
    assert report.counts["records_identity_conflict_cross_publication"] == 1
    assert scene.message().identity_conflict
    assert len(scene.world.items) == 1


def test_check_d_in_window_is_checked_on_every_observation_merged_siblings_included() -> None:
    scene = Scene()
    inbox, sent = s.lane_pair(5, selected_received=at(17, 13), selected_sent=at(17, 12))
    sibling = s.richen(inbox, in_window=False)  # declares out of window; it is in it
    primary = s.richen(sent, in_window=True)
    report = scene.ingest("20261117-comms.json", pub(17, [sibling, primary], rich=True))
    by_role = {o.folder_role: o for o in scene.world.observations.values()}
    assert by_role["inbox"].classification == "lane_observation_merged"
    assert "in_window_disagreement" in by_role["inbox"].reasons
    assert "in_window_disagreement" not in by_role["sent"].reasons
    assert report.counts["records_in_window_disagreement_added"] == 1


# ---- projection ------------------------------------------------------------------------


def _text_variants() -> tuple[bytes, bytes]:
    """The same message twice: older window with unique-body text, newer with body text."""
    older = s.richen(s.message(1, selected=at(17), content="<p>Body text, RFI 9.</p>"))
    older["unique_body"]["content"] = "<p>Only the new part.</p>"
    older["unique_body"]["sha256"] = s.sha("<p>Only the new part.</p>")
    older["unique_body"]["utf8_bytes"] = len(b"<p>Only the new part.</p>")
    newer = s.message(1, selected=at(18), content="<p>Body text, RFI 9.</p>")
    return pub(17, [older], rich=True), pub(18, [newer])


@pytest.mark.parametrize("order", ["oldest_first", "newest_first"])
def test_the_projection_is_the_latest_window_with_text_whatever_the_arrival_order(
    order: str,
) -> None:
    scene = Scene()
    older, newer = _text_variants()
    arrivals = [("20261117-comms.json", older), ("20261118-comms.json", newer)]
    if order == "newest_first":
        arrivals.reverse()
    for name, data in arrivals:
        scene.ingest(name, data)
    message = scene.message()
    assert message.projection.search_text == "Body text, RFI 9."
    assert message.projection.search_text_basis == "body_content"
    newer_sha = next(
        snap.file_sha256
        for snap in scene.world.snapshots.values()
        if scene.world.coverage[(P, snap.snapshot_id)].start_utc.day == 18
    )
    assert scene.snapshot_sha(message.projection.text_snapshot_id) == newer_sha
    assert scene.snapshot_sha(message.latest_snapshot_id) == newer_sha
    assert ("rfi", "9") in {(i.kind, i.value) for i in scene.world.identifiers.values()}


@pytest.mark.parametrize("order", ["oldest_first", "newest_first"])
def test_a_newer_withheld_body_never_replaces_text(order: str) -> None:
    scene = Scene()
    older = pub(17, [s.message(1, selected=at(17))])
    newer = pub(18, [s.richen(s.message(1, selected=at(18)), withheld=True)], rich=True)
    arrivals = [("20261117-comms.json", older), ("20261118-comms.json", newer)]
    if order == "newest_first":
        arrivals.reverse()
    for name, data in arrivals:
        scene.ingest(name, data)
    message = scene.message()
    assert message.projection.search_text == "Synthetic body."
    assert message.projection.body_state == "present"
    assert scene.world.coverage[(P, message.latest_snapshot_id)].start_utc.day == 18


# ---- failure and dry run ---------------------------------------------------------------


def test_a_failing_write_rolls_back_every_communications_row_of_the_snapshot() -> None:
    scene = Scene()
    scene.world.fail_on.add("insert_identifiers")
    report = scene.ingest("20261117-comms.json", s.encode(s.lean_publication()))
    assert report.outcome is IngestRunOutcome.FAILED
    for table in ("messages", "items", "observations", "participants", "quarantine", "snapshots"):
        assert getattr(scene.world, table) == {}, table
    assert (
        scene.ingest("20261117-comms.json", s.encode(s.lean_publication())).counts[
            "snapshots_ingested"
        ]
        == 1
    )


def test_a_snapshot_whose_rows_do_not_reconcile_rolls_back(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    scene = Scene()
    honest = FakeCommunications.tally_snapshot

    def short(
        self: FakeCommunications, principal_id: str, snapshot_id: str
    ) -> CommunicationSnapshotTally:
        tally = honest(self, principal_id, snapshot_id)
        return CommunicationSnapshotTally(tally.observations - 1, tally.quarantined)

    monkeypatch.setattr(FakeCommunications, "tally_snapshot", short)
    report = scene.ingest("20261117-comms.json", s.encode(s.lean_publication()))
    assert report.counts["snapshots_failed"] == 1
    assert (scene.world.snapshots, scene.world.observations) == ({}, {})


def test_the_injected_parser_answer_is_accepted_or_rejected_not_both() -> None:
    with pytest.raises(ValueError, match="not both"):
        ParsedPublication(None, None)


def test_a_rejected_publication_is_a_rejected_snapshot_with_its_code() -> None:
    scene = Scene()
    report = scene.ingest("20261117-comms.json", b'{"schema": "something_else"}')
    assert report.counts["snapshots_rejected"] == 1
    (snapshot,) = scene.world.snapshots.values()
    assert snapshot.rejection_code == "unknown_schema"
    assert snapshot.parser_version == "communications_evidence_v2_parser_v1"
    assert scene.world.messages == {}
    assert scene.world.coverage == {}


def test_a_dry_run_parses_classifies_and_writes_nothing() -> None:
    scene = Scene()
    scene.store.put(f"{DIRECTORY}/20261117-comms.json", s.encode(s.lean_publication()))
    scene.store.put(f"{DIRECTORY}/20261116-comms.json", s.encode(s.rich_publication()))
    rows, writes = scene.world.row_count(), list(scene.world.writes)
    report = scene.lifecycle.backfill(P, scene.source_id, dry_run=True)
    assert report.run_id is None
    assert report.counts["snapshots_ingested"] == 2
    assert report.counts["records_total"] == len(s.lean_publication()["messages"]) + len(
        s.rich_publication()["messages"]
    )
    assert report.counts["records_quarantined"] > 0
    assert scene.world.row_count() == rows
    assert scene.world.writes == writes


# ---- coverage read ---------------------------------------------------------------------


def test_the_coverage_reader_merges_stored_windows_and_reports_the_rolling_gap() -> None:
    scene = Scene()
    for day in (17, 18, 20):
        scene.ingest(f"202611{day}-comms.json", pub(day, [s.message(day, selected=at(day))]))
    reader = CommunicationsCoverageReader(
        unit_of_work=unit_of_work_factory(scene.world), clock=lambda: NOW
    )
    summary = reader.summary(P, scene.source_id)
    assert summary.snapshots == 3
    assert [(i.start.day, i.end.day) for i in summary.intervals] == [(17, 19), (20, 21)]
    (gap,) = summary.gaps
    assert gap.inclusive_seconds == 86_400
    assert summary.freshness_seconds == int(
        (NOW - datetime(2026, 11, 21, 4, 59, 59, tzinfo=UTC)).total_seconds()
    )
    lanes = {lane.key_kind: lane for lane in summary.lanes}
    assert lanes["procore_rfis"].latest_state == "not_authorized"
    assert lanes["procore_rfis"].intervals == ()
    rolling = reader.rolling(P, scene.source_id)
    assert rolling is not None
    # Ends at the latest covered instant, not at the clock: no trailing gap.
    assert rolling.end == datetime(2026, 11, 21, 4, 59, 59, tzinfo=UTC)
    assert rolling.start == rolling.end - timedelta(days=30)
    assert rolling.state is RangeState.PARTIAL
    assert len(rolling.gaps) == 2  # before the 17th, the 19th; nothing after the 21st


def test_the_coverage_reader_reads_one_range_and_merges_several_sources() -> None:
    """The operator CLI's `coverage --from/--to` and `aggregate` reads (contract 9, 19)."""
    scene = Scene()
    for day in (17, 18):
        scene.ingest(f"202611{day}-comms.json", pub(day, [s.message(day, selected=at(day))]))
    other_dir = "Daily/rich"
    other = scene.lifecycle.admit(
        P,
        consumer=IngestConsumer.COMMUNICATIONS_EVIDENCE_V2,
        workspace_id="mcp",
        path_prefix=other_dir + "/",
        file_pattern="*-comms.json",
    ).ingest_source_id
    scene.store.put(f"{other_dir}/20261119-comms.json", pub(19, [s.message(19, selected=at(19))]))
    scene.lifecycle.backfill(P, other)
    reader = CommunicationsCoverageReader(
        unit_of_work=unit_of_work_factory(scene.world), clock=lambda: NOW
    )
    inside = reader.range(
        P,
        scene.source_id,
        start=datetime(2026, 11, 17, 6, tzinfo=UTC),
        end=datetime(2026, 11, 18, 6, tzinfo=UTC),
    )
    assert (inside.state, inside.gaps) == (RangeState.COMPLETE, ())
    beyond = reader.range(
        P,
        scene.source_id,
        start=datetime(2026, 11, 18, 6, tzinfo=UTC),
        end=datetime(2026, 11, 20, 6, tzinfo=UTC),
    )
    assert beyond.state is RangeState.PARTIAL
    assert len(beyond.gaps) == 1
    alone = reader.summary(P, scene.source_id)
    combined = reader.combined(P, [other, scene.source_id, other])
    assert (alone.snapshots, combined.snapshots) == (2, 3)
    assert [(i.start.day, i.end.day) for i in combined.intervals] == [(17, 20)]
    assert combined.gaps == ()
    assert reader.combined(P, []).snapshots == 0
