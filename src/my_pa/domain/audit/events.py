"""Audit events.

An audit event records that something happened and how it was decided. It never
records what was in it. There is no field on `AuditEvent` that can hold a
document body, extracted text, snippet, query string, filesystem path, contact
detail, credential, database URL, or host name, so redaction cannot be forgotten
at a call site (`docs/specs`, section 11).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import DenialReason, PolicyDecision

__all__ = ["AuditEvent", "AuditOutcome", "audit_event_for"]


class AuditOutcome(StrEnum):
    """How an audited operation ended."""

    ALLOWED = "allowed"
    DENIED = "denied"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One redacted audit record.

    Counts are bounded aggregates. `denial_reason` is a stable category, not a
    free-text message, so it cannot become a leak channel.
    """

    audit_id: str
    correlation_id: str
    principal_id: str
    capability: Capability
    purpose: Purpose
    outcome: AuditOutcome
    policy_version: str
    recorded_at: datetime
    denial_reason: DenialReason | None = None
    item_count: int = 0
    duration_ms: int = 0
    scope_source_id_count: int = 0
    metadata: dict[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        validate_identifier(self.audit_id, IdKind.AUDIT)
        validate_identifier(self.correlation_id, IdKind.CORRELATION)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        if self.outcome is AuditOutcome.DENIED and self.denial_reason is None:
            raise ValueError("a denied audit event must record a denial reason")
        if self.outcome is not AuditOutcome.DENIED and self.denial_reason is not None:
            raise ValueError("only a denied audit event may record a denial reason")
        for count in (self.item_count, self.duration_ms, self.scope_source_id_count):
            if count < 0:
                raise ValueError("audit counts cannot be negative")
        object.__setattr__(self, "recorded_at", ensure_utc(self.recorded_at))
        object.__setattr__(self, "metadata", dict(self.metadata))


def audit_event_for(
    *,
    audit_id: str,
    correlation_id: str,
    principal_id: str,
    capability: Capability,
    purpose: Purpose,
    decision: PolicyDecision,
    recorded_at: datetime,
    item_count: int = 0,
    duration_ms: int = 0,
    scope_source_id_count: int = 0,
) -> AuditEvent:
    """Build the audit event implied by `decision`.

    Deriving outcome and reason from the decision keeps the audit trail and the
    policy result from drifting apart.
    """
    return AuditEvent(
        audit_id=audit_id,
        correlation_id=correlation_id,
        principal_id=principal_id,
        capability=capability,
        purpose=purpose,
        outcome=AuditOutcome.ALLOWED if decision.allowed else AuditOutcome.DENIED,
        policy_version=decision.policy_version,
        recorded_at=recorded_at,
        denial_reason=decision.reason,
        item_count=item_count,
        duration_ms=duration_ms,
        scope_source_id_count=scope_source_id_count,
    )
