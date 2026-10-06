"""KLP-WP-04: concurrent duplicates and race 14 (real multi-session DB races).

KLP-AC-027, KLP-AC-151 and the carried WP-03 follow-up N3. Marked `database`
(auto `database_clone`), routed to `database-current-head`.

Every write is a production create/submit through `ApplicationService.invoke`
on its own thread and connection. Pause points are held row locks taken by a
third "holder" session (the C6 subject-lock row, or the C5 proposal row), never
sleeps; each wait is observed in `pg_stat_activity` before it is released.

* **N3 / same key** -- two creates (and two submits) of the same key and
  candidate race: the first holds its reservation while paused at C6, the
  second waits on the reservation's speculative insert; after release one
  completes and the other replays the identical stored result.
* **KLP-AC-027 / different keys** -- two submits of the same fact under two
  candidate ids both pass C2 and wait at C6: the first creates; the second sees
  the live duplicate appear under its lock, answers a retryable `conflict` and
  rolls back whole; its retry is `duplicate_existing`. One live assertion.
* **KLP-AC-151** -- an equivalent open proposal yields `duplicate_pending_review`
  and the older proposal is unchanged; race 14 (a): the proposal becomes
  terminal while the submit waits at C5 -- `accepted` -> the live assertion is
  enriched (`duplicate_enriched`), `rejected` -> a new proposal
  (`review_queued`), the old one unchanged; race 14 (b): an equivalent proposal
  first seen after C6 -> retryable `conflict`, nothing written, retry
  `duplicate_pending_review`.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Final

import pytest
from sqlalchemy import Connection, Engine, select, text
from tests.concurrency.test_knowledge_shared_evidence_raise import (
    DEADLINE_SECONDS,
    _wait_for_waiters,
)
from tests.database.test_knowledge_assertion_repository import (
    POLICY,
    counts,
    create_command,
    new_principal,
)
from tests.database.test_knowledge_assertion_submissions import (
    CLIENT,
    OPERATING,
    PAYMENT,
    SUBMIT_GRANTS,
    SubmitRuntime,
    external,
    live_assertions,
)

from my_pa.application.commands import DecideReviewCase
from my_pa.domain.capture.review import Disposition
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeSubjectKind
from my_pa.infrastructure.persistence.tables import knowledge_assertion_proposals

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

ENTITY: Final = "entity"
FINANCIAL: Final = "project.financial_fact"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[SubmitRuntime]:
    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def hold_subject_lock(
    holder: Connection, principal: str, subject_kind: str, subject_id: str, predicate: str
) -> None:
    """Upsert and hold one C6 key `FOR UPDATE` on the holder's open transaction."""
    holder.execute(
        text(
            "INSERT INTO knowledge.knowledge_assertion_subject_locks (principal_id, subject_kind, "
            "subject_id, predicate_code) VALUES (:p, :k, :s, :c) ON CONFLICT DO NOTHING"
        ),
        {"p": principal, "k": subject_kind, "s": subject_id, "c": predicate},
    )
    holder.execute(
        text(
            "SELECT 1 FROM knowledge.knowledge_assertion_subject_locks WHERE principal_id = :p "
            "AND subject_kind = :k AND subject_id = :s AND predicate_code = :c FOR UPDATE"
        ),
        {"p": principal, "k": subject_kind, "s": subject_id, "c": predicate},
    ).one()


def commit_lock_row(
    engine: Engine, principal: str, kind: str, subject: str, predicate: str
) -> None:
    """Make the C6 key exist (committed), so the holder's lock is a plain row lock."""
    with engine.begin() as connection:
        hold_subject_lock(connection, principal, kind, subject, predicate)


def race(
    engine: Engine,
    hold: Callable[[Connection], None],
    first: Callable[[], Any],
    second: Callable[[], Any],
    *,
    waiters: int = 2,
    release: Callable[[Connection], None] | None = None,
) -> tuple[Any, Any]:
    """Hold, start both (first, then second), observe `waiters`, release, collect."""
    with engine.connect() as holder:
        hold(holder)
        with ThreadPoolExecutor(max_workers=2) as pool:
            one: Future[Any] = pool.submit(first)
            _wait_for_waiters(engine, 1, one)
            two: Future[Any] = pool.submit(second)
            _wait_for_waiters(engine, waiters, one, two)
            if release is None:
                holder.rollback()
            else:
                release(holder)
            return one.result(timeout=DEADLINE_SECONDS), two.result(timeout=DEADLINE_SECONDS)


def _remote() -> dict[str, Any]:
    return {
        "transport": CaptureTransport.REMOTE_CLIENT,
        "grants": SUBMIT_GRANTS,
        "client_id": CLIENT,
    }


