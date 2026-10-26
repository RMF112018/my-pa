"""The public shapes of an `issues.timeline` answer (record lineage S3 contract section 7.3).

`TimelineEntryView` is one entry of either plane, `TimelineNativeView` a native
entry's Record Event and `IssueTimelineView` one page. Kept beside
`contracts.v1.issues` rather than in it, so the S1 Issue shapes stay free of
the Record Event vocabulary a native entry names (the S1 scope guard,
`tests/architecture/test_record_lineage_s1_scope.py`).

**What these models cannot carry is the point of them.** No field value of a
native record (a native entry names the event's own columns, and only a
Constraint event carries its stored revision snapshot's `recorded_fields`), no
Project name, no evidence anchor, no count and no `principal_id`.

**S3.1 labels** (S3.1 contract section 7.6): a `project_link`, `membership`,
`association`, `handoff` or `handoff_correction` entry states its row's
`acceptance_basis` and `user_directed_claim`, and `asserting_client_id` (the
writing OAuth client, `null` for the human channel, an unstamped local caller
and every remote reader); the 3 keys are `null` on an `issue_revision` and a
`native_event`. `action` may name `confirm`.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import Field, model_validator

from my_pa.contracts.v1.base import StrictModel
from my_pa.contracts.v1.issues import HandoffHolderView
from my_pa.contracts.v1.record_lineage import ASSERTING_CLIENT_ID, RecordRefView
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.lineage.cursor import instant_token
from my_pa.domain.lineage.vocabulary import (
    AcceptanceBasis,
    HandoffCorrectionAction,
    IssueProjectMembershipState,
    LineageCompleteness,
    LinkLifecycleState,
    MemberRole,
    RelationType,
    TimelineEntryKind,
)
from my_pa.domain.record_events import RecordEventFamily, RecordEventKind

__all__ = [
    "TIMELINE_ENTRY_ID_KINDS",
    "TIMELINE_KIND_RANKS",
    "TIMELINE_LABELLED_KINDS",
    "TIMELINE_PLANE_RANKS",
    "IssueTimelineView",
    "TimelineEntryView",
    "TimelineNativeView",
]


#: Section 7.3: the order rank of each entry kind (the table order).
TIMELINE_KIND_RANKS: dict[TimelineEntryKind, int] = {
    kind: rank for rank, kind in enumerate(TimelineEntryKind)
}
#: Section 7.3: the order rank of each plane.
TIMELINE_PLANE_RANKS: dict[str, int] = {"lineage": 0, "native": 1}
#: The identifier kind of each entry kind's `entry_id` (the row's own identifier).
TIMELINE_ENTRY_ID_KINDS: dict[TimelineEntryKind, IdKind] = {
    TimelineEntryKind.ISSUE_REVISION: IdKind.ISSUE_REVISION,
    TimelineEntryKind.PROJECT_LINK: IdKind.ISSUE_PROJECT_MEMBERSHIP_EVENT,
    TimelineEntryKind.MEMBERSHIP: IdKind.RECORD_LINK_REVISION,
    TimelineEntryKind.ASSOCIATION: IdKind.RECORD_LINK_REVISION,
    TimelineEntryKind.HANDOFF: IdKind.ISSUE_HANDOFF,
    TimelineEntryKind.HANDOFF_CORRECTION: IdKind.ISSUE_HANDOFF_CORRECTION,
    TimelineEntryKind.NATIVE_EVENT: IdKind.RECORD_EVENT,
}

#: S3.1 section 7.6: the kinds whose entries carry the provenance labels.
TIMELINE_LABELLED_KINDS: frozenset[TimelineEntryKind] = frozenset(
    {
        TimelineEntryKind.PROJECT_LINK,
        TimelineEntryKind.MEMBERSHIP,
        TimelineEntryKind.ASSOCIATION,
        TimelineEntryKind.HANDOFF,
        TimelineEntryKind.HANDOFF_CORRECTION,
    }
)


class TimelineNativeView(StrictModel):
    """A native entry's Record Event (S3 section 7.3): its own columns, never a field value."""

    record_family: RecordEventFamily
    record_id: str
    event_kind: RecordEventKind
    record_version: int = Field(ge=1)
    changed_fields: tuple[str, ...]
    source_capability: str


