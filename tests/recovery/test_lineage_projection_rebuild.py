"""AT-014 (rebuild): marks, requests, facts and heads stay one consistent record (S3 section 4).

Marked `database` and `recovery`, routed to `database-recovery`. Against
PostgreSQL through `ApplicationService.invoke` and the persistence rebuild:

* a lineage write killed before its commit leaves no commit mark, no head and
  no request row, and the allocator does not advance;
* after the S3 actions (contest, reinstate, end, `related_context`) the heads
  rebuilt from roots and revisions alone equal the stored projection, and
  rebuilding again is byte-identical;
* the as-of read at the committed horizon equals the head read;
* a side-channel edit of the head projection is refused by the database;
* every completed write names its own mark, every mark is one write's, and
  every fact row carries a mark of a completed write.

Every identity and every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

import pytest
from sqlalchemy import Engine, select, text
from sqlalchemy.exc import DBAPIError

from my_pa.application.commands import EndRecordAssociation
from my_pa.domain.lineage.vocabulary import LinkLifecycleState
from my_pa.infrastructure.persistence.issues import SqlIssueRepository
from my_pa.infrastructure.persistence.principal_scope import capture_context, principal_scoped
from my_pa.infrastructure.persistence.record_lineage import LinkHeadRow, rebuild_link_heads
from my_pa.infrastructure.persistence.tables import (
    issue_project_membership_events,
    issue_responsibility_corrections,
    issue_responsibility_events,
    issue_revisions,
    record_link_heads,
    record_link_revisions,
)
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_s3_harness import (
    GATEWAY,
    all_s3_counts,
    blocks_scene,
    contest,
    corroborates,
    mark_count,
    reinstate,
    related,
)
from tests.database.lineage_s3_read_harness import S3ReadRuntime, horizon

pytestmark = [pytest.mark.database, pytest.mark.recovery]

#: The four fact tables that carry a commit mark, and the correction ledger.
_FACT_TABLES = (
    issue_revisions,
    issue_project_membership_events,
    record_link_revisions,
    issue_responsibility_events,
    issue_responsibility_corrections,
)


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _stored(engine: Engine) -> tuple[LinkHeadRow, ...]:
    context = capture_context(PRINCIPAL)
    with engine.connect() as connection:
        return tuple(
            LinkHeadRow(
                principal_id=row.principal_id,
                link_id=row.link_id,
                revision_no=row.revision_no,
                lifecycle_state=LinkLifecycleState(row.lifecycle_state),
                normalized_identity=row.normalized_identity,
            )
            for row in connection.execute(
                principal_scoped(
                    select(record_link_heads).order_by(record_link_heads.c.link_id),
                    record_link_heads,
                    context,
                )
            )
        )


def _rebuilt(engine: Engine) -> tuple[LinkHeadRow, ...]:
    with engine.connect() as connection:
        return rebuild_link_heads(connection, capture_context(PRINCIPAL))


def _s3_actions(runtime: S3ReadRuntime, key: str) -> dict[str, Any]:
    """A contested-then-reinstated link, an ended one and a `related_context` link."""
    scene = blocks_scene(runtime, key, members=True)
    link = scene["link"]
    runtime.ok(contest(link, 1, key, (scene["contradicts"],)), surface=GATEWAY)
    runtime.ok(reinstate(link, 2, key, (scene["corroborates"],)), surface=GATEWAY)
    disputed = blocks_scene(runtime, f"{key}-2", members=True)
    runtime.ok(
        contest(disputed["link"], 1, f"{key}-2", (disputed["contradicts"],)), surface=GATEWAY
    )
    ended = blocks_scene(runtime, f"{key}-3")
    runtime.ok(
        EndRecordAssociation(
            link_id=ended["link"],
            expected_revision=1,
            idempotency_key=f"{key}-3-end",
            reason="Synthetic end.",
            evidence_anchors=(),
        ),
        surface=GATEWAY,
    )
    written = runtime.ok(
        related(
            ("task", scene["second"]),
            ("task", scene["first"]),
            key,
            (corroborates(scene["meeting"], scene["note"]),),
            context=scene["issue"],
        ),
        surface=GATEWAY,
    )
    return {
        "scene": scene,
        "contested": disputed["link"],
        "ended": ended["link"],
        "related": written["association"]["link_id"],
    }


def test_a_write_killed_before_commit_leaves_no_mark_head_or_request(
    runtime: S3ReadRuntime, monkeypatch: pytest.MonkeyPatch
) -> None:
    scene = blocks_scene(runtime, "rb-kill", members=True)
    counts, marks, before = (
        all_s3_counts(runtime.engine),
        mark_count(runtime.engine),
        (horizon(runtime.engine)),
    )

    def killed(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("the process died before commit")

    # Everything is written -- the mark, the revision, the head -- then the
    # request's completion dies, so the transaction never commits.
    monkeypatch.setattr(SqlIssueRepository, "complete_write_request", killed)
    try:
        envelope = runtime.invoke(
            contest(scene["link"], 1, "rb-kill", (scene["contradicts"],)), surface=GATEWAY
        )
        assert envelope.error is not None
    except RuntimeError:
        pass
    monkeypatch.undo()
    assert all_s3_counts(runtime.engine) == counts
    assert mark_count(runtime.engine) == marks
    assert horizon(runtime.engine) == before
    assert _rebuilt(runtime.engine) == _stored(runtime.engine)
    # The same request then commits normally, taking the next mark.
    runtime.ok(contest(scene["link"], 1, "rb-kill", (scene["contradicts"],)), surface=GATEWAY)
    assert mark_count(runtime.engine) == marks + 1


def test_rebuilt_heads_equal_stored_heads_after_s3_actions(runtime: S3ReadRuntime) -> None:
    done = _s3_actions(runtime, "rb-heads")
    stored = _stored(runtime.engine)
    assert _rebuilt(runtime.engine) == stored
    states = {head.link_id: (head.revision_no, head.lifecycle_state) for head in stored}
    assert states[done["scene"]["link"]] == (3, LinkLifecycleState.ACTIVE)
    assert states[done["contested"]] == (2, LinkLifecycleState.CONTESTED)
    assert states[done["ended"]] == (2, LinkLifecycleState.ENDED)
    assert states[done["related"]] == (1, LinkLifecycleState.ACTIVE)


def test_the_as_of_read_at_the_horizon_equals_the_head_read(runtime: S3ReadRuntime) -> None:
    done = _s3_actions(runtime, "rb-asof")
    known = horizon(runtime.engine)
    heads = {head.link_id: head for head in _stored(runtime.engine)}
    for issue in (done["scene"]["issue"],):
        root = ("situation", issue)
        current = runtime.lineage(root)
        asof = runtime.lineage(root, known_at=known)
        for key in ("nodes", "typed_edges", "virtual_native_edges", "issues_matching_root"):
            assert asof[key] == current[key], key
        for edge in asof["typed_edges"]:
            head = heads[edge["link_id"]]
            assert (edge["revision_no"], edge["lifecycle_state"]) == (
                head.revision_no,
                head.lifecycle_state.value,
            )
    # The contested link of the second scene reads contested at the horizon.
    other = runtime.lineage(("task", _first_task(runtime, done["contested"])), known_at=known)
    (edge,) = [edge for edge in other["typed_edges"] if edge["link_id"] == done["contested"]]
    assert edge["lifecycle_state"] == "contested"


def _first_task(runtime: S3ReadRuntime, link_id: str) -> str:
    with runtime.engine.connect() as connection:
        return str(
            connection.execute(
                text("SELECT from_id FROM knowledge.record_links WHERE link_id = :link"),
                {"link": link_id},
            ).scalar_one()
        )


def test_repeated_rebuilds_are_byte_identical(runtime: S3ReadRuntime) -> None:
    _s3_actions(runtime, "rb-repeat")
    first = _rebuilt(runtime.engine)
    assert first
    for _ in range(3):
        assert repr(_rebuilt(runtime.engine)) == repr(first)


def test_a_side_channel_head_edit_is_refused(runtime: S3ReadRuntime) -> None:
    done = _s3_actions(runtime, "rb-side")
    stored = _stored(runtime.engine)
    link = done["contested"]
    for statement in (
        "UPDATE knowledge.record_link_heads SET lifecycle_state = 'active' WHERE link_id = :link",
        "UPDATE knowledge.record_link_heads SET revision_no = 1 WHERE link_id = :link",
        "DELETE FROM knowledge.record_link_heads WHERE link_id = :link",
    ):
        with pytest.raises(DBAPIError), runtime.engine.begin() as connection:
            connection.execute(text(statement), {"link": link})
    assert _stored(runtime.engine) == stored == _rebuilt(runtime.engine)


def test_marks_requests_and_facts_are_consistent(runtime: S3ReadRuntime) -> None:
    _s3_actions(runtime, "rb-consistent")
    with runtime.engine.connect() as connection:
        marks = [
            row.commit_seq
            for row in connection.execute(
                text(
                    "SELECT commit_seq FROM knowledge.lineage_commit_marks "
                    "WHERE principal_id = :p ORDER BY commit_seq"
                ),
                {"p": PRINCIPAL},
            )
        ]
        requests = [
            row.commit_seq
            for row in connection.execute(
                text(
                    "SELECT commit_seq FROM knowledge.lineage_write_requests "
                    "WHERE principal_id = :p AND completed_at IS NOT NULL "
                    "AND commit_seq IS NOT NULL ORDER BY commit_seq"
                ),
                {"p": PRINCIPAL},
            )
        ]
        incomplete = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.lineage_write_requests "
                "WHERE principal_id = :p AND completed_at IS NULL"
            ),
            {"p": PRINCIPAL},
        ).scalar_one()
        facts: set[int | None] = set()
        for table in _FACT_TABLES:
            facts.update(
                connection.execute(
                    select(table.c.commit_seq).where(table.c.principal_id == PRINCIPAL)
                ).scalars()
            )
        last_seq = connection.execute(
            text("SELECT last_seq FROM knowledge.lineage_commit_sequences WHERE principal_id = :p"),
            {"p": PRINCIPAL},
        ).scalar_one()
    # Contiguous from 1 to the allocator's `last_seq`, one per completed write.
    assert marks == list(range(1, last_seq + 1))
    assert requests == marks
    assert incomplete == 0
    # Every fact row (all written after the S3 revision) names a mark of a write.
    assert None not in facts
    assert facts <= set(marks)
