"""Persistence for native-source identities, evidence, receipts, and checkpoints.

Provider locators and cursors enter and leave only through explicitly named
methods in this module.  They are never placed in domain values or exception
messages.  The caller owns the transaction; checkpoint compare-and-set takes a
transaction-scoped advisory lock so the read and append form one serialized
operation per bucket.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from hashlib import sha256

from sqlalchemy import Connection, Engine, func, insert, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.contracts.native_baseline import (
    AdmittedNativePage,
    BaselineResumePoint,
    FrozenBaseline,
    NativeBaselineJob,
)
from my_pa.contracts.v1.base import canonical_json
from my_pa.contracts.v1.native_sources import (
    NativeAdmissionEnvelope,
    NativeBucketProgress,
    NativeCoverageState,
    NativePreflightState,
    NativeProviderFailure,
)
from my_pa.contracts.v1.native_sources import (
    NativeSourceKind as ContractNativeSourceKind,
)
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import NativeSourceCapability
from my_pa.domain.native_sources import (
    ContactMembership,
    ExactBucketSelection,
    LiveActivationGate,
    NativeAdmissionAuthority,
    NativeAdmissionAuthorityError,
    NativeBridge,
    NativeCheckpoint,
    NativeConfigurationRevision,
    NativeRun,
    NativeRunKind,
    NativeRunState,
    NativeSourceAccount,
    NativeSourceBucket,
    SimulationReceipt,
    WatcherSimulation,
)
from my_pa.domain.source.provider import ObjectKind
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence import conflicting_row
from my_pa.infrastructure.persistence.registry import observe_object
from my_pa.infrastructure.persistence.review import open_review_case
from my_pa.infrastructure.persistence.tables import (
    audit_events,
    capture_proposals,
    native_admission_authorities,
    native_bridge_observations,
    native_bridges,
    native_bucket_runs,
    native_checkpoints,
    native_configuration_buckets,
    native_configuration_revisions,
    native_live_activation_gates,
    native_preflight_observations,
    native_simulation_receipts,
    native_source_accounts,
    native_source_buckets,
    native_source_review_routes,
    native_sync_jobs,
    native_sync_runs,
    native_watcher_simulations,
    source_memberships,
    source_observations,
    source_version_evidence,
)

__all__ = [
    "CheckpointConflictError",
    "NativeBucketBindingRecord",
    "NativeConfigurationSnapshotRecord",
    "NativeJobLease",
    "NativePersistenceConflictError",
    "SqlNativeBaselineStore",
    "SqlNativeReviewProposalRouter",
    "SqlNativeSourceControlStore",
    "SqlNativeSourceRepository",
]


class CheckpointConflictError(RuntimeError):
    """The requested checkpoint did not extend the bucket's current chain."""


class NativePersistenceConflictError(RuntimeError):
    """An idempotency key was reused for different native-source work."""


@dataclass(frozen=True, slots=True)
class NativeJobLease:
    job_id: str
    run_id: str
    configuration_id: str
    configuration_revision: int
    bucket_id: str
    range_start: datetime
    range_end: datetime
    read_mode: str
    lease_owner: str
    lease_expires_at: datetime


@dataclass(frozen=True, slots=True)
class NativeBucketBindingRecord:
    bucket_id: str
    account_id: str
    source_id: str
    bridge_id: str
    kind: ContractNativeSourceKind
    account_label: str
    bucket_label: str
    account_locator: str
    bucket_locator: str
    selectable: bool


