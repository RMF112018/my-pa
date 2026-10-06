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
* **Remote replay re-gate** (fix round 3, R6 10.3): the remote replay key hashes
  (capability, principal, arguments) and names no client, so a stored Knowledge
  decision is re-gated for a remote caller before the generic replay answers.
  The same client replays byte-identically; a second remote client without the
  read grant, and any remote replay of a case that became withheld, get the
  unknown-id `not_found` and none of the stored kadec_/kasr_/kamut_ ids. The
  replay identity is driven here as a fixed request id (what the adapter derives
  for both clients); a CLI replay of the withheld case is unchanged.

Every identity here is synthetic.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from datetime import datetime, timedelta
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
    _holder_and_case,
    _queued,
    _refused_and_untouched,
    decisions_of,
    proposal_of,
    remote,
    without_correlation,
)
from tests.database.test_knowledge_assertion_submissions import EARLY, LATER, external

from my_pa.application.commands import ListReviewCases
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeEvidenceAvailability
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.identifier_claim_lock import lock_entity_mutation_scopes
from my_pa.infrastructure.persistence.tables import (
    knowledge_assertion_evidence_links,
    knowledge_submission_evidence,
)
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


def _decide_under(
    review: ReviewRuntime, principal: str, case: str, request_id: str, via: dict[str, object]
) -> Any:  # noqa: ANN401 - the response envelope
    return review.invoke_with_request_id(
        review.decide_command(case, Disposition.ACCEPT),
        principal_id=principal,
        request_id=request_id,
        **via,
    )


def _unknown_reference(review: ReviewRuntime, principal: str) -> dict[str, Any]:
    unknown = issue_identifier(IdKind.REVIEW_CASE)
    reference = without_correlation(
        review.decide_error(principal, unknown, via=remote(OPERATOR_CLIENT))
    )
    assert reference["code"] == "not_found"
    return reference


def test_a_remote_replay_by_the_same_client_stays_byte_identical(review: ReviewRuntime) -> None:
    principal, _entity, case = _queued(review)
    request_id = issue_identifier(IdKind.CORRELATION)
    fresh = _decide_under(review, principal, case, request_id, remote(OPERATOR_CLIENT))
    assert fresh.error is None, fresh.error
    replayed = _decide_under(review, principal, case, request_id, remote(OPERATOR_CLIENT))
    assert replayed.error is None, replayed.error
    assert json.dumps(replayed.result, sort_keys=True) == json.dumps(fresh.result, sort_keys=True)


def test_a_remote_replay_without_the_read_grant_is_not_found_like_an_unknown_id(
    review: ReviewRuntime,
) -> None:
    principal, _entity, case = _queued(review)
    request_id = issue_identifier(IdKind.CORRELATION)
    fresh = _decide_under(review, principal, case, request_id, remote(OPERATOR_CLIENT))
    assert fresh.error is None, fresh.error
    reference = _unknown_reference(review, principal)
    for via in (remote(CHATLLM_CLIENT, NO_READ_GRANTS), {"grants": NO_READ_GRANTS}):
        replayed = _decide_under(review, principal, case, request_id, via)
        assert replayed.result is None, replayed.result
        assert replayed.error is not None
        assert without_correlation(replayed.error.model_dump(mode="json")) == reference
    assert len(decisions_of(review.engine, case)) == 1


def test_a_remote_replay_of_a_case_withheld_since_is_not_found_like_an_unknown_id(
    review: ReviewRuntime,
) -> None:
    principal, _entity, case = _queued(review)
    request_id = issue_identifier(IdKind.CORRELATION)
    fresh = _decide_under(review, principal, case, request_id, remote(OPERATOR_CLIENT))
    assert fresh.error is None, fresh.error
    _restrict(review, principal, case)
    reference = _unknown_reference(review, principal)
    replayed = _decide_under(review, principal, case, request_id, remote(OPERATOR_CLIENT))
    assert replayed.result is None, replayed.result
    assert replayed.error is not None
    body = replayed.error.model_dump(mode="json")
    assert without_correlation(body) == reference
    assert "kadec_" not in json.dumps(body)
    # A local replay is unchanged: the CLI still receives the stored decision.
    local = _decide_under(review, principal, case, request_id, CLI)
    assert local.error is None, local.error
    assert local.result == fresh.result


