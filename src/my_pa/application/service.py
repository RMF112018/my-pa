"""The eight capabilities, behind one authorization and one transaction.

`ApplicationService` has exactly one public method. That is the whole design.
A use case cannot be reached without going through `invoke`, `invoke` cannot
reach a use case without going through `authorize`, and there is no second door
— no per-capability entry point, no "internal" variant that skips the check, and
no handler a caller holds a reference to. Bypassing the authorization path is
therefore not something a use case is trusted not to do; it is something the
shape of this class does not offer.

**The transaction is opened once, around the decision and the work.** Leaving
`invoke`'s `with` block normally commits, which matters most on the paths that
look least like they need a transaction: a refusal returns out of the block
normally, so the audit event recording it commits, where raising from inside
would have rolled the record of the refusal back along with everything else.

**Which outcomes leave a durable trace, exhaustively.** This list is the whole
of it, because an incomplete disclosure of an audit gap is itself a gap, and one
case was missing from it before a reviewer measured `audit events: 0`:

1. *Policy denied the request.* Audited, and the audit commits. The reason is in
   the record and never in the answer.
2. *The declared capability and the payload's capability disagree.* A
   security-relevant refusal — it is the guard against a request authorized as
   one capability and executed as another — so it is audited as `failed`, inside
   the transaction, and the audit commits. It is `failed` rather than `denied`
   because no policy decision was reached: there is nothing to name a
   `DenialReason` from, and inventing one would misreport why the request
   stopped.
3. *Allowed, and the handler succeeded.* Audited as allowed; commits with the
   work.
4. *Allowed, and the handler then failed.* Audited as allowed, and then **rolled
   back with the failed work**, so a failed security-relevant action currently
   leaves no trace. That is a defect rather than a design. It is here because the
   rollback is also what stops a half-written enrollment from committing, and
   separating the two needs a second transaction and a durable audit store,
   neither of which exists in this build. `D-34` puts both in WP-4B.
5. *A command that could not be constructed at all.* Not audited, and cannot be:
   a malformed command is refused by its own `__post_init__` before `invoke` is
   called, so this layer never sees the attempt. Whatever calls it is the only
   thing that could record one.

**Provider reads happen inside that transaction.** `module-boundaries.md`
section 10 says long source fetches are not held inside database transactions,
and the reading here is bounded by `max_fetch_bytes` against a local filesystem
adapter — the rule's target is the worker's extraction path, which this package
does not own. What is gained is that the coverage a disclosure states and the
bytes the same response returns come from one consistent read. Should a provider
ever be remote, this is the sentence that has to change first.

**Nothing here decides what is authorized.** The handlers receive an
`Authorization`, not a `Principal`; there is no `is_operator` to consult, no
scope to widen, and the enrollments were loaded once by the shared path. What a
handler decides is what a *result* is, which is a different question.

**Every limit enforced here is the limit published by `capabilities.get`.**
`_effective_limits` builds one `EffectiveLimits` from validated configuration
and the domain's own ceilings, and that single object is what the manifest
publishes and what every clamp below reads. There is no second copy to drift
(`D-24`).
"""

from __future__ import annotations

import base64
from collections.abc import Callable, Iterator, Mapping
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from itertools import islice
from types import MappingProxyType
from typing import Any, Final, assert_never

from my_pa.application.authorization import Authorization, authorize
from my_pa.application.capabilities import build_capability_manifest, build_readiness_report
from my_pa.application.commands import (
    Command,
    EnrollSource,
    FetchSource,
    GetCapabilities,
    GetSourceMetadata,
    GetSourceStatus,
    ListSources,
    ReadKnowledge,
    Representation,
    SearchKnowledge,
)
from my_pa.application.disclosure import (
    Limitation,
    disclosure_for,
    eligible_total,
    unenrolled_disclosure,
)
from my_pa.application.errors import (
    AmbiguousRequestError,
    ApplicationError,
    ConflictError,
    DeniedError,
    InternalError,
    InvalidRequestError,
    NotFoundError,
    QuarantinedError,
    SafeDetail,
    UnavailableError,
    UnsupportedError,
    problem_detail,
)
from my_pa.contracts.ports import (
    Acceptance,
    EvidenceUnavailableError,
    PortError,
    SearchOutcome,
    SourceProviders,
    UnitOfWork,
    UnknownScopeError,
)
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.disclosure import Disclosure, SourceReference, Truncation
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.audit.events import AuditEvent, AuditOutcome
from my_pa.domain.common.coverage import CoverageState
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.provenance import TrustLevel
from my_pa.domain.common.time import format_rfc3339, utc_now
from my_pa.domain.extraction.coverage import CoverageCounts
from my_pa.domain.extraction.text import ExtractionStatus, extract_text
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.policy.decision import POLICY_VERSION
from my_pa.domain.search.query import (
    DEFAULT_SNIPPET_WORDS,
    MAX_PAGE_SIZE,
    EmptySearchQueryError,
    SearchCursorError,
    SearchQuery,
    SearchQueryError,
    SearchRequest,
    label_for_media_type,
)
from my_pa.domain.source.enrollment import (
    MAX_ENROLLMENT_BYTES,
    MAX_ENROLLMENT_DEPTH,
    MAX_ENROLLMENT_ITEMS,
    Enrollment,
    EnrollmentBoundsError,
    EnrollmentConflictError,
    EnrollmentRequest,
    EnrollmentScope,
)
from my_pa.domain.source.provider import (
    ObjectKind,
    ProviderError,
    SourceObject,
    SourceProvider,
    TraversalDeniedError,
    VersionChangedError,
)
from my_pa.domain.source.registry import issue_identifier

