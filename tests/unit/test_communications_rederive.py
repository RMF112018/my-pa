"""WP4-S3: `application.communications_rederive`, FAST tier (rulings D2, D3, R2-R4, R9).

The real lifecycle and handler ingest synthetic publications into the in-memory
`IngestWorld` with the search text and identifiers pinned to v1 (the state a
WP3a database holds), then the rederive brings them to the current versions
over the in-memory `FakeStore`. Proved here: the due rule; the limit and
`messages_deferred`; one read per snapshot group; a digest mismatch and a
missing file flag `source_unavailable`, keep the stored projection and still
write current identifiers over the stored text (R9); a restored file clears the
flag; a pointer that names another record is counted and not written; the dry
run writes nothing; a rerun is idempotent; identifier-only messages read no
file; a failed group rolls back alone. Everything is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Final

import pytest

from my_pa.application import communications_ingest as ingest_module
from my_pa.application.communications_rederive import (
    REDERIVE_COUNT_KEYS,
    CommunicationsRederiver,
    RederiveReport,
)
from my_pa.bootstrap.communications_ingest import parse_for_ingestion
from my_pa.contracts.ports import CommunicationMessageRecord
from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION,
    IDENTIFIER_VERSION_V1,
)
from my_pa.domain.communications.search_text import (
    SEARCH_TEXT_VERSION,
    SEARCH_TEXT_VERSION_V1,
    derive_search_text_v1,
)
from my_pa.infrastructure.communications.evidence_v2 import MAX_PUBLICATION_BYTES
from tests.fixtures.communications_evidence import synthetic as s
from tests.unit.communications_ingest_fakes import unit_of_work_factory
from tests.unit.test_communications_ingest import DIRECTORY, P, Scene, at, pub

#: A mid-body line that merely starts with "Disclaimer", above the trailing
#: region: v1 cuts the body there, v2 keeps it (the anchoring fix), so the
#: identifiers on it appear only in v2.
MID_BODY: Final = (
    "<p>Hi team,</p>"
    "<p>Disclaimer language for the contract is attached; please review RFI 12 and PCO 7.</p>"
    + "".join(f"<p>Schedule note {i} for the synthetic site.</p>" for i in range(16))
    + "<p>Thanks, Alpha</p>"
)
PLAIN: Final = "<p>Please see Change Order 5 for the slab.</p>"


def body_message(n: int, day: int, content: str) -> dict[str, object]:
    return s.message(n, selected=at(day), subject=f"Synthetic {n}", content=content)


class RederiveScene(Scene):
    """A `Scene` whose ingest writes the v1 text and identifiers, plus the rederiver."""

    def __init__(self, monkeypatch: pytest.MonkeyPatch) -> None:
        super().__init__()
        self._monkeypatch = monkeypatch
        self.rederiver = CommunicationsRederiver(
            unit_of_work=unit_of_work_factory(self.world),
            stores=self._stores,
            parse=parse_for_ingestion,
            max_bytes=MAX_PUBLICATION_BYTES,
        )

    def ingest_v1(self, name: str, data: bytes) -> None:
        with pytest.MonkeyPatch.context() as patch:
            patch.setattr(ingest_module, "derive_search_text", derive_search_text_v1)
            patch.setattr(ingest_module, "IDENTIFIER_VERSION", IDENTIFIER_VERSION_V1)
            report = self.ingest(name, data)
        assert report.counts["snapshots_ingested"] == 1

    def run(self, **kwargs: object) -> RederiveReport:
        report = self.rederiver.rederive(P, **kwargs)  # type: ignore[arg-type]
        assert set(report.counts) == set(REDERIVE_COUNT_KEYS)
        return report

    def by_subject(self, subject: str) -> CommunicationMessageRecord:
        (found,) = [m for m in self.world.messages.values() if m.subject == subject]
        return found

    def identifiers(self, message_id: str, version: str) -> set[str]:
        return {
            f"{row.kind}:{row.value}"
            for row in self.world.identifiers.values()
            if row.message_id == message_id and row.extractor_version == version
        }

    def set_message(self, message: CommunicationMessageRecord) -> None:
        self.world.messages[(P, message.message_id)] = message


@pytest.fixture
def scene(monkeypatch: pytest.MonkeyPatch) -> Iterator[RederiveScene]:
    yield RederiveScene(monkeypatch)


def two_snapshots(scene: RederiveScene) -> None:
    scene.ingest_v1("20261117-comms.json", pub(17, [body_message(1, 17, MID_BODY)]))
    scene.ingest_v1(
        "20261118-comms.json",
        pub(18, [body_message(2, 18, PLAIN), body_message(3, 18, MID_BODY)]),
    )


def test_v1_seeding_holds_the_state_a_wp3a_database_holds(scene: RederiveScene) -> None:
    two_snapshots(scene)
    first = scene.by_subject("Synthetic 1")
    assert first.projection.search_text_version == SEARCH_TEXT_VERSION_V1
    assert first.projection.search_text == "Hi team,"
    assert first.identifiers_version == IDENTIFIER_VERSION_V1
    assert scene.identifiers(first.message_id, IDENTIFIER_VERSION) == set()


def test_a_run_rederives_text_and_identifiers_and_keeps_the_v1_rows(
    scene: RederiveScene,
) -> None:
    two_snapshots(scene)
    before = scene.by_subject("Synthetic 1")
    v1_rows = scene.identifiers(before.message_id, IDENTIFIER_VERSION_V1)
    report = scene.run()
    counts = report.counts
    assert (report.search_text_version, report.identifier_version) == (
        SEARCH_TEXT_VERSION,
        IDENTIFIER_VERSION,
    )
    assert counts["messages_checked"] == counts["messages_due_text"] == 3
    assert counts["messages_rederived"] == 3
    assert counts["messages_text_changed"] == 2  # the two mid-body disclaimers
    assert (counts["snapshots_read"], counts["snapshots_unavailable"]) == (2, 0)
    assert counts["messages_failed"] == counts["messages_deferred"] == 0
    after = scene.by_subject("Synthetic 1")
    assert after.projection.search_text_version == SEARCH_TEXT_VERSION
    assert after.projection.search_text is not None
    assert after.projection.search_text.startswith("Hi team,")  # v1 is a prefix of v2
    assert "RFI 12" in after.projection.search_text
    # The pointer and the body are the same record's.
    assert (
        after.projection.text_snapshot_id,
        after.projection.text_record_ordinal,
        after.projection.body_sha256,
        after.latest_snapshot_id,
    ) == (
        before.projection.text_snapshot_id,
        before.projection.text_record_ordinal,
        before.projection.body_sha256,
        before.latest_snapshot_id,
    )
    assert after.identifiers_version == IDENTIFIER_VERSION
    assert scene.identifiers(after.message_id, IDENTIFIER_VERSION) == {"rfi:12", "pco:7"}
    assert scene.identifiers(after.message_id, IDENTIFIER_VERSION_V1) == v1_rows  # R4
    plain = scene.by_subject("Synthetic 2")
    assert scene.identifiers(plain.message_id, IDENTIFIER_VERSION) == {"co:5"}
    assert counts["identifiers_added"] == 5


def test_a_rerun_is_idempotent(scene: RederiveScene) -> None:
    two_snapshots(scene)
    scene.run()
    rows, writes = scene.world.row_count(), len(scene.world.writes)
    scene.store.calls.clear()
    again = scene.run().counts
    assert again["messages_checked"] == 0
    assert sum(again.values()) == 0
    assert (scene.world.row_count(), len(scene.world.writes)) == (rows, writes)
    assert scene.store.calls == []


def test_the_limit_defers_the_rest_and_a_rerun_resumes(scene: RederiveScene) -> None:
    two_snapshots(scene)
    first = scene.run(limit=2).counts
    assert (first["messages_checked"], first["messages_deferred"]) == (2, 1)
    assert first["messages_rederived"] == 2
    second = scene.run(limit=2).counts
    assert (second["messages_checked"], second["messages_deferred"]) == (1, 0)
    assert second["messages_rederived"] == 1
    assert scene.run().counts["messages_checked"] == 0


def test_one_read_per_snapshot_group(scene: RederiveScene) -> None:
    two_snapshots(scene)
    scene.store.calls.clear()
    scene.run()
    assert scene.store.calls.count("open_download") == 2
    assert "list_directory" not in scene.store.calls


def test_a_dry_run_counts_and_writes_nothing(scene: RederiveScene) -> None:
    two_snapshots(scene)
    rows, writes = scene.world.row_count(), len(scene.world.writes)
    scene.store.calls.clear()
    report = scene.run(dry_run=True)
    assert report.dry_run is True
    assert report.counts["messages_due_text"] == 3
    assert report.counts["messages_rederived"] == 0
    assert (scene.world.row_count(), len(scene.world.writes)) == (rows, writes)
    assert scene.store.calls == []


def _unavailable_checks(scene: RederiveScene, before: CommunicationMessageRecord) -> None:
    after = scene.by_subject("Synthetic 1")
    assert after.source_unavailable is True
    assert after.projection == before.projection  # the stored text is kept (D2)
    # R9: current identifiers over the stored text ("Hi team," has none; the
    # subject neither), and the marker set, so identifier search is current.
    assert after.identifiers_version == IDENTIFIER_VERSION
    assert scene.identifiers(after.message_id, IDENTIFIER_VERSION) == set()


def test_a_digest_mismatch_flags_source_unavailable_and_keeps_the_projection(
    scene: RederiveScene,
) -> None:
    two_snapshots(scene)
    before = scene.by_subject("Synthetic 1")
    path = f"{DIRECTORY}/20261117-comms.json"
    original = scene.store.files[path].data
    scene.store.put(path, original.replace(b"Hi team,", b"Hi crew,"))
    counts = scene.run().counts
    assert (counts["snapshots_unavailable"], counts["snapshots_read"]) == (1, 1)
    assert counts["messages_source_unavailable"] == 1
    assert counts["messages_rederived"] == 2
    _unavailable_checks(scene, before)


def test_a_missing_file_flags_source_unavailable(scene: RederiveScene) -> None:
    two_snapshots(scene)
    before = scene.by_subject("Synthetic 1")
    scene.store.remove(f"{DIRECTORY}/20261117-comms.json")
    counts = scene.run().counts
    assert counts["snapshots_unavailable"] == 1
    assert counts["messages_source_unavailable"] == 1
    _unavailable_checks(scene, before)
    # Still due (its text is v1): a rerun retries and writes nothing new.
    writes = len(scene.world.writes)
    again = scene.run().counts
    assert again["messages_checked"] == 1
    assert again["messages_source_unavailable"] == 1
    assert again["identifiers_added"] == 0
    assert len(scene.world.writes) == writes + 1  # only the set-like identifier insert


def test_a_restored_file_clears_the_flag(scene: RederiveScene) -> None:
    two_snapshots(scene)
    path = f"{DIRECTORY}/20261117-comms.json"
    original = scene.store.files[path].data
    scene.store.remove(path)
    scene.run()
    assert scene.by_subject("Synthetic 1").source_unavailable is True
    scene.store.put(path, original)
    counts = scene.run().counts
    assert counts["messages_source_restored"] == 1
    assert counts["messages_rederived"] == 1
    after = scene.by_subject("Synthetic 1")
    assert after.source_unavailable is False
    assert after.projection.search_text_version == SEARCH_TEXT_VERSION
    assert scene.identifiers(after.message_id, IDENTIFIER_VERSION) == {"rfi:12", "pco:7"}
    assert scene.run().counts["messages_checked"] == 0


def test_a_pointer_that_names_another_record_is_counted_and_not_written(
    scene: RederiveScene,
) -> None:
    two_snapshots(scene)
    message = scene.by_subject("Synthetic 3")
    other = scene.by_subject("Synthetic 2")
    # Point message 3 at message 2's record of the same snapshot.
    scene.set_message(
        replace(
            message,
            projection=replace(
                message.projection,
                text_record_ordinal=other.projection.text_record_ordinal,
            ),
        )
    )
    stored = scene.by_subject("Synthetic 3")
    counts = scene.run().counts
    assert counts["messages_pointer_mismatch"] == 1
    assert counts["messages_rederived"] == 2
    assert scene.by_subject("Synthetic 3") == stored


def test_identifier_only_messages_read_no_file(scene: RederiveScene) -> None:
    two_snapshots(scene)
    scene.run()
    message = scene.by_subject("Synthetic 2")
    scene.set_message(replace(message, identifiers_version=IDENTIFIER_VERSION_V1))
    scene.store.calls.clear()
    counts = scene.run().counts
    assert (counts["messages_due_identifiers"], counts["messages_due_text"]) == (1, 0)
    assert counts["messages_rederived"] == 1
    assert scene.store.calls == []
    assert scene.by_subject("Synthetic 2").identifiers_version == IDENTIFIER_VERSION


def test_a_failed_group_rolls_back_alone(scene: RederiveScene) -> None:
    two_snapshots(scene)
    sizes: dict[str, int] = {}
    for message in scene.world.messages.values():
        snapshot_id = message.projection.text_snapshot_id
        sizes[snapshot_id] = sizes.get(snapshot_id, 0) + 1
    first = sizes[min(sizes)]  # groups are written in snapshot id order
    scene.world.fail_on.add("update_message_projection")
    counts = scene.run().counts
    # The first group fails and rolls back whole; the other commits.
    assert counts["messages_failed"] == first
    assert counts["messages_rederived"] == 3 - first
    stale = [
        m
        for m in scene.world.messages.values()
        if m.projection.search_text_version == SEARCH_TEXT_VERSION_V1
    ]
    assert len(stale) == first
    assert all(m.identifiers_version == IDENTIFIER_VERSION_V1 for m in stale)
    assert all(not scene.identifiers(m.message_id, IDENTIFIER_VERSION) for m in stale)
    assert scene.run().counts["messages_rederived"] == first


def test_the_source_scope_selects_by_the_text_pointer(scene: RederiveScene) -> None:
    two_snapshots(scene)
    assert scene.run(ingest_source_id="isrc_doesnotexist0000").counts["messages_checked"] == 0
    assert scene.run(ingest_source_id=scene.source_id).counts["messages_checked"] == 3


@pytest.mark.parametrize("limit", [0, -1, 20_001, True, "5"])
def test_a_limit_outside_its_bounds_is_refused(scene: RederiveScene, limit: object) -> None:
    with pytest.raises(ValueError, match="limit"):
        scene.rederiver.rederive(P, limit=limit)  # type: ignore[arg-type]
