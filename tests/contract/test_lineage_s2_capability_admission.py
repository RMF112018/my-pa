"""Record lineage S2 capability admission and compatibility (AT-023, FAST).

S2 contract sections 6.1, 7, 7.1, 7.5 and 8:

* every S2 name is `CHATLLM_OPERATOR_DECISION_REQUIRED` with the S2 rationale,
  scopeless, not operator-only, in the `lineage` gateway feature; the six
  writes are writes and idempotent remotely, the three additive ones additive;
* `issue_work_authoring` is the composites' own remote-write purpose and no
  other capability's;
* the close, reopen, readiness and membership-correction requests refuse every
  server-owned field, an exception/override field and any unknown key;
* `records.associations.assert` publishes and parses exactly the S2 relations
  it may write (`escalated_from`, `blocks`), never a creation relation;
* the S1 Issue and association views keep every S1 key; `IssueView` gains
  exactly `closure`;
* `lineage_enabled` off withholds all eight S2 names from the published surface
  and answers `unsupported` to each, before authority.

* the v1 Work create requests and views the composites run through keep
  every field, and each composite's nested object is exactly its v1 create
  request less `idempotency_key` and `situation_id` (and, for a Task,
  `accepted_by_review_decision_id`).

Every identity here is synthetic.
"""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeUnitOfWork,
    Scene,
    build_service,
    metadata_for,
)

from my_pa.adapters.mcp import remote as remote_mcp
from my_pa.adapters.mcp.chatllm_gateway import _FEATURE_BY_FAMILY
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.mcp.tools import payload_schema_for
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import _IDEMPOTENT_REMOTE_CAPABILITIES
from my_pa.application.commands import (
    AssertRecordAssociation,
    CloseIssue,
    Command,
    CorrectIssueMembership,
    CreateCommitment,
    CreateIssueWorkCommitment,
    CreateIssueWorkTask,
    CreateTask,
    GetCapabilities,
    ListIssueHandoffs,
    ReadIssueClosureReadiness,
    RecordIssueHandoff,
    ReopenIssue,
)
from my_pa.application.errors import ApplicationError, InvalidRequestError
from my_pa.application.service import _LINEAGE_CAPABILITIES, ApplicationService
from my_pa.contracts.v1.commitments import CommitmentView
from my_pa.contracts.v1.issues import (
    ClosureBlockerView,
    HandoffHolderView,
    HandoffView,
    IssueClosureView,
    IssueListEntry,
    IssueRevisionView,
    IssueView,
)
from my_pa.contracts.v1.record_lineage import AssociationView, EvidenceAnchorView
from my_pa.contracts.v1.tasks import TaskView
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.lineage.vocabulary import COMPOSITE_ONLY_RELATIONS, RelationType
from my_pa.domain.policy.decision import _SCOPELESS

S2_NAMES: Final = frozenset(
    {
        "issues.close",
        "issues.reopen",
        "issues.closure_readiness",
        "issues.memberships.correct",
        "issues.handoffs.record",
        "issues.handoffs.list",
        "issues.work.create_task",
        "issues.work.create_commitment",
    }
)
_WRITES: Final = S2_NAMES - {"issues.closure_readiness", "issues.handoffs.list"}
_ADDITIVE: Final = frozenset(
    {"issues.handoffs.record", "issues.work.create_task", "issues.work.create_commitment"}
)
_COMPOSITES: Final = frozenset({"issues.work.create_task", "issues.work.create_commitment"})
_RATIONALE: Final = "record lineage S2; exposure is an operator decision (ADR-015, OD-07)"
_ISSUE: Final = "sit_lineages2fast0001"
_LINK: Final = "irl_lineages2fast0001"
_COMMITMENT: Final = "cmt_lineages2fast0001"
_ANCHOR: Final[dict[str, object]] = {
    "family": "meeting_note_version",
    "root_id": "mtg_lineages2fast0001",
    "version_kind": "immutable_version",
    "version_id": "mnote_lineages2fast0001",
    "source_sha256": "a" * 64,
    "role": "resolution",
}


def _s2() -> frozenset[Capability]:
    return frozenset(capability for capability in Capability if capability.value in S2_NAMES)


