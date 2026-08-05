"""Persistence for native-source identities, evidence, receipts, and checkpoints.

Provider locators and cursors enter and leave only through explicitly named
methods in this module.  They are never placed in domain values or exception
messages.  The caller owns the transaction; checkpoint compare-and-set takes a
transaction-scoped advisory lock so the read and append form one serialized
operation per bucket.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import Connection, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.native_sources import (
    ContactMembership,
    LiveActivationGate,
    NativeBridge,
    NativeCheckpoint,
    NativeConfigurationRevision,
    NativeRun,
    NativeSourceAccount,
    NativeSourceBucket,
    SimulationReceipt,
    WatcherSimulation,
)
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.tables import (
    native_bridge_observations,
    native_bridges,
    native_bucket_runs,
    native_checkpoints,
    native_configuration_buckets,
    native_configuration_revisions,
    native_live_activation_gates,
    native_simulation_receipts,
    native_source_accounts,
    native_source_buckets,
    native_sync_jobs,
    native_sync_runs,
    native_watcher_simulations,
    source_memberships,
    source_observations,
    source_version_evidence,
)

__all__ = [
    "CheckpointConflictError",
    "NativeJobLease",
    "NativePersistenceConflictError",
    "SqlNativeSourceRepository",
]


class CheckpointConflictError(RuntimeError):
    """The requested checkpoint did not extend the bucket's current chain."""


class NativePersistenceConflictError(RuntimeError):
    """An idempotency key was reused for different native-source work."""


@dataclass(frozen=True, slots=True)
class NativeJobLease:
    job_id: str
    bucket_id: str
    range_start: datetime
    range_end: datetime
    lease_owner: str
    lease_expires_at: datetime


