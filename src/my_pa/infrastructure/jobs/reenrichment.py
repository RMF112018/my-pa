"""The re-enrichment plane: claim one bounded work item, re-resolve, settle.

**Why this module exists.** `WP-03` / `RI-P3-BLK-001`: the claim-and-settle
primitive was complete and had no caller anywhere in the repository, so nothing
executed durable Relationship Intelligence invalidation. This is the production
consumer, and it is a *third plane on the existing worker process* rather than a
new one. `AGENTS.md` section 2 forbids a new process, daemon, queue or cache
without durable architectural justification and section 3 defers "additional
... worker types"; `ADR-001` already accepts `my-pa-worker` as a composition
surface, so a row in `apps/worker.py`'s `_PLANES` and a loop here is the
compliant shape and a second process would not be.

**Why it is not `infrastructure.jobs.worker.run_worker`.** That loop is
parameterised over a `JobPlane`, and `entity_reenrichment_work` deliberately is
not one (`tables.py` says so where it is declared): it carries its own
`lease_owner`, `lease_expires_at` and `next_attempt_at`, its own terminal
vocabulary including `partial` and `stale`, and a currency fence no `JobPlane`
has. Parameterising `run_worker` over a second lease protocol would have made
one function mean two things. `module-boundaries.md` section 5.5 gives
`infrastructure.jobs` "leases, attempts, retry state", which is what this is,
and section 5.10 leaves the process itself in `apps.worker`.

## The transaction discipline, and why it is three rather than one

1. **Claim, and commit.** The lease and the spent attempt have to be durable
   before the work runs. A loop that claimed inside the working transaction
   would roll the attempt back with the failure, and a work item that fails
   every time would be retried without bound -- which is the opposite of what
   `max_attempts` is for.
2. **Apply, and settle, in one transaction.** This is the half that cannot be
   split. `SqlReenrichmentWorkRepository.apply_claimed` re-reads the row
   `FOR UPDATE` against the *server's* `clock_timestamp()`, takes the
   Principal advisory lock, locks every current binding, assesses currency,
   runs the derived mutation inside a savepoint, re-assesses currency, and
   writes the terminal state -- all on one connection, which it verifies. A
   currency change discovered after the callback rolls the savepoint back, so a
   moved binding can never leave an untracked partial effect behind.
3. **Fail, alone.** An attempt that raised has already rolled its transaction
   back and has nothing left to write on, so the failure is recorded on a fresh
   transaction. `fail` matches on the lease owner, so a worker that lost its
   lease writes nothing and says so.

`GatewayRuntime.run_reenrichment_once` composes exactly these steps for a single
item, so there is one implementation of the protocol and not two.

## What the derived application actually does

v0.2 section 15.3 asks a merge to "invalidate cached summaries and context
packets". **There is no cache to invalidate at this head, and that is not an
omission.** `domain/relationship/context_card.py` states it in those words --
"the invalidation rule (there is no cache to invalidate)" -- a context card is
derived at request time, there are no materialized views, and
`knowledge.context_runs` is an immutable disclosure manifest rather than a
cache. So the requirement is discharged by *re-resolution*: the derived answer
is recomputed against the corrected identity graph, which is what invalidating a
cache would have been in aid of.

The one linkage this worker may recompute and rewrite is a mention whose entity
has been **merged away**. `entities` states the equivalence itself --
`(status = 'merged_redirect') = (superseded_by_entity_id IS NOT NULL)` -- so
following that pointer is deterministic lineage the operator already authorized
when they merged, not a new judgement about who somebody is. Everything else is
deliberately left alone and *reported* rather than done:

* an unresolved mention that the corrected graph could now place is a governed
  write this plane does not publish (`D-RI-21`), and
  `EntityResolutionService` is "a veto and not a licence" -- so the worker
  counts those mentions and settles `partial` with
  `NO_AUTONOMOUS_IDENTITY_MUTATION`, which is exactly what that limitation
  exists to say;
* a row whose `resolution_version` moved under the guarded update is one a
  governed decision is deciding right now, and the worker yields to it;
* the observation bound is a bound, and reaching it is reported as
  `BOUNDED_SUBJECT_SET`.

RI v0.2 section 27.5 line 1846 -- "partial processing never appears complete" --
is therefore load-bearing here rather than decorative: the settlement is
`succeeded` only when nothing was left undone.

**Idempotent, bounded, observable, safe to retry** (`AGENTS.md` section 6). A
second run finds no observation pointing at a merged-away entity, because the
first run pointed them at the survivor; every rewrite is guarded on the
`resolution_version` it read; the pass is `LIMIT`ed; and the run returns counts
which `apps/worker.py` prints.

**Nothing here logs and nothing here is disclosed.** The counts are counts. No
observed value, normalized value, display name or entity name leaves this
module.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Final

from sqlalchemy import Connection, Engine, and_, exists, func, or_, select

from my_pa.domain.relationship.entity import EntityStatus
from my_pa.domain.relationship.governance import ObservationState
from my_pa.domain.relationship.reenrichment import (
    ReenrichmentBinding,
    ReenrichmentLimitation,
    ReenrichmentWork,
)
from my_pa.infrastructure.persistence.entity_reenrichment import (
    DEFAULT_REENRICHMENT_LEASE_SECONDS,
    ReenrichmentTables,
    SqlCurrentReenrichmentBindings,
    SqlReenrichmentWorkRepository,
)
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    capture_context,
    partition_criterion,
)
from my_pa.infrastructure.persistence.tables import (
    entities,
    entity_aliases,
    entity_observations,
    entity_reenrichment_subjects,
    entity_reenrichment_version_watermarks,
    entity_reenrichment_work,
)

__all__ = [
    "DEFAULT_REENRICHMENT_POLL_SECONDS",
    "MAX_REBOUND_OBSERVATIONS",
    "DerivedResolution",
    "ReenrichmentRun",
    "claim_reenrichment_work",
    "reenrichment_tables",
    "resolve_derived_linkage",
    "run_reenrichment_worker",
    "settle_reenrichment_work",
    "work_partition",
]

#: How long an idle re-enrichment worker waits before looking again. The same
#: number `infrastructure.jobs.worker` uses, for the same reason, and waited on
#: the stop event so a signal does not wait it out.
DEFAULT_REENRICHMENT_POLL_SECONDS: Final = 5.0

#: The most observations one attempt rebinds. A bound rather than everything:
#: the whole pass runs inside the transaction that holds the work row and the
#: Principal advisory lock, so an unbounded pass would hold both for as long as
#: the backlog took. Reaching it is disclosed as `BOUNDED_SUBJECT_SET` and the
#: remainder is picked up by the next work item rather than dropped.
MAX_REBOUND_OBSERVATIONS: Final = 500

#: How far a chain of merges is followed before the worker gives up on it. A
#: merge redirect can point at an entity that was itself later merged away;
#: the schema forbids self-supersession but not a cycle across rows, so the
#: walk is bounded rather than trusted.
_MAX_LINEAGE_DEPTH: Final = 16


def reenrichment_tables() -> ReenrichmentTables:
    """The three declared tables, in the one place that names them."""
    return ReenrichmentTables(
        entity_reenrichment_work,
        entity_reenrichment_subjects,
        entity_reenrichment_version_watermarks,
    )


@dataclass(frozen=True, slots=True)
class DerivedResolution:
    """What one re-resolution pass did, and what it deliberately did not do.

    Counts only. `left_to_a_governed_decision` is the number of mentions the
    corrected graph could now place and this worker may not, which is the
    difference between a run that finished and a run that stopped short.
    """

    rebound: int = 0
    left_to_a_governed_decision: int = 0
    bound_reached: bool = False

    @property
    def limitations(self) -> tuple[ReenrichmentLimitation, ...]:
        """The closed, content-free limitations this pass settles under."""
        found: list[ReenrichmentLimitation] = []
        if self.left_to_a_governed_decision:
            found.append(ReenrichmentLimitation.NO_AUTONOMOUS_IDENTITY_MUTATION)
        if self.bound_reached:
            found.append(ReenrichmentLimitation.BOUNDED_SUBJECT_SET)
        return tuple(found)


@dataclass(frozen=True, slots=True)
class ReenrichmentRun:
    """What one run of the loop did. Counts and nothing else."""

    iterations: int = 0
    claimed: int = 0
    succeeded: int = 0
    partial: int = 0
    stale: int = 0
    failed: int = 0
    idle: int = 0
    rebound: int = 0


def work_partition(connection: Connection, work_id: str) -> str:
    """The Principal the stored work row is partitioned into.

    Read back from the row rather than taken off the in-memory
    `ReenrichmentBinding`, which is `persistence.jobs.job_principal`'s idiom and
    is chosen for the same reason: the partition every statement below is
    scoped to is then the one the leased row actually occupies, established by
    the server inside the transaction that is about to write, rather than a
    value carried in from anywhere else.
    """
    found = connection.execute(
        select(entity_reenrichment_work.c.principal_id).where(
            entity_reenrichment_work.c.work_id == work_id
        )
    ).scalar_one_or_none()
    if found is None:
        raise ValueError("re-enrichment work names no stored row")
    return str(found)


def resolve_derived_linkage(
    connection: Connection,
    *,
    principal_id: str,
    limit: int = MAX_REBOUND_OBSERVATIONS,
) -> DerivedResolution:
    """Re-resolve one Principal's mention/identity linkage. Bounded, guarded.

    Every statement reaches its partition through
    `persistence.principal_scope`, never through a comparison written here:
    `partition_criterion` resolves the column and the vocabulary from the table
    itself, so a neighbouring statement cannot forget the predicate or spell it
    differently. The pass is idempotent by construction -- a rebound
    observation no longer selects -- so it needs no digest to remember.
    """
    if limit < 1:
        raise ValueError("a re-resolution pass has a positive bound")
    context = capture_context(principal_id)

    # The merged-away entities of this partition, and then the observations of
    # this partition that point at one. Two scoped statements joined on
    # `entity_id` alone, rather than one join carrying a hand-written
    # owner-to-owner comparison: both sides are already constrained to the same
    # Principal, so the join cannot reach across partitions and nothing here
    # restates how a partition is spelled.
    merged_away = (
        select(
            entities.c.entity_id.label("merged_entity_id"),
            entities.c.superseded_by_entity_id,
        )
        .where(
            partition_criterion(entities, context),
            entities.c.superseded_by_entity_id.is_not(None),
        )
        .subquery()
    )
    candidates = connection.execute(
        select(
            entity_observations.c.observation_id,
            entity_observations.c.resolution_version,
            merged_away.c.superseded_by_entity_id,
        )
        .select_from(
            entity_observations.join(
                merged_away,
                merged_away.c.merged_entity_id == entity_observations.c.entity_id,
            )
        )
        .where(partition_criterion(entity_observations, context))
        .order_by(entity_observations.c.observation_id)
        .limit(limit + 1)
    ).all()
    bound_reached = len(candidates) > limit
    rebound = 0
    yielded = 0
    for candidate in candidates[:limit]:
        survivor = _current_survivor(
            connection,
            context=context,
            entity_id=str(candidate.superseded_by_entity_id),
        )
        if survivor is None:
            # The lineage does not end at a current entity within the bound.
            # Naming a non-current identity would be the false join the plane
            # refuses, so the row is left exactly as it is.
            yielded += 1
            continue
        updated = connection.execute(
            entity_observations.update()
            .where(
                # An UPDATE reaches the partition through the same function a
                # SELECT does, which is what `partition_criterion`'s own
                # docstring requires of a statement that can rewrite rows.
                partition_criterion(entity_observations, context),
                entity_observations.c.observation_id == candidate.observation_id,
                # The optimistic guard `plan_observations` deliberately left
                # open: a governed `decide_observation` running concurrently
                # advances this, and the rebinding is then refused rather than
                # applied over the top of somebody's conclusion.
                entity_observations.c.resolution_version == candidate.resolution_version,
            )
            .values(
                entity_id=survivor,
                resolution_version=entity_observations.c.resolution_version + 1,
            )
        )
        if updated.rowcount == 1:
            rebound += 1
        else:
            yielded += 1
    return DerivedResolution(
        rebound=rebound,
        left_to_a_governed_decision=yielded
        + _placeable_unresolved_mentions(connection, context=context, limit=limit),
        bound_reached=bound_reached,
    )


def _current_survivor(
    connection: Connection, *, context: PrincipalContext, entity_id: str
) -> str | None:
    """Follow a merge redirect to the entity that is current, or answer none."""
    seen: set[str] = set()
    at = entity_id
    for _ in range(_MAX_LINEAGE_DEPTH):
        if at in seen:
            return None
        seen.add(at)
        row = connection.execute(
            select(entities.c.status, entities.c.superseded_by_entity_id).where(
                partition_criterion(entities, context),
                entities.c.entity_id == at,
            )
        ).one_or_none()
        if row is None:
            return None
        if row.superseded_by_entity_id is None:
            return at if str(row.status) == EntityStatus.ACTIVE.value else None
        at = str(row.superseded_by_entity_id)
    return None


def _placeable_unresolved_mentions(
    connection: Connection, *, context: PrincipalContext, limit: int
) -> int:
    """How many unplaced mentions the corrected graph could now place.

    Counted and never acted on. Linking a mention to an entity is a governed
    write this plane publishes nothing for (`D-RI-21`), so a background worker
    that did it would hold an authority no caller has. The count is what makes
    the settlement truthful instead: it is the reason the run is `partial`.

    All three tables are scoped, including the two inside the `EXISTS`. A
    correlated subquery that named no partition would let another Principal's
    entity or alias decide whether this Principal's mention is placeable, which
    is a cross-partition read even though it returns only a count.
    """
    matched = or_(
        exists().where(
            and_(
                partition_criterion(entities, context),
                entities.c.status == EntityStatus.ACTIVE.value,
                entities.c.canonical_name == entity_observations.c.normalized_value,
            )
        ),
        exists().where(
            and_(
                partition_criterion(entity_aliases, context),
                entity_aliases.c.state == "active",
                entity_aliases.c.normalized_value == entity_observations.c.normalized_value,
            )
        ),
    )
    counted = connection.execute(
        select(func.count()).select_from(
            select(entity_observations.c.observation_id)
            .where(
                partition_criterion(entity_observations, context),
                entity_observations.c.entity_id.is_(None),
                entity_observations.c.state == ObservationState.CURRENT.value,
                matched,
            )
            .limit(limit)
            .subquery()
        )
    ).scalar_one()
    return int(counted)


def claim_reenrichment_work(
    engine: Engine,
    *,
    owner: str,
    at: datetime,
    lease_seconds: int = DEFAULT_REENRICHMENT_LEASE_SECONDS,
) -> ReenrichmentWork | None:
    """Transaction one: take the lease and spend the attempt, durably."""
    tables = reenrichment_tables()
    with engine.begin() as connection:
        return SqlReenrichmentWorkRepository(connection, tables).claim(
            owner=owner, at=at, lease_seconds=lease_seconds
        )


def settle_reenrichment_work(
    engine: Engine,
    work: ReenrichmentWork,
    *,
    owner: str,
    at: datetime,
    limit: int = MAX_REBOUND_OBSERVATIONS,
) -> tuple[str, DerivedResolution]:
    """Transaction two, and transaction three only when two raised.

    Returns the terminal state the item settled in and what the pass did. The
    derived mutation, the currency fence around it and the settlement are one
    transaction, which is what makes a moved binding discard the mutation
    rather than leave it behind.
    """
    tables = reenrichment_tables()
    outcome = DerivedResolution()

    def apply(binding: ReenrichmentBinding, digest: str) -> None:
        # The binding and its digest are the callback contract's, not this
        # pass's: the partition comes from the leased row and the idempotency
        # from the rows themselves.
        del binding, digest
        nonlocal outcome
        outcome = resolve_derived_linkage(connection, principal_id=principal_id, limit=limit)

    try:
        with engine.begin() as connection:
            principal_id = work_partition(connection, work.work_id)
            repository = SqlReenrichmentWorkRepository(connection, tables)
            # The repository's own `apply_claimed` rather than
            # `EntityReenrichmentService`'s: an infrastructure module does not
            # import `my_pa.application` (`AGENTS.md` section 4, proved by
            # `tests/architecture/test_dependency_direction.py`). Nothing is
            # lost by the directness -- the service's pre-checks on state,
            # owner and lease are re-run here against PostgreSQL's own
            # `clock_timestamp()`, which is the stronger fence of the two.
            currency = repository.apply_claimed(
                principal_id,
                work.work_id,
                owner=owner,
                current=SqlCurrentReenrichmentBindings(connection, tables),
                apply=apply,
                at=at,
            )
            if not currency.is_current:
                return "stale", DerivedResolution()
            limitations = outcome.limitations
            if not limitations:
                return "succeeded", outcome
            _correct_settlement_to_partial(
                connection,
                principal_id=principal_id,
                work_id=work.work_id,
                limitations=limitations,
            )
            return "partial", outcome
    except Exception:
        with engine.begin() as connection:
            SqlReenrichmentWorkRepository(connection, tables).fail(
                work_partition(connection, work.work_id),
                work.work_id,
                owner=owner,
                error_code="internal_error",
                retryable=True,
                at=at,
            )
        return "failed", DerivedResolution()


def _correct_settlement_to_partial(
    connection: Connection,
    *,
    principal_id: str,
    work_id: str,
    limitations: tuple[ReenrichmentLimitation, ...],
) -> None:
    """Turn the settlement `apply_claimed` just wrote into the truthful one.

    **Why the correction is here and not a repository method.** `apply_claimed`
    settles `succeeded` and only `succeeded`, because that is the one terminal
    state it can write while holding the currency fence, and it is the fence
    that has to own the settlement. The repository's `mark_partial` exists but
    requires the row to still be `running` and still hold the lease, which it
    does not once `apply_claimed` has returned. The right home for this is a
    `mark_partial` variant on `SqlReenrichmentWorkRepository`; that file is
    outside this change's write ownership, so the statement lives here.

    **It is not a race.** It runs on the same connection, inside the same
    transaction, while that transaction still holds the row's `FOR UPDATE` lock
    and the Principal advisory lock `apply_claimed` took. Nothing else can see
    the `succeeded` row: it has not been committed. The `WHERE` clause pins the
    exact row this transaction just settled, so a mismatched shape raises rather
    than silently rewriting somebody else's terminal state.
    """
    updated = connection.execute(
        entity_reenrichment_work.update()
        .where(
            partition_criterion(entity_reenrichment_work, capture_context(principal_id)),
            entity_reenrichment_work.c.work_id == work_id,
            entity_reenrichment_work.c.state == "succeeded",
            entity_reenrichment_work.c.completed_at.is_not(None),
        )
        .values(limitations=[item.value for item in limitations], state="partial")
    )
    if updated.rowcount != 1:  # pragma: no cover - the settlement above wrote this row
        raise RuntimeError("a settled re-enrichment result could not be corrected")


def run_reenrichment_worker(
    engine: Engine,
    *,
    owner: str,
    stop: threading.Event,
    max_iterations: int | None = None,
    lease_seconds: int = DEFAULT_REENRICHMENT_LEASE_SECONDS,
    poll_seconds: float = DEFAULT_REENRICHMENT_POLL_SECONDS,
    heartbeat: Callable[[], None] | None = None,
    now: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> ReenrichmentRun:
    """Claim and settle work until `stop` is set or `max_iterations` is reached.

    Bounded the same way `run_worker` is, and deliberately not interruptible in
    the middle of an item: a worker that dropped a claimed item on a signal
    would leave a lease held until it expired, which is the abandonment the
    shutdown exists to avoid. The bound on a stop is therefore one item, which
    the lease already bounds.
    """
    if not 1 <= lease_seconds <= 900:
        raise ValueError("lease_seconds must be between 1 and 900")
    if poll_seconds <= 0:
        raise ValueError("poll_seconds must be positive")
    if max_iterations is not None and max_iterations < 0:
        raise ValueError("max_iterations cannot be negative")

    bounded = max_iterations is not None
    iterations = claimed = succeeded = partial = stale = failed = idle = rebound = 0

    while not stop.is_set():
        if max_iterations is not None and iterations >= max_iterations:
            break
        iterations += 1
        if heartbeat is not None:
            heartbeat()

        moment = now()
        work = claim_reenrichment_work(engine, owner=owner, at=moment, lease_seconds=lease_seconds)
        if work is None:
            idle += 1
            if not bounded:
                stop.wait(poll_seconds)
            continue

        claimed += 1
        state, outcome = settle_reenrichment_work(engine, work, owner=owner, at=now())
        rebound += outcome.rebound
        match state:
            case "succeeded":
                succeeded += 1
            case "partial":
                partial += 1
            case "stale":
                stale += 1
            case _:
                failed += 1
        if heartbeat is not None:
            heartbeat()

    return ReenrichmentRun(
        iterations=iterations,
        claimed=claimed,
        succeeded=succeeded,
        partial=partial,
        stale=stale,
        failed=failed,
        idle=idle,
        rebound=rebound,
    )
