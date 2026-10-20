"""AT-016 (plans): the as-of read statements reach their indexes (S3 contract sections 4 and 7.2).

Each statement the lineage repository issues for one read step is captured as
sent and `EXPLAIN`ed on the same connection with sequential scans disabled, so
the plan names the index the planner can use: the endpoint indexes for incident
links, the revision key for the as-of revision selection, and the
`marked_at` index for mark resolution. With sequential scans disabled a
statement whose predicate no index serves still plans a (penalized)
sequential scan, which the assertions reject.

The `issues.timeline` row (worker L4): the timeline's lineage reads reach the
Issue-keyed indexes (the revision key, the context index, the handoff Issue
index) and its native read the Record Event `(principal, family, record)`
index. Every identity and every body is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from datetime import UTC, datetime

import pytest
from sqlalchemy import Connection, event, text

from my_pa.contracts.ports import LineageFactCut
from my_pa.domain.lineage.model import RecordRef
from my_pa.domain.lineage.vocabulary import RecordFamily
from my_pa.domain.record_events import RecordEventFamily
from my_pa.infrastructure.persistence.issue_handoffs import SqlIssueHandoffRepository
from my_pa.infrastructure.persistence.issue_timeline import SqlIssueTimelineRepository
from my_pa.infrastructure.persistence.record_lineage import SqlRecordLineageRepository
from tests.database.lineage_issue_harness import PRINCIPAL
from tests.database.lineage_s2_harness import handoff
from tests.database.lineage_s3_harness import GATEWAY, blocks_scene, shortly_after
from tests.database.lineage_s3_read_harness import S3ReadRuntime

pytestmark = pytest.mark.database


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3ReadRuntime]:
    composed = S3ReadRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _plans(connection: Connection, run: Callable[[SqlRecordLineageRepository], object]) -> str:
    """Every statement `run` sends, `EXPLAIN`ed with sequential scans off, joined."""
    captured: list[tuple[str, object]] = []

    def record(
        _conn: object, _cursor: object, statement: str, parameters: object, *_: object
    ) -> None:
        captured.append((statement, parameters))

    event.listen(connection, "before_cursor_execute", record)
    try:
        run(SqlRecordLineageRepository(connection))
    finally:
        event.remove(connection, "before_cursor_execute", record)
    connection.execute(text("SET enable_seqscan = off"))
    plans = [
        "\n".join(connection.exec_driver_sql(f"EXPLAIN {statement}", parameters).scalars())  # type: ignore[arg-type]
        for statement, parameters in captured
    ]
    assert plans, "the step issued no statement"
    return "\n---\n".join(plans)


def _scene(runtime: S3ReadRuntime) -> dict[str, str]:
    scene = blocks_scene(runtime, "plan", members=True, context=False)
    _volume(runtime)
    return {key: str(value) for key, value in scene.items() if isinstance(value, str)}


def _volume(runtime: S3ReadRuntime, copies: int = 4000) -> None:
    """Enough synthetic links and revisions for the planner's choice to mean something.

    Each copy of the scene's links gets fresh endpoints; replica mode skips the
    append-only and mark triggers for this bulk seed (a synthetic database only).
    """
    with runtime.engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "INSERT INTO knowledge.record_links (principal_id, link_id, kind, from_family, "
                "from_id, to_family, to_id, relation_type, member_role, context_issue_id, "
                "context_issue_kind, normalized_identity, authority_class, decision_channel, "
                "source_capability, created_at) "
                "SELECT principal_id, 'irl_vol' || n || 'x' || substr(link_id, 5, 20), kind, "
                "from_family, 'tsk_vol' || n || 'f' || substr(from_id, 5, 20), to_family, "
                "'tsk_vol' || n || 't' || substr(to_id, 5, 20), relation_type, member_role, "
                "context_issue_id, context_issue_kind, normalized_identity || n, "
                "authority_class, decision_channel, source_capability, created_at "
                "FROM knowledge.record_links, generate_series(1, :copies) AS n "
                "WHERE kind = 'semantic'"
            ),
            {"copies": copies},
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.record_link_revisions (principal_id, link_id, "
                "revision_no, revision_id, predecessor_revision_no, action, lifecycle_state, "
                "acceptance_basis, authority_class, decision_channel, source_capability, "
                "reason, evidence_count, evidence_set_digest, recorded_at, "
                "member_native_version, commit_seq) "
                "SELECT r.principal_id, 'irl_vol' || n || 'x' || substr(r.link_id, 5, 20), "
                "r.revision_no, 'irv_vol' || n || 'x' || substr(r.revision_id, 5, 20), "
                "r.predecessor_revision_no, r.action, r.lifecycle_state, r.acceptance_basis, "
                "r.authority_class, r.decision_channel, r.source_capability, r.reason, 0, "
                "r.evidence_set_digest, r.recorded_at, r.member_native_version, r.commit_seq "
                "FROM knowledge.record_link_revisions r "
                "JOIN knowledge.record_links l "
                "ON l.principal_id = r.principal_id AND l.link_id = r.link_id "
                "AND l.kind = 'semantic', generate_series(1, :copies) AS n"
            ),
            {"copies": copies},
        )
    with runtime.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        for table in ("record_links", "record_link_revisions", "lineage_commit_marks"):
            connection.execute(text(f"ANALYZE knowledge.{table}"))


def _cut(connection: Connection) -> LineageFactCut:
    repository = SqlRecordLineageRepository(connection)
    at = repository.commit_horizon(PRINCIPAL)
    assert at is not None
    return LineageFactCut(watermark=repository.commit_watermark(PRINCIPAL, at), at=at)


def test_incident_link_reads_use_the_endpoint_indexes(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime)
    refs = (RecordRef(family=RecordFamily.TASK, record_id=scene["first"]),)
    with runtime.engine.connect() as connection:
        cut = _cut(connection)
        plan = _plans(connection, lambda repo: repo.live_links_incident(PRINCIPAL, refs, cut))
    assert "record_links_outgoing" in plan, plan
    assert "record_links_incoming" in plan, plan
    assert "Seq Scan on record_links " not in plan, plan


def test_as_of_revision_reads_use_the_revision_key(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime)
    refs = (RecordRef(family=RecordFamily.SITUATION, record_id=scene["issue"]),)
    with runtime.engine.connect() as connection:
        cut = _cut(connection)
        plan = _plans(connection, lambda repo: repo.live_links_incident(PRINCIPAL, refs, cut))
        history = _plans(
            connection,
            lambda repo: repo.link_revisions_known_at(
                PRINCIPAL, scene["link"], cut, after=None, limit=26
            ),
        )
    for read in (plan, history):
        assert "record_link_revisions_pkey" in read, read
        assert "Seq Scan on record_link_revisions" not in read, read


def test_mark_resolution_uses_the_marked_at_index(runtime: S3ReadRuntime) -> None:
    _scene(runtime)
    # Many later marks (a synthetic seed past the real ones): resolving an
    # earlier cut must not walk them all from the top of the key.
    with runtime.engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "INSERT INTO knowledge.lineage_commit_marks "
                "(principal_id, commit_seq, marked_at, recorded_xact) "
                "SELECT :p, 1000 + n, now() + n * interval '1 second', "
                "(1000000 + n)::text::xid8 FROM generate_series(1, 20000) AS n"
            ),
            {"p": PRINCIPAL},
        )
    with runtime.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("ANALYZE knowledge.lineage_commit_marks"))
    with runtime.engine.connect() as connection:
        plan = _plans(
            connection,
            lambda repo: repo.commit_watermark(PRINCIPAL, datetime.now(UTC)),
        )
    assert "lineage_commit_marks_by_time" in plan, plan
    assert "Seq Scan on lineage_commit_marks" not in plan, plan


def _event_volume(runtime: S3ReadRuntime, copies: int = 20000) -> None:
    """Many synthetic Record Events of other records, so the record index means something.

    Copies of one real event under fresh `rcev_` ids, record ids and sequence
    numbers past the real ones; replica mode skips the feed's append-only
    trigger for this bulk seed (a synthetic database only).
    """
    with runtime.engine.begin() as connection:
        connection.execute(text("SET LOCAL session_replication_role = replica"))
        connection.execute(
            text(
                "INSERT INTO knowledge.record_events (event_id, principal_id, sequence_number, "
                "record_family, record_id, event_kind, record_version, changed_fields, "
                "source_capability, source_receipt_id, actor_class, authority, classification, "
                "correlation_id, causation_event_id, occurred_at, recorded_at) "
                "SELECT 'rcev_vol' || n || 'x' || substr(e.event_id, 6, 20), e.principal_id, "
                "1000000 + n, e.record_family, "
                "'tsk_vol' || n || 'x' || substr(e.record_id, 5, 20), e.event_kind, "
                "e.record_version, e.changed_fields, e.source_capability, NULL, "
                "e.actor_class, e.authority, e.classification, NULL, NULL, e.occurred_at, "
                "e.recorded_at FROM (SELECT * FROM knowledge.record_events "
                "WHERE principal_id = :p AND record_family = 'task' LIMIT 1) AS e, "
                "generate_series(1, :copies) AS n"
            ),
            {"p": PRINCIPAL, "copies": copies},
        )
    with runtime.engine.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(text("ANALYZE knowledge.record_events"))


def _statement_plans(connection: Connection, run: Callable[[], object]) -> str:
    """`_plans` for a step that is not a `SqlRecordLineageRepository` call."""
    return _plans(connection, lambda _repository: run())


def test_timeline_reads_use_the_issue_and_record_event_indexes(runtime: S3ReadRuntime) -> None:
    scene = _scene(runtime)
    issue = scene["issue"]
    commitment = runtime.commitment("plan-tl")
    runtime.member(issue, "commitment", commitment, "plan-tl", "discussion")
    created = str(runtime.commitment_view(commitment)["created_at"])
    runtime.ok(
        handoff(
            issue,
            commitment,
            "counterparty",
            shortly_after(created, 10),
            "plan-tl",
            runtime.handoff_anchor("plan-tl-handoff"),
        ),
        surface=GATEWAY,
    )
    _event_volume(runtime)
    inside = {
        RecordRef(family=RecordFamily.SITUATION, record_id=issue),
        RecordRef(family=RecordFamily.TASK, record_id=scene["first"]),
        RecordRef(family=RecordFamily.TASK, record_id=scene["second"]),
    }
    members = [(RecordEventFamily.TASK, scene["first"]), (RecordEventFamily.TASK, scene["second"])]
    with runtime.engine.connect() as connection:
        cut = _cut(connection)
        timeline = SqlIssueTimelineRepository(connection)
        lineage = SqlRecordLineageRepository(connection)
        handoffs = SqlIssueHandoffRepository(connection)
        revisions = _statement_plans(
            connection, lambda: timeline.issue_revisions(PRINCIPAL, issue, cut)
        )
        context = _statement_plans(
            connection, lambda: lineage.links_in_issue_context_at(PRINCIPAL, issue, inside, cut)
        )
        events = _statement_plans(
            connection,
            lambda: handoffs.known_events(
                PRINCIPAL,
                issue,
                commitment_id=None,
                page_size=100,
                after=None,
                watermark=cut.watermark,
                at=cut.at,
            ),
        )
        native = _statement_plans(
            connection,
            lambda: timeline.native_events(
                PRINCIPAL,
                members,
                families=frozenset({RecordEventFamily.TASK}),
                include_restricted_memory=True,
                occurred_at_most=None,
                sequence_at_most=None,
            ),
        )
        remote = _statement_plans(
            connection,
            lambda: timeline.native_events(
                PRINCIPAL,
                members,
                families=frozenset({RecordEventFamily.TASK}),
                include_restricted_memory=False,
                occurred_at_most=cut.at,
                sequence_at_most=10**9,
            ),
        )
    assert "issue_revisions_pkey" in revisions, revisions
    assert "Seq Scan on issue_revisions" not in revisions, revisions
    assert "record_links_by_issue" in context, context
    assert "Seq Scan on record_links " not in context, context
    assert "record_link_revisions_pkey" in context, context
    assert "issue_responsibility_events_by_issue" in events, events
    assert "Seq Scan on issue_responsibility_events" not in events, events
    for read in (native, remote):
        assert "record_events_by_principal_record" in read, read
        assert "Seq Scan on record_events" not in read, read
