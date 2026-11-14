"""Files workspace WP5: the 17 `files.*` names, closed over every registry (FAST).

Files-workspace contract sections 1, 7, 9, 11 and 12: the vocabulary is
appended in contract order; each name permits exactly its one purpose, is
scopeless and never operator-only; the 10 writes are writes (4 additive, 6
with the destructive hint); the authoring purpose is a remote write purpose;
the ChatLLM profile classifies all 17 `DATA_CONDITIONAL` on `FILES_WORKSPACE`
at `chatllm-data-v14`; the façade publishes them under the `files` feature;
the remote boundary stamps a fresh idempotency key per call; and a process
with no workspace root serves none of them. Every value is synthetic.
"""

from __future__ import annotations

from typing import Final

import pytest
from tests.files_workspace_samples import FILES_WORKSPACE_COMMAND_TYPES, files_payloads
from tests.schema.files_workspace_vocabulary_contract import (
    FILES_CAPABILITIES,
    FILES_PURPOSES,
)

from my_pa.adapters.mcp.chatllm_gateway import facade_kind, feature_label, render_describe
from my_pa.adapters.mcp.remote import is_remote_write
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import _BUILDERS
from my_pa.adapters.remote_request import compose_remote_arguments, is_remote_idempotent
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    composed_capabilities,
    desired_effective_capabilities,
)
from my_pa.application.errors import SafeDetail
from my_pa.application.file_workspace import FILE_WORKSPACE_CAPABILITIES
from my_pa.application.service import _HANDLERS
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.files.vocabulary import FilesReason
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    FILES_WORKSPACE_DATA_NAMES,
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
from my_pa.domain.identity.principal import Principal, PrincipalKind
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import _SCOPELESS

_R: Final = Purpose.FILE_WORKSPACE_READ
_W: Final = Purpose.FILE_WORKSPACE_AUTHORING

#: Contract section 1.1, in order: `name -> (purpose, write, additive)`.
INVENTORY: Final[dict[str, tuple[Purpose, bool, bool]]] = {
    "files.workspaces.list": (_R, False, False),
    "files.list": (_R, False, False),
    "files.stat": (_R, False, False),
    "files.search": (_R, False, False),
    "files.preview": (_R, False, False),
    "files.history": (_R, False, False),
    "files.download.begin": (_R, False, False),
    "files.mkdir": (_W, True, True),
    "files.copy": (_W, True, True),
    "files.upload.begin": (_W, True, True),
    "files.upload.abort": (_W, True, True),
    "files.rename": (_W, True, False),
    "files.move": (_W, True, False),
    "files.trash": (_W, True, False),
    "files.restore": (_W, True, False),
    "files.upload.finalize": (_W, True, False),
    "files.write_text": (_W, True, False),
}
_WRITES: Final = frozenset(Capability(name) for name, row in INVENTORY.items() if row[1])


def test_the_inventory_is_the_17_appended_names_and_the_2_purposes() -> None:
    members = list(Capability)
    assert [member.value for member in members[-17:]] == list(INVENTORY)
    assert list(Purpose)[-2:] == [_R, _W]
    assert (len(Capability), len(Purpose), len(IdKind)) == (298, 70, 179)
    assert frozenset(members[-17:]) == FILE_WORKSPACE_CAPABILITIES
    assert set(FILES_WORKSPACE_COMMAND_TYPES) == FILE_WORKSPACE_CAPABILITIES
    # WP4's frozen audit vocabulary names exactly these (contract section 13).
    assert {member.value for member in FILE_WORKSPACE_CAPABILITIES} == FILES_CAPABILITIES
    assert {_R.value, _W.value} == FILES_PURPOSES


def test_the_id_kinds_are_the_contract_prefixes() -> None:
    assert [kind.value for kind in list(IdKind)[-5:]] == [
        "fwupl",
        "fwdnl",
        "fwver",
        "fwtrs",
        "fwrcp",
    ]


