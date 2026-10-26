"""AT-019 (snapshot): one `programs.overview` reads one database snapshot (S4 sections 3.4, 6.3).

Record lineage S4 (worker M4). Every statement of one overview runs in one
`REPEATABLE READ, READ ONLY` transaction on its Program-pool connection, whose
first query takes the snapshot. So a Commitment and an Issue link committed by
another connection **between** the overview's statements -- right after that
first query, before the metric reads -- are absent from its answer, and the
next overview, a new snapshot, sees them. The lineage horizon the first query
reads (`lineage_known_at`) is exactly the cut of the Issue links counted: an
`issues.timeline` read at that `known_at` shows the same Project links.

The interleaving is forced, not hoped for: a listener on the Program engine
runs the concurrent writes on another thread (other connections) and waits
for their commit, right after the snapshot query returns. Every identity is
synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest
from sqlalchemy import event
from tests.database.lineage_s3_read_harness import horizon
from tests.database.lineage_s4_harness import T0, S4Runtime

pytestmark = pytest.mark.database

#: The overview's first statement: the one that takes the snapshot.
SNAPSHOT_MARK = "statement_timestamp()"


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S4Runtime]:
    composed = S4Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _member(runtime: S4Runtime, name: str, program: str) -> str:
    seeds = runtime.seeds
    project_id, entity_id = seeds.project(name)
    seeds.edge(entity_id, program, effective_from=T0)
    seeds.constraint_calendar(project_id)
    seeds.sync_target(project_id)
    return project_id


def _overview_with_writes_between(
    runtime: S4Runtime, program: str, writes: Callable[[], None]
) -> dict[str, Any]:
    """`programs.overview` with `writes` committed by other connections after its snapshot."""
    fired: list[str] = []

    def after(
        _connection: object,
        _cursor: object,
        statement: str,
        *_rest: object,
    ) -> None:
        if fired or SNAPSHOT_MARK not in statement:
            return
        fired.append(statement)
        with ThreadPoolExecutor(max_workers=1) as pool:
            pool.submit(writes).result(timeout=60)

    event.listen(runtime.program_engine, "after_cursor_execute", after)
    try:
        answer = runtime.overview(program)
    finally:
        event.remove(runtime.program_engine, "after_cursor_execute", after)
    assert len(fired) == 1, "the writes did not run between the overview's statements"
    return answer


def _metric(rows: list[dict[str, Any]], metric_id: str) -> Any:  # noqa: ANN401
    (row,) = [row for row in rows if row["metric_id"] == metric_id]
    return row["value"]


def _per_project(answer: dict[str, Any], project_id: str, metric_id: str) -> Any:  # noqa: ANN401
    (entry,) = [entry for entry in answer["per_project"] if entry["project_id"] == project_id]
    return _metric(entry["metrics"], metric_id)


def test_one_overview_reads_one_snapshot(runtime: S4Runtime) -> None:
    program = runtime.seeds.program("Snapshot")
    project_id = _member(runtime, "Snapshot member", program)
    written: dict[str, str] = {}

    def writes() -> None:
        written["commitment"] = runtime.work_commitment(
            "snapshot-proposed", project_id=project_id, accepted=False
        )
        written["issue"] = runtime.linked_issue("snapshot-issue", project_id)

    during = _overview_with_writes_between(runtime, program, writes)
    assert set(written) == {"commitment", "issue"}
    # Committed after the snapshot: absent at every scope of that one answer.
    assert _per_project(during, project_id, "commitment_open_proposed") == 0
    assert _per_project(during, project_id, "issue_outstanding") == 0
    for totals in (during["programs"][0]["totals"], during["portfolio"]["totals"]):
        assert _metric(totals, "commitment_open_proposed") == 0
        assert _metric(totals, "issue_outstanding") == 0
    # The next overview is a new snapshot and sees both.
    after = runtime.overview(program)
    assert _per_project(after, project_id, "commitment_open_proposed") == 1
    assert _per_project(after, project_id, "issue_outstanding") == 1
    assert _metric(after["programs"][0]["totals"], "commitment_open_proposed") == 1
    assert after["source_cutoff_at"] > during["source_cutoff_at"]


def _linked_projects(runtime: S4Runtime, issue_id: str, **kwargs: Any) -> set[str]:  # noqa: ANN401
    """The Projects an `issues.timeline` read shows the Issue actively linked to."""
    links: dict[str, str] = {}
    for page in runtime.timeline_pages(issue_id, **kwargs):
        for entry in page["entries"]:
            if entry["kind"] == "project_link":
                links[entry["project_id"]] = entry["link_state"]
    return {project for project, state in links.items() if state == "active"}


def test_lineage_known_at_matches_the_issue_links_read(runtime: S4Runtime) -> None:
    program = runtime.seeds.program("Horizon")
    first = _member(runtime, "Horizon first", program)
    second = _member(runtime, "Horizon second", program)
    issue = runtime.linked_issue("horizon", first)
    before = horizon(runtime.engine)

    def writes() -> None:
        # Link the same Issue to the 2nd member: a lineage fact after the snapshot.
        runtime.link_project(issue, second, "horizon-second")

    during = _overview_with_writes_between(runtime, program, writes)
    assert during["lineage_known_at"] == before
    assert horizon(runtime.engine) > before
    counted = {
        project_id
        for project_id in (first, second)
        if _per_project(during, project_id, "issue_outstanding") == 1
    }
    assert counted == {first}
    # An `issues.timeline` read at the overview's horizon shows exactly the
    # Project links the overview counted; the current read shows both.
    assert _linked_projects(runtime, issue, known_at=during["lineage_known_at"]) == counted
    assert _linked_projects(runtime, issue) == {first, second}
    after = runtime.overview(program)
    assert after["lineage_known_at"] == horizon(runtime.engine)
    assert _per_project(after, second, "issue_outstanding") == 1
