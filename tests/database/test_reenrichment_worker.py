"""PostgreSQL evidence that the re-enrichment plane executes real work.

`WP-03` / `RI-P3-BLK-001`. `tests/database/test_entity_reenrichment.py` proves
the queue: dedupe, leasing, concurrency, expiry, backoff, watermark fencing and
the savepoint. This file proves the thing that had no proof at all, because it
had no caller -- that a queued item is claimed by a worker, that a **downstream
output actually changes**, that the change is discarded when the binding moves
under it, and that a run which left something undone settles `partial` rather
than `succeeded` (`WP-05` / `RI-P3-MED-001`, v0.2 section 27.5).
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from threading import Event
from typing import Final

import pytest
from alembic.config import Config
from sqlalchemy import Engine, select
from sqlalchemy.engine import Connection

import my_pa.infrastructure.jobs.reenrichment as reenrichment_module
from my_pa.domain.relationship.reenrichment import (
    BindingVersion,
    ReenrichmentBinding,
    ReenrichmentLimitation,
    ReenrichmentState,
    ReenrichmentSubject,
    ReenrichmentSubjectKind,
    ReenrichmentTrigger,
)
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.jobs.reenrichment import (
    claim_reenrichment_work,
    reenrichment_tables,
    resolve_derived_linkage,
    run_reenrichment_worker,
    settle_reenrichment_work,
)
from my_pa.infrastructure.persistence.entity_reenrichment import (
    SqlCurrentReenrichmentBindings,
    SqlReenrichmentWorkRepository,
)
from my_pa.infrastructure.persistence.tables import (
    entities,
    entity_observations,
    entity_reenrichment_version_watermarks,
    entity_reenrichment_work,
)

pytestmark = pytest.mark.database

ROOT: Final = Path(__file__).resolve().parents[2]
DISPOSABLE_DATABASE: Final = "my_pa_ri_reenrichment_worker_test"
PRINCIPAL: Final = "prn_aaaa0001aaaa0001aaaa0001"
OTHER_PRINCIPAL: Final = "prn_bbbb0002bbbb0002bbbb0002"
SURVIVOR: Final = "ent_aaaa0001aaaa0001"
MERGED_AWAY: Final = "ent_bbbb0002bbbb0002"
BOUND_MENTION: Final = "eobs_aaaa0001aaaa0001"
UNPLACED_MENTION: Final = "eobs_cccc0003cccc0003"
OWNER: Final = "worker-reenrich01"
#: Seed rows are stamped in the past so `next_attempt_at <= now` holds without
#: the test depending on the machine's clock agreeing with a literal. The worker
#: is driven by the real clock, because `apply_claimed` fences on PostgreSQL's
#: own `clock_timestamp()` and a frozen literal would race it.
WHEN: Final = datetime(2020, 1, 1, tzinfo=UTC)


def _now() -> datetime:
    return datetime.now(UTC)


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


@pytest.fixture
def engine(disposable_database: str) -> Iterator[Engine]:
    migrated = create_database_engine(disposable_database)
    try:
        yield migrated
    finally:
        migrated.dispose()


# ---- synthetic fixtures ---------------------------------------------------
#
# Two entities and two mentions, all synthetic. `MERGED_AWAY` is redirected at
# `SURVIVOR` exactly as `redirect_entity` leaves it, which is what the schema's
# `(status = 'merged_redirect') = (superseded_by_entity_id IS NOT NULL)` makes
# the only representable shape.


def _entity(
    connection: Connection,
    entity_id: str,
    *,
    principal_id: str = PRINCIPAL,
    canonical_name: str,
    status: str = "active",
    superseded_by: str | None = None,
    version: int = 1,
) -> None:
    connection.execute(
        entities.insert().values(
            entity_id=entity_id,
            principal_id=principal_id,
            entity_type="person",
            canonical_name=canonical_name,
            display_name=canonical_name.title(),
            status=status,
            superseded_by_entity_id=superseded_by,
            created_at=WHEN,
            updated_at=WHEN,
            version=version,
        )
    )


def _observation(
    connection: Connection,
    observation_id: str,
    *,
    principal_id: str = PRINCIPAL,
    entity_id: str | None,
    normalized_value: str,
) -> None:
    connection.execute(
        entity_observations.insert().values(
            observation_id=observation_id,
            principal_id=principal_id,
            kind="document_mention",
            observed_value=normalized_value.title(),
            normalized_value=normalized_value,
            source_id="src_aaaa0001aaaa0001",
            source_object_id="obj_aaaa0001aaaa0001",
            source_version_id="ver_aaaa0001aaaa0001",
            observed_at=WHEN,
            recorded_at=WHEN,
            entity_id=entity_id,
            authority="source_observation",
            state="current",
            resolution_version=0,
        )
    )


def _binding(
    *,
    principal_id: str = PRINCIPAL,
    subjects: tuple[ReenrichmentSubject, ...] | None = None,
) -> ReenrichmentBinding:
    return ReenrichmentBinding(
        principal_id=principal_id,
        trigger=ReenrichmentTrigger.CORRECTED_IDENTITY,
        cause_record_id="eiop_aaaa0001aaaa0001",
        subjects=subjects
        or (ReenrichmentSubject(ReenrichmentSubjectKind.PRINCIPAL, principal_id, "1"),),
        input_versions=(),
        producer_versions=(BindingVersion("relationship_intelligence", "ri-v0.2"),),
        policy_version="policy-v1",
    )


def _register(connection: Connection, binding: ReenrichmentBinding) -> str:
    repository = SqlReenrichmentWorkRepository(connection, reenrichment_tables())
    for item in binding.producer_versions:
        repository.observe_version(
            binding.principal_id,
            namespace="producer",
            key=item.key,
            version=item.version,
            at=WHEN,
        )
    repository.observe_version(
        binding.principal_id,
        namespace="policy",
        key="current",
        version=binding.policy_version,
        at=WHEN,
    )
    return repository.register(binding, at=WHEN).work_id


def _stored(connection: Connection, work_id: str) -> object:
    return connection.execute(
        select(
            entity_reenrichment_work.c.state,
            entity_reenrichment_work.c.limitations,
            entity_reenrichment_work.c.stale_reasons,
            entity_reenrichment_work.c.completed_at,
            entity_reenrichment_work.c.attempt_count,
            entity_reenrichment_work.c.lease_owner,
        ).where(entity_reenrichment_work.c.work_id == work_id)
    ).one()


def _bound_entity(connection: Connection, observation_id: str) -> tuple[str | None, int]:
    row = connection.execute(
        select(
            entity_observations.c.entity_id,
            entity_observations.c.resolution_version,
        ).where(entity_observations.c.observation_id == observation_id)
    ).one()
    return (None if row.entity_id is None else str(row.entity_id)), int(row.resolution_version)


# ---- the four claims ------------------------------------------------------


def test_queued_work_is_claimed_applied_and_settles_succeeded(engine: Engine) -> None:
    """Queued -> claimed -> the downstream output really changes -> succeeded."""
    with engine.begin() as connection:
        _entity(connection, SURVIVOR, canonical_name="alex chen")
        _entity(
            connection,
            MERGED_AWAY,
            canonical_name="a chen",
            status="merged_redirect",
            superseded_by=SURVIVOR,
        )
        # Bound to the merged-away entity, and named by nothing current, so
        # nothing is left for a governed decision after the rebind.
        _observation(
            connection,
            BOUND_MENTION,
            entity_id=MERGED_AWAY,
            normalized_value="a chen who is nobody current",
        )
        work_id = _register(connection, _binding())

    run = run_reenrichment_worker(engine, owner=OWNER, stop=Event(), max_iterations=1, now=_now)

    assert (run.claimed, run.succeeded, run.partial, run.stale, run.failed) == (1, 1, 0, 0, 0)
    assert run.rebound == 1
    with engine.begin() as connection:
        stored = _stored(connection, work_id)
        assert stored.state == ReenrichmentState.SUCCEEDED.value  # type: ignore[attr-defined]
        assert stored.limitations is None  # type: ignore[attr-defined]
        assert stored.completed_at is not None  # type: ignore[attr-defined]
        assert stored.lease_owner is None  # type: ignore[attr-defined]
        # The real downstream output: the mention now names the surviving
        # identity, and the decision counter advanced with it.
        assert _bound_entity(connection, BOUND_MENTION) == (SURVIVOR, 1)


def test_a_second_run_finds_nothing_to_do_which_is_what_idempotent_means(
    engine: Engine,
) -> None:
    with engine.begin() as connection:
        _entity(connection, SURVIVOR, canonical_name="alex chen")
        _entity(
            connection,
            MERGED_AWAY,
            canonical_name="a chen",
            status="merged_redirect",
            superseded_by=SURVIVOR,
        )
        _observation(
            connection,
            BOUND_MENTION,
            entity_id=MERGED_AWAY,
            normalized_value="a chen who is nobody current",
        )
        binding = _binding()
        _register(connection, binding)

    run_reenrichment_worker(engine, owner=OWNER, stop=Event(), max_iterations=1, now=_now)
    with engine.begin() as connection:
        second = resolve_derived_linkage(connection, principal_id=PRINCIPAL)
    assert second.rebound == 0
    assert second.limitations == ()
    with engine.begin() as connection:
        # Not rebound twice: `resolution_version` moved exactly once.
        assert _bound_entity(connection, BOUND_MENTION) == (SURVIVOR, 1)


def test_partial_downstream_completion_settles_partial_and_never_succeeded(
    engine: Engine,
) -> None:
    """v0.2 section 27.5 line 1846: partial processing never appears complete."""
    with engine.begin() as connection:
        _entity(connection, SURVIVOR, canonical_name="alex chen")
        _entity(
            connection,
            MERGED_AWAY,
            canonical_name="a chen",
            status="merged_redirect",
            superseded_by=SURVIVOR,
        )
        _observation(
            connection,
            BOUND_MENTION,
            entity_id=MERGED_AWAY,
            normalized_value="a chen who is nobody current",
        )
        # A mention the corrected graph could now place -- its normalized form
        # is the survivor's canonical name -- and that only a governed decision
        # may place. The worker counts it and refuses to bind it.
        _observation(
            connection,
            UNPLACED_MENTION,
            entity_id=None,
            normalized_value="alex chen",
        )
        work_id = _register(connection, _binding())

    run = run_reenrichment_worker(engine, owner=OWNER, stop=Event(), max_iterations=1, now=_now)

    assert (run.succeeded, run.partial) == (0, 1)
    with engine.begin() as connection:
        stored = _stored(connection, work_id)
        assert stored.state == ReenrichmentState.PARTIAL.value  # type: ignore[attr-defined]
        assert stored.state != ReenrichmentState.SUCCEEDED.value  # type: ignore[attr-defined]
        # `partial_reenrichment_states_its_limitations` and
        # `terminal_reenrichment_records_completion` are both satisfied by the
        # same row, which is what makes `partial` a durable terminal answer.
        assert list(stored.limitations) == [  # type: ignore[attr-defined]
            ReenrichmentLimitation.NO_AUTONOMOUS_IDENTITY_MUTATION.value
        ]
        assert stored.completed_at is not None  # type: ignore[attr-defined]
        assert stored.stale_reasons is None  # type: ignore[attr-defined]
        # The half it could do, it did; the half it could not, it did not.
        assert _bound_entity(connection, BOUND_MENTION) == (SURVIVOR, 1)
        assert _bound_entity(connection, UNPLACED_MENTION) == (None, 0)


def test_a_stored_partial_result_hydrates_as_partial_with_its_limitations(
    engine: Engine,
) -> None:
    """The `_hydrate` half: a `partial` row reads back as a valid domain object.

    Before WP-05 the domain type had no `limitations` field, so a `partial`
    row could be written and could not be read: the invariant
    `(state is PARTIAL) is bool(limitations)` would refuse the object the
    adapter built. This is the proof that both ends now agree.
    """
    with engine.begin() as connection:
        _entity(connection, SURVIVOR, canonical_name="alex chen")
        _observation(connection, UNPLACED_MENTION, entity_id=None, normalized_value="alex chen")
        work_id = _register(connection, _binding())

    run_reenrichment_worker(engine, owner=OWNER, stop=Event(), max_iterations=1, now=_now)

    with engine.begin() as connection:
        repository = SqlReenrichmentWorkRepository(connection, reenrichment_tables())
        stored = repository.get(PRINCIPAL, work_id)
    assert stored is not None
    assert stored.state is ReenrichmentState.PARTIAL
    assert stored.limitations == (ReenrichmentLimitation.NO_AUTONOMOUS_IDENTITY_MUTATION,)
    assert stored.completed_at is not None


def test_currency_moving_during_apply_discards_the_output_and_settles_stale(
    engine: Engine,
) -> None:
    """The savepoint fence, proved against a real downstream mutation.

    The callback does the derived pass *and then* advances the policy
    watermark, so the post-apply currency check finds the binding has moved
    under it. The savepoint that contains the callback is rolled back, so the
    rebinding it performed is discarded rather than committed under a `stale`
    result -- which is the property that makes `stale` safe to trust.

    The watermark rather than the subject version, because
    `SqlCurrentReenrichmentBindings` locks and caches subject versions before
    the callback runs and re-reads only the watermarks afterwards. Moving the
    thing that is actually re-read is what exercises the post-apply check
    rather than the pre-apply one.
    """
    binding = _binding()
    with engine.begin() as connection:
        _entity(connection, SURVIVOR, canonical_name="alex chen")
        _entity(
            connection,
            MERGED_AWAY,
            canonical_name="a chen",
            status="merged_redirect",
            superseded_by=SURVIVOR,
        )
        _observation(
            connection,
            BOUND_MENTION,
            entity_id=MERGED_AWAY,
            normalized_value="a chen who is nobody current",
        )
        work_id = _register(connection, binding)

    work = claim_reenrichment_work(engine, owner=OWNER, at=_now())
    assert work is not None

    tables = reenrichment_tables()
    with engine.begin() as connection:

        def apply_then_move_the_binding(bound: ReenrichmentBinding, digest: str) -> None:
            del bound, digest
            outcome = resolve_derived_linkage(connection, principal_id=PRINCIPAL)
            assert outcome.rebound == 1
            connection.execute(
                entity_reenrichment_version_watermarks.update()
                .where(
                    entity_reenrichment_version_watermarks.c.principal_id == PRINCIPAL,
                    entity_reenrichment_version_watermarks.c.namespace == "policy",
                    entity_reenrichment_version_watermarks.c.binding_key == "current",
                )
                .values(version="policy-v2")
            )

        currency = SqlReenrichmentWorkRepository(connection, tables).apply_claimed(
            PRINCIPAL,
            work.work_id,
            owner=OWNER,
            current=SqlCurrentReenrichmentBindings(connection, tables),
            apply=apply_then_move_the_binding,
            at=_now(),
        )
    assert not currency.is_current

    with engine.begin() as connection:
        stored = _stored(connection, work_id)
        assert stored.state == ReenrichmentState.STALE.value  # type: ignore[attr-defined]
        assert stored.limitations is None  # type: ignore[attr-defined]
        assert list(stored.stale_reasons) == ["policy_version_changed"]  # type: ignore[attr-defined]
        # Rolled back with the savepoint: the mention still names the
        # merged-away entity and nothing counted a decision about it.
        assert _bound_entity(connection, BOUND_MENTION) == (MERGED_AWAY, 0)
        # And the callback's own write went with it.
        assert (
            connection.execute(
                select(entity_reenrichment_version_watermarks.c.version).where(
                    entity_reenrichment_version_watermarks.c.principal_id == PRINCIPAL,
                    entity_reenrichment_version_watermarks.c.namespace == "policy",
                )
            ).scalar_one()
            == "policy-v1"
        )


# ---- the preserved invariants the plane now runs under --------------------


def test_the_worker_never_crosses_a_principal(engine: Engine) -> None:
    """Principal isolation, through the worker rather than the repository.

    Another Principal's mention is bound to *their* merged-away entity. The
    claimed item belongs to `PRINCIPAL`, and the pass is scoped to the
    binding's own Principal, so the other partition is untouched.
    """
    with engine.begin() as connection:
        _entity(connection, SURVIVOR, canonical_name="alex chen")
        _entity(
            connection,
            MERGED_AWAY,
            canonical_name="a chen",
            status="merged_redirect",
            superseded_by=SURVIVOR,
        )
        _observation(
            connection,
            BOUND_MENTION,
            entity_id=MERGED_AWAY,
            normalized_value="a chen who is nobody current",
        )
        _entity(
            connection,
            "ent_cccc0003cccc0003",
            principal_id=OTHER_PRINCIPAL,
            canonical_name="other survivor",
        )
        _entity(
            connection,
            "ent_dddd0004dddd0004",
            principal_id=OTHER_PRINCIPAL,
            canonical_name="other merged",
            status="merged_redirect",
            superseded_by="ent_cccc0003cccc0003",
        )
        _observation(
            connection,
            "eobs_eeee0005eeee0005",
            principal_id=OTHER_PRINCIPAL,
            entity_id="ent_dddd0004dddd0004",
            normalized_value="somebody else entirely",
        )
        _register(connection, _binding())

    run = run_reenrichment_worker(engine, owner=OWNER, stop=Event(), max_iterations=1, now=_now)
    assert run.rebound == 1
    with engine.begin() as connection:
        assert _bound_entity(connection, BOUND_MENTION) == (SURVIVOR, 1)
        assert _bound_entity(connection, "eobs_eeee0005eeee0005") == (
            "ent_dddd0004dddd0004",
            0,
        )


def test_a_governed_decision_running_concurrently_is_yielded_to(
    engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The `resolution_version` guard `plan_observations` deliberately left open.

    A separate committed transaction advances the counter between the pass's
    read and its guarded write, standing in for the `decide_observation` a
    reviewer is running at the same moment. The guarded update then matches
    nothing, the worker leaves the row exactly as it found it rather than
    overwriting somebody's conclusion about who a mention is, and the shortfall
    is reported instead of hidden.

    The interference is committed from its own connection, so this is a real
    concurrent write and not a simulation of one. `_current_survivor` is the
    seam because it is what runs between the read and the write.
    """
    with engine.begin() as connection:
        _entity(connection, SURVIVOR, canonical_name="alex chen")
        _entity(
            connection,
            MERGED_AWAY,
            canonical_name="a chen",
            status="merged_redirect",
            superseded_by=SURVIVOR,
        )
        _observation(
            connection,
            BOUND_MENTION,
            entity_id=MERGED_AWAY,
            normalized_value="a chen who is nobody current",
        )
        binding = _binding()
        _register(connection, binding)

    original = reenrichment_module._current_survivor
    interfered = False

    def decide_underneath(connection: Connection, **kwargs: object) -> str | None:
        nonlocal interfered
        if not interfered:
            interfered = True
            with engine.begin() as other:
                other.execute(
                    entity_observations.update()
                    .where(entity_observations.c.observation_id == BOUND_MENTION)
                    .values(resolution_version=entity_observations.c.resolution_version + 1)
                )
        return original(connection, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reenrichment_module, "_current_survivor", decide_underneath)

    with engine.begin() as connection:
        outcome = resolve_derived_linkage(connection, principal_id=PRINCIPAL)

    assert interfered
    assert outcome.rebound == 0
    assert ReenrichmentLimitation.NO_AUTONOMOUS_IDENTITY_MUTATION in outcome.limitations
    with engine.begin() as connection:
        # Untouched by this worker; the decision that raced it owns the row.
        assert _bound_entity(connection, BOUND_MENTION) == (MERGED_AWAY, 1)