__all__ = ["ApplicationService"]

#: The absence of truncation, as one shared immutable value. A default argument
#: may not be a constructor call, and a frozen contract model is safe to share.
_NO_TRUNCATION: Final = Truncation()


@dataclass(frozen=True, slots=True)
class _Result:
    """One capability's payload and the envelope that must accompany it."""

    payload: dict[str, Any]
    disclosure: Disclosure


def _effective_limits(configured: EffectiveLimits) -> EffectiveLimits:
    """The limits that will actually be enforced, which are the ones published.

    Configuration cannot raise a bound the domain already fixes: a page size
    above `domain.search.query.MAX_PAGE_SIZE` would be published and then not
    honoured by `knowledge.search`, and an enrollment depth above
    `domain.source.enrollment.MAX_ENROLLMENT_DEPTH` would be published and then
    refused by the value object that enforces it. Taking the smaller of the two
    here is what keeps the published number equal to the enforced one, in the
    one direction that cannot be wrong (`D-24`).
    """
    max_page_size = min(configured.max_page_size, MAX_PAGE_SIZE)
    return EffectiveLimits(
        max_page_size=max_page_size,
        default_page_size=min(configured.default_page_size, max_page_size),
        max_fetch_bytes=configured.max_fetch_bytes,
        max_enrollment_depth=min(configured.max_enrollment_depth, MAX_ENROLLMENT_DEPTH),
    )


def _observed(source_object: SourceObject) -> dict[str, Any]:
    """One object as the contract may disclose it: opaque, and with no locator."""
    return {
        "source_object_id": source_object.source_object_id,
        "version_id": source_object.version_id,
        "kind": source_object.kind.value,
        "media_type": source_object.media_type,
        "size_bytes": source_object.size_bytes,
        "modified_at": format_rfc3339(source_object.modified_at),
    }


def _reference(source_object: SourceObject) -> SourceReference:
    return SourceReference(
        source_id=source_object.source_id,
        source_object_id=source_object.source_object_id,
        version_id=source_object.version_id,
    )


def _state_of_coverage(state: CoverageState) -> SourceStatusState:
    """The public status a coverage state implies.

    Written out exhaustively rather than with a fallback, because a fallback is
    how a newly added coverage state would silently be reported as something it
    is not. `assert_never` makes that a type error instead.
    """
    match state:
        case CoverageState.NOT_ENROLLED:
            return SourceStatusState.CONFIGURED
        case CoverageState.ELIGIBLE:
            return SourceStatusState.ACCEPTED
        case CoverageState.QUEUED:
            return SourceStatusState.QUEUED
        case CoverageState.PROCESSED:
            return SourceStatusState.COMPLETE_FOR_SCOPE
        case CoverageState.PARTIALLY_PROCESSED | CoverageState.STALE | CoverageState.SUPERSEDED:
            # All three say the answer is incomplete: one because outcomes are
            # mixed or outstanding, and two because the snapshot no longer
            # describes the source. None of them may report completion.
            return SourceStatusState.PARTIALLY_COMPLETE
        case CoverageState.QUARANTINED:
            return SourceStatusState.QUARANTINED
        case CoverageState.UNSUPPORTED:
            return SourceStatusState.UNSUPPORTED
        case CoverageState.UNAVAILABLE:
            return SourceStatusState.UNAVAILABLE
    assert_never(state)


def _state_of_outcome(outcome: ExtractionStatus | None) -> SourceStatusState:
    """The public status one object's stored outcome implies."""
    match outcome:
        case None:
            # Enrolled and no outcome recorded. `accepted` rather than
            # `complete_for_scope`, because nothing has happened to it yet.
            return SourceStatusState.ACCEPTED
        case ExtractionStatus.EXTRACTED:
            return SourceStatusState.COMPLETE_FOR_SCOPE
        case ExtractionStatus.UNSUPPORTED:
            return SourceStatusState.UNSUPPORTED
        case ExtractionStatus.QUARANTINED:
            return SourceStatusState.QUARANTINED
    assert_never(outcome)


