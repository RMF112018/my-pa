"""WP-RE-08: Capture admissions stage exactly the Record Events they should (FAST half).

Driven through `ApplicationService.invoke` over the conftest fake unit of work,
whose `FakeRecordEventStager` publishes to `World.record_events` only when the
block ends normally. The fake capture store computes `changed_fields` with the
same domain helper the real store calls. The database half is
`tests/database/test_capture_record_events.py`.

* **RE-AC-086** -- a `capture.create` that admits a new capture stages one
  `capture` `created` event at version 1, named by the capture, with the
  capture receipt as `source_receipt_id`; a replay, an idempotency conflict and
  an unknown Project stage nothing.
* **RE-AC-087** -- a `capture.revise` that appends a version stages one
  `updated` event at the new version number; a replay, a conflict and an
  unknown or foreign capture stage nothing.
* **RE-AC-088 (MR-07/MR-11)** -- `changed_fields` are exact: a create names the
  static set plus each optional field it wrote non-null; a revise names the new
  head plus each version field that differs from the predecessor; a text-only
  revise names the new head and nothing else; no token names the text, a digest
  or a label value.
* **RE-AC-089** -- the committed version's classification, `principal` actor,
  no authority, the request's correlation id and no causation.

Every text, label and identity here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Final

import pytest

from my_pa.application.commands import Command, CreateCapture, CreateProject, ReviseCapture
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.record_events import (
    CAPTURE_CREATED_FIELDS,
    CAPTURE_HEAD_FIELDS,
    CaptureVersionFacts,
    InvalidRecordEventError,
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
    capture_changed_fields,
    capture_record_event,
)
from my_pa.domain.source.registry import issue_identifier
from tests.conftest import Scene, build_service, metadata_for

DEVICE: Final = datetime(2026, 9, 29, 8, tzinfo=UTC)
SUBJECT: Final = datetime(2026, 9, 28, 17, tzinfo=UTC)
TEXT: Final = "Synthetic capture text 0001"
LABEL: Final = "Synthetic label 0001"


def _invoke(
    service: ApplicationService, principal: Principal, purpose: Purpose, command: Command
) -> ResponseEnvelope:
    capability: Capability = type(command).capability  # type: ignore[attr-defined]
    return service.invoke(
        metadata_for(capability, purpose, principal), command, principal=principal
    )


def _create(
    service: ApplicationService, scene: Scene, key: str = "cap-create-0001", **extra: object
) -> ResponseEnvelope:
    response = _invoke(
        service,
        scene.principal,
        Purpose.CAPTURE_AUTHORING,
        CreateCapture(text=TEXT, idempotency_key=key, **extra),  # type: ignore[arg-type]
    )
    return response


def _revise(
    service: ApplicationService,
    scene: Scene,
    capture_id: str,
    key: str = "cap-revise-0001",
    text: str = "Synthetic capture text 0002",
    **extra: object,
) -> ResponseEnvelope:
    return _invoke(
        service,
        scene.principal,
        Purpose.CAPTURE_AUTHORING,
        ReviseCapture(capture_id=capture_id, text=text, idempotency_key=key, **extra),  # type: ignore[arg-type]
    )


def _result(response: ResponseEnvelope) -> dict[str, object]:
    assert response.error is None, response.error
    assert response.result is not None
    return response.result


def _captures(scene: Scene) -> list[RecordEventDraft]:
    return [e for e in scene.world.record_events if e.record_family is RecordEventFamily.CAPTURE]


def _only(scene: Scene) -> RecordEventDraft:
    events = _captures(scene)
    assert len(events) == 1, events
    return events[0]


def _seeded(service: ApplicationService, scene: Scene, **extra: object) -> str:
    capture_id = str(_result(_create(service, scene, key="cap-seed-0001", **extra))["capture_id"])
    scene.world.record_events.clear()
    return capture_id


# ---- RE-AC-086 --------------------------------------------------------------


def test_create_stages_one_created_event(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    receipt = _result(_create(service, scene))
    event = _only(scene)
    assert event.record_family is RecordEventFamily.CAPTURE
    assert event.record_id == receipt["capture_id"]
    assert event.event_kind is RecordEventKind.CREATED
    assert event.record_version == 1
    assert event.source_receipt_id == receipt["receipt_id"]
    assert event.source_capability == "capture.create"
    assert event.principal_id == scene.principal.principal_id


def test_a_replay_stages_nothing(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    first = _result(_create(service, scene))
    scene.world.record_events.clear()
    again = _result(_create(service, scene))
    assert again["receipt_id"] == first["receipt_id"]
    assert again["created"] is False
    assert _captures(scene) == []


def test_a_conflict_and_an_unknown_project_stage_nothing(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    _seeded(service, scene)
    conflict = _invoke(
        service,
        scene.principal,
        Purpose.CAPTURE_AUTHORING,
        CreateCapture(text="Different synthetic text", idempotency_key="cap-seed-0001"),
    )
    assert conflict.error is not None and conflict.error.code is ErrorCode.CONFLICT
    unknown = _create(
        service, scene, key="cap-unknown-project-0001", project_id=issue_identifier(IdKind.PROJECT)
    )
    assert unknown.error is not None and unknown.error.code is ErrorCode.NOT_FOUND
    assert _captures(scene) == []


# ---- RE-AC-087 --------------------------------------------------------------


def test_revise_stages_updated_at_the_new_version(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    capture_id = _seeded(service, scene)
    receipt = _result(_revise(service, scene, capture_id))
    event = _only(scene)
    assert event.event_kind is RecordEventKind.UPDATED
    assert event.record_id == capture_id
    assert event.record_version == 2 == receipt["version_number"]
    assert event.source_receipt_id == receipt["receipt_id"]
    assert event.source_capability == "capture.revise"

    scene.world.record_events.clear()
    third = _result(_revise(service, scene, capture_id, key="cap-revise-0002", text="Third text"))
    assert _only(scene).record_version == 3 == third["version_number"]


def test_a_revise_replay_conflict_and_unknown_capture_stage_nothing(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    capture_id = _seeded(service, scene)
    _result(_revise(service, scene, capture_id))
    scene.world.record_events.clear()
    replay = _result(_revise(service, scene, capture_id))
    assert replay["created"] is False
    conflict = _revise(service, scene, capture_id, text="Other synthetic text")
    assert conflict.error is not None and conflict.error.code is ErrorCode.CONFLICT
    unknown = _revise(service, scene, issue_identifier(IdKind.CAPTURE), key="cap-revise-unknown")
    assert unknown.error is not None and unknown.error.code is ErrorCode.NOT_FOUND
    assert _captures(scene) == []


# ---- RE-AC-088 (MR-07 / MR-11) ----------------------------------------------


def test_created_fields_follow_what_was_written(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    _result(_create(service, scene))
    assert (
        _only(scene).changed_fields
        == CAPTURE_CREATED_FIELDS
        == (
            "character_count",
            "classification",
            "latest_version_id",
            "latest_version_number",
            "owner_principal_id",
            "processing_policy",
            "version_count",
        )
    )

    scene.world.record_events.clear()
    project = _result(
        _invoke(
            service,
            scene.principal,
            Purpose.CONTINUITY_AUTHORING,
            CreateProject(name="Synthetic capture project", idempotency_key="cap-project-0001"),
        )
    )
    scene.world.record_events.clear()
    _result(
        _create(
            service,
            scene,
            key="cap-create-full-0001",
            project_id=project["project_id"],
            display_label=LABEL,
            client_created_at=DEVICE,
            occurred_at=SUBJECT,
        )
    )
    assert _only(scene).changed_fields == (
        "character_count",
        "classification",
        "client_created_at",
        "display_label",
        "latest_version_id",
        "latest_version_number",
        "occurred_at",
        "owner_principal_id",
        "processing_policy",
        "project_id",
        "version_count",
    )


def test_a_text_only_revise_names_exactly_the_new_head(scene: Scene) -> None:
    """MR-11: the text changed (same length), and the text is never named; the head is."""
    service = build_service(scene.world, scene.providers)
    capture_id = _seeded(service, scene, client_created_at=DEVICE, occurred_at=SUBJECT)
    same_length = "Other synthetic captured 01"
    assert len(same_length) == len(TEXT)
    _result(
        _revise(
            service,
            scene,
            capture_id,
            text=same_length,
            client_created_at=DEVICE,
            occurred_at=SUBJECT,
        )
    )
    assert _only(scene).changed_fields == (
        "latest_version_id",
        "latest_version_number",
        "supersedes_version_id",
        "version_count",
    )
    assert _only(scene).changed_fields == CAPTURE_HEAD_FIELDS


def test_a_revise_whose_text_changes_length_names_the_character_count(scene: Scene) -> None:
    """MR-11: `character_count` is a count `capture.read` exposes -- named when it moves."""
    service = build_service(scene.world, scene.providers)
    capture_id = _seeded(service, scene, client_created_at=DEVICE, occurred_at=SUBJECT)
    _result(
        _revise(
            service,
            scene,
            capture_id,
            text="A wholly different and longer synthetic text",
            client_created_at=DEVICE,
            occurred_at=SUBJECT,
        )
    )
    assert _only(scene).changed_fields == (
        "character_count",
        "latest_version_id",
        "latest_version_number",
        "supersedes_version_id",
        "version_count",
    )


def test_updated_fields_name_exactly_the_differing_version_fields(scene: Scene) -> None:
    """MR-07: several candidate fields held, exactly one differs, exactly one named."""
    service = build_service(scene.world, scene.providers)
    capture_id = _seeded(service, scene, client_created_at=DEVICE, occurred_at=SUBJECT)
    _result(
        _revise(
            service,
            scene,
            capture_id,
            client_created_at=DEVICE,
            occurred_at=SUBJECT + timedelta(hours=1),
        )
    )
    assert _only(scene).changed_fields == (
        "latest_version_id",
        "latest_version_number",
        "occurred_at",
        "supersedes_version_id",
        "version_count",
    )


def test_a_revise_that_clears_a_time_names_it(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    capture_id = _seeded(service, scene, client_created_at=DEVICE, occurred_at=SUBJECT)
    _result(_revise(service, scene, capture_id, occurred_at=SUBJECT))
    assert _only(scene).changed_fields == (
        "client_created_at",
        "latest_version_id",
        "latest_version_number",
        "supersedes_version_id",
        "version_count",
    )


_FACTS: Final = CaptureVersionFacts(
    classification=Classification.PRIVATE_LOCAL,
    processing_policy="local_only",
    client_created_at=DEVICE,
    occurred_at=SUBJECT,
    character_count=27,
)


@pytest.mark.parametrize(
    ("written", "named"),
    [
        (
            CaptureVersionFacts(
                classification=Classification.RESTRICTED_LOCAL,
                processing_policy="local_only",
                client_created_at=DEVICE,
                occurred_at=SUBJECT,
                character_count=27,
            ),
            "classification",
        ),
        (
            CaptureVersionFacts(
                classification=Classification.PRIVATE_LOCAL,
                processing_policy="some_other_policy",
                client_created_at=DEVICE,
                occurred_at=SUBJECT,
                character_count=27,
            ),
            "processing_policy",
        ),
        (
            CaptureVersionFacts(
                classification=Classification.PRIVATE_LOCAL,
                processing_policy="local_only",
                client_created_at=DEVICE,
                occurred_at=SUBJECT,
                character_count=28,
            ),
            "character_count",
        ),
    ],
    ids=["classification", "processing_policy", "character_count"],
)
def test_the_helper_names_each_differing_version_field_alone(
    written: CaptureVersionFacts, named: str
) -> None:
    assert capture_changed_fields(
        prior=_FACTS, written=written, label_recorded=False, project_bound=False
    ) == tuple(sorted((*CAPTURE_HEAD_FIELDS, named)))
    assert (
        capture_changed_fields(
            prior=_FACTS, written=_FACTS, label_recorded=False, project_bound=False
        )
        == CAPTURE_HEAD_FIELDS
    )


def test_a_revise_can_never_claim_a_label_or_a_project() -> None:
    with pytest.raises(InvalidRecordEventError):
        capture_changed_fields(
            prior=_FACTS, written=_FACTS, label_recorded=True, project_bound=False
        )
    with pytest.raises(InvalidRecordEventError):
        capture_changed_fields(
            prior=_FACTS, written=_FACTS, label_recorded=False, project_bound=True
        )


# ---- RE-AC-089 --------------------------------------------------------------


def test_a_capture_event_carries_the_version_classification_and_the_request_origin(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    capture_id = _seeded(service, scene)
    _result(_revise(service, scene, capture_id))
    event = _only(scene)
    admitted = scene.world.capture_admissions[-1]
    assert event.classification is admitted.classification is Classification.PRIVATE_LOCAL
    assert event.actor_class is RecordEventActorClass.PRINCIPAL
    assert event.authority is None
    assert event.correlation_id == admitted.correlation_id
    assert event.causation_event_id is None
    assert event.occurred_at == admitted.accepted_at


def test_the_builder_carries_the_committed_version_classification() -> None:
    """OD-W8-5: not `NON_MEMORY_CLASSIFICATION` -- the version's own, even restricted."""
    draft = capture_record_event(
        principal_id=issue_identifier(IdKind.PRINCIPAL),
        capture_id=issue_identifier(IdKind.CAPTURE),
        event_kind=RecordEventKind.UPDATED,
        version_number=4,
        changed_fields=CAPTURE_HEAD_FIELDS,
        capability="capture.revise",
        classification=Classification.RESTRICTED_LOCAL,
        occurred_at=DEVICE,
        receipt_id=issue_identifier(IdKind.RECEIPT),
        correlation_id=issue_identifier(IdKind.CORRELATION),
    )
    assert draft.classification is Classification.RESTRICTED_LOCAL
    assert draft.record_family is RecordEventFamily.CAPTURE
    assert draft.record_version == 4
    assert draft.actor_class is RecordEventActorClass.PRINCIPAL
    assert draft.authority is None
    assert draft.causation_event_id is None