@dataclass(frozen=True, slots=True)
class NativeConfigurationSnapshotRecord:
    configuration: NativeConfigurationRevision
    active: bool = True


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
                bridge_id=run.bridge_id,
                adapter_identity=run.adapter_identity,
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
                native_sync_runs.c.bridge_id,
                native_sync_runs.c.adapter_identity,
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
            row.bridge_id,
            row.adapter_identity,
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
            run.bridge_id,
            run.adapter_identity,
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
        evidence_id, _ = self._record_evidence_with_created(
            version_id=version_id,
            kind=kind,
            payload=payload,
            recorded_at=recorded_at,
        )
        return evidence_id

    def _record_evidence_with_created(
        self,
        *,
        version_id: str,
        kind: ObjectKind,
        payload: bytes,
        recorded_at: datetime,
    ) -> tuple[str, bool]:
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
            return str(inserted), True
        existing = self._connection.execute(
            select(source_version_evidence.c.evidence_id).where(
                source_version_evidence.c.version_id == version_id,
                source_version_evidence.c.evidence_kind == kind.value,
                source_version_evidence.c.payload_sha256 == digest,
            )
        ).scalar_one_or_none()
        return str(conflicting_row(existing, "knowledge.source_version_evidence")), False

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
            pg_insert(source_observations)
            .values(
                observation_id=observation_id,
                source_object_id=source_object_id,
                version_id=version_id,
                bucket_id=bucket_id,
                observed_at=ensure_utc(observed_at),
            )
            .on_conflict_do_nothing(constraint="source_version_observation_is_idempotent")
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
        if checkpoint.job_id is None:
            # Historical-revision compatibility only.  The WP-12E head trigger
            # rejects every new unbound checkpoint; this shape remains useful
            # when validating the pre-WP-12E schema itself.
            self._connection.execute(
                text(
                    """INSERT INTO knowledge.native_checkpoints
                         (checkpoint_id, bucket_id, sequence, previous_checkpoint_id,
                          cursor_private, cursor_digest, recorded_at)
                       VALUES (:checkpoint_id, :bucket_id, :sequence,
                               :previous_checkpoint_id, :cursor_private,
                               :cursor_digest, :recorded_at)"""
                ),
                {
                    "checkpoint_id": checkpoint.checkpoint_id,
                    "bucket_id": checkpoint.bucket_id,
                    "sequence": checkpoint.sequence,
                    "previous_checkpoint_id": checkpoint.previous_checkpoint_id,
                    "cursor_private": cursor_private,
                    "cursor_digest": checkpoint.cursor_digest,
                    "recorded_at": checkpoint.recorded_at,
                },
            )
        else:
            self._connection.execute(
                insert(native_checkpoints).values(
                    checkpoint_id=checkpoint.checkpoint_id,
                    bucket_id=checkpoint.bucket_id,
                    job_id=checkpoint.job_id,
                    admission_authority_id=checkpoint.admission_authority_id,
                    sequence=checkpoint.sequence,
                    previous_checkpoint_id=checkpoint.previous_checkpoint_id,
                    cursor_private=cursor_private,
                    cursor_digest=checkpoint.cursor_digest,
                    terminal=checkpoint.terminal,
                    item_count=checkpoint.item_count,
                    recorded_at=checkpoint.recorded_at,
                )
            )

    def latest_job_checkpoint(self, job_id: str) -> tuple[NativeCheckpoint, str] | None:
        """Return the latest durable cursor for one baseline job only."""
        validate_identifier(job_id, IdKind.NATIVE_JOB)
        row = self._connection.execute(
            select(
                native_checkpoints.c.checkpoint_id,
                native_checkpoints.c.bucket_id,
                native_checkpoints.c.job_id,
                native_checkpoints.c.admission_authority_id,
                native_checkpoints.c.sequence,
                native_checkpoints.c.previous_checkpoint_id,
                native_checkpoints.c.cursor_private,
                native_checkpoints.c.cursor_digest,
                native_checkpoints.c.terminal,
                native_checkpoints.c.item_count,
                native_checkpoints.c.recorded_at,
            )
            .where(native_checkpoints.c.job_id == job_id)
            .order_by(native_checkpoints.c.sequence.desc())
            .limit(1)
        ).one_or_none()
        if row is None:
            return None
        return (
            NativeCheckpoint(
                checkpoint_id=str(row.checkpoint_id),
                bucket_id=str(row.bucket_id),
                job_id=str(row.job_id),
                admission_authority_id=str(row.admission_authority_id),
                sequence=int(row.sequence),
                previous_checkpoint_id=(
                    None if row.previous_checkpoint_id is None else str(row.previous_checkpoint_id)
                ),
                cursor_digest=str(row.cursor_digest),
                terminal=bool(row.terminal),
                item_count=int(row.item_count),
                recorded_at=row.recorded_at,
            ),
            str(row.cursor_private),
        )

    def enqueue_job(
        self,
        *,
        job_id: str,
        run_id: str | None = None,
        configuration_id: str,
        configuration_revision: int,
        bucket_id: str,
        range_start: datetime,
        range_end: datetime,
        read_mode: str = "bounded_time",
        idempotency_key: str,
        created_at: datetime,
    ) -> str:
        validate_identifier(job_id, IdKind.NATIVE_JOB)
        if run_id is not None:
            validate_identifier(run_id, IdKind.NATIVE_RUN)
        if read_mode not in {"bounded_time", "current_inventory"}:
            raise ValueError("a native job requires a closed read mode")
        if run_id is None:
            # Historical-revision compatibility only.  The WP-12E head trigger
            # rejects this legacy shape so current callers cannot bypass the
            # frozen-run binding.
            inserted = self._connection.execute(
                text(
                    """INSERT INTO knowledge.native_sync_jobs
                         (job_id, configuration_id, configuration_revision, bucket_id,
                          range_start, range_end, state, idempotency_key, created_at,
                          updated_at)
                       VALUES (:job_id, :configuration_id, :configuration_revision,
                               :bucket_id, :range_start, :range_end, 'queued',
                               :idempotency_key, :created_at, :created_at)
                       ON CONFLICT ON CONSTRAINT native_sync_job_idempotency_is_scoped
                       DO NOTHING RETURNING job_id"""
                ),
                {
                    "job_id": job_id,
                    "configuration_id": configuration_id,
                    "configuration_revision": configuration_revision,
                    "bucket_id": bucket_id,
                    "range_start": ensure_utc(range_start),
                    "range_end": ensure_utc(range_end),
                    "idempotency_key": idempotency_key,
                    "created_at": ensure_utc(created_at),
                },
            ).scalar_one_or_none()
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
        statement = (
            pg_insert(native_sync_jobs)
            .values(
                job_id=job_id,
                run_id=run_id,
                configuration_id=configuration_id,
                configuration_revision=configuration_revision,
                bucket_id=bucket_id,
                range_start=ensure_utc(range_start),
                range_end=ensure_utc(range_end),
                read_mode=read_mode,
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
                native_sync_jobs.c.run_id,
                native_sync_jobs.c.range_start,
                native_sync_jobs.c.range_end,
                native_sync_jobs.c.read_mode,
            ).where(
                native_sync_jobs.c.configuration_id == configuration_id,
                native_sync_jobs.c.configuration_revision == configuration_revision,
                native_sync_jobs.c.bucket_id == bucket_id,
                native_sync_jobs.c.idempotency_key == idempotency_key,
            )
        ).one_or_none()
        row = conflicting_row(existing, "knowledge.native_sync_jobs")
        if (row.run_id, row.range_start, row.range_end, row.read_mode) != (
            run_id,
            ensure_utc(range_start),
            ensure_utc(range_end),
            read_mode,
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
                native_sync_jobs.c.run_id,
                native_sync_jobs.c.configuration_id,
                native_sync_jobs.c.configuration_revision,
                native_sync_jobs.c.bucket_id,
                native_sync_jobs.c.range_start,
                native_sync_jobs.c.range_end,
                native_sync_jobs.c.read_mode,
                native_sync_jobs.c.lease_owner,
                native_sync_jobs.c.lease_expires_at,
            )
        ).one_or_none()
        return None if row is None else NativeJobLease(*row)

    def finish_job(
        self,
        *,
        job_id: str,
        owner: str,
        item_count: int,
        recorded_at: datetime,
    ) -> None:
        """Finish exactly the caller's lease after a terminal admitted checkpoint."""
        validate_identifier(job_id, IdKind.NATIVE_JOB)
        if item_count < 0:
            raise ValueError("a native job item count cannot be negative")
        terminal = self._connection.execute(
            select(native_checkpoints.c.checkpoint_id).where(
                native_checkpoints.c.job_id == job_id,
                native_checkpoints.c.terminal.is_(True),
            )
        ).scalar_one_or_none()
        if terminal is None:
            raise NativePersistenceConflictError(
                "a native job cannot finish without its terminal admitted checkpoint"
            )
        row = self._connection.execute(
            update(native_sync_jobs)
            .where(
                native_sync_jobs.c.job_id == job_id,
                native_sync_jobs.c.state == "running",
                native_sync_jobs.c.lease_owner == owner,
            )
            .values(
                state="succeeded",
                lease_owner=None,
                lease_expires_at=None,
                updated_at=ensure_utc(recorded_at),
            )
            .returning(native_sync_jobs.c.run_id, native_sync_jobs.c.bucket_id)
        ).one_or_none()
        if row is None or row.run_id is None:
            raise NativePersistenceConflictError("the native job lease is stale")
        self.append_bucket_run(
            bucket_run_id=issue_identifier(IdKind.NATIVE_BUCKET_RUN),
            run_id=str(row.run_id),
            bucket_id=str(row.bucket_id),
            state="succeeded",
            item_count=item_count,
            recorded_at=recorded_at,
        )

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


