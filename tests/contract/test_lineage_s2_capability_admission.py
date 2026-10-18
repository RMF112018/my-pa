"""Record lineage S2 capability admission and compatibility (AT-023, FAST).

S2 contract sections 6.1, 7, 7.1, 7.5 and 8:

* every S2 name is `CHATLLM_OPERATOR_DECISION_REQUIRED` with the S2 rationale,
  scopeless, not operator-only, in the `lineage` gateway feature; the six
  writes are writes and idempotent remotely, the three additive ones additive;
* `issue_work_authoring` is the composites' own remote-write purpose and no
  other capability's;
* the close, reopen, readiness and membership-correction requests refuse every
  server-owned field, an exception/override field and any unknown key;
* the S1 Issue and association views keep every S1 key; `IssueView` gains
  exactly `closure`;
* `lineage_enabled` off withholds all eight S2 names from the published surface
  and answers `unsupported` to each, before authority.

The composite native-object mirror and the v1 shape freeze for the composite
writers are the composite worker's (S2 contract section 9, K2). Every
identity here is synthetic.
"""

from __future__ import annotations

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
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import _IDEMPOTENT_REMOTE_CAPABILITIES
from my_pa.application.commands import (
    CloseIssue,
    Command,
    CorrectIssueMembership,
    CreateIssueWorkCommitment,
    CreateIssueWorkTask,
    GetCapabilities,
    ListIssueHandoffs,
    ReadIssueClosureReadiness,
    RecordIssueHandoff,
    ReopenIssue,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.application.service import _LINEAGE_CAPABILITIES, ApplicationService
from my_pa.contracts.v1.issues import (
    ClosureBlockerView,
    IssueClosureView,
    IssueListEntry,
    IssueRevisionView,
    IssueView,
)
from my_pa.contracts.v1.record_lineage import AssociationView, EvidenceAnchorView
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
    if name == "issues.close":
        # An empty closure set, a blank outcome and a state are refused by shape.
        for broken in (
            {**base, "closure_evidence_anchors": []},
            {**base, "outcome": "   "},
            {**base, "state": "closed"},
        ):
            with pytest.raises(InvalidRequestError):
                normalize(name, _arguments(name, broken))


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
            issue_id=_ISSUE, idempotency_key="fast-s2-task", task={"title": "x"}
        ),
        Capability.ISSUES_WORK_CREATE_COMMITMENT: CreateIssueWorkCommitment(
            issue_id=_ISSUE, idempotency_key="fast-s2-commitment", commitment={"summary": "x"}
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
