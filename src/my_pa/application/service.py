"""Every capability, behind one authorization and one transaction.

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

**Which outcomes leave a durable trace.** An incomplete disclosure of an audit
gap is itself a gap, and this list has been wrong twice — once by omitting the
capability mismatch, and once by omitting case 5 while claiming to be complete.
So it is derived rather than surveyed, and the derivation itself changed when
WP-4B1 gave the audit its own transaction (`D-34`).

`AuditSink.record` has exactly two call sites in this layer,
`authorization.authorize` and the mismatch branch of `_run`. Both are still
reached from inside the transaction `_run` opens, and neither is written by it:
the durable sink commits the event on its own connection before returning, so
whether an audit survives no longer depends on how the work transaction ended.
Every outcome is therefore some combination of two facts — was `record`
reached, and did `record` itself succeed — and the list below is closed because
those two facts have no third value, not because seven cases is where the
searching stopped.

1. *Policy denied the request.* Recorded and durable. The reason is in the record
   and never in the answer.
2. *The declared capability and the payload's capability disagree.* A
   security-relevant refusal — it is the guard against a request authorized as
   one capability and executed as another — so it is recorded as `failed` and
   durable. `failed` rather than `denied` because no policy decision was reached:
   there is nothing to name a `DenialReason` from, and inventing one would
   misreport why the request stopped.
3. *Allowed, and the handler succeeded.* Recorded as allowed and durable; the
   work commits after it.
4. *Allowed, and the handler then failed.* Recorded as allowed and **still
   durable**, because the event was committed before the handler ran and the
   rollback that discards the half-written work cannot reach it. This is the
   asymmetry WP-4B1 closed. What the record claims is that the request was
   authorized, which is true whether or not the work landed; it does not claim
   the work committed, and no second event is written to say that it did not —
   the job plane and `sources.status` are where that is recorded.
5. *A failure before any decision was reached.* A port failure in `authorize`'s
   own reads — `for_principal`, or the operation and object lookups that resolve
   a status request's scope — raises before `record` is called, and the unit of
   work may also fail to open at all. Nothing is recorded, and nothing is
   missing: no decision existed to record.
6. *The audit itself could not be persisted.* Nothing is recorded, and the
   request **fails closed**: `record` raises, the exception leaves the `with`
   block so the work rolls back, and `invoke` answers with an error. This is the
   case that separates the new design from the old one — a decision was reached
   and its record was lost, and the only correct response is to refuse the
   request rather than to complete it unrecorded
   (`module-boundaries.md` section 5.6). It is `_run`'s only path where a request
   that policy allowed still fails without the handler being at fault.
7. *A command that could not be constructed at all.* Not recorded, and cannot be:
   a malformed command is refused by its own `__post_init__` before `invoke` is
   called, so this layer never sees the attempt. Whatever calls it is the only
   thing that could record one.

**No code in this class changed to achieve that**, and the reason is worth
stating rather than leaving as an absence. Durability is a property of the sink's
transaction, which this layer is deliberately unable to see; fail-closed is a
property of not catching what `record` raises, which this layer already did. What
changed is which implementation a composition root supplies, and the enumeration
above, which was describing the old one.

**Provider reads happen inside that transaction.** `module-boundaries.md`
section 10 says long source fetches are not held inside database transactions,
and the reading here is bounded by `max_fetch_bytes` against a local filesystem
adapter — the rule's target is the worker's extraction path, which this package
does not own. What is gained is that the coverage a disclosure states and the
bytes the same response returns come from one consistent read. Should a provider
ever be remote, this is the sentence that has to change first.

`_enumerate` is a *new caller* of that decision and not a reopening of it, and it
is said here rather than left to be discovered in review. It reads no bytes —
`iterdir` and `stat`, bounded by the enrollment's own `max_items` — so it is
strictly cheaper than `sources.fetch`, which already runs inside the transaction
under the same decision. It has to be inside: the identifiers it records are
issued by a provider bound to this connection, so an enrollment that rolls back
must issue none, and the enumerated set has to commit with the acceptance it
measures or the two can disagree.

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
    Representation,
    RevealSubject,
    ReviseCapture,
    SearchCaptures,
    SearchKnowledge,
)
from my_pa.application.disclosure import (
    Limitation,
    disclosure_for,
    unavailable_disclosure,
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
    CaptureAdmission,
    CaptureAdmissionRequest,
    CaptureSearchOutcome,
    CaptureSearchRequest,
    EvidenceUnavailableError,
    PortError,
    ReviewDecisionRequest,
    SearchOutcome,
    UnitOfWork,
    UnknownScopeError,
)
from my_pa.contracts.v1.capabilities import EffectiveLimits
from my_pa.contracts.v1.capture import CaptureListEntry, CaptureReceiptView, CaptureVersionView
from my_pa.contracts.v1.disclosure import Disclosure, SourceReference, Truncation
from my_pa.contracts.v1.envelope import RequestMetadata, ResponseEnvelope
from my_pa.contracts.v1.reveal import RevealView
from my_pa.contracts.v1.status import SourceStatusState
from my_pa.domain.audit.events import AuditEvent, AuditOutcome
from my_pa.domain.capture.errors import (
    CaptureBoundsError,
    CaptureConflictError,
    CaptureError,
    EmptyCaptureError,
)
from my_pa.domain.capture.reveal import EvidenceState
from my_pa.domain.capture.review import (
    ReviewConflictError,
    ReviewNotFoundError,
    ReviewUnsupportedError,
)
from my_pa.domain.capture.submission import CaptureKind, CaptureTransport
from my_pa.domain.capture.version import CaptureContent, CaptureVersion, ProcessingPolicy
from my_pa.domain.common.classification import Classification
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


#: What a capture answer's trust rests on. Not `source_provider` and not
#: `text_extractor`: nothing read a source and nothing derived anything.
#: `ADR-003` makes a user-authored record an authority in its own right, so the
#: level is `source_original` and the basis names the person who wrote it.
_CAPTURE_TRUST_BASIS: Final = ("user_authored",)

#: What a reveal's trust rests on. The stored rows and nothing else: every value
#: in the answer was read from `capture_spans`, `capture_proposals`,
#: `capture_review_decisions`, `capture_assertions` and
#: `capture_promotion_receipts`, and none of it was computed here. Naming
#: `stored_evidence_rows` rather than reusing `_CAPTURE_TRUST_BASIS` is the
#: difference between "the person wrote this" and "these are the rows that
#: record what was derived from what the person wrote".
_REVEAL_TRUST_BASIS: Final = ("stored_evidence_rows", "reviewed_promotion")


def _capture_content(text: str) -> CaptureContent:
    """Build the domain value, reporting which field a refusal was about.

    The two refusals are different answers and are reported as such: an empty
    capture names the field, and one past the bound names the field and the
    bound. Neither message carries the text — the domain's own exceptions do not
    hold it, and the public error's details are closed tokens.
    """
    failure: ApplicationError | None = None
    try:
        return CaptureContent(text)
    except EmptyCaptureError:
        failure = InvalidRequestError(SafeDetail.TEXT)
    except CaptureBoundsError:
        failure = InvalidRequestError(SafeDetail.TEXT, SafeDetail.MAX_CAPTURE_CHARACTERS)
    except CaptureError:
        failure = InvalidRequestError(SafeDetail.TEXT)
    # Raised outside the handler so the original — whose traceback frames render
    # the value that was refused — is not left in `__context__`.
    raise failure


def _capture_version_view(version: CaptureVersion, *, is_current: bool) -> CaptureVersionView:
    """One stored version as the contract publishes it.

    `is_current` is passed in rather than read off the version, because there is
    no column that says so: the current version is the greatest version number
    the capture holds, and the use case is what has read both.
    """
    return CaptureVersionView(
        capture_id=version.capture_id,
        version_id=version.version_id,
        version_number=version.version_number,
        supersedes_version_id=version.supersedes_version_id,
        is_current=is_current,
        owner_principal_id=version.owner_principal_id,
        classification=version.classification,
        processing_policy=version.processing_policy.value,
        content_sha256=version.content.digest,
        character_count=version.content.character_count,
        text=version.content.text,
        client_created_at=version.client_created_at,
        server_received_at=version.server_received_at,
        occurred_at=version.occurred_at,
        accepted_at=version.accepted_at,
        recorded_at=version.recorded_at,
    )


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
        limits: EffectiveLimits,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._limits = _effective_limits(limits)
        self._clock = clock

    def invoke(
        self,
        metadata: RequestMetadata,
        command: Command,
        *,
        principal: Principal,
        transport: CaptureTransport = CaptureTransport.LOCAL,
    ) -> ResponseEnvelope:
        """Execute one request and return the envelope describing what happened.

        `principal` is authenticated context supplied by the composition root.
        `metadata.principal_id` is correlation input and is deliberately not
        consulted: a caller-supplied identity is never trusted alone
        (`docs/specs` section 8.2).

        `transport` is the second thing the composition root supplies and the
        caller cannot (WP-10): how the request reached this process. It defaults
        to `LOCAL`, which is what the loopback gateway, MCP over stdio and the
        CLI all are, and the authenticated remote ingress passes
        `REMOTE_CLIENT`. It is provenance the capture plane stores and it
        authorizes nothing — the whole point of routing a remote submission
        through this method is that it takes the *same* path as a local one, and
        a transport that could change what a request is permitted to do would be
        a second capture path wearing the first one's name.

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
                metadata,
                command,
                principal=principal,
                correlation_id=correlation_id,
                at=started_at,
                transport=transport,
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
        transport: CaptureTransport = CaptureTransport.LOCAL,
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
                    request_id=metadata.request_id,
                    at=at,
                    transport=transport,
                )
                if authorization.allowed:
                    return _HANDLERS[command.capability](self, unit_of_work, authorization, command)
        # Reached only after the transaction committed, which is what preserves
        # the audit event recording the refusal.
        if mismatch:
            raise InvalidRequestError(SafeDetail.SUBJECT)
        raise DeniedError()

    # ---- the source and knowledge planes -----------------------------------

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
        provider = self._provider(unit_of_work, command.source_id)
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
        provider = self._provider(unit_of_work, command.source_id)
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
        provider = self._provider(unit_of_work, command.source_id)
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
                operation = unit_of_work.operations.operation(
                    command.operation_id, principal_id=authorization.principal.principal_id
                )
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
        """Enumerate one bounded grant, persist it, and queue the work it authorizes.

        The enrollment, its enumerated object set, the queued operation, and the
        decision's audit event commit together or not at all: they are one
        transaction, and a partial commit would create work with no authority, no
        measured scope, or no evidence behind it (`module-boundaries.md` section
        10).

        **The enumeration happens here, before the job is queued, and that is the
        decision the rest of the package rests on.** The alternative — the worker
        walks the root — leaves a window between this call returning and the job
        running in which an accepted grant has no measured denominator, so every
        disclosure in that window has to say so, which is the token and the clamp
        this package just deleted plus a *new* token distinguishing "not measured
        yet" from "not measurable". Measuring at acceptance means there is no such
        instant: `record_scope` refuses an empty set and its refusal rolls back
        `accept_enrollment` with it, so `enrollment_objects` is non-empty for
        every stored enrollment by construction rather than by convention.

        A retry — the same idempotency key carrying the same normalized request —
        enumerates nothing and queues nothing. Both are gated on
        `acceptance.created`, so a retry makes no provider call at all; the row
        count would be identical either way because `record_scope` inserts under
        a primary key, which is why the assertion that proves this has to be on a
        recording provider's call log. `enqueue_job` is deliberately not
        idempotent, because two calls are two operations to observe separately,
        so the enrollment's own key is what makes "queue this once" true. The
        response says so with a null operation rather than inventing an
        identifier for work that was never queued.
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
            # Enumeration happens inside this branch and nowhere above it, so a
            # retry resolves no provider and makes no provider call.
            enumerated = self._enumerate(unit_of_work, enrollment)
            if not enumerated:
                # Refused here rather than left to `record_scope`, which refuses
                # the empty set too. Both roll the transaction back; only this one
                # can say what the caller did wrong. A root that holds no
                # extractable object is a scope the operator named and not a fault
                # of this system, and reporting it as `internal_error` would be
                # the misclassification `docs/specs` section 10 forbids.
                raise InvalidRequestError(SafeDetail.SELECTOR)
            with _translated():
                unit_of_work.enrollments.record_scope(enrollment.enrollment_id, enumerated)
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

    # ---- the capture plane -------------------------------------------------

    def _capture_create(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: CreateCapture
    ) -> _Result:
        """Store one user-authored note as the first version of a new capture."""
        return self._admit(
            unit_of_work,
            authorization,
            capture_id=None,
            text=command.text,
            idempotency_key=command.idempotency_key,
            client_created_at=command.client_created_at,
            occurred_at=command.occurred_at,
            capture_kind=command.capture_kind,
            context_source_object_id=command.context_source_object_id,
            context_source_version_id=command.context_source_version_id,
        )

    def _capture_revise(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ReviseCapture
    ) -> _Result:
        """Append a successor version to an existing capture the caller owns.

        `D-72`'s owner-equality refusal is superseded here
        (`PKL-MYPA-D-WP03-001`). Its premise — that identity was a property of
        the serving process, so an owner check would make a capture unrevisable
        across restarts — dissolved when `local_principal` began deriving the
        local operator's identifier from a durable UUID namespace
        (`my_pa.domain.identity.binding`): the same operator now presents the
        same `principal_id` in every process, so `QC-AC-013` stays provable
        across two of them. The check itself lives where the data does — the
        head lookup in the capture store is principal-scoped, so a foreign
        capture is indistinguishable from an absent one and surfaces as
        `not_found` rather than as a `forbidden` that would confirm the
        identifier exists.
        """
        return self._admit(
            unit_of_work,
            authorization,
            capture_id=command.capture_id,
            text=command.text,
            idempotency_key=command.idempotency_key,
            client_created_at=command.client_created_at,
            occurred_at=command.occurred_at,
            capture_kind=CaptureKind.QUICK_NOTE,
            context_source_object_id=None,
            context_source_version_id=None,
        )

    def _capture_read(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ReadCapture
    ) -> _Result:
        """One stored version of one capture, exactly as it was written.

        A named version is returned whether or not it is the current one, which
        is `QC-AC-010`'s "independently retrievable": an edit appends, and the
        predecessor stays readable at its own identifier.
        """
        principal_id = authorization.principal.principal_id
        with _translated():
            version = unit_of_work.captures.version(
                command.capture_id, version_id=command.version_id, principal_id=principal_id
            )
            current = unit_of_work.captures.version(command.capture_id, principal_id=principal_id)
        if version is None or current is None:
            raise NotFoundError(SafeDetail.CAPTURE_ID)
        view = _capture_version_view(version, is_current=version.version_id == current.version_id)
        return _Result(
            payload=view.to_canonical_dict(),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_CAPTURE_TRUST_BASIS),
        )

    def _capture_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListCaptures
    ) -> _Result:
        """One page of stored captures, newest first, carrying no content.

        Bounded by the same published page size every other listing here uses
        (`D-24`), so `capabilities.get` states the limit a caller will actually
        get. One row past the page is read so that truncation is a fact rather
        than a guess, exactly as `sources.list` does it.
        """
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.captures.captures(
                limit=page_size + 1, principal_id=authorization.principal.principal_id
            )
        truncated = len(found) > page_size
        page = found[:page_size]
        return _Result(
            payload={
                "captures": [
                    CaptureListEntry(
                        capture_id=summary.capture_id,
                        owner_principal_id=summary.owner_principal_id,
                        created_at=summary.created_at,
                        version_count=summary.version_count,
                        latest_version_id=summary.latest_version_id,
                        latest_version_number=summary.latest_version_number,
                        latest_recorded_at=summary.latest_recorded_at,
                    ).to_canonical_dict()
                    for summary in page
                ]
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_CAPTURE_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=truncated, reason="page_size_reached" if truncated else None
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _capture_search(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: SearchCaptures
    ) -> _Result:
        """Exact lexical search over stored capture text.

        **No enrollment is resolved, and that is the whole difference from
        `_knowledge_search`.** `capture.search` is in `_SCOPELESS` because a
        capture belongs to no configured source and no enrollment; asking
        `authorization.covering(...)` here would be asking for a grant that
        cannot exist, and inventing one would be the fabricated authority
        `_enumerate`'s own docstring refuses.

        **Authorization is capability plus purpose; scope is the caller's own
        captures.** `D-72`'s "no owner condition" is superseded
        (`PKL-MYPA-D-WP03-001`): `capture_text_in_scope` now carries the
        caller's partition as a structural condition, and both counts in the
        totals statement are partitioned the same way, so neither a match nor a
        denominator can leak another principal's existence through this
        endpoint. Capability and purpose still decide *whether* the caller may
        search; the partition decides *what there is* to search.

        **The answer carries no capture text.** `CaptureSearchMatch` has no
        field one could go in — identifiers, a version number, a character
        count, a time — so a search cannot become a second read of content that
        `capture.read` audits under its own capability (`QC-AC-041`). A caller
        therefore cannot see *why* a capture matched, which is a limitation the
        envelope states rather than an omission it hides.

        **Every limitation here is derived from what this search measured.** The
        no-stemming token is the price of the `simple` configuration `D-90`
        chose and is unconditional because the property is; the superseded token
        is emitted only when the two counts the same statement snapshot produced
        actually differ. Neither is built from the query and neither is built
        from any capture's content — which is `QC-AC-042`'s disclosure half:
        captured text cannot suppress a limitation, inflate a count, or alter a
        freshness label, because no path exists from content to any of them.
        """
        page_size = self._page_size(command.page_size)
        request: CaptureSearchRequest | None = None
        failure: ApplicationError | None = None
        try:
            request = CaptureSearchRequest(query=SearchQuery(command.query), limit=page_size)
        except EmptySearchQueryError:
            # The query normalized to terms but yielded no lexemes — a different
            # answer from "the search found nothing", which section 9.7 forbids
            # collapsing it into. Caught before `SearchQueryError` because it is
            # a subclass of it and would otherwise be reported as a malformed
            # query rather than an empty one.
            failure = InvalidRequestError(SafeDetail.QUERY)
        except SearchQueryError:
            failure = InvalidRequestError(SafeDetail.QUERY)
        if failure is not None:
            raise failure
        if request is None:  # pragma: no cover - the branches above are exhaustive
            raise InternalError()

        outcome: CaptureSearchOutcome | None = None
        with _translated():
            outcome = unit_of_work.captures.search(
                request, principal_id=authorization.principal.principal_id
            )
        if outcome is None:  # pragma: no cover - `_translated` raises or the call returns
            raise InternalError()

        limitations: tuple[Limitation, ...] = (Limitation.CAPTURE_SEARCH_DOES_NOT_STEM,)
        if outcome.searchable_versions != outcome.stored_versions:
            limitations = (*limitations, Limitation.CAPTURE_SEARCH_EXCLUDES_SUPERSEDED)
        if outcome.truncated:
            limitations = (*limitations, Limitation.LISTING_HAS_NO_CONTINUATION)
        return _Result(
            payload={
                "matches": [
                    {
                        "capture_id": match.capture_id,
                        "version_id": match.version_id,
                        "version_number": match.version_number,
                        "character_count": match.character_count,
                        "recorded_at": format_rfc3339(match.recorded_at),
                    }
                    for match in outcome.matches
                ],
                "searchable_versions": outcome.searchable_versions,
                "stored_versions": outcome.stored_versions,
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_CAPTURE_TRUST_BASIS,
                truncation=Truncation(
                    is_truncated=outcome.truncated,
                    reason="page_size_reached" if outcome.truncated else None,
                ),
                extra_limitations=limitations,
            ),
        )

    def _knowledge_reveal(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: RevealSubject
    ) -> _Result:
        """The evidence behind one subject: spans, versions, and the derivation trace.

        **Three answers, and the whole point of the capability is that a caller
        can tell them apart.**

        * The subject is not this Principal's, or is not there at all -> a
          `not_found` error, the same one for both. `CaptureRepository.reveal`
          answers `None` for the two cases because the identifier is compared
          inside a partitioned statement, so a foreign subject is not found
          rather than found-and-refused, and this endpoint cannot be used to
          discover that somebody else's record exists.
        * The scope could not be searched — a subject kind this evidence model
          does not cover, or a version whose derivation has not completed -> a
          **success** whose `state` is `unavailable` and whose envelope carries
          `CoverageState.UNAVAILABLE`, `partial_result`, the
          `EVIDENCE_SCOPE_WAS_NOT_SEARCHED` limitation, and the gap in
          `unavailable_evidence`. Not an error, because nothing failed and a
          retry may well succeed; and never an empty result, because
          `INV-PKL-007` forbids reporting unavailable evidence as empty.
        * Otherwise the rows, with `proposed` and `accepted` in two separate
          arrays.

        **No enrollment is resolved**, for the reason `_capture_search` states:
        the rows belong to no configured source and no enrollment, which is why
        `knowledge.reveal` is in `domain.policy.decision._SCOPELESS`.

        **The answer carries no capture text and no derived value**, and neither
        `RevealSpanView` nor `RevealProposalView` has a field one could go in.
        The offsets and the digest are enough for a holder of the version to
        confirm a citation and are nothing to anyone else, which is what lets a
        Reveal be shown beside an item without becoming a second read of the
        content `capture.read` audits under its own capability.
        """
        with _translated():
            reveal = unit_of_work.captures.reveal(
                command.subject_id, principal_id=authorization.principal.principal_id
            )
        if reveal is None:
            raise NotFoundError(SafeDetail.SUBJECT)
        view = RevealView.of(reveal)
        if reveal.state is EvidenceState.UNAVAILABLE:
            assert reveal.gap is not None  # noqa: S101 - `Reveal` refuses the other shape
            return _Result(
                payload=view.to_canonical_dict(),
                disclosure=unavailable_disclosure(
                    authorization.at,
                    unavailable_evidence=(reveal.gap.value,),
                    trust_basis=_REVEAL_TRUST_BASIS,
                    extra_limitations=(Limitation.EVIDENCE_SPANS_CARRY_NO_QUOTED_TEXT,),
                ),
            )
        return _Result(
            payload=view.to_canonical_dict(),
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=_REVEAL_TRUST_BASIS,
                extra_limitations=(Limitation.EVIDENCE_SPANS_CARRY_NO_QUOTED_TEXT,),
            ),
        )

    def _review_list(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: ListReviewCases
    ) -> _Result:
        """List review cases without capture or normalized-value content."""
        page_size = self._page_size(command.page_size)
        with _translated():
            found = unit_of_work.reviews.cases(
                limit=page_size + 1, principal_id=authorization.principal.principal_id
            )
        truncated = len(found) > page_size
        return _Result(
            payload={
                "review_cases": [
                    {
                        "review_case_id": case.review_case_id,
                        "proposal_id": case.proposal_id,
                        "capture_id": case.capture_id,
                        "version_id": case.version_id,
                        "proposal_type": case.proposal_type.value,
                        "proposal_state": case.proposal_state.value,
                        "risk_class": case.risk_class.value,
                        "opened_at": format_rfc3339(case.opened_at),
                        "review_version": case.review_version,
                        "latest_disposition": (
                            None
                            if case.latest_disposition is None
                            else case.latest_disposition.value
                        ),
                    }
                    for case in found[:page_size]
                ]
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=("review_policy",),
                truncation=Truncation(
                    is_truncated=truncated,
                    reason="page_size_reached" if truncated else None,
                ),
                extra_limitations=((Limitation.LISTING_HAS_NO_CONTINUATION,) if truncated else ()),
            ),
        )

    def _review_decide(
        self, unit_of_work: UnitOfWork, authorization: Authorization, command: DecideReviewCase
    ) -> _Result:
        """Append one disposition and, for acceptance, its assertion and receipt."""
        decision = None
        conflict = False
        missing = False
        unsupported = False
        with _translated():
            try:
                decision = unit_of_work.reviews.decide(
                    ReviewDecisionRequest(
                        review_case_id=command.review_case_id,
                        expected_review_version=command.expected_review_version,
                        disposition=command.disposition,
                        principal_id=authorization.principal.principal_id,
                        correlation_id=authorization.correlation_id,
                        audit_id=authorization.audit_id,
                        policy_version=authorization.decision.policy_version,
                        decided_at=self._clock(),
                        corrected_value=command.corrected_value,
                    )
                )
            except ReviewConflictError:
                conflict = True
            except ReviewNotFoundError:
                missing = True
            except ReviewUnsupportedError:
                unsupported = True
        if conflict:
            raise ConflictError(SafeDetail.EXPECTED_REVIEW_VERSION)
        if unsupported:
            raise UnsupportedError(SafeDetail.DISPOSITION)
        if missing:
            raise NotFoundError(SafeDetail.REVIEW_CASE_ID)
        if decision is None:
            return _Result(
                payload={"review_case_id": command.review_case_id, "result": "invalidated"},
                disclosure=unenrolled_disclosure(
                    authorization.at,
                    trust_basis=("review_policy", "source_span_validation"),
                ),
            )
        return _Result(
            payload={
                "review_case_id": decision.review_case_id,
                "decision_id": decision.decision_id,
                "review_version": decision.sequence,
                "disposition": decision.disposition.value,
                "proposal_state": decision.proposal_state.value,
                "assertion_id": decision.assertion_id,
                "receipt_id": decision.receipt_id,
            },
            disclosure=unenrolled_disclosure(
                authorization.at,
                trust_basis=("review_policy", "reviewed_promotion"),
            ),
        )

    def _admit(
        self,
        unit_of_work: UnitOfWork,
        authorization: Authorization,
        *,
        capture_id: str | None,
        text: str,
        idempotency_key: str,
        client_created_at: datetime | None,
        occurred_at: datetime | None,
        capture_kind: CaptureKind,
        context_source_object_id: str | None,
        context_source_version_id: str | None,
    ) -> _Result:
        """The one write path both `capture.create` and `capture.revise` take.

        **The transaction is the one this method was handed.** `_run` opened it
        before `authorize` ran and the commit is that `with` block's exit, so the
        capture, its version, its receipt, its submission, and its queued
        processing job commit together or not at all without this method
        arranging anything (`QC-AC-034`). The redacted audit event is *not* among
        them: it committed first, on the sink's own connection, and the version
        stores its identifier (`D-34`). A failed audit therefore fails the
        request closed before any of this runs, and a failed work transaction
        leaves an audit event describing an authorization whose work never
        landed, which `D-34` records as the correct direction of the trade.

        **Three clocks, read at three moments.** `authorization.at` is when this
        process received the request, `self._clock()` here is when the admission
        decided, and the store writes `recorded_at` from the server's own clock.
        The two the caller may supply are passed through untouched, including
        when they are absent. Five columns, five origins, no default from one to
        another (`QC-AC-012`).
        """
        content = _capture_content(text)
        request = CaptureAdmissionRequest(
            capture_id=capture_id,
            content=content,
            idempotency_key=idempotency_key,
            request_id=authorization.request_id,
            correlation_id=authorization.correlation_id,
            principal_id=authorization.principal.principal_id,
            audit_id=authorization.audit_id,
            # Fixed rather than requested. `QC-AC-040` requires the default to be
            # private-local with cloud and training false, and a caller-selected
            # classification would be a caller widening its own processing
            # eligibility, which `docs/specs/quick-capture/09_LOGICAL_DATA_MODEL.md`
            # forbids: `:56` names the field and defaults it to `private_local`,
            # and `:73` states that "classification changes cannot silently widen
            # processing eligibility". Two lines, not one sentence.
            classification=Classification.PRIVATE_LOCAL,
            processing_policy=ProcessingPolicy.LOCAL_ONLY,
            server_received_at=authorization.at,
            accepted_at=self._clock(),
            client_created_at=client_created_at,
            occurred_at=occurred_at,
            capture_kind=capture_kind,
            context_source_object_id=context_source_object_id,
            context_source_version_id=context_source_version_id,
            # Provenance, not a decision. It arrived on `invoke`'s own parameter
            # from the composition root and reaches the submission row unchanged;
            # nothing between here and the INSERT reads it, and no branch in this
            # method depends on it. That is what makes a remote submission the
            # same transaction rather than a parallel one.
            transport=authorization.transport,
        )
        admission: CaptureAdmission | None = None
        conflict: ApplicationError | None = None
        with _translated():
            try:
                admission = unit_of_work.captures.admit(
                    request, principal_id=authorization.principal.principal_id
                )
            except CaptureConflictError:
                # The key is bound to materially different content. `conflict`,
                # which is one of the eleven public codes; there is no
                # `idempotency_conflict` and inventing one would be an
                # unauthorised expansion of the v1 error set. Which field differs
                # is deliberately not reported: that would describe the stored
                # request to whoever guessed the key. The raise is outside the
                # handler for the usual reason.
                conflict = ConflictError(SafeDetail.IDEMPOTENCY_KEY)
        if conflict is not None:
            raise conflict
        if admission is None:
            raise InternalError()

        receipt = admission.receipt
        return _Result(
            payload=CaptureReceiptView(
                receipt_id=receipt.receipt_id,
                capture_id=receipt.capture_id,
                version_id=receipt.version_id,
                version_number=receipt.version_number,
                idempotency_key=receipt.idempotency_key,
                content_sha256=receipt.content_sha256,
                issued_at=receipt.issued_at,
                created=admission.created,
            ).to_canonical_dict(),
            disclosure=unenrolled_disclosure(authorization.at, trust_basis=_CAPTURE_TRUST_BASIS),
        )

    # ---- shared helpers ----------------------------------------------------

    def _page_size(self, requested: int | None) -> int:
        """The page size to use: the caller's, bounded by the published maximum."""
        if requested is None:
            return self._limits.default_page_size
        return min(requested, self._limits.max_page_size)

    def _provider(self, unit_of_work: UnitOfWork, source_id: str) -> SourceProvider:
        """The adapter serving `source_id`, or a truthful unavailability.

        A source that is configured but has no adapter wired is `unavailable`
        rather than `not_found`: the source exists, and saying otherwise would
        report a wiring gap as a fact about the corpus.

        Taken from the unit of work rather than from a constructor argument, and
        `contracts.ports.UnitOfWork.providers` gives the reason: the adapter
        resolves opaque identifiers against `knowledge.source_objects`, so it has
        to read the rows this request's transaction sees, and the identifiers it
        issues have to roll back with it.
        """
        provider = unit_of_work.providers.for_source(source_id)
        if provider is None:
            raise UnavailableError(SafeDetail.SOURCE_ID)
        return provider

    def _enumerate(self, unit_of_work: UnitOfWork, enrollment: Enrollment) -> tuple[str, ...]:
        """The objects `enrollment` authorizes, measured once, at acceptance.

        For an enrollment that named its objects this is those objects: the list
        *is* the authorization, and walking anything would answer a question
        nobody asked. **No provider is resolved on that path**, which is a
        decision rather than an ordering accident: requiring an adapter to
        enumerate a set the request already stated would make `sources.enroll`
        fail for a source whose root is momentarily unreachable, over an answer
        that never depended on the root. `record_scope` still refuses an
        identifier `knowledge.source_objects` has no row for, so the named set is
        checked against the store rather than trusted.

        For a root selector it is the walk, and every bound the walk obeys is
        read off the accepted enrollment rather than restated here —
        `scope.depth` and `max_items`, both of which the domain already refused
        to construct outside their ceilings. There the provider *is* required,
        and a source with no adapter is `unavailable` with the whole transaction
        rolled back: an enrollment nobody can enumerate must not exist.

        **Depth is levels of listing, and the level count is `depth + 1`.**
        `domain.source.enrollment` fixes depth zero as "the named root itself and
        its immediate children — never a walk", so the default enrollment is one
        `list_children` call. Depth one adds the children of those children, and
        so on to `MAX_ENROLLMENT_DEPTH`.

        **Containers are descended and not recorded.** The eligible total is a
        count of objects that could hold extractable content, and a directory
        holds none; counting one would make `processed == eligible` unreachable
        for every enrollment that contains a folder. The table's own docstring
        records the same decision from the schema's side.

        Refuses with `InvalidRequestError(MAX_ITEMS)` at `max_items + 1` objects,
        so the walk stops rather than materialising a scope the enrollment never
        authorized. The refusal rolls the accepting transaction back, so the
        enrollment does not exist rather than existing over a truncated scope.

        The provider reads run inside the enroll transaction, under `D-35`, which
        permits it while the provider is local. This is a new caller of that
        decision and not a reopening of it: enumeration reads no bytes — only
        `iterdir` and `stat` — so it is strictly cheaper than `sources.fetch`,
        which already runs inside the transaction under the same decision. This
        module's own docstring, at "Provider reads happen inside that
        transaction", is the sentence that has to change first if a provider ever
        becomes remote.
        """
        scope = enrollment.scope
        if scope.root_object_id is None:
            return scope.object_ids

        provider = self._provider(unit_of_work, enrollment.source_id)
        found: list[str] = []
        frontier: list[str] = [scope.root_object_id]
        for _ in range(scope.depth + 1):
            if not frontier:
                break
            descend: list[str] = []
            for parent in frontier:
                with _translated():
                    children = tuple(provider.list_children(parent))
                for child in children:
                    if child.kind is ObjectKind.CONTAINER:
                        descend.append(child.source_object_id)
                        continue
                    found.append(child.source_object_id)
                    if len(found) > enrollment.max_items:
                        raise InvalidRequestError(SafeDetail.MAX_ITEMS)
            frontier = descend
        # A symlink inside the root and its target are one object with one
        # identifier (`providers.fixture.list_children`), so the same object can
        # be listed twice under two names. `dict.fromkeys` keeps the first
        # occurrence and the order; `record_scope` would collapse the duplicate
        # against its primary key anyway, but then `max_items` would have been
        # counted against a number the stored set does not have.
        return tuple(dict.fromkeys(found))

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
        """Coverage of one enrollment, with the denominator the store measured.

        Nothing about the size of the scope is passed down. The repository reads
        the enumerated object set beside the outcomes it counts, which is what
        makes the reported `eligible` a measurement rather than this layer's
        arithmetic. `queued` is still stated here, because work in flight is a
        fact about the job plane that no count of objects can carry.
        """
        with _translated():
            return unit_of_work.knowledge.coverage(
                enrollment.enrollment_id,
                observed_at=observed_at,
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
        Capability.KNOWLEDGE_REVEAL: ApplicationService._knowledge_reveal,
        Capability.CAPTURE_CREATE: ApplicationService._capture_create,
        Capability.CAPTURE_REVISE: ApplicationService._capture_revise,
        Capability.CAPTURE_READ: ApplicationService._capture_read,
        Capability.CAPTURE_LIST: ApplicationService._capture_list,
        Capability.CAPTURE_SEARCH: ApplicationService._capture_search,
        Capability.REVIEW_LIST: ApplicationService._review_list,
        Capability.REVIEW_DECIDE: ApplicationService._review_decide,
    }
)
