"""Reports Modernization WP05b Part C: the operator custody capabilities -- canonical path.

`reports.hold.place`, `reports.hold.release`, `reports.retention.set` and
`reports.retention.get` through `normalize` and `ApplicationService.invoke`
over the FAST world's in-memory general report fake: the local operator
surface (the CLI's `OperatorSurface.CLI` stamp) answers; every caller without
it -- stdio MCP, a remote client -- is `denied` before the repository is even
reached; a process without a preservation store refuses a placement
(`unavailable`, `preservation_store`) and writes no hold; a held report cannot
be trashed but can be archived, restored and updated. PostgreSQL behaviour is
`tests/database/test_reports_custody_cli.py`'s.

Every title, body and identifier is synthetic.
"""

from __future__ import annotations

from typing import Any, Final

import pytest

from my_pa.adapters.mcp.chatllm_gateway import facade_kind
from my_pa.adapters.mcp.remote import is_remote_write
from my_pa.adapters.normalization import normalize
from my_pa.adapters.remote_request import _IDEMPOTENT_REMOTE_CAPABILITIES
from my_pa.application.errors import ApplicationError, SafeDetail
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
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
from tests.conftest import FakeUnitOfWork, Scene, build_service

CUSTODY: Final = (
    Capability.REPORTS_HOLD_PLACE,
    Capability.REPORTS_HOLD_RELEASE,
    Capability.REPORTS_RETENTION_SET,
    Capability.REPORTS_RETENTION_GET,
)
WRITES: Final = CUSTODY[:3]
PUBLISH: Final[dict[str, Any]] = {
    "title": "Synthetic custody report",
    "content": {"format": "markdown", "body": "# Synthetic\n\nBody"},
    "idempotency_key": "publish-for-custody",
}


def _wire(scene: Scene, capability: Capability, payload: dict[str, Any]) -> dict[str, Any]:
    (permitted,) = permitted_purposes(capability)
    return {
        "request_id": f"req-{capability.value}",
        "purpose": permitted.value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-11-06T12:00:00Z",
        "payload": payload,
    }


def _invoke(
    service: ApplicationService,
    scene: Scene,
    capability: Capability,
    payload: dict[str, Any],
    *,
    surface: OperatorSurface | None = OperatorSurface.CLI,
) -> dict[str, Any]:
    metadata, command = normalize(capability.value, _wire(scene, capability, payload))
    envelope = service.invoke(
        metadata, command, principal=scene.principal, operator_surface=surface
    )
    return envelope.model_dump(mode="json")


def _ok(answer: dict[str, Any]) -> dict[str, Any]:
    assert answer["error"] is None, answer["error"]
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def _error(answer: dict[str, Any]) -> tuple[str, list[str]]:
    assert answer["result"] is None
    return answer["error"]["code"], answer["error"]["safe_details"]


def _publish(service: ApplicationService, scene: Scene) -> str:
    result = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, PUBLISH))
    return str(result["report_id"])


def _hold(report_id: str, revision: int, key: str = "hold-1") -> dict[str, Any]:
    return {
        "report_id": report_id,
        "expected_hold_revision": revision,
        "reason": "Synthetic litigation hold.",
        "idempotency_key": key,
    }


def _lifecycle(report_id: str, revision: int, key: str) -> dict[str, Any]:
    return {"report_id": report_id, "expected_lifecycle_revision": revision, "idempotency_key": key}


# ---- layer 1/2: classification, policy and publication -------------------------------


def test_the_four_are_classified_operator_only_with_their_own_purposes() -> None:
    for capability in CUSTODY:
        assert is_operator_only(capability), capability
        assert capability in _SCOPELESS, capability
        assert facade_kind(capability) == "operator", capability
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED
        assert "operator decision 2026-11-05" in (policy.exclusion_rationale or "")
    for capability in WRITES:
        assert is_write_capability(capability) and is_destructive_capability(capability)
        # Keyed (one replay identity, as the attested confirms).
        assert is_remote_write(capability) and capability in _IDEMPOTENT_REMOTE_CAPABILITIES
    assert not is_write_capability(Capability.REPORTS_RETENTION_GET)
    assert Capability.REPORTS_RETENTION_GET not in _IDEMPOTENT_REMOTE_CAPABILITIES
    hold = frozenset({Purpose.REPORT_HOLD})
    retention = frozenset({Purpose.REPORT_RETENTION})
    assert permitted_purposes(Capability.REPORTS_HOLD_PLACE) == hold
    assert permitted_purposes(Capability.REPORTS_HOLD_RELEASE) == hold
    assert permitted_purposes(Capability.REPORTS_RETENTION_SET) == retention
    assert permitted_purposes(Capability.REPORTS_RETENTION_GET) == retention
    # Neither purpose is implied by, or reaches, anything else.
    for capability in Capability:
        if capability not in CUSTODY:
            assert not permitted_purposes(capability) & (hold | retention), capability


# ---- layer 3/4: commands and normalization ----------------------------------------


