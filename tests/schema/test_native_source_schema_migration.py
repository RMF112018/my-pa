"""WP-12B frozen schema, persistence boundaries, and concurrent checkpoints."""

from __future__ import annotations

import ast
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from hashlib import sha256
from pathlib import Path
from threading import Barrier

import pytest
from alembic import command
from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import Engine, inspect, select, text, update
from sqlalchemy.engine import Connection, make_url
from sqlalchemy.exc import DBAPIError, IntegrityError

from my_pa.bootstrap.settings import ENV_PREFIX, load_settings
from my_pa.domain.native_sources import (
    ContactMembership,
    ExactBucketSelection,
    LiveActivationGate,
    LiveActivationGateState,
    NativeCheckpoint,
    NativeConfigurationRevision,
    NativeRun,
    NativeRunKind,
    NativeRunState,
    NativeSourceAccount,
    NativeSourceKind,
    SimulationReceipt,
    WatcherSimulation,
    WatcherSimulationState,
)
from my_pa.domain.source.provider import ObjectKind
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.native_sources import (
    CheckpointConflictError,
    NativePersistenceConflictError,
    SqlNativeSourceRepository,
)
from my_pa.infrastructure.persistence.principal_scope import capture_context
from my_pa.infrastructure.persistence.tables import (
    METADATA,
    native_checkpoints,
    native_configuration_revisions,
)

ROOT = Path(__file__).resolve().parents[2]
REVISION = "8c4d1e7a2b90"
PRIOR_REVISION = "7f2a9d6c4e18"
HEAD_REVISION = "d7e1a4c8b926"
WP12E_PRIOR_REVISION = "9d5e2f7b4c61"
DATABASE = "my_pa_native_sources_test"
WHEN = datetime(2026, 8, 4, 12, tzinfo=UTC)
CONTEXT = capture_context("prn_0000000000000001")
OTHER_CONTEXT = capture_context("prn_0000000000000002")

EXPECTED_TABLES = frozenset(
    {
        "source_version_evidence",
        "native_bridges",
        "native_bridge_observations",
        "native_source_accounts",
        "native_source_buckets",
        "native_discovery_snapshots",
        "native_configuration_revisions",
        "native_configuration_buckets",
        "native_sync_runs",
        "native_bucket_runs",
        "native_sync_jobs",
        "native_checkpoints",
        "source_observations",
        "source_memberships",
        "native_watcher_simulations",
        "native_simulation_receipts",
        "native_live_activation_gates",
    }
)

REQUIRED_NAMED_CONSTRAINTS = frozenset(
    {
        "native_account_locator_is_issued_once",
        "native_bucket_locator_is_issued_once",
        "native_configuration_selection_digest_is_sha256",
        "native_sync_run_idempotency_is_scoped",
        "one_native_bucket_receipt_per_run",
        "native_job_requires_selected_bucket",
        "native_sync_job_idempotency_is_scoped",
        "native_checkpoint_sequence_is_monotonic",
        "source_version_evidence_is_idempotent",
        "source_version_observation_is_idempotent",
        "source_membership_version_is_idempotent",
        "native_simulation_receipt_state_is_terminal",
        "one_receipt_per_native_simulation",
        "one_native_live_gate_per_bucket",
    }
)

APPEND_ONLY_TABLES = frozenset(
    {
        "source_version_evidence",
        "native_bridge_observations",
        "native_discovery_snapshots",
        "native_configuration_revisions",
        "native_configuration_buckets",
        "native_sync_runs",
        "native_bucket_runs",
        "native_checkpoints",
        "source_observations",
        "source_memberships",
        "native_watcher_simulations",
        "native_simulation_receipts",
        "native_live_activation_gates",
    }
)

REQUIRED_TRIGGERS = frozenset(
    {f"{table}_is_append_only" for table in APPEND_ONLY_TABLES}
    | {
        "native_checkpoint_requires_current_predecessor",
        "native_simulation_requires_closed_transition",
        "native_configuration_requires_bucket",
        "native_configuration_bucket_matches_seal",
        "source_observation_requires_matching_version",
        "source_membership_requires_matching_contact_version",
        "source_evidence_requires_matching_object_kind",
        "native_account_requires_matching_provider",
        "native_bucket_requires_account_and_parent_scope",
        "native_bucket_run_requires_selected_bucket",
        "native_simulation_receipt_requires_exact_evidence",
        "native_run_requires_exact_frozen_inputs",
        "native_job_requires_exact_frozen_run",
        "native_checkpoint_requires_admitted_page",
    }
)


def _id(prefix: str, ordinal: int) -> str:
    return f"{prefix}_{ordinal:016d}"


def _config() -> Config:
    return Config(str(ROOT / "alembic.ini"))


def _migration_path() -> Path:
    return next((ROOT / "migrations" / "versions").glob(f"*_{REVISION}_*.py"))


def test_revision_remains_frozen_below_the_single_wp12c_head() -> None:
    script = ScriptDirectory.from_config(_config())
    assert script.get_heads() == [HEAD_REVISION]
    revision = script.get_revision(REVISION)
    assert revision.down_revision == PRIOR_REVISION

    tree = ast.parse(_migration_path().read_text())
    imported_modules = {
        node.module
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.module is not None
    }
    assert not any(module.startswith("my_pa.domain") for module in imported_modules)
    assert "my_pa.infrastructure.persistence.tables" not in imported_modules


