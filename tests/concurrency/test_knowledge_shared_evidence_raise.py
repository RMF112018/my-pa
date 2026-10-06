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

**KLP-WP-04 slice B2 adds the submit half (KLP-AC-152):** the same two orders
with a production autonomous submit as the linker of one external evidence row;
a later submit re-citing the identity creates no second row; and a new row for
an already-restricted object -- through a second profile of the same origin
system -- is born `restricted_local` with its excerpt NULL. The KLP-R6V-202
*sibling* race (a new version written while the ingress is paused) is
`tests/concurrency/test_knowledge_c4_order.py`.

**Fix round 3 (KLP-R6V-202 option A, the writer-first sibling order):** a
production submit inserts a new version E2 of the object and pauses after its
C4b (holding E1 `FOR UPDATE` and its own uncommitted E2); the ingress
classifying E1 blocks on E1 (observed). After the submit commits, the ingress
re-reads the sibling set under its lock, sees E2, restarts its C4b savepoint
over {E1, E2} in sorted order, and raises+redacts both in its one UPDATE: E2
ends `restricted_local` with its excerpt NULL, both linked assertions are
classified in the same run and `remaining` is 0. No 40P01.
A grown part of the set may sort below rows already held, so it is locked
`NOWAIT`: when another transaction holds the new sibling, the ingress fails
fast with a retryable conflict (never waits holding an out-of-order lock, so
never deadlocks) and the operator command restarts the transaction, whose first
read carries the larger set in sorted order -- proven end to end through
`run_knowledge_source_profiles classify-evidence`.
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

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import knowledge_assertions as persistence
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


# ---- KLP-WP-04 slice B2: the submit half (KLP-AC-152) -----------------------------------


@pytest.fixture
def submitter(disposable_database: str) -> Iterator[Any]:
    from tests.database.test_knowledge_assertion_submissions import SubmitRuntime

    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _external_row(engine: Engine, principal: str, version: str = "v1") -> dict[str, Any]:
    e = knowledge_evidence_refs
    with engine.connect() as connection:
        return dict(
            connection.execute(
                select(e).where(e.c.principal_id == principal, e.c.external_version_id == version)
            )
            .mappings()
            .one()
        )


def _seed_submit(submitter: Any, key: str) -> tuple[str, str, str, str]:  # noqa: ANN401
    from tests.database.test_knowledge_assertion_submissions import external

    principal = new_principal()
    profile = submitter.profile(principal)
    org = submitter.entity(principal, f"{key}-first")
    first = submitter.submit(
        principal, profile, subject_id=org, evidence=(external("obj-shared", excerpt="Shared."),)
    )
    assert first["outcome"] == "direct_created"
    return (
        principal,
        profile,
        first["assertion_id"],
        _external_row(submitter.engine, principal)["evidence_ref_id"],
    )


def _link_submit(submitter: Any, principal: str, profile: str, key: str) -> str:  # noqa: ANN401
    from tests.database.test_knowledge_assertion_submissions import external

    org = submitter.entity(principal, f"{key}-second")
    result = submitter.submit(
        principal,
        profile,
        subject_id=org,
        candidate=f"cand-{key}",
        value=f"Synthetic linked requirement {key}",
        evidence=(external("obj-shared", excerpt="Shared."),),
    )
    assert result["outcome"] == "direct_created", result
    return str(result["assertion_id"])


def test_submit_maintenance_first_the_linker_waits_and_links_the_restricted_row(
    submitter: Any,  # noqa: ANN401
) -> None:
    principal, profile, first, evidence = _seed_submit(submitter, "s-raise-first")
    locked = threading.Event()
    release = threading.Event()

    def classify() -> KnowledgeMaintenanceResult:
        with knowledge_maintenance_transaction(submitter.engine) as repository:
            result = repository.classify_evidence_restricted(principal, evidence, at=WHEN)
            locked.set()
            assert release.wait(DEADLINE_SECONDS), "never released"
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        maintenance = pool.submit(classify)
        assert locked.wait(DEADLINE_SECONDS)
        writer = pool.submit(_link_submit, submitter, principal, profile, "s-raise-first")
        _wait_for_waiters(submitter.engine, 1, writer)
        release.set()
        result = maintenance.result(timeout=DEADLINE_SECONDS)
        second = writer.result(timeout=DEADLINE_SECONDS)
    assert result.mutated_assertion_ids == (first,)
    assert _evidence_class(submitter.engine, evidence) == "restricted_local"
    assert _classes(submitter.engine, principal) == {
        first: "restricted_local",
        second: "restricted_local",
    }
    # Re-citing the identity creates no second evidence row.
    _link_submit(submitter, principal, profile, "s-raise-again")
    with submitter.engine.connect() as connection:
        rows = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal
            )
        ).all()
    assert len(rows) == 1