class SqlNativeBaselineStore:
    """Engine-backed frozen baseline/job/checkpoint implementation."""

    _TERMINAL_CURSOR = "__my_pa_native_baseline_complete__"

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _lock_configuration(connection: Connection, configuration_id: str) -> None:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:configuration_id, 0))"),
            {"configuration_id": configuration_id},
        )

    def selected_kinds(self, configuration_id: str) -> tuple[ContractNativeSourceKind, ...]:
        validate_identifier(configuration_id, IdKind.NATIVE_CONFIGURATION)
        with self._engine.connect() as connection:
            revision = connection.scalar(
                select(func.max(native_configuration_revisions.c.revision)).where(
                    native_configuration_revisions.c.configuration_id == configuration_id
                )
            )
            if revision is None:
                return ()
            values = connection.execute(
                select(native_source_buckets.c.source_kind)
                .select_from(
                    native_configuration_buckets.join(
                        native_source_buckets,
                        native_source_buckets.c.bucket_id
                        == native_configuration_buckets.c.bucket_id,
                    )
                )
                .where(
                    native_configuration_buckets.c.configuration_id == configuration_id,
                    native_configuration_buckets.c.revision == revision,
                )
                .distinct()
                .order_by(native_source_buckets.c.source_kind)
            ).scalars()
        return tuple(ContractNativeSourceKind(str(value)) for value in values)

    def prepare(
        self,
        *,
        configuration_id: str,
        idempotency_key: str,
        proposed_cutoff_at: datetime,
        adapter_identity: str,
    ) -> FrozenBaseline:
        validate_identifier(configuration_id, IdKind.NATIVE_CONFIGURATION)
        if not idempotency_key:
            raise ValueError("a native baseline idempotency key is required")
        cutoff = ensure_utc(proposed_cutoff_at)
        with self._engine.begin() as connection:
            self._lock_configuration(connection, configuration_id)
            existing = connection.execute(
                select(
                    native_sync_runs.c.run_id,
                    native_sync_runs.c.configuration_revision,
                    native_sync_runs.c.cutoff_at,
                    native_sync_runs.c.adapter_identity,
                ).where(
                    native_sync_runs.c.configuration_id == configuration_id,
                    native_sync_runs.c.idempotency_key == idempotency_key,
                )
            ).one_or_none()
            if existing is not None:
                if str(existing.adapter_identity) != adapter_identity:
                    raise NativePersistenceConflictError(
                        "a native baseline retry changed its frozen adapter identity"
                    )
                return FrozenBaseline(
                    run_id=str(existing.run_id),
                    configuration_id=configuration_id,
                    configuration_revision=int(existing.configuration_revision),
                    cutoff_at=existing.cutoff_at,
                )
            configuration = connection.execute(
                select(
                    native_configuration_revisions.c.revision,
                    native_configuration_revisions.c.bridge_id,
                    native_configuration_revisions.c.start_at,
                )
                .where(native_configuration_revisions.c.configuration_id == configuration_id)
                .order_by(native_configuration_revisions.c.revision.desc())
                .limit(1)
            ).one_or_none()
            if configuration is None:
                raise LookupError("native baseline configuration was not found")
            start_at = configuration.start_at
            if start_at > cutoff:
                raise NativePersistenceConflictError(
                    "the server cutoff precedes the normalized configuration start"
                )
            prior_start = connection.scalar(
                select(native_configuration_revisions.c.start_at).where(
                    native_configuration_revisions.c.configuration_id == configuration_id,
                    native_configuration_revisions.c.revision == int(configuration.revision) - 1,
                )
            )
            backfill = prior_start is not None and start_at < prior_start
            prior_boundary = prior_start if isinstance(prior_start, datetime) else None
            run_id = issue_identifier(IdKind.NATIVE_RUN)
            run = NativeRun(
                run_id=run_id,
                configuration_id=configuration_id,
                configuration_revision=int(configuration.revision),
                bridge_id=str(configuration.bridge_id),
                adapter_identity=adapter_identity,
                kind=NativeRunKind.BACKFILL if backfill else NativeRunKind.BASELINE,
                state=NativeRunState.RUNNING,
                start_at=start_at,
                cutoff_at=cutoff,
                calendar_horizon_at=cutoff + timedelta(days=90),
                recorded_at=cutoff,
            )
            repository = SqlNativeSourceRepository(connection)
            repository.append_run(run, idempotency_key=idempotency_key)
            selected = connection.execute(
                select(
                    native_configuration_buckets.c.bucket_id,
                    native_source_buckets.c.source_kind,
                )
                .select_from(
                    native_configuration_buckets.join(
                        native_source_buckets,
                        native_source_buckets.c.bucket_id
                        == native_configuration_buckets.c.bucket_id,
                    )
                )
                .where(
                    native_configuration_buckets.c.configuration_id == configuration_id,
                    native_configuration_buckets.c.revision == configuration.revision,
                )
                .order_by(native_configuration_buckets.c.bucket_id)
            ).all()
            for bucket in selected:
                kind = ContractNativeSourceKind(str(bucket.source_kind))
                current_inventory = kind is ContractNativeSourceKind.CONTACTS
                range_end = (
                    cutoff
                    if kind is not ContractNativeSourceKind.CALENDAR
                    else cutoff + timedelta(days=90)
                )
                if backfill and not current_inventory and prior_boundary is not None:
                    range_end = min(range_end, prior_boundary - timedelta(milliseconds=1))
                repository.enqueue_job(
                    job_id=issue_identifier(IdKind.NATIVE_JOB),
                    run_id=run_id,
                    configuration_id=configuration_id,
                    configuration_revision=int(configuration.revision),
                    bucket_id=str(bucket.bucket_id),
                    range_start=cutoff if current_inventory else start_at,
                    range_end=cutoff if current_inventory else range_end,
                    read_mode="current_inventory" if current_inventory else "bounded_time",
                    idempotency_key=f"{idempotency_key}:{bucket.bucket_id}",
                    created_at=cutoff,
                )
        return FrozenBaseline(
            run_id=run_id,
            configuration_id=configuration_id,
            configuration_revision=int(configuration.revision),
            cutoff_at=cutoff,
        )

    def claim(self, run_id: str, *, owner: str, lease_for: timedelta) -> NativeBaselineJob | None:
        validate_identifier(run_id, IdKind.NATIVE_RUN)
        if not owner or lease_for <= timedelta(0):
            raise ValueError("a native baseline claim requires owner and positive lease")
        with self._engine.begin() as connection:
            candidate = (
                select(native_sync_jobs.c.job_id)
                .where(
                    native_sync_jobs.c.run_id == run_id,
                    (native_sync_jobs.c.state == "queued")
                    | (
                        (native_sync_jobs.c.state == "running")
                        & (
                            (native_sync_jobs.c.lease_expires_at <= func.now())
                            | (native_sync_jobs.c.lease_owner == owner)
                        )
                    ),
                )
                .order_by(native_sync_jobs.c.created_at, native_sync_jobs.c.job_id)
                .with_for_update(skip_locked=True)
                .limit(1)
                .cte("claimable_baseline_job")
            )
            row = connection.execute(
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
                    native_sync_jobs.c.run_id,
                    native_sync_jobs.c.configuration_id,
                    native_sync_jobs.c.configuration_revision,
                    native_sync_jobs.c.bucket_id,
                    native_sync_jobs.c.range_start,
                    native_sync_jobs.c.range_end,
                    native_sync_jobs.c.read_mode,
                )
            ).one_or_none()
            if row is None:
                return None
            kind = connection.scalar(
                select(native_source_buckets.c.source_kind).where(
                    native_source_buckets.c.bucket_id == row.bucket_id
                )
            )
        return NativeBaselineJob(
            job_id=str(row.job_id),
            run_id=str(row.run_id),
            configuration_id=str(row.configuration_id),
            configuration_revision=int(row.configuration_revision),
            bucket_id=str(row.bucket_id),
            kind=ContractNativeSourceKind(str(kind)),
            range_start=row.range_start,
            range_end=row.range_end,
            current_inventory=str(row.read_mode) == "current_inventory",
            lease_owner=owner,
        )

    def resume_point(self, job_id: str) -> BaselineResumePoint:
        validate_identifier(job_id, IdKind.NATIVE_JOB)
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(native_checkpoints.c.cursor_private, native_checkpoints.c.terminal)
                .where(native_checkpoints.c.job_id == job_id)
                .order_by(native_checkpoints.c.sequence)
            ).all()
        if not rows:
            return BaselineResumePoint(cursor=None, terminal=False, page_count=0)
        latest = rows[-1]
        return BaselineResumePoint(
            cursor=None if latest.terminal else str(latest.cursor_private),
            terminal=bool(latest.terminal),
            page_count=len(rows),
        )

    def checkpoint_admitted_page(
        self,
        job: NativeBaselineJob,
        page: AdmittedNativePage,
        *,
        recorded_at: datetime,
    ) -> None:
        cursor = self._TERMINAL_CURSOR if page.next_cursor is None else page.next_cursor
        with self._engine.begin() as connection:
            lease = connection.execute(
                select(native_sync_jobs.c.bucket_id).where(
                    native_sync_jobs.c.job_id == job.job_id,
                    native_sync_jobs.c.run_id == job.run_id,
                    native_sync_jobs.c.state == "running",
                    native_sync_jobs.c.lease_owner == job.lease_owner,
                    native_sync_jobs.c.lease_expires_at > func.now(),
                )
            ).scalar_one_or_none()
            if lease is None or str(lease) != job.bucket_id:
                raise NativePersistenceConflictError("the native baseline lease is stale")
            prior_job = connection.execute(
                select(native_checkpoints.c.cursor_private)
                .where(native_checkpoints.c.job_id == job.job_id)
                .order_by(native_checkpoints.c.sequence.desc())
                .limit(1)
            ).scalar_one_or_none()
            if page.next_cursor is not None and prior_job == page.next_cursor:
                raise NativePersistenceConflictError("a native page cursor made no progress")
            latest = connection.execute(
                select(native_checkpoints.c.checkpoint_id, native_checkpoints.c.sequence)
                .where(native_checkpoints.c.bucket_id == job.bucket_id)
                .order_by(native_checkpoints.c.sequence.desc())
                .limit(1)
            ).one_or_none()
            sequence = 1 if latest is None else int(latest.sequence) + 1
            checkpoint = NativeCheckpoint(
                checkpoint_id=issue_identifier(IdKind.NATIVE_CHECKPOINT),
                bucket_id=job.bucket_id,
                job_id=job.job_id,
                admission_authority_id=page.authority_id,
                sequence=sequence,
                previous_checkpoint_id=None if latest is None else str(latest.checkpoint_id),
                cursor_digest=sha256(cursor.encode()).hexdigest(),
                terminal=page.next_cursor is None,
                item_count=page.admission.admitted_count + page.admission.duplicate_count,
                recorded_at=recorded_at,
            )
            SqlNativeSourceRepository(connection).compare_and_set_checkpoint(
                checkpoint,
                expected_sequence=sequence - 1,
                cursor_private=cursor,
            )

    def finish(self, job: NativeBaselineJob, *, recorded_at: datetime) -> None:
        with self._engine.begin() as connection:
            total = connection.scalar(
                select(func.coalesce(func.sum(native_checkpoints.c.item_count), 0)).where(
                    native_checkpoints.c.job_id == job.job_id
                )
            )
            SqlNativeSourceRepository(connection).finish_job(
                job_id=job.job_id,
                owner=job.lease_owner,
                item_count=int(total or 0),
                recorded_at=recorded_at,
            )

    def complete(self, run_id: str) -> bool:
        validate_identifier(run_id, IdKind.NATIVE_RUN)
        with self._engine.connect() as connection:
            counts = connection.execute(
                select(
                    func.count(native_sync_jobs.c.job_id),
                    func.count(native_sync_jobs.c.job_id).filter(
                        native_sync_jobs.c.state == "succeeded"
                    ),
                ).where(native_sync_jobs.c.run_id == run_id)
            ).one()
        return int(counts[0]) > 0 and int(counts[0]) == int(counts[1])


