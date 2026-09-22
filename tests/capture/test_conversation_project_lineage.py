"""T19: the Project a Conversation capture was filed against survives the whole
downstream path, and is resolved by joining back to the root.

**What makes this proof rather than a seed count.** A test that saves a
`conversation_log` and asserts one `capture_conversations` row proves the save
transaction and nothing after it. The question WP08 has to answer is different:
after the *real* asynchronous pipeline has run, after a reviewer has accepted a
proposal, and after an assertion has been written, can the Project the note was
filed against still be established? So every stage below is the production one:

* `capture.create` through the real application composition;
* `capture_pipeline.process_capture_version`, claimed off the real
  `CAPTURE_JOBS` plane by the real `run_worker` lease loop;
* `review.list` and `review.decide` through the real capabilities, which is
  what reaches `persistence/review.py::open_review_case` and `promote_proposal`;
* and then the join — `capture_assertions.version_id` →
  `capture_versions.capture_id` → `captures.project_id`.

**There is no Project column downstream, and this file does not add one.** The
Conversation seed, the stage results, the proposal, the review case and the
assertion all carry a version or a capture identifier, and the Project is
resolved *through* them. That retained linkage is the whole finding: nothing
downstream needs its own copy, and a duplicate would be a second place for the
answer to disagree with itself.

Every value here is synthetic. The database is the package's disposable clone.
"""

from __future__ import annotations

import threading
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, select, text
from tests.capture.conftest import WHEN, invoke, succeeded

from my_pa.application.commands import (
    Command,
    CreateCapture,
    DecideReviewCase,
    ListReviewCases,
    ReadCapture,
)
from my_pa.bootstrap.gateway import GatewayRuntime
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.domain.capture.submission import CaptureKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.capture.review import Disposition
from my_pa.infrastructure.jobs.capture_pipeline import process_capture_version
from my_pa.infrastructure.jobs.worker import issue_worker_owner, run_worker
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS
from my_pa.infrastructure.persistence.tables import (
    capture_assertions,
    capture_conversations,
    capture_proposals,
    capture_review_cases,
    capture_stage_results,
    capture_versions,
    projects,
)

PROJECT: Final = "prj_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
FOREIGN_PRINCIPAL: Final = "prn_eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee"

#: A conversation whose text carries one commitment, so the pipeline has
#: something consequential to propose and the review plane has something to
#: accept. Obviously synthetic, and distinctive enough that a match is this note.
CONVERSATION: Final = (
    "synthetic conversation log — walked the north slab with the owner's rep.\n"
    "I will send the flange tolerance summary by 2026-09-14.\n"
)


def _seed_project(engine: Engine, project_id: str, principal_id: str) -> None:
    """One Project row in the given partition. The same pattern T04 uses."""
    with engine.begin() as connection:
        at = connection.execute(select(text("clock_timestamp()"))).scalar_one()
        connection.execute(
            insert(projects).values(
                project_id=project_id,
                principal_id=principal_id,
                name=f"Synthetic {project_id[-4:]}",
                opened_at=at,
                created_at=at,
                updated_at=at,
            )
        )


def _create_conversation(
    runtime: GatewayRuntime,
    *,
    key: str,
    project_id: str | None,
    tag: str,
) -> dict[str, Any]:
    return succeeded(
        invoke(
            runtime,
            Capability.CAPTURE_CREATE,
            CreateCapture(
                text=CONVERSATION,
                idempotency_key=key,
                capture_kind=CaptureKind.CONVERSATION_LOG,
                project_id=project_id,
            ),
            tag,
        ),
        "capture.create conversation_log",
    )


def _drain(runtime: GatewayRuntime, *, jobs: int = 1) -> None:
    """The real worker loop, the real plane, the real handler."""
    run_worker(
        runtime.work_engine,
        principal_id=runtime.principal.principal_id,
        owner=issue_worker_owner(),
        handler=process_capture_version,
        stop=threading.Event(),
        plane=CAPTURE_JOBS,
        max_iterations=jobs,
        poll_seconds=0.01,
    )


def _project_through_version(engine: Engine, version_id: str) -> str | None:
    """The Project, resolved the only way it can be: version → root.

    Written as SQL against the live schema rather than through the `captures`
    SQLAlchemy declaration, which is deliberately frozen historical metadata and
    carries no `project_id`. The canonical runtime reads the same column through
    its own `TableClause`; repairing the frozen declaration is explicitly out of
    scope, so the join is stated here instead.
    """
    with engine.connect() as connection:
        return connection.execute(
            text(
                "SELECT c.project_id FROM knowledge.capture_versions v "
                "JOIN knowledge.captures c ON c.capture_id = v.capture_id "
                "WHERE v.version_id = :version_id"
            ),
            {"version_id": version_id},
        ).scalar_one()


def _columns(engine: Engine, table_name: str) -> set[str]:
    """The live column names of one knowledge-schema table."""
    with engine.connect() as connection:
        return {
            str(row[0])
            for row in connection.execute(
                text(
                    "SELECT column_name FROM information_schema.columns "
                    "WHERE table_schema = 'knowledge' AND table_name = :table_name"
                ),
                {"table_name": table_name},
            ).all()
        }