def test_declared_tables_match_the_frozen_revision_and_live_activation_is_absent() -> None:
    declared = {name.removeprefix("knowledge.") for name in METADATA.tables}
    assert declared >= EXPECTED_TABLES

    migration = _migration_path().read_text()
    created = set(__import__("re").findall(r"CREATE TABLE knowledge\.([a-z_]+)", migration))
    assert created == EXPECTED_TABLES
    assert "CREATE TABLE knowledge.native_live_attestations" not in migration
    assert "CREATE TABLE knowledge.native_authoritative_registrations" not in migration
    assert "CREATE TABLE knowledge.native_activation_receipts" not in migration
    assert "'watching'" not in migration
    assert "'simulation_complete', 'simulation_failed'" in migration


@pytest.fixture
def native_engine(monkeypatch: pytest.MonkeyPatch) -> Iterator[Engine]:
    configured = make_url(load_settings().database_url)
    maintenance = create_database_engine(
        configured.set(database="postgres").render_as_string(hide_password=False)
    )
    drop = text(f'DROP DATABASE IF EXISTS "{DATABASE}" WITH (FORCE)')
    with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
        connection.execute(drop)
        connection.execute(text(f'CREATE DATABASE "{DATABASE}"'))
    url = configured.set(database=DATABASE).render_as_string(hide_password=False)
    monkeypatch.setenv(f"{ENV_PREFIX}DATABASE_URL", url)
    engine = create_database_engine(url)
    try:
        command.upgrade(_config(), "head")
        yield engine
    finally:
        engine.dispose()
        with maintenance.connect().execution_options(isolation_level="AUTOCOMMIT") as connection:
            connection.execute(drop)
        maintenance.dispose()


@pytest.mark.database
def test_central_declarations_match_applied_columns_constraints_indexes_and_triggers(
    native_engine: Engine,
) -> None:
    inspector = inspect(native_engine)
    for table_name in EXPECTED_TABLES:
        declared = METADATA.tables[f"knowledge.{table_name}"]
        declared_columns = tuple(column.name for column in declared.columns)
        applied_columns = tuple(
            str(column["name"]) for column in inspector.get_columns(table_name, schema="knowledge")
        )
        assert applied_columns == declared_columns, table_name

    declared_constraints = {
        str(constraint.name)
        for table_name in EXPECTED_TABLES
        for constraint in METADATA.tables[f"knowledge.{table_name}"].constraints
        if constraint.name is not None
    }
    assert declared_constraints >= REQUIRED_NAMED_CONSTRAINTS
    with native_engine.connect() as connection:
        applied_constraints = set(
            connection.execute(
                text(
                    "SELECT con.conname FROM pg_constraint con "
                    "JOIN pg_namespace n ON n.oid = con.connamespace "
                    "WHERE n.nspname = 'knowledge'"
                )
            ).scalars()
        )
        applied_indexes = set(
            connection.execute(
                text("SELECT indexname FROM pg_indexes WHERE schemaname = 'knowledge'")
            ).scalars()
        )
        trigger_rows = tuple(
            connection.execute(
                text(
                    "SELECT relation.relname, trigger.tgname FROM pg_trigger trigger "
                    "JOIN pg_class relation ON relation.oid = trigger.tgrelid "
                    "JOIN pg_namespace namespace ON namespace.oid = relation.relnamespace "
                    "WHERE namespace.nspname = 'knowledge' AND NOT trigger.tgisinternal"
                )
            )
        )
        applied_triggers = {
            str(row.tgname) for row in trigger_rows if str(row.relname) in EXPECTED_TABLES
        }
    assert applied_constraints >= REQUIRED_NAMED_CONSTRAINTS
    assert "one_active_native_lease_per_bucket_range" in applied_indexes
    assert applied_triggers == REQUIRED_TRIGGERS


def _seed(connection: Connection) -> None:
    values = {
        "source_id": _id("src", 1),
        "object_id": _id("obj", 1),
        "version_id": _id("ver", 1),
        "bridge_id": _id("nbrg", 1),
        "account_id": _id("nacct", 1),
        "bucket_id": _id("nbkt", 1),
        "root": "synthetic-root",
        "object_locator": "synthetic-object",
        "account_locator": "synthetic-account",
        "bucket_locator": "synthetic-bucket",
        "principal_id": CONTEXT.capture_principal_id,
        "at": WHEN,
    }
    statements = (
        """INSERT INTO knowledge.sources
             (source_id, provider_kind, label, classification, native_root)
           VALUES (:source_id, 'apple_mail', 'Synthetic Mail', 'synthetic_test', :root)""",
        """INSERT INTO knowledge.source_objects
             (source_object_id, source_id, kind, native_locator)
           VALUES (:object_id, :source_id, 'mail_message', :object_locator)""",
        """INSERT INTO knowledge.source_object_versions
             (version_id, source_object_id, fingerprint, media_type, size_bytes, modified_at)
           VALUES (:version_id, :object_id, 'synthetic-v1', 'message/rfc822', 4, :at)""",
        """INSERT INTO knowledge.native_bridges
             (bridge_id, protocol_version, label, created_at, principal_id)
           VALUES (:bridge_id, 'my-pa.native-source.v1', 'Synthetic Bridge', :at,
                   :principal_id)""",
        """INSERT INTO knowledge.native_source_accounts
             (account_id, bridge_id, source_id, source_kind, label, private_locator,
              first_observed_at, principal_id)
           VALUES (:account_id, :bridge_id, :source_id, 'mail', 'Synthetic Account',
                   :account_locator, :at, :principal_id)""",
        """INSERT INTO knowledge.native_source_buckets
             (bucket_id, account_id, source_kind, label, private_locator, selectable,
              first_observed_at, principal_id)
           VALUES (:bucket_id, :account_id, 'mail', 'Synthetic Inbox', :bucket_locator,
                   true, :at, :principal_id)""",
    )
    for statement in statements:
        connection.execute(text(statement), values)
    configuration = NativeConfigurationRevision(
        configuration_id=_id("ncfg", 1),
        revision=1,
        bridge_id=_id("nbrg", 1),
        timezone_name="America/New_York",
        start_date=date(2026, 3, 8),
        cutoff_at=WHEN,
        selection=ExactBucketSelection((_id("nbkt", 1),)),
        created_at=WHEN,
    )
    SqlNativeSourceRepository(connection, CONTEXT).append_configuration(configuration)


