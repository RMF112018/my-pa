"""Reports Modernization WP05b W2: legal holds and the sealed preservation copy (FAST tier).

Over the FAST world's in-memory general report fake, which seals through the
same `infrastructure.persistence.report_custody.seal_preservation_copy` as the
SQL repository, and an in-memory report content store per namespace. The
PostgreSQL behaviour (rows, locking, the two-session race, a real filesystem
store) is `tests/database/test_reports_custody.py`'s.

Every title, body and identifier is synthetic.
"""

from __future__ import annotations

import base64
import gc
import gzip
import hashlib
import json
import tracemalloc
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.errors import SafeDetail
from my_pa.application.report_preservation import verify_preservation_copy
from my_pa.contracts.ports import (
    ReportContentIntegrityError,
    ReportContentNamespace,
    ReportContentPart,
    ReportContentStore,
    ReportContentStoreError,
    ReportHeldError,
    ReportHoldStateError,
    ReportIdempotencyConflictError,
    ReportNotFoundError,
    ReportPreservationError,
    ReportPreservationUnavailableError,
    ReportStaleHoldRevisionError,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.reports.content import validate_content
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.custody import (
    PRESERVATION_SEAL_SCHEMA,
    CustodyAuthority,
    HoldOperation,
    HoldRequest,
    HoldResult,
    preservation_seal_parts,
)
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.publication import PublicationRequest
from my_pa.domain.reports.revision import LifecycleRequest, ReportPatch, UpdateRequest
from my_pa.domain.reports.vocabulary import LifecycleOperation, LifecycleState
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore
from tests.conftest import (
    InMemoryReportContentStore,
    Scene,
    _GeneralReports,
    build_service,
)

AUTHORITY: Final = CustodyAuthority("local_operator", "local_cli")
WHEN: Final = datetime(2026, 11, 6, 12, 0, tzinfo=UTC)
FOREIGN: Final = "prn_ffff0009ffff0009ffff0009"
REASON: Final = "Synthetic litigation hold."
SEAL_KEYS: Final = {
    "schema",
    "report_id",
    "owner_principal_id",
    "hold_event_id",
    "sealed_at",
    "root",
    "versions",
    "objects",
    "lifecycle_events",
}


def _preservation() -> InMemoryReportContentStore:
    return InMemoryReportContentStore(ReportContentNamespace.PRESERVATION)


def _gzip(raw: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    return {"format": "text", "encoding": "gzip+base64", "encoded": encoded}


def _publish(
    reports: _GeneralReports,
    principal_id: str,
    content: dict[str, Any] | None = None,
    *,
    key: str = "pub",
    content_store: ReportContentStore | None = None,
    inline_max_bytes: int = 262_144,
) -> str:
    return reports.publish(
        PublicationRequest(
            title="Synthetic held report",
            content=validate_content(content or {"format": "markdown", "body": "# Held\n"}),
        ),
        principal_id=principal_id,
        creator=derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal_id),
        idempotency_key=key,
        recorded_at=WHEN,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        content_store=content_store,
        inline_max_bytes=inline_max_bytes,
    ).receipt.report_id


def _hold(
    reports: _GeneralReports,
    principal_id: str,
    operation: HoldOperation,
    report_id: str,
    key: str,
    revision: int,
    *,
    store: ReportContentStore | None = None,
    content_store: ReportContentStore | None = None,
    reason: str = REASON,
) -> HoldResult:
    request = HoldRequest(operation, report_id, revision, reason)
    common: dict[str, Any] = {
        "principal_id": principal_id,
        "idempotency_key": key,
        "authority": AUTHORITY,
        "recorded_at": WHEN,
        "correlation_id": issue_identifier(IdKind.CORRELATION),
        "audit_id": issue_identifier(IdKind.AUDIT),
    }
    if operation is HoldOperation.PLACE:
        return reports.place_hold(
            request, preservation_store=store, content_store=content_store, **common
        )
    return reports.release_hold(request, **common)


def _move(
    reports: _GeneralReports,
    principal_id: str,
    operation: LifecycleOperation,
    report_id: str,
    revision: int,
    key: str,
) -> None:
    reports.transition(
        LifecycleRequest(operation, report_id, revision),
        principal_id=principal_id,
        idempotency_key=key,
        recorded_at=WHEN,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
    )


def _update(
    reports: _GeneralReports,
    principal_id: str,
    report_id: str,
    expected: int,
    patch: ReportPatch,
    key: str,
    *,
    content_store: ReportContentStore | None = None,
    inline_max_bytes: int = 262_144,
) -> None:
    reports.update(
        UpdateRequest(
            report_id=report_id,
            expected_version=expected,
            patch=patch,
            change_reason="A synthetic change.",
        ),
        principal_id=principal_id,
        creator=derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal_id),
        idempotency_key=key,
        recorded_at=WHEN,
        correlation_id=issue_identifier(IdKind.CORRELATION),
        audit_id=issue_identifier(IdKind.AUDIT),
        content_store=content_store,
        inline_max_bytes=inline_max_bytes,
    )


