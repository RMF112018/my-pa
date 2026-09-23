"""Derive the ChatLLM full-data profile and compare it to durable grants.

This module does not mutate grants, OAuth clients, or runtime composition.
Desired capabilities come from `derive_available_capabilities` intersected with
ChatLLM data-management classification. `composed_capabilities` is not mutation
authority.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal
from uuid import UUID

from my_pa.application.service import (
    ApplicationCompositionState,
    derive_available_capabilities,
)
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
    is_chatllm_data_management,
)
from my_pa.domain.identity.operation import (
    REMOTE_CAPABILITY_VERSION,
    Capability,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.purpose import Purpose

#: Must stay aligned with `CANONICAL_REMOTE_PURPOSES` in the remote adapter.
#: Duplicated here so application code does not import an outer layer.
_CHATLLM_MULTI_PURPOSE_STAMP: Final[Mapping[Capability, Purpose]] = MappingProxyType(
    {
        Capability.CAPABILITIES_GET: Purpose.STATUS_OBSERVATION,
        Capability.SOURCES_FETCH: Purpose.SOURCE_INSPECTION,
    }
)

_PHASE_ORDER: Final[tuple[str, ...]] = ("revoke", "renew", "add", "noop")
_SEVERITY_ORDER: Final[tuple[str, ...]] = ("blocking", "drift", "warning")

FAILING_OUTCOMES: Final = frozenset(
    {
        "IMPLEMENTED_COMPOSED_GRANT_MISSING",
        "IMPLEMENTED_COMPOSED_GRANT_EXPIRED",
        "IMPLEMENTED_COMPOSED_GRANT_REVOKED",
        "IMPLEMENTED_COMPOSED_GRANT_MISMATCHED",
        "IMPLEMENTED_COMPOSED_GRANT_FINITE_EXPIRY",
        "UNEXPECTED_CONTROL_PLANE_GRANT",
    }
)


class ChatLLMProfileOutcome(StrEnum):
    POLICY_REQUIRED_NOT_IMPLEMENTED = "POLICY_REQUIRED_NOT_IMPLEMENTED"
    IMPLEMENTED_COMPOSED_GRANTED = "IMPLEMENTED_COMPOSED_GRANTED"
    IMPLEMENTED_COMPOSED_GRANT_MISSING = "IMPLEMENTED_COMPOSED_GRANT_MISSING"
    IMPLEMENTED_COMPOSED_GRANT_EXPIRED = "IMPLEMENTED_COMPOSED_GRANT_EXPIRED"
    IMPLEMENTED_COMPOSED_GRANT_REVOKED = "IMPLEMENTED_COMPOSED_GRANT_REVOKED"
    IMPLEMENTED_COMPOSED_GRANT_MISMATCHED = "IMPLEMENTED_COMPOSED_GRANT_MISMATCHED"
    IMPLEMENTED_COMPOSED_GRANT_FINITE_EXPIRY = "IMPLEMENTED_COMPOSED_GRANT_FINITE_EXPIRY"
    UNEXPECTED_CONTROL_PLANE_GRANT = "UNEXPECTED_CONTROL_PLANE_GRANT"
    EXCLUDED = "EXCLUDED"


class ChatLLMConditionCode(StrEnum):
    MISSING_CANONICAL = "MISSING_CANONICAL"
    GRANTED_CANONICAL_DURABLE = "GRANTED_CANONICAL_DURABLE"
    CANONICAL_FINITE_EXPIRY = "CANONICAL_FINITE_EXPIRY"
    CANONICAL_EXPIRED = "CANONICAL_EXPIRED"
    CANONICAL_REVOKED_HISTORY = "CANONICAL_REVOKED_HISTORY"
    ACTIVE_PURPOSE_MISMATCH = "ACTIVE_PURPOSE_MISMATCH"
    INACTIVE_PURPOSE_MISMATCH = "INACTIVE_PURPOSE_MISMATCH"
    ACTIVE_WRITE_CLASS_MISMATCH = "ACTIVE_WRITE_CLASS_MISMATCH"
    EXPIRED_WRITE_CLASS_MISMATCH = "EXPIRED_WRITE_CLASS_MISMATCH"
    OUT_OF_PROFILE_ACTIVE_RESOURCE = "OUT_OF_PROFILE_ACTIVE_RESOURCE"
    OUT_OF_PROFILE_ACTIVE_SCOPE = "OUT_OF_PROFILE_ACTIVE_SCOPE"
    UNSUPPORTED_ACTIVE_VERSION = "UNSUPPORTED_ACTIVE_VERSION"
    DUPLICATE_CANONICAL_ACTIVE = "DUPLICATE_CANONICAL_ACTIVE"
    EXTRA_ACTIVE_VARIANT = "EXTRA_ACTIVE_VARIANT"
    DESIRED_NOT_IMPLEMENTED = "DESIRED_NOT_IMPLEMENTED"
    EXCLUDED_COMPOSITION = "EXCLUDED_COMPOSITION"
    UNEXPECTED_UNCOMPOSED_DATA_GRANT = "UNEXPECTED_UNCOMPOSED_DATA_GRANT"
    UNEXPECTED_CONTROL_PLANE_AUTHORITY = "UNEXPECTED_CONTROL_PLANE_AUTHORITY"
    ACTIVE_COMPATIBILITY_ONLY = "ACTIVE_COMPATIBILITY_ONLY"
    UNEXPECTED_ODR_AUTHORITY = "UNEXPECTED_ODR_AUTHORITY"
    CLIENT_INELIGIBLE = "CLIENT_INELIGIBLE"
    UNMANAGED_ACTIVE_ROW = "UNMANAGED_ACTIVE_ROW"
    UNMANAGED_HISTORICAL_ROW = "UNMANAGED_HISTORICAL_ROW"


_BLOCKING_CODES: Final = frozenset(
    {
        ChatLLMConditionCode.UNSUPPORTED_ACTIVE_VERSION,
        ChatLLMConditionCode.OUT_OF_PROFILE_ACTIVE_RESOURCE,
        ChatLLMConditionCode.OUT_OF_PROFILE_ACTIVE_SCOPE,
        ChatLLMConditionCode.UNEXPECTED_CONTROL_PLANE_AUTHORITY,
        ChatLLMConditionCode.UNEXPECTED_ODR_AUTHORITY,
        ChatLLMConditionCode.DUPLICATE_CANONICAL_ACTIVE,
        ChatLLMConditionCode.DESIRED_NOT_IMPLEMENTED,
        ChatLLMConditionCode.CLIENT_INELIGIBLE,
        ChatLLMConditionCode.UNMANAGED_ACTIVE_ROW,
    }
)


@dataclass(frozen=True, slots=True)
class ChatLLMCompositionPlanes:
    managed_documents: bool
    relationship_intelligence: bool
    relationship_intelligence_writes: bool
    relationship_memory: bool
    constraints: bool


@dataclass(frozen=True, slots=True)
class ChatLLMGrantRecord:
    capability_raw: str
    capability_version: str
    purpose_raw: str | None
    is_write: bool
    resource: str
    scope: str
    expires_at: datetime | None
    revoked_at: datetime | None
    grant_id: UUID | None = None
    capability: Capability | None = None
    purpose: Purpose | None = None


_OriginalGrantRecord = ChatLLMGrantRecord


@dataclass(frozen=True, slots=True)
class ChatLLMGrantAction:
    kind: Literal["revoke", "renew", "add", "noop"]
    capability: Capability | None
    purpose: Purpose | None
    is_write: bool
    grant_id: UUID | None = None
    capability_raw: str = ""


@dataclass(frozen=True, slots=True)
class ChatLLMCondition:
    capability: str
    code: ChatLLMConditionCode
    severity: Literal["blocking", "drift", "warning"]
    grant_ids: tuple[UUID | None, ...]


@dataclass(frozen=True, slots=True)
class ChatLLMProfilePlan:
    desired_effective: frozenset[Capability]
    conditions: tuple[ChatLLMCondition, ...]
    actions: tuple[ChatLLMGrantAction, ...]
    healthy: bool
    blockers: tuple[ChatLLMConditionCode, ...]


@dataclass(frozen=True, slots=True)
class ChatLLMProfileDiff:
    profile_version: str
    desired_effective: frozenset[Capability]
    policy_required_not_implemented: frozenset[Capability]
    outcomes: Mapping[Capability, ChatLLMProfileOutcome]
    unexpected_control_plane: frozenset[Capability]
    add: frozenset[Capability]
    renew: frozenset[Capability]
    revoke: frozenset[Capability] = frozenset()
    plan: ChatLLMProfilePlan | None = None

    def is_healthy(self) -> bool:
        if self.plan is not None:
            return self.plan.healthy
        return not any(outcome.value in FAILING_OUTCOMES for outcome in self.outcomes.values())


def chatllm_grant_purpose(capability: Capability) -> Purpose:
    """Purpose stamped on a dedicated ChatLLM data-management grant."""
    permitted = permitted_purposes(capability)
    if len(permitted) == 1:
        return next(iter(permitted))
    canonical = _CHATLLM_MULTI_PURPOSE_STAMP.get(capability)
    if canonical is not None and canonical in permitted:
        return canonical
    raise RuntimeError(f"no canonical ChatLLM purpose for {capability.value}")


def parse_grant_record(
    *,
    capability_raw: str,
    capability_version: str,
    purpose_raw: str | None,
    is_write: bool,
    resource: str,
    scope: str,
    expires_at: datetime | None,
    revoked_at: datetime | None,
    grant_id: UUID | None = None,
) -> ChatLLMGrantRecord:
    capability: Capability | None
    try:
        capability = Capability(capability_raw)
    except ValueError:
        capability = None
    purpose: Purpose | None
    if purpose_raw is None:
        purpose = None
    else:
        try:
            purpose = Purpose(purpose_raw)
        except ValueError:
            purpose = None
    return _OriginalGrantRecord(
        capability_raw=capability_raw,
        capability_version=capability_version,
        purpose_raw=purpose_raw,
        is_write=is_write,
        resource=resource,
        scope=scope,
        expires_at=expires_at,
        revoked_at=revoked_at,
        grant_id=grant_id,
        capability=capability,
        purpose=purpose,
    )


def _is_revoked(record: ChatLLMGrantRecord) -> bool:
    return record.revoked_at is not None


def _is_active(record: ChatLLMGrantRecord, now: datetime) -> bool:
    if _is_revoked(record):
        return False
    return record.expires_at is None or record.expires_at > now


def _is_expired(record: ChatLLMGrantRecord, now: datetime) -> bool:
    return not _is_revoked(record) and record.expires_at is not None and record.expires_at <= now


def _is_durable(record: ChatLLMGrantRecord) -> bool:
    return not _is_revoked(record) and record.expires_at is None


def _canonical_for(capability: Capability, record: ChatLLMGrantRecord) -> bool:
    expected_purpose = chatllm_grant_purpose(capability)
    expected_write = is_write_capability(capability)
    return (
        record.capability is capability
        and record.capability_version == REMOTE_CAPABILITY_VERSION
        and record.purpose is expected_purpose
        and record.is_write is expected_write
    )


def _severity(code: ChatLLMConditionCode) -> Literal["blocking", "drift", "warning"]:
    if code in _BLOCKING_CODES:
        return "blocking"
    if code is ChatLLMConditionCode.UNMANAGED_HISTORICAL_ROW:
        return "warning"
    if code is ChatLLMConditionCode.GRANTED_CANONICAL_DURABLE:
        return "warning"
    if code is ChatLLMConditionCode.EXCLUDED_COMPOSITION:
        return "warning"
    if code is ChatLLMConditionCode.INACTIVE_PURPOSE_MISMATCH:
        return "warning"
    return "drift"


def _condition(
    capability: str,
    code: ChatLLMConditionCode,
    grant_ids: Sequence[UUID | None],
) -> ChatLLMCondition:
    return ChatLLMCondition(
        capability=capability,
        code=code,
        severity=_severity(code),
        grant_ids=tuple(grant_ids),
    )


def _sort_conditions(conditions: Iterable[ChatLLMCondition]) -> tuple[ChatLLMCondition, ...]:
    return tuple(
        sorted(
            conditions,
            key=lambda item: (
                item.capability,
                _SEVERITY_ORDER.index(item.severity),
                item.code.value,
                tuple(str(grant_id or "") for grant_id in item.grant_ids),
            ),
        )
    )


def _sort_actions(actions: Iterable[ChatLLMGrantAction]) -> tuple[ChatLLMGrantAction, ...]:
    return tuple(
        sorted(
            actions,
            key=lambda item: (
                _PHASE_ORDER.index(item.kind),
                item.capability.value if item.capability is not None else item.capability_raw,
                item.purpose.value if item.purpose is not None else "",
                str(item.grant_id or ""),
            ),
        )
    )


def desired_effective_capabilities(
    composed_or_implemented: frozenset[Capability],
    state: ApplicationCompositionState | None = None,
) -> frozenset[Capability]:
    composed = (
        composed_or_implemented
        if state is None
        else derive_available_capabilities(composed_or_implemented, state)
    )
    return frozenset(
        capability for capability in composed if is_chatllm_data_management(capability)
    )


def composed_capabilities(
    implemented: frozenset[Capability],
    planes: ChatLLMCompositionPlanes,
) -> frozenset[Capability]:
    """Compatibility shim. Not mutation authority."""
    state = ApplicationCompositionState(
        managed_documents=planes.managed_documents,
        relationship_intelligence=planes.relationship_intelligence,
        relationship_intelligence_writes=planes.relationship_intelligence_writes,
        relationship_memory=planes.relationship_memory,
        producer_origins_registered=True,
        relationship_identity_correction=planes.relationship_intelligence_writes,
        goodnotes_pull=False,
        constraints=planes.constraints,
    )
    return derive_available_capabilities(implemented, state)


def plan_profile_state(
    *,
    implemented: frozenset[Capability],
    state: ApplicationCompositionState,
    grants: Iterable[ChatLLMGrantRecord],
    now: datetime,
    resource: str,
    scope: str,
) -> ChatLLMProfilePlan:
    records = tuple(grants)
    desired = desired_effective_capabilities(implemented, state)
    composed = derive_available_capabilities(implemented, state)
    conditions: list[ChatLLMCondition] = []
    actions: list[ChatLLMGrantAction] = []

    for record in records:
        if _is_active(record, now) and record.capability_version != REMOTE_CAPABILITY_VERSION:
            conditions.append(
                _condition(
                    record.capability_raw,
                    ChatLLMConditionCode.UNSUPPORTED_ACTIVE_VERSION,
                    (record.grant_id,),
                )
            )
        if _is_active(record, now) and record.resource != resource:
            conditions.append(
                _condition(
                    record.capability_raw,
                    ChatLLMConditionCode.OUT_OF_PROFILE_ACTIVE_RESOURCE,
                    (record.grant_id,),
                )
            )
        if _is_active(record, now) and record.scope != scope:
            conditions.append(
                _condition(
                    record.capability_raw,
                    ChatLLMConditionCode.OUT_OF_PROFILE_ACTIVE_SCOPE,
                    (record.grant_id,),
                )
            )
        if _is_active(record, now) and (
            record.capability is None or (record.purpose_raw is not None and record.purpose is None)
        ):
            conditions.append(
                _condition(
                    record.capability_raw,
                    ChatLLMConditionCode.UNMANAGED_ACTIVE_ROW,
                    (record.grant_id,),
                )
            )
        elif not _is_active(record, now) and (
            record.capability is None or (record.purpose_raw is not None and record.purpose is None)
        ):
            conditions.append(
                _condition(
                    record.capability_raw,
                    ChatLLMConditionCode.UNMANAGED_HISTORICAL_ROW,
                    (record.grant_id,),
                )
            )

    in_profile = [
        record
        for record in records
        if record.resource == resource
        and record.scope == scope
        and record.capability_version == REMOTE_CAPABILITY_VERSION
        and record.capability is not None
        and (record.purpose_raw is None or record.purpose is not None)
    ]

    by_capability: dict[Capability, list[ChatLLMGrantRecord]] = {}
    for record in in_profile:
        if record.capability is None:
            continue
        by_capability.setdefault(record.capability, []).append(record)

    for capability in sorted(CHATLLM_CAPABILITY_POLICY, key=lambda item: item.value):
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        rows = by_capability.get(capability, [])
        active = [record for record in rows if _is_active(record, now)]
        classification = policy.classification
        if classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED:
            if active:
                conditions.append(
                    _condition(
                        capability.value,
                        ChatLLMConditionCode.UNEXPECTED_CONTROL_PLANE_AUTHORITY,
                        tuple(record.grant_id for record in active),
                    )
                )
            continue
        if classification is ChatLLMCapabilityClass.OPERATOR_DECISION_REQUIRED:
            if active:
                conditions.append(
                    _condition(
                        capability.value,
                        ChatLLMConditionCode.UNEXPECTED_ODR_AUTHORITY,
                        tuple(record.grant_id for record in active),
                    )
                )
            continue
        if classification is ChatLLMCapabilityClass.COMPATIBILITY_ONLY:
            if active:
                conditions.append(
                    _condition(
                        capability.value,
                        ChatLLMConditionCode.ACTIVE_COMPATIBILITY_ONLY,
                        tuple(record.grant_id for record in active),
                    )
                )
                for record in active:
                    actions.append(
                        ChatLLMGrantAction(
                            kind="revoke",
                            capability=capability,
                            purpose=record.purpose,
                            is_write=record.is_write,
                            grant_id=record.grant_id,
                            capability_raw=capability.value,
                        )
                    )
            continue
        if not is_chatllm_data_management(capability):
            continue
        if capability not in implemented:
            conditions.append(
                _condition(capability.value, ChatLLMConditionCode.DESIRED_NOT_IMPLEMENTED, ())
            )
            continue
        if capability not in composed:
            if active:
                conditions.append(
                    _condition(
                        capability.value,
                        ChatLLMConditionCode.UNEXPECTED_UNCOMPOSED_DATA_GRANT,
                        tuple(record.grant_id for record in active),
                    )
                )
                for record in active:
                    actions.append(
                        ChatLLMGrantAction(
                            kind="revoke",
                            capability=capability,
                            purpose=record.purpose,
                            is_write=record.is_write,
                            grant_id=record.grant_id,
                            capability_raw=capability.value,
                        )
                    )
            else:
                conditions.append(
                    _condition(capability.value, ChatLLMConditionCode.EXCLUDED_COMPOSITION, ())
                )
            continue

        expected_purpose = chatllm_grant_purpose(capability)
        expected_write = is_write_capability(capability)
        canonical_active = [record for record in active if _canonical_for(capability, record)]
        extra_active = [record for record in active if record not in canonical_active]
        unrevoked = [record for record in rows if not _is_revoked(record)]
        expired_canonical = [
            record
            for record in unrevoked
            if _is_expired(record, now) and _canonical_for(capability, record)
        ]
        revoked_canonical = [
            record for record in rows if _is_revoked(record) and _canonical_for(capability, record)
        ]
        finite_canonical = [
            record
            for record in canonical_active
            if record.expires_at is not None and record.expires_at > now
        ]
        durable_canonical = [record for record in canonical_active if _is_durable(record)]

        if len(canonical_active) > 1:
            conditions.append(
                _condition(
                    capability.value,
                    ChatLLMConditionCode.DUPLICATE_CANONICAL_ACTIVE,
                    tuple(record.grant_id for record in canonical_active),
                )
            )
            continue

        for record in extra_active:
            if record.purpose is None or record.purpose is not expected_purpose:
                code = ChatLLMConditionCode.ACTIVE_PURPOSE_MISMATCH
            elif record.is_write is not expected_write:
                code = ChatLLMConditionCode.ACTIVE_WRITE_CLASS_MISMATCH
            else:
                code = ChatLLMConditionCode.EXTRA_ACTIVE_VARIANT
            conditions.append(_condition(capability.value, code, (record.grant_id,)))
            actions.append(
                ChatLLMGrantAction(
                    kind="revoke",
                    capability=capability,
                    purpose=record.purpose,
                    is_write=record.is_write,
                    grant_id=record.grant_id,
                    capability_raw=capability.value,
                )
            )

        expired_wrong_write = [
            record
            for record in unrevoked
            if _is_expired(record, now)
            and record.is_write is not expected_write
            and record not in extra_active
        ]
        for record in expired_wrong_write:
            conditions.append(
                _condition(
                    capability.value,
                    ChatLLMConditionCode.EXPIRED_WRITE_CLASS_MISMATCH,
                    (record.grant_id,),
                )
            )
            actions.append(
                ChatLLMGrantAction(
                    kind="revoke",
                    capability=capability,
                    purpose=record.purpose,
                    is_write=record.is_write,
                    grant_id=record.grant_id,
                    capability_raw=capability.value,
                )
            )

        inactive_purpose = [
            record
            for record in rows
            if not _is_active(record, now)
            and record.purpose is not expected_purpose
            and record not in expired_wrong_write
        ]
        if inactive_purpose:
            conditions.append(
                _condition(
                    capability.value,
                    ChatLLMConditionCode.INACTIVE_PURPOSE_MISMATCH,
                    tuple(record.grant_id for record in inactive_purpose),
                )
            )

        if durable_canonical and not extra_active and not expired_wrong_write:
            conditions.append(
                _condition(
                    capability.value,
                    ChatLLMConditionCode.GRANTED_CANONICAL_DURABLE,
                    (durable_canonical[0].grant_id,),
                )
            )
            actions.append(
                ChatLLMGrantAction(
                    kind="noop",
                    capability=capability,
                    purpose=expected_purpose,
                    is_write=expected_write,
                    grant_id=durable_canonical[0].grant_id,
                    capability_raw=capability.value,
                )
            )
            continue
        if finite_canonical:
            record = finite_canonical[0]
            conditions.append(
                _condition(
                    capability.value,
                    ChatLLMConditionCode.CANONICAL_FINITE_EXPIRY,
                    (record.grant_id,),
                )
            )
            actions.append(
                ChatLLMGrantAction(
                    kind="renew",
                    capability=capability,
                    purpose=expected_purpose,
                    is_write=expected_write,
                    grant_id=record.grant_id,
                    capability_raw=capability.value,
                )
            )
            continue
        if expired_canonical and not extra_active:
            record = expired_canonical[0]
            conditions.append(
                _condition(
                    capability.value, ChatLLMConditionCode.CANONICAL_EXPIRED, (record.grant_id,)
                )
            )
            actions.append(
                ChatLLMGrantAction(
                    kind="renew",
                    capability=capability,
                    purpose=expected_purpose,
                    is_write=expected_write,
                    grant_id=record.grant_id,
                    capability_raw=capability.value,
                )
            )
            continue
        if revoked_canonical and not extra_active and not expired_canonical:
            conditions.append(
                _condition(
                    capability.value,
                    ChatLLMConditionCode.CANONICAL_REVOKED_HISTORY,
                    tuple(record.grant_id for record in revoked_canonical),
                )
            )
            actions.append(
                ChatLLMGrantAction(
                    kind="add",
                    capability=capability,
                    purpose=expected_purpose,
                    is_write=expected_write,
                    grant_id=None,
                    capability_raw=capability.value,
                )
            )
            continue
        if not active and not expired_canonical and not extra_active:
            conditions.append(
                _condition(capability.value, ChatLLMConditionCode.MISSING_CANONICAL, ())
            )
            actions.append(
                ChatLLMGrantAction(
                    kind="add",
                    capability=capability,
                    purpose=expected_purpose,
                    is_write=expected_write,
                    grant_id=None,
                    capability_raw=capability.value,
                )
            )
            continue
        if extra_active or expired_wrong_write:
            actions.append(
                ChatLLMGrantAction(
                    kind="add",
                    capability=capability,
                    purpose=expected_purpose,
                    is_write=expected_write,
                    grant_id=None,
                    capability_raw=capability.value,
                )
            )

    sorted_conditions = _sort_conditions(conditions)
    sorted_actions = _sort_actions(actions)
    blockers = tuple(
        sorted(
            {item.code for item in sorted_conditions if item.severity == "blocking"},
            key=lambda code: code.value,
        )
    )
    healthy = not blockers and not any(
        action.kind in {"revoke", "renew", "add"} for action in sorted_actions
    )
    return ChatLLMProfilePlan(
        desired_effective=desired,
        conditions=sorted_conditions,
        actions=sorted_actions,
        healthy=healthy,
        blockers=blockers,
    )


def diff_chatllm_data_profile(
    *,
    implemented: frozenset[Capability],
    composed: frozenset[Capability] | None = None,
    grants: Iterable[ChatLLMGrantRecord],
    now: datetime,
    resource: str,
    scope: str,
    state: ApplicationCompositionState | None = None,
) -> ChatLLMProfileDiff:
    if state is None:
        state = ApplicationCompositionState(
            managed_documents=True,
            relationship_intelligence=True,
            relationship_intelligence_writes=True,
            relationship_memory=True,
            producer_origins_registered=True,
            relationship_identity_correction=True,
            goodnotes_pull=True,
            constraints=True,
        )
        if composed is not None:
            withheld = implemented - composed
            state = ApplicationCompositionState(
                managed_documents=not any(
                    capability.value.startswith("documents.") for capability in withheld
                ),
                relationship_intelligence=not any(
                    capability.value.startswith("entities.") for capability in withheld
                ),
                relationship_intelligence_writes=not any(
                    is_write_capability(capability) and capability.value.startswith("entities.")
                    for capability in withheld
                ),
                relationship_memory=not any(
                    capability.value.startswith("relationship_memory.") for capability in withheld
                ),
                producer_origins_registered=True,
                relationship_identity_correction=True,
                goodnotes_pull=not any(
                    capability.value.startswith("goodnotes.") for capability in withheld
                ),
                constraints=not any(
                    capability.value.startswith("constraints.")
                    or capability.value.startswith("constraint_")
                    for capability in withheld
                ),
            )
    plan = plan_profile_state(
        implemented=implemented,
        state=state,
        grants=grants,
        now=now,
        resource=resource,
        scope=scope,
    )
    outcomes: dict[Capability, ChatLLMProfileOutcome] = {}
    unexpected: set[Capability] = set()
    not_implemented: set[Capability] = set()
    add: set[Capability] = set()
    renew: set[Capability] = set()
    revoke: set[Capability] = set()
    for condition in plan.conditions:
        try:
            capability = Capability(condition.capability)
        except ValueError:
            continue
        if condition.code is ChatLLMConditionCode.DESIRED_NOT_IMPLEMENTED:
            outcomes[capability] = ChatLLMProfileOutcome.POLICY_REQUIRED_NOT_IMPLEMENTED
            not_implemented.add(capability)
        elif condition.code is ChatLLMConditionCode.UNEXPECTED_CONTROL_PLANE_AUTHORITY:
            outcomes[capability] = ChatLLMProfileOutcome.UNEXPECTED_CONTROL_PLANE_GRANT
            unexpected.add(capability)
        elif condition.code is ChatLLMConditionCode.MISSING_CANONICAL:
            outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_MISSING
        elif condition.code is ChatLLMConditionCode.CANONICAL_EXPIRED:
            outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_EXPIRED
        elif condition.code is ChatLLMConditionCode.CANONICAL_REVOKED_HISTORY:
            outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_REVOKED
        elif condition.code in {
            ChatLLMConditionCode.ACTIVE_PURPOSE_MISMATCH,
            ChatLLMConditionCode.ACTIVE_WRITE_CLASS_MISMATCH,
            ChatLLMConditionCode.EXTRA_ACTIVE_VARIANT,
        }:
            outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_MISMATCHED
        elif condition.code is ChatLLMConditionCode.CANONICAL_FINITE_EXPIRY:
            outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_FINITE_EXPIRY
        elif condition.code is ChatLLMConditionCode.GRANTED_CANONICAL_DURABLE:
            outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANTED
        elif condition.code in {
            ChatLLMConditionCode.EXCLUDED_COMPOSITION,
            ChatLLMConditionCode.UNEXPECTED_UNCOMPOSED_DATA_GRANT,
        }:
            outcomes[capability] = ChatLLMProfileOutcome.EXCLUDED
    for action in plan.actions:
        if action.capability is None:
            continue
        if action.kind == "add":
            add.add(action.capability)
        elif action.kind == "renew":
            renew.add(action.capability)
        elif action.kind == "revoke":
            revoke.add(action.capability)
    return ChatLLMProfileDiff(
        profile_version=CHATLLM_DATA_PROFILE_VERSION,
        desired_effective=plan.desired_effective,
        policy_required_not_implemented=frozenset(not_implemented),
        outcomes=outcomes,
        unexpected_control_plane=frozenset(unexpected),
        add=frozenset(add),
        renew=frozenset(renew),
        revoke=frozenset(revoke),
        plan=plan,
    )


def plan_chatllm_grant_actions(
    diff: ChatLLMProfileDiff,
    records: Iterable[ChatLLMGrantRecord],
    *,
    now: datetime,
    resource: str,
    scope: str,
) -> tuple[ChatLLMGrantAction, ...]:
    del records, now, resource, scope
    if diff.plan is not None:
        return diff.plan.actions
    return ()


def profile_diff_as_json(diff: ChatLLMProfileDiff) -> dict[str, object]:
    return {
        "profile_version": diff.profile_version,
        "healthy": diff.is_healthy(),
        "desired_effective": sorted(item.value for item in diff.desired_effective),
        "add": sorted(item.value for item in diff.add),
        "renew": sorted(item.value for item in diff.renew),
        "revoke": sorted(item.value for item in diff.revoke),
        "unexpected_control_plane": sorted(item.value for item in diff.unexpected_control_plane),
        "policy_required_not_implemented": sorted(
            item.value for item in diff.policy_required_not_implemented
        ),
    }


def _legacy_grant_record(
    *,
    capability: Capability,
    purpose: Purpose | None,
    is_write: bool,
    resource: str,
    scope: str,
    expires_at: datetime | None,
    revoked_at: datetime | None,
    grant_id: UUID | None = None,
    capability_version: str = REMOTE_CAPABILITY_VERSION,
) -> ChatLLMGrantRecord:
    return parse_grant_record(
        capability_raw=capability.value,
        capability_version=capability_version,
        purpose_raw=None if purpose is None else purpose.value,
        is_write=is_write,
        resource=resource,
        scope=scope,
        expires_at=expires_at,
        revoked_at=revoked_at,
        grant_id=grant_id,
    )


def grant_record(**kwargs: object) -> ChatLLMGrantRecord:
    if "capability_raw" in kwargs:
        return parse_grant_record(**kwargs)  # type: ignore[arg-type]
    if "capability" in kwargs and isinstance(kwargs["capability"], Capability):
        purpose = kwargs.get("purpose")
        if purpose is not None and not isinstance(purpose, Purpose):
            raise TypeError("purpose must be Purpose or None")
        return _legacy_grant_record(
            capability=kwargs["capability"],
            purpose=purpose,
            is_write=bool(kwargs["is_write"]),
            resource=str(kwargs["resource"]),
            scope=str(kwargs["scope"]),
            expires_at=kwargs.get("expires_at"),  # type: ignore[arg-type]
            revoked_at=kwargs.get("revoked_at"),  # type: ignore[arg-type]
            grant_id=kwargs.get("grant_id"),  # type: ignore[arg-type]
            capability_version=str(kwargs.get("capability_version", REMOTE_CAPABILITY_VERSION)),
        )
    return _OriginalGrantRecord(**kwargs)  # type: ignore[arg-type]


ChatLLMGrantRecord = grant_record  # type: ignore[misc, assignment]