@pytest.mark.database
def test_evidence_is_idempotent_and_receipts_are_append_only(native_engine: Engine) -> None:
    with native_engine.begin() as connection:
        # This WP-12B repository test exercises the historical compare-and-set
        # primitive in isolation. WP-12E's admitted-page trigger has its own
        # end-to-end coverage in test_wp12_slice_c_admission.py.
        connection.execute(
            text(
                "ALTER TABLE knowledge.native_checkpoints "
                "DISABLE TRIGGER native_checkpoint_requires_admitted_page"
            )
        )
        _seed(connection)
        repository = SqlNativeSourceRepository(connection, CONTEXT)
        first = repository.record_evidence(
            version_id=_id("ver", 1),
            kind=ObjectKind.MAIL_MESSAGE,
            payload=b"test",
            recorded_at=WHEN,
        )
        second = repository.record_evidence(
            version_id=_id("ver", 1),
            kind=ObjectKind.MAIL_MESSAGE,
            payload=b"test",
            recorded_at=WHEN + timedelta(seconds=1),
        )
        assert first == second

        cursor = "synthetic-cursor-1"
        checkpoint = NativeCheckpoint(
            _id("ncp", 1),
            _id("nbkt", 1),
            1,
            None,
            sha256(cursor.encode()).hexdigest(),
            WHEN,
        )
        repository.compare_and_set_checkpoint(
            checkpoint, expected_sequence=0, cursor_private=cursor
        )
        with pytest.raises(CheckpointConflictError):
            repository.compare_and_set_checkpoint(
                checkpoint, expected_sequence=0, cursor_private=cursor
            )

        pending = WatcherSimulation(
            _id("nsim", 1),
            _id("nbkt", 1),
            WatcherSimulationState.PENDING,
            1,
            WHEN,
        )
        running = pending.transition(WatcherSimulationState.RUNNING, at=WHEN + timedelta(seconds=1))
        complete = running.transition(
            WatcherSimulationState.COMPLETE, at=WHEN + timedelta(seconds=2)
        )
        for simulation in (pending, running, complete):
            repository.append_simulation(simulation)
        failed_pending = WatcherSimulation(
            _id("nsim", 2),
            _id("nbkt", 1),
            WatcherSimulationState.PENDING,
            1,
            WHEN,
        )
        failed_running = failed_pending.transition(
            WatcherSimulationState.RUNNING, at=WHEN + timedelta(seconds=1)
        )
        failed = failed_running.transition(
            WatcherSimulationState.FAILED, at=WHEN + timedelta(seconds=2)
        )
        for simulation in (failed_pending, failed_running, failed):
            repository.append_simulation(simulation)

        invalid_simulations = (
            WatcherSimulation(
                _id("nsim", 3),
                _id("nbkt", 1),
                WatcherSimulationState.RUNNING,
                1,
                WHEN,
            ),
            WatcherSimulation(
                complete.simulation_id,
                complete.bucket_id,
                WatcherSimulationState.PENDING,
                complete.sequence + 1,
                WHEN + timedelta(seconds=3),
            ),
        )
        for invalid in invalid_simulations:
            invalid_savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError):
                repository.append_simulation(invalid)
            invalid_savepoint.rollback()

        skipped_pending = WatcherSimulation(
            _id("nsim", 4),
            _id("nbkt", 1),
            WatcherSimulationState.PENDING,
            1,
            WHEN,
        )
        repository.append_simulation(skipped_pending)
        skipped_savepoint = connection.begin_nested()
        with pytest.raises(DBAPIError):
            repository.append_simulation(
                WatcherSimulation(
                    skipped_pending.simulation_id,
                    skipped_pending.bucket_id,
                    WatcherSimulationState.COMPLETE,
                    2,
                    WHEN + timedelta(seconds=1),
                )
            )
        skipped_savepoint.rollback()

        state_mismatch = connection.begin_nested()
        with pytest.raises(DBAPIError, match="state contradicts its simulation"):
            connection.execute(
                text(
                    """INSERT INTO knowledge.native_simulation_receipts
                         (receipt_id, simulation_id, simulation_sequence, checkpoint_id,
                          terminal_state, recorded_at)
                       VALUES (:receipt_id, :simulation_id, :sequence, :checkpoint_id,
                               'simulation_failed', :at)"""
                ),
                {
                    "receipt_id": _id("nsimr", 20),
                    "simulation_id": complete.simulation_id,
                    "sequence": complete.sequence,
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "at": WHEN,
                },
            )
        state_mismatch.rollback()

        connection.execute(
            text(
                """INSERT INTO knowledge.native_source_buckets
                     (principal_id, bucket_id, account_id, source_kind, label, private_locator,
                      selectable, first_observed_at)
                   VALUES (:principal_id, :bucket_id, :account_id, 'mail', 'Other Mailbox',
                           'other-simulation-bucket', true, :at)"""
            ),
            {
                "principal_id": CONTEXT.capture_principal_id,
                "bucket_id": _id("nbkt", 2),
                "account_id": _id("nacct", 1),
                "at": WHEN,
            },
        )
        other_cursor = "synthetic-cursor-other-bucket"
        other_checkpoint = NativeCheckpoint(
            _id("ncp", 2),
            _id("nbkt", 2),
            1,
            None,
            sha256(other_cursor.encode()).hexdigest(),
            WHEN,
        )
        repository.compare_and_set_checkpoint(
            other_checkpoint, expected_sequence=0, cursor_private=other_cursor
        )
        bucket_mismatch = connection.begin_nested()
        with pytest.raises(DBAPIError, match="checkpoint is outside its bucket"):
            connection.execute(
                text(
                    """INSERT INTO knowledge.native_simulation_receipts
                         (receipt_id, simulation_id, simulation_sequence, checkpoint_id,
                          terminal_state, recorded_at)
                       VALUES (:receipt_id, :simulation_id, :sequence, :checkpoint_id,
                               'simulation_complete', :at)"""
                ),
                {
                    "receipt_id": _id("nsimr", 21),
                    "simulation_id": complete.simulation_id,
                    "sequence": complete.sequence,
                    "checkpoint_id": other_checkpoint.checkpoint_id,
                    "at": WHEN,
                },
            )
        bucket_mismatch.rollback()
        repository.append_simulation_receipt(
            SimulationReceipt(
                _id("nsimr", 1),
                pending.simulation_id,
                WatcherSimulationState.COMPLETE,
                checkpoint.checkpoint_id,
                WHEN + timedelta(seconds=2),
            ),
            simulation_sequence=complete.sequence,
        )
        repository.record_live_gate(
            LiveActivationGate(
                _id("nlg", 1),
                _id("nbkt", 1),
                LiveActivationGateState.NOT_AUTHORIZED,
                WHEN,
            ),
            reason_code="slice_b_has_no_live_writer",
        )

        checkpoint_savepoint = connection.begin_nested()
        with pytest.raises(DBAPIError):
            connection.execute(
                update(native_checkpoints)
                .where(native_checkpoints.c.checkpoint_id == checkpoint.checkpoint_id)
                .values(cursor_digest="f" * 64)
            )
        checkpoint_savepoint.rollback()
        configuration_savepoint = connection.begin_nested()
        with pytest.raises(DBAPIError):
            connection.execute(
                update(native_configuration_revisions)
                .where(native_configuration_revisions.c.configuration_id == _id("ncfg", 1))
                .values(timezone_name="UTC")
            )
        configuration_savepoint.rollback()
        connection.execute(
            text(
                "ALTER TABLE knowledge.native_checkpoints "
                "ENABLE TRIGGER native_checkpoint_requires_admitted_page"
            )
        )


