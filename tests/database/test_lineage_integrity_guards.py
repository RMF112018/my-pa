"""AT-012: the record lineage S1 integrity guards, on a live server.

The record lineage S1 revision (S1 contract section 4) puts the S1 invariants in the
database so that they hold for every writer, not only for the application:
append-only and TRUNCATE refusal, the head and write-request transitions, the
deferred commit checks, the Situation kind and version rule, same-Principal
and digest-bearing foreign keys, the anchor family, passage and identity
checks, the local-operator attestation CHECK and the linked-record delete
refusal. Each test here drives one family of those guards with direct SQL
inserts -- there is no application writer in this slice of S1 -- and asserts
the SQLSTATE and the guard's own message or constraint name, so a test can only
pass for the reason it names.

`database` tier on a disposable head-migrated clone per test. Every value is
synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, insert, select, text, update
from sqlalchemy.engine import Connection
from sqlalchemy.exc import DBAPIError

from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.lineage.canonical import ANCHOR_KEYS, canonical_json
from my_pa.domain.lineage.vocabulary import LinkLifecycleState
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.principal_scope import capture_context, principal_scoped
from my_pa.infrastructure.persistence.record_lineage import LinkHeadRow, rebuild_link_heads
from my_pa.infrastructure.persistence.tables import (
    capture_versions,
    captures,
    issue_project_membership_events,
    issue_revisions,
    lineage_evidence_anchors,
    lineage_write_requests,
    meeting_history,
    meeting_note_versions,
    meetings,
    project_situations,
    projects,
    record_link_heads,
    record_link_revision_evidence,
    record_link_revisions,
    record_links,
    situations,
    tasks,
)

pytestmark = pytest.mark.database

P: Final = "prn_lineageguard0001"
Q: Final = "prn_lineageguard0002"
WHEN: Final = datetime(2026, 10, 17, 12, tzinfo=UTC)
#: A note body with a two-byte, a combining and a four-byte character, so a
#: passage offset is only right when it counts code points.
BODY: Final = "Agreed: café vendor; café later \U0001f600 C1 due Friday."

RESTRICT: Final = "23001"
FOREIGN_KEY: Final = "23503"
CHECK: Final = "23514"

#: The six immutable tables and a column each can be "updated" through.
IMMUTABLE: Final[dict[str, str]] = {
    "issue_revisions": "title",
    "issue_project_membership_events": "reason",
    "record_links": "created_at",
    "record_link_revisions": "reason",
    "lineage_evidence_anchors": "recorded_at",
    "record_link_revision_evidence": "role",
}
ALL_TABLES: Final = (
    "lineage_evidence_anchors",
    "issue_revisions",
    "issue_project_membership_events",
    "record_links",
    "record_link_revisions",
    "record_link_revision_evidence",
    "record_link_heads",
    "lineage_write_requests",
)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


EMPTY_SET_DIGEST: Final = hashlib.sha256(
    b"lineage-evidence-set-v1\n" + b'{"anchors":[],"schema_version":1}'
).hexdigest()


def _refused(
    engine: Engine, statement: Callable[[Connection], object], sqlstate: str, needle: str
) -> None:
    """`statement` (or its commit) fails with `sqlstate`, naming `needle`."""
    with pytest.raises(DBAPIError) as refused, engine.begin() as connection:
        statement(connection)
    assert getattr(refused.value.orig, "sqlstate", None) == sqlstate, refused.value
    assert needle in str(refused.value), refused.value


# ------------------------------------------------------------------ seeding


def _issue(c: Connection, principal: str, *, title: str = "Synthetic issue") -> str:
    issue_id = issue_identifier(IdKind.SITUATION)
    c.execute(
        insert(situations).values(
            situation_id=issue_id,
            principal_id=principal,
            title=title,
            state="open",
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
            kind="issue_workstream",
            version=1,
        )
    )
    c.execute(insert(issue_revisions).values(**_revision_values(principal, issue_id, 1, title)))
    return issue_id


def _revision_values(
    principal: str,
    issue_id: str,
    version: int,
    title: str,
    *,
    state: str = "open",
    action: str | None = None,
    authority: str = "local_operator",
    channel: str = "local_cli",
) -> dict[str, object]:
    return {
        "principal_id": principal,
        "issue_id": issue_id,
        "version": version,
        "revision_id": issue_identifier(IdKind.ISSUE_REVISION),
        "predecessor_version": None if version == 1 else version - 1,
        "action": action or ("created" if version == 1 else "updated"),
        "state": state,
        "title": title,
        "description": None,
        "authority_class": authority,
        "decision_channel": channel,
        "source_capability": "issues.create" if version == 1 else "issues.update",
        "recorded_at": WHEN,
    }


def _context_situation(c: Connection, principal: str) -> str:
    situation_id = issue_identifier(IdKind.SITUATION)
    c.execute(
        insert(situations).values(
            situation_id=situation_id,
            principal_id=principal,
            title="Synthetic context",
            state="open",
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return situation_id


def _project(c: Connection, principal: str) -> str:
    project_id = issue_identifier(IdKind.PROJECT)
    c.execute(
        insert(projects).values(
            project_id=project_id,
            principal_id=principal,
            name="Synthetic project",
            state="active",
            participants=[],
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return project_id


def _project_link(c: Connection, principal: str, project_id: str, issue_id: str) -> None:
    c.execute(
        insert(project_situations).values(
            project_situation_id=issue_identifier(IdKind.PROJECT_SITUATION),
            project_id=project_id,
            situation_id=issue_id,
            principal_id=principal,
            linked_at=WHEN,
        )
    )


def _membership_event(
    principal: str,
    project_id: str,
    issue_id: str,
    revision_no: int,
    action: str,
    *,
    authority: str = "local_operator",
    channel: str = "local_cli",
) -> dict[str, object]:
    ended = action == "end"
    return {
        "principal_id": principal,
        "membership_event_id": issue_identifier(IdKind.ISSUE_PROJECT_MEMBERSHIP_EVENT),
        "project_id": project_id,
        "issue_id": issue_id,
        "revision_no": revision_no,
        "predecessor_revision_no": None if revision_no == 1 else revision_no - 1,
        "action": action,
        "state": "ended" if ended else "active",
        "evidence_anchor_id": None,
        "reason": "Synthetic reason." if ended else None,
        "acceptance_basis": "user_confirmed",
        "authority_class": authority,
        "decision_channel": channel,
        "source_capability": ("issues.project_links.end" if ended else "issues.project_links.add"),
        "recorded_at": WHEN,
    }


def _meeting(c: Connection, principal: str) -> str:
    meeting_id = issue_identifier(IdKind.MEETING)
    c.execute(
        insert(meetings).values(
            meeting_id=meeting_id,
            principal_id=principal,
            title="Synthetic meeting",
            start_at=WHEN,
            timezone_name="UTC",
            status="scheduled",
            version=1,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return meeting_id


def _note(c: Connection, principal: str, meeting_id: str, body: str = BODY) -> str:
    history_id = issue_identifier(IdKind.MEETING_HISTORY)
    c.execute(
        insert(meeting_history).values(
            history_id=history_id,
            principal_id=principal,
            meeting_id=meeting_id,
            action="create",
            actor="principal",
            outcome="applied",
            before_version=0,
            after_version=1,
            idempotency_key=f"seed-{history_id}",
            request_digest="a" * 64,
            occurred_at=WHEN,
            recorded_at=WHEN,
        )
    )
    note_id = issue_identifier(IdKind.MEETING_NOTE_VERSION)
    c.execute(
        insert(meeting_note_versions).values(
            note_version_id=note_id,
            principal_id=principal,
            meeting_id=meeting_id,
            version_number=1,
            supersedes_note_version_id=None,
            content_markdown=body,
            content_sha256=_sha(body),
            meeting_history_id=history_id,
            recorded_at=WHEN,
        )
    )
    return note_id


def _capture(c: Connection, principal: str, content: str = BODY) -> tuple[str, str]:
    capture_id = issue_identifier(IdKind.CAPTURE)
    version_id = issue_identifier(IdKind.CAPTURE_VERSION)
    c.execute(insert(captures).values(capture_id=capture_id, owner_principal_id=principal))
    c.execute(
        insert(capture_versions).values(
            version_id=version_id,
            capture_id=capture_id,
            version_number=1,
            supersedes_version_id=None,
            content=content,
            content_sha256=_sha(content),
            owner_principal_id=principal,
            classification="synthetic_test",
            processing_policy="local_only",
            idempotency_key=f"seed-{version_id}",
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
            server_received_at=WHEN,
            accepted_at=WHEN,
            recorded_at=WHEN,
        )
    )
    return capture_id, version_id


def _task(c: Connection, principal: str) -> str:
    task_id = issue_identifier(IdKind.TASK)
    c.execute(
        insert(tasks).values(
            task_id=task_id,
            principal_id=principal,
            title="Synthetic task",
            origin_kind="direct_principal",
            opened_at=WHEN,
            created_at=WHEN,
            updated_at=WHEN,
        )
    )
    return task_id


def _with_identity(values: dict[str, Any]) -> dict[str, Any]:
    """`values` plus the section 5.1 identity of exactly those values."""
    identity = canonical_json({key: values[key] for key in ANCHOR_KEYS if key != "role"})
    return {**values, "anchor_identity": identity}


def _note_anchor(
    principal: str,
    meeting: str,
    note: str,
    *,
    body: str = BODY,
    passage: tuple[int, int] | None = None,
    **overrides: object,
) -> dict[str, Any]:
    start, end = passage if passage is not None else (None, None)
    values: dict[str, Any] = {
        "principal_id": principal,
        "anchor_id": issue_identifier(IdKind.LINEAGE_EVIDENCE_ANCHOR),
        "source_family": "meeting_note_version",
        "source_root_id": meeting,
        "source_version_kind": "immutable_version",
        "source_version_id": note,
        "source_version_no": 1,
        "source_sha256": _sha(body),
        "passage_start_cp": start,
        "passage_end_cp": end,
        "passage_sha256": None if passage is None else _sha(body[start:end]),
        "meeting_id": meeting,
        "note_version_id": note,
        "capture_id": None,
        "capture_version_id": None,
        "recorded_at": WHEN,
    }
    values.update(overrides)
    return _with_identity(values)


def _capture_anchor(
    principal: str,
    capture: str,
    version: str | None,
    *,
    body: str = BODY,
    passage: tuple[int, int] | None = None,
    **overrides: object,
) -> dict[str, Any]:
    start, end = passage if passage is not None else (None, None)
    legacy = version is None
    values: dict[str, Any] = {
        "principal_id": principal,
        "anchor_id": issue_identifier(IdKind.LINEAGE_EVIDENCE_ANCHOR),
        "source_family": "capture" if legacy else "capture_version",
        "source_root_id": capture,
        "source_version_kind": "legacy_unversioned" if legacy else "immutable_version",
        "source_version_id": version,
        "source_version_no": None if legacy else 1,
        "source_sha256": None if legacy else _sha(body),
        "passage_start_cp": start,
        "passage_end_cp": end,
        "passage_sha256": None if passage is None else _sha(body[start:end]),
        "meeting_id": None,
        "note_version_id": None,
        "capture_id": capture,
        "capture_version_id": version,
        "recorded_at": WHEN,
    }
    values.update(overrides)
    return _with_identity(values)


def _link_values(
    principal: str,
    *,
    kind: str,
    relation: str,
    source: tuple[str, str],
    target: tuple[str, str],
    member_role: str | None = None,
    context: str | None = None,
    **overrides: object,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "principal_id": principal,
        "link_id": issue_identifier(IdKind.RECORD_LINK),
        "kind": kind,
        "from_family": source[0],
        "from_id": source[1],
        "to_family": target[0],
        "to_id": target[1],
        "relation_type": relation,
        "member_role": member_role,
        "context_issue_id": context,
        "context_issue_kind": None if context is None else "issue_workstream",
        "authority_class": "local_operator",
        "decision_channel": "local_cli",
        "source_capability": (
            "issues.memberships.add"
            if kind == "issue_membership"
            else "records.associations.assert"
        ),
        "created_at": WHEN,
    }
    values.update(overrides)
    values["normalized_identity"] = canonical_json(
        {
            "schema_version": 1,
            "kind": values["kind"],
            "relation_type": values["relation_type"],
            "from": {
                "family": values["from_family"],
                "record_id": values["from_id"],
                "selector": "root",
            },
            "to": {"family": values["to_family"], "record_id": values["to_id"], "selector": "root"},
            "member_role": values["member_role"],
            "context_issue_id": values["context_issue_id"],
        }
    )
    return values


def _link_revision(
    principal: str,
    link_id: str,
    revision_no: int,
    action: str,
    *,
    evidence_count: int = 0,
    **overrides: object,
) -> dict[str, Any]:
    values: dict[str, Any] = {
        "principal_id": principal,
        "link_id": link_id,
        "revision_no": revision_no,
        "revision_id": issue_identifier(IdKind.RECORD_LINK_REVISION),
        "predecessor_revision_no": None if revision_no == 1 else revision_no - 1,
        "action": action,
        "lifecycle_state": "ended" if action == "end" else "active",
        "acceptance_basis": "user_confirmed",
        "authority_class": "local_operator",
        "decision_channel": "local_cli",
        "source_capability": {
            "assert": "records.associations.assert",
            "end": "records.associations.end",
            "correct_evidence": "records.associations.correct",
        }[action],
        "reason": None if action == "assert" else "Synthetic reason.",
        "evidence_count": evidence_count,
        "evidence_set_digest": EMPTY_SET_DIGEST if evidence_count == 0 else "e" * 64,
        "recorded_at": WHEN,
    }
    values.update(overrides)
    return values


def _write_link(
    c: Connection, link: dict[str, Any], anchors: tuple[tuple[dict[str, Any], str], ...] = ()
) -> str:
    """Root, revision 1 with its evidence, and the head, in one transaction."""
    c.execute(insert(record_links).values(**link))
    for anchor, _role in anchors:
        c.execute(insert(lineage_evidence_anchors).values(**anchor))
    c.execute(
        insert(record_link_revisions).values(
            **_link_revision(
                link["principal_id"],
                link["link_id"],
                1,
                "assert",
                evidence_count=len(anchors),
                source_capability=link["source_capability"],
            )
        )
    )
    for ordinal, (anchor, role) in enumerate(anchors, start=1):
        c.execute(
            insert(record_link_revision_evidence).values(
                principal_id=link["principal_id"],
                link_id=link["link_id"],
                revision_no=1,
                ordinal=ordinal,
                anchor_id=anchor["anchor_id"],
                role=role,
            )
        )
    c.execute(
        insert(record_link_heads).values(
            principal_id=link["principal_id"],
            link_id=link["link_id"],
            revision_no=1,
            lifecycle_state="active",
            normalized_identity=link["normalized_identity"],
        )
    )
    return str(link["link_id"])


def _advance_head(
    c: Connection, principal: str, link_id: str, revision_no: int, state: str
) -> None:
    c.execute(
        update(record_link_heads)
        .where(record_link_heads.c.principal_id == principal)
        .where(record_link_heads.c.link_id == link_id)
        .values(revision_no=revision_no, lifecycle_state=state)
    )


@dataclass(frozen=True)
class World:
    """One Principal's synthetic S1 graph: I, a Project link, M/N, T and two links."""

    principal: str
    issue: str
    project: str
    meeting: str
    note: str
    task: str
    membership: str
    origin: str
    anchor: str


