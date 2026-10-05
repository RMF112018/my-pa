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
from tests.database.test_knowledge_assertion_submissions import SubmitRuntime, external

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeEvidenceAvailability
from my_pa.domain.source.registry import issue_identifier
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
