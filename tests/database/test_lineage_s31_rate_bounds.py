"""Record lineage S3.1: the client lineage write budgets (database).

S3.1 contract sections 4.8 and 6.2 step 7 through `ApplicationService.invoke`
against PostgreSQL (worker N2). Every non-attested lineage write of a client
channel counts against 2 rolling budgets of its writer bucket --
`(decision_channel, asserting_client_id)` -- and 1 of the Principal: 120 an
hour and 1000 a day per bucket, 2000 a day per Principal. Reaching one answers
`rate_limited` / `lineage_write_budget` (bounded retry) and writes nothing.
Replays and refusals never consume budget; the human channel is never counted
or limited; every OAuth client has its own bucket while stdio and unstamped
local callers share one; an identity answered `created: false` is checked and
counted; a composite past its budget creates no native record.

The budgets are filled with synthetic completed request rows
(`seed_completed_requests`), the rows the bound counts. Every identity here is
synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import replace
from typing import Any, Final

import pytest
from sqlalchemy import text

from my_pa.application.commands import CreateIssue
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.lineage.vocabulary import (
    CLIENT_LINEAGE_WRITES_PER_DAY,
    CLIENT_LINEAGE_WRITES_PER_HOUR,
    PRINCIPAL_CLIENT_LINEAGE_WRITES_PER_DAY,
)
from my_pa.domain.source.registry import issue_identifier
from tests.database.lineage_record_harness import all_lineage_counts, membership
from tests.database.lineage_s2_harness import assertion, work_task
from tests.database.lineage_s3_harness import corroborates
from tests.database.lineage_s31_harness import (
    GATEWAY,
    OTHER_CLIENT,
    REMOTE_CLIENT,
    OpenScene,
    S31Runtime,
    completed_requests,
    open_scene,
    seed_completed_requests,
)

pytestmark = pytest.mark.database

_REMOTE: Final = "remote_interactive"
_LOCAL: Final = "local_unattested"
_THIRD_CLIENT: Final = "synthetic-lineage-third-client"
_ABSENT_TASK: Final = issue_identifier(IdKind.TASK)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S31Runtime]:
    composed = S31Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _limited(error: dict[str, Any]) -> bool:
    return (error["code"], error["safe_details"]) == ("rate_limited", ["lineage_write_budget"])


def _fill(
    runtime: S31Runtime,
    issue_id: str,
    up_to: int,
    *,
    channel: str = _REMOTE,
    client: str | None = REMOTE_CLIENT,
) -> None:
    """Seed the bucket's completed rows up to `up_to` within the hour."""
    missing = up_to - completed_requests(runtime.engine, channel=channel, client=client)
    if missing > 0:
        seed_completed_requests(
            runtime.engine, missing, issue_id=issue_id, channel=channel, client=client
        )


def _member(scene: OpenScene, key: str) -> Any:  # noqa: ANN401
    return membership(scene.issue, "task", scene.member_task, key, role="reference")


def _blocks(runtime: S31Runtime, scene: OpenScene, key: str) -> Any:  # noqa: ANN401
    task_a = runtime.task(f"{key}-a")
    task_b = runtime.task(f"{key}-b")
    return assertion(
        "blocks",
        ("task", task_a),
        ("task", task_b),
        key,
        (corroborates(scene.meeting, scene.note),),
    )


def test_a_client_past_its_hourly_budget_is_rate_limited_and_writes_nothing(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "hourly")
    _fill(runtime, scene.issue, CLIENT_LINEAGE_WRITES_PER_HOUR)
    before = all_lineage_counts(runtime.engine)
    error = runtime.client_refused(_member(scene, "hourly"))
    assert _limited(error)
    assert error["retry"] == "bounded_retry"
    # The recorded Issue writes are bounded too.
    assert _limited(runtime.client_refused(CreateIssue(title="Over", idempotency_key="s31-over")))
    assert all_lineage_counts(runtime.engine) == before
    assert completed_requests(runtime.engine, channel=_REMOTE, client=REMOTE_CLIENT) == (
        CLIENT_LINEAGE_WRITES_PER_HOUR
    )


def test_the_daily_and_principal_budgets_bound_client_writes(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "daily")
    # Older than an hour, within the day: the hourly budget is free, the daily full.
    seed_completed_requests(
        runtime.engine,
        CLIENT_LINEAGE_WRITES_PER_DAY,
        issue_id=scene.issue,
        channel=_REMOTE,
        client=REMOTE_CLIENT,
        age="2 hours",
    )
    # Rows older than a day never count.
    seed_completed_requests(
        runtime.engine,
        50,
        issue_id=scene.issue,
        channel=_REMOTE,
        client=OTHER_CLIENT,
        age="25 hours",
        prefix="old",
    )
    assert _limited(runtime.client_refused(_member(scene, "daily")))
    runtime.client_ok(_member(scene, "daily-other"), client=OTHER_CLIENT)
    # The Principal's budget: every client bucket within the day.
    seed_completed_requests(
        runtime.engine,
        PRINCIPAL_CLIENT_LINEAGE_WRITES_PER_DAY - CLIENT_LINEAGE_WRITES_PER_DAY - 1,
        issue_id=scene.issue,
        channel=_LOCAL,
        client=None,
        age="3 hours",
    )
    before = all_lineage_counts(runtime.engine)
    for caller in (
        lambda command: runtime.client_refused(command, client=_THIRD_CLIENT),
        lambda command: runtime.client_refused(command, client=OTHER_CLIENT),
        runtime.local_refused,
    ):
        assert _limited(caller(_blocks(runtime, scene, f"principal-{id(caller)}")))
    assert all_lineage_counts(runtime.engine) == before


