"""AT-023 (S4): the record lineage S4 capabilities are admitted as the contract states.

FAST, against the composed service, the gateway composition and the identity
registries. Worker M1's part of the S4 contract section 10 row (sections 6.1,
6.3, 7 and 7.6):

* all 7 S4 names are scopeless reads, `CHATLLM_DATA_CONDITIONAL` under the
  `PROGRAM_REPORTING` prerequisite (P1 client exposure, chatllm-data-v10), in
  no write, idempotent or additive set, under their section 7 purposes and
  feature rows; the 30-name lineage set is unchanged;
* S4 registers no report type and issues no grant (P1 then made the 7 data
  names the profile planner plans);
* `MY_PA_PROGRAM_REPORTING_ENABLED` and `MY_PA_LINEAGE_ENABLED` must both be on;
  the 2 Program reads also need the entity plane and the Program read factory,
  and the overview the Constraint plane;
* no S4 request admits a server-owned field, and the overview admits no
  `as_of`, `valid_at` or `project_ids`;
* `program_reporting_read` admits exactly the 2 Program reads;
* `create_database_engine` keeps its 30 s checkout timeout for every existing
  caller, and only the gateway's Program engine passes 1 s.

Every value is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Final, cast

import pytest
from tests.conftest import (
    DEFAULT_LIMITS,
    WHEN,
    FakeConstraintManagementUnitOfWork,
    FakeUnitOfWork,
    Scene,
    build_service,
    metadata_for,
)

from my_pa.adapters.mcp.chatllm_gateway import _FEATURE_BY_FAMILY
from my_pa.adapters.mcp.server import published_tools
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import _IDEMPOTENT_REMOTE_CAPABILITIES
from my_pa.application.commands import Command
from my_pa.application.errors import InvalidRequestError
from my_pa.application.service import (
    _LINEAGE_CAPABILITIES,
    _PROGRAM_READ_CAPABILITIES,
    _PROGRAM_REPORTING_CAPABILITIES,
    ApplicationService,
)
from my_pa.bootstrap.gateway import build_gateway_runtime
from my_pa.bootstrap.settings import DATABASE_URL_SCHEME, Settings
from my_pa.contracts.ports import ProgramReadUnitOfWork
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
from my_pa.domain.intelligence.catalog import BUILTIN_REPORT_TYPES
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.program.vocabulary import (
    PROGRAM_READ_CAPABILITIES,
    PROGRAM_REPORTING_CAPABILITIES,
)
from my_pa.infrastructure.database.engine import create_database_engine

S4_NAMES: Final = frozenset(
    {
        "programs.members.resolve",
        "programs.overview",
        "commitments.v2.read",
        "commitments.v2.list",
        "commitments.v2.search",
        "commitments.v2.waiting_on",
        "reports.manifest",
    }
)
_PROGRAM_READS: Final = frozenset({"programs.members.resolve", "programs.overview"})
_PURPOSES: Final = {
    "programs.members.resolve": Purpose.PROGRAM_REPORTING_READ,
    "programs.overview": Purpose.PROGRAM_REPORTING_READ,
    "commitments.v2.read": Purpose.COMMITMENT_READ,
    "commitments.v2.list": Purpose.COMMITMENT_READ,
    "commitments.v2.search": Purpose.COMMITMENT_READ,
    "commitments.v2.waiting_on": Purpose.COMMITMENT_READ,
    "reports.manifest": Purpose.REPORT_READ,
}
_FEATURES: Final = {"programs": "programs", "commitments": "work", "reports": "reports"}
_PROGRAM: Final = "ent_lineages4fast0001"
_BASE_PAYLOADS: Final[dict[str, dict[str, object]]] = {
    "programs.members.resolve": {"program_entity_ids": [_PROGRAM]},
    "programs.overview": {"program_entity_ids": [_PROGRAM]},
    "commitments.v2.read": {"commitment_id": "cmt_lineages4fast0001"},
    "commitments.v2.list": {"project_ids": ["prj_lineages4fast0001"]},
    "commitments.v2.search": {"query": "synthetic", "project_ids": ["prj_lineages4fast0001"]},
    "commitments.v2.waiting_on": {"project_ids": ["prj_lineages4fast0001"]},
    "reports.manifest": {"report_id": "rpt_lineages4fast0001"},
}
_SERVER_OWNED: Final = (
    "principal_id",
    "actor_class",
    "authority_class",
    "decision_channel",
    "source_cutoff_at",
    "lineage_known_at",
    "overview_sha256",
    "manifest_sha256",
    "grant",
    "selector",
)
_A_URL: Final = f"{DATABASE_URL_SCHEME}://someone@db.invalid:5432/somewhere"


def _s4() -> frozenset[Capability]:
    return frozenset(capability for capability in Capability if capability.value in S4_NAMES)


def _arguments(name: str, payload: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "req-lineage-s4-fast",
        "purpose": sorted(permitted_purposes(Capability(name)))[0].value,
        "principal_id": "prn_lineages4fast0001",
        "requested_at": "2026-10-24T12:00:00Z",
        "payload": payload,
    }


def _command(name: str, payload: dict[str, object] | None = None) -> Command:
    _metadata, command = normalize(
        name, _arguments(name, _BASE_PAYLOADS[name] if payload is None else payload)
    )
    return command


class _NoProgramReads:
    """A Program read factory stand-in: composed, never opened in FAST."""

    def __call__(self) -> ProgramReadUnitOfWork:
        raise AssertionError("no FAST test opens a Program read")


def _service(
    scene: Scene,
    *,
    lineage: bool = True,
    program: bool = True,
    entities: bool = True,
    factory: bool = True,
    constraints: bool = True,
) -> ApplicationService:
    world = scene.world
    return ApplicationService(
        unit_of_work=lambda: FakeUnitOfWork(world),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        constraint_management_unit_of_work=(
            (lambda: FakeConstraintManagementUnitOfWork(world)) if constraints else None
        ),
        relationship_intelligence_enabled=entities,
        lineage_enabled=lineage,
        program_reporting_enabled=program,
        program_read_unit_of_work=(
            cast(Callable[[], ProgramReadUnitOfWork], _NoProgramReads()) if factory else None
        ),
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


def test_s4_capabilities_are_operator_decision_required_reads() -> None:
    declared = _s4()
    assert {capability.value for capability in declared} == S4_NAMES
    assert declared == _PROGRAM_REPORTING_CAPABILITIES
    assert {capability.value for capability in declared} == PROGRAM_REPORTING_CAPABILITIES
    assert {c.value for c in _PROGRAM_READ_CAPABILITIES} == PROGRAM_READ_CAPABILITIES
    assert PROGRAM_READ_CAPABILITIES == _PROGRAM_READS
    # Not lineage capabilities: the lineage switch set (30 names at S4, 34
    # since S3.1 adds its 4) never holds an S4 name.
    assert not declared & _LINEAGE_CAPABILITIES
    assert len(_LINEAGE_CAPABILITIES) == 34
    assert len(list(Capability)) == 233
    for capability in declared:
        name = capability.value
        assert capability in _SCOPELESS
        assert _FEATURE_BY_FAMILY[name.split(".", 1)[0]] == _FEATURES[name.split(".", 1)[0]]
        assert permitted_purposes(capability) == frozenset({_PURPOSES[name]})
        assert not is_write_capability(capability)
        assert not is_destructive_capability(capability)
        assert capability not in _IDEMPOTENT_REMOTE_CAPABILITIES
        assert not is_operator_only(capability)
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        # P1 client exposure (operator directive 2026-10-26, chatllm-data-v10):
        # the ChatLLM decision is made; the 7 are plane-conditional data.
        assert policy.classification is ChatLLMCapabilityClass.DATA_CONDITIONAL
        assert policy.composition_prerequisite is ChatLLMCompositionPrerequisite.PROGRAM_REPORTING
        assert policy.exclusion_rationale is None


def test_s4_registers_no_report_type_and_issues_no_grant() -> None:
    # The built-in report types are the S3 set: no Program report type.
    assert len(BUILTIN_REPORT_TYPES) == 5
    assert all("program" not in str(kind) for kind, _stage, _name, _text in BUILTIN_REPORT_TYPES)
    # P1 client exposure (operator directive 2026-10-26): every S4 name is in
    # `DATA_CONDITIONAL`, so the profile planner -- never a bootstrap source --
    # plans its grant; the data profile moved to v10 with it.
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v10"
    assert all(
        CHATLLM_CAPABILITY_POLICY[capability].classification
        is ChatLLMCapabilityClass.DATA_CONDITIONAL
        for capability in _s4()
    )
    # No grant, profile or client allowlist source names an S4 capability.
    source = Path(__file__).resolve().parents[2] / "src" / "my_pa" / "bootstrap"
    for path in source.glob("*profile*.py"):
        text = path.read_text(encoding="utf-8")
        for name in S4_NAMES:
            assert name not in text, (path.name, name)


@pytest.mark.parametrize(("lineage", "program"), [(True, False), (False, True), (False, False)])
def test_switch_off_withholds_every_s4_capability(
    scene: Scene, lineage: bool, program: bool
) -> None:
    declared = _s4()
    off = _service(scene, lineage=lineage, program=program)
    on = _service(scene)
    assert not off.available_capabilities & declared
    assert declared <= on.available_capabilities
    names = {capability.value for capability in declared}
    published_off = {tool.name for tool in published_tools(off, authenticated_client_present=True)}
    published_on = {tool.name for tool in published_tools(on, authenticated_client_present=True)}
    assert not published_off & names
    assert names <= published_on
    # The default test build has neither switch on.
    default = build_service(scene.world, scene.providers)
    assert not default.available_capabilities & declared
    for name in sorted(names):
        # The switch first: a stamped operator surface still answers `unsupported`.
        assert _code(_invoke(off, scene, name)) == "unsupported", name


@pytest.mark.parametrize("missing", ["entities", "factory"])
def test_program_reads_need_the_entity_plane_and_their_factory(scene: Scene, missing: str) -> None:
    withheld = _service(scene, **{missing: False})  # type: ignore[arg-type]
    served = withheld.available_capabilities
    assert not served & _PROGRAM_READ_CAPABILITIES
    # The other 5 follow the switches only.
    assert _s4() - _PROGRAM_READ_CAPABILITIES <= served
    for name in sorted(_PROGRAM_READS):
        assert _code(_invoke(withheld, scene, name)) == "unsupported", name


def test_program_overview_needs_the_constraint_plane(scene: Scene) -> None:
    withheld = _service(scene, constraints=False)
    served = withheld.available_capabilities
    assert Capability.PROGRAMS_OVERVIEW not in served
    assert Capability.PROGRAMS_MEMBERS_RESOLVE in served
    assert _code(_invoke(withheld, scene, "programs.overview")) == "unsupported"


@pytest.mark.parametrize("name", sorted(_BASE_PAYLOADS))
def test_s4_requests_reject_server_owned_fields(name: str) -> None:
    base = _BASE_PAYLOADS[name]
    command = _command(name)
    assert command.capability.value == name
    for field in _SERVER_OWNED:
        with pytest.raises(InvalidRequestError):
            normalize(name, _arguments(name, {**base, field: "server-owned"}))


@pytest.mark.parametrize(
    "payload",
    [
        {"program_entity_ids": [_PROGRAM], "as_of": "2026-10-01T00:00:00Z"},
        {"program_entity_ids": [_PROGRAM], "valid_at": "2026-10-01T00:00:00Z"},
        {"program_entity_ids": [_PROGRAM], "project_ids": ["prj_lineages4fast0001"]},
        {"program_entity_ids": []},
        {"program_entity_ids": [_PROGRAM, _PROGRAM]},
        {"program_entity_ids": [f"ent_lineages4fast{index:04d}" for index in range(11)]},
        {"program_entity_ids": ["prj_lineages4fast0001"]},
    ],
)
def test_program_overview_admits_no_as_of(payload: dict[str, object]) -> None:
    with pytest.raises(InvalidRequestError):
        normalize("programs.overview", _arguments("programs.overview", payload))
    # The resolver admits `valid_at` with an offset, and only with one.
    normalize(
        "programs.members.resolve",
        _arguments(
            "programs.members.resolve",
            {"program_entity_ids": [_PROGRAM], "valid_at": "2026-10-01T00:00:00+00:00"},
        ),
    )
    with pytest.raises(InvalidRequestError):
        normalize(
            "programs.members.resolve",
            _arguments(
                "programs.members.resolve",
                {"program_entity_ids": [_PROGRAM], "valid_at": "2026-10-01T00:00:00"},
            ),
        )


def test_the_program_purpose_admits_exactly_the_program_reads() -> None:
    using = {
        capability.value
        for capability in Capability
        if Purpose.PROGRAM_REPORTING_READ in permitted_purposes(capability)
    }
    assert using == _PROGRAM_READS
    # No Program read may be reached through `report_read` (or any other purpose).
    for name in _PROGRAM_READS:
        assert permitted_purposes(Capability(name)) == frozenset({Purpose.PROGRAM_REPORTING_READ})
    assert len(list(Purpose)) == 60


def test_create_database_engine_keeps_its_default_checkout_timeout() -> None:
    default = create_database_engine(_A_URL)
    try:
        assert default.pool.timeout() == 30
    finally:
        default.dispose()
    with pytest.raises(ValueError, match="pool_timeout_seconds"):
        create_database_engine(_A_URL, pool_timeout_seconds=0)
    off = build_gateway_runtime(Settings(database_url=_A_URL))
    try:
        # Switch off: no third engine, and the 2 existing pools keep 30 s.
        assert off.program_read_engine is None
        assert off.work_engine.pool.timeout() == 30
        assert off.audit_engine.pool.timeout() == 30
    finally:
        off.close()
    on = build_gateway_runtime(
        Settings(database_url=_A_URL, lineage_enabled=True, program_reporting_enabled=True)
    )
    try:
        engine = on.program_read_engine
        assert engine is not None
        assert engine.pool.timeout() == 1
        assert engine.pool.size() == on.work_engine.pool.size() == 5
        assert engine.pool is not on.work_engine.pool
        assert engine.pool is not on.audit_engine.pool
        assert on.work_engine.pool.timeout() == 30
        assert on.audit_engine.pool.timeout() == 30
        assert Capability.PROGRAMS_MEMBERS_RESOLVE not in on.service.available_capabilities
        assert Capability.REPORTS_MANIFEST in on.service.available_capabilities
    finally:
        on.close()
