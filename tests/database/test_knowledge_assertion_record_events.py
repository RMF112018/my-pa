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
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import select, text

from my_pa.application.commands import ListRecordEvents
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
from my_pa.infrastructure.persistence.tables import knowledge_assertions
from tests.database.test_knowledge_assertion_repository import (
    DECISION,
    FINANCIAL,
    LESSON,
    KnowledgeRuntime,
    capture_evidence,
    create_command,
    knowledge_events,
    new_principal,
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
