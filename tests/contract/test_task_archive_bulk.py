"""Task archive preview/confirm contracts with synthetic storage and a moving clock.

No network or database: execute the same canonical normalization and application
handlers the HTTP adapter invokes. Real persistence atomicity has separate tests.
"""

from __future__ import annotations

from dataclasses import replace
from datetime import timedelta

import pytest
from tests.conftest import WHEN, Scene, build_service, staged_task
from tests.contract.test_transport_parity import document

from my_pa.adapters.normalization import normalize
from my_pa.application.service import ApplicationService, _normalise_bulk_mutations
from my_pa.domain.identity.operation import Capability


def _invoke(
    service: ApplicationService, scene: Scene, capability: Capability, payload: dict
) -> dict:
    metadata, command = normalize(
        capability.value, document(capability, scene.principal.principal_id, payload)
    )
    return service.invoke(metadata, command, principal=scene.principal).to_canonical_dict()


@pytest.mark.parametrize(
    ("initial_archived", "archived", "mixed", "affected"),
    [
        (False, True, False, 1),
        (True, True, False, 0),
        (True, False, False, 1),
        (False, False, False, 0),
        (True, True, True, 1),
        (False, False, True, 1),
    ],
)
def test_archive_bulk_preview_confirm_counts_stay_stable_with_clock_advance(
    scene: Scene,
    monkeypatch: pytest.MonkeyPatch,
    initial_archived: bool,
    archived: bool,
    mixed: bool,
    affected: int,
) -> None:
    task = staged_task(scene)
    timestamp = WHEN if initial_archived else None
    task = replace(task, archived_at=timestamp)
    scene.world.tasks_v2[:] = [task]
    now = [WHEN]
    service = build_service(scene.world, scene.providers)
    monkeypatch.setattr(service, "_clock", lambda: now[0])
    values = {"archived": archived}
    if mixed:
        values["title"] = "changed synthetic title"
    mutations = [
        {
            "kind": "update",
            "task_id": task.task_id,
            "expected_version": task.version,
            "values": values,
            "clear_fields": [],
        }
    ]
    preview_payload = {"mutations": mutations, "idempotency_key": "archive-bulk-preview"}
    initial_history_count = len(scene.world.task_history_v2)
    preview_envelope = _invoke(service, scene, Capability.TASKS_BULK_PREVIEW, preview_payload)
    assert preview_envelope["error"] is None
    preview = preview_envelope["result"]
    assert preview["affected"] == affected
    assert preview["no_op"] == 1 - affected
    assert scene.world.tasks_v2 == [task]
    assert len(scene.world.task_history_v2) == initial_history_count
    now[0] += timedelta(seconds=30)
    preview_replay = _invoke(service, scene, Capability.TASKS_BULK_PREVIEW, preview_payload)
    assert preview_replay["result"] == {**preview, "replayed": True}
    now[0] += timedelta(seconds=30)
    confirm_payload = {
        "mutations": mutations,
        "bulk_operation_id": preview["bulk_operation_id"],
        "idempotency_key": "archive-bulk-confirm",
    }
    confirmed_envelope = _invoke(service, scene, Capability.TASKS_BULK_CONFIRM, confirm_payload)
    assert confirmed_envelope["error"] is None
    confirmed = confirmed_envelope["result"]
    assert confirmed["affected"] == preview["affected"]
    assert confirmed["no_op"] == preview["no_op"]
    assert len(confirmed["history_ids"]) == 1
    assert len(scene.world.task_history_v2) == initial_history_count + 1
    row = scene.world.tasks_v2[0]
    assert row.version == task.version + affected
    expected_timestamp = timestamp if initial_archived else now[0]
    assert row.archived_at == (expected_timestamp if archived else None)
    assert row.title == ("changed synthetic title" if mixed else task.title)
    history = scene.world.task_history_v2[-1]
    assert history.outcome.value == ("applied" if affected else "no_op")
    assert history.action.value == "update"
    assert history.before_version == task.version
    assert history.after_version == row.version
    before = tuple(scene.world.task_history_v2)
    now[0] += timedelta(seconds=30)
    replay = _invoke(service, scene, Capability.TASKS_BULK_CONFIRM, confirm_payload)
    assert replay["result"] == {**confirmed, "replayed": True}
    assert scene.world.tasks_v2 == [row]
    assert tuple(scene.world.task_history_v2) == before
    changed = [{**mutations[0], "values": {**values, "title": "conflicting title"}}]
    conflicting = _invoke(
        service, scene, Capability.TASKS_BULK_CONFIRM, {**confirm_payload, "mutations": changed}
    )
    assert conflicting["error"]["code"] == "conflict"
    assert scene.world.tasks_v2 == [row]
    assert tuple(scene.world.task_history_v2) == before


