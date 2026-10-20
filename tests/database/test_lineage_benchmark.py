"""AT-016 (benchmark): paging a full-budget lineage answer, recorded -- not a service level.

S3 contract section 7.2 step 5. One Issue reaches exactly the whole-query
budget -- 250 nodes and 400 typed edges, 650 items -- inside a synthetic corpus
of background records and links, and `records.lineage` pages it at
`page_size` 10 (65 recomputations). The per-page p50 and p95 and the total are
printed and, when `MY_PA_LINEAGE_BENCHMARK_REPORT` names a file, written there
as JSON.

Scale (`MY_PA_LINEAGE_BENCHMARK_SCALE`): `small` (the default; 2000 records and
10000 links of background) or `full` (100000 records and 1000000 links, run
once locally and recorded). The corpus is bulk-seeded in SQL with replica-mode
triggers off (a synthetic database only); its rows carry no commit mark and are
known by their own `recorded_at`, as rows written before the S3 revision are.

Every identity and every body is synthetic.
"""

from __future__ import annotations

import json
import os
import statistics
import time
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, text

from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_s3_read_harness import S3ReadRuntime

pytestmark = [pytest.mark.database, pytest.mark.slow]

_SCALES: Final = {"small": (2_000, 10_000), "full": (100_000, 1_000_000)}
#: The Issue's own Task members (with the Issue: 250 nodes) and `blocks` links
#: among them (with the 249 memberships: 400 typed edges).
_MEMBERS: Final = 249
_BLOCKS: Final = 151
_PAST: Final = datetime(2026, 1, 1, tzinfo=UTC)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _seed(engine: Engine, issue: str, records: int, links: int) -> None:
    """The Issue's 249 members and 151 `blocks` links, then the background corpus."""
    parameters = {"p": PRINCIPAL, "issue": issue, "past": _PAST}
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        # Tasks: the Issue's members (bm...) and the background (bg...).
        connection.execute(
            text(
                "INSERT INTO knowledge.tasks (task_id, principal_id, title, origin_kind, "
                "opened_at, created_at, updated_at) "
                "SELECT 'tsk_bm' || lpad(n::text, 8, '0'), :p, 'Synthetic member', "
                "'direct_principal', :past, :past, :past FROM generate_series(1, :members) n "
                "UNION ALL "
                "SELECT 'tsk_bg' || lpad(n::text, 8, '0'), :p, 'Synthetic background', "
                "'direct_principal', :past, :past, :past FROM generate_series(1, :records) n"
            ),
            {**parameters, "members": _MEMBERS, "records": records},
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.record_links (principal_id, link_id, kind, from_family, "
                "from_id, to_family, to_id, relation_type, member_role, context_issue_id, "
                "context_issue_kind, normalized_identity, authority_class, decision_channel, "
                "source_capability, created_at) "
                # The memberships.
                "SELECT :p, 'irl_bm' || lpad(n::text, 8, '0'), 'issue_membership', "
                "'situation', :issue, 'task', 'tsk_bm' || lpad(n::text, 8, '0'), "
                "'issue_member', 'reference', :issue, 'issue_workstream', "
                "'bench-m-' || n, 'local_operator', 'local_web', 'issues.memberships.add', "
                ":past + n * interval '1 millisecond' "
                "FROM generate_series(1, :members) n "
                "UNION ALL "
                # The Issue-scoped `blocks` links among its members.
                "SELECT :p, 'irl_bb' || lpad(n::text, 8, '0'), 'semantic', "
                "'task', 'tsk_bm' || lpad(n::text, 8, '0'), "
                "'task', 'tsk_bm' || lpad((n + 1)::text, 8, '0'), 'blocks', NULL, :issue, "
                "'issue_workstream', 'bench-b-' || n, 'local_operator', 'local_web', "
                "'records.associations.assert', "
                ":past + (1000 + n) * interval '1 millisecond' "
                "FROM generate_series(1, :blocks) n "
                "UNION ALL "
                # The background: context-free `blocks` links among background Tasks.
                "SELECT :p, 'irl_bg' || lpad(n::text, 9, '0'), 'semantic', "
                "'task', 'tsk_bg' || lpad((1 + n % :records)::text, 8, '0'), "
                "'task', 'tsk_bg' || lpad((1 + (n * 7 + 3) % :records)::text, 8, '0'), "
                "'blocks', NULL, NULL, NULL, 'bench-g-' || n, 'local_operator', 'local_web', "
                "'records.associations.assert', :past "
                "FROM generate_series(1, :links) n"
            ),
            {
                **parameters,
                "members": _MEMBERS,
                "blocks": _BLOCKS,
                "records": records,
                "links": links,
            },
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.record_link_revisions (principal_id, link_id, "
                "revision_no, revision_id, predecessor_revision_no, action, lifecycle_state, "
                "acceptance_basis, authority_class, decision_channel, source_capability, "
                "reason, evidence_count, evidence_set_digest, recorded_at) "
                "SELECT principal_id, link_id, 1, 'irv_' || substr(link_id, 5), NULL, "
                "'assert', 'active', 'user_confirmed', authority_class, decision_channel, "
                "source_capability, NULL, 0, repeat('a', 64), created_at "
                "FROM knowledge.record_links WHERE principal_id = :p "
                "AND (link_id LIKE 'irl_bm%' OR link_id LIKE 'irl_bb%' OR link_id LIKE 'irl_bg%')"
            ),
            parameters,
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.record_link_heads (principal_id, link_id, revision_no, "
                "lifecycle_state, normalized_identity) "
                "SELECT principal_id, link_id, 1, 'active', normalized_identity "
                "FROM knowledge.record_links WHERE principal_id = :p "
                "AND (link_id LIKE 'irl_bm%' OR link_id LIKE 'irl_bb%' OR link_id LIKE 'irl_bg%')"
            ),
            parameters,
        )
    with engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for table in ("tasks", "record_links", "record_link_revisions", "record_link_heads"):
            connection.execute(text(f"ANALYZE knowledge.{table}"))


