"""RECR-3 (Gate-2 finding F-3): a cursor position resolves only under the page's predicate.

Marked `database` (auto `database_clone`), routed to `database-current-head`.
The list is the use case over the production unit of work's reader; the
writers are the production `ApplicationService` and `RelationshipMemoryService`,
and -- as in `test_record_events_bootstrap_race.py` -- the restricted capture
version is fixture-written, because no production capture writer can produce
one.

A *hand-built* cursor here carries a genuine binding `b`, read from a token the
same request was issued, and the `e` of an event that request's page would
hide. Decoding still runs in the U-002 order (shape, binding, position); what
changed is step 3: before the position is resolved, the anchor must pass the
page's own visibility predicate (the reader's `visible_event_ids` probe, under
the effective families and, for a remote caller, the withholding of restricted
memory and capture events), so a hidden anchor is `invalid_request(cursor)` --
the same answer as an unknown `e`, so there is no existence oracle.

* **RECR-AC-012** -- an anchor outside the effective families is refused:
  `test_a_hand_built_cursor_on_an_ungranted_family_event_is_refused` (a family
  the grants do not make visible) and
  `test_a_hand_built_cursor_outside_the_requested_narrowing_is_refused` (a
  visible family the request did not ask for).
* **RECR-AC-013** -- a remote anchor on a withheld memory or capture event is
  refused, and a local caller still resumes:
  `test_a_hand_built_cursor_on_a_withheld_memory_event_is_refused`,
  `test_a_hand_built_cursor_on_a_withheld_capture_event_is_refused`,
  `test_a_local_caller_still_resumes_after_a_restricted_event`.
* **RECR-AC-014** (DB half) -- a wrong binding on a hidden anchor is still
  `conflict(cursor)`, with neither the visibility check nor the position lookup:
  `test_a_wrong_binding_on_a_hidden_anchor_is_still_a_conflict`.

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

import pytest
from sqlalchemy import Engine

from my_pa.application.errors import ConflictError, InvalidRequestError, SafeDetail
from my_pa.application.record_events import encode_cursor, list_record_events, read_cursor
from my_pa.contracts.v1.record_events import RecordEventListView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.relationship.memory import MemoryKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import record_events as feed_persistence
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from tests.database.test_record_events_bootstrap_race import (
    CAPTURE_GRANTS,
    MEMORY_GRANTS,
    _capture_events,
    _captured,
    _memory_events,
    _raise_to_restricted,
)
from tests.database.test_relationship_memory_record_events import PRINCIPAL as MEMORY_PRINCIPAL
from tests.database.test_relationship_memory_record_events import _create as create_memory
from tests.database.test_relationship_memory_record_events import _revise as revise_memory
from tests.database.test_relationship_memory_record_events import staged  # noqa: F401
from tests.database.test_task_record_events import PRINCIPAL_A, Runtime, _create, feed

pytestmark = pytest.mark.database

ALL: Final = frozenset(Capability)

type Grants = frozenset[tuple[Capability, Any]]


def _grants(*capabilities: Capability) -> Grants:
    return frozenset(
        (capability, next(iter(permitted_purposes(capability)))) for capability in capabilities
    )


TASK_GRANTS: Final = _grants(Capability.TASKS_READ)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def listing(
    engine: Engine,
    principal_id: str,
    *,
    capability_grants: Grants | None,
    record_families: list[str] | None = None,
    page_size: int = 1,
    cursor: str | None = None,
) -> RecordEventListView:
    with SqlAlchemyUnitOfWork(engine, audit=SqlAlchemyAuditSink(engine)) as uow:
        return list_record_events(
            uow.record_event_reader,
            principal_id=principal_id,
            available_capabilities=ALL,
            capability_grants=capability_grants,
            record_families=record_families,
            page_size=page_size,
            cursor=cursor,
        )


def binding_of(view: RecordEventListView) -> str:
    """The genuine `b` the request was issued, read from its watermark token."""
    read = read_cursor(view.high_watermark_cursor)
    assert read is not None
    return read[0]


def assert_refused(engine: Engine, principal_id: str, cursor: str, **request: Any) -> None:  # noqa: ANN401
    with pytest.raises(InvalidRequestError) as refused:
        listing(engine, principal_id, cursor=cursor, **request)
    assert refused.value.safe_details == (SafeDetail.CURSOR,)


def _task_capture_task(runtime: Runtime) -> tuple[str, str, str]:
    """Task t1, then a capture, then task t2, all PRINCIPAL_A's: their event ids."""
    _create(runtime, "recr03-t1")
    _captured(runtime, PRINCIPAL_A, "recr03-capture")
    _create(runtime, "recr03-t2")
    events = feed(runtime.work_engine, PRINCIPAL_A)
    tasks = [item["event_id"] for item in events if item["record_family"] == "task"]
    captures = [item["event_id"] for item in events if item["record_family"] == "capture"]
    assert len(tasks) == 2 and len(captures) == 1
    return tasks[0], captures[0], tasks[1]


