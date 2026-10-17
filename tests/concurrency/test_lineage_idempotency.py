"""Record lineage S1 idempotency, CAS and concurrency (AT-010, S1 contract 5.4, 6.2, 6.3).

Against PostgreSQL through `ApplicationService.invoke`, on separate
connections where the case is about overlap. Each overlapping case holds the
contended row from a third connection, starts both writers in threads, waits
until PostgreSQL reports both blocked on a lock, and only then releases the
holder, so the two writers really race. Every lock wait is bounded by the
default statement path, and the test waits on the threads with a timeout, so a
build that takes no lock reports rather than hangs.

This module holds the Issue and Project-link rows of the crosswalk (worker I2)
and the association and membership rows (worker I3):
`test_distinct_keys_same_identity_return_the_existing_association`,
`test_a_duplicate_assert_never_changes_authority`,
`test_concurrent_identical_asserts_create_one_active_head`,
`test_a_replay_reports_the_recorded_created_flag`, and the association forms
of the replay, same-key, stale-revision and moved-on rows.

Every identity here is synthetic.
"""

from __future__ import annotations

import time
import unicodedata
from collections.abc import Callable, Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Any, Final

import pytest
from sqlalchemy import Engine, func, select, text
from tests.database.lineage_issue_harness import LineageRuntime, lineage_row_counts
from tests.database.lineage_record_harness import (
    NOTE_BODY,
    commitment,
    meeting,
    membership,
    note_anchor,
    originated_from,
)

from my_pa.application.commands import (
    AddIssueProjectLink,
    CorrectRecordAssociation,
    CreateIssue,
    EndIssueProjectLink,
    EndRecordAssociation,
    UpdateIssue,
)
from my_pa.contracts.v1.envelope import ResponseEnvelope
from my_pa.domain.identity.operator_surface import OperatorSurface
from my_pa.infrastructure.persistence.tables import (
    issue_project_membership_events,
    issue_revisions,
    lineage_write_requests,
    record_link_heads,
    record_link_revisions,
    record_links,
    situations,
)

pytestmark = pytest.mark.database

#: How long the test waits to observe both writers blocked.
BLOCK_DEADLINE_SECONDS: Final = 15.0
#: How long the test waits for a writer once the holder released.
JOIN_TIMEOUT_SECONDS: Final = 60.0

_GATEWAY: Final = OperatorSurface.HTTP_GATEWAY


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[LineageRuntime]:
    composed = LineageRuntime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _count(engine: Engine, table: Any, *criteria: Any) -> int:  # noqa: ANN401
    with engine.connect() as connection:
        return int(
            connection.execute(
                select(func.count()).select_from(table).where(*criteria)
            ).scalar_one()
        )


def _error(envelope: ResponseEnvelope) -> dict[str, Any] | None:
    error = envelope.to_canonical_dict().get("error")
    assert error is None or isinstance(error, dict)
    return error


def _wait_until_blocked(engine: Engine, futures: list[Future[Any]], waiters: int) -> None:
    deadline = time.monotonic() + BLOCK_DEADLINE_SECONDS
    with engine.connect() as observer:
        while time.monotonic() < deadline:
            assert not any(future.done() for future in futures), "a writer did not wait"
            waiting = observer.execute(
                text(
                    "SELECT count(*) FROM pg_stat_activity "
                    "WHERE datname = current_database() AND wait_event_type = 'Lock' "
                    "AND pid <> pg_backend_pid()"
                )
            ).scalar_one()
            observer.rollback()
            if waiting >= waiters:
                return
            time.sleep(0.05)
    pytest.fail("the writers never blocked on the held row")


def _race(
    runtime: LineageRuntime, hold: str, parameters: dict[str, Any], writers: list[Callable[[], Any]]
) -> list[ResponseEnvelope]:
    """Hold one row `FOR UPDATE`, start every writer, release once all wait."""
    with runtime.engine.connect() as holder, ThreadPoolExecutor(max_workers=len(writers)) as pool:
        transaction = holder.begin()
        holder.execute(text(hold), parameters)
        futures = [pool.submit(writer) for writer in writers]
        _wait_until_blocked(runtime.engine, futures, len(writers))
        transaction.rollback()
        return [future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures]


