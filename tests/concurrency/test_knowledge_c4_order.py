"""KLP-WP-04: the C4b evidence order and the sibling-restriction race (real DB races).

KLP-AC-099 (C4b canonical order) and KLP-R6V-202 (sibling writer half). Marked
`database` (auto `database_clone`), routed to `database-current-head`.

* **Reversed citation order** -- two production submits cite the same two *new*
  evidence identities as {X, Y} and {Y, X}. A holder session keeps an
  uncommitted speculative insert of X, so both submits block on X (observed);
  on release both complete with no 40P01, and both link the same two canonical
  evidence rows. The upsert runs in canonical identity order (R6 5.1,
  KLP-R6V-002), so neither ever holds Y while waiting for X.
* **KLP-R6V-202** -- the source-classification ingress restricts external row E1
  and pauses before COMMIT; a submit citing a *new version* of the same object
  (sibling row E2) includes E1 in its one sorted C4b lock and blocks on it
  (observed). After the ingress commits, the submit recomputes the sibling max
  under the lock: E2 is `restricted_local` with its excerpt NULL
  (`excerpt_sha256` kept), the new assertion is `restricted_local`, and no
  40P01 is raised.
* **Availability under C4b** -- the availability ingress marks the cited
  external row E1 `permission_lost` and pauses before COMMIT; a submit citing E1
  (direct-admissible on the stale C2 read) blocks on E1 at C4b (observed).
  After the ingress commits, the submit re-reads the locked rows' availability
  and re-runs the admission policy: it ends `review_queued` (no assertion), never
  `direct_created` / `active` on a `permission_lost` row.
* **Holder counterevidence under C6** (KLP-AC-031, fix round 2) -- a session
  takes the C6 subject lock of a live `organization.payment_terms` holder and
  links counterevidence to it (what `_enrich` does after C6), pausing before
  COMMIT; a later direct-supersede candidate blocks on that C6 row (the waiting
  statement is the subject-lock `SELECT ... FOR UPDATE`, observed in
  `pg_stat_activity`). After the commit the submit re-derives the current fact
  under C6 and ends `review_queued`, the holder still `active`. The linking
  session takes no C3: every production link writer (create, submit `_enrich`,
  Review decide) takes C3 first for an Entity subject, and the only
  single_current predicate is Entity-only, so with today's registry the
  production race is serialised at C3 -- the next node drives that path.
* **Production enrich vs supersede** -- the production submit `_enrich` of the
  holder (citing new counterevidence) is paused after it linked, before COMMIT;
  the supersede candidate waits (at C3), then ends `review_queued`. This node
  proves the production serialisation; it is NOT a prove-red for the C6
  re-derivation (it stays green without it: the holder is read after C3).
"""

from __future__ import annotations

import hashlib
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from tests.concurrency.test_knowledge_shared_evidence_raise import (
    DEADLINE_SECONDS,
    WHEN,
    _wait_for_waiters,
)
from tests.database.test_knowledge_assertion_repository import capture_evidence, new_principal
from tests.database.test_knowledge_assertion_submissions import (
    EARLY,
    LATER,
    PAYMENT,
    SubmitRuntime,
    _payment,
    add_direct_payment_head,
    assertion,
    external,
)

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeEvidenceAvailability
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import knowledge_assertions as persistence
from my_pa.infrastructure.persistence.knowledge_assertions import KnowledgeMaintenanceResult
from my_pa.infrastructure.persistence.tables import (
    knowledge_assertions,
    knowledge_evidence_refs,
    knowledge_submission_evidence,
)
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[SubmitRuntime]:
    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _evidence_rows(engine: Engine, principal: str) -> list[dict[str, Any]]:
    e = knowledge_evidence_refs
    with engine.connect() as connection:
        return [
            dict(row)
            for row in connection.execute(
                select(e).where(e.c.principal_id == principal).order_by(e.c.evidence_ref_id)
            ).mappings()
        ]


def _cited(engine: Engine, submission_id: str) -> set[str]:
    s = knowledge_submission_evidence
    with engine.connect() as connection:
        return set(
            connection.execute(
                select(s.c.evidence_ref_id).where(s.c.submission_id == submission_id)
            ).scalars()
        )


