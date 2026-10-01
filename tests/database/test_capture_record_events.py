"""WP-RE-08: Capture Record Events on a real database (RE-AC-086..089, 092, 094; T-16).

Marked `database` (auto `database_clone`) and routed to `database-current-head`.
Every write goes through `ApplicationService.invoke` on the production SQL unit
of work (U1), so what is checked is the committed feed row next to the
committed capture version:

* **RE-AC-086** -- `capture.create` commits one `capture` `created` event at
  version 1, named by the capture, with the capture receipt; a replay, an
  idempotency conflict and an unknown Project commit none and advance no
  sequence.
* **RE-AC-087** -- `capture.revise` commits one `updated` event at the new
  version; a replay, a conflict, and an unknown or foreign capture commit none.
* **RE-AC-088** -- the committed `changed_fields` are exact (MR-07/MR-11),
  including a text-only revise and a one-field difference computed from the
  predecessor the head statement read.
* **RE-AC-089** -- the committed version's classification and correlation, the
  version's `accepted_at`, `principal`, no authority, no causation.
* **RE-AC-092** -- the event lives in the capture owner's partition, and a
  foreign revise commits nothing in either partition.
* **RE-AC-094 (database half)** -- the capture pipeline and the review plane's
  capture writes (RP3) commit no event.

Assertions are relative to each test's own Principal (INFO-2). Every text,
label and identity here is synthetic.
"""

from __future__ import annotations

import threading
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import select, text

