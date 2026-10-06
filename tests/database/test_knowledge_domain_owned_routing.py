"""KLP-WP-04: DOMAIN_OWNED routes of autonomous submit on a real database.

KLP-AC-097 and KLP-AC-128 (database half). Marked `database` (auto
`database_clone`), routed to `database-current-head`.

* KLP-AC-097: `project.decision` completes `domain_owned_no_intake` with
  `result_canonical_owner = continuity_decision` and writes no assertion,
  proposal or subject-lock row; a decision-shaped candidate under another
  predicate (`project.financial_fact`) is `review_queued`.
* KLP-AC-128: a routed completion stores the owner (and the routed id when
  routed), creates no assertion/proposal/subject-lock row, and takes no Knowledge
  C5-C8 lock -- proven by a third session holding the subject-lock row of the
  same key `FOR UPDATE`: the routed submit completes without waiting, while a
  Knowledge-path submit on that key blocks on it (the control).
* `project.critical_date`: a resolving task ref routes to `tasks`; an
  unresolvable one is refused `owner_ref_invalid`; no ref goes to Review.
* `entity.communication_preference` is `domain_owned_no_intake` naming
  `relationship_memory` (KLP-WP-04 deviation).
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.application.commands import CreateTask
from my_pa.domain.knowledge_assertion.vocabulary import KnowledgeSubjectKind
from my_pa.domain.task.lifecycle import TaskOriginKind
from my_pa.infrastructure.persistence.tables import (
    knowledge_assertion_proposals,
    knowledge_assertion_subject_locks,
    knowledge_assertions,
)
from tests.concurrency.test_knowledge_shared_evidence_raise import (
    DEADLINE_SECONDS,
    _wait_for_waiters,
)
from tests.database.test_knowledge_assertion_repository import (
    capture_evidence,
    new_principal,
    submission_row,
)
from tests.database.test_knowledge_assertion_submissions import (
    SubmitRuntime,
    external,
    table_count,
)

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]

DECISION: Final = "project.decision"
CRITICAL: Final = "project.critical_date"
FINANCIAL: Final = "project.financial_fact"
PREFERENCE: Final = "entity.communication_preference"
CRITICAL_VALUE: Final = "2026-11-20T00:00:00+00:00"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[SubmitRuntime]:
    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _nothing_knowledge(engine: Engine, principal: str) -> None:
    for table in (
        knowledge_assertions,
        knowledge_assertion_proposals,
        knowledge_assertion_subject_locks,
    ):
        assert table_count(engine, table, principal) == 0, table.name


def _project_submit(
    runtime: SubmitRuntime,
    principal: str,
    profile: str,
    project: str,
    **fields: Any,  # noqa: ANN401 - the submit_command keywords
) -> dict[str, Any]:
    return runtime.submit(
        principal,
        profile,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        subject_id=project,
        evidence=(external("obj-route"),),
        **fields,
    )


def test_project_decision_is_no_intake_and_writes_no_knowledge_row(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    project = runtime.project(principal, "decision")
    result = _project_submit(
        runtime, principal, profile, project, predicate=DECISION, value="Synthetic decision"
    )
    assert result["outcome"] == "domain_owned_no_intake", result
    assert result["reason"] == "canonical_owner_no_intake"
    assert result["canonical_owner"] == "continuity_decision"
    row = submission_row(runtime.engine, result["submission_id"])
    assert row["submission_state"] == "completed"
    assert row["result_canonical_owner"] == "continuity_decision"
    assert row["result_routed_record_id"] is None
    _nothing_knowledge(runtime.engine, principal)


def test_a_decision_shaped_candidate_under_another_predicate_is_queued(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    project = runtime.project(principal, "decision-shaped")
    result = _project_submit(
        runtime,
        principal,
        profile,
        project,
        predicate=FINANCIAL,
        value="We decided to approve the synthetic budget",
    )
    assert result["outcome"] == "review_queued", result


def test_a_resolving_task_ref_routes_a_critical_date_to_tasks(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    project = runtime.project(principal, "critical")
    task = runtime.ok(
        CreateTask(
            title="Synthetic task",
            idempotency_key="klp04-task",
            origin_kind=TaskOriginKind.DIRECT_PRINCIPAL,
        ),
        principal_id=principal,
    )
    task_id = next(value for value in _strings(task) if value.startswith("tsk_"))
    result = _project_submit(
        runtime,
        principal,
        profile,
        project,
        predicate=CRITICAL,
        value=CRITICAL_VALUE,
        qualifier={"date_kind": "deadline"},
        owner_ref={"kind": "task", "id": task_id},
    )
    assert result["outcome"] == "domain_owned_routed", result
    assert result["canonical_owner"] == "tasks"
    assert result["routed_record_id"] == task_id
    assert submission_row(runtime.engine, result["submission_id"])["owner_ref_id"] == task_id
    _nothing_knowledge(runtime.engine, principal)


def test_an_unresolvable_owner_ref_is_refused(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    project = runtime.project(principal, "critical-bad")
    result = _project_submit(
        runtime,
        principal,
        profile,
        project,
        predicate=CRITICAL,
        value=CRITICAL_VALUE,
        qualifier={"date_kind": "deadline"},
        owner_ref={"kind": "meeting", "id": "mtg_" + "Abc123Def456Ghi7"},
    )
    assert result["outcome"] == "refused"
    assert result["reason"] == "owner_ref_invalid"
    _nothing_knowledge(runtime.engine, principal)


def test_a_critical_date_without_a_ref_goes_to_review(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    project = runtime.project(principal, "critical-review")
    result = runtime.submit(
        principal,
        profile,
        subject_kind=KnowledgeSubjectKind.PROJECT,
        subject_id=project,
        predicate=CRITICAL,
        value=CRITICAL_VALUE,
        qualifier={"date_kind": "deadline"},
        evidence=(external("obj-route"),),
    )
    assert result["outcome"] == "review_queued", result
    assert result["reason"] == "requires_operator"


def test_communication_preference_is_no_intake_naming_relationship_memory(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    person = runtime.entity(principal, "pref")
    capture = runtime.capture(principal, "pref")
    result = runtime.submit(
        principal,
        profile,
        subject_id=person,
        predicate=PREFERENCE,
        value="Prefers synthetic email",
        evidence=(capture_evidence(*capture),),
    )
    assert result["outcome"] == "domain_owned_no_intake", result
    assert result["canonical_owner"] == "relationship_memory"
    _nothing_knowledge(runtime.engine, principal)


def test_a_routed_submit_takes_no_knowledge_subject_lock(runtime: SubmitRuntime) -> None:
    """KLP-AC-128: the routed path never waits on C6; the Knowledge path does (control)."""
    principal = new_principal()
    profile = runtime.profile(principal)
    project = runtime.project(principal, "routed-lock")
    engine = runtime.engine
    with engine.begin() as connection:
        for predicate in (DECISION, FINANCIAL):
            connection.execute(
                text(
                    "INSERT INTO knowledge.knowledge_assertion_subject_locks (principal_id, "
                    "subject_kind, subject_id, predicate_code) VALUES (:p, 'project', :s, :c)"
                ),
                {"p": principal, "s": project, "c": predicate},
            )
    with engine.connect() as holder:
        holder.execute(
            text(
                "SELECT 1 FROM knowledge.knowledge_assertion_subject_locks WHERE principal_id = "
                ":p AND subject_id = :s ORDER BY predicate_code FOR UPDATE"
            ),
            {"p": principal, "s": project},
        ).all()
        with ThreadPoolExecutor(max_workers=1) as pool:
            routed = pool.submit(
                _project_submit,
                runtime,
                principal,
                profile,
                project,
                predicate=DECISION,
                value="Synthetic decision",
                candidate="routed",
            )
            # Completes while the key is held: no C6 (nor C5, C7, C8) lock.
            assert routed.result(timeout=DEADLINE_SECONDS)["outcome"] == "domain_owned_no_intake"
            knowledge = pool.submit(
                _project_submit,
                runtime,
                principal,
                profile,
                project,
                predicate=FINANCIAL,
                value="Synthetic financial fact",
                candidate="knowledge",
            )
            _wait_for_waiters(engine, 1, knowledge)
            holder.rollback()
            assert knowledge.result(timeout=DEADLINE_SECONDS)["outcome"] == "review_queued"


def _strings(document: object) -> list[str]:
    if isinstance(document, str):
        return [document]
    if isinstance(document, dict):
        return [item for value in document.values() for item in _strings(value)]
    if isinstance(document, list):
        return [item for value in document for item in _strings(value)]
    return []
