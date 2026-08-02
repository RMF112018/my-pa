"""The one place principal, purpose, capability, and scope are decided.

`docs/architecture/module-boundaries.md` section 5.6 says policy "is not hidden
in transport or adapter conditionals". This module is what that sentence buys:
every capability reaches `domain.policy.decision.evaluate` through `authorize`
and through nothing else, so there is one answer to "may this happen" rather
than eight of them that could drift.

**The authorized scope is read, never supplied.** `PolicyRequest.authorized_source_ids`
comes from the enrollments the principal actually holds, loaded inside the same
transaction the request runs in. A caller cannot state what it is entitled to;
it can only state what it wants, and the two are compared. That is the
difference between an authorization check and a formality, and it is why this
function needs the unit of work rather than being a pure function of the
command.

**The requested scope is derived from the command, not declared beside it.**
`_requested_scope` reads the source out of the command itself. A request that
declared a narrow scope in its metadata and then named a wider one in its
payload would be authorized against the declaration and executed against the
payload; there is no declaration here to disagree with.

Three shapes of derivation, and each fails closed:

* a command naming a source contributes that source;
* a command naming an enrollment contributes the source of that enrollment *if
  the principal holds it*, and the empty set otherwise — so an enrollment
  belonging to someone else is indistinguishable from one that does not exist,
  which is what section 10 requires of `denied`;
* a command naming an operation or an object resolves it to a source and
  contributes that, or the empty set when the lookup finds nothing.

An empty requested scope is not a wildcard. `domain.policy.decision` treats it
as unauthorized for every capability except `capabilities.get`, which describes
the interface itself and carries no scope at all.

**The audit event is written here and not by the caller.** `audit_event_for`
derives outcome and reason from the decision, so the record and the decision
cannot disagree. The denial *reason* is recorded and never returned: an operator
reading the audit can see why, and a caller probing for the difference between
"you may not" and "it is not there" cannot.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from my_pa.application.commands import (
    Command,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetSourceMetadata,
    GetSourceStatus,
    ListSources,
    ReadKnowledge,
    SearchKnowledge,
)
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.audit.events import audit_event_for
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import PolicyDecision, PolicyRequest, evaluate
from my_pa.domain.source.enrollment import Enrollment
from my_pa.domain.source.registry import issue_identifier

__all__ = ["Authorization", "authorize"]


@dataclass(frozen=True, slots=True)
class Authorization:
    """The outcome of the one authorization, and what the use case may act on.

    A handler receives this instead of a principal, which is deliberate: there
    is no `principal.is_operator` for a use case to consult and no scope for it
    to widen. What it gets is the decision that was already made and the
    enrollments that were already loaded.
    """

    principal: Principal
    capability: Capability
    purpose: Purpose
    correlation_id: str
    at: datetime
    decision: PolicyDecision
    requested_source_ids: frozenset[str]
    enrollments: tuple[Enrollment, ...]

    @property
    def allowed(self) -> bool:
        """Whether the request may proceed."""
        return self.decision.allowed

    def covering(self, source_id: str) -> tuple[Enrollment, ...]:
        """The principal's enrollments over `source_id`, in acceptance order.

        Order is by acceptance time and then identifier, so "the enrollment"
        means the same one on two calls when a caller has not named which.
        """
        return tuple(
            sorted(
                (e for e in self.enrollments if e.source_id == source_id),
                key=lambda e: (e.accepted_at, e.enrollment_id),
            )
        )

    def enrollment(self, enrollment_id: str) -> Enrollment | None:
        """The principal's enrollment with this identifier, or `None`."""
        return next((e for e in self.enrollments if e.enrollment_id == enrollment_id), None)


def _requested_scope(
    unit_of_work: UnitOfWork, command: Command, enrollments: tuple[Enrollment, ...]
) -> frozenset[str]:
    """The sources this command would read, derived from the command itself."""
    match command:
        case GetCapabilities():
            return frozenset()
        case ListSources() | GetSourceMetadata() | FetchSource() | EnrollSource():
            return frozenset({command.source_id})
        case SearchKnowledge() | ReadKnowledge():
            return _scope_of_enrollment(command.enrollment_id, enrollments)
        case GetSourceStatus():
            return _status_scope(unit_of_work, command, enrollments)


def _scope_of_enrollment(enrollment_id: str, enrollments: tuple[Enrollment, ...]) -> frozenset[str]:
    """The source of one of the principal's own enrollments, or nothing.

    Restricted to the principal's enrollments on purpose. Reading the enrollment
    row directly would resolve a grant the principal does not hold and then deny
    it one rule later, which answers the same question with an extra read and a
    slightly different timing.
    """
    return frozenset(e.source_id for e in enrollments if e.enrollment_id == enrollment_id)


def _status_scope(
    unit_of_work: UnitOfWork, command: GetSourceStatus, enrollments: tuple[Enrollment, ...]
) -> frozenset[str]:
    """The source behind whichever single subject a status request named."""
    if command.source_id is not None:
        return frozenset({command.source_id})
    if command.enrollment_id is not None:
        return _scope_of_enrollment(command.enrollment_id, enrollments)
    if command.operation_id is not None:
        operation = unit_of_work.operations.operation(command.operation_id)
        if operation is None:
            return frozenset()
        return _scope_of_enrollment(operation.enrollment_id, enrollments)
    if command.source_object_id is not None:
        source_id = unit_of_work.sources.source_of_object(command.source_object_id)
        return frozenset() if source_id is None else frozenset({source_id})
    # `GetSourceStatus` refuses to exist without exactly one subject, so nothing
    # reaches this line. It is the empty set rather than an error because the
    # rule this module is built on is that an unresolved scope authorizes
    # nothing, and a default that failed open would be the one exception to it.
    return frozenset()


def authorize(
    unit_of_work: UnitOfWork,
    *,
    principal: Principal,
    purpose: Purpose,
    command: Command,
    correlation_id: str,
    at: datetime,
    classification: Classification = Classification.PRIVATE_LOCAL,
) -> Authorization:
    """Decide one request, record the decision, and return what was decided.

    Returns a denial rather than raising it. The caller has to leave its
    transaction normally for the audit event to commit, and an exception thrown
    from here would roll back the record of the refusal along with it.

    `correlation_id` is issued by the caller rather than here, because the same
    identifier has to appear on the response envelope of a request that never
    reached this function at all.
    """
    validate_identifier(correlation_id, IdKind.CORRELATION)
    enrollments = unit_of_work.enrollments.for_principal(principal.principal_id)
    requested = _requested_scope(unit_of_work, command, enrollments)
    decision = evaluate(
        PolicyRequest(
            principal=principal,
            purpose=purpose,
            capability=command.capability,
            classification=classification,
            requested_source_ids=requested,
            authorized_source_ids=frozenset(e.source_id for e in enrollments),
        )
    )
    unit_of_work.audit.record(
        audit_event_for(
            audit_id=issue_identifier(IdKind.AUDIT),
            correlation_id=correlation_id,
            principal_id=principal.principal_id,
            capability=command.capability,
            purpose=purpose,
            decision=decision,
            recorded_at=at,
            scope_source_id_count=len(requested),
        )
    )
    return Authorization(
        principal=principal,
        capability=command.capability,
        purpose=purpose,
        correlation_id=correlation_id,
        at=at,
        decision=decision,
        requested_source_ids=requested,
        enrollments=enrollments,
    )
