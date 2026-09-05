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
        # The Relationship Memory plane names an Entity, not a source. A memory
        # is the product's own knowledge under ADR-003 — written by the
        # Principal about a person, never read out of a source root — so its
        # rows carry no `source_id` and no `enrollment_id` for a scope to be
        # compared against, exactly as a capture's and a managed document's do
        # not. Requiring one would make the whole plane permanently unusable;
        # naming one would be naming a grant this plane cannot hold.
        Capability.RELATIONSHIP_MEMORY_CREATE,
        Capability.RELATIONSHIP_MEMORY_GET,
        Capability.RELATIONSHIP_MEMORY_LIST,
        Capability.RELATIONSHIP_MEMORY_SEARCH,
        Capability.RELATIONSHIP_MEMORY_HISTORY,
        Capability.RELATIONSHIP_MEMORY_REVISE,
        Capability.RELATIONSHIP_MEMORY_ARCHIVE,
        Capability.RELATIONSHIP_MEMORY_RESTORE,
        # Phase B's four. Each names records of the acting Principal's own
        # partition and no configured source, so a request that states a scope
        # for one is a contradiction rather than a narrower ask.
        Capability.RELATIONSHIP_MEMORY_PROPOSE,
        Capability.ENTITIES_PROPOSALS_CREATE,
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_IDENTITY_HISTORY,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
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
        Capability.COMMITMENTS_SEARCH,
        Capability.COMMITMENTS_HISTORY,
        Capability.COMMITMENTS_WAITING_ON,
        Capability.COMMITMENTS_CREATE,
        Capability.COMMITMENTS_UPDATE,
        Capability.COMMITMENTS_CLOSE,
        # `context.prepare` names a query, not a source. The package it returns
        # may later cite enrolled source evidence, but the request itself does
        # not name a grant — naming one would turn a cross-plane assembly into
        # a search of one enrollment, which is `knowledge.search`. Until WP-KC-02
        # searches a plane, the requested scope is empty as a measurement.
        Capability.CONTEXT_PREPARE,
        # `context.feedback` names a ranking preference, not a source. The rows
        # it writes belong to the acting Principal's partition and carry no
        # `enrollment_id` and no grant a scope could be compared against.
        Capability.CONTEXT_FEEDBACK,
        # `goodnotes.work` and `goodnotes.propose` name a Principal's own
        # GoodNotes partition, not a source. Page versions and semantic
        # proposals carry no `enrollment_id` and no grant a scope could be
        # compared against. Requiring one would make both permanently unusable.
        Capability.GOODNOTES_WORK,
        Capability.GOODNOTES_PROPOSE,
        Capability.GOODNOTES_CONTENT,
        Capability.GOODNOTES_PULL,
        Capability.GOODNOTES_COMPLETE,
        Capability.GOODNOTES_STATUS,
        Capability.GSQS_START,
        Capability.GSQS_STATUS,
        # Intelligence artifacts name a Principal partition and a cycle run, not
        # a configured source. Requiring an enrollment would make the plane
        # unusable; naming one would be naming a grant this plane cannot hold.
        Capability.REPORTS_BEGIN_CYCLE,
        Capability.REPORTS_COMMIT,
        Capability.REPORTS_RECORD_RUN_STATE,
        Capability.REPORTS_READ,
        Capability.REPORTS_LATEST,
        Capability.REPORTS_LIST,
        Capability.REPORTS_SEARCH,
        Capability.REPORTS_RESOLVE_SET,
        # The entity plane's partition, not a source. An entity carries no
        # `enrollment_id` and no grant a requested scope could be compared
        # against -- it is the Principal's own record of a person, not an
        # extraction from an enrolled source. Requiring a scope would make every
        # one of them permanently unusable, which is how an unlisted capability
        # fails: silently, with `scope_not_authorized`, on every request.
        Capability.ENTITIES_SEARCH,
        Capability.ENTITIES_GET,
        Capability.ENTITIES_RESOLVE,
        Capability.ENTITIES_CONTEXT,
        Capability.ENTITIES_RELATIONSHIPS,
        Capability.ENTITIES_UNRESOLVED_MENTIONS,
        # The authoring half (`WP-RI-A-02`), scopeless for the identical reason
        # and named one at a time rather than by prefix. A write to this plane
        # has *less* to compare a scope against than a read does, not more: it
        # creates or corrects the Principal's own record of a person, and the
        # row it writes carries no `source_id` and no `enrollment_id` for a
        # requested scope to be checked against.
        Capability.ENTITIES_IDENTIFIERS_LIST,
        Capability.ENTITIES_ALIASES_LIST,
        Capability.ENTITIES_CREATE,
        Capability.ENTITIES_UPDATE,
        Capability.ENTITIES_ARCHIVE,
        Capability.ENTITIES_RESTORE,
        Capability.ENTITIES_IDENTIFIERS_BIND,
        Capability.ENTITIES_IDENTIFIERS_RETIRE,
        Capability.ENTITIES_IDENTIFIERS_SUPERSEDE,
        Capability.ENTITIES_ALIASES_ADD,
        Capability.ENTITIES_ALIASES_RETIRE,
        Capability.ENTITIES_ALIASES_SUPERSEDE,
        # The directed-relationship family is scopeless on exactly the same
        # argument, and the argument does not change because these six write.
        # An assignment and an edge carry no `source_id` and no `enrollment_id`
        # -- they are the Principal's own statement about the Principal's own
        # entities, and the scope they *do* name is a scope Entity, which is
        # another row in the same partition rather than a grant. Requiring a
        # source scope would make the whole family permanently unusable;
        # accepting one would let a request name a grant this plane cannot hold
        # and have it silently ignored.
        Capability.ENTITIES_ASSIGNMENTS_LIST,
        Capability.ENTITIES_ASSIGNMENTS_CREATE,
        Capability.ENTITIES_ASSIGNMENTS_REVISE,
        Capability.ENTITIES_ASSIGNMENTS_END,
        Capability.ENTITIES_RELATIONSHIPS_CREATE,
        Capability.ENTITIES_RELATIONSHIPS_REVISE,
        Capability.ENTITIES_RELATIONSHIPS_END,
        # WP-RI-A-04's three, here for the same reason and with one addition
        # worth stating: `entities.observe` *carries* a `source_id`, and that
        # is provenance written onto the row rather than a scope the request
        # holds. Comparing a caller's grant against a value the caller supplied
        # would be authorizing on the payload; and the same capability may name
        # a product-owned capture instead, which belongs to no configured source
        # at all (`ADR-003`), so a scope requirement would make that path
        # permanently unusable rather than merely wrong.
        Capability.ENTITIES_OBSERVATIONS_LIST,
        Capability.ENTITIES_OBSERVE,
        Capability.ENTITIES_UNRESOLVED_MENTIONS_RESOLVE,
        # `RI-ENT-WP-10`'s five record-family reads, scopeless on the identical
        # argument. A typed name, an address, a communication method, a project
        # participation and an affiliation are the Principal's own record of
        # their own contacts: those rows carry no `source_id` and no
        # `enrollment_id` for a requested scope to be checked against, so a
        # scope requirement would make all five permanently unusable and
        # accepting a scope would let a request name a grant this plane cannot
        # hold. Omitting them here is the silent failure this set's docstring
        # warns about -- `scope_not_authorized` on every request, with nothing
        # saying the capability was never mapped.
        Capability.ENTITIES_PROFILE,
        Capability.ENTITIES_NAMES_LIST,
        Capability.ENTITIES_ADDRESSES_LIST,
        Capability.ENTITIES_COMMUNICATION_LIST,
        Capability.ENTITIES_PARTICIPATIONS_LIST,
        Capability.ENTITIES_GRAPH,
        # `RI-ENT-WP-11`'s record-family writes, scopeless on the identical
        # argument, and the argument does not change because these write. A
        # typed name, an address, a communication method, a participation and an
        # affiliation are the Principal's own record of their own contacts:
        # those rows carry no `source_id` and no `enrollment_id` for a requested
        # scope to be checked against, so a scope requirement would make every
        # one of them permanently unusable and accepting a scope would let a
        # request name a grant this plane cannot hold. Omitting them here is the
        # silent failure this set's docstring warns about -- `scope_not_authorized`
        # on every request, with nothing saying the capability was never mapped.
        Capability.ENTITIES_NAMES_ADD,
        Capability.ENTITIES_NAMES_SUPERSEDE,
        Capability.ENTITIES_NAMES_RETIRE,
        Capability.ENTITIES_ADDRESSES_ADD,
        Capability.ENTITIES_ADDRESSES_REVISE,
        Capability.ENTITIES_ADDRESSES_RETIRE,
        Capability.ENTITIES_COMMUNICATION_ADD,
        Capability.ENTITIES_COMMUNICATION_REVISE,
        Capability.ENTITIES_COMMUNICATION_RETIRE,
        Capability.ENTITIES_PARTICIPATIONS_CREATE,
        Capability.ENTITIES_PARTICIPATIONS_REVISE,
        Capability.ENTITIES_PARTICIPATIONS_END,
        Capability.ENTITIES_AFFILIATIONS_CREATE,
        Capability.ENTITIES_AFFILIATIONS_REVISE,
        Capability.ENTITIES_AFFILIATIONS_END,
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
