"""KLP-WP-03: every Knowledge surface and write is Principal-partitioned (KLP-AC-014).

Marked `database` (auto `database_clone`), routed to `database-current-head`.

* Another Principal's assertion answers every read surface exactly as an absent
  one does (`not_found`, or simply not listed), locally and remotely.
* The same idempotency key under two Principals is two independent ledgers.
* A create naming another Principal's Entity, Project or Principal subject is a
  `subject_not_canonical` refusal byte-identical to an absent subject, and a
  citation of another Principal's capture is the same `not_found` as an absent
  one.
* The feed never carries another Principal's Knowledge event.
* The database itself refuses a cross-Principal link, mutation or evidence
  citation (the composite same-Principal foreign keys).
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from tests.database.test_knowledge_assertion_repository import (
    LESSON,
    OPERATING,
    KnowledgeRuntime,
    capture_evidence,
    counts,
    create_command,
    new_principal,
)
from tests.security.test_knowledge_assertion_disclosure import REMOTE

from my_pa.application.commands import (
    GetKnowledgeAssertionHistory,
    ListKnowledgeAssertions,
    ListRecordEvents,
    ReadKnowledgeAssertion,
    RevealKnowledgeAssertion,
    SearchKnowledgeAssertions,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeSubjectKind
from my_pa.domain.source.registry import issue_identifier

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


def _without_correlation(error: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in error.items() if key != "correlation_id"}


@pytest.mark.parametrize("remote", [False, True], ids=["local", "remote"])
def test_a_foreign_assertion_answers_exactly_as_an_absent_one(
    runtime: KnowledgeRuntime, remote: bool
) -> None:
    owner, stranger = new_principal(), new_principal()
    created = runtime.create(owner, "klp03-iso", value="Requirement isolated value")
    absent = issue_identifier(IdKind.KNOWLEDGE_ASSERTION)
    extra = REMOTE if remote else {}
    for command_type in (
        ReadKnowledgeAssertion,
        GetKnowledgeAssertionHistory,
        RevealKnowledgeAssertion,
    ):
        foreign = runtime.error(
            command_type(assertion_id=created["assertion_id"]), principal_id=stranger, **extra
        )
        missing = runtime.error(command_type(assertion_id=absent), principal_id=stranger, **extra)
        assert foreign["code"] == "not_found"
        assert _without_correlation(foreign) == _without_correlation(missing)
    listed = runtime.ok(ListKnowledgeAssertions(), principal_id=stranger, **extra)
    searched = runtime.ok(
        SearchKnowledgeAssertions(query="isolated"), principal_id=stranger, **extra
    )
    assert listed["assertions"] == [] and listed["next_cursor"] is None
    assert searched["assertions"] == []
    events = runtime.ok(ListRecordEvents(), principal_id=stranger, **extra)
    assert created["assertion_id"] not in {item["record_id"] for item in events["events"]}
    owner_view = runtime.ok(
        ReadKnowledgeAssertion(assertion_id=created["assertion_id"]), principal_id=owner
    )
    assert owner_view["assertion"]["assertion_id"] == created["assertion_id"]


def test_one_key_under_two_principals_is_two_ledgers(runtime: KnowledgeRuntime) -> None:
    first, second = new_principal(), new_principal()
    a = runtime.create(first, "klp03-shared-key", value="Same text")
    b = runtime.create(second, "klp03-shared-key", value="Same text")
    assert a["outcome"] == b["outcome"] == "direct_created"
    assert a["assertion_id"] != b["assertion_id"]
    assert counts(runtime.engine, first)["knowledge_assertions"] == 1
    assert counts(runtime.engine, second)["knowledge_assertions"] == 1


@pytest.mark.parametrize("kind", ["entity", "project", "principal"])
def test_a_foreign_subject_is_the_same_refusal_as_an_absent_one(
    runtime: KnowledgeRuntime, kind: str
) -> None:
    owner, stranger = new_principal(), new_principal()
    if kind == "entity":
        foreign, absent = runtime.entity(owner, "iso-org"), issue_identifier(IdKind.ENTITY)
        subject_kind, predicate = KnowledgeSubjectKind.ENTITY, OPERATING
    elif kind == "project":
        foreign, absent = runtime.project(owner, "iso-prj"), issue_identifier(IdKind.PROJECT)
        subject_kind, predicate = KnowledgeSubjectKind.PROJECT, LESSON
    else:
        foreign, absent = owner, issue_identifier(IdKind.PRINCIPAL)
        subject_kind, predicate = KnowledgeSubjectKind.PRINCIPAL, LESSON
    answers = []
    for index, subject in enumerate((foreign, absent)):
        result = runtime.ok(
            create_command(
                f"klp03-iso-{kind}-{index}",
                subject_id=subject,
                subject_kind=subject_kind,
                predicate=predicate,
            ),
            principal_id=stranger,
        )
        result.pop("submission_id")
        answers.append(result)
    assert answers[0] == answers[1]
    assert (answers[0]["outcome"], answers[0]["reason"]) == ("refused", "subject_not_canonical")
    assert counts(runtime.engine, stranger)["knowledge_assertions"] == 0
    assert counts(runtime.engine, owner)["knowledge_assertions"] == 0


def test_the_database_refuses_a_cross_principal_link_mutation_and_citation(
    runtime: KnowledgeRuntime,
) -> None:
    owner, stranger = new_principal(), new_principal()
    capture_id, digest = runtime.capture(owner, "iso-cite")
    mine = runtime.create(owner, "klp03-db-iso", evidence=(capture_evidence(capture_id, digest),))
    theirs = runtime.create(stranger, "klp03-db-iso-2")
    with runtime.engine.connect() as connection:
        evidence = connection.execute(
            text(
                "SELECT evidence_ref_id FROM knowledge.knowledge_evidence_refs "
                "WHERE principal_id = :p"
            ),
            {"p": owner},
        ).scalar_one()
    statements = [
        (
            "INSERT INTO knowledge.knowledge_assertion_evidence_links (principal_id, "
            "assertion_id, evidence_ref_id, evidence_role, linked_by_mutation_id, created_at) "
            "VALUES (:p, :a, :e, 'supporting', :m, now())",
            {"p": stranger, "a": theirs["assertion_id"], "e": evidence, "m": theirs["mutation_id"]},
        ),
        (
            "INSERT INTO knowledge.knowledge_assertion_mutations (principal_id, mutation_id, "
            "assertion_id, mutation_kind, prior_version, new_version, created_at) VALUES "
            "(:p, :m, :a, 'archive', 1, 2, now())",
            {
                "p": stranger,
                "m": issue_identifier(IdKind.KNOWLEDGE_ASSERTION_MUTATION),
                "a": mine["assertion_id"],
            },
        ),
        (
            "INSERT INTO knowledge.knowledge_evidence_refs (principal_id, evidence_ref_id, "
            "identity_kind, capture_id, content_hash, content_origin, source_classification, "
            "created_at, updated_at) VALUES (:p, :e, 'capture', :c, :h, 'capture', "
            "'private_local', now(), now())",
            {
                "p": stranger,
                "e": issue_identifier(IdKind.KNOWLEDGE_EVIDENCE_REF),
                "c": capture_id,
                "h": digest,
            },
        ),
    ]
    for statement, parameters in statements:
        with pytest.raises(IntegrityError), runtime.engine.begin() as connection:
            connection.execute(text(statement), parameters)