@pytest.mark.parametrize(
    ("capability", "payload", "details"),
    [
        (
            Capability.REPORTS_HOLD_PLACE,
            {**_hold("grpt_aaaaaaaa11111111", -1)},
            ["expected_hold_revision"],
        ),
        (Capability.REPORTS_HOLD_PLACE, {**_hold("rpt_aaaaaaaa11111111", 0)}, ["artifact_id"]),
        (
            Capability.REPORTS_HOLD_RELEASE,
            {**_hold("grpt_aaaaaaaa11111111", 0), "reason": ""},
            ["reason"],
        ),
        (Capability.REPORTS_HOLD_PLACE, {**_hold("grpt_aaaaaaaa11111111", 0), "held": True}, []),
        (
            Capability.REPORTS_HOLD_PLACE,
            {**_hold("grpt_aaaaaaaa11111111", 0), "authority_class": "local_operator"},
            [],
        ),
        (
            Capability.REPORTS_RETENTION_SET,
            {"expected_policy_revision": 0, "reason": "r", "idempotency_key": "k"},
            ["period", "unset"],
        ),
        (
            Capability.REPORTS_RETENTION_SET,
            {
                "expected_policy_revision": 0,
                "reason": "r",
                "idempotency_key": "k",
                "period": {"count": 5, "unit": "years"},
                "unset": True,
            },
            ["period", "unset"],
        ),
        (
            Capability.REPORTS_RETENTION_SET,
            {
                "expected_policy_revision": 0,
                "reason": "r",
                "idempotency_key": "k",
                "period": {"count": 101, "unit": "years"},
            },
            ["period"],
        ),
        (
            Capability.REPORTS_RETENTION_SET,
            {
                "expected_policy_revision": 0,
                "reason": "r",
                "idempotency_key": "k",
                "period": {"count": 5, "unit": "months"},
            },
            ["period"],
        ),
        (
            Capability.REPORTS_RETENTION_SET,
            {
                "expected_policy_revision": 0,
                "reason": "r",
                "idempotency_key": "k",
                "unset": True,
                "policy_revision": 1,
            },
            [],
        ),
        (Capability.REPORTS_RETENTION_GET, {"history_limit": 51}, ["history_limit"]),
        (Capability.REPORTS_RETENTION_GET, {"history_limit": 0}, ["history_limit"]),
        (Capability.REPORTS_RETENTION_GET, {"principal_id": "prn_x"}, []),
    ],
)
def test_malformed_and_server_owned_fields_are_refused(
    scene: Scene, capability: Capability, payload: dict[str, Any], details: list[str]
) -> None:
    with pytest.raises(ApplicationError) as refused:
        normalize(capability.value, _wire(scene, capability, payload))
    assert refused.value.code.value == "invalid_request"
    assert [detail.value for detail in refused.value.safe_details] == details


# ---- layer 5: handlers ------------------------------------------------------------------


@pytest.mark.parametrize("capability", CUSTODY, ids=lambda c: c.value)
@pytest.mark.parametrize("surface", [None], ids=["stdio-or-remote"])
def test_a_caller_without_the_operator_surface_is_denied_before_any_read(
    scene: Scene,
    monkeypatch: pytest.MonkeyPatch,
    capability: Capability,
    surface: OperatorSurface | None,
) -> None:
    """H1: no operator surface (stdio MCP, every remote client) -> `denied`; the
    repository is never reached, so nothing is read or written."""
    service = build_service(scene.world, scene.providers)
    report_id = _publish(service, scene)
    payloads: dict[Capability, dict[str, Any]] = {
        Capability.REPORTS_HOLD_PLACE: _hold(report_id, 0),
        Capability.REPORTS_HOLD_RELEASE: _hold(report_id, 1),
        Capability.REPORTS_RETENTION_SET: {
            "expected_policy_revision": 0,
            "reason": "Synthetic.",
            "idempotency_key": "ret-1",
            "unset": True,
        },
        Capability.REPORTS_RETENTION_GET: {"report_id": report_id},
    }

    def _unreachable(self: FakeUnitOfWork) -> object:
        raise AssertionError("a custody refusal reached the general report repository")

    monkeypatch.setattr(FakeUnitOfWork, "general_reports", property(_unreachable))
    code, details = _error(
        _invoke(service, scene, capability, payloads[capability], surface=surface)
    )
    assert (code, details) == ("denied", [])
    assert not scene.world.general_report_hold_events
    assert not scene.world.general_report_retention_events


def test_place_without_a_preservation_store_is_unavailable_and_writes_no_hold(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers, report_preservation_store=None)
    report_id = _publish(service, scene)
    answer = _invoke(service, scene, Capability.REPORTS_HOLD_PLACE, _hold(report_id, 0))
    assert _error(answer) == ("unavailable", [SafeDetail.PRESERVATION_STORE.value])
    assert not scene.world.general_report_hold_events


