"""The one place principal, purpose, capability, and scope are decided.

`docs/architecture/module-boundaries.md` section 5.6 says policy "is not hidden
in transport or adapter conditionals". This module is what that sentence buys:
every capability reaches `domain.policy.decision.evaluate` through `authorize`
and through nothing else, so there is one answer to "may this happen" rather
than twelve of them that could drift.

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
as unauthorized for every capability outside its `_SCOPELESS` set —
`capabilities.get`, which describes the interface itself, and the four capture
capabilities, which read and write a product-owned record that belongs to no
configured source.

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
    CreateCapture,
    DecideReviewCase,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetSourceMetadata,
    GetSourceStatus,
    ListCaptures,
    ListReviewCases,
    ListSources,
    ReadCapture,
    ReadKnowledge,
    ReviseCapture,
    SearchCaptures,
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
    #: The caller's own identifier for this request. Correlation input, exactly
    #: as `metadata.principal_id` is: nothing authorizes on it. It is carried
    #: here because a use case that records an admission has to record which
    #: request admitted it, and the alternative — handing every handler the
    #: whole `RequestMetadata` — would put a caller-controlled document inside
    #: the layer that decides what a result is.
    request_id: str
    #: The audit event this decision was recorded as. Already committed, on the
    #: sink's own connection, before this value exists (`D-34`), so a use case
    #: can store the *reference* inside its own transaction and a later reader
    #: can tie a stored record back to the decision that admitted it.
    audit_id: str
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
        # A capture is a product-owned record under `ADR-003` and belongs to no
        # configured source, so there is no source for it to contribute. That is
        # the empty set as a *measurement* rather than as a failure to resolve
        # one, and `domain.policy.decision._SCOPELESS` is where it is read that
        # way — a capability missing from that set is denied here instead, with
        # nothing to say the mapping was never made.
        case (
            GetCapabilities()
            | ReviseCapture()
            | ReadCapture()
            | ListCaptures()
            | SearchCaptures()
            | ListReviewCases()
            | DecideReviewCase()
        ):
            return frozenset()
        case CreateCapture():
            if command.context_source_object_id is None:
                return frozenset()
            source_id = unit_of_work.sources.source_of_object(command.context_source_object_id)
            return frozenset() if source_id is None else frozenset({source_id})
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
    request_id: str,
    at: datetime,
    classification: Classification = Classification.PRIVATE_LOCAL,
) -> Authorization:
    """Decide one request, record the decision, and return what was decided.

    Returns a denial rather than raising it. That was originally because the
    caller had to leave its transaction normally for the audit event to commit;
    since `D-34` gave the audit its own transaction that reason no longer holds,
    and the remaining one is better: a denial is a decision this function
    reached, and raising it would make it arrive at the caller the same way a
    port failure does — as an exception with no `Authorization` behind it — which
    is the one distinction `service.py`'s outcome 5 exists to keep.

    What an exception from here *does* still mean is that no decision was
    recorded. `unit_of_work.audit.record` is not wrapped, deliberately: a failure
    to persist an audit event leaves this function by raising, which rolls the
    caller's work back and fails the request closed
    (`module-boundaries.md` section 5.6).

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
    audit_id = issue_identifier(IdKind.AUDIT)
    unit_of_work.audit.record(
        audit_event_for(
            audit_id=audit_id,
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
        request_id=request_id,
        # Issued before `record` and returned only after it, so an
        # `Authorization` can only ever name an audit event that is already
        # durable: a failure to record raises out of this function and no
        # reference to a lost decision reaches a use case.
        audit_id=audit_id,
        at=at,
        decision=decision,
        requested_source_ids=requested,
        enrollments=enrollments,
    )