def test_a_second_worker_finds_nothing_claimable_while_the_first_holds_the_lease(
    engine: Engine,
) -> None:
    """`FOR UPDATE SKIP LOCKED` plus a committed lease: one claimant, not two."""
    with engine.begin() as connection:
        _register(connection, _binding())

    first = claim_reenrichment_work(engine, owner=OWNER, at=_now())
    second = claim_reenrichment_work(engine, owner="worker-reenrich02", at=_now())
    assert first is not None
    assert second is None
    assert first.state is ReenrichmentState.RUNNING
    assert first.attempt_count == 1


def test_an_expired_lease_is_reclaimable_and_the_stale_claim_cannot_settle(
    engine: Engine,
) -> None:
    """Lease expiry, the reaper, and stale-claim rejection, in one sequence."""
    with engine.begin() as connection:
        _register(connection, _binding())

    abandoned = claim_reenrichment_work(engine, owner=OWNER, at=_now(), lease_seconds=1)
    assert abandoned is not None

    later = _now() + timedelta(minutes=5)
    reclaimed = claim_reenrichment_work(engine, owner="worker-reenrich02", at=later)
    assert reclaimed is not None
    assert reclaimed.work_id == abandoned.work_id
    assert reclaimed.attempt_count == 2

    # The abandoned worker comes back and tries to settle. Its owner no longer
    # matches the row's, so `apply_claimed` refuses and the attempt is failed
    # rather than committed.
    state, outcome = settle_reenrichment_work(engine, abandoned, owner=OWNER, at=later)
    assert state == "failed"
    assert outcome.rebound == 0
    with engine.begin() as connection:
        # The live claim is untouched: still running, still the second worker's.
        stored = _stored(connection, reclaimed.work_id)
        assert stored.state == ReenrichmentState.RUNNING.value  # type: ignore[attr-defined]
        assert stored.lease_owner == "worker-reenrich02"  # type: ignore[attr-defined]


