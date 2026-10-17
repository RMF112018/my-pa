"""AT-024 (S1, server): what a record lineage read carries and never carries (FAST).

S1 contract sections 7.1 and 7.2, against `application.record_lineage`'s
traversal over an in-memory lineage source and the `contracts.v1.record_lineage`
views: every edge states its relation, direction, acceptance basis, actor class
and evidence; no read carries a body, a hidden count or a title but an Issue's
own; anchor views carry no source or passage digest and carry the
server-derived version number; and `complete_state` is stated even though
`next_cursor` is always `null`. The budget and completeness rows of section 7.2
step 6 are proved here too. Every identity is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Collection, Mapping
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from pydantic import ValidationError

from my_pa.application import record_lineage as lineage_module
from my_pa.application.commands import AddIssueMembership
from my_pa.application.errors import InvalidRequestError, NotFoundError
from my_pa.application.lineage_endpoints import EVIDENCE_ANCHOR_INPUT_KEYS
from my_pa.application.record_lineage import LineageReadRequest, traverse_lineage
from my_pa.contracts.ports import (
    LineageLinkEvidence,
    LineageNoteVersionRef,
    LineageResolvedRecord,
    LinkHeadRecord,
    LinkRevisionRecord,
    RecordLineageRepository,
    RecordLinkRecord,
)
from my_pa.contracts.v1.record_lineage import (
    AssociationView,
    EvidenceAnchorView,
    LineageNodeView,
    LineageView,
)
from my_pa.domain.lineage.canonical import evidence_set_digest, normalized_identity
from my_pa.domain.lineage.model import EvidenceAnchor, RecordRef
from my_pa.domain.lineage.vocabulary import (
    AcceptanceBasis,
    EvidenceRole,
    EvidenceSourceFamily,
    LinkLifecycleState,
    LinkRevisionAction,
    MemberRole,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SituationKind,
    SourceVersionKind,
)

_PRINCIPAL: Final = "prn_lineagereadfast01"
_WHEN: Final = datetime(2026, 10, 17, 12, tzinfo=UTC)
_ISSUE: Final = RecordRef(family=RecordFamily.SITUATION, record_id="sit_readissue0001")
_MEETING: Final = RecordRef(family=RecordFamily.MEETING, record_id="mtg_readmeeting0001")
_NOTE: Final = RecordRef(family=RecordFamily.MEETING_NOTE_VERSION, record_id="mnote_readnote0001")
_LATER: Final = RecordRef(family=RecordFamily.MEETING_NOTE_VERSION, record_id="mnote_readnote0002")
_COMMITMENT: Final = RecordRef(family=RecordFamily.COMMITMENT, record_id="cmt_readcommit0001")
_NOTE_TEXT: Final = "Synthetic confidential note body that must never be returned."


class _Source(RecordLineageRepository):
    """An in-memory lineage source: native records, note versions, active links."""

    def __init__(self) -> None:
        self.records: dict[RecordRef, LineageResolvedRecord] = {}
        self.notes: dict[str, list[LineageNoteVersionRef]] = {}
        self.heads: list[LinkHeadRecord] = []
        self.revisions: dict[str, LinkRevisionRecord] = {}
        self.gone: set[RecordRef] = set()
        self.resolutions = 0

    # --- seeding -----------------------------------------------------------

    def issue(self, ref: RecordRef, title: str = "Synthetic read issue") -> None:
        self.records[ref] = LineageResolvedRecord(
            ref=ref, situation_kind=SituationKind.ISSUE_WORKSTREAM, title=title, state="open"
        )

    def plain(self, ref: RecordRef) -> None:
        self.records[ref] = LineageResolvedRecord(ref=ref)

    def note(self, ref: RecordRef, meeting: RecordRef, number: int) -> None:
        self.records[ref] = LineageResolvedRecord(ref=ref, meeting_id=meeting.record_id)
        self.notes.setdefault(meeting.record_id, []).append(
            LineageNoteVersionRef(
                note_version_id=ref.record_id, meeting_id=meeting.record_id, version_number=number
            )
        )

    def link(
        self,
        number: int,
        relation: RelationType,
        from_ref: RecordRef,
        to_ref: RecordRef,
        *,
        role: MemberRole | None = None,
        context: str | None = None,
        anchors: tuple[EvidenceAnchor, ...] = (),
    ) -> str:
        link_id = f"irl_readlink{number:06d}"
        kind = (
            RecordLinkKind.ISSUE_MEMBERSHIP
            if relation is RelationType.ISSUE_MEMBER
            else RecordLinkKind.SEMANTIC
        )
        if kind is RecordLinkKind.ISSUE_MEMBERSHIP:
            context = from_ref.record_id
        root = RecordLinkRecord(
            link_id=link_id,
            kind=kind,
            from_ref=from_ref,
            to_ref=to_ref,
            relation_type=relation,
            member_role=role,
            context_issue_id=context,
            normalized_identity=normalized_identity(
                kind=kind,
                relation_type=relation,
                from_ref=from_ref,
                to_ref=to_ref,
                member_role=role,
                context_issue_id=context,
            ),
            authority_class="local_operator",
            decision_channel="local_web",
            source_capability="records.associations.assert",
            created_at=_WHEN,
        )
        self.heads.append(
            LinkHeadRecord(link=root, revision_no=1, lifecycle_state=LinkLifecycleState.ACTIVE)
        )
        self.revisions[link_id] = LinkRevisionRecord(
            link_id=link_id,
            revision_no=1,
            revision_id=f"irv_readrev{number:06d}",
            predecessor_revision_no=None,
            action=LinkRevisionAction.ASSERT,
            lifecycle_state=LinkLifecycleState.ACTIVE,
            acceptance_basis=AcceptanceBasis.USER_CONFIRMED,
            authority_class="local_operator",
            decision_channel="local_web",
            source_capability="records.associations.assert",
            reason=None,
            evidence_set_digest=evidence_set_digest(anchors),
            recorded_at=_WHEN,
            evidence=tuple(
                LineageLinkEvidence(anchor_id=f"ian_readanchor{number:04d}{index:02d}", anchor=a)
                for index, a in enumerate(anchors)
            ),
        )
        return link_id

    # --- the port's reads ----------------------------------------------------

    def resolve_records(
        self, principal_id: str, refs: Collection[RecordRef]
    ) -> Mapping[RecordRef, LineageResolvedRecord]:
        self.resolutions += 1
        return {
            ref: self.records[ref] for ref in refs if ref in self.records and ref not in self.gone
        }

    def note_versions_of(
        self, principal_id: str, meeting_ids: Collection[str]
    ) -> Mapping[str, tuple[LineageNoteVersionRef, ...]]:
        return {key: tuple(self.notes[key]) for key in meeting_ids if key in self.notes}

    def active_links_incident(
        self, principal_id: str, refs: Collection[RecordRef]
    ) -> tuple[LinkHeadRecord, ...]:
        wanted = set(refs)
        return tuple(
            head
            for head in self.heads
            if head.link.from_ref in wanted or head.link.to_ref in wanted
        )

    def read_revision(
        self, principal_id: str, link_id: str, revision_no: int
    ) -> LinkRevisionRecord | None:
        return self.revisions.get(link_id)

    def archived_capture_roots(
        self, principal_id: str, capture_ids: Collection[str]
    ) -> frozenset[str]:
        return frozenset()

    # --- write side: unused by a read --------------------------------------------

    def _unused(self, *_args: Any, **_kwargs: Any) -> Any:  # noqa: ANN401
        raise AssertionError("a lineage read wrote or locked")

    capture_version_root = share_endpoint = lock_identity = _unused
    active_head_by_identity = lock_head = insert_link = append_revision = _unused
    read_link = issue_memberships = _unused


def _anchor(number: int = 1) -> EvidenceAnchor:
    return EvidenceAnchor(
        source_family=EvidenceSourceFamily.MEETING_NOTE_VERSION,
        source_root_id=_MEETING.record_id,
        source_version_kind=SourceVersionKind.IMMUTABLE_VERSION,
        source_version_id=_NOTE.record_id,
        source_version_no=number,
        source_sha256="c" * 64,
        passage_start_cp=3,
        passage_end_cp=9,
        passage_sha256="d" * 64,
        role=EvidenceRole.ORIGIN,
    )


def _fixture() -> _Source:
    """AT-001's shape: I, M1 with N1 and N1b, C1; I -> M1, I -> C1, C1 <- N1 in I."""
    source = _Source()
    source.issue(_ISSUE)
    source.plain(_MEETING)
    source.plain(_COMMITMENT)
    source.note(_NOTE, _MEETING, 1)
    source.note(_LATER, _MEETING, 2)
    source.link(1, RelationType.ISSUE_MEMBER, _ISSUE, _MEETING, role=MemberRole.DISCUSSION)
    source.link(2, RelationType.ISSUE_MEMBER, _ISSUE, _COMMITMENT, role=MemberRole.WORK)
    source.link(
        3,
        RelationType.ORIGINATED_FROM,
        _COMMITMENT,
        _NOTE,
        context=_ISSUE.record_id,
        anchors=(_anchor(),),
    )
    return source


