"""KLP-WP-04: a restriction racing a writer that links the same evidence (DB, real races).

KLP-AC-142, the maintenance half of KLP-AC-099 and the same-row half of
KLP-AC-152. Marked `database` (auto `database_clone`), routed to
`database-current-head`.

Two real sessions on one canonical (capture-kind) evidence row, in both orders.
The maintenance session is the production source-classification ingress
(`classify_evidence_restricted` inside `knowledge_maintenance_transaction`, the
transaction the operator command runs); the writer is a production explicit
create through `ApplicationService.invoke` that cites the same Capture version.
Pause points are held row locks, never sleeps, and each wait is observed in
`pg_stat_activity` before it is released:

* **maintenance first** -- the ingress holds the evidence row `FOR UPDATE` and
  pauses before COMMIT; the create blocks on that row; after COMMIT the create
  links the now-restricted row and stores `restricted_local` itself.
* **writer first** -- a third session holds the create's C6 subject lock, so the
  create pauses holding its C4b `FOR SHARE` on the evidence row; the ingress
  then blocks on `FOR UPDATE`; on release the create commits and the ingress
  classifies the newly linked assertion in the same run.

Neither order raises 40P01 (a deadlock would fail the test, not be retried),
and every assertion linked to the row ends `restricted_local`.

**Deferred to slice B2 (bounded, unproven here):** the KLP-R6V-202 *sibling*
half -- `classify-evidence` on E1 paused before COMMIT vs a *submit* inserting a
sibling external row E2 -- needs the autonomous submit writer, which slice B2
lands. The classify side already raises and redacts every existing sibling in
the same sorted C4b set (`tests/database/test_knowledge_classification_monotonicity.py`).
"""

from __future__ import annotations

import threading
import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, select, text
from tests.database.test_knowledge_assertion_repository import (
    POLICY,
    KnowledgeRuntime,
    capture_evidence,
    new_principal,
)

from my_pa.infrastructure.persistence.knowledge_assertions import KnowledgeMaintenanceResult
from my_pa.infrastructure.persistence.tables import knowledge_assertions, knowledge_evidence_refs
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

WHEN: Final = datetime(2026, 10, 5, 12, tzinfo=UTC)
DEADLINE_SECONDS: Final = 20.0


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[KnowledgeRuntime]:
    composed = KnowledgeRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _wait_for_waiters(engine: Engine, count: int, *futures: Future[Any]) -> None:
    """Return once `count` other backends of this database wait on a lock."""
    deadline = time.monotonic() + DEADLINE_SECONDS
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            for future in futures:
                if future.done():
                    future.result()  # surface the failure
                    pytest.fail("a session finished instead of waiting on the lock")
            waiting = observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
            observer.rollback()
            if waiting >= count:
                return
            time.sleep(0.05)
    pytest.fail(f"{count} session(s) never blocked")


def _seed(runtime: KnowledgeRuntime, key: str) -> tuple[str, tuple[str, str], str, str]:
    """A principal, a capture, one assertion citing it, and the canonical evidence row."""
    principal = new_principal()
    capture = runtime.capture(principal, key)
    first = runtime.create(principal, f"klp04-{key}-first", evidence=(capture_evidence(*capture),))
    with runtime.engine.connect() as connection:
        evidence = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal
            )
        ).scalar_one()
    return principal, capture, first["assertion_id"], evidence


def _create(runtime: KnowledgeRuntime, principal: str, capture: tuple[str, str], key: str) -> str:
    created = runtime.create(
        principal,
        f"klp04-{key}-second",
        value=f"Synthetic racing requirement {key}",
        evidence=(capture_evidence(*capture),),
    )
    assert created["outcome"] == "direct_created", created
    return str(created["assertion_id"])


def _classes(engine: Engine, principal: str) -> dict[str, str]:
    a = knowledge_assertions
    with engine.connect() as connection:
        return {
            row.assertion_id: row.classification
            for row in connection.execute(
                select(a.c.assertion_id, a.c.classification).where(a.c.principal_id == principal)
            )
        }


def _evidence_class(engine: Engine, evidence: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                select(knowledge_evidence_refs.c.source_classification).where(
                    knowledge_evidence_refs.c.evidence_ref_id == evidence
                )
            ).scalar_one()
        )


def test_maintenance_first_the_linker_waits_and_links_the_restricted_row(
    runtime: KnowledgeRuntime,
) -> None:
    principal, capture, first, evidence = _seed(runtime, "raise-first")
    locked = threading.Event()
    release = threading.Event()

    def classify() -> KnowledgeMaintenanceResult:
        with knowledge_maintenance_transaction(runtime.engine) as repository:
            result = repository.classify_evidence_restricted(principal, evidence, at=WHEN)
            locked.set()
            assert release.wait(DEADLINE_SECONDS), "never released"
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        maintenance = pool.submit(classify)
        assert locked.wait(DEADLINE_SECONDS)
        writer = pool.submit(_create, runtime, principal, capture, "raise-first")
        _wait_for_waiters(runtime.engine, 1, writer)
        release.set()
        result = maintenance.result(timeout=DEADLINE_SECONDS)
        second = writer.result(timeout=DEADLINE_SECONDS)

    assert result.mutated_assertion_ids == (first,)
    assert result.remaining == 0
    assert _evidence_class(runtime.engine, evidence) == "restricted_local"
    assert _classes(runtime.engine, principal) == {
        first: "restricted_local",
        second: "restricted_local",
    }


def test_writer_first_the_ingress_waits_and_classifies_the_new_link(
    runtime: KnowledgeRuntime,
) -> None:
    principal, capture, first, evidence = _seed(runtime, "link-first")
    engine = runtime.engine
    key = {"p": principal, "k": "principal", "s": principal, "c": POLICY}
    with engine.connect() as holder:
        holder.execute(
            text(
                "SELECT 1 FROM knowledge.knowledge_assertion_subject_locks WHERE principal_id = :p "
                "AND subject_kind = :k AND subject_id = :s AND predicate_code = :c FOR UPDATE"
            ),
            key,
        ).one()

        def classify() -> KnowledgeMaintenanceResult:
            with knowledge_maintenance_transaction(engine) as repository:
                return repository.classify_evidence_restricted(principal, evidence, at=WHEN)

        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(_create, runtime, principal, capture, "link-first")
            # The create holds its C4b FOR SHARE and waits on the held C6 key.
            _wait_for_waiters(engine, 1, writer)
            maintenance = pool.submit(classify)
            # The ingress now waits on FOR UPDATE behind the create's FOR SHARE.
            _wait_for_waiters(engine, 2, writer, maintenance)
            holder.rollback()
            second = writer.result(timeout=DEADLINE_SECONDS)
            result = maintenance.result(timeout=DEADLINE_SECONDS)

    assert sorted(result.mutated_assertion_ids) == sorted([first, second])
    assert result.remaining == 0
    assert _evidence_class(engine, evidence) == "restricted_local"
    assert set(_classes(engine, principal).values()) == {"restricted_local"}
