"""WP3a: `SqlIngestionRepository` and `SqlCommunicationsRepository`, on a live server.

The `database` tier, on a disposable head-migrated clone. What is proved here is
the persistence half the WP3a application builds on: each repository operation
writes and reads back exactly what it was given; every read is partitioned, so
another Principal's row answers as an absent one; a targeted update of a row
that does not exist (or is another Principal's) is `RepositoryFailureError`;
the revision's guards surface through the repository unabsorbed (a second
finalization, supersession or finish is refused); participants and identifiers
are set-like; a provider id finds its message through its item (Manager ruling
M6); observation participants are the read-time provenance (ruling M7); and the
general unit of work exposes both repositories on its one connection.

Every identifier, address and text here is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from my_pa.contracts.ports import (
    CommunicationIdentifierRecord,
    CommunicationMailboxItemRecord,
    CommunicationMessageRecord,
    CommunicationObservationRecord,
    CommunicationParticipantRecord,
    CommunicationProjection,
    CommunicationQuarantineRecord,
    CommunicationSnapshotTally,
    IngestConsumer,
    IngestCoverageWindowRecord,
    IngestRunOutcome,
    IngestRunRecord,
    IngestRunSnapshotOutcome,
    IngestRunSnapshotRecord,
    IngestRunTrigger,
    IngestSnapshotPathRecord,
    IngestSnapshotRecord,
    IngestSnapshotStatus,
    IngestSourceRecord,
    RepositoryFailureError,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.communications import SqlCommunicationsRepository
from my_pa.infrastructure.persistence.ingestion import SqlIngestionRepository
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

P: Final = "prn_cmsrepo0001aaaa"
OTHER: Final = "prn_cmsrepo0002bbbb"
WHEN: Final = datetime(2026, 11, 22, 12, tzinfo=UTC)
LATER: Final = WHEN + timedelta(hours=1)
RESTRICT_VIOLATION: Final = "23001"

SOURCE: Final = IngestSourceRecord(
    ingest_source_id="isrc_repo0001",
    consumer=IngestConsumer.COMMUNICATIONS_EVIDENCE_V2,
    workspace_id="mcp",
    path_prefix="My PA/Daily Intelligence/communications/",
    file_pattern="*-comms.json",
    enabled=True,
    admitted_at=WHEN,
)


def _snapshot(snapshot_id: str, digest: str, **overrides: object) -> IngestSnapshotRecord:
    values: dict[str, object] = {
        "snapshot_id": snapshot_id,
        "ingest_source_id": SOURCE.ingest_source_id,
        "file_sha256": digest * 64,
        "byte_count": 1024,
        "observed_version_token": "fp-1",
        "first_seen_at": WHEN,
    }
    values.update(overrides)
    return IngestSnapshotRecord(**values)  # type: ignore[arg-type]


PROJECTION: Final = CommunicationProjection(
    body_state="present",
    body_sha256="d" * 64,
    body_utf8_bytes=120,
    content_type="html",
    search_text="Concrete pour moved for RFI 174",
    search_text_sha256="e" * 64,
    search_text_version="comms_search_text_v1",
    search_text_basis="body_content",
    search_text_flags=("markup_dropped",),
    text_snapshot_id="isnp_repo0001",
    text_record_ordinal=0,
)

MESSAGE: Final = CommunicationMessageRecord(
    message_id="cmsg_repo0001",
    mailbox_ref="mbx-synthetic",
    identity_kind="provider_returned",
    identity_value="<m1@example.invalid>",
    conversation_id="conv-1",
    subject="Pour schedule",
    sender_address="a@example.invalid",
    message_time=WHEN,
    message_time_basis="sent",
    has_attachments=False,
    projection=PROJECTION,
    first_snapshot_id="isnp_repo0001",
    latest_snapshot_id="isnp_repo0001",
)

ITEM: Final = CommunicationMailboxItemRecord(
    item_id="cmitm_repo0001",
    message_id=MESSAGE.message_id,
    mailbox_ref=MESSAGE.mailbox_ref,
    provider_id="AAMk-repo-1",
    provider_id_format="mutable",
    first_snapshot_id="isnp_repo0001",
)


def _observation(
    observation_id: str, ordinal: int, **overrides: object
) -> CommunicationObservationRecord:
    values: dict[str, object] = {
        "observation_id": observation_id,
        "item_id": ITEM.item_id,
        "snapshot_id": "isnp_repo0001",
        "record_ordinal": ordinal,
        "classification": "accepted",
        "reasons": (),
        "folder_role": "inbox",
        "lane_verification": "verified",
        "selected_field": "received",
        "selected_utc": WHEN,
        "received_utc": WHEN,
        "received_state": "present",
        "sent_utc": None,
        "sent_state": "absent",
        "body_sha256": "d" * 64,
        "unique_body_sha256": None,
        "participants": {"from": ("a@example.invalid",), "to": ("b@example.invalid",)},
    }
    values.update(overrides)
    return CommunicationObservationRecord(**values)  # type: ignore[arg-type]


@pytest.fixture
def connection(migrated_engine: Engine) -> Iterator[Connection]:
    """One transaction, rolled back after the test."""
    with migrated_engine.connect() as opened:
        transaction = opened.begin()
        try:
            yield opened
        finally:
            transaction.rollback()


@pytest.fixture
def planted(connection: Connection) -> tuple[SqlIngestionRepository, SqlCommunicationsRepository]:
    """A source, an ingested snapshot, one message with an item and an observation."""
    ingestion = SqlIngestionRepository(connection)
    communications = SqlCommunicationsRepository(connection)
    ingestion.insert_source(P, SOURCE)
    ingestion.insert_snapshot(P, _snapshot("isnp_repo0001", "a"))
    ingestion.finalize_snapshot(
        P,
        "isnp_repo0001",
        status=IngestSnapshotStatus.INGESTED,
        rejection_code=None,
        parser_version="evidence_v2-1.0",
    )
    communications.insert_message(P, MESSAGE)
    communications.insert_item(P, ITEM)
    communications.insert_observation(P, _observation("cobs_repo0001", 0))
    return ingestion, communications


def _sqlstate(error: DBAPIError) -> str | None:
    return getattr(error.orig, "sqlstate", None)


def _refused(connection: Connection, call: Callable[[], object]) -> str | None:
    """Run `call` under a savepoint; return its SQLSTATE (and undo the failure)."""
    savepoint = connection.begin_nested()
    try:
        call()
    except DBAPIError as error:
        savepoint.rollback()
        return _sqlstate(error)
    savepoint.rollback()
    return None


# ---- ingestion lifecycle --------------------------------------------------------------


def test_a_source_round_trips_and_switches(connection: Connection) -> None:
    ingestion = SqlIngestionRepository(connection)
    ingestion.insert_source(P, SOURCE)
    assert ingestion.get_source(P, SOURCE.ingest_source_id) == SOURCE
    assert ingestion.list_sources(P) == (SOURCE,)
    ingestion.set_source_enabled(P, SOURCE.ingest_source_id, False)
    assert ingestion.list_sources(P, enabled_only=True) == ()
    assert ingestion.get_source(P, SOURCE.ingest_source_id) == replace(SOURCE, enabled=False)


def test_a_source_is_invisible_to_another_principal(connection: Connection) -> None:
    ingestion = SqlIngestionRepository(connection)
    ingestion.insert_source(P, SOURCE)
    assert ingestion.get_source(OTHER, SOURCE.ingest_source_id) is None
    assert ingestion.list_sources(OTHER) == ()
    with pytest.raises(RepositoryFailureError):
        ingestion.set_source_enabled(OTHER, SOURCE.ingest_source_id, False)
    with pytest.raises(RepositoryFailureError):
        ingestion.set_source_enabled(P, "isrc_absent0001", False)


def test_a_snapshot_is_found_by_its_digest_and_finalized_once(connection: Connection) -> None:
    ingestion = SqlIngestionRepository(connection)
    ingestion.insert_source(P, SOURCE)
    pending = _snapshot("isnp_repo0002", "b")
    ingestion.insert_snapshot(P, pending)
    assert ingestion.find_snapshot(P, SOURCE.ingest_source_id, "b" * 64) == pending
    assert ingestion.find_snapshot(P, SOURCE.ingest_source_id, "c" * 64) is None
    assert ingestion.find_snapshot(OTHER, SOURCE.ingest_source_id, "b" * 64) is None
    ingestion.finalize_snapshot(
        P,
        "isnp_repo0002",
        status=IngestSnapshotStatus.REJECTED,
        rejection_code="malformed_json",
        parser_version="evidence_v2-1.0",
    )
    rejected = ingestion.get_snapshot(P, "isnp_repo0002")
    assert rejected is not None
    assert (rejected.status, rejected.rejection_code) == (
        IngestSnapshotStatus.REJECTED,
        "malformed_json",
    )
    assert ingestion.list_snapshots(P, SOURCE.ingest_source_id) == (rejected,)
    # The guard surfaces through the repository: a terminal snapshot is frozen.
    again = _refused(
        connection,
        lambda: ingestion.finalize_snapshot(
            P,
            "isnp_repo0002",
            status=IngestSnapshotStatus.INGESTED,
            rejection_code=None,
            parser_version="evidence_v2-1.0",
        ),
    )
    assert again == RESTRICT_VIOLATION
    with pytest.raises(RepositoryFailureError):
        ingestion.finalize_snapshot(
            OTHER,
            "isnp_repo0002",
            status=IngestSnapshotStatus.INGESTED,
            rejection_code=None,
            parser_version="p1",
        )


def test_paths_alias_and_supersede_once(connection: Connection) -> None:
    ingestion = SqlIngestionRepository(connection)
    ingestion.insert_source(P, SOURCE)
    ingestion.insert_snapshot(P, _snapshot("isnp_repo0001", "a"))
    ingestion.insert_snapshot(P, _snapshot("isnp_repo0002", "b"))
    first = IngestSnapshotPathRecord(
        "isnp_repo0001", SOURCE.ingest_source_id, "20261120-comms.json", WHEN
    )
    alias = IngestSnapshotPathRecord(
        "isnp_repo0001", SOURCE.ingest_source_id, "copy/20261120-comms.json", WHEN
    )
    ingestion.insert_snapshot_path(P, first)
    ingestion.insert_snapshot_path(P, alias)
    assert ingestion.current_path(P, SOURCE.ingest_source_id, "20261120-comms.json") == first
    assert ingestion.current_path(OTHER, SOURCE.ingest_source_id, "20261120-comms.json") is None
    ingestion.supersede_path(
        P,
        "isnp_repo0001",
        "20261120-comms.json",
        superseded_by_snapshot_id="isnp_repo0002",
        superseded_at=LATER,
    )
    newer = IngestSnapshotPathRecord(
        "isnp_repo0002", SOURCE.ingest_source_id, "20261120-comms.json", LATER
    )
    ingestion.insert_snapshot_path(P, newer)
    assert ingestion.current_path(P, SOURCE.ingest_source_id, "20261120-comms.json") == newer
    assert ingestion.list_snapshot_paths(P, SOURCE.ingest_source_id) == (
        replace(first, superseded_by_snapshot_id="isnp_repo0002", superseded_at=LATER),
        newer,
        alias,
    )
    again = _refused(
        connection,
        lambda: ingestion.supersede_path(
            P,
            "isnp_repo0001",
            "20261120-comms.json",
            superseded_by_snapshot_id="isnp_repo0002",
            superseded_at=LATER,
        ),
    )
    assert again == RESTRICT_VIOLATION
    with pytest.raises(RepositoryFailureError):
        ingestion.supersede_path(
            P,
            "isnp_repo0002",
            "absent.json",
            superseded_by_snapshot_id="isnp_repo0001",
            superseded_at=LATER,
        )


def test_a_run_links_snapshots_and_finishes_once(connection: Connection) -> None:
    ingestion = SqlIngestionRepository(connection)
    ingestion.insert_source(P, SOURCE)
    ingestion.insert_snapshot(P, _snapshot("isnp_repo0001", "a"))
    run = IngestRunRecord("irun_repo0001", SOURCE.ingest_source_id, IngestRunTrigger.BACKFILL, WHEN)
    ingestion.insert_run(P, run)
    assert ingestion.get_run(P, run.run_id) == run
    assert ingestion.get_run(OTHER, run.run_id) is None
    link = IngestRunSnapshotRecord(
        run.run_id,
        "isnp_repo0001",
        SOURCE.ingest_source_id,
        IngestRunSnapshotOutcome.INGESTED,
        WHEN,
    )
    ingestion.link_run_snapshot(P, link)
    assert ingestion.list_run_snapshots(P, run.run_id) == (link,)
    assert ingestion.list_run_snapshots(OTHER, run.run_id) == ()
    counts = {"snapshots_seen": 1, "records_accepted": 3}
    ingestion.finish_run(
        P, run.run_id, finished_at=LATER, outcome=IngestRunOutcome.COMPLETED, counts=counts
    )
    finished = ingestion.get_run(P, run.run_id)
    assert finished == IngestRunRecord(
        run.run_id,
        SOURCE.ingest_source_id,
        IngestRunTrigger.BACKFILL,
        WHEN,
        LATER,
        IngestRunOutcome.COMPLETED,
        counts,
    )
    again = _refused(
        connection,
        lambda: ingestion.finish_run(
            P, run.run_id, finished_at=LATER, outcome=IngestRunOutcome.FAILED, counts={}
        ),
    )
    assert again == RESTRICT_VIOLATION
    with pytest.raises(RepositoryFailureError):
        ingestion.finish_run(
            OTHER, run.run_id, finished_at=LATER, outcome=IngestRunOutcome.FAILED, counts={}
        )
    with pytest.raises(ValueError, match="unfinished"):
        ingestion.insert_run(
            P,
            IngestRunRecord(
                "irun_repo0002", SOURCE.ingest_source_id, IngestRunTrigger.OPERATOR, WHEN, LATER
            ),
        )


def test_a_coverage_window_round_trips_its_lane_states(connection: Connection) -> None:
    ingestion = SqlIngestionRepository(connection)
    ingestion.insert_source(P, SOURCE)
    ingestion.insert_snapshot(P, _snapshot("isnp_repo0001", "a"))
    ingestion.insert_snapshot(P, _snapshot("isnp_repo0002", "b"))
    lanes = (
        {
            "key_kind": "inbox",
            "role": "inbox",
            "lane": "mail",
            "authorized": True,
            "state": "complete",
        },
        {
            "key_kind": "procore_rfis",
            "role": "other",
            "lane": "project_system",
            "authorized": False,
            "state": "not_authorized",
        },
    )
    later = IngestCoverageWindowRecord(
        "icov_repo0002",
        SOURCE.ingest_source_id,
        "isnp_repo0002",
        LATER,
        LATER + timedelta(days=1),
        "complete",
        lanes,
        WHEN,
    )
    earlier = IngestCoverageWindowRecord(
        "icov_repo0001",
        SOURCE.ingest_source_id,
        "isnp_repo0001",
        WHEN,
        LATER,
        "partial",
        lanes[:1],
        WHEN,
    )
    ingestion.insert_coverage_window(P, later)
    ingestion.insert_coverage_window(P, earlier)
    assert ingestion.list_coverage_windows(P, SOURCE.ingest_source_id) == (earlier, later)
    assert ingestion.list_coverage_windows(OTHER, SOURCE.ingest_source_id) == ()


# ---- communications -------------------------------------------------------------------


def test_a_message_round_trips_and_is_found_by_identity_and_provider_id(
    planted: tuple[SqlIngestionRepository, SqlCommunicationsRepository],
) -> None:
    _ingestion, communications = planted
    assert communications.get_message(P, MESSAGE.message_id) == MESSAGE
    assert communications.get_message(P, MESSAGE.message_id, for_update=True) == MESSAGE
    assert (
        communications.find_message_by_identity(
            P, MESSAGE.mailbox_ref, MESSAGE.identity_kind, MESSAGE.identity_value
        )
        == MESSAGE
    )
    assert (
        communications.find_message_by_identity(
            P, MESSAGE.mailbox_ref, "provider_id_only", MESSAGE.identity_value
        )
        is None
    )
    assert communications.find_item_by_provider_id(P, ITEM.mailbox_ref, ITEM.provider_id) == ITEM
    assert (
        communications.find_message_by_provider_id(
            P, ITEM.mailbox_ref, ITEM.provider_id, for_update=True
        )
        == MESSAGE
    )
    assert communications.find_message_by_provider_id(P, ITEM.mailbox_ref, "AAMk-absent") is None
    assert communications.list_items(P, MESSAGE.message_id) == (ITEM,)


def test_communications_rows_are_invisible_to_another_principal(
    planted: tuple[SqlIngestionRepository, SqlCommunicationsRepository],
) -> None:
    _ingestion, communications = planted
    assert communications.get_message(OTHER, MESSAGE.message_id) is None
    assert (
        communications.find_message_by_identity(
            OTHER, MESSAGE.mailbox_ref, MESSAGE.identity_kind, MESSAGE.identity_value
        )
        is None
    )
    assert (
        communications.find_item_by_provider_id(OTHER, ITEM.mailbox_ref, ITEM.provider_id) is None
    )
    assert (
        communications.find_message_by_provider_id(OTHER, ITEM.mailbox_ref, ITEM.provider_id)
        is None
    )
    assert communications.list_items(OTHER, MESSAGE.message_id) == ()
    assert communications.list_observations(OTHER, MESSAGE.message_id) == ()
    assert communications.list_participants(OTHER, MESSAGE.message_id) == ()
    assert communications.list_identifiers(OTHER, MESSAGE.message_id) == ()
    assert communications.tally_snapshot(OTHER, "isnp_repo0001") == CommunicationSnapshotTally(0, 0)
    for call in (
        lambda: communications.set_latest_snapshot(OTHER, MESSAGE.message_id, "isnp_repo0001"),
        lambda: communications.set_message_flags(OTHER, MESSAGE.message_id, identity_conflict=True),
        lambda: communications.update_message_projection(
            OTHER, MESSAGE.message_id, projection=PROJECTION, latest_snapshot_id="isnp_repo0001"
        ),
    ):
        with pytest.raises(RepositoryFailureError):
            call()


def test_the_projection_and_flags_move_and_nothing_else(
    planted: tuple[SqlIngestionRepository, SqlCommunicationsRepository],
) -> None:
    ingestion, communications = planted
    ingestion.insert_snapshot(P, _snapshot("isnp_repo0002", "b"))
    withheld = CommunicationProjection(
        body_state="withheld",
        body_sha256="f" * 64,
        body_utf8_bytes=9,
        content_type="text",
        search_text=None,
        search_text_sha256=None,
        search_text_version="comms_search_text_v1",
        search_text_basis="none",
        search_text_flags=("metadata_only", "withheld"),
        text_snapshot_id="isnp_repo0002",
        text_record_ordinal=3,
    )
    communications.update_message_projection(
        P, MESSAGE.message_id, projection=withheld, latest_snapshot_id="isnp_repo0002"
    )
    communications.set_message_flags(P, MESSAGE.message_id, identity_conflict=True)
    communications.set_message_flags(
        P, MESSAGE.message_id, participants_reconciled=True, participants_disagreed=True
    )
    moved = communications.get_message(P, MESSAGE.message_id)
    assert moved == replace(
        MESSAGE,
        projection=withheld,
        latest_snapshot_id="isnp_repo0002",
        identity_conflict=True,
        participants_reconciled=True,
        participants_disagreed=True,
    )
    communications.set_latest_snapshot(P, MESSAGE.message_id, "isnp_repo0001")
    latest = communications.get_message(P, MESSAGE.message_id)
    assert latest is not None
    assert latest.latest_snapshot_id == "isnp_repo0001"
    with pytest.raises(ValueError, match="names no flag"):
        communications.set_message_flags(P, MESSAGE.message_id)


def test_observations_quarantine_and_the_snapshot_tally(
    planted: tuple[SqlIngestionRepository, SqlCommunicationsRepository],
) -> None:
    _ingestion, communications = planted
    sent = _observation(
        "cobs_repo0002",
        1,
        classification="lane_observation_merged",
        reasons=("lane_identity_inconsistent", "conversation_id_absent"),
        folder_role="sent",
        lane_verification="unverified_lane_claim",
        selected_field="sent",
        sent_utc=WHEN,
        sent_state="present",
        participants={"from": ("a@example.invalid",), "bcc": ("c@example.invalid",)},
    )
    communications.insert_observation(P, sent)
    communications.insert_quarantine(
        P,
        CommunicationQuarantineRecord(
            "cqrn_repo0001", "isnp_repo0001", 2, ("missing_required_field", "body_truncated")
        ),
    )
    observations = communications.list_observations(P, MESSAGE.message_id)
    assert [o.observation_id for o in observations] == ["cobs_repo0001", "cobs_repo0002"]
    stored = observations[1]
    # Reasons are stored sorted; participants come back as address tuples per field.
    assert stored.reasons == ("conversation_id_absent", "lane_identity_inconsistent")
    assert stored.participants == {"bcc": ("c@example.invalid",), "from": ("a@example.invalid",)}
    assert stored == _observation(
        "cobs_repo0002",
        1,
        classification="lane_observation_merged",
        reasons=("conversation_id_absent", "lane_identity_inconsistent"),
        folder_role="sent",
        lane_verification="unverified_lane_claim",
        selected_field="sent",
        sent_utc=WHEN,
        sent_state="present",
        participants={"bcc": ("c@example.invalid",), "from": ("a@example.invalid",)},
    )
    assert communications.tally_snapshot(P, "isnp_repo0001") == CommunicationSnapshotTally(2, 1)


def test_participants_and_identifiers_are_set_like(
    planted: tuple[SqlIngestionRepository, SqlCommunicationsRepository],
) -> None:
    _ingestion, communications = planted
    first = CommunicationParticipantRecord(
        MESSAGE.message_id, "from", "a@example.invalid", "cobs_repo0001"
    )
    second = CommunicationParticipantRecord(
        MESSAGE.message_id, "to", "b@example.invalid", "cobs_repo0001"
    )
    assert communications.insert_participants(P, [first, second]) == 2
    assert communications.insert_participants(P, [first]) == 0
    assert communications.insert_participants(P, []) == 0
    assert communications.list_participants(P, MESSAGE.message_id) == (first, second)
    rfi = CommunicationIdentifierRecord(MESSAGE.message_id, "rfi", "174", "comms_identifiers_v1")
    gmp = CommunicationIdentifierRecord(MESSAGE.message_id, "gmp", "gmp", "comms_identifiers_v1")
    assert communications.insert_identifiers(P, [rfi, gmp]) == 2
    assert communications.insert_identifiers(P, [rfi]) == 0
    assert communications.insert_identifiers(P, []) == 0
    assert communications.list_identifiers(P, MESSAGE.message_id) == (gmp, rfi)


def test_the_general_unit_of_work_exposes_both_repositories(migrated_engine: Engine) -> None:
    audit_engine = migrated_engine
    unit = SqlAlchemyUnitOfWork(migrated_engine, audit=SqlAlchemyAuditSink(audit_engine))
    with unit as opened:
        assert isinstance(opened.ingestion, SqlIngestionRepository)
        assert isinstance(opened.communications, SqlCommunicationsRepository)
        opened.ingestion.insert_source(P, SOURCE)
        assert opened.ingestion.get_source(P, SOURCE.ingest_source_id) == SOURCE
    with SqlAlchemyUnitOfWork(migrated_engine, audit=SqlAlchemyAuditSink(audit_engine)) as again:
        assert again.ingestion.list_sources(P) == (SOURCE,)