def _port_failure(error: PortError) -> ApplicationError:
    """The public error a port failure is, by classification and nothing else."""
    if isinstance(error, UnknownScopeError):
        return NotFoundError(SafeDetail.ENROLLMENT_ID)
    if isinstance(error, EvidenceUnavailableError):
        return UnavailableError()
    return InternalError()


def _provider_failure(error: ProviderError) -> ApplicationError:
    """The public error a source-provider failure is.

    `docs/specs` section 10 puts these in three rows with three different retry
    answers, and `INV-PKL-007` forbids converting one into another — a refusal
    stays `denied`, a changed object stays `conflict`, and a shortage stays
    `unavailable`. The provider already refuses to distinguish "absent" from
    "outside the root" in its message, and giving both the same public code is
    what preserves that.
    """
    if isinstance(error, TraversalDeniedError):
        return DeniedError()
    if isinstance(error, VersionChangedError):
        return ConflictError(SafeDetail.SOURCE_OBJECT_ID)
    return UnavailableError(SafeDetail.SOURCE_OBJECT_ID)


@contextmanager
def _translated() -> Iterator[None]:
    """Run a block, converting a port or provider failure into a public error.

    The `raise` is outside the `except` block, which is the same discipline the
    persistence and provider layers apply: `raise … from None` clears
    `__cause__` and leaves the original in `__context__`, where a rendered
    traceback would show whatever it carried. Leaving the handler first is what
    actually empties it.
    """
    failure: ApplicationError | None = None
    try:
        yield
    except PortError as error:
        failure = _port_failure(error)
    except ProviderError as error:
        failure = _provider_failure(error)
    if failure is not None:
        raise failure


