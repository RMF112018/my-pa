"""AT-025: the backfill dry run, against PostgreSQL (S3 contract sections 4.2, 5 and 8.3).

`records.backfill.plan` freezes a population of legacy native shapes in one
statement and classifies it in resumable batches; `records.backfill.report`
reads the run back. Every test here drives both capabilities through
`ApplicationService.invoke` with the backfill sub-switch on, as the local
operator on the CLI surface, over **synthetic fixtures only** (S3 section 13:
no worker runs the dry run against any other database).

Native rows are seeded directly in one transaction with foreign keys and
deferred checks silenced (`session_replication_role = replica`; CHECKs still
apply), as the digest-parity test does, because a legacy row's parents need not
exist for the dry run to classify it. Records a link must name are real rows:
a Capture through `capture.create`, links through `records.associations.*`.
`database` tier on a disposable head-migrated clone per test.
"""

from __future__ import annotations

import hashlib
import json
import unicodedata
from collections.abc import Iterator
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, text
from sqlalchemy.engine import Connection

from my_pa.application.commands import (
    ArchiveCapture,
    EndRecordAssociation,
    PlanLineageBackfill,
    ReportLineageBackfill,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.domain.lineage.backfill import origin_reference, plan_digest
from my_pa.domain.lineage.canonical import normalized_identity
from my_pa.domain.lineage.model import RecordRef
from my_pa.domain.lineage.vocabulary import (
    RecordFamily,
    RecordLinkKind,
    RelationType,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.lineage_backfill import SqlLineageBackfillRepository
from my_pa.infrastructure.persistence.tables import (
    capture_assertion_spans,
    capture_assertions,
    capture_spans,
    commitments,
    meetings,
    project_constraint_relationships,
    project_situations,
    projects,
    situations,
    tasks,
)
from tests.database.lineage_issue_harness import OTHER_PRINCIPAL, PRINCIPAL, REMOTE_CLIENT
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    capture,
    capture_anchor,
    originated_from,
    restricted_capture_version,
)
from tests.database.lineage_s3_harness import (
    S3Runtime,
    all_s3_counts,
    contest,
    contradicts,
)

pytestmark = pytest.mark.database

CLI: Final = OperatorSurface.CLI
WHEN: Final = datetime(2026, 10, 19, 12, tzinfo=UTC)
#: A passage of `NOTE_BODY` an exact span quotes.
PASSAGE: Final = "façade survey"
#: Free-text references whose text must never reach a ledger row or a report.
FREE_TEXT: Final = "Café au lait — notes about the façade"
NON_NFC: Final = "Café north slab"
LONG_TEXT: Final = "Pour schedule " * 40


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[S3Runtime]:
    composed = S3Runtime(disposable_database, lineage_backfill_enabled=True)
    try:
        yield composed
    finally:
        composed.close()


# --- requests -----------------------------------------------------------------------


def plan(
    runtime: S3Runtime,
    key: str,
    *,
    run_id: str | None = None,
    checkpoint: int | None = None,
    batch: int | None = None,
    principal_id: str = PRINCIPAL,
) -> dict[str, Any]:
    return runtime.ok(
        PlanLineageBackfill(
            idempotency_key=f"backfill-{key}",
            run_id=run_id,
            expected_checkpoint=checkpoint,
            batch_size=batch,
        ),
        surface=CLI,
        principal_id=principal_id,
    )


def classify_all(runtime: S3Runtime, run_id: str, key: str, *, batch: int = 500) -> dict[str, Any]:
    """Classify a run to the end in batches of `batch`; the last answer."""
    answer = plan(runtime, f"{key}-0", run_id=run_id, checkpoint=0, batch=batch)
    step = 1
    while answer["run"]["state"] != "classified":
        answer = plan(
            runtime,
            f"{key}-{step}",
            run_id=run_id,
            checkpoint=answer["run"]["classified_count"],
            batch=batch,
        )
        step += 1
    return answer


def report(runtime: S3Runtime, run_id: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    return runtime.ok(ReportLineageBackfill(run_id=run_id, **kwargs), surface=CLI)


def every_item(runtime: S3Runtime, run_id: str) -> list[dict[str, Any]]:
    """Every item of a run, paged through the report."""
    items: list[dict[str, Any]] = []
    after: int | None = None
    while True:
        page = report(runtime, run_id, page_size=7, after=after)
        items.extend(page["items"])
        if page["next_cursor"] is None:
            return items
        after = page["next_cursor"]


def by_source(items: list[dict[str, Any]]) -> dict[tuple[str, str], dict[str, Any]]:
    """Items keyed by `(source_kind, source_id)` (one item each in these fixtures)."""
    keyed: dict[tuple[str, str], dict[str, Any]] = {}
    for item in items:
        key = (item["source_kind"], item["source_id"])
        assert key not in keyed, key
        keyed[key] = item
    return keyed


def settled(item: dict[str, Any]) -> tuple[str, str, bool]:
    return item["classification"], item["reason"], item["quarantined"]


def ledger(engine: Engine, run_id: str) -> list[dict[str, Any]]:
    with engine.connect() as c:
        rows = c.execute(
            text(
                "SELECT * FROM knowledge.lineage_backfill_items WHERE run_id = :r ORDER BY item_no"
            ),
            {"r": run_id},
        ).mappings()
        return [dict(row) for row in rows]


def run_row(engine: Engine, run_id: str) -> dict[str, Any]:
    with engine.connect() as c:
        return dict(
            c.execute(
                text("SELECT * FROM knowledge.lineage_backfill_runs WHERE run_id = :r"),
                {"r": run_id},
            )
            .mappings()
            .one()
        )


# --- native seeds ---------------------------------------------------------------------


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def native(engine: Engine) -> Any:  # noqa: ANN401 - a context manager over a Connection
    """One seeding transaction with foreign keys and deferred checks silenced."""

    class _Seeding:
        def __enter__(self) -> Connection:
            self._context = engine.begin()
            connection = self._context.__enter__()
            connection.execute(text("SET LOCAL session_replication_role = replica"))
            return connection

        def __exit__(self, *exc: object) -> None:
            self._context.__exit__(*exc)  # type: ignore[arg-type]

    return _Seeding()


def seed_task(
    c: Connection,
    *,
    reference: str | None = None,
    commitment_id: str | None = None,
    title: str = "Synthetic task",
    principal_id: str = PRINCIPAL,
    project_id: str | None = None,
) -> str:
    task_id = issue_identifier(IdKind.TASK)
    row: dict[str, object] = {
        "task_id": task_id,
        "principal_id": principal_id,
        "title": title,
        "origin_kind": "direct_principal",
        "opened_at": WHEN,
        "created_at": WHEN,
        "updated_at": WHEN,
        "commitment_id": commitment_id,
    }
    if reference is not None:
        row.update(origin_kind="evidence", origin_evidence_ref=reference)
    if project_id is not None:
        row["project_id"] = project_id
    c.execute(insert(tasks).values(**row))
    return task_id


def seed_commitment(c: Connection, reference: str, *, summary: str = "Synthetic") -> str:
    commitment_id = issue_identifier(IdKind.COMMITMENT)
    c.execute(
        insert(commitments).values(
            commitment_id=commitment_id,
            principal_id=PRINCIPAL,
            counterparty_entity_id=issue_identifier(IdKind.ENTITY),
            direction="owed_by_principal",
            summary=summary,
            origin_evidence_ref=reference,
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return commitment_id


def seed_meeting(c: Connection, series_id: str | None, *, title: str = "Synthetic") -> str:
    meeting_id = issue_identifier(IdKind.MEETING)
    c.execute(
        insert(meetings).values(
            meeting_id=meeting_id,
            principal_id=PRINCIPAL,
            meeting_series_id=series_id,
            title=title,
            start_at=WHEN,
            timezone_name="UTC",
            status="scheduled",
            version=1,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return meeting_id


def seed_follow_up(c: Connection) -> tuple[str, str]:
    source, target = (issue_identifier(IdKind.PROJECT_CONSTRAINT) for _ in range(2))
    c.execute(
        insert(project_constraint_relationships).values(
            relationship_id=issue_identifier(IdKind.PROJECT_CONSTRAINT_RELATIONSHIP),
            principal_id=PRINCIPAL,
            project_id=issue_identifier(IdKind.PROJECT),
            source_constraint_id=source,
            target_constraint_id=target,
            relationship_type="follow_up_of",
            created_by_history_id=issue_identifier(IdKind.PROJECT_CONSTRAINT_HISTORY),
            created_at=WHEN,
        )
    )
    return source, target


def seed_situation(c: Connection, *, object_refs: list[object] | None = None) -> str:
    situation_id = issue_identifier(IdKind.SITUATION)
    c.execute(
        insert(situations).values(
            situation_id=situation_id,
            principal_id=PRINCIPAL,
            title="Synthetic context",
            state="open",
            object_refs=object_refs or [],
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return situation_id


def seed_project(c: Connection, *, principal_id: str = PRINCIPAL) -> str:
    project_id = issue_identifier(IdKind.PROJECT)
    c.execute(
        insert(projects).values(
            project_id=project_id,
            principal_id=principal_id,
            name="Synthetic project",
            state="active",
            participants=[],
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return project_id


def seed_project_link(c: Connection, situation_id: str, project_id: str) -> None:
    c.execute(
        insert(project_situations).values(
            project_situation_id=issue_identifier(IdKind.PROJECT_SITUATION),
            project_id=project_id,
            situation_id=situation_id,
            principal_id=PRINCIPAL,
            linked_at=WHEN,
        )
    )


def seed_assertion(
    c: Connection,
    version_id: str,
    *,
    body: str = NOTE_BODY,
    passages: tuple[str, ...] = (PASSAGE,),
    state: str = "accepted",
    processing_text: bool = False,
) -> str:
    """An assertion on `version_id` citing one span per passage of `body`."""
    assertion_id = issue_identifier(IdKind.ASSERTION)
    c.execute(
        insert(capture_assertions).values(
            assertion_id=assertion_id,
            version_id=version_id,
            proposal_id=issue_identifier(IdKind.PROPOSAL),
            decision_id=issue_identifier(IdKind.REVIEW_DECISION),
            principal_id=PRINCIPAL,
            assertion_type="task",
            state=state,
            accepted_at=WHEN,
        )
    )
    for passage in passages:
        start = body.index(passage)
        end = start + len(passage)
        span_id = issue_identifier(IdKind.SPAN)
        c.execute(
            insert(capture_spans).values(
                span_id=span_id,
                version_id=version_id,
                processing_text_id=(
                    issue_identifier(IdKind.PROCESSING_TEXT) if processing_text else None
                ),
                start_offset=start,
                end_offset=end,
                offset_basis="unicode_code_point_v1",
                line_start=1,
                column_start=start + 1,
                line_end=1,
                column_end=end + 1,
                quoted_text_sha256=_sha(passage),
                span_role="direct",
            )
        )
        c.execute(
            insert(capture_assertion_spans).values(
                assertion_id=assertion_id, span_id=span_id, principal_id=PRINCIPAL
            )
        )
    return assertion_id


def enumerate_run(runtime: S3Runtime, key: str) -> dict[str, Any]:
    answer = plan(runtime, key)
    assert answer["items"] == []
    assert answer["run"]["state"] == "enumerated"
    assert answer["run"]["classified_count"] == 0
    return answer["run"]


# --- the corpus -----------------------------------------------------------------------


def corpus(runtime: S3Runtime) -> dict[str, Any]:
    """One of every source kind and every class, seeded natively; the expected classes."""
    capture_id, version_id, _ = capture(runtime, "bf-corpus")
    restricted = restricted_capture_version(runtime.engine, version_id)
    archived_capture, archived_version, _ = capture(runtime, "bf-corpus-archived")
    expected: dict[tuple[str, str], tuple[str, str, bool]] = {}
    with native(runtime.engine) as c:
        follow = seed_task(c, commitment_id=issue_identifier(IdKind.COMMITMENT))
        expected[("task_follow_up", follow)] = ("native_virtual_proven", "native_follow_up", False)
        source, _ = seed_follow_up(c)
        expected[("constraint_follow_up", source)] = (
            "native_virtual_proven",
            "native_constraint_follow_up",
            False,
        )
        series = seed_meeting(c, issue_identifier(IdKind.MEETING_SERIES))
        expected[("meeting_series", series)] = (
            "native_virtual_proven",
            "native_meeting_series",
            False,
        )
        seed_meeting(c, None)  # no Series: not in scope
        context = seed_situation(c)
        seed_project_link(c, context, seed_project(c))
        expected[("project_situation", context)] = (
            "native_virtual_proven",
            "native_project_situation",
            False,
        )
        orphan = seed_situation(c)
        seed_project_link(c, orphan, issue_identifier(IdKind.PROJECT))  # no such Project
        expected[("project_situation", orphan)] = (
            "unresolved",
            "project_situation_inconsistent",
            True,
        )
        exact = seed_task(c, reference=seed_assertion(c, version_id))
        expected[("work_origin_assertion", exact)] = (
            "source_backed_accepted",
            "exact_original_span",
            False,
        )
        normalized = seed_task(c, reference=seed_assertion(c, version_id, processing_text=True))
        expected[("work_origin_assertion", normalized)] = (
            "review_candidate",
            "passage_unproven",
            False,
        )
        stale = seed_task(c, reference=seed_assertion(c, version_id, state="superseded"))
        expected[("work_origin_assertion", stale)] = ("refused", "assertion_not_current", True)
        hidden = seed_task(c, reference=seed_assertion(c, restricted))
        expected[("work_origin_assertion", hidden)] = ("refused", "source_restricted", True)
        withdrawn = seed_task(c, reference=seed_assertion(c, archived_version))
        expected[("work_origin_assertion", withdrawn)] = ("refused", "source_withdrawn", True)
        nowhere = seed_task(c, reference=issue_identifier(IdKind.ASSERTION))
        expected[("work_origin_assertion", nowhere)] = (
            "unresolved",
            "reference_unresolvable",
            True,
        )
        root = seed_commitment(c, capture_id)
        expected[("work_origin_capture_root", root)] = ("unresolved", "no_exact_version", True)
        for reference in (
            issue_identifier(IdKind.MEETING_NOTE_VERSION),
            FREE_TEXT,
            "asrt_not-an-identifier",
        ):
            other = seed_task(c, reference=reference)
            expected[("work_origin_other", other)] = ("unresolved", "origin_ref_unsupported", True)
        owned = seed_task(c)
        objects = seed_situation(c, object_refs=[owned])
        expected[("situation_object_ref", objects)] = (
            "review_candidate",
            "object_ref_unproven",
            False,
        )
    runtime.ok(_archive(archived_capture))
    return {
        "expected": expected,
        "capture_id": capture_id,
        "version_id": version_id,
        "exact": exact,
        "normalized": normalized,
        "root": root,
        "objects": objects,
        "owned": owned,
    }


def _archive(capture_id: str) -> ArchiveCapture:
    return ArchiveCapture(
        capture_id=capture_id,
        expected_lifecycle_revision=0,
        idempotency_key=f"backfill-archive-{capture_id}",
        reason="Synthetic backfill withdrawal",
    )


# --- tests ------------------------------------------------------------------------------


def test_every_source_in_scope_is_classified_once(runtime: S3Runtime) -> None:
    seeded = corpus(runtime)
    expected = seeded["expected"]
    run = enumerate_run(runtime, "once")
    assert run["population_count"] == len(expected)
    # Small batches: every call classifies the next items, never one twice.
    seen: list[int] = []
    answer = plan(runtime, "once-0", run_id=run["run_id"], checkpoint=0, batch=3)
    seen.extend(item["item_no"] for item in answer["items"])
    step = 1
    while answer["run"]["state"] != "classified":
        assert len(answer["items"]) == 3
        answer = plan(
            runtime,
            f"once-{step}",
            run_id=run["run_id"],
            checkpoint=answer["run"]["classified_count"],
            batch=3,
        )
        seen.extend(item["item_no"] for item in answer["items"])
        step += 1
    assert seen == list(range(1, len(expected) + 1))
    assert answer["run"]["classified_count"] == len(expected)
    assert len(str(answer["run"]["plan_digest"])) == 64
    items = every_item(runtime, run["run_id"])
    assert {key: settled(item) for key, item in by_source(items).items()} == expected
    # Every row settled exactly once, each with a time.
    rows = ledger(runtime.engine, run["run_id"])
    assert all(row["classified_at"] is not None for row in rows)
    # A classified run classifies nothing more, and a moved checkpoint is refused.
    again = plan(runtime, "once-after", run_id=run["run_id"], checkpoint=len(expected), batch=3)
    assert again["items"] == [] and again["run"] == answer["run"]
    stale = runtime.refused(
        PlanLineageBackfill(
            idempotency_key="backfill-once-stale",
            run_id=run["run_id"],
            expected_checkpoint=0,
        ),
        surface=CLI,
    )
    assert (stale["code"], stale["safe_details"]) == ("conflict", ["checkpoint"])
    assert ledger(runtime.engine, run["run_id"]) == rows


def test_every_origin_reference_is_enumerated_and_unsupported_ones_are_unresolved(
    runtime: S3Runtime,
) -> None:
    capture_id, version_id, _ = capture(runtime, "bf-refs")
    with native(runtime.engine) as c:
        references = {
            "assertion": seed_assertion(c, version_id),
            "capture": capture_id,
            "note": issue_identifier(IdKind.MEETING_NOTE_VERSION),
            "decision": issue_identifier(IdKind.REVIEW_DECISION),
            "free": FREE_TEXT,
            "non_nfc": NON_NFC,
            "asrt_text": "asrt_not-an-identifier",
            "cap_text": "cap_short",
            "long": LONG_TEXT,
        }
        work = {name: seed_task(c, reference=ref) for name, ref in references.items()}
        commitment = seed_commitment(c, "Promised in the hallway")
    run = enumerate_run(runtime, "refs")
    classify_all(runtime, run["run_id"], "refs")
    items = every_item(runtime, run["run_id"])
    origin = {
        item["source_id"]: item for item in items if item["source_kind"].startswith("work_origin")
    }
    # Every reference is an item: the population is assigned by shape, not by prefix.
    assert set(origin) == {*work.values(), commitment}
    for name, task_id in work.items():
        kind, token = origin_reference(references[name])
        assert (origin[task_id]["source_kind"], origin[task_id]["source_ref"]) == (
            kind.value,
            token,
        ), name
    unsupported = ("note", "decision", "free", "non_nfc", "asrt_text", "cap_text", "long")
    for name in unsupported:
        item = origin[work[name]]
        assert item["source_kind"] == "work_origin_other", name
        assert settled(item) == ("unresolved", "origin_ref_unsupported", True), name
        assert item["candidate_relation"] is None
    assert origin[work["note"]]["source_ref"].startswith("prefix:mnote:")
    assert origin[work["free"]]["source_ref"] == f"free_text:{_sha(FREE_TEXT)}"
    assert settled(origin[commitment]) == ("unresolved", "origin_ref_unsupported", True)
    assert settled(origin[work["capture"]]) == ("unresolved", "no_exact_version", True)
    assert settled(origin[work["assertion"]])[0] == "source_backed_accepted"


def test_a_plan_writes_no_link_fact_or_mark(runtime: S3Runtime) -> None:
    corpus(runtime)
    # A lineage write first, so the Principal holds an allocator row and a mark.
    issue = runtime.issue("bf-nofact")
    before = all_s3_counts(runtime.engine)
    with runtime.engine.connect() as c:
        allocator = c.execute(
            text(
                "SELECT last_seq, last_marked_at FROM knowledge.lineage_commit_sequences "
                "ORDER BY principal_id"
            )
        ).all()
    run = enumerate_run(runtime, "nofact")
    classify_all(runtime, run["run_id"], "nofact", batch=4)
    after = all_s3_counts(runtime.engine)
    written = {name for name in after if after[name] != before[name]}
    assert written == {"lineage_backfill_runs", "lineage_backfill_items", "lineage_write_requests"}
    with runtime.engine.connect() as c:
        assert (
            c.execute(
                text(
                    "SELECT last_seq, last_marked_at FROM knowledge.lineage_commit_sequences "
                    "ORDER BY principal_id"
                )
            ).all()
            == allocator
        )
        requests = c.execute(
            text(
                "SELECT commit_seq, result_backfill_run_id, result_backfill_checkpoint "
                "FROM knowledge.lineage_write_requests WHERE capability = 'records.backfill.plan' "
                "ORDER BY result_backfill_checkpoint"
            )
        ).all()
    assert requests and all(row.commit_seq is None for row in requests)
    assert {row.result_backfill_run_id for row in requests} == {run["run_id"]}
    assert run_row(runtime.engine, run["run_id"])["commit_seq_cutoff"] == allocator[0].last_seq
    assert issue


def test_an_exact_original_span_origin_is_source_backed_in_the_report_only(
    runtime: S3Runtime,
) -> None:
    capture_id, version_id, content_sha = capture(runtime, "bf-exact")
    with native(runtime.engine) as c:
        assertion = seed_assertion(c, version_id, passages=(PASSAGE, "Next: pour"))
        task_id = seed_task(c, reference=assertion)
    before = all_s3_counts(runtime.engine)
    run = enumerate_run(runtime, "exact")
    classify_all(runtime, run["run_id"], "exact")
    (item,) = every_item(runtime, run["run_id"])
    assert settled(item) == ("source_backed_accepted", "exact_original_span", False)
    assert item["candidate_relation"] == "originated_from"
    assert (item["existing_link_id"], item["existing_link_state"]) == (None, "none")
    (row,) = ledger(runtime.engine, run["run_id"])
    expected_identity = normalized_identity(
        kind=RecordLinkKind.SEMANTIC,
        relation_type=RelationType.ORIGINATED_FROM,
        from_ref=RecordRef(family=RecordFamily.TASK, record_id=task_id),
        to_ref=RecordRef(family=RecordFamily.CAPTURE_VERSION, record_id=version_id),
        member_role=None,
        context_issue_id=None,
    )
    assert row["candidate_identity"] == expected_identity
    candidate = json.loads(row["candidate"])
    anchors = candidate.pop("evidence")
    assert candidate == json.loads(expected_identity)
    assert len(anchors) == 2
    for anchor in anchors:
        assert anchor["role"] == "origin"
        assert anchor["source_family"] == "capture_version"
        assert anchor["source_root_id"] == capture_id
        assert anchor["source_version_id"] == version_id
        assert anchor["source_sha256"] == content_sha
        start, end = anchor["passage_start_cp"], anchor["passage_end_cp"]
        assert anchor["passage_sha256"] == _sha(NOTE_BODY[start:end])
    # In the report only: no link, revision, anchor or mark was written.
    after = all_s3_counts(runtime.engine)
    assert {name for name in after if after[name] != before[name]} == {
        "lineage_backfill_runs",
        "lineage_backfill_items",
        "lineage_write_requests",
    }


def test_a_normalized_text_span_is_only_a_review_candidate(runtime: S3Runtime) -> None:
    _, version_id, _ = capture(runtime, "bf-normalized")
    with native(runtime.engine) as c:
        normalized = seed_task(c, reference=seed_assertion(c, version_id, processing_text=True))
        exact = seed_task(c, reference=seed_assertion(c, version_id))
    run = enumerate_run(runtime, "normalized")
    classify_all(runtime, run["run_id"], "normalized")
    items = by_source(every_item(runtime, run["run_id"]))
    review = items[("work_origin_assertion", normalized)]
    assert settled(review) == ("review_candidate", "passage_unproven", False)
    # The link is derivable, but no anchor is proven: the candidate carries none.
    assert review["candidate_relation"] == "originated_from"
    rows = {row["source_id"]: row for row in ledger(runtime.engine, run["run_id"])}
    assert json.loads(rows[normalized]["candidate"])["evidence"] == []
    assert settled(items[("work_origin_assertion", exact)])[0] == "source_backed_accepted"


def test_object_refs_are_never_accepted(runtime: S3Runtime) -> None:
    _, version_id, _ = capture(runtime, "bf-objects")
    with native(runtime.engine) as c:
        owned_task = seed_task(c)
        foreign_task = seed_task(c, principal_id=OTHER_PRINCIPAL)
        absent_task = issue_identifier(IdKind.TASK)
        project = seed_project(c)
        refs: list[object] = [
            owned_task,
            version_id,
            foreign_task,
            absent_task,
            project,
            FREE_TEXT,
            42,
            owned_task,  # repeated: one source
        ]
        situation = seed_situation(c, object_refs=refs)
    run = enumerate_run(runtime, "objects")
    classify_all(runtime, run["run_id"], "objects")
    items = [
        item
        for item in every_item(runtime, run["run_id"])
        if item["source_kind"] == "situation_object_ref"
    ]
    assert all(item["source_id"] == situation for item in items)
    by_ref = {item["source_ref"]: item for item in items}
    assert set(by_ref) == {
        owned_task,
        version_id,
        foreign_task,
        absent_task,
        project,
        f"free_text:{_sha(FREE_TEXT)}",
        f"free_text:{_sha('42')}",
    }
    for owned in (owned_task, version_id):
        assert settled(by_ref[owned]) == ("review_candidate", "object_ref_unproven", False)
    for unresolved in set(by_ref) - {owned_task, version_id}:
        assert settled(by_ref[unresolved]) == ("unresolved", "reference_unresolvable", True)
    # Never accepted, and never a candidate link.
    assert all(item["classification"] != "source_backed_accepted" for item in items)
    assert all(item["candidate_relation"] is None for item in items)
    rendered = json.dumps(report(runtime, run["run_id"]), ensure_ascii=False)
    assert FREE_TEXT not in rendered


def test_a_capture_root_origin_is_unresolved(runtime: S3Runtime) -> None:
    capture_id, _, _ = capture(runtime, "bf-root")
    with native(runtime.engine) as c:
        task_id = seed_task(c, reference=capture_id)
        commitment_id = seed_commitment(c, capture_id)
    run = enumerate_run(runtime, "root")
    classify_all(runtime, run["run_id"], "root")
    items = by_source(every_item(runtime, run["run_id"]))
    for key in (("work_origin_capture_root", task_id), ("work_origin_capture_root", commitment_id)):
        item = items[key]
        assert item["source_ref"] == capture_id
        assert settled(item) == ("unresolved", "no_exact_version", True)
        assert item["candidate_relation"] is None
        assert item["existing_link_state"] == "none"


def test_an_inconsistent_project_situation_is_quarantined(runtime: S3Runtime) -> None:
    linked_issue = runtime.issue("bf-ps-linked")
    linked_project = runtime.project("bf-ps-linked")
    runtime.link_project(linked_issue, linked_project, "bf-ps-linked")
    unlinked_issue = runtime.issue("bf-ps-unlinked")
    with native(runtime.engine) as c:
        context = seed_situation(c)
        seed_project_link(c, context, seed_project(c))
        # An Issue whose membership-event ledger has no event for its triplet.
        seed_project_link(c, unlinked_issue, seed_project(c))
        # A Project of another Principal.
        foreign = seed_situation(c)
        seed_project_link(c, foreign, seed_project(c, principal_id=OTHER_PRINCIPAL))
    run = enumerate_run(runtime, "ps")
    classify_all(runtime, run["run_id"], "ps")
    items = by_source(every_item(runtime, run["run_id"]))
    proven = ("native_virtual_proven", "native_project_situation", False)
    inconsistent = ("unresolved", "project_situation_inconsistent", True)
    assert settled(items[("project_situation", linked_issue)]) == proven
    assert settled(items[("project_situation", context)]) == proven
    assert settled(items[("project_situation", unlinked_issue)]) == inconsistent
    assert settled(items[("project_situation", foreign)]) == inconsistent
    answer = report(runtime, run["run_id"])
    assert answer["census"]["project_situation"] == {"consistent": 2, "inconsistent": 2}
    assert answer["counts"]["quarantined"] == 2


def test_existing_links_are_reported_in_any_context_and_state_at_the_cutoff(
    runtime: S3Runtime,
) -> None:
    capture_id, version_id, _ = capture(runtime, "bf-existing")
    with native(runtime.engine) as c:
        tasks_by_case = {
            case: seed_task(c, reference=seed_assertion(c, version_id))
            for case in ("scoped_ended", "contested", "ended_after", "after", "none")
        }
    anchor = capture_anchor(capture_id, version_id, NOTE_BODY)
    issue = runtime.issue("bf-existing")
    for case in tasks_by_case:
        runtime.member(issue, "task", tasks_by_case[case], f"bf-existing-{case}", "reference")

    def assert_link(case: str, key: str, *, context: str | None) -> str:
        written = runtime.ok(
            originated_from(
                "task",
                tasks_by_case[case],
                "capture_version",
                version_id,
                key,
                (anchor,),
                context_issue_id=context,
            ),
            surface=CLI,
        )
        return str(written["association"]["link_id"])

    # An Issue-scoped link, ended before the cutoff: found in any context and state.
    scoped = assert_link("scoped_ended", "bf-ex-scoped", context=issue)
    runtime.ok(
        EndRecordAssociation(
            link_id=scoped,
            expected_revision=1,
            idempotency_key="bf-ex-scoped-end",
            reason="Synthetic end",
        ),
        surface=CLI,
    )
    # A contested link with a null context.
    disputed = assert_link("contested", "bf-ex-contested", context=None)
    meeting_id, note_id = runtime.note("bf-ex-contradicts")
    contradicting = contradicts(meeting_id, note_id)
    runtime.ok(contest(disputed, 1, "bf-ex-contest", (contradicting,)), surface=CLI)
    # Active at the cutoff, ended after it.
    later_ended = assert_link("ended_after", "bf-ex-ended-after", context=None)
    run = enumerate_run(runtime, "existing")
    runtime.ok(
        EndRecordAssociation(
            link_id=later_ended,
            expected_revision=1,
            idempotency_key="bf-ex-ended-after-end",
            reason="Synthetic end",
        ),
        surface=CLI,
    )
    # Asserted after the cutoff: not this run's fact.
    assert_link("after", "bf-ex-after", context=None)
    classify_all(runtime, run["run_id"], "existing")
    items = by_source(every_item(runtime, run["run_id"]))
    found = {
        case: (
            items[("work_origin_assertion", task_id)]["existing_link_id"],
            items[("work_origin_assertion", task_id)]["existing_link_state"],
        )
        for case, task_id in tasks_by_case.items()
    }
    assert found == {
        "scoped_ended": (scoped, "ended"),
        "contested": (disputed, "contested"),
        "ended_after": (later_ended, "active"),
        "after": (None, "none"),
        "none": (None, "none"),
    }
    answer = report(runtime, run["run_id"])
    assert answer["counts"]["existing_link_state"] == {
        "none": 2,
        "active": 1,
        "contested": 1,
        "ended": 1,
    }


def test_an_interrupted_plan_resumes_to_the_same_plan_digest(
    runtime: S3Runtime, monkeypatch: pytest.MonkeyPatch
) -> None:
    corpus(runtime)
    interrupted = enumerate_run(runtime, "resume-a")["run_id"]
    straight = enumerate_run(runtime, "resume-b")["run_id"]
    answer = plan(runtime, "resume-a-0", run_id=interrupted, checkpoint=0, batch=2)
    # Interrupt the next call after its items are settled: the transaction rolls back.
    original = SqlLineageBackfillRepository.advance_run

    def interrupt(*args: Any, **kwargs: Any) -> None:  # noqa: ANN401
        raise RuntimeError("synthetic interruption")

    monkeypatch.setattr(SqlLineageBackfillRepository, "advance_run", interrupt)
    failed = runtime.invoke(
        PlanLineageBackfill(
            idempotency_key="backfill-resume-a-1",
            run_id=interrupted,
            expected_checkpoint=2,
            batch_size=3,
        ),
        surface=CLI,
    )
    assert failed.error is not None
    monkeypatch.setattr(SqlLineageBackfillRepository, "advance_run", original)
    assert run_row(runtime.engine, interrupted)["classified_count"] == 2
    assert (
        sum(row["classification"] is not None for row in ledger(runtime.engine, interrupted)) == 2
    )
    # Resume from the previous checkpoint, in other batch sizes.
    answer = plan(runtime, "resume-a-1b", run_id=interrupted, checkpoint=2, batch=5)
    step = 2
    while answer["run"]["state"] != "classified":
        answer = plan(
            runtime,
            f"resume-a-{step}",
            run_id=interrupted,
            checkpoint=answer["run"]["classified_count"],
            batch=1 + step % 3,
        )
        step += 1
    resumed = answer["run"]
    whole = plan(runtime, "resume-b-0", run_id=straight, checkpoint=0, batch=500)["run"]
    assert whole["state"] == "classified"

    def settled_rows(run_id: str) -> list[tuple[object, ...]]:
        return [
            (
                row["item_no"],
                row["source_kind"],
                row["source_id"],
                row["source_ref"],
                row["source_digest"],
                row["classification"],
                row["reason"],
                row["candidate_identity"],
                row["candidate"],
                row["existing_link_id"],
                row["existing_link_state"],
                row["quarantined"],
            )
            for row in ledger(runtime.engine, run_id)
        ]

    assert settled_rows(interrupted) == settled_rows(straight)
    # The digest binds the run: the same items under the other run's identifier.
    items = [
        (
            row["item_no"],
            row["source_digest"],
            row["classification"],
            row["reason"],
            row["candidate_identity"],
        )
        for row in ledger(runtime.engine, straight)
    ]
    assert resumed["plan_digest"] == plan_digest(
        run_id=interrupted, validator_version=1, items=items
    )
    assert whole["plan_digest"] == plan_digest(run_id=straight, validator_version=1, items=items)


def test_a_source_changed_after_enumeration_is_quarantined(runtime: S3Runtime) -> None:
    seeded = corpus(runtime)
    run = enumerate_run(runtime, "changed")
    with native(runtime.engine) as c:
        # A re-pointed follow-up, a rewritten origin reference, a grown object_refs.
        follow = next(
            source_id for kind, source_id in seeded["expected"] if kind == "task_follow_up"
        )
        c.execute(
            text("UPDATE knowledge.tasks SET commitment_id = :c, version = 2 WHERE task_id = :t"),
            {"c": issue_identifier(IdKind.COMMITMENT), "t": follow},
        )
        c.execute(
            text(
                "UPDATE knowledge.commitments SET origin_evidence_ref = 'Rewritten origin' "
                "WHERE commitment_id = :c"
            ),
            {"c": seeded["root"]},
        )
        c.execute(
            text(
                "UPDATE knowledge.situations SET object_refs = object_refs || '[\"more\"]'::jsonb "
                "WHERE situation_id = :s"
            ),
            {"s": seeded["objects"]},
        )
    classify_all(runtime, run["run_id"], "changed", batch=4)
    items = by_source(every_item(runtime, run["run_id"]))
    changed = {
        ("task_follow_up", follow),
        ("work_origin_capture_root", seeded["root"]),
        ("situation_object_ref", seeded["objects"]),
    }
    for key, expected in seeded["expected"].items():
        if key in changed:
            assert settled(items[key]) == ("unresolved", "source_changed", True), key
            assert items[key]["candidate_relation"] is None
        else:
            assert settled(items[key]) == expected, key
    assert report(runtime, run["run_id"])["counts"]["reason"]["source_changed"] == 3


def test_a_late_source_is_reported_not_classified(runtime: S3Runtime) -> None:
    seeded = corpus(runtime)
    run = enumerate_run(runtime, "late")
    with native(runtime.engine) as c:
        late_follow = seed_task(c, commitment_id=issue_identifier(IdKind.COMMITMENT))
        late_origin = seed_commitment(c, "A late free-text origin")
    final = classify_all(runtime, run["run_id"], "late")
    assert final["run"]["population_count"] == len(seeded["expected"])
    answer = report(runtime, run["run_id"])
    assert answer["late_source_count"] == 2
    ids = {item["source_id"] for item in every_item(runtime, run["run_id"])}
    assert late_follow not in ids and late_origin not in ids
    # A new run holds them.
    fresh = enumerate_run(runtime, "late-fresh")
    assert fresh["population_count"] == len(seeded["expected"]) + 2
    assert report(runtime, fresh["run_id"])["late_source_count"] == 0


def test_the_census_counts_every_examined_row(runtime: S3Runtime) -> None:
    capture_id, version_id, _ = capture(runtime, "bf-census")
    with native(runtime.engine) as c:
        for _ in range(3):
            seed_task(c, commitment_id=issue_identifier(IdKind.COMMITMENT))
        seed_task(c)  # no follow-up, no origin: examined by no kind
        for _ in range(2):
            seed_follow_up(c)
        seed_meeting(c, issue_identifier(IdKind.MEETING_SERIES))
        seed_meeting(c, None)
        consistent = seed_situation(c)
        seed_project_link(c, consistent, seed_project(c))
        orphan = seed_situation(c)
        seed_project_link(c, orphan, issue_identifier(IdKind.PROJECT))
        seed_task(c, reference=seed_assertion(c, version_id))
        seed_commitment(c, issue_identifier(IdKind.ASSERTION))
        seed_task(c, reference=capture_id)
        seed_task(c, reference=issue_identifier(IdKind.MEETING_NOTE_VERSION))
        seed_commitment(c, FREE_TEXT)
        seed_commitment(c, "asrt_not-an-identifier")
        seed_situation(c, object_refs=[issue_identifier(IdKind.TASK), FREE_TEXT, FREE_TEXT])
        # Another Principal's rows are never examined.
        seed_task(
            c, commitment_id=issue_identifier(IdKind.COMMITMENT), principal_id=OTHER_PRINCIPAL
        )
    run = enumerate_run(runtime, "census")
    census = report(runtime, run["run_id"])["census"]
    kinds = {
        "task_follow_up": 3,
        "constraint_follow_up": 2,
        "meeting_series": 1,
        "project_situation": 2,
        "work_origin_assertion": 2,
        "work_origin_capture_root": 1,
        "work_origin_other": 3,
        "situation_object_ref": 2,
    }
    assert census == {
        "schema_version": 1,
        "kinds": {kind: {"examined": count, "enumerated": count} for kind, count in kinds.items()},
        "origin_reference_shapes": {
            "task": {"asrt_": 1, "cap_": 1, "other_prefix": 1, "not_an_identifier": 0},
            "commitment": {"asrt_": 1, "cap_": 0, "other_prefix": 0, "not_an_identifier": 2},
        },
        "project_situation": {"consistent": 1, "inconsistent": 1},
    }
    assert run["population_count"] == sum(kinds.values())
    assert run_row(runtime.engine, run["run_id"])["census"] == census


def test_the_report_carries_no_origin_reference_text(runtime: S3Runtime) -> None:
    texts = (FREE_TEXT, NON_NFC, LONG_TEXT, "asrt_not-an-identifier")
    assert unicodedata.normalize("NFC", NON_NFC) != NON_NFC
    with native(runtime.engine) as c:
        work = [seed_task(c, reference=value) for value in texts]
        work.append(seed_commitment(c, FREE_TEXT))
        seed_situation(c, object_refs=[NON_NFC])
    run = enumerate_run(runtime, "notext")
    classify_all(runtime, run["run_id"], "notext")
    pages = [report(runtime, run["run_id"], page_size=2)]
    while pages[-1]["next_cursor"] is not None:
        pages.append(report(runtime, run["run_id"], page_size=2, after=pages[-1]["next_cursor"]))
    rendered = json.dumps(pages, ensure_ascii=False)
    stored = json.dumps(
        [ledger(runtime.engine, run["run_id"]), run_row(runtime.engine, run["run_id"])],
        default=str,
        ensure_ascii=False,
    )
    for value in texts:
        for fragment in (value, value[:8], unicodedata.normalize("NFC", value)[:8]):
            if fragment.startswith("asrt_"):
                fragment = value  # the identifier-looking prefix is a shape token
            assert fragment not in rendered, fragment
            assert fragment not in stored, fragment
    for row in ledger(runtime.engine, run["run_id"]):
        assert row["source_ref"].isascii()
        if row["source_kind"] in ("work_origin_other", "situation_object_ref"):
            assert row["source_ref"].startswith("free_text:")
            assert len(row["source_ref"]) == len("free_text:") + 64
    assert len(work) == 5


def test_no_candidate_comes_from_words_projects_series_or_dates(runtime: S3Runtime) -> None:
    capture_id, version_id, _ = capture(runtime, "bf-words")
    project = runtime.project("bf-words")
    series = issue_identifier(IdKind.MEETING_SERIES)
    with native(runtime.engine) as c:
        explicit = seed_task(c, reference=seed_assertion(c, version_id))
        # Same words as the Capture, same Project, same Series, same dates -- and no
        # explicit exact reference: never a candidate.
        seed_task(c, reference=NOTE_BODY, title=NOTE_BODY, project_id=project)
        seed_task(c, title=PASSAGE, project_id=project, commitment_id=None)
        seed_commitment(c, NOTE_BODY, summary=NOTE_BODY)
        seed_meeting(c, series, title=NOTE_BODY)
        seed_meeting(c, series, title=PASSAGE)
        situation = seed_situation(c, object_refs=[NOTE_BODY])
        seed_project_link(c, situation, project)
    run = enumerate_run(runtime, "words")
    classify_all(runtime, run["run_id"], "words")
    items = every_item(runtime, run["run_id"])
    with_candidate = [item for item in items if item["candidate_relation"] is not None]
    assert [(item["source_kind"], item["source_id"]) for item in with_candidate] == [
        ("work_origin_assertion", explicit)
    ]
    rows = {row["source_id"]: row for row in ledger(runtime.engine, run["run_id"])}
    candidate = json.loads(rows[explicit]["candidate"])
    assert candidate["to"]["record_id"] == version_id
    assert all(row["candidate"] is None for source_id, row in rows.items() if source_id != explicit)
    series_items = [item for item in items if item["source_kind"] == "meeting_series"]
    assert len(series_items) == 2
    assert all(settled(item)[0] == "native_virtual_proven" for item in series_items)
    assert capture_id


def test_backfill_is_operator_only_attested_and_behind_its_own_switch(
    disposable_database: str,
) -> None:
    on = S3Runtime(disposable_database, lineage_backfill_enabled=True)
    try:
        corpus(on)
        run = enumerate_run(on, "switch")
        before = all_s3_counts(on.engine)
        backfill_rows = (
            ledger(on.engine, run["run_id"]),
            run_row(on.engine, run["run_id"]),
        )
        commands = (
            PlanLineageBackfill(idempotency_key="backfill-switch-denied"),
            PlanLineageBackfill(
                idempotency_key="backfill-switch-denied-2",
                run_id=run["run_id"],
                expected_checkpoint=0,
            ),
            ReportLineageBackfill(run_id=run["run_id"]),
        )
        for command in commands:
            # An ordinary remote client, and an unstamped local caller: denied.
            for kwargs in ({"remote_client": REMOTE_CLIENT}, {}):
                error = on.refused(command, **kwargs)
                assert error["code"] == "denied", (command.capability.value, kwargs)
        assert all_s3_counts(on.engine) == before
        assert (ledger(on.engine, run["run_id"]), run_row(on.engine, run["run_id"])) == (
            backfill_rows
        )
        assert on.service.available_capabilities >= {command.capability for command in commands}
    finally:
        on.close()
    for lineage, backfill in ((True, False), (False, True), (False, False)):
        off = S3Runtime(
            disposable_database, lineage_enabled=lineage, lineage_backfill_enabled=backfill
        )
        try:
            before_off = all_s3_counts(off.engine)
            for command in commands:
                error = off.refused(command, surface=CLI)
                assert error["code"] == "unsupported", (lineage, backfill, command.capability)
                assert command.capability not in off.service.available_capabilities
            assert all_s3_counts(off.engine) == before_off
            assert run_row(off.engine, run["run_id"]) == backfill_rows[1]
        finally:
            off.close()
