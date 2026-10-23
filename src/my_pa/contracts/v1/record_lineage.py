"""The public shapes of record lineage S1 answers (S1 contract sections 7.1 and 7.2).

`EvidenceAnchorView` is one anchor of one link revision; `AssociationView` one
membership or semantic association at one revision with its evidence; and the
`records.lineage` answer is `LineageView`, built of `LineageNodeView`,
`AssociationView` and `VirtualEdgeView`.

**What these models cannot carry is the point of them** (F11, F07, F09):

* no `source_sha256` and no `passage_sha256` on an anchor -- a short passage's
  digest is brute-forceable, so digests are revealed only by
  `meetings.notes.read_version` and the Capture read surfaces under their own
  grants. The stored `evidence_set_digest` is withheld too (FR1-F05): it is
  built over those digests and every other anchor field the view shows, so a
  caller could confirm a guessed low-entropy body through it;
* `source_version_no` is the server-derived version number of the bound row,
  never a client's;
* no body, no title but an Issue's own, and no count of anything withheld;
* `next_cursor` is always `null` in S1 and says nothing about completeness,
  which `complete_state` states.

Every model is a `StrictModel`, so an unknown key -- a digest included -- is
refused on construction, not silently dropped.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import Field, field_validator, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.lineage.model import MAX_ISSUE_TITLE_CHARACTERS
from my_pa.domain.lineage.vocabulary import (
    RECORD_FAMILY_ID_KINDS,
    AcceptanceBasis,
    EvidenceAvailability,
    EvidenceRole,
    EvidenceSourceFamily,
    LineageCompleteness,
    LinkLifecycleState,
    MemberRole,
    NativeVirtualEdge,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SourceVersionKind,
)

__all__ = [
    "MAX_ISSUE_MEMBERSHIPS",
    "MAX_MATCHING_ISSUES",
    "AssociationView",
    "EvidenceAnchorView",
    "LineageIssueMatch",
    "LineageNodeView",
    "LineageView",
    "RecordRefView",
    "VirtualEdgeView",
]

#: At most this many memberships in one `issues.read` (section 7.2).
MAX_ISSUE_MEMBERSHIPS = 100
#: At most this many candidate Issues in one `records.lineage` (section 7.2).
MAX_MATCHING_ISSUES = 20

#: The Issue states: S1's three and, from S2, `closed` (S2 section 3).
_IssueState = Literal["open", "active", "suspended", "closed"]


class RecordRefView(StrictModel):
    """One endpoint root: its family and its identifier."""

    family: RecordFamily
    record_id: str

    @model_validator(mode="after")
    def _check(self) -> RecordRefView:
        validate_identifier(self.record_id, RECORD_FAMILY_ID_KINDS[self.family])
        return self


class EvidenceAnchorView(StrictModel):
    """One anchor of one link revision, with its availability now (F19)."""

    anchor_id: str
    family: EvidenceSourceFamily
    root_id: str
    version_kind: SourceVersionKind
    version_id: str | None
    source_version_no: int | None = Field(ge=1)
    passage_start_cp: int | None = Field(ge=0)
    passage_end_cp: int | None = Field(ge=1)
    role: EvidenceRole
    availability: EvidenceAvailability

    @field_validator("anchor_id")
    @classmethod
    def _anchor_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.LINEAGE_EVIDENCE_ANCHOR)


class AssociationView(StrictModel):
    """One membership or semantic association at one revision, with its evidence.

    `from_ref`/`to_ref` serialize as `from`/`to` (section 7.1): the two names
    are Python keywords, so the attributes carry a suffix and the wire keys do
    not. `recorded_at` is the shown revision's.
    """

    link_id: str
    kind: RecordLinkKind
    relation_type: RelationType
    from_ref: RecordRefView = Field(serialization_alias="from")
    to_ref: RecordRefView = Field(serialization_alias="to")
    member_role: MemberRole | None
    context_issue_id: str | None
    revision_no: int = Field(ge=1)
    lifecycle_state: LinkLifecycleState
    acceptance_basis: AcceptanceBasis
    authority_class: str
    evidence: tuple[EvidenceAnchorView, ...] = Field(max_length=32)
    created_at: UtcDatetime
    recorded_at: UtcDatetime

    @field_validator("link_id")
    @classmethod
    def _link_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.RECORD_LINK)

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation, with the section 7.1 `from`/`to` keys."""
        return self.model_dump(mode="json", by_alias=True)