def test_replays_and_refusals_never_consume_budget(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "free")
    written = runtime.client_ok(_member(scene, "free"))
    _fill(runtime, scene.issue, CLIENT_LINEAGE_WRITES_PER_HOUR - 1)
    # Below the bound, refusals answer their own refusal and leave the budget.
    absent = membership(scene.issue, "task", _ABSENT_TASK, "free-absent")
    for _ in range(3):
        assert runtime.client_refused(absent)["code"] == "not_found"
    assert completed_requests(runtime.engine, channel=_REMOTE, client=REMOTE_CLIENT) == (
        CLIENT_LINEAGE_WRITES_PER_HOUR - 1
    )
    runtime.client_ok(_blocks(runtime, scene, "free-last"))
    # At the bound: a replay returns before the count, a refusal is still its
    # own, and only a write that passes every check is refused by the bound.
    again = runtime.client_ok(_member(scene, "free"))
    assert again["replayed"] is True and again["membership"] == written["membership"]
    assert runtime.client_refused(absent)["code"] == "not_found"
    assert _limited(runtime.client_refused(_blocks(runtime, scene, "free-over")))
    assert completed_requests(runtime.engine, channel=_REMOTE, client=REMOTE_CLIENT) == (
        CLIENT_LINEAGE_WRITES_PER_HOUR
    )


def test_operator_writes_are_never_rate_limited(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "operator-free")
    # Operator rows are never counted against any client.
    seed_completed_requests(
        runtime.engine,
        PRINCIPAL_CLIENT_LINEAGE_WRITES_PER_DAY,
        issue_id=scene.issue,
        channel="local_web",
        client=None,
    )
    runtime.client_ok(_member(scene, "operator-rows"))
    # Every client budget full: the human channel still writes.
    _fill(runtime, scene.issue, CLIENT_LINEAGE_WRITES_PER_HOUR)
    seed_completed_requests(
        runtime.engine,
        PRINCIPAL_CLIENT_LINEAGE_WRITES_PER_DAY,
        issue_id=scene.issue,
        channel=_LOCAL,
        client=None,
        age="2 hours",
    )
    assert _limited(runtime.client_refused(_blocks(runtime, scene, "operator-client")))
    runtime.ok(_blocks(runtime, scene, "operator-free"), surface=GATEWAY)
    runtime.ok(CreateIssue(title="Operator", idempotency_key="s31-op-free"), surface=GATEWAY)


def test_each_client_has_its_own_budget_and_unattested_callers_share_one(
    runtime: S31Runtime,
) -> None:
    scene = open_scene(runtime, "buckets")
    _fill(runtime, scene.issue, CLIENT_LINEAGE_WRITES_PER_HOUR)
    assert _limited(runtime.client_refused(_member(scene, "buckets")))
    runtime.client_ok(_blocks(runtime, scene, "buckets-other"), client=OTHER_CLIENT)
    runtime.local_ok(_blocks(runtime, scene, "buckets-local"))
    _fill(runtime, scene.issue, CLIENT_LINEAGE_WRITES_PER_HOUR, channel=_LOCAL, client=None)
    # Every unstamped local caller is the one `local_unattested` bucket.
    assert _limited(runtime.local_refused(_blocks(runtime, scene, "buckets-local-2")))
    runtime.client_ok(_blocks(runtime, scene, "buckets-third"), client=_THIRD_CLIENT)


def test_a_created_false_answer_is_checked_and_counted(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "identity-count")
    first = _blocks(runtime, scene, "identity-count")
    runtime.ok(first, surface=GATEWAY)
    _fill(runtime, scene.issue, CLIENT_LINEAGE_WRITES_PER_HOUR - 1)
    again = runtime.client_ok(replace(first, idempotency_key="s2-assoc-identity-count-client"))
    assert again["created"] is False
    # It completed a client request row: it counted, so the bucket is now full.
    assert completed_requests(runtime.engine, channel=_REMOTE, client=REMOTE_CLIENT) == (
        CLIENT_LINEAGE_WRITES_PER_HOUR
    )
    error = runtime.client_refused(replace(first, idempotency_key="s2-assoc-identity-count-2"))
    assert _limited(error)


def test_a_composite_past_its_budget_creates_no_native_record(runtime: S31Runtime) -> None:
    scene = open_scene(runtime, "composite-bound")
    _fill(runtime, scene.issue, CLIENT_LINEAGE_WRITES_PER_HOUR)
    with runtime.engine.connect() as connection:
        tasks = connection.execute(text("SELECT count(*) FROM knowledge.tasks")).scalar_one()
    assert _limited(runtime.client_refused(work_task(scene.issue, "composite-bound")))
    with runtime.engine.connect() as connection:
        assert (
            connection.execute(text("SELECT count(*) FROM knowledge.tasks")).scalar_one() == tasks
        )