@pytest.mark.database
def test_shared_source_version_evidence_is_idempotent_per_principal(
    native_engine: Engine,
) -> None:
    with native_engine.begin() as connection:
        _seed(connection)
        first = SqlNativeSourceRepository(connection, CONTEXT).record_evidence(
            version_id=_id("ver", 1),
            kind=ObjectKind.MAIL_MESSAGE,
            payload=b"same-evidence",
            recorded_at=WHEN,
        )
        second = SqlNativeSourceRepository(connection, OTHER_CONTEXT).record_evidence(
            version_id=_id("ver", 1),
            kind=ObjectKind.MAIL_MESSAGE,
            payload=b"same-evidence",
            recorded_at=WHEN,
        )
        replay = SqlNativeSourceRepository(connection, OTHER_CONTEXT).record_evidence(
            version_id=_id("ver", 1),
            kind=ObjectKind.MAIL_MESSAGE,
            payload=b"same-evidence",
            recorded_at=WHEN + timedelta(seconds=1),
        )
        assert first != second == replay
        principals = tuple(
            connection.execute(
                text(
                    "SELECT principal_id FROM knowledge.source_version_evidence "
                    "WHERE version_id = :version_id ORDER BY principal_id"
                ),
                {"version_id": _id("ver", 1)},
            ).scalars()
        )
        assert principals == (
            CONTEXT.capture_principal_id,
            OTHER_CONTEXT.capture_principal_id,
        )


