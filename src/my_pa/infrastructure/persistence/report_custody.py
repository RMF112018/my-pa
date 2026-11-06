"""The sealed preservation copy a legal hold is placed on (Reports Modernization WP05b B5).

`place_hold` gathers, under the report root's `FOR UPDATE` lock, every version
(verified as a read verifies it), every distinct content object and every
lifecycle event of the report, and hands them to `seal_preservation_copy`,
which writes the copy into the preservation namespace of the report content
store and proves it before anything of the hold is written:

1. one preservation object (a fresh `grprv_` id) per distinct content object:
   its decoded part is the verified decoded bytes, its original part the
   verified uploaded gzip bytes (none for identity content);
2. the seal: the canonical JSON of `preservation_seal_document` under its own
   fresh `grprv_` id (decoded part only);
3. **verification** (`_verify_copy`): every part of every preserved object is
   `verify`-ed against the source digests and sizes, and the seal is read back
   and must equal the bytes sealed.

Every store failure, a missing or mismatched part or a seal that does not read
back byte-equal is `ReportPreservationError`; the caller then writes no hold
row. The store has no delete: the objects already put remain (orphans), and
nothing here removes one.

Shared by the SQL repository and the in-memory fake, so both seal alike.
Nothing here returns or logs content, a path or a digest value.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from my_pa.contracts.ports import (
    ReportContentPart,
    ReportContentStore,
    ReportContentStoreError,
    ReportPreservationError,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.reports.content import ReportContent
from my_pa.domain.reports.custody import (
    HoldPreservation,
    PreservedLifecycleEvent,
    PreservedObject,
    PreservedRoot,
    PreservedVersion,
    preservation_seal,
    preservation_seal_document,
)
from my_pa.domain.reports.records import ReportVersionRecord, StoredReportVersion
from my_pa.domain.reports.vocabulary import ContentEncoding
from my_pa.domain.source.registry import issue_identifier

__all__ = ["PreservationSource", "preservation_source", "seal_preservation_copy"]


@dataclass(frozen=True, slots=True)
class PreservationSource:
    """One distinct content object's verified bytes and the facts they were verified against."""

    content_id: str
    format: str
    encoding: str
    storage_kind: str
    decoded: bytes
    decoded_sha256: str
    decoded_byte_count: int
    #: The uploaded gzip bytes and their facts; all `None` for identity content.
    original: bytes | None
    original_sha256: str | None
    original_byte_count: int | None


def _read(
    store: ReportContentStore, content_id: str, part: ReportContentPart, sha256: str, size: int
) -> bytes:
    try:
        return store.read(content_id, part, expected_sha256=sha256, expected_byte_count=size)
    except ReportContentStoreError:
        raise ReportPreservationError() from None


def preservation_source(
    stored: StoredReportVersion, content_store: ReportContentStore | None
) -> PreservationSource:
    """The verified bytes of a version's content object.

    Inline content was recomputed from its row by the version read; a
    `managed_blob` one (facts only there) is read from `content_store`,
    verified against its row's digests and sizes. An unreadable, absent or
    mismatched blob, or a blob with no store, is `ReportPreservationError`.
    """
    content: ReportContent = stored.content
    gzip = content.encoding is ContentEncoding.GZIP_BASE64
    if content.materialized:
        decoded = content.decoded
        original = content.original if gzip else None
        if gzip and original is None:
            raise ReportPreservationError()
    else:
        if content_store is None:
            raise ReportPreservationError()
        decoded = _read(
            content_store,
            stored.content_id,
            ReportContentPart.DECODED,
            content.decoded_sha256,
            content.decoded_byte_count,
        )
        original = (
            _read(
                content_store,
                stored.content_id,
                ReportContentPart.ORIGINAL,
                content.original_sha256,
                content.original_byte_count,
            )
            if gzip
            else None
        )
    return PreservationSource(
        content_id=stored.content_id,
        format=content.format.value,
        encoding=content.encoding.value,
        storage_kind=stored.storage_kind.value,
        decoded=decoded,
        decoded_sha256=content.decoded_sha256,
        decoded_byte_count=content.decoded_byte_count,
        original=original,
        original_sha256=content.original_sha256 if gzip else None,
        original_byte_count=content.original_byte_count if gzip else None,
    )