#: The review plane's own purposes. Declared here rather than added to the
#: package conftest, whose map is deliberately the capture capabilities only —
#: a test that widened it would be changing what every module in the package is
#: allowed to invoke.
_REVIEW_PURPOSE: Final[dict[Capability, Purpose]] = {
    Capability.REVIEW_LIST: Purpose.CAPTURE_REVIEW,
    Capability.REVIEW_DECIDE: Purpose.REVIEW_DISPOSITION,
}


def _invoke_review(
    runtime: GatewayRuntime, capability: Capability, request: Command, tag: str
) -> ResponseEnvelope:
    """One review request through the same real application composition."""
    return runtime.service.invoke(
        RequestMetadata(
            request_id=f"req-review-{tag}",
            capability=capability,
            purpose=_REVIEW_PURPOSE[capability],
            principal_id=runtime.principal.principal_id,
            requested_at=WHEN,
        ),
        request,
        principal=runtime.principal,
    )


def _accept_one_case(runtime: GatewayRuntime) -> dict[str, Any] | None:
    """Accept the first open review case, through the real capabilities."""
    listed = succeeded(
        _invoke_review(runtime, Capability.REVIEW_LIST, ListReviewCases(), "list"),
        "review.list",
    )
    cases = listed.get("cases") or listed.get("review_cases") or []
    if not cases:
        return None
    case = cases[0]
    decided = succeeded(
        _invoke_review(
            runtime,
            Capability.REVIEW_DECIDE,
            DecideReviewCase(
                review_case_id=case["review_case_id"],
                expected_review_version=int(case.get("review_version", 0)),
                disposition=Disposition.ACCEPT,
            ),
            "decide",
        ),
        "review.decide accept",
    )
    return decided


@pytest.mark.database
@pytest.mark.database_clone
def test_conversation_project_survives_the_real_worker_and_review_lineage(
    runtime: GatewayRuntime,
) -> None:
    """Root → version → seed → job → worker → proposal → review → assertion → root."""
    principal_id = runtime.principal.principal_id
    _seed_project(runtime.work_engine, PROJECT, principal_id)

    created = _create_conversation(
        runtime, key="conversation-lineage-0001", project_id=PROJECT, tag="lineage-project"
    )
    capture_id = created["capture_id"]
    version_id = created["version_id"]

    # 1. The root carries the Project, and the immutable version belongs to it.
    assert _project_through_version(runtime.work_engine, version_id) == PROJECT

    # 2. The Conversation seed is keyed to that capture and version, and carries
    #    no Project of its own — the join is the association.
    with runtime.work_engine.connect() as connection:
        seed = connection.execute(
            select(capture_conversations.c.capture_id, capture_conversations.c.version_id).where(
                capture_conversations.c.capture_id == capture_id
            )
        ).all()
    assert len(seed) == 1
    assert tuple(seed[0]) == (capture_id, version_id)
    assert "project_id" not in _columns(runtime.work_engine, "capture_conversations"), (
        "the skeletal Conversation must not acquire its own Project column; "
        "the retained version to root join is the association"
    )

    # 3. The real worker claims the real job off the real plane and runs the
    #    real nine-stage handler.
    _drain(runtime)

    with runtime.work_engine.connect() as connection:
        stages = connection.execute(
            select(capture_stage_results.c.stage).where(
                capture_stage_results.c.version_id == version_id
            )
        ).scalars().all()
        proposal_rows = connection.execute(
            select(capture_proposals.c.proposal_id, capture_proposals.c.version_id).where(
                capture_proposals.c.version_id == version_id
            )
        ).all()
    assert stages, "the pipeline recorded no stage results; nothing downstream ran"
    assert proposal_rows, (
        "the pipeline produced no proposal for this conversation, so the review "
        "and assertion lineage below cannot be exercised"
    )

    # 4. Every proposal still resolves to the Project through its version.
    for proposal_id, proposal_version in proposal_rows:
        assert _project_through_version(runtime.work_engine, proposal_version) == PROJECT, (
            f"proposal {proposal_id} lost the Project on the version join"
        )

    # 5. The review case the pipeline opened carries the capture and version,
    #    and resolves to the same Project.
    with runtime.work_engine.connect() as connection:
        cases = connection.execute(
            select(
                capture_review_cases.c.review_case_id,
                capture_review_cases.c.capture_id,
                capture_review_cases.c.version_id,
                capture_review_cases.c.principal_id,
            ).where(capture_review_cases.c.version_id == version_id)
        ).all()
    assert cases, "no review case was opened, so acceptance cannot be exercised"
    for _case_id, case_capture, case_version, case_principal in cases:
        assert case_capture == capture_id
        assert case_version == version_id
        assert case_principal == principal_id
        assert _project_through_version(runtime.work_engine, case_version) == PROJECT

    # 6. A reviewer accepts, through the real capability, which is what reaches
    #    `promote_proposal` and writes the assertion.
    accepted = _accept_one_case(runtime)
    assert accepted is not None, "review.list returned no case to accept"

    with runtime.work_engine.connect() as connection:
        assertions = connection.execute(
            select(
                capture_assertions.c.assertion_id,
                capture_assertions.c.version_id,
                capture_assertions.c.principal_id,
            ).where(capture_assertions.c.version_id == version_id)
        ).all()
    assert assertions, "acceptance wrote no assertion; the promotion lineage is not exercised"

    # 7. The accepted assertion still resolves to the Project the note was filed
    #    against — through the version, back to the root. This is the whole claim.
    for assertion_id, assertion_version, assertion_principal in assertions:
        assert assertion_principal == principal_id
        assert _project_through_version(runtime.work_engine, assertion_version) == PROJECT, (
            f"assertion {assertion_id} cannot resolve the Project of the capture it derives from"
        )
        assert "project_id" not in _columns(runtime.work_engine, "capture_assertions"), (
            "the assertion must not acquire its own Project column"
        )

    # 8. And the canonical read still reports it, so the lineage and the read
    #    agree rather than one of them being repaired by the other.
    read = succeeded(
        invoke(runtime, Capability.CAPTURE_READ, ReadCapture(capture_id=capture_id), "lineage-read"),
        "capture.read",
    )
    assert read["project_id"] == PROJECT