def _seal(store: InMemoryReportContentStore, result: HoldResult) -> dict[str, Any]:
    assert result.preservation is not None
    data = store.objects[result.preservation.seal_object_id][ReportContentPart.DECODED]
    assert hashlib.sha256(data).hexdigest() == result.preservation.seal_sha256
    assert len(data) == result.preservation.seal_byte_count
    document = json.loads(data)
    assert isinstance(document, dict)
    return document


# ---- domain ------------------------------------------------------------------------------


def test_a_hold_request_validates_and_digests_its_caller_fields() -> None:
    request = HoldRequest(HoldOperation.PLACE, "grpt_x", 0, REASON)
    payload = {
        "operation": "place",
        "report_id": "grpt_x",
        "expected_hold_revision": 0,
        "reason": REASON,
    }
    expected = hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    assert request.intent_digest == expected
    assert HoldRequest(HoldOperation.RELEASE, "grpt_x", 0, REASON).intent_digest != expected
    refused: tuple[Callable[[], object], ...] = (
        lambda: HoldRequest("place", "grpt_x", 0, REASON),  # type: ignore[arg-type]
        lambda: HoldRequest(HoldOperation.PLACE, "", 0, REASON),
        lambda: HoldRequest(HoldOperation.PLACE, "grpt_x", -1, REASON),
        lambda: HoldRequest(HoldOperation.PLACE, "grpt_x", True, REASON),
        lambda: HoldRequest(HoldOperation.PLACE, "grpt_x", 0, None),  # type: ignore[arg-type]
        lambda: HoldRequest(HoldOperation.PLACE, "grpt_x", 0, ""),
        lambda: HoldRequest(HoldOperation.PLACE, "grpt_x", 0, "x" * 501),
        lambda: HoldRequest(HoldOperation.PLACE, "grpt_x", 0, "bad\x00"),
    )
    for bad in refused:
        with pytest.raises(ReportValidationError):
            bad()


def test_only_the_attested_operator_pair_is_an_authority() -> None:
    assert AUTHORITY.validated() == AUTHORITY
    assert CustodyAuthority("local_operator", "local_web").validated()
    for pair in (
        ("ordinary_reviewer", "local_cli"),
        ("local_operator", "remote_mcp"),
        ("local_operator", ""),
    ):
        with pytest.raises(ReportValidationError):
            CustodyAuthority(*pair).validated()


def test_a_malformed_seal_lists_nothing() -> None:
    for seal in (b"", b"[]", b'{"schema":"other"}', b"\xff", b'{"schema":"x","objects":[]}'):
        with pytest.raises(ValueError, match="malformed"):
            preservation_seal_parts(seal)
    empty = json.dumps({"schema": PRESERVATION_SEAL_SCHEMA, "objects": []}).encode()
    with pytest.raises(ValueError, match="no object"):
        preservation_seal_parts(empty)