@pytest.mark.parametrize("name", list(INVENTORY))
def test_each_name_is_classified_as_the_contract_states(name: str) -> None:
    capability = Capability(name)
    purpose, write, additive = INVENTORY[name]
    assert permitted_purposes(capability) == frozenset({purpose})
    assert not is_operator_only(capability)
    assert capability in _SCOPELESS
    assert is_write_capability(capability) is write
    assert is_destructive_capability(capability) is (write and not additive)
    assert is_remote_write(capability) is write
    assert facade_kind(capability) == ("write" if write else "read")
    assert feature_label(name) == "files"
    assert capability in _HANDLERS and capability in _BUILDERS


def test_the_section_7_reason_tokens_are_safe_details() -> None:
    for reason in FilesReason:
        assert SafeDetail(reason.value).name == reason.name


def test_the_tool_hints_follow_the_classification() -> None:
    tools = {tool.name: tool for tool in TOOLS}
    for name, (_purpose, write, additive) in INVENTORY.items():
        annotations = tools[name].annotations
        assert annotations is not None
        assert annotations.read_only_hint is (not write), name
        assert annotations.destructive_hint is (write and not additive), name
        # A fresh remote key per call: no remote retry replays (contract section 5).
        assert annotations.idempotent_hint is False, name
        assert tools[name].description, name


def test_chatllm_classifies_the_17_data_conditional_on_the_workspace_at_v14() -> None:
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v14"
    assert FILES_WORKSPACE_DATA_NAMES == FILE_WORKSPACE_CAPABILITIES
    for capability in FILE_WORKSPACE_CAPABILITIES:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.FILES_WORKSPACE
        assert policy.family == "files"
        assert policy.exclusion_rationale is None
    assert ChatLLMCompositionPlanes.__dataclass_fields__["files_workspace"].default is False


def test_v14_desires_the_17_exactly_when_the_workspace_is_composed() -> None:
    implemented = frozenset(_HANDLERS)
    base = {
        "managed_documents": True,
        "relationship_intelligence": True,
        "relationship_intelligence_writes": True,
        "relationship_memory": True,
        "constraints": True,
    }
    without = desired_effective_capabilities(
        composed_capabilities(implemented, ChatLLMCompositionPlanes(**base))
    )
    with_root = desired_effective_capabilities(
        composed_capabilities(implemented, ChatLLMCompositionPlanes(**base, files_workspace=True))
    )
    assert not without & FILE_WORKSPACE_CAPABILITIES
    assert with_root - without == FILE_WORKSPACE_CAPABILITIES


def test_describe_lists_the_files_feature_only_for_eligible_names() -> None:
    eligible = frozenset({"files.list", "files.mkdir"})
    catalog = render_describe({"feature": "files"}, allowed_canonical=eligible)
    assert '"capability":"files.list"' in catalog and '"capability":"files.mkdir"' in catalog
    assert '"files.write_text"' not in catalog
    assert '"items":[]' in render_describe({"feature": "files"}, allowed_canonical=frozenset())


def test_every_sample_builds_its_command() -> None:
    for capability, payload in files_payloads("contract").items():
        command = _BUILDERS[capability](payload)
        assert type(command) is FILES_WORKSPACE_COMMAND_TYPES[capability]


@pytest.mark.parametrize("capability", sorted(_WRITES, key=lambda c: c.value))
def test_the_remote_boundary_stamps_a_fresh_key_for_every_files_write(
    capability: Capability,
) -> None:
    """Contract section 5 with a server-owned key: never a digest of the payload.

    A payload-derived key would replay a stale receipt for the same create after
    its target was removed (`mkdir a`, `trash a`, `mkdir a`); two identical
    remote calls therefore carry two different keys.
    """
    principal = Principal(
        principal_id="prn_fileswp5contract1", kind=PrincipalKind.OPERATOR, authenticated=True
    )
    payload = files_payloads("remote")[capability]
    payload = {key: value for key, value in payload.items() if key != "idempotency_key"}
    grants = frozenset({(capability, _W)})
    keys = {
        compose_remote_arguments(
            capability_name=capability.value,
            arguments={"payload": dict(payload)},
            principal=principal,
            grants=grants,
            authenticated_client_id="synthetic-client",
        )["payload"]["idempotency_key"]
        for _ in range(2)
    }
    assert len(keys) == 2
    assert not is_remote_idempotent(capability)
