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
from my_pa.domain.identity.operation import (
    AuthorizedCapability,
    Capability,
    is_operator_only,
    permitted_purposes,
)
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
    capability: AuthorizedCapability
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
        # `knowledge.reveal` names a subject, not a source. The rows it
        # traverses belong to the capture plane, which belongs to no configured
        # source and no enrollment, so a request that named a scope would be
        # naming a grant this plane cannot hold.
        Capability.KNOWLEDGE_REVEAL,
        # The three continuity reads name a Principal, not a source. Situations,
        # Projects and the Pulse belong to no configured source and to no
        # enrollment — a Situation *references* objects across planes and owns
        # none of them — so a request that named a scope would be naming a grant
        # this plane cannot hold, exactly as `knowledge.reveal` cannot.
        Capability.CONTINUITY_PULSE,
        Capability.CONTINUITY_SITUATIONS,
        Capability.CONTINUITY_PROJECTS,
        Capability.CONTINUITY_PROJECTS_CREATE,
        Capability.CONTINUITY_SITUATIONS_CREATE,
        Capability.CONTINUITY_TASKS_CREATE,
        # `knowledge.coverage` names a Principal, not a source. Its whole subject
        # is "everything you hold", which the store derives from
        # `enrollments.principal_id`; a request that named a scope would be asking
        # a corpus-wide question about one source, and answering it would be
        # answering a different question from the one authorized. The scope it
        # reads is therefore not caller-stated at all, which is what puts it here
        # rather than under the held-scope rule below.
        Capability.KNOWLEDGE_COVERAGE,
        # The managed-document plane names a document, not a source. A managed
        # document is the product's own custody under `AGENTS.md` section 4 —
        # written into the designated managed root and never into a source root —
        # so its rows carry no `source_id` and no `enrollment_id` for a scope to
        # be compared against, exactly as a capture's do not. Requiring one would
        # make the whole plane permanently unusable; naming one would be naming a
        # grant this plane cannot hold.
        Capability.DOCUMENTS_CREATE,
        Capability.DOCUMENTS_REVISE,
        Capability.DOCUMENTS_READ,
        Capability.DOCUMENTS_LIST,
        Capability.DOCUMENTS_ARCHIVE,
        Capability.DOCUMENTS_RESTORE,
        # The task plane (WP-TM-03) names a Principal, not a source. A task is
        # opened by a Principal directly — through the assistant surface or an
        # accepted review decision — and never through a configured source's
        # ingest path, so its rows carry no `source_id` and no `enrollment_id`
        # for a scope to be compared against, exactly as a managed document's
        # do not. Exact Principal scoping is enforced the same way
        # `knowledge.coverage` enforces it: the repository filters by
        # `principal_id` on every read, which is not a caller-stated scope at
        # all, so a request that named one would be naming a grant this plane
        # cannot hold.
        Capability.TASKS_READ,
        Capability.TASKS_LIST,
        Capability.TASKS_SEARCH,
        Capability.TASKS_HISTORY,
        # The task plane's five write capabilities (WP-TM-04) belong here for
        # the identical reason its four reads do, immediately above: a task's
        # rows carry no `source_id` and no `enrollment_id` for a scope to be
        # compared against, whether the request reads or writes them. This
        # entry corrects a gap against this module's own stated intent — the
        # comment above the four reads already says "all nine `tasks.*`
        # capabilities (four reads and five writes)" are scopeless, but only
        # the four reads were actually admitted here, which denied every
        # `tasks.create`/`update`/`transition`/`bulk_preview`/`bulk_confirm`
        # request with `scope_not_authorized` regardless of purpose or
        # authority. WP-TM-05's own representative scenario test is what
        # surfaced it, by being the first test in this build to invoke task
        # mutation through `ApplicationService.invoke`'s full authorize path
        # rather than only through `TaskManagementService` directly.
        Capability.TASKS_CREATE,
        Capability.TASKS_UPDATE,
        Capability.TASKS_TRANSITION,
        Capability.TASKS_BULK_PREVIEW,
        Capability.TASKS_BULK_CONFIRM,
        # The Commitment plane (WP-TM-05) names a Principal, not a source, for
        # the identical reason the task plane does: a Commitment is opened
        # directly by a Principal or accepted through an accepted review
        # decision, never through a configured source's ingest path, so its
        # rows carry no `source_id` and no `enrollment_id` for a scope to be
        # compared against. `commitments.waiting_on` is scopeless for the same
        # reason: it is an assembled read over the same two scopeless planes,
        # naming no source of its own.
        Capability.COMMITMENTS_READ,
        Capability.COMMITMENTS_LIST,
        Capability.COMMITMENTS_WAITING_ON,
        Capability.COMMITMENTS_CREATE,
        Capability.COMMITMENTS_CLOSE,
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
