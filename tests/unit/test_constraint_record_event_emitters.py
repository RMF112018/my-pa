"""WP-RE-03: Constraint-plane writes stage exactly the Record Events they should (FAST half).

Driven through `ConstraintManagementService` and
`ProjectControlsConfigurationService` over the in-memory Constraint unit of work
of `tests/unit/test_constraint_management_service.py` (and its settings
sibling), whose stager publishes to `_State.record_events` only when the block
ends normally. Everything here is staged on the Constraint unit of work.

* **RE-AC-031** -- a direct create is one `created` event;
* **RE-AC-032** -- `create_published` is one `created` event for the published
  record, and no intermediate Draft or Publish event;
* **RE-AC-033** -- publish is `state_changed`;
* **RE-AC-034** -- an APPLIED update is `updated` over exactly the fields it
  changed; an empty patch (NO_OP) stages nothing;
* **RE-AC-035** -- transition, close, void and reopen are `state_changed`;
* **RE-AC-036** -- `close_with_follow_up` stages the predecessor's
  `state_changed`, then the successor's `created`, caused by it;
* **RE-AC-037** -- Category create / update / deactivate are
  `created` / `updated` / `state_changed`;
* **RE-AC-038** -- a reorder stages one `updated` per Category, in request order;
* **RE-AC-039** -- configure stages a settings event named by its Project;
* **T-16** -- replays, NO_OPs and stale rejections stage nothing.
"""

from __future__ import annotations

from datetime import date
from typing import Final

import pytest

from my_pa.application.constraint_management import (
    ConstraintMutationDisposition,
    ConstraintVersionConflictError,
    RecordEventOrigin,
)
from my_pa.domain.project_controls.constraint import ConstraintLifecycleState
from my_pa.domain.project_controls.history import ConstraintMutationActor
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from tests.unit.test_constraint_management_service import (
    PRINCIPAL_A,
    PROJECT_A,
    _create_published,
    _draft,
    _follow_up,
    _published,
    _World,
    _world,
)

ORIGIN: Final = RecordEventOrigin("constraints.update", "corr_cstemit0000001")


@pytest.fixture
def world() -> _World:
    built = _world()
    built.state.record_events.clear()  # the seeded Category's own event
    return built


def _events(world: _World) -> list[RecordEventDraft]:
    return list(world.state.record_events)


def _new(world: _World, before: int) -> list[RecordEventDraft]:
    return _events(world)[before:]


# ---- RE-AC-031 / 033 --------------------------------------------------------


def test_a_direct_create_stages_one_created_event(world: _World) -> None:
    draft = _draft(world)
    (event,) = _events(world)
    assert event.record_family is RecordEventFamily.CONSTRAINT
    assert event.record_id == draft.constraint_id
    assert event.event_kind is RecordEventKind.CREATED
    assert event.record_version == 1
    assert event.source_capability == "constraints.create"
    assert event.actor_class is RecordEventActorClass.PRINCIPAL
    assert "description" in event.changed_fields
    assert "lifecycle_state" in event.changed_fields


def test_publish_is_state_changed(world: _World) -> None:
    published = _published(world)
    create, publish = _events(world)
    assert create.event_kind is RecordEventKind.CREATED
    assert publish.event_kind is RecordEventKind.STATE_CHANGED
    assert publish.record_version == published.version == 2
    assert {"constraint_code", "lifecycle_state", "published_at"} <= set(publish.changed_fields)
    assert publish.source_capability == "constraints.publish"


# ---- RE-AC-032 --------------------------------------------------------------


def test_create_published_stages_one_created_event_and_no_intermediate(world: _World) -> None:
    created = _create_published(world)
    (event,) = _events(world)
    assert event.event_kind is RecordEventKind.CREATED
    assert event.record_id == created.record.constraint_id
    assert event.record_version == created.record.version == 2
    assert event.source_capability == "constraints.create_published"
    assert event.source_receipt_id == created.receipt.history_id
    assert created.record_event_id == event.event_id
    assert "constraint_code" in event.changed_fields