def _read(source: _Source, origin: RecordRef, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    request = LineageReadRequest(
        origin=origin, issue_id=kwargs.get("issue_id"), max_depth=kwargs.get("max_depth", 4)
    )
    return traverse_lineage(source, _PRINCIPAL, request).to_canonical_dict()


def _keys(document: object) -> set[str]:
    found: set[str] = set()
    if isinstance(document, dict):
        for key, value in document.items():
            found.add(key)
            found |= _keys(value)
    elif isinstance(document, list):
        for item in document:
            found |= _keys(item)
    return found


def test_edges_carry_relation_direction_basis_and_evidence() -> None:
    answer = _read(_fixture(), _COMMITMENT)
    origin = next(
        edge for edge in answer["typed_edges"] if edge["relation_type"] == "originated_from"
    )
    assert origin["from"] == {"family": "commitment", "record_id": _COMMITMENT.record_id}
    assert origin["to"] == {"family": "meeting_note_version", "record_id": _NOTE.record_id}
    assert origin["kind"] == "semantic" and origin["lifecycle_state"] == "active"
    assert origin["acceptance_basis"] == "user_confirmed"
    assert origin["authority_class"] == "local_operator"
    assert origin["context_issue_id"] == _ISSUE.record_id
    assert len(origin["evidence_set_digest"]) == 64
    (anchor,) = origin["evidence"]
    assert anchor["role"] == "origin" and anchor["availability"] == "available"
    memberships = [edge for edge in answer["typed_edges"] if edge["kind"] == "issue_membership"]
    assert {edge["member_role"] for edge in memberships} == {"discussion", "work"}
    assert all(edge["from"]["family"] == "situation" for edge in memberships)
    # Output order is by link id; nodes by (depth, family, record id).
    assert [edge["link_id"] for edge in answer["typed_edges"]] == sorted(
        edge["link_id"] for edge in answer["typed_edges"]
    )


def test_reads_carry_no_body_or_hidden_count_and_only_issue_titles() -> None:
    source = _fixture()
    answer = _read(source, _MEETING)
    rendered = json.dumps(answer)
    assert _NOTE_TEXT not in rendered
    keys = _keys(answer)
    assert not keys & {"body", "body_markdown", "content", "content_markdown", "text"}
    assert not {key for key in keys if "count" in key or "hidden" in key}
    for node in answer["nodes"]:
        assert ("title" in node) is (node["family"] == "situation")
        assert ("state" in node) is (node["family"] == "situation")
        assert ("meeting_id" in node) is (node["family"] == "meeting_note_version")
    assert [match["title"] for match in answer["issues_matching_root"]] == ["Synthetic read issue"]
    with pytest.raises(ValidationError):
        LineageNodeView(
            family=RecordFamily.TASK, record_id="tsk_readtask00001", depth=1, title="leak"
        )
    for model in (LineageView, LineageNodeView, AssociationView):
        assert not set(model.model_fields) & {"body", "body_markdown", "hidden_node_count"}


def test_views_carry_no_source_or_passage_digest() -> None:
    answer = _read(_fixture(), _NOTE)
    keys = _keys(answer)
    assert "source_sha256" not in keys and "passage_sha256" not in keys
    assert not set(EvidenceAnchorView.model_fields) & {"source_sha256", "passage_sha256"}
    with pytest.raises(ValidationError):
        EvidenceAnchorView(
            anchor_id="ian_readanchor000001",
            family=EvidenceSourceFamily.MEETING_NOTE_VERSION,
            root_id=_MEETING.record_id,
            version_kind=SourceVersionKind.IMMUTABLE_VERSION,
            version_id=_NOTE.record_id,
            source_version_no=1,
            passage_start_cp=0,
            passage_end_cp=4,
            role=EvidenceRole.ORIGIN,
            availability="available",
            source_sha256="e" * 64,  # type: ignore[call-arg]
        )
    # The whole-set digest stays: it cannot be inverted to a passage.
    assert all(len(edge["evidence_set_digest"]) == 64 for edge in answer["typed_edges"])


def test_anchor_views_carry_the_server_derived_version_number() -> None:
    source = _Source()
    source.issue(_ISSUE)
    source.plain(_COMMITMENT)
    source.plain(_MEETING)
    source.note(_NOTE, _MEETING, 7)
    source.link(1, RelationType.ISSUE_MEMBER, _ISSUE, _COMMITMENT, role=MemberRole.WORK)
    source.link(
        2,
        RelationType.ORIGINATED_FROM,
        _COMMITMENT,
        _NOTE,
        context=_ISSUE.record_id,
        anchors=(_anchor(7),),
    )
    answer = _read(source, _COMMITMENT)
    origin = next(
        edge for edge in answer["typed_edges"] if edge["relation_type"] == "originated_from"
    )
    assert origin["evidence"][0]["source_version_no"] == 7
    # A caller never supplies it: the input shape has no such key and refuses it.
    assert "source_version_no" not in EVIDENCE_ANCHOR_INPUT_KEYS
    assert "version_no" not in EVIDENCE_ANCHOR_INPUT_KEYS
    with pytest.raises(InvalidRequestError):
        AddIssueMembership(
            issue_id=_ISSUE.record_id,
            member={"family": "commitment", "record_id": _COMMITMENT.record_id},
            role="work",
            idempotency_key="read-contract-version-no",
            evidence_anchors=(
                {
                    "family": "meeting_note_version",
                    "root_id": _MEETING.record_id,
                    "version_kind": "immutable_version",
                    "version_id": _NOTE.record_id,
                    "source_sha256": "c" * 64,
                    "source_version_no": 7,
                    "role": "origin",
                },
            ),
        )


def test_completeness_is_stated_even_with_a_null_cursor() -> None:
    complete = _read(_fixture(), _ISSUE)
    assert complete["complete_state"] == "complete" and complete["next_cursor"] is None
    # A record no Issue reaches still says what it can claim.
    lonely = _Source()
    lonely.plain(_COMMITMENT)
    alone = _read(lonely, _COMMITMENT)
    assert alone["complete_state"] == "complete" and alone["next_cursor"] is None
    assert alone["selected_issue_id"] is None and alone["issues_matching_root"] == []
    # Two Issues: the candidates, no traversal, still a null cursor.
    ambiguous = _fixture()
    other = RecordRef(family=RecordFamily.SITUATION, record_id="sit_readissue0002")
    ambiguous.issue(other, "Another synthetic issue")
    ambiguous.link(9, RelationType.ISSUE_MEMBER, other, _MEETING, role=MemberRole.REFERENCE)
    answer = _read(ambiguous, _MEETING)
    assert answer["complete_state"] == "unresolved_ambiguity" and answer["next_cursor"] is None
    assert answer["typed_edges"] == []
    assert len(answer["issues_matching_root"]) == 2
    assert "next_cursor" in LineageView.model_fields


# --- section 7.2 steps 1, 3, 5 and 6 --------------------------------------------------


def test_the_node_budget_truncates_and_says_so() -> None:
    source = _Source()
    source.issue(_ISSUE)
    for number in range(300):
        member = RecordRef(family=RecordFamily.TASK, record_id=f"tsk_readbudget{number:05d}")
        source.plain(member)
        source.link(100 + number, RelationType.ISSUE_MEMBER, _ISSUE, member, role=MemberRole.WORK)
    answer = _read(source, _ISSUE)
    assert answer["complete_state"] == "truncated_budget"
    assert len(answer["nodes"]) == lineage_module.MAX_LINEAGE_NODES
    assert len(answer["typed_edges"]) <= lineage_module.MAX_LINEAGE_EDGES


def test_the_byte_budget_truncates_and_says_so(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(lineage_module, "MAX_LINEAGE_BYTES", 2000)
    answer = _read(_fixture(), _ISSUE)
    assert answer["complete_state"] == "truncated_budget"
    assert len(json.dumps(answer, separators=(",", ":"))) <= 2000


def test_a_node_that_no_longer_resolves_is_partial_native_history() -> None:
    source = _fixture()

    original = source.resolve_records

    def resolve(principal_id: str, refs: Collection[RecordRef]) -> Any:  # noqa: ANN401
        found = dict(original(principal_id, refs))
        if len(set(refs)) > 1:
            # The final re-resolution (step 5): the Commitment is gone.
            found.pop(_COMMITMENT, None)
        return found

    source.resolve_records = resolve  # type: ignore[method-assign]
    answer = _read(source, _ISSUE)
    assert answer["complete_state"] == "partial_native_history"
    assert ("commitment", _COMMITMENT.record_id) not in {
        (node["family"], node["record_id"]) for node in answer["nodes"]
    }
    assert all(
        _COMMITMENT.record_id not in (edge["from"]["record_id"], edge["to"]["record_id"])
        for edge in answer["typed_edges"]
    )


def test_the_depth_bound_limits_the_walk() -> None:
    answer = _read(_fixture(), _ISSUE, max_depth=1)
    depths = {node["record_id"]: node["depth"] for node in answer["nodes"]}
    assert _NOTE.record_id not in depths
    assert max(depths.values()) == 1
    none = _read(_fixture(), _ISSUE, max_depth=0)
    assert [node["record_id"] for node in none["nodes"]] == [_ISSUE.record_id]
    assert none["typed_edges"] == []


def test_an_absent_root_and_an_unmatched_issue_are_not_found() -> None:
    with pytest.raises(NotFoundError):
        _read(_Source(), _COMMITMENT)
    with pytest.raises(NotFoundError):
        _read(_fixture(), _COMMITMENT, issue_id="sit_readissue0009")
    context = _Source()
    context.records[_ISSUE] = LineageResolvedRecord(
        ref=_ISSUE, situation_kind=SituationKind.CONTEXT, title="ctx", state="open"
    )
    with pytest.raises(InvalidRequestError):
        _read(context, _ISSUE)
