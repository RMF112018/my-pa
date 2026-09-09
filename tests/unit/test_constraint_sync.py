from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime

import pytest

from my_pa.adapters.normalization import (
    _constraint_sync,
    _preview_constraint_sync,
    _resolve_constraint_sync_conflict,
)
from my_pa.application.commands import (
    AcknowledgeConstraintSync,
    PreviewConstraintSync,
    ResolveConstraintSyncConflict,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.application.service import _sync_update_patch
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import PersistedConstraintRecord
from my_pa.domain.project_controls.sync import (
    MAX_SYNC_ROWS,
    SYNC_LOGICAL_FIELDS,
    ConstraintSyncAction,
    ConstraintSyncBaseline,
    ConstraintSyncConflictKind,
    ConstraintSyncError,
    ConstraintSyncResolution,
    ConstraintSyncState,
    NormalizedExternalConstraintRow,
    compare_three_way,
)
from my_pa.infrastructure.persistence.constraints import (
    _sync_preview_request_digest,
    _sync_preview_state,
)

NOW = datetime(2026, 9, 8, 12, tzinfo=UTC)


def _record(**changes: object) -> PersistedConstraintRecord:
    record = PersistedConstraintRecord(
        constraint_id="cst_12345678",
        principal_id="prn_12345678",
        project_id="prj_12345678",
        category_id="ccat_12345678",
        constraint_code="C.01",
        description="Canonical",
        date_identified=date(2026, 9, 1),
        lifecycle_state=ConstraintLifecycleState.IDENTIFIED,
        due_date=date(2026, 9, 30),
        record_quality=ConstraintRecordQuality.NORMAL,
        origin=ConstraintOrigin.PRODUCT,
        version=2,
        created_at=NOW,
        updated_at=NOW,
    )
    return replace(record, **changes)


def _external(
    record: PersistedConstraintRecord, **changes: object
) -> NormalizedExternalConstraintRow:
    row = NormalizedExternalConstraintRow(
        external_row_key="row-1",
        constraint_id=record.constraint_id,
        constraint_code=record.constraint_code,
        category=record.category_id,
        description=record.description,
        date_identified=record.date_identified,
        status=record.lifecycle_state,
        bic=record.bic,
        responsible=record.responsible,
        due_date=record.due_date,
        reference=record.reference,
        current_update=record.current_update,
        completion_date=record.completion_date,
    )
    return replace(row, **changes)


def _baseline(record: PersistedConstraintRecord) -> ConstraintSyncBaseline:
    row = _external(record)
    return ConstraintSyncBaseline(
        constraint_id=record.constraint_id,
        revision_id="crev_12345678",
        constraint_version=record.version,
        field_digests=row.field_digests(),
        record_digest=row.record_digest(),
        external_row_key=row.external_row_key,
        verified_provider_version="etag-1",
        verified_at=NOW,
    )


def test_the_sync_state_vocabulary_is_exactly_ten() -> None:
    assert {member.name for member in ConstraintSyncState} == {
        "NEVER_SYNCED",
        "IN_SYNC",
        "DB_EXPORT_PENDING",
        "EXTERNAL_IMPORT_PENDING",
        "CONFLICT",
        "WORKBOOK_UNAVAILABLE",
        "SCHEMA_UNSUPPORTED",
        "PARTIAL",
        "VERIFICATION_PENDING",
        "VERIFICATION_FAILED",
    }
    assert len(SYNC_LOGICAL_FIELDS) == 11


def test_normalization_is_deterministic_and_rejects_oversize() -> None:
    record = _record()
    row = _external(record, description="  Cafe\N{COMBINING ACUTE ACCENT}\r\n ")
    assert row.description == "Caf\N{LATIN SMALL LETTER E WITH ACUTE}"
    assert row.record_digest() == row.record_digest()
    with pytest.raises(ConstraintSyncError):
        _external(record, description="x" * 4097)


@pytest.mark.parametrize("field", ["bic", "responsible"])
@pytest.mark.parametrize(
    "malformed",
    [
        [{"kind": "bogus"}],
        [{"kind": "unresolved"}],
        "principal",
        {"kind": "principal"},
        [[{"kind": "principal"}]],
    ],
)
def test_preview_normalization_refuses_malformed_external_parties(
    field: str, malformed: object
) -> None:
    with pytest.raises(InvalidRequestError):
        _preview_constraint_sync(
            {
                "project_id": "prj_12345678",
                "external_identity": "book-1",
                "normalization_version": "constraint-sync-v1",
                "rows": [{"external_row_key": "row-1", field: malformed}],
                "idempotency_key": "preview_12345678",
            }
        )


@pytest.mark.parametrize("row_key", ["row key", "row\tkey", " row-key", "row-key\n"])
def test_external_row_identity_rejects_every_kind_of_whitespace(row_key: str) -> None:
    with pytest.raises(ConstraintSyncError, match="must not contain whitespace"):
        NormalizedExternalConstraintRow(external_row_key=row_key)
    with pytest.raises(InvalidRequestError):
        _preview_constraint_sync(
            {
                "project_id": "prj_12345678",
                "external_identity": "book-1",
                "normalization_version": "constraint-sync-v1",
                "rows": [{"external_row_key": row_key}],
                "idempotency_key": "preview_12345678",
            }
        )


def test_external_row_identity_accepts_its_exact_non_whitespace_boundary() -> None:
    row = NormalizedExternalConstraintRow(external_row_key="r" * 256)
    assert len(row.external_row_key) == 256
    with pytest.raises(ConstraintSyncError):
        NormalizedExternalConstraintRow(external_row_key="r" * 257)


def test_a_baseline_uses_the_same_row_identity_invariant_as_an_external_row() -> None:
    baseline = _baseline(_record())
    assert baseline.external_row_key == "row-1"
    with pytest.raises(ConstraintSyncError, match="must not contain whitespace"):
        replace(baseline, external_row_key="row reassigned")


def test_a_verified_row_key_reassignment_is_an_identity_conflict() -> None:
    record = _record()
    decision = compare_three_way(
        _baseline(record), record, _external(record, external_row_key="row-2")
    )
    assert decision.action is ConstraintSyncAction.CONFLICT
    assert decision.conflict_kind is ConstraintSyncConflictKind.IDENTITY
    assert decision.conflict_fields == ()


def test_swapping_two_verified_row_keys_produces_two_bounded_identity_conflicts() -> None:
    first = _record()
    second = replace(first, constraint_id="cst_87654321", constraint_code="C.02")
    decisions = (
        compare_three_way(_baseline(first), first, _external(first, external_row_key="row-2")),
        compare_three_way(
            replace(_baseline(second), external_row_key="row-2"),
            second,
            _external(second, external_row_key="row-1"),
        ),
    )
    assert {decision.external_row_key for decision in decisions} == {"row-1", "row-2"}
    assert all(
        decision.action is ConstraintSyncAction.CONFLICT
        and decision.conflict_kind is ConstraintSyncConflictKind.IDENTITY
        for decision in decisions
    )


def test_preview_request_digest_binds_the_canonical_constraint_identity() -> None:
    first = _external(_record(), constraint_id="cst_12345678")
    second = replace(first, constraint_id="cst_87654321")
    common = {
        "project_id": "prj_12345678",
        "external_identity": "book-1",
        "normalization_version": "constraint-sync-v1",
        "provider_version": "etag-1",
        "workbook_digest": "a" * 64,
    }
    assert _sync_preview_request_digest(**common, rows=(first,)) != _sync_preview_request_digest(
        **common, rows=(second,)
    )


def test_manual_resolution_patch_normalizes_dates_and_party_refs() -> None:
    converted = _constraint_sync(
        {
            "manual_patch": {
                "due_date": "2026-10-01",
                "completion_date": "2026-10-02",
                "bic": [{"kind": "principal"}],
                "responsible": [{"kind": "unresolved", "label": "Synthetic reviewer"}],
            }
        }
    )["manual_patch"]
    assert isinstance(converted, dict)
    assert converted["due_date"] == date(2026, 10, 1)
    assert converted["completion_date"] == date(2026, 10, 2)
    assert converted["bic"][0].kind.value == "principal"
    assert converted["responsible"][0].kind.value == "unresolved"


def test_reopen_resolution_normalizes_without_a_client_supplied_principal() -> None:
    command = _resolve_constraint_sync_conflict(
        {
            "project_id": "prj_12345678",
            "conflict_id": "csyc_12345678",
            "resolution": "reopen",
            "expected_version": 1,
            "idempotency_key": "resolve_12345678",
        }
    )
    assert command.resolution is ConstraintSyncResolution.REOPEN
    assert command.manual_patch is None
    assert not hasattr(command, "principal_id")


def _manual_resolution(**patch: object) -> ResolveConstraintSyncConflict:
    return ResolveConstraintSyncConflict(
        project_id="prj_12345678",
        conflict_id="csyc_12345678",
        resolution=ConstraintSyncResolution.MANUAL_PATCH,
        expected_version=1,
        idempotency_key="resolve_12345678",
        manual_patch=patch,
    )


def test_manual_resolution_accepts_every_exact_published_boundary() -> None:
    parties = tuple(PartyRef(kind=PartyKind.PRINCIPAL) for _ in range(32))
    assert len(_manual_resolution(bic=parties).manual_patch["bic"]) == 32  # type: ignore[index]
    assert len(_manual_resolution(responsible=parties).manual_patch["responsible"]) == 32  # type: ignore[index]
    assert _manual_resolution(description="d" * 4096).manual_patch is not None
    assert _manual_resolution(current_update="u" * 4096).manual_patch is not None
    assert _manual_resolution(reference="r" * 1024).manual_patch is not None
    assert (
        _manual_resolution(bic=(PartyRef(kind=PartyKind.UNRESOLVED, label="x" * 512),)).manual_patch
        is not None
    )
    assert (
        _manual_resolution(
            date_identified=date(2026, 9, 8),
            due_date=date(2026, 9, 9),
            project_id="prj_12345678",
            category_id="ccat_12345678",
        ).manual_patch
        is not None
    )


@pytest.mark.parametrize(
    "patch",
    [
        {"description": "x" * 4097},
        {"current_update": "x" * 4097},
        {"reference": "x" * 1025},
        {"bic": tuple(PartyRef(PartyKind.PRINCIPAL) for _ in range(33))},
        {"bic": [PartyRef(PartyKind.PRINCIPAL)]},
        {"responsible": (object(),)},
        {"bic": (PartyRef(PartyKind.UNRESOLVED, label="x" * 513),)},
        {"date_identified": "2026-09-08"},
        {"due_date": datetime(2026, 9, 8, tzinfo=UTC)},
        {"project_id": "not-a-project"},
        {"category_id": "not-a-category"},
    ],
)
def test_direct_manual_resolution_rejects_every_out_of_contract_field(
    patch: dict[str, object],
) -> None:
    with pytest.raises(InvalidRequestError):
        _manual_resolution(**patch)


@pytest.mark.parametrize(
    "parties",
    [
        [{"kind": "unknown"}],
        [{"kind": "unresolved", "label": " "}],
        [{"kind": "unresolved", "label": 42}],
        [{"kind": "entity", "entity_id": 42}],
        ["not-a-party"],
        [{"kind": "unresolved", "label": "x" * 513}],
        [{"kind": "principal"}] * 33,
    ],
)
def test_manual_resolution_wire_parties_fail_closed_before_persistence(
    parties: list[object],
) -> None:
    with pytest.raises(InvalidRequestError):
        _resolve_constraint_sync_conflict(
            {
                "project_id": "prj_12345678",
                "conflict_id": "csyc_12345678",
                "resolution": "manual_patch",
                "expected_version": 1,
                "idempotency_key": "resolve_12345678",
                "manual_patch": {"bic": parties},
            }
        )


def test_internal_legacy_resolution_cannot_be_authored_as_a_command() -> None:
    with pytest.raises(InvalidRequestError):
        _resolve_constraint_sync_conflict(
            {
                "project_id": "prj_12345678",
                "conflict_id": "csyc_12345678",
                "resolution": "legacy_migrated",
                "expected_version": 1,
                "idempotency_key": "resolve_12345678",
            }
        )


def test_malformed_external_dates_fail_as_an_invalid_request() -> None:
    with pytest.raises(ConstraintSyncError):
        NormalizedExternalConstraintRow(
            external_row_key="row-1",
            date_identified="2026-99-99",  # type: ignore[arg-type]
        )


def test_malformed_manual_resolution_date_fails_as_an_invalid_request() -> None:
    with pytest.raises(InvalidRequestError):
        _resolve_constraint_sync_conflict(
            {
                "project_id": "prj_12345678",
                "conflict_id": "csyc_12345678",
                "resolution": "manual_patch",
                "expected_version": 1,
                "idempotency_key": "resolve_12345678",
                "manual_patch": {"due_date": "2026-99-99"},
            }
        )


def test_acknowledgement_requires_the_exact_bounded_action_cardinality() -> None:
    common = {
        "project_id": "prj_12345678",
        "target_id": "csyt_12345678",
        "run_id": "csyr_12345678",
        "lease_token": "a" * 64,
        "canonical_digest": "b" * 64,
        "idempotency_key": "acknowledge_12345678",
        "provider_version": "v1",
    }
    exact = {action.value: 0 for action in ConstraintSyncAction}
    command = AcknowledgeConstraintSync(item_count=0, action_counts=exact, **common)
    assert command.item_count == sum(command.action_counts.values())
    with pytest.raises(InvalidRequestError):
        AcknowledgeConstraintSync(item_count=0, action_counts={"no_op": 0}, **common)
    with pytest.raises(InvalidRequestError):
        AcknowledgeConstraintSync(
            item_count=1,
            action_counts=exact,
            **common,
        )
    with pytest.raises(InvalidRequestError):
        _preview_constraint_sync(
            {
                "project_id": "prj_12345678",
                "external_identity": "book-1",
                "normalization_version": "constraint-sync-v1",
                "rows": [{"external_row_key": "row-1", "due_date": "2026-99-99"}],
                "idempotency_key": "preview_12345678",
            }
        )


def test_preview_is_bounded_and_rejects_duplicate_row_identity() -> None:
    row = _external(_record())
    with pytest.raises(InvalidRequestError):
        PreviewConstraintSync(
            project_id="prj_12345678",
            external_identity="book-1",
            normalization_version="constraint-sync-v1",
            rows=(row,) * (MAX_SYNC_ROWS + 1),
            idempotency_key="preview_12345678",
        )
    with pytest.raises(InvalidRequestError):
        PreviewConstraintSync(
            project_id="prj_12345678",
            external_identity="book-1",
            normalization_version="constraint-sync-v1",
            rows=(row, row),
            idempotency_key="preview_12345678",
        )


def test_preview_rejects_duplicate_canonical_identity_or_normalized_code() -> None:
    first = _external(_record())
    duplicate_id = replace(first, external_row_key="row-2", constraint_code="C.02")
    duplicate_code = replace(
        first,
        external_row_key="row-2",
        constraint_id="cst_87654321",
        constraint_code="  C.01  ",
    )
    for second in (duplicate_id, duplicate_code):
        with pytest.raises(InvalidRequestError):
            PreviewConstraintSync(
                project_id="prj_12345678",
                external_identity="book-1",
                normalization_version="constraint-sync-v1",
                rows=(first, second),
                idempotency_key="preview_12345678",
            )


def test_preview_allows_distinct_rows_without_a_canonical_identity_or_code() -> None:
    rows = (
        NormalizedExternalConstraintRow(external_row_key="row-1"),
        NormalizedExternalConstraintRow(external_row_key="row-2"),
    )
    command = PreviewConstraintSync(
        project_id="prj_12345678",
        external_identity="book-1",
        normalization_version="constraint-sync-v1",
        rows=rows,
        idempotency_key="preview_12345678",
    )
    assert command.rows == rows


def test_three_way_no_change_and_each_one_sided_change() -> None:
    original = _record()
    baseline = _baseline(original)
    assert (
        compare_three_way(baseline, original, _external(original)).action
        is ConstraintSyncAction.NO_OP
    )
    external_change = _external(original, description="External")
    assert (
        compare_three_way(baseline, original, external_change).action
        is ConstraintSyncAction.IMPORT_EXTERNAL
    )
    db_change = replace(original, description="Database", version=3)
    assert (
        compare_three_way(baseline, db_change, _external(original)).action
        is ConstraintSyncAction.EXPORT_CANONICAL
    )


def test_three_way_merges_disjoint_changes_and_conflicts_on_one_field() -> None:
    original = _record()
    baseline = _baseline(original)
    db_change = replace(original, description="Database", version=3)
    disjoint = _external(original, due_date=date(2026, 10, 1))
    assert compare_three_way(baseline, db_change, disjoint).action is ConstraintSyncAction.MERGE
    divergent = _external(original, description="External")
    conflict = compare_three_way(baseline, db_change, divergent)
    assert conflict.action is ConstraintSyncAction.CONFLICT
    assert conflict.conflict_fields == ("description",)


def test_three_way_merge_keeps_a_canonical_only_active_status_out_of_the_external_patch() -> None:
    original = _record()
    baseline = _baseline(original)
    canonical = replace(
        original,
        lifecycle_state=ConstraintLifecycleState.IN_PROGRESS,
        version=original.version + 1,
    )
    external = _external(original, description="External description")
    decision = compare_three_way(baseline, canonical, external)
    assert decision.action is ConstraintSyncAction.MERGE
    assert decision.changed_in_db == ("status",)
    assert decision.changed_external == ("description",)


def test_three_way_convergence_verifies_without_reapplying_ordinary_fields() -> None:
    original = _record()
    baseline = _baseline(original)
    converged = replace(original, description="Same final value", version=3)
    decision = compare_three_way(
        baseline,
        converged,
        _external(original, description="Same final value"),
    )
    assert decision.action is ConstraintSyncAction.NO_OP
    assert decision.changed_in_db == ()
    assert decision.changed_external == ()


def test_three_way_converged_close_verifies_without_repeating_terminal_lifecycle() -> None:
    original = _record()
    baseline = _baseline(original)
    closed = replace(
        original,
        lifecycle_state=ConstraintLifecycleState.CLOSED,
        completion_date=date(2026, 9, 8),
        version=3,
    )
    decision = compare_three_way(baseline, closed, _external(closed))
    assert decision.action is ConstraintSyncAction.NO_OP
    assert decision.changed_in_db == ()
    assert decision.changed_external == ()


def test_identity_close_delete_and_reopen_rules_fail_closed() -> None:
    record = _record()
    baseline = _baseline(record)
    identity = compare_three_way(baseline, record, _external(record, constraint_code="OTHER.01"))
    assert identity.conflict_kind is ConstraintSyncConflictKind.IDENTITY
    invalid_close = compare_three_way(
        baseline,
        record,
        _external(record, status=ConstraintLifecycleState.CLOSED, completion_date=None),
    )
    assert invalid_close.conflict_kind is ConstraintSyncConflictKind.LIFECYCLE
    terminal = replace(
        record,
        lifecycle_state=ConstraintLifecycleState.CLOSED,
        completion_date=date(2026, 9, 8),
    )
    reopen = compare_three_way(
        _baseline(terminal),
        terminal,
        _external(terminal, status=ConstraintLifecycleState.IDENTIFIED, completion_date=None),
    )
    assert reopen.conflict_kind is ConstraintSyncConflictKind.LIFECYCLE
    missing = compare_three_way(baseline, record, None)
    assert missing.action is ConstraintSyncAction.EXPORT_CANONICAL
    assert missing.conflict_kind is ConstraintSyncConflictKind.DELETED_IN_EXTERNAL


def test_preview_refuses_unapplicable_category_and_lifecycle_imports() -> None:
    record = _record()
    baseline = _baseline(record)
    category_clear = compare_three_way(baseline, record, _external(record, category=None))
    assert category_clear.conflict_kind is ConstraintSyncConflictKind.IDENTITY
    for status in (ConstraintLifecycleState.DRAFT, ConstraintLifecycleState.VOID):
        unsupported = compare_three_way(baseline, record, _external(record, status=status))
        assert unsupported.conflict_kind is ConstraintSyncConflictKind.LIFECYCLE
    closed = replace(
        record,
        lifecycle_state=ConstraintLifecycleState.CLOSED,
        completion_date=date(2026, 9, 8),
    )
    changed_completion = compare_three_way(
        _baseline(closed),
        closed,
        _external(closed, completion_date=date(2026, 9, 9)),
    )
    assert changed_completion.conflict_kind is ConstraintSyncConflictKind.LIFECYCLE


def test_draft_nullable_clears_are_advertised_and_apply_through_the_shared_patch() -> None:
    draft = replace(
        _record(),
        lifecycle_state=ConstraintLifecycleState.DRAFT,
        published_at=None,
        reference="reference",
        current_update="update",
    )
    baseline = _baseline(draft)
    external = _external(
        draft,
        description=None,
        date_identified=None,
        due_date=None,
        reference=None,
        current_update=None,
    )
    decision = compare_three_way(baseline, draft, external)
    assert decision.action is ConstraintSyncAction.IMPORT_EXTERNAL
    patch, clear_fields = _sync_update_patch(external, set(decision.changed_external))
    assert patch == {}
    assert clear_fields == frozenset(
        {"description", "date_identified", "due_date", "reference", "current_update"}
    )
    published = compare_three_way(
        _baseline(_record()), _record(), _external(_record(), due_date=None)
    )
    assert published.action is ConstraintSyncAction.CONFLICT


def test_a_merge_requires_apply_and_can_never_preview_as_in_sync() -> None:
    decision = compare_three_way(
        _baseline(_record()),
        replace(_record(), description="Database", version=3),
        _external(_record(), due_date=date(2026, 10, 1)),
    )
    assert decision.action is ConstraintSyncAction.MERGE
    assert _sync_preview_state([decision]) is ConstraintSyncState.EXTERNAL_IMPORT_PENDING