def test_the_report_held_detail_is_a_stable_token() -> None:
    assert SafeDetail.REPORT_HELD.value == "report_held"


def test_the_preservation_namespace_admits_only_preservation_ids() -> None:
    store = _preservation()
    with pytest.raises(ReportContentStoreError):
        store.put(issue_identifier(IdKind.REPORT_CONTENT), decoded=b"x", original=None)
    store.put(issue_identifier(IdKind.REPORT_PRESERVATION_OBJECT), decoded=b"x", original=None)
    with pytest.raises(ReportContentStoreError):
        InMemoryReportContentStore().put(
            issue_identifier(IdKind.REPORT_PRESERVATION_OBJECT), decoded=b"x", original=None
        )


# ---- hold blocks delete only --------------------------------------------------------------


def test_a_hold_blocks_delete_and_nothing_else_until_released(scene: Scene) -> None:
    world, reports = scene.world, _GeneralReports(scene.world)
    p = scene.principal.principal_id
    report = _publish(reports, p)
    store = _preservation()
    placed = _hold(reports, p, HoldOperation.PLACE, report, "hold-1", 0, store=store)
    assert (placed.held, placed.hold_revision, placed.replayed) == (True, 1, False)
    root = reports.read_version(report, principal_id=p)
    assert root is not None and root.root.held and root.root.hold_event_id == placed.event_id

    with pytest.raises(ReportHeldError):
        _move(reports, p, LifecycleOperation.DELETE, report, 0, "del-1")
    assert world.general_report_events.get((p, report), []) == []
    # Archive, restore and update are never gated by a hold (H2).
    _move(reports, p, LifecycleOperation.ARCHIVE, report, 0, "arc")
    _move(reports, p, LifecycleOperation.RESTORE, report, 1, "res")
    _update(reports, p, report, 1, ReportPatch(title="Still editable"), "upd")
    with pytest.raises(ReportHeldError):
        _move(reports, p, LifecycleOperation.DELETE, report, 2, "del-2")

    released = _hold(reports, p, HoldOperation.RELEASE, report, "hold-1", 1)
    assert (released.held, released.hold_revision, released.preservation) == (False, 2, None)
    puts = store.puts
    _move(reports, p, LifecycleOperation.DELETE, report, 2, "del-3")
    head = reports.read_version(report, principal_id=p)
    assert head is not None and head.root.lifecycle_state is LifecycleState.TRASHED
    # Release never touched the copy.
    assert store.puts == puts and len(store.objects) == 2


