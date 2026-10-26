"""Record lineage S1 capability admission and old-client compatibility (AT-023, FAST).

S1 contract sections 6.1, 7, 7.5 and 8, for the names the Issue slice declares
(the six Issue-plane names) and the compatibility rule every S1 slice inherits:

* every declared S1 name is `CHATLLM_OPERATOR_DECISION_REQUIRED`, scopeless,
  not operator-only, in the `lineage` gateway feature, and in no ChatLLM data
  profile;
* an S1 request refuses every server-owned field;
* `lineage_enabled` off withholds every declared S1 name from the published
  surface and answers `unsupported` to an invocation;
* `continuity.situations` keeps its exact keys and lists context Situations
  only, and `context.prepare` never offers an Issue `situation_id`;
* the lineage authority derivation never reads the Knowledge allowlists.

`test_note_body_needs_the_history_purpose` covers `meetings.notes.read_version`. The
switch test's name set grows with each slice: it reads the declared part of the
contract's fourteen-name set, so a name declared later is covered the moment it
exists. Every identity here is synthetic.
"""

from __future__ import annotations

import json
from dataclasses import replace
from types import SimpleNamespace
from typing import Any, Final

import pytest
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeUnitOfWork,
    Scene,
    build_service,
    metadata_for,
    staged_situation,
)

