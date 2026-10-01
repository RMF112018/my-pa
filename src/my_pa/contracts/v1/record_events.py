"""The public shapes of a `record_events.list` answer (WP-RE-06, plan section 6.5).

Two models: `RecordEventItemView`, one committed Record Event as a caller sees
it, and `RecordEventListView`, the page around it.

**What an item cannot carry is the point of it.**

*No Principal.* The caller reads only its own partition; echoing a
`principal_id` would make every item a place another Principal's identifier
could appear if a filter ever broke.

*No classification and no correlation.* Package section 12 omits both: the
classification is a disclosure decision the server makes, not a fact the
caller is given, and the correlation identifier belongs to the request that
wrote the event.

*No sequence number* (OD-1). Sequences are gap-free per Principal, so a public
number would let a remote caller count the events withheld from it
(G1-RD-001). The order is still the sequence; the cursor is anchored on the
opaque `event_id`.

**What an item adds: a routing reference** (RECR-1). For the families whose
`record_id` no mapped read accepts as a key (`RECORD_EVENT_ROUTING`), an item
carries `routing_family` and `routing_record_id`: the kind and opaque id of the
record to reread it through -- the comment's Task, the category's Project, the
Entity-plane child's owning Entity. Both are metadata: an identifier, never a
value, a name or narrative, and they exist only on an item the caller already
sees, so they inherit its grant intersection and remote withholding. They name
the record's *current* owner, read at list time. Both are set, or both are
`null`: `null` on a routed family means "not currently resolvable", for example
an observation with no Entity, and a consumer treats it as a tombstone.
"""

from __future__ import annotations

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.record_events import (
    RECEIPT_IDENTIFIER_PATTERN,
    RECORD_EVENT_ROUTING,
    RecordEventActorClass,
    RecordEventAuthority,
    RecordEventFamily,
    RecordEventKind,
    validate_changed_fields,
    validate_source_capability,
)

__all__ = ["RecordEventItemView", "RecordEventListView"]

#: The identifier kind each routing family's id must carry.
_ROUTING_KINDS: dict[RecordEventFamily, IdKind] = {
    RecordEventFamily.TASK: IdKind.TASK,
    RecordEventFamily.PROJECT: IdKind.PROJECT,
    RecordEventFamily.ENTITY: IdKind.ENTITY,
}


class RecordEventItemView(StrictModel):
    """One committed Record Event, exactly as `record_events.list` discloses it."""

    event_id: str
    record_family: RecordEventFamily
    record_id: str
    event_kind: RecordEventKind
    record_version: int = Field(ge=1)
    changed_fields: tuple[str, ...]
    source_capability: str
    source_receipt_id: str | None = None
    actor_class: RecordEventActorClass
    authority: RecordEventAuthority | None = None
    occurred_at: UtcDatetime
    recorded_at: UtcDatetime
    causation_event_id: str | None = None
    routing_family: RecordEventFamily | None = None
    routing_record_id: str | None = None

    @model_validator(mode="after")
    def _check(self) -> RecordEventItemView:
        validate_identifier(self.event_id, IdKind.RECORD_EVENT)
        if self.causation_event_id is not None:
            validate_identifier(self.causation_event_id, IdKind.RECORD_EVENT)
        if not RECEIPT_IDENTIFIER_PATTERN.fullmatch(self.record_id):
            raise ValueError("record_id is not an opaque identifier")
        if self.source_receipt_id is not None and not RECEIPT_IDENTIFIER_PATTERN.fullmatch(
            self.source_receipt_id
        ):
            raise ValueError("source_receipt_id is not an opaque identifier")
        validate_changed_fields(self.changed_fields)
        validate_source_capability(self.source_capability)
        self._check_routing()
        return self

    def _check_routing(self) -> None:
        """RECR-1: both routing fields or neither, and only as the table says."""
        if (self.routing_family is None) != (self.routing_record_id is None):
            raise ValueError("routing_family and routing_record_id are set together")
        if self.routing_family is None or self.routing_record_id is None:
            return
        if RECORD_EVENT_ROUTING.get(self.record_family) is not self.routing_family:
            raise ValueError("this record family carries no such routing reference")
        validate_identifier(self.routing_record_id, _ROUTING_KINDS[self.routing_family])


class RecordEventListView(StrictModel):
    """One `record_events.list` page.

    `next_cursor` is present only when there is more; `high_watermark_cursor`
    is always present and resumes after the greatest effective visible event at
    the snapshot that produced the page. `visible_families` is the
    grant- and composition-derived set, sorted -- never a data-dependent fact.
    """

    events: tuple[RecordEventItemView, ...]
    next_cursor: str | None = None
    high_watermark_cursor: str
    visible_families: tuple[RecordEventFamily, ...]