def test_reversed_citation_orders_of_new_identities_never_deadlock(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    first_org, second_org = runtime.entity(principal, "c4-a"), runtime.entity(principal, "c4-b")
    captures = sorted([runtime.capture(principal, "c4-x"), runtime.capture(principal, "c4-y")])
    x, y = (capture_evidence(*capture, role="supporting") for capture in captures)
    engine = runtime.engine
    with engine.connect() as holder:
        # An uncommitted speculative insert of X (the canonical first identity).
        holder.execute(
            text(
                "INSERT INTO knowledge.knowledge_evidence_refs (principal_id, evidence_ref_id, "
                "identity_kind, capture_id, content_hash, content_origin, source_classification, "
                "created_at, updated_at) VALUES (:p, :e, 'capture', :c, :h, 'capture', "
                "'private_local', now(), now())"
            ),
            {
                "p": principal,
                "e": issue_identifier(IdKind.KNOWLEDGE_EVIDENCE_REF),
                "c": captures[0][0],
                "h": captures[0][1],
            },
        )
        with ThreadPoolExecutor(max_workers=2) as pool:
            forward = pool.submit(
                runtime.submit, principal, profile, subject_id=first_org, evidence=(x, y)
            )
            reverse = pool.submit(
                runtime.submit,
                principal,
                profile,
                subject_id=second_org,
                candidate="cand-2",
                evidence=(y, x),
            )
            _wait_for_waiters(engine, 2, forward, reverse)
            holder.rollback()
            one = forward.result(timeout=DEADLINE_SECONDS)
            two = reverse.result(timeout=DEADLINE_SECONDS)
    assert one["outcome"] == two["outcome"] == "review_queued"
    rows = _evidence_rows(engine, principal)
    assert len(rows) == 2
    canonical = {row["evidence_ref_id"] for row in rows}
    assert _cited(engine, one["submission_id"]) == canonical
    assert _cited(engine, two["submission_id"]) == canonical


def test_a_sibling_restricted_concurrently_is_waited_for_and_redacts_the_new_row(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    first_org, second_org = runtime.entity(principal, "202-a"), runtime.entity(principal, "202-b")
    first = runtime.submit(
        principal,
        profile,
        subject_id=first_org,
        evidence=(external("obj-sib", version="v1", excerpt="Synthetic v1 excerpt."),),
    )
    assert first["outcome"] == "direct_created"
    (e1,) = (row["evidence_ref_id"] for row in _evidence_rows(runtime.engine, principal))
    locked = threading.Event()
    release = threading.Event()

    def classify() -> KnowledgeMaintenanceResult:
        with knowledge_maintenance_transaction(runtime.engine) as repository:
            result = repository.classify_evidence_restricted(principal, e1, at=WHEN)
            locked.set()
            assert release.wait(DEADLINE_SECONDS), "never released"
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        maintenance = pool.submit(classify)
        assert locked.wait(DEADLINE_SECONDS)
        writer = pool.submit(
            runtime.submit,
            principal,
            profile,
            subject_id=second_org,
            candidate="cand-2",
            value="Another synthetic requirement",
            evidence=(external("obj-sib", version="v2", excerpt="Synthetic v2 excerpt."),),
        )
        _wait_for_waiters(runtime.engine, 1, writer)
        release.set()
        maintenance.result(timeout=DEADLINE_SECONDS)
        second = writer.result(timeout=DEADLINE_SECONDS)
    assert second["outcome"] == "direct_created", second
    rows = {row["external_version_id"]: row for row in _evidence_rows(runtime.engine, principal)}
    e2 = rows["v2"]
    assert e2["source_classification"] == "restricted_local"
    assert e2["excerpt"] is None
    assert e2["excerpt_sha256"] == hashlib.sha256(b"Synthetic v2 excerpt.").hexdigest()
    assert rows["v1"]["source_classification"] == "restricted_local"
    with runtime.engine.connect() as connection:
        classes = dict(
            connection.execute(
                select(
                    knowledge_assertions.c.assertion_id, knowledge_assertions.c.classification
                ).where(knowledge_assertions.c.principal_id == principal)
            ).all()
        )
    assert classes == {
        first["assertion_id"]: "restricted_local",
        second["assertion_id"]: "restricted_local",
    }


def test_availability_lost_while_waiting_at_c4b_is_decided_on_never_direct(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    first_org, second_org = runtime.entity(principal, "av-a"), runtime.entity(principal, "av-b")
    cited = external("obj-av", version="v1", excerpt="Synthetic availability excerpt.")
    first = runtime.submit(principal, profile, subject_id=first_org, evidence=(cited,))
    assert first["outcome"] == "direct_created"
    (e1,) = (row["evidence_ref_id"] for row in _evidence_rows(runtime.engine, principal))
    locked = threading.Event()
    release = threading.Event()

    def lose() -> KnowledgeMaintenanceResult:
        with knowledge_maintenance_transaction(runtime.engine) as repository:
            result = repository.record_evidence_availability(
                principal, e1, KnowledgeEvidenceAvailability.PERMISSION_LOST, at=WHEN
            )
            locked.set()
            assert release.wait(DEADLINE_SECONDS), "never released"
        return result

    with ThreadPoolExecutor(max_workers=2) as pool:
        maintenance = pool.submit(lose)
        assert locked.wait(DEADLINE_SECONDS)
        writer = pool.submit(
            runtime.submit,
            principal,
            profile,
            subject_id=second_org,
            candidate="cand-2",
            evidence=(cited,),
        )
        _wait_for_waiters(runtime.engine, 1, writer)
        release.set()
        maintenance.result(timeout=DEADLINE_SECONDS)
        second = writer.result(timeout=DEADLINE_SECONDS)
    assert second["outcome"] == "review_queued", second
    assert second.get("assertion_id") is None
    rows = _evidence_rows(runtime.engine, principal)
    assert [row["availability_state"] for row in rows] == ["permission_lost"]
    assert _cited(runtime.engine, second["submission_id"]) == {e1}
    with runtime.engine.connect() as connection:
        lifecycles = dict(
            connection.execute(
                select(knowledge_assertions.c.assertion_id, knowledge_assertions.c.lifecycle).where(
                    knowledge_assertions.c.principal_id == principal
                )
            ).all()
        )
    # Only the first assertion exists, and the ingress marked it for revalidation.
    assert lifecycles == {first["assertion_id"]: "revalidation_required"}


def _waiting_on_subject_lock(engine: Engine) -> int:
    with engine.connect() as observer:
        return int(
            observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity WHERE datname = current_database() "
                    "AND wait_event_type = 'Lock' AND pid <> pg_backend_pid() "
                    "AND query ILIKE '%knowledge_assertion_subject_locks%FOR UPDATE%'"
                )
            ).scalar_one()
        )


def _holder_evidence(engine: Engine, principal: str) -> str:
    with engine.connect() as connection:
        return str(
            connection.execute(
                select(knowledge_evidence_refs.c.evidence_ref_id).where(
                    knowledge_evidence_refs.c.principal_id == principal
                )
            ).scalar_one()
        )


def test_counterevidence_linked_to_the_holder_while_waiting_at_c6_blocks_supersession(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    add_direct_payment_head(runtime.engine)
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "c6-counter")
    first = _payment(runtime, principal, profile, org, "Net 30", "p", EARLY)
    assert first["outcome"] == "direct_created", first
    evidence = _holder_evidence(runtime.engine, principal)
    locked = threading.Event()
    release = threading.Event()

    def link_counterevidence() -> None:
        # What `_enrich` does once it holds C6: the subject lock, then the link.
        with runtime.engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT 1 FROM knowledge.knowledge_assertion_subject_locks "
                    "WHERE principal_id = :p AND subject_kind = 'entity' AND subject_id = :s "
                    "AND predicate_code = :k FOR UPDATE"
                ),
                {"p": principal, "s": org, "k": PAYMENT},
            ).all()
            connection.execute(
                text(
                    "INSERT INTO knowledge.knowledge_assertion_evidence_links (principal_id, "
                    "assertion_id, evidence_ref_id, evidence_role, linked_by_mutation_id, "
                    "created_at) VALUES (:p, :a, :e, 'counterevidence', :m, now())"
                ),
                {
                    "p": principal,
                    "a": first["assertion_id"],
                    "e": evidence,
                    "m": first["mutation_id"],
                },
            )
            locked.set()
            assert release.wait(DEADLINE_SECONDS), "never released"

    with ThreadPoolExecutor(max_workers=2) as pool:
        linker = pool.submit(link_counterevidence)
        assert locked.wait(DEADLINE_SECONDS)
        writer = pool.submit(_payment, runtime, principal, profile, org, "Net 90", "q", LATER)
        _wait_for_waiters(runtime.engine, 1, writer)
        assert _waiting_on_subject_lock(runtime.engine) == 1
        release.set()
        linker.result(timeout=DEADLINE_SECONDS)
        second = writer.result(timeout=DEADLINE_SECONDS)
    assert second["outcome"] == "review_queued", second
    assert assertion(runtime.engine, first["assertion_id"])["lifecycle"] == "active"


