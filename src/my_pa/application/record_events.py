"""WP-RE-06: the `record_events.list` read core -- visibility, cursor, page.

The Phase 6B handler calls `list_record_events` with the server-resolved
Principal, the composed capability set and the remote grant set (or `None` for
a local caller), and presents the `RecordEventListView` it returns. Nothing here
takes a Principal, a grant, a family visibility or a disclosure mode from the
request: each is re-derived on every call (REQUEST section 5.M), so the cursor
carries no authority and needs no signing secret.

**Visible families** (plan section 6.1). A family is *composed* when one of its
mapped reads (`domain.record_events.RECORD_EVENT_FAMILY_READS`) is in the
composed capability set. A local caller sees every composed family. A remote
caller sees a composed family only when it holds a purpose-aware grant
(`domain.identity.operation.granted_purposes`) on one of that family's composed
reads, and -- for the ten Entity-plane sub-families -- also on the Entity base
read `entities.get` (the OD-10 floor). `effective = visible ∩ requested`.

**The cursor** (OD-1; plan sections 6.2-6.3). A token is canonical JSON
`{"b", "e", "v"}` in unpadded base64url: `b` the 64-hex SHA-256 of the binding
document, `e` the opaque `event_id` of the last consumed event (or `null`), `v`
the cursor version. Decoding runs in the U-002 order, and the order is the
guard:

1. **shape** -- length, strict alphabet, key set, `v == 1`, 64-hex `b`, `e`
   null or `rcev_`-shaped; anything else is `invalid_request(cursor)` and no
   lookup happens;
2. **binding** -- `b` against the binding re-derived for this request; a
   mismatch, including a token issued to another Principal, is
   `conflict(cursor)`, before `e` is looked at;
3. **position** -- only then is `e` looked at: first it must pass the page's
   own visibility predicate (RECR-3: `visible_event_ids` under the effective
   families and, for a remote caller, the withholding of restricted memory and
   capture events), and only then is it resolved inside the caller's partition;
   an `e` that is hidden or does not resolve is `invalid_request(cursor)`, so a
   hidden event is indistinguishable from an unknown one.

**Remote disclosure.** A remote read withholds restricted Relationship Memory
events in SQL (OD-8, in the reader) and nulls every `causation_event_id` that
names an event the caller cannot see (OD-12). A local read does neither.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import re
from collections.abc import Callable, Iterable
from enum import StrEnum
from typing import Any, Final

from my_pa.application.errors import ConflictError, InvalidRequestError, SafeDetail
from my_pa.contracts.ports import RecordEventFeedItem, RecordEventReader
from my_pa.contracts.v1.record_events import RecordEventItemView, RecordEventListView
from my_pa.domain.identity.operation import Capability, granted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.record_events import (
    ENTITY_FLOOR_CAPABILITY,
    ENTITY_FLOOR_FAMILIES,
    RECORD_EVENT_FAMILY_READS,
    RecordEventFamily,
)

__all__ = [
    "DEFAULT_RECORD_EVENT_PAGE_SIZE",
    "MAX_RECORD_EVENT_CURSOR_CHARACTERS",
    "MAX_RECORD_EVENT_PAGE_SIZE",
    "RECORD_EVENT_CURSOR_VERSION",
    "RECORD_EVENT_ORDER",
    "MemoryDisclosure",
    "cursor_binding",
    "decode_cursor",
    "effective_families",
    "encode_cursor",
    "grant_digest",
    "granted_read",
    "list_record_events",
    "memory_disclosure",
    "read_cursor",
    "record_event_page_size",
    "requested_families",
    "visible_families",
]

type Grants = frozenset[tuple[Capability, Purpose | None]]

#: Plan D-02: the published cap. A larger request is clamped, never refused.
MAX_RECORD_EVENT_PAGE_SIZE: Final = 100
#: Plan D-02: the page size when the caller names none.
DEFAULT_RECORD_EVENT_PAGE_SIZE: Final = 50
#: Plan D-03: the feed's own token cap, deliberately not the repository-wide
#: `MAX_CURSOR_CHARACTERS` (a real token is about 150 characters).
MAX_RECORD_EVENT_CURSOR_CHARACTERS: Final = 512
#: REQUEST section 5.M: the token schema version, inside the binding and the token.
RECORD_EVENT_CURSOR_VERSION: Final = 1
#: The one order the feed serves: per-Principal sequence, ascending.
RECORD_EVENT_ORDER: Final = "principal_sequence_asc_v1"

_HEX_DIGEST: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_EVENT_ID: Final = re.compile(r"\Arcev_[A-Za-z0-9]{8,64}\Z")
_BASE64URL: Final = re.compile(r"\A[A-Za-z0-9_-]+\Z")

#: Every capability whose grant can change what a remote caller sees: each
#: family's mapped reads and the Entity floor.
_VISIBILITY_CAPABILITIES: Final[frozenset[Capability]] = frozenset(
    {capability for reads in RECORD_EVENT_FAMILY_READS.values() for capability in reads}
    | {ENTITY_FLOOR_CAPABILITY}
)


class MemoryDisclosure(StrEnum):
    """Whether restricted Relationship Memory events are disclosed (G1-RD-003).

    WP-RE-08 (OD-W8-10): the same choice now also governs restricted Capture
    events; the name is kept rather than widened into a port change.
    """

    INCLUDE_RESTRICTED = "include_restricted"
    EXCLUDE_RESTRICTED = "exclude_restricted"


# --- page size ------------------------------------------------------------------


def record_event_page_size(requested: object, *, published_max: int) -> int:
    """The effective page size: the caller's, clamped to the published cap.

    `None` is the default (50). Anything that is not a positive integer --
    including a boolean -- is `invalid_request(page_size)`. Never above
    `MAX_RECORD_EVENT_PAGE_SIZE` however large the published maximum is.
    """
    ceiling = min(published_max, MAX_RECORD_EVENT_PAGE_SIZE)
    if requested is None:
        return min(DEFAULT_RECORD_EVENT_PAGE_SIZE, ceiling)
    if isinstance(requested, bool) or not isinstance(requested, int) or requested < 1:
        raise InvalidRequestError(SafeDetail.PAGE_SIZE)
    return min(requested, ceiling)


# --- visibility -------------------------------------------------------------------


def granted_read(capability: Capability, grants: Grants) -> bool:
    """Whether a remote grant set admits `capability` for one of its purposes."""
    return bool(granted_purposes(capability, grants))


def memory_disclosure(grants: Grants | None) -> MemoryDisclosure:
    """Local callers see restricted memory events; remote callers never do."""
    return (
        MemoryDisclosure.INCLUDE_RESTRICTED
        if grants is None
        else MemoryDisclosure.EXCLUDE_RESTRICTED
    )


def visible_families(
    available: frozenset[Capability], grants: Grants | None
) -> frozenset[RecordEventFamily]:
    """The families this caller may see, from composition and grants only.

    Local (`grants is None`): every composed family. Remote: a composed family
    one of whose *composed* reads the caller is granted for a permitted purpose,
    plus, for an Entity-plane sub-family, a composed and granted `entities.get`.
    """
    visible: set[RecordEventFamily] = set()
    for family, reads in RECORD_EVENT_FAMILY_READS.items():
        composed = reads & available
        if not composed:
            continue
        if grants is None:
            visible.add(family)
            continue
        if not any(granted_read(capability, grants) for capability in composed):
            continue
        if family in ENTITY_FLOOR_FAMILIES and not (
            ENTITY_FLOOR_CAPABILITY in available and granted_read(ENTITY_FLOOR_CAPABILITY, grants)
        ):
            continue
        visible.add(family)
    return frozenset(visible)


def requested_families(value: object) -> tuple[RecordEventFamily, ...] | None:
    """The caller's family narrowing, validated; `None` means no narrowing.

    Empty, an unknown family or a repeated one is `invalid_request`.
    """
    if value is None:
        return None
    if not isinstance(value, (tuple, list)) or not value:
        raise InvalidRequestError(SafeDetail.RECORD_FAMILIES)
    families: list[RecordEventFamily] = []
    for item in value:
        try:
            families.append(RecordEventFamily(item))
        except ValueError:
            families = []
            break
    if len(families) != len(value) or len(set(families)) != len(families):
        raise InvalidRequestError(SafeDetail.RECORD_FAMILIES)
    return tuple(families)


def effective_families(
    visible: frozenset[RecordEventFamily], requested: tuple[RecordEventFamily, ...] | None
) -> frozenset[RecordEventFamily]:
    """`visible ∩ requested`; a requested family that is not visible is omitted."""
    if requested is None:
        return visible
    return visible & frozenset(requested)


# --- binding and cursor ---------------------------------------------------------


def _canonical(document: object) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode(
        "ascii"
    )


def grant_digest(grants: Grants | None) -> str | None:
    """SHA-256 over the sorted grants that determine visibility; `None` locally.

    The list grant plus every grant on a family's mapped read or the Entity
    floor (R-002). Any change to that set changes the digest, so a prior cursor
    is a conflict (RE-AC-069).
    """
    if grants is None:
        return None
    relevant = sorted(
        (capability.value, None if purpose is None else purpose.value)
        for capability, purpose in grants
        if capability in _VISIBILITY_CAPABILITIES or capability is Capability.RECORD_EVENTS_LIST
    )
    return hashlib.sha256(_canonical([list(pair) for pair in relevant])).hexdigest()


def cursor_binding(
    *,
    principal_id: str,
    visible: frozenset[RecordEventFamily],
    requested: tuple[RecordEventFamily, ...] | None,
    page_size: int,
    disclosure: MemoryDisclosure,
    grants_digest: str | None,
) -> str:
    """The 64-hex digest a token must carry to belong to this request (plan 6.2)."""
    document: dict[str, Any] = {
        "cursor_version": RECORD_EVENT_CURSOR_VERSION,
        "grant_digest": grants_digest,
        "memory_disclosure": disclosure.value,
        "order": RECORD_EVENT_ORDER,
        "page_size": page_size,
        "principal_id": principal_id,
        "requested_families": (
            None if requested is None else sorted(family.value for family in requested)
        ),
        "visible_families": sorted(family.value for family in visible),
    }
    return hashlib.sha256(_canonical(document)).hexdigest()


def encode_cursor(binding: str, event_id: str | None) -> str:
    """One opaque token resuming after `event_id` (or from the start) under `binding`."""
    payload = _canonical({"b": binding, "e": event_id, "v": RECORD_EVENT_CURSOR_VERSION})
    return base64.urlsafe_b64encode(payload).decode("ascii").rstrip("=")


def read_cursor(token: object) -> tuple[str, str | None] | None:
    """Step 1, shape only: `(b, e)` for a well-formed token, else `None`. No lookup."""
    if (
        not isinstance(token, str)
        or not 1 <= len(token) <= MAX_RECORD_EVENT_CURSOR_CHARACTERS
        or not _BASE64URL.fullmatch(token)
    ):
        return None
    padded = token + "=" * (-len(token) % 4)
    try:
        raw = base64.b64decode(padded.encode("ascii"), altchars=b"-_", validate=True)
        decoded = json.loads(raw)
    except (binascii.Error, UnicodeDecodeError, ValueError):
        return None
    if not isinstance(decoded, dict) or set(decoded) != {"b", "e", "v"}:
        return None
    version, binding, event_id = decoded["v"], decoded["b"], decoded["e"]
    if type(version) is not int or version != RECORD_EVENT_CURSOR_VERSION:
        return None
    if not isinstance(binding, str) or not _HEX_DIGEST.fullmatch(binding):
        return None
    if event_id is not None and (
        not isinstance(event_id, str) or not _EVENT_ID.fullmatch(event_id)
    ):
        return None
    return binding, event_id


def decode_cursor(token: str | None, binding: str, resolve: Callable[[str], int | None]) -> int:
    """The internal position to resume after, in the U-002 order.

    `None` starts from the beginning. Shape, then binding, then -- only after a
    binding match -- `resolve(e)` inside the caller's partition.
    """
    if token is None:
        return 0
    read = read_cursor(token)
    if read is None:
        raise InvalidRequestError(SafeDetail.CURSOR)
    carried, event_id = read
    if carried != binding:
        raise ConflictError(SafeDetail.CURSOR)
    if event_id is None:
        return 0
    position = resolve(event_id)
    if position is None:
        raise InvalidRequestError(SafeDetail.CURSOR)
    return position


# --- causation -------------------------------------------------------------------


def _visible_causes(
    reader: RecordEventReader,
    *,
    principal_id: str,
    items: Iterable[RecordEventFeedItem],
    families: frozenset[RecordEventFamily],
) -> frozenset[str]:
    """Which causes a remote caller may see: in this page, or found by one probe."""
    listed = tuple(items)
    in_page = frozenset(item.event_id for item in listed)
    elsewhere = frozenset(
        item.causation_event_id
        for item in listed
        if item.causation_event_id is not None and item.causation_event_id not in in_page
    )
    return in_page | reader.visible_event_ids(
        principal_id=principal_id,
        event_ids=elsewhere,
        families=families,
        include_restricted_memory=False,
    )


def _view(item: RecordEventFeedItem, *, causation_event_id: str | None) -> RecordEventItemView:
    return RecordEventItemView(
        event_id=item.event_id,
        record_family=item.record_family,
        record_id=item.record_id,
        event_kind=item.event_kind,
        record_version=item.record_version,
        changed_fields=item.changed_fields,
        source_capability=item.source_capability,
        source_receipt_id=item.source_receipt_id,
        actor_class=item.actor_class,
        authority=item.authority,
        occurred_at=item.occurred_at,
        recorded_at=item.recorded_at,
        causation_event_id=causation_event_id,
        routing_family=item.routing_family,
        routing_record_id=item.routing_record_id,
    )


def _anchor_position(
    reader: RecordEventReader,
    *,
    principal_id: str,
    event_id: str,
    families: frozenset[RecordEventFamily],
    include_restricted_memory: bool,
) -> int | None:
    """Step 3 (RECR-3): the anchor's position, only if this page would show it.

    The visibility check is the same predicate the page applies, asked through
    the reader's existing probe; a hidden anchor answers `None`, exactly as an
    unknown one does, and is never resolved.
    """
    visible = reader.visible_event_ids(
        principal_id=principal_id,
        event_ids=frozenset({event_id}),
        families=families,
        include_restricted_memory=include_restricted_memory,
    )
    if event_id not in visible:
        return None
    return reader.resolve_position(principal_id=principal_id, event_id=event_id)


# --- the use case ----------------------------------------------------------------


def list_record_events(
    reader: RecordEventReader,
    *,
    principal_id: str,
    available_capabilities: frozenset[Capability],
    capability_grants: Grants | None,
    record_families: object,
    page_size: int,
    cursor: str | None,
) -> RecordEventListView:
    """One `record_events.list` page for the server-resolved `principal_id`.

    `page_size` is the effective size (`record_event_page_size`). The caller
    (the Phase 6B handler) has already refused a remote caller without the list
    grant. Validation order: family narrowing, then the cursor in the U-002
    order; the page and its watermark come from one reader statement.
    """
    if isinstance(page_size, bool) or not 1 <= page_size <= MAX_RECORD_EVENT_PAGE_SIZE:
        raise InvalidRequestError(SafeDetail.PAGE_SIZE)
    requested = requested_families(record_families)
    visible = visible_families(available_capabilities, capability_grants)
    effective = effective_families(visible, requested)
    disclosure = memory_disclosure(capability_grants)
    include_restricted = disclosure is MemoryDisclosure.INCLUDE_RESTRICTED
    binding = cursor_binding(
        principal_id=principal_id,
        visible=visible,
        requested=requested,
        page_size=page_size,
        disclosure=disclosure,
        grants_digest=grant_digest(capability_grants),
    )
    after = decode_cursor(
        cursor,
        binding,
        lambda event_id: _anchor_position(
            reader,
            principal_id=principal_id,
            event_id=event_id,
            families=effective,
            include_restricted_memory=include_restricted,
        ),
    )
    if effective:
        page = reader.page(
            principal_id=principal_id,
            after_sequence=after,
            families=effective,
            include_restricted_memory=include_restricted,
            limit=page_size,
        )
        rows, high_watermark = page.rows, page.high_watermark_event_id
    else:
        rows, high_watermark = (), None
    has_more = len(rows) > page_size
    items = rows[:page_size]
    if include_restricted:
        causes = frozenset(
            item.causation_event_id for item in items if item.causation_event_id is not None
        )
    else:
        causes = _visible_causes(reader, principal_id=principal_id, items=items, families=effective)
    return RecordEventListView(
        events=tuple(
            _view(
                item,
                causation_event_id=(
                    item.causation_event_id if item.causation_event_id in causes else None
                ),
            )
            for item in items
        ),
        next_cursor=encode_cursor(binding, items[-1].event_id) if has_more else None,
        high_watermark_cursor=encode_cursor(binding, high_watermark),
        visible_families=tuple(sorted(visible, key=lambda family: family.value)),
    )