# ---- RE-AC-034 --------------------------------------------------------------


def test_an_applied_update_names_exactly_the_fields_it_changed(world: _World) -> None:
    draft = _draft(world)
    before = len(_events(world))
    world.service.update(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"reference": "RFI-12", "description": draft.description},
        event_origin=ORIGIN,
    )
    (event,) = _new(world, before)
    assert event.event_kind is RecordEventKind.UPDATED
    assert event.changed_fields == ("reference",)
    assert event.source_capability == "constraints.update"
    assert event.correlation_id == "corr_cstemit0000001"


def test_an_empty_patch_is_a_no_op_and_stages_nothing(world: _World) -> None:
    draft = _draft(world)
    before = len(_events(world))
    result = world.service.update(
        principal_id=PRINCIPAL_A,
        constraint_id=draft.constraint_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={},
    )
    assert result.disposition is ConstraintMutationDisposition.NO_OP
    assert _new(world, before) == []


def test_a_stale_update_stages_nothing(world: _World) -> None:
    draft = _draft(world)
    before = len(_events(world))
    with pytest.raises(ConstraintVersionConflictError):
        world.service.update(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=9,
            actor=ConstraintMutationActor.PRINCIPAL,
            values={"reference": "late"},
        )
    assert _new(world, before) == []


def test_a_replayed_update_stages_nothing(world: _World) -> None:
    draft = _draft(world)
    kwargs = {
        "principal_id": PRINCIPAL_A,
        "constraint_id": draft.constraint_id,
        "expected_version": 1,
        "actor": ConstraintMutationActor.PRINCIPAL,
        "values": {"reference": "RFI-9"},
        "idempotency_key": "cst-emit-replay-0001",
    }
    world.service.update(**kwargs)  # type: ignore[arg-type]
    before = len(_events(world))
    replay = world.service.update(**kwargs)  # type: ignore[arg-type]
    assert replay.disposition is ConstraintMutationDisposition.REPLAYED
    assert _new(world, before) == []


# ---- RE-AC-035 --------------------------------------------------------------


def test_transition_close_void_and_reopen_are_state_changed(world: _World) -> None:
    record = _published(world)
    before = len(_events(world))
    moved = world.service.transition_active(
        principal_id=PRINCIPAL_A,
        constraint_id=record.constraint_id,
        target_state=ConstraintLifecycleState.IN_PROGRESS,
        expected_version=record.version,
        actor=ConstraintMutationActor.PRINCIPAL,
    ).record
    closed = world.service.close(
        principal_id=PRINCIPAL_A,
        constraint_id=record.constraint_id,
        expected_version=moved.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        completion_date=date(2026, 9, 3),
    ).record
    reopened = world.service.reopen(
        principal_id=PRINCIPAL_A,
        constraint_id=record.constraint_id,
        target_state=ConstraintLifecycleState.IDENTIFIED,
        expected_version=closed.version,
        actor=ConstraintMutationActor.PRINCIPAL,
    ).record
    world.service.void(
        principal_id=PRINCIPAL_A,
        constraint_id=record.constraint_id,
        expected_version=reopened.version,
        actor=ConstraintMutationActor.PRINCIPAL,
        void_reason="Superseded.",
        voided_date=date(2026, 9, 4),
    )
    events = _new(world, before)
    assert [event.event_kind for event in events] == [RecordEventKind.STATE_CHANGED] * 4
    assert [event.source_capability for event in events] == [
        "constraints.transition",
        "constraints.close",
        "constraints.reopen",
        "constraints.void",
    ]
    assert [event.record_version for event in events] == [3, 4, 5, 6]
    assert "completion_date" in events[1].changed_fields
    assert "void_reason" in events[3].changed_fields


# ---- RE-AC-036 --------------------------------------------------------------