def _world(engine: Engine, principal: str = P) -> World:
    with engine.begin() as c:
        issue = _issue(c, principal)
        project = _project(c, principal)
        _project_link(c, principal, project, issue)
        c.execute(
            insert(issue_project_membership_events).values(
                **_membership_event(principal, project, issue, 1, "assert")
            )
        )
        meeting = _meeting(c, principal)
        note = _note(c, principal, meeting)
        task = _task(c, principal)
        membership = _write_link(
            c,
            _link_values(
                principal,
                kind="issue_membership",
                relation="issue_member",
                source=("situation", issue),
                target=("meeting", meeting),
                member_role="discussion",
                context=issue,
            ),
        )
        anchor = _note_anchor(principal, meeting, note, passage=(0, 6))
        origin = _write_link(
            c,
            _link_values(
                principal,
                kind="semantic",
                relation="originated_from",
                source=("task", task),
                target=("meeting_note_version", note),
                context=issue,
            ),
            ((anchor, "origin"),),
        )
        # The Issue's own create request, completed in the same transaction.
        c.execute(
            insert(lineage_write_requests).values(
                principal_id=principal,
                capability="issues.create",
                idempotency_key=f"world-{issue}",
                request_digest="a" * 64,
                result_issue_id=issue,
                result_issue_version=1,
                created_at=WHEN,
                completed_at=WHEN,
            )
        )
    return World(
        principal, issue, project, meeting, note, task, membership, origin, anchor["anchor_id"]
    )


