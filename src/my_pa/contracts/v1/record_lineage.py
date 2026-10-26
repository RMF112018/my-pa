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

**S3.1 labels** (S3.1 contract sections 4.3 and 7.6): every revision-bearing
view states its stored `acceptance_basis` (`user_confirmed`, the human channel,
or `client_identified`, a connected client's unreviewed fact), the writing
client's unverified `user_directed_claim`, and `asserting_client_id` -- the
authenticated OAuth client that wrote it, shown only to a local reader and
`null` for every remote one (`lineage_visibility.withhold_client_ids`).

Every model is a `StrictModel`, so an unknown key -- a digest included -- is
refused on construction, not silently dropped.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Final, Literal

from pydantic import Field, field_validator, model_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.lineage.cursor import MAX_CURSOR_CHARACTERS, instant_token
from my_pa.domain.lineage.model import MAX_ISSUE_TITLE_CHARACTERS
from my_pa.domain.lineage.vocabulary import (
    MAX_ASSERTING_CLIENT_ID_CHARACTERS,
    MAX_RELATED_SEEDS,
    RECORD_FAMILY_ID_KINDS,
    AcceptanceBasis,
    EvidenceAvailability,
    EvidenceRole,
    EvidenceSourceFamily,
    LineageCompleteness,
    LinkLifecycleState,
    LinkRevisionAction,
    MemberRole,
    NativeVirtualEdge,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SourceVersionKind,
)

__all__ = [
    "ASSERTING_CLIENT_ID",
    "MAX_ISSUE_MEMBERSHIPS",
    "MAX_MATCHING_ISSUES",
    "AssociationView",
    "EvidenceAnchorView",
    "LineageIssueMatch",
    "LineageNodeView",
    "LineagePathEdgeView",
    "LineageView",
    "LinkHistoryRevisionView",
    "LinkHistoryRootView",
    "RecordRefView",
    "RelatedRecordView",
    "RelatedRecordsView",
    "VirtualEdgeView",
]

#: At most this many memberships in one `issues.read` (section 7.2).
MAX_ISSUE_MEMBERSHIPS = 100
#: At most this many candidate Issues in one `records.lineage` (section 7.2).
MAX_MATCHING_ISSUES = 20

#: S3.1 section 4.3: a view's `asserting_client_id` -- the writing OAuth client,
#: 1..256 characters, `null` for the human channel, an unstamped local caller
#: and every remote reader.
ASSERTING_CLIENT_ID: Final = Field(
    default=None, min_length=1, max_length=MAX_ASSERTING_CLIENT_ID_CHARACTERS
)

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
    #: S3.1 section 7.6: the writing client's unverified claim, and its OAuth id.
    user_directed_claim: bool = False
    asserting_client_id: str | None = ASSERTING_CLIENT_ID
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


class LinkHistoryRootView(StrictModel):
    """The link a `records.associations.history` answer is about (S3 section 7.3)."""

    link_id: str
    kind: RecordLinkKind
    relation_type: RelationType
    from_ref: RecordRefView = Field(serialization_alias="from")
    to_ref: RecordRefView = Field(serialization_alias="to")
    member_role: MemberRole | None
    context_issue_id: str | None
    created_at: UtcDatetime

    @field_validator("link_id")
    @classmethod
    def _link_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.RECORD_LINK)

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", by_alias=True)


class LinkHistoryRevisionView(StrictModel):
    """One revision of one link, with its (visible) evidence (S3 section 7.3)."""

    revision_no: int = Field(ge=1)
    revision_id: str
    action: LinkRevisionAction
    lifecycle_state: LinkLifecycleState
    acceptance_basis: AcceptanceBasis
    authority_class: str
    #: S3.1 section 7.6, as `AssociationView`.
    user_directed_claim: bool = False
    asserting_client_id: str | None = ASSERTING_CLIENT_ID
    reason: str | None
    evidence: tuple[EvidenceAnchorView, ...] = Field(max_length=32)
    recorded_at: UtcDatetime

    @field_validator("revision_id")
    @classmethod
    def _revision_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.RECORD_LINK_REVISION)


class LineageIssueMatch(StrictModel):
    """One Issue the root matches: its id, its own title and state only."""

    issue_id: str
    title: str = Field(min_length=1, max_length=MAX_ISSUE_TITLE_CHARACTERS)
    state: _IssueState

    @field_validator("issue_id")
    @classmethod
    def _issue_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.SITUATION)


