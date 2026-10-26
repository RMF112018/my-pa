"""Record lineage S3.1: the client write budget under concurrency (R31-F13, database).

S3.1 contract section 4.8 against PostgreSQL. The count is read after the
commit mark: the Principal's allocator row stays locked from the mark to
commit, so a Principal's lineage writers serialize there and the count each
reads cannot move before it commits. Two client writes racing at the last free
place of a bucket therefore admit exactly one; the other is `rate_limited`.

The race holds the allocator row on a separate connection, starts both
writers, waits until PostgreSQL reports both waiting, and only then releases
it, so the two really overlap. Each wait is bounded and each thread joined
with a timeout. Every identity is synthetic.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_s2_harness import assertion
from tests.database.lineage_s3_harness import corroborates
from tests.database.lineage_s31_harness import (
    REMOTE_CLIENT,
    S31Runtime,
    completed_requests,
    open_scene,
    seed_completed_requests,
)

from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.lineage.vocabulary import CLIENT_LINEAGE_WRITES_PER_HOUR

pytestmark = pytest.mark.database

BLOCK_DEADLINE_SECONDS: Final = 15.0
JOIN_TIMEOUT_SECONDS: Final = 60.0


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31Runtime]:
    composed = S31Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _waiting(engine: Engine) -> int:
    with engine.connect() as observer:
        return int(
            observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
        )


def _detail(envelope: ResponseEnvelope) -> tuple[str, list[str]] | None:
    error = envelope.to_canonical_dict().get("error")
    assert error is None or isinstance(error, dict)
    return None if error is None else (str(error["code"]), list(error["safe_details"]))


def test_concurrent_client_writes_at_the_budget_boundary_admit_exactly_one(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "race")
    commands: list[Any] = []
    for key in ("one", "two"):
        task_a = runtime.task(f"race-{key}-a")
        task_b = runtime.task(f"race-{key}-b")
        commands.append(
            assertion(
                "blocks",
                ("task", task_a),
                ("task", task_b),
                f"race-{key}",
                (corroborates(scene.meeting, scene.note),),
            )
        )
    seed_completed_requests(
        runtime.engine,
        CLIENT_LINEAGE_WRITES_PER_HOUR - 1,
        issue_id=scene.issue,
        channel="remote_interactive",
        client=REMOTE_CLIENT,
    )
    with runtime.engine.connect() as holder, ThreadPoolExecutor(max_workers=2) as pool:
        held = holder.begin()
        # The allocator row every lineage writer of the Principal locks at its mark.
        holder.execute(
            text(
                "SELECT principal_id FROM knowledge.lineage_commit_sequences"
                " WHERE principal_id = :principal FOR UPDATE"
            ),
            {"principal": PRINCIPAL},
        ).one()
        futures: list[Future[ResponseEnvelope]] = []
        for command in commands:
            futures.append(pool.submit(runtime.client, command))
            deadline = time.monotonic() + BLOCK_DEADLINE_SECONDS
            while _waiting(runtime.engine) < len(futures):
                assert not any(future.done() for future in futures), "a writer did not wait"
                assert time.monotonic() < deadline, "the writers never blocked"
                time.sleep(0.02)
        held.rollback()
        outcomes = [_detail(future.result(timeout=JOIN_TIMEOUT_SECONDS)) for future in futures]
    assert sorted(outcomes, key=lambda item: item is not None) == [
        None,
        ("rate_limited", ["lineage_write_budget"]),
    ]
    assert (
        completed_requests(runtime.engine, channel="remote_interactive", client=REMOTE_CLIENT)
        == CLIENT_LINEAGE_WRITES_PER_HOUR
    )
