"""CRL-WP-03: the Capture archive / restore use case.

One function, `transition_capture`, that a later checkpoint's `capture.archive`
and `capture.restore` handlers call with the Authorization `invoke` already
resolved and the unit of work it already opened. Until then no Capability
reaches it; tests drive it directly. It restates no rule the domain or the
store owns: intent normalization and the digest are `domain.capture.lifecycle`,
alternation and the honest receipt are the domain's value objects, and
contiguity, alternation and same-owner protection are also the tables'.

**One unit of work, one fixed order** (plan (b.5), (h); MR-C06):

1. take the root `FOR NO KEY UPDATE` -- a foreign or absent root is
   `not_found`, before anything else is read, so neither the key, the state
   nor the revision of another Principal's root can shape the answer;
2. look up the idempotency key -- the same intent returns the original receipt
   (even after an inverse transition, CW-008), a changed intent is
   `conflict/idempotency_key`;
3. read the current lifecycle and decide: a stale expected revision is
   `conflict/expected_lifecycle_revision` even when the state is already the
   requested one; a current same-state request is an honest NO_OP;
4. on APPLIED: the job effects (suspend on archive, resume under then-current
   eligibility on restore), then the event;
5. the receipt -- a key collision here can only be another root, and is
   `conflict/idempotency_key` with everything rolled back;
6. on APPLIED only: stage exactly one `capture` `state_changed` Record Event,
   flushed by the unit of work's exit after all of the above.

Every refusal raises an `ApplicationError` out of the unit of work, so nothing
it staged commits and no draft flushes (T-18). There is no savepoint anywhere.

**What a Record Event carries** (plan (b), MR-C02/C03): the durable Principal,
`record_version` = the root's current head version number (the transition
appends no content version), `changed_fields` = `CAPTURE_LIFECYCLE_FIELDS`,
the head version's classification, the lifecycle receipt as source receipt.
Never the reason, a digest, the key or text.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime
from types import MappingProxyType
from typing import Final

from my_pa.application.authorization import Authorization
from my_pa.application.errors import (
    ApplicationError,
    ConflictError,
    InternalError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.contracts.ports import UnitOfWork
from my_pa.domain.capture.lifecycle import (
    CaptureLifecycleEvent,
    CaptureLifecycleIntent,
    CaptureLifecycleKeyConflictError,
    CaptureLifecycleOperation,
    CaptureLifecycleOutcome,
    CaptureLifecycleReasonError,
    CaptureLifecycleReceipt,
    CaptureLifecycleRevisionError,
    CaptureProcessingEligibility,
    CaptureProcessingSubject,
    StaleCaptureLifecycleRevisionError,
    decide_transition,
)
from my_pa.domain.capture.submission import MAX_IDEMPOTENCY_KEY_CHARACTERS
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.record_events import (
    CAPTURE_LIFECYCLE_FIELDS,
    RecordEventKind,
    capture_record_event,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = [
    "LIFECYCLE_SOURCE_CAPABILITIES",
    "CaptureLifecycleResult",
    "always_eligible",
    "transition_capture",
]

#: The operation name each lifecycle event records as `source_capability`. The
#: same strings the later `Capability.CAPTURE_ARCHIVE` / `CAPTURE_RESTORE` will
#: carry; stated here because no Capability exists yet at this checkpoint.
LIFECYCLE_SOURCE_CAPABILITIES: Final[Mapping[CaptureLifecycleOperation, str]] = MappingProxyType(
    {
        CaptureLifecycleOperation.ARCHIVE: "capture.archive",
        CaptureLifecycleOperation.RESTORE: "capture.restore",
    }
)


def always_eligible(subject: CaptureProcessingSubject) -> CaptureProcessingEligibility:
    """The current build's then-current policy: no restriction beyond the saved ceiling.

    No capture-processing enablement setting exists (plan (a)), so restore
    re-exposes withdrawn work as eligible and the pipeline still enforces the
    immutable saved policy ceiling (D-95). A composition with a real policy
    passes its own resolver.
    """
    del subject
    return CaptureProcessingEligibility.ELIGIBLE


@dataclass(frozen=True, slots=True)
class CaptureLifecycleResult:
    """The receipt a request is answered with, and whether it is a replay.

    A replayed receipt is the *original* outcome and is never presented as
    the root's current state (CW-008).
    """

    receipt: CaptureLifecycleReceipt
    replayed: bool


def _intent(
    *,
    principal_id: str,
    capture_id: str,
    operation: CaptureLifecycleOperation,
    expected_lifecycle_revision: object,
    reason: object,
    idempotency_key: object,
) -> CaptureLifecycleIntent:
    """The normalized intent, or the field-naming refusal (raised outside handlers)."""
    failure: ApplicationError | None = None
    intent: CaptureLifecycleIntent | None = None
    try:
        validate_identifier(capture_id, IdKind.CAPTURE)
    except InvalidIdentifierError:
        failure = InvalidRequestError(SafeDetail.CAPTURE_ID)
    if failure is None and (
        not isinstance(idempotency_key, str)
        or not 1 <= len(idempotency_key) <= MAX_IDEMPOTENCY_KEY_CHARACTERS
    ):
        failure = InvalidRequestError(SafeDetail.IDEMPOTENCY_KEY)
    if failure is None:
        try:
            intent = CaptureLifecycleIntent(
                owner_principal_id=principal_id,
                capture_id=capture_id,
                operation=operation,
                expected_lifecycle_revision=expected_lifecycle_revision,  # type: ignore[arg-type]
                reason=reason,  # type: ignore[arg-type]
            )
        except CaptureLifecycleRevisionError:
            failure = InvalidRequestError(SafeDetail.EXPECTED_LIFECYCLE_REVISION)
        except CaptureLifecycleReasonError:
            failure = InvalidRequestError(SafeDetail.REASON)
    if failure is not None:
        raise failure
    if intent is None:  # pragma: no cover - every branch above assigns or raises
        raise InternalError()
    return intent


def transition_capture(
    unit_of_work: UnitOfWork,
    authorization: Authorization,
    *,
    operation: CaptureLifecycleOperation,
    capture_id: str,
    expected_lifecycle_revision: object,
    reason: object,
    idempotency_key: str,
    now: datetime,
    eligibility: Callable[
        [CaptureProcessingSubject], CaptureProcessingEligibility
    ] = always_eligible,
) -> CaptureLifecycleResult:
    """Archive or restore one owned Capture root, or answer with its receipt.

    `now` is the application clock read once by the caller: it is the event's
    `transitioned_at`, the receipt's `issued_at` and the Record Event's
    `occurred_at`, and it never enters the digest. Port failures propagate as
    the port's own errors for the handler's translation.
    """
    operation = CaptureLifecycleOperation(operation)
    principal_id = authorization.principal.principal_id
    intent = _intent(
        principal_id=principal_id,
        capture_id=capture_id,
        operation=operation,
        expected_lifecycle_revision=expected_lifecycle_revision,
        reason=reason,
        idempotency_key=idempotency_key,
    )
    lifecycle = unit_of_work.capture_lifecycle

    # 1. The root, first. A foreign root and an absent one are the same answer.
    if not lifecycle.lock_root(capture_id, principal_id=principal_id):
        raise NotFoundError(SafeDetail.CAPTURE_ID)

    # 2. The key. Same intent: the original receipt, whatever happened since.
    digest = intent.digest
    prior = lifecycle.receipt(idempotency_key, principal_id=principal_id)
    if prior is not None:
        if prior.intent_digest != digest:
            raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)
        return CaptureLifecycleResult(receipt=prior, replayed=True)

    # 3. Decide against the current lifecycle.
    projection = lifecycle.latest(capture_id, principal_id=principal_id)
    stale = False
    try:
        decision = decide_transition(projection, operation, intent.expected_lifecycle_revision)
    except StaleCaptureLifecycleRevisionError:
        stale = True
    if stale:
        raise ConflictError(SafeDetail.EXPECTED_LIFECYCLE_REVISION)

    receipt_id = issue_identifier(IdKind.CAPTURE_LIFECYCLE_RECEIPT)
    applied = decision.outcome is CaptureLifecycleOutcome.APPLIED
    event_id = projection.latest_event_id
    if applied:
        event = CaptureLifecycleEvent.following(
            projection,
            decision,
            event_id=issue_identifier(IdKind.CAPTURE_LIFECYCLE_EVENT),
            transitioned_at=now,
            intent_digest=digest,
            correlation_id=authorization.correlation_id,
            audit_id=authorization.audit_id,
        )
        # 4. Job rows (after the root, before the event), then the event.
        if operation is CaptureLifecycleOperation.ARCHIVE:
            lifecycle.suspend_jobs(capture_id, principal_id=principal_id)
        else:
            lifecycle.resume_jobs(capture_id, principal_id=principal_id, eligibility=eligibility)
        lifecycle.record_event(event, principal_id=principal_id)
        event_id = event.event_id

    # 5. The receipt: the original outcome of this key.
    receipt = CaptureLifecycleReceipt(
        receipt_id=receipt_id,
        owner_principal_id=principal_id,
        idempotency_key=idempotency_key,
        capture_id=capture_id,
        operation=operation,
        intent_digest=digest,
        expected_lifecycle_revision=decision.expected_lifecycle_revision,
        resulting_lifecycle_revision=decision.resulting_lifecycle_revision,
        outcome=decision.outcome,
        event_id=event_id,
        issued_at=now,
        correlation_id=authorization.correlation_id,
        audit_id=authorization.audit_id,
    )
    collided = False
    try:
        lifecycle.record_receipt(receipt, principal_id=principal_id)
    except CaptureLifecycleKeyConflictError:
        collided = True
    if collided:
        raise ConflictError(SafeDetail.IDEMPOTENCY_KEY)

    # 6. APPLIED only: one Record Event, flushed at the unit of work's exit.
    if applied:
        head = unit_of_work.captures.version(capture_id, principal_id=principal_id)
        if head is None:  # a locked, owned root always has its first version
            raise InternalError()
        unit_of_work.record_events.stage(
            capture_record_event(
                principal_id=authorization.principal.principal_id,
                capture_id=capture_id,
                event_kind=RecordEventKind.STATE_CHANGED,
                version_number=head.version_number,
                changed_fields=CAPTURE_LIFECYCLE_FIELDS,
                capability=LIFECYCLE_SOURCE_CAPABILITIES[operation],
                classification=head.classification,
                occurred_at=now,
                receipt_id=receipt_id,
                correlation_id=authorization.correlation_id,
            )
        )
    return CaptureLifecycleResult(receipt=receipt, replayed=False)
