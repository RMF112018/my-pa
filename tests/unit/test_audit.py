"""Audit events are redacted by construction."""

from __future__ import annotations

import dataclasses
from datetime import UTC, datetime

import pytest

from my_pa.domain.audit.events import AuditEvent, AuditOutcome, audit_event_for
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import POLICY_VERSION, DenialReason, PolicyDecision

RECORDED_AT = datetime(2026, 7, 30, 20, 0, 0, tzinfo=UTC)

#: Substrings that must never be able to appear in an audit record.
FORBIDDEN_FIELD_TOKENS = (
    "body",
    "content",
    "text",
    "snippet",
    "query",
    "path",
    "contact",
    "credential",
    "password",
    "token",
    "secret",
    "url",
    "host",
    "email",
    "filename",
)


def _event(**overrides: object) -> AuditEvent:
    base: dict[str, object] = {
        "audit_id": "audit_abc123def456",
        "correlation_id": "corr_abc123def456",
        "principal_id": "prn_gateway00001",
        "capability": Capability.KNOWLEDGE_SEARCH,
        "purpose": Purpose.KNOWLEDGE_SEARCH,
        "outcome": AuditOutcome.ALLOWED,
        "policy_version": POLICY_VERSION,
        "recorded_at": RECORDED_AT,
    }
    base.update(overrides)
    return AuditEvent(**base)  # type: ignore[arg-type]


def test_audit_event_has_no_field_that_could_hold_sensitive_payload() -> None:
    names = {field.name for field in dataclasses.fields(AuditEvent)}
    for name in names:
        for token in FORBIDDEN_FIELD_TOKENS:
            assert token not in name, f"audit field {name!r} could carry sensitive payload"


def test_audit_event_serialisation_contains_only_safe_values() -> None:
    event = _event(item_count=3, duration_ms=12, scope_source_id_count=1)
    rendered = repr(dataclasses.asdict(event)).lower()
    for token in ("/users/", "select ", "password", "bearer ", "@", "://"):
        assert token not in rendered


def test_denied_event_requires_a_reason() -> None:
    with pytest.raises(ValueError, match="must record a denial reason"):
        _event(outcome=AuditOutcome.DENIED)


def test_allowed_event_cannot_carry_a_reason() -> None:
    with pytest.raises(ValueError, match="only a denied audit event"):
        _event(denial_reason=DenialReason.OPERATOR_REQUIRED)


def test_counts_cannot_be_negative() -> None:
    with pytest.raises(ValueError, match="cannot be negative"):
        _event(item_count=-1)


def test_naive_recorded_at_is_rejected() -> None:
    with pytest.raises(ValueError, match="timezone-aware"):
        _event(recorded_at=datetime(2026, 7, 30, 20, 0, 0))


def test_event_derived_from_a_denial_matches_the_decision() -> None:
    decision = PolicyDecision(
        allowed=False, policy_version=POLICY_VERSION, reason=DenialReason.OPERATOR_REQUIRED
    )
    event = audit_event_for(
        audit_id="audit_abc123def456",
        correlation_id="corr_abc123def456",
        principal_id="prn_gateway00001",
        capability=Capability.SOURCES_ENROLL,
        purpose=Purpose.BOUNDED_ENROLLMENT,
        decision=decision,
        recorded_at=RECORDED_AT,
    )
    assert event.outcome is AuditOutcome.DENIED
    assert event.denial_reason is DenialReason.OPERATOR_REQUIRED
    assert event.policy_version == POLICY_VERSION


def test_event_derived_from_an_allow_records_no_reason() -> None:
    decision = PolicyDecision(allowed=True, policy_version=POLICY_VERSION)
    event = audit_event_for(
        audit_id="audit_abc123def456",
        correlation_id="corr_abc123def456",
        principal_id="prn_gateway00001",
        capability=Capability.KNOWLEDGE_SEARCH,
        purpose=Purpose.KNOWLEDGE_SEARCH,
        decision=decision,
        recorded_at=RECORDED_AT,
    )
    assert event.outcome is AuditOutcome.ALLOWED
    assert event.denial_reason is None


def test_denial_reasons_are_stable_categories_not_free_text() -> None:
    for reason in DenialReason:
        assert reason.value.replace("_", "").isalpha()


def test_event_is_frozen() -> None:
    event = _event()
    with pytest.raises(dataclasses.FrozenInstanceError):
        event.item_count = 5  # type: ignore[misc]