_HOLD_ISSUE: Final = (
    "SELECT situation_id FROM knowledge.situations WHERE situation_id = :issue_id FOR UPDATE"
)


def _create(key: str, title: str = "Synthetic idempotent issue") -> CreateIssue:
    return CreateIssue(title=title, idempotency_key=key)


def _link(issue_id: str, project_id: str, key: str, expected: int = 0) -> AddIssueProjectLink:
    return AddIssueProjectLink(
        issue_id=issue_id,
        project_id=project_id,
        expected_membership_revision=expected,
        idempotency_key=key,
    )


def test_identical_replay_returns_one_root_revision_and_request(runtime: LineageRuntime) -> None:
    """Issue form: one Issue, one revision, one request row; byte-stable apart from `replayed`."""
    first = runtime.ok(_create("lineage-replay-create"))
    second = runtime.ok(_create("lineage-replay-create"))
    assert first["replayed"] is False and second["replayed"] is True
    assert {**second, "replayed": False} == first
    issue_id = first["issue"]["issue_id"]
    assert _count(runtime.engine, situations, situations.c.situation_id == issue_id) == 1
    assert _count(runtime.engine, issue_revisions, issue_revisions.c.issue_id == issue_id) == 1
    assert _count(runtime.engine, lineage_write_requests) == 1
    project = runtime.project("replay")
    linked = runtime.ok(_link(issue_id, project, "lineage-replay-link"), surface=_GATEWAY)
    again = runtime.ok(_link(issue_id, project, "lineage-replay-link"), surface=_GATEWAY)
    assert again["replayed"] is True and {**again, "replayed": False} == linked
    assert _count(runtime.engine, issue_project_membership_events) == 1


def test_same_key_different_payload_is_conflict(runtime: LineageRuntime) -> None:
    runtime.ok(_create("lineage-same-key"))
    before = lineage_row_counts(runtime.engine)
    error = runtime.refused(_create("lineage-same-key", title="Another synthetic issue"))
    assert error["code"] == "conflict"
    assert error["safe_details"] == ["idempotency_conflict"]
    assert lineage_row_counts(runtime.engine) == before


def test_nfd_and_nfc_titles_under_one_key_conflict(runtime: LineageRuntime) -> None:
    """Section 5.4: the request digest is not NFC-normalized, so these are two requests."""
    nfc = unicodedata.normalize("NFC", "Café review")
    nfd = unicodedata.normalize("NFD", nfc)
    assert nfc != nfd
    runtime.ok(_create("lineage-nfc-nfd", title=nfc))
    error = runtime.refused(_create("lineage-nfc-nfd", title=nfd))
    assert error["code"] == "conflict"
    assert error["safe_details"] == ["idempotency_conflict"]


def test_a_stale_expected_revision_is_conflict(runtime: LineageRuntime) -> None:
    issue_id = runtime.issue("stale")
    project = runtime.project("stale")
    runtime.ok(
        UpdateIssue(
            issue_id=issue_id,
            expected_version=1,
            idempotency_key="lineage-stale-update-1",
            title="Synthetic issue, retitled",
        )
    )
    before = lineage_row_counts(runtime.engine)
    stale_update = runtime.refused(
        UpdateIssue(
            issue_id=issue_id,
            expected_version=1,
            idempotency_key="lineage-stale-update-2",
            description="A stale description",
        )
    )
    assert stale_update["code"] == "conflict"
    assert stale_update["safe_details"] == ["stale_version"]
    stale_add = runtime.refused(
        _link(issue_id, project, "lineage-stale-add", expected=1), surface=_GATEWAY
    )
    assert stale_add["code"] == "conflict"
    stale_end = runtime.refused(
        EndIssueProjectLink(
            issue_id=issue_id,
            project_id=project,
            expected_membership_revision=1,
            idempotency_key="lineage-stale-end",
            reason="there is no link to end",
        ),
        surface=_GATEWAY,
    )
    assert stale_end["code"] == "conflict"
    runtime.ok(_link(issue_id, project, "lineage-stale-add-0"), surface=_GATEWAY)
    active = runtime.refused(
        _link(issue_id, project, "lineage-stale-add-again", expected=1), surface=_GATEWAY
    )
    assert active["code"] == "conflict", "an active link cannot be asserted again"
    # The refused requests left no request row behind.
    after = lineage_row_counts(runtime.engine)
    assert after["lineage_write_requests"] == before["lineage_write_requests"] + 1
    assert after["issue_revisions"] == before["issue_revisions"]


