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
"""

from __future__ import annotations

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.record_events import (
    RECEIPT_IDENTIFIER_PATTERN,
    RecordEventActorClass,
    RecordEventAuthority,
    RecordEventFamily,
    RecordEventKind,
    validate_changed_fields,
    validate_source_capability,
)

__all__ = ["RecordEventItemView", "RecordEventListView"]


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
        return self


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