def test_submit_writer_first_the_ingress_waits_and_classifies_the_new_link(
    submitter: Any,  # noqa: ANN401
) -> None:
    principal, profile, first, evidence = _seed_submit(submitter, "s-link-first")
    engine = submitter.engine
    org = submitter.entity(principal, "s-link-first-held")
    from tests.concurrency.test_knowledge_assertion_concurrency import hold_subject_lock
    from tests.database.test_knowledge_assertion_submissions import OPERATING, external

    with engine.connect() as holder:
        hold_subject_lock(holder, principal, "entity", org, OPERATING)
        holder.commit()
        hold_subject_lock(holder, principal, "entity", org, OPERATING)

        def classify() -> KnowledgeMaintenanceResult:
            with knowledge_maintenance_transaction(engine) as repository:
                return repository.classify_evidence_restricted(principal, evidence, at=WHEN)

        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(
                submitter.submit,
                principal,
                profile,
                subject_id=org,
                candidate="cand-held",
                value="Synthetic held requirement",
                evidence=(external("obj-shared", excerpt="Shared."),),
            )
            # The submit holds its C4b lock on the shared row and waits at C6.
            _wait_for_waiters(engine, 1, writer)
            maintenance = pool.submit(classify)
            _wait_for_waiters(engine, 2, writer, maintenance)
            holder.rollback()
            second = writer.result(timeout=DEADLINE_SECONDS)
            result = maintenance.result(timeout=DEADLINE_SECONDS)
    assert second["outcome"] == "direct_created"
    assert sorted(result.mutated_assertion_ids) == sorted([first, second["assertion_id"]])
    assert set(_classes(engine, principal).values()) == {"restricted_local"}


def test_a_new_row_for_an_object_restricted_under_another_profile_is_born_restricted(
    submitter: Any,  # noqa: ANN401
) -> None:
    from tests.database.test_knowledge_assertion_submissions import external

    principal, _profile, _first, evidence = _seed_submit(submitter, "s-cross")
    with knowledge_maintenance_transaction(submitter.engine) as repository:
        repository.classify_evidence_restricted(principal, evidence, at=WHEN)
    other_profile = submitter.profile(principal, scope="scope-b")
    org = submitter.entity(principal, "s-cross-other")
    result = submitter.submit(
        principal,
        other_profile,
        subject_id=org,
        evidence=(external("obj-shared", excerpt="Cross-profile excerpt."),),
    )
    assert result["outcome"] == "direct_created"
    e = knowledge_evidence_refs
    with submitter.engine.connect() as connection:
        row = (
            connection.execute(
                select(e).where(
                    e.c.principal_id == principal, e.c.source_profile_id == other_profile
                )
            )
            .mappings()
            .one()
        )
    assert row["source_classification"] == "restricted_local"
    assert row["excerpt"] is None
    assert row["excerpt_sha256"] is not None
    assert _classes(submitter.engine, principal)[result["assertion_id"]] == "restricted_local"


