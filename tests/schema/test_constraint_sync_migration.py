"""Offline guards for the additive Constraint synchronization revision."""

from __future__ import annotations

import ast
import importlib.util
import io
from pathlib import Path
from types import ModuleType
from typing import Final

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, delete, func, insert, select, text, update
from tests.database.test_constraint_schema_invariants import (
    HISTORY,
    PRINCIPAL,
    SYNC_RUN,
    SYNC_TARGET,
    T0,
    _base,
    _refuses,
    _sync_conflict_values,
    _sync_run_values,
    _sync_target_values,
)

from my_pa.infrastructure.persistence.constraints import SqlConstraintManagementRepository
from my_pa.infrastructure.persistence.tables import (
    constraint_sync_conflicts,
    constraint_sync_legacy_unbound_conflicts,
    constraint_sync_resolution_history,
    constraint_sync_runs,
    constraint_sync_targets,
    project_constraint_history,
)

ROOT: Final = Path(__file__).resolve().parents[2]
REVISION: Final = "b8e4d6f20a11"
PREVIOUS: Final = "f7a2c9d51e64"
MIGRATION: Final = ROOT / "migrations/versions/20260908_b8e4d6f20a11_add_constraint_sync_backend.py"
TABLES: Final = (
    "constraint_sync_legacy_unbound_conflicts",
    "constraint_sync_run_items",
    "constraint_sync_resolution_history",
)
CAPABILITIES: Final = (
    "constraint_sync.acknowledge",
    "constraint_sync.apply",
    "constraint_sync.conflicts",
    "constraint_sync.delta",
    "constraint_sync.preview",
    "constraint_sync.resolve",
    "constraint_sync.state",
)
PURPOSES: Final = ("constraint_sync_authoring", "constraint_sync_read")


def _config(buffer: io.StringIO | None = None) -> Config:
    return Config(str(ROOT / "alembic.ini"), output_buffer=buffer)


def _module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("_constraint_sync_revision", MIGRATION)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _offline(target: str, *, down: bool = False) -> str:
    buffer = io.StringIO()
    (command.downgrade if down else command.upgrade)(_config(buffer), target, sql=True)
    return buffer.getvalue()


def test_revision_is_the_only_head_and_directly_follows_wp07() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [REVISION]
    assert script.get_revision(REVISION).down_revision == PREVIOUS
    assert len(list(script.walk_revisions())) == 101


def test_revision_is_frozen_and_adds_exact_vocabulary() -> None:
    tree = ast.parse(MIGRATION.read_text(encoding="utf-8"))
    imports = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not [name for name in imports if name == "my_pa" or name.startswith("my_pa.")]
    module = _module()
    before_caps = module._CAPABILITIES_BEFORE_THIS_REVISION
    after_caps = module._CAPABILITIES_AT_THIS_REVISION
    before_purposes = module._PURPOSES_BEFORE_THIS_REVISION
    after_purposes = module._PURPOSES_AT_THIS_REVISION
    assert all(
        f"'{value}'" not in before_caps and f"'{value}'" in after_caps for value in CAPABILITIES
    )
    assert all(
        f"'{value}'" not in before_purposes and f"'{value}'" in after_purposes for value in PURPOSES
    )


