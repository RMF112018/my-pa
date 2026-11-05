"""Reports Modernization WP03, contract C: update, lifecycle and history on PostgreSQL.

The `database` tier, one disposable head-migrated clone per test
(`migrated_engine`). What it proves, at the persistence level:

* RM-AC-007: an update writes version N+1 superseding N; a metadata-only update
  reuses the head's content object (same `content_id`, digest, no new content
  row); a content update writes one content object and a manifest naming its
  predecessor, kind and reason; the old version stays readable byte-identical;
* RM-AC-008: a stale `expected_version`, an archived or trashed report, a reused
  key with another intent and a missing association target each refuse with
  zero rows written to any `knowledge.report_*` table; a replay writes nothing
  and returns the original receipt; a no-op update writes only its receipt;
* RM-AC-010 / RM-AC-012: archive, delete (from active and from archived) and
  restore (from archived to active, and from trash to the state the delete
  recorded), archive on archived as a `no_op` receipt, stale revisions and
  illegal moves refused with zero writes;
* RM-AC-011 / RM-AC-025: no row of any append-only table is ever removed or
  changed by any operation, and the root cache equals the ledger after each;
* a foreign Principal's report answers exactly as a nonexistent one for every
  method; history pages are stable, bounded and cursor-checked;
* associations not patched carry forward verbatim; an `intelligence_report`
  target in the caller's scope verifies.

Every identifier, title and byte is synthetic.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Final

import pytest
from sqlalchemy import Engine, text

from my_pa.contracts.ports import (
    ReportAssociationTargetNotFoundError,
    ReportIdempotencyConflictError,
    ReportIntegrityError,
    ReportNotFoundError,
    ReportStaleLifecycleRevisionError,
    ReportStaleVersionError,
    ReportWithdrawnError,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.reports.content import validate_content
from my_pa.domain.reports.creator import CreatorKind, ReportCreator, derive_creator
from my_pa.domain.reports.errors import ReportLifecycleRefusal, ReportValidationError
from my_pa.domain.reports.manifest import manifest_digest
from my_pa.domain.reports.publication import RequestedAssociation
from my_pa.domain.reports.records import (
    ReportLifecycleEventRecord,
    ReportVersionSummary,
    StoredReportVersion,
)
from my_pa.domain.reports.revision import (
    ClearableField,
    LifecycleRequest,
    LifecycleResult,
    ReportPatch,
    UpdateRequest,
    UpdateResult,
)
from my_pa.domain.reports.vocabulary import (
    AssociationTargetKind,
    AssociationVerification,
    ChangeKind,
    LifecycleOperation,
    LifecycleState,
    ReceiptOutcome,
)
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from tests.database.test_reports_general_persistence import (
    CONTENTS,
    PLANE_TABLES,
    PRINCIPAL_A,
    PRINCIPAL_B,
    _counts,
    _project,
    _publish_committed,
    _request,
    _tamper_manifest_and_digest,
)

pytestmark = pytest.mark.database

ARCHIVE: Final = LifecycleOperation.ARCHIVE
DELETE: Final = LifecycleOperation.DELETE
RESTORE: Final = LifecycleOperation.RESTORE
_CLOCK: dict[str, datetime] = {"now": datetime(2026, 11, 4, 10, 0, tzinfo=UTC)}

#: Each append-only table and its primary key column.
APPEND_ONLY: Final = {
    "report_content_objects": "content_id",
    "report_versions": "version_id",
    "report_version_manifests": "version_id",
    "report_associations": "association_id",
    "report_lifecycle_events": "event_id",
    "report_receipts": "receipt_id",
}


def _tick() -> datetime:
    _CLOCK["now"] += timedelta(seconds=1)
    return _CLOCK["now"]


def _update(
    engine: Engine,
    report_id: str,
    expected: int,
    patch: ReportPatch,
    key: str,
    *,
    clear: frozenset[ClearableField] = frozenset(),
    reason: str = "Synthetic change.",
    principal_id: str = PRINCIPAL_A,
    creator: ReportCreator | None = None,
) -> UpdateResult:
    request = UpdateRequest(
        report_id=report_id,
        expected_version=expected,
        patch=patch,
        clear_fields=clear,
        change_reason=reason,
    )
    with engine.begin() as connection:
        return SqlGeneralReportRepository(connection).update(
            request,
            principal_id=principal_id,
            creator=creator or derive_creator(CreatorKind.LOCAL_PRINCIPAL, principal_id),
            idempotency_key=key,
            recorded_at=_tick(),
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
        )


def _transition(
    engine: Engine,
    operation: LifecycleOperation,
    report_id: str,
    expected: int,
    key: str,
    *,
    reason: str | None = None,
    principal_id: str = PRINCIPAL_A,
) -> LifecycleResult:
    with engine.begin() as connection:
        return SqlGeneralReportRepository(connection).transition(
            LifecycleRequest(operation, report_id, expected, reason),
            principal_id=principal_id,
            idempotency_key=key,
            recorded_at=_tick(),
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
        )


def _read(
    engine: Engine,
    report_id: str,
    *,
    principal_id: str = PRINCIPAL_A,
    version_number: int | None = None,
) -> StoredReportVersion | None:
    with engine.connect() as connection:
        return SqlGeneralReportRepository(connection).read_version(
            report_id, principal_id=principal_id, version_number=version_number
        )


def _head(engine: Engine, report_id: str, version_number: int | None = None) -> StoredReportVersion:
    stored = _read(engine, report_id, version_number=version_number)
    assert stored is not None
    return stored


def _published(engine: Engine, key: str = "pub", **overrides: object) -> str:
    request = _request(None, **overrides)
    return _publish_committed(engine, request, key).receipt.report_id


def _rows(engine: Engine) -> dict[str, dict[str, str]]:
    """Every append-only row as its jsonb text, by table and primary key."""
    with engine.connect() as connection:
        return {
            table: {
                str(row[0]): str(row[1])
                for row in connection.execute(
                    text(f"SELECT {key}, to_jsonb(t)::text FROM knowledge.{table} t")  # noqa: S608
                )
            }
            for table, key in APPEND_ONLY.items()
        }


def _assert_only_appended(
    before: dict[str, dict[str, str]], after: dict[str, dict[str, str]]
) -> None:
    for table, rows in before.items():
        for key, value in rows.items():
            assert after[table].get(key) == value, f"{table} row {key} changed or vanished"


def _assert_cache_is_the_ledger(engine: Engine) -> None:
    with engine.connect() as connection:
        drift = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.report_roots r WHERE "
                "r.head_version_number <> (SELECT max(v.version_number) FROM "
                "knowledge.report_versions v WHERE v.report_id = r.report_id) OR "
                "r.head_version_id <> (SELECT v.version_id FROM knowledge.report_versions v "
                "WHERE v.report_id = r.report_id AND v.version_number = r.head_version_number) "
                "OR r.lifecycle_revision <> coalesce((SELECT max(e.lifecycle_revision) FROM "
                "knowledge.report_lifecycle_events e WHERE e.report_id = r.report_id), 0) OR "
                "r.lifecycle_event_id IS DISTINCT FROM (SELECT e.event_id FROM "
                "knowledge.report_lifecycle_events e WHERE e.report_id = r.report_id AND "
                "e.lifecycle_revision = r.lifecycle_revision) OR r.lifecycle_state <> "
                "coalesce((SELECT e.resulting_state FROM knowledge.report_lifecycle_events e "
                "WHERE e.report_id = r.report_id AND e.lifecycle_revision = "
                "r.lifecycle_revision), 'active')"
            )
        ).scalar_one()
    assert drift == 0


# ---- update ------------------------------------------------------------------------


def test_a_metadata_only_update_reuses_the_content_object(migrated_engine: Engine) -> None:
    report_id = _published(migrated_engine)
    v1 = _head(migrated_engine, report_id)
    before = _counts(migrated_engine)
    same_bytes = validate_content(CONTENTS["markdown"])
    result = _update(
        migrated_engine,
        report_id,
        1,
        ReportPatch(title="Renamed", content=same_bytes),
        "meta",
        reason="Rename.",
    )
    after = _counts(migrated_engine)
    assert result.outcome is ReceiptOutcome.APPLIED
    assert (result.version_number, result.change_kind) == (2, ChangeKind.METADATA)
    assert result.content_id == v1.content_id
    assert result.decoded_sha256 == v1.content.decoded_sha256
    assert after["report_content_objects"] == before["report_content_objects"]
    for table in ("report_versions", "report_version_manifests", "report_receipts"):
        assert after[table] == before[table] + 1
    head = _head(migrated_engine, report_id)
    assert head.version.supersedes_version_id == v1.version.version_id
    assert head.version.change_reason == "Rename."
    assert head.manifest["supersedes_version_id"] == v1.version.version_id
    assert (head.manifest["change_kind"], head.manifest["change_reason"]) == ("metadata", "Rename.")
    assert head.root.head_version_number == 2
    # The exact old version is still readable, byte-identical but for the root.
    old = _read(migrated_engine, report_id, version_number=1)
    assert old is not None
    assert (old.version, old.content, old.manifest, old.associations) == (
        v1.version,
        v1.content,
        v1.manifest,
        v1.associations,
    )
    assert old.content.decoded == v1.content.decoded
    _assert_cache_is_the_ledger(migrated_engine)


def test_a_content_update_writes_content_and_a_manifest_naming_its_predecessor(
    migrated_engine: Engine,
) -> None:
    report_id = _published(migrated_engine)
    v1 = _head(migrated_engine, report_id)
    before = _counts(migrated_engine)
    new = validate_content(CONTENTS["json"])
    result = _update(migrated_engine, report_id, 1, ReportPatch(content=new), "content")
    after = _counts(migrated_engine)
    assert result.change_kind is ChangeKind.CONTENT
    assert result.content_id != v1.content_id
    assert result.decoded_sha256 == new.decoded_sha256
    assert after["report_content_objects"] == before["report_content_objects"] + 1
    head = _head(migrated_engine, report_id)
    assert head.content.decoded == new.decoded
    assert head.manifest["content"]["content_id"] == result.content_id
    assert head.manifest["supersedes_version_id"] == v1.version.version_id
    assert manifest_digest(head.manifest) == result.manifest_sha256
    # Fields not in the patch carried forward.
    assert (head.version.title, head.version.topics) == ("Synthetic report", ("alpha",))
    assert _head(migrated_engine, report_id, 1).content.decoded == (v1.content.decoded)


def test_clear_fields_and_wholesale_replacement(migrated_engine: Engine) -> None:
    report_id = _published(migrated_engine)
    _update(
        migrated_engine,
        report_id,
        1,
        ReportPatch(metadata={}, topics=()),
        "clear",
        clear=frozenset({ClearableField.SUMMARY, ClearableField.TYPE}),
    )
    head = _head(migrated_engine, report_id)
    assert (head.version.summary, head.version.report_type) == (None, None)
    assert (dict(head.version.metadata), head.version.topics, head.version.tags) == (
        {},
        (),
        ("t1",),
    )


def test_a_stale_expected_version_refuses_with_zero_writes(migrated_engine: Engine) -> None:
    report_id = _published(migrated_engine)
    _update(migrated_engine, report_id, 1, ReportPatch(title="Two"), "two")
    before = _counts(migrated_engine)
    with pytest.raises(ReportStaleVersionError):
        _update(migrated_engine, report_id, 1, ReportPatch(title="Three"), "stale")
    with pytest.raises(ReportStaleVersionError):
        _update(migrated_engine, report_id, 3, ReportPatch(title="Three"), "ahead")
    assert _counts(migrated_engine) == before


@pytest.mark.parametrize("withdraw", [(ARCHIVE,), (DELETE,), (ARCHIVE, DELETE)])
def test_an_update_of_a_withdrawn_report_is_refused(
    migrated_engine: Engine, withdraw: tuple[LifecycleOperation, ...]
) -> None:
    report_id = _published(migrated_engine)
    for revision, operation in enumerate(withdraw):
        _transition(migrated_engine, operation, report_id, revision, f"w{revision}")
    before = _counts(migrated_engine)
    with pytest.raises(ReportWithdrawnError):
        _update(migrated_engine, report_id, 1, ReportPatch(title="New"), "withdrawn")
    assert _counts(migrated_engine) == before


def test_replay_returns_the_original_receipt_and_another_intent_conflicts(
    migrated_engine: Engine,
) -> None:
    report_id = _published(migrated_engine)
    first = _update(migrated_engine, report_id, 1, ReportPatch(title="Two"), "k")
    before = _counts(migrated_engine)
    again = _update(migrated_engine, report_id, 1, ReportPatch(title="Two"), "k")
    assert _counts(migrated_engine) == before
    assert again.replayed is True and first.replayed is False
    assert {**vars_of(again), "replayed": False} == vars_of(first)
    with pytest.raises(ReportIdempotencyConflictError):
        _update(migrated_engine, report_id, 1, ReportPatch(title="Other"), "k")
    with pytest.raises(ReportIdempotencyConflictError):
        # The key is the Principal's: another report under it is another intent.
        _update(
            migrated_engine, _published(migrated_engine, "pub2"), 1, ReportPatch(title="Two"), "k"
        )
    after = _counts(migrated_engine)
    assert {t: after[t] - before[t] for t in PLANE_TABLES if t != "report_roots"} == {
        "report_content_objects": 1,  # the second publish only
        "report_versions": 1,
        "report_version_manifests": 1,
        "report_associations": 0,
        "report_lifecycle_events": 0,
        "report_receipts": 1,
        "report_transfer_sessions": 0,
    }


def vars_of(result: UpdateResult) -> dict[str, object]:
    return {name: getattr(result, name) for name in UpdateResult.__slots__}


def test_a_no_op_update_writes_only_its_receipt(migrated_engine: Engine) -> None:
    report_id = _published(migrated_engine)
    head = _head(migrated_engine, report_id)
    before = _counts(migrated_engine)
    result = _update(migrated_engine, report_id, 1, ReportPatch(title="Synthetic report"), "noop")
    after = _counts(migrated_engine)
    assert result.outcome is ReceiptOutcome.NO_OP
    assert result.change_kind is None
    assert (result.version_id, result.version_number) == (head.version.version_id, 1)
    assert result.manifest_sha256 == head.version.manifest_sha256
    assert {t: after[t] - before[t] for t in PLANE_TABLES} == {
        **dict.fromkeys(PLANE_TABLES, 0),
        "report_receipts": 1,
    }
    replay = _update(migrated_engine, report_id, 1, ReportPatch(title="Synthetic report"), "noop")
    assert replay.replayed and replay.outcome is ReceiptOutcome.NO_OP
    assert replay.receipt_id == result.receipt_id
    assert _counts(migrated_engine) == after


def test_associations_carry_forward_and_patched_ones_are_verified(migrated_engine: Engine) -> None:
    project = _project(migrated_engine, PRINCIPAL_A)
    foreign = _project(migrated_engine, PRINCIPAL_B)
    p = AssociationTargetKind.PROJECT
    report_id = _published(
        migrated_engine,
        associations=(
            RequestedAssociation(p, project, "about"),
            RequestedAssociation(AssociationTargetKind.EXTERNAL_SOURCE, "https://x.test", "cites"),
        ),
    )
    with migrated_engine.connect() as connection:
        v1_rows = connection.execute(
            text(
                "SELECT ordinal, target_kind, target_ref, target_version_ref, relation, "
                "verification, observed_at FROM knowledge.report_associations "
                "WHERE report_id = :r ORDER BY version_number, ordinal"
            ),
            {"r": report_id},
        ).all()
    _update(migrated_engine, report_id, 1, ReportPatch(title="Carried"), "carry")
    with migrated_engine.connect() as connection:
        v2_rows = connection.execute(
            text(
                "SELECT ordinal, target_kind, target_ref, target_version_ref, relation, "
                "verification, observed_at FROM knowledge.report_associations "
                "WHERE report_id = :r AND version_number = 2 ORDER BY ordinal"
            ),
            {"r": report_id},
        ).all()
    assert v2_rows == v1_rows  # verbatim, observation included

    before = _counts(migrated_engine)
    with pytest.raises(ReportAssociationTargetNotFoundError):
        _update(
            migrated_engine,
            report_id,
            2,
            ReportPatch(associations=(RequestedAssociation(p, foreign, "about"),)),
            "foreign-target",
        )
    assert _counts(migrated_engine) == before

    other = _project(migrated_engine, PRINCIPAL_A)
    _update(
        migrated_engine,
        report_id,
        2,
        ReportPatch(associations=(RequestedAssociation(p, other, "about"),)),
        "repoint",
    )
    head = _head(migrated_engine, report_id)
    assert [(a.target_ref, a.verification) for a in head.associations] == [
        (other, AssociationVerification.VERIFIED)
    ]
    assert head.version.change_kind is ChangeKind.METADATA


def test_an_intelligence_report_target_in_scope_verifies(migrated_engine: Engine) -> None:
    from tests.database.test_lineage_s4_integrity_guards import _committed

    principal_id, artifact_id, _digest = _committed(migrated_engine)
    assert artifact_id.startswith("rpt_")
    association = RequestedAssociation(
        AssociationTargetKind.INTELLIGENCE_REPORT, artifact_id, "summarizes"
    )
    result = _publish_committed(
        migrated_engine,
        _request(associations=(association,)),
        "intel-target",
        principal_id=principal_id,
    )
    stored = _read(migrated_engine, result.receipt.report_id, principal_id=principal_id)
    assert stored is not None
    assert [(a.target_kind, a.target_ref, a.verification) for a in stored.associations] == [
        (AssociationTargetKind.INTELLIGENCE_REPORT, artifact_id, AssociationVerification.VERIFIED)
    ]
    # The same artifact is foreign to another Principal.
    with pytest.raises(ReportAssociationTargetNotFoundError):
        _publish_committed(migrated_engine, _request(associations=(association,)), "intel-foreign")


def test_a_tampered_later_manifest_is_refused_by_the_whole_rebuild(
    migrated_engine: Engine,
) -> None:
    report_id = _published(migrated_engine)
    result = _update(migrated_engine, report_id, 1, ReportPatch(title="Two"), "two", reason="R")
    stored = _head(migrated_engine, report_id)
    for key, forged in (("change_reason", "forged"), ("supersedes_version_id", None)):
        manifest = {**stored.manifest, key: forged}
        _tamper_manifest_and_digest(
            migrated_engine, result.version_id, manifest, manifest_digest(manifest)
        )
        with pytest.raises(ReportIntegrityError):
            _read(migrated_engine, report_id)
        with migrated_engine.connect() as connection, pytest.raises(ReportIntegrityError):
            SqlGeneralReportRepository(connection).version_history(
                report_id, principal_id=PRINCIPAL_A
            )


# ---- lifecycle ---------------------------------------------------------------------


def test_archive_then_archive_is_a_no_op_receipt(migrated_engine: Engine) -> None:
    report_id = _published(migrated_engine)
    archived = _transition(migrated_engine, ARCHIVE, report_id, 0, "a1", reason="Done.")
    assert (archived.outcome, archived.prior_state, archived.resulting_state) == (
        ReceiptOutcome.APPLIED,
        LifecycleState.ACTIVE,
        LifecycleState.ARCHIVED,
    )
    assert archived.lifecycle_revision == 1 and archived.event_id is not None
    before = _counts(migrated_engine)
    again = _transition(migrated_engine, ARCHIVE, report_id, 1, "a2")
    after = _counts(migrated_engine)
    assert again.outcome is ReceiptOutcome.NO_OP
    assert (again.expected_lifecycle_revision, again.lifecycle_revision) == (1, 1)
    assert again.event_id == archived.event_id  # the current event is an archive
    assert again.prior_state is again.resulting_state is LifecycleState.ARCHIVED
    assert {t: after[t] - before[t] for t in PLANE_TABLES} == {
        **dict.fromkeys(PLANE_TABLES, 0),
        "report_receipts": 1,
    }
    replay = _transition(migrated_engine, ARCHIVE, report_id, 1, "a2")
    assert replay.replayed and replay.receipt_id == again.receipt_id
    assert replay.outcome is ReceiptOutcome.NO_OP and replay.event_id == archived.event_id


def test_delete_from_active_and_from_archived_and_restore_to_the_prior_state(
    migrated_engine: Engine,
) -> None:
    rows = _rows(migrated_engine)
    # active -> trashed -> active
    one = _published(migrated_engine, "one")
    deleted = _transition(migrated_engine, DELETE, one, 0, "d1")
    assert (deleted.prior_state, deleted.resulting_state) == (
        LifecycleState.ACTIVE,
        LifecycleState.TRASHED,
    )
    restored = _transition(migrated_engine, RESTORE, one, 1, "r1")
    assert restored.resulting_state is LifecycleState.ACTIVE
    _assert_cache_is_the_ledger(migrated_engine)

    # active -> archived -> trashed -> archived (the delete's prior state) -> active
    two = _published(migrated_engine, "two")
    _transition(migrated_engine, ARCHIVE, two, 0, "a2")
    trashed = _transition(migrated_engine, DELETE, two, 1, "d2")
    assert trashed.prior_state is LifecycleState.ARCHIVED
    back = _transition(migrated_engine, RESTORE, two, 2, "r2")
    assert (back.prior_state, back.resulting_state) == (
        LifecycleState.TRASHED,
        LifecycleState.ARCHIVED,
    )
    # Archive on an archived report whose current event is a restore: no_op, no event.
    no_op = _transition(migrated_engine, ARCHIVE, two, 3, "a2b")
    assert no_op.outcome is ReceiptOutcome.NO_OP and no_op.event_id is None
    assert no_op.lifecycle_revision == 3
    active = _transition(migrated_engine, RESTORE, two, 3, "r2b")
    assert active.resulting_state is LifecycleState.ACTIVE and active.lifecycle_revision == 4
    _assert_cache_is_the_ledger(migrated_engine)
    _assert_only_appended(rows, _rows(migrated_engine))

    with migrated_engine.connect() as connection:
        predecessors = connection.execute(
            text(
                "SELECT lifecycle_revision, predecessor_revision, predecessor_prior_state, "
                "intent_digest FROM knowledge.report_lifecycle_events WHERE report_id = :r "
                "ORDER BY lifecycle_revision"
            ),
            {"r": two},
        ).all()
    assert [(row[0], row[1], row[2]) for row in predecessors] == [
        (1, None, None),
        (2, 1, "active"),
        (3, 2, "archived"),
        (4, 3, "trashed"),
    ]
    assert predecessors[1][3] == trashed.intent_digest


def test_stale_lifecycle_revisions_and_illegal_moves_refuse_with_zero_writes(
    migrated_engine: Engine,
) -> None:
    report_id = _published(migrated_engine)
    before = _counts(migrated_engine)
    with pytest.raises(ReportLifecycleRefusal):
        _transition(migrated_engine, RESTORE, report_id, 0, "restore-active")
    with pytest.raises(ReportStaleLifecycleRevisionError):
        _transition(migrated_engine, ARCHIVE, report_id, 1, "stale")
    assert _counts(migrated_engine) == before
    _transition(migrated_engine, DELETE, report_id, 0, "delete")
    before = _counts(migrated_engine)
    with pytest.raises(ReportLifecycleRefusal):
        _transition(migrated_engine, DELETE, report_id, 1, "delete-trashed")
    with pytest.raises(ReportLifecycleRefusal):
        _transition(migrated_engine, ARCHIVE, report_id, 1, "archive-trashed")
    with pytest.raises(ReportStaleLifecycleRevisionError):
        _transition(migrated_engine, RESTORE, report_id, 0, "stale-restore")
    with pytest.raises(ReportIdempotencyConflictError):
        _transition(migrated_engine, DELETE, report_id, 0, "delete", reason="other intent")
    assert _counts(migrated_engine) == before


def test_no_row_is_ever_removed_or_changed(migrated_engine: Engine) -> None:
    project = _project(migrated_engine, PRINCIPAL_A)
    report_id = _published(
        migrated_engine,
        associations=(RequestedAssociation(AssociationTargetKind.PROJECT, project, "about"),),
    )
    steps: list[Callable[[], object]] = [
        lambda: _update(migrated_engine, report_id, 1, ReportPatch(title="2"), "u2"),
        lambda: _update(
            migrated_engine,
            report_id,
            2,
            ReportPatch(content=validate_content(CONTENTS["text"])),
            "u3",
        ),
        lambda: _update(migrated_engine, report_id, 3, ReportPatch(title="2"), "u-noop"),
        lambda: _transition(migrated_engine, ARCHIVE, report_id, 0, "a"),
        lambda: _transition(migrated_engine, ARCHIVE, report_id, 1, "a-noop"),
        lambda: _transition(migrated_engine, DELETE, report_id, 1, "d"),
        lambda: _transition(migrated_engine, RESTORE, report_id, 2, "r"),
        lambda: _transition(migrated_engine, RESTORE, report_id, 3, "r2"),
    ]
    previous = _rows(migrated_engine)
    previous_counts = _counts(migrated_engine)
    for step in steps:
        step()
        current = _rows(migrated_engine)
        _assert_only_appended(previous, current)
        counts = _counts(migrated_engine)
        assert all(counts[t] >= previous_counts[t] for t in PLANE_TABLES)
        _assert_cache_is_the_ledger(migrated_engine)
        previous, previous_counts = current, counts
    for number in (1, 2, 3):
        assert _read(migrated_engine, report_id, version_number=number) is not None
    root = _head(migrated_engine, report_id)
    assert (root.root.lifecycle_state, root.root.lifecycle_revision) == (LifecycleState.ACTIVE, 4)


def test_a_foreign_report_answers_as_a_nonexistent_one_for_every_method(
    migrated_engine: Engine,
) -> None:
    report_id = _published(migrated_engine)
    missing = issue_identifier(IdKind.REPORT)
    before = _counts(migrated_engine)
    for target, principal in (
        (report_id, PRINCIPAL_B),
        (missing, PRINCIPAL_A),
        ("bad", PRINCIPAL_A),
    ):
        with pytest.raises(ReportNotFoundError):
            _update(migrated_engine, target, 1, ReportPatch(title="x"), "f", principal_id=principal)
        for operation in LifecycleOperation:
            with pytest.raises(ReportNotFoundError):
                _transition(migrated_engine, operation, target, 0, "f", principal_id=principal)
        with migrated_engine.connect() as connection:
            repository = SqlGeneralReportRepository(connection)
            assert repository.version_history(target, principal_id=principal) is None
            assert repository.lifecycle_history(target, principal_id=principal) is None
            assert repository.read_version(target, principal_id=principal) is None
    assert _counts(migrated_engine) == before


# ---- history -----------------------------------------------------------------------


def test_version_history_pages_are_stable_and_cursor_checked(migrated_engine: Engine) -> None:
    report_id = _published(migrated_engine)
    for number in range(1, 5):
        _update(
            migrated_engine, report_id, number, ReportPatch(title=f"T{number + 1}"), f"u{number}"
        )
    other = _published(migrated_engine, "other")
    with migrated_engine.connect() as connection:
        repository = SqlGeneralReportRepository(connection)
        pages: list[list[int]] = []
        cursor: str | None = None
        while True:
            page = repository.version_history(
                report_id, principal_id=PRINCIPAL_A, after_version_id=cursor, page_size=2
            )
            assert page is not None
            assert page.root.head_version_number == 5
            pages.append([item.version_number for item in page.items])
            cursor = page.next_cursor
            if cursor is None:
                break
            assert cursor == page.items[-1].version_id
        assert pages == [[1, 2], [3, 4], [5]]
        exact = repository.version_history(report_id, principal_id=PRINCIPAL_A, page_size=5)
        assert exact is not None and exact.next_cursor is None and len(exact.items) == 5
        first = exact.items[0]
        assert isinstance(first, ReportVersionSummary)
        assert (first.change_kind, first.supersedes_version_id, first.manifest) == (
            ChangeKind.INITIAL,
            None,
            None,
        )
        assert exact.items[1].change_reason == "Synthetic change."
        with_manifests = repository.version_history(
            report_id, principal_id=PRINCIPAL_A, include_manifests=True, page_size=10
        )
        assert with_manifests is not None
        for item in with_manifests.items:
            assert item.manifest is not None
            assert manifest_digest(item.manifest) == item.manifest_sha256
        foreign_cursor = repository.version_history(other, principal_id=PRINCIPAL_A)
        assert foreign_cursor is not None
        for bad in (foreign_cursor.items[0].version_id, "grver_aaaaaaaa", "nonsense"):
            with pytest.raises(ReportValidationError, match="cursor"):
                repository.version_history(
                    report_id, principal_id=PRINCIPAL_A, after_version_id=bad
                )
        for size, manifests in ((0, False), (51, False), (11, True)):
            with pytest.raises(ReportValidationError, match="page_size"):
                repository.version_history(
                    report_id, principal_id=PRINCIPAL_A, page_size=size, include_manifests=manifests
                )


def test_lifecycle_history_pages_oldest_first(migrated_engine: Engine) -> None:
    report_id = _published(migrated_engine)
    operations = [ARCHIVE, RESTORE, DELETE, RESTORE, DELETE]
    for revision, operation in enumerate(operations):
        _transition(
            migrated_engine, operation, report_id, revision, f"l{revision}", reason=f"r{revision}"
        )
    with migrated_engine.connect() as connection:
        repository = SqlGeneralReportRepository(connection)
        empty = repository.lifecycle_history(
            _published(migrated_engine, "quiet"), principal_id=PRINCIPAL_A
        )
        assert empty is not None and empty.items == () and empty.next_cursor is None
        first = repository.lifecycle_history(report_id, principal_id=PRINCIPAL_A, page_size=3)
        assert first is not None and first.next_cursor is not None
        assert first.root.lifecycle_state is LifecycleState.TRASHED
        second = repository.lifecycle_history(
            report_id, principal_id=PRINCIPAL_A, page_size=3, after_event_id=first.next_cursor
        )
        assert second is not None and second.next_cursor is None
        items = [*first.items, *second.items]
        assert all(isinstance(item, ReportLifecycleEventRecord) for item in items)
        assert [item.lifecycle_revision for item in items] == [1, 2, 3, 4, 5]
        assert [item.operation for item in items] == operations
        assert [item.reason for item in items] == [f"r{n}" for n in range(5)]
        with pytest.raises(ReportValidationError, match="cursor"):
            repository.lifecycle_history(
                report_id, principal_id=PRINCIPAL_A, after_event_id="grlev_aaaaaaaa"
            )