@pytest.fixture
def world(db_engine: Engine) -> Iterator[World]:
    yield _world(db_engine)


# ------------------------------------------------------------------ tests


@pytest.mark.parametrize("table", sorted(IMMUTABLE))
def test_immutable_lineage_tables_refuse_update_and_delete(
    db_engine: Engine, world: World, table: str
) -> None:
    del world
    column = IMMUTABLE[table]
    _refused(
        db_engine,
        lambda c: c.execute(text(f"UPDATE knowledge.{table} SET {column} = {column}")),  # noqa: S608
        RESTRICT,
        f"{table} is append-only",
    )
    _refused(
        db_engine,
        lambda c: c.execute(text(f"DELETE FROM knowledge.{table}")),  # noqa: S608
        RESTRICT,
        f"{table} is append-only",
    )


@pytest.mark.parametrize("table", ALL_TABLES)
def test_lineage_tables_refuse_truncate(db_engine: Engine, world: World, table: str) -> None:
    """Each table's own trigger refuses: the other seven are disabled for the probe.

    A TRUNCATE of a referenced table alone fails PostgreSQL's foreign-key check
    before any trigger fires, so the probe truncates all eight together (which
    satisfies that check) with only `table`'s refusal enabled, and rolls back.
    """
    del world
    # Record lineage S2's three tables reference these eight, so the probe
    # truncates them too (their own refusals disabled) to pass the same check.
    referencing = (
        "issue_revision_evidence",
        "issue_responsibility_events",
        "lineage_write_request_links",
        # Record lineage S3's five tables reference these or are referenced by
        # them (the commit marks), so they are truncated too, refusals disabled.
        "lineage_commit_sequences",
        "lineage_commit_marks",
        "issue_responsibility_corrections",
        "lineage_backfill_runs",
        "lineage_backfill_items",
    )

    def truncate(c: Connection) -> None:
        for other in (*ALL_TABLES, *referencing):
            if other != table:
                c.execute(
                    text(f"ALTER TABLE knowledge.{other} DISABLE TRIGGER {other}_refuse_truncate")
                )
        c.execute(
            text("TRUNCATE " + ", ".join(f"knowledge.{t}" for t in (*ALL_TABLES, *referencing)))
        )

    _refused(db_engine, truncate, RESTRICT, f"{table} refuses TRUNCATE")