def test_records_the_synthetic_scale_benchmark(runtime: S3ReadRuntime) -> None:
    scale = os.environ.get("MY_PA_LINEAGE_BENCHMARK_SCALE", "small")
    records, links = _SCALES[scale]
    issue = runtime.issue("bench")
    seeded = time.perf_counter()
    _seed(runtime.engine, issue, records, links)
    seed_seconds = time.perf_counter() - seeded
    root = ("situation", issue)
    timings: list[float] = []
    pages: list[dict[str, object]] = []
    cursor: str | None = None
    started = time.perf_counter()
    while True:
        before = time.perf_counter()
        page = runtime.lineage(root, page_size=10, cursor=cursor)
        timings.append(time.perf_counter() - before)
        pages.append(page)
        cursor = page["next_cursor"]  # type: ignore[assignment]
        if cursor is None:
            break
    total = time.perf_counter() - started
    items = sum(
        len(page["nodes"]) + len(page["typed_edges"]) + len(page["virtual_native_edges"])  # type: ignore[arg-type]
        for page in pages
    )
    ordered = sorted(timings)
    report = {
        "scale": scale,
        "background_records": records,
        "background_links": links,
        "seed_seconds": round(seed_seconds, 3),
        "pages": len(pages),
        "items": items,
        "complete_state": pages[0]["complete_state"],
        "page_p50_ms": round(1000 * statistics.median(ordered), 1),
        "page_p95_ms": round(1000 * ordered[max(0, int(0.95 * len(ordered)) - 1)], 1),
        "total_ms": round(1000 * total, 1),
    }
    print("lineage benchmark:", json.dumps(report, sort_keys=True))
    target = os.environ.get("MY_PA_LINEAGE_BENCHMARK_REPORT")
    if target:
        Path(target).write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    # A recorded expectation, not a service level: at the default scale the
    # answer is the whole budget, paged to the end. At `full` the numbers are
    # recorded as measured (a deadline hit would show as `truncated_budget`).
    if scale == "small":
        assert (report["pages"], items) == (65, 650)
        assert report["complete_state"] == "complete"
