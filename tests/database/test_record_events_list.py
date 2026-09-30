"""WP-RE-06 Phase 6A: the `record_events.list` read core on a real database.

Marked `database` (auto `database_clone`), routed to `database-current-head`.
The capability is registered in Phase 6B, so these tests drive the use case
`application.record_events.list_record_events` directly over the production
unit of work's `record_event_reader`; the Phase 6B handler adds only the
transport half. Events are staged through the unit of work's own stager, so the
rows are exactly what an emitter commits.

* **RE-AC-057** -- the page is in per-Principal sequence order.
* **RE-AC-058** -- keyset pages have no duplicates and no skips.
* **RE-AC-059** -- a malformed cursor is `invalid_request(cursor)`.
* **RE-AC-060 / 061** -- a readable token under another binding is
  `conflict(cursor)`; a token issued to Principal A and presented by Principal
  B is a conflict and never data (U-002), before its `e` is resolved; a forged
  `e` naming another Principal's event does not resolve.
* **RE-AC-062 / 063** -- the binding changes with the visible families, the
  requested narrowing, the page size and the disclosure mode.
* **RE-AC-064** -- an empty feed still returns a high-watermark cursor.
* Effective families, the local restricted-memory rule, and remote causation
  nulling through the reader's existence probe (OD-12).

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Final

import pytest
from sqlalchemy import Engine

from my_pa.application.errors import ConflictError, InvalidRequestError
from my_pa.application.record_events import (
    MemoryDisclosure,
    cursor_binding,
    encode_cursor,
    list_record_events,
    read_cursor,
)
from my_pa.contracts.v1.record_events import RecordEventListView
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.record_events import (
    RecordEventActorClass,
    RecordEventDraft,
    RecordEventFamily,
    RecordEventKind,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork

pytestmark = pytest.mark.database

PRINCIPAL_A: Final = "prn_rcevwp06aaaa0001"
PRINCIPAL_B: Final = "prn_rcevwp06bbbb0001"
WHEN: Final = datetime(2026, 9, 30, 12, tzinfo=UTC)
ALL: Final = frozenset(Capability)

type Grants = frozenset[tuple[Capability, Purpose | None]]


def grants(*capabilities: Capability) -> Grants:
    """A synthetic remote grant set: each capability for its one permitted purpose."""
    return frozenset(
        (capability, next(iter(permitted_purposes(capability)))) for capability in capabilities
    )


@pytest.fixture
def engine(migrated_engine: Engine) -> Iterator[Engine]:
    yield migrated_engine


def stage(
    engine: Engine,
    principal_id: str = PRINCIPAL_A,
    family: RecordEventFamily = RecordEventFamily.TASK,
    *,
    classification: Classification = Classification.PRIVATE_LOCAL,
    causation_event_id: str | None = None,
    record_id: str | None = None,
) -> str:
    """Commit one event through the unit of work's own stager; return its id."""
    draft = RecordEventDraft.issue(
        principal_id=principal_id,
        record_family=family,
        record_id=record_id or issue_identifier(IdKind.TASK),
        event_kind=RecordEventKind.CREATED,
        record_version=1,
        changed_fields=("title",),
        source_capability="tasks.create",
        actor_class=RecordEventActorClass.PRINCIPAL,
        classification=classification,
        occurred_at=WHEN,
        causation_event_id=causation_event_id,
    )
    with SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine)) as uow:
        uow.record_events.stage(draft)
    return draft.event_id


def listing(
    engine: Engine,
    principal_id: str = PRINCIPAL_A,
    *,
    capability_grants: Grants | None = None,
    available: frozenset[Capability] = ALL,
    families: object = None,
    page_size: int = 50,
    cursor: str | None = None,
) -> RecordEventListView:
    with SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine)) as uow:
        return list_record_events(
            uow.record_event_reader,
            principal_id=principal_id,
            available_capabilities=available,
            capability_grants=capability_grants,
            record_families=families,
            page_size=page_size,
            cursor=cursor,
        )


def watermark(view: RecordEventListView) -> str | None:
    read = read_cursor(view.high_watermark_cursor)
    assert read is not None
    return read[1]


def ids(view: RecordEventListView) -> list[str]:
    return [item.event_id for item in view.events]


# ---- RE-AC-057 / 058 ----------------------------------------------------------


def test_the_page_is_in_sequence_order(engine: Engine) -> None:
    staged = [
        stage(engine, family=family)
        for family in (
            RecordEventFamily.MEETING,
            RecordEventFamily.TASK,
            RecordEventFamily.PROJECT,
            RecordEventFamily.TASK,
        )
    ]
    view = listing(engine)
    assert ids(view) == staged
    assert view.next_cursor is None
    assert watermark(view) == staged[-1]


def test_keyset_pages_have_no_duplicates_and_no_skips(engine: Engine) -> None:
    staged = [stage(engine) for _ in range(7)]
    seen: list[str] = []
    cursor: str | None = None
    pages = 0
    while True:
        view = listing(engine, page_size=3, cursor=cursor)
        pages += 1
        seen.extend(ids(view))
        assert watermark(view) == staged[-1]
        if view.next_cursor is None:
            break
        cursor = view.next_cursor
    assert pages == 3
    assert seen == staged


def test_resuming_from_the_watermark_returns_only_later_events(engine: Engine) -> None:
    stage(engine)
    first = listing(engine, page_size=10)
    later = [stage(engine), stage(engine)]
    resumed = listing(engine, page_size=10, cursor=first.high_watermark_cursor)
    assert ids(resumed) == later


