"""KLP-WP-04: autonomous submit vs source-profile disable (real DB race).

KLP-AC-156 and the submit half of KLP-AC-090. Marked `database` (auto
`database_clone`), routed to `database-current-head`.

A production submit takes the active profile `FOR SHARE` at C4a and re-reads
`disabled_at`; a holder session keeps the cited (pre-existing) evidence row
`FOR UPDATE`, so the submit pauses at C4b *after* C4a (observed). The production
disable (the operator command's maintenance transaction, `FOR NO KEY UPDATE`)
then blocks behind the submit's share lock (observed: two waiters). On release
the submit commits `direct_created`, the disable commits, and the next submit
on that profile is refused `source_profile_inactive` -- a refusal that deletes
and rewrites no Knowledge row.
"""

from __future__ import annotations

from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor

import pytest
from sqlalchemy import select, text
from tests.concurrency.test_knowledge_shared_evidence_raise import (
    DEADLINE_SECONDS,
    _wait_for_waiters,
)
from tests.database.test_knowledge_assertion_repository import counts, new_principal
from tests.database.test_knowledge_assertion_submissions import SubmitRuntime, external

from my_pa.infrastructure.persistence.tables import knowledge_evidence_refs

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


def test_disable_blocks_until_the_submit_commits_then_refuses_the_next(
    runtime: SubmitRuntime,
) -> None:
    principal = new_principal()
    profile = runtime.profile(principal)
    seed_org, org, later_org = (runtime.entity(principal, f"disable-{k}") for k in "abc")
    seeded = runtime.submit(principal, profile, subject_id=seed_org, candidate="seed")
    assert seeded["outcome"] == "direct_created"
    engine = runtime.engine
    with engine.connect() as connection:
        evidence = connection.execute(
            select(knowledge_evidence_refs.c.evidence_ref_id).where(
                knowledge_evidence_refs.c.principal_id == principal
            )
        ).scalar_one()
    with engine.connect() as holder:
        holder.execute(
            text(
                "SELECT 1 FROM knowledge.knowledge_evidence_refs WHERE evidence_ref_id = :e "
                "FOR UPDATE"
            ),
            {"e": evidence},
        ).one()
        with ThreadPoolExecutor(max_workers=2) as pool:
            writer = pool.submit(
                runtime.submit,
                principal,
                profile,
                subject_id=org,
                candidate="paused",
                value="Paused synthetic requirement",
                evidence=(external("obj-1"),),
            )
            _wait_for_waiters(engine, 1, writer)  # at C4b, holding C4a FOR SHARE
            disabling = pool.submit(runtime.disable, principal, profile)
            _wait_for_waiters(engine, 2, writer, disabling)
            assert not disabling.done()
            holder.rollback()
            paused = writer.result(timeout=DEADLINE_SECONDS)
            disabling.result(timeout=DEADLINE_SECONDS)
    assert paused["outcome"] == "direct_created", paused
    before = counts(engine, principal)
    refused = runtime.submit(principal, profile, subject_id=later_org, candidate="after")
    assert refused["outcome"] == "refused"
    assert refused["reason"] == "source_profile_inactive"
    after = counts(engine, principal)
    assert after["knowledge_assertion_submissions"] == before["knowledge_assertion_submissions"] + 1
    assert {k: v for k, v in after.items() if k != "knowledge_assertion_submissions"} == {
        k: v for k, v in before.items() if k != "knowledge_assertion_submissions"
    }