def test_a_capture_cascade_truncate_passes_only_while_lineage_holds_no_row(
    db_engine: Engine,
) -> None:
    """The refusal guards rows, not empty relations (contract divergence, recorded).

    `lineage_evidence_anchors` references `captures` and `capture_versions`, so a
    `TRUNCATE knowledge.captures ... CASCADE` -- the fixture idiom several
    existing modules use on fresh databases -- reaches every lineage table. On
    an empty plane it removes nothing and is let through; once any lineage row
    exists it is refused.
    """
    cascade = "TRUNCATE knowledge.captures, knowledge.capture_versions CASCADE"
    with db_engine.begin() as c:
        c.execute(text(cascade))
    _world(db_engine)
    _refused(
        db_engine,
        lambda c: c.execute(text(cascade)),
        RESTRICT,
        "lineage_evidence_anchors refuses TRUNCATE",
    )


def test_a_head_admits_only_the_next_revision(db_engine: Engine, world: World) -> None:
    p, link = world.principal, world.membership

    def revision(c: Connection, number: int, action: str) -> None:
        c.execute(insert(record_link_revisions).values(**_link_revision(p, link, number, action)))

    # Skipping a revision: 1 -> 3.
    _refused(
        db_engine,
        lambda c: (
            revision(c, 2, "correct_evidence"),
            revision(c, 3, "end"),
            _advance_head(c, p, link, 3, "ended"),
        ),
        RESTRICT,
        "a link head advances to the next revision only",
    )
    with db_engine.begin() as c:
        revision(c, 2, "correct_evidence")
        _advance_head(c, p, link, 2, "active")
    # A head carries its revision's state and its root's identity.
    _refused(
        db_engine,
        lambda c: (revision(c, 3, "end"), _advance_head(c, p, link, 3, "active")),
        RESTRICT,
        "a link head carries its root identity and its revision state",
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            update(record_link_heads)
            .where(record_link_heads.c.link_id == link)
            .values(normalized_identity='{"other":1}')
        ),
        RESTRICT,
        "a link head carries its root identity and its revision state",
    )
    # A new head starts at revision 1; a head is never deleted.
    other = _link_values(
        p,
        kind="semantic",
        relation="discusses",
        source=("meeting", world.meeting),
        target=("task", world.task),
    )

    def head_at_two(c: Connection) -> None:
        c.execute(insert(record_links).values(**other))
        for number, action in ((1, "assert"), (2, "correct_evidence")):
            c.execute(
                insert(record_link_revisions).values(
                    **_link_revision(p, other["link_id"], number, action)
                )
            )
        c.execute(
            insert(record_link_heads).values(
                principal_id=p,
                link_id=other["link_id"],
                revision_no=2,
                lifecycle_state="active",
                normalized_identity=other["normalized_identity"],
            )
        )

    _refused(db_engine, head_at_two, RESTRICT, "a link head starts at revision 1")
    _refused(
        db_engine,
        lambda c: c.execute(record_link_heads.delete().where(record_link_heads.c.link_id == link)),
        RESTRICT,
        "a link head is never deleted",
    )
    # The legal step: 2 -> 3 with the ended state.
    with db_engine.begin() as c:
        revision(c, 3, "end")
        _advance_head(c, p, link, 3, "ended")


def test_a_head_cannot_lag_its_revisions_at_commit(db_engine: Engine, world: World) -> None:
    p, link = world.principal, world.membership
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(record_link_revisions).values(**_link_revision(p, link, 2, "end"))
        ),
        CHECK,
        "a link head names its latest revision",
    )


def _reserve(c: Connection, key: str, capability: str = "issues.create") -> None:
    c.execute(
        insert(lineage_write_requests).values(
            principal_id=P,
            capability=capability,
            idempotency_key=key,
            request_digest="a" * 64,
            created_at=WHEN,
        )
    )


def _complete(c: Connection, key: str, **result: object) -> None:
    c.execute(
        update(lineage_write_requests)
        .where(lineage_write_requests.c.idempotency_key == key)
        .values(completed_at=WHEN, **result)
    )