def test_offline_upgrade_and_downgrade_are_bounded_and_reversible(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("MY_PA_DATABASE_URL", "postgresql+psycopg://localhost/my_pa")
    upgrade = _offline(f"{PREVIOUS}:{REVISION}")
    downgrade = _offline(f"{REVISION}:{PREVIOUS}", down=True)
    for table in TABLES:
        assert f"CREATE TABLE knowledge.{table}" in upgrade
        assert f"DROP TABLE knowledge.{table}" in downgrade
    assert "ALTER TABLE knowledge.constraint_sync_targets ADD COLUMN last_run_id" in upgrade
    assert "ALTER TABLE knowledge.constraint_sync_runs ADD COLUMN sync_state" in upgrade
    assert "ADD COLUMN preview_lease_until" in upgrade
    assert "ADD COLUMN apply_canonical_digest" in upgrade
    assert "DROP COLUMN last_run_id" in downgrade
    assert "DROP COLUMN sync_state" in downgrade
    for value in (*CAPABILITIES, *PURPOSES):
        assert value in upgrade
    assert "constraint_sync_runs_scope_is_unique" in upgrade
    assert "constraint_sync_targets_scope_is_unique" in upgrade
    assert "INSERT INTO knowledge.constraint_sync_legacy_unbound_conflicts" in upgrade
    assert "legacy_scope_disposition = 'legacy_unbound'" in upgrade
    assert "USING knowledge.constraint_sync_legacy_unbound_conflicts" in upgrade
    assert "constraint_sync_runs_principal_preview_key_is_unique" in upgrade
    assert "constraint_sync_runs_principal_preview_key_is_unique" in downgrade
    assert "constraint_sync_conflicts_scope_is_unique" in upgrade
    assert "constraint_sync_conflicts_run_scope_is_unique" in upgrade
    assert "response_summary JSONB NOT NULL" in upgrade
    assert "sync_target_id TEXT NOT NULL" in upgrade
    assert "'legacy_migrated'" in upgrade
    assert "'reopen'" in upgrade
    trigger = "constraint_sync_resolution_history_is_append_only"
    function = "knowledge.constraint_sync_resolution_history_stays_written()"
    assert f"CREATE TRIGGER {trigger} BEFORE UPDATE OR DELETE" in upgrade
    assert f"EXECUTE FUNCTION {function}" in upgrade
    assert f"DROP TRIGGER {trigger}" in downgrade
    assert f"DROP FUNCTION {function}" in downgrade
    assert (
        downgrade.index(f"DROP TRIGGER {trigger}")
        < downgrade.index("DROP TABLE knowledge.constraint_sync_resolution_history")
        < downgrade.index(f"DROP FUNCTION {function}")
    )


@pytest.mark.database
@pytest.mark.migration
@pytest.mark.migration_edge
def test_populated_resolution_receipts_survive_upgrade_and_downgrade(
    migrated_engine: Engine,
) -> None:
    command.downgrade(_config(), PREVIOUS)
    try:
        with migrated_engine.begin() as connection:
            _base(connection)
            connection.execute(insert(constraint_sync_targets).values(**_sync_target_values()))
            predecessor_columns = {
                "sync_run_id",
                "principal_id",
                "project_id",
                "sync_target_id",
                "state",
                "started_at",
                "finished_at",
                "provider_version_before",
                "provider_version_after",
                "workbook_digest_before",
                "workbook_digest_after",
                "preview_digest",
                "outcome",
                "safe_failure_reason",
                "created_at",
                "updated_at",
            }
            predecessor_run = {
                key: value
                for key, value in _sync_run_values().items()
                if key in predecessor_columns
            }
            connection.execute(insert(constraint_sync_runs).values(**predecessor_run))
            connection.execute(
                insert(constraint_sync_conflicts).values(
                    **_sync_conflict_values(
                        state="resolved",
                        resolved_at=_sync_conflict_values()["created_at"],
                        resolution_history_id=HISTORY,
                    )
                )
            )

        command.upgrade(_config(), REVISION)
        with migrated_engine.begin() as connection:
            conflict = connection.execute(select(constraint_sync_conflicts)).one()._mapping
            receipt = connection.execute(select(constraint_sync_resolution_history)).one()._mapping
            assert str(conflict["resolution_history_id"]).startswith("csyrh_")
            assert receipt["constraint_history_id"] == HISTORY
            assert receipt["resolution"] == "legacy_migrated"
            assert receipt["resolution"] not in {
                "keep_canonical",
                "accept_external",
                "manual_patch",
            }
            assert receipt["sync_run_id"] == SYNC_RUN
            assert receipt["sync_target_id"] == _sync_target_values()["sync_target_id"]
            assert receipt["principal_id"] == PRINCIPAL
            assert receipt["constraint_version"] == 1
            _refuses(
                connection,
                update(constraint_sync_resolution_history).values(resolution="keep_canonical"),
            )
            _refuses(connection, delete(constraint_sync_resolution_history))
            assert (
                connection.execute(
                    select(constraint_sync_resolution_history.c.resolution)
                ).scalar_one()
                == "legacy_migrated"
            )

        command.downgrade(_config(), PREVIOUS)
        with migrated_engine.begin() as connection:
            restored = connection.execute(select(constraint_sync_conflicts)).one()._mapping
            assert restored["state"] == "resolved"
            assert restored["resolution_history_id"] == HISTORY

        command.upgrade(_config(), REVISION)
        with migrated_engine.begin() as connection:
            connection.execute(
                insert(constraint_sync_conflicts).values(
                    **_sync_conflict_values(
                        sync_conflict_id="csyc_wpzerodddd0004dddd",
                        state="resolved",
                        resolved_at=_sync_conflict_values()["created_at"],
                        resolution_history_id="csyrh_wpzerodddd0004dddd",
                    )
                )
            )
            connection.execute(
                insert(constraint_sync_resolution_history).values(
                    resolution_history_id="csyrh_wpzerodddd0004dddd",
                    principal_id=PRINCIPAL,
                    project_id=_sync_target_values()["project_id"],
                    sync_target_id=_sync_target_values()["sync_target_id"],
                    sync_conflict_id="csyc_wpzerodddd0004dddd",
                    sync_run_id=SYNC_RUN,
                    resolution="keep_canonical",
                    expected_constraint_version=1,
                    idempotency_key="resolved_sync_0004",
                    request_digest="4" * 64,
                    constraint_history_id=None,
                    constraint_version=1,
                    created_at=_sync_conflict_values()["created_at"],
                )
            )
            for index, kind in enumerate(("identity", "lifecycle"), start=2):
                connection.execute(
                    insert(constraint_sync_conflicts).values(
                        **_sync_conflict_values(
                            sync_conflict_id=f"csyc_wpzero{index:04d}cccc{index:04d}cccc",
                            conflict_kind=kind,
                            field_names=["constraint_code" if kind == "identity" else "status"],
                        )
                    )
                )
        command.downgrade(_config(), PREVIOUS)
        with migrated_engine.begin() as connection:
            conflicts = {
                row._mapping["sync_conflict_id"]: row._mapping
                for row in connection.execute(select(constraint_sync_conflicts)).all()
            }
            assert conflicts["csyc_wpzeroaaaa0001aaaa"]["state"] == "resolved"
            assert conflicts["csyc_wpzeroaaaa0001aaaa"]["resolution_history_id"] == HISTORY
            preserved = conflicts["csyc_wpzerodddd0004dddd"]
            assert preserved["state"] == "superseded"
            assert preserved["resolved_at"] is None
            assert preserved["resolution_history_id"] is None
            translated = [
                row
                for identifier, row in conflicts.items()
                if identifier
                not in {
                    "csyc_wpzeroaaaa0001aaaa",
                    "csyc_wpzerodddd0004dddd",
                }
            ]
            assert len(translated) == 2
            assert {(row["conflict_kind"], row["state"]) for row in translated} == {
                ("both_changed", "superseded")
            }
    finally:
        command.upgrade(_config(), REVISION)


@pytest.mark.database
@pytest.mark.migration
@pytest.mark.migration_edge
def test_populated_targets_backfill_the_current_scoped_run_and_survive_downgrade(
    migrated_engine: Engine,
) -> None:
    verified_target = "csyt_wpzerobbbb0002bbbb"
    verified_run = "csyr_wpzerobbbb0002bbbb"
    fallback_target = "csyt_wpzerocccc0003cccc"
    fallback_run = "csyr_wpzerocccc0003cccc"
    command.downgrade(_config(), PREVIOUS)
    try:
        with migrated_engine.begin() as connection:
            _base(connection)
            predecessor_target_columns = {
                "sync_target_id",
                "principal_id",
                "project_id",
                "external_kind",
                "external_identity",
                "normalization_contract_version",
                "last_verified_provider_version",
                "last_verified_workbook_digest",
                "last_verified_at",
                "last_verified_sync_run_id",
                "active_run_id",
                "active_run_lease_until",
                "version",
                "created_at",
                "updated_at",
            }
            predecessor_run_columns = {
                "sync_run_id",
                "principal_id",
                "project_id",
                "sync_target_id",
                "state",
                "started_at",
                "finished_at",
                "provider_version_before",
                "provider_version_after",
                "workbook_digest_before",
                "workbook_digest_after",
                "preview_digest",
                "outcome",
                "safe_failure_reason",
                "created_at",
                "updated_at",
            }

            def target(**values: object) -> dict[str, object]:
                return {
                    key: value
                    for key, value in _sync_target_values(**values).items()
                    if key in predecessor_target_columns
                }

            def run(**values: object) -> dict[str, object]:
                return {
                    key: value
                    for key, value in _sync_run_values(**values).items()
                    if key in predecessor_run_columns
                }

            connection.execute(
                insert(constraint_sync_targets),
                [
                    target(active_run_id=SYNC_RUN, active_run_lease_until=T0),
                    target(
                        sync_target_id=verified_target,
                        external_identity="synthetic-workbook-identity-0002",
                        last_verified_provider_version="v2",
                        last_verified_workbook_digest="2" * 64,
                        last_verified_at=T0,
                        last_verified_sync_run_id=verified_run,
                    ),
                    target(
                        sync_target_id=fallback_target,
                        external_identity="synthetic-workbook-identity-0003",
                        active_run_id=SYNC_RUN,
                        active_run_lease_until=T0,
                        last_verified_provider_version="v3",
                        last_verified_workbook_digest="3" * 64,
                        last_verified_at=T0,
                        last_verified_sync_run_id=fallback_run,
                    ),
                ],
            )
            connection.execute(
                insert(constraint_sync_runs),
                [
                    run(state="applied", finished_at=T0, outcome="applied"),
                    run(
                        sync_run_id=verified_run,
                        sync_target_id=verified_target,
                        state="acknowledged",
                        finished_at=T0,
                        outcome="no_change",
                    ),
                    run(
                        sync_run_id=fallback_run,
                        sync_target_id=fallback_target,
                        state="acknowledged",
                        finished_at=T0,
                        outcome="no_change",
                    ),
                ],
            )

        command.upgrade(_config(), REVISION)
        with migrated_engine.begin() as connection:
            targets = {
                row.sync_target_id: row.last_run_id
                for row in connection.execute(
                    select(
                        constraint_sync_targets.c.sync_target_id,
                        constraint_sync_targets.c.last_run_id,
                    )
                )
            }
            assert targets == {
                _sync_target_values()["sync_target_id"]: SYNC_RUN,
                verified_target: verified_run,
                fallback_target: fallback_run,
            }
            repository = SqlConstraintManagementRepository(connection)
            project_id = str(_sync_target_values()["project_id"])
            active_state = repository.read_sync_state(
                PRINCIPAL, project_id, str(_sync_target_values()["sync_target_id"])
            )
            verified_state = repository.read_sync_state(PRINCIPAL, project_id, verified_target)
            fallback_state = repository.read_sync_state(PRINCIPAL, project_id, fallback_target)
            assert active_state is not None and active_state["state"] == "verification_pending"
            assert verified_state is not None and verified_state["state"] == "in_sync"
            assert fallback_state is not None and fallback_state["state"] == "in_sync"
            assert fallback_state["active_run_id"] is None

        command.downgrade(_config(), PREVIOUS)
        with migrated_engine.begin() as connection:
            assert (
                connection.execute(
                    text(
                        "SELECT column_name FROM information_schema.columns "
                        "WHERE table_schema = 'knowledge' "
                        "AND table_name = 'constraint_sync_targets' "
                        "AND column_name = 'last_run_id'"
                    )
                ).all()
                == []
            )
    finally:
        command.upgrade(_config(), REVISION)


@pytest.mark.database
@pytest.mark.migration
@pytest.mark.migration_edge
def test_predecessor_cross_target_conflicts_are_quarantined_and_round_trip_exactly(
    migrated_engine: Engine,
) -> None:
    other_target = "csyt_wpzerobbbb0002bbbb"
    open_conflict_id = "csyc_wpzerobbbb0002bbbb"
    resolved_conflict_id = "csyc_wpzerocccc0003cccc"
    command.downgrade(_config(), PREVIOUS)
    try:
        with migrated_engine.begin() as connection:
            _base(connection)
            predecessor_target_columns = {
                "sync_target_id",
                "principal_id",
                "project_id",
                "external_kind",
                "external_identity",
                "normalization_contract_version",
                "last_verified_provider_version",
                "last_verified_workbook_digest",
                "last_verified_at",
                "last_verified_sync_run_id",
                "active_run_id",
                "active_run_lease_until",
                "version",
                "created_at",
                "updated_at",
            }
            predecessor_run_columns = {
                "sync_run_id",
                "principal_id",
                "project_id",
                "sync_target_id",
                "state",
                "started_at",
                "finished_at",
                "provider_version_before",
                "provider_version_after",
                "workbook_digest_before",
                "workbook_digest_after",
                "preview_digest",
                "outcome",
                "safe_failure_reason",
                "created_at",
                "updated_at",
            }

            def target(**values: object) -> dict[str, object]:
                return {
                    key: value
                    for key, value in _sync_target_values(**values).items()
                    if key in predecessor_target_columns
                }

            def run(**values: object) -> dict[str, object]:
                return {
                    key: value
                    for key, value in _sync_run_values(**values).items()
                    if key in predecessor_run_columns
                }

            connection.execute(
                insert(constraint_sync_targets),
                [
                    target(),
                    target(
                        sync_target_id=other_target,
                        external_identity="synthetic-workbook-identity-0002",
                    ),
                ],
            )
            connection.execute(insert(constraint_sync_runs).values(**run()))
            predecessor_conflict_columns = {
                column.name for column in constraint_sync_conflicts.c
            } - {"external_candidate_digest"}
            conflicts = [
                {
                    key: value
                    for key, value in _sync_conflict_values(
                        sync_conflict_id=open_conflict_id,
                        sync_target_id=other_target,
                    ).items()
                    if key in predecessor_conflict_columns
                },
                {
                    key: value
                    for key, value in _sync_conflict_values(
                        sync_conflict_id=resolved_conflict_id,
                        sync_target_id=other_target,
                        state="resolved",
                        resolved_at=T0,
                        resolution_history_id=HISTORY,
                    ).items()
                    if key in predecessor_conflict_columns
                },
            ]
            connection.execute(insert(constraint_sync_conflicts), conflicts)
            history_before = connection.execute(
                select(func.count()).select_from(project_constraint_history)
            ).scalar_one()

        for destination in (REVISION, PREVIOUS, REVISION):
            if destination == PREVIOUS:
                command.downgrade(_config(), destination)
            else:
                command.upgrade(_config(), destination)
            with migrated_engine.begin() as connection:
                assert set(
                    connection.execute(select(constraint_sync_targets.c.sync_target_id)).scalars()
                ) == {SYNC_TARGET, other_target}
                assert connection.execute(
                    select(constraint_sync_runs.c.sync_run_id)
                ).scalars().all() == [SYNC_RUN]
                assert (
                    connection.execute(
                        select(func.count()).select_from(project_constraint_history)
                    ).scalar_one()
                    == history_before
                )
                if destination == REVISION:
                    assert (
                        connection.execute(select(constraint_sync_conflicts.c.sync_conflict_id))
                        .scalars()
                        .all()
                        == []
                    )
                    quarantined = {
                        row._mapping["sync_conflict_id"]: row._mapping
                        for row in connection.execute(
                            select(constraint_sync_legacy_unbound_conflicts)
                        ).all()
                    }
                    assert set(quarantined) == {open_conflict_id, resolved_conflict_id}
                    assert {
                        identifier: (
                            row["sync_target_id"],
                            row["sync_run_id"],
                            row["state"],
                            row["resolved_at"],
                            row["resolution_history_id"],
                            row["legacy_scope_disposition"],
                        )
                        for identifier, row in quarantined.items()
                    } == {
                        open_conflict_id: (
                            other_target,
                            SYNC_RUN,
                            "open",
                            None,
                            None,
                            "legacy_unbound",
                        ),
                        resolved_conflict_id: (
                            other_target,
                            SYNC_RUN,
                            "resolved",
                            T0,
                            HISTORY,
                            "legacy_unbound",
                        ),
                    }
                    assert (
                        connection.execute(
                            text(
                                "SELECT count(*) FROM knowledge.constraint_sync_resolution_history"
                            )
                        ).scalar_one()
                        == 0
                    )
                else:
                    restored = {
                        row._mapping["sync_conflict_id"]: row._mapping
                        for row in connection.execute(select(constraint_sync_conflicts)).all()
                    }
                    assert set(restored) == {open_conflict_id, resolved_conflict_id}
                    assert restored[open_conflict_id]["state"] == "open"
                    assert restored[open_conflict_id]["resolution_history_id"] is None
                    assert restored[resolved_conflict_id]["state"] == "resolved"
                    assert restored[resolved_conflict_id]["resolved_at"] == T0
                    assert restored[resolved_conflict_id]["resolution_history_id"] == HISTORY
    finally:
        command.upgrade(_config(), REVISION)
