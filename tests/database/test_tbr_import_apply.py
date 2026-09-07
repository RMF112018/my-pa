"""PC-CM-IMP-WP13 T13-06/09/10/11/12/13: the disposable apply, against a real server.

The `database` tier, on a disposable head-migrated clone. What the FAST tier
proves about classification and codes against a pure planner, this proves
against the stored CHECKs, the unique indexes, the deferred revision/receipt
cycle, the row-locked allocator and the read plane that later has to describe
what was written.

Four claims are the ones that need a server and could not be established
anywhere else. *The write aggregate stays strict*: the ordinary mutation service
still refuses to produce a legacy record, and the importer's ability to make one
does not widen it. *The allocator cannot collide with a preserved code*, proved
by two overlapping Publishes after an import, not by a sequential pair. *No
baseline row exists*, so every imported record reads `NEVER_SYNCED` — which is
the truthful state, and is what "initial baseline requires post-import external
verification" means when an unverified baseline is not representable. And *a
rerun is a replay*: same key and same digest write nothing, and a changed digest
under the same key is an explicit conflict rather than an overwrite.

Every identifier, prefix, label, code and date here is synthetic.
"""

from __future__ import annotations

import inspect
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Final

import pytest
from sqlalchemy import Engine, func, insert, select
from sqlalchemy.sql import ColumnElement, FromClause

from my_pa.application import constraint_management
from my_pa.application.constraint_legacy_import import (
    TOOL_CLIENT_CONTEXT,
    ConstraintLegacyImportService,
    LegacyImportError,
    LegacyImportIdempotencyConflictError,
    row_idempotency_key,
)
from my_pa.application.constraint_management import (
    ConstraintManagementService,
    ConstraintMutationDisposition,
)
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
)
from my_pa.domain.project_controls.history import (
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import (
    MAX_LIST_LIMIT,
    ConstraintFieldKey,
    ConstraintListQuery,
    ConstraintListScope,
    ConstraintListSpec,
    ConstraintSyncStateView,
    attention_for,
    legacy_missing_fields,
)
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.ooxml_worksheet_reader import OoxmlWorkbookSource
from my_pa.infrastructure.persistence.constraints import (
    SqlAlchemyConstraintManagementUnitOfWork,
)
from my_pa.infrastructure.persistence.tables import (
    constraint_categories,
    constraint_sync_baselines,
    entities,
    project_constraint_history,
    project_constraint_parties,
    project_constraint_revisions,
    project_constraints,
    projects,
)
from tests.fixtures.tbr_workbook import (
    DESIGN,
    PERMITS,
    SHEET_NAME,
    register_rows,
    text,
    write_register,
    write_workbook,
)

pytestmark = [pytest.mark.database, pytest.mark.database_clone]

PRINCIPAL_A: Final = "prn_impaaaa0001aaaa0001aa"
PRINCIPAL_B: Final = "prn_impbbbb0002bbbb0002bb"
PROJECT_A: Final = "prj_impaaaa0001aaaa"
PROJECT_B: Final = "prj_impbbbb0002bbbb"
ENTITY_MINE: Final = "ent_impaaaa0001aaaa"
ENTITY_THEIRS: Final = "ent_impbbbb0002bbbb"
REGISTER: Final = "synthetic-register-01"
ZONE: Final = "America/Chicago"
VENDOR_WORDING: Final = "A Synthetic Vendor"
OTHER_WORDING: Final = "Another Synthetic Vendor"
JOIN_TIMEOUT_SECONDS: Final = 30

T0: Final = datetime(2026, 9, 2, 15, 0, tzinfo=UTC)


def seed(engine: Engine) -> None:
    with engine.begin() as connection:
        for principal, project, entity in (
            (PRINCIPAL_A, PROJECT_A, ENTITY_MINE),
            (PRINCIPAL_B, PROJECT_B, ENTITY_THEIRS),
        ):
            connection.execute(
                insert(projects).values(
                    project_id=project,
                    principal_id=principal,
                    name="A Synthetic Project",
                    state="active",
                    participants=[],
                    opened_at=T0,
                    created_at=T0,
                    updated_at=T0,
                )
            )
            connection.execute(
                insert(entities).values(
                    entity_id=entity,
                    principal_id=principal,
                    entity_type="organization",
                    canonical_name="a synthetic vendor",
                    display_name="A Synthetic Vendor",
                    status="active",
                    created_at=T0,
                    updated_at=T0,
                    version=1,
                )
            )
    with SqlAlchemyConstraintManagementUnitOfWork(engine) as uow:
        for principal, project in ((PRINCIPAL_A, PROJECT_A), (PRINCIPAL_B, PROJECT_B)):
            uow.constraints.insert_project_settings(
                principal,
                ConstraintProjectSettings(
                    principal_id=principal,
                    project_id=project,
                    timezone_name=ZONE,
                    version=1,
                    created_at=T0,
                    updated_at=T0,
                ),
            )


@pytest.fixture
def staged(migrated_engine: Engine) -> Engine:
    seed(migrated_engine)
    return migrated_engine


def _importer(engine: Engine) -> ConstraintLegacyImportService:
    return ConstraintLegacyImportService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(engine),
        clock=lambda: T0,
    )


