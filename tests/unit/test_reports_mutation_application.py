"""Reports Modernization WP03: update, history, archive, delete, restore -- canonical path.

Through `normalize` and `ApplicationService.invoke` -- the exact path every
local transport takes -- over the FAST world's in-memory general report fake.
PostgreSQL behaviour (the real repository, locking, row counts) is
`tests/database/test_reports_general_application.py`'s and
`tests/database/test_reports_general_mutation.py`'s.

Every title, body and identifier is synthetic.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any, Final

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import (
    ArchiveGeneralReport,
    GetGeneralReportHistory,
    UpdateGeneralReport,
)
from my_pa.application.errors import ApplicationError, InvalidRequestError, SafeDetail
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import ReportIntegrityError
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.reports.manifest import manifest_digest
from tests.conftest import Scene, build_service, metadata_for, operator

BODY: Final = "# Assessment\n\nReport text"
PUBLISH: Final[dict[str, Any]] = {
    "title": "Project Schedule Risk Assessment",
    "content": {"format": "markdown", "body": BODY},
    "idempotency_key": "publish-for-mutation",
    "type": "schedule_risk",
    "summary": "A synthetic summary.",
    "topics": ["schedule"],
}
WRITES: Final = (
    Capability.REPORTS_UPDATE,
    Capability.REPORTS_ARCHIVE,
    Capability.REPORTS_DELETE,
    Capability.REPORTS_RESTORE,
)
LIFECYCLE: Final = (
    Capability.REPORTS_ARCHIVE,
    Capability.REPORTS_DELETE,
    Capability.REPORTS_RESTORE,
)
ALL: Final = (*WRITES, Capability.REPORTS_HISTORY)

#: Server-derived fields a caller might forge, each a bare `invalid_request`.
FORGED: Final = (
    "principal_id",
    "owner",
    "version_id",
    "version_number",
    "receipt_id",
    "manifest",
    "manifest_sha256",
    "recorded_at",
    "created_at",
    "verification",
    "lifecycle_state",
    "lifecycle_event_id",
    "event_id",
    "prior_state",
    "resulting_state",
    "content_id",
)


def _wire(
    scene: Scene, capability: Capability, payload: dict[str, Any], purpose: Purpose | None = None
) -> dict[str, Any]:
    (permitted,) = permitted_purposes(capability)
    return {
        "request_id": f"req-{capability.value}",
        "purpose": (purpose or permitted).value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-11-04T12:00:00Z",
        "payload": payload,
    }


def _invoke(
    service: ApplicationService,
    scene: Scene,
    capability: Capability,
    payload: dict[str, Any],
    *,
    principal: Principal | None = None,
) -> dict[str, Any]:
    metadata, command = normalize(capability.value, _wire(scene, capability, payload))
    envelope = service.invoke(metadata, command, principal=principal or scene.principal)
    return envelope.model_dump(mode="json")


def _ok(answer: dict[str, Any]) -> dict[str, Any]:
    assert answer["error"] is None, answer["error"]
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def _error(answer: dict[str, Any]) -> tuple[str, list[str]]:
    assert answer["result"] is None
    return answer["error"]["code"], answer["error"]["safe_details"]


def _refusal(capability: Capability, payload: dict[str, Any]) -> ApplicationError:
    with pytest.raises(ApplicationError) as refused:
        normalize(
            capability.value,
            {
                "request_id": "req",
                "purpose": next(iter(permitted_purposes(capability))).value,
                "principal_id": "prn_aaaa0001aaaa0001aaaa0001",
                "requested_at": "2026-11-04T12:00:00Z",
                "payload": payload,
            },
        )
    return refused.value


def _published(service: ApplicationService, scene: Scene) -> dict[str, Any]:
    return _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, dict(PUBLISH)))


def _update(report_id: str, key: str, patch: dict[str, Any], **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "report_id": report_id,
        "expected_version": extra.pop("expected_version", 1),
        "patch": patch,
        "change_reason": extra.pop("change_reason", "A synthetic revision."),
        "idempotency_key": key,
        **extra,
    }


def _move(report_id: str, key: str, revision: int, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
    return {
        "report_id": report_id,
        "expected_lifecycle_revision": revision,
        "idempotency_key": key,
        **extra,
    }


# ---- vocabulary and authorization ---------------------------------------------------------


def test_the_five_are_registered_with_their_purposes_and_classes() -> None:
    assert permitted_purposes(Capability.REPORTS_UPDATE) == {Purpose.REPORT_AUTHORING}
    assert permitted_purposes(Capability.REPORTS_HISTORY) == {Purpose.REPORT_READ}
    for capability in LIFECYCLE:
        assert permitted_purposes(capability) == {Purpose.REPORT_LIFECYCLE}
    for capability in WRITES:
        assert is_write_capability(capability)
        assert is_destructive_capability(capability)
    assert not is_write_capability(Capability.REPORTS_HISTORY)
    for capability in ALL:
        assert not is_operator_only(capability)
        assert capability in _SCOPELESS
    assert Purpose.REPORT_LIFECYCLE.value == "report_lifecycle"
    # Least privilege (D1): no other capability takes the lifecycle purpose.
    assert {
        capability
        for capability in Capability
        if Purpose.REPORT_LIFECYCLE in permitted_purposes(capability)
    } == set(LIFECYCLE)


@pytest.mark.parametrize("capability", LIFECYCLE)
def test_report_authoring_alone_cannot_move_a_lifecycle(
    scene: Scene, capability: Capability
) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    command = normalize(
        capability.value, _wire(scene, capability, _move(report["report_id"], "k", 0))
    )[1]
    envelope = service.invoke(
        metadata_for(capability, Purpose.REPORT_AUTHORING, scene.principal),
        command,
        principal=scene.principal,
    ).model_dump(mode="json")
    assert envelope["error"]["code"] == ErrorCode.DENIED.value
    assert not scene.world.general_report_events


def test_report_lifecycle_alone_cannot_update(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    command = normalize(
        Capability.REPORTS_UPDATE.value,
        _wire(scene, Capability.REPORTS_UPDATE, _update(report["report_id"], "k", {"title": "T2"})),
    )[1]
    envelope = service.invoke(
        metadata_for(Capability.REPORTS_UPDATE, Purpose.REPORT_LIFECYCLE, scene.principal),
        command,
        principal=scene.principal,
    ).model_dump(mode="json")
    assert envelope["error"]["code"] == ErrorCode.DENIED.value
    assert (
        len(scene.world.general_report_ledger[(scene.principal.principal_id, report["report_id"])])
        == 1
    )


# ---- update -------------------------------------------------------------------------------


def test_a_metadata_update_reuses_the_content_and_reads_back(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    updated = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_UPDATE,
            _update(report["report_id"], "u1", {"title": "Revised title", "tags": ["risk"]}),
        )
    )
    assert updated["plane"] == "standalone"
    assert updated["outcome"] == "applied"
    assert updated["version_number"] == 2
    assert updated["version_id"].startswith("grver_")
    assert updated["change_kind"] == "metadata"
    assert updated["content_id"] == report["content"]["content_id"]
    assert updated["decoded_sha256"] == report["content"]["decoded_sha256"]
    assert updated["replayed"] is False
    receipt = updated["receipt"]
    assert receipt["receipt_id"].startswith("grrc_")
    assert receipt["operation"] == "update"
    assert receipt["outcome"] == "applied"
    assert receipt["expected_version"] == 1
    read = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_READ,
            {"report_id": report["report_id"], "include_manifest": True},
        )
    )
    assert read["version_number"] == 2
    assert read["head_version_number"] == 2
    assert read["title"] == "Revised title"
    assert read["tags"] == ["risk"]
    # Untouched fields carry forward.
    assert read["type"] == "schedule_risk"
    assert read["topics"] == ["schedule"]
    assert read["change_reason"] == "A synthetic revision."
    assert read["supersedes_version_id"] == report["version_id"]
    assert manifest_digest(read["manifest"]) == updated["manifest_sha256"]
    first = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_READ,
            {"report_id": report["report_id"], "version_number": 1},
        )
    )
    assert first["title"] == PUBLISH["title"]
    assert first["change_reason"] is None


def test_a_content_update_is_a_content_version(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    body = "# Assessment\n\nRevised text"
    updated = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_UPDATE,
            _update(report["report_id"], "u1", {"content": {"format": "markdown", "body": body}}),
        )
    )
    assert updated["change_kind"] == "content"
    assert updated["content_id"] != report["content"]["content_id"]
    assert updated["decoded_sha256"] == hashlib.sha256(body.encode()).hexdigest()
    read = _ok(_invoke(service, scene, Capability.REPORTS_READ, {"report_id": report["report_id"]}))
    assert read["content"]["body"] == body


def test_an_unchanged_patch_is_a_no_op(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    answer = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_UPDATE,
            _update(report["report_id"], "u1", {"title": PUBLISH["title"]}),
        )
    )
    assert answer["outcome"] == "no_op"
    assert answer["change_kind"] is None
    assert answer["version_number"] == 1
    assert answer["version_id"] == report["version_id"]
    assert answer["receipt"]["outcome"] == "no_op"


def test_clear_fields_clears_and_conflicts_are_refused(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_UPDATE,
            _update(report["report_id"], "u1", {}, clear_fields=["type", "summary"]),
        )
    )
    read = _ok(_invoke(service, scene, Capability.REPORTS_READ, {"report_id": report["report_id"]}))
    assert read["type"] is None
    assert read["summary"] is None
    for clear, detail in (
        (["summary", "summary"], SafeDetail.CLEAR_FIELDS),
        (["title"], SafeDetail.CLEAR_FIELDS),
        ("summary", SafeDetail.CLEAR_FIELDS),
        ([1], SafeDetail.CLEAR_FIELDS),
    ):
        refusal = _refusal(
            Capability.REPORTS_UPDATE, _update(report["report_id"], "x", {}, clear_fields=clear)
        )
        assert isinstance(refusal, InvalidRequestError)
        assert refusal.safe_details == (detail,), clear
    both = _refusal(
        Capability.REPORTS_UPDATE,
        _update(report["report_id"], "x", {"summary": "s"}, clear_fields=["summary"]),
    )
    assert both.safe_details == (SafeDetail.CLEAR_FIELDS,)


def test_a_replay_answers_the_original_and_a_changed_retry_conflicts(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    payload = _update(report["report_id"], "u1", {"title": "Revised"})
    first = _ok(_invoke(service, scene, Capability.REPORTS_UPDATE, payload))
    again = _ok(_invoke(service, scene, Capability.REPORTS_UPDATE, payload))
    assert again["replayed"] is True
    assert {k: v for k, v in again.items() if k != "replayed"} == {
        k: v for k, v in first.items() if k != "replayed"
    }
    changed = _invoke(
        service, scene, Capability.REPORTS_UPDATE, {**payload, "change_reason": "Other."}
    )
    assert _error(changed) == (ErrorCode.CONFLICT.value, ["idempotency_key"])
    key = (scene.principal.principal_id, report["report_id"])
    assert len(scene.world.general_report_ledger[key]) == 2


def test_a_stale_expected_version_is_a_conflict_and_writes_nothing(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_UPDATE,
            _update(report["report_id"], "u1", {"title": "A"}),
        )
    )
    stale = _invoke(
        service,
        scene,
        Capability.REPORTS_UPDATE,
        _update(report["report_id"], "u2", {"title": "B"}),
    )
    assert _error(stale) == (ErrorCode.CONFLICT.value, ["stale_version"])
    key = (scene.principal.principal_id, report["report_id"])
    assert len(scene.world.general_report_ledger[key]) == 2
    assert (scene.principal.principal_id, "u2") not in scene.world.general_report_update_receipts


@pytest.mark.parametrize("move", [Capability.REPORTS_ARCHIVE, Capability.REPORTS_DELETE])
def test_a_withdrawn_report_refuses_every_update(scene: Scene, move: Capability) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    _ok(_invoke(service, scene, move, _move(report["report_id"], "m1", 0)))
    for patch in ({"title": "A"}, {"content": {"format": "text", "body": "new"}}):
        refused = _invoke(
            service, scene, Capability.REPORTS_UPDATE, _update(report["report_id"], "u1", patch)
        )
        assert _error(refused) == (ErrorCode.DENIED.value, ["report_withdrawn"])
    key = (scene.principal.principal_id, report["report_id"])
    assert len(scene.world.general_report_ledger[key]) == 1


def test_foreign_and_missing_reports_are_one_not_found(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    stranger = operator()
    answers = [
        _invoke(
            service,
            scene,
            Capability.REPORTS_UPDATE,
            _update(report["report_id"], "u1", {"title": "A"}),
            principal=stranger,
        ),
        _invoke(
            service,
            scene,
            Capability.REPORTS_UPDATE,
            _update("grpt_00000000nothere0", "u1", {"title": "A"}),
        ),
        _invoke(
            service,
            scene,
            Capability.REPORTS_ARCHIVE,
            _move(report["report_id"], "a1", 0),
            principal=stranger,
        ),
        _invoke(service, scene, Capability.REPORTS_DELETE, _move("grpt_00000000nothere0", "d", 0)),
        _invoke(
            service,
            scene,
            Capability.REPORTS_HISTORY,
            {"report_id": report["report_id"]},
            principal=stranger,
        ),
        _invoke(service, scene, Capability.REPORTS_HISTORY, {"report_id": "grpt_00000000nothere0"}),
        _invoke(service, scene, Capability.REPORTS_READ, {"report_id": "grpt_00000000nothere0"}),
    ]
    errors = [{k: v for k, v in a["error"].items() if k != "correlation_id"} for a in answers]
    assert errors[0]["code"] == ErrorCode.NOT_FOUND.value
    assert errors[0]["safe_details"] == ["artifact_id"]
    assert all(error == errors[0] for error in errors)
    assert report["report_id"] not in json.dumps(answers)
    assert not scene.world.general_report_events


def test_a_foreign_association_in_a_patch_is_not_found(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    foreign = _ok(
        _invoke(service, scene, Capability.REPORTS_PUBLISH, dict(PUBLISH), principal=operator())
    )
    refused = _invoke(
        service,
        scene,
        Capability.REPORTS_UPDATE,
        _update(
            report["report_id"],
            "u1",
            {
                "associations": [
                    {
                        "target_kind": "standalone_report",
                        "target_ref": foreign["report_id"],
                        "relation": "follows",
                    }
                ]
            },
        ),
    )
    assert _error(refused) == (ErrorCode.NOT_FOUND.value, ["associations"])


@pytest.mark.parametrize(
    ("patch", "detail"),
    [
        ({"title": None}, SafeDetail.TITLE),
        ({"summary": None}, SafeDetail.SUMMARY),
        ({"type": None}, SafeDetail.REPORT_TYPE),
        ({"metadata": None}, SafeDetail.METADATA),
        ({"coverage_period": {"start": None}}, SafeDetail.COVERAGE_PERIOD),
        (
            {
                "associations": [
                    {
                        "target_kind": "external_source",
                        "target_ref": "x",
                        "relation": "cites",
                        "target_version_ref": None,
                    }
                ]
            },
            SafeDetail.ASSOCIATIONS,
        ),
        ({"title": "   "}, SafeDetail.TITLE),
        ({"topics": ["a", "A"]}, SafeDetail.TOPICS),
        ({"report_date": "2026-13-01"}, SafeDetail.REPORT_DATE),
        ({"content": {"format": "pdf", "body": "x"}}, SafeDetail.CONTENT),
        ({"metadata": {"_reserved": 1}}, SafeDetail.METADATA),
        ({}, SafeDetail.PATCH),
    ],
)
def test_a_bad_patch_names_its_field(patch: dict[str, Any], detail: SafeDetail) -> None:
    refusal = _refusal(Capability.REPORTS_UPDATE, _update("grpt_00000000abcdefgh", "k", patch))
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details[0] is detail


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"expected_version": 0}, SafeDetail.EXPECTED_VERSION),
        ({"expected_version": True}, SafeDetail.EXPECTED_VERSION),
        ({"change_reason": ""}, SafeDetail.CHANGE_REASON),
        ({"change_reason": "x" * 501}, SafeDetail.CHANGE_REASON),
        ({"report_id": "rpt_00000000abcdefgh"}, SafeDetail.ARTIFACT_ID),
        ({"patch": "not-an-object"}, SafeDetail.PATCH),
        ({"idempotency_key": ""}, SafeDetail.IDEMPOTENCY_KEY),
    ],
)
def test_bad_update_fields_name_themselves(payload: dict[str, Any], detail: SafeDetail) -> None:
    refusal = _refusal(
        Capability.REPORTS_UPDATE,
        {**_update("grpt_00000000abcdefgh", "k", {"title": "T"}), **payload},
    )
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details[0] is detail


def test_change_reason_is_required() -> None:
    payload = _update("grpt_00000000abcdefgh", "k", {"title": "T"})
    del payload["change_reason"]
    refusal = _refusal(Capability.REPORTS_UPDATE, payload)
    assert isinstance(refusal, InvalidRequestError)


@pytest.mark.parametrize("capability", ALL)
@pytest.mark.parametrize("field", FORGED)
def test_a_forged_server_field_is_a_bare_refusal(capability: Capability, field: str) -> None:
    base: dict[str, Any] = (
        _update("grpt_00000000abcdefgh", "k", {"title": "T"})
        if capability is Capability.REPORTS_UPDATE
        else {"report_id": "grpt_00000000abcdefgh"}
        if capability is Capability.REPORTS_HISTORY
        else _move("grpt_00000000abcdefgh", "k", 0)
    )
    refusal = _refusal(capability, {**base, field: "forged"})
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details == ()


@pytest.mark.parametrize("field", ["version_number", "principal_id", "client_intent_id", "owner"])
def test_a_server_or_unknown_field_inside_patch_is_a_bare_refusal(field: str) -> None:
    refusal = _refusal(
        Capability.REPORTS_UPDATE, _update("grpt_00000000abcdefgh", "k", {"title": "T", field: 1})
    )
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details == ()


@pytest.mark.parametrize(
    ("field", "detail"),
    [("cycle_run_id", "cycle_run_id"), ("stage", "stage"), ("focus_area", "focus_area_id")],
)
def test_a_pipeline_field_is_refused_by_name(field: str, detail: str) -> None:
    top = _refusal(
        Capability.REPORTS_UPDATE,
        {**_update("grpt_00000000abcdefgh", "k", {"title": "T"}), field: "x"},
    )
    inside = _refusal(
        Capability.REPORTS_UPDATE, _update("grpt_00000000abcdefgh", "k", {"title": "T", field: "x"})
    )
    lifecycle = _refusal(
        Capability.REPORTS_ARCHIVE, {**_move("grpt_00000000abcdefgh", "k", 0), field: "x"}
    )
    for refusal in (top, inside, lifecycle):
        assert [item.value for item in refusal.safe_details] == [detail]


# ---- lifecycle ----------------------------------------------------------------------------


def test_archive_delete_restore_round_trip_returns_to_archived(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    rid = report["report_id"]
    archived = _ok(
        _invoke(service, scene, Capability.REPORTS_ARCHIVE, _move(rid, "a", 0, reason="Old."))
    )
    assert archived["plane"] == "standalone"
    assert archived["operation"] == "archive"
    assert archived["outcome"] == "applied"
    assert archived["prior_state"] == "active"
    assert archived["lifecycle_state"] == "archived"
    assert archived["lifecycle_revision"] == 1
    assert archived["event_id"].startswith("grlev_")
    assert archived["receipt"]["expected_lifecycle_revision"] == 0
    trashed = _ok(_invoke(service, scene, Capability.REPORTS_DELETE, _move(rid, "d", 1)))
    assert (trashed["prior_state"], trashed["lifecycle_state"]) == ("archived", "trashed")
    restored = _ok(_invoke(service, scene, Capability.REPORTS_RESTORE, _move(rid, "r", 2)))
    assert (restored["prior_state"], restored["lifecycle_state"]) == ("trashed", "archived")
    assert restored["lifecycle_revision"] == 3
    # Readable only with include_withdrawn; every version intact.
    hidden = _invoke(service, scene, Capability.REPORTS_READ, {"report_id": rid})
    assert _error(hidden)[0] == ErrorCode.NOT_FOUND.value
    shown = _ok(
        _invoke(
            service, scene, Capability.REPORTS_READ, {"report_id": rid, "include_withdrawn": True}
        )
    )
    assert shown["lifecycle_state"] == "archived"
    assert shown["lifecycle_revision"] == 3
    assert shown["content"]["body"] == BODY
    active = _ok(_invoke(service, scene, Capability.REPORTS_RESTORE, _move(rid, "r2", 3)))
    assert active["lifecycle_state"] == "active"


def test_archive_on_archived_is_a_no_op_and_replays(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    rid = _published(service, scene)["report_id"]
    first = _ok(_invoke(service, scene, Capability.REPORTS_ARCHIVE, _move(rid, "a", 0)))
    noop = _ok(_invoke(service, scene, Capability.REPORTS_ARCHIVE, _move(rid, "a2", 1)))
    assert noop["outcome"] == "no_op"
    assert noop["lifecycle_revision"] == 1
    assert noop["event_id"] == first["event_id"]
    replay = _ok(_invoke(service, scene, Capability.REPORTS_ARCHIVE, _move(rid, "a", 0)))
    assert replay["replayed"] is True
    assert replay["receipt"]["receipt_id"] == first["receipt"]["receipt_id"]
    conflict = _invoke(service, scene, Capability.REPORTS_ARCHIVE, _move(rid, "a", 0, reason="x"))
    assert _error(conflict) == (ErrorCode.CONFLICT.value, ["idempotency_key"])


@pytest.mark.parametrize(
    ("setup", "move"),
    [
        ((), Capability.REPORTS_RESTORE),
        ((Capability.REPORTS_DELETE,), Capability.REPORTS_DELETE),
        ((Capability.REPORTS_DELETE,), Capability.REPORTS_ARCHIVE),
    ],
)
def test_an_illegal_move_is_a_lifecycle_state_conflict(
    scene: Scene, setup: tuple[Capability, ...], move: Capability
) -> None:
    service = build_service(scene.world, scene.providers)
    rid = _published(service, scene)["report_id"]
    for revision, step in enumerate(setup):
        _ok(_invoke(service, scene, step, _move(rid, f"s{revision}", revision)))
    events = list(scene.world.general_report_events.get((scene.principal.principal_id, rid), []))
    refused = _invoke(service, scene, move, _move(rid, "illegal", len(setup)))
    assert _error(refused) == (ErrorCode.CONFLICT.value, ["lifecycle_state"])
    assert scene.world.general_report_events.get((scene.principal.principal_id, rid), []) == events


def test_a_stale_lifecycle_revision_is_a_conflict(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    rid = _published(service, scene)["report_id"]
    stale = _invoke(service, scene, Capability.REPORTS_ARCHIVE, _move(rid, "a", 5))
    assert _error(stale) == (ErrorCode.CONFLICT.value, ["expected_lifecycle_revision"])
    assert not scene.world.general_report_events.get((scene.principal.principal_id, rid))


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"expected_lifecycle_revision": -1}, SafeDetail.EXPECTED_LIFECYCLE_REVISION),
        ({"expected_lifecycle_revision": False}, SafeDetail.EXPECTED_LIFECYCLE_REVISION),
        ({"reason": ""}, SafeDetail.REASON),
        ({"reason": "x" * 501}, SafeDetail.REASON),
        ({"report_id": "cap_00000000abcdefgh"}, SafeDetail.ARTIFACT_ID),
    ],
)
@pytest.mark.parametrize("capability", LIFECYCLE)
def test_bad_lifecycle_fields_name_themselves(
    capability: Capability, payload: dict[str, Any], detail: SafeDetail
) -> None:
    refusal = _refusal(capability, {**_move("grpt_00000000abcdefgh", "k", 0), **payload})
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details == (detail,)


# ---- history ------------------------------------------------------------------------------


def test_version_history_pages_oldest_first_with_a_cursor(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    report = _published(service, scene)
    rid = report["report_id"]
    for number in range(1, 4):
        _ok(
            _invoke(
                service,
                scene,
                Capability.REPORTS_UPDATE,
                _update(rid, f"u{number}", {"title": f"T{number}"}, expected_version=number),
            )
        )
    page = _ok(
        _invoke(service, scene, Capability.REPORTS_HISTORY, {"report_id": rid, "page_size": 3})
    )
    assert page["plane"] == "standalone"
    assert page["entries"] == "versions"
    assert page["head_version_number"] == 4
    assert page["lifecycle_state"] == "active"
    assert [item["version_number"] for item in page["items"]] == [1, 2, 3]
    assert page["next_cursor"] == page["items"][-1]["version_id"]
    item = page["items"][1]
    assert item["change_kind"] == "metadata"
    assert item["change_reason"] == "A synthetic revision."
    assert item["content"]["content_id"] == report["content"]["content_id"]
    assert set(item["content"]) == {
        "content_id",
        "format",
        "encoding",
        "storage_kind",
        "decoded_sha256",
        "decoded_byte_count",
        "canonical_sha256",
        "original_sha256",
    }
    assert "manifest" not in item
    assert BODY not in json.dumps(page)
    rest = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_HISTORY,
            {"report_id": rid, "page_size": 3, "after": page["next_cursor"]},
        )
    )
    assert [item["version_number"] for item in rest["items"]] == [4]
    assert rest["next_cursor"] is None
    with_manifests = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_HISTORY,
            {"report_id": rid, "include_manifests": True},
        )
    )
    assert len(with_manifests["items"]) == 4
    for entry in with_manifests["items"]:
        assert manifest_digest(entry["manifest"]) == entry["manifest_sha256"]


def test_lifecycle_history_lists_every_event(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    rid = _published(service, scene)["report_id"]
    empty = _ok(
        _invoke(
            service, scene, Capability.REPORTS_HISTORY, {"report_id": rid, "entries": "lifecycle"}
        )
    )
    assert empty["items"] == []
    assert empty["next_cursor"] is None
    _ok(_invoke(service, scene, Capability.REPORTS_ARCHIVE, _move(rid, "a", 0, reason="Done.")))
    _ok(_invoke(service, scene, Capability.REPORTS_RESTORE, _move(rid, "r", 1)))
    page = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_HISTORY,
            {"report_id": rid, "entries": "lifecycle", "page_size": 1},
        )
    )
    assert page["entries"] == "lifecycle"
    assert page["items"][0]["operation"] == "archive"
    assert page["items"][0]["reason"] == "Done."
    assert page["items"][0]["lifecycle_revision"] == 1
    assert set(page["items"][0]) == {
        "event_id",
        "lifecycle_revision",
        "operation",
        "prior_state",
        "resulting_state",
        "reason",
        "transitioned_at",
    }
    rest = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_HISTORY,
            {"report_id": rid, "entries": "lifecycle", "after": page["next_cursor"]},
        )
    )
    assert [(i["operation"], i["resulting_state"]) for i in rest["items"]] == [
        ("restore", "active")
    ]


def test_history_of_a_withdrawn_report_needs_include_withdrawn(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    rid = _published(service, scene)["report_id"]
    _ok(_invoke(service, scene, Capability.REPORTS_DELETE, _move(rid, "d", 0)))
    hidden = _invoke(service, scene, Capability.REPORTS_HISTORY, {"report_id": rid})
    assert _error(hidden) == (ErrorCode.NOT_FOUND.value, ["artifact_id"])
    shown = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_HISTORY,
            {"report_id": rid, "entries": "lifecycle", "include_withdrawn": True},
        )
    )
    assert shown["lifecycle_state"] == "trashed"
    assert [item["operation"] for item in shown["items"]] == ["delete"]


def test_a_cursor_from_another_report_is_invalid(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    one = _published(service, scene)
    two = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_PUBLISH,
            {**PUBLISH, "idempotency_key": "second", "client_intent_id": "b-1"},
        )
    )
    refused = _invoke(
        service,
        scene,
        Capability.REPORTS_HISTORY,
        {"report_id": one["report_id"], "after": two["version_id"]},
    )
    assert _error(refused) == (ErrorCode.INVALID_REQUEST.value, ["cursor"])


@pytest.mark.parametrize("entries", ["versions", "lifecycle"])
def test_root_visibility_outranks_a_bad_cursor(scene: Scene, entries: str) -> None:
    """WP04 C11(1): a bad cursor never says a hidden, missing or foreign report is there."""
    service = build_service(scene.world, scene.providers)
    one = _published(service, scene)
    two = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_PUBLISH,
            {**PUBLISH, "idempotency_key": "second", "client_intent_id": "b-1"},
        )
    )
    # A well-formed cursor that is not an item of report one.
    if entries == "versions":
        alien = two["version_id"]
    else:
        archived = _invoke(
            service, scene, Capability.REPORTS_ARCHIVE, _move(two["report_id"], "a2", 0)
        )
        alien = _ok(archived)["event_id"]
    rid = one["report_id"]

    def history(report_id: str, **extra: Any) -> dict[str, Any]:  # noqa: ANN401
        return _invoke(
            service,
            scene,
            Capability.REPORTS_HISTORY,
            {"report_id": report_id, "entries": entries, "after": alien, **extra},
        )

    not_found = (ErrorCode.NOT_FOUND.value, ["artifact_id"])
    bad_cursor = (ErrorCode.INVALID_REQUEST.value, ["cursor"])
    # Visible (active): the cursor is what is wrong.
    assert _error(history(rid)) == bad_cursor
    # Missing: not found, whatever the cursor.
    assert _error(history("grpt_00000000missing0")) == not_found
    # Foreign: not found, exactly as missing.
    stranger = operator()
    foreign = _invoke(
        service,
        scene,
        Capability.REPORTS_HISTORY,
        {"report_id": rid, "entries": entries, "after": alien},
        principal=stranger,
    )
    assert _error(foreign) == not_found
    # Withdrawn without include_withdrawn: not found; with it, the cursor again.
    _ok(_invoke(service, scene, Capability.REPORTS_ARCHIVE, _move(rid, "a1", 0)))
    assert _error(history(rid)) == not_found
    assert _error(history(rid, include_withdrawn=True)) == bad_cursor


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        ({"page_size": 0}, SafeDetail.PAGE_SIZE),
        ({"page_size": 51}, SafeDetail.PAGE_SIZE),
        ({"page_size": 11, "include_manifests": True}, SafeDetail.PAGE_SIZE),
        ({"entries": "events"}, SafeDetail.ENTRIES),
        ({"entries": "lifecycle", "include_manifests": True}, SafeDetail.INCLUDE_MANIFESTS),
        ({"include_manifests": "yes"}, SafeDetail.INCLUDE_MANIFESTS),
        ({"include_withdrawn": 1}, SafeDetail.INCLUDE_WITHDRAWN),
        ({"after": "grlev_00000000abcdefgh"}, SafeDetail.CURSOR),
        ({"entries": "lifecycle", "after": "grver_00000000abcdefgh"}, SafeDetail.CURSOR),
        ({"report_id": "rpt_00000000abcdefgh"}, SafeDetail.ARTIFACT_ID),
    ],
)
def test_bad_history_selectors_name_themselves(payload: dict[str, Any], detail: SafeDetail) -> None:
    refusal = _refusal(
        Capability.REPORTS_HISTORY, {"report_id": "grpt_00000000abcdefgh", **payload}
    )
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details[0] is detail


def test_the_history_page_size_defaults() -> None:
    assert GetGeneralReportHistory(report_id="grpt_00000000abcdefgh").resolved_page_size == 20
    with_manifests = GetGeneralReportHistory(
        report_id="grpt_00000000abcdefgh", include_manifests=True
    )
    assert with_manifests.resolved_page_size == 10


def test_a_history_integrity_failure_is_internal_error(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tests import conftest

    service = build_service(scene.world, scene.providers)
    rid = _published(service, scene)["report_id"]

    def tampered(*_args: object, **_kwargs: object) -> None:
        raise ReportIntegrityError()

    monkeypatch.setattr(conftest._GeneralReports, "version_history", tampered)
    answer = _invoke(service, scene, Capability.REPORTS_HISTORY, {"report_id": rid})
    assert _error(answer)[0] == ErrorCode.INTERNAL_ERROR.value


def test_commands_hide_the_patch_and_reason_from_repr() -> None:
    update = UpdateGeneralReport(
        report_id="grpt_00000000abcdefgh",
        expected_version=1,
        patch={"title": "Secret title"},
        change_reason="Secret reason",
        idempotency_key="k",
    )
    archive = ArchiveGeneralReport(
        report_id="grpt_00000000abcdefgh",
        expected_lifecycle_revision=0,
        idempotency_key="k",
        reason="Secret reason",
    )
    assert "Secret" not in repr(update)
    assert "Secret" not in repr(archive)
