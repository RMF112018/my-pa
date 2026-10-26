"""Record lineage P1: the ChatLLM classification of the lineage plane (FAST).

Client exposure contract (`docs/architecture/record-lineage-client-exposure-contract.md`)
sections 3, 4 and 10, under the operator directive of 2026-10-26 (ADR-015
decision 16):

* the 34 client-usable lineage-plane names are `CHATLLM_DATA_CONDITIONAL` under
  the `LINEAGE` or `PROGRAM_REPORTING` prerequisite, with no exclusion rationale;
* Issue close and reopen and the 3 confirms are `CHATLLM_CONTROL_PLANE_EXCLUDED`
  with the attested rationale, the backfill pair is unchanged, and all 7 are
  operator kind;
* the planner desires a lineage name exactly when its plane is composed, never
  a withheld one, and flags an active grant on a withheld one as unhealthy;
* every switch stays default-off in code;
* the policy equals the contract's section 3 exposure table.

The expected sets are derived from the service's switch sets and the lineage
and Program vocabularies, never from the policy's own name sets, so a name that
leaves a policy set is caught. Every value is synthetic.
"""

from __future__ import annotations

import itertools
import re
from dataclasses import fields
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from my_pa.adapters.mcp.chatllm_gateway import facade_kind
from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    ChatLLMGrantRecord,
    ChatLLMProfileOutcome,
    chatllm_grant_purpose,
    composed_capabilities,
    desired_effective_capabilities,
    diff_chatllm_data_profile,
)
from my_pa.application.service import (
    _HANDLERS,
    _LINEAGE_CAPABILITIES,
    _PROGRAM_REPORTING_CAPABILITIES,
)
from my_pa.bootstrap.settings import Settings
from my_pa.contracts.mcp_database_profiles import MCP_PROFILE_OPT_IN_CAPABILITY_NAMES
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    LINEAGE_DATA_NAMES,
    PROGRAM_REPORTING_DATA_NAMES,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
    is_chatllm_data_management,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.lineage.vocabulary import (
    ATTESTED_LINEAGE_WRITE_CAPABILITIES,
    LINEAGE_BACKFILL_CAPABILITIES,
)
from my_pa.domain.program.vocabulary import (
    PROGRAM_READ_CAPABILITIES,
    PROGRAM_REPORTING_CAPABILITIES,
)

_CONTRACT: Final = (
    Path(__file__).resolve().parents[2]
    / "docs"
    / "architecture"
    / "record-lineage-client-exposure-contract.md"
)
_ATTESTED_RATIONALE: Final = (
    "attested to the local operator surface; withheld from every client "
    "(operator directive 2026-10-26)"
)
_BACKFILL_RATIONALE: Final = "operator-only lineage backfill"

IMPLEMENTED: Final = frozenset(_HANDLERS)
NOW: Final = datetime(2026, 10, 26, 12, tzinfo=UTC)
RESOURCE: Final = "https://my-pa.example/mcp"
SCOPE: Final = "my-pa.read"


def _members(names: frozenset[str]) -> frozenset[Capability]:
    return frozenset(capability for capability in Capability if capability.value in names)


#: The 7 withheld names: the attested writes (close, reopen, the 3 confirms,
#: the backfill plan) and the backfill pair.
WITHHELD: Final = _members(ATTESTED_LINEAGE_WRITE_CAPABILITIES | LINEAGE_BACKFILL_CAPABILITIES)
#: The 5 attested names P1 moves to `CONTROL_PLANE_EXCLUDED`.
ATTESTED_MOVED: Final = WITHHELD - _members(LINEAGE_BACKFILL_CAPABILITIES)
#: The 27 exposed names under `LINEAGE` and the 7 under `PROGRAM_REPORTING`.
EXPOSED_LINEAGE: Final = _LINEAGE_CAPABILITIES - WITHHELD
EXPOSED_PROGRAM: Final = _members(PROGRAM_REPORTING_CAPABILITIES)
EXPOSED: Final = EXPOSED_LINEAGE | EXPOSED_PROGRAM
PROGRAM_READS: Final = _members(PROGRAM_READ_CAPABILITIES)

_PLANE_FLAGS: Final = tuple(field.name for field in fields(ChatLLMCompositionPlanes))


def _planes(**flags: bool) -> ChatLLMCompositionPlanes:
    return ChatLLMCompositionPlanes(
        **{name: flags.get(name, False) for name in _PLANE_FLAGS}  # type: ignore[arg-type]
    )


def _every_composition() -> list[ChatLLMCompositionPlanes]:
    return [
        ChatLLMCompositionPlanes(**dict(zip(_PLANE_FLAGS, bits, strict=True)))  # type: ignore[arg-type]
        for bits in itertools.product((False, True), repeat=len(_PLANE_FLAGS))
    ]


def _desired(
    planes: ChatLLMCompositionPlanes, *, knowledge_manager: bool = False
) -> frozenset[Capability]:
    return desired_effective_capabilities(
        composed_capabilities(IMPLEMENTED, planes), knowledge_manager=knowledge_manager
    )