# ---- RECR-AC-012 -------------------------------------------------------------------


def test_a_hand_built_cursor_on_an_ungranted_family_event_is_refused(runtime: Runtime) -> None:
    engine = runtime.work_engine
    t1, capture, t2 = _task_capture_task(runtime)
    issued = listing(engine, PRINCIPAL_A, capability_grants=TASK_GRANTS)
    assert [family.value for family in issued.visible_families] == ["task"]
    assert [item.event_id for item in issued.events] == [t1]
    binding = binding_of(issued)
    assert_refused(
        engine, PRINCIPAL_A, encode_cursor(binding, capture), capability_grants=TASK_GRANTS
    )
    # Control: the same binding on a visible anchor resumes.
    resumed = listing(
        engine, PRINCIPAL_A, capability_grants=TASK_GRANTS, cursor=encode_cursor(binding, t1)
    )
    assert [item.event_id for item in resumed.events] == [t2]


def test_a_hand_built_cursor_outside_the_requested_narrowing_is_refused(runtime: Runtime) -> None:
    engine = runtime.work_engine
    t1, capture, t2 = _task_capture_task(runtime)
    narrowed: dict[str, Any] = {"capability_grants": None, "record_families": ["task"]}
    issued = listing(engine, PRINCIPAL_A, **narrowed)
    assert "capture" in {family.value for family in issued.visible_families}
    assert [item.event_id for item in issued.events] == [t1]
    binding = binding_of(issued)
    assert_refused(engine, PRINCIPAL_A, encode_cursor(binding, capture), **narrowed)
    resumed = listing(engine, PRINCIPAL_A, cursor=encode_cursor(binding, t1), **narrowed)
    assert [item.event_id for item in resumed.events] == [t2]


# ---- RECR-AC-013 -------------------------------------------------------------------


def _plain_and_raised_memory(engine: Engine) -> tuple[str, str, str]:
    """A plain memory (e1), then one created (e2) and raised to restricted (e3)."""
    create_memory(engine, kind=MemoryKind.WORKING_PREFERENCE, key="recr03-plain")
    raised = create_memory(engine, kind=MemoryKind.WORKING_PREFERENCE, key="recr03-raised")
    revise_memory(
        engine,
        raised,
        expected=1,
        key="recr03-raise",
        memory_kind=MemoryKind.SENSITIVITY,
        current_kind=MemoryKind.WORKING_PREFERENCE,
    )
    e1, e2, e3 = _memory_events(engine)
    return e1, e2, e3


def test_a_hand_built_cursor_on_a_withheld_memory_event_is_refused(staged: Engine) -> None:  # noqa: F811
    e1, e2, _ = _plain_and_raised_memory(staged)
    issued = listing(staged, MEMORY_PRINCIPAL, capability_grants=MEMORY_GRANTS)
    assert [item.event_id for item in issued.events] == [e1]
    binding = binding_of(issued)
    # e2 is stored private_local; only its memory's current version withholds it.
    assert_refused(
        staged, MEMORY_PRINCIPAL, encode_cursor(binding, e2), capability_grants=MEMORY_GRANTS
    )
    resumed = listing(
        staged,
        MEMORY_PRINCIPAL,
        capability_grants=MEMORY_GRANTS,
        cursor=encode_cursor(binding, e1),
    )
    assert resumed.events == ()