def test_a_replay_rebuilds_the_original_response_after_the_link_moved_on(
    runtime: LineageRuntime,
) -> None:
    """Section 6.3: a replay answers from the immutable event, never from current state."""
    issue_id = runtime.issue("moved-on")
    project = runtime.project("moved-on")
    original = runtime.ok(_link(issue_id, project, "lineage-moved-on-add"), surface=_GATEWAY)
    runtime.ok(
        EndIssueProjectLink(
            issue_id=issue_id,
            project_id=project,
            expected_membership_revision=1,
            idempotency_key="lineage-moved-on-end",
            reason="the synthetic issue left the project",
        ),
        surface=_GATEWAY,
    )
    replayed = runtime.ok(_link(issue_id, project, "lineage-moved-on-add"), surface=_GATEWAY)
    assert replayed["project_link"]["state"] == "active"
    assert {**replayed, "replayed": False} == original
    created = runtime.ok(_create("lineage-moved-on-issue"))
    runtime.ok(
        UpdateIssue(
            issue_id=created["issue"]["issue_id"],
            expected_version=1,
            idempotency_key="lineage-moved-on-update",
            state="active",
        )
    )
    again = runtime.ok(_create("lineage-moved-on-issue"))
    assert again["issue"]["version"] == 1 and again["issue"]["state"] == "open"
    assert {**again, "replayed": False} == created


def test_concurrent_issue_updates_admit_one(runtime: LineageRuntime) -> None:
    issue_id = runtime.issue("concurrent-update")

    def writer(key: str, title: str) -> Callable[[], ResponseEnvelope]:
        return lambda: runtime.invoke(
            UpdateIssue(issue_id=issue_id, expected_version=1, idempotency_key=key, title=title)
        )

    answers = _race(
        runtime,
        _HOLD_ISSUE,
        {"issue_id": issue_id},
        [writer("lineage-race-update-a", "Title A"), writer("lineage-race-update-b", "Title B")],
    )
    errors = [_error(answer) for answer in answers]
    assert sorted(error is None for error in errors) == [False, True]
    loser = next(error for error in errors if error is not None)
    assert loser["code"] == "conflict" and loser["safe_details"] == ["stale_version"]
    assert _count(runtime.engine, issue_revisions, issue_revisions.c.issue_id == issue_id) == 2
    assert _count(runtime.engine, lineage_write_requests) == 2


def test_concurrent_project_link_adds_admit_one(runtime: LineageRuntime) -> None:
    issue_id = runtime.issue("concurrent-link")
    project = runtime.project("concurrent-link")

    def writer(key: str) -> Callable[[], ResponseEnvelope]:
        return lambda: runtime.invoke(_link(issue_id, project, key), surface=_GATEWAY)

    answers = _race(
        runtime,
        _HOLD_ISSUE,
        {"issue_id": issue_id},
        [writer("lineage-race-link-a"), writer("lineage-race-link-b")],
    )
    errors = [_error(answer) for answer in answers]
    assert sorted(error is None for error in errors) == [False, True]
    loser = next(error for error in errors if error is not None)
    assert loser["code"] == "conflict"
    assert _count(runtime.engine, issue_project_membership_events) == 1