def test_s2_capabilities_are_operator_decision_required() -> None:
    declared = _s2()
    assert {capability.value for capability in declared} == S2_NAMES
    assert declared <= _LINEAGE_CAPABILITIES
    assert len(_LINEAGE_CAPABILITIES) == 22
    for capability in declared:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED
        assert policy.exclusion_rationale == _RATIONALE
        assert not is_operator_only(capability)
        assert capability in _SCOPELESS
        assert _FEATURE_BY_FAMILY[capability.value.split(".", 1)[0]] == "lineage"
        writes = capability.value in _WRITES
        assert is_write_capability(capability) is writes
        assert is_destructive_capability(capability) is (
            writes and capability.value not in _ADDITIVE
        )
        assert (capability in _IDEMPOTENT_REMOTE_CAPABILITIES) is writes
        purposes = permitted_purposes(capability)
        assert len(purposes) == 1
        assert bool(purposes & remote_mcp._WRITE_PURPOSES) is writes
    # No data-class member moved, so the ChatLLM data profile did not either.
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v9"


def test_issue_work_authoring_is_its_own_purpose() -> None:
    using = {
        capability.value
        for capability in Capability
        if Purpose.ISSUE_WORK_AUTHORING in permitted_purposes(capability)
    }
    assert using == _COMPOSITES
    for name in _COMPOSITES:
        assert permitted_purposes(Capability(name)) == frozenset({Purpose.ISSUE_WORK_AUTHORING})
    # An Issue-authoring grant does not reach a composite, nor the reverse.
    authoring = {
        capability.value
        for capability in Capability
        if Purpose.ISSUE_AUTHORING in permitted_purposes(capability)
    }
    assert not authoring & _COMPOSITES
    assert {"issues.close", "issues.reopen", "issues.memberships.correct"} <= authoring
    assert Purpose.ISSUE_WORK_AUTHORING in remote_mcp._WRITE_PURPOSES


# ---- request shapes ---------------------------------------------------------

_BASE_PAYLOADS: Final[dict[str, dict[str, object]]] = {
    "issues.close": {
        "issue_id": _ISSUE,
        "expected_version": 1,
        "idempotency_key": "fast-s2-close",
        "outcome": "Resolved.",
        "closure_evidence_anchors": [_ANCHOR],
    },
    "issues.reopen": {
        "issue_id": _ISSUE,
        "expected_version": 2,
        "idempotency_key": "fast-s2-reopen",
        "reason": "Recurred.",
    },
    "issues.closure_readiness": {"issue_id": _ISSUE},
    "issues.memberships.correct": {
        "link_id": _LINK,
        "expected_revision": 1,
        "idempotency_key": "fast-s2-correct",
        "reason": "Resolution recorded.",
        "evidence_anchors": [_ANCHOR],
    },
    "issues.handoffs.record": {
        "issue_id": _ISSUE,
        "commitment_id": _COMMITMENT,
        "from_side": "counterparty",
        "effective_at": "2026-10-18T12:00:00+00:00",
        "reason": "Moved.",
        "evidence_anchor": {**_ANCHOR, "role": "handoff"},
        "idempotency_key": "fast-s2-handoff",
    },
    "issues.handoffs.list": {"issue_id": _ISSUE},
    "issues.work.create_task": {
        "issue_id": _ISSUE,
        "idempotency_key": "fast-s2-task",
        "task": {"title": "Synthetic", "origin_kind": "direct_principal"},
    },
    "issues.work.create_commitment": {
        "issue_id": _ISSUE,
        "idempotency_key": "fast-s2-commitment",
        "commitment": {
            "counterparty_entity_id": "ent_lineages2fast0001",
            "direction": "owed_to_principal",
            "summary": "Synthetic",
            "origin_evidence_ref": "cap_lineages2fast0001",
        },
    },
}
_SERVER_OWNED: Final = (
    "principal_id",
    "actor_class",
    "authority_class",
    "decision_channel",
    "acceptance_basis",
    "review_decision_id",
    "recorded_at",
    "closed_at",
    "selector",
    "exception",
    "override",
    "member_native_version",
)