def test_a_hand_built_cursor_on_a_withheld_capture_event_is_refused(runtime: Runtime) -> None:
    principal = issue_identifier(IdKind.PRINCIPAL)
    engine = runtime.work_engine
    _captured(runtime, principal, "recr03-capture-plain")
    raised = _captured(runtime, principal, "recr03-capture-raised")
    _raise_to_restricted(engine, principal, raised)
    e1, e2 = (item["event_id"] for item in _capture_events(engine, principal))
    issued = listing(engine, principal, capability_grants=CAPTURE_GRANTS)
    assert [item.event_id for item in issued.events] == [e1]
    binding = binding_of(issued)
    assert_refused(engine, principal, encode_cursor(binding, e2), capability_grants=CAPTURE_GRANTS)
    resumed = listing(
        engine, principal, capability_grants=CAPTURE_GRANTS, cursor=encode_cursor(binding, e1)
    )
    assert resumed.events == ()


def test_a_local_caller_still_resumes_after_a_restricted_event(staged: Engine) -> None:  # noqa: F811
    e1, e2, e3 = _plain_and_raised_memory(staged)
    issued = listing(staged, MEMORY_PRINCIPAL, capability_grants=None)
    assert [item.event_id for item in issued.events] == [e1]
    resumed = listing(
        staged,
        MEMORY_PRINCIPAL,
        capability_grants=None,
        cursor=encode_cursor(binding_of(issued), e2),
    )
    assert [item.event_id for item in resumed.events] == [e3]


# ---- RECR-AC-014 (DB half) --------------------------------------------------------


def test_a_wrong_binding_on_a_hidden_anchor_is_still_a_conflict(
    staged: Engine,  # noqa: F811
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _, e2, _ = _plain_and_raised_memory(staged)
    # A genuine binding, but the local request's, not the remote one's.
    foreign = binding_of(listing(staged, MEMORY_PRINCIPAL, capability_grants=None))
    lookups: list[tuple[str, object]] = []
    reader_class = feed_persistence.SqlRecordEventReader
    original_probe = reader_class.visible_event_ids
    original_resolve = reader_class.resolve_position

    def probed(reader: Any, **arguments: Any) -> frozenset[str]:  # noqa: ANN401
        lookups.append(("visible_event_ids", arguments["event_ids"]))
        return original_probe(reader, **arguments)

    def resolved(reader: Any, **arguments: Any) -> int | None:  # noqa: ANN401
        lookups.append(("resolve_position", arguments["event_id"]))
        return original_resolve(reader, **arguments)

    monkeypatch.setattr(reader_class, "visible_event_ids", probed)
    monkeypatch.setattr(reader_class, "resolve_position", resolved)
    with pytest.raises(ConflictError) as conflict:
        listing(
            staged,
            MEMORY_PRINCIPAL,
            capability_grants=MEMORY_GRANTS,
            cursor=encode_cursor(foreign, e2),
        )
    assert conflict.value.safe_details == (SafeDetail.CURSOR,)
    # Neither the visibility check nor the position lookup ran.
    assert lookups == []
    # The counting seams are live: the right binding reaches both, in that order.
    right = listing(staged, MEMORY_PRINCIPAL, capability_grants=MEMORY_GRANTS)
    (visible,) = (item.event_id for item in right.events)
    lookups.clear()
    resumed = listing(
        staged,
        MEMORY_PRINCIPAL,
        capability_grants=MEMORY_GRANTS,
        cursor=encode_cursor(binding_of(right), visible),
    )
    assert resumed.events == ()
    assert lookups[:2] == [
        ("visible_event_ids", frozenset({visible})),
        ("resolve_position", visible),
    ]
