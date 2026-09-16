"""Derive the ChatLLM full-data profile and compare it to durable grants.

This module does not mutate grants, OAuth clients, or runtime composition.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from types import MappingProxyType
from typing import Final, Literal
from uuid import UUID

from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    CHATLLM_DATA_PROFILE_VERSION,
    ChatLLMCapabilityClass,
    ChatLLMCompositionPrerequisite,
    is_chatllm_data_management,
)
from my_pa.domain.identity.operation import (
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


@dataclass(frozen=True, slots=True)
class ChatLLMCompositionPlanes:
    managed_documents: bool
    relationship_intelligence: bool
    relationship_intelligence_writes: bool
    relationship_memory: bool
    constraints: bool


@dataclass(frozen=True, slots=True)
class ChatLLMGrantRecord:
    capability: Capability
    purpose: Purpose | None
    is_write: bool
    resource: str
    scope: str
    expires_at: datetime | None
    revoked_at: datetime | None
    grant_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ChatLLMGrantAction:
    kind: Literal["add", "renew", "noop"]
    capability: Capability
    purpose: Purpose
    is_write: bool
    grant_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class ChatLLMProfileDiff:
    profile_version: str
    desired_effective: frozenset[Capability]
    policy_required_not_implemented: frozenset[Capability]
    outcomes: Mapping[Capability, ChatLLMProfileOutcome]
    unexpected_control_plane: frozenset[Capability]
    add: frozenset[Capability]
    renew: frozenset[Capability]

    def is_healthy(self) -> bool:
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


def composed_capabilities(
    implemented: frozenset[Capability],
    planes: ChatLLMCompositionPlanes,
) -> frozenset[Capability]:
    """Approximate ApplicationService.available_capabilities from plane flags."""
    composed = set(implemented)
    for capability, policy in CHATLLM_CAPABILITY_POLICY.items():
        if capability not in composed:
            continue
        prerequisite = policy.composition_prerequisite
        if prerequisite is ChatLLMCompositionPrerequisite.MANAGED_DOCUMENTS:
            if not planes.managed_documents:
                composed.discard(capability)
        elif prerequisite is ChatLLMCompositionPrerequisite.RELATIONSHIP_INTELLIGENCE:
            if not planes.relationship_intelligence or (
                is_write_capability(capability) and not planes.relationship_intelligence_writes
            ):
                composed.discard(capability)
        elif prerequisite is ChatLLMCompositionPrerequisite.RELATIONSHIP_MEMORY:
            if not (planes.relationship_intelligence and planes.relationship_memory):
                composed.discard(capability)
        elif prerequisite is ChatLLMCompositionPrerequisite.CONSTRAINTS and not planes.constraints:
            composed.discard(capability)
    return frozenset(composed)


def desired_effective_capabilities(composed: frozenset[Capability]) -> frozenset[Capability]:
    return frozenset(
        capability for capability in composed if is_chatllm_data_management(capability)
    )


def _is_active(record: ChatLLMGrantRecord, now: datetime) -> bool:
    if record.revoked_at is not None:
        return False
    return record.expires_at is None or record.expires_at > now


def _matching_records(
    records: Iterable[ChatLLMGrantRecord],
    capability: Capability,
    *,
    resource: str,
    scope: str,
) -> tuple[ChatLLMGrantRecord, ...]:
    return tuple(
        record
        for record in records
        if record.capability is capability and record.resource == resource and record.scope == scope
    )


def diff_chatllm_data_profile(
    *,
    implemented: frozenset[Capability],
    composed: frozenset[Capability],
    grants: Iterable[ChatLLMGrantRecord],
    now: datetime,
    resource: str,
    scope: str,
) -> ChatLLMProfileDiff:
    grant_records = tuple(grants)
    desired = desired_effective_capabilities(composed)
    outcomes: dict[Capability, ChatLLMProfileOutcome] = {}
    unexpected: set[Capability] = set()
    not_implemented: set[Capability] = set()
    add: set[Capability] = set()
    renew: set[Capability] = set()

    for capability, policy in CHATLLM_CAPABILITY_POLICY.items():
        records = _matching_records(grant_records, capability, resource=resource, scope=scope)
        active = tuple(record for record in records if _is_active(record, now))
        data = is_chatllm_data_management(capability)
        if policy.classification is ChatLLMCapabilityClass.CONTROL_PLANE_EXCLUDED and active:
            outcomes[capability] = ChatLLMProfileOutcome.UNEXPECTED_CONTROL_PLANE_GRANT
            unexpected.add(capability)
            continue
        if data and capability not in implemented:
            outcomes[capability] = ChatLLMProfileOutcome.POLICY_REQUIRED_NOT_IMPLEMENTED
            not_implemented.add(capability)
            continue
        if capability not in desired:
            outcomes[capability] = ChatLLMProfileOutcome.EXCLUDED
            continue
        expected_purpose = chatllm_grant_purpose(capability)
        expected_write = is_write_capability(capability)
        if active:
            matching_active = [
                record
                for record in active
                if record.purpose is expected_purpose and record.is_write is expected_write
            ]
            if matching_active:
                durable = [record for record in matching_active if record.expires_at is None]
                if durable:
                    outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANTED
                else:
                    outcomes[
                        capability
                    ] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_FINITE_EXPIRY
                    renew.add(capability)
            else:
                outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_MISMATCHED
            continue
        expired = tuple(
            record
            for record in records
            if record.revoked_at is None
            and record.expires_at is not None
            and record.expires_at <= now
        )
        if expired:
            outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_EXPIRED
            renew.add(capability)
            continue
        revoked = tuple(record for record in records if record.revoked_at is not None)
        if revoked:
            outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_REVOKED
            add.add(capability)
            continue
        outcomes[capability] = ChatLLMProfileOutcome.IMPLEMENTED_COMPOSED_GRANT_MISSING
        add.add(capability)

    return ChatLLMProfileDiff(
        profile_version=CHATLLM_DATA_PROFILE_VERSION,
        desired_effective=desired,
        policy_required_not_implemented=frozenset(not_implemented),
        outcomes=outcomes,
        unexpected_control_plane=frozenset(unexpected),
        add=frozenset(add),
        renew=frozenset(renew),
    )


def plan_chatllm_grant_actions(
    diff: ChatLLMProfileDiff,
    grants: Iterable[ChatLLMGrantRecord],
    *,
    now: datetime,
    resource: str,
    scope: str,
) -> tuple[ChatLLMGrantAction, ...]:
    """Deterministic add/renew set. Never includes control-plane names."""
    grant_records = tuple(grants)
    actions: list[ChatLLMGrantAction] = []
    for capability in sorted(diff.desired_effective, key=lambda item: item.value):
        if not is_chatllm_data_management(capability):
            continue
        purpose = chatllm_grant_purpose(capability)
        is_write = is_write_capability(capability)
        records = _matching_records(grant_records, capability, resource=resource, scope=scope)
        active = tuple(record for record in records if _is_active(record, now))
        matching_active = [
            record for record in active if record.purpose is purpose and record.is_write is is_write
        ]
        if matching_active:
            durable = [record for record in matching_active if record.expires_at is None]
            if durable:
                actions.append(
                    ChatLLMGrantAction("noop", capability, purpose, is_write, durable[0].grant_id)
                )
            else:
                finite = matching_active
                actions.append(
                    ChatLLMGrantAction("renew", capability, purpose, is_write, finite[0].grant_id)
                )
            continue
        expired = tuple(
            record
            for record in records
            if record.revoked_at is None
            and record.expires_at is not None
            and record.expires_at <= now
            and record.purpose is purpose
        )
        if expired:
            actions.append(
                ChatLLMGrantAction("renew", capability, purpose, is_write, expired[0].grant_id)
            )
            continue
        actions.append(ChatLLMGrantAction("add", capability, purpose, is_write, None))
    return tuple(actions)


def profile_diff_as_json(diff: ChatLLMProfileDiff) -> dict[str, object]:
    failing = sorted(
        capability.value
        for capability, outcome in diff.outcomes.items()
        if outcome.value in FAILING_OUTCOMES
    )
    return {
        "profile_version": diff.profile_version,
        "healthy": diff.is_healthy(),
        "desired_effective_count": len(diff.desired_effective),
        "desired_effective": sorted(item.value for item in diff.desired_effective),
        "policy_required_not_implemented": sorted(
            item.value for item in diff.policy_required_not_implemented
        ),
        "unexpected_control_plane": sorted(item.value for item in diff.unexpected_control_plane),
        "add": sorted(item.value for item in diff.add),
        "renew": sorted(item.value for item in diff.renew),
        "failing": failing,
        "outcomes": {
            capability.value: outcome.value
            for capability, outcome in sorted(diff.outcomes.items(), key=lambda item: item[0].value)
        },
    }
