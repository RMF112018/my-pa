"""KLP-WP-03: the Knowledge Assertion Record Event family on a real database.

KLP-AC-042 (WP-03 slice) and KLP-AC-045. Marked `database` (auto
`database_clone`), routed to `database-current-head`.

* An admitted explicit create commits exactly the mapped event: family
  `knowledge_assertion`, `record_id` the assertion, `created`, version 1, the
  frozen changed-field tokens, `source_capability` `knowledge.assertions.create`,
  actor `principal`, authority `user_confirmed_assertion`, the assertion's class,
  `source_receipt_id` the `kamut_` mutation, the request's correlation, and no
  cause.
* A replay, an exact duplicate, a domain-owned completion, a born-completed
  refusal, an admissibility refusal and a rolled-back create commit no event and
  advance no sequence.
* `causation_event_id` keeps its same-transaction meaning: an explicit create is
  a root write, so it names none, and the column's foreign key is still
  `NOT DEFERRABLE` against the feed.

KLP-WP-04 slice B2 adds the autonomous-submit kinds (KLP-AC-042 submit half,
KLP-AC-043):

* `direct_created` -> one `created`; `direct_superseded` -> `state_changed
  (lifecycle)` on the predecessor then `created` on the successor;
  `duplicate_enriched` -> `updated(evidence)`; an enrichment whose new evidence
  is restricted adds `state_changed(classification)` (the classification-raise
  kind) -- each with actor `assistant`, authority `source_backed_assertion`,
  `source_capability` `knowledge.assertions.submit` and its `kamut_` receipt.
* `review_queued` and `duplicate_pending_review` (proposals) commit no event and
  advance no sequence (KLP-AC-043).
* The revalidation kind is staged by the availability ingress, whose event is
  proven in `tests/database/test_knowledge_evidence_availability.py`; submit
  carries no availability report in this build (slice B2 residual).

KLP-WP-04 slice C adds the Review promotion kinds (KLP-AC-042 review half,
KLP-AC-043): `review_accept` and `review_correct` -> `created`, and a superseded
single-current holder -> `state_changed(lifecycle)` first, each with actor
`review_promotion`, authority `review_accepted`, `source_capability`
`review.decide` and its `kamut_` receipt; a proposal and every non-promoting
decision (defer, mark_unresolved, reject, invalidate) commit no event and
advance no sequence.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import timedelta

import pytest
from sqlalchemy import select, text

from my_pa.application.commands import ListRecordEvents
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.knowledge_assertion.provenance import (
    KNOWLEDGE_EVENT_ACTOR_CLASSES,
    KNOWLEDGE_EVENT_AUTHORITIES,
    KNOWLEDGE_MUTATION_EVENTS,
    KnowledgeEventOrigin,
)
from my_pa.domain.knowledge_assertion.vocabulary import (
    KnowledgeMutationKind,
    KnowledgeSubjectKind,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.tables import knowledge_assertions, knowledge_evidence_refs
from my_pa.infrastructure.persistence.unit_of_work import knowledge_maintenance_transaction
from tests.database.test_knowledge_assertion_repository import (
    DECISION,
    FINANCIAL,
    LESSON,
    WHEN,
    KnowledgeRuntime,
    capture_evidence,
    create_command,
    knowledge_events,
    new_principal,
)
from tests.database.test_knowledge_assertion_review import ReviewRuntime
from tests.database.test_knowledge_assertion_submissions import (
    EARLY,
    LATER,
    PAYMENT,
    SubmitRuntime,
    add_direct_payment_head,
    external,
)
from tests.database.test_task_record_events import next_sequence

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[KnowledgeRuntime]:
    composed = KnowledgeRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def test_an_explicit_create_commits_exactly_the_mapped_event(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    capture_id, digest = runtime.capture(principal, "events")
    response = runtime.invoke(
        create_command(
            "klp03-event", subject_id=principal, evidence=(capture_evidence(capture_id, digest),)
        ),
        principal_id=principal,
    )
    assert response.error is None and response.result is not None
    created = response.result
    (event,) = knowledge_events(runtime.engine, principal)
    mapped = KNOWLEDGE_MUTATION_EVENTS[KnowledgeMutationKind.CREATE]
    origin = KnowledgeEventOrigin.EXPLICIT_CREATE
    with runtime.engine.connect() as connection:
        classification = connection.execute(
            select(knowledge_assertions.c.classification).where(
                knowledge_assertions.c.assertion_id == created["assertion_id"]
            )
        ).scalar_one()
    assert event["record_family"] == "knowledge_assertion"
    assert event["record_id"] == created["assertion_id"]
    assert event["event_kind"] == mapped.kind.value == "created"
    assert event["record_version"] == 1
    assert tuple(event["changed_fields"]) == mapped.changed_fields
    assert event["source_capability"] == "knowledge.assertions.create"
    assert event["actor_class"] == KNOWLEDGE_EVENT_ACTOR_CLASSES[origin].value == "principal"
    assert event["authority"] == KNOWLEDGE_EVENT_AUTHORITIES[origin].value
    assert event["authority"] == "user_confirmed_assertion"
    assert event["classification"] == classification == "private_local"
    assert event["source_receipt_id"] == created["mutation_id"]
    assert event["source_receipt_id"].startswith("kamut_")
    assert event["correlation_id"] == response.correlation_id
    assert event["causation_event_id"] is None
    assert event["principal_id"] == principal


def test_no_other_create_outcome_commits_an_event_or_advances_the_sequence(
    runtime: KnowledgeRuntime,
) -> None:
    principal = new_principal()
    runtime.create(principal, "klp03-first")
    sequence = next_sequence(runtime.engine, principal)
    before = len(knowledge_events(runtime.engine, principal))
    # Replay of the same key, an exact duplicate under a new key, a domain-owned
    # completion, a born-completed refusal, and an admissibility refusal.
    runtime.create(principal, "klp03-first")
    assert runtime.create(principal, "klp03-dup")["outcome"] == "duplicate_existing"
    project = runtime.project(principal, "events")
    sequence = next_sequence(runtime.engine, principal)  # the project write has its own event
    owned = runtime.create(
        principal,
        "klp03-owned",
        subject_id=project,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        predicate=DECISION,
    )
    assert owned["outcome"] == "domain_owned_no_intake"
    refused = runtime.create(
        principal,
        "klp03-refused",
        subject_id=issue_identifier(IdKind.PROJECT),
        subject_kind=KnowledgeSubjectKind.PROJECT,
        predicate=LESSON,
    )
    assert refused["outcome"] == "refused"
    runtime.error(
        create_command(
            "klp03-financial",
            subject_id=project,
            subject_kind=KnowledgeSubjectKind.PROJECT,
            predicate=FINANCIAL,
        ),
        principal_id=principal,
    )
    assert len(knowledge_events(runtime.engine, principal)) == before
    assert next_sequence(runtime.engine, principal) == sequence


def test_a_rolled_back_create_commits_no_event(runtime: KnowledgeRuntime) -> None:
    """A citation that does not resolve rolls the whole create back, event included."""
    principal = new_principal()
    runtime.error(
        create_command(
            "klp03-rollback",
            subject_id=principal,
            evidence=(capture_evidence(issue_identifier(IdKind.CAPTURE), "a" * 64),),
        ),
        principal_id=principal,
    )
    assert knowledge_events(runtime.engine, principal) == []
    assert next_sequence(runtime.engine, principal) is None


def test_the_local_feed_lists_the_knowledge_event(runtime: KnowledgeRuntime) -> None:
    principal = new_principal()
    created = runtime.create(principal, "klp03-feed")
    listed = runtime.ok(ListRecordEvents(), principal_id=principal)
    assert "knowledge_assertion" in listed["visible_families"]
    (item,) = [row for row in listed["events"] if row["record_family"] == "knowledge_assertion"]
    assert item["record_id"] == created["assertion_id"]
    assert item["source_receipt_id"] == created["mutation_id"]
    assert item["causation_event_id"] is None


def test_the_causation_foreign_key_is_still_not_deferrable(runtime: KnowledgeRuntime) -> None:
    with runtime.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT condeferrable FROM pg_constraint WHERE conrelid = "
                "'knowledge.record_events'::regclass AND contype = 'f' AND "
                "pg_get_constraintdef(oid) LIKE '%(causation_event_id%'"
            )
        ).scalars()
        assert list(rows) == [False]


# ---- KLP-WP-04 slice B2: autonomous submit ------------------------------------------


@pytest.fixture
def submitter(disposable_database: str) -> Iterator[SubmitRuntime]:
    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _assert_submit_event(event: dict[str, object], kind: KnowledgeMutationKind) -> None:
    mapped = KNOWLEDGE_MUTATION_EVENTS[kind]
    origin = KnowledgeEventOrigin.AUTONOMOUS_SUBMIT
    assert event["event_kind"] == mapped.kind.value
    assert tuple(event["changed_fields"]) == mapped.changed_fields  # type: ignore[arg-type]
    assert event["actor_class"] == KNOWLEDGE_EVENT_ACTOR_CLASSES[origin].value
    assert event["authority"] == KNOWLEDGE_EVENT_AUTHORITIES[origin].value
    assert event["source_capability"] == "knowledge.assertions.submit"
    assert str(event["source_receipt_id"]).startswith("kamut_")
    assert event["causation_event_id"] is None


def test_submit_supersede_and_enrich_stage_exactly_the_mapped_events(
    submitter: SubmitRuntime,
) -> None:
    principal = new_principal()
    add_direct_payment_head(submitter.engine)
    profile = submitter.profile(principal)
    org = submitter.entity(principal, "events")
    first = submitter.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        value="Net 30",
        candidate="e1",
        effective_from=WHEN - timedelta(days=9),
    )
    second = submitter.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        value="Net 45",
        candidate="e2",
        effective_from=WHEN - timedelta(days=2),
    )
    enriched = submitter.submit(
        principal,
        profile,
        subject_id=org,
        predicate=PAYMENT,
        value="Net 45",
        candidate="e3",
        effective_from=WHEN - timedelta(days=2),
        evidence=(external("obj-1"), external("obj-extra", role="supporting")),
    )
    assert (first["outcome"], second["outcome"], enriched["outcome"]) == (
        "direct_created",
        "direct_superseded",
        "duplicate_enriched",
    )
    events = knowledge_events(submitter.engine, principal)
    expected = [
        (first["assertion_id"], KnowledgeMutationKind.CREATE, 1),
        (first["assertion_id"], KnowledgeMutationKind.SUPERSEDE_PREDECESSOR, 2),
        (second["assertion_id"], KnowledgeMutationKind.SUPERSEDE_SUCCESSOR, 1),
        (second["assertion_id"], KnowledgeMutationKind.EVIDENCE_ENRICH, 2),
    ]
    assert [(e["record_id"], e["record_version"]) for e in events] == [
        (assertion_id, version) for assertion_id, _kind, version in expected
    ]
    for event, (_assertion_id, kind, _version) in zip(events, expected, strict=True):
        _assert_submit_event(event, kind)
    assert events[3]["source_receipt_id"] == enriched["mutation_id"]


def test_an_enrichment_with_restricted_evidence_stages_the_classification_raise(
    submitter: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = submitter.profile(principal)
    org, other = submitter.entity(principal, "raise-a"), submitter.entity(principal, "raise-b")
    first = submitter.submit(principal, profile, subject_id=org, candidate="r1")
    # Restrict an object through the source-classification ingress, via its row
    # under another assertion; then re-cite a new version of that object.
    submitter.submit(
        principal,
        profile,
        subject_id=other,
        candidate="r2",
        value="Other requirement",
        evidence=(external("obj-secret"),),
    )
    with submitter.engine.connect() as connection:
        secret = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal,
                knowledge_evidence_refs.c.external_object_id == "obj-secret",
            )
        ).scalar_one()
    with knowledge_maintenance_transaction(submitter.engine) as repository:
        repository.classify_evidence_restricted(principal, secret, at=WHEN)
    enriched = submitter.submit(
        principal,
        profile,
        subject_id=org,
        candidate="r3",
        evidence=(external("obj-1"), external("obj-secret", version="v2", role="supporting")),
    )
    assert enriched["outcome"] == "duplicate_enriched", enriched
    assert enriched["assertion_version"] == 3
    with submitter.engine.connect() as connection:
        row = connection.execute(
            select(knowledge_assertions.c.classification).where(
                knowledge_assertions.c.assertion_id == first["assertion_id"]
            )
        ).scalar_one()
    assert row == "restricted_local"
    mine = [
        e
        for e in knowledge_events(submitter.engine, principal)
        if e["record_id"] == first["assertion_id"]
    ]
    assert [(e["event_kind"], e["record_version"]) for e in mine] == [
        ("created", 1),
        ("updated", 2),
        ("state_changed", 3),
    ]
    _assert_submit_event(mine[2], KnowledgeMutationKind.CLASSIFY)
    assert mine[2]["classification"] == "restricted_local"


def test_proposals_alone_emit_no_canonical_event(submitter: SubmitRuntime) -> None:
    principal = new_principal()
    profile = submitter.profile(principal)
    org = submitter.entity(principal, "proposals")
    before = next_sequence(submitter.engine, principal)
    queued = submitter.submit(principal, profile, subject_id=org, predicate=PAYMENT)
    pending = submitter.submit(
        principal, profile, subject_id=org, predicate=PAYMENT, candidate="c2"
    )
    assert queued["outcome"] == "review_queued"
    assert pending["outcome"] == "duplicate_pending_review"
    assert pending["proposal_id"] == queued["proposal_id"]
    assert knowledge_events(submitter.engine, principal) == []
    assert next_sequence(submitter.engine, principal) == before


# ---- KLP-WP-04 slice C: Review promotion kinds (KLP-AC-042 review half, AC-043) ---------


@pytest.fixture
def reviewer(disposable_database: str) -> Iterator[ReviewRuntime]:
    composed = ReviewRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _assert_review_event(event: dict[str, object], kind: KnowledgeMutationKind) -> None:
    mapped = KNOWLEDGE_MUTATION_EVENTS[kind]
    origin = KnowledgeEventOrigin.REVIEW_PROMOTION
    assert event["event_kind"] == mapped.kind.value
    assert tuple(event["changed_fields"]) == mapped.changed_fields  # type: ignore[arg-type]
    assert event["actor_class"] == KNOWLEDGE_EVENT_ACTOR_CLASSES[origin].value
    assert event["authority"] == KNOWLEDGE_EVENT_AUTHORITIES[origin].value
    assert event["source_capability"] == "review.decide"
    assert str(event["source_receipt_id"]).startswith("kamut_")
    assert event["causation_event_id"] is None


def test_review_accept_correct_and_supersede_stage_exactly_the_mapped_events(
    reviewer: ReviewRuntime,
) -> None:
    principal = new_principal()
    profile = reviewer.profile(principal)
    org = reviewer.entity(principal, "review-events")
    # Both bounds recorded and ordered: a Review supersession re-checks the
    # KLP-AC-031 guards (fix round 4, DEV-66 ruling).
    first = reviewer.queue(
        principal, profile, org, candidate="r1", value="Synthetic net 30", effective_from=EARLY
    )
    accepted = reviewer.decide(principal, str(first["review_case_id"]))
    (created,) = knowledge_events(reviewer.engine, principal)
    _assert_review_event(created, KnowledgeMutationKind.REVIEW_ACCEPT)
    assert created["record_id"] == accepted["assertion_id"]
    assert created["source_receipt_id"] == accepted["receipt_id"]
    assert created["record_version"] == 1
    # A second, different value for the single-current key: correct-and-accept
    # supersedes the accepted fact (predecessor state change, then creation).
    second = reviewer.queue(
        principal,
        profile,
        org,
        candidate="r2",
        value="Synthetic net 60",
        evidence=(external("obj-r2"),),
    )
    corrected = reviewer.decide(
        principal,
        str(second["review_case_id"]),
        Disposition.CORRECT_AND_ACCEPT,
        patch={"value": "Synthetic net 75", "effective_from": LATER.isoformat()},
    )
    events = knowledge_events(reviewer.engine, principal)
    assert len(events) == 3
    _assert_review_event(events[1], KnowledgeMutationKind.SUPERSEDE_PREDECESSOR)
    assert events[1]["record_id"] == accepted["assertion_id"]
    assert events[1]["record_version"] == 2
    _assert_review_event(events[2], KnowledgeMutationKind.REVIEW_CORRECT)
    assert events[2]["record_id"] == corrected["assertion_id"]


def test_proposals_and_non_promoting_decisions_emit_no_canonical_event(
    reviewer: ReviewRuntime,
) -> None:
    principal = new_principal()
    profile = reviewer.profile(principal)
    org = reviewer.entity(principal, "review-quiet")
    sequence = next_sequence(reviewer.engine, principal)
    queued = reviewer.queue(principal, profile, org)
    case = str(queued["review_case_id"])
    for version, disposition in enumerate(
        (Disposition.DEFER, Disposition.MARK_UNRESOLVED, Disposition.REJECT)
    ):
        reviewer.decide(principal, case, disposition, version=version)
    other = reviewer.queue(principal, profile, org, candidate="c2", value="Synthetic other")
    reviewer.decide(principal, str(other["review_case_id"]), Disposition.INVALIDATE)
    assert knowledge_events(reviewer.engine, principal) == []
    assert next_sequence(reviewer.engine, principal) == sequence