def _arguments(name: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "req-lineage-s2-fast",
        "purpose": sorted(permitted_purposes(Capability(name)))[0].value,
        "principal_id": "prn_lineages2fast0001",
        "requested_at": "2026-10-18T12:00:00Z",
        "payload": payload,
    }


@pytest.mark.parametrize("name", sorted(_BASE_PAYLOADS))
def test_s2_requests_reject_server_owned_fields(name: str) -> None:
    base = _BASE_PAYLOADS[name]
    _metadata, command = normalize(name, _arguments(name, base))
    assert command.capability.value == name
    for field in _SERVER_OWNED:
        with pytest.raises(InvalidRequestError):
            normalize(name, _arguments(name, {**base, field: "server-owned"}))
    for key in ("closure_evidence_anchors", "evidence_anchors"):
        if key in base:
            for owned in ("version_no", "source_version_no", "anchor_id", "principal_id"):
                with pytest.raises(InvalidRequestError):
                    normalize(name, _arguments(name, {**base, key: [{**_ANCHOR, owned: 1}]}))
    for nested in ("task", "commitment"):
        if nested in base:
            # Inside the native object, every server-owned field is refused too
            # (`accepted_by_review_decision_id` is the Commitment's v1 field).
            for field in (*_SERVER_OWNED, "idempotency_key", "situation_id"):
                document = {**base[nested], field: "server-owned"}  # type: ignore[dict-item]
                with pytest.raises(InvalidRequestError):
                    normalize(name, _arguments(name, {**base, nested: document}))
    if name == "issues.close":
        # An empty closure set, a blank outcome and a state are refused by shape.
        for broken in (
            {**base, "closure_evidence_anchors": []},
            {**base, "outcome": "   "},
            {**base, "state": "closed"},
        ):
            with pytest.raises(InvalidRequestError):
                normalize(name, _arguments(name, broken))


def test_assert_admits_exactly_the_s2_relations_it_writes() -> None:
    """`records.associations.assert` widens to `escalated_from` and `blocks` only (S2 7.2).

    The published schema names every relation the assert writes and no
    creation relation (`delegated_from`, `created_to_resolve` are the
    composites' own); the request parses each S2 relation in its matrix pair
    and refuses one outside it before anything runs.
    """
    schema = AssertRecordAssociation.mcp_payload_properties["relation_type"]
    published = list(schema["enum"])  # type: ignore[index]
    assert published == ["blocks", "discusses", "escalated_from", "originated_from"]
    semantic = {relation.value for relation in RelationType} - {"issue_member"}
    assert set(published) == semantic - {relation.value for relation in COMPOSITE_ONLY_RELATIONS}
    anchor = {**_ANCHOR, "role": "corroborates"}
    payloads = {
        "escalated_from": (
            ("constraint", "cst_lineages2fast0001"),
            ("task", "tsk_lineages2fast0001"),
        ),
        "blocks": (("task", "tsk_lineages2fast0001"), ("constraint", "cst_lineages2fast0001")),
    }
    for relation, (source, target) in payloads.items():
        payload: dict[str, object] = {
            "from_record": {"family": source[0], "record_id": source[1]},
            "to_record": {"family": target[0], "record_id": target[1]},
            "relation_type": relation,
            "idempotency_key": f"fast-s2-assert-{relation}",
            "evidence_anchors": [anchor],
            "context_issue_id": _ISSUE,
        }
        name = "records.associations.assert"
        _metadata, command = normalize(name, _arguments(name, payload))
        assert isinstance(command, AssertRecordAssociation)
        assert command.lineage_request().relation_type.value == relation
        # The reverse escalation is outside the matrix; a reversed `blocks` is
        # another `blocks`.
        reverse = {
            **payload,
            "from_record": payload["to_record"],
            "to_record": payload["from_record"],
        }
        if relation == "escalated_from":
            with pytest.raises(InvalidRequestError):
                normalize(name, _arguments(name, reverse))
        for field in _SERVER_OWNED:
            with pytest.raises(InvalidRequestError):
                normalize(name, _arguments(name, {**payload, field: "server-owned"}))


