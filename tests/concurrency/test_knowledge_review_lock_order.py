"""KLP-WP-04 slice C: Knowledge Review lock order, real multi-session races (R6 section 8).

KLP-AC-036 (lock-order half), KLP-AC-038 (two decides), KLP-AC-099 (Review
order), KLP-AC-113, KLP-AC-122 (real 40P01 half), KLP-AC-153. Marked `database`
(auto `database_clone`), routed to `database-current-head`.

Every decision is a production `review.decide`, every submission a production
autonomous submit and every merge the production `entities.merge.preview` /
`entities.merge`, each through `ApplicationService.invoke` on its own thread
and connection. Pause points are locks a third "holder" session takes and
keeps (a proposal row, a C6 subject-lock row, a source-profile row, a merge
preview row, an Entity mutation-scope advisory key), never sleeps; each wait is
observed in `pg_stat_activity` before it is released.

* **Two decides, one case (KLP-AC-038)** -- both block (one at C5 behind the
  holder, the other at C3 behind the first); after release exactly one
  succeeds and the other answers `conflict(expected_review_version)`; one
  decision row, one assertion.
* **Merge vs decide / submit on one Entity (KLP-AC-113, AC-036)** -- the
  Knowledge path takes the Entity mutation scope (C3) before the proposal
  (C5); merge apply takes the same scope before reading Knowledge references.
  Whichever holds the scope first finishes; the other waits and then refuses
  (merge: blocker / stale preview; Knowledge: subject no longer canonical).
  No 40P01, no hang.
* **KLP-AC-122 (real half)** -- a genuine deadlock: a foreign session takes the
  proposal (the decide's C5) and then the Entity scope the waiting decide holds
  (C3). PostgreSQL aborts the decide (the holder's own `deadlock_timeout` is
  raised so the decide's check fires first); the service answers `conflict`
  with `retry = after_refresh` and writes nothing.
* **KLP-AC-153 (bounded)** -- proposal subject columns are trigger-immutable and
  a correction cannot name a subject, so the subject-key set cannot really
  change; the guard is proven by making the key derivation return a different
  set (a) before C6 and (b) after C6: each answers a retryable `conflict`, the
  C6 lock is never taken for the changed set, and nothing is written. This
  seam is labelled BOUNDED: no production interleaving reaches it.

Every identity here is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Final

import pytest
from sqlalchemy import Connection, Engine, select, text
from tests.concurrency.test_knowledge_assertion_concurrency import (
    commit_lock_row,
    hold_subject_lock,
)
from tests.concurrency.test_knowledge_shared_evidence_raise import (
    DEADLINE_SECONDS,
    _wait_for_waiters,
)
from tests.database.test_knowledge_assertion_repository import counts, new_principal
from tests.database.test_knowledge_assertion_review import (
    CLI,
    ReviewRuntime,
    _holder_and_case,
    _queued,
    assertion_count,
    assertion_of,
    decisions_of,
    proposal_of,
)
from tests.database.test_knowledge_assertion_submissions import LATER, PAYMENT, external

from my_pa.application.commands import MergeEntities, PreviewEntityMerge
from my_pa.domain.capture.review import Disposition
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeSubjectKind
from my_pa.infrastructure.persistence import knowledge_assertions as persistence
from my_pa.infrastructure.persistence.identifier_claim_lock import lock_entity_mutation_scopes
from my_pa.infrastructure.persistence.tables import (
    knowledge_assertion_mutations,
    knowledge_evidence_refs,
)

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

FINANCIAL: Final = "project.financial_fact"
REASON: Final = "Synthetic merge of two organizations"


@pytest.fixture
def review(disposable_database: str) -> Iterator[ReviewRuntime]:
    composed = ReviewRuntime(disposable_database, identity_correction=True)
    try:
        yield composed
    finally:
        composed.close()


def _hold_proposal(holder: Connection, case: str) -> None:
    holder.execute(
        text(
            "SELECT 1 FROM knowledge.knowledge_assertion_proposals WHERE review_case_id = :c "
            "FOR UPDATE"
        ),
        {"c": case},
    ).one()


def _decide_envelope(review: ReviewRuntime, principal: str, case: str, **kwargs: Any) -> Any:  # noqa: ANN401
    return review.invoke(
        review.decide_command(case, kwargs.pop("disposition", Disposition.ACCEPT), **kwargs),
        principal_id=principal,
        **CLI,
    )


# ---- KLP-AC-038: two concurrent decides on one case ------------------------------------


def test_two_concurrent_decides_yield_one_success_and_one_conflict(review: ReviewRuntime) -> None:
    principal, _entity, case = _queued(review)
    engine = review.engine
    with engine.connect() as holder:
        _hold_proposal(holder, case)
        with ThreadPoolExecutor(max_workers=2) as pool:
            one: Future[Any] = pool.submit(_decide_envelope, review, principal, case)
            _wait_for_waiters(engine, 1, one)
            two: Future[Any] = pool.submit(
                _decide_envelope, review, principal, case, disposition=Disposition.REJECT
            )
            _wait_for_waiters(engine, 2, one, two)
            holder.rollback()
            first = one.result(timeout=DEADLINE_SECONDS)
            second = two.result(timeout=DEADLINE_SECONDS)
    outcomes = sorted(
        "ok" if envelope.error is None else envelope.error.code.value
        for envelope in (first, second)
    )
    assert outcomes == ["conflict", "ok"]
    loser = first if first.error is not None else second
    assert loser.error.safe_details == ("expected_review_version",)
    assert loser.error.retry.value == "after_refresh"
    assert len(decisions_of(engine, case)) == 1
    assert proposal_of(engine, case)["state"] in {"accepted", "rejected"}


# ---- KLP-AC-113 / AC-036: merge vs decide and submit on one Entity ---------------------


def _preview(review: ReviewRuntime, principal: str, survivor: str, merged: str) -> dict[str, Any]:
    return review.ok(
        PreviewEntityMerge(
            survivor_entity_id=survivor,
            expected_survivor_version=1,
            merged_away=({"entity_id": merged, "expected_version": 1},),
            reason=REASON,
        ),
        principal_id=principal,
    )


def _merge_envelope(review: ReviewRuntime, principal: str, preview: dict[str, Any]) -> Any:  # noqa: ANN401
    return review.invoke(
        MergeEntities(
            preview_id=str(preview["preview_id"]),
            preview_digest=str(preview["preview_token"]),
            reason=REASON,
        ),
        principal_id=principal,
    )


def test_decide_holding_the_entity_scope_finishes_before_a_waiting_merge(
    review: ReviewRuntime,
) -> None:
    """Decide takes C3 then waits at C5; merge waits on C3; the decide wins, merge refuses."""
    principal, entity, case = _queued(review)
    other = review.org(principal, "globex")
    preview = _preview(review, principal, entity, other)
    assert [blocker["kind"] for blocker in preview["blockers"]] == ["knowledge_reference_present"]
    engine = review.engine
    with engine.connect() as holder:
        _hold_proposal(holder, case)
        with ThreadPoolExecutor(max_workers=2) as pool:
            decide: Future[Any] = pool.submit(_decide_envelope, review, principal, case)
            _wait_for_waiters(engine, 1, decide)
            merge: Future[Any] = pool.submit(_merge_envelope, review, principal, preview)
            _wait_for_waiters(engine, 2, decide, merge)
            holder.rollback()
            decided = decide.result(timeout=DEADLINE_SECONDS)
            merged = merge.result(timeout=DEADLINE_SECONDS)
    assert decided.error is None, decided.error
    assert merged.error is not None
    assert merged.error.code.value == "conflict"
    assert assertion_count(engine, principal) == 1


def test_a_submit_holding_the_entity_scope_makes_a_waiting_merge_refuse(
    review: ReviewRuntime,
) -> None:
    """A clean preview; submit takes C3 and waits at C4a; merge waits on C3, then is stale."""
    principal = new_principal()
    profile = review.profile(principal)
    survivor = review.org(principal, "acme")
    merged_away = review.org(principal, "globex")
    preview = _preview(review, principal, survivor, merged_away)
    assert preview["blockers"] == []
    engine = review.engine
    with engine.connect() as holder:
        holder.execute(
            text(
                "SELECT 1 FROM knowledge.knowledge_discovery_source_profiles "
                "WHERE source_profile_id = :p FOR NO KEY UPDATE"
            ),
            {"p": profile},
        ).one()
        with ThreadPoolExecutor(max_workers=2) as pool:
            submit: Future[Any] = pool.submit(
                review.submit, principal, profile, subject_id=merged_away, predicate=PAYMENT
            )
            _wait_for_waiters(engine, 1, submit)
            merge: Future[Any] = pool.submit(_merge_envelope, review, principal, preview)
            _wait_for_waiters(engine, 2, submit, merge)
            holder.rollback()
            submitted = submit.result(timeout=DEADLINE_SECONDS)
            merged = merge.result(timeout=DEADLINE_SECONDS)
    assert submitted["outcome"] == "review_queued", submitted
    assert merged.error is not None
    assert merged.error.code.value == "conflict"
    assert merged.error.safe_details == ("preview_stale",)


def test_a_merge_holding_the_entity_scope_makes_a_waiting_submit_refuse_the_subject(
    review: ReviewRuntime,
) -> None:
    """Merge locks the participants then waits on its preview row; submit waits on C3."""
    principal = new_principal()
    profile = review.profile(principal)
    survivor = review.org(principal, "acme")
    merged_away = review.org(principal, "globex")
    preview = _preview(review, principal, survivor, merged_away)
    engine = review.engine
    with engine.connect() as holder:
        holder.execute(
            text(
                "SELECT 1 FROM knowledge.entity_identity_previews WHERE preview_id = :p FOR UPDATE"
            ),
            {"p": preview["preview_id"]},
        ).one()
        with ThreadPoolExecutor(max_workers=2) as pool:
            merge: Future[Any] = pool.submit(_merge_envelope, review, principal, preview)
            _wait_for_waiters(engine, 1, merge)
            submit: Future[Any] = pool.submit(
                review.submit, principal, profile, subject_id=merged_away, predicate=PAYMENT
            )
            _wait_for_waiters(engine, 2, merge, submit)
            holder.rollback()
            merged = merge.result(timeout=DEADLINE_SECONDS)
            submitted = submit.result(timeout=DEADLINE_SECONDS)
    assert merged.error is None, merged.error
    assert submitted["outcome"] == "refused", submitted
    assert submitted["reason"] == "subject_not_canonical"


# ---- KLP-AC-122: a genuine 40P01 through the Knowledge decide port ------------------------


def test_a_real_deadlock_victim_decide_answers_a_retryable_conflict(review: ReviewRuntime) -> None:
    principal, entity, case = _queued(review)
    engine = review.engine
    with engine.connect() as holder:
        # The holder must never be the victim: its own deadlock check fires late.
        holder.execute(text("SET deadlock_timeout = '30s'"))
        _hold_proposal(holder, case)
        with ThreadPoolExecutor(max_workers=2) as pool:
            decide: Future[Any] = pool.submit(_decide_envelope, review, principal, case)
            # The decide holds C3 (the Entity scope) and waits at C5 on the holder.
            _wait_for_waiters(engine, 1, decide)
            closing: Future[None] = pool.submit(
                lambda: lock_entity_mutation_scopes(holder, principal, (entity,))
            )
            decided = decide.result(timeout=DEADLINE_SECONDS)
            closing.result(timeout=DEADLINE_SECONDS)
            holder.rollback()
    assert decided.error is not None
    assert decided.error.code.value == "conflict"
    assert decided.error.retry.value == "after_refresh"
    assert decisions_of(engine, case) == []
    assert assertion_count(engine, principal) == 0
    retried = _decide_envelope(review, principal, case)
    assert retried.error is None, retried.error


# ---- KLP-AC-153 (BOUNDED): a changed subject-key set is never late-locked -------------------


@pytest.mark.parametrize("changed_at_call", [2, 3], ids=["before_c6", "after_c6"])
def test_a_changed_subject_key_set_is_a_retryable_conflict_without_a_late_lock(
    review: ReviewRuntime, monkeypatch: pytest.MonkeyPatch, changed_at_call: int
) -> None:
    principal, _entity, case = _queued(review)
    original = persistence._ReviewDecision._subject_keys
    lock = persistence._ReviewDecision._lock_subjects
    calls: list[int] = []
    locked: list[frozenset[tuple[str, str, str]]] = []

    def keys(self: Any, proposal: Any) -> frozenset[tuple[str, str, str]]:  # noqa: ANN401
        calls.append(1)
        found = original(self, proposal)
        if len(calls) >= changed_at_call:
            return found | {("project", "prj_synthetic000000001", FINANCIAL)}
        return found

    def spy(self: Any, chosen: frozenset[tuple[str, str, str]]) -> None:  # noqa: ANN401
        locked.append(chosen)
        lock(self, chosen)

    monkeypatch.setattr(persistence._ReviewDecision, "_subject_keys", keys)
    monkeypatch.setattr(persistence._ReviewDecision, "_lock_subjects", spy)
    before = counts(review.engine, principal)
    envelope = _decide_envelope(review, principal, case)
    assert envelope.error is not None
    assert envelope.error.code.value == "conflict"
    assert envelope.error.retry.value == "after_refresh"
    # Never a lock on the changed set: before C6 nothing is locked; after C6 only
    # the set computed before the locks was.
    expected = [] if changed_at_call == 2 else [original(None, proposal_row(review, case))]
    assert locked == expected
    assert all(("project", "prj_synthetic000000001", FINANCIAL) not in chosen for chosen in locked)
    assert decisions_of(review.engine, case) == []
    assert counts(review.engine, principal) == before


def proposal_row(review: ReviewRuntime, case: str) -> Any:  # noqa: ANN401
    """The proposal as the key derivation reads it (attribute access)."""

    class _Row:
        def __init__(self, values: dict[str, Any]) -> None:
            self.__dict__.update(values)

    return _Row(proposal_of(review.engine, case))


# ---- KLP-AC-099: the Review path never waits on C3-C5 after C6 -----------------------------


def test_a_promotion_waiting_at_c6_holds_c5_and_a_second_waits_at_c5(
    review: ReviewRuntime,
) -> None:
    """Project subject (no C3): decide A holds C5 and waits at C6; decide B waits at C5.

    Nothing after C6 re-requests a C5 lock: releasing the C6 key lets A finish,
    then B gets C5 and conflicts. No 40P01.
    """
    principal = new_principal()
    profile = review.profile(principal)
    project = review.project(principal, "c6")
    queued = review.queue(
        principal,
        profile,
        project,
        predicate=FINANCIAL,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        value="Synthetic budget fact",
        evidence=(external("obj-c6"),),
    )
    case = str(queued["review_case_id"])
    commit_lock_row(review.engine, principal, "project", project, FINANCIAL)
    engine = review.engine
    with engine.connect() as holder:
        hold_subject_lock(holder, principal, "project", project, FINANCIAL)
        with ThreadPoolExecutor(max_workers=2) as pool:
            one: Future[Any] = pool.submit(_decide_envelope, review, principal, case)
            _wait_for_waiters(engine, 1, one)
            two: Future[Any] = pool.submit(_decide_envelope, review, principal, case)
            _wait_for_waiters(engine, 2, one, two)
            holder.rollback()
            first = one.result(timeout=DEADLINE_SECONDS)
            second = two.result(timeout=DEADLINE_SECONDS)
    assert first.error is None, first.error
    assert second.error is not None
    assert second.error.code.value == "conflict"
    assert second.error.safe_details == ("expected_review_version",)


# ---- Review supersession under C6 (fix rounds 4-5, DEV-66 rulings) ---------------------


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


def test_counterevidence_linked_while_a_decide_waits_at_c6_does_not_block_review(
    review: ReviewRuntime,
) -> None:
    """Fix round 5 ruling: Review has no counterevidence guard, even under a race.

    Modelled on test_knowledge_c4_order's holder-counterevidence node: a session
    takes the C6 subject lock of the live payment_terms holder and links
    counterevidence to it, pausing before COMMIT. An acceptance of a queued,
    ordered, not-future different-value proposal blocks on that C6 row (the
    waiting statement is the subject-lock `SELECT ... FOR UPDATE`, observed).
    After the commit the decide re-reads the holder under C6 and supersedes it:
    a contested holder is a reviewer's to replace.
    """
    principal, holder, case = _holder_and_case(review, successor_from=LATER, direct_successor=False)
    engine = review.engine
    with engine.connect() as connection:
        evidence = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id)
            .where(knowledge_evidence_refs.c.principal_id == principal)
            .order_by(knowledge_evidence_refs.c.evidence_ref_id)
            .limit(1)
        ).scalar_one()
        mutation = connection.execute(
            select(knowledge_assertion_mutations.c.mutation_id).where(
                knowledge_assertion_mutations.c.assertion_id == holder
            )
        ).scalar_one()
        subject_id = connection.execute(
            text("SELECT subject_id FROM knowledge.knowledge_assertions WHERE assertion_id = :a"),
            {"a": holder},
        ).scalar_one()
    locked = threading.Event()
    release = threading.Event()

    def link_counterevidence() -> None:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "SELECT 1 FROM knowledge.knowledge_assertion_subject_locks "
                    "WHERE principal_id = :p AND subject_kind = 'entity' AND subject_id = :s "
                    "AND predicate_code = :k FOR UPDATE"
                ),
                {"p": principal, "s": subject_id, "k": PAYMENT},
            ).all()
            connection.execute(
                text(
                    "INSERT INTO knowledge.knowledge_assertion_evidence_links (principal_id, "
                    "assertion_id, evidence_ref_id, evidence_role, linked_by_mutation_id, "
                    "created_at) VALUES (:p, :a, :e, 'counterevidence', :m, now())"
                ),
                {"p": principal, "a": holder, "e": evidence, "m": mutation},
            )
            locked.set()
            assert release.wait(DEADLINE_SECONDS), "never released"

    with ThreadPoolExecutor(max_workers=2) as pool:
        linker = pool.submit(link_counterevidence)
        assert locked.wait(DEADLINE_SECONDS)
        decide: Future[Any] = pool.submit(_decide_envelope, review, principal, case)
        _wait_for_waiters(engine, 1, decide)
        assert _waiting_on_subject_lock(engine) == 1
        release.set()
        linker.result(timeout=DEADLINE_SECONDS)
        envelope = decide.result(timeout=DEADLINE_SECONDS)
    assert envelope.error is None, envelope.error
    assert envelope.result is not None
    assert len(decisions_of(engine, case)) == 1
    successor = assertion_of(engine, envelope.result["assertion_id"])
    assert successor["supersedes_assertion_id"] == holder
    assert assertion_of(engine, holder)["lifecycle"] == "superseded"