class ApplicationService:
    """Every capability this build can execute, behind one entry point."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], UnitOfWork],
        providers: SourceProviders,
        limits: EffectiveLimits,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._providers = providers
        self._limits = _effective_limits(limits)
        self._clock = clock

    def invoke(
        self, metadata: RequestMetadata, command: Command, *, principal: Principal
    ) -> ResponseEnvelope:
        """Execute one request and return the envelope describing what happened.

        `principal` is authenticated context supplied by the composition root.
        `metadata.principal_id` is correlation input and is deliberately not
        consulted: a caller-supplied identity is never trusted alone
        (`docs/specs` section 8.2).

        **No exception leaves this method.** The first two handlers classify what
        this layer already understands. The third is a terminal catch, and it is
        deliberate rather than defensive: a `SQLAlchemyError` escaping an
        unwrapped statement carries the statement and its bound parameters, and
        letting one out of here would put the obligation to catch it — and the
        redaction that obligation implies — on every transport that WP-4B writes.
        A response is built in exactly one place, so the failure classification
        has to be in that place too.

        `InternalError` is constructed *outside* the handler, so the exception it
        replaces is not left in its `__context__`. That is the same discipline the
        persistence and provider layers apply, and here it is what keeps a
        rendered traceback of the public error from carrying the driver message
        the catch exists to withhold. Nothing of the original reaches the payload
        either way: `problem_detail` reads a code and a closed token set, and
        there is no path from an exception's text to a `ProblemDetail`.

        `Exception` and not `BaseException`: a `KeyboardInterrupt` or a
        `SystemExit` is the operator stopping the process, and converting that
        into a 500-shaped answer would be this method deciding something it has
        no business deciding.
        """
        correlation_id = issue_identifier(IdKind.CORRELATION)
        started_at = self._clock()
        failure: ApplicationError | None = None
        result: _Result | None = None
        unclassified = False
        try:
            result = self._run(
                metadata, command, principal=principal, correlation_id=correlation_id, at=started_at
            )
        except ApplicationError as error:
            failure = error
        except PortError as error:
            # A port failure raised outside a translated block — from the shared
            # authorization path's own reads, for instance — still has to reach
            # the caller as a classified public error rather than as a crash.
            failure = _port_failure(error)
        except Exception:
            # Nothing that reaches here has been classified, so nothing about it
            # is safe to report beyond that the request did not complete.
            unclassified = True
        if unclassified:
            failure = InternalError()
        if failure is not None:
            return ResponseEnvelope(
                request_id=metadata.request_id,
                correlation_id=correlation_id,
                completed_at=self._clock(),
                error=problem_detail(failure, correlation_id=correlation_id),
            )
        if result is None:
            raise InternalError()
        return ResponseEnvelope(
            request_id=metadata.request_id,
            correlation_id=correlation_id,
            completed_at=self._clock(),
            result=result.payload,
            disclosure=result.disclosure,
        )

    def _run(
        self,
        metadata: RequestMetadata,
        command: Command,
        *,
        principal: Principal,
        correlation_id: str,
        at: datetime,
    ) -> _Result:
        """Authorize, then execute, then commit — or refuse and still commit.

        The capability is checked against the command before anything else. The
        two arrive from a transport separately, and a request whose metadata
        declares one capability while its payload performs another would be
        authorized against the declaration; there is no reading of that which is
        a valid request.

        The check runs *inside* the transaction, which it did not before. It is a
        security-relevant refusal — the whole of what it guards is a request
        being authorized as one capability and executed as another — and
        `AGENTS.md` section 5 requires a denied attempt to produce a
        proportionate audit event. Checking it before the transaction opened
        produced none at all, which a reviewer measured. The capability recorded
        is the *declared* one, because that is what authority would have been
        evaluated against.

        Both refusals return out of the block normally rather than raising from
        inside it, and for the same reason: raising would roll the record of the
        refusal back along with everything else.
        """
        mismatch = metadata.capability is not command.capability
        with self._unit_of_work() as unit_of_work:
            if mismatch:
                unit_of_work.audit.record(
                    AuditEvent(
                        audit_id=issue_identifier(IdKind.AUDIT),
                        correlation_id=correlation_id,
                        principal_id=principal.principal_id,
                        capability=metadata.capability,
                        purpose=metadata.purpose,
                        # `failed` rather than `denied`: no policy decision was
                        # reached, so there is no `DenialReason` to name and
                        # inventing one would misreport why the request stopped.
                        outcome=AuditOutcome.FAILED,
                        policy_version=POLICY_VERSION,
                        recorded_at=at,
                    )
                )
            else:
                authorization = authorize(
                    unit_of_work,
                    principal=principal,
                    purpose=metadata.purpose,
                    command=command,
                    correlation_id=correlation_id,
                    at=at,
                )
                if authorization.allowed:
                    return _HANDLERS[command.capability](self, unit_of_work, authorization, command)
        # Reached only after the transaction committed, which is what preserves
        # the audit event recording the refusal.
        if mismatch:
            raise InvalidRequestError(SafeDetail.SUBJECT)
        raise DeniedError()

    # ---- the eight use cases -----------------------------------------------

    def _capabilities_get(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetCapabilities
    ) -> _Result:
        """What this build supports, derived from what it has wired."""
        manifest = build_capability_manifest(implemented=frozenset(_HANDLERS), limits=self._limits)
        return _Result(
            payload={
                "manifest": manifest.to_canonical_dict(),
                "readiness": build_readiness_report(manifest).to_canonical_dict(),
            },
            disclosure=unenrolled_disclosure(authorization.at),
        )

    def _sources_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListSources
    ) -> _Result:
        """The immediate children of one container, bounded by the page size.

        Immediate children only, and one page of them. Nothing here recurses: a
        caller that wants a subtree asks for one level at a time and decides for
        itself when to stop, so no single request can walk a volume
        (`docs/specs` section 9.2). One row past the page is fetched so that
        truncation is a fact rather than a guess.
        """
        enrollment = self._one_enrollment(authorization, command.source_id, command.enrollment_id)
        provider = self._provider(command.source_id)
        page_size = self._page_size(command.page_size)
        with _translated():
            children = tuple(
                islice(provider.list_children(command.parent_object_id), page_size + 1)
            )
        truncated = len(children) > page_size
        page = children[:page_size]
        return _Result(
            payload={"objects": [_observed(child) for child in page]},
            disclosure=self._disclose(
                unit_of_work,
                authorization,
                enrollment,
                trust_level=TrustLevel.SOURCE_ORIGINAL,
                trust_basis=("source_provider",),
                source_references=tuple(_reference(child) for child in page),
                truncation=Truncation(
                    is_truncated=truncated, reason="page_size_reached" if truncated else None
                ),
                extra_limitations=(Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else (),
            ),
        )

    def _sources_metadata(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetSourceMetadata
    ) -> _Result:
        """Normalized metadata for one object, plus what has happened to it.

        The supported operations are listed rather than implied, and the list is
        derived from the object's kind. There is no mutating operation to list,
        because the port that would perform one has no such method.
        """
        enrollment = self._one_enrollment(authorization, command.source_id, command.enrollment_id)
        provider = self._provider(command.source_id)
        with _translated():
            observed = provider.metadata(command.source_object_id)
            outcome = unit_of_work.knowledge.outcome_for_object(
                enrollment_id=enrollment.enrollment_id,
                source_object_id=command.source_object_id,
            )
        operations = (
            ["metadata", "list_children"]
            if observed.kind is ObjectKind.CONTAINER
            else ["metadata", "fetch"]
        )
        return _Result(
            payload={
                **_observed(observed),
                "supported_operations": operations,
                "status": _state_of_outcome(outcome).value,
            },
            disclosure=self._disclose(
                unit_of_work,
                authorization,
                enrollment,
                trust_level=TrustLevel.SOURCE_ORIGINAL,
                trust_basis=("source_provider",),
                source_references=(_reference(observed),),
            ),
        )

    def _sources_fetch(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: FetchSource
    ) -> _Result:
        """Bounded bytes from one object, or the text they decode to.

        Metadata is read first because that is what binds the observation the
        read is checked against: the provider compares the descriptor it opened
        against the version it last described, and a difference is `conflict`
        rather than stale bytes labelled current. `max_bytes` is the smaller of
        what the caller asked for and what configuration permits, so a request
        cannot widen the ceiling.
        """
        enrollment = self._one_enrollment(authorization, command.source_id, command.enrollment_id)
        provider = self._provider(command.source_id)
        ceiling = self._limits.max_fetch_bytes
        max_bytes = ceiling if command.max_bytes is None else min(command.max_bytes, ceiling)
        with _translated():
            observed = provider.metadata(command.source_object_id)
            content = provider.fetch(command.source_object_id, max_bytes=max_bytes)

        if command.representation is Representation.RAW_BYTES:
            payload: dict[str, Any] = {
                "representation": Representation.RAW_BYTES.value,
                "version_id": content.version_id,
                "media_type": content.media_type,
                "byte_count": len(content.content),
                "content_base64": base64.b64encode(content.content).decode("ascii"),
                "is_truncated": content.is_truncated,
            }
            trust_level, basis = TrustLevel.SOURCE_ORIGINAL, ("source_provider",)
        else:
            outcome = extract_text(
                source_id=command.source_id,
                source_object_id=command.source_object_id,
                observed_version_id=observed.version_id,
                content_version_id=content.version_id,
                media_type=content.media_type,
                content=content.content,
                observed_at=observed.modified_at,
                # Deliberately not the request clock. `Provenance` refuses a
                # processing time earlier than the observation, and the
                # observation is the object's own modification time, which a
                # fixed or skewed request clock can precede.
                is_truncated=content.is_truncated,
            )
            if outcome.status is ExtractionStatus.UNSUPPORTED:
                # Reported, never coerced into empty text. `application/pdf`
                # arrives here while `P00-OD-003` is open.
                raise UnsupportedError(SafeDetail.MEDIA_TYPE_NOT_EXTRACTABLE)
            if outcome.status is ExtractionStatus.QUARANTINED:
                raise QuarantinedError(SafeDetail.PROCESSING_STOPPED)
            payload = {
                "representation": Representation.NORMALIZED_TEXT.value,
                "version_id": content.version_id,
                "media_type": content.media_type,
                "character_count": outcome.character_count,
                "text": outcome.text,
                "is_truncated": outcome.is_truncated,
            }
            trust_level, basis = TrustLevel.SOURCE_BOUND_DERIVED, ("text_extractor",)

        return _Result(
            payload=payload,
            disclosure=self._disclose(
                unit_of_work,
                authorization,
                enrollment,
                trust_level=trust_level,
                trust_basis=basis,
                source_references=(_reference(observed),),
                truncation=Truncation(
                    is_truncated=content.is_truncated,
                    reason="max_fetch_bytes_reached" if content.is_truncated else None,
                ),
                extra_limitations=(
                    (Limitation.CONTENT_TRUNCATED_AT_FETCH_LIMIT,) if content.is_truncated else ()
                ),
            ),
        )

    def _sources_status(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetSourceStatus
    ) -> _Result:
        """What one subject is doing, for exactly one subject.

        Every branch resolves to an enrollment, because coverage is reported for
        a stated enrollment and never inferred globally (`docs/specs` section
        12), and because `complete_for_scope` is meaningless without the bounded
        scope it is complete for.
        """
        if command.source_id is not None:
            enrollment = self._one_enrollment(authorization, command.source_id, None)
            with _translated():
                source = unit_of_work.sources.source(command.source_id)
            if source is None:
                raise NotFoundError(SafeDetail.SOURCE_ID)
            subject, state = "source", SourceStatusState.CONFIGURED
        elif command.enrollment_id is not None:
            enrollment = self._required_enrollment(authorization, command.enrollment_id)
            counts = self._coverage(unit_of_work, enrollment, authorization.at)
            subject, state = "enrollment", _state_of_coverage(counts.state())
        elif command.operation_id is not None:
            with _translated():
                operation = unit_of_work.operations.operation(command.operation_id)
            if operation is None:
                raise NotFoundError(SafeDetail.OPERATION_ID)
            enrollment = self._required_enrollment(authorization, operation.enrollment_id)
            subject, state = "operation", operation.state
        else:
            enrollment, state = self._object_status(unit_of_work, authorization, command)
            subject = "object"

        return _Result(
            payload={"subject": subject, "state": state.value},
            disclosure=self._disclose(
                unit_of_work,
                authorization,
                enrollment,
                trust_level=TrustLevel.SOURCE_ORIGINAL,
                trust_basis=("application_state",),
            ),
        )

    def _sources_enroll(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: EnrollSource
    ) -> _Result:
        """Persist one bounded grant and queue the work it authorizes.

        The enrollment, the queued operation, and the decision's audit event
        commit together or not at all: they are one transaction, and a partial
        commit would create work with no authority or no evidence behind it
        (`module-boundaries.md` section 10).

        A retry — the same idempotency key carrying the same normalized request
        — queues nothing. `enqueue_job` is deliberately not idempotent, because
        two calls are two operations to observe separately, so the enrollment's
        own key is what makes "queue this once" true. The response says so with
        a null operation rather than inventing an identifier for work that was
        never queued.
        """
        with _translated():
            source = unit_of_work.sources.source(command.source_id)
        if source is None:
            raise NotFoundError(SafeDetail.SOURCE_ID)
        if command.depth > self._limits.max_enrollment_depth:
            raise InvalidRequestError(SafeDetail.DEPTH, SafeDetail.MAX_ENROLLMENT_DEPTH)

        request = self._enrollment_request(authorization, command)
        acceptance: Acceptance | None = None
        conflict: ApplicationError | None = None
        with _translated():
            try:
                acceptance = unit_of_work.enrollments.accept(request)
            except EnrollmentConflictError:
                # The key is bound to a materially different normalized request.
                # Which field differs is deliberately not reported: that would
                # describe the stored request to whoever guessed the key. The
                # raise is outside the handler for the usual reason.
                conflict = ConflictError(SafeDetail.IDEMPOTENCY_KEY)
        if conflict is not None:
            raise conflict
        if acceptance is None:
            raise InternalError()

        enrollment = acceptance.enrollment
        operation_id: str | None = None
        if acceptance.created:
            with _translated():
                operation_id = unit_of_work.operations.enqueue(enrollment.enrollment_id)

        counts = self._coverage(
            unit_of_work, enrollment, authorization.at, queued=1 if acceptance.created else 0
        )
        with _translated():
            limitations = unit_of_work.knowledge.limitations(enrollment.enrollment_id)
        return _Result(
            payload={
                "enrollment_id": enrollment.enrollment_id,
                "operation_id": operation_id,
                "created": acceptance.created,
                "selector": enrollment.scope.selector_kind,
                "depth": enrollment.scope.depth,
                "media_types": list(enrollment.media_types),
                "policy_version": enrollment.policy_version,
                "accepted_at": format_rfc3339(enrollment.accepted_at),
            },
            disclosure=disclosure_for(
                enrollment=enrollment,
                counts=counts,
                limitations=limitations,
                classification=source.classification,
                observed_at=authorization.at,
                trust_level=TrustLevel.SOURCE_ORIGINAL,
                trust_basis=("accepted_enrollment",),
            ),
        )

    def _knowledge_search(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: SearchKnowledge
    ) -> _Result:
        """Search one enrollment's extracted text.

        The disclosure is the one the search itself produced. It is built from
        the coverage of the rows the same statement snapshot saw, so rebuilding
        it here from a second read would replace a consistent answer with a
        plausible one.

        Nothing of the query reaches the error either way. `SearchQuery` refuses
        to render itself, every message these constructors raise names the rule
        rather than the value, and the public error carries a code and a field
        name and nothing else.
        """
        self._required_enrollment(authorization, command.enrollment_id)
        request = self._search_request(command)
        outcome: SearchOutcome | None = None
        failure: ApplicationError | None = None
        with _translated():
            try:
                outcome = unit_of_work.knowledge.search(request, now=authorization.at)
            except SearchCursorError:
                failure = ConflictError(SafeDetail.CURSOR)
            except EmptySearchQueryError:
                # The query normalized to terms but produced no lexemes — a
                # different answer from "the search found nothing", which is what
                # section 9.7 forbids collapsing it into.
                failure = InvalidRequestError(SafeDetail.QUERY)
        if failure is not None:
            raise failure
        if outcome is None:
            raise InternalError()

        return _Result(
            payload={
                "matches": [
                    {
                        "knowledge_id": match.knowledge_id,
                        "label": match.label,
                        "snippet": match.snippet,
                        "rank": match.rank.value,
                        "source_id": match.source_id,
                        "source_object_id": match.source_object_id,
                        "version_id": match.version_id,
                    }
                    for match in outcome.matches
                ]
            },
            disclosure=outcome.disclosure,
        )

    def _knowledge_read(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ReadKnowledge
    ) -> _Result:
        """One stored record, its provenance, and honest truncation.

        The record is looked up inside the stated grant, so one written under a
        different enrollment is `not_found` — the same answer as one that does
        not exist, which is what section 10 requires.
        """
        enrollment = self._required_enrollment(authorization, command.enrollment_id)
        with _translated():
            record = unit_of_work.knowledge.read(
                command.knowledge_id, enrollment_id=command.enrollment_id
            )
        if record is None:
            raise NotFoundError(SafeDetail.KNOWLEDGE_ID)

        text: str | None = None
        cut = False
        if not command.metadata_only:
            text = record.text
            if command.max_characters is not None and len(text) > command.max_characters:
                text, cut = text[: command.max_characters], True

        provenance = record.provenance
        payload: dict[str, Any] = {
            "knowledge_id": record.knowledge_id,
            "label": label_for_media_type(record.media_type),
            "media_type": record.media_type,
            "character_count": len(record.text),
            "metadata_only": command.metadata_only,
            "is_truncated": record.is_truncated or cut,
            "provenance": {
                "source_id": provenance.source_id,
                "source_object_id": provenance.source_object_id,
                "version_id": provenance.version_id,
                "extractor": provenance.extractor,
                "extractor_version": provenance.extractor_version,
                "trust_level": provenance.trust_level.value,
                "observed_at": format_rfc3339(provenance.observed_at),
                "processed_at": format_rfc3339(provenance.processed_at),
            },
        }
        if text is not None:
            payload["text"] = text

        limitations: tuple[Limitation, ...] = (Limitation.LABEL_IS_MEDIA_TYPE_ONLY,)
        if cut:
            limitations = (*limitations, Limitation.TEXT_TRUNCATED_TO_REQUESTED_MAXIMUM)
        return _Result(
            payload=payload,
            disclosure=self._disclose(
                unit_of_work,
                authorization,
                enrollment,
                trust_level=provenance.trust_level,
                trust_basis=(provenance.extractor,),
                source_references=(
                    SourceReference(
                        source_id=provenance.source_id,
                        source_object_id=provenance.source_object_id,
                        version_id=provenance.version_id,
                    ),
                ),
                truncation=Truncation(
                    is_truncated=cut, reason="max_characters_reached" if cut else None
                ),
                extra_limitations=limitations,
            ),
        )

    # ---- shared helpers ----------------------------------------------------

    def _page_size(self, requested: int | None) -> int:
        """The page size to use: the caller's, bounded by the published maximum."""
        if requested is None:
            return self._limits.default_page_size
        return min(requested, self._limits.max_page_size)

    def _provider(self, source_id: str) -> SourceProvider:
        """The adapter serving `source_id`, or a truthful unavailability.

        A source that is configured but has no adapter wired is `unavailable`
        rather than `not_found`: the source exists, and saying otherwise would
        report a wiring gap as a fact about the corpus.
        """
        provider = self._providers.for_source(source_id)
        if provider is None:
            raise UnavailableError(SafeDetail.SOURCE_ID)
        return provider

    def _one_enrollment(
        self, authorization: Authorization, source_id: str, named: str | None
    ) -> Enrollment:
        """The single grant a source-scoped request runs under.

        A principal may hold more than one enrollment over a source, and the two
        may have different scopes and different coverage. Choosing between them
        would be the guess section 10 forbids, so a request that does not name
        one is `ambiguous_request` and a request that does is answered under
        exactly that grant.
        """
        covering = authorization.covering(source_id)
        if named is not None:
            match = next((e for e in covering if e.enrollment_id == named), None)
            if match is None:
                raise NotFoundError(SafeDetail.ENROLLMENT_ID)
            return match
        if len(covering) > 1:
            raise AmbiguousRequestError(
                SafeDetail.ENROLLMENT_ID, SafeDetail.MULTIPLE_ENROLLMENTS_COVER_THE_SCOPE
            )
        if not covering:
            # The narrowing an index requires. Policy already refused a source
            # outside the principal's enrollments, so nothing reaches this with
            # an empty set; it denies rather than raising an untyped IndexError.
            raise DeniedError()
        return covering[0]

    def _required_enrollment(self, authorization: Authorization, enrollment_id: str) -> Enrollment:
        """The principal's enrollment with this identifier.

        The narrowing an enrollment-scoped handler requires. The shared
        authorization path derives such a request's scope from the principal's
        own enrollments, so one it does not hold was already denied.
        """
        enrollment = authorization.enrollment(enrollment_id)
        if enrollment is None:
            raise NotFoundError(SafeDetail.ENROLLMENT_ID)
        return enrollment

    def _object_status(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: GetSourceStatus
    ) -> tuple[Enrollment, SourceStatusState]:
        """The grant and the state behind a status request naming one object."""
        object_id = command.source_object_id
        if object_id is None:
            # Unreachable: `GetSourceStatus` refuses to exist without exactly one
            # subject and the caller has excluded the other three.
            raise InternalError()
        with _translated():
            source_id = unit_of_work.sources.source_of_object(object_id)
        if source_id is None:
            raise NotFoundError(SafeDetail.SOURCE_OBJECT_ID)
        enrollment = self._one_enrollment(authorization, source_id, None)
        with _translated():
            outcome = unit_of_work.knowledge.outcome_for_object(
                enrollment_id=enrollment.enrollment_id, source_object_id=object_id
            )
        return enrollment, _state_of_outcome(outcome)

    def _coverage(
        self,
        unit_of_work: UnitOfWork,
        enrollment: Enrollment,
        observed_at: datetime,
        *,
        queued: int = 0,
    ) -> CoverageCounts:
        """Coverage of one enrollment, with the denominator it can honestly state."""
        with _translated():
            return unit_of_work.knowledge.coverage(
                enrollment.enrollment_id,
                observed_at=observed_at,
                eligible=eligible_total(enrollment),
                queued=queued,
            )

    def _disclose(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        enrollment: Enrollment,
        *,
        trust_level: TrustLevel,
        trust_basis: tuple[str, ...],
        source_references: tuple[SourceReference, ...] = (),
        truncation: Truncation = _NO_TRUNCATION,
        extra_limitations: tuple[Limitation, ...] = (),
    ) -> Disclosure:
        """The envelope for a result produced under one grant.

        Every part of it is read: the counts from the rows extraction wrote, the
        limitations from what the last enumeration pass recorded, and the
        classification from the configured source. Nothing here is a constant a
        result could outlive.
        """
        counts = self._coverage(unit_of_work, enrollment, authorization.at)
        with _translated():
            limitations = unit_of_work.knowledge.limitations(enrollment.enrollment_id)
            source = unit_of_work.sources.source(enrollment.source_id)
        if source is None:
            # An enrollment's source is a foreign key; a missing row here is a
            # broken store rather than a request problem.
            raise InternalError()
        return disclosure_for(
            enrollment=enrollment,
            counts=counts,
            limitations=limitations,
            classification=source.classification,
            observed_at=authorization.at,
            trust_level=trust_level,
            trust_basis=trust_basis,
            source_references=source_references,
            truncation=truncation,
            extra_limitations=extra_limitations,
        )

    def _search_request(self, command: SearchKnowledge) -> SearchRequest:
        """Build the domain request, bounded by the published page size."""
        query: SearchQuery | None = None
        request: SearchRequest | None = None
        failure: ApplicationError | None = None
        try:
            query = SearchQuery(command.query)
        except SearchQueryError:
            failure = InvalidRequestError(SafeDetail.QUERY)
        if query is not None:
            try:
                request = SearchRequest(
                    enrollment_id=command.enrollment_id,
                    query=query,
                    page_size=self._page_size(command.page_size),
                    cursor=command.cursor,
                    snippet_words=(
                        DEFAULT_SNIPPET_WORDS
                        if command.snippet_words is None
                        else command.snippet_words
                    ),
                )
            except SearchQueryError:
                failure = InvalidRequestError(SafeDetail.SNIPPET_WORDS)
            except SearchCursorError:
                failure = ConflictError(SafeDetail.CURSOR)
        if failure is not None:
            raise failure
        if request is None:
            raise InternalError()
        return request

    def _enrollment_request(
        self, authorization: Authorization, command: EnrollSource
    ) -> EnrollmentRequest:
        """Build the domain request, reporting which field a refusal was about.

        The bounds are the domain's, enforced on construction, so there is no
        path here that holds an unbounded enrollment and checks it later.
        """
        request: EnrollmentRequest | None = None
        failure: ApplicationError | None = None
        try:
            request = EnrollmentRequest(
                source_id=command.source_id,
                principal_id=authorization.principal.principal_id,
                purpose=authorization.purpose,
                scope=EnrollmentScope(
                    object_ids=command.object_ids,
                    root_object_id=command.root_object_id,
                    depth=command.depth,
                ),
                media_types=command.media_types,
                policy_version=authorization.decision.policy_version,
                idempotency_key=command.idempotency_key,
                max_items=MAX_ENROLLMENT_ITEMS if command.max_items is None else command.max_items,
                max_bytes=MAX_ENROLLMENT_BYTES if command.max_bytes is None else command.max_bytes,
            )
        except EnrollmentBoundsError:
            # The domain message names the field and the limit and never the
            # value, and none of it crosses into the public error either way.
            failure = InvalidRequestError(SafeDetail.SELECTOR)
        if failure is not None:
            raise failure
        if request is None:
            raise InternalError()
        return request


#: The wiring. `capabilities.get` reports availability from these keys, so a
#: capability is available exactly when something here can execute it, and there
#: is no constant to edit at the moment one starts working.
_HANDLERS: Final[Mapping[Capability, Callable[..., _Result]]] = MappingProxyType(
    {
        Capability.CAPABILITIES_GET: ApplicationService._capabilities_get,
        Capability.SOURCES_LIST: ApplicationService._sources_list,
        Capability.SOURCES_METADATA: ApplicationService._sources_metadata,
        Capability.SOURCES_FETCH: ApplicationService._sources_fetch,
        Capability.SOURCES_STATUS: ApplicationService._sources_status,
        Capability.SOURCES_ENROLL: ApplicationService._sources_enroll,
        Capability.KNOWLEDGE_SEARCH: ApplicationService._knowledge_search,
        Capability.KNOWLEDGE_READ: ApplicationService._knowledge_read,
    }
)