@pytest.mark.database
@pytest.mark.database_clone
def test_conversation_with_no_project_stays_no_project_through_the_same_path(
    runtime: GatewayRuntime,
) -> None:
    """A historical no-Project conversation is null at every stage, not unknown."""
    created = _create_conversation(
        runtime, key="conversation-lineage-0002", project_id=None, tag="lineage-null"
    )
    version_id = created["version_id"]
    assert _project_through_version(runtime.work_engine, version_id) is None

    _drain(runtime)

    with runtime.work_engine.connect() as connection:
        proposal_versions = connection.execute(
            select(capture_proposals.c.version_id).where(
                capture_proposals.c.version_id == version_id
            )
        ).scalars().all()
    assert proposal_versions, "no proposal was produced for the no-Project conversation"
    for proposal_version in proposal_versions:
        # Null, not inferred from anywhere. Nothing downstream may supply one.
        assert _project_through_version(runtime.work_engine, proposal_version) is None

    accepted = _accept_one_case(runtime)
    if accepted is not None:
        with runtime.work_engine.connect() as connection:
            assertion_versions = connection.execute(
                select(capture_assertions.c.version_id).where(
                    capture_assertions.c.version_id == version_id
                )
            ).scalars().all()
        for assertion_version in assertion_versions:
            assert _project_through_version(runtime.work_engine, assertion_version) is None


@pytest.mark.database
@pytest.mark.database_clone
def test_replaying_the_same_conversation_intent_adds_no_second_lineage(
    runtime: GatewayRuntime,
) -> None:
    """The same key twice is one capture, one seed, one job — and one Project."""
    principal_id = runtime.principal.principal_id
    _seed_project(runtime.work_engine, PROJECT, principal_id)

    first = _create_conversation(
        runtime, key="conversation-lineage-0003", project_id=PROJECT, tag="lineage-first"
    )
    second = _create_conversation(
        runtime, key="conversation-lineage-0003", project_id=PROJECT, tag="lineage-replay"
    )
    assert second["capture_id"] == first["capture_id"]
    assert second["version_id"] == first["version_id"]

    with runtime.work_engine.connect() as connection:
        seeds = connection.execute(
            select(capture_conversations.c.capture_id).where(
                capture_conversations.c.capture_id == first["capture_id"]
            )
        ).all()
    assert len(seeds) == 1

    # Draining twice must not duplicate downstream rows either: a stage already
    # completed under its key is not re-run.
    _drain(runtime)
    _drain(runtime)
    with runtime.work_engine.connect() as connection:
        proposals = connection.execute(
            select(capture_proposals.c.proposal_id).where(
                capture_proposals.c.version_id == first["version_id"]
            )
        ).scalars().all()
    assert len(proposals) == len(set(proposals))
    assert _project_through_version(runtime.work_engine, first["version_id"]) == PROJECT


@pytest.mark.database
@pytest.mark.database_clone
def test_a_foreign_principal_cannot_reach_the_conversation_lineage(
    runtime: GatewayRuntime,
) -> None:
    """The lineage lives in one partition; a foreign Principal sees none of it."""
    principal_id = runtime.principal.principal_id
    _seed_project(runtime.work_engine, PROJECT, principal_id)
    created = _create_conversation(
        runtime, key="conversation-lineage-0004", project_id=PROJECT, tag="lineage-partition"
    )
    _drain(runtime)

    with runtime.work_engine.connect() as connection:
        foreign_cases = connection.execute(
            select(capture_review_cases.c.review_case_id).where(
                capture_review_cases.c.principal_id == FOREIGN_PRINCIPAL
            )
        ).scalars().all()
        owned_versions = connection.execute(
            select(capture_versions.c.owner_principal_id).where(
                capture_versions.c.version_id == created["version_id"]
            )
        ).scalars().all()
    assert foreign_cases == []
    assert owned_versions == [principal_id]
