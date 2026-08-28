"""Dedicated SQL persistence for Relationship Intelligence re-enrichment.

Tables are injected until the integration owner adds the shared ``tables.py``
declarations and additive migration. This adapter intentionally does not reuse
``capture_jobs``: capture processing and RI invalidation bind different
subjects, versions, terminal states, and workers.
"""

from __future__ import annotations

import re
import secrets
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final, Protocol

from sqlalchemy import Connection, Table, and_, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.relationship.reenrichment import (
    BindingVersion,
    ReenrichmentBinding,
    ReenrichmentState,
    ReenrichmentSubject,
    ReenrichmentSubjectKind,
    ReenrichmentTrigger,
    ReenrichmentWork,
    StaleBindingReason,
)
from my_pa.infrastructure.persistence import conflicting_row

__all__ = [
    "DEFAULT_REENRICHMENT_LEASE_SECONDS",
    "ReenrichmentTables",
    "SqlReenrichmentWorkRepository",
    "VersionObservation",
]

DEFAULT_REENRICHMENT_LEASE_SECONDS: Final = 300
_OWNER = re.compile(r"\A[A-Za-z0-9_-]{4,64}\Z")
_SAFE_TOKEN = re.compile(r"\A[a-z][a-z0-9_]{0,63}\Z")
_QUEUED = "queued"
_RUNNING = "running"
_SUCCEEDED = "succeeded"
_STALE = "stale"
_FAILED = "failed"


class _Value(Protocol):
    value: str


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

    def complete(self, principal_id: str, work_id: str, *, owner: str, at: datetime) -> bool:
        return self._terminal(principal_id, work_id, owner=owner, state=_SUCCEEDED, at=at)

    def mark_stale(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        reasons: Sequence[_Value],
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

    def _terminal(
        self,
        principal_id: str,
        work_id: str,
        *,
        owner: str,
        state: str,
        at: datetime,
        stale_reasons: list[str] | None = None,
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
                completed_at=moment,
                updated_at=moment,
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
        )