@pytest.mark.database
def test_ac_005_account_identity_survives_rename_and_source_rebind_is_refused(
    native_engine: Engine,
) -> None:
    with native_engine.begin() as connection:
        _seed(connection)
        repository = SqlNativeSourceRepository(connection, CONTEXT)
        reobserved = NativeSourceAccount(
            _id("nacct", 2),
            _id("nbrg", 1),
            _id("src", 1),
            NativeSourceKind.MAIL,
            "Synthetic Account",
            WHEN + timedelta(minutes=1),
        )
        assert repository.register_account(reobserved, private_locator="synthetic-account") == _id(
            "nacct", 1
        )
        renamed = NativeSourceAccount(
            _id("nacct", 3),
            _id("nbrg", 1),
            _id("src", 1),
            NativeSourceKind.MAIL,
            "Changed Label",
            WHEN + timedelta(minutes=2),
        )
        assert repository.register_account(renamed, private_locator="synthetic-account") == _id(
            "nacct", 1
        )
        stored = connection.execute(
            text(
                "SELECT account_id, label FROM knowledge.native_source_accounts "
                "WHERE private_locator = :locator"
            ),
            {"locator": "synthetic-account"},
        ).one()
        assert tuple(stored) == (_id("nacct", 1), "Changed Label")

        connection.execute(
            text(
                """INSERT INTO knowledge.sources
                     (source_id, provider_kind, label, classification, native_root)
                   VALUES (:source_id, 'apple_mail', 'Other Synthetic Mail',
                           'synthetic_test', 'other-synthetic-root')"""
            ),
            {"source_id": _id("src", 3)},
        )
        with pytest.raises(NativePersistenceConflictError, match="cannot be rebound"):
            repository.register_account(
                NativeSourceAccount(
                    _id("nacct", 4),
                    _id("nbrg", 1),
                    _id("src", 3),
                    NativeSourceKind.MAIL,
                    "Other Account",
                    WHEN + timedelta(minutes=3),
                ),
                private_locator="synthetic-account",
            )
        rebind = connection.begin_nested()
        with pytest.raises(DBAPIError, match="authority scope is immutable"):
            connection.execute(
                text(
                    "UPDATE knowledge.native_source_accounts SET source_id = :source_id "
                    "WHERE account_id = :account_id"
                ),
                {"source_id": _id("src", 3), "account_id": _id("nacct", 1)},
            )
        rebind.rollback()


@pytest.mark.database
def test_ac_007_future_bucket_is_denied_by_the_immutable_exact_selection(
    native_engine: Engine,
) -> None:
    with native_engine.begin() as connection:
        _seed(connection)
        connection.execute(
            text(
                """INSERT INTO knowledge.native_source_buckets
                     (principal_id, bucket_id, account_id, source_kind, label, private_locator,
                      selectable, first_observed_at)
                   VALUES (:principal_id, :bucket_id, :account_id, 'mail',
                           'Future Mailbox', :locator, true, :at)"""
            ),
            {
                "bucket_id": _id("nbkt", 2),
                "account_id": _id("nacct", 1),
                "locator": "future-synthetic-bucket",
                "principal_id": CONTEXT.capture_principal_id,
                "at": WHEN + timedelta(minutes=1),
            },
        )
        selected = tuple(
            connection.execute(
                text(
                    "SELECT bucket_id FROM knowledge.native_configuration_buckets "
                    "WHERE configuration_id = :configuration_id AND revision = 1 "
                    "ORDER BY bucket_id"
                ),
                {"configuration_id": _id("ncfg", 1)},
            ).scalars()
        )
        assert selected == (_id("nbkt", 1),)
        assert _id("nbkt", 2) not in selected

        late_selection = connection.begin_nested()
        with pytest.raises(DBAPIError, match="does not match its immutable seal"):
            connection.execute(
                text(
                    "INSERT INTO knowledge.native_configuration_buckets "
                    "(principal_id, configuration_id, revision, bucket_id) "
                    "VALUES (:principal_id, :configuration_id, 1, :bucket_id)"
                ),
                {
                    "principal_id": CONTEXT.capture_principal_id,
                    "configuration_id": _id("ncfg", 1),
                    "bucket_id": _id("nbkt", 2),
                },
            )
            connection.execute(text("SET CONSTRAINTS ALL IMMEDIATE"))
        late_selection.rollback()

        unselected_job = connection.begin_nested()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """INSERT INTO knowledge.native_sync_jobs
                         (principal_id, job_id, configuration_id, configuration_revision, bucket_id,
                          range_start, range_end, state, idempotency_key, created_at, updated_at)
                       VALUES (:principal_id, :job_id, :configuration_id, 1, :bucket_id,
                               :start_at, :cutoff_at, 'queued', 'unselected-job', :at, :at)"""
                ),
                {
                    "job_id": _id("njob", 20),
                    "configuration_id": _id("ncfg", 1),
                    "bucket_id": _id("nbkt", 2),
                    "start_at": WHEN - timedelta(days=1),
                    "cutoff_at": WHEN,
                    "at": WHEN,
                    "principal_id": CONTEXT.capture_principal_id,
                },
            )
        unselected_job.rollback()

        run = NativeRun(
            _id("nrun", 20),
            _id("ncfg", 1),
            1,
            _id("nbrg", 1),
            "synthetic-v1",
            NativeRunKind.BASELINE,
            NativeRunState.SUCCEEDED,
            datetime(2026, 3, 8, 5, tzinfo=UTC),
            WHEN,
            WHEN + timedelta(days=90),
            WHEN,
        )
        SqlNativeSourceRepository(connection, CONTEXT).append_run(
            run, idempotency_key="run-for-selection"
        )
        unselected_bucket_run = connection.begin_nested()
        with pytest.raises(DBAPIError, match="outside its exact configuration selection"):
            connection.execute(
                text(
                    """INSERT INTO knowledge.native_bucket_runs
                         (principal_id, bucket_run_id, run_id, bucket_id, state, item_count,
                          recorded_at)
                       VALUES (:principal_id, :bucket_run_id, :run_id, :bucket_id,
                               'succeeded', 0, :at)"""
                ),
                {
                    "bucket_run_id": _id("nbrun", 20),
                    "run_id": run.run_id,
                    "bucket_id": _id("nbkt", 2),
                    "at": WHEN,
                    "principal_id": CONTEXT.capture_principal_id,
                },
            )
        unselected_bucket_run.rollback()