class LineageIssueMatch(StrictModel):
    """One Issue the root matches: its id, its own title and state only."""

    issue_id: str
    title: str = Field(min_length=1, max_length=MAX_ISSUE_TITLE_CHARACTERS)
    state: _IssueState

    @field_validator("issue_id")
    @classmethod
    def _issue_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.SITUATION)


class LineageNodeView(StrictModel):
    """One reached record.

    `meeting_id` only on a note version, `title` and `state` only on an Issue,
    `availability` only on a Capture version; absent keys are not serialized.
    """

    family: RecordFamily
    record_id: str
    depth: int = Field(ge=0, le=4)
    meeting_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=MAX_ISSUE_TITLE_CHARACTERS)
    state: _IssueState | None = None
    availability: Literal["available", "archived"] | None = None

    @model_validator(mode="after")
    def _check(self) -> LineageNodeView:
        validate_identifier(self.record_id, RECORD_FAMILY_ID_KINDS[self.family])
        is_note = self.family is RecordFamily.MEETING_NOTE_VERSION
        is_issue = self.family is RecordFamily.SITUATION
        is_capture = self.family is RecordFamily.CAPTURE_VERSION
        if (self.meeting_id is not None) is not is_note:
            raise ValueError("only a note version node names its Meeting")
        if self.meeting_id is not None:
            validate_identifier(self.meeting_id, IdKind.MEETING)
        if (self.title is not None) is not is_issue or (self.state is not None) is not is_issue:
            raise ValueError("only an Issue node carries a title and a state")
        if (self.availability is not None) is not is_capture:
            raise ValueError("only a Capture version node carries an availability")
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation without the keys this family does not carry."""
        return self.model_dump(mode="json", exclude_none=True)


class VirtualEdgeView(StrictModel):
    """One native note-version edge, derived from `meeting_note_versions`."""

    edge_type: NativeVirtualEdge
    from_ref: RecordRefView = Field(serialization_alias="from")
    to_ref: RecordRefView = Field(serialization_alias="to")

    @model_validator(mode="after")
    def _check(self) -> VirtualEdgeView:
        if (
            self.from_ref.family is not RecordFamily.MEETING_NOTE_VERSION
            or self.to_ref.family is not RecordFamily.MEETING
        ):
            raise ValueError("a note-version edge runs from a note version to its Meeting")
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation, with the `from`/`to` keys."""
        return self.model_dump(mode="json", by_alias=True)


class LineageView(StrictModel):
    """One `records.lineage` answer (section 7.2)."""

    root: RecordRefView
    selected_issue_id: str | None
    issues_matching_root: tuple[LineageIssueMatch, ...] = Field(max_length=MAX_MATCHING_ISSUES)
    nodes: tuple[LineageNodeView, ...] = Field(max_length=250)
    typed_edges: tuple[AssociationView, ...]
    virtual_native_edges: tuple[VirtualEdgeView, ...]
    complete_state: LineageCompleteness
    next_cursor: None = None

    @model_validator(mode="after")
    def _check(self) -> LineageView:
        if len(self.typed_edges) + len(self.virtual_native_edges) > 400:
            raise ValueError("a lineage answer holds at most 400 edges")
        if self.selected_issue_id is not None:
            validate_identifier(self.selected_issue_id, IdKind.SITUATION)
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation, each part through its own serializer."""
        return {
            "root": self.root.to_canonical_dict(),
            "selected_issue_id": self.selected_issue_id,
            "issues_matching_root": [
                match.to_canonical_dict() for match in self.issues_matching_root
            ],
            "nodes": [node.to_canonical_dict() for node in self.nodes],
            "typed_edges": [edge.to_canonical_dict() for edge in self.typed_edges],
            "virtual_native_edges": [
                edge.to_canonical_dict() for edge in self.virtual_native_edges
            ],
            "complete_state": self.complete_state.value,
            "next_cursor": None,
        }