def submit_envelope(
    runtime: SubmitRuntime,
    principal: str,
    profile: str,
    **fields: Any,  # noqa: ANN401 - the submit_command keywords
) -> Any:  # noqa: ANN401 - a ResponseEnvelope
    """The raw envelope of one submit (a conflict is an answer, not a failure here)."""
    return runtime.invoke(
        runtime.submit_command(principal, profile, **fields),
        principal_id=principal,
        **_remote(),
    )


# ---- N3: the same key / candidate ----------------------------------------------------


def test_two_creates_of_one_key_complete_once_and_replay(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    commit_lock_row(runtime.engine, principal, "principal", principal, POLICY)

    def create() -> dict[str, Any]:
        return runtime.ok(create_command("klp04-n3", subject_id=principal), principal_id=principal)

    one, two = race(
        runtime.engine,
        lambda holder: hold_subject_lock(holder, principal, "principal", principal, POLICY),
        create,
        create,
    )
    assert one == two
    assert one["outcome"] == "direct_created"
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 1


def test_two_submits_of_one_candidate_complete_once_and_replay(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "n3")
    commit_lock_row(runtime.engine, principal, ENTITY, org, OPERATING)

    def submit() -> dict[str, Any]:
        return runtime.submit(principal, profile, subject_id=org)

    one, two = race(
        runtime.engine,
        lambda holder: hold_subject_lock(holder, principal, ENTITY, org, OPERATING),
        submit,
        submit,
    )
    assert one == two
    assert one["outcome"] == "direct_created"
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 1


# ---- KLP-AC-027: one fact, two keys ----------------------------------------------------


def test_one_fact_under_two_candidates_leaves_one_live_assertion(runtime: SubmitRuntime) -> None:
    """Same fact, two candidate ids, concurrently: never two live assertions.

    The first submit pauses at C6 holding the subject's C3 Entity scope, so the
    second waits at C3 (observed), reads the committed assertion after release
    and completes `duplicate_existing` -- the Entity scope serializes them
    before C6. (A non-Entity subject reaches the under-C6 re-check instead:
    race 14 (b) below proves that branch's retryable conflict.)
    """
    principal = new_principal()
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "fact")
    commit_lock_row(runtime.engine, principal, ENTITY, org, OPERATING)
    one, two = race(
        runtime.engine,
        lambda holder: hold_subject_lock(holder, principal, ENTITY, org, OPERATING),
        lambda: submit_envelope(runtime, principal, profile, subject_id=org, candidate="a"),
        lambda: submit_envelope(
            runtime,
            principal,
            profile,
            subject_id=org,
            candidate="b",
            value="  Synthetic   operating requirement ",
        ),
    )
    assert one.error is None and one.result["outcome"] == "direct_created"
    assert two.error is None and two.result["outcome"] == "duplicate_existing"
    assert two.result["assertion_id"] == one.result["assertion_id"]
    assert len(live_assertions(runtime.engine, principal, OPERATING)) == 1


# ---- KLP-AC-151 / race 14 ---------------------------------------------------------------


def _proposal(engine: Engine, proposal_id: str) -> dict[str, Any]:
    with engine.connect() as connection:
        return dict(
            connection.execute(
                select(knowledge_assertion_proposals).where(
                    knowledge_assertion_proposals.c.proposal_id == proposal_id
                )
            )
            .mappings()
            .one()
        )


def _queue(runtime: SubmitRuntime, principal: str, profile: str, org: str) -> dict[str, Any]:
    queued = runtime.submit(principal, profile, subject_id=org, predicate=PAYMENT, candidate="p0")
    assert queued["outcome"] == "review_queued"
    return queued


def test_an_equivalent_open_proposal_is_pending_review_and_unchanged(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "pending")
    queued = _queue(runtime, principal, profile, org)
    before = _proposal(runtime.engine, queued["proposal_id"])
    pending = runtime.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        candidate="p1",
        evidence=(external("obj-other"),),
    )
    assert pending["outcome"] == "duplicate_pending_review"
    assert pending["reason"] == "pending_review_exists"
    assert (pending["proposal_id"], pending["review_case_id"]) == (
        queued["proposal_id"],
        queued["review_case_id"],
    )
    assert _proposal(runtime.engine, queued["proposal_id"]) == before


def _queue_financial(runtime: SubmitRuntime, key: str) -> tuple[str, str, str, dict[str, Any]]:
    """(principal, profile, project, queued) for one requires_operator project proposal."""
    principal = new_principal()
    profile = runtime.profile(principal)
    project = runtime.project(principal, key)
    queued = submit_envelope(
        runtime,
        principal,
        profile,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        subject_id=project,
        predicate=FINANCIAL,
        value="Synthetic budget fact",
        candidate="p0",
    )
    assert queued.error is None and queued.result["outcome"] == "review_queued"
    return principal, profile, project, dict(queued.result)


