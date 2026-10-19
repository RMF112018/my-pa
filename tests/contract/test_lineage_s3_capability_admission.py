"""AT-023 (S3): the record lineage S3 capabilities are admitted as the contract states.

FAST, against the composed service and the identity registries. Worker L1's
part of the S3 contract section 10 row (registration, section 7 and 7.7):

* the six lineage reads and writes are `CHATLLM_OPERATOR_DECISION_REQUIRED`,
  scopeless, the `lineage` feature, writes keyed and attested, under their
  section 7 purposes;
* the two backfill capabilities are operator-only and
  `CHATLLM_CONTROL_PLANE_EXCLUDED` under their own `lineage_backfill` purpose;
* the backfill sub-switch withholds both unless `lineage_enabled` and
  `lineage_backfill_enabled` are both on, and each backfill handler answers
  `unsupported` while it is off, whatever the lineage switch says;
* `lineage_enabled` off withholds all eight and answers `unsupported` first;
* no S3 request admits a server-owned field.

The remaining tests of the row (the v1 and S1/S2 shapes, the widened
`records.lineage`, the web routes) are their packages'. Every value is
synthetic.
"""

from __future__ import annotations

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
from my_pa.application.commands import Command
from my_pa.application.errors import InvalidRequestError
from my_pa.application.service import (
    _LINEAGE_BACKFILL_CAPABILITIES,
    _LINEAGE_CAPABILITIES,
    ApplicationService,
)
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
from my_pa.domain.lineage.vocabulary import (
    LINEAGE_BACKFILL_CAPABILITIES,
    LINEAGE_WRITE_CAPABILITIES,
)
from my_pa.domain.policy.decision import _SCOPELESS

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
    assert len(_LINEAGE_CAPABILITIES) == 30
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
        assert policy.classification is ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED
        assert policy.exclusion_rationale == (
            "record lineage S3; exposure is an operator decision (ADR-015, OD-07)"
        )
        assert not is_operator_only(capability)
    # No data-class member moved, so the ChatLLM data profile did not either.
    assert CHATLLM_DATA_PROFILE_VERSION == "chatllm-data-v9"


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