def test_a_write_request_completes_once(db_engine: Engine, world: World) -> None:
    issue_result = {"result_issue_id": world.issue, "result_issue_version": 1}
    with db_engine.begin() as c:
        _reserve(c, "s1-complete")
        _complete(c, "s1-complete", **issue_result)
    _refused(
        db_engine, lambda c: _complete(c, "s1-complete", **issue_result), RESTRICT, "completes once"
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            lineage_write_requests.delete().where(
                lineage_write_requests.c.idempotency_key == "s1-complete"
            )
        ),
        RESTRICT,
        "a lineage write request is never deleted",
    )
    # A reserved row changes only by completing, and keeps its identity.
    for change in ({"request_digest": "b" * 64}, {"created_at": WHEN.replace(hour=13)}):
        _refused(
            db_engine,
            lambda c, change=change: (
                _reserve(c, "s1-identity"),
                c.execute(
                    update(lineage_write_requests)
                    .where(lineage_write_requests.c.idempotency_key == "s1-identity")
                    .values(**change)
                ),
            ),
            RESTRICT,
            "changes only by completing",
        )
    # The completed row names exactly the result group its capability produces.
    _refused(
        db_engine,
        lambda c: (
            _reserve(c, "s1-wrong-group"),
            _complete(
                c,
                "s1-wrong-group",
                result_link_id=world.membership,
                result_link_revision_no=1,
            ),
        ),
        CHECK,
        "a_completed_issue_write_names_its_revision",
    )
    _refused(
        db_engine,
        lambda c: (
            _reserve(c, "s1-no-created", "issues.memberships.add"),
            _complete(
                c, "s1-no-created", result_link_id=world.membership, result_link_revision_no=1
            ),
        ),
        CHECK,
        "a_completed_link_write_names_its_revision",
    )
    with db_engine.begin() as c:
        _reserve(c, "s1-created", "issues.memberships.add")
        _complete(
            c,
            "s1-created",
            result_link_id=world.membership,
            result_link_revision_no=1,
            result_created=True,
        )


def test_a_write_request_is_never_committed_reserved(db_engine: Engine) -> None:
    _refused(
        db_engine,
        lambda c: _reserve(c, "s1-left-reserved"),
        CHECK,
        "a reserved lineage write request cannot commit",
    )
    with db_engine.connect() as c:
        assert c.execute(select(lineage_write_requests)).first() is None


def test_an_issue_cannot_change_without_a_matching_revision(
    db_engine: Engine, world: World
) -> None:
    p, issue = world.principal, world.issue

    def bump(c: Connection, **values: object) -> None:
        c.execute(
            update(situations)
            .where(situations.c.situation_id == issue)
            .values(version=situations.c.version + 1, updated_at=WHEN, **values)
        )

    needle = "an issue matches its revision at its version"
    _refused(db_engine, lambda c: bump(c, title="Renamed"), CHECK, needle)
    _refused(
        db_engine,
        lambda c: (
            c.execute(insert(issue_revisions).values(**_revision_values(p, issue, 2, "Other"))),
            bump(c, title="Renamed"),
        ),
        CHECK,
        needle,
    )
    _refused(
        db_engine,
        lambda c: (
            c.execute(insert(issue_revisions).values(**_revision_values(p, issue, 2, "Renamed"))),
            bump(c, title="Renamed", state="closed", closed_at=WHEN),
        ),
        CHECK,
        needle,
    )
    # An Issue row inserted without its first revision never commits.
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(situations).values(
                situation_id=issue_identifier(IdKind.SITUATION),
                principal_id=p,
                title="Orphan issue",
                state="open",
                opened_at=WHEN,
                created_at=WHEN,
                updated_at=WHEN,
                kind="issue_workstream",
            )
        ),
        CHECK,
        needle,
    )
    with db_engine.begin() as c:
        c.execute(
            insert(issue_revisions).values(
                **_revision_values(p, issue, 2, "Renamed", state="active", action="activated")
            )
        )
        bump(c, title="Renamed", state="active")


def test_a_situation_kind_is_fixed(db_engine: Engine, world: World) -> None:
    with db_engine.begin() as c:
        context = _context_situation(c, world.principal)

    def change(target: str, **values: object) -> Callable[[Connection], object]:
        return lambda c: c.execute(
            update(situations).where(situations.c.situation_id == target).values(**values)
        )

    fixed = "a situation keeps its kind, identifier and principal"
    _refused(db_engine, change(context, kind="issue_workstream"), RESTRICT, fixed)
    _refused(db_engine, change(world.issue, kind="context", version=2), RESTRICT, fixed)
    _refused(db_engine, change(context, principal_id=Q), RESTRICT, fixed)
    _refused(
        db_engine,
        change(context, situation_id=issue_identifier(IdKind.SITUATION)),
        RESTRICT,
        fixed,
    )
    _refused(
        db_engine, change(context, version=2), RESTRICT, "a context situation keeps its version"
    )
    # The legacy no-CAS shape (no version move) is refused for an Issue.
    _refused(
        db_engine,
        change(world.issue, title="Renamed"),
        RESTRICT,
        "an issue changes only by advancing its version by one",
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(situations).values(
                situation_id=issue_identifier(IdKind.SITUATION),
                principal_id=world.principal,
                title="Synthetic context",
                state="open",
                opened_at=WHEN,
                created_at=WHEN,
                updated_at=WHEN,
                version=2,
            )
        ),
        RESTRICT,
        "a situation is inserted at version 1",
    )
    # A context Situation still changes as it always has (the legacy close).
    with db_engine.begin() as c:
        change(context, state="closed", closed_at=WHEN, outcome="Done.")(c)