def test_the_hold_refusal_is_denied_report_held_on_the_canonical_path(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    p = scene.principal.principal_id
    reports = _GeneralReports(scene.world)
    report = _publish(reports, p)
    _hold(reports, p, HoldOperation.PLACE, report, "h", 0, store=_preservation())

    def invoke(capability: Capability, key: str, revision: int) -> dict[str, Any]:
        (purpose,) = permitted_purposes(capability)
        metadata, command = normalize(
            capability.value,
            {
                "request_id": "req",
                "purpose": purpose.value,
                "principal_id": p,
                "requested_at": "2026-11-06T12:00:00Z",
                "payload": {
                    "report_id": report,
                    "expected_lifecycle_revision": revision,
                    "idempotency_key": key,
                },
            },
        )
        return service.invoke(metadata, command, principal=scene.principal).model_dump(mode="json")

    refused = invoke(Capability.REPORTS_DELETE, "d", 0)
    assert refused["result"] is None
    assert refused["error"]["code"] == ErrorCode.DENIED.value
    assert refused["error"]["safe_details"] == ["report_held"]
    assert report not in json.dumps(refused["error"])
    assert invoke(Capability.REPORTS_ARCHIVE, "a", 0)["error"] is None


def test_place_and_release_alternate_against_the_current_revision(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    store = _preservation()
    with pytest.raises(ReportHoldStateError):
        _hold(reports, p, HoldOperation.RELEASE, report, "r0", 0)
    with pytest.raises(ReportStaleHoldRevisionError):
        _hold(reports, p, HoldOperation.PLACE, report, "p-stale", 1, store=store)
    assert store.puts == 0
    _hold(reports, p, HoldOperation.PLACE, report, "p1", 0, store=store)
    with pytest.raises(ReportHoldStateError):
        _hold(reports, p, HoldOperation.PLACE, report, "p2", 1, store=store)
    with pytest.raises(ReportStaleHoldRevisionError):
        _hold(reports, p, HoldOperation.RELEASE, report, "r-stale", 0)
    _hold(reports, p, HoldOperation.RELEASE, report, "r1", 1)
    again = _hold(reports, p, HoldOperation.PLACE, report, "p3", 2, store=store)
    assert again.hold_revision == 3
    ledger = reports.hold_events(report, principal_id=p)
    assert ledger is not None
    assert [(e.hold_revision, e.operation, e.resulting_held) for e in ledger] == [
        (1, HoldOperation.PLACE, True),
        (2, HoldOperation.RELEASE, False),
        (3, HoldOperation.PLACE, True),
    ]
    assert [e.predecessor_event_id for e in ledger] == [
        None,
        ledger[0].event_id,
        ledger[1].event_id,
    ]
    assert all(e.authority == AUTHORITY for e in ledger)
    # Each placement sealed its own copy: two seals, four objects.
    assert ledger[0].preservation is not None and ledger[2].preservation is not None
    assert ledger[0].preservation.seal_object_id != ledger[2].preservation.seal_object_id
    assert len(store.objects) == 4


def test_placement_is_allowed_in_every_lifecycle_state(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    _move(reports, p, LifecycleOperation.ARCHIVE, report, 0, "a")
    _move(reports, p, LifecycleOperation.DELETE, report, 1, "d")
    store = _preservation()
    placed = _hold(reports, p, HoldOperation.PLACE, report, "h", 0, store=store)
    seal = _seal(store, placed)
    assert seal["root"]["lifecycle_state"] == "trashed"
    assert [e["operation"] for e in seal["lifecycle_events"]] == ["archive", "delete"]
    assert placed.preservation is not None and placed.preservation.lifecycle_revision == 2


def test_placement_without_a_store_is_refused_with_no_hold(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    with pytest.raises(ReportPreservationUnavailableError):
        _hold(reports, p, HoldOperation.PLACE, report, "h", 0, store=None)
    assert reports.hold_events(report, principal_id=p) == ()
    head = reports.read_version(report, principal_id=p)
    assert head is not None and (head.root.held, head.root.hold_revision) == (False, 0)


def test_the_authority_must_be_the_attested_pair(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    store = _preservation()
    with pytest.raises(ReportValidationError):
        reports.place_hold(
            HoldRequest(HoldOperation.PLACE, report, 0, REASON),
            principal_id=p,
            idempotency_key="h",
            authority=CustodyAuthority("ordinary_reviewer", "local_cli"),
            recorded_at=WHEN,
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
            preservation_store=store,
            content_store=None,
        )
    assert store.puts == 0 and reports.hold_events(report, principal_id=p) == ()


def test_a_foreign_report_is_not_found_for_place_and_release(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    store = _preservation()
    with pytest.raises(ReportNotFoundError):
        _hold(reports, FOREIGN, HoldOperation.PLACE, report, "h", 0, store=store)
    _hold(reports, p, HoldOperation.PLACE, report, "h", 0, store=store)
    with pytest.raises(ReportNotFoundError):
        _hold(reports, FOREIGN, HoldOperation.RELEASE, report, "r", 1)
    assert reports.hold_events(report, principal_id=FOREIGN) is None
    assert store.puts == 2


# ---- idempotency -------------------------------------------------------------------------


def test_a_same_key_replay_returns_the_original_without_a_second_copy(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    store = _preservation()
    first = _hold(reports, p, HoldOperation.PLACE, report, "same", 0, store=store)
    objects = dict(store.objects)
    replay = _hold(reports, p, HoldOperation.PLACE, report, "same", 0, store=store)
    assert replay.replayed and not first.replayed
    assert (replay.event_id, replay.preservation) == (first.event_id, first.preservation)
    assert store.objects == objects
    with pytest.raises(ReportIdempotencyConflictError):
        _hold(reports, p, HoldOperation.PLACE, report, "same", 0, store=store, reason="Other.")
    # The release has its own key space: the same key is a new release.
    released = _hold(reports, p, HoldOperation.RELEASE, report, "same", 1)
    assert not released.replayed and released.hold_revision == 2
    assert _hold(reports, p, HoldOperation.RELEASE, report, "same", 1).replayed
    assert store.objects == objects


# ---- the preservation copy ---------------------------------------------------------------


def test_the_seal_lists_every_version_object_and_event(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p, {"format": "markdown", "body": "# First body\n"})
    _update(reports, p, report, 1, ReportPatch(title="Metadata only"), "u1")
    _update(
        reports,
        p,
        report,
        2,
        ReportPatch(content=validate_content({"format": "markdown", "body": "# Second\n"})),
        "u2",
    )
    _move(reports, p, LifecycleOperation.ARCHIVE, report, 0, "a")
    store = _preservation()
    placed = _hold(reports, p, HoldOperation.PLACE, report, "h", 0, store=store)
    assert placed.preservation is not None
    assert (placed.preservation.object_count, placed.preservation.version_count) == (2, 3)
    assert placed.preservation.head_version_number == 3
    seal = _seal(store, placed)
    assert set(seal) == SEAL_KEYS
    assert seal["schema"] == PRESERVATION_SEAL_SCHEMA
    assert (seal["report_id"], seal["owner_principal_id"]) == (report, p)
    assert seal["hold_event_id"] == placed.event_id
    assert seal["sealed_at"] == "2026-11-06T12:00:00.000000Z"
    assert seal["root"]["head_version_number"] == 3
    assert seal["root"]["lifecycle_state"] == "archived"
    versions = seal["versions"]
    assert [v["version_number"] for v in versions] == [1, 2, 3]
    assert [v["change_kind"] for v in versions] == ["initial", "metadata", "content"]
    # Content reused by the metadata-only update: one preserved object per DISTINCT content.
    assert versions[0]["content_id"] == versions[1]["content_id"] != versions[2]["content_id"]
    assert versions[0]["preservation_object_id"] == versions[1]["preservation_object_id"]
    stored = [reports.read_version(report, principal_id=p, version_number=n) for n in (1, 2, 3)]
    for version, kept in zip(versions, stored, strict=True):
        assert kept is not None
        assert version["manifest"] == json.loads(json.dumps(dict(kept.manifest)))
        assert version["manifest_sha256"] == kept.version.manifest_sha256
    objects = {o["preservation_object_id"]: o for o in seal["objects"]}
    assert len(objects) == 2
    for version, kept in zip(versions, stored, strict=True):
        assert kept is not None
        item = objects[version["preservation_object_id"]]
        assert item["original"] is None and item["encoding"] == "identity"
        assert item["storage_kind"] == "inline"
        decoded = store.objects[item["preservation_object_id"]][ReportContentPart.DECODED]
        assert decoded == kept.content.decoded
        assert item["decoded"] == {
            "sha256": kept.content.decoded_sha256,
            "byte_count": kept.content.decoded_byte_count,
        }
    assert [e["operation"] for e in seal["lifecycle_events"]] == ["archive"]
    event = reports.hold_events(report, principal_id=p)
    assert event is not None
    assert verify_preservation_copy(store, event[0]) == 2


def test_gzip_and_managed_blob_content_preserve_both_parts(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    content = InMemoryReportContentStore()
    raw = b"Synthetic gzip body line.\n" * 8
    inline_gzip = _publish(reports, p, _gzip(raw), key="gz")
    blob_gzip = _publish(
        reports, p, _gzip(raw * 4), key="blob", content_store=content, inline_max_bytes=64
    )
    blob_identity = _publish(
        reports,
        p,
        {"format": "text", "body": "identity blob body " * 10},
        key="blob-id",
        content_store=content,
        inline_max_bytes=64,
    )
    store = _preservation()
    for report, storage in (
        (inline_gzip, "inline"),
        (blob_gzip, "managed_blob"),
        (blob_identity, "managed_blob"),
    ):
        placed = _hold(
            reports,
            p,
            HoldOperation.PLACE,
            report,
            f"h-{report}",
            0,
            store=store,
            content_store=content,
        )
        seal = _seal(store, placed)
        (item,) = seal["objects"]
        assert item["storage_kind"] == storage
        parts = store.objects[item["preservation_object_id"]]
        assert (
            hashlib.sha256(parts[ReportContentPart.DECODED]).hexdigest()
            == (item["decoded"]["sha256"])
        )
        if item["encoding"] == "gzip+base64":
            assert (
                gzip.decompress(parts[ReportContentPart.ORIGINAL])
                == (parts[ReportContentPart.DECODED])
            )
            assert item["original"]["byte_count"] == len(parts[ReportContentPart.ORIGINAL])
        else:
            assert item["original"] is None and ReportContentPart.ORIGINAL not in parts
        (event,) = reports.hold_events(report, principal_id=p) or ()
        assert verify_preservation_copy(store, event) == len(parts)


def test_a_blob_report_without_its_content_store_is_not_held(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    content = InMemoryReportContentStore()
    report = _publish(
        reports,
        p,
        {"format": "text", "body": "blob " * 40},
        content_store=content,
        inline_max_bytes=64,
    )
    store = _preservation()
    with pytest.raises(ReportPreservationError):
        _hold(reports, p, HoldOperation.PLACE, report, "h", 0, store=store, content_store=None)
    (object_id,) = content.objects
    content.objects[object_id][ReportContentPart.DECODED] = b"tampered"
    with pytest.raises(ReportPreservationError):
        _hold(reports, p, HoldOperation.PLACE, report, "h", 0, store=store, content_store=content)
    assert reports.hold_events(report, principal_id=p) == ()
    assert store.puts == 0


# ---- tamper: nothing of the hold is written ------------------------------------------------


class _CorruptsTheSealOnPut(InMemoryReportContentStore):
    def put(self, object_id: str, *, decoded: bytes, original: bytes | None) -> None:
        if decoded.startswith(b'{"hold_event_id"'):
            decoded = decoded.replace(b"place", b"PLACE", 1) + b" "
        super().put(object_id, decoded=decoded, original=original)


class _ReadsBackOtherBytes(InMemoryReportContentStore):
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


class _VerifyMismatches(InMemoryReportContentStore):
    def verify(
        self,
        object_id: str,
        part: ReportContentPart,
        *,
        expected_sha256: str,
        expected_byte_count: int,
    ) -> None:
        raise ReportContentIntegrityError("digest")


class _FailsAfterTheFirstPut(InMemoryReportContentStore):
    def put(self, object_id: str, *, decoded: bytes, original: bytes | None) -> None:
        self.fail_puts = self.puts >= 1
        super().put(object_id, decoded=decoded, original=original)


@pytest.mark.parametrize(
    "store_type",
    [_CorruptsTheSealOnPut, _ReadsBackOtherBytes, _VerifyMismatches, _FailsAfterTheFirstPut],
)
def test_a_copy_that_does_not_verify_writes_no_hold(
    scene: Scene, store_type: type[InMemoryReportContentStore]
) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p)
    store = store_type(ReportContentNamespace.PRESERVATION)
    with pytest.raises(ReportPreservationError):
        _hold(reports, p, HoldOperation.PLACE, report, "h", 0, store=store)
    assert reports.hold_events(report, principal_id=p) == ()
    head = reports.read_version(report, principal_id=p)
    assert head is not None and (head.root.held, head.root.hold_revision) == (False, 0)
    assert store.objects, "what was put before the failure remains (no delete)"
    # The report is not held: trashing proceeds.
    _move(reports, p, LifecycleOperation.DELETE, report, 0, "d")


def test_a_corrupted_preserved_part_fails_reverification(scene: Scene) -> None:
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    report = _publish(reports, p, _gzip(b"Synthetic preserved body.\n" * 4))
    store = _preservation()
    placed = _hold(reports, p, HoldOperation.PLACE, report, "h", 0, store=store)
    (event,) = reports.hold_events(report, principal_id=p) or ()
    assert verify_preservation_copy(store, event) == 2
    seal_id = placed.preservation.seal_object_id if placed.preservation else ""
    (object_id,) = (o for o in store.objects if o != seal_id)
    for part in (ReportContentPart.DECODED, ReportContentPart.ORIGINAL):
        kept = store.objects[object_id][part]
        store.objects[object_id][part] = kept + b"x"
        with pytest.raises(ReportPreservationError):
            verify_preservation_copy(store, event)
        del store.objects[object_id][part]
        with pytest.raises(ReportPreservationError):
            verify_preservation_copy(store, event)
        store.objects[object_id][part] = kept
    assert verify_preservation_copy(store, event) == 2
    store.objects[seal_id][ReportContentPart.DECODED] += b" "
    with pytest.raises(ReportPreservationError):
        verify_preservation_copy(store, event)
    released = _hold(reports, p, HoldOperation.RELEASE, report, "r", 1)
    (_, release_event) = reports.hold_events(report, principal_id=p) or ()
    assert release_event.event_id == released.event_id
    with pytest.raises(ReportPreservationError):
        verify_preservation_copy(store, release_event)


# ---- one content object at a time (finding 1) ----------------------------------------------


Event = tuple[object, ...]


class RecordingPreservationStore(InMemoryReportContentStore):
    """Records `put`, `verify` and `read` in order; a read also records `hold_rows()` then."""

    def __init__(self, log: list[Event], hold_rows: Callable[[], int]) -> None:
        super().__init__(ReportContentNamespace.PRESERVATION)
        self.log = log
        self.hold_rows = hold_rows

    def put(self, object_id: str, *, decoded: bytes, original: bytes | None) -> None:
        self.log.append(("put", object_id))
        super().put(object_id, decoded=decoded, original=original)

    def read(
        self,
        object_id: str,
        part: ReportContentPart,
        *,
        expected_sha256: str,
        expected_byte_count: int,
    ) -> bytes:
        self.log.append(("read", object_id, part.value, self.hold_rows()))
        return super().read(
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
        self.log.append(("verify", object_id, part.value))
        # The parent's `verify` reads through `self.read`; check without recording a read.
        InMemoryReportContentStore.read(
            self,
            object_id,
            part,
            expected_sha256=expected_sha256,
            expected_byte_count=expected_byte_count,
        )


def recording_loads(module: Any, log: list[Event]) -> Callable[..., Any]:  # noqa: ANN401
    """`module.preservation_source`, recording ("load", content_id) before each call."""
    original = module.preservation_source

    def recorded(content_id: str, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        log.append(("load", content_id))
        return original(content_id, *args, **kwargs)

    return recorded


def assert_one_object_at_a_time(log: list[Event], seal: dict[str, Any], seal_id: str) -> None:
    """load(i) -> put(i) -> verify(i, every part) before load(i+1); then the seal, no hold row.

    The objects come in the order the versions first name their content; the
    seal is put after the last object's verification and read back while no
    hold row exists yet.
    """
    order = list(dict.fromkeys(version["content_id"] for version in seal["versions"]))
    objects = {item["content_id"]: item for item in seal["objects"]}
    assert [item["content_id"] for item in seal["objects"]] == order
    expected: list[Event] = []
    for content_id in order:
        item = objects[content_id]
        prv = item["preservation_object_id"]
        expected += [("load", content_id), ("put", prv), ("verify", prv, "decoded")]
        if item["original"] is not None:
            expected.append(("verify", prv, "original"))
    expected += [("put", seal_id), ("read", seal_id, "decoded", 0)]
    assert log == expected


def test_each_content_object_is_loaded_put_and_verified_before_the_next(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    import tests.conftest as fakes

    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    content = InMemoryReportContentStore()
    small = 64
    report = _publish(
        reports,
        p,
        _gzip(b"Synthetic blob gzip line.\n" * 16),
        content_store=content,
        inline_max_bytes=small,
    )
    _update(reports, p, report, 1, ReportPatch(title="Metadata only"), "u1")
    revisions: tuple[tuple[dict[str, Any], int], ...] = (
        ({"format": "markdown", "body": "# Inline\n"}, 262_144),
        ({"format": "text", "body": "identity blob body " * 10}, small),
        (_gzip(b"Inline gzip.\n"), 262_144),
    )
    for expected, (body, inline_max) in enumerate(revisions, start=2):
        _update(
            reports,
            p,
            report,
            expected,
            ReportPatch(content=validate_content(body)),
            f"u{expected}",
            content_store=content,
            inline_max_bytes=inline_max,
        )
    log: list[Event] = []
    store = RecordingPreservationStore(
        log, lambda: len(reports.hold_events(report, principal_id=p) or ())
    )
    monkeypatch.setattr(fakes, "preservation_source", recording_loads(fakes, log))
    placed = _hold(
        reports, p, HoldOperation.PLACE, report, "h", 0, store=store, content_store=content
    )
    assert placed.preservation is not None
    seal = _seal(store, placed)
    kinds = {(o["storage_kind"], o["encoding"]) for o in seal["objects"]}
    assert kinds == {
        ("managed_blob", "gzip+base64"),
        ("inline", "identity"),
        ("managed_blob", "identity"),
        ("inline", "gzip+base64"),
    }
    assert (placed.preservation.object_count, placed.preservation.version_count) == (4, 5)
    assert_one_object_at_a_time(log, seal, placed.preservation.seal_object_id)
    assert len(reports.hold_events(report, principal_id=p) or ()) == 1  # only after the seal


def test_a_placement_holds_one_content_objects_bytes_at_a_time(
    scene: Scene, tmp_path: Path
) -> None:
    """Peak traced memory of a placement over N ~1 MiB blobs stays near ONE object's size.

    tracemalloc (not a weakref counter) because it measures what the finding is
    about -- the bytes a placement allocates -- whichever frame or container would
    keep them; it is deterministic here (single thread, allocations inside the
    traced window only). The sources' bytes are allocated by the blob reads
    inside the window; the fake world's own copies predate it and are not traced.
    """
    reports, p = _GeneralReports(scene.world), scene.principal.principal_id
    root = tmp_path / "report-content"
    root.mkdir()
    content = FilesystemReportContentStore(root, ReportContentNamespace.CONTENT)
    preservation = FilesystemReportContentStore(root, ReportContentNamespace.PRESERVATION)
    size, count = 1 << 20, 4

    def body(i: int) -> dict[str, Any]:
        # gzip, because identity content is bounded at 512 KiB: 1 MiB decoded each,
        # a repeated 16 KiB block of hex digests so the expansion ratio stays ~59 (< 256).
        block = b"".join(
            hashlib.sha256(f"{i}:{n}".encode()).hexdigest().encode() for n in range(256)
        )
        return _gzip((block * (size // len(block) + 1))[:size])

    report = _publish(reports, p, body(0), content_store=content, inline_max_bytes=64)
    for i in range(1, count):
        _update(
            reports,
            p,
            report,
            i,
            ReportPatch(content=validate_content(body(i))),
            f"u{i}",
            content_store=content,
            inline_max_bytes=64,
        )
    gc.collect()
    tracemalloc.start()
    try:
        placed = _hold(
            reports,
            p,
            HoldOperation.PLACE,
            report,
            "h",
            0,
            store=preservation,
            content_store=content,
        )
        _current, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    assert placed.preservation is not None and placed.preservation.object_count == count
    slack = 256 * 1024
    assert peak < 2.5 * size + slack, f"peak {peak} bytes for {count} objects of {size}"