def test_a_sibling_inserted_by_a_paused_submit_is_raised_by_the_waiting_ingress(
    submitter: Any,  # noqa: ANN401
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.database.test_knowledge_assertion_submissions import external

    principal, profile, first_assertion, e1 = _seed_submit(submitter, "sib-writer")
    org = submitter.entity(principal, "sib-writer-second")
    resolve = persistence._AutonomousSubmit._resolve_evidence
    locked = threading.Event()
    release = threading.Event()

    def paused(self: Any, product: Any) -> Any:  # noqa: ANN401
        result = resolve(self, product)
        locked.set()
        assert release.wait(DEADLINE_SECONDS), "never released"
        return result

    monkeypatch.setattr(persistence._AutonomousSubmit, "_resolve_evidence", paused)

    def classify() -> KnowledgeMaintenanceResult:
        with knowledge_maintenance_transaction(submitter.engine) as repository:
            return repository.classify_evidence_restricted(principal, e1, at=WHEN)

    with ThreadPoolExecutor(max_workers=2) as pool:
        writer = pool.submit(
            submitter.submit,
            principal,
            profile,
            subject_id=org,
            candidate="cand-2",
            value="Another synthetic requirement",
            evidence=(external("obj-shared", version="v2", excerpt="Synthetic v2."),),
        )
        assert locked.wait(DEADLINE_SECONDS)
        maintenance = pool.submit(classify)
        _wait_for_waiters(submitter.engine, 1, maintenance)
        release.set()
        second = writer.result(timeout=DEADLINE_SECONDS)
        result = maintenance.result(timeout=DEADLINE_SECONDS)
    assert second["outcome"] == "direct_created", second
    e2 = _external_row(submitter.engine, principal, "v2")
    assert e2["source_classification"] == "restricted_local"
    assert e2["excerpt"] is None
    assert _external_row(submitter.engine, principal)["source_classification"] == (
        "restricted_local"
    )
    assert set(result.evidence_ref_ids) == {e1, e2["evidence_ref_id"]}
    assert set(result.mutated_assertion_ids) == {first_assertion, second["assertion_id"]}
    assert result.remaining == 0
    assert _classes(submitter.engine, principal) == {
        first_assertion: "restricted_local",
        second["assertion_id"]: "restricted_local",
    }


def test_a_held_new_sibling_restarts_the_classify_command_in_sorted_order(
    submitter: Any,  # noqa: ANN401
) -> None:
    from tests.database.test_knowledge_source_profiles import run_cli

    principal, _profile, first_assertion, e1 = _seed_submit(submitter, "sib-held")
    engine = submitter.engine
    e = knowledge_evidence_refs
    row = _external_row(engine, principal)
    e2 = issue_identifier(IdKind.KNOWLEDGE_EVIDENCE_REF)
    with engine.connect() as holder, engine.connect() as sharer:
        # X: holds the named row, so the command's first C4b waits on it.
        holder.execute(
            select(e.c.evidence_ref_id).where(e.c.evidence_ref_id == e1).with_for_update()
        ).all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            command = pool.submit(
                run_cli,
                engine,
                principal,
                "classify-evidence",
                "--evidence-ref",
                e1,
                "--classification",
                "restricted_local",
            )
            _wait_for_waiters(engine, 1, command)
            # A new version of the object commits while the command waits ...
            with engine.begin() as writer:
                writer.execute(
                    e.insert().values(
                        {
                            **row,
                            "evidence_ref_id": e2,
                            "external_version_id": "v2",
                            "content_hash": "f" * 64,
                        }
                    )
                )
            # ... and W holds it (a reader of the new row).
            sharer.execute(
                select(e.c.evidence_ref_id)
                .where(e.c.evidence_ref_id == e2)
                .with_for_update(read=True)
            ).all()
            sharer_pid = sharer.execute(text("SELECT pg_backend_pid()")).scalar_one()
            holder.rollback()
            # Attempt 1 re-reads {E1, E2}, cannot take E2 NOWAIT, rolls back; the
            # restart locks the sorted set from the start and waits on W.
            deadline = time.monotonic() + DEADLINE_SECONDS
            with engine.connect() as observer:
                while True:
                    blocked = observer.execute(
                        text(
                            "SELECT count(*) FROM pg_stat_activity "
                            "WHERE :w = ANY(pg_blocking_pids(pid))"
                        ),
                        {"w": sharer_pid},
                    ).scalar_one()
                    observer.rollback()
                    if blocked:
                        break
                    assert not command.done(), command.result()
                    assert time.monotonic() < deadline, "the restart never waited on W"
                    time.sleep(0.05)
            sharer.rollback()
            code, lines = command.result(timeout=DEADLINE_SECONDS)
    assert code == 0, lines
    restricted = _external_row(engine, principal, "v2")
    assert restricted["source_classification"] == "restricted_local"
    assert restricted["excerpt"] is None
    assert _evidence_class(engine, e1) == "restricted_local"
    assert _classes(engine, principal) == {first_assertion: "restricted_local"}
