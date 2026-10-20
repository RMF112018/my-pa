"""AT-016: `records.lineage` is bounded in items, bytes, nodes, edges and time (S3 section 7.2).

Against PostgreSQL through `ApplicationService.invoke`:

* each page holds at most `page_size` items and 512 KiB, and the pages still
  reconstruct the whole answer when the byte bound cuts a page short;
* the whole-query node and edge budgets stop expansion and say
  `truncated_budget`;
* a traversal deadline hit says `truncated_budget` and ends paging;
* the expansion order is deterministic, on a dense hub too, and a high-degree
  Meeting never fans out to another Issue;
* `page_size` is 10..100, never clamped;
* link identifiers page and expand in code-point order whatever the database
  collation (`COLLATE "C"`, R3-F10).

The tests that need a smaller bound than the design value move it with
`monkeypatch` on the application module, as the S1 read-contract tests do.
Every identity and every body is synthetic.
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from typing import Any, Final

import pytest
from sqlalchemy import Engine, delete, insert, select, text

from my_pa.application import record_lineage as lineage_module
from my_pa.application.commands import ReadRecordLineage
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.infrastructure.persistence.tables import (
    record_link_heads,
    record_link_revision_evidence,
    record_link_revisions,
    record_links,
)
from tests.database.lineage_record_harness import NOTE_BODY, note_anchor
from tests.database.lineage_s2_harness import assertion
from tests.database.lineage_s3_harness import GATEWAY
from tests.database.lineage_s3_read_harness import S3ReadRuntime, node_set, union

pytestmark = pytest.mark.database

_LINK_TABLES: Final = (
    record_links,
    record_link_revisions,
    record_link_revision_evidence,
)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _hub(runtime: S3ReadRuntime, key: str, tasks: int) -> dict[str, Any]:
    """An Issue whose Meeting note discusses `tasks` Task members, in its context."""
    issue = runtime.issue(key)
    meeting_id, note_id = runtime.note(f"{key}-m")
    runtime.member(issue, "meeting", meeting_id, f"{key}-m", "discussion")
    task_ids = []
    for number in range(tasks):
        task_id = runtime.task(f"{key}-{number:02d}")
        runtime.member(issue, "task", task_id, f"{key}-{number:02d}", "reference")
        runtime.ok(
            assertion(
                "discusses",
                ("meeting_note_version", note_id),
                ("task", task_id),
                f"{key}-{number:02d}",
                (note_anchor(meeting_id, note_id, NOTE_BODY, role="discussion"),),
                context=issue,
            ),
            surface=GATEWAY,
        )
        task_ids.append(task_id)
    return {"issue": issue, "meeting": meeting_id, "note": note_id, "tasks": task_ids}


def _size(document: object) -> int:
    return len(json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8"))


def _items(answer: dict[str, Any]) -> int:
    return len(answer["nodes"]) + len(answer["typed_edges"]) + len(answer["virtual_native_edges"])


def test_each_page_stays_within_its_item_and_byte_budget(
    runtime: S3ReadRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = _hub(runtime, "bnd-page", 8)
    root = ("situation", scene["issue"])
    whole = runtime.lineage(root)
    for page_size in (10, 17, 100):
        pages = runtime.pages(root, page_size=page_size)
        for page in pages:
            assert 1 <= _items(page) <= page_size
            assert _size(page) <= lineage_module.MAX_LINEAGE_BYTES
        assert union(pages)["typed_edges"] == whole["typed_edges"], page_size
    # A byte bound well below the item bound cuts pages short, and they still
    # reconstruct the whole answer.
    monkeypatch.setattr(lineage_module, "MAX_LINEAGE_BYTES", 6000)
    pages = runtime.pages(root, page_size=100)
    assert len(pages) > 1
    for page in pages:
        assert _items(page) >= 1
        assert _size(page) <= 6000
    merged = union(pages)
    for key in ("nodes", "typed_edges", "virtual_native_edges"):
        assert merged[key] == whole[key], key


def test_node_and_edge_budgets_answer_truncated_budget(
    runtime: S3ReadRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert (lineage_module.MAX_LINEAGE_NODES, lineage_module.MAX_LINEAGE_EDGES) == (250, 400)
    scene = _hub(runtime, "bnd-budget", 6)
    root = ("situation", scene["issue"])
    assert runtime.lineage(root)["complete_state"] == "complete"
    for nodes, edges in ((5, 400), (250, 4)):
        monkeypatch.setattr(lineage_module, "MAX_LINEAGE_NODES", nodes)
        monkeypatch.setattr(lineage_module, "MAX_LINEAGE_EDGES", edges)
        for answer in (runtime.lineage(root), *runtime.pages(root, page_size=10)):
            assert answer["complete_state"] == "truncated_budget", (nodes, edges)
            assert "truncated_budget" in answer["qualifiers"]
        whole = runtime.lineage(root)
        assert len(whole["nodes"]) <= nodes
        assert len(whole["typed_edges"]) + len(whole["virtual_native_edges"]) <= edges
        # Truncated, paging still ends and reproduces the truncated answer.
        assert union(runtime.pages(root, page_size=10))["nodes"] == whole["nodes"]


def test_a_deadline_hit_answers_truncated_budget_without_a_cursor(
    runtime: S3ReadRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = _hub(runtime, "bnd-deadline", 12)
    root = ("situation", scene["issue"])
    assert runtime.lineage(root, page_size=10)["next_cursor"] is not None
    ticks = iter(range(1_000_000))

    def clock() -> float:
        # Each reading is 0.6 s after the last: the third check is past 2 s.
        return 0.6 * next(ticks)

    monkeypatch.setattr(lineage_module, "_monotonic", clock)
    page = runtime.lineage(root, page_size=10)
    assert page["complete_state"] == "truncated_budget"
    assert page["next_cursor"] is None
    assert _items(page) >= 1
    single = runtime.lineage(root)
    assert single["complete_state"] == "truncated_budget"


def test_expansion_order_is_deterministic_on_a_dense_hub(
    runtime: S3ReadRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = _hub(runtime, "bnd-hub", 10)
    roots = (
        ("situation", scene["issue"]),
        ("meeting", scene["meeting"]),
        ("meeting_note_version", scene["note"]),
    )

    def read(root: tuple[str, str]) -> dict[str, Any]:
        answer = runtime.lineage(root, issue_id=scene["issue"])
        # The read time is the one thing a current read may differ in.
        return {key: value for key, value in answer.items() if key != "native_cut_at"}

    first = {root: read(root) for root in roots}
    for _ in range(3):
        for root in roots:
            assert read(root) == first[root], root
    # Truncated, the hub always keeps the same, earliest-linked records.
    monkeypatch.setattr(lineage_module, "MAX_LINEAGE_NODES", 6)
    kept = [node_set(runtime.lineage(roots[0])) for _ in range(3)]
    assert kept[0] == kept[1] == kept[2]
    assert len(kept[0]) == 6
    # The Issue's memberships are expanded in creation order: the first Tasks win.
    assert {("task", task) for task in scene["tasks"][:4]} <= kept[0]


def test_a_high_degree_meeting_never_fans_out_to_other_issues(runtime: S3ReadRuntime) -> None:
    scene = _hub(runtime, "bnd-fan", 30)
    other = runtime.issue("bnd-fan-other")
    own_task = runtime.task("bnd-fan-own")
    runtime.member(other, "meeting", scene["meeting"], "bnd-fan-other-m", "discussion")
    runtime.member(other, "task", own_task, "bnd-fan-own", "reference")
    for root in (("situation", other), ("meeting", scene["meeting"]), ("task", own_task)):
        answer = runtime.lineage(root, issue_id=other)
        assert node_set(answer) == {
            ("situation", other),
            ("meeting", scene["meeting"]),
            ("task", own_task),
        }, root
        assert answer["complete_state"] == "complete", root
        rendered = json.dumps(answer["nodes"]) + json.dumps(answer["typed_edges"])
        assert not any(task in rendered for task in scene["tasks"]), root


def test_page_size_below_the_minimum_is_refused(runtime: S3ReadRuntime) -> None:
    scene = _hub(runtime, "bnd-min", 1)
    origin = {"family": "situation", "record_id": scene["issue"]}
    for page_size in (0, 1, 9, 101, "10"):
        with pytest.raises(InvalidRequestError) as refused:
            ReadRecordLineage(origin=origin, page_size=page_size)  # type: ignore[arg-type]
        assert refused.value.safe_details == (SafeDetail.PAGE_SIZE,), page_size
    # At the bounds a page is served and never holds more than asked.
    for page_size in (10, 100):
        page = runtime.lineage(("situation", scene["issue"]), page_size=page_size)
        assert _items(page) <= page_size


# ---- code-point order (R3-F10) ---------------------------------------------------------------


def _rename_links(engine: Engine, renames: dict[str, str]) -> None:
    """Give links chosen identifiers and one creation instant (synthetic database only).

    Replica mode bypasses the append-only triggers and foreign keys so the rows
    can be re-keyed; every value but the identifier is copied.
    """
    with engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        created = connection.execute(
            select(record_links.c.created_at).where(record_links.c.link_id.in_(list(renames)))
        ).scalars()
        same = min(created)
        for old, new in renames.items():
            copied: dict[Any, list[dict[str, Any]]] = {}
            for table in (*_LINK_TABLES, record_link_heads):
                copied[table] = [
                    {**row, "link_id": new}
                    for row in connection.execute(
                        select(table).where(table.c.link_id == old)
                    ).mappings()
                ]
            for table in (record_link_heads, *reversed(_LINK_TABLES)):
                connection.execute(delete(table).where(table.c.link_id == old))
            copied[record_links] = [{**row, "created_at": same} for row in copied[record_links]]
            for table in (*_LINK_TABLES, record_link_heads):
                if copied[table]:
                    connection.execute(insert(table), copied[table])


def test_mixed_case_link_ids_page_in_code_point_order(
    runtime: S3ReadRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    issue = runtime.issue("bnd-case")
    tasks = [runtime.task(f"bnd-case-{number:02d}") for number in range(12)]
    links = [
        runtime.member(issue, "task", task, f"bnd-case-{number:02d}", "reference")
        for number, task in enumerate(tasks)
    ]
    # Upper case sorts before lower case by code point, after it by en_US rules.
    chosen = [
        f"irl_{prefix}{number:02d}synthetic"
        for number, prefix in enumerate(["b", "A", "c", "B", "a", "C"] * 2)
    ]
    _rename_links(runtime.engine, dict(zip(links, chosen, strict=True)))
    root = ("situation", issue)
    pages = runtime.pages(root, page_size=10)
    order = [edge["link_id"] for edge in union(pages)["typed_edges"]]
    assert order == sorted(chosen)
    assert order != sorted(chosen, key=str.lower)
    # Expansion ties fall to the code-point-first link: with room for 4 Tasks,
    # those reached are the members whose links sort first by code point.
    monkeypatch.setattr(lineage_module, "MAX_LINEAGE_NODES", 5)
    reached = node_set(runtime.lineage(root))
    by_link = dict(zip(chosen, tasks, strict=True))
    assert reached == {("situation", issue)} | {
        ("task", by_link[link]) for link in sorted(chosen)[:4]
    }