from my_pa.application.commands import (
    CreateCapture,
    CreateProject,
    DecideReviewCase,
    ListReviewCases,
    ReviseCapture,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.jobs.capture_pipeline import process_capture_version
from my_pa.infrastructure.jobs.worker import issue_worker_owner, run_worker
from my_pa.infrastructure.persistence.jobs import CAPTURE_JOBS
from my_pa.infrastructure.persistence.tables import capture_review_cases, capture_versions
from tests.database.test_task_record_events import Runtime, feed, next_sequence

pytestmark = pytest.mark.database

DEVICE: Final = datetime(2026, 9, 29, 8, tzinfo=UTC)
SUBJECT: Final = datetime(2026, 9, 28, 17, tzinfo=UTC)
NOTE: Final = (
    "Synthetic capture wp08 note.\nI will send the flange tolerance summary by 2026-09-14.\n"
)
#: The same length as `NOTE`, so a revise to it moves no `character_count`.
SAME_LENGTH: Final = NOTE.replace("note", "memo")
HEAD: Final = [
    "latest_version_id",
    "latest_version_number",
    "supersedes_version_id",
    "version_count",
]


@pytest.fixture
def runtime(disposable_database: str) -> Iterator[Runtime]:
    composed = Runtime(disposable_database)
    try:
        yield composed
    finally:
        composed.close()


def _principal() -> str:
    return issue_identifier(IdKind.PRINCIPAL)


def _captures(runtime: Runtime, principal: str) -> list[dict[str, Any]]:
    return [e for e in feed(runtime.work_engine, principal) if e["record_family"] == "capture"]


def _one(events: list[dict[str, Any]]) -> dict[str, Any]:
    assert len(events) == 1, events
    return events[0]


def _version(runtime: Runtime, version_id: str) -> dict[str, Any]:
    with runtime.work_engine.connect() as connection:
        return dict(
            connection.execute(
                select(
                    capture_versions.c.classification,
                    capture_versions.c.correlation_id,
                    capture_versions.c.accepted_at,
                    capture_versions.c.owner_principal_id,
                ).where(capture_versions.c.version_id == version_id)
            )
            .mappings()
            .one()
        )


def _create(runtime: Runtime, principal: str, key: str, **extra: object) -> dict[str, Any]:
    return runtime.ok(
        CreateCapture(text=NOTE, idempotency_key=key, **extra),  # type: ignore[arg-type]
        principal_id=principal,
    )


def _revise(
    runtime: Runtime,
    principal: str,
    capture_id: str,
    key: str,
    text_value: str = "Synthetic capture wp08 revised text",
    **extra: object,
) -> dict[str, Any]:
    return runtime.ok(
        ReviseCapture(capture_id=capture_id, text=text_value, idempotency_key=key, **extra),  # type: ignore[arg-type]
        principal_id=principal,
    )


# ---- RE-AC-086 / RE-AC-089 --------------------------------------------------


def test_create_commits_one_created_event(runtime: Runtime) -> None:
    principal = _principal()
    receipt = _create(runtime, principal, "wp08-cap-create-0001")
    event = _one(_captures(runtime, principal))
    stored = _version(runtime, str(receipt["version_id"]))
    assert event["record_id"] == receipt["capture_id"]
    assert event["event_kind"] == "created"
    assert event["record_version"] == 1
    assert event["changed_fields"] == [
        "character_count",
        "classification",
        "latest_version_id",
        "latest_version_number",
        "owner_principal_id",
        "processing_policy",
        "version_count",
    ]
    assert event["source_receipt_id"] == receipt["receipt_id"]
    assert event["source_capability"] == "capture.create"
    # RE-AC-089: every row fact is the committed version's or the request's.
    assert event["classification"] == stored["classification"] == "private_local"
    assert event["correlation_id"] == stored["correlation_id"]
    assert event["occurred_at"] == stored["accepted_at"]
    assert event["actor_class"] == "principal"
    assert event["authority"] is None
    assert event["causation_event_id"] is None
    assert event["principal_id"] == stored["owner_principal_id"] == principal
    assert next_sequence(runtime.work_engine, principal) == 2


def test_a_full_create_names_each_optional_field_it_wrote(runtime: Runtime) -> None:
    principal = _principal()
    project = runtime.ok(
        CreateProject(name="Synthetic wp08 capture project", idempotency_key="wp08-cap-prj-01"),
        principal_id=principal,
    )
    _create(
        runtime,
        principal,
        "wp08-cap-create-full-0001",
        project_id=project["project_id"],
        display_label="Synthetic wp08 label",
        client_created_at=DEVICE,
        occurred_at=SUBJECT,
    )
    event = _one(_captures(runtime, principal))
    assert event["changed_fields"] == [
        "character_count",
        "classification",
        "client_created_at",
        "display_label",
        "latest_version_id",
        "latest_version_number",
        "occurred_at",
        "owner_principal_id",
        "processing_policy",
        "project_id",
        "version_count",
    ]


def test_replay_conflict_and_unknown_project_commit_nothing(runtime: Runtime) -> None:
    principal = _principal()
    _create(runtime, principal, "wp08-cap-rep-0001")
    before = (feed(runtime.work_engine, principal), next_sequence(runtime.work_engine, principal))
    replay = _create(runtime, principal, "wp08-cap-rep-0001")
    assert replay["created"] is False
    conflict = runtime.invoke(
        CreateCapture(text="Different synthetic text", idempotency_key="wp08-cap-rep-0001"),
        principal_id=principal,
    )
    assert conflict.error is not None and conflict.error.code is ErrorCode.CONFLICT
    unknown = runtime.invoke(
        CreateCapture(
            text=NOTE,
            idempotency_key="wp08-cap-unknown-project",
            project_id=issue_identifier(IdKind.PROJECT),
        ),
        principal_id=principal,
    )
    assert unknown.error is not None and unknown.error.code is ErrorCode.NOT_FOUND
    after = (feed(runtime.work_engine, principal), next_sequence(runtime.work_engine, principal))
    assert after == before


# ---- RE-AC-087 / RE-AC-088 --------------------------------------------------


def test_revise_commits_one_updated_event_at_the_new_version(runtime: Runtime) -> None:
    principal = _principal()
    capture_id = str(_create(runtime, principal, "wp08-cap-rev-seed")["capture_id"])
    receipt = _revise(runtime, principal, capture_id, "wp08-cap-rev-0001")
    events = _captures(runtime, principal)
    assert len(events) == 2, events
    created, updated = events
    assert created["event_kind"] == "created"
    assert updated["event_kind"] == "updated"
    assert updated["record_id"] == capture_id
    assert updated["record_version"] == 2 == receipt["version_number"]
    assert updated["source_receipt_id"] == receipt["receipt_id"]
    assert updated["source_capability"] == "capture.revise"
    stored = _version(runtime, str(receipt["version_id"]))
    assert updated["classification"] == stored["classification"]
    assert updated["correlation_id"] == stored["correlation_id"]
    assert updated["sequence_number"] == created["sequence_number"] + 1


def test_a_text_only_revise_commits_exactly_the_new_head(runtime: Runtime) -> None:
    """MR-11: the text differs and is never named; the new head always is."""
    principal = _principal()
    capture_id = str(
        _create(
            runtime, principal, "wp08-cap-txt-seed", client_created_at=DEVICE, occurred_at=SUBJECT
        )["capture_id"]
    )
    _revise(
        runtime,
        principal,
        capture_id,
        "wp08-cap-txt-0001",
        text_value=SAME_LENGTH,
        client_created_at=DEVICE,
        occurred_at=SUBJECT,
    )
    assert _captures(runtime, principal)[-1]["changed_fields"] == HEAD


def test_a_revise_whose_text_changes_length_commits_the_character_count(
    runtime: Runtime,
) -> None:
    """MR-11: the count `capture.read` exposes moves, so it is named; the text never is."""
    principal = _principal()
    capture_id = str(
        _create(
            runtime, principal, "wp08-cap-len-seed", client_created_at=DEVICE, occurred_at=SUBJECT
        )["capture_id"]
    )
    _revise(
        runtime,
        principal,
        capture_id,
        "wp08-cap-len-0001",
        text_value=NOTE + "One more synthetic line.\n",
        client_created_at=DEVICE,
        occurred_at=SUBJECT,
    )
    assert _captures(runtime, principal)[-1]["changed_fields"] == sorted([*HEAD, "character_count"])


def test_updated_fields_name_exactly_the_differing_version_fields(runtime: Runtime) -> None:
    """MR-07: two candidate times held, only `occurred_at` differs, only it is named."""
    principal = _principal()
    capture_id = str(
        _create(
            runtime, principal, "wp08-cap-diff-seed", client_created_at=DEVICE, occurred_at=SUBJECT
        )["capture_id"]
    )
    _revise(
        runtime,
        principal,
        capture_id,
        "wp08-cap-diff-0001",
        text_value=SAME_LENGTH,
        client_created_at=DEVICE,
        occurred_at=SUBJECT + timedelta(hours=2),
    )
    assert _captures(runtime, principal)[-1]["changed_fields"] == [
        "latest_version_id",
        "latest_version_number",
        "occurred_at",
        "supersedes_version_id",
        "version_count",
    ]


def test_a_foreign_or_unknown_revise_commits_nothing(runtime: Runtime) -> None:
    principal = _principal()
    capture_id = str(_create(runtime, principal, "wp08-cap-foreign-seed")["capture_id"])
    _revise(runtime, principal, capture_id, "wp08-cap-foreign-rev")
    before = (feed(runtime.work_engine, principal), next_sequence(runtime.work_engine, principal))
    replay = _revise(runtime, principal, capture_id, "wp08-cap-foreign-rev")
    assert replay["created"] is False
    conflict = runtime.invoke(
        ReviseCapture(
            capture_id=capture_id, text="Other text", idempotency_key="wp08-cap-foreign-rev"
        ),
        principal_id=principal,
    )
    assert conflict.error is not None and conflict.error.code is ErrorCode.CONFLICT
    unknown = runtime.invoke(
        ReviseCapture(
            capture_id=issue_identifier(IdKind.CAPTURE),
            text="Synthetic text",
            idempotency_key="wp08-cap-unknown-rev",
        ),
        principal_id=principal,
    )
    assert unknown.error is not None and unknown.error.code is ErrorCode.NOT_FOUND
    after = (feed(runtime.work_engine, principal), next_sequence(runtime.work_engine, principal))
    assert after == before


# ---- RE-AC-092 --------------------------------------------------------------


def test_capture_events_stay_in_the_owners_partition(runtime: Runtime) -> None:
    owner, stranger = _principal(), _principal()
    capture_id = str(_create(runtime, owner, "wp08-cap-part-0001")["capture_id"])
    event = _one(_captures(runtime, owner))
    assert event["principal_id"] == owner
    before = (feed(runtime.work_engine, owner), next_sequence(runtime.work_engine, owner))

    foreign = runtime.invoke(
        ReviseCapture(capture_id=capture_id, text="Stranger text", idempotency_key="wp08-cap-str"),
        principal_id=stranger,
    )
    assert foreign.error is not None and foreign.error.code is ErrorCode.NOT_FOUND
    assert feed(runtime.work_engine, stranger) == []
    assert next_sequence(runtime.work_engine, stranger) is None
    after = (feed(runtime.work_engine, owner), next_sequence(runtime.work_engine, owner))
    assert after == before
    with runtime.work_engine.connect() as connection:
        partitions = set(
            connection.execute(
                text(
                    "SELECT DISTINCT principal_id FROM knowledge.record_events "
                    "WHERE record_family = 'capture' AND record_id = :capture_id"
                ),
                {"capture_id": capture_id},
            ).scalars()
        )
    assert partitions == {owner}


# ---- RE-AC-094 (database half) ----------------------------------------------


def test_pipeline_and_review_writes_commit_no_event(runtime: Runtime) -> None:
    principal = _principal()
    created = _create(runtime, principal, "wp08-cap-pipe-0001")
    before = (feed(runtime.work_engine, principal), next_sequence(runtime.work_engine, principal))

    run_worker(
        runtime.work_engine,
        principal_id=principal,
        owner=issue_worker_owner(),
        handler=process_capture_version,
        stop=threading.Event(),
        plane=CAPTURE_JOBS,
        max_iterations=1,
        poll_seconds=0.01,
    )
    with runtime.work_engine.connect() as connection:
        cases = connection.execute(
            select(capture_review_cases.c.review_case_id).where(
                capture_review_cases.c.version_id == created["version_id"]
            )
        ).all()
    assert cases, "the pipeline opened no review case, so the review half cannot be exercised"
    assert (
        feed(runtime.work_engine, principal),
        next_sequence(runtime.work_engine, principal),
    ) == (before)

    listed = runtime.ok(ListReviewCases(), principal_id=principal)
    listed_cases = listed.get("cases") or listed.get("review_cases") or []
    case = next(c for c in listed_cases if c.get("version_id") == created["version_id"])
    runtime.ok(
        DecideReviewCase(
            review_case_id=case["review_case_id"],
            expected_review_version=int(case.get("review_version", 0)),
            disposition=Disposition.ACCEPT,
        ),
        principal_id=principal,
    )
    assert (
        feed(runtime.work_engine, principal),
        next_sequence(runtime.work_engine, principal),
    ) == (before)
