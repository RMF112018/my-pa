"""Policy evaluation.

Every path through `evaluate` that is not an explicit allow returns a denial.
The function has exactly one `allowed=True` construction site, so a new input
state cannot accidentally become permitted.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import StrEnum

from my_pa.domain.common.classification import Classification, is_cloud_eligible
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose

__all__ = [
    "POLICY_VERSION",
    "DenialReason",
    "PolicyDecision",
    "PolicyRequest",
    "evaluate",
    "validate_policy_version",
]

#: Version of the rule set below. Audit records bind decisions to this value.
POLICY_VERSION = "policy-v1"

#: Shape a policy version must take. Constrained so the field cannot become a
#: free-text channel into the audit log.
POLICY_VERSION_PATTERN = re.compile(r"\Apolicy-v[0-9]{1,4}\Z")


def validate_policy_version(value: str) -> str:
    """Return `value` if it is a well-formed policy version, else raise."""
    if not isinstance(value, str):
        # Domain models are plain dataclasses with no runtime type enforcement,
        # matching the guard in validate_identifier.
        raise ValueError(f"policy version must be a string, got {type(value).__name__}")
    if not POLICY_VERSION_PATTERN.fullmatch(value):
        raise ValueError(f"policy version must match 'policy-vN', got {value!r}")
    return value


class DenialReason(StrEnum):
    """Safe, stable denial categories.

    These are disclosure-safe: they describe why authority was insufficient and
    never reveal whether a denied object exists.
    """

    PRINCIPAL_NOT_AUTHENTICATED = "principal_not_authenticated"
    PRINCIPAL_MAY_NOT_HOLD_AUTHORITY = "principal_may_not_hold_authority"
    OPERATOR_REQUIRED = "operator_required"
    PURPOSE_NOT_PERMITTED_FOR_CAPABILITY = "purpose_not_permitted_for_capability"
    SCOPE_NOT_AUTHORIZED = "scope_not_authorized"
    DESTINATION_NOT_ELIGIBLE = "destination_not_eligible"


@dataclass(frozen=True, slots=True)
class PolicyRequest:
    """Everything policy is allowed to consider.

    `authorized_source_ids` is the enrollment the principal already holds. An
    empty requested scope is not a wildcard; it is an unauthorized scope.
    """

    principal: Principal
    purpose: Purpose
    capability: Capability
    classification: Classification = Classification.PRIVATE_LOCAL
    requested_source_ids: frozenset[str] = field(default_factory=frozenset)
    authorized_source_ids: frozenset[str] = field(default_factory=frozenset)
    to_cloud: bool = False


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    """The outcome of one evaluation."""

    allowed: bool
    policy_version: str
    reason: DenialReason | None = None

    def __post_init__(self) -> None:
        validate_policy_version(self.policy_version)
        if self.allowed and self.reason is not None:
            raise ValueError("an allowed decision cannot carry a denial reason")
        if not self.allowed and self.reason is None:
            raise ValueError("a denial must carry a reason")


def _deny(reason: DenialReason) -> PolicyDecision:
    return PolicyDecision(allowed=False, policy_version=POLICY_VERSION, reason=reason)


def evaluate(request: PolicyRequest) -> PolicyDecision:
    """Return the policy decision for `request`, denying unless every rule allows."""
    principal = request.principal

    if not principal.authenticated:
        return _deny(DenialReason.PRINCIPAL_NOT_AUTHENTICATED)

    if not principal.may_hold_authority:
        return _deny(DenialReason.PRINCIPAL_MAY_NOT_HOLD_AUTHORITY)

    if is_operator_only(request.capability) and not principal.is_operator:
        return _deny(DenialReason.OPERATOR_REQUIRED)

    if request.purpose not in permitted_purposes(request.capability):
        return _deny(DenialReason.PURPOSE_NOT_PERMITTED_FOR_CAPABILITY)

    if not _scope_is_authorized(request):
        return _deny(DenialReason.SCOPE_NOT_AUTHORIZED)

    if request.to_cloud and not is_cloud_eligible(request.classification):
        return _deny(DenialReason.DESTINATION_NOT_ELIGIBLE)

    return PolicyDecision(allowed=True, policy_version=POLICY_VERSION)


#: Capabilities that carry no source scope at all, and for which naming one is
#: therefore a contradiction rather than a request.
#:
#: `capabilities.get` describes the interface itself. The five capture
#: capabilities read and write a product-owned record, which `ADR-003` makes a
#: third authority class: a capture belongs to no configured source and no
#: enrollment, so requiring one would make them permanently unusable in exactly
#: the way requiring a held scope would make `sources.enroll` unusable.
#:
#: `capture.search` is the fifth, and it is scopeless for the same reason and
#: not for convenience: the plane it searches is `knowledge.capture_versions`,
#: whose rows carry no `enrollment_id` and no `source_id` at all. A source scope
#: on it would name something the searched rows cannot be filtered by.
#:
#: **This set widening is what an added capability most easily gets wrong.** An
#: unlisted capability falls to the rule below, which denies an empty requested
#: scope — a correct default, and a silent one: the request is refused with
#: `scope_not_authorized` and nothing says the capability was never mapped.
_SCOPELESS: frozenset[Capability] = frozenset(
    {
        Capability.CAPABILITIES_GET,
        Capability.CAPTURE_REVISE,
        Capability.CAPTURE_READ,
        Capability.CAPTURE_LIST,
        Capability.CAPTURE_SEARCH,
        Capability.REVIEW_LIST,
        Capability.REVIEW_DECIDE,
    }
)


def _scope_is_authorized(request: PolicyRequest) -> bool:
    """Whether the requested scope lies inside the authorized enrollment.

    A scopeless capability must name no scope; every other capability must name
    a scope it already holds.
    """
    if request.capability in _SCOPELESS:
        return not request.requested_source_ids
    if request.capability is Capability.CAPTURE_CREATE:
        return not request.requested_source_ids or (
            request.requested_source_ids <= request.authorized_source_ids
        )
    if not request.requested_source_ids:
        return False
    if request.capability is Capability.SOURCES_ENROLL:
        # Enrollment is the operation that grants scope, so requiring the scope
        # to be held already would make the capability permanently unusable.
        # Authority comes from the operator-only check above. The bound on which
        # sources may be enrolled is the configured-source registry, which does
        # not exist until Phase 02; until then an authenticated operator may
        # enroll any named source.
        return True
    return request.requested_source_ids <= request.authorized_source_ids