def test_registration_dedupes_so_the_worker_never_runs_one_binding_twice(
    engine: Engine,
) -> None:
    """`one_entity_reenrichment_binding` survives the plane being executable."""
    binding = _binding()
    with engine.begin() as connection:
        first = _register(connection, binding)
        second = _register(connection, binding)
    assert first == second

    run = run_reenrichment_worker(engine, owner=OWNER, stop=Event(), max_iterations=2, now=_now)
    assert run.claimed == 1
    assert run.idle == 1


def test_a_moved_watermark_makes_the_claimed_item_stale_before_any_output(
    engine: Engine,
) -> None:
    """Watermark fencing: the pre-apply fence runs before the callback does."""
    with engine.begin() as connection:
        _entity(connection, SURVIVOR, canonical_name="alex chen")
        _entity(
            connection,
            MERGED_AWAY,
            canonical_name="a chen",
            status="merged_redirect",
            superseded_by=SURVIVOR,
        )
        _observation(
            connection,
            BOUND_MENTION,
            entity_id=MERGED_AWAY,
            normalized_value="a chen who is nobody current",
        )
        work_id = _register(connection, _binding())
        SqlReenrichmentWorkRepository(connection, reenrichment_tables()).observe_version(
            PRINCIPAL,
            namespace="policy",
            key="current",
            version="policy-v2",
            at=WHEN,
        )

    run = run_reenrichment_worker(engine, owner=OWNER, stop=Event(), max_iterations=1, now=_now)
    assert (run.stale, run.succeeded, run.partial) == (1, 0, 0)
    assert run.rebound == 0
    with engine.begin() as connection:
        stored = _stored(connection, work_id)
        assert stored.state == ReenrichmentState.STALE.value  # type: ignore[attr-defined]
        assert list(stored.stale_reasons) == ["policy_version_changed"]  # type: ignore[attr-defined]
        assert _bound_entity(connection, BOUND_MENTION) == (MERGED_AWAY, 0)


def test_an_empty_queue_is_an_idle_bounded_run(engine: Engine) -> None:
    run = run_reenrichment_worker(engine, owner=OWNER, stop=Event(), max_iterations=3, now=_now)
    assert (run.iterations, run.claimed, run.idle) == (3, 0, 3)