def test_close_with_follow_up_stages_predecessor_then_caused_successor(world: _World) -> None:
    world.state.record_events.clear()
    _published_record, result = _follow_up(world)
    before = 2  # the predecessor's own create and publish
    predecessor, successor = _new(world, before)
    assert predecessor.record_id == result.predecessor.constraint_id
    assert predecessor.event_kind is RecordEventKind.STATE_CHANGED
    assert successor.record_id == result.successor.constraint_id
    assert successor.event_kind is RecordEventKind.CREATED
    assert successor.record_version == result.successor.version
    assert successor.causation_event_id == predecessor.event_id
    assert {predecessor.source_capability, successor.source_capability} == {
        "constraints.close_follow_up"
    }


# ---- RE-AC-037 / 038 --------------------------------------------------------


def test_category_create_update_and_deactivate(world: _World) -> None:
    created = world.service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="STR",
        title="Structure",
        actor=ConstraintMutationActor.PRINCIPAL,
    ).record
    updated = world.service.update_category(
        principal_id=PRINCIPAL_A,
        category_id=created.category_id,
        expected_version=1,
        actor=ConstraintMutationActor.PRINCIPAL,
        values={"title": "Structures"},
    )
    world.service.deactivate_category(
        principal_id=PRINCIPAL_A,
        category_id=created.category_id,
        expected_version=updated.receipt.after_version,
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    events = _events(world)
    assert [event.record_family for event in events] == [RecordEventFamily.CONSTRAINT_CATEGORY] * 3
    assert [event.event_kind for event in events] == [
        RecordEventKind.CREATED,
        RecordEventKind.UPDATED,
        RecordEventKind.STATE_CHANGED,
    ]
    assert events[1].changed_fields == ("title",)
    assert events[2].changed_fields == ("state",)
    assert [event.record_version for event in events] == [1, 2, 3]
    assert [event.source_capability for event in events] == [
        "constraint_categories.create",
        "constraint_categories.update",
        "constraint_categories.deactivate",
    ]


def test_a_reorder_stages_one_updated_per_category_in_request_order(world: _World) -> None:
    second = world.service.create_category(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        prefix="MEP",
        title="Services",
        actor=ConstraintMutationActor.PRINCIPAL,
        display_order=1,
    ).record
    first = world.category()
    before = len(_events(world))
    world.service.reorder_categories(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        ordered_category_ids=(second.category_id, first),
        expected_versions={second.category_id: 1, first: 1},
        actor=ConstraintMutationActor.PRINCIPAL,
    )
    events = _new(world, before)
    assert [event.record_id for event in events] == [second.category_id, first]
    assert [event.event_kind for event in events] == [RecordEventKind.UPDATED] * 2
    assert all("version" in event.changed_fields for event in events)
    assert all(event.record_version == 2 for event in events)
    assert {event.source_capability for event in events} == {"constraint_categories.reorder"}


# ---- RE-AC-039 --------------------------------------------------------------


def test_configure_stages_a_settings_event_named_by_its_project() -> None:
    from tests.unit.test_project_controls_settings_service import (
        PRINCIPAL_A as SETTINGS_PRINCIPAL,
    )
    from tests.unit.test_project_controls_settings_service import (
        PROJECT_A as SETTINGS_PROJECT,
    )
    from tests.unit.test_project_controls_settings_service import _world as settings_world

    built = settings_world()
    built.service.configure(
        principal_id=SETTINGS_PRINCIPAL,
        actor=ConstraintMutationActor.PRINCIPAL,
        project_id=SETTINGS_PROJECT,
        timezone_name="America/Chicago",
        idempotency_key="settings-emit-0001",
    )
    (event,) = built.state.record_events
    assert event.record_family is RecordEventFamily.PROJECT_CONTROLS_SETTINGS
    assert event.record_id == SETTINGS_PROJECT
    assert event.event_kind is RecordEventKind.CREATED
    assert event.record_version == 1
    assert event.changed_fields == ("timezone_name",)
    assert event.source_capability == "project_controls.configure"
    assert event.source_receipt_id is not None
    assert event.source_receipt_id.startswith("cpsh_")