def _seed_contacts(connection: Connection) -> None:
    values = {
        "source_id": _id("src", 2),
        "object_id": _id("obj", 2),
        "version_id": _id("ver", 2),
        "bridge_id": _id("nbrg", 1),
        "account_id": _id("nacct", 2),
        "bucket_id_1": _id("nbkt", 3),
        "bucket_id_2": _id("nbkt", 4),
        "principal_id": CONTEXT.capture_principal_id,
        "at": WHEN,
    }
    statements = (
        """INSERT INTO knowledge.sources
             (source_id, provider_kind, label, classification, native_root)
           VALUES (:source_id, 'apple_contacts', 'Synthetic Contacts',
                   'synthetic_test', 'synthetic-contacts-root')""",
        """INSERT INTO knowledge.source_objects
             (source_object_id, source_id, kind, native_locator)
           VALUES (:object_id, :source_id, 'contact', 'synthetic-contact')""",
        """INSERT INTO knowledge.source_object_versions
             (version_id, source_object_id, fingerprint, media_type, size_bytes, modified_at)
           VALUES (:version_id, :object_id, 'synthetic-contact-v1', 'text/vcard', 4, :at)""",
        """INSERT INTO knowledge.native_source_accounts
             (principal_id, account_id, bridge_id, source_id, source_kind, label, private_locator,
              first_observed_at)
           VALUES (:principal_id, :account_id, :bridge_id, :source_id, 'contacts',
                   'Synthetic Contacts', 'synthetic-contacts-account', :at)""",
        """INSERT INTO knowledge.native_source_buckets
             (principal_id, bucket_id, account_id, source_kind, label, private_locator, selectable,
              first_observed_at)
           VALUES (:principal_id, :bucket_id_1, :account_id, 'contacts', 'Friends',
                   'contacts-friends', true, :at)""",
        """INSERT INTO knowledge.native_source_buckets
             (principal_id, bucket_id, account_id, source_kind, label, private_locator, selectable,
              first_observed_at)
           VALUES (:principal_id, :bucket_id_2, :account_id, 'contacts', 'Vendors',
                   'contacts-vendors', true, :at)""",
    )
    for statement in statements:
        connection.execute(text(statement), values)


@pytest.mark.database
def test_ac_015_memberships_preserve_multi_container_cardinality_and_source_scope(
    native_engine: Engine,
) -> None:
    with native_engine.begin() as connection:
        _seed(connection)
        _seed_contacts(connection)
        repository = SqlNativeSourceRepository(connection, CONTEXT)
        friends = ContactMembership(
            _id("smem", 1), _id("nbkt", 3), _id("obj", 2), _id("ver", 2), WHEN
        )
        vendors = ContactMembership(
            _id("smem", 2), _id("nbkt", 4), _id("obj", 2), _id("ver", 2), WHEN
        )
        assert repository.record_membership(friends) == friends.membership_id
        assert repository.record_membership(vendors) == vendors.membership_id
        duplicate = ContactMembership(
            _id("smem", 3), _id("nbkt", 3), _id("obj", 2), _id("ver", 2), WHEN
        )
        assert repository.record_membership(duplicate) == friends.membership_id
        count = connection.execute(
            text(
                "SELECT count(*) FROM knowledge.source_memberships "
                "WHERE source_object_id = :object_id AND version_id = :version_id"
            ),
            {"object_id": _id("obj", 2), "version_id": _id("ver", 2)},
        ).scalar_one()
        assert count == 2

        cross_source_statements = (
            (
                """INSERT INTO knowledge.source_observations
                     (principal_id, observation_id, source_object_id, version_id, bucket_id,
                      observed_at)
                   VALUES (:principal_id, :identifier, :object_id, :version_id, :bucket_id, :at)""",
                _id("sobs", 10),
            ),
            (
                """INSERT INTO knowledge.source_memberships
                     (principal_id, membership_id, parent_bucket_id, source_object_id, version_id,
                      observed_at)
                   VALUES (:principal_id, :identifier, :bucket_id, :object_id, :version_id, :at)""",
                _id("smem", 10),
            ),
        )
        for statement, identifier in cross_source_statements:
            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError, match="outside the selected account scope"):
                connection.execute(
                    text(statement),
                    {
                        "identifier": identifier,
                        "object_id": _id("obj", 1),
                        "version_id": _id("ver", 1),
                        "bucket_id": _id("nbkt", 3),
                        "at": WHEN,
                        "principal_id": CONTEXT.capture_principal_id,
                    },
                )
            savepoint.rollback()