# ---- associations and memberships (worker I3) --------------------------------


def _origin_fixture(runtime: LineageRuntime, key: str) -> dict[str, Any]:
    m1, n1 = meeting(runtime, key)
    c1 = commitment(runtime, key)
    return {"m1": m1, "n1": n1, "c1": c1, "anchor": note_anchor(m1, n1, NOTE_BODY)}


def _assert(ids: dict[str, Any], key: str, anchor: dict[str, object] | None = None) -> Any:  # noqa: ANN401
    return originated_from(
        "commitment",
        ids["c1"],
        "meeting_note_version",
        ids["n1"],
        key,
        (anchor or ids["anchor"],),
    )


def test_association_replay_and_same_key_conflict(runtime: LineageRuntime) -> None:
    """The association form of the replay and same-key rows above."""
    ids = _origin_fixture(runtime, "assoc-replay")
    first = runtime.ok(_assert(ids, "assoc-replay"), surface=_GATEWAY)
    again = runtime.ok(_assert(ids, "assoc-replay"), surface=_GATEWAY)
    assert first["replayed"] is False and again["replayed"] is True
    assert {**again, "replayed": False} == first
    assert _count(runtime.engine, record_links) == 1
    assert _count(runtime.engine, record_link_revisions) == 1
    before = lineage_row_counts(runtime.engine)
    other = note_anchor(ids["m1"], ids["n1"], NOTE_BODY, passage="Next: pour")
    conflict = runtime.refused(_assert(ids, "assoc-replay", other), surface=_GATEWAY)
    assert conflict["code"] == "conflict"
    assert conflict["safe_details"] == ["idempotency_conflict"]
    assert lineage_row_counts(runtime.engine) == before


def test_distinct_keys_same_identity_return_the_existing_association(
    runtime: LineageRuntime,
) -> None:
    ids = _origin_fixture(runtime, "assoc-same")
    first = runtime.ok(_assert(ids, "assoc-same-a"), surface=_GATEWAY)
    narrower = note_anchor(ids["m1"], ids["n1"], NOTE_BODY, passage="façade")
    second = runtime.ok(_assert(ids, "assoc-same-b", narrower), surface=_GATEWAY)
    assert first["created"] is True and second["created"] is False
    assert second["association"] == first["association"]
    assert _count(runtime.engine, record_links) == 1
    assert _count(runtime.engine, record_link_heads) == 1
    # A membership of the same member and role behaves the same way.
    issue = runtime.issue("assoc-same")
    added = runtime.ok(
        membership(issue, "meeting", ids["m1"], "same-a", role="discussion"), surface=_GATEWAY
    )
    repeat = runtime.ok(
        membership(issue, "meeting", ids["m1"], "same-b", role="discussion"), surface=_GATEWAY
    )
    assert repeat["created"] is False and repeat["membership"] == added["membership"]
    other_role = runtime.ok(
        membership(issue, "meeting", ids["m1"], "same-c", role="reference"), surface=_GATEWAY
    )
    assert other_role["created"] is True


def test_a_duplicate_assert_never_changes_authority(runtime: LineageRuntime) -> None:
    ids = _origin_fixture(runtime, "assoc-authority")
    first = runtime.ok(_assert(ids, "assoc-authority-a"), surface=_GATEWAY)
    second = runtime.ok(_assert(ids, "assoc-authority-b"), surface=OperatorSurface.CLI)
    assert second["created"] is False
    assert second["association"]["authority_class"] == first["association"]["authority_class"]
    with runtime.engine.connect() as connection:
        channels = connection.execute(
            select(record_links.c.decision_channel, record_link_revisions.c.decision_channel).join(
                record_link_revisions,
                record_link_revisions.c.link_id == record_links.c.link_id,
            )
        ).all()
    assert channels == [("local_web", "local_web")]