@pytest.mark.parametrize("refusal", ["version_drift", "changed_payload", "expired"])
def test_archive_bulk_confirm_refusal_writes_no_rows_or_history(
    scene: Scene, monkeypatch: pytest.MonkeyPatch, refusal: str
) -> None:
    task = staged_task(scene)
    now = [WHEN]
    service = build_service(scene.world, scene.providers)
    monkeypatch.setattr(service, "_clock", lambda: now[0])
    mutations = [
        {
            "kind": "update",
            "task_id": task.task_id,
            "expected_version": task.version,
            "values": {"archived": True},
            "clear_fields": [],
        }
    ]
    preview = _invoke(
        service,
        scene,
        Capability.TASKS_BULK_PREVIEW,
        {"mutations": mutations, "idempotency_key": "archive-refusal-preview"},
    )["result"]
    now[0] += timedelta(seconds=30)
    if refusal == "version_drift":
        scene.world.tasks_v2[:] = [replace(task, version=task.version + 1)]
    elif refusal == "changed_payload":
        mutations = [{**mutations[0], "values": {"archived": False}}]
    else:
        now[0] += timedelta(minutes=15)
    before_rows = tuple(scene.world.tasks_v2)
    before_history = tuple(scene.world.task_history_v2)
    refused = _invoke(
        service,
        scene,
        Capability.TASKS_BULK_CONFIRM,
        {
            "mutations": mutations,
            "bulk_operation_id": preview["bulk_operation_id"],
            "idempotency_key": "archive-refusal-confirm",
        },
    )
    assert refused["error"]["code"] == "conflict"
    assert tuple(scene.world.tasks_v2) == before_rows
    assert tuple(scene.world.task_history_v2) == before_history


def test_archive_bulk_keys_bind_preview_payload_and_confirm_operation(
    scene: Scene, monkeypatch: pytest.MonkeyPatch
) -> None:
    task = replace(staged_task(scene), archived_at=WHEN)
    scene.world.tasks_v2[:] = [task]
    now = [WHEN]
    service = build_service(scene.world, scene.providers)
    monkeypatch.setattr(service, "_clock", lambda: now[0])
    mutations = [
        {
            "kind": "update",
            "task_id": task.task_id,
            "expected_version": task.version,
            "values": {"archived": True},
            "clear_fields": [],
        }
    ]
    previews = []
    before_history = tuple(scene.world.task_history_v2)
    for key in ("archive-preview-first", "archive-preview-second"):
        envelope = _invoke(
            service,
            scene,
            Capability.TASKS_BULK_PREVIEW,
            {"mutations": mutations, "idempotency_key": key},
        )
        assert envelope["error"] is None
        previews.append(envelope["result"])
    changed = [{**mutations[0], "values": {"archived": False}}]
    refused_preview = _invoke(
        service,
        scene,
        Capability.TASKS_BULK_PREVIEW,
        {"mutations": changed, "idempotency_key": "archive-preview-first"},
    )
    assert refused_preview["error"]["code"] == "conflict"
    assert scene.world.tasks_v2 == [task]
    assert tuple(scene.world.task_history_v2) == before_history
    now[0] += timedelta(seconds=30)
    confirm_payload = {"mutations": mutations, "idempotency_key": "archive-confirm-shared"}
    confirmed = _invoke(
        service,
        scene,
        Capability.TASKS_BULK_CONFIRM,
        {**confirm_payload, "bulk_operation_id": previews[0]["bulk_operation_id"]},
    )
    assert confirmed["error"] is None
    assert confirmed["result"]["no_op"] == 1
    assert scene.world.tasks_v2 == [task]
    after_first = tuple(scene.world.task_history_v2)
    assert len(after_first) == len(before_history) + 1
    refused_confirm = _invoke(
        service,
        scene,
        Capability.TASKS_BULK_CONFIRM,
        {**confirm_payload, "bulk_operation_id": previews[1]["bulk_operation_id"]},
    )
    assert refused_confirm["error"]["code"] == "conflict"
    assert scene.world.tasks_v2 == [task]
    assert tuple(scene.world.task_history_v2) == after_first


@pytest.mark.parametrize(
    ("values", "historical_digest"),
    [
        ({"archived": True}, "4e7df651807f3ac494dd127342c2dda4e75d2ce9806b2dc53c0544cf9872b150"),
        ({"archived": False}, "fd7f6f28fcf65275d624fb118f577208b5bd56b447d316c3720399a4aee8ce69"),
        (
            {"title": "historical title"},
            "d40e9dc0c4d305ef643c001d0afe67ff3b6f84dc5424de4d4858b3e11e085ce8",
        ),
    ],
)
def test_bulk_archive_digest_preserves_historical_normalized_bytes(
    values: dict, historical_digest: str
) -> None:
    """Pin existing d6c706bb receipt compatibility, including sorted clear fields."""
    mutation = {
        "kind": "update",
        "task_id": "tsk_0123456789abcdef0123456789abcdef",
        "expected_version": 3,
        "values": values,
        "clear_fields": ["scheduled_at", "due_at"],
    }
    normalized, digest = _normalise_bulk_mutations((mutation,))
    assert digest == historical_digest
    assert normalized[0]["clear_fields"] == ["due_at", "scheduled_at"]