def _product(engine: Engine) -> ConstraintManagementService:
    return ConstraintManagementService(
        unit_of_work=lambda: SqlAlchemyConstraintManagementUnitOfWork(engine),
        clock=lambda: T0,
    )


def _reader(path: Path) -> OoxmlWorkbookSource:
    return OoxmlWorkbookSource(path, sheet_name=SHEET_NAME)


def _register(tmp_path: Path, name: str = "register.xlsm") -> Path:
    return write_register(tmp_path / name, with_vba=True)


def _apply(engine: Engine, source: Path, **overrides: object) -> object:
    arguments: dict[str, object] = {
        "principal_id": PRINCIPAL_A,
        "project_id": PROJECT_A,
        "register_id": REGISTER,
        "reader": _reader(source),
    }
    arguments.update(overrides)
    return _importer(engine).apply_disposable(**arguments)  # type: ignore[arg-type]


def _count(engine: Engine, table: FromClause, *where: ColumnElement[bool]) -> int:
    with engine.begin() as connection:
        return int(
            connection.execute(select(func.count()).select_from(table).where(*where)).scalar_one()
        )


def _codes(engine: Engine) -> list[str]:
    with engine.begin() as connection:
        return sorted(
            row[0]
            for row in connection.execute(
                select(project_constraints.c.constraint_code).where(
                    project_constraints.c.constraint_code.is_not(None)
                )
            ).all()
        )


def _allocator(engine: Engine, prefix: str) -> tuple[int, int]:
    with engine.begin() as connection:
        row = connection.execute(
            select(
                constraint_categories.c.next_sequence, constraint_categories.c.issued_count
            ).where(constraint_categories.c.prefix == prefix)
        ).one()
        return int(row[0]), int(row[1])


def _record(engine: Engine, code: str) -> object:
    """One imported record, read through the hydrator legacy rows survive.

    `read_constraint` and not `get`: the write aggregate's constructor refuses a
    stored legacy-incomplete row, and it is the read hydrator that returns it
    intact, with its parties joined and every absent value still absent.
    """
    with SqlAlchemyConstraintManagementUnitOfWork(engine) as uow:
        page = uow.constraints.list_constraints(PRINCIPAL_A, PROJECT_A, spec=_all_spec())
        found = next(record for record in page if record.constraint_code == code)
        record = uow.constraints.read_constraint(PRINCIPAL_A, found.constraint_id)
    assert record is not None
    return record


def _all_spec(
    sync_states: frozenset[ConstraintSyncStateView] = frozenset(),
) -> ConstraintListSpec:
    """One whole-register page, optionally narrowed to a derived sync state."""
    query = ConstraintListQuery(
        scope=ConstraintListScope.ALL, limit=MAX_LIST_LIMIT, sync_states=sync_states
    )
    today = date(2026, 9, 2)
    return ConstraintListSpec(
        query=query,
        as_of=T0,
        project_today=today,
        due_soon_through=today,
        fetch_limit=query.limit + 1,
    )


