"""WP-RE-06 Phase 6A: grant narrowing, the entity floor and causation nulling (FAST half).

The application-level half of RE-AC-062, 067, 068, 069 and 072 (and the OD-12
part of 070). Phase 6B adds the end-to-end handler half (the capability, the
handler-level `record_events.list` grant check and the per-name payload
refusals of RE-AC-071). Every grant set here is synthetic and in memory; no live
grant, profile or OAuth row is read or written.

* **RE-AC-067** -- a remote caller whose grants name no family read sees no
  family, no event and no watermark, and the reader is never asked for a page.
* **RE-AC-068** -- each mapped read admits exactly the families mapped to it,
  purpose-aware; the Entity-plane sub-families additionally need `entities.get`
  (OD-10); a family whose reads are not composed is invisible to everyone.
* **RE-AC-069** -- any change to the visibility grants changes `grant_digest`,
  so a prior cursor is a conflict even when the visible set is unchanged.
* **OD-12** -- a remote item's `causation_event_id` survives only when the
  cause is visible to that caller.
* **RE-AC-072** -- the public item carries exactly its thirteen fields: no
  Principal, classification, correlation or sequence number.
* **RECR-AC-014** (RECR-3) -- a cursor anchor is checked for visibility under
  exactly the effective families and the request's disclosure flag before its
  position is resolved.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final

import pytest

from my_pa.application.errors import ConflictError
from my_pa.application.record_events import list_record_events, read_cursor, visible_families
from my_pa.contracts.ports import RecordEventFeedItem, RecordEventPage, RecordEventReader
from my_pa.contracts.v1.record_events import RecordEventItemView, RecordEventListView
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.record_events import (
    ENTITY_FLOOR_CAPABILITY,
    ENTITY_FLOOR_FAMILIES,
    RECORD_EVENT_FAMILY_READS,
    RecordEventActorClass,
    RecordEventFamily,
    RecordEventKind,
)

PRINCIPAL: Final = "prn_grantnarrow00001"
WHEN: Final = datetime(2026, 9, 30, 12, tzinfo=UTC)
ALL: Final = frozenset(Capability)
MAPPED: Final = sorted(
    {capability for reads in RECORD_EVENT_FAMILY_READS.values() for capability in reads},
    key=lambda capability: capability.value,
)

type Grants = frozenset[tuple[Capability, Purpose | None]]


def grants(*capabilities: Capability) -> Grants:
    return frozenset(
        (capability, next(iter(permitted_purposes(capability)))) for capability in capabilities
    )


def item(
    event_id: str, family: RecordEventFamily, causation_event_id: str | None = None
) -> RecordEventFeedItem:
    return RecordEventFeedItem(
        event_id=event_id,
        record_family=family,
        record_id="task_grantnarrow0001",
        event_kind=RecordEventKind.CREATED,
        record_version=1,
        changed_fields=("title",),
        source_capability="tasks.create",
        source_receipt_id=None,
        actor_class=RecordEventActorClass.PRINCIPAL,
        authority=None,
        occurred_at=WHEN,
        recorded_at=WHEN,
        causation_event_id=causation_event_id,
    )


@dataclass
class FakeReader(RecordEventReader):
    """An in-memory reader over already-visible rows, recording what it is asked."""

    rows: tuple[RecordEventFeedItem, ...] = ()
    probe_answer: frozenset[str] = frozenset()
    page_calls: list[frozenset[RecordEventFamily]] = field(default_factory=list)
    probes: list[frozenset[str]] = field(default_factory=list)
    visibility_calls: list[tuple[frozenset[str], frozenset[RecordEventFamily], bool]] = field(
        default_factory=list
    )

    def page(
        self,
        *,
        principal_id: str,
        after_sequence: int,
        families: frozenset[RecordEventFamily],
        include_restricted_memory: bool,
        limit: int,
    ) -> RecordEventPage:
        self.page_calls.append(families)
        rows = tuple(row for row in self.rows if row.record_family in families)
        return RecordEventPage(
            rows=rows[: limit + 1], high_watermark_event_id=rows[-1].event_id if rows else None
        )

    def resolve_position(self, *, principal_id: str, event_id: str) -> int | None:
        return next(
            (index + 1 for index, row in enumerate(self.rows) if row.event_id == event_id), None
        )

    def visible_event_ids(
        self,
        *,
        principal_id: str,
        event_ids: frozenset[str],
        families: frozenset[RecordEventFamily],
        include_restricted_memory: bool,
    ) -> frozenset[str]:
        self.probes.append(event_ids)
        self.visibility_calls.append((event_ids, families, include_restricted_memory))
        # RECR-3: a cursor anchor among the rows is visible under its own family.
        listed = frozenset(row.event_id for row in self.rows if row.record_family in families)
        return event_ids & (self.probe_answer | listed)


def run(
    reader: RecordEventReader,
    capability_grants: Grants | None,
    *,
    available: frozenset[Capability] = ALL,
    cursor: str | None = None,
    page_size: int = 50,
) -> RecordEventListView:
    return list_record_events(
        reader,
        principal_id=PRINCIPAL,
        available_capabilities=available,
        capability_grants=capability_grants,
        record_families=None,
        page_size=page_size,
        cursor=cursor,
    )


# ---- RE-AC-067 -------------------------------------------------------------------


def test_a_grant_set_naming_no_family_read_sees_nothing() -> None:
    reader = FakeReader(rows=(item("rcev_grantnarrow0001", RecordEventFamily.TASK),))
    list_only = frozenset({(Capability.TASKS_CREATE, Purpose.TASK_AUTHORING)})
    view = run(reader, list_only)
    assert view.visible_families == ()
    assert view.events == ()
    assert view.next_cursor is None
    read = read_cursor(view.high_watermark_cursor)
    assert read is not None and read[1] is None
    assert reader.page_calls == []


# ---- RE-AC-068 -------------------------------------------------------------------


@pytest.mark.parametrize("capability", MAPPED, ids=lambda capability: capability.value)
def test_each_mapped_read_admits_exactly_its_families(capability: Capability) -> None:
    mapped = {family for family, reads in RECORD_EVENT_FAMILY_READS.items() if capability in reads}
    alone = visible_families(ALL, grants(capability))
    assert alone == {family for family in mapped if family not in ENTITY_FLOOR_FAMILIES}
    with_floor = visible_families(ALL, grants(capability, ENTITY_FLOOR_CAPABILITY))
    assert with_floor == mapped | {RecordEventFamily.ENTITY}


def test_the_entity_floor_withholds_every_sub_family_without_entities_get() -> None:
    profile = visible_families(ALL, grants(Capability.ENTITIES_PROFILE))
    assert profile == frozenset()
    floored = visible_families(ALL, grants(Capability.ENTITIES_PROFILE, Capability.ENTITIES_GET))
    assert floored == {
        RecordEventFamily.ENTITY,
        RecordEventFamily.ENTITY_NAME,
        RecordEventFamily.ENTITY_ADDRESS,
        RecordEventFamily.ENTITY_COMMUNICATION_METHOD,
        RecordEventFamily.ENTITY_PROJECT_PARTICIPATION,
        RecordEventFamily.PERSON_ORGANIZATION_AFFILIATION,
    }


def test_a_grant_for_another_purpose_admits_nothing() -> None:
    wrong = frozenset({(Capability.TASKS_READ, Purpose.COMMITMENT_READ)})
    assert visible_families(ALL, wrong) == frozenset()
    wide = frozenset({(Capability.TASKS_READ, None)})
    assert visible_families(ALL, wide) == {RecordEventFamily.TASK}


def test_a_family_whose_reads_are_not_composed_is_invisible_to_everyone() -> None:
    memory_reads = RECORD_EVENT_FAMILY_READS[RecordEventFamily.RELATIONSHIP_MEMORY]
    without_memory = ALL - memory_reads
    assert RecordEventFamily.RELATIONSHIP_MEMORY not in visible_families(without_memory, None)
    granted = grants(*memory_reads)
    assert visible_families(without_memory, granted) == frozenset()
    assert visible_families(ALL, granted) == {RecordEventFamily.RELATIONSHIP_MEMORY}
    # The floor must itself be composed.
    floor_absent = ALL - {Capability.ENTITIES_GET}
    both = grants(Capability.ENTITIES_NAMES_LIST, Capability.ENTITIES_GET)
    assert visible_families(floor_absent, both) == frozenset()


def test_a_local_caller_sees_every_composed_family() -> None:
    assert visible_families(ALL, None) == frozenset(RecordEventFamily)


def test_capture_and_comment_families_need_their_own_read() -> None:
    """WP-RE-08 RE-AC-100: `capture` needs `capture.read` or `capture.list`, and
    `task_comment` needs `tasks.comments.list`; nothing else discloses either,
    and neither takes a floor (OD-W8-1 (i))."""
    capture, comment = RecordEventFamily.CAPTURE, RecordEventFamily.TASK_COMMENT
    assert visible_families(ALL, grants(Capability.CAPTURE_READ)) == {capture}
    assert visible_families(ALL, grants(Capability.CAPTURE_LIST)) == {capture}
    assert visible_families(ALL, grants(Capability.TASKS_COMMENTS_LIST)) == {comment}
    # `capture.search` returns identifiers without records: never a disclosure.
    assert visible_families(ALL, grants(Capability.CAPTURE_SEARCH)) == frozenset()
    # A Task read does not disclose its comments, nor a comment read its Task.
    assert comment not in visible_families(ALL, grants(Capability.TASKS_READ))
    assert RecordEventFamily.TASK not in visible_families(
        ALL, grants(Capability.TASKS_COMMENTS_LIST)
    )
    everything_else = grants(
        *(
            capability
            for capability in MAPPED
            if capability
            not in {
                Capability.CAPTURE_READ,
                Capability.CAPTURE_LIST,
                Capability.TASKS_COMMENTS_LIST,
            }
        )
    )
    visible = visible_families(ALL, everything_else)
    assert capture not in visible
    assert comment not in visible
    # The withheld rows never reach the page either.
    rows = (
        item("rcev_grantnarrow0001", capture),
        item("rcev_grantnarrow0002", comment),
        item("rcev_grantnarrow0003", RecordEventFamily.TASK),
    )
    view = run(FakeReader(rows=rows), grants(Capability.TASKS_READ))
    assert [event.event_id for event in view.events] == ["rcev_grantnarrow0003"]


def test_a_capture_read_grant_enters_the_digest_and_invalidates_the_cursor() -> None:
    """RE-AC-100/069: gaining `capture.read` changes the binding of a prior cursor."""
    rows = tuple(item(f"rcev_grantnarrow000{index}", RecordEventFamily.TASK) for index in (1, 2))
    reader = FakeReader(rows=rows)
    before = run(reader, grants(Capability.TASKS_READ), page_size=1)
    assert before.next_cursor is not None
    for widened in (
        grants(Capability.TASKS_READ, Capability.CAPTURE_READ),
        grants(Capability.TASKS_READ, Capability.TASKS_COMMENTS_LIST),
    ):
        with pytest.raises(ConflictError):
            run(reader, widened, page_size=1, cursor=before.next_cursor)


# ---- RE-AC-062 / 069 ---------------------------------------------------------------


def test_a_grant_change_that_keeps_the_visible_set_still_invalidates_the_cursor() -> None:
    rows = tuple(item(f"rcev_grantnarrow000{index}", RecordEventFamily.TASK) for index in (1, 2))
    reader = FakeReader(rows=rows)
    before = run(reader, grants(Capability.TASKS_READ), page_size=1)
    assert before.next_cursor is not None
    widened = grants(Capability.TASKS_READ, Capability.TASKS_LIST)
    assert run(reader, widened).visible_families == before.visible_families
    with pytest.raises(ConflictError):
        run(reader, widened, page_size=1, cursor=before.next_cursor)
    assert (
        len(
            run(
                reader, grants(Capability.TASKS_READ), page_size=1, cursor=before.next_cursor
            ).events
        )
        == 1
    )


def test_the_visible_set_is_part_of_the_binding() -> None:
    reader = FakeReader(
        rows=tuple(item(f"rcev_grantnarrow000{index}", RecordEventFamily.TASK) for index in (1, 2))
    )
    token = run(reader, None, page_size=1).next_cursor
    assert token is not None
    with pytest.raises(ConflictError):
        run(
            reader,
            None,
            available=ALL - {Capability.MEETINGS_READ, Capability.MEETINGS_LIST},
            page_size=1,
            cursor=token,
        )


# ---- OD-12 ------------------------------------------------------------------------


def test_remote_causation_is_nulled_unless_the_cause_is_visible() -> None:
    cause, effect, sibling = "rcev_grantnarrow0001", "rcev_grantnarrow0002", "rcev_grantnarrow0003"
    rows = (
        item(effect, RecordEventFamily.TASK, causation_event_id=cause),
        item(sibling, RecordEventFamily.TASK, causation_event_id=effect),
    )
    hidden = FakeReader(rows=rows)
    remote = run(hidden, grants(Capability.TASKS_READ))
    assert [event.causation_event_id for event in remote.events] == [None, effect]
    assert hidden.probes == [frozenset({cause})]

    visible = FakeReader(rows=rows, probe_answer=frozenset({cause}))
    assert [
        event.causation_event_id for event in run(visible, grants(Capability.TASKS_READ)).events
    ] == [cause, effect]

    local = FakeReader(rows=rows)
    assert [event.causation_event_id for event in run(local, None).events] == [cause, effect]
    assert local.probes == []


# ---- RECR-AC-014 -------------------------------------------------------------------


def test_the_position_is_resolved_under_the_effective_families_and_disclosure() -> None:
    """RECR-3 (Gate-2 F-3): a cursor's `e` must pass the page's own predicate.

    Before the position is resolved, the reader's visibility probe is asked
    about exactly `{e}`, under exactly `effective` (visible ∩ requested, not the
    wider visible set) and the request's disclosure flag: false for a remote
    caller, true for a local one.
    """
    task, capture = RecordEventFamily.TASK, RecordEventFamily.CAPTURE
    rows = (
        item("rcev_grantnarrow0001", task),
        item("rcev_grantnarrow0002", capture),
        item("rcev_grantnarrow0003", task),
    )
    for capability_grants, include_restricted in (
        (grants(Capability.TASKS_READ, Capability.CAPTURE_READ), False),
        (None, True),
    ):
        reader = FakeReader(rows=rows)
        cursor: str | None = None
        for _ in range(2):
            view = list_record_events(
                reader,
                principal_id=PRINCIPAL,
                available_capabilities=ALL,
                capability_grants=capability_grants,
                record_families=["task"],
                page_size=1,
                cursor=cursor,
            )
            assert capture in view.visible_families
            assert view.next_cursor is not None
            cursor = view.next_cursor
        anchor = frozenset({"rcev_grantnarrow0001"})
        # The remote page's own causation probes (empty here) are not the anchor check.
        anchor_checks = [call for call in reader.visibility_calls if call[0] == anchor]
        assert anchor_checks == [(anchor, frozenset({task}), include_restricted)]


# ---- RE-AC-072 --------------------------------------------------------------------


def test_the_public_item_carries_exactly_its_thirteen_fields() -> None:
    assert set(RecordEventItemView.model_fields) == {
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
    }
    for withheld in ("principal_id", "classification", "correlation_id", "sequence_number"):
        assert withheld not in RecordEventItemView.model_fields
        assert withheld not in RecordEventFeedItem.__dataclass_fields__
    assert set(RecordEventListView.model_fields) == {
        "events",
        "next_cursor",
        "high_watermark_cursor",
        "visible_families",
    }


# ==== Phase 6B: the end-to-end handler half ====================================
#
# Through `normalize` and `ApplicationService.invoke` over the conftest fake
# unit of work, with synthetic in-memory grant sets.

#: RE-AC-071: every server-owned or authority-bearing name a caller might try to
#: put in the payload. None is a `ListRecordEvents` field, so each is refused by
#: absence -- the builder raises `TypeError` and the request is `invalid_request`.
SERVER_OWNED_PAYLOAD_NAMES: Final = (
    "principal_id",
    "actor",
    "actor_class",
    "authority",
    "classification",
    "sequence_number",
    "after_sequence",
    "grants",
    "capability_grants",
    "visible_families",
    "high_watermark",
    "memory_disclosure",
)
_SERVER_OWNED_VALUES: Final[dict[str, object]] = {
    "principal_id": "prn_grantnarrow99999",
    "sequence_number": 1,
    "after_sequence": 0,
    "grants": [],
    "capability_grants": [],
    "visible_families": ["task"],
    "high_watermark": 0,
}


def _document(payload: dict[str, object]) -> dict[str, object]:
    return {
        "request_id": "req-record_events.list",
        "purpose": Purpose.RECORD_EVENT_READ.value,
        "principal_id": PRINCIPAL,
        "requested_at": "2026-09-30T12:00:00Z",
        "payload": payload,
    }


@pytest.mark.parametrize("name", SERVER_OWNED_PAYLOAD_NAMES)
def test_no_server_owned_field_is_accepted_in_the_payload(name: str) -> None:
    from my_pa.adapters.normalization import normalize
    from my_pa.application.errors import InvalidRequestError

    value = _SERVER_OWNED_VALUES.get(name, "restricted_local")
    refused = False
    try:
        normalize(Capability.RECORD_EVENTS_LIST.value, _document({name: value}))
    except InvalidRequestError:
        refused = True
    assert refused, f"`{name}` was accepted in a record_events.list payload"


def test_the_three_real_fields_are_accepted() -> None:
    """The positive control for the refusals above."""
    from my_pa.adapters.normalization import normalize
    from my_pa.application.commands import ListRecordEvents

    _, command = normalize(
        Capability.RECORD_EVENTS_LIST.value,
        _document({"page_size": 5, "record_families": ["task", "meeting"]}),
    )
    assert command == ListRecordEvents(
        page_size=5, record_families=(RecordEventFamily.TASK, RecordEventFamily.MEETING)
    )
    _, bare = normalize(Capability.RECORD_EVENTS_LIST.value, _document({}))
    assert bare == ListRecordEvents()


@pytest.mark.parametrize(
    "families", [[], ["task", "task"], ["not_a_family"]], ids=["empty", "repeated", "unknown"]
)
def test_a_bad_family_narrowing_is_refused(families: list[str]) -> None:
    from my_pa.adapters.normalization import normalize
    from my_pa.application.errors import InvalidRequestError, SafeDetail

    with pytest.raises(InvalidRequestError) as refused:
        normalize(Capability.RECORD_EVENTS_LIST.value, _document({"record_families": families}))
    assert refused.value.safe_details == (SafeDetail.RECORD_FAMILIES,)


def _handler_result(scene: Any, capability_grants: Grants | None) -> dict[str, Any]:  # noqa: ANN401
    from tests.conftest import build_service, metadata_for

    from my_pa.application.commands import ListRecordEvents

    response = build_service(scene.world, scene.providers).invoke(
        metadata_for(Capability.RECORD_EVENTS_LIST, Purpose.RECORD_EVENT_READ, scene.principal),
        ListRecordEvents(),
        principal=scene.principal,
        capability_grants=capability_grants,
    )
    assert response.error is None, response.error
    assert response.result is not None
    return response.result


LIST_GRANT: Final = frozenset({(Capability.RECORD_EVENTS_LIST, Purpose.RECORD_EVENT_READ)})


def test_through_the_handler_the_entity_floor_and_family_grants_narrow(scene: Any) -> None:  # noqa: ANN401
    from my_pa.domain.common.classification import Classification
    from my_pa.domain.common.identifiers import IdKind
    from my_pa.domain.record_events import RecordEventDraft
    from my_pa.domain.source.registry import issue_identifier

    for family in (RecordEventFamily.TASK, RecordEventFamily.ENTITY_NAME, RecordEventFamily.ENTITY):
        scene.world.record_events.append(
            RecordEventDraft.issue(
                principal_id=scene.principal.principal_id,
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
        )
    assert _handler_result(scene, LIST_GRANT)["events"] == []
    profile_only = _handler_result(scene, LIST_GRANT | grants(Capability.ENTITIES_PROFILE))
    assert profile_only["visible_families"] == []
    floored = _handler_result(
        scene, LIST_GRANT | grants(Capability.ENTITIES_PROFILE, Capability.ENTITIES_GET)
    )
    assert [item["record_family"] for item in floored["events"]] == ["entity_name", "entity"]
    tasks = _handler_result(scene, LIST_GRANT | grants(Capability.TASKS_READ))
    assert [item["record_family"] for item in tasks["events"]] == ["task"]
