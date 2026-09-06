"""PC-CM-IMP-WP03 §L T22: the four sync states persisted rows can prove, and nothing else.

The frontend recognises ten sync state names. Six of them — external import
pending, workbook unavailable, schema unsupported, partial, verification pending
and verification failed — each require a connector call, a workbook read, or a
live run comparison, which is WP11's behavior. They are not members of
`ConstraintSyncStateView` at all, so this read plane cannot emit one to satisfy a
fixture even by mistake, and the enumeration is asserted below to be exactly four.

What *is* derivable is derived from rows and in one stated order: an open
conflict outranks any baseline comparison, a missing target or missing baseline
is never-synced, and otherwise the baseline version either lags the Constraint's
version or matches it. WP02 shipped no sync writer, so every row in a live
database reads `NEVER_SYNCED` today; the rows here are hand-seeded so WP11
inherits semantics that were actually tested rather than merely intended.

The boundary is the last test. The whole read plane is exercised with a
statement recorder attached, and every statement it issues is a `SELECT`: no
lease is taken, no run is started, no baseline is written, and
`constraint_sync_runs` is not read at all.

Every identifier, digest and workbook name here is synthetic.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any, Final

import pytest
from sqlalchemy import Engine, event, insert
from sqlalchemy.engine import Connection

from my_pa.application.constraints import ConstraintReadService
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintRecordQuality,
    ProjectConstraint,
)
from my_pa.domain.project_controls.history import (
    ConstraintHistoryEntry,
    ConstraintMutationActor,
    ConstraintMutationOperation,
    ConstraintMutationOutcome,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef
from my_pa.domain.project_controls.read_models import (
    ConstraintListQuery,
    ConstraintListScope,
    ConstraintSyncStateView,
)
from my_pa.domain.project_controls.revision import ConstraintRevision
from my_pa.domain.project_controls.settings import ConstraintProjectSettings
from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import (
    constraint_sync_baselines,
    constraint_sync_conflicts,
    constraint_sync_runs,
    constraint_sync_targets,
    projects,
)

pytestmark = pytest.mark.database

#: Two Principals and two Projects in every test, so "one Principal cannot see
#: the other's rows" is something the data could disprove rather than something
#: the arrangement quietly guarantees.
PRINCIPAL_A: Final = "prn_synaaaa01"
PRINCIPAL_B: Final = "prn_synbbbb02"
PROJECT_A: Final = "prj_synaaaa01"
PROJECT_B: Final = "prj_synbbbb02"
CATEGORY_A: Final = "ccat_synaaaa01"
CATEGORY_B: Final = "ccat_synbbbb02"

#: One fixed UTC instant, and the two IANA zones a Project may read it in. No
#: test here reads a wall clock: every Project date is a function of these.
NOW: Final = datetime(2026, 9, 14, 16, 30, tzinfo=UTC)
ZONE_EAST: Final = "America/New_York"
ZONE_WEST: Final = "America/Los_Angeles"
T0: Final = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)

SERVICE: Final = ConstraintReadService()


def _id(prefix: str, ordinal: int) -> str:
    """A synthetic, disposable identifier of the shape `prefix` requires."""
    return f"{prefix}_syn{ordinal:06d}"


def _seed_project(connection: Connection, principal: str, project: str) -> None:
    connection.execute(
        insert(projects).values(
            project_id=project,
            principal_id=principal,
            name="Sample Project",
            state="active",
            participants=[],
            opened_at=T0,
            created_at=T0,
            updated_at=T0,
        )
    )


def _category(
    category_id: str, principal: str, project: str, prefix: str, display_order: int
) -> ConstraintCategory:
    return ConstraintCategory(
        category_id=category_id,
        principal_id=principal,
        project_id=project,
        prefix=prefix,
        title=f"Category {prefix}",
        state=ConstraintCategoryState.ACTIVE,
        created_at=T0,
        updated_at=T0,
        display_order=display_order,
    )


def _settings(principal: str, project: str, zone: str = ZONE_EAST) -> ConstraintProjectSettings:
    return ConstraintProjectSettings(
        principal_id=principal,
        project_id=project,
        timezone_name=zone,
        version=1,
        created_at=T0,
        updated_at=T0,
    )


def _constraint(**overrides: object) -> ProjectConstraint:
    """One published, active Constraint. Every value in it is synthetic."""
    values: dict[str, Any] = {
        "constraint_id": _id("cst", 1),
        "principal_id": PRINCIPAL_A,
        "lifecycle_state": ConstraintLifecycleState.IDENTIFIED,
        "origin": ConstraintOrigin.PRODUCT,
        "record_quality": ConstraintRecordQuality.NORMAL,
        "created_at": T0,
        "updated_at": T0,
        "version": 2,
        "project_id": PROJECT_A,
        "category_id": CATEGORY_A,
        "constraint_code": "1.01",
        "description": "Switchgear submittal outstanding",
        "date_identified": date(2026, 9, 1),
        "due_date": date(2026, 9, 30),
        "bic": (PartyRef(kind=PartyKind.PRINCIPAL),),
        "published_at": T0,
    }
    values.update(overrides)
    return ProjectConstraint(**values)


def _world(connection: Connection, *, zone: str = ZONE_EAST) -> SqlConstraintManagementRepository:
    """Both Principals, both Projects, one Category each. Nothing is shared."""
    _seed_project(connection, PRINCIPAL_A, PROJECT_A)
    _seed_project(connection, PRINCIPAL_B, PROJECT_B)
    repository = SqlConstraintManagementRepository(connection)
    repository.insert_project_settings(PRINCIPAL_A, _settings(PRINCIPAL_A, PROJECT_A, zone))
    repository.insert_project_settings(PRINCIPAL_B, _settings(PRINCIPAL_B, PROJECT_B, zone))
    repository.insert_category(PRINCIPAL_A, _category(CATEGORY_A, PRINCIPAL_A, PROJECT_A, "AAA", 1))
    repository.insert_category(PRINCIPAL_B, _category(CATEGORY_B, PRINCIPAL_B, PROJECT_B, "BBB", 1))
    return repository


IN_SYNC: Final = _id("cst", 1)
PENDING: Final = _id("cst", 2)
CONFLICTED: Final = _id("cst", 3)
NEVER: Final = _id("cst", 4)
TARGET: Final = _id("csyt", 1)
RUN: Final = _id("csyr", 1)
OPEN_CONFLICT: Final = _id("csyc", 1)
RESOLVED_CONFLICT: Final = _id("csyc", 2)

LAST_VERIFIED: Final = datetime(2026, 9, 10, 8, 0, tzinfo=UTC)
DIGEST: Final = "c" * 64

#: The `(constraint, its version, its baseline's version)` triples the states are
#: read from. `PENDING` is the one whose Constraint has moved past its baseline.
VERSIONS: Final = ((IN_SYNC, 2, 2), (PENDING, 3, 2), (CONFLICTED, 2, 2))


def _receipt(history_id: str, constraint_id: str) -> ConstraintHistoryEntry:
    return ConstraintHistoryEntry(
        history_id=history_id,
        principal_id=PRINCIPAL_A,
        constraint_id=constraint_id,
        project_id=PROJECT_A,
        operation=ConstraintMutationOperation.PUBLISH,
        actor=ConstraintMutationActor.PRINCIPAL,
        outcome=ConstraintMutationOutcome.NO_OP,
        before_version=1,
        after_version=1,
        occurred_at=T0,
        recorded_at=T0,
    )


def _seed_target(connection: Connection) -> None:
    connection.execute(
        insert(constraint_sync_targets).values(
            sync_target_id=TARGET,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            external_kind="excel_workbook",
            external_identity="synthetic-workbook-identity",
            normalization_contract_version="v1",
            last_verified_at=LAST_VERIFIED,
            version=1,
            created_at=T0,
            updated_at=T0,
        )
    )
    connection.execute(
        insert(constraint_sync_runs).values(
            sync_run_id=RUN,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            sync_target_id=TARGET,
            state="applied",
            started_at=T0,
            finished_at=T0,
            outcome="applied",
            created_at=T0,
            updated_at=T0,
        )
    )


def _seed_baseline(
    connection: Connection, constraint_id: str, revision_id: str, version: int
) -> None:
    connection.execute(
        insert(constraint_sync_baselines).values(
            sync_target_id=TARGET,
            constraint_id=constraint_id,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            baseline_revision_id=revision_id,
            baseline_constraint_version=version,
            baseline_field_digests={"description": DIGEST},
            baseline_record_digest=DIGEST,
            workbook_row_identity=f"row-{constraint_id}",
            verified_at=LAST_VERIFIED,
            created_at=T0,
            updated_at=T0,
        )
    )


def _synced(
    connection: Connection, *, with_target: bool = True
) -> SqlConstraintManagementRepository:
    repository = _world(connection)
    for ordinal, (identifier, version, _) in enumerate(VERSIONS, start=1):
        repository.insert_constraint(
            PRINCIPAL_A,
            _constraint(constraint_id=identifier, constraint_code=f"1.0{ordinal}", version=version),
        )
    repository.insert_constraint(
        PRINCIPAL_A, _constraint(constraint_id=NEVER, constraint_code="1.09")
    )
    if not with_target:
        return repository
    _seed_target(connection)
    for ordinal, (identifier, version, baseline_version) in enumerate(VERSIONS, start=1):
        history_id = _id("chst", ordinal)
        revision_id = _id("crev", ordinal)
        repository.insert_history(PRINCIPAL_A, _receipt(history_id, identifier))
        repository.insert_revision(
            PRINCIPAL_A,
            ConstraintRevision.from_constraint(
                _constraint(constraint_id=identifier, version=version),
                revision_id=revision_id,
                history_id=history_id,
                recorded_at=T0,
            ),
        )
        _seed_baseline(connection, identifier, revision_id, baseline_version)
    connection.execute(
        insert(constraint_sync_conflicts).values(
            sync_conflict_id=OPEN_CONFLICT,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            sync_target_id=TARGET,
            constraint_id=CONFLICTED,
            sync_run_id=RUN,
            conflict_kind="both_changed",
            field_names=["description"],
            state="open",
            created_at=T0,
        )
    )
    connection.execute(
        insert(constraint_sync_conflicts).values(
            sync_conflict_id=RESOLVED_CONFLICT,
            principal_id=PRINCIPAL_A,
            project_id=PROJECT_A,
            sync_target_id=TARGET,
            constraint_id=IN_SYNC,
            sync_run_id=RUN,
            conflict_kind="both_changed",
            field_names=["due_date"],
            state="resolved",
            resolved_at=T0,
            resolution_history_id=_id("chst", 1),
            created_at=T0,
        )
    )
    return repository


def _states(repository: SqlConstraintManagementRepository) -> dict[str, ConstraintSyncStateView]:
    page = SERVICE.list_constraints(
        repository,
        principal_id=PRINCIPAL_A,
        project_id=PROJECT_A,
        query=ConstraintListQuery(scope=ConstraintListScope.ALL),
        now=NOW,
    )
    return {entry.constraint_id: entry.sync_state for entry in page.entries}


def test_only_four_sync_states_exist_to_be_emitted(migrated_engine: Engine) -> None:
    """The six that need a connector have no member, so no path can produce one."""
    assert {state.value for state in ConstraintSyncStateView} == {
        "never_synced",
        "in_sync",
        "db_export_pending",
        "conflict",
    }
    assert migrated_engine is not None


def test_a_project_with_no_target_reads_as_never_synced_throughout(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _synced(connection, with_target=False)
        assert set(_states(repository).values()) == {ConstraintSyncStateView.NEVER_SYNCED}
        facts = repository.sync_summary(PRINCIPAL_A, PROJECT_A, ())
        assert facts.has_target is False
        assert facts.last_verified_at is None
        assert facts.baseline_versions == {}
        assert facts.open_conflict_counts == {}
        overview = SERVICE.read_overview(
            repository, principal_id=PRINCIPAL_A, project_id=PROJECT_A, now=NOW
        )
        assert overview.sync_health.state is ConstraintSyncStateView.NEVER_SYNCED
        assert overview.sync_health.open_conflict_count == 0
        assert overview.sync_health.last_verified_at is None


def test_a_baseline_at_the_constraints_own_version_reads_as_in_sync(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _synced(connection)
        assert _states(repository)[IN_SYNC] is ConstraintSyncStateView.IN_SYNC


def test_a_constraint_past_its_baseline_reads_as_export_pending(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _synced(connection)
        assert _states(repository)[PENDING] is ConstraintSyncStateView.DB_EXPORT_PENDING


def test_an_open_conflict_outranks_the_baseline_comparison(migrated_engine: Engine) -> None:
    """The conflicted row's baseline matches its version and it is still a conflict."""
    with migrated_engine.begin() as connection:
        repository = _synced(connection)
        assert _states(repository)[CONFLICTED] is ConstraintSyncStateView.CONFLICT