_FULL: Final = {
    "managed_documents": True,
    "relationship_intelligence": True,
    "relationship_intelligence_writes": True,
    "relationship_memory": True,
    "constraints": True,
}


# ---- classification -----------------------------------------------------------


def test_v10_client_usable_lineage_names_are_data_conditional() -> None:
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v10"
    assert len(EXPOSED_LINEAGE) == 27
    assert len(EXPOSED_PROGRAM) == 7
    assert len(EXPOSED) == 34
    # Every exposed name is implemented, so the planner never reports it as
    # `POLICY_REQUIRED_NOT_IMPLEMENTED`.
    assert EXPOSED <= IMPLEMENTED
    for capability in EXPOSED:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL, capability
        expected = (
            ChatLLMCompositionPrerequisite.LINEAGE
            if capability in EXPOSED_LINEAGE
            else ChatLLMCompositionPrerequisite.PROGRAM_REPORTING
        )
        assert policy.composition_prerequisite is expected, capability
        assert policy.exclusion_rationale is None, capability
        assert is_chatllm_data_management(capability)


def test_v10_withheld_lineage_names_are_control_plane_excluded() -> None:
    assert len(WITHHELD) == 7
    assert len(ATTESTED_MOVED) == 5
    for capability in WITHHELD:
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED, capability
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.NONE
        assert policy.exclusion_rationale == (
            _ATTESTED_RATIONALE if capability in ATTESTED_MOVED else _BACKFILL_RATIONALE
        ), capability
        assert not is_chatllm_data_management(capability)
        # Publication withholds all 7 independently (S3.1 section 7.13).
        assert is_operator_only(capability), capability
    # Only the GSQS pair remains an operator decision.
    assert {
        capability
        for capability, policy in CHATLLM_CAPABILITY_POLICY.items()
        if policy.classification is ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED
    } == {Capability.GSQS_START, Capability.GSQS_STATUS}


def test_the_lineage_name_sets_equal_the_switch_sets() -> None:
    assert LINEAGE_DATA_NAMES == _LINEAGE_CAPABILITIES - WITHHELD
    assert PROGRAM_REPORTING_DATA_NAMES == _PROGRAM_REPORTING_CAPABILITIES
    assert len(LINEAGE_DATA_NAMES) == 27
    assert len(PROGRAM_REPORTING_DATA_NAMES) == 7
    assert not LINEAGE_DATA_NAMES & PROGRAM_REPORTING_DATA_NAMES


def test_every_exposed_lineage_name_has_one_chatllm_purpose_and_its_remote_kind() -> None:
    writes = 0
    for capability in EXPOSED:
        permitted = permitted_purposes(capability)
        assert len(permitted) == 1, capability
        assert chatllm_grant_purpose(capability) is next(iter(permitted))
        write = is_write_capability(capability)
        writes += write
        assert facade_kind(capability) == ("write" if write else "read"), capability
    assert writes == 16
    for capability in WITHHELD:
        assert facade_kind(capability) == "operator", capability


# ---- planner ------------------------------------------------------------------


def test_v10_demands_lineage_grants_only_when_the_lineage_plane_is_composed() -> None:
    for planes in _every_composition():
        for knowledge_manager in (False, True):
            desired = _desired(planes, knowledge_manager=knowledge_manager)
            if planes.lineage:
                assert desired >= EXPOSED_LINEAGE, planes
            else:
                assert not desired & EXPOSED_LINEAGE, planes


def test_v10_demands_program_reporting_grants_only_with_both_switches_and_their_planes() -> None:
    for planes in _every_composition():
        desired = _desired(planes)
        switches = planes.lineage and planes.program_reporting
        for capability in EXPOSED_PROGRAM:
            expected = switches
            if capability in PROGRAM_READS:
                expected = expected and planes.relationship_intelligence
            if capability is Capability.PROGRAMS_OVERVIEW:
                expected = expected and planes.constraints
            assert (capability in desired) is expected, (capability, planes)
    # The Program reporting switch alone, without lineage, plans nothing.
    alone = _desired(_planes(**_FULL, program_reporting=True))
    assert not alone & EXPOSED


def test_v10_never_desires_a_withheld_lineage_name_in_any_composition() -> None:
    compositions = _every_composition()
    assert len(compositions) == 256
    for planes in compositions:
        for knowledge_manager in (False, True):
            assert not _desired(planes, knowledge_manager=knowledge_manager) & WITHHELD, planes


