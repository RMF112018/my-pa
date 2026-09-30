"""WP-RE-04 Phase 4C (T-17): the re-enrichment rebind's Record Events (W5, OD-5).

Marked `database` and routed to `database-current-head`. The worker's own
transaction (`settle_reenrichment_work`) stages one `entity_observation`
`updated` per rebound observation into a connection-scoped stager -- only after
`apply_claimed` kept the savepoint -- and flushes it as the last database work
before COMMIT (R-008):

* a kept savepoint commits the events, in ascending `observation_id` order, at
  the feed version of the new `resolution_version` (T-002: the floor holds);
* a stale pass (the savepoint rolled back) and a lost lease commit nothing;
* the partial path commits its events in the same transaction as the
  settlement correction (one `xmin`);
* a flush failure rolls the whole pass back -- the rebind with it.

Every identity is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.engine import Connection

import my_pa.infrastructure.jobs.reenrichment as reenrichment_module
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs.reenrichment import (
    REBIND_SOURCE_CAPABILITY,
    claim_reenrichment_work,
    settle_reenrichment_work,
)
from my_pa.infrastructure.persistence.tables import (
    entity_observations,
    entity_reenrichment_version_watermarks,
)
from tests.database.test_reenrichment_worker import (
    MERGED_AWAY,
    OWNER,
    PRINCIPAL,
    SURVIVOR,
    UNPLACED_MENTION,
    _binding,
    _entity,
    _now,
    _observation,
    _register,
)
from tests.database.test_task_record_events import assert_gap_free, feed, next_sequence

pytestmark = pytest.mark.database

FIRST: Final = "eobs_rcev04c0000000a1"
SECOND: Final = "eobs_rcev04c0000000b2"


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    migrated = create_database_engine(disposable_database)
    try:
        yield migrated
    finally:
        migrated.dispose()


def _stage_world(engine: Engine, *, placeable: bool = False) -> str:
    """Two mentions bound to a merged-away identity; optionally one it could place."""
    with engine.begin() as connection:
        _entity(connection, SURVIVOR, canonical_name="alex chen")
        _entity(
            connection,
            MERGED_AWAY,
            canonical_name="a chen",
            status="merged_redirect",
            superseded_by=SURVIVOR,
        )
        # Inserted out of order: the events must still come in id order.
        for observation_id in (SECOND, FIRST):
            _observation(
                connection,
                observation_id,
                entity_id=MERGED_AWAY,
                normalized_value="a chen who is nobody current",
            )
        if placeable:
            _observation(connection, UNPLACED_MENTION, entity_id=None, normalized_value="alex chen")
        return _register(connection, _binding())


def _resolution_version(engine: Engine, observation_id: str) -> int:
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(entity_observations.c.resolution_version).where(
                    entity_observations.c.observation_id == observation_id
                )
            ).scalar_one()
        )


def _settle(engine: Engine) -> tuple[str, Any, str]:
    work = claim_reenrichment_work(engine, owner=OWNER, at=_now())
    assert work is not None
    state, outcome = settle_reenrichment_work(engine, work, owner=OWNER, at=_now())
    return state, outcome, work.work_id


def test_a_kept_savepoint_commits_one_event_per_rebind_in_id_order(engine: Engine) -> None:
    work_id = _stage_world(engine)
    state, outcome, settled = _settle(engine)
    assert settled == work_id
    assert state == "succeeded"
    assert outcome.rebinds == ((FIRST, 1), (SECOND, 1))
    events = feed(engine, PRINCIPAL)
    assert [(e["record_family"], e["record_id"], e["event_kind"]) for e in events] == [
        ("entity_observation", FIRST, "updated"),
        ("entity_observation", SECOND, "updated"),
    ]
    for event in events:
        # T-002, the feed floor: the new `resolution_version` (1) plus one.
        assert event["record_version"] == _resolution_version(engine, event["record_id"]) + 1 == 2
        assert event["changed_fields"] == ["entity_id", "resolution_version"]
        assert event["source_capability"] == REBIND_SOURCE_CAPABILITY
        assert event["actor_class"] == "system"
        assert event["source_receipt_id"] == work_id
        assert event["classification"] == "private_local"
        assert event["causation_event_id"] is None
    assert_gap_free(engine, PRINCIPAL)


def test_a_stale_pass_commits_no_event(engine: Engine, monkeypatch: pytest.MonkeyPatch) -> None:
    """The savepoint is rolled back when currency moves during apply: the rebind
    it held is discarded, and nothing was staged for it."""
    _stage_world(engine)
    original = reenrichment_module.resolve_derived_linkage

    def rebind_then_move_the_policy(connection: Connection, **kwargs: Any) -> Any:  # noqa: ANN401
        outcome = original(connection, **kwargs)
        assert outcome.rebound == 2
        connection.execute(
            entity_reenrichment_version_watermarks.update()
            .where(
                entity_reenrichment_version_watermarks.c.principal_id == PRINCIPAL,
                entity_reenrichment_version_watermarks.c.namespace == "policy",
            )
            .values(version="policy-v2")
        )
        return outcome

    monkeypatch.setattr(reenrichment_module, "resolve_derived_linkage", rebind_then_move_the_policy)
    state, outcome, _ = _settle(engine)
    assert state == "stale"
    assert outcome.rebinds == ()
    assert _resolution_version(engine, FIRST) == 0
    assert feed(engine, PRINCIPAL) == []
    assert next_sequence(engine, PRINCIPAL) is None


def test_a_lost_lease_commits_no_event(engine: Engine) -> None:
    """The abandoned claim cannot settle; its attempt is failed, not committed."""
    _stage_world(engine)
    abandoned = claim_reenrichment_work(engine, owner=OWNER, at=_now(), lease_seconds=1)
    assert abandoned is not None
    later = _now() + timedelta(minutes=5)
    assert claim_reenrichment_work(engine, owner="worker-reenrich02", at=later) is not None
    state, _ = settle_reenrichment_work(engine, abandoned, owner=OWNER, at=later)
    assert state == "failed"
    assert feed(engine, PRINCIPAL) == []


def test_the_partial_path_commits_its_events_with_the_settlement_correction(
    engine: Engine,
) -> None:
    """R-008: on `partial`, the flush follows `_correct_settlement_to_partial` in
    the same transaction -- the events and the corrected work row share an `xmin`."""
    work_id = _stage_world(engine, placeable=True)
    state, outcome, _ = _settle(engine)
    assert state == "partial"
    assert [event["record_id"] for event in feed(engine, PRINCIPAL)] == [FIRST, SECOND]
    with engine.connect() as connection:
        work_xmin = connection.execute(
            text(
                "SELECT xmin::text FROM knowledge.entity_reenrichment_work "
                "WHERE work_id = :id AND state = 'partial'"
            ),
            {"id": work_id},
        ).scalar_one()
        event_xmins = {
            str(row[0])
            for row in connection.execute(
                text("SELECT xmin::text FROM knowledge.record_events WHERE principal_id = :p"),
                {"p": PRINCIPAL},
            )
        }
    assert event_xmins == {work_xmin}
    assert outcome.rebinds == ((FIRST, 1), (SECOND, 1))


def test_a_flush_failure_rolls_the_whole_pass_back(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The flush raises inside the `with`: the rebind, its settlement and its
    events roll back together, and the attempt is failed in its own transaction."""
    _stage_world(engine)

    def refuse(*args: object, **kwargs: object) -> None:
        raise RuntimeError("synthetic flush failure")

    monkeypatch.setattr(reenrichment_module, "flush_record_events", refuse)
    state, _, _ = _settle(engine)
    assert state == "failed"
    assert _resolution_version(engine, FIRST) == 0
    assert feed(engine, PRINCIPAL) == []
    assert next_sequence(engine, PRINCIPAL) is None


def test_an_idle_rebind_pass_commits_no_event(engine: Engine) -> None:
    """Nothing to rebind: no drafts, so the committing exit has nothing to flush."""
    with engine.begin() as connection:
        _entity(connection, SURVIVOR, canonical_name="alex chen")
        work_id = _register(connection, _binding())
    state, outcome, settled = _settle(engine)
    assert (state, settled, outcome.rebinds) == ("succeeded", work_id, ())
    assert feed(engine, PRINCIPAL) == []
