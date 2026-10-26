"""Record lineage S3.1: provenance labels on every lineage read (FAST and database).

S3.1 contract sections 4.3, 7.6 and 8 (worker N3). Every view that shows a
revision-bearing fact states its stored `acceptance_basis`, the writing
client's unverified `user_directed_claim` and `asserting_client_id` -- the
OAuth client that wrote it, shown only to a local reader and `null` for every
remote one. For a Principal holding no client row, every lineage answer equals
its S4 answer plus the added keys at their neutral values.

Every identity and every body here is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import replace
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from pydantic import BaseModel
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    capture,
    capture_anchor,
    membership,
    note_anchor,
)
from tests.database.lineage_s2_harness import assertion, handoff
from tests.database.lineage_s3_harness import contradicts, correct_handoff, corroborates
from tests.database.lineage_s31_harness import (
    GATEWAY,
    REMOTE_CLIENT,
    S31Runtime,
    client_grants,
    open_scene,
)

from my_pa.application.commands import (
    AddIssueProjectLink,
    ListIssueHandoffs,
    ReadIssue,
    ReadIssueClosureReadiness,
    ReadIssueTimeline,
    ReadRecordAssociationHistory,
    ReadRecordLineage,
    ReadRelatedRecords,
)
from my_pa.application.issue_work import WorkCompositeResult
from my_pa.application.issues import ProjectLinkResult
from my_pa.application.record_lineage import AssociationResult
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.issue_timeline import (
    TIMELINE_LABELLED_KINDS,
    TimelineEntryView,
)
from my_pa.contracts.v1.issues import (
    HandoffCorrectionView,
    HandoffHolderView,
    HandoffView,
    ProjectLinkView,
)
from my_pa.contracts.v1.record_lineage import (
    AssociationView,
    EvidenceAnchorView,
    LinkHistoryRevisionView,
    RecordRefView,
    RelatedRecordsView,
)
from my_pa.domain.identity.operation import Capability
from my_pa.domain.lineage.model import RecordRef
from my_pa.domain.lineage.vocabulary import (
    AcceptanceBasis,
    EvidenceAvailability,
    EvidenceRole,
    EvidenceSourceFamily,
    HandoffCorrectionAction,
    HandoffHolderKind,
    IssueProjectMembershipState,
    LinkLifecycleState,
    LinkRevisionAction,
    MemberRole,
    RecordFamily,
    RecordLinkKind,
    RelationType,
    SourceVersionKind,
    TimelineEntryKind,
)

#: Section 7.6: the 2 labels every revision-bearing view gains.
_LABELS: Final = frozenset({"user_directed_claim", "asserting_client_id"})
#: Their neutral values on an operator fact (section 8).
_NEUTRAL: Final = {"user_directed_claim": False, "asserting_client_id": None}
_AT: Final = datetime(2026, 10, 25, 9, tzinfo=UTC)
_ISSUE: Final = "sit_labelsissue0001"
_TASK: Final = RecordRefView(family=RecordFamily.TASK, record_id="tsk_labelstask0001")
_NOTE: Final = RecordRefView(
    family=RecordFamily.MEETING_NOTE_VERSION, record_id="mnote_labelsnote0001"
)

#: The S4 keys of each labelled view (S2 section 7.1 plus the S3 additions),
#: as the S3 key guard pins them.
_S4_KEYS: Final[dict[type[BaseModel], frozenset[str]]] = {
    AssociationView: frozenset(
        {
            "link_id",
            "kind",
            "relation_type",
            "from_ref",
            "to_ref",
            "member_role",
            "context_issue_id",
            "revision_no",
            "lifecycle_state",
            "acceptance_basis",
            "authority_class",
            "evidence",
            "created_at",
            "recorded_at",
        }
    ),
    LinkHistoryRevisionView: frozenset(
        {
            "revision_no",
            "revision_id",
            "action",
            "lifecycle_state",
            "acceptance_basis",
            "authority_class",
            "reason",
            "evidence",
            "recorded_at",
        }
    ),
    ProjectLinkView: frozenset(
        {
            "project_id",
            "project_situation_id",
            "state",
            "membership_revision_no",
            "acceptance_basis",
            "evidence_anchor_id",
            "recorded_at",
        }
    ),
    HandoffView: frozenset(
        {
            "handoff_id",
            "issue_id",
            "commitment_id",
            "sequence_no",
            "from_holder",
            "to_holder",
            "effective_at",
            "recorded_at",
            "reason",
            "evidence",
            "acceptance_basis",
            "authority_class",
            "current_effective_at",
            "voided",
            "correction_ids",
        }
    ),
    HandoffCorrectionView: frozenset(
        {
            "correction_id",
            "handoff_id",
            "correction_no",
            "action",
            "effective_at",
            "reason",
            "evidence",
            "recorded_at",
            "authority_class",
        }
    ),
}
#: Section 7.6: what each view adds; `HandoffCorrectionView` gains its basis too.
_ADDED: Final[dict[type[BaseModel], frozenset[str]]] = {
    AssociationView: _LABELS,
    LinkHistoryRevisionView: _LABELS,
    ProjectLinkView: _LABELS,
    HandoffView: _LABELS,
    HandoffCorrectionView: _LABELS | {"acceptance_basis"},
}


def test_every_lineage_view_carries_the_s31_labels() -> None:
    for view, keys in _S4_KEYS.items():
        fields = frozenset(view.model_fields)
        assert keys <= fields, view.__name__
        assert fields - keys == _ADDED[view], view.__name__
    # The timeline's fact entries carry the 3 labels (null on the other kinds).
    assert {"acceptance_basis", "user_directed_claim", "asserting_client_id"} <= set(
        TimelineEntryView.model_fields
    )
    assert {
        TimelineEntryKind.PROJECT_LINK,
        TimelineEntryKind.MEMBERSHIP,
        TimelineEntryKind.ASSOCIATION,
        TimelineEntryKind.HANDOFF,
        TimelineEntryKind.HANDOFF_CORRECTION,
    } == TIMELINE_LABELLED_KINDS
    # The related read's links are `AssociationView`s, so they carry the labels.
    assert RelatedRecordsView.model_fields["links"].annotation == tuple[AssociationView, ...]
    # The closed sets admit the S3.1 members.
    assert AcceptanceBasis.CLIENT_IDENTIFIED.value == "client_identified"
    assert LinkRevisionAction.CONFIRM.value == "confirm"


# ---- section 8: no client row, the S4 answer plus neutral keys (FAST) ---------------


def _anchor() -> EvidenceAnchorView:
    return EvidenceAnchorView(
        anchor_id="ian_labelsanchor0001",
        family=EvidenceSourceFamily.MEETING_NOTE_VERSION,
        root_id="mtg_labelsmeeting001",
        version_kind=SourceVersionKind.IMMUTABLE_VERSION,
        version_id=_NOTE.record_id,
        source_version_no=1,
        passage_start_cp=0,
        passage_end_cp=9,
        role=EvidenceRole.ORIGIN,
        availability=EvidenceAvailability.AVAILABLE,
    )


def _operator_association() -> AssociationView:
    return AssociationView(
        link_id="irl_labelslink00001",
        kind=RecordLinkKind.SEMANTIC,
        relation_type=RelationType.ORIGINATED_FROM,
        from_ref=_TASK,
        to_ref=_NOTE,
        member_role=None,
        context_issue_id=_ISSUE,
        revision_no=1,
        lifecycle_state=LinkLifecycleState.ACTIVE,
        acceptance_basis=AcceptanceBasis.USER_CONFIRMED,
        authority_class="local_operator",
        evidence=(_anchor(),),
        created_at=_AT,
        recorded_at=_AT,
    )


def _operator_membership() -> AssociationView:
    return _operator_association().model_copy(
        update={
            "link_id": "irl_labelsmember0001",
            "kind": RecordLinkKind.ISSUE_MEMBERSHIP,
            "relation_type": RelationType.ISSUE_MEMBER,
            "from_ref": RecordRefView(family=RecordFamily.SITUATION, record_id=_ISSUE),
            "to_ref": _TASK,
            "member_role": MemberRole.WORK,
            "context_issue_id": None,
            "evidence": (),
        }
    )


def _operator_project_link() -> ProjectLinkView:
    return ProjectLinkView(
        project_id="prj_labelsproject001",
        project_situation_id="psit_labelsproject01",
        state=IssueProjectMembershipState.ACTIVE,
        membership_revision_no=1,
        acceptance_basis=AcceptanceBasis.USER_CONFIRMED,
        recorded_at=_AT,
    )


def _operator_handoff() -> HandoffView:
    anchor = _anchor().model_copy(update={"role": EvidenceRole.HANDOFF})
    return HandoffView(
        handoff_id="ihnd_labelshandoff01",
        issue_id=_ISSUE,
        commitment_id="cmt_labelscommit0001",
        sequence_no=1,
        from_holder=HandoffHolderView(kind=HandoffHolderKind.PRINCIPAL, entity_id=None),
        to_holder=HandoffHolderView(kind=HandoffHolderKind.ENTITY, entity_id="ent_labelsentity001"),
        effective_at=_AT,
        recorded_at=_AT,
        reason="Synthetic handoff.",
        evidence=anchor,
        acceptance_basis=AcceptanceBasis.USER_CONFIRMED,
        authority_class="local_operator",
        current_effective_at=_AT,
        voided=False,
        correction_ids=(),
    )


def _operator_correction() -> HandoffCorrectionView:
    anchor = _anchor().model_copy(update={"role": EvidenceRole.CONTRADICTS})
    return HandoffCorrectionView(
        correction_id="ihcr_labelscorrect01",
        handoff_id="ihnd_labelshandoff01",
        correction_no=1,
        action=HandoffCorrectionAction.VOID,
        effective_at=None,
        reason="Synthetic void.",
        evidence=anchor,
        recorded_at=_AT,
        authority_class="local_operator",
        acceptance_basis=AcceptanceBasis.USER_CONFIRMED,
    )


def _differs_by_neutral_keys(
    document: dict[str, Any], s4_keys: frozenset[str], added: dict[str, Any]
) -> None:
    """`document` is an S4 document (exactly its keys) plus `added` at those values."""
    assert set(document) == set(s4_keys) | set(added)
    for key, value in added.items():
        assert document[key] == value, key


def _wire(keys: frozenset[str]) -> frozenset[str]:
    """Model field names as the wire spells them (`from_ref` -> `from`)."""
    return frozenset({"from_ref": "from", "to_ref": "to"}.get(key, key) for key in keys)


def test_s31_answers_without_client_rows_differ_from_s4_only_by_the_added_keys() -> None:
    association = _operator_association()
    _differs_by_neutral_keys(
        association.to_canonical_dict(), _wire(_S4_KEYS[AssociationView]), _NEUTRAL
    )
    _differs_by_neutral_keys(
        _operator_project_link().to_canonical_dict(), _S4_KEYS[ProjectLinkView], _NEUTRAL
    )
    _differs_by_neutral_keys(
        _operator_handoff().to_canonical_dict(),
        _wire(_S4_KEYS[HandoffView]) - {"from_holder", "to_holder"} | {"from", "to"},
        _NEUTRAL,
    )
    _differs_by_neutral_keys(
        _operator_correction().to_canonical_dict(),
        _S4_KEYS[HandoffCorrectionView],
        {**_NEUTRAL, "acceptance_basis": "user_confirmed"},
    )
    # A timeline fact entry of the human channel: its labels at their values,
    # and `null` on an Issue revision entry.
    entry = TimelineEntryView(
        entry_id="irv_labelsrevision01",
        kind=TimelineEntryKind.ASSOCIATION,
        plane="lineage",
        at=_AT,
        recorded_at=_AT,
        subject=None,
        action="assert",
        historical_fields_partial=False,
        link_id=association.link_id,
        revision_no=1,
        relation_type=RelationType.ORIGINATED_FROM,
        lifecycle_state=LinkLifecycleState.ACTIVE,
        from_ref=_TASK,
        to_ref=_NOTE,
        acceptance_basis=AcceptanceBasis.USER_CONFIRMED,
        user_directed_claim=False,
    ).to_canonical_dict()
    assert {key: entry[key] for key in ("acceptance_basis", *_NEUTRAL)} == {
        "acceptance_basis": "user_confirmed",
        **_NEUTRAL,
    }
    authorization: Any = type("Authorization", (), {"at": _AT})()
    # Every open-write answer shape: the views' S4 keys, the neutral labels and
    # `restricted: false` for a local caller.
    for key, view in (("association", association), ("membership", _operator_membership())):
        for created in (True, None):
            payload = ApplicationService._association_result(
                authorization, key, AssociationResult(view, created, False)
            ).payload
            expected = {key, "replayed", "restricted"} | ({"created"} if created else set())
            assert set(payload) == expected
            assert payload["restricted"] is False
            _differs_by_neutral_keys(payload[key], _wire(_S4_KEYS[AssociationView]), _NEUTRAL)
    project = ApplicationService._project_link_result(
        authorization, ProjectLinkResult(_operator_project_link(), _ISSUE, False)
    ).payload
    assert set(project) == {"project_link", "issue_id", "replayed", "restricted"}
    assert project["restricted"] is False
    _differs_by_neutral_keys(project["project_link"], _S4_KEYS[ProjectLinkView], _NEUTRAL)
    composite = ApplicationService._composite_result(
        authorization,
        WorkCompositeResult(
            record=RecordRef(family=RecordFamily.TASK, record_id=_TASK.record_id),
            membership=_operator_membership(),
            associations=(association,),
            replayed=False,
        ),
    ).payload
    assert set(composite) == {"record", "membership", "associations", "replayed", "restricted"}
    assert composite["restricted"] is False
    for view in (composite["membership"], *composite["associations"]):
        _differs_by_neutral_keys(view, _wire(_S4_KEYS[AssociationView]), _NEUTRAL)


# ---- database: reads of client facts --------------------------------------------------

#: Every lineage read the reader below holds, with its own grant.
_READS: Final = (
    Capability.RECORDS_LINEAGE,
    Capability.RECORDS_LINEAGE_RELATED,
    Capability.RECORDS_ASSOCIATIONS_HISTORY,
    Capability.ISSUES_READ,
    Capability.ISSUES_TIMELINE,
    Capability.ISSUES_HANDOFFS_LIST,
    Capability.ISSUES_CLOSURE_READINESS,
)
#: A second synthetic OAuth client that only reads.
_READER: Final = "synthetic-lineage-reader-client"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31Runtime]:
    composed = S31Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _reader_grants() -> Any:  # noqa: ANN401
    granted: frozenset[Any] = frozenset()
    for capability in _READS:
        granted |= client_grants(capability)
    return granted


def _client_facts(runtime: S31Runtime, key: str) -> dict[str, str]:
    """A remote client's membership, link, Project link, handoff and void, each claimed."""
    scene = open_scene(runtime, key)
    claimed: dict[str, str] = {
        "issue": scene.issue,
        "task": scene.member_task,
        "note": scene.note,
        "project": scene.project,
    }

    def write(command: Any) -> dict[str, Any]:  # noqa: ANN401
        return runtime.client_ok(replace(command, user_directed=True))

    claimed["membership"] = write(
        membership(scene.issue, "task", scene.member_task, f"{key}-member", role="reference")
    )["membership"]["link_id"]
    claimed["link"] = write(
        assertion(
            "discusses",
            ("meeting_note_version", scene.note),
            ("task", scene.member_task),
            f"{key}-discusses",
            (note_anchor(scene.meeting, scene.note, NOTE_BODY, role="discussion"),),
            context=scene.issue,
        )
    )["association"]["link_id"]
    write(
        AddIssueProjectLink(
            issue_id=scene.issue,
            project_id=scene.project,
            expected_membership_revision=0,
            idempotency_key=f"s31-labels-{key}-link",
        )
    )
    claimed["handoff"] = write(
        handoff(
            scene.issue,
            scene.handoff_commitment,
            "counterparty",
            scene.handoff_effective_at,
            f"{key}-handoff",
            note_anchor(scene.meeting, scene.note, NOTE_BODY, role="handoff"),
        )
    )["handoff"]["handoff_id"]
    write(
        correct_handoff(
            claimed["handoff"], "void", f"{key}-void", contradicts(scene.meeting, scene.note)
        )
    )
    return claimed