# ---- the read-only candidate on review.list (fix round 4, Manager ruling on DEV-83) ------


def _knowledge_row(rows: list[dict[str, Any]], case: str) -> dict[str, Any]:
    (row,) = [row for row in rows if row["review_case_id"] == case]
    return row


def _holder_evidence(review: ReviewRuntime, holder: str) -> str:
    links = knowledge_assertion_evidence_links
    with review.engine.connect() as connection:
        return str(
            connection.execute(
                select(links.c.evidence_ref_id).where(links.c.assertion_id == holder)
            ).scalar_one()
        )


def test_a_granted_remote_reviewer_and_a_local_one_see_the_candidate_and_holder(
    review: ReviewRuntime,
) -> None:
    principal, holder, case = _holder_and_case(review, successor_from=LATER, direct_successor=False)
    cited = _evidence_of(review, case)
    expected = {
        "value_type": "text",
        "value": "Synthetic net 60",
        "qualifier": None,
        "effective_from": LATER.isoformat(),
        "effective_to": None,
        "evidence_ref_ids": cited,
        "current_assertion_id": holder,
        "current_value": "Synthetic net 30",
    }
    assert cited and all(ref.startswith("kaevd_") for ref in cited)
    for via in (remote(CHATLLM_CLIENT), remote(OPERATOR_CLIENT), LOCAL_WITH_GRANTS, CLI, {}):
        row = _knowledge_row(review.cases(principal, via=via), case)
        assert {key: row[key] for key in expected} == expected, via
        assert row["subject_kind_of_fact"] == "entity"
        assert row["predicate_code"] == "organization.payment_terms"


def test_the_candidate_never_carries_excerpt_text(review: ReviewRuntime) -> None:
    principal = review_principal()
    profile = review.profile(principal)
    entity = review.org(principal, "acme")
    excerpt = "Synthetic private excerpt words"
    queued = review.queue(
        principal, profile, entity, evidence=(external("obj-x", excerpt=excerpt),)
    )
    for via in (remote(CHATLLM_CLIENT), CLI):
        row = _knowledge_row(review.cases(principal, via=via), str(queued["review_case_id"]))
        assert row["evidence_ref_ids"] == _evidence_of(review, str(queued["review_case_id"]))
        assert excerpt not in json.dumps(row)
        assert "excerpt" not in json.dumps(row)


def test_a_withheld_holder_is_nulled_for_a_remote_reviewer_only(review: ReviewRuntime) -> None:
    """The holder's own `withheld_remote` nulls BOTH holder fields remotely.

    The holder's evidence is raised to restricted_local through the production
    classification ingress; the proposal cites other evidence and stays
    visible, so the case is listed with its own candidate and no holder.
    """
    principal, holder, case = _holder_and_case(review, successor_from=LATER, direct_successor=False)
    with knowledge_maintenance_transaction(review.engine) as repository:
        repository.classify_evidence_restricted(
            principal, _holder_evidence(review, holder), at=WHEN
        )
    for via in (remote(CHATLLM_CLIENT), remote(OPERATOR_CLIENT), LOCAL_WITH_GRANTS):
        row = _knowledge_row(review.cases(principal, via=via), case)
        assert row["value"] == "Synthetic net 60", via
        assert row["current_assertion_id"] is None, via
        assert row["current_value"] is None, via
        assert "Synthetic net 30" not in json.dumps(row)
    for via in (CLI, {}):
        row = _knowledge_row(review.cases(principal, via=via), case)
        assert row["current_assertion_id"] == holder, via
        assert row["current_value"] == "Synthetic net 30", via