def test_a_production_enrich_with_counterevidence_serialises_the_supersession(
    runtime: SubmitRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    principal = new_principal()
    add_direct_payment_head(runtime.engine)
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "c3-counter")
    first = _payment(runtime, principal, profile, org, "Net 30", "p", EARLY)
    assert first["outcome"] == "direct_created", first
    linked = threading.Event()
    release = threading.Event()
    enrich = persistence._AutonomousSubmit._enrich

    def paused_enrich(self: Any, *args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        result = enrich(self, *args, **kwargs)
        linked.set()
        assert release.wait(DEADLINE_SECONDS), "never released"
        return result

    monkeypatch.setattr(persistence._AutonomousSubmit, "_enrich", paused_enrich)
    with ThreadPoolExecutor(max_workers=2) as pool:
        enricher = pool.submit(
            _payment,
            runtime,
            principal,
            profile,
            org,
            "Net 30",
            "e",
            EARLY,
            evidence=(external("inv-p"), external("contra-e", role="counterevidence")),
        )
        assert linked.wait(DEADLINE_SECONDS)
        writer = pool.submit(_payment, runtime, principal, profile, org, "Net 90", "q", LATER)
        _wait_for_waiters(runtime.engine, 1, writer)
        # Serialised before C6 (at C3), not on the subject lock.
        assert _waiting_on_subject_lock(runtime.engine) == 0
        release.set()
        enriched = enricher.result(timeout=DEADLINE_SECONDS)
        second = writer.result(timeout=DEADLINE_SECONDS)
    assert enriched["assertion_id"] == first["assertion_id"], enriched
    assert second["outcome"] == "review_queued", second
    assert assertion(runtime.engine, first["assertion_id"])["lifecycle"] == "active"