@pytest.mark.database
def test_authoritative_source_account_bucket_and_evidence_kinds_cannot_diverge(
    native_engine: Engine,
) -> None:
    with native_engine.begin() as connection:
        _seed(connection)
        _seed_contacts(connection)
        plants = (
            (
                """INSERT INTO knowledge.source_version_evidence
                     (principal_id, evidence_id, version_id, evidence_kind, payload, payload_sha256,
                      byte_count, recorded_at)
                   VALUES (:principal_id, :identifier, :version_id, 'contact', 'test', :digest,
                           4, :at)""",
                {
                    "identifier": _id("sevd", 20),
                    "version_id": _id("ver", 1),
                    "digest": sha256(b"test").hexdigest(),
                    "at": WHEN,
                    "principal_id": CONTEXT.capture_principal_id,
                },
                "does not match its authoritative object",
            ),
            (
                """INSERT INTO knowledge.native_source_accounts
                     (principal_id, account_id, bridge_id, source_id, source_kind, label,
                      private_locator, first_observed_at)
                   VALUES (:principal_id, :identifier, :bridge_id, :source_id, 'contacts',
                           'Wrong Kind', 'wrong-kind-account', :at)""",
                {
                    "identifier": _id("nacct", 20),
                    "bridge_id": _id("nbrg", 1),
                    "source_id": _id("src", 1),
                    "at": WHEN,
                    "principal_id": CONTEXT.capture_principal_id,
                },
                "does not match its authoritative source",
            ),
            (
                """INSERT INTO knowledge.native_source_buckets
                     (principal_id, bucket_id, account_id, source_kind, label, private_locator,
                      selectable, first_observed_at)
                   VALUES (:principal_id, :identifier, :account_id, 'contacts', 'Wrong Kind',
                           'wrong-kind-bucket', true, :at)""",
                {
                    "identifier": _id("nbkt", 20),
                    "account_id": _id("nacct", 1),
                    "at": WHEN,
                    "principal_id": CONTEXT.capture_principal_id,
                },
                "does not match its account",
            ),
            (
                """INSERT INTO knowledge.native_source_buckets
                     (principal_id, bucket_id, account_id, parent_bucket_id, source_kind, label,
                      private_locator, selectable, first_observed_at)
                   VALUES (:principal_id, :identifier, :account_id, :parent_bucket_id, 'mail',
                           'Wrong Parent', 'wrong-parent-bucket', true, :at)""",
                {
                    "identifier": _id("nbkt", 21),
                    "account_id": _id("nacct", 1),
                    "parent_bucket_id": _id("nbkt", 3),
                    "at": WHEN,
                    "principal_id": CONTEXT.capture_principal_id,
                },
                "outside its parent scope",
            ),
        )
        for statement, values, message in plants:
            savepoint = connection.begin_nested()
            with pytest.raises(DBAPIError, match=message):
                connection.execute(text(statement), values)
            savepoint.rollback()


@pytest.mark.database
def test_native_job_idempotency_and_one_active_range(native_engine: Engine) -> None:
    with native_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE knowledge.native_sync_jobs "
                "DISABLE TRIGGER native_job_requires_exact_frozen_run"
            )
        )
        _seed(connection)
        repository = SqlNativeSourceRepository(connection, CONTEXT)

        def enqueue(ordinal: int, key: str) -> str:
            return repository.enqueue_job(
                job_id=_id("njob", ordinal),
                configuration_id=_id("ncfg", 1),
                configuration_revision=1,
                bucket_id=_id("nbkt", 1),
                range_start=WHEN - timedelta(days=1),
                range_end=WHEN,
                idempotency_key=key,
                created_at=WHEN,
            )

        first = enqueue(1, "baseline-1")
        repeated = enqueue(2, "baseline-1")
        assert first == repeated == _id("njob", 1)
        enqueue(3, "baseline-2")

        connection.execute(
            text(
                """UPDATE knowledge.native_sync_jobs
                   SET state = 'running', lease_owner = 'synthetic-worker-1',
                       lease_expires_at = :lease_expires_at, updated_at = :updated_at
                   WHERE job_id = :job_id"""
            ),
            {
                "job_id": _id("njob", 1),
                "lease_expires_at": WHEN + timedelta(minutes=5),
                "updated_at": WHEN,
            },
        )
        claim_savepoint = connection.begin_nested()
        with pytest.raises(IntegrityError):
            connection.execute(
                text(
                    """UPDATE knowledge.native_sync_jobs
                       SET state = 'running', lease_owner = 'synthetic-worker-2',
                           lease_expires_at = :lease_expires_at, updated_at = :updated_at
                       WHERE job_id = :job_id"""
                ),
                {
                    "job_id": _id("njob", 3),
                    "lease_expires_at": WHEN + timedelta(minutes=5),
                    "updated_at": WHEN,
                },
            )
        claim_savepoint.rollback()
        connection.execute(
            text(
                "ALTER TABLE knowledge.native_sync_jobs "
                "ENABLE TRIGGER native_job_requires_exact_frozen_run"
            )
        )