class SqlNativeSourceRepository:
    """Provider-neutral statements for the WP-12B persistence foundation."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def register_bridge(self, bridge: NativeBridge) -> str:
        statement = (
            pg_insert(native_bridges)
            .values(
                bridge_id=bridge.bridge_id,
                protocol_version=bridge.protocol_version,
                label=bridge.label,
                created_at=bridge.observed_at,
            )
            .on_conflict_do_nothing(constraint="a_native_bridge_identity_is_stable")
            .returning(native_bridges.c.bridge_id)
        )
        inserted = self._connection.execute(statement).scalar_one_or_none()
        if inserted is not None:
            return str(inserted)
        existing = self._connection.execute(
            select(native_bridges.c.bridge_id).where(
                native_bridges.c.protocol_version == bridge.protocol_version,
                native_bridges.c.label == bridge.label,
            )
        ).scalar_one_or_none()
        return str(conflicting_row(existing, "knowledge.native_bridges"))

    def record_bridge_observation(self, bridge: NativeBridge, *, available: bool) -> str:
        observation_id = issue_identifier(IdKind.SOURCE_OBSERVATION)
        self._connection.execute(
            insert(native_bridge_observations).values(
                observation_id=observation_id,
                bridge_id=bridge.bridge_id,
                available=available,
                protocol_version=bridge.protocol_version,
                observed_at=bridge.observed_at,
            )
        )
        return observation_id

    def register_account(self, account: NativeSourceAccount, *, private_locator: str) -> str:
        if not private_locator:
            raise ValueError("a native account private locator is required")
        statement = (
            pg_insert(native_source_accounts)
            .values(
                account_id=account.account_id,
                bridge_id=account.bridge_id,
                source_id=account.source_id,
                source_kind=account.kind.value,
                label=account.label,
                private_locator=private_locator,
                first_observed_at=account.observed_at,
            )
            .on_conflict_do_nothing(constraint="native_account_locator_is_issued_once")
            .returning(native_source_accounts.c.account_id)
        )
        inserted = self._connection.execute(statement).scalar_one_or_none()
        if inserted is not None:
            return str(inserted)
        existing = self._connection.execute(
            select(
                native_source_accounts.c.account_id,
                native_source_accounts.c.source_id,
                native_source_accounts.c.label,
            ).where(
                native_source_accounts.c.bridge_id == account.bridge_id,
                native_source_accounts.c.source_kind == account.kind.value,
                native_source_accounts.c.private_locator == private_locator,
            )
        ).one_or_none()
        row = conflicting_row(existing, "knowledge.native_source_accounts")
        if row.source_id != account.source_id:
            raise NativePersistenceConflictError(
                "a native account locator cannot be rebound to another source"
            )
        if row.label != account.label:
            self._connection.execute(
                update(native_source_accounts)
                .where(native_source_accounts.c.account_id == row.account_id)
                .values(label=account.label)
            )
        return str(row.account_id)

    def register_bucket(self, bucket: NativeSourceBucket, *, private_locator: str) -> str:
        if not private_locator:
            raise ValueError("a native bucket private locator is required")
        statement = (
            pg_insert(native_source_buckets)
            .values(
                bucket_id=bucket.bucket_id,
                account_id=bucket.account_id,
                parent_bucket_id=bucket.parent_bucket_id,
                source_kind=bucket.kind.value,
                label=bucket.label,
                private_locator=private_locator,
                selectable=bucket.selectable,
                first_observed_at=bucket.observed_at,
            )
            .on_conflict_do_nothing(constraint="native_bucket_locator_is_issued_once")
            .returning(native_source_buckets.c.bucket_id)
        )
        inserted = self._connection.execute(statement).scalar_one_or_none()
        if inserted is not None:
            return str(inserted)
        existing = self._connection.execute(
            select(native_source_buckets.c.bucket_id).where(
                native_source_buckets.c.account_id == bucket.account_id,
                native_source_buckets.c.private_locator == private_locator,
            )
        ).scalar_one_or_none()
        return str(conflicting_row(existing, "knowledge.native_source_buckets"))

    def resolve_bucket_locator(self, bucket_id: str) -> str:
        """Return the private provider locator; callers must not disclose it."""
        validate_identifier(bucket_id, IdKind.NATIVE_BUCKET)
        value = self._connection.execute(
            select(native_source_buckets.c.private_locator).where(
                native_source_buckets.c.bucket_id == bucket_id
            )
        ).scalar_one_or_none()
        if value is None:
            raise LookupError(f"no native source bucket {bucket_id}")
        return str(value)

    def append_configuration(self, configuration: NativeConfigurationRevision) -> None:
        self._connection.execute(
            insert(native_configuration_revisions).values(
                configuration_id=configuration.configuration_id,
                revision=configuration.revision,
                bridge_id=configuration.bridge_id,
                timezone_name=configuration.timezone_name,
                start_date=configuration.start_date,
                start_at=configuration.start_at,
                cutoff_at=configuration.cutoff_at,
                calendar_horizon_at=configuration.calendar_horizon_at,
                selection_sha256=configuration.selection_sha256,
                created_at=configuration.created_at,
            )
        )
        self._connection.execute(
            insert(native_configuration_buckets),
            [
                {
                    "configuration_id": configuration.configuration_id,
                    "revision": configuration.revision,
                    "bucket_id": bucket_id,
                }
                for bucket_id in configuration.selection.bucket_ids
            ],
        )

    def append_run(self, run: NativeRun, *, idempotency_key: str) -> str:
        if not idempotency_key:
            raise ValueError("a native run idempotency key is required")
        statement = (
            pg_insert(native_sync_runs)
            .values(
                run_id=run.run_id,
                configuration_id=run.configuration_id,
                configuration_revision=run.configuration_revision,
                run_kind=run.kind.value,
                state=run.state.value,
                start_at=run.start_at,
                cutoff_at=run.cutoff_at,
                calendar_horizon_at=run.calendar_horizon_at,
                idempotency_key=idempotency_key,
                recorded_at=run.recorded_at,
            )
            .on_conflict_do_nothing(constraint="native_sync_run_idempotency_is_scoped")
            .returning(native_sync_runs.c.run_id)
        )
        inserted = self._connection.execute(statement).scalar_one_or_none()
        if inserted is not None:
            return str(inserted)
        existing = self._connection.execute(
            select(
                native_sync_runs.c.run_id,
                native_sync_runs.c.configuration_id,
                native_sync_runs.c.configuration_revision,
                native_sync_runs.c.run_kind,
                native_sync_runs.c.state,
                native_sync_runs.c.start_at,
                native_sync_runs.c.cutoff_at,
                native_sync_runs.c.calendar_horizon_at,
                native_sync_runs.c.recorded_at,
            ).where(
                native_sync_runs.c.configuration_id == run.configuration_id,
                native_sync_runs.c.configuration_revision == run.configuration_revision,
                native_sync_runs.c.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        row = conflicting_row(existing, "knowledge.native_sync_runs")
        stored_inputs = (
            row.configuration_id,
            row.configuration_revision,
            row.run_kind,
            row.state,
            row.start_at,
            row.cutoff_at,
            row.calendar_horizon_at,
            row.recorded_at,
        )
        requested_inputs = (
            run.configuration_id,
            run.configuration_revision,
            run.kind.value,
            run.state.value,
            run.start_at,
            run.cutoff_at,
            run.calendar_horizon_at,
            run.recorded_at,
        )
        if stored_inputs != requested_inputs:
            raise NativePersistenceConflictError(
                "a native run idempotency key names different immutable work"
            )
        return str(row.run_id)

    def append_bucket_run(
        self,
        *,
        bucket_run_id: str,
        run_id: str,
        bucket_id: str,
        state: str,
        item_count: int,
        recorded_at: datetime,
    ) -> None:
        validate_identifier(bucket_run_id, IdKind.NATIVE_BUCKET_RUN)
        self._connection.execute(
            insert(native_bucket_runs).values(
                bucket_run_id=bucket_run_id,
                run_id=run_id,
                bucket_id=bucket_id,
                state=state,
                item_count=item_count,
                recorded_at=ensure_utc(recorded_at),
            )
        )

    def record_evidence(
        self,
        *,
        version_id: str,
        kind: ObjectKind,
        payload: bytes,
        recorded_at: datetime,
    ) -> str:
        validate_identifier(version_id, IdKind.VERSION)
        if kind not in {ObjectKind.MAIL_MESSAGE, ObjectKind.CALENDAR_EVENT, ObjectKind.CONTACT}:
            raise ValueError("source evidence requires a native evidence kind")
        digest = sha256(payload).hexdigest()
        statement = (
            pg_insert(source_version_evidence)
            .values(
                evidence_id=issue_identifier(IdKind.SOURCE_EVIDENCE),
                version_id=version_id,
                evidence_kind=kind.value,
                payload=payload,
                payload_sha256=digest,
                byte_count=len(payload),
                recorded_at=ensure_utc(recorded_at),
            )
            .on_conflict_do_nothing(constraint="source_version_evidence_is_idempotent")
            .returning(source_version_evidence.c.evidence_id)
        )
        inserted = self._connection.execute(statement).scalar_one_or_none()
        if inserted is not None:
            return str(inserted)
        existing = self._connection.execute(
            select(source_version_evidence.c.evidence_id).where(
                source_version_evidence.c.version_id == version_id,
                source_version_evidence.c.evidence_kind == kind.value,
                source_version_evidence.c.payload_sha256 == digest,
            )
        ).scalar_one_or_none()
        return str(conflicting_row(existing, "knowledge.source_version_evidence"))

    def record_observation(
        self,
        *,
        observation_id: str,
        source_object_id: str,
        version_id: str,
        bucket_id: str,
        observed_at: datetime,
    ) -> None:
        validate_identifier(observation_id, IdKind.SOURCE_OBSERVATION)
        self._connection.execute(
            insert(source_observations).values(
                observation_id=observation_id,
                source_object_id=source_object_id,
                version_id=version_id,
                bucket_id=bucket_id,
                observed_at=ensure_utc(observed_at),
            )
        )

    def record_membership(self, membership: ContactMembership) -> str:
        statement = (
            pg_insert(source_memberships)
            .values(
                membership_id=membership.membership_id,
                parent_bucket_id=membership.group_bucket_id,
                source_object_id=membership.contact_object_id,
                version_id=membership.version_id,
                observed_at=membership.observed_at,
            )
            .on_conflict_do_nothing(constraint="source_membership_version_is_idempotent")
            .returning(source_memberships.c.membership_id)
        )
        inserted = self._connection.execute(statement).scalar_one_or_none()
        if inserted is not None:
            return str(inserted)
        existing = self._connection.execute(
            select(source_memberships.c.membership_id).where(
                source_memberships.c.parent_bucket_id == membership.group_bucket_id,
                source_memberships.c.version_id == membership.version_id,
            )
        ).scalar_one_or_none()
        return str(conflicting_row(existing, "knowledge.source_memberships"))

    def compare_and_set_checkpoint(
        self,
        checkpoint: NativeCheckpoint,
        *,
        expected_sequence: int,
        cursor_private: str,
    ) -> None:
        if not cursor_private:
            raise ValueError("a private checkpoint cursor is required")
        if sha256(cursor_private.encode()).hexdigest() != checkpoint.cursor_digest:
            raise ValueError("a private checkpoint cursor does not match its digest")
        self._connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:bucket_id, 0))"),
            {"bucket_id": checkpoint.bucket_id},
        )
        latest = self._connection.execute(
            select(native_checkpoints.c.checkpoint_id, native_checkpoints.c.sequence)
            .where(native_checkpoints.c.bucket_id == checkpoint.bucket_id)
            .order_by(native_checkpoints.c.sequence.desc())
            .limit(1)
        ).one_or_none()
        actual_sequence = 0 if latest is None else int(latest.sequence)
        actual_predecessor = None if latest is None else str(latest.checkpoint_id)
        if (
            expected_sequence != actual_sequence
            or checkpoint.sequence != actual_sequence + 1
            or checkpoint.previous_checkpoint_id != actual_predecessor
        ):
            raise CheckpointConflictError("native checkpoint compare-and-set failed")
        self._connection.execute(
            insert(native_checkpoints).values(
                checkpoint_id=checkpoint.checkpoint_id,
                bucket_id=checkpoint.bucket_id,
                sequence=checkpoint.sequence,
                previous_checkpoint_id=checkpoint.previous_checkpoint_id,
                cursor_private=cursor_private,
                cursor_digest=checkpoint.cursor_digest,
                recorded_at=checkpoint.recorded_at,
            )
        )

    def enqueue_job(
        self,
        *,
        job_id: str,
        configuration_id: str,
        configuration_revision: int,
        bucket_id: str,
        range_start: datetime,
        range_end: datetime,
        idempotency_key: str,
        created_at: datetime,
    ) -> str:
        validate_identifier(job_id, IdKind.NATIVE_JOB)
        statement = (
            pg_insert(native_sync_jobs)
            .values(
                job_id=job_id,
                configuration_id=configuration_id,
                configuration_revision=configuration_revision,
                bucket_id=bucket_id,
                range_start=ensure_utc(range_start),
                range_end=ensure_utc(range_end),
                state="queued",
                idempotency_key=idempotency_key,
                created_at=ensure_utc(created_at),
                updated_at=ensure_utc(created_at),
            )
            .on_conflict_do_nothing(constraint="native_sync_job_idempotency_is_scoped")
            .returning(native_sync_jobs.c.job_id)
        )
        inserted = self._connection.execute(statement).scalar_one_or_none()
        if inserted is not None:
            return str(inserted)
        existing = self._connection.execute(
            select(
                native_sync_jobs.c.job_id,
                native_sync_jobs.c.range_start,
                native_sync_jobs.c.range_end,
            ).where(
                native_sync_jobs.c.configuration_id == configuration_id,
                native_sync_jobs.c.configuration_revision == configuration_revision,
                native_sync_jobs.c.bucket_id == bucket_id,
                native_sync_jobs.c.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        row = conflicting_row(existing, "knowledge.native_sync_jobs")
        if (row.range_start, row.range_end) != (
            ensure_utc(range_start),
            ensure_utc(range_end),
        ):
            raise NativePersistenceConflictError(
                "a native job idempotency key names different temporal bounds"
            )
        return str(row.job_id)

    def claim_job(self, *, owner: str, lease_for: timedelta) -> NativeJobLease | None:
        if not owner or lease_for <= timedelta(0):
            raise ValueError("a native job claim requires an owner and positive lease")
        candidate = (
            select(native_sync_jobs.c.job_id)
            .where(
                (native_sync_jobs.c.state == "queued")
                | (
                    (native_sync_jobs.c.state == "running")
                    & (native_sync_jobs.c.lease_expires_at <= text("now()"))
                )
            )
            .order_by(native_sync_jobs.c.created_at, native_sync_jobs.c.job_id)
            .with_for_update(skip_locked=True)
            .limit(1)
            .cte("claimable_native_job")
        )
        row = self._connection.execute(
            update(native_sync_jobs)
            .where(native_sync_jobs.c.job_id == candidate.c.job_id)
            .values(
                state="running",
                lease_owner=owner,
                lease_expires_at=func.now() + lease_for,
                updated_at=func.now(),
            )
            .returning(
                native_sync_jobs.c.job_id,
                native_sync_jobs.c.bucket_id,
                native_sync_jobs.c.range_start,
                native_sync_jobs.c.range_end,
                native_sync_jobs.c.lease_owner,
                native_sync_jobs.c.lease_expires_at,
            )
        ).one_or_none()
        return None if row is None else NativeJobLease(*row)

    def append_simulation(self, simulation: WatcherSimulation) -> None:
        self._connection.execute(
            insert(native_watcher_simulations).values(
                simulation_id=simulation.simulation_id,
                sequence=simulation.sequence,
                bucket_id=simulation.bucket_id,
                state=simulation.state.value,
                recorded_at=simulation.recorded_at,
            )
        )

    def append_simulation_receipt(
        self, receipt: SimulationReceipt, *, simulation_sequence: int
    ) -> None:
        self._connection.execute(
            insert(native_simulation_receipts).values(
                receipt_id=receipt.receipt_id,
                simulation_id=receipt.simulation_id,
                simulation_sequence=simulation_sequence,
                checkpoint_id=receipt.checkpoint_id,
                terminal_state=receipt.terminal_state.value,
                recorded_at=receipt.recorded_at,
            )
        )

    def record_live_gate(self, gate: LiveActivationGate, *, reason_code: str) -> None:
        if not reason_code:
            raise ValueError("a denied live activation gate requires a reason code")
        self._connection.execute(
            insert(native_live_activation_gates).values(
                gate_id=gate.gate_id,
                bucket_id=gate.bucket_id,
                state=gate.state.value,
                reason_code=reason_code,
                recorded_at=gate.recorded_at,
            )
        )