# ---- RE-AC-059 / 060 / 061 ----------------------------------------------------


def test_a_malformed_cursor_is_an_invalid_request(engine: Engine) -> None:
    stage(engine)
    with pytest.raises(InvalidRequestError):
        listing(engine, cursor="not a cursor!")


def test_a_token_from_another_principal_is_a_conflict_and_never_data(engine: Engine) -> None:
    for _ in range(3):
        stage(engine, PRINCIPAL_A)
    mine = listing(engine, PRINCIPAL_A, page_size=1)
    assert mine.next_cursor is not None
    assert listing(engine, PRINCIPAL_B).events == ()
    with pytest.raises(ConflictError):
        listing(engine, PRINCIPAL_B, page_size=1, cursor=mine.next_cursor)
    with pytest.raises(ConflictError):
        listing(engine, PRINCIPAL_B, page_size=1, cursor=mine.high_watermark_cursor)


def test_a_forged_event_id_from_another_partition_does_not_resolve(engine: Engine) -> None:
    """Step 3 is Principal-scoped: B's own binding with A's event id is unreadable."""
    theirs = stage(engine, PRINCIPAL_A)
    stage(engine, PRINCIPAL_B)
    binding = cursor_binding(
        principal_id=PRINCIPAL_B,
        visible=frozenset(RecordEventFamily),
        requested=None,
        page_size=50,
        disclosure=MemoryDisclosure.INCLUDE_RESTRICTED,
        grants_digest=None,
    )
    refused = False
    try:
        listing(engine, PRINCIPAL_B, cursor=encode_cursor(binding, theirs))
    except InvalidRequestError:
        refused = True
    assert refused, "another Principal's event id resolved inside this partition"
    assert len(listing(engine, PRINCIPAL_B, cursor=encode_cursor(binding, None)).events) == 1


# ---- RE-AC-062 / 063 ----------------------------------------------------------


def test_the_binding_follows_visibility_narrowing_page_size_and_disclosure(
    engine: Engine,
) -> None:
    for _ in range(3):
        stage(engine)
    token = listing(engine, page_size=1).next_cursor
    assert token is not None
    assert len(listing(engine, page_size=1, cursor=token).events) == 1
    with pytest.raises(ConflictError):
        listing(engine, page_size=2, cursor=token)
    with pytest.raises(ConflictError):
        listing(engine, page_size=1, families=(RecordEventFamily.TASK,), cursor=token)
    with pytest.raises(ConflictError):
        listing(
            engine,
            page_size=1,
            available=ALL - {Capability.MEETINGS_READ, Capability.MEETINGS_LIST},
            cursor=token,
        )
    with pytest.raises(ConflictError):
        listing(engine, page_size=1, capability_grants=grants(*ALL), cursor=token)


# ---- RE-AC-064 ----------------------------------------------------------------


def test_an_empty_feed_returns_a_high_watermark_cursor(engine: Engine) -> None:
    view = listing(engine)
    assert view.events == ()
    assert view.next_cursor is None
    assert watermark(view) is None
    stage(engine)
    resumed = listing(engine, cursor=view.high_watermark_cursor)
    assert len(resumed.events) == 1


# ---- effective families, disclosure, causation --------------------------------


def test_effective_families_narrow_the_page_and_the_watermark(engine: Engine) -> None:
    task = stage(engine, family=RecordEventFamily.TASK)
    stage(engine, family=RecordEventFamily.MEETING)
    view = listing(engine, families=(RecordEventFamily.TASK, RecordEventFamily.ENTITY))
    assert ids(view) == [task]
    assert watermark(view) == task
    assert RecordEventFamily.MEETING in view.visible_families
    # A requested family that is not visible is silently omitted.
    hidden = listing(
        engine,
        available=ALL - {Capability.ENTITIES_GET},
        families=(RecordEventFamily.ENTITY,),
    )
    assert hidden.events == ()
    assert watermark(hidden) is None


def test_a_local_reader_sees_restricted_memory_and_a_remote_one_does_not(engine: Engine) -> None:
    restricted = stage(
        engine,
        family=RecordEventFamily.RELATIONSHIP_MEMORY,
        classification=Classification.RESTRICTED_LOCAL,
    )
    assert ids(listing(engine)) == [restricted]
    remote = listing(engine, capability_grants=grants(Capability.RELATIONSHIP_MEMORY_GET))
    assert remote.visible_families == (RecordEventFamily.RELATIONSHIP_MEMORY,)
    assert remote.events == ()
    assert watermark(remote) is None


def test_remote_causation_is_kept_only_when_the_cause_is_visible(engine: Engine) -> None:
    cause = stage(engine, family=RecordEventFamily.PROJECT)
    effect = stage(engine, family=RecordEventFamily.TASK, causation_event_id=cause)
    local = listing(engine)
    assert local.events[1].causation_event_id == cause
    tasks_only = listing(engine, capability_grants=grants(Capability.TASKS_READ))
    assert ids(tasks_only) == [effect]
    assert tasks_only.events[0].causation_event_id is None
    # Visible, but not on this page: kept through the reader's existence probe.
    both = grants(Capability.TASKS_READ, Capability.CONTINUITY_PROJECTS_READ)
    first = listing(engine, capability_grants=both, page_size=1)
    assert ids(first) == [cause]
    assert first.next_cursor is not None
    second = listing(engine, capability_grants=both, page_size=1, cursor=first.next_cursor)
    assert ids(second) == [effect]
    assert second.events[0].causation_event_id == cause