@pytest.mark.database
def test_native_run_idempotency_replays_exact_inputs_and_rejects_every_mismatch(
    native_engine: Engine,
) -> None:
    with native_engine.begin() as connection:
        _seed(connection)
        repository = SqlNativeSourceRepository(connection, CONTEXT)
        run = NativeRun(
            _id("nrun", 1),
            _id("ncfg", 1),
            1,
            _id("nbrg", 1),
            "synthetic-v1",
            NativeRunKind.BASELINE,
            NativeRunState.SUCCEEDED,
            datetime(2026, 3, 8, 5, tzinfo=UTC),
            WHEN,
            WHEN + timedelta(days=90),
            WHEN,
        )
        assert repository.append_run(run, idempotency_key="run-replay") == run.run_id
        assert (
            repository.append_run(replace(run, run_id=_id("nrun", 2)), idempotency_key="run-replay")
            == run.run_id
        )

        mismatches = (
            replace(run, run_id=_id("nrun", 3), kind=NativeRunKind.BACKFILL),
            replace(run, run_id=_id("nrun", 4), state=NativeRunState.FAILED),
            replace(
                run,
                run_id=_id("nrun", 6),
                cutoff_at=run.cutoff_at + timedelta(days=1),
                calendar_horizon_at=run.calendar_horizon_at + timedelta(days=1),
            ),
            replace(run, run_id=_id("nrun", 7), recorded_at=run.recorded_at + timedelta(seconds=1)),
        )
        for mismatch in mismatches:
            with pytest.raises(NativePersistenceConflictError, match="different immutable work"):
                repository.append_run(mismatch, idempotency_key="run-replay")
        with pytest.raises(DBAPIError, match="exact configuration inputs"):
            repository.append_run(
                replace(run, run_id=_id("nrun", 5), start_at=run.start_at + timedelta(hours=1)),
                idempotency_key="run-replay",
            )


@pytest.mark.database
def test_checkpoint_compare_and_set_serializes_concurrent_writers(
    native_engine: Engine,
) -> None:
    with native_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE knowledge.native_checkpoints "
                "DISABLE TRIGGER native_checkpoint_requires_admitted_page"
            )
        )
        _seed(connection)

    barrier = Barrier(2)

    def contender(ordinal: int) -> str:
        cursor = f"synthetic-cursor-{ordinal}"
        checkpoint = NativeCheckpoint(
            _id("ncp", ordinal),
            _id("nbkt", 1),
            1,
            None,
            sha256(cursor.encode()).hexdigest(),
            WHEN,
        )
        barrier.wait()
        try:
            with native_engine.begin() as connection:
                SqlNativeSourceRepository(connection, CONTEXT).compare_and_set_checkpoint(
                    checkpoint,
                    expected_sequence=0,
                    cursor_private=cursor,
                )
            return "committed"
        except CheckpointConflictError:
            return "conflict"

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = sorted(pool.map(contender, (1, 2)))
    assert results == ["committed", "conflict"]
    with native_engine.connect() as connection:
        stored = tuple(connection.execute(select(native_checkpoints.c.checkpoint_id)).scalars())
        assert stored in ((_id("ncp", 1),), (_id("ncp", 2),))
    with native_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE knowledge.native_checkpoints "
                "ENABLE TRIGGER native_checkpoint_requires_admitted_page"
            )
        )


@pytest.mark.database
def test_revision_round_trips_from_prior_head(native_engine: Engine) -> None:
    command.downgrade(_config(), PRIOR_REVISION)
    with native_engine.connect() as connection:
        before = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'knowledge'"
                )
            ).scalars()
        )
    assert before.isdisjoint(EXPECTED_TABLES)

    command.upgrade(_config(), REVISION)
    with native_engine.connect() as connection:
        after = set(
            connection.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'knowledge'"
                )
            ).scalars()
        )
    assert after - before == EXPECTED_TABLES


@pytest.mark.database
def test_native_partition_upgrades_an_empty_prior_head(native_engine: Engine) -> None:
    command.downgrade(_config(), "b4e8d2c7a613")
    command.upgrade(_config(), HEAD_REVISION)
    columns = inspect(native_engine).get_columns("native_bridges", schema="knowledge")
    principal = next(column for column in columns if column["name"] == "principal_id")
    assert principal["nullable"] is False


@pytest.mark.database
def test_native_partition_refuses_populated_prior_without_partial_ddl(
    native_engine: Engine,
) -> None:
    command.downgrade(_config(), "b4e8d2c7a613")
    with native_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.native_bridges "
                "(bridge_id, protocol_version, label, created_at) VALUES "
                "('nbrg_0123456789abcdef', '1', 'synthetic', :at)"
            ),
            {"at": WHEN},
        )
    with pytest.raises(DBAPIError, match="cannot infer Principal"):
        command.upgrade(_config(), HEAD_REVISION)
    assert "principal_id" not in {
        column["name"]
        for column in inspect(native_engine).get_columns("native_bridges", schema="knowledge")
    }


@pytest.mark.database
def test_native_partition_fk_refuses_a_cross_principal_bridge_link(
    native_engine: Engine,
) -> None:
    with native_engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO knowledge.sources "
                "(source_id, provider_kind, label, classification, native_root) VALUES "
                "('src_0123456789abcdef', 'apple_mail', 'synthetic', 'private_local', '/synthetic')"
            )
        )
        connection.execute(
            text(
                "INSERT INTO knowledge.native_bridges "
                "(bridge_id, protocol_version, label, created_at, principal_id) VALUES "
                "('nbrg_0123456789abcdef', '1', 'synthetic', :at, 'prn_aaaaaaaaaaaaaaaa')"
            ),
            {"at": WHEN},
        )
        with pytest.raises(IntegrityError, match="native_account_bridge_stays_in_principal"):
            connection.execute(
                text(
                    "INSERT INTO knowledge.native_source_accounts "
                    "(account_id, bridge_id, source_id, source_kind, label, private_locator, "
                    "first_observed_at, principal_id) VALUES "
                    "('nacct_0123456789abcdef', 'nbrg_0123456789abcdef', "
                    "'src_0123456789abcdef', 'mail', 'synthetic', 'private', :at, "
                    "'prn_bbbbbbbbbbbbbbbb')"
                ),
                {"at": WHEN},
            )