def _late_submit(runtime: SubmitRuntime, principal: str, profile: str, project: str) -> Any:  # noqa: ANN401
    """The same fact under a new candidate with new evidence (an enrichment if live)."""
    return submit_envelope(
        runtime,
        principal,
        profile,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        subject_id=project,
        predicate=FINANCIAL,
        value="Synthetic budget fact",
        candidate="p-late",
        evidence=(external("obj-late"),),
    )


def _decide(runtime: SubmitRuntime, principal: str, case: str, disposition: Disposition) -> Any:  # noqa: ANN401
    """A real Knowledge `review.decide` from the CLI operator surface (slice C)."""
    return runtime.invoke(
        DecideReviewCase(review_case_id=case, expected_review_version=0, disposition=disposition),
        principal_id=principal,
        operator_surface=OperatorSurface.CLI,
    )


def test_race_14a_accepted_after_the_c5_wait_enriches_the_live_assertion(
    runtime: SubmitRuntime,
) -> None:
    """A real accept holds C5 and waits at C6; the late submit waits at C5 behind it.

    Releasing the C6 key lets the accept commit; the submit then takes C5, finds
    the proposal `accepted` and its fact live, and enriches it.
    """
    principal, profile, project, queued = _queue_financial(runtime, "race14a-accept")
    engine = runtime.engine
    commit_lock_row(engine, principal, "project", project, FINANCIAL)
    accepted, late = race(
        engine,
        lambda holder: hold_subject_lock(holder, principal, "project", project, FINANCIAL),
        lambda: _decide(runtime, principal, queued["review_case_id"], Disposition.ACCEPT),
        lambda: _late_submit(runtime, principal, profile, project),
    )
    assert accepted.error is None, accepted.error
    assert late.error is None, late.error
    assert late.result["outcome"] == "duplicate_enriched", late.result
    assert late.result["assertion_id"] == accepted.result["assertion_id"]
    assert late.result["assertion_version"] == 2
    assert _proposal(engine, queued["proposal_id"])["state"] == "accepted"


def test_race_14a_rejected_after_the_c5_wait_queues_a_new_proposal(
    runtime: SubmitRuntime,
) -> None:
    """The late submit has seen the proposal open (C2) and waits at C4a; a real reject
    completes meanwhile; the submit then takes C5, finds it `rejected`, and queues a new
    proposal -- the old one is unchanged."""
    principal, profile, project, queued = _queue_financial(runtime, "race14a-reject")
    engine = runtime.engine
    with engine.connect() as holder:
        holder.execute(
            text(
                "SELECT 1 FROM knowledge.knowledge_discovery_source_profiles "
                "WHERE source_profile_id = :p FOR NO KEY UPDATE"
            ),
            {"p": profile},
        ).one()
        with ThreadPoolExecutor(max_workers=1) as pool:
            waiting = pool.submit(_late_submit, runtime, principal, profile, project)
            _wait_for_waiters(engine, 1, waiting)
            rejected = _decide(runtime, principal, queued["review_case_id"], Disposition.REJECT)
            assert rejected.error is None, rejected.error
            holder.rollback()
            late = waiting.result(timeout=DEADLINE_SECONDS)
    assert late.error is None, late.error
    assert late.result["outcome"] == "review_queued", late.result
    assert late.result["proposal_id"] != queued["proposal_id"]
    assert _proposal(engine, queued["proposal_id"])["state"] == "rejected"


def test_race_14b_a_proposal_first_seen_after_c6_is_a_retryable_conflict(
    runtime: SubmitRuntime,
) -> None:
    """A project subject takes no C3, so both submits pass C5 and wait at C6."""
    principal = new_principal()
    profile = runtime.profile(principal)
    project = runtime.project(principal, "race14b")
    commit_lock_row(runtime.engine, principal, "project", project, FINANCIAL)

    def queue(candidate: str) -> Any:  # noqa: ANN401 - a ResponseEnvelope
        return submit_envelope(
            runtime,
            principal,
            profile,
            subject_kind=KnowledgeSubjectKind.PROJECT,
            subject_id=project,
            predicate=FINANCIAL,
            value="Synthetic budget fact",
            candidate=candidate,
        )

    one, two = race(
        runtime.engine,
        lambda holder: hold_subject_lock(holder, principal, "project", project, FINANCIAL),
        lambda: queue("x"),
        lambda: queue("y"),
    )
    assert one.error is None and one.result["outcome"] == "review_queued"
    assert two.error is not None and two.error.code.value == "conflict"
    assert two.error.retry.value == "after_refresh"
    assert counts(runtime.engine, principal)["knowledge_assertion_submissions"] == 1
    with runtime.engine.connect() as connection:
        proposals = connection.execute(
            select(knowledge_assertion_proposals.c.proposal_id).where(
                knowledge_assertion_proposals.c.principal_id == principal
            )
        ).all()
    assert len(proposals) == 1
    retry = queue("y")
    assert retry.error is None
    assert retry.result["outcome"] == "duplicate_pending_review"
    assert retry.result["proposal_id"] == one.result["proposal_id"]