class TimelineEntryView(StrictModel):
    """One `issues.timeline` entry (S3 section 7.3).

    Every entry carries every key; a key that is not its kind's is `null`.
    `entry_id` is the row's own identifier; `at` is the current effective time
    of a `handoff`, the `occurred_at` of a `native_event`, and the
    `recorded_at` of every other kind. A lineage entry's values are the
    recorded ones (`historical_fields_partial` false); a native entry carries
    no former or current field value (`true`), except a Constraint event whose
    stored revision snapshot gives `recorded_fields`. A Project link entry never
    names its Project; no entry carries an evidence anchor.
    """

    entry_id: str
    kind: TimelineEntryKind
    plane: Literal["lineage", "native"]
    at: datetime
    recorded_at: datetime
    subject: RecordRefView | None
    action: str
    historical_fields_partial: bool
    # issue_revision
    issue_version: int | None = None
    state: str | None = None
    title: str | None = None
    closed_at: datetime | None = None
    outcome: str | None = None
    # project_link
    project_id: str | None = None
    membership_revision_no: int | None = None
    link_state: IssueProjectMembershipState | None = None
    # membership, association
    link_id: str | None = None
    revision_no: int | None = None
    relation_type: RelationType | None = None
    member_role: MemberRole | None = None
    lifecycle_state: LinkLifecycleState | None = None
    from_ref: RecordRefView | None = None
    to_ref: RecordRefView | None = None
    # handoff, handoff_correction
    handoff_id: str | None = None
    commitment_id: str | None = None
    sequence_no: int | None = None
    from_holder: HandoffHolderView | None = None
    to_holder: HandoffHolderView | None = None
    voided: bool | None = None
    correction_id: str | None = None
    correction_action: HandoffCorrectionAction | None = None
    corrected_effective_at: datetime | None = None
    # native_event
    native: TimelineNativeView | None = None
    recorded_fields: dict[str, Any] | None = None
    # S3.1: project_link, membership, association, handoff, handoff_correction
    acceptance_basis: AcceptanceBasis | None = None
    user_directed_claim: bool | None = None
    asserting_client_id: str | None = ASSERTING_CLIENT_ID

    @model_validator(mode="after")
    def _check(self) -> TimelineEntryView:
        validate_identifier(self.entry_id, TIMELINE_ENTRY_ID_KINDS[self.kind])
        native = self.kind is TimelineEntryKind.NATIVE_EVENT
        if native is not (self.plane == "native") or native is (self.native is None):
            raise ValueError("a native entry, and only one, is of the native plane")
        if not native and (self.historical_fields_partial or self.recorded_fields is not None):
            raise ValueError("a lineage entry carries its recorded values")
        if native and self.historical_fields_partial is (self.recorded_fields is not None):
            raise ValueError("a native entry is partial exactly when it records no fields")
        for instant in (self.at, self.recorded_at, self.closed_at, self.corrected_effective_at):
            if instant is not None and instant.tzinfo is None:
                raise ValueError("a timeline instant is aware")
        labelled = self.kind in TIMELINE_LABELLED_KINDS
        if labelled is (self.acceptance_basis is None) or labelled is (
            self.user_directed_claim is None
        ):
            raise ValueError("a fact entry, and only one, carries its provenance labels")
        if not labelled and self.asserting_client_id is not None:
            raise ValueError("only a fact entry names its writing client")
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        """Every key; instants RFC 3339 UTC with microseconds; `from`/`to` keys."""

        def ref(value: RecordRefView | None) -> dict[str, Any] | None:
            return None if value is None else value.to_canonical_dict()

        def holder(value: HandoffHolderView | None) -> dict[str, Any] | None:
            return None if value is None else value.to_canonical_dict()

        return {
            "entry_id": self.entry_id,
            "kind": self.kind.value,
            "plane": self.plane,
            "at": instant_token(self.at),
            "recorded_at": instant_token(self.recorded_at),
            "subject": ref(self.subject),
            "action": self.action,
            "historical_fields_partial": self.historical_fields_partial,
            "issue_version": self.issue_version,
            "state": self.state,
            "title": self.title,
            "closed_at": instant_token(self.closed_at),
            "outcome": self.outcome,
            "project_id": self.project_id,
            "membership_revision_no": self.membership_revision_no,
            "link_state": None if self.link_state is None else self.link_state.value,
            "link_id": self.link_id,
            "revision_no": self.revision_no,
            "relation_type": None if self.relation_type is None else self.relation_type.value,
            "member_role": None if self.member_role is None else self.member_role.value,
            "lifecycle_state": (
                None if self.lifecycle_state is None else self.lifecycle_state.value
            ),
            "from": ref(self.from_ref),
            "to": ref(self.to_ref),
            "handoff_id": self.handoff_id,
            "commitment_id": self.commitment_id,
            "sequence_no": self.sequence_no,
            "from_holder": holder(self.from_holder),
            "to_holder": holder(self.to_holder),
            "voided": self.voided,
            "correction_id": self.correction_id,
            "correction_action": (
                None if self.correction_action is None else self.correction_action.value
            ),
            "corrected_effective_at": instant_token(self.corrected_effective_at),
            "native": None if self.native is None else self.native.to_canonical_dict(),
            "recorded_fields": self.recorded_fields,
            "acceptance_basis": (
                None if self.acceptance_basis is None else self.acceptance_basis.value
            ),
            "user_directed_claim": self.user_directed_claim,
            "asserting_client_id": self.asserting_client_id,
        }


class IssueTimelineView(StrictModel):
    """One `issues.timeline` page (S3 section 7.3).

    `known_at` is `T_k`, `valid_at` the requested value (else `T_k`) and
    `lineage_valid_at` `T_v`, each RFC 3339 UTC with microseconds; entries in
    `(at, plane, kind, entry_id)` order; `next_cursor` while entries remain.
    """

    issue_id: str
    known_at: datetime | None
    valid_at: datetime | None
    lineage_valid_at: datetime | None
    entries: tuple[TimelineEntryView, ...] = Field(max_length=100)
    complete_state: LineageCompleteness
    qualifiers: tuple[LineageCompleteness, ...]
    next_cursor: str | None = Field(
        default=None, min_length=1, max_length=2048, pattern=r"^[A-Za-z0-9_-]+$"
    )

    @model_validator(mode="after")
    def _check(self) -> IssueTimelineView:
        validate_identifier(self.issue_id, IdKind.SITUATION)
        if not self.qualifiers or self.qualifiers[0] is not self.complete_state:
            raise ValueError("the complete_state is the first qualifier")
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation, each entry through its own serializer."""
        return {
            "issue_id": self.issue_id,
            "known_at": instant_token(self.known_at),
            "valid_at": instant_token(self.valid_at),
            "lineage_valid_at": instant_token(self.lineage_valid_at),
            "entries": [entry.to_canonical_dict() for entry in self.entries],
            "complete_state": self.complete_state.value,
            "qualifiers": [code.value for code in self.qualifiers],
            "next_cursor": self.next_cursor,
        }
