"""AT-023 (S3): the record lineage S3 capabilities are admitted as the contract states.

FAST, against the composed service and the identity registries. Worker L1's
part of the S3 contract section 10 row (registration, section 7 and 7.7):

* the six lineage reads and writes are `CHATLLM_DATA_CONDITIONAL` under the
  `LINEAGE` prerequisite (P1 client exposure, chatllm-data-v10), scopeless,
  the `lineage` feature, writes keyed and attested, under their section 7
  purposes;
* the two backfill capabilities are operator-only and
  `CHATLLM_CONTROL_PLANE_EXCLUDED` under their own `lineage_backfill` purpose;
* the backfill sub-switch withholds both unless `lineage_enabled` and
  `lineage_backfill_enabled` are both on, and each backfill handler answers
  `unsupported` while it is off, whatever the lineage switch says;
* `lineage_enabled` off withholds all eight and answers `unsupported` first;
* no S3 request admits a server-owned field.

Worker L6's part (sections 7.6 and 8.1):

* every v1 request shape (each published non-lineage tool's payload schema)
  and every v1 view's keys are byte-identical to the S2 basis;
* every S1/S2 lineage view keeps every key, and gains exactly the section 8.1
  additions;
* a `records.lineage` request without the S3 fields is the S1 single-page
  read, answered with exactly the 5 added top-level keys and 2 node keys;
* the web lineage routes call exactly the capabilities the MCP transport
  serves, with payload fields each published tool admits.

Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import importlib
import inspect
import json
import re
from pathlib import Path
from typing import Any, Final

import pytest
from pydantic import BaseModel
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
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import _IDEMPOTENT_REMOTE_CAPABILITIES
from my_pa.application.commands import Command, ReadRecordLineage
from my_pa.application.errors import InvalidRequestError
from my_pa.application.record_lineage import LineageReadRequest, traverse_lineage
from my_pa.application.service import (
    _LINEAGE_BACKFILL_CAPABILITIES,
    _LINEAGE_CAPABILITIES,
    ApplicationService,
)
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
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
from my_pa.domain.lineage.vocabulary import (
    LINEAGE_BACKFILL_CAPABILITIES,
    LINEAGE_WRITE_CAPABILITIES,
)
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.program.vocabulary import PROGRAM_REPORTING_CAPABILITIES

S3_NAMES: Final = frozenset(
    {
        "records.associations.contest",
        "records.associations.reinstate",
        "records.associations.history",
        "issues.history",
        "issues.timeline",
        "issues.handoffs.correct",
        "records.backfill.plan",
        "records.backfill.report",
    }
)
_BACKFILL: Final = frozenset({"records.backfill.plan", "records.backfill.report"})
_WRITES: Final = frozenset(
    {
        "records.associations.contest",
        "records.associations.reinstate",
        "issues.handoffs.correct",
        "records.backfill.plan",
    }
)
_ADDITIVE: Final = frozenset({"records.backfill.plan"})
_PURPOSES: Final = {
    "records.associations.contest": Purpose.RECORD_LINEAGE_AUTHORING,
    "records.associations.reinstate": Purpose.RECORD_LINEAGE_AUTHORING,
    "records.associations.history": Purpose.RECORD_LINEAGE_READ,
    "issues.history": Purpose.ISSUE_READ,
    "issues.timeline": Purpose.ISSUE_READ,
    "issues.handoffs.correct": Purpose.ISSUE_AUTHORING,
    "records.backfill.plan": Purpose.LINEAGE_BACKFILL,
    "records.backfill.report": Purpose.LINEAGE_BACKFILL,
}
_ANCHOR: Final[dict[str, object]] = {
    "family": "meeting_note_version",
    "root_id": "mtg_lineages3fast0001",
    "version_kind": "immutable_version",
    "version_id": "mnote_lineages3fast0001",
    "source_sha256": "a" * 64,
    "role": "contradicts",
}
_BASE_PAYLOADS: Final[dict[str, dict[str, object]]] = {
    "records.associations.contest": {
        "link_id": "irl_lineages3fast0001",
        "expected_revision": 1,
        "idempotency_key": "fast-s3-contest",
        "reason": "Disputed.",
        "evidence_anchors": [_ANCHOR],
    },
    "records.associations.reinstate": {
        "link_id": "irl_lineages3fast0001",
        "expected_revision": 2,
        "idempotency_key": "fast-s3-reinstate",
        "reason": "Resolved.",
        "evidence_anchors": [{**_ANCHOR, "role": "corroborates"}],
    },
    "records.associations.history": {"link_id": "irl_lineages3fast0001"},
    "issues.history": {"issue_id": "sit_lineages3fast0001"},
    "issues.timeline": {"issue_id": "sit_lineages3fast0001"},
    "issues.handoffs.correct": {
        "handoff_id": "ihnd_lineages3fast0001",
        "action": "void",
        "reason": "It did not happen.",
        "evidence_anchor": _ANCHOR,
        "idempotency_key": "fast-s3-correct",
    },
    "records.backfill.plan": {"idempotency_key": "fast-s3-plan"},
    "records.backfill.report": {"run_id": "lbfr_lineages3fast0001"},
}
_SERVER_OWNED: Final = (
    "principal_id",
    "actor_class",
    "authority_class",
    "decision_channel",
    "acceptance_basis",
    "recorded_at",
    "commit_seq",
    "marked_at",
    "grant",
    "selector",
)


def _s3() -> frozenset[Capability]:
    return frozenset(capability for capability in Capability if capability.value in S3_NAMES)


def _arguments(name: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "req-lineage-s3-fast",
        "purpose": sorted(permitted_purposes(Capability(name)))[0].value,
        "principal_id": "prn_lineages3fast0001",
        "requested_at": "2026-10-19T12:00:00Z",
        "payload": payload,
    }


def _command(name: str) -> Command:
    _metadata, command = normalize(name, _arguments(name, _BASE_PAYLOADS[name]))
    return command


def _service(scene: Scene, *, lineage: bool, backfill: bool) -> ApplicationService:
    return ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(scene.world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        lineage_enabled=lineage,
        lineage_backfill_enabled=backfill,
    )


def _code(envelope: Any) -> str | None:  # noqa: ANN401
    error = envelope.to_canonical_dict().get("error")
    return None if error is None else str(error["code"])


def _invoke(service: ApplicationService, scene: Scene, name: str) -> Any:  # noqa: ANN401
    capability = Capability(name)
    return service.invoke(
        metadata_for(capability, sorted(permitted_purposes(capability))[0], scene.principal),
        _command(name),
        principal=scene.principal,
        operator_surface=OperatorSurface.HTTP_GATEWAY,
    )


def test_s3_capabilities_are_operator_decision_required() -> None:
    declared = _s3()
    assert {capability.value for capability in declared} == S3_NAMES
    assert declared <= _LINEAGE_CAPABILITIES
    # Record lineage S3.1 adds its 4 names to the same switch set, 30 -> 34.
    assert len(_LINEAGE_CAPABILITIES) == 34
    for capability in declared:
        name = capability.value
        assert capability in _SCOPELESS
        assert _FEATURE_BY_FAMILY[name.split(".", 1)[0]] == "lineage"
        assert permitted_purposes(capability) == frozenset({_PURPOSES[name]})
        writes = name in _WRITES
        assert is_write_capability(capability) is writes
        assert is_destructive_capability(capability) is (writes and name not in _ADDITIVE)
        assert (capability in _IDEMPOTENT_REMOTE_CAPABILITIES) is writes
        assert (name in LINEAGE_WRITE_CAPABILITIES) is writes
        if name in _BACKFILL:
            continue
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        # P1 client exposure (operator directive 2026-10-26, chatllm-data-v10):
        # the ChatLLM decision is made; the 6 are plane-conditional data.
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.LINEAGE
        assert policy.exclusion_rationale is None
        assert not is_operator_only(capability)
    # P1 moved data-class members, so the ChatLLM data profile moved too.
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v10"


def test_backfill_capabilities_are_operator_only_and_control_plane_excluded() -> None:
    backfill = frozenset(Capability(name) for name in _BACKFILL)
    assert backfill == _LINEAGE_BACKFILL_CAPABILITIES
    assert {capability.value for capability in backfill} == LINEAGE_BACKFILL_CAPABILITIES
    for capability in backfill:
        assert is_operator_only(capability)
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
        assert policy.exclusion_rationale == "operator-only lineage backfill"
    # Their purpose is their own: no lineage or Issue grant becomes a backfill.
    using = {
        capability.value
        for capability in Capability
        if Purpose.LINEAGE_BACKFILL in permitted_purposes(capability)
    }
    assert using == _BACKFILL
    assert Purpose.LINEAGE_BACKFILL in remote_mcp._WRITE_PURPOSES


@pytest.mark.parametrize(("lineage", "backfill"), [(True, False), (False, True), (False, False)])
def test_the_backfill_sub_switch_withholds_both_backfill_capabilities(
    scene: Scene, lineage: bool, backfill: bool
) -> None:
    withheld = _service(scene, lineage=lineage, backfill=backfill)
    served = _service(scene, lineage=True, backfill=True)
    backfill_names = _LINEAGE_BACKFILL_CAPABILITIES
    assert not withheld.available_capabilities & backfill_names
    assert backfill_names <= served.available_capabilities
    published = {tool.name for tool in published_tools(withheld, authenticated_client_present=True)}
    assert not published & _BACKFILL
    # Enabling lineage alone never serves a backfill: the other S3 names follow
    # the lineage switch only.
    others = _s3() - backfill_names
    assert (others <= withheld.available_capabilities) is lineage
    for name in sorted(_BACKFILL):
        assert _code(_invoke(withheld, scene, name)) == "unsupported", name


def test_switch_off_withholds_every_s3_capability(scene: Scene) -> None:
    declared = _s3()
    off = build_service(scene.world, scene.providers)
    on = _service(scene, lineage=True, backfill=True)
    assert not off.available_capabilities & declared
    assert declared <= on.available_capabilities
    names = {capability.value for capability in declared}
    published_off = {tool.name for tool in published_tools(off, authenticated_client_present=True)}
    published_on = {tool.name for tool in published_tools(on, authenticated_client_present=True)}
    assert not published_off & names
    assert names <= published_on
    for name in sorted(names):
        # The switch first: a stamped operator surface still answers `unsupported`.
        assert _code(_invoke(off, scene, name)) == "unsupported", name


@pytest.mark.parametrize("name", sorted(_BASE_PAYLOADS))
def test_s3_requests_reject_server_owned_fields(name: str) -> None:
    base = _BASE_PAYLOADS[name]
    command = _command(name)
    assert command.capability.value == name
    for field in _SERVER_OWNED:
        with pytest.raises(InvalidRequestError):
            normalize(name, _arguments(name, {**base, field: "server-owned"}))
    if "evidence_anchors" in base:
        for owned in ("version_no", "source_version_no", "anchor_id", "principal_id"):
            with pytest.raises(InvalidRequestError):
                normalize(
                    name, _arguments(name, {**base, "evidence_anchors": [{**_ANCHOR, owned: 1}]})
                )


# ---- L6: the v1 and S1/S2 shapes, the S1 read, the web routes (sections 7.6, 8.1) ----

#: SHA-256 of every published non-lineage tool's payload schema (name -> the
#: `payload` property of its input schema, canonical JSON), measured at the S2
#: basis `84ddab37` and unchanged at the S3 head: S3 changes no v1 request.
_V1_PAYLOAD_SCHEMA_SHA256: Final = (
    "e87a5186273905f60ae033764f70d6715cb01829a56a19e77409ab2d2de63ebb"
)
#: The v1 view modules and the SHA-256 of their models' field names
#: (`module.Model` -> sorted field names, canonical JSON), measured alike.
_V1_VIEW_MODULES: Final = (
    "tasks",
    "commitments",
    "meetings",
    "record_events",
    "capture",
    "canvas_workspace",
    "documents",
    "reveal",
    "status",
    "capabilities",
)
_V1_VIEW_FIELDS_SHA256: Final = "dff6d5a7482e860134079775c898014ed6b14342fd04164eeae2112d2babc32a"


def _canonical_sha256(document: object) -> str:
    return hashlib.sha256(
        json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def test_existing_v1_shapes_are_unchanged_by_s3() -> None:
    lineage = {capability.value for capability in _LINEAGE_CAPABILITIES}
    # Record lineage S4 (S4 contract section 10): its 7 names are excluded
    # beside the lineage names; the count and both pins stay.
    lineage |= PROGRAM_REPORTING_CAPABILITIES
    payloads = {
        tool.name: tool.input_schema["properties"]["payload"]
        for tool in TOOLS
        if tool.name not in lineage
    }
    assert len(payloads) == 192
    assert _canonical_sha256(payloads) == _V1_PAYLOAD_SCHEMA_SHA256
    views: dict[str, list[str]] = {}
    for name in _V1_VIEW_MODULES:
        module = importlib.import_module(f"my_pa.contracts.v1.{name}")
        for model_name, model in vars(module).items():
            if (
                inspect.isclass(model)
                and issubclass(model, BaseModel)
                and model.__module__ == module.__name__
            ):
                views[f"{name}.{model_name}"] = sorted(model.model_fields)
    assert len(views) == 38
    assert _canonical_sha256(views) == _V1_VIEW_FIELDS_SHA256
    # The envelope's `purpose` enum is the one v1 schema S3 widens, and only by
    # its own backfill purpose (section 7.7); S4 widens it by exactly its one
    # Program purpose after it (S4 contract sections 8 and 10, R4-F04, R4-F15).
    basis_tail = ["record_lineage_authoring", "meeting_note_history_read", "issue_work_authoring"]
    published = TOOLS[0].input_schema["$defs"]["Purpose"]["enum"]
    assert published[-5:] == [*basis_tail, "lineage_backfill", "program_reporting_read"]


#: Every S1/S2 lineage view's keys at the S2 basis (`84ddab37`).
_S2_BASIS_VIEW_KEYS: Final[dict[str, frozenset[str]]] = {
    "AssociationView": frozenset(
        {
            "acceptance_basis",
            "authority_class",
            "context_issue_id",
            "created_at",
            "evidence",
            "from_ref",
            "kind",
            "lifecycle_state",
            "link_id",
            "member_role",
            "recorded_at",
            "relation_type",
            "revision_no",
            "to_ref",
        }
    ),
    "ClosureBlockerView": frozenset(
        {"evidence_state", "link_id", "member", "native_state", "reasons", "role"}
    ),
    "EvidenceAnchorView": frozenset(
        {
            "anchor_id",
            "availability",
            "family",
            "passage_end_cp",
            "passage_start_cp",
            "role",
            "root_id",
            "source_version_no",
            "version_id",
            "version_kind",
        }
    ),
    "HandoffHolderView": frozenset({"entity_id", "kind"}),
    "HandoffView": frozenset(
        {
            "acceptance_basis",
            "authority_class",
            "commitment_id",
            "effective_at",
            "evidence",
            "from_holder",
            "handoff_id",
            "issue_id",
            "reason",
            "recorded_at",
            "sequence_no",
            "to_holder",
        }
    ),
    "IssueClosureView": frozenset({"closed_at", "evidence", "outcome", "version"}),
    "IssueListEntry": frozenset({"issue_id", "state", "title", "updated_at", "version"}),
    "IssueReopeningView": frozenset({"evidence", "reason"}),
    "IssueRevisionView": frozenset(
        {
            "action",
            "created_at",
            "description",
            "issue_id",
            "kind",
            "opened_at",
            "recorded_at",
            "revision_id",
            "state",
            "title",
            "version",
        }
    ),
    "IssueView": frozenset(
        {
            "closure",
            "created_at",
            "description",
            "issue_id",
            "kind",
            "opened_at",
            "project_links",
            "project_links_truncated",
            "state",
            "title",
            "updated_at",
            "version",
        }
    ),
    "LineageIssueMatch": frozenset({"issue_id", "state", "title"}),
    "LineageNodeView": frozenset(
        {"availability", "depth", "family", "meeting_id", "record_id", "state", "title"}
    ),
    "LineageView": frozenset(
        {
            "complete_state",
            "issues_matching_root",
            "next_cursor",
            "nodes",
            "root",
            "selected_issue_id",
            "typed_edges",
            "virtual_native_edges",
        }
    ),
    "ProjectLinkView": frozenset(
        {
            "acceptance_basis",
            "evidence_anchor_id",
            "membership_revision_no",
            "project_id",
            "project_situation_id",
            "recorded_at",
            "state",
        }
    ),
    "RecordRefView": frozenset({"family", "record_id"}),
    "VirtualEdgeView": frozenset({"edge_type", "from_ref", "to_ref"}),
}
#: Section 8.1: the only keys S3 adds to an S1/S2 view.
_S3_VIEW_ADDITIONS: Final[dict[str, frozenset[str]]] = {
    "HandoffView": frozenset({"current_effective_at", "voided", "correction_ids"}),
    "LineageNodeView": frozenset({"reached_from", "reached_via"}),
    "LineageView": frozenset(
        {"qualifiers", "known_at", "valid_at", "lineage_valid_at", "native_cut_at"}
    ),
}
#: S3.1 contract section 7.6 (an admitted lockstep edit, S3.1 section 10.1): the
#: provenance labels S3.1 adds beside the S3 additions; the subset assertion stays.
_S31_LABELS: Final = frozenset({"user_directed_claim", "asserting_client_id"})
_S31_VIEW_ADDITIONS: Final[dict[str, frozenset[str]]] = {
    "AssociationView": _S31_LABELS,
    "ProjectLinkView": _S31_LABELS,
    "HandoffView": _S31_LABELS,
}


def test_s1_and_s2_views_keep_every_key() -> None:
    modules = [
        importlib.import_module("my_pa.contracts.v1.issues"),
        importlib.import_module("my_pa.contracts.v1.record_lineage"),
    ]
    views = {
        name: model
        for module in modules
        for name, model in vars(module).items()
        if inspect.isclass(model)
        and issubclass(model, BaseModel)
        and model.__module__ == module.__name__
    }
    for name, basis in _S2_BASIS_VIEW_KEYS.items():
        keys = frozenset(views[name].model_fields)
        assert basis <= keys, f"{name} lost {sorted(basis - keys)}"
        assert keys - basis == _S3_VIEW_ADDITIONS.get(name, frozenset()) | _S31_VIEW_ADDITIONS.get(
            name, frozenset()
        ), name


#: S1 contract section 7.2: the top-level and node keys of an S1 answer.
_S1_LINEAGE_KEYS: Final = frozenset(
    {
        "root",
        "selected_issue_id",
        "issues_matching_root",
        "nodes",
        "typed_edges",
        "virtual_native_edges",
        "complete_state",
        "next_cursor",
    }
)
_S1_NODE_KEYS: Final = frozenset(
    {"family", "record_id", "depth", "meeting_id", "title", "state", "availability"}
)


def test_records_lineage_without_s3_fields_keeps_the_s1_answer() -> None:
    from tests.contract.test_lineage_read_contract import _ISSUE, _PRINCIPAL, _fixture

    _metadata, command = normalize(
        "records.lineage",
        _arguments(
            "records.lineage",
            {"origin": {"family": "situation", "record_id": _ISSUE.record_id}},
        ),
    )
    assert isinstance(command, ReadRecordLineage)
    request = command.lineage_request()
    # No cut, no page: the S1 single-page read (section 7.2 step 6).
    assert (request.known_at, request.valid_at, request.page_size, request.cursor) == (
        None,
        None,
        None,
        None,
    )
    assert request == LineageReadRequest(origin=_ISSUE, issue_id=None, max_depth=4)
    answer = traverse_lineage(_fixture(), _PRINCIPAL, request).to_canonical_dict()
    assert set(answer) == _S1_LINEAGE_KEYS | _S3_VIEW_ADDITIONS["LineageView"]
    assert answer["next_cursor"] is None
    assert answer["complete_state"] == "complete"
    assert answer["qualifiers"] == ["complete"]
    assert answer["nodes"]
    for node in answer["nodes"]:
        assert {"family", "record_id", "depth", "reached_from", "reached_via"} <= set(node)
        assert set(node) - _S1_NODE_KEYS == _S3_VIEW_ADDITIONS["LineageNodeView"]
    assert {edge["link_id"] for edge in answer["typed_edges"]} == {
        "irl_readlink000001",
        "irl_readlink000002",
        "irl_readlink000003",
    }


_WEB_API: Final = Path(__file__).resolve().parents[2] / "web" / "src" / "app" / "api"
#: Section 7.6 (and S1 section 7.4): each lineage BFF route, the one capability
#: it calls, and the payload members it fixes itself (beside its query fields).
_LINEAGE_ROUTES: Final[dict[str, tuple[str, frozenset[str]]]] = {
    "issues/route.ts": ("issues.list", frozenset()),
    "issues/[issueId]/route.ts": ("issues.read", frozenset({"issue_id"})),
    "issues/[issueId]/timeline/route.ts": ("issues.timeline", frozenset({"issue_id"})),
    "issues/[issueId]/lineage/route.ts": ("records.lineage", frozenset({"origin", "issue_id"})),
    "records/[family]/[recordId]/related-issues/route.ts": (
        "records.lineage",
        frozenset({"origin", "max_depth"}),
    ),
    "meetings/[meetingId]/notes/[noteVersionId]/route.ts": (
        "meetings.notes.read_version",
        frozenset({"meeting_id", "note_version_id"}),
    ),
}
_WORK_GET: Final = re.compile(r"workGet\(\s*request,\s*[^,]+,\s*\"([a-z_.]+)\"")
_GATEWAY_FIELD: Final = re.compile(r"gateway:\s*\"([a-z_]+)\"")


def test_the_web_routes_call_exactly_the_capabilities_mcp_serves(scene: Scene) -> None:
    on = _service(scene, lineage=True, backfill=False)
    served = {tool.name: tool for tool in published_tools(on, authenticated_client_present=True)}
    called: set[str] = set()
    for path, (capability, fixed) in _LINEAGE_ROUTES.items():
        source = (_WEB_API / path).read_text(encoding="utf-8")
        assert _WORK_GET.findall(source) == [capability], path
        called.add(capability)
        admitted = set(served[capability].input_schema["properties"]["payload"]["properties"])
        for name in fixed:
            assert re.search(rf"[{{,]\s*{name}:", source), f"{path} does not fix {name}"
        sent = set(_GATEWAY_FIELD.findall(source)) | fixed
        assert sent, path
        assert sent <= admitted, f"{path} sends {sorted(sent - admitted)}"
    assert called == {
        "issues.list",
        "issues.read",
        "issues.timeline",
        "records.lineage",
        "meetings.notes.read_version",
    }
    # Each is a lineage read the MCP transport serves under the switch, and none
    # is served with the switch off (the web views render nothing then).
    off = build_service(scene.world, scene.providers)
    unserved = {tool.name for tool in published_tools(off, authenticated_client_present=True)}
    assert not called & unserved
    assert all(not is_write_capability(Capability(name)) for name in called)
