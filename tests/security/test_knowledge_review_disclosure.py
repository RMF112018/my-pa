"""KLP-WP-04 slice C: Knowledge Review disclosure on a real database (R6 5.2, 5.3, 10.3).

KLP-AC-033 (Python half), KLP-AC-034, KLP-AC-060 (review.list), KLP-AC-136.
Marked `database` (auto `database_clone`), routed to `database-current-head`.

*Remote* is R6's predicate everywhere: `transport is REMOTE_CLIENT or
capability_grants is not None`, so a LOCAL-transport composition that attached a
grant set (gsqs_b0-style stdio) is remote.

* `review.list` carries Knowledge rows only when the plane is composed and, for a
  remote caller, the caller holds `knowledge.assertions.read` for
  `knowledge_assertion_read`. A remote page omits every case whose *proposal
  effective class* is withheld -- the proposal's own class, or any origin
  evidence row restricted (including a dynamic raise after intake) or
  unavailable -- inside the statement, before the page LIMIT: a remote page of
  one whose oldest cases are withheld still returns the visible case, with no
  truncation flag pointing at hidden rows.
* `review.decide` on a withheld case, without the grant, or from a LOCAL
  composition with grants is `not_found(review_case_id)` byte-identical to an
  unknown id, writes no decision row, and is answered without waiting for the
  case's C3 Entity lock (a held mutation-scope lock does not delay it). A CLI
  `local_operator` may accept the same restricted `requires_operator` case
  (decision row `local_cli` / `local_operator`).

Every identity here is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import timedelta
from typing import Any, Final

import pytest
from sqlalchemy import select
from tests.database.test_knowledge_assertion_repository import WHEN, KnowledgeRuntime
from tests.database.test_knowledge_assertion_review import (
    CHATLLM_CLIENT,
    CLI,
    NO_READ_GRANTS,
    OPERATOR_CLIENT,
    READ_GRANTS,
    ReviewRuntime,
    decisions_of,
    proposal_of,
    remote,
    without_correlation,
)
from tests.database.test_knowledge_assertion_submissions import external

from my_pa.application.commands import ListReviewCases
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeEvidenceAvailability
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.identifier_claim_lock import lock_entity_mutation_scopes
from my_pa.infrastructure.persistence.tables import knowledge_submission_evidence
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

#: A LOCAL-transport composition with a grant ceiling: remote for disclosure.
LOCAL_WITH_GRANTS: Final[dict[str, object]] = {"grants": READ_GRANTS}


@pytest.fixture
def review(disposable_database: str) -> Iterator[ReviewRuntime]:
    composed = ReviewRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _evidence_of(review: ReviewRuntime, case: str) -> list[str]:
    origin = proposal_of(review.engine, case)["origin_submission_id"]
    se = knowledge_submission_evidence
    with review.engine.connect() as connection:
        return sorted(
            connection.execute(
                select(se.c.evidence_ref_id).where(se.c.submission_id == origin)
            ).scalars()
        )


def _restrict(review: ReviewRuntime, principal: str, case: str) -> None:
    """Raise one origin evidence row through the production classification ingress."""
    (evidence_ref_id,) = _evidence_of(review, case)
    with knowledge_maintenance_transaction(review.engine) as repository:
        repository.classify_evidence_restricted(principal, evidence_ref_id, at=WHEN)


def _lose_permission(review: ReviewRuntime, principal: str, case: str) -> None:
    (evidence_ref_id,) = _evidence_of(review, case)
    with knowledge_maintenance_transaction(review.engine) as repository:
        repository.record_evidence_availability(
            principal, evidence_ref_id, KnowledgeEvidenceAvailability.PERMISSION_LOST, at=WHEN
        )


def _world(review: ReviewRuntime) -> tuple[str, str, str, str, str]:
    """(principal, entity, restricted case, unavailable case, visible case), oldest first."""
    principal = review_principal()
    profile = review.profile(principal)
    entity = review.org(principal, "acme")
    cases = []
    for index in range(3):
        # Each case one minute later, so the oldest two (withheld) sort first.
        review.service._clock = lambda index=index: WHEN + timedelta(minutes=index)  # type: ignore[attr-defined]
        queued = review.queue(
            principal,
            profile,
            entity,
            candidate=f"cand-{index}",
            value=f"Synthetic terms {index}",
            evidence=(external(f"obj-{index}"),),
        )
        cases.append(str(queued["review_case_id"]))
    review.service._clock = lambda: WHEN  # type: ignore[attr-defined]
    restricted, unavailable, visible = cases
    _restrict(review, principal, restricted)
    _lose_permission(review, principal, unavailable)
    return principal, entity, restricted, unavailable, visible


def review_principal() -> str:
    return issue_identifier(IdKind.PRINCIPAL)


def _ids(rows: list[dict[str, Any]]) -> list[str]:
    return [row["review_case_id"] for row in rows if row["subject_kind"] == "knowledge_assertion"]


# ---- review.list ----------------------------------------------------------------------


def test_local_surfaces_list_every_case_and_remote_ones_only_the_visible(
    review: ReviewRuntime,
) -> None:
    principal, _entity, restricted, unavailable, visible = _world(review)
    # The restricted case's proposal row itself is unchanged: withholding is dynamic.
    assert proposal_of(review.engine, restricted)["classification"] == "private_local"
    every = [restricted, unavailable, visible]
    assert _ids(review.cases(principal, via=CLI)) == every
    assert _ids(review.cases(principal, via={})) == every
    for via in (remote(CHATLLM_CLIENT), remote(OPERATOR_CLIENT), LOCAL_WITH_GRANTS):
        assert _ids(review.cases(principal, via=via)) == [visible], via


def test_a_remote_caller_without_the_knowledge_read_grant_lists_no_knowledge_case(
    review: ReviewRuntime,
) -> None:
    principal, _entity, _r, _u, _visible = _world(review)
    for via in (
        remote(CHATLLM_CLIENT, NO_READ_GRANTS),
        {"grants": NO_READ_GRANTS},
        # A remote transport with no grant set at all holds no read grant.
        {"transport": remote(CHATLLM_CLIENT)["transport"], "client_id": CHATLLM_CLIENT},
    ):
        assert _ids(review.cases(principal, via=via)) == [], via


def test_withholding_runs_before_the_page_limit(review: ReviewRuntime) -> None:
    principal, _entity, restricted, unavailable, visible = _world(review)
    # The two withheld cases are the oldest: a LIMIT before withholding would
    # return the restricted one (and a truncation flag) to a remote page of one.
    assert _ids(review.cases(principal, via=CLI))[:2] == [restricted, unavailable]
    listed = review.invoke(
        ListReviewCases(page_size=1), principal_id=principal, **remote(CHATLLM_CLIENT)
    )
    assert listed.error is None, listed.error
    assert listed.result is not None
    assert _ids(list(listed.result["review_cases"])) == [visible]
    assert listed.disclosure.truncation.is_truncated is False
    local = review.invoke(ListReviewCases(page_size=1), principal_id=principal, **CLI)
    assert local.result is not None
    assert local.disclosure.truncation.is_truncated is True


def test_an_uncomposed_plane_lists_no_knowledge_case(
    review: ReviewRuntime, disposable_database: str
) -> None:
    principal, _entity, _r, _u, _visible = _world(review)
    off = KnowledgeRuntime(disposable_database, knowledge_enabled=False)
    try:
        listed = off.ok(ListReviewCases(), principal_id=principal)
    finally:
        off.close()
    assert _ids(list(listed["review_cases"])) == []


# ---- review.decide -----------------------------------------------------------------------


def test_a_withheld_or_ungranted_remote_decide_is_not_found_like_an_unknown_id(
    review: ReviewRuntime,
) -> None:
    principal, _entity, restricted, unavailable, visible = _world(review)
    unknown = issue_identifier(IdKind.REVIEW_CASE)
    reference = without_correlation(
        review.decide_error(principal, unknown, via=remote(OPERATOR_CLIENT))
    )
    assert reference["code"] == "not_found"
    assert reference["safe_details"] == ["review_case_id"]
    attempts = [
        (restricted, remote(OPERATOR_CLIENT)),
        (unavailable, remote(OPERATOR_CLIENT)),
        (restricted, LOCAL_WITH_GRANTS),
        (visible, remote(OPERATOR_CLIENT, NO_READ_GRANTS)),
        (visible, {"grants": NO_READ_GRANTS}),
    ]
    for case, via in attempts:
        assert without_correlation(review.decide_error(principal, case, via=via)) == reference
    for case in (restricted, unavailable, visible):
        assert decisions_of(review.engine, case) == []


def test_a_withheld_remote_decide_does_not_wait_for_the_case_entity_lock(
    review: ReviewRuntime,
) -> None:
    """The visibility answer precedes C3: a held mutation-scope lock does not delay it."""
    principal, entity, restricted, _unavailable, visible = _world(review)
    answers: dict[str, dict[str, Any]] = {}

    def decide(case: str) -> None:
        answers[case] = review.decide_error(principal, case, via=remote(OPERATOR_CLIENT))

    with review.engine.begin() as holder:
        lock_entity_mutation_scopes(holder, principal, (entity,))
        worker = threading.Thread(target=decide, args=(restricted,), daemon=True)
        worker.start()
        worker.join(timeout=20)
        assert not worker.is_alive(), "a withheld decide waited on the Entity lock"
    assert answers[restricted]["code"] == "not_found"
    # Control: a visible promotion does take C3 -- it waits until the holder commits.
    done = threading.Event()

    def accept() -> None:
        review.decide(principal, visible, via=remote(OPERATOR_CLIENT))
        done.set()

    with review.engine.begin() as holder:
        lock_entity_mutation_scopes(holder, principal, (entity,))
        worker = threading.Thread(target=accept, daemon=True)
        worker.start()
        assert not done.wait(timeout=2), "an acceptance must wait for the Entity lock"
    worker.join(timeout=20)
    assert done.is_set()


def test_a_cli_operator_may_accept_a_restricted_operator_case(review: ReviewRuntime) -> None:
    principal, _entity, restricted, _unavailable, _visible = _world(review)
    decided = review.decide(principal, restricted, via=CLI)
    assert decided["proposal_state"] == "accepted"
    (decision,) = decisions_of(review.engine, restricted)
    assert decision["decision_channel"] == "local_cli"
    assert decision["operator_authority_class"] == "local_operator"
    assert decision["authenticated_client_id"] is None
    # The promoted fact carries the raised evidence class forward.
    assert decided["assertion_id"] is not None