def test_cross_principal_foreign_keys_refuse(db_engine: Engine, world: World) -> None:
    foreign = _world(db_engine, Q)
    p = world.principal
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_revisions).values(**_revision_values(p, foreign.issue, 2, "Theirs"))
        ),
        FOREIGN_KEY,
        "an_issue_revision_names_an_issue_of_its_principal",
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(record_links).values(
                **_link_values(
                    p,
                    kind="semantic",
                    relation="originated_from",
                    source=("task", world.task),
                    target=("meeting_note_version", world.note),
                    context=foreign.issue,
                )
            )
        ),
        FOREIGN_KEY,
        "a_record_link_context_is_an_issue_of_its_principal",
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(lineage_evidence_anchors).values(
                **_note_anchor(p, foreign.meeting, foreign.note)
            )
        ),
        FOREIGN_KEY,
        "a_lineage_anchor_binds_an_exact_meeting_note",
    )
    _refused(
        db_engine,
        lambda c: _project_link(c, p, foreign.project, world.issue),
        FOREIGN_KEY,
        "a_project_situation_names_a_project_of_its_principal",
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_project_membership_events).values(
                **_membership_event(p, foreign.project, world.issue, 2, "end")
            )
        ),
        FOREIGN_KEY,
        "a_membership_event_names_a_project_link_of_its_principal",
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(record_link_revision_evidence).values(
                principal_id=p,
                link_id=world.origin,
                revision_no=1,
                ordinal=2,
                anchor_id=foreign.anchor,
                role="corroborates",
            )
        ),
        FOREIGN_KEY,
        "a_link_evidence_cites_an_anchor_of_its_principal",
    )
    _refused(
        db_engine,
        lambda c: (
            _reserve(c, "s1-foreign", "records.associations.end"),
            _complete(c, "s1-foreign", result_link_id=foreign.origin, result_link_revision_no=1),
        ),
        FOREIGN_KEY,
        "a_lineage_write_request_names_a_link_revision",
    )


def test_an_anchor_binds_the_note_digest_and_parent(db_engine: Engine, world: World) -> None:
    p = world.principal
    with db_engine.begin() as c:
        other_meeting = _meeting(c, p)
    needle = "a_lineage_anchor_binds_an_exact_meeting_note"
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(lineage_evidence_anchors).values(
                **_note_anchor(p, world.meeting, world.note, source_sha256="f" * 64)
            )
        ),
        FOREIGN_KEY,
        needle,
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(lineage_evidence_anchors).values(**_note_anchor(p, other_meeting, world.note))
        ),
        FOREIGN_KEY,
        needle,
    )
    with db_engine.begin() as c:
        c.execute(
            insert(lineage_evidence_anchors).values(**_note_anchor(p, world.meeting, world.note))
        )


def test_an_anchor_binds_the_capture_version_digest_and_parent(
    db_engine: Engine, world: World
) -> None:
    p = world.principal
    with db_engine.begin() as c:
        capture_id, version_id = _capture(c, p)
        other_capture, _other_version = _capture(c, p, "Another synthetic capture.")
        foreign_capture, _foreign_version = _capture(c, Q)
    needle = "a_lineage_anchor_binds_an_exact_capture_version"
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(lineage_evidence_anchors).values(
                **_capture_anchor(p, capture_id, version_id, source_sha256="f" * 64)
            )
        ),
        FOREIGN_KEY,
        needle,
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(lineage_evidence_anchors).values(**_capture_anchor(p, other_capture, version_id))
        ),
        FOREIGN_KEY,
        needle,
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(lineage_evidence_anchors).values(**_capture_anchor(p, foreign_capture, None))
        ),
        FOREIGN_KEY,
        "a_lineage_anchor_names_a_capture_of_its_principal",
    )
    with db_engine.begin() as c:
        c.execute(
            insert(lineage_evidence_anchors).values(**_capture_anchor(p, capture_id, version_id))
        )
        c.execute(insert(lineage_evidence_anchors).values(**_capture_anchor(p, capture_id, None)))


def test_an_anchor_binds_exactly_its_family(db_engine: Engine, world: World) -> None:
    p = world.principal
    with db_engine.begin() as c:
        capture_id, version_id = _capture(c, p)
    malformed = (
        # a note anchor that also names a Capture
        _note_anchor(p, world.meeting, world.note, capture_id=capture_id),
        # a note anchor whose binding column is null (the NULL-comparison hole)
        _note_anchor(p, world.meeting, world.note, note_version_id=None),
        # a note anchor whose binding Meeting is not its root
        _note_anchor(p, world.meeting, world.note, meeting_id=None),
        # a note anchor labelled legacy
        _note_anchor(p, world.meeting, world.note, source_version_kind="legacy_unversioned"),
        # a Capture-version anchor that also names a Meeting
        _capture_anchor(p, capture_id, version_id, meeting_id=world.meeting),
        # a Capture-version anchor without its digest
        _capture_anchor(p, capture_id, version_id, source_sha256=None),
        # a legacy root that pins a version number or a passage
        _capture_anchor(p, capture_id, None, source_version_no=1),
        _capture_anchor(
            p,
            capture_id,
            None,
            passage_start_cp=0,
            passage_end_cp=3,
            passage_sha256=_sha(BODY[0:3]),
        ),
    )
    for row in malformed:
        _refused(
            db_engine,
            lambda c, row=row: c.execute(insert(lineage_evidence_anchors).values(**row)),
            CHECK,
            "an_anchor_binds_exactly_its_family",
        )


def test_attested_tables_refuse_a_non_local_operator_row(db_engine: Engine, world: World) -> None:
    p = world.principal
    needle = "a_lineage_row_is_local_operator_attested"
    for authority, channel in (
        ("ordinary_reviewer", "local_cli"),
        ("remote_operator_attested", "remote_operator_review"),
        ("local_operator", "remote_interactive"),
        ("local_operator", "local_unattested"),
    ):
        attested = {"authority_class": authority, "decision_channel": channel}
        _refused(
            db_engine,
            lambda c, a=attested: c.execute(
                insert(record_links).values(
                    **_link_values(
                        p,
                        kind="semantic",
                        relation="discusses",
                        source=("meeting", world.meeting),
                        target=("task", world.task),
                        **a,
                    )
                )
            ),
            CHECK,
            needle,
        )
        _refused(
            db_engine,
            lambda c, a=attested: c.execute(
                insert(record_link_revisions).values(
                    **_link_revision(p, world.membership, 2, "end", **a)
                )
            ),
            CHECK,
            needle,
        )
        _refused(
            db_engine,
            lambda c, a=attested: c.execute(
                insert(issue_project_membership_events).values(
                    **_membership_event(
                        p,
                        world.project,
                        world.issue,
                        2,
                        "end",
                        authority=a["authority_class"],
                        channel=a["decision_channel"],
                    )
                )
            ),
            CHECK,
            needle,
        )
    # Issue revisions are recorded writes: an ordinary remote caller is admitted,
    # the unreachable remote attested class is not.
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_revisions).values(
                **_revision_values(
                    p, world.issue, 2, "Theirs", authority="remote_operator_attested"
                )
            )
        ),
        CHECK,
        "an_issue_revision_authority_is_known",
    )
    with db_engine.begin() as c:
        c.execute(
            insert(issue_revisions).values(
                **_revision_values(
                    p,
                    world.issue,
                    2,
                    "Renamed",
                    authority="ordinary_reviewer",
                    channel="remote_interactive",
                )
            )
        )
        c.execute(
            update(situations)
            .where(situations.c.situation_id == world.issue)
            .values(version=2, title="Renamed")
        )


