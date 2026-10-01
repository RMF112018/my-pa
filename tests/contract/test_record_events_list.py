"""WP-RE-06 Phase 6B: `record_events.list` through the real handler (RE-AC-072, 067-069).

FAST: `ApplicationService.invoke` over the conftest fake unit of work, whose
reader serves `World.record_events` (test infrastructure; the SQL reader's
evidence is `tests/database/test_record_events_list.py`). Remote callers are
simulated with synthetic in-memory grant sets passed to `invoke`, the
`test_context_prepare.py` precedent; no live grant or profile is touched.

* **RE-AC-072** -- the result is exactly `{events, next_cursor,
  high_watermark_cursor, visible_families}` and every item carries exactly its
  public fields (thirteen until RECR-1 added the two routing fields): no
  Principal, classification, correlation or sequence.
* the handler clamps the page size, discloses truncation with the page's own
  `next_cursor`, and resumes from it;
* **G1-RD-008 / RE-AC-067** -- a remote caller without the `record_events.list`
  grant is `unsupported` even through `invoke`; with only that grant it sees no
  family, no event and a null watermark;
* **RE-AC-068 / 069** -- a family grant admits only its mapped families, and a
  changed grant set makes a prior cursor a conflict.
* **RECR-AC-007** -- the item contract for the routing reference: both fields
  or neither, only on a routed family, the kind `RECORD_EVENT_ROUTING` names,
  and that kind's opaque-id shape.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Final

from tests.conftest import Scene, build_service, metadata_for

from my_pa.application.commands import ListRecordEvents
from my_pa.application.record_events import read_cursor
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.contracts.v1.record_events import RecordEventItemView
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.record_events import (
    RECORD_EVENT_ROUTING,
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.source.registry import issue_identifier

WHEN: Final = datetime(2026, 9, 30, 12, tzinfo=UTC)
LIST_GRANT: Final = (Capability.RECORD_EVENTS_LIST, Purpose.RECORD_EVENT_READ)
ITEM_FIELDS: Final = {
    "event_id",
    "record_family",
    "record_id",
    "event_kind",
    "record_version",
    "changed_fields",
    "source_capability",
    "source_receipt_id",
    "actor_class",
    "authority",
    "occurred_at",
    "recorded_at",
    "causation_event_id",
    # RECR-1 (MR-R08): the routing reference, both null on a direct family.
    "routing_family",
    "routing_record_id",
}

type Grants = frozenset[tuple[Capability, Purpose | None]]


def grants(*capabilities: Capability) -> Grants:
    return frozenset(
        (capability, next(iter(permitted_purposes(capability)))) for capability in capabilities
    )


def commit(scene: Scene, family: RecordEventFamily, principal_id: str | None = None) -> str:
    draft = RecordEventDraft.issue(
        principal_id=principal_id or scene.principal.principal_id,
        record_family=family,
        record_id=issue_identifier(IdKind.TASK),
        event_kind=RecordEventKind.CREATED,
        record_version=1,
        changed_fields=("title",),
        source_capability="tasks.create",
        actor_class=RecordEventActorClass.PRINCIPAL,
        classification=Classification.PRIVATE_LOCAL,
        occurred_at=WHEN,
    )
    scene.world.record_events.append(draft)
    return draft.event_id


def invoke(
    scene: Scene, command: ListRecordEvents, capability_grants: Grants | None = None
) -> ResponseEnvelope:
    return build_service(scene.world, scene.providers).invoke(
        metadata_for(Capability.RECORD_EVENTS_LIST, Purpose.RECORD_EVENT_READ, scene.principal),
        command,
        principal=scene.principal,
        capability_grants=capability_grants,
    )


def ok(
    scene: Scene, command: ListRecordEvents, capability_grants: Grants | None = None
) -> dict[str, Any]:
    response = invoke(scene, command, capability_grants)
    assert response.error is None, response.error
    assert response.result is not None
    return response.result


def watermark(result: dict[str, Any]) -> str | None:
    read = read_cursor(result["high_watermark_cursor"])
    assert read is not None
    return read[1]


# ---- RE-AC-072 --------------------------------------------------------------------


def test_the_result_and_every_item_carry_exactly_their_public_fields(scene: Scene) -> None:
    mine = [commit(scene, RecordEventFamily.TASK), commit(scene, RecordEventFamily.MEETING)]
    commit(scene, RecordEventFamily.TASK, principal_id=issue_identifier(IdKind.PRINCIPAL))
    result = ok(scene, ListRecordEvents())
    assert set(result) == {"events", "next_cursor", "high_watermark_cursor", "visible_families"}
    assert [item["event_id"] for item in result["events"]] == mine
    for item in result["events"]:
        assert set(item) == ITEM_FIELDS
    assert result["next_cursor"] is None
    assert watermark(result) == mine[-1]
    assert result["visible_families"] == sorted(family.value for family in RecordEventFamily)


def test_a_full_page_discloses_truncation_and_resumes(scene: Scene) -> None:
    staged = [commit(scene, RecordEventFamily.TASK) for _ in range(3)]
    response = invoke(scene, ListRecordEvents(page_size=2))
    assert response.result is not None and response.disclosure is not None
    first = response.result
    assert [item["event_id"] for item in first["events"]] == staged[:2]
    truncation = response.disclosure.truncation
    assert truncation is not None and truncation.is_truncated
    assert truncation.next_cursor == first["next_cursor"]
    second = ok(scene, ListRecordEvents(page_size=2, cursor=first["next_cursor"]))
    assert [item["event_id"] for item in second["events"]] == staged[2:]
    assert second["next_cursor"] is None


def test_the_handler_clamps_the_page_size_to_one_hundred(scene: Scene) -> None:
    staged = [commit(scene, RecordEventFamily.TASK) for _ in range(101)]
    result = ok(scene, ListRecordEvents(page_size=500))
    assert len(result["events"]) == 100
    assert result["next_cursor"] is not None
    assert watermark(result) == staged[-1]


# ---- G1-RD-008 / RE-AC-067 ------------------------------------------------------------


def test_a_remote_caller_without_the_list_grant_is_unsupported(scene: Scene) -> None:
    commit(scene, RecordEventFamily.TASK)
    response = invoke(scene, ListRecordEvents(), grants(Capability.TASKS_READ))
    assert response.error is not None
    assert response.error.code is ErrorCode.UNSUPPORTED
    assert response.result is None
    wrong_purpose = frozenset({(Capability.RECORD_EVENTS_LIST, Purpose.TASK_READ)})
    refused = invoke(scene, ListRecordEvents(), wrong_purpose | grants(Capability.TASKS_READ))
    assert refused.error is not None and refused.error.code is ErrorCode.UNSUPPORTED


def test_the_list_grant_alone_exposes_no_family(scene: Scene) -> None:
    commit(scene, RecordEventFamily.TASK)
    result = ok(scene, ListRecordEvents(), frozenset({LIST_GRANT}))
    assert result["visible_families"] == []
    assert result["events"] == []
    assert watermark(result) is None


# ---- RE-AC-068 / 069 ----------------------------------------------------------------


def test_a_family_grant_admits_only_its_mapped_families(scene: Scene) -> None:
    task = commit(scene, RecordEventFamily.TASK)
    commit(scene, RecordEventFamily.MEETING)
    result = ok(scene, ListRecordEvents(), frozenset({LIST_GRANT}) | grants(Capability.TASKS_READ))
    assert result["visible_families"] == ["task"]
    assert [item["event_id"] for item in result["events"]] == [task]
    assert watermark(result) == task


def test_a_changed_grant_set_makes_a_prior_cursor_a_conflict(scene: Scene) -> None:
    for _ in range(2):
        commit(scene, RecordEventFamily.TASK)
    before = frozenset({LIST_GRANT}) | grants(Capability.TASKS_READ)
    first = ok(scene, ListRecordEvents(page_size=1), before)
    assert first["next_cursor"] is not None
    widened = before | grants(Capability.TASKS_LIST)
    response = invoke(scene, ListRecordEvents(page_size=1, cursor=first["next_cursor"]), widened)
    assert response.error is not None
    assert response.error.code is ErrorCode.CONFLICT
    resumed = ok(scene, ListRecordEvents(page_size=1, cursor=first["next_cursor"]), before)
    assert len(resumed["events"]) == 1


# ---- RECR-AC-007 ------------------------------------------------------------------

_ROUTING_KINDS: Final = {
    RecordEventFamily.TASK: IdKind.TASK,
    RecordEventFamily.PROJECT: IdKind.PROJECT,
    RecordEventFamily.ENTITY: IdKind.ENTITY,
}


def _view(family: RecordEventFamily, **routing: object) -> RecordEventItemView:
    return RecordEventItemView.model_validate(
        {
            "event_id": issue_identifier(IdKind.RECORD_EVENT),
            "record_family": family.value,
            "record_id": "rec_routing00000001",
            "event_kind": RecordEventKind.CREATED.value,
            "record_version": 1,
            "changed_fields": ["title"],
            "source_capability": "tasks.create",
            "actor_class": RecordEventActorClass.PRINCIPAL.value,
            "occurred_at": "2026-10-01T12:00:00Z",
            "recorded_at": "2026-10-01T12:00:00Z",
            **routing,
        }
    )


def _refused(family: RecordEventFamily, **routing: object) -> bool:
    try:
        _view(family, **routing)
    except ValueError:
        return True
    return False


def test_routing_fields_are_validated() -> None:
    """RECR-AC-007: both or neither; only on a routed family; the table's kind and shape."""
    for family in RecordEventFamily:
        # Neither field is always admitted: a direct family, or a routed one that
        # is not currently resolvable (MR-R05 (ii)).
        bare = _view(family)
        assert bare.routing_family is None and bare.routing_record_id is None
        routed = RECORD_EVENT_ROUTING.get(family)
        for kind, id_kind in _ROUTING_KINDS.items():
            good_id = issue_identifier(id_kind)
            pair = {"routing_family": kind.value, "routing_record_id": good_id}
            if routed is kind:
                view = _view(family, **pair)
                assert (view.routing_family, view.routing_record_id) == (kind, good_id)
            else:
                assert _refused(family, **pair), (family, kind)
        if routed is not None:
            right_kind = routed.value
            # One without the other.
            assert _refused(family, routing_family=right_kind)
            assert _refused(family, routing_record_id=issue_identifier(_ROUTING_KINDS[routed]))
            # The wrong identifier kind, and a value that is not an identifier.
            other = next(kind for kind in _ROUTING_KINDS if kind is not routed)
            wrong_id = issue_identifier(_ROUTING_KINDS[other])
            assert _refused(family, routing_family=right_kind, routing_record_id=wrong_id)
            assert _refused(family, routing_family=right_kind, routing_record_id="Dana Synthetic")