from my_pa.adapters.mcp import remote as remote_mcp
from my_pa.adapters.mcp.chatllm_gateway import _FEATURE_BY_FAMILY
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.mcp.tools import payload_schema_for
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import _IDEMPOTENT_REMOTE_CAPABILITIES
from my_pa.application.commands import (
    AddIssueMembership,
    AddIssueProjectLink,
    AssertRecordAssociation,
    Command,
    CorrectRecordAssociation,
    CreateCommitment,
    CreateIssue,
    CreateSituation,
    CreateTask,
    EndIssueMembership,
    EndIssueProjectLink,
    EndRecordAssociation,
    GetCapabilities,
    ListIssues,
    ListMeetingNoteVersions,
    ListSituations,
    PrepareContext,
    ReadIssue,
    ReadMeeting,
    ReadMeetingNoteVersion,
    ReadRecordLineage,
    RecordTask,
    UpdateIssue,
)
from my_pa.application.errors import DeniedError, InvalidRequestError
from my_pa.application.lineage_authority import attested_lineage_authority, lineage_authority
from my_pa.application.service import (
    _LINEAGE_CAPABILITIES,
    _LINEAGE_CAPABILITY_NAMES,
    ApplicationService,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
    is_chatllm_data_management,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.lineage.vocabulary import SituationKind
from my_pa.domain.policy.decision import _SCOPELESS

#: The contract's exact S1 set (section 7), restated here as the reviewed list.
S1_NAMES: Final = frozenset(
    {
        "issues.create",
        "issues.read",
        "issues.list",
        "issues.update",
        "issues.project_links.add",
        "issues.project_links.end",
        "issues.memberships.add",
        "issues.memberships.end",
        "records.associations.assert",
        "records.associations.correct",
        "records.associations.end",
        "records.lineage",
        "meetings.notes.versions",
        "meetings.notes.read_version",
    }
)
_S1_WRITES: Final = frozenset(
    {
        "issues.create",
        "issues.update",
        "issues.project_links.add",
        "issues.project_links.end",
        "issues.memberships.add",
        "issues.memberships.end",
        "records.associations.assert",
        "records.associations.correct",
        "records.associations.end",
    }
)
_S1_ADDITIVE: Final = frozenset(
    {
        "issues.create",
        "issues.project_links.add",
        "issues.memberships.add",
        "records.associations.assert",
    }
)
_RATIONALE: Final = "record lineage S1; exposure is an operator decision (ADR-015, OD-07)"
_ISSUE: Final = "sit_lineagefast00001"
_PROJECT: Final = "prj_lineagefast00001"
_TASK: Final = "tsk_lineagefast00001"
_COMMITMENT: Final = "cmt_lineagefast00001"
_MEETING: Final = "mtg_lineagefast00001"
_NOTE: Final = "mnote_lineagefast00001"
_LINK: Final = "irl_lineagefast00001"
_PASSAGE_ANCHOR: Final[dict[str, object]] = {
    "family": "meeting_note_version",
    "root_id": _MEETING,
    "version_kind": "immutable_version",
    "version_id": _NOTE,
    "source_sha256": "a" * 64,
    "passage_start_cp": 0,
    "passage_end_cp": 4,
    "passage_sha256": "b" * 64,
    "role": "origin",
}
_CLIENT: Final = "synthetic-lineage-fast-client"


def _declared() -> frozenset[Capability]:
    return frozenset(capability for capability in Capability if capability.value in S1_NAMES)


def _lineage_service(scene: Scene, **switches: Any) -> ApplicationService:  # noqa: ANN401
    """A FAST service with the lineage plane on (the FAST world models no Issue rows)."""
    return ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(scene.world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        lineage_enabled=True,
        **switches,
    )


def _samples() -> dict[Capability, Command]:
    return {
        Capability.ISSUES_CREATE: CreateIssue(title="Synthetic", idempotency_key="fast-create"),
        Capability.ISSUES_READ: ReadIssue(issue_id=_ISSUE),
        Capability.ISSUES_LIST: ListIssues(),
        Capability.ISSUES_UPDATE: UpdateIssue(
            issue_id=_ISSUE, expected_version=1, idempotency_key="fast-update", title="Retitled"
        ),
        Capability.ISSUES_PROJECT_LINKS_ADD: AddIssueProjectLink(
            issue_id=_ISSUE,
            project_id=_PROJECT,
            expected_membership_revision=0,
            idempotency_key="fast-add",
        ),
        Capability.ISSUES_PROJECT_LINKS_END: EndIssueProjectLink(
            issue_id=_ISSUE,
            project_id=_PROJECT,
            expected_membership_revision=1,
            idempotency_key="fast-end",
            reason="synthetic",
        ),
        Capability.ISSUES_MEMBERSHIPS_ADD: AddIssueMembership(
            issue_id=_ISSUE,
            member={"family": "task", "record_id": _TASK},
            role="work",
            idempotency_key="fast-member-add",
        ),
        Capability.ISSUES_MEMBERSHIPS_END: EndIssueMembership(
            link_id=_LINK, expected_revision=1, idempotency_key="fast-member-end", reason="x"
        ),
        Capability.RECORDS_ASSOCIATIONS_ASSERT: AssertRecordAssociation(
            from_record={"family": "commitment", "record_id": _COMMITMENT},
            to_record={"family": "meeting_note_version", "record_id": _NOTE},
            relation_type="originated_from",
            idempotency_key="fast-assert",
            evidence_anchors=(_PASSAGE_ANCHOR,),
        ),
        Capability.RECORDS_ASSOCIATIONS_CORRECT: CorrectRecordAssociation(
            link_id=_LINK,
            expected_revision=1,
            idempotency_key="fast-correct",
            reason="synthetic",
            evidence_anchors=(_PASSAGE_ANCHOR,),
        ),
        Capability.RECORDS_ASSOCIATIONS_END: EndRecordAssociation(
            link_id=_LINK, expected_revision=1, idempotency_key="fast-assoc-end", reason="x"
        ),
        Capability.RECORDS_LINEAGE: ReadRecordLineage(
            origin={"family": "task", "record_id": _TASK}
        ),
        Capability.MEETINGS_NOTES_VERSIONS: ListMeetingNoteVersions(meeting_id=_MEETING),
        Capability.MEETINGS_NOTES_READ_VERSION: ReadMeetingNoteVersion(
            meeting_id=_MEETING, note_version_id=_NOTE
        ),
    }


def _invoke(
    service: ApplicationService,
    scene: Scene,
    command: Command,
    *,
    remote_client: str | None = None,
    surface: OperatorSurface | None = None,
) -> ResponseEnvelope:
    capability = command.capability
    purpose = sorted(permitted_purposes(capability))[0]
    return service.invoke(
        metadata_for(capability, purpose, scene.principal),
        command,
        principal=scene.principal,
        transport=CaptureTransport.REMOTE_CLIENT if remote_client else CaptureTransport.LOCAL,
        capability_grants=frozenset({(capability, purpose)}) if remote_client else None,
        authenticated_client_id=remote_client,
        operator_surface=surface,
    )


def _code(envelope: ResponseEnvelope) -> str | None:
    error = envelope.to_canonical_dict().get("error")
    return None if error is None else str(error["code"])  # type: ignore[index]


# ---- classification ---------------------------------------------------------


def test_s1_capabilities_are_operator_decision_required() -> None:
    declared = _declared()
    assert declared, "no S1 name is declared, so this test proves nothing"
    # S2 widens the switch's set by its own names (S2 contract 7.5); the
    # S1 part of it is unchanged.
    assert declared == {c for c in _LINEAGE_CAPABILITIES if c.value in S1_NAMES}
    assert S1_NAMES <= _LINEAGE_CAPABILITY_NAMES
    for capability in declared:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED
        assert policy.exclusion_rationale == _RATIONALE
        assert not is_operator_only(capability)
        assert capability in _SCOPELESS
        family = capability.value.split(".", 1)[0]
        expected_feature = "meetings" if family == "meetings" else "lineage"
        assert _FEATURE_BY_FAMILY[family] == expected_feature
        writes = capability.value in _S1_WRITES
        assert is_write_capability(capability) is writes
        assert is_destructive_capability(capability) is (
            writes and capability.value not in _S1_ADDITIVE
        )
        assert (capability in _IDEMPOTENT_REMOTE_CAPABILITIES) is writes
        purposes = permitted_purposes(capability)
        assert len(purposes) == 1
        assert bool(purposes & remote_mcp._WRITE_PURPOSES) is writes
    assert Purpose.ISSUE_AUTHORING in remote_mcp._WRITE_PURPOSES
    assert Purpose.ISSUE_READ not in remote_mcp._WRITE_PURPOSES


def test_no_s1_capability_is_in_the_chatllm_data_profile() -> None:
    from my_pa.application.chatllm_data_profile import desired_effective_capabilities

    declared = _declared()
    assert all(not is_chatllm_data_management(capability) for capability in declared)
    every = frozenset(Capability)
    assert not desired_effective_capabilities(every) & declared
    assert not desired_effective_capabilities(every, knowledge_manager=True) & declared
    # No data-class member moved, so the profile version did not either.
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v9"


# ---- request shapes ---------------------------------------------------------

_BASE_PAYLOADS: Final[dict[str, dict[str, object]]] = {
    "issues.create": {"title": "Synthetic", "idempotency_key": "fast-create"},
    "issues.read": {"issue_id": _ISSUE},
    "issues.list": {},
    "issues.update": {
        "issue_id": _ISSUE,
        "expected_version": 1,
        "idempotency_key": "fast-update",
        "title": "Retitled",
    },
    "issues.project_links.add": {
        "issue_id": _ISSUE,
        "project_id": _PROJECT,
        "expected_membership_revision": 0,
        "idempotency_key": "fast-add",
    },
    "issues.project_links.end": {
        "issue_id": _ISSUE,
        "project_id": _PROJECT,
        "expected_membership_revision": 1,
        "idempotency_key": "fast-end",
        "reason": "synthetic",
    },
    "issues.memberships.add": {
        "issue_id": _ISSUE,
        "member": {"family": "task", "record_id": _TASK},
        "role": "work",
        "idempotency_key": "fast-member-add",
    },
    "issues.memberships.end": {
        "link_id": _LINK,
        "expected_revision": 1,
        "idempotency_key": "fast-member-end",
        "reason": "synthetic",
    },
    "records.associations.assert": {
        "from_record": {"family": "commitment", "record_id": _COMMITMENT},
        "to_record": {"family": "meeting_note_version", "record_id": _NOTE},
        "relation_type": "originated_from",
        "idempotency_key": "fast-assert",
        "evidence_anchors": [_PASSAGE_ANCHOR],
    },
    "records.associations.correct": {
        "link_id": _LINK,
        "expected_revision": 1,
        "idempotency_key": "fast-correct",
        "reason": "synthetic",
        "evidence_anchors": [_PASSAGE_ANCHOR],
    },
    "records.associations.end": {
        "link_id": _LINK,
        "expected_revision": 1,
        "idempotency_key": "fast-assoc-end",
        "reason": "synthetic",
    },
    "records.lineage": {"origin": {"family": "task", "record_id": _TASK}},
    "meetings.notes.versions": {"meeting_id": _MEETING},
    "meetings.notes.read_version": {"meeting_id": _MEETING, "note_version_id": _NOTE},
}
_SERVER_OWNED: Final = (
    "principal_id",
    "actor_class",
    "authority_class",
    "decision_channel",
    "acceptance_basis",
    "review_decision_id",
    "recorded_at",
    "selector",
)
_ANCHOR: Final[dict[str, object]] = {
    "family": "meeting_note_version",
    "root_id": "mtg_lineagefast00001",
    "version_kind": "immutable_version",
    "version_id": "mnote_lineagefast00001",
    "source_sha256": "a" * 64,
    "role": "origin",
}


def _arguments(payload: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "req-lineage-fast",
        "purpose": "issue_authoring",
        "principal_id": "prn_lineagefast00001",
        "requested_at": "2026-10-17T12:00:00Z",
        "payload": payload,
    }


@pytest.mark.parametrize("name", sorted(_BASE_PAYLOADS))
def test_s1_requests_reject_server_owned_fields(name: str) -> None:
    base = _BASE_PAYLOADS[name]
    _metadata, command = normalize(name, _arguments(base))
    assert command.capability.value == name
    for field in _SERVER_OWNED:
        with pytest.raises(InvalidRequestError):
            normalize(name, _arguments({**base, field: "server-owned"}))
    if name == "issues.project_links.add":
        normalize(name, _arguments({**base, "evidence_anchor": _ANCHOR}))
        # `version_no` is server-derived from the bound row, never accepted.
        for owned in ("version_no", "source_version_no", "anchor_id", "principal_id"):
            with pytest.raises(InvalidRequestError):
                normalize(name, _arguments({**base, "evidence_anchor": {**_ANCHOR, owned: 1}}))
    if "evidence_anchors" in base:
        for owned in ("version_no", "source_version_no", "anchor_id", "principal_id"):
            with pytest.raises(InvalidRequestError):
                normalize(
                    name,
                    _arguments({**base, "evidence_anchors": [{**_PASSAGE_ANCHOR, owned: 1}]}),
                )
    for nested in ("member", "origin", "from_record", "to_record"):
        if nested in base:
            # A record reference is exactly `{family, record_id}`: no selector,
            # no version, no Principal.
            for owned in ("selector", "principal_id", "version_no"):
                with pytest.raises(InvalidRequestError):
                    normalize(
                        name,
                        _arguments({**base, nested: {**base[nested], owned: "root"}}),  # type: ignore[dict-item]
                    )


#: The existing v1 request shapes S1 promises not to change (section 8), as
#: published payload schemas: field names and required fields.
_EXISTING_SHAPES: Final[dict[type, tuple[frozenset[str], frozenset[str]]]] = {
    ListSituations: (frozenset({"page_size"}), frozenset()),
    CreateSituation: (
        frozenset({"title", "idempotency_key", "description"}),
        frozenset({"title", "idempotency_key"}),
    ),
    RecordTask: (
        frozenset({"title", "idempotency_key", "project_id", "situation_id", "due_at"}),
        frozenset({"title", "idempotency_key"}),
    ),
    ReadMeeting: (frozenset({"meeting_id"}), frozenset({"meeting_id"})),
}


def test_existing_v1_shapes_are_unchanged() -> None:
    for command, (fields, required) in _EXISTING_SHAPES.items():
        schema = payload_schema_for(command)
        assert set(schema["properties"]) == fields, command.__name__
        assert set(schema["required"]) == required, command.__name__
    # The two Work writers keep `situation_id` as an optional field of the same
    # shape; S1 adds a refusal for an Issue, not a field.
    for command in (CreateTask, CreateCommitment):
        schema = payload_schema_for(command)
        assert "situation_id" in schema["properties"]
        assert "situation_id" not in schema["required"]
    assert set(ListSituations.__dataclass_fields__) == {"capability", "page_size"}


# ---- continuity compatibility ------------------------------------------------


def _stage_issue(scene: Scene, *, title: str) -> str:
    """An Issue-kind Situation in the FAST world, as S1 stores one."""
    situation = staged_situation(scene, title=title)
    issue = replace(situation, kind=SituationKind.ISSUE_WORKSTREAM)
    situations = scene.world.situations
    situations[situations.index(situation)] = issue
    return issue.situation_id


_SITUATION_KEYS: Final = frozenset(
    {
        "situation_id",
        "title",
        "state",
        "description",
        "object_refs",
        "opened_at",
        "closed_at",
        "outcome",
    }
)


def _situations(scene: Scene) -> list[dict[str, Any]]:
    envelope = build_service(scene.world, scene.providers).invoke(
        metadata_for(
            Capability.CONTINUITY_SITUATIONS,
            sorted(permitted_purposes(Capability.CONTINUITY_SITUATIONS))[0],
            scene.principal,
        ),
        ListSituations(),
        principal=scene.principal,
    )
    assert envelope.error is None, envelope.error
    result = envelope.to_canonical_dict()["result"]
    assert isinstance(result, dict)
    return list(result["situations"])


def test_continuity_situations_keeps_exactly_the_old_keys(scene: Scene) -> None:
    staged_situation(scene, title="synthetic context")
    _stage_issue(scene, title="synthetic issue")
    listed = _situations(scene)
    assert listed
    for row in listed:
        assert set(row) == _SITUATION_KEYS


def test_continuity_situations_excludes_issues_and_keeps_contexts(scene: Scene) -> None:
    context = staged_situation(scene, title="synthetic context").situation_id
    issue = _stage_issue(scene, title="synthetic issue")
    listed = [row["situation_id"] for row in _situations(scene)]
    assert listed == [context]
    assert issue not in listed


def test_context_prepare_returns_no_issue_situation_id(scene: Scene) -> None:
    context = staged_situation(scene, title="quarterly planning").situation_id
    issue = _stage_issue(scene, title="quarterly escalation")
    envelope = build_service(scene.world, scene.providers).invoke(
        metadata_for(Capability.CONTEXT_PREPARE, Purpose.CONTEXT_PREPARATION, scene.principal),
        PrepareContext(query="quarterly"),
        principal=scene.principal,
    )
    assert envelope.error is None, envelope.error
    rendered = json.dumps(envelope.to_canonical_dict()["result"])
    assert context in rendered
    assert issue not in rendered


# ---- note history purpose ------------------------------------------------------


def test_note_body_needs_the_history_purpose(scene: Scene) -> None:
    """Section 7: a historical note body is a widening over `meeting_read`.

    `meetings.notes.read_version` is admitted under `meeting_note_history_read`
    only, so a caller holding the ordinary Meeting read purpose is denied
    before the handler, while version metadata stays a Meeting read.
    """
    read_version = Capability.MEETINGS_NOTES_READ_VERSION
    assert permitted_purposes(read_version) == frozenset({Purpose.MEETING_NOTE_HISTORY_READ})
    assert permitted_purposes(Capability.MEETINGS_NOTES_VERSIONS) == frozenset(
        {Purpose.MEETING_READ}
    )
    assert Purpose.MEETING_NOTE_HISTORY_READ not in permitted_purposes(Capability.MEETINGS_READ)
    assert Purpose.MEETING_NOTE_HISTORY_READ not in remote_mcp._WRITE_PURPOSES
    service = _lineage_service(scene)
    command = _samples()[read_version]
    denied = service.invoke(
        metadata_for(read_version, Purpose.MEETING_READ, scene.principal),
        command,
        principal=scene.principal,
    )
    assert _code(denied) == "denied"
    # A remote grant of the Meeting read purpose for this capability is
    # refused the same way: the grant cannot name a purpose the capability
    # does not admit.
    remote = service.invoke(
        metadata_for(read_version, Purpose.MEETING_READ, scene.principal),
        command,
        principal=scene.principal,
        transport=CaptureTransport.REMOTE_CLIENT,
        capability_grants=frozenset({(read_version, Purpose.MEETING_READ)}),
        authenticated_client_id=_CLIENT,
    )
    assert _code(remote) == "denied"


# ---- the admission switch -----------------------------------------------------


def test_switch_off_withholds_every_s1_capability(scene: Scene) -> None:
    declared = _declared()
    off = build_service(scene.world, scene.providers)
    on = _lineage_service(scene)
    assert not off.available_capabilities & declared
    assert declared <= on.available_capabilities
    published_off = {tool.name for tool in published_tools(off, authenticated_client_present=True)}
    published_on = {tool.name for tool in published_tools(on, authenticated_client_present=True)}
    assert not published_off & {capability.value for capability in declared}
    assert {capability.value for capability in declared} <= published_on
    manifest = off.invoke(
        metadata_for(Capability.CAPABILITIES_GET, Purpose.STATUS_OBSERVATION, scene.principal),
        GetCapabilities(),
        principal=scene.principal,
    ).to_canonical_dict()["result"]
    assert isinstance(manifest, dict)
    availability = {
        row["name"]: row["availability"] for row in manifest["manifest"]["capabilities"]
    }
    for capability in declared:
        assert availability[capability.value] == "not_implemented"
    samples = _samples()
    assert set(samples) == declared
    for capability, command in samples.items():
        # The switch is checked first: even a stamped operator surface, which an
        # attested write needs, answers `unsupported`, and the FAST world's
        # unmodelled Issue repository is never reached.
        envelope = _invoke(off, scene, command, surface=OperatorSurface.HTTP_GATEWAY)
        assert _code(envelope) == "unsupported", capability.value


# ---- authority ---------------------------------------------------------------


def test_lineage_authority_ignores_the_knowledge_manager_allowlist(scene: Scene) -> None:
    remote = SimpleNamespace(
        operator_surface=None,
        transport=CaptureTransport.REMOTE_CLIENT,
        principal=Principal(
            principal_id=scene.principal.principal_id,
            kind=PrincipalKind.OPERATOR,
            authenticated=True,
        ),
        authenticated_client_id=_CLIENT,
        capability_grants=frozenset(),
    )
    derived = lineage_authority(remote)  # type: ignore[arg-type]
    assert derived.authority_class.value == "ordinary_reviewer"
    assert derived.decision_channel.value == "remote_interactive"
    service = _lineage_service(
        scene,
        knowledge_operator_review_client_ids=frozenset({_CLIENT}),
        knowledge_manager_client_ids=frozenset({_CLIENT}),
    )
    for command in (_samples()[Capability.ISSUES_PROJECT_LINKS_ADD],):
        envelope = _invoke(service, scene, command, remote_client=_CLIENT)
        # S3.1 section 10.1 (the operator directives of 2026-10-20 and
        # 2026-10-25): the write is open, so it is never `denied` for want of
        # attestation; the allowlists confer nothing either way. The client
        # holds no Issue read, so the S3.1 section 6.4 pre-check answers its
        # hidden Issue exactly as an absent one, before any row (the FAST world
        # models no Issue rows, so reaching the repository would not be this).
        error = envelope.to_canonical_dict()["error"]
        assert _code(envelope) == "not_found"
        assert error["safe_details"] == ["issue_id"]  # type: ignore[index]
    with pytest.raises(DeniedError):
        attested_lineage_authority(remote)  # type: ignore[arg-type]
