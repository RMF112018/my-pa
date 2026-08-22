"""Content-free persisted state for the two-phase Task bulk protocol."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = ["TaskBulkOperation"]


@dataclass(frozen=True, slots=True)
class TaskBulkOperation:
    bulk_operation_id: str
    principal_id: str
    preview_idempotency_key: str
    request_digest: str
    previewed_at: datetime
    expires_at: datetime
    preview_affected: int = 0
    preview_no_op: int = 0
    confirmed_at: datetime | None = None
    confirm_idempotency_key: str | None = None
    affected: int | None = None
    no_op: int | None = None
    rejected: int | None = None
    history_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        validate_identifier(self.bulk_operation_id, IdKind.BULK_OPERATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if not re.fullmatch(r"[A-Za-z0-9_-]{8,128}", self.preview_idempotency_key):
            raise ValueError("a preview key is opaque and bounded")
        if self.confirm_idempotency_key is not None and not re.fullmatch(
            r"[A-Za-z0-9_-]{8,128}", self.confirm_idempotency_key
        ):
            raise ValueError("a confirm key is opaque and bounded")
        if not re.fullmatch(r"[0-9a-f]{64}", self.request_digest):
            raise ValueError("a bulk request digest is SHA-256")
        ensure_utc(self.previewed_at)
        ensure_utc(self.expires_at)
        if self.confirmed_at is not None:
            ensure_utc(self.confirmed_at)
        for history_id in self.history_ids:
            validate_identifier(history_id, IdKind.TASK_HISTORY)
        if min(self.preview_affected, self.preview_no_op) < 0:
            raise ValueError("bulk preview counts are non-negative")
        preview_total = self.preview_affected + self.preview_no_op
        if not 1 <= preview_total <= 100:
            raise ValueError("a bulk preview contains between one and one hundred tasks")
        confirmed = self.confirmed_at is not None
        result_present = (
            self.affected is not None or self.no_op is not None or self.rejected is not None
        )
        if confirmed != result_present:
            raise ValueError("bulk confirmation and result counts are paired")
        if confirmed:
            if None in {self.affected, self.no_op, self.rejected}:
                raise ValueError("a confirmed bulk operation has complete result counts")
            if min(self.affected or 0, self.no_op or 0, self.rejected or 0) < 0:
                raise ValueError("bulk confirmation counts are non-negative")
            if (
                self.affected != self.preview_affected
                or self.no_op != self.preview_no_op
                or self.rejected != 0
                or len(self.history_ids) != preview_total
            ):
                raise ValueError("bulk confirmation preserves the exact preview receipt")
        elif self.history_ids:
            raise ValueError("an unconfirmed bulk operation has no history receipts")
