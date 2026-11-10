"""The sealed preservation copy a legal hold is placed on (Reports Modernization WP05b B5).

`place_hold` verifies, under the report root's `FOR UPDATE` lock, every
version (as a read verifies it) and gathers every lifecycle event of the
report, then hands the versions' records and manifests, the events and a
`load` callable to `seal_preservation_copy`, which writes the copy into the
preservation namespace of the report content store and proves it before
anything of the hold is written. It works ONE distinct content object at a
time (finding 1: a placement's memory is bounded by its largest object, not
by the report), in the order the versions first name them:

1. `load(content_id)` returns that object's verified bytes (inline: recomputed
   from its row; `managed_blob`: read verified from the content store);
2. one preservation object (a fresh `grprv_` id) is put: its decoded part is
   the verified decoded bytes, its original part the verified uploaded gzip
   bytes (none for identity content);
3. **verification**: every part of that preserved object is `verify`-ed
   against the source digests and sizes;
4. the bytes are released -- only the object's facts (`PreservedObject`) are
   kept -- before the next object is loaded.

After the last object the seal (the canonical JSON of
`preservation_seal_document`, decoded part only, under its own fresh `grprv_`
id) is put and read back, and must equal the bytes sealed; only then does this
return, so only then is the hold row written.

Every store failure, a missing or mismatched part or a seal that does not read
back byte-equal is `ReportPreservationError`; the caller then writes no hold
row. The store has no delete: the objects already put remain (orphans), and
nothing here removes one.

Shared by the SQL repository and the in-memory fake, so both seal alike.
Nothing here returns or logs content, a path or a digest value.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
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
from my_pa.domain.reports.records import ReportVersionRecord
from my_pa.domain.reports.vocabulary import ContentEncoding, StorageKind
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "PreservationLoader",
    "PreservationSource",
    "preservation_source",
    "seal_preservation_copy",
]


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


#: Returns the verified `PreservationSource` of one content id, read when called
#: (never cached), or raises `ReportPreservationError`.
PreservationLoader = Callable[[str], PreservationSource]


def _read(
    store: ReportContentStore, content_id: str, part: ReportContentPart, sha256: str, size: int
) -> bytes:
    try:
        return store.read(content_id, part, expected_sha256=sha256, expected_byte_count=size)
    except ReportContentStoreError:
        raise ReportPreservationError() from None


def preservation_source(
    content_id: str,
    storage_kind: StorageKind,
    content: ReportContent,
    content_store: ReportContentStore | None,
) -> PreservationSource:
    """The verified bytes of one content object.

    Inline content was recomputed from its row by the caller's verified read;
    a `managed_blob` one (facts only there) is read from `content_store`,
    verified against its row's digests and sizes. An unreadable, absent or
    mismatched blob, or a blob with no store, is `ReportPreservationError`.
    """
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
            content_id,
            ReportContentPart.DECODED,
            content.decoded_sha256,
            content.decoded_byte_count,
        )
        original = (
            _read(
                content_store,
                content_id,
                ReportContentPart.ORIGINAL,
                content.original_sha256,
                content.original_byte_count,
            )
            if gzip
            else None
        )
    return PreservationSource(
        content_id=content_id,
        format=content.format.value,
        encoding=content.encoding.value,
        storage_kind=storage_kind.value,
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


def _verify_object(store: ReportContentStore, item: PreservedObject) -> None:
    """Prove one preserved object right after its put: every part against the source digests."""
    try:
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
    except ReportContentStoreError:
        raise ReportPreservationError() from None


def _verify_seal(store: ReportContentStore, seal_id: str, seal: bytes) -> None:
    """The seal read back must equal the bytes sealed."""
    try:
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


def _preserve_object(
    store: ReportContentStore, content_id: str, load: PreservationLoader
) -> PreservedObject:
    """Load, put and verify ONE content object; only its facts outlive this call.

    The bytes live in this frame alone (no list or dict keeps them), so they
    are released when it returns, before the next object is loaded.
    """
    source = load(content_id)
    if (
        source.content_id != content_id
        or hashlib.sha256(source.decoded).hexdigest() != source.decoded_sha256
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
    _put(store, item.preservation_object_id, decoded=source.decoded, original=source.original)
    del source
    _verify_object(store, item)
    return item


def seal_preservation_copy(
    preservation_store: ReportContentStore,
    *,
    root: PreservedRoot,
    hold_event_id: str,
    sealed_at: datetime,
    versions: Sequence[ReportVersionRecord],
    manifests: Sequence[Mapping[str, Any]],
    lifecycle_events: Sequence[PreservedLifecycleEvent],
    load: PreservationLoader,
) -> HoldPreservation:
    """Write and verify one placement's preservation copy; its facts for the hold row.

    `versions` is every (already verified) version ascending and `manifests`
    their stored manifests, in the same order. Each DISTINCT content object,
    in the order the versions first name it, is loaded through `load`, put
    and verified before the next is loaded; then the seal is put and read
    back. Any failure is `ReportPreservationError`.
    """
    if not versions or len(versions) != len(manifests):
        raise ReportPreservationError()
    preserved: dict[str, PreservedObject] = {}
    for version in versions:
        if version.content_id not in preserved:  # one preservation object per DISTINCT object
            preserved[version.content_id] = _preserve_object(
                preservation_store, version.content_id, load
            )
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
                    for version, manifest in zip(versions, manifests, strict=True)
                ],
                objects=objects,
                lifecycle_events=lifecycle_events,
            )
        )
    except (KeyError, TypeError, ValueError):
        raise ReportPreservationError() from None
    seal_id = issue_identifier(IdKind.REPORT_PRESERVATION_OBJECT)
    _put(preservation_store, seal_id, decoded=seal, original=None)
    _verify_seal(preservation_store, seal_id, seal)
    return HoldPreservation(
        seal_object_id=seal_id,
        seal_sha256=hashlib.sha256(seal).hexdigest(),
        seal_byte_count=len(seal),
        object_count=len(objects),
        version_count=len(versions),
        head_version_number=root.head_version_number,
        lifecycle_revision=root.lifecycle_revision,
    )