def _read_all(runtime: S31Runtime, facts: dict[str, str], **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    issue, task = facts["issue"], facts["task"]
    commands = {
        "records.lineage": ReadRecordLineage(
            origin={"family": "task", "record_id": task}, issue_id=issue
        ),
        "records.lineage.related": ReadRelatedRecords(
            seeds=({"family": "task", "record_id": task},)
        ),
        "records.associations.history": ReadRecordAssociationHistory(link_id=facts["link"]),
        "issues.read": ReadIssue(issue_id=issue, include_members=True),
        "issues.timeline": ReadIssueTimeline(issue_id=issue),
        "issues.handoffs.list": ListIssueHandoffs(issue_id=issue),
        "issues.closure_readiness": ReadIssueClosureReadiness(issue_id=issue),
    }
    if kwargs:
        return {
            name: runtime.client_ok(command, client=_READER, **kwargs)
            for name, command in commands.items()
        }
    return {name: runtime.ok(command, surface=GATEWAY) for name, command in commands.items()}


def _client_views(
    answers: dict[str, Any], facts: dict[str, str]
) -> dict[str, list[dict[str, Any]]]:
    """Every view of a client fact in each answer."""
    lineage = answers["records.lineage"]["typed_edges"]
    related = answers["records.lineage.related"]["links"]
    read = answers["issues.read"]
    timeline = [
        entry
        for entry in answers["issues.timeline"]["entries"]
        if entry["kind"] in {kind.value for kind in TIMELINE_LABELLED_KINDS}
        and entry["acceptance_basis"] == "client_identified"
    ]
    return {
        "records.lineage": [
            edge for edge in lineage if edge["link_id"] in {facts["membership"], facts["link"]}
        ],
        "records.lineage.related": [
            link for link in related if link["link_id"] in {facts["membership"], facts["link"]}
        ],
        "records.associations.history": answers["records.associations.history"]["revisions"],
        "issues.read": [
            *[m for m in read["memberships"] if m["link_id"] == facts["membership"]],
            *read["issue"]["project_links"],
        ],
        "issues.timeline": timeline,
        "issues.handoffs.list": answers["issues.handoffs.list"]["handoffs"],
        "issues.closure_readiness": answers["issues.closure_readiness"]["unreviewed_links"],
    }


@pytest.mark.database
def test_every_read_labels_a_client_fact(runtime: S31Runtime) -> None:
    facts = _client_facts(runtime, "labels-every")
    views = _client_views(_read_all(runtime, facts), facts)
    for name, found in views.items():
        assert found, name
        for view in found:
            assert view["user_directed_claim"] is True, name
            if name != "issues.closure_readiness":
                assert view["acceptance_basis"] == "client_identified", name
    # The timeline labels each kind a client wrote, the void included.
    kinds = {entry["kind"] for entry in views["issues.timeline"]}
    assert kinds == {"membership", "association", "project_link", "handoff", "handoff_correction"}
    # Readiness lists the client's membership and link as unreviewed and is not ready.
    readiness = views["issues.closure_readiness"]
    assert {entry["link_id"] for entry in readiness} >= {facts["membership"], facts["link"]}


@pytest.mark.database
def test_a_remote_reader_never_sees_a_client_id(runtime: S31Runtime) -> None:
    facts = _client_facts(runtime, "labels-hidden")
    local = _read_all(runtime, facts)
    for name, found in _client_views(local, facts).items():
        if name == "issues.closure_readiness":
            continue  # `UnreviewedLinkView` names no client (section 7.5).
        assert {view["asserting_client_id"] for view in found} == {REMOTE_CLIENT}, name
    remote = _read_all(runtime, facts, grants=_reader_grants())
    for name, answer in remote.items():
        assert REMOTE_CLIENT not in json.dumps(answer), name
    for name, found in _client_views(remote, facts).items():
        assert found, name
        assert all(view.get("asserting_client_id") is None for view in found), name
    # The writing client itself reads `null` too.
    own = runtime.client_ok(
        ReadRecordAssociationHistory(link_id=facts["link"]),
        grants=client_grants(Capability.RECORDS_ASSOCIATIONS_HISTORY),
    )
    assert REMOTE_CLIENT not in json.dumps(own)


@pytest.mark.database
def test_a_replay_applies_the_current_answer_filter(runtime: S31Runtime) -> None:
    """A replay is rebuilt from stored rows under the reader's current visibility.

    The operator asserts `blocks` T1 -> T2 citing a Capture version; a client
    asserts the same identity citing a note (`created: false`, the operator's
    revision shown with its Capture anchor). After the client loses Capture
    visibility, its replay withholds that anchor and says `restricted`.
    """
    scene = open_scene(runtime, "labels-replay")
    first, second = runtime.task("labels-replay-a"), runtime.task("labels-replay-b")
    capture_id, version_id, _digest = capture(runtime, "labels-replay")
    runtime.ok(
        assertion(
            "blocks",
            ("task", first),
            ("task", second),
            "labels-replay-operator",
            (capture_anchor(capture_id, version_id, NOTE_BODY, role="corroborates"),),
        ),
        surface=GATEWAY,
    )
    command = assertion(
        "blocks",
        ("task", first),
        ("task", second),
        "labels-replay-client",
        (corroborates(scene.meeting, scene.note),),
    )
    answered = runtime.client_ok(command)
    assert answered["created"] is False
    assert answered["restricted"] is False
    assert {anchor["family"] for anchor in answered["association"]["evidence"]} == {
        "capture_version"
    }
    hidden = client_grants(Capability.RECORDS_ASSOCIATIONS_ASSERT, without=("capture.read",))
    replayed = runtime.client_ok(command, grants=hidden)
    assert replayed["replayed"] is True
    assert replayed["restricted"] is True
    assert replayed["association"]["evidence"] == []
    assert replayed["association"]["link_id"] == answered["association"]["link_id"]
    # The same replay under the visibility it was first answered with shows it all.
    again = runtime.client_ok(command)
    assert (again["replayed"], again["restricted"]) == (True, False)
    assert again["association"] == answered["association"]