def test_the_anchor_trigger_verifies_the_passage(db_engine: Engine, world: World) -> None:
    p, meeting, note = world.principal, world.meeting, world.note
    needle = "an anchor passage lies in its source and matches its digest"
    emoji = BODY.index("\U0001f600")
    combining = BODY.index("café")

    def anchor(row: dict[str, Any]) -> Callable[[Connection], object]:
        return lambda c: c.execute(insert(lineage_evidence_anchors).values(**row))

    _refused(
        db_engine,
        anchor(_note_anchor(p, meeting, note, passage=(0, 6), passage_sha256="f" * 64)),
        CHECK,
        needle,
    )
    _refused(
        db_engine,
        anchor(
            _note_anchor(
                p,
                meeting,
                note,
                passage_start_cp=0,
                passage_end_cp=len(BODY) + 1,
                passage_sha256=_sha(BODY),
            )
        ),
        CHECK,
        needle,
    )
    # The digest of the NFC form of a decomposed passage is not its digest.
    _refused(
        db_engine,
        anchor(
            _note_anchor(
                p,
                meeting,
                note,
                passage_start_cp=combining,
                passage_end_cp=combining + 5,
                passage_sha256=_sha("café"),
            )
        ),
        CHECK,
        needle,
    )
    # Byte offsets of the four-byte character are not its code-point offsets.
    byte_start = len(BODY[:emoji].encode("utf-8"))
    _refused(
        db_engine,
        anchor(
            _note_anchor(
                p,
                meeting,
                note,
                passage_start_cp=byte_start,
                passage_end_cp=byte_start + 1,
                passage_sha256=_sha("\U0001f600"),
            )
        ),
        CHECK,
        needle,
    )
    _refused(
        db_engine,
        anchor(_note_anchor(p, meeting, note, source_version_no=2)),
        CHECK,
        "an anchor carries the version number of its source",
    )
    with db_engine.begin() as c:
        capture_id, version_id = _capture(c, p)
    _refused(
        db_engine,
        anchor(_capture_anchor(p, capture_id, version_id, passage=(0, 6), passage_sha256="f" * 64)),
        CHECK,
        needle,
    )
    with db_engine.begin() as c:
        for row in (
            _note_anchor(p, meeting, note, passage=(emoji, emoji + 1)),
            _note_anchor(p, meeting, note, passage=(combining, combining + 5)),
            _capture_anchor(p, capture_id, version_id, passage=(emoji, emoji + 1)),
        ):
            c.execute(insert(lineage_evidence_anchors).values(**row))


def test_rebuilt_heads_equal_stored_heads(db_engine: Engine, world: World) -> None:
    foreign = _world(db_engine, Q)
    p = world.principal
    with db_engine.begin() as c:
        c.execute(
            insert(record_link_revisions).values(**_link_revision(p, world.membership, 2, "end"))
        )
        _advance_head(c, p, world.membership, 2, "ended")
        c.execute(
            insert(record_link_revisions).values(
                **_link_revision(p, world.origin, 2, "correct_evidence")
            )
        )
        _advance_head(c, p, world.origin, 2, "active")
    context = capture_context(p)
    with db_engine.connect() as c:
        rebuilt = rebuild_link_heads(c, context)
        stored = tuple(
            LinkHeadRow(
                principal_id=row.principal_id,
                link_id=row.link_id,
                revision_no=row.revision_no,
                lifecycle_state=LinkLifecycleState(row.lifecycle_state),
                normalized_identity=row.normalized_identity,
            )
            for row in c.execute(
                principal_scoped(
                    select(record_link_heads).order_by(record_link_heads.c.link_id),
                    record_link_heads,
                    context,
                )
            )
        )
    assert rebuilt == stored
    assert {head.link_id for head in rebuilt} == {world.membership, world.origin}
    assert {(head.link_id, head.revision_no, head.lifecycle_state) for head in rebuilt} == {
        (world.membership, 2, LinkLifecycleState.ENDED),
        (world.origin, 2, LinkLifecycleState.ACTIVE),
    }
    assert not {foreign.membership, foreign.origin} & {head.link_id for head in rebuilt}


# -------------------------------------------- the remaining guard families


@pytest.mark.parametrize("family", ["situation", "meeting", "task"])
def test_a_linked_native_row_is_not_deleted(db_engine: Engine, world: World, family: str) -> None:
    """`a_linked_record_is_not_deleted` refuses before any foreign key is checked."""
    table, column, record_id = {
        "situation": ("situations", "situation_id", world.issue),
        "meeting": ("meetings", "meeting_id", world.meeting),
        "task": ("tasks", "task_id", world.task),
    }[family]
    _refused(
        db_engine,
        lambda c: c.execute(
            text(f"DELETE FROM knowledge.{table} WHERE {column} = :id"),  # noqa: S608
            {"id": record_id},
        ),
        RESTRICT,
        f"a {family} a record link names is never deleted",
    )
    # An unlinked native row is deleted exactly as before S1.
    with db_engine.begin() as c:
        loose = _task(c, world.principal)
    with db_engine.begin() as c:
        c.execute(text("DELETE FROM knowledge.tasks WHERE task_id = :id"), {"id": loose})