class LineagePathEdgeView(StrictModel):
    """How a node was first reached (S3 section 7.1, `LineagePathStep.reached_via`).

    `{"edge": "typed", "link_id": irl_}` or `{"edge": "virtual", "edge_type":
    "meeting_note_version_of"}`; the other key is never serialized.
    """

    edge: Literal["typed", "virtual"]
    link_id: str | None = None
    edge_type: NativeVirtualEdge | None = None

    @model_validator(mode="after")
    def _check(self) -> LineagePathEdgeView:
        if self.edge == "typed":
            if self.link_id is None or self.edge_type is not None:
                raise ValueError("a typed path step names its link only")
            validate_identifier(self.link_id, IdKind.RECORD_LINK)
        elif self.edge_type is None or self.link_id is not None:
            raise ValueError("a virtual path step names its edge type only")
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json", exclude_none=True)


class LineageNodeView(StrictModel):
    """One reached record.

    `meeting_id` only on a note version, `title` and `state` only on an Issue,
    `availability` only on a Capture version; absent keys are not serialized.
    S3 (section 7.1) adds the path step that first reached the node:
    `reached_from` (`null` for the root) and `reached_via` (`null` for the
    root), always serialized, so following `reached_from` reaches the root.
    """

    family: RecordFamily
    record_id: str
    depth: int = Field(ge=0, le=4)
    meeting_id: str | None = None
    title: str | None = Field(default=None, min_length=1, max_length=MAX_ISSUE_TITLE_CHARACTERS)
    state: _IssueState | None = None
    availability: Literal["available", "archived"] | None = None
    reached_from: RecordRefView | None = None
    reached_via: LineagePathEdgeView | None = None

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
        if (self.reached_from is None) is not (self.reached_via is None):
            raise ValueError("a path step names both its parent and its edge, or neither")
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation without the keys this family does not carry.

        The two path keys are always present (`null` on the root).
        """
        document = self.model_dump(
            mode="json", exclude_none=True, exclude={"reached_from", "reached_via"}
        )
        document["reached_from"] = (
            None if self.reached_from is None else self.reached_from.to_canonical_dict()
        )
        document["reached_via"] = (
            None if self.reached_via is None else self.reached_via.to_canonical_dict()
        )
        return document


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
    """One `records.lineage` answer (S1 section 7.2, widened by S3 section 7.2).

    S3 adds `qualifiers` (every applicable completeness code, by precedence),
    the cuts the answer was read at -- `known_at` (`T_k`), `valid_at` (as
    requested, else `T_k`), `lineage_valid_at` (`T_v`) and `native_cut_at`
    (`N`), each RFC 3339 UTC with microseconds -- and a string `next_cursor`
    when another page follows.
    """

    root: RecordRefView
    selected_issue_id: str | None
    issues_matching_root: tuple[LineageIssueMatch, ...] = Field(max_length=MAX_MATCHING_ISSUES)
    nodes: tuple[LineageNodeView, ...] = Field(max_length=250)
    typed_edges: tuple[AssociationView, ...]
    virtual_native_edges: tuple[VirtualEdgeView, ...]
    complete_state: LineageCompleteness
    qualifiers: tuple[LineageCompleteness, ...] = ()
    known_at: datetime | None = None
    valid_at: datetime | None = None
    lineage_valid_at: datetime | None = None
    native_cut_at: datetime | None = None
    next_cursor: str | None = Field(
        default=None, min_length=1, max_length=MAX_CURSOR_CHARACTERS, pattern=r"^[A-Za-z0-9_-]+$"
    )

    @model_validator(mode="after")
    def _check(self) -> LineageView:
        if len(self.typed_edges) + len(self.virtual_native_edges) > 400:
            raise ValueError("a lineage answer holds at most 400 edges")
        if self.selected_issue_id is not None:
            validate_identifier(self.selected_issue_id, IdKind.SITUATION)
        if self.qualifiers and self.qualifiers[0] is not self.complete_state:
            raise ValueError("the complete_state is the first qualifier")
        for instant in (self.known_at, self.valid_at, self.lineage_valid_at, self.native_cut_at):
            if instant is not None and instant.tzinfo is None:
                raise ValueError("a lineage cut is an aware instant")
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
            "qualifiers": [code.value for code in self.qualifiers or (self.complete_state,)],
            "known_at": instant_token(self.known_at),
            "valid_at": instant_token(self.valid_at),
            "lineage_valid_at": instant_token(self.lineage_valid_at),
            "native_cut_at": instant_token(self.native_cut_at),
            "next_cursor": self.next_cursor,
        }


class RelatedRecordView(LineageNodeView):
    """One record a `records.lineage.related` read reached (S3.1 contract section 7.4).

    The `LineageNodeView` keys -- `depth` is the least over every seed and
    `reached_from` / `reached_via` the first reaching step -- plus `seeds`, the
    0-based positions of every seed that reached it, and `issue_ids`, the
    visible Issues (at most 20, sorted) under which it was reached.
    """

    seeds: tuple[int, ...] = Field(min_length=1, max_length=MAX_RELATED_SEEDS)
    issue_ids: tuple[str, ...] = Field(default=(), max_length=MAX_MATCHING_ISSUES)

    @model_validator(mode="after")
    def _check_related(self) -> RelatedRecordView:
        if list(self.seeds) != sorted(set(self.seeds)) or self.seeds[0] < 0:
            raise ValueError("a related record names each reaching seed once, in order")
        if list(self.issue_ids) != sorted(set(self.issue_ids)):
            raise ValueError("a related record names each Issue once, sorted")
        for issue_id in self.issue_ids:
            validate_identifier(issue_id, IdKind.SITUATION)
        return self


class RelatedRecordsView(StrictModel):
    """One `records.lineage.related` page (S3.1 contract section 7.4).

    `seeds` echoes the request's seeds in order; `records`, `links` and
    `virtual_edges` are this page's items of the one bounded result;
    `related_sha256` is the digest of that whole result -- the same on every
    page of one cursor chain, and reproduced by a read at the same explicit
    `known_at` while visibility, native resolution and evidence availability
    stay unchanged. It is a digest of metadata the reader can read, never of a
    source or passage.
    """

    seeds: tuple[RecordRefView, ...] = Field(min_length=1, max_length=MAX_RELATED_SEEDS)
    records: tuple[RelatedRecordView, ...] = Field(max_length=250)
    links: tuple[AssociationView, ...]
    virtual_edges: tuple[VirtualEdgeView, ...]
    complete_state: LineageCompleteness
    qualifiers: tuple[LineageCompleteness, ...]
    known_at: datetime | None = None
    valid_at: datetime | None = None
    lineage_valid_at: datetime | None = None
    native_cut_at: datetime | None = None
    related_sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    next_cursor: str | None = Field(
        default=None, min_length=1, max_length=MAX_CURSOR_CHARACTERS, pattern=r"^[A-Za-z0-9_-]+$"
    )

    @model_validator(mode="after")
    def _check(self) -> RelatedRecordsView:
        if len(self.links) + len(self.virtual_edges) > 400:
            raise ValueError("a related answer holds at most 400 edges")
        if not self.qualifiers or self.qualifiers[0] is not self.complete_state:
            raise ValueError("the complete_state is the first qualifier")
        for instant in (self.known_at, self.valid_at, self.lineage_valid_at, self.native_cut_at):
            if instant is not None and instant.tzinfo is None:
                raise ValueError("a lineage cut is an aware instant")
        return self

    def to_canonical_dict(self) -> dict[str, Any]:
        """The JSON-mode representation, each part through its own serializer."""
        return {
            "seeds": [seed.to_canonical_dict() for seed in self.seeds],
            "records": [record.to_canonical_dict() for record in self.records],
            "links": [link.to_canonical_dict() for link in self.links],
            "virtual_edges": [edge.to_canonical_dict() for edge in self.virtual_edges],
            "complete_state": self.complete_state.value,
            "qualifiers": [code.value for code in self.qualifiers],
            "known_at": instant_token(self.known_at),
            "valid_at": instant_token(self.valid_at),
            "lineage_valid_at": instant_token(self.lineage_valid_at),
            "native_cut_at": instant_token(self.native_cut_at),
            "related_sha256": self.related_sha256,
            "next_cursor": self.next_cursor,
        }