class SqlNativeSourceControlStore:
    """Engine-backed C store whose admission transaction commits before enrichment."""

    def __init__(self, engine: Engine) -> None:
        self._engine = engine

    @staticmethod
    def _lock_configuration(connection: Connection, configuration_id: str) -> None:
        connection.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:configuration_id, 0))"),
            {"configuration_id": configuration_id},
        )

    def bridge_protocol(self, bridge_id: str) -> str | None:
        validate_identifier(bridge_id, IdKind.NATIVE_BRIDGE)
        with self._engine.connect() as connection:
            value = connection.execute(
                select(native_bridges.c.protocol_version).where(
                    native_bridges.c.bridge_id == bridge_id
                )
            ).scalar_one_or_none()
        return None if value is None else str(value)

    def bucket_bindings(self, bucket_ids: tuple[str, ...]) -> tuple[NativeBucketBindingRecord, ...]:
        for bucket_id in bucket_ids:
            validate_identifier(bucket_id, IdKind.NATIVE_BUCKET)
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    native_source_buckets.c.bucket_id,
                    native_source_accounts.c.account_id,
                    native_source_accounts.c.source_id,
                    native_source_accounts.c.bridge_id,
                    native_source_buckets.c.source_kind,
                    native_source_accounts.c.label,
                    native_source_buckets.c.label,
                    native_source_accounts.c.private_locator,
                    native_source_buckets.c.private_locator,
                    native_source_buckets.c.selectable,
                )
                .join(
                    native_source_accounts,
                    native_source_accounts.c.account_id == native_source_buckets.c.account_id,
                )
                .where(native_source_buckets.c.bucket_id.in_(bucket_ids))
                .order_by(native_source_buckets.c.bucket_id)
            ).all()
        return tuple(
            NativeBucketBindingRecord(
                bucket_id=str(row[0]),
                account_id=str(row[1]),
                source_id=str(row[2]),
                bridge_id=str(row[3]),
                kind=ContractNativeSourceKind(str(row[4])),
                account_label=str(row[5]),
                bucket_label=str(row[6]),
                account_locator=str(row[7]),
                bucket_locator=str(row[8]),
                selectable=bool(row[9]),
            )
            for row in rows
        )

    def visible_locator_pairs(
        self, bridge_id: str, source_ids: frozenset[str]
    ) -> frozenset[tuple[str, str]]:
        validate_identifier(bridge_id, IdKind.NATIVE_BRIDGE)
        for source_id in source_ids:
            validate_identifier(source_id, IdKind.SOURCE)
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    native_source_accounts.c.private_locator,
                    native_source_buckets.c.private_locator,
                )
                .join(
                    native_source_buckets,
                    native_source_buckets.c.account_id == native_source_accounts.c.account_id,
                )
                .where(
                    native_source_accounts.c.bridge_id == bridge_id,
                    native_source_accounts.c.source_id.in_(source_ids),
                )
            ).all()
        return frozenset((str(row[0]), str(row[1])) for row in rows)

    def append_configuration(
        self,
        configuration: NativeConfigurationRevision,
        *,
        expected_prior_revision: int,
        preflight: tuple[NativeBucketProgress, ...] = (),
    ) -> None:
        if expected_prior_revision < 0 or configuration.revision != expected_prior_revision + 1:
            raise NativePersistenceConflictError(
                "a native configuration revision must follow its expected predecessor"
            )
        with self._engine.begin() as connection:
            self._lock_configuration(connection, configuration.configuration_id)
            latest = connection.execute(
                select(func.max(native_configuration_revisions.c.revision)).where(
                    native_configuration_revisions.c.configuration_id
                    == configuration.configuration_id
                )
            ).scalar_one()
            actual_prior = 0 if latest is None else int(latest)
            if actual_prior != expected_prior_revision:
                raise NativePersistenceConflictError(
                    "the native configuration expected revision is stale"
                )
            SqlNativeSourceRepository(connection).append_configuration(configuration)
            self._record_preflight_rows(
                connection,
                configuration.configuration_id,
                configuration.revision,
                preflight,
                observed_at=configuration.created_at,
            )

    @staticmethod
    def _record_preflight_rows(
        connection: Connection,
        configuration_id: str,
        configuration_revision: int,
        results: tuple[NativeBucketProgress, ...],
        *,
        observed_at: datetime,
    ) -> None:
        for result in results:
            if result.state not in {state.value for state in NativePreflightState}:
                raise ValueError("native preflight state is not durable vocabulary")
            connection.execute(
                insert(native_preflight_observations).values(
                    observation_id=issue_identifier(IdKind.SOURCE_OBSERVATION),
                    configuration_id=configuration_id,
                    configuration_revision=configuration_revision,
                    bucket_id=result.bucket_id,
                    state=result.state,
                    failure=None if result.failure is None else result.failure.value,
                    observed_at=ensure_utc(observed_at),
                )
            )

    def record_preflight(
        self,
        configuration_id: str,
        configuration_revision: int,
        results: tuple[NativeBucketProgress, ...],
        *,
        observed_at: datetime,
    ) -> None:
        with self._engine.begin() as connection:
            self._lock_configuration(connection, configuration_id)
            self._record_preflight_rows(
                connection,
                configuration_id,
                configuration_revision,
                results,
                observed_at=observed_at,
            )

    def issue_sync_authority(
        self,
        configuration: NativeConfigurationRevision,
        binding: NativeBucketBindingRecord,
        *,
        audit_id: str,
        request_id: str,
        issued_at: datetime,
        expires_at: datetime,
    ) -> NativeAdmissionAuthority:
        authority_id = issue_identifier(IdKind.NATIVE_AUTHORITY)
        authority = NativeAdmissionAuthority(
            authority_id=authority_id,
            configuration_id=configuration.configuration_id,
            configuration_revision=configuration.revision,
            bridge_id=configuration.bridge_id,
            bucket_id=binding.bucket_id,
            source_id=binding.source_id,
            audit_id=audit_id,
            envelope_id=authority_id,
            request_id=request_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
        with self._engine.begin() as connection:
            self._lock_configuration(connection, configuration.configuration_id)
            latest = connection.execute(
                select(func.max(native_configuration_revisions.c.revision)).where(
                    native_configuration_revisions.c.configuration_id
                    == configuration.configuration_id
                )
            ).scalar_one()
            allowed_audit = connection.execute(
                select(audit_events.c.audit_id).where(
                    audit_events.c.audit_id == audit_id,
                    audit_events.c.capability == NativeSourceCapability.SYNC.value,
                    audit_events.c.outcome == "allowed",
                )
            ).scalar_one_or_none()
            selected = connection.execute(
                select(native_source_accounts.c.source_id, native_source_accounts.c.bridge_id)
                .select_from(
                    native_configuration_buckets.join(
                        native_source_buckets,
                        native_source_buckets.c.bucket_id
                        == native_configuration_buckets.c.bucket_id,
                    ).join(
                        native_source_accounts,
                        native_source_accounts.c.account_id == native_source_buckets.c.account_id,
                    )
                )
                .where(
                    native_configuration_buckets.c.configuration_id
                    == configuration.configuration_id,
                    native_configuration_buckets.c.revision == configuration.revision,
                    native_configuration_buckets.c.bucket_id == binding.bucket_id,
                )
            ).one_or_none()
            if (
                latest != configuration.revision
                or allowed_audit is None
                or selected is None
                or str(selected.source_id) != binding.source_id
                or str(selected.bridge_id) != configuration.bridge_id
            ):
                raise NativeAdmissionAuthorityError("native authority issuance scope is stale")
            connection.execute(
                insert(native_admission_authorities).values(
                    authority_id=authority.authority_id,
                    audit_id=authority.audit_id,
                    configuration_id=authority.configuration_id,
                    configuration_revision=authority.configuration_revision,
                    bridge_id=authority.bridge_id,
                    bucket_id=authority.bucket_id,
                    source_id=authority.source_id,
                    host_instance_id=authority.bridge_id,
                    envelope_id=authority.envelope_id,
                    request_id=authority.request_id,
                    issued_at=authority.issued_at,
                    expires_at=authority.expires_at,
                )
            )
        return authority

    def latest_configuration(
        self, configuration_id: str
    ) -> NativeConfigurationSnapshotRecord | None:
        validate_identifier(configuration_id, IdKind.NATIVE_CONFIGURATION)
        with self._engine.connect() as connection:
            row = connection.execute(
                select(
                    native_configuration_revisions.c.configuration_id,
                    native_configuration_revisions.c.revision,
                    native_configuration_revisions.c.bridge_id,
                    native_configuration_revisions.c.timezone_name,
                    native_configuration_revisions.c.start_date,
                    native_configuration_revisions.c.cutoff_at,
                    native_configuration_revisions.c.created_at,
                )
                .where(native_configuration_revisions.c.configuration_id == configuration_id)
                .order_by(native_configuration_revisions.c.revision.desc())
                .limit(1)
            ).one_or_none()
            if row is None:
                return None
            bucket_ids = tuple(
                str(value)
                for value in connection.execute(
                    select(native_configuration_buckets.c.bucket_id)
                    .where(
                        native_configuration_buckets.c.configuration_id == configuration_id,
                        native_configuration_buckets.c.revision == row.revision,
                    )
                    .order_by(native_configuration_buckets.c.bucket_id)
                ).scalars()
            )
        return NativeConfigurationSnapshotRecord(
            NativeConfigurationRevision(
                configuration_id=str(row.configuration_id),
                revision=int(row.revision),
                bridge_id=str(row.bridge_id),
                timezone_name=str(row.timezone_name),
                start_date=row.start_date,
                cutoff_at=row.cutoff_at,
                selection=ExactBucketSelection(bucket_ids),
                created_at=row.created_at,
            )
        )

    def progress(self, configuration_id: str) -> tuple[NativeBucketProgress, ...]:
        snapshot = self.latest_configuration(configuration_id)
        if snapshot is None:
            return ()
        with self._engine.connect() as connection:
            rows = connection.execute(
                select(
                    native_configuration_buckets.c.bucket_id,
                    func.count(func.distinct(source_observations.c.version_id)).label("admitted"),
                    func.coalesce(func.sum(native_bucket_runs.c.item_count), 0).label("measured"),
                    func.count(func.distinct(native_bucket_runs.c.bucket_run_id)).label(
                        "run_count"
                    ),
                )
                .outerjoin(
                    source_observations,
                    source_observations.c.bucket_id == native_configuration_buckets.c.bucket_id,
                )
                .outerjoin(
                    native_bucket_runs,
                    native_bucket_runs.c.bucket_id == native_configuration_buckets.c.bucket_id,
                )
                .where(
                    native_configuration_buckets.c.configuration_id == configuration_id,
                    native_configuration_buckets.c.revision == snapshot.configuration.revision,
                )
                .group_by(native_configuration_buckets.c.bucket_id)
                .order_by(native_configuration_buckets.c.bucket_id)
            ).all()
            latest_preflight: dict[str, tuple[str, str | None]] = {}
            for row in rows:
                observed = connection.execute(
                    select(
                        native_preflight_observations.c.state,
                        native_preflight_observations.c.failure,
                    )
                    .where(
                        native_preflight_observations.c.configuration_id == configuration_id,
                        native_preflight_observations.c.configuration_revision
                        == snapshot.configuration.revision,
                        native_preflight_observations.c.bucket_id == row.bucket_id,
                    )
                    .order_by(
                        native_preflight_observations.c.observed_at.desc(),
                        native_preflight_observations.c.observation_id.desc(),
                    )
                    .limit(1)
                ).one_or_none()
                if observed is not None:
                    latest_preflight[str(row.bucket_id)] = (
                        str(observed.state),
                        None if observed.failure is None else str(observed.failure),
                    )
        progress: list[NativeBucketProgress] = []
        for row in rows:
            admitted = int(row.admitted)
            measured = int(row.measured)
            run_count = int(row.run_count)
            observed_state, observed_failure = latest_preflight.get(
                str(row.bucket_id), ("reachable", None)
            )
            coverage = (
                NativeCoverageState.PERMISSION_DENIED
                if observed_state == NativePreflightState.PERMISSION_DENIED.value
                else NativeCoverageState.UNAVAILABLE
                if observed_state
                in {
                    NativePreflightState.UNAVAILABLE.value,
                    NativePreflightState.IDENTITY_DRIFT.value,
                }
                else NativeCoverageState.EVIDENCE_PRESENT
                if admitted
                else NativeCoverageState.EMPTY
                if run_count and measured == 0
                else NativeCoverageState.NOT_MEASURED
            )
            progress.append(
                NativeBucketProgress(
                    bucket_id=str(row.bucket_id),
                    state=observed_state
                    if observed_state != "reachable"
                    else (
                        "complete"
                        if coverage is not NativeCoverageState.NOT_MEASURED
                        else "pending"
                    ),
                    coverage=coverage,
                    admitted_count=admitted,
                    failed_count=(
                        1
                        if coverage
                        in {
                            NativeCoverageState.PERMISSION_DENIED,
                            NativeCoverageState.UNAVAILABLE,
                        }
                        else 0
                    ),
                    pending_count=1 if coverage is NativeCoverageState.NOT_MEASURED else 0,
                    failure=(
                        None
                        if observed_failure is None
                        else NativeProviderFailure(observed_failure)
                    ),
                )
            )
        return tuple(progress)

    @staticmethod
    def _admission_digest(envelope: NativeAdmissionEnvelope) -> str:
        return sha256(
            canonical_json(envelope.model_dump(mode="json", by_alias=True)).encode()
        ).hexdigest()

    def _validate_authority_locked(
        self,
        connection: Connection,
        envelope: NativeAdmissionEnvelope,
        authority: NativeAdmissionAuthority,
        *,
        at: datetime,
    ) -> tuple[ContractNativeSourceKind, str]:
        recorded_at = ensure_utc(at)
        admission_digest = self._admission_digest(envelope)
        self._lock_configuration(connection, authority.configuration_id)
        grant = connection.execute(
            select(
                native_admission_authorities,
                audit_events.c.capability,
                audit_events.c.outcome,
            )
            .join(
                audit_events,
                audit_events.c.audit_id == native_admission_authorities.c.audit_id,
            )
            .where(native_admission_authorities.c.authority_id == authority.authority_id)
            .with_for_update(of=native_admission_authorities)
        ).one_or_none()
        latest = connection.execute(
            select(func.max(native_configuration_revisions.c.revision)).where(
                native_configuration_revisions.c.configuration_id == authority.configuration_id
            )
        ).scalar_one()
        selected = connection.execute(
            select(
                native_source_accounts.c.account_id,
                native_source_accounts.c.source_id,
                native_source_accounts.c.bridge_id,
                native_source_accounts.c.private_locator.label("account_locator"),
                native_source_buckets.c.private_locator.label("bucket_locator"),
                native_source_buckets.c.source_kind,
                native_source_buckets.c.selectable,
            )
            .select_from(
                native_configuration_buckets.join(
                    native_source_buckets,
                    native_source_buckets.c.bucket_id == native_configuration_buckets.c.bucket_id,
                ).join(
                    native_source_accounts,
                    native_source_accounts.c.account_id == native_source_buckets.c.account_id,
                )
            )
            .where(
                native_configuration_buckets.c.configuration_id == authority.configuration_id,
                native_configuration_buckets.c.revision == authority.configuration_revision,
                native_configuration_buckets.c.bucket_id == authority.bucket_id,
            )
        ).one_or_none()
        if grant is None or selected is None:
            raise NativeAdmissionAuthorityError("native admission authority was not found")
        durable = grant._mapping
        exact = (
            str(durable["audit_id"]) == authority.audit_id
            and str(durable["configuration_id"]) == authority.configuration_id
            and int(durable["configuration_revision"]) == authority.configuration_revision
            and str(durable["bridge_id"]) == authority.bridge_id
            and str(durable["host_instance_id"]) == authority.bridge_id
            and str(durable["bucket_id"]) == authority.bucket_id
            and str(durable["source_id"]) == authority.source_id
            and str(durable["envelope_id"]) == authority.envelope_id
            and str(durable["request_id"]) == authority.request_id
            and durable["issued_at"] == authority.issued_at
            and durable["expires_at"] == authority.expires_at
            and str(durable["capability"]) == NativeSourceCapability.SYNC.value
            and str(durable["outcome"]) == "allowed"
            and latest == authority.configuration_revision
            and str(selected.source_id) == authority.source_id
            and str(selected.bridge_id) == authority.bridge_id
            and bool(selected.selectable)
            and str(selected.account_locator) == envelope.account_id
            and str(selected.bucket_locator) == envelope.bucket_id
            and str(selected.source_kind) == envelope.kind.value
            and envelope.metadata.host_instance_id == authority.bridge_id
            and envelope.metadata.envelope_id == authority.envelope_id
            and envelope.request_id == authority.request_id
            and authority.issued_at <= recorded_at <= authority.expires_at
        )
        prior_digest = durable["admission_sha256"]
        if not exact or (prior_digest is not None and str(prior_digest) != admission_digest):
            raise NativeAdmissionAuthorityError("native admission authority did not match")
        return ContractNativeSourceKind(str(selected.source_kind)), admission_digest

    def prevalidate_authority(
        self,
        envelope: NativeAdmissionEnvelope,
        authority: NativeAdmissionAuthority,
        *,
        at: datetime,
    ) -> None:
        """Lock and validate a durable grant without consuming it or writing status."""
        with self._engine.begin() as connection:
            self._validate_authority_locked(connection, envelope, authority, at=at)

    def record_admission_preflight_durably(
        self,
        envelope: NativeAdmissionEnvelope,
        authority: NativeAdmissionAuthority,
        results: tuple[NativeBucketProgress, ...],
        *,
        observed_at: datetime,
    ) -> None:
        """Record an accepted operational denial only while its grant remains current."""
        with self._engine.begin() as connection:
            self._validate_authority_locked(connection, envelope, authority, at=observed_at)
            self._record_preflight_rows(
                connection,
                authority.configuration_id,
                authority.configuration_revision,
                results,
                observed_at=observed_at,
            )

    def admit_evidence_durably(
        self,
        envelope: NativeAdmissionEnvelope,
        authority: NativeAdmissionAuthority,
        preflight: tuple[NativeBucketProgress, ...] = (),
        *,
        at: datetime,
    ) -> tuple[tuple[str, bool], ...]:
        recorded_at = ensure_utc(at)
        outcomes: list[tuple[str, bool]] = []
        with self._engine.begin() as connection:
            source_kind, admission_digest = self._validate_authority_locked(
                connection, envelope, authority, at=recorded_at
            )
            self._record_preflight_rows(
                connection,
                authority.configuration_id,
                authority.configuration_revision,
                preflight,
                observed_at=recorded_at,
            )
            prior_digest = connection.scalar(
                select(native_admission_authorities.c.admission_sha256).where(
                    native_admission_authorities.c.authority_id == authority.authority_id
                )
            )
            if prior_digest is None:
                connection.execute(
                    update(native_admission_authorities)
                    .where(
                        native_admission_authorities.c.authority_id == authority.authority_id,
                        native_admission_authorities.c.admission_sha256.is_(None),
                    )
                    .values(consumed_at=recorded_at, admission_sha256=admission_digest)
                )
            object_kind = {
                ContractNativeSourceKind.MAIL: ObjectKind.MAIL_MESSAGE,
                ContractNativeSourceKind.CALENDAR: ObjectKind.CALENDAR_EVENT,
                ContractNativeSourceKind.CONTACTS: ObjectKind.CONTACT,
            }[source_kind]
            media_type = {
                ObjectKind.MAIL_MESSAGE: "message/rfc822",
                ObjectKind.CALENDAR_EVENT: "application/calendar+json",
                ObjectKind.CONTACT: "application/contact+json",
            }[object_kind]
            repository = SqlNativeSourceRepository(connection)
            for record in envelope.records:
                modified_at = (
                    recorded_at
                    if record.source_modified_unix_milliseconds is None
                    else datetime.fromtimestamp(
                        record.source_modified_unix_milliseconds / 1000, tz=recorded_at.tzinfo
                    )
                )
                observed = observe_object(
                    connection,
                    source_id=authority.source_id,
                    native_locator=record.id,
                    kind=object_kind,
                    fingerprint=record.source_revision,
                    modified_at=modified_at,
                    media_type=media_type,
                    size_bytes=len(record.payload),
                )
                _, created = repository._record_evidence_with_created(
                    version_id=observed.version_id,
                    kind=object_kind,
                    payload=bytes(record.payload),
                    recorded_at=recorded_at,
                )
                repository.record_observation(
                    observation_id=issue_identifier(IdKind.SOURCE_OBSERVATION),
                    source_object_id=observed.source_object_id,
                    version_id=observed.version_id,
                    bucket_id=authority.bucket_id,
                    observed_at=recorded_at,
                )
                if source_kind is ContractNativeSourceKind.CONTACTS:
                    repository.record_membership(
                        ContactMembership(
                            membership_id=issue_identifier(IdKind.SOURCE_MEMBERSHIP),
                            group_bucket_id=authority.bucket_id,
                            contact_object_id=observed.source_object_id,
                            version_id=observed.version_id,
                            observed_at=recorded_at,
                        )
                    )
                outcomes.append((observed.version_id, created))
        return tuple(outcomes)


class SqlNativeReviewProposalRouter:
    """Route existing consequential proposals to Review with exact source lineage.

    The candidate source is the bounded extraction boundary: it may name an
    already-persisted proposal for one source version. This adapter can only
    open Review cases and persist lineage; it exposes no decision or promotion
    operation.
    """

    def __init__(
        self,
        engine: Engine,
        candidates_for_version: Callable[[str], tuple[str, ...]],
    ) -> None:
        self._engine = engine
        self._candidates_for_version = candidates_for_version

    def open_review_proposals(self, version_ids: tuple[str, ...]) -> tuple[str, ...]:
        if version_ids != tuple(dict.fromkeys(version_ids)):
            raise ValueError("native Review routing requires unique source versions")
        routed: list[str] = []
        with self._engine.begin() as connection:
            for source_version_id in version_ids:
                validate_identifier(source_version_id, IdKind.VERSION)
                proposal_ids = self._candidates_for_version(source_version_id)
                if proposal_ids != tuple(dict.fromkeys(proposal_ids)):
                    raise ValueError("native enrichment candidates must be unique")
                for proposal_id in proposal_ids:
                    validate_identifier(proposal_id, IdKind.PROPOSAL)
                    proposal_exists = connection.execute(
                        select(capture_proposals.c.proposal_id).where(
                            capture_proposals.c.proposal_id == proposal_id
                        )
                    ).scalar_one_or_none()
                    if proposal_exists is None:
                        raise LookupError("native enrichment candidate is not a stored proposal")
                    review_case_id = open_review_case(connection, proposal_id)
                    if review_case_id is None:
                        continue
                    prior = connection.execute(
                        select(native_source_review_routes.c.review_case_id).where(
                            native_source_review_routes.c.source_version_id == source_version_id,
                            native_source_review_routes.c.proposal_id == proposal_id,
                        )
                    ).scalar_one_or_none()
                    if prior is not None:
                        if str(prior) != review_case_id:
                            raise NativePersistenceConflictError(
                                "a proposal cannot be rebound to another Review case"
                            )
                    else:
                        connection.execute(
                            insert(native_source_review_routes).values(
                                source_version_id=source_version_id,
                                proposal_id=proposal_id,
                                review_case_id=review_case_id,
                                routed_at=func.now(),
                            )
                        )
                    routed.append(proposal_id)
        return tuple(routed)