def test_hold_blocks_trash_only_and_release_reopens_it(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report_id = _publish(service, scene)
    placed = _ok(_invoke(service, scene, Capability.REPORTS_HOLD_PLACE, _hold(report_id, 0)))
    assert placed["plane"] == "standalone"
    assert placed["operation"] == "place" and placed["held"] is True
    assert placed["hold_revision"] == 1 and placed["replayed"] is False
    preservation = placed["preservation"]
    assert set(preservation) == {
        "seal_object_id",
        "seal_sha256",
        "seal_byte_count",
        "object_count",
        "version_count",
    }
    assert preservation["seal_object_id"].startswith("grprv_")
    assert preservation["object_count"] == 1 and preservation["version_count"] == 1
    # Same request, same key: the original answer, replayed.
    again = _ok(_invoke(service, scene, Capability.REPORTS_HOLD_PLACE, _hold(report_id, 0)))
    assert again["event_id"] == placed["event_id"] and again["replayed"] is True
    # A second placement on a held report is `hold_state`; a stale revision is its own token.
    assert _error(
        _invoke(service, scene, Capability.REPORTS_HOLD_PLACE, _hold(report_id, 1, "hold-2"))
    ) == ("conflict", ["hold_state"])
    assert _error(
        _invoke(service, scene, Capability.REPORTS_HOLD_RELEASE, _hold(report_id, 0, "rel-0"))
    ) == ("conflict", ["expected_hold_revision"])
    # Trash refused while held; archive, restore and read allowed.
    assert _error(
        _invoke(service, scene, Capability.REPORTS_DELETE, _lifecycle(report_id, 0, "del-1"))
    ) == ("denied", ["report_held"])
    _ok(_invoke(service, scene, Capability.REPORTS_ARCHIVE, _lifecycle(report_id, 0, "arc-1")))
    _ok(_invoke(service, scene, Capability.REPORTS_RESTORE, _lifecycle(report_id, 1, "res-1")))
    read = _ok(_invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id}))
    assert read["held"] is True
    released = _ok(
        _invoke(service, scene, Capability.REPORTS_HOLD_RELEASE, _hold(report_id, 1, "rel-1"))
    )
    assert released["held"] is False and released["hold_revision"] == 2
    assert "preservation" not in released
    assert _error(
        _invoke(service, scene, Capability.REPORTS_HOLD_RELEASE, _hold(report_id, 2, "rel-2"))
    ) == ("conflict", ["hold_state"])
    deleted = _ok(
        _invoke(service, scene, Capability.REPORTS_DELETE, _lifecycle(report_id, 2, "del-2"))
    )
    assert deleted["lifecycle_state"] == "trashed"


def test_a_foreign_or_missing_report_is_not_found(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    missing = "grpt_aaaaaaaa11111111"
    assert _error(_invoke(service, scene, Capability.REPORTS_HOLD_PLACE, _hold(missing, 0))) == (
        "not_found",
        ["artifact_id"],
    )
    assert _error(
        _invoke(service, scene, Capability.REPORTS_RETENTION_GET, {"report_id": missing})
    ) == ("not_found", ["artifact_id"])


def test_retention_is_unset_then_set_with_append_only_history_and_eligibility(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    report_id = _publish(service, scene)
    initial = _ok(
        _invoke(service, scene, Capability.REPORTS_RETENTION_GET, {"report_id": report_id})
    )
    assert initial["policy"] is None and initial["history"] == []
    assert initial["eligibility"]["reason"] == "no_policy"
    assert initial["eligibility"]["eligible"] is False
    assert initial["eligibility"]["clock_start_strategy"] == "most_recent_trash_event"
    set_once = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_RETENTION_SET,
            {
                "expected_policy_revision": 0,
                "reason": "Synthetic policy.",
                "idempotency_key": "ret-1",
                "period": {"count": 5, "unit": "years"},
            },
        )
    )
    assert set_once["policy_revision"] == 1
    assert set_once["period"] == {"count": 5, "unit": "years"}
    assert set_once["previous_period"] is None and set_once["replayed"] is False
    assert _error(
        _invoke(
            service,
            scene,
            Capability.REPORTS_RETENTION_SET,
            {
                "expected_policy_revision": 0,
                "reason": "Synthetic stale.",
                "idempotency_key": "ret-2",
                "unset": True,
            },
        )
    ) == ("conflict", ["expected_policy_revision"])
    unset = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_RETENTION_SET,
            {
                "expected_policy_revision": 1,
                "reason": "Synthetic unset.",
                "idempotency_key": "ret-3",
                "unset": True,
            },
        )
    )
    assert unset["period"] is None and unset["previous_period"] == {"count": 5, "unit": "years"}
    view = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_RETENTION_GET,
            {"report_id": report_id, "history_limit": 1},
        )
    )
    assert view["policy"]["policy_revision"] == 2 and view["policy"]["period"] is None
    assert [item["policy_revision"] for item in view["history"]] == [2]
    assert view["history"][0]["authority_class"] == "local_operator"
    assert view["history"][0]["decision_channel"] == "local_cli"
    assert view["eligibility"]["reason"] == "no_policy"