def test_an_active_grant_on_a_withheld_lineage_name_is_an_unexpected_control_plane_grant() -> None:
    planes = _planes(**_FULL, lineage=True, program_reporting=True)
    composed = composed_capabilities(IMPLEMENTED, planes)
    desired = desired_effective_capabilities(composed)
    healthy = tuple(_grant(capability) for capability in desired)
    baseline = diff_chatllm_data_profile(
        implemented=IMPLEMENTED,
        composed=composed,
        grants=healthy,
        now=NOW,
        resource=RESOURCE,
        scope=SCOPE,
    )
    assert baseline.is_healthy()
    for capability in sorted(WITHHELD, key=lambda item: item.value):
        for knowledge_manager in (False, True):
            diff = diff_chatllm_data_profile(
                implemented=IMPLEMENTED,
                composed=composed,
                grants=(*healthy, _grant(capability)),
                now=NOW,
                resource=RESOURCE,
                scope=SCOPE,
                knowledge_manager=knowledge_manager,
            )
            assert (
                diff.outcomes[capability] is ChatLLMProfileOutcome.UNEXPECTED_CONTROL_PLANE_GRANT
            ), capability
            assert diff.unexpected_control_plane == {capability}
            assert not diff.is_healthy()


def test_v10_full_plane_targets_with_lineage_and_program_reporting() -> None:
    assert len(_desired(_planes(**_FULL))) == 164
    assert len(_desired(_planes(**_FULL, lineage=True))) == 191
    both = _desired(_planes(**_FULL, lineage=True, program_reporting=True))
    assert len(both) == 198
    assert both - _desired(_planes(**_FULL)) == EXPOSED
    # Relationship intelligence off (the default planes): the 2 Program reads
    # need the entity plane.
    default = _desired(_planes(constraints=True, lineage=True, program_reporting=True))
    assert len(default) == 130
    assert default & EXPOSED == EXPOSED - PROGRAM_READS


# ---- defaults -----------------------------------------------------------------


def test_no_lineage_or_remote_switch_defaults_on() -> None:
    model = Settings.model_fields
    for name in (
        "lineage_enabled",
        "program_reporting_enabled",
        "lineage_backfill_enabled",
        "remote_writes_enabled",
        "mcp_database_profiles_enabled",
    ):
        assert model[name].default is False, name
    assert model["mcp_database_profile_opt_ins"].default == ""
    # The planner's planes follow the switches: off unless set.
    planes = ChatLLMCompositionPlanes(
        managed_documents=True,
        relationship_intelligence=True,
        relationship_intelligence_writes=True,
        relationship_memory=True,
        constraints=True,
    )
    assert planes.lineage is False
    assert planes.program_reporting is False


# ---- the contract's exposure table --------------------------------------------

_ROW: Final = re.compile(
    r"^\| `(?P<name>[a-z0-9_.]+)` \| (?P<wr>[WR]) \| `(?P<purpose>[a-z_]+)` \| "
    r"(?P<v9>[A-Z]+) \| (?P<v10>[A-Z]+) \| (?P<prerequisite>`[A-Z_]+`|—) \| "
    r"(?P<grant>yes|no) \| (?P<opt_in>[^|]+) \|"
)
_CLASS: Final = {
    "DC": ChatLLMCapabilityClass.DATA_CONDITIONAL,
    "CPE": ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED,
    "ODR": ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED,
}


def _exposure_table() -> dict[Capability, re.Match[str]]:
    text = _CONTRACT.read_text(encoding="utf-8")
    section = text.split("## 3. Exposure table", 1)[1].split("\n## 4.", 1)[0]
    rows: dict[Capability, re.Match[str]] = {}
    for line in section.splitlines():
        match = _ROW.match(line)
        if match is None:
            continue
        capability = Capability(match["name"])
        assert capability not in rows, capability
        rows[capability] = match
    return rows


def test_the_policy_matches_the_contract_exposure_table() -> None:
    rows = _exposure_table()
    assert set(rows) == EXPOSED | WITHHELD
    assert len(rows) == 41
    for capability, row in rows.items():
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is _CLASS[row["v10"]], capability
        prerequisite = row["prerequisite"]
        expected = (
            ChatLLMCompositionPrerequisite.NONE
            if prerequisite == "—"
            else ChatLLMCompositionPrerequisite(prerequisite.strip("`"))
        )
        assert policy.composition_prerequisite is expected, capability
        assert permitted_purposes(capability) == {row["purpose"]}, capability
        assert is_write_capability(capability) is (row["wr"] == "W"), capability
        assert (row["grant"] == "yes") is (capability in EXPOSED), capability
        admissible = row["opt_in"].strip() == "admissible"
        assert admissible is (capability.value in MCP_PROFILE_OPT_IN_CAPABILITY_NAMES), capability


def _grant(capability: Capability) -> ChatLLMGrantRecord:
    """A durable, active grant under the purpose the ChatLLM profile stamps."""
    if is_chatllm_data_management(capability):
        purpose = chatllm_grant_purpose(capability)
    else:
        (purpose,) = permitted_purposes(capability)
    return ChatLLMGrantRecord(
        capability=capability,
        purpose=purpose,
        is_write=is_write_capability(capability),
        resource=RESOURCE,
        scope=SCOPE,
        expires_at=None,
        revoked_at=None,
    )