def test_a_constraint_with_a_target_but_no_baseline_is_still_never_synced(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _synced(connection)
        assert _states(repository)[NEVER] is ConstraintSyncStateView.NEVER_SYNCED


def test_a_resolved_conflict_is_not_an_open_one(migrated_engine: Engine) -> None:
    with migrated_engine.begin() as connection:
        repository = _synced(connection)
        facts = repository.sync_summary(PRINCIPAL_A, PROJECT_A, ())
        assert facts.open_conflict_counts == {CONFLICTED: 1}
        assert facts.has_target is True
        assert facts.last_verified_at == LAST_VERIFIED


def test_the_detail_read_reports_the_state_the_instant_and_the_count(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _synced(connection)
        view = SERVICE.read_constraint(
            repository, principal_id=PRINCIPAL_A, constraint_id=CONFLICTED, now=NOW
        )
        assert view.sync.state is ConstraintSyncStateView.CONFLICT
        assert view.sync.conflict_count == 1
        assert view.sync.last_verified_at == LAST_VERIFIED
        assert view.needs_attention is True


def test_the_overview_rolls_the_project_up_to_conflict_when_one_is_open(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _synced(connection)
        overview = SERVICE.read_overview(
            repository, principal_id=PRINCIPAL_A, project_id=PROJECT_A, now=NOW
        )
        assert overview.sync_health.state is ConstraintSyncStateView.CONFLICT
        assert overview.sync_health.open_conflict_count == 1
        assert overview.sync_health.last_verified_at == LAST_VERIFIED


def test_the_sync_state_filter_selects_on_the_same_derivation(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _synced(connection)
        for state, expected in (
            (ConstraintSyncStateView.IN_SYNC, [IN_SYNC]),
            (ConstraintSyncStateView.DB_EXPORT_PENDING, [PENDING]),
            (ConstraintSyncStateView.CONFLICT, [CONFLICTED]),
            (ConstraintSyncStateView.NEVER_SYNCED, [NEVER]),
        ):
            page = SERVICE.list_constraints(
                repository,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A,
                query=ConstraintListQuery(
                    scope=ConstraintListScope.ALL, sync_states=frozenset({state})
                ),
                now=NOW,
            )
            assert [entry.constraint_id for entry in page.entries] == expected


def test_the_other_principal_derives_nothing_from_this_projects_sync_rows(
    migrated_engine: Engine,
) -> None:
    with migrated_engine.begin() as connection:
        repository = _synced(connection)
        facts = repository.sync_summary(PRINCIPAL_B, PROJECT_A, ())
        assert facts.has_target is False
        assert facts.open_conflict_counts == {}
        assert facts.baseline_versions == {}


def test_no_read_writes_to_a_sync_table_or_touches_a_run(migrated_engine: Engine) -> None:
    """Read-only in the literal sense: every statement the plane issues is a SELECT."""
    statements: list[str] = []

    def _record(
        conn: object,
        cursor: object,
        statement: str,
        parameters: object,
        context: object,
        executemany: bool,
    ) -> None:
        statements.append(statement)

    with migrated_engine.begin() as connection:
        repository = _synced(connection)
        event.listen(migrated_engine, "before_cursor_execute", _record)
        try:
            SERVICE.list_constraints(
                repository,
                principal_id=PRINCIPAL_A,
                project_id=PROJECT_A,
                query=ConstraintListQuery(scope=ConstraintListScope.ALL),
                now=NOW,
            )
            SERVICE.read_constraint(
                repository, principal_id=PRINCIPAL_A, constraint_id=CONFLICTED, now=NOW
            )
            SERVICE.read_overview(
                repository, principal_id=PRINCIPAL_A, project_id=PROJECT_A, now=NOW
            )
        finally:
            event.remove(migrated_engine, "before_cursor_execute", _record)
        assert statements
        for statement in statements:
            normalised = " ".join(statement.split()).upper()
            assert normalised.startswith("SELECT")
            assert "INSERT INTO" not in normalised
            assert "UPDATE " not in normalised
            assert "DELETE FROM" not in normalised
            assert "FOR UPDATE" not in normalised
            assert "CONSTRAINT_SYNC_RUNS" not in normalised


def test_the_project_roll_up_does_not_fan_the_target_out_across_every_baseline(
    migrated_engine: Engine,
) -> None:
    """The overview's `sync_summary` reads no baseline row at all.

    `sync_summary` takes an empty Constraint collection to mean "the whole
    Project", which is what `read_overview` passes. That path consumes
    `has_target` and the open-conflict counts and nothing else, so joining the
    baselines there would return one row per baseline in the Project to build a
    mapping no caller reads — a fetch whose row volume grows with the Register
    while the statement count stays flat, which is exactly the unbounded shape a
    statement-count guard cannot see.

    Asserted two ways, because either alone is weak: the emitted SQL must not
    name the baselines table, and the returned mapping must be empty even though
    baselines exist. The per-Constraint call in the same test is the control —
    it *does* read baselines, so a regression that simply stopped reading them
    everywhere would redden here rather than pass quietly.
    """
    with migrated_engine.begin() as connection:
        repository = _synced(connection)

        statements: list[str] = []

        def _record(
            _conn: object,
            _cursor: object,
            statement: str,
            _parameters: object,
            _context: object,
            _executemany: object,
        ) -> None:
            statements.append(statement)

        event.listen(migrated_engine, "before_cursor_execute", _record)
        try:
            roll_up = repository.sync_summary(PRINCIPAL_A, PROJECT_A, ())
        finally:
            event.remove(migrated_engine, "before_cursor_execute", _record)

        assert statements, "no statement was captured, so the assertions below prove nothing"
        assert not any("constraint_sync_baselines" in s.lower() for s in statements), (
            "the Project roll-up joined constraint_sync_baselines. It reads only "
            "has_target and the conflict counts, so the join returns rows nobody "
            "consumes and grows with the Register"
        )
        assert roll_up.has_target is True
        assert roll_up.baseline_versions == {}
        assert sum(roll_up.open_conflict_counts.values()) == 1

        scoped = repository.sync_summary(PRINCIPAL_A, PROJECT_A, (IN_SYNC,))
        assert scoped.baseline_versions, (
            "the per-Constraint call read no baseline, so the roll-up assertion "
            "above would pass even if baselines were never readable at all"
        )