def _put(
    store: ReportContentStore, object_id: str, *, decoded: bytes, original: bytes | None
) -> None:
    try:
        store.put(object_id, decoded=decoded, original=original)
    except ReportContentStoreError:
        raise ReportPreservationError() from None


def _verify_copy(
    store: ReportContentStore,
    objects: Sequence[PreservedObject],
    seal_id: str,
    seal: bytes,
) -> None:
    """Prove the copy before any hold row: every part verified, the seal read back equal."""
    try:
        for item in objects:
            store.verify(
                item.preservation_object_id,
                ReportContentPart.DECODED,
                expected_sha256=item.decoded_sha256,
                expected_byte_count=item.decoded_byte_count,
            )
            if item.original_sha256 is not None and item.original_byte_count is not None:
                store.verify(
                    item.preservation_object_id,
                    ReportContentPart.ORIGINAL,
                    expected_sha256=item.original_sha256,
                    expected_byte_count=item.original_byte_count,
                )
        read_back = store.read(
            seal_id,
            ReportContentPart.DECODED,
            expected_sha256=hashlib.sha256(seal).hexdigest(),
            expected_byte_count=len(seal),
        )
    except ReportContentStoreError:
        raise ReportPreservationError() from None
    if read_back != seal:
        raise ReportPreservationError()


def seal_preservation_copy(
    preservation_store: ReportContentStore,
    *,
    root: PreservedRoot,
    hold_event_id: str,
    sealed_at: datetime,
    versions: Sequence[tuple[ReportVersionRecord, PreservationSource]],
    manifests: Sequence[Mapping[str, Any]],
    lifecycle_events: Sequence[PreservedLifecycleEvent],
) -> HoldPreservation:
    """Write and verify one placement's preservation copy; its facts for the hold row.

    `versions` is every version ascending with its content's verified source
    and `manifests` their stored manifests, in the same order.
    """
    if not versions or len(versions) != len(manifests):
        raise ReportPreservationError()
    preserved: dict[str, PreservedObject] = {}
    for _version, source in versions:
        if source.content_id in preserved:
            continue  # one preservation object per DISTINCT content object
        if (
            hashlib.sha256(source.decoded).hexdigest() != source.decoded_sha256
            or len(source.decoded) != source.decoded_byte_count
        ):
            raise ReportPreservationError()
        item = PreservedObject(
            preservation_object_id=issue_identifier(IdKind.REPORT_PRESERVATION_OBJECT),
            content_id=source.content_id,
            format=source.format,
            encoding=source.encoding,
            storage_kind=source.storage_kind,
            decoded_sha256=source.decoded_sha256,
            decoded_byte_count=source.decoded_byte_count,
            original_sha256=source.original_sha256,
            original_byte_count=source.original_byte_count,
        )
        _put(
            preservation_store,
            item.preservation_object_id,
            decoded=source.decoded,
            original=source.original,
        )
        preserved[source.content_id] = item
    objects = tuple(preserved.values())
    try:
        seal = preservation_seal(
            preservation_seal_document(
                root=root,
                hold_event_id=hold_event_id,
                sealed_at=sealed_at,
                versions=[
                    PreservedVersion(
                        version_id=version.version_id,
                        version_number=version.version_number,
                        change_kind=version.change_kind.value,
                        recorded_at=version.recorded_at,
                        manifest_sha256=version.manifest_sha256,
                        manifest=manifest,
                        content_id=version.content_id,
                        preservation_object_id=preserved[version.content_id].preservation_object_id,
                    )
                    for (version, _source), manifest in zip(versions, manifests, strict=True)
                ],
                objects=objects,
                lifecycle_events=lifecycle_events,
            )
        )
    except (KeyError, TypeError, ValueError):
        raise ReportPreservationError() from None
    seal_id = issue_identifier(IdKind.REPORT_PRESERVATION_OBJECT)
    _put(preservation_store, seal_id, decoded=seal, original=None)
    _verify_copy(preservation_store, objects, seal_id, seal)
    return HoldPreservation(
        seal_object_id=seal_id,
        seal_sha256=hashlib.sha256(seal).hexdigest(),
        seal_byte_count=len(seal),
        object_count=len(objects),
        version_count=len(versions),
        head_version_number=root.head_version_number,
        lifecycle_revision=root.lifecycle_revision,
    )
