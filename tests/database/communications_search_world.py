"""A synthetic communications world for the WP4-S4 database tier (search, read, coverage).

Rows are written through the real repositories (and, for the latency set, by
bulk inserts into the same tables), so the reads under test see exactly what
ingestion and rederive store. Every subject, text, address and identifier here
is synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import Engine

from my_pa.application.communications_search import CommunicationsReads
from my_pa.contracts.ports import (
    CommunicationIdentifierRecord,
    CommunicationMailboxItemRecord,
    CommunicationMessageRecord,
    CommunicationObservationRecord,
    CommunicationParticipantRecord,
    CommunicationProjection,
    IngestConsumer,
    IngestCoverageWindowRecord,
    IngestSnapshotRecord,
    IngestSnapshotStatus,
    IngestSourceRecord,
    UnitOfWork,
)
from my_pa.domain.communications.identifiers import IDENTIFIER_VERSION, extract_identifiers
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

P: Final = "prn_cmsearch0001aaaa"
OTHER: Final = "prn_cmsearch0002bbbb"
NOW: Final = datetime(2026, 11, 21, 12, tzinfo=UTC)
TEXT_VERSION: Final = "comms_search_text_v2"


def at(day: int, hour: int = 12, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UTC)


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def unit_of_work(engine: Engine) -> Callable[[], UnitOfWork]:
    return lambda: SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine))


def reads(engine: Engine, **kwargs: object) -> CommunicationsReads:
    return CommunicationsReads(
        unit_of_work=unit_of_work(engine),
        clock=lambda: NOW,
        **kwargs,  # type: ignore[arg-type]
    )


@dataclass
class World:
    """Writes one Principal's source, snapshots, windows and messages."""

    engine: Engine
    principal_id: str = P
    tag: str = "a"
    days: dict[int, str] = field(default_factory=dict)
    source_id: str = ""

    def __post_init__(self) -> None:
        self.source_id = f"isrc_srch{self.tag}source"
        with unit_of_work(self.engine)() as unit:
            unit.ingestion.insert_source(
                self.principal_id,
                IngestSourceRecord(
                    ingest_source_id=self.source_id,
                    consumer=IngestConsumer.COMMUNICATIONS_EVIDENCE_V2,
                    workspace_id="mcp",
                    path_prefix="My PA/Daily Intelligence/communications/",
                    file_pattern="*-comms.json",
                    enabled=True,
                    admitted_at=NOW,
                ),
            )

    def snapshot(self, day: int, *, covered: bool = True) -> str:
        """The day's snapshot (created once), with a complete window when `covered`."""
        if day in self.days:
            return self.days[day]
        snapshot_id = f"isnp_srch{self.tag}day{day:02d}"
        with unit_of_work(self.engine)() as unit:
            unit.ingestion.insert_snapshot(
                self.principal_id,
                IngestSnapshotRecord(
                    snapshot_id=snapshot_id,
                    ingest_source_id=self.source_id,
                    file_sha256=_sha(snapshot_id),
                    byte_count=1024,
                    observed_version_token=None,
                    first_seen_at=NOW,
                ),
            )
            unit.ingestion.finalize_snapshot(
                self.principal_id,
                snapshot_id,
                status=IngestSnapshotStatus.INGESTED,
                rejection_code=None,
                parser_version="evidence_v2-1.0",
            )
            if covered:
                unit.ingestion.insert_coverage_window(
                    self.principal_id,
                    IngestCoverageWindowRecord(
                        coverage_window_id=f"icov_srch{self.tag}day{day:02d}",
                        ingest_source_id=self.source_id,
                        snapshot_id=snapshot_id,
                        start_utc=at(day, 0),
                        end_utc=at(day, 23, 59) + timedelta(seconds=59),
                        coverage_state="complete",
                        lane_states=(
                            {
                                "key_kind": "inbox",
                                "role": "inbox",
                                "lane": "mail",
                                "authorized": True,
                                "state": "complete",
                            },
                        ),
                        recorded_at=NOW,
                    ),
                )
        self.days[day] = snapshot_id
        return snapshot_id

    def message(
        self,
        n: int,
        *,
        subject: str | None,
        text: str | None,
        when: datetime,
        conversation: str | None = None,
        participants: Sequence[tuple[str, str]] = (("from", "alpha@example.invalid"),),
        lanes: Sequence[tuple[str, str]] = (("inbox", "verified"),),
        body_state: str = "present",
        identifiers_version: str | None = IDENTIFIER_VERSION,
        extra_identifiers: Sequence[tuple[str, str, str]] = (),
    ) -> str:
        """One message with its item, observations, participants and current identifiers."""
        snapshot_id = self.snapshot(when.day)
        message_id = f"cmsg_srch{self.tag}{n:06d}"
        item_id = f"cmitm_srch{self.tag}{n:06d}"
        record = CommunicationMessageRecord(
            message_id=message_id,
            mailbox_ref="mbx-synthetic",
            identity_kind="provider_returned",
            identity_value=f"<{self.tag}{n}@example.invalid>",
            conversation_id=conversation,
            subject=subject,
            sender_address=participants[0][1] if participants else None,
            message_time=when,
            message_time_basis="sent",
            has_attachments=False,
            projection=CommunicationProjection(
                body_state=body_state,
                body_sha256=_sha(f"body-{message_id}"),
                body_utf8_bytes=0 if text is None else len(text.encode("utf-8")),
                content_type="text",
                search_text=text,
                search_text_sha256=None if text is None else _sha(text),
                search_text_version=TEXT_VERSION,
                search_text_basis="none" if text is None else "body_content",
                search_text_flags=(),
                text_snapshot_id=snapshot_id,
                text_record_ordinal=n,
            ),
            first_snapshot_id=snapshot_id,
            latest_snapshot_id=snapshot_id,
            identifiers_version=identifiers_version,
        )
        observations: dict[str, list[str]] = {}
        for name, address in participants:
            observations.setdefault(name, []).append(address)
        with unit_of_work(self.engine)() as unit:
            repository = unit.communications
            repository.insert_message(self.principal_id, record)
            repository.insert_item(
                self.principal_id,
                CommunicationMailboxItemRecord(
                    item_id=item_id,
                    message_id=message_id,
                    mailbox_ref="mbx-synthetic",
                    provider_id=f"AAMk-{self.tag}-{n}",
                    provider_id_format="mutable",
                    first_snapshot_id=snapshot_id,
                ),
            )
            first = ""
            for index, (role, verification) in enumerate(lanes):
                observation_id = f"cobs_srch{self.tag}{n:06d}x{index}"
                first = first or observation_id
                repository.insert_observation(
                    self.principal_id,
                    CommunicationObservationRecord(
                        observation_id=observation_id,
                        item_id=item_id,
                        snapshot_id=snapshot_id,
                        record_ordinal=n if index == 0 else 100_000 + n * 10 + index,
                        classification="accepted" if index == 0 else "lane_observation_merged",
                        reasons=(),
                        folder_role=role,
                        lane_verification=verification,
                        selected_field="sent",
                        selected_utc=when,
                        received_utc=None,
                        received_state="absent",
                        sent_utc=when,
                        sent_state="present",
                        body_sha256=record.projection.body_sha256,
                        unique_body_sha256=None,
                        participants={k: tuple(v) for k, v in observations.items()},
                    ),
                )
            repository.insert_participants(
                self.principal_id,
                [
                    CommunicationParticipantRecord(
                        message_id=message_id,
                        field=name,
                        address=address,
                        first_observation_id=first,
                    )
                    for name, address in participants
                ],
            )
            found = extract_identifiers(f"{subject or ''}\n{text or ''}")
            repository.insert_identifiers(
                self.principal_id,
                [
                    CommunicationIdentifierRecord(
                        message_id=message_id,
                        kind=identifier.kind.value,
                        value=identifier.value,
                        extractor_version=IDENTIFIER_VERSION,
                    )
                    for identifier in found
                ]
                + [
                    CommunicationIdentifierRecord(message_id, kind, value, version)
                    for kind, value, version in extra_identifiers
                ],
            )
        return message_id