def test_a_restricted_or_ungranted_case_shows_nothing_and_the_page_is_not_short(
    review: ReviewRuntime,
) -> None:
    """Remote with the grant: page of one = the visible case, with its candidate.

    No word of a withheld case's candidate reaches the page; without the grant no
    Knowledge row at all. A local caller sees every candidate, the withheld
    ones included.
    """
    principal, _entity, restricted, unavailable, visible = _world(review)
    listed = review.invoke(
        ListReviewCases(page_size=1), principal_id=principal, **remote(CHATLLM_CLIENT)
    )
    assert listed.error is None and listed.result is not None
    page = list(listed.result["review_cases"])
    assert _ids(page) == [visible]
    assert page[-1]["value"] == "Synthetic terms 2"
    assert page[-1]["evidence_ref_ids"] == _evidence_of(review, visible)
    text = json.dumps(page)
    for withheld in (restricted, unavailable):
        assert withheld not in text
        for ref in _evidence_of(review, withheld):
            assert ref not in text
    assert "Synthetic terms 0" not in text and "Synthetic terms 1" not in text
    assert listed.disclosure.truncation.is_truncated is False
    for via in (remote(CHATLLM_CLIENT, NO_READ_GRANTS), {"grants": NO_READ_GRANTS}):
        assert _ids(review.cases(principal, via=via)) == [], via
    local = review.cases(principal, via=CLI)
    assert [
        _knowledge_row(local, case)["value"] for case in (restricted, unavailable, visible)
    ] == ["Synthetic terms 0", "Synthetic terms 1", "Synthetic terms 2"]


# ---- NB-R5-1: a remote guard refusal over a withheld holder is generic (fix round 5) ----

#: The three Review supersession guard failures: regressing, future-dated, and a
#: NULL successor over a dated predecessor.
GUARD_FAILURES: Final = (EARLY - timedelta(days=5), WHEN + timedelta(days=5), None)


def _withheld_holder_case(
    review: ReviewRuntime, successor_from: datetime | None, *, withhold: bool = True
) -> tuple[str, str, str]:
    principal, holder, case = _holder_and_case(
        review, successor_from=successor_from, direct_successor=False
    )
    if withhold:
        with knowledge_maintenance_transaction(review.engine) as repository:
            repository.classify_evidence_restricted(
                principal, _holder_evidence(review, holder), at=WHEN
            )
    return principal, holder, case


def test_a_remote_guard_refusal_over_a_withheld_holder_is_one_uniform_generic_conflict(
    review: ReviewRuntime,
) -> None:
    """Every guard failure answers the same body, naming no field of the holder.

    The case itself stays visible (its own evidence is unrestricted); only the
    holder is `withheld_remote`. Remote is R6's predicate, so the LOCAL
    composition with grants is generic too. Nothing is written by any refusal.
    """
    bodies: set[str] = set()
    for successor_from in GUARD_FAILURES:
        principal, holder, case = _withheld_holder_case(review, successor_from)
        for via in (remote(OPERATOR_CLIENT), LOCAL_WITH_GRANTS):
            error = _refused_and_untouched(
                review, principal, holder, case, Disposition.ACCEPT, ["review_case_id"], via=via
            )
            bodies.add(json.dumps(without_correlation(error), sort_keys=True))
    assert len(bodies) == 1, bodies
    assert "effective_from" not in next(iter(bodies))


def test_local_and_holder_visible_remote_refusals_keep_the_specific_reason(
    review: ReviewRuntime,
) -> None:
    for successor_from in GUARD_FAILURES:
        # Withheld holder: a local caller still gets the field.
        principal, holder, case = _withheld_holder_case(review, successor_from)
        for via in (CLI, {}):
            _refused_and_untouched(
                review, principal, holder, case, Disposition.ACCEPT, ["effective_from"], via=via
            )
        # Visible holder: a remote caller gets the field as well.
        principal, holder, case = _withheld_holder_case(review, successor_from, withhold=False)
        for via in (remote(OPERATOR_CLIENT), LOCAL_WITH_GRANTS):
            _refused_and_untouched(
                review, principal, holder, case, Disposition.ACCEPT, ["effective_from"], via=via
            )
