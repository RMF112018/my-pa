"""KLP-WP-04 slice C: Entity merge refuses while Knowledge names a participant (R6 8.6).

KLP-AC-036 (merge half), KLP-AC-108, KLP-AC-113 (sequential half), KLP-AC-137.
Marked `database` (auto `database_clone`), routed to `database-current-head`.

Every write is production: Knowledge facts by explicit create / autonomous
submit, proposals decided by `review.decide`, merges by `entities.merge.preview`
and `entities.merge` through `ApplicationService.invoke`.

* A live Knowledge assertion or an open Knowledge proposal whose subject is the
  survivor or a merged-away Entity is reported by preview as a blocker of kind
  `knowledge_reference_present` (family `entity`, the participant's id), and
  apply refuses with `conflict(identity_correction_conflict)`; nothing is
  reparented -- the Knowledge rows still name their original subject.
* A terminal proposal (rejected) no longer blocks: a fresh preview is clean and
  the merge applies.
* Apply re-checks under the participant mutation-scope lock: a proposal filed
  after a clean preview makes apply refuse `conflict(preview_stale)`.
* No `MergeFamily` member names Knowledge, and preview still reports exactly
  the `MergeFamily` set of groups.

Every identity here is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Final

import pytest
from sqlalchemy import select

from my_pa.application.commands import MergeEntities, PreviewEntityMerge
from my_pa.application.identity_correction import MergeFamily
from my_pa.domain.capture.review import Disposition
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeSubjectKind
from my_pa.domain.relationship.identity_correction import IdentityConflictKind, blocks_merge
from my_pa.infrastructure.persistence.tables import (
    knowledge_assertion_proposals,
    knowledge_assertions,
)
from tests.database.test_knowledge_assertion_repository import new_principal
from tests.database.test_knowledge_assertion_review import ReviewRuntime
from tests.database.test_knowledge_assertion_submissions import PAYMENT

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

OPERATING: Final = "organization.operating_requirement"
REASON: Final = "Synthetic merge of two organizations"


@pytest.fixture
def review(disposable_database: str) -> Iterator[ReviewRuntime]:
    composed = ReviewRuntime(disposable_database, identity_correction=True)
    try:
        yield composed
    finally:
        composed.close()


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


def _apply(review: ReviewRuntime, principal: str, preview: dict[str, Any]) -> Any:  # noqa: ANN401
    return review.invoke(
        MergeEntities(
            preview_id=str(preview["preview_id"]),
            preview_digest=str(preview["preview_token"]),
            reason=REASON,
        ),
        principal_id=principal,
    )


def _pair(review: ReviewRuntime) -> tuple[str, str, str]:
    principal = new_principal()
    return principal, review.org(principal, "acme"), review.org(principal, "globex")


def test_the_blocker_kind_is_python_only_and_blocks() -> None:
    assert IdentityConflictKind.KNOWLEDGE_REFERENCE_PRESENT.value == "knowledge_reference_present"
    assert blocks_merge(IdentityConflictKind.KNOWLEDGE_REFERENCE_PRESENT) is True
    assert not [family for family in MergeFamily if "knowledge" in family.value]


def test_a_live_assertion_on_a_merged_away_entity_blocks_preview_and_apply(
    review: ReviewRuntime,
) -> None:
    principal, survivor, merged = _pair(review)
    created = review.create(
        principal,
        "klp04-merge-live",
        subject_id=merged,
        subject_kind=KnowledgeSubjectKind.ENTITY,
        predicate=OPERATING,
        value="Synthetic badge required",
    )
    assert created["outcome"] == "direct_created"
    preview = _preview(review, principal, survivor, merged)
    assert preview["blockers"] == [
        {"kind": "knowledge_reference_present", "family": "entity", "record_id": merged}
    ]
    assert {group["family"] for group in preview["affected_groups"]} == {
        family.value for family in MergeFamily
    }
    applied = _apply(review, principal, preview)
    assert applied.error is not None
    assert applied.error.code.value == "conflict"
    assert applied.error.safe_details == ("identity_correction_conflict",)
    with review.engine.connect() as connection:
        subject = connection.execute(
            select(knowledge_assertions.c.subject_id).where(
                knowledge_assertions.c.assertion_id == created["assertion_id"]
            )
        ).scalar_one()
    assert subject == merged  # never reparented (KLP-AC-137)


def test_an_open_proposal_on_the_survivor_blocks_until_it_is_decided(
    review: ReviewRuntime,
) -> None:
    principal, survivor, merged = _pair(review)
    profile = review.profile(principal)
    queued = review.queue(principal, profile, survivor, predicate=PAYMENT)
    case = str(queued["review_case_id"])
    blocked = _preview(review, principal, survivor, merged)
    assert [blocker["record_id"] for blocker in blocked["blockers"]] == [survivor]
    review.decide(principal, case, Disposition.DEFER)  # still open: still blocks
    still = _preview(review, principal, survivor, merged)
    assert [blocker["kind"] for blocker in still["blockers"]] == ["knowledge_reference_present"]
    review.decide(principal, case, Disposition.REJECT, version=1)
    clean = _preview(review, principal, survivor, merged)
    assert clean["blockers"] == []
    applied = _apply(review, principal, clean)
    assert applied.error is None, applied.error
    with review.engine.connect() as connection:
        subject = connection.execute(
            select(knowledge_assertion_proposals.c.subject_id).where(
                knowledge_assertion_proposals.c.review_case_id == case
            )
        ).scalar_one()
    assert subject == survivor


def test_apply_rechecks_knowledge_references_under_the_participant_lock(
    review: ReviewRuntime,
) -> None:
    principal, survivor, merged = _pair(review)
    profile = review.profile(principal)
    clean = _preview(review, principal, survivor, merged)
    assert clean["blockers"] == []
    review.queue(principal, profile, merged, predicate=PAYMENT)
    applied = _apply(review, principal, clean)
    assert applied.error is not None
    assert applied.error.code.value == "conflict"
    assert applied.error.safe_details == ("preview_stale",)


def test_an_accepted_fact_keeps_blocking_after_its_proposal_is_terminal(
    review: ReviewRuntime,
) -> None:
    principal, survivor, merged = _pair(review)
    profile = review.profile(principal)
    queued = review.queue(principal, profile, merged, predicate=PAYMENT)
    review.decide(principal, str(queued["review_case_id"]))
    preview = _preview(review, principal, survivor, merged)
    assert [blocker["record_id"] for blocker in preview["blockers"]] == [merged]
