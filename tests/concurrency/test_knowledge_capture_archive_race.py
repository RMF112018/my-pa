"""KLP-WP-04: autonomous submit vs `capture.archive` (real DB races).

KLP-AC-112 (submit half) and the rolled-back half of KLP-AC-102. Marked
`database` (auto `database_clone`), routed to `database-current-head`.

* **Submit holds the fence first** -- a production submit citing a Capture
  pauses at C6 (a holder session keeps the subject-lock row), so it already
  holds its C4c `FOR SHARE` on the Capture root; a production `capture.archive`
  then blocks on its conflicting root lock (observed). On release the submit
  commits its link and the archive completes, writing nothing in Knowledge
  (no fan-out: the assertion stays `active`, no row is added).
* **Archive between C2 and C4c** -- the submit's C2 lifecycle read sees an
  active root, then it waits at C4b on the cited (pre-existing) evidence row a
  holder keeps `FOR UPDATE`. The archive runs to completion meanwhile -- the
  Knowledge path has taken no Capture lock before C4c (R6 8.3: Entity and
  evidence locks never block the archive). On release the one C4c fence refuses
  the archived root: `denied(capture_withdrawn)`, and the whole transaction --
  reservation included -- rolls back (no submission, link, mutation or event).
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, text
from tests.concurrency.test_knowledge_assertion_concurrency import hold_subject_lock
from tests.concurrency.test_knowledge_shared_evidence_raise import (
    DEADLINE_SECONDS,
    _wait_for_waiters,
)
from tests.database.test_knowledge_assertion_repository import (
    capture_evidence,
    counts,
    new_principal,
)
from tests.database.test_knowledge_assertion_submissions import (
    OPERATING,
    SubmitRuntime,
    external,
)

from my_pa.application.commands import ArchiveCapture
from my_pa.infrastructure.persistence.tables import knowledge_assertions, knowledge_evidence_refs

pytestmark = [
    pytest.mark.database,
    pytest.mark.filterwarnings("error::sqlalchemy.exc.SAWarning"),
]


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[SubmitRuntime]:
    composed = SubmitRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _archive(runtime: SubmitRuntime, principal: str, capture_id: str) -> None:
    runtime.ok(
        ArchiveCapture(
            capture_id=capture_id,
            expected_lifecycle_revision=0,
            idempotency_key=f"klp04-race-archive-{capture_id}",
            reason="Synthetic archive race",
        ),
        principal_id=principal,
    )


def test_an_archive_waits_for_a_submit_holding_the_capture_fence(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    org = runtime.entity(principal, "fence-first")
    capture = runtime.capture(principal, "fence-first")
    engine = runtime.engine
    with engine.begin() as connection:
        hold_subject_lock(connection, principal, "entity", org, OPERATING)
    with engine.connect() as holder:
        hold_subject_lock(holder, principal, "entity", org, OPERATING)
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(
                runtime.submit,
                principal,
                profile,
                subject_id=org,
                evidence=(external("obj-fence"), capture_evidence(*capture, role="supporting")),
            )
            _wait_for_waiters(engine, 1, writer)  # at C6, C4c share held
            archive = pool.submit(_archive, runtime, principal, capture[0])
            _wait_for_waiters(engine, 2, writer, archive)
            holder.rollback()
            created = writer.result(timeout=DEADLINE_SECONDS)
            after_submit = counts(engine, principal)
            archive.result(timeout=DEADLINE_SECONDS)
    assert created["outcome"] == "direct_created", created
    # The archive fans out into nothing in Knowledge.
    assert counts(engine, principal) == after_submit
    with engine.connect() as connection:
        lifecycle = connection.execute(
            select(knowledge_assertions.c.lifecycle).where(
                knowledge_assertions.c.assertion_id == created["assertion_id"]
            )
        ).scalar_one()
    assert lifecycle == "active"


def test_an_archive_before_the_fence_rolls_the_whole_submit_back(runtime: SubmitRuntime) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    capture = runtime.capture(principal, "fence-late")
    seed_org, org = runtime.entity(principal, "fence-seed"), runtime.entity(principal, "fence-late")
    seeded = runtime.submit(
        principal,
        profile,
        subject_id=seed_org,
        candidate="seed",
        value="Seed requirement",
        evidence=(external("obj-seed"), capture_evidence(*capture, role="supporting")),
    )
    assert seeded["outcome"] == "direct_created"
    engine = runtime.engine
    with engine.connect() as connection:
        capture_row = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal,
                knowledge_evidence_refs.c.identity_kind == "capture",
            )
        ).scalar_one()
    before = counts(engine, principal)
    with engine.connect() as holder:
        holder.execute(
            text(
                "SELECT 1 FROM knowledge.knowledge_evidence_refs WHERE evidence_ref_id = :e "
                "FOR UPDATE"
            ),
            {"e": capture_row},
        ).one()
        with ThreadPoolExecutor(max_workers=1) as pool:
            writer = pool.submit(
                runtime.invoke,
                runtime.submit_command(
                    principal,
                    profile,
                    subject_id=org,
                    evidence=(external("obj-late"), capture_evidence(*capture, role="supporting")),
                ),
                principal_id=principal,
                **_remote(),
            )
            _wait_for_waiters(engine, 1, writer)  # at C4b, after the C2 lifecycle read
            # The archive is not blocked by any Knowledge lock taken so far.
            _archive(runtime, principal, capture[0])
            holder.rollback()
            envelope = writer.result(timeout=DEADLINE_SECONDS)
    assert envelope.error is not None
    assert envelope.error.code.value == "denied"
    assert "capture_withdrawn" in envelope.error.safe_details
    assert counts(engine, principal) == before


def _remote() -> dict[str, object]:
    from tests.database.test_knowledge_assertion_submissions import CLIENT, SUBMIT_GRANTS

    from my_pa.domain.capture.submission import CaptureTransport

    return {
        "transport": CaptureTransport.REMOTE_CLIENT,
        "grants": SUBMIT_GRANTS,
        "client_id": CLIENT,
    }
