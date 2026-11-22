"""WP3a-I2: the `communications_evidence_v2` consumer through the lifecycle, FAST tier.

The real WP1 parser (wired by `bootstrap.communications_ingest`) over synthetic
publications, the real lifecycle, and the in-memory repositories of
`communications_ingest_fakes`. Proved here: every record ordinal leaves exactly
one row and the totals reconcile; an exact repeat is an observation of its
provider id's item; every Manager ruling M6 branch (agree and attach, sender
disagreement, body disagreement, check c, check d, `provider_id_only` joined
to `provider_returned` by provider id, a second item under one Message-ID);
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


@pytest.mark.parametrize("first_has_id", [False, True], ids=["id_only_first", "returned_first"])
def test_provider_id_only_and_provider_returned_join_by_provider_id(first_has_id: bool) -> None:
    scene = Scene()
    with_id = s.message(1, selected=at(17))
    without = s.message(1, selected=at(18), imid=None)
    first, second = (with_id, without) if first_has_id else (without, with_id)
    scene.ingest("20261117-comms.json", pub(17, [first]))
    report = scene.ingest("20261118-comms.json", pub(18, [second]))
    message = scene.message()
    assert message.identity_kind == ("provider_returned" if first_has_id else "provider_id_only")
    assert report.counts["records_identity_joined_by_provider_id"] == 1
    assert len(scene.world.items) == 1
    assert len(scene.world.observations) == 2
    assert not message.identity_conflict


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
    assert rolling.state is RangeState.PARTIAL
    assert len(rolling.gaps) == 3  # before the 17th, the 19th, after the 21st