def test_the_linked_record_trigger_is_on_all_five_native_tables(db_engine: Engine) -> None:
    with db_engine.connect() as c:
        guarded = set(
            c.execute(
                text(
                    "SELECT c.relname FROM pg_trigger t JOIN pg_class c ON c.oid = t.tgrelid "
                    "JOIN pg_namespace n ON n.oid = c.relnamespace "
                    "WHERE n.nspname = 'knowledge' AND t.tgname = 'a_linked_record_is_not_deleted'"
                )
            ).scalars()
        )
    assert guarded == {"situations", "meetings", "tasks", "commitments", "project_constraints"}


def test_a_membership_event_follows_an_event_it_can_follow(db_engine: Engine, world: World) -> None:
    p, project, issue = world.principal, world.project, world.issue
    needle = "a membership event follows a predecessor it can follow"

    def event(revision_no: int, action: str) -> Callable[[Connection], object]:
        return lambda c: c.execute(
            insert(issue_project_membership_events).values(
                **_membership_event(p, project, issue, revision_no, action)
            )
        )

    _refused(db_engine, event(2, "reinstate"), RESTRICT, needle)
    with db_engine.begin() as c:
        event(2, "end")(c)
    _refused(db_engine, event(3, "end"), RESTRICT, needle)
    with db_engine.begin() as c:
        event(3, "reinstate")(c)


def test_an_issue_project_link_needs_its_membership_event(db_engine: Engine, world: World) -> None:
    p = world.principal
    with db_engine.begin() as c:
        project = _project(c, p)
        context = _context_situation(c, p)
    _refused(
        db_engine,
        lambda c: _project_link(c, p, project, world.issue),
        CHECK,
        "an issue project link is written with its membership event",
    )
    # A context Situation's link, the legacy shape, needs no event.
    with db_engine.begin() as c:
        _project_link(c, p, project, context)


def test_an_issue_revision_cannot_be_ahead_of_its_issue(db_engine: Engine, world: World) -> None:
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_revisions).values(
                **_revision_values(world.principal, world.issue, 2, "Ahead")
            )
        ),
        CHECK,
        "an issue revision is not ahead of its issue",
    )


def test_an_ended_link_takes_no_further_revision(db_engine: Engine, world: World) -> None:
    p, link = world.principal, world.membership
    with db_engine.begin() as c:
        c.execute(insert(record_link_revisions).values(**_link_revision(p, link, 2, "end")))
        _advance_head(c, p, link, 2, "ended")
    _refused(
        db_engine,
        lambda c: (
            c.execute(
                insert(record_link_revisions).values(
                    **_link_revision(p, link, 3, "correct_evidence")
                )
            ),
            _advance_head(c, p, link, 3, "active"),
        ),
        RESTRICT,
        "a link revision follows an active predecessor",
    )


def test_an_evidence_set_is_frozen_at_its_count(db_engine: Engine, world: World) -> None:
    p, link = world.principal, world.origin
    needle = "a link revision holds exactly its evidence count"
    _refused(
        db_engine,
        lambda c: (
            c.execute(
                insert(record_link_revisions).values(
                    **_link_revision(p, link, 2, "correct_evidence", evidence_count=1)
                )
            ),
            _advance_head(c, p, link, 2, "active"),
        ),
        CHECK,
        needle,
    )
    # Evidence added to a committed revision in a later transaction.
    later = _note_anchor(p, world.meeting, world.note, passage=(6, 10))

    def add_evidence(c: Connection) -> None:
        c.execute(insert(lineage_evidence_anchors).values(**later))
        c.execute(
            insert(record_link_revision_evidence).values(
                principal_id=p,
                link_id=link,
                revision_no=1,
                ordinal=2,
                anchor_id=later["anchor_id"],
                role="corroborates",
            )
        )

    _refused(db_engine, add_evidence, CHECK, needle)


def test_the_link_shape_checks_refuse(db_engine: Engine, world: World) -> None:
    p = world.principal

    def link(**values: Any) -> Callable[[Connection], object]:  # noqa: ANN401 - link fields
        return lambda c: c.execute(insert(record_links).values(**_link_values(p, **values)))

    _refused(
        db_engine,
        link(
            kind="semantic",
            relation="originated_from",
            source=("meeting", world.meeting),
            target=("task", world.task),
        ),
        CHECK,
        "a_record_link_pair_is_admitted",
    )
    # A membership scoped to another Issue than its `from`, or to none (the
    # NULL-comparison hole a plain `=` would leave open).
    for context in (world.issue, None):
        _refused(
            db_engine,
            link(
                kind="issue_membership",
                relation="issue_member",
                source=("situation", issue_identifier(IdKind.SITUATION)),
                target=("meeting", world.meeting),
                member_role="discussion",
                context=context,
            ),
            CHECK,
            "a_membership_link_is_issue_scoped",
        )
    _refused(
        db_engine,
        link(
            kind="semantic",
            relation="discusses",
            source=("meeting", world.meeting),
            target=("task", world.task),
            member_role="work",
        ),
        CHECK,
        "a_semantic_link_is_not_a_membership",
    )
    _refused(
        db_engine,
        link(
            kind="semantic",
            relation="discusses",
            source=("meeting", world.task),
            target=("task", world.task),
        ),
        CHECK,
        "from_id_is_an_opaque_identifier",
    )


def test_the_predecessor_checks_refuse_a_missing_predecessor(
    db_engine: Engine, world: World
) -> None:
    """A null predecessor above revision 1 is refused, not passed as unknown."""
    p = world.principal
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_revisions).values(
                **{**_revision_values(p, world.issue, 2, "Renamed"), "predecessor_version": None}
            )
        ),
        CHECK,
        "an_issue_revision_follows_its_predecessor",
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(record_link_revisions).values(
                **_link_revision(p, world.membership, 2, "end", predecessor_revision_no=None)
            )
        ),
        CHECK,
        "a_link_revision_follows_its_predecessor",
    )
    _refused(
        db_engine,
        lambda c: c.execute(
            insert(issue_project_membership_events).values(
                **{
                    **_membership_event(p, world.project, world.issue, 2, "end"),
                    "predecessor_revision_no": None,
                }
            )
        ),
        CHECK,
        "a_membership_event_follows_the_prior_revision",
    )
