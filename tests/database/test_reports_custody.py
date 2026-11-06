"""Reports Modernization WP05b W2: legal holds and the sealed preservation copy on PostgreSQL.

The `database` tier, each test on its own disposable head-migrated clone
(`migrated_engine`) and a real `FilesystemReportContentStore` per namespace
(`content`, `preservation`) under one root in `tmp_path`. What it proves:

* a hold refuses `delete` (no lifecycle row) and nothing else; release then
  delete succeeds; place/release alternate against the current revision;
* placement without a preservation store writes no hold row;
* the copy on disk: the seal parses and lists every version, manifest, event
  and object; every part verifies; identity and gzip, inline and
  `managed_blob`; one preserved object per DISTINCT content object;
* a copy that does not verify (seal corrupted on put, a read-back that
  differs, a part that does not verify) raises and commits NO hold row and
  no root change; a part corrupted on disk after placement fails
  `verify_preservation_copy`;
* a same-key replay returns the original and puts nothing; another payload
  under the key is an idempotency conflict;
* the hold-vs-delete race on two real sessions, both orders;
* Principal scoping: a foreign report is not found.

Every identifier, title and byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import json
import threading
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Connection, Engine, text

from my_pa.application.report_preservation import verify_preservation_copy
from my_pa.contracts.ports import (
    ReportContentIntegrityError,
    ReportContentNamespace,
    ReportContentPart,
    ReportContentStore,
    ReportHeldError,
    ReportHoldStateError,
    ReportIdempotencyConflictError,
    ReportNotFoundError,
    ReportPreservationError,
    ReportPreservationUnavailableError,
    ReportStaleHoldRevisionError,
)
from my_pa.domain.common.identifiers import IdKind, parse_identifier
from my_pa.domain.reports.content import validate_content
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.custody import (
    PRESERVATION_SEAL_SCHEMA,
    CustodyAuthority,
    HoldOperation,
    HoldRequest,
    HoldResult,
)
from my_pa.domain.reports.publication import PublicationRequest
from my_pa.domain.reports.revision import (
    LifecycleRequest,
    LifecycleResult,
    ReportPatch,
    UpdateRequest,
)
from my_pa.domain.reports.vocabulary import LifecycleOperation
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore
from tests.database.test_reports_general_persistence import PRINCIPAL_A, PRINCIPAL_B, _wait_until

pytestmark = pytest.mark.database

AUTHORITY: Final = CustodyAuthority("local_operator", "local_cli")
REASON: Final = "Synthetic litigation hold."
LOW: Final = 64
JOIN_SECONDS: Final = 30.0


class Stores:
    """The content and preservation namespaces of one store root."""

    def __init__(self, tmp_path: Path) -> None:
        self.root = tmp_path / "report-content"
        self.root.mkdir()
        self.content = FilesystemReportContentStore(self.root, ReportContentNamespace.CONTENT)
        self.preservation = FilesystemReportContentStore(
            self.root, ReportContentNamespace.PRESERVATION
        )

    def part_path(self, object_id: str, part: ReportContentPart) -> Path:
        _kind, suffix = parse_identifier(object_id)
        return self.root / "preservation" / suffix[:2] / object_id / part.value


@pytest.fixture
def stores(tmp_path: Path) -> Stores:
    return Stores(tmp_path)


def _now() -> dict[str, Any]:
    return {
        "recorded_at": datetime.now(UTC),
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
    }


def _gzip(raw: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    return {"format": "text", "encoding": "gzip+base64", "encoded": encoded}


def _publish(
    engine: Engine,
    content: dict[str, Any] | None = None,
    *,
    key: str = "pub",
    principal_id: str = PRINCIPAL_A,
    content_store: ReportContentStore | None = None,
) -> str:
    with engine.begin() as connection:
        return (
            SqlGeneralReportRepository(connection)
            .publish(
                PublicationRequest(
                    title="Synthetic held report",
                    content=validate_content(content or {"format": "markdown", "body": "# H\n"}),
                ),
                principal_id=principal_id,
                creator=derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal_id),
                idempotency_key=key,
                content_store=content_store,
                inline_max_bytes=LOW,
                **_now(),
            )
            .receipt.report_id
        )


def _hold_on(
    connection: Connection,
    operation: HoldOperation,
    report_id: str,
    key: str,
    revision: int,
    *,
    store: ReportContentStore | None = None,
    content_store: ReportContentStore | None = None,
    principal_id: str = PRINCIPAL_A,
    reason: str = REASON,
) -> HoldResult:
    repository = SqlGeneralReportRepository(connection)
    request = HoldRequest(operation, report_id, revision, reason)
    common: dict[str, Any] = {
        "principal_id": principal_id,
        "idempotency_key": key,
        "authority": AUTHORITY,
        **_now(),
    }
    if operation is HoldOperation.PLACE:
        return repository.place_hold(
            request, preservation_store=store, content_store=content_store, **common
        )
    return repository.release_hold(request, **common)


def _hold(engine: Engine, *args: Any, **kwargs: Any) -> HoldResult:  # noqa: ANN401
    with engine.begin() as connection:
        return _hold_on(connection, *args, **kwargs)


def _move_on(
    connection: Connection, operation: LifecycleOperation, report_id: str, revision: int, key: str
) -> LifecycleResult:
    return SqlGeneralReportRepository(connection).transition(
        LifecycleRequest(operation, report_id, revision),
        principal_id=PRINCIPAL_A,
        idempotency_key=key,
        **_now(),
    )


def _move(
    engine: Engine, operation: LifecycleOperation, report_id: str, revision: int, key: str
) -> LifecycleResult:
    with engine.begin() as connection:
        return _move_on(connection, operation, report_id, revision, key)


def _update(
    engine: Engine,
    report_id: str,
    expected: int,
    patch: ReportPatch,
    key: str,
    content_store: ReportContentStore | None = None,
) -> None:
    with engine.begin() as connection:
        SqlGeneralReportRepository(connection).update(
            UpdateRequest(
                report_id=report_id,
                expected_version=expected,
                patch=patch,
                change_reason="A synthetic change.",
            ),
            principal_id=PRINCIPAL_A,
            creator=derive_creator(CreatorKind.LOCAL_PRINCIPAL, PRINCIPAL_A),
            idempotency_key=key,
            content_store=content_store,
            inline_max_bytes=LOW,
            **_now(),
        )


def _scalar(engine: Engine, statement: str, **parameters: object) -> Any:  # noqa: ANN401
    with engine.connect() as connection:
        return connection.execute(text(statement), parameters).scalar_one()


def _hold_rows(engine: Engine) -> int:
    return int(_scalar(engine, "SELECT count(*) FROM knowledge.report_hold_events"))


def _lifecycle_rows(engine: Engine, report_id: str) -> int:
    return int(
        _scalar(
            engine,
            "SELECT count(*) FROM knowledge.report_lifecycle_events WHERE report_id = :r",
            r=report_id,
        )
    )


def _root_hold(engine: Engine, report_id: str) -> tuple[int, str | None, bool]:
    with engine.connect() as connection:
        row = connection.execute(
            text(
                "SELECT hold_revision, hold_event_id, held FROM knowledge.report_roots "
                "WHERE report_id = :r"
            ),
            {"r": report_id},
        ).one()
    return int(row[0]), row[1], bool(row[2])


def _ledger(engine: Engine, report_id: str, principal_id: str = PRINCIPAL_A) -> Any:  # noqa: ANN401
    with engine.connect() as connection:
        return SqlGeneralReportRepository(connection).hold_events(
            report_id, principal_id=principal_id
        )


def _seal(stores: Stores, result: HoldResult) -> dict[str, Any]:
    assert result.preservation is not None
    data = stores.part_path(result.preservation.seal_object_id, ReportContentPart.DECODED)
    document = json.loads(data.read_bytes())
    assert isinstance(document, dict)
    return document


# ---- hold blocks delete only --------------------------------------------------------------


def test_a_hold_blocks_delete_only_until_released(migrated_engine: Engine, stores: Stores) -> None:
    engine = migrated_engine
    report = _publish(engine)
    placed = _hold(engine, HoldOperation.PLACE, report, "h1", 0, store=stores.preservation)
    assert _root_hold(engine, report) == (1, placed.event_id, True)
    with pytest.raises(ReportHeldError):
        _move(engine, LifecycleOperation.DELETE, report, 0, "d1")
    assert _lifecycle_rows(engine, report) == 0
    _move(engine, LifecycleOperation.ARCHIVE, report, 0, "a")
    _move(engine, LifecycleOperation.RESTORE, report, 1, "r")
    _update(engine, report, 1, ReportPatch(title="Still editable"), "u")
    with pytest.raises(ReportHeldError):
        _move(engine, LifecycleOperation.DELETE, report, 2, "d2")
    assert _lifecycle_rows(engine, report) == 2
    objects = stores.preservation.stored_object_ids()
    released = _hold(engine, HoldOperation.RELEASE, report, "h1", 1)
    assert _root_hold(engine, report) == (2, released.event_id, False)
    assert stores.preservation.stored_object_ids() == objects  # kept after release
    trashed = _move(engine, LifecycleOperation.DELETE, report, 2, "d3")
    assert trashed.resulting_state.value == "trashed"
    ledger = _ledger(engine, report)
    assert [(e.operation, e.hold_revision) for e in ledger] == [
        (HoldOperation.PLACE, 1),
        (HoldOperation.RELEASE, 2),
    ]
    assert ledger[1].predecessor_event_id == ledger[0].event_id
    assert ledger[0].authority == AUTHORITY and ledger[1].preservation is None


def test_alternation_and_stale_revisions_write_nothing(
    migrated_engine: Engine, stores: Stores
) -> None:
    engine = migrated_engine
    report = _publish(engine)
    with pytest.raises(ReportHoldStateError):
        _hold(engine, HoldOperation.RELEASE, report, "r0", 0)
    with pytest.raises(ReportStaleHoldRevisionError):
        _hold(engine, HoldOperation.PLACE, report, "p-stale", 1, store=stores.preservation)
    assert _hold_rows(engine) == 0 and stores.preservation.stored_object_ids() == ()
    _hold(engine, HoldOperation.PLACE, report, "p1", 0, store=stores.preservation)
    with pytest.raises(ReportHoldStateError):
        _hold(engine, HoldOperation.PLACE, report, "p2", 1, store=stores.preservation)
    with pytest.raises(ReportStaleHoldRevisionError):
        _hold(engine, HoldOperation.RELEASE, report, "r-stale", 0)
    assert _hold_rows(engine) == 1 and len(stores.preservation.stored_object_ids()) == 2


def test_placement_without_a_store_writes_no_hold(migrated_engine: Engine) -> None:
    report = _publish(migrated_engine)
    with pytest.raises(ReportPreservationUnavailableError):
        _hold(migrated_engine, HoldOperation.PLACE, report, "h", 0, store=None)
    assert _hold_rows(migrated_engine) == 0
    assert _root_hold(migrated_engine, report) == (0, None, False)


def test_a_foreign_report_is_not_found(migrated_engine: Engine, stores: Stores) -> None:
    engine = migrated_engine
    report = _publish(engine)
    with pytest.raises(ReportNotFoundError):
        _hold(
            engine,
            HoldOperation.PLACE,
            report,
            "h",
            0,
            store=stores.preservation,
            principal_id=PRINCIPAL_B,
        )
    _hold(engine, HoldOperation.PLACE, report, "h", 0, store=stores.preservation)
    with pytest.raises(ReportNotFoundError):
        _hold(engine, HoldOperation.RELEASE, report, "r", 1, principal_id=PRINCIPAL_B)
    assert _ledger(engine, report, PRINCIPAL_B) is None
    assert _hold_rows(engine) == 1


# ---- the copy on disk -------------------------------------------------------------------


def test_the_sealed_copy_on_disk_lists_and_verifies_everything(
    migrated_engine: Engine, stores: Stores
) -> None:
    engine = migrated_engine
    raw = b"Synthetic gzip body line.\n" * 8
    report = _publish(engine, _gzip(raw), content_store=stores.content)
    _update(engine, report, 1, ReportPatch(title="Metadata only"), "u1")
    _update(
        engine,
        report,
        2,
        ReportPatch(content=validate_content({"format": "markdown", "body": "# Short\n"})),
        "u2",
    )
    _move(engine, LifecycleOperation.ARCHIVE, report, 0, "a")
    placed = _hold(
        engine,
        HoldOperation.PLACE,
        report,
        "h",
        0,
        store=stores.preservation,
        content_store=stores.content,
    )
    preservation = placed.preservation
    assert preservation is not None
    assert (preservation.object_count, preservation.version_count) == (2, 3)
    assert (preservation.head_version_number, preservation.lifecycle_revision) == (3, 1)
    # One object per DISTINCT content object, plus the seal.
    assert len(stores.preservation.stored_object_ids()) == 3
    seal = _seal(stores, placed)
    assert seal["schema"] == PRESERVATION_SEAL_SCHEMA
    assert (seal["report_id"], seal["owner_principal_id"], seal["hold_event_id"]) == (
        report,
        PRINCIPAL_A,
        placed.event_id,
    )
    assert seal["root"]["lifecycle_state"] == "archived"
    assert [v["change_kind"] for v in seal["versions"]] == ["initial", "metadata", "content"]
    first, second, third = seal["versions"]
    assert first["preservation_object_id"] == second["preservation_object_id"]
    assert first["preservation_object_id"] != third["preservation_object_id"]
    with engine.connect() as connection:
        manifests = connection.execute(
            text(
                "SELECT m.manifest_sha256, m.manifest FROM knowledge.report_version_manifests m "
                "JOIN knowledge.report_versions v USING (version_id) "
                "WHERE v.report_id = :r ORDER BY v.version_number"
            ),
            {"r": report},
        ).all()
        kinds = connection.execute(
            text(
                "SELECT c.content_id, c.storage_kind, c.original_encoding "
                "FROM knowledge.report_content_objects c JOIN knowledge.report_versions v "
                "USING (content_id) WHERE v.report_id = :r ORDER BY v.version_number"
            ),
            {"r": report},
        ).all()
    for version, (digest, manifest) in zip(seal["versions"], manifests, strict=True):
        assert version["manifest_sha256"] == digest and version["manifest"] == manifest
    objects = {item["content_id"]: item for item in seal["objects"]}
    assert {(row[0], row[1], row[2]) for row in kinds} == {
        (cid, item["storage_kind"], item["encoding"]) for cid, item in objects.items()
    }
    blob = objects[first["content_id"]]
    assert (blob["storage_kind"], blob["encoding"]) == ("managed_blob", "gzip+base64")
    decoded = stores.part_path(blob["preservation_object_id"], ReportContentPart.DECODED)
    original = stores.part_path(blob["preservation_object_id"], ReportContentPart.ORIGINAL)
    assert decoded.read_bytes() == raw
    assert gzip.decompress(original.read_bytes()) == raw
    inline = objects[third["content_id"]]
    assert (inline["storage_kind"], inline["encoding"], inline["original"]) == (
        "inline",
        "identity",
        None,
    )
    assert [e["operation"] for e in seal["lifecycle_events"]] == ["archive"]
    (event,) = _ledger(engine, report)
    assert event.preservation == preservation
    assert verify_preservation_copy(stores.preservation, event) == 3


def test_a_part_corrupted_on_disk_fails_reverification(
    migrated_engine: Engine, stores: Stores
) -> None:
    engine = migrated_engine
    report = _publish(engine, _gzip(b"Synthetic preserved.\n" * 2))
    placed = _hold(engine, HoldOperation.PLACE, report, "h", 0, store=stores.preservation)
    (event,) = _ledger(engine, report)
    assert verify_preservation_copy(stores.preservation, event) == 2
    assert placed.preservation is not None
    (object_id,) = (
        o
        for o in stores.preservation.stored_object_ids()
        if o != placed.preservation.seal_object_id
    )
    path = stores.part_path(object_id, ReportContentPart.ORIGINAL)
    kept = path.read_bytes()
    path.chmod(0o600)
    path.write_bytes(kept[:-1] + bytes([kept[-1] ^ 1]))
    with pytest.raises(ReportPreservationError):
        verify_preservation_copy(stores.preservation, event)
    path.write_bytes(kept)
    assert verify_preservation_copy(stores.preservation, event) == 2
    seal = stores.part_path(placed.preservation.seal_object_id, ReportContentPart.DECODED)
    seal.chmod(0o600)
    seal.write_bytes(seal.read_bytes() + b" ")
    with pytest.raises(ReportPreservationError):
        verify_preservation_copy(stores.preservation, event)


# ---- tamper: verified before the hold row --------------------------------------------------


class _Delegating(ReportContentStore):
    def __init__(self, inner: ReportContentStore) -> None:
        self.inner = inner

    def put(self, object_id: str, *, decoded: bytes, original: bytes | None) -> None:
        self.inner.put(object_id, decoded=decoded, original=original)

    def read(
        self,
        object_id: str,
        part: ReportContentPart,
        *,
        expected_sha256: str,
        expected_byte_count: int,
    ) -> bytes:
        return self.inner.read(
            object_id,
            part,
            expected_sha256=expected_sha256,
            expected_byte_count=expected_byte_count,
        )

    def verify(
        self,
        object_id: str,
        part: ReportContentPart,
        *,
        expected_sha256: str,
        expected_byte_count: int,
    ) -> None:
        self.inner.verify(
            object_id,
            part,
            expected_sha256=expected_sha256,
            expected_byte_count=expected_byte_count,
        )

    def has(self, object_id: str) -> bool:
        return self.inner.has(object_id)

    def stored_object_ids(self) -> tuple[str, ...]:
        return self.inner.stored_object_ids()

    def unreadable_entries(self) -> tuple[str, ...]:
        return self.inner.unreadable_entries()


class _CorruptsTheSealOnPut(_Delegating):
    def put(self, object_id: str, *, decoded: bytes, original: bytes | None) -> None:
        if decoded.startswith(b'{"hold_event_id"'):
            decoded += b" "
        super().put(object_id, decoded=decoded, original=original)


class _ReadsBackOtherBytes(_Delegating):
    def read(
        self,
        object_id: str,
        part: ReportContentPart,
        *,
        expected_sha256: str,
        expected_byte_count: int,
    ) -> bytes:
        data = super().read(
            object_id,
            part,
            expected_sha256=expected_sha256,
            expected_byte_count=expected_byte_count,
        )
        return data[:-1] + b"?"


class _VerifyMismatches(_Delegating):
    def verify(
        self,
        object_id: str,
        part: ReportContentPart,
        *,
        expected_sha256: str,
        expected_byte_count: int,
    ) -> None:
        raise ReportContentIntegrityError("digest")


@pytest.mark.parametrize(
    "wrapper", [_CorruptsTheSealOnPut, _ReadsBackOtherBytes, _VerifyMismatches]
)
def test_a_copy_that_does_not_verify_commits_no_hold(
    migrated_engine: Engine, stores: Stores, wrapper: Callable[[ReportContentStore], _Delegating]
) -> None:
    engine = migrated_engine
    report = _publish(engine)
    with pytest.raises(ReportPreservationError):
        _hold(engine, HoldOperation.PLACE, report, "h", 0, store=wrapper(stores.preservation))
    assert _hold_rows(engine) == 0
    assert _root_hold(engine, report) == (0, None, False)
    # What was put before the failure remains (orphans); nothing deletes it.
    assert len(stores.preservation.stored_object_ids()) == 2
    _move(engine, LifecycleOperation.DELETE, report, 0, "d")


# ---- idempotency -------------------------------------------------------------------------


def test_a_same_key_replay_puts_no_second_copy(migrated_engine: Engine, stores: Stores) -> None:
    engine = migrated_engine
    report = _publish(engine)
    first = _hold(engine, HoldOperation.PLACE, report, "same", 0, store=stores.preservation)
    objects = stores.preservation.stored_object_ids()
    replay = _hold(engine, HoldOperation.PLACE, report, "same", 0, store=stores.preservation)
    assert replay.replayed and not first.replayed
    assert (replay.event_id, replay.preservation, replay.recorded_at) == (
        first.event_id,
        first.preservation,
        first.recorded_at,
    )
    assert stores.preservation.stored_object_ids() == objects
    with pytest.raises(ReportIdempotencyConflictError):
        _hold(
            engine,
            HoldOperation.PLACE,
            report,
            "same",
            0,
            store=stores.preservation,
            reason="Another reason.",
        )
    assert _hold_rows(engine) == 1 and stores.preservation.stored_object_ids() == objects


# ---- the hold-vs-delete race on two real sessions ------------------------------------------


def _blocked_on_a_lock(engine: Engine) -> bool:
    with engine.connect() as observer:
        return bool(
            observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND state = 'active'"
                )
            ).scalar_one()
        )


def _race(
    engine: Engine,
    first: Callable[[Connection], object],
    second: Callable[[Connection], object],
) -> tuple[object, dict[str, object]]:
    """Run `first` on A and hold its transaction; `second` on B blocks; then commit A."""
    outcome: dict[str, object] = {}

    def writer_b() -> None:
        try:
            with engine.begin() as connection:
                connection.execute(text("SET LOCAL lock_timeout = '20s'"))
                outcome["result"] = second(connection)
        except Exception as error:  # the typed refusal is the assertion target
            outcome["error"] = error

    connection_a = engine.connect()
    transaction = connection_a.begin()
    thread = threading.Thread(target=writer_b, daemon=True)
    try:
        winner = first(connection_a)
        thread.start()
        assert _wait_until(lambda: _blocked_on_a_lock(engine)), "writer B never blocked"
        assert thread.is_alive() and not outcome
        transaction.commit()
    finally:
        if transaction.is_active:
            transaction.rollback()
        connection_a.close()
    thread.join(timeout=JOIN_SECONDS)
    assert not thread.is_alive(), "writer B did not finish after A committed"
    return winner, outcome


def test_a_placement_holding_the_lock_refuses_the_waiting_delete(
    migrated_engine: Engine, stores: Stores
) -> None:
    engine = migrated_engine
    report = _publish(engine)
    winner, outcome = _race(
        engine,
        lambda c: _hold_on(c, HoldOperation.PLACE, report, "h", 0, store=stores.preservation),
        lambda c: _move_on(c, LifecycleOperation.DELETE, report, 0, "d"),
    )
    assert isinstance(winner, HoldResult) and winner.held
    assert isinstance(outcome.get("error"), ReportHeldError), outcome
    assert _lifecycle_rows(engine, report) == 0
    assert _root_hold(engine, report) == (1, winner.event_id, True)


def test_a_delete_holding_the_lock_lets_the_waiting_placement_hold_the_trashed_report(
    migrated_engine: Engine, stores: Stores
) -> None:
    engine = migrated_engine
    report = _publish(engine)
    winner, outcome = _race(
        engine,
        lambda c: _move_on(c, LifecycleOperation.DELETE, report, 0, "d"),
        lambda c: _hold_on(c, HoldOperation.PLACE, report, "h", 0, store=stores.preservation),
    )
    assert isinstance(winner, LifecycleResult) and winner.resulting_state.value == "trashed"
    placed = outcome.get("result")
    assert isinstance(placed, HoldResult), outcome
    assert _root_hold(engine, report) == (1, placed.event_id, True)
    seal = _seal(stores, placed)
    # B sealed after A's commit: the copy names the trashed root and its delete event.
    assert seal["root"]["lifecycle_state"] == "trashed"
    assert [e["operation"] for e in seal["lifecycle_events"]] == ["delete"]
