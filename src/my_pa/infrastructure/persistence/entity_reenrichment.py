"""Dedicated SQL persistence for Relationship Intelligence re-enrichment.

Tables are injected until the integration owner adds the shared ``tables.py``
declarations and additive migration. This adapter intentionally does not reuse
``capture_jobs``: capture processing and RI invalidation bind different
subjects, versions, terminal states, and workers.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from sqlalchemy import Connection, Table, and_, func, or_, select, tuple_
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.reenrichment import (
    BindingCurrency,
    BindingVersion,
    CurrentReenrichmentBindings,
    ReenrichmentBinding,
    ReenrichmentLimitation,
    ReenrichmentState,
    ReenrichmentSubject,
    ReenrichmentSubjectKind,
    ReenrichmentTrigger,
    ReenrichmentWork,
    StaleBindingReason,
    assess_currency,
)
from my_pa.infrastructure.persistence import conflicting_row

__all__ = [
    "DEFAULT_REENRICHMENT_LEASE_SECONDS",
    "ReenrichmentTables",
    "SqlCurrentReenrichmentBindings",
    "SqlReenrichmentWorkRepository",
    "VersionObservation",
]

DEFAULT_REENRICHMENT_LEASE_SECONDS: Final = 300
_OWNER = re.compile(r"\A[A-Za-z0-9_-]{4,64}\Z")
_SAFE_TOKEN = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")
_QUEUED = "queued"
_RUNNING = "running"
_SUCCEEDED = "succeeded"
_PARTIAL = "partial"
_STALE = "stale"
_FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ReenrichmentTables:
    """The three additive tables supplied by the shared schema owner."""

    work: Table
    subjects: Table
    version_watermarks: Table


@dataclass(frozen=True, slots=True)
class VersionObservation:
    previous_version: str | None
    current_version: str

    @property
    def changed(self) -> bool:
        return self.previous_version is not None and self.previous_version != self.current_version


class SqlCurrentReenrichmentBindings:
    """Current versions read and locked on the worker transaction."""

    def __init__(self, connection: Connection, tables: ReenrichmentTables) -> None:
        self.connection = connection
        self._tables = tables
        self._locked: dict[tuple[ReenrichmentSubjectKind, str], str | None] = {}

    def lock(self, binding: ReenrichmentBinding) -> None:
        for subject in binding.subjects:
            self._locked[(subject.kind, subject.subject_id)] = self._read_subject(
                binding.principal_id, subject.kind, subject.subject_id, lock=True
            )
        table = self._tables.version_watermarks
        keys = [
            *(("input", item.key) for item in binding.input_versions),
            *(("producer", item.key) for item in binding.producer_versions),
            ("policy", "current"),
        ]
        if keys:
            self.connection.execute(
                select(table.c.namespace, table.c.binding_key)
                .where(
                    table.c.principal_id == binding.principal_id,
                    tuple_(table.c.namespace, table.c.binding_key).in_(keys),
                )
                .with_for_update(of=table)
            ).all()

    def subject_version(
        self, principal_id: str, kind: ReenrichmentSubjectKind, subject_id: str
    ) -> str | None:
        key = (kind, subject_id)
        if key in self._locked:
            return self._locked[key]
        return self._read_subject(principal_id, kind, subject_id, lock=False)

    def input_version(self, principal_id: str, key: str) -> str | None:
        return self._watermark(principal_id, "input", key)

    def producer_version(self, principal_id: str, key: str) -> str | None:
        return self._watermark(principal_id, "producer", key)

    def policy_version(self, principal_id: str) -> str | None:
        return self._watermark(principal_id, "policy", "current")

    def _watermark(self, principal_id: str, namespace: str, key: str) -> str | None:
        table = self._tables.version_watermarks
        return self.connection.execute(
            select(table.c.version).where(
                table.c.principal_id == principal_id,
                table.c.namespace == namespace,
                table.c.binding_key == key,
            )
        ).scalar_one_or_none()

    def _read_subject(
        self,
        principal_id: str,
        kind: ReenrichmentSubjectKind,
        subject_id: str,
        *,
        lock: bool,
    ) -> str | None:
        # Imported lazily to keep this adapter's injectable queue tables useful
        # to focused tests without creating a second schema declaration.
        from my_pa.infrastructure.persistence import tables as schema

        if kind is ReenrichmentSubjectKind.PRINCIPAL:
            return "1" if subject_id == principal_id else None
        if kind is ReenrichmentSubjectKind.ENTITY:
            table, id_column, version = (
                schema.entities,
                schema.entities.c.entity_id,
                schema.entities.c.version,
            )
            ownership = schema.entities.c.principal_id
        elif kind is ReenrichmentSubjectKind.ALIAS:
            table, id_column, version = (
                schema.entity_aliases,
                schema.entity_aliases.c.alias_id,
                schema.entity_aliases.c.version,
            )
            ownership = schema.entity_aliases.c.principal_id
        elif kind is ReenrichmentSubjectKind.ASSIGNMENT:
            table, id_column, version = (
                schema.entity_assignments,
                schema.entity_assignments.c.assignment_id,
                schema.entity_assignments.c.version,
            )
            ownership = schema.entity_assignments.c.principal_id
        elif kind is ReenrichmentSubjectKind.RELATIONSHIP:
            table, id_column, version = (
                schema.entity_relationships,
                schema.entity_relationships.c.relationship_id,
                schema.entity_relationships.c.version,
            )
            ownership = schema.entity_relationships.c.principal_id
        elif kind is ReenrichmentSubjectKind.CAPTURE:
            table, id_column, version = (
                schema.captures,
                schema.captures.c.capture_id,
                schema.capture_versions.c.version_number,
            )
            ownership = schema.captures.c.owner_principal_id
            statement = (
                select(version)
                .select_from(table.join(schema.capture_versions))
                .where(id_column == subject_id, ownership == principal_id)
                .order_by(version.desc())
                .limit(1)
            )
            if lock:
                statement = statement.with_for_update(of=table)
            value = self.connection.execute(statement).scalar_one_or_none()
            return None if value is None else str(value)
        elif kind is ReenrichmentSubjectKind.CAPTURE_VERSION:
            table, id_column, version = (
                schema.capture_versions,
                schema.capture_versions.c.version_id,
                schema.capture_versions.c.version_number,
            )
            ownership = schema.capture_versions.c.owner_principal_id
        elif kind is ReenrichmentSubjectKind.PROPOSAL:
            table, id_column, version = (
                schema.entity_proposals,
                schema.entity_proposals.c.proposal_id,
                schema.entity_proposals.c.state,
            )
            ownership = schema.entity_proposals.c.principal_id
        elif kind is ReenrichmentSubjectKind.REVIEW_DECISION:
            table, id_column, version = (
                schema.entity_proposal_review_decisions,
                schema.entity_proposal_review_decisions.c.decision_id,
                schema.entity_proposal_review_decisions.c.sequence,
            )
            ownership = schema.entity_proposal_review_decisions.c.principal_id
        elif kind is ReenrichmentSubjectKind.IDENTITY_OPERATION:
            table, id_column, version = (
                schema.entity_identity_operations,
                schema.entity_identity_operations.c.identity_operation_id,
                schema.entity_identity_operations.c.effects_digest,
            )
            ownership = schema.entity_identity_operations.c.principal_id
        elif kind is ReenrichmentSubjectKind.SOURCE_VERSION:
            table, id_column, version = (
                schema.source_object_versions,
                schema.source_object_versions.c.version_id,
                schema.source_object_versions.c.version_id,
            )
            ownership = None
        elif kind is ReenrichmentSubjectKind.SOURCE_OBJECT:
            table, id_column, version = (
                schema.source_objects,
                schema.source_objects.c.source_object_id,
                schema.source_object_versions.c.version_id,
            )
            ownership = None
            statement = (
                select(version)
                .select_from(table.join(schema.source_object_versions))
                .where(id_column == subject_id)
                .order_by(schema.source_object_versions.c.observed_at.desc(), version.desc())
                .limit(1)
            )
            if lock:
                statement = statement.with_for_update(of=table)
            value = self.connection.execute(statement).scalar_one_or_none()
            return None if value is None else str(value)
        else:  # pragma: no cover - closed enum exhaustiveness
            raise AssertionError(kind)
        criteria = [id_column == subject_id]
        if ownership is not None:
            criteria.append(ownership == principal_id)
        statement = select(version).where(*criteria)
        if lock:
            statement = statement.with_for_update(of=table)
        value = self.connection.execute(statement).scalar_one_or_none()
        return None if value is None else str(value)


def _owner(value: str) -> str:
    if not _OWNER.fullmatch(value):
        raise ValueError("a lease owner is a bounded non-identifying token")
    return value


class SqlReenrichmentWorkRepository:
    """Principal-scoped registration, leasing, retry, and completion."""

    def __init__(self, connection: Connection, tables: ReenrichmentTables) -> None:
        self._connection = connection
        self._tables = tables

    def register(self, binding: ReenrichmentBinding, *, at: datetime) -> ReenrichmentWork:
        moment = ensure_utc(at)
        self._lock_principal(binding.principal_id)
        table = self._tables.work
        work_id = f"erwk_{secrets.token_hex(12)}"
        inserted = self._connection.execute(
            pg_insert(table)
            .values(
                work_id=work_id,
                principal_id=binding.principal_id,
                trigger=binding.trigger.value,
                cause_record_id=binding.cause_record_id,
                binding_sha256=binding.binding_sha256,
                input_versions=[
                    {"key": item.key, "version": item.version} for item in binding.input_versions
                ],
                producer_versions=[
                    {"key": item.key, "version": item.version} for item in binding.producer_versions
                ],
                policy_version=binding.policy_version,
                state=_QUEUED,
                attempt_count=0,
                max_attempts=3,
                created_at=moment,
                updated_at=moment,
                next_attempt_at=moment,
            )
            .on_conflict_do_nothing(constraint="one_entity_reenrichment_binding")
            .returning(table.c.work_id)
        ).scalar_one_or_none()
        if inserted is not None:
            self._connection.execute(
                self._tables.subjects.insert(),
                [
                    {
                        "work_id": work_id,
                        "principal_id": binding.principal_id,
                        "sequence": sequence,
                        "subject_kind": item.kind.value,
                        "subject_id": item.subject_id,
                        "subject_version": item.version,
                    }
                    for sequence, item in enumerate(binding.subjects, start=1)
                ],
            )
            return self._required(binding.principal_id, work_id)
        prior = self._connection.execute(
            select(table.c.work_id).where(
                table.c.principal_id == binding.principal_id,
                table.c.binding_sha256 == binding.binding_sha256,
            )
        ).scalar_one_or_none()
        prior_id = str(conflicting_row(prior, "knowledge.entity_reenrichment_work"))
        return self._required(binding.principal_id, prior_id)

    def _lock_principal(self, principal_id: str) -> None:
        """Serialize invalidation registration and application per Principal."""
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        self._connection.execute(
            select(func.pg_advisory_xact_lock(func.hashtextextended(principal_id, 0)))
        ).scalar_one()

    def get(self, principal_id: str, work_id: str) -> ReenrichmentWork | None:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        row = self._connection.execute(
            select(self._tables.work).where(
                self._tables.work.c.principal_id == principal_id,
                self._tables.work.c.work_id == work_id,
            )
        ).one_or_none()
        return None if row is None else self._hydrate(row)

    def _required(self, principal_id: str, work_id: str) -> ReenrichmentWork:
        found = self.get(principal_id, work_id)
        if found is None:  # pragma: no cover - insert/read invariant
            raise RuntimeError("registered re-enrichment work cannot be read back")
        return found

    def claim(
        self,
        *,
        owner: str,
        at: datetime,
        lease_seconds: int = DEFAULT_REENRICHMENT_LEASE_SECONDS,
    ) -> ReenrichmentWork | None:
        owner = _owner(owner)
        moment = ensure_utc(at)
        if not 1 <= lease_seconds <= 900:
            raise ValueError("a re-enrichment lease is bounded")
        table = self._tables.work
        # A worker that spent its final attempt until the lease expired cannot
        # be claimed again, but it also must not remain ``running`` forever.
        # Terminalize those rows under the same transaction that searches for
        # the next claim so operational status has no stranded final attempt.
        self._connection.execute(
            table.update()
            .where(
                table.c.state == _RUNNING,
                table.c.lease_expires_at <= moment,
                table.c.attempt_count >= table.c.max_attempts,
            )
            .values(
                state=_FAILED,
                lease_owner=None,
                lease_expires_at=None,
                last_error_code="lease_expired",
                completed_at=moment,
                updated_at=moment,
            )
        )
        candidate = self._connection.execute(
            select(table.c.work_id, table.c.principal_id)
            .where(
                or_(
                    and_(
                        table.c.state == _QUEUED,
                        table.c.next_attempt_at <= moment,
                    ),
                    and_(
                        table.c.state == _RUNNING,
                        table.c.lease_expires_at <= moment,
                    ),
                ),
                table.c.attempt_count < table.c.max_attempts,
            )
            .order_by(table.c.next_attempt_at, table.c.created_at, table.c.work_id)
            .limit(1)
            .with_for_update(skip_locked=True, of=table)
        ).one_or_none()
        if candidate is None:
            return None
        self._connection.execute(
            table.update()
            .where(
                table.c.work_id == candidate.work_id,
                table.c.principal_id == candidate.principal_id,
            )
            .values(
                state=_RUNNING,
                attempt_count=table.c.attempt_count + 1,
                lease_owner=owner,
                lease_expires_at=moment + timedelta(seconds=lease_seconds),
                updated_at=moment,
            )
        )
        return self._required(str(candidate.principal_id), str(candidate.work_id))

    def apply_claimed(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        current: CurrentReenrichmentBindings,
        apply: Callable[[ReenrichmentBinding, str], None],
        at: datetime,
    ) -> BindingCurrency:
        """Validate, mutate, and settle under one transaction and lock set.

        The row lock prevents reclaim while the callback runs. PostgreSQL's
        wall clock, rather than the caller's pre-callback timestamp, gates both
        entry and completion. The Principal advisory lock is shared with every
        registration, closing the current-binding race. A savepoint lets a
        post-callback currency failure discard the derived mutation before the
        work is durably marked stale.
        """
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        ensure_utc(at)
        owner = _owner(owner)
        if not isinstance(current, SqlCurrentReenrichmentBindings):
            raise TypeError("SQL re-enrichment requires its transactional current binding view")
        if current.connection is not self._connection:
            raise ValueError("re-enrichment currency and application share one transaction")
        self._lock_principal(principal_id)
        table = self._tables.work
        row = self._connection.execute(
            select(table)
            .where(
                table.c.principal_id == principal_id,
                table.c.work_id == work_id,
                table.c.state == _RUNNING,
                table.c.lease_owner == owner,
                table.c.lease_expires_at > func.clock_timestamp(),
            )
            .with_for_update(of=table)
        ).one_or_none()
        if row is None:
            raise ValueError("re-enrichment application requires this worker's live claim")
        work = self._hydrate(row)
        current.lock(work.binding)
        currency = assess_currency(work.binding, current)
        if not currency.is_current:
            if not self._terminal_now(
                principal_id,
                work_id,
                owner=owner,
                state=_STALE,
                stale_reasons=[reason.value for reason in currency.reasons],
            ):
                raise RuntimeError("the re-enrichment lease was lost before stale completion")
            return currency

        post_apply_currency = currency
        lost_lease = False
        with self._connection.begin_nested() as application:
            apply(work.binding, work.binding.binding_sha256)
            post_apply_currency = assess_currency(work.binding, current)
            if not post_apply_currency.is_current:
                # The savepoint contains every derived write made by the
                # callback. Rolling it back before settling stale means a
                # version change can never leave an untracked partial effect.
                application.rollback()
            elif not self._terminal_now(principal_id, work_id, owner=owner, state=_SUCCEEDED):
                # The callback may have crossed the lease deadline. Settlement
                # belongs inside the same savepoint as the mutation: if the
                # database clock says the fence is gone, discard the mutation
                # before reporting the lost claim, even when a caller catches
                # the resulting exception and commits the outer transaction.
                application.rollback()
                lost_lease = True
        if lost_lease:
            raise RuntimeError("the re-enrichment lease expired before atomic completion")
        if not post_apply_currency.is_current:
            if not self._terminal_now(
                principal_id,
                work_id,
                owner=owner,
                state=_STALE,
                stale_reasons=[reason.value for reason in post_apply_currency.reasons],
            ):
                raise RuntimeError("the re-enrichment lease was lost before stale completion")
            return post_apply_currency
        return post_apply_currency

    def complete(self, principal_id: str, work_id: str, *, owner: str, at: datetime) -> bool:
        return self._terminal(principal_id, work_id, owner=owner, state=_SUCCEEDED, at=at)

    def mark_stale(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        reasons: Sequence[StaleBindingReason],
        at: datetime,
    ) -> bool:
        values = sorted({reason.value for reason in reasons})
        if not values:
            raise ValueError("stale work states why")
        return self._terminal(
            principal_id,
            work_id,
            owner=owner,
            state=_STALE,
            at=at,
            stale_reasons=values,
        )

    def mark_partial(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        limitations: Sequence[ReenrichmentLimitation],
        at: datetime,
    ) -> bool:
        """Settle work that did some of what it was registered for, and says which part.

        The third terminal outcome beside `mark_stale` and `fail`, and it exists
        because the two of them plus `complete` could not express it: a
        re-enrichment that produced some of its intended effects had to report
        `succeeded` -- claiming effects it did not produce -- or `failed`,
        discarding the ones it did. `partial_reenrichment_states_its_limitations`
        makes the state and the column that explains it true together, so this
        settlement cannot land without saying what it left undone, exactly as
        `mark_stale` cannot land without saying what moved.
        """
        values = sorted({limitation.value for limitation in limitations})
        if not values:
            raise ValueError("partial work states its limitations")
        return self._terminal(
            principal_id,
            work_id,
            owner=owner,
            state=_PARTIAL,
            at=at,
            limitations=values,
        )

    def _terminal(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        state: str,
        at: datetime,
        stale_reasons: list[str] | None = None,
        limitations: list[str] | None = None,
    ) -> bool:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        moment = ensure_utc(at)
        table = self._tables.work
        result = self._connection.execute(
            table.update()
            .where(
                table.c.principal_id == principal_id,
                table.c.work_id == work_id,
                table.c.state == _RUNNING,
                table.c.lease_owner == _owner(owner),
                table.c.lease_expires_at > moment,
            )
            .values(
                state=state,
                lease_owner=None,
                lease_expires_at=None,
                stale_reasons=stale_reasons,
                limitations=limitations,
                completed_at=moment,
                updated_at=moment,
            )
        )
        return result.rowcount == 1

    def _terminal_now(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        state: str,
        stale_reasons: list[str] | None = None,
    ) -> bool:
        table = self._tables.work
        result = self._connection.execute(
            table.update()
            .where(
                table.c.principal_id == principal_id,
                table.c.work_id == work_id,
                table.c.state == _RUNNING,
                table.c.lease_owner == owner,
                table.c.lease_expires_at > func.clock_timestamp(),
            )
            .values(
                state=state,
                lease_owner=None,
                lease_expires_at=None,
                stale_reasons=stale_reasons,
                completed_at=func.clock_timestamp(),
                updated_at=func.clock_timestamp(),
            )
        )
        return result.rowcount == 1

    def fail(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        error_code: str,
        retryable: bool,
        at: datetime,
        retry_after_seconds: int = 30,
    ) -> bool:
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if not _SAFE_TOKEN.fullmatch(error_code) or not 0 <= retry_after_seconds <= 3600:
            raise ValueError("failure metadata is safe and bounded")
        moment = ensure_utc(at)
        table = self._tables.work
        row = self._connection.execute(
            select(table.c.attempt_count, table.c.max_attempts)
            .where(
                table.c.principal_id == principal_id,
                table.c.work_id == work_id,
                table.c.state == _RUNNING,
                table.c.lease_owner == _owner(owner),
                table.c.lease_expires_at > moment,
            )
            .with_for_update(of=table)
        ).one_or_none()
        if row is None:
            return False
        retry = retryable and int(row.attempt_count) < int(row.max_attempts)
        result = self._connection.execute(
            table.update()
            .where(table.c.principal_id == principal_id, table.c.work_id == work_id)
            .values(
                state=(_QUEUED if retry else _FAILED),
                lease_owner=None,
                lease_expires_at=None,
                last_error_code=error_code,
                next_attempt_at=moment + timedelta(seconds=retry_after_seconds),
                completed_at=None if retry else moment,
                updated_at=moment,
            )
        )
        return result.rowcount == 1

    def observe_version(
        self,
        principal_id: str,
        *,
        namespace: str,
        key: str,
        version: str,
        at: datetime,
    ) -> VersionObservation:
        """Establish or advance one server-owned producer/policy watermark."""
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        if not _SAFE_TOKEN.fullmatch(namespace) or not _SAFE_TOKEN.fullmatch(key):
            raise ValueError("watermark names are safe bounded tokens")
        moment = ensure_utc(at)
        self._lock_principal(principal_id)
        table = self._tables.version_watermarks
        row = self._connection.execute(
            select(table.c.version)
            .where(
                table.c.principal_id == principal_id,
                table.c.namespace == namespace,
                table.c.binding_key == key,
            )
            .with_for_update(of=table)
        ).one_or_none()
        previous = None if row is None else str(row.version)
        if row is None:
            self._connection.execute(
                table.insert().values(
                    principal_id=principal_id,
                    namespace=namespace,
                    binding_key=key,
                    version=version,
                    updated_at=moment,
                )
            )
        elif previous != version:
            self._connection.execute(
                table.update()
                .where(
                    table.c.principal_id == principal_id,
                    table.c.namespace == namespace,
                    table.c.binding_key == key,
                )
                .values(version=version, updated_at=moment)
            )
        return VersionObservation(previous, version)

    def _hydrate(self, row: object) -> ReenrichmentWork:
        principal_id = str(row.principal_id)  # type: ignore[attr-defined]
        work_id = str(row.work_id)  # type: ignore[attr-defined]
        subjects = self._connection.execute(
            select(self._tables.subjects)
            .where(
                self._tables.subjects.c.principal_id == principal_id,
                self._tables.subjects.c.work_id == work_id,
            )
            .order_by(self._tables.subjects.c.sequence)
        ).all()
        binding = ReenrichmentBinding(
            principal_id=principal_id,
            trigger=ReenrichmentTrigger(str(row.trigger)),  # type: ignore[attr-defined]
            cause_record_id=str(row.cause_record_id),  # type: ignore[attr-defined]
            subjects=tuple(
                ReenrichmentSubject(
                    ReenrichmentSubjectKind(str(item.subject_kind)),
                    str(item.subject_id),
                    str(item.subject_version),
                )
                for item in subjects
            ),
            input_versions=tuple(
                BindingVersion(str(item["key"]), str(item["version"]))
                for item in row.input_versions  # type: ignore[attr-defined]
            ),
            producer_versions=tuple(
                BindingVersion(str(item["key"]), str(item["version"]))
                for item in row.producer_versions  # type: ignore[attr-defined]
            ),
            policy_version=str(row.policy_version),  # type: ignore[attr-defined]
        )
        if binding.binding_sha256 != str(row.binding_sha256):  # type: ignore[attr-defined]
            raise RuntimeError("a persisted re-enrichment binding digest does not verify")
        return ReenrichmentWork(
            work_id=work_id,
            binding=binding,
            state=ReenrichmentState(str(row.state)),  # type: ignore[attr-defined]
            attempt_count=int(row.attempt_count),  # type: ignore[attr-defined]
            max_attempts=int(row.max_attempts),  # type: ignore[attr-defined]
            created_at=row.created_at,  # type: ignore[attr-defined]
            updated_at=row.updated_at,  # type: ignore[attr-defined]
            lease_owner=getattr(row, "lease_owner", None),
            lease_expires_at=getattr(row, "lease_expires_at", None),
            completed_at=getattr(row, "completed_at", None),
            stale_reasons=tuple(
                StaleBindingReason(value) for value in (getattr(row, "stale_reasons", None) or ())
            ),
            last_error_code=getattr(row, "last_error_code", None),
            limitations=tuple(
                ReenrichmentLimitation(v) for v in (getattr(row, "limitations", None) or ())
            ),
        )