def test_an_apply_writes_the_records_the_dry_run_promised(staged: Engine, tmp_path: Path) -> None:
    """T13-11, CM-BE-AC-124. Every planned insert becomes one record and one revision."""
    source = _register(tmp_path)
    planned = _importer(staged).dry_run(
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        register_id=REGISTER,
        reader=_reader(source),
    )
    outcome = _apply(staged, source)
    assert outcome.report.applied == planned.report.planned_inserts  # type: ignore[attr-defined]
    assert _count(staged, project_constraints) == planned.report.planned_inserts
    assert _count(staged, project_constraint_revisions) == planned.report.planned_inserts
    assert _count(staged, project_constraint_history) == planned.report.planned_inserts
    assert _count(staged, constraint_categories) == 2


def test_every_imported_record_carries_the_legacy_origin_and_an_opaque_identity(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-11. The origin is the migration origin; the identity is minted, not derived."""
    _apply(staged, _register(tmp_path))
    with staged.begin() as connection:
        rows = connection.execute(
            select(
                project_constraints.c.constraint_id,
                project_constraints.c.origin,
                project_constraints.c.constraint_code,
                project_constraints.c.published_at,
            )
        ).all()
    assert rows
    for constraint_id, origin, code, published_at in rows:
        assert origin == ConstraintOrigin.LEGACY_WORKBOOK_IMPORT.value
        assert constraint_id.startswith("cst_")
        assert code not in constraint_id
        assert published_at is not None


def test_the_receipt_carries_the_composed_provenance_and_no_payload(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-11, CM-BE-AC-135. Key, digest and tool identity, in the columns that mean that."""
    _apply(staged, _register(tmp_path))
    with staged.begin() as connection:
        rows = connection.execute(
            select(
                project_constraint_history.c.idempotency_key,
                project_constraint_history.c.request_digest,
                project_constraint_history.c.client_context,
                project_constraint_history.c.operation,
                project_constraint_history.c.outcome,
                project_constraint_history.c.actor,
                project_constraint_history.c.revision_id,
            )
        ).all()
    assert rows
    expected = {
        row_idempotency_key(REGISTER, PROJECT_A, f"{SHEET_NAME}!{number}")
        for number in range(1, 40)
    }
    for key, digest, context, operation, outcome, actor, revision_id in rows:
        assert key in expected
        assert len(digest) == 64
        assert int(digest, 16) >= 0
        assert context == TOOL_CLIENT_CONTEXT
        assert operation == ConstraintMutationOperation.CREATE.value
        assert outcome == ConstraintMutationOutcome.APPLIED.value
        assert actor == ConstraintMutationActor.SYSTEM.value
        assert revision_id is not None


def test_codes_are_preserved_exactly_and_the_allocator_is_seeded_above_them(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-06, CM-BE-AC-124/127. Four `3.x` codes survive; the seed is 101."""
    _apply(staged, _register(tmp_path))
    stored = _codes(staged)
    assert {"3.01", "3.1", "3.10", "3.100"} <= set(stored)
    assert len(stored) == len(set(stored))
    assert _allocator(staged, "3") == (101, 5)
    assert _allocator(staged, "1") == (3, 2)


def test_an_unresolved_party_keeps_its_source_wording_in_the_original_label(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-09. No identity is fabricated; the wording is preserved where it belongs."""
    _apply(staged, _register(tmp_path))
    with staged.begin() as connection:
        rows = connection.execute(
            select(
                project_constraint_parties.c.party_kind,
                project_constraint_parties.c.entity_id,
                project_constraint_parties.c.original_label,
            )
        ).all()
    assert rows
    for kind, entity_id, original in rows:
        assert kind == PartyKind.UNRESOLVED.value
        assert entity_id is None
        assert original in {VENDOR_WORDING, OTHER_WORDING}
    assert VENDOR_WORDING in {row[2] for row in rows}
    assert OTHER_WORDING in {row[2] for row in rows}


def test_an_explicitly_mapped_entity_in_this_partition_resolves(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-09. Deterministic resolution: the operator's exact map, and nothing else."""
    _apply(staged, _register(tmp_path), party_map={VENDOR_WORDING: ENTITY_MINE})
    with staged.begin() as connection:
        rows = connection.execute(
            select(
                project_constraint_parties.c.party_kind,
                project_constraint_parties.c.entity_id,
                project_constraint_parties.c.original_label,
            )
        ).all()
    mapped = {(kind, entity_id) for kind, entity_id, label in rows if label == VENDOR_WORDING}
    unmapped = {(kind, entity_id) for kind, entity_id, label in rows if label == OTHER_WORDING}
    assert mapped == {(PartyKind.ENTITY.value, ENTITY_MINE)}
    assert unmapped == {(PartyKind.UNRESOLVED.value, None)}


def test_an_entity_in_another_principals_partition_is_refused(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-09, CM-BE-AC-132. A foreign identity is a blocker, never a silent fallback."""
    with pytest.raises(LegacyImportError) as error:
        _apply(staged, _register(tmp_path), party_map={VENDOR_WORDING: ENTITY_THEIRS})
    assert error.value.code == "legacy_import_blocked"
    assert _count(staged, project_constraints) == 0


def test_a_class_b_row_is_stored_legacy_incomplete_with_typed_missing_fields(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-10, CM-BE-AC-125. Reported through the existing read derivation, not a new one."""
    _apply(staged, _register(tmp_path))
    record = _record(staged, "1.02")
    assert record.record_quality is ConstraintRecordQuality.LEGACY_INCOMPLETE  # type: ignore[attr-defined]
    missing = legacy_missing_fields(record)  # type: ignore[arg-type]
    assert ConstraintFieldKey.DESCRIPTION in missing
    assert ConstraintFieldKey.BIC in missing
    attention = attention_for(record, has_open_conflict=False)  # type: ignore[arg-type]
    assert attention.needs_attention


def test_a_class_a_row_is_stored_normal_and_reports_no_missing_fields(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-10. Quality is data quality: a complete legacy row is not a defect."""
    _apply(staged, _register(tmp_path))
    record = _record(staged, "1.01")
    assert record.record_quality is ConstraintRecordQuality.NORMAL  # type: ignore[attr-defined]
    assert legacy_missing_fields(record) == ()  # type: ignore[arg-type]
    assert record.lifecycle_state is ConstraintLifecycleState.IDENTIFIED  # type: ignore[attr-defined]


def test_the_ordinary_write_aggregate_still_refuses_to_make_a_legacy_record(
    staged: Engine,
) -> None:
    """T13-10, dispatch section 11.7. The importer's licence widens nothing else."""
    signature = inspect.signature(ConstraintManagementService.create_draft)
    assert "origin" not in signature.parameters
    assert "record_quality" not in signature.parameters
    source = inspect.getsource(constraint_management)
    assert "ConstraintRecordQuality.LEGACY_INCOMPLETE" not in source
    assert "ConstraintOrigin.LEGACY_WORKBOOK_IMPORT" not in source


def test_no_baseline_row_is_written_and_every_record_reads_never_synced(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-13, CM-BE-AC-131. An unverified baseline is unrepresentable, so none is faked."""
    _apply(staged, _register(tmp_path))
    assert _count(staged, constraint_sync_baselines) == 0
    with SqlAlchemyConstraintManagementUnitOfWork(staged) as uow:
        everything = uow.constraints.list_constraints(PRINCIPAL_A, PROJECT_A, spec=_all_spec())
        by_state = {
            state: uow.constraints.list_constraints(
                PRINCIPAL_A, PROJECT_A, spec=_all_spec(frozenset({state}))
            )
            for state in ConstraintSyncStateView
        }
        facts = uow.constraints.sync_summary(
            PRINCIPAL_A, PROJECT_A, [record.constraint_id for record in everything]
        )
    assert everything
    assert facts.baseline_versions == {}
    never = by_state[ConstraintSyncStateView.NEVER_SYNCED]
    assert {record.constraint_id for record in never} == {
        record.constraint_id for record in everything
    }
    for state, page in by_state.items():
        if state is not ConstraintSyncStateView.NEVER_SYNCED:
            assert page == (), state


def test_a_rerun_of_the_same_register_writes_nothing_and_replays(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-12, CM-BE-AC-129. Same key, same digest: no record, no revision, no sequence."""
    source = _register(tmp_path)
    first = _apply(staged, source)
    census = (
        _count(staged, project_constraints),
        _count(staged, project_constraint_revisions),
        _count(staged, project_constraint_history),
        _allocator(staged, "3"),
        _allocator(staged, "1"),
    )
    second = _apply(staged, source)
    assert second.report.applied == 0  # type: ignore[attr-defined]
    assert second.report.replayed == first.report.applied  # type: ignore[attr-defined]
    assert (
        _count(staged, project_constraints),
        _count(staged, project_constraint_revisions),
        _count(staged, project_constraint_history),
        _allocator(staged, "3"),
        _allocator(staged, "1"),
    ) == census


def test_the_same_import_identity_with_changed_content_is_an_explicit_conflict(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-12, CM-BE-AC-130. Canonical state is never silently overwritten."""
    source = _register(tmp_path)
    _apply(staged, source)
    before = _count(staged, project_constraints)
    rows = register_rows()
    changed = list(rows[2])
    changed[1] = text("The permit set narrative has changed materially.")
    rows[2] = changed
    edited = write_workbook(tmp_path / "edited.xlsx", {SHEET_NAME: rows})
    with pytest.raises(LegacyImportIdempotencyConflictError):
        _apply(staged, edited)
    assert _count(staged, project_constraints) == before


def test_a_publish_after_an_import_cannot_allocate_a_preserved_code(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-12, CM-BE-AC-127. Two overlapping Publishes, neither colliding with the import."""
    _apply(staged, _register(tmp_path))
    imported = set(_codes(staged))
    with staged.begin() as connection:
        category_id = connection.execute(
            select(constraint_categories.c.category_id).where(constraint_categories.c.prefix == "3")
        ).scalar_one()

    def publish() -> str:
        service = _product(staged)
        draft = service.create_draft(
            principal_id=PRINCIPAL_A,
            actor=ConstraintMutationActor.PRINCIPAL,
            project_id=PROJECT_A,
            category_id=category_id,
            description="A product record, authored after the import.",
            date_identified=date(2026, 9, 2),
            # `CM-BE-AC-034`: a normal Publish requires at least one BIC. The
            # import path is exempt because a legacy row may carry none; this
            # Publish is the ordinary product path and is not.
            bic=[PartyRef(kind=PartyKind.PRINCIPAL)],
        ).record
        result = service.publish(
            principal_id=PRINCIPAL_A,
            constraint_id=draft.constraint_id,
            expected_version=draft.version,
            actor=ConstraintMutationActor.PRINCIPAL,
        )
        assert result.disposition is ConstraintMutationDisposition.APPLIED
        assert result.record.constraint_code is not None
        return result.record.constraint_code

    with ThreadPoolExecutor(max_workers=2) as pool:
        futures = [pool.submit(publish) for _ in range(2)]
        allocated = sorted(future.result(timeout=JOIN_TIMEOUT_SECONDS) for future in futures)

    assert len(set(allocated)) == 2
    assert not set(allocated) & imported
    for code in allocated:
        assert int(code.split(".", 1)[1]) > 100
    assert len(_codes(staged)) == len(imported) + 2


def test_the_categories_carry_the_authoritative_names_and_a_locked_prefix(
    staged: Engine, tmp_path: Path
) -> None:
    """T13-07 against the server. The names are authoritative; the prefix is locked."""
    _apply(staged, _register(tmp_path))
    with staged.begin() as connection:
        rows = connection.execute(
            select(
                constraint_categories.c.title,
                constraint_categories.c.prefix,
                constraint_categories.c.prefix_locked_at,
                constraint_categories.c.project_id,
            )
        ).all()
    assert {row[0] for row in rows} == {PERMITS, DESIGN}
    assert {row[1] for row in rows} == {"1", "3"}
    assert all(row[2] is not None for row in rows)
    assert all(row[3] == PROJECT_A for row in rows)