_HOLD_COMMITMENT: Final = (
    "SELECT commitment_id FROM knowledge.commitments WHERE commitment_id = :commitment_id "
    "FOR UPDATE"
)


def test_concurrent_identical_asserts_create_one_active_head(runtime: LineageRuntime) -> None:
    ids = _origin_fixture(runtime, "assoc-race")

    def writer(key: str) -> Callable[[], ResponseEnvelope]:
        return lambda: runtime.invoke(_assert(ids, key), surface=_GATEWAY)

    answers = _race(
        runtime,
        _HOLD_COMMITMENT,
        {"commitment_id": ids["c1"]},
        [writer("assoc-race-a"), writer("assoc-race-b")],
    )
    results = [answer.to_canonical_dict()["result"] for answer in answers]
    assert all(answer.error is None for answer in answers)
    assert sorted(result["created"] for result in results) == [False, True]
    assert results[0]["association"]["link_id"] == results[1]["association"]["link_id"]
    assert _count(runtime.engine, record_links) == 1
    assert (
        _count(runtime.engine, record_link_heads, record_link_heads.c.lifecycle_state == "active")
        == 1
    )
    assert _count(runtime.engine, lineage_write_requests) == 2


def test_a_replay_reports_the_recorded_created_flag(runtime: LineageRuntime) -> None:
    ids = _origin_fixture(runtime, "assoc-flag")
    runtime.ok(_assert(ids, "assoc-flag-a"), surface=_GATEWAY)
    duplicate = runtime.ok(_assert(ids, "assoc-flag-b"), surface=_GATEWAY)
    assert duplicate["created"] is False
    replayed_duplicate = runtime.ok(_assert(ids, "assoc-flag-b"), surface=_GATEWAY)
    assert replayed_duplicate["replayed"] is True and replayed_duplicate["created"] is False
    replayed_original = runtime.ok(_assert(ids, "assoc-flag-a"), surface=_GATEWAY)
    assert replayed_original["replayed"] is True and replayed_original["created"] is True


def test_association_stale_revision_and_replay_after_end(runtime: LineageRuntime) -> None:
    """The association form of the stale-revision and moved-on replay rows above."""
    ids = _origin_fixture(runtime, "assoc-stale")
    original = runtime.ok(_assert(ids, "assoc-stale"), surface=_GATEWAY)
    link_id = original["association"]["link_id"]
    ended = runtime.ok(
        EndRecordAssociation(
            link_id=link_id,
            expected_revision=1,
            idempotency_key="lineage-assoc-stale-end",
            reason="the synthetic association was wrong",
        ),
        surface=_GATEWAY,
    )
    assert ended["association"]["lifecycle_state"] == "ended"
    assert "created" not in ended
    before = lineage_row_counts(runtime.engine)
    for command in (
        EndRecordAssociation(
            link_id=link_id,
            expected_revision=1,
            idempotency_key="lineage-assoc-stale-end-again",
            reason="stale",
        ),
        CorrectRecordAssociation(
            link_id=link_id,
            expected_revision=2,
            idempotency_key="lineage-assoc-stale-correct",
            reason="an ended link is terminal",
            evidence_anchors=(note_anchor(ids["m1"], ids["n1"], NOTE_BODY, passage="façade"),),
        ),
    ):
        error = runtime.refused(command, surface=_GATEWAY)
        assert error["code"] == "conflict" and error["safe_details"] == ["stale_version"]
    assert lineage_row_counts(runtime.engine) == before
    replayed = runtime.ok(_assert(ids, "assoc-stale"), surface=_GATEWAY)
    assert replayed["association"]["lifecycle_state"] == "active"
    assert {**replayed, "replayed": False} == original
    # Re-asserting the same meaning after the end is a new root.
    fresh = runtime.ok(_assert(ids, "assoc-stale-new"), surface=_GATEWAY)
    assert fresh["created"] is True and fresh["association"]["link_id"] != link_id