def test_s1_lineage_views_keep_every_s1_key() -> None:
    """S1 keys keep their meaning; `IssueView` gains exactly `closure` (S2 section 7.1)."""
    assert set(IssueView.model_fields) == {
        "issue_id",
        "kind",
        "version",
        "state",
        "title",
        "description",
        "opened_at",
        "created_at",
        "updated_at",
        "project_links",
        "project_links_truncated",
        "closure",
    }
    assert set(IssueRevisionView.model_fields) == {
        "issue_id",
        "kind",
        "version",
        "state",
        "title",
        "description",
        "revision_id",
        "action",
        "opened_at",
        "created_at",
        "recorded_at",
    }
    assert set(IssueListEntry.model_fields) == {
        "issue_id",
        "version",
        "state",
        "title",
        "updated_at",
    }
    assert set(AssociationView.model_fields) == {
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
    assert set(IssueClosureView.model_fields) == {"version", "closed_at", "outcome", "evidence"}
    assert set(ClosureBlockerView.model_fields) == {
        "link_id",
        "member",
        "role",
        "native_state",
        "evidence_state",
        "reasons",
    }
    # No closure view carries a digest, and an anchor view still carries none.
    assert not any("digest" in name for name in IssueClosureView.model_fields)
    assert not any("sha256" in name for name in EvidenceAnchorView.model_fields)
    # A closed Issue is admitted where S1 admitted only three states.
    view = IssueListEntry(
        issue_id=_ISSUE,
        version=2,
        state="closed",
        title="Synthetic",
        updated_at=datetime(2026, 10, 18, tzinfo=UTC),
    )
    assert view.to_canonical_dict()["state"] == "closed"


# ---- the switch --------------------------------------------------------------


def _samples() -> dict[Capability, Command]:
    anchor = dict(_ANCHOR)
    return {
        Capability.ISSUES_CLOSE: CloseIssue(
            issue_id=_ISSUE,
            expected_version=1,
            idempotency_key="fast-s2-close",
            outcome="Resolved.",
            closure_evidence_anchors=(anchor,),
        ),
        Capability.ISSUES_REOPEN: ReopenIssue(
            issue_id=_ISSUE, expected_version=2, idempotency_key="fast-s2-reopen", reason="x"
        ),
        Capability.ISSUES_CLOSURE_READINESS: ReadIssueClosureReadiness(issue_id=_ISSUE),
        Capability.ISSUES_MEMBERSHIPS_CORRECT: CorrectIssueMembership(
            link_id=_LINK, expected_revision=1, idempotency_key="fast-s2-correct", reason="x"
        ),
        Capability.ISSUES_HANDOFFS_RECORD: RecordIssueHandoff(
            issue_id=_ISSUE,
            commitment_id=_COMMITMENT,
            from_side="counterparty",
            effective_at="2026-10-18T12:00:00+00:00",
            idempotency_key="fast-s2-handoff",
            reason="x",
            evidence_anchor={**anchor, "role": "handoff"},
        ),
        Capability.ISSUES_HANDOFFS_LIST: ListIssueHandoffs(issue_id=_ISSUE),
        Capability.ISSUES_WORK_CREATE_TASK: CreateIssueWorkTask(
            issue_id=_ISSUE,
            idempotency_key="fast-s2-task",
            task=dict(_BASE_PAYLOADS["issues.work.create_task"]["task"]),  # type: ignore[call-overload]
        ),
        Capability.ISSUES_WORK_CREATE_COMMITMENT: CreateIssueWorkCommitment(
            issue_id=_ISSUE,
            idempotency_key="fast-s2-commitment",
            commitment=dict(_BASE_PAYLOADS["issues.work.create_commitment"]["commitment"]),  # type: ignore[call-overload]
        ),
    }


def _lineage_service(scene: Scene) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(scene.world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        lineage_enabled=True,
    )


def _code(envelope: Any) -> str | None:  # noqa: ANN401
    error = envelope.to_canonical_dict().get("error")
    return None if error is None else str(error["code"])


def test_switch_off_withholds_every_s2_capability(scene: Scene) -> None:
    declared = _s2()
    off = build_service(scene.world, scene.providers)
    on = _lineage_service(scene)
    assert not off.available_capabilities & declared
    assert declared <= on.available_capabilities
    names = {capability.value for capability in declared}
    published_off = {tool.name for tool in published_tools(off, authenticated_client_present=True)}
    published_on = {tool.name for tool in published_tools(on, authenticated_client_present=True)}
    assert not published_off & names
    assert names <= published_on
    manifest = off.invoke(
        metadata_for(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION, scene.principal),
        GetCapabilities(),
        principal=scene.principal,
    ).to_canonical_dict()["result"]
    assert isinstance(manifest, dict)
    availability = {
        row["name"]: row["availability"] for row in manifest["manifest"]["capabilities"]
    }
    assert {availability[name] for name in names} == {"not_implemented"}
    samples = _samples()
    assert set(samples) == declared
    for capability, command in samples.items():
        # The switch first: a stamped operator surface still answers `unsupported`.
        envelope = off.invoke(
            metadata_for(capability, sorted(permitted_purposes(capability))[0], scene.principal),
            command,
            principal=scene.principal,
            operator_surface=OperatorSurface.HTTP_GATEWAY,
        )
        assert _code(envelope) == "unsupported", capability.value


# ---- the composites and the v1 shapes ---------------------------------------------


def _names(shape: type) -> frozenset[str]:
    if dataclasses.is_dataclass(shape):
        return frozenset(item.name for item in dataclasses.fields(shape))
    return frozenset(shape.model_fields)  # type: ignore[attr-defined]


#: The v1 Work create requests and views at the S2 basis (S2 contract section 8).
_V1_TASK_CREATE: Final = frozenset(
    {
        "title",
        "idempotency_key",
        "origin_kind",
        "origin_evidence_ref",
        "description",
        "priority",
        "due_at",
        "project_id",
        "situation_id",
        "accepted_by_review_decision_id",
        "commitment_id",
        "role",
        "client_context",
    }
)
_V1_COMMITMENT_CREATE: Final = frozenset(
    {
        "counterparty_entity_id",
        "direction",
        "summary",
        "origin_evidence_ref",
        "idempotency_key",
        "due_at",
        "project_id",
        "situation_id",
        "accepted_by_review_decision_id",
        "client_context",
    }
)
_V1_TASK_VIEW: Final = frozenset(
    {
        "acceptance_kind",
        "accepted_by_review_decision_id",
        "archived_at",
        "closed_at",
        "closure_evidence_capture_state",
        "closure_evidence_ref",
        "closure_history_id",
        "commitment_id",
        "created_at",
        "deferred_until",
        "description",
        "due_at",
        "evidence_state",
        "lifecycle_state",
        "opened_at",
        "origin_evidence_capture_state",
        "origin_evidence_ref",
        "origin_kind",
        "priority",
        "project_id",
        "recurrence_id",
        "role",
        "scheduled_at",
        "situation_id",
        "task_id",
        "title",
        "updated_at",
        "version",
    }
)
_V1_COMMITMENT_VIEW: Final = frozenset(
    {
        "accepted_by_review_decision_id",
        "closed_at",
        "closure_evidence_capture_state",
        "closure_evidence_ref",
        "commitment_id",
        "counterparty_entity_id",
        "created_at",
        "description",
        "direction",
        "due_date",
        "evidence_state",
        "origin_evidence_capture_state",
        "origin_evidence_ref",
        "state",
        "title",
        "updated_at",
        "version",
    }
)


def test_existing_v1_shapes_are_unchanged_by_s2() -> None:
    """No v1 Work request or view gains, loses or re-means a field (section 8)."""
    assert _names(CreateTask) == _V1_TASK_CREATE
    assert _names(CreateCommitment) == _V1_COMMITMENT_CREATE
    assert _names(TaskView) == _V1_TASK_VIEW
    assert _names(CommitmentView) == _V1_COMMITMENT_VIEW
    # The published v1 tools are the same shapes: required fields included.
    task_schema = payload_schema_for(CreateTask)
    commitment_schema = payload_schema_for(CreateCommitment)
    assert set(task_schema["properties"]) == _V1_TASK_CREATE
    assert set(task_schema["required"]) == {"title", "idempotency_key"}
    assert set(commitment_schema["properties"]) == _V1_COMMITMENT_CREATE
    assert set(commitment_schema["required"]) == {
        "counterparty_entity_id",
        "direction",
        "summary",
        "origin_evidence_ref",
        "idempotency_key",
    }
    # The v1 commands' own capability names: a composite is a new name, not a mode.
    assert CreateTask.capability is Capability.TASKS_CREATE
    assert CreateCommitment.capability is Capability.COMMITMENTS_CREATE
    # The handoff view's keys (S2 section 7.1), with `from`/`to` on the wire.
    assert _names(HandoffView) == {
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
    }
    assert _names(HandoffHolderView) == {"kind", "entity_id"}


def _wire(schema: dict[str, Any]) -> dict[str, Any]:
    """A property's wire shape: what a caller may send, without its prose."""
    return {key: value for key, value in schema.items() if key in {"type", "enum", "format"}}


def test_composite_native_objects_mirror_the_v1_requests() -> None:
    """Each nested object is its v1 create request less exactly the refused fields."""
    for composite, nested, v1, refused in (
        (
            CreateIssueWorkTask,
            "task",
            CreateTask,
            {"idempotency_key", "situation_id", "accepted_by_review_decision_id"},
        ),
        (
            CreateIssueWorkCommitment,
            "commitment",
            CreateCommitment,
            {"idempotency_key", "situation_id"},
        ),
    ):
        v1_schema = payload_schema_for(v1)
        published = payload_schema_for(composite)["properties"][nested]
        assert published["type"] == "object"
        assert published["additionalProperties"] is False
        assert set(v1_schema["properties"]) - set(published["properties"]) == refused
        assert set(published["properties"]) <= set(v1_schema["properties"])
        assert set(published["required"]) == set(v1_schema["required"]) - refused
        for name, shape in published["properties"].items():
            assert _wire(shape) == _wire(v1_schema["properties"][name]), (nested, name)
    # The nested object is built by the v1 command class itself.
    command = CreateIssueWorkTask(
        issue_id=_ISSUE,
        idempotency_key="fast-s2-mirror",
        task={"title": "Synthetic", "origin_kind": "direct_principal", "priority": "p2"},
    )
    native = command.native_command()
    assert isinstance(native, CreateTask)
    assert native.idempotency_key == "fast-s2-mirror"
    assert native.situation_id is None and native.accepted_by_review_decision_id is None


def _refusal(name: str, payload: dict[str, object]) -> tuple[object, ...]:
    """How `normalize` refuses a payload: the error class, its safe details and choices."""
    with pytest.raises(ApplicationError) as refused:
        normalize(name, _arguments(name, payload))
    error = refused.value
    return (type(error), error.safe_details, dict(error.allowed_values))


#: Malformed values for the nested native fields the composites convert themselves.
_MALFORMED: Final[dict[str, tuple[tuple[str, object], ...]]] = {
    "task": (
        ("due_at", "not-a-time"),
        ("due_at", "2026-10-18T12:00:00"),
        ("due_at", 17),
        ("priority", "urgent"),
        ("priority", 3),
        ("role", "boss"),
        ("origin_kind", "rumour"),
        ("origin_kind", None),
        ("title", ""),
    ),
    "commitment": (
        ("due_at", "not-a-time"),
        ("due_at", "2026-10-18T12:00:00"),
        ("direction", "sideways"),
        ("direction", None),
        ("summary", ""),
        ("counterparty_entity_id", "ent_not valid"),
    ),
}


@pytest.mark.parametrize(
    ("composite", "nested", "v1"),
    [
        ("issues.work.create_task", "task", "tasks.create"),
        ("issues.work.create_commitment", "commitment", "commitments.create"),
    ],
)
def test_composite_native_objects_refuse_malformed_values_like_the_v1_requests(
    composite: str, nested: str, v1: str
) -> None:
    """The composite's own conversion refuses exactly as the v1 normalizer does (FR2-F05)."""
    base = _BASE_PAYLOADS[composite]
    native = dict(base[nested])  # type: ignore[call-overload]
    normalize(v1, _arguments(v1, {**native, "idempotency_key": "fast-s2-v1"}))
    for field, value in _MALFORMED[nested]:
        broken = {**native, field: value}
        expected = _refusal(v1, {**broken, "idempotency_key": "fast-s2-v1"})
        assert _refusal(composite, {**base, nested: broken}) == expected, (field, value)
