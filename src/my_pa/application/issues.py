"""The Issue use cases of record lineage (S1 contract sections 6 and 7.2; S2 contract 3.3, 6, 7.2).

`IssueApplication` is stateless. Every method takes the unit of work that
`ApplicationService.invoke` has **already opened**, the authenticated
`principal_id` as a plain parameter, the parsed request and, for a write, the
authority pair `application.lineage_authority` derived and the authorization
time. It opens no transaction: the reservation, locks, rows and request
completion below run in the caller's one transaction, so any refusal rolls all
of them back together and a refused write leaves no row and no request.

**Order of every write** (section 6.3): request digest, reservation (section
6.2 step 1), locks in section 6.2 order, validation, write, completion. A
replay -- the same key and digest -- answers from the immutable rows the stored
result names, never from current state, so its response is byte-identical to
the original apart from `replayed`.

**Errors are the public application errors**, each naming one field and never
a value: an absent, foreign or context-Situation Issue is `not_found` /
`issue_id`; a stale `expected_version` or `expected_membership_revision`, an
already-active Project link and a key reused for another request are
`conflict`; a refused value or state move is `invalid_request`.

**S2** adds `issues.close` behind the OD-03 gate (section 3.3: every mandatory
member natively closed, accepted where the family has acceptance, and proven
by available, current, uncontradicted resolution evidence; no exception, no
cascade), `issues.reopen`, the read-only `issues.closure_readiness`, the
`corrected` revision of a closed Issue's `issues.update` (attested, R2-F10 and
R2-F14), `IssueView.closure`, and the closed-Issue rule on the Project-link
writes (section 3.2). Closing or reopening changes no member, link or native
record.

**S3** (S3 contract section 3.2) adds one gate condition: no link in the
Issue's context has a `contested` head (the one "in the Issue's context"
predicate, `record_lineage.links_in_context`), so `issues.close` answers
`conflict` / `closure_gate` and `issues.closure_readiness` lists the
`contested_links` (at most 100, by `link_id`) and is not ready while any
exist. The close also shares the endpoints of every in-context semantic link
it evaluates.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Final

from my_pa.application.errors import (
    ConflictError,
    DeniedError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.application.lineage_endpoints import (
    EvidenceAnchorInput,
    admit_evidence_anchor,
    admit_evidence_set,
    anchor_input_of,
    anchor_inputs_document,
    insert_evidence_anchor,
    lock_evidence_source,
    lock_lineage_sources,
)
from my_pa.application.lineage_visibility import LineageVisibility
from my_pa.application.record_lineage import (
    anchor_view,
    evidence_availability,
    lineage_known_at,
    links_in_context,
    visible_anchor_sets,
)
from my_pa.contracts.ports import (
    IssueListPage,
    IssueRecord,
    IssueRepository,
    IssueRevisionRecord,
    LineageEndpoint,
    LineageFactCut,
    LineageLinkEvidence,
    LineageWriteRequestRecord,
    LinkHeadRecord,
    LinkRevisionRecord,
    ProjectLinkEventRecord,
    RecordLineageRepository,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.contracts.v1.issues import (
    MAX_CLOSURE_BLOCKERS,
    MAX_CONTESTED_LINKS,
    MAX_ISSUE_PROJECT_LINKS,
    ClosureBlockerView,
    ContestedLinkView,
    IssueClosureView,
    IssueHistoryEntryView,
    IssueListEntry,
    IssueReopeningView,
    IssueRevisionView,
    IssueView,
    ProjectLinkView,
)
from my_pa.contracts.v1.record_lineage import EvidenceAnchorView, RecordRefView
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.lineage.canonical import evidence_set_digest, request_digest
from my_pa.domain.lineage.closure import (
    MemberNativeFacts,
    MembershipHeadEvidence,
    has_resolution_anchor,
    member_blockers,
)
from my_pa.domain.lineage.model import EvidenceAnchor, RecordRef
from my_pa.domain.lineage.vocabulary import (
    ATTESTED_AUTHORITY_CLASSES,
    ATTESTED_DECISION_CHANNELS,
    AcceptanceBasis,
    EvidenceRole,
    EvidenceSourceFamily,
    IssueClosureBlocker,
    IssueProjectMembershipAction,
    IssueProjectMembershipState,
    IssueRevisionAction,
    LinkLifecycleState,
    RecordFamily,
)
from my_pa.domain.situation.issue_lifecycle import (
    IssueStateMoveError,
    issue_close_action,
    issue_correction_action,
    issue_reopen_action,
    issue_update_action,
)
from my_pa.domain.situation.situation import SituationState
from my_pa.domain.source.registry import issue_identifier

if TYPE_CHECKING:
    # Type-only: `lineage_authority` reads `Authorization`, whose module imports
    # the command union that imports this module's request values.
    from my_pa.application.lineage_authority import LineageAuthority

__all__ = [
    "IssueApplication",
    "IssueCloseRequest",
    "IssueCloseResult",
    "IssueClosureReadiness",
    "IssueCreateRequest",
    "IssueHistoryRequest",
    "IssueHistoryResult",
    "IssueListRequest",
    "IssueReopenRequest",
    "IssueReopenResult",
    "IssueRevisionResult",
    "IssueUpdateRequest",
    "ProjectLinkAddRequest",
    "ProjectLinkEndRequest",
    "ProjectLinkResult",
]

_CREATE: Final = Capability.ISSUES_CREATE.value
_UPDATE: Final = Capability.ISSUES_UPDATE.value
_LINK_ADD: Final = Capability.ISSUES_PROJECT_LINKS_ADD.value
_LINK_END: Final = Capability.ISSUES_PROJECT_LINKS_END.value
_CLOSE: Final = Capability.ISSUES_CLOSE.value
_REOPEN: Final = Capability.ISSUES_REOPEN.value


# ------------------------------------------------------------------- requests


@dataclass(frozen=True, slots=True)
class IssueCreateRequest:
    """`issues.create`, parsed: the title and optional description."""

    title: str
    description: str | None


@dataclass(frozen=True, slots=True)
class IssueUpdateRequest:
    """`issues.update`, parsed. `clear_fields` is a subset of `{"description"}`."""

    issue_id: str
    expected_version: int
    title: str | None
    description: str | None
    state: SituationState | None
    clear_fields: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class IssueListRequest:
    """`issues.list`, parsed."""

    page_size: int
    after: str | None
    state: SituationState | None
    project_id: str | None


@dataclass(frozen=True, slots=True)
class ProjectLinkAddRequest:
    """`issues.project_links.add`, parsed."""

    issue_id: str
    project_id: str
    expected_membership_revision: int
    evidence_anchor: EvidenceAnchorInput | None
    reason: str | None


@dataclass(frozen=True, slots=True)
class IssueCloseRequest:
    """`issues.close`, parsed: the outcome and the closure evidence set (1..32)."""

    issue_id: str
    expected_version: int
    outcome: str
    closure_evidence_anchors: tuple[EvidenceAnchorInput, ...]


@dataclass(frozen=True, slots=True)
class IssueReopenRequest:
    """`issues.reopen`, parsed: the reason and the optional evidence set (0..32)."""

    issue_id: str
    expected_version: int
    reason: str
    evidence_anchors: tuple[EvidenceAnchorInput, ...]


@dataclass(frozen=True, slots=True)
class ProjectLinkEndRequest:
    """`issues.project_links.end`, parsed."""

    issue_id: str
    project_id: str
    expected_membership_revision: int
    reason: str


# -------------------------------------------------------------------- results


@dataclass(frozen=True, slots=True)
class IssueRevisionResult:
    """What `issues.create` and `issues.update` answer."""

    issue: IssueRevisionView
    replayed: bool


@dataclass(frozen=True, slots=True)
class IssueCloseResult:
    """What `issues.close` answers."""

    issue: IssueRevisionView
    closure: IssueClosureView
    replayed: bool


@dataclass(frozen=True, slots=True)
class IssueReopenResult:
    """What `issues.reopen` answers."""

    issue: IssueRevisionView
    reopening: IssueReopeningView
    replayed: bool


@dataclass(frozen=True, slots=True)
class IssueClosureReadiness:
    """What `issues.closure_readiness` answers (no locks, current state)."""

    issue_id: str
    version: int
    state: str
    ready: bool
    blockers: tuple[ClosureBlockerView, ...]
    blockers_truncated: bool
    #: S3 section 7.1: contested links in the Issue's context, by `link_id`.
    contested_links: tuple[ContestedLinkView, ...] = ()
    contested_links_truncated: bool = False
    #: S3 section 6.4: whether a blocker or contested link was withheld from a
    #: remote reader (`ready` is computed over everything).
    restricted: bool = False


@dataclass(frozen=True, slots=True)
class IssueHistoryRequest:
    """`issues.history`, parsed (S3 section 7.3)."""

    issue_id: str
    known_at: datetime | None
    page_size: int
    after: int | None


@dataclass(frozen=True, slots=True)
class IssueHistoryResult:
    """One page of an Issue's revisions as known at `known_at` (`T_k`)."""

    issue_id: str
    known_at: datetime | None
    revisions: tuple[IssueHistoryEntryView, ...]
    next_cursor: int | None


@dataclass(frozen=True, slots=True)
class ProjectLinkResult:
    """What `issues.project_links.add` and `.end` answer."""

    project_link: ProjectLinkView
    issue_id: str
    replayed: bool


# --------------------------------------------------------------------- digest


def _create_document(request: IssueCreateRequest) -> dict[str, object]:
    return {"title": request.title, "description": request.description}


def _update_document(request: IssueUpdateRequest) -> dict[str, object]:
    return {
        "issue_id": request.issue_id,
        "expected_version": request.expected_version,
        "title": request.title,
        "description": request.description,
        "state": None if request.state is None else request.state.value,
        "clear_fields": sorted(request.clear_fields),
    }


def _link_add_document(request: ProjectLinkAddRequest) -> dict[str, object]:
    return {
        "issue_id": request.issue_id,
        "project_id": request.project_id,
        "expected_membership_revision": request.expected_membership_revision,
        "evidence_anchor": (
            None if request.evidence_anchor is None else request.evidence_anchor.digest_document()
        ),
        "reason": request.reason,
    }


def _close_document(request: IssueCloseRequest) -> dict[str, object]:
    return {
        "issue_id": request.issue_id,
        "expected_version": request.expected_version,
        "outcome": request.outcome,
        "closure_evidence_anchors": anchor_inputs_document(request.closure_evidence_anchors),
    }


def _reopen_document(request: IssueReopenRequest) -> dict[str, object]:
    return {
        "issue_id": request.issue_id,
        "expected_version": request.expected_version,
        "reason": request.reason,
        "evidence_anchors": anchor_inputs_document(request.evidence_anchors),
    }


def _link_end_document(request: ProjectLinkEndRequest) -> dict[str, object]:
    return {
        "issue_id": request.issue_id,
        "project_id": request.project_id,
        "expected_membership_revision": request.expected_membership_revision,
        "reason": request.reason,
    }


# -------------------------------------------------------------------- helpers


def _revision_view(issue: IssueRecord, revision: IssueRevisionRecord) -> IssueRevisionView:
    """An `IssueRevisionView` from immutable values only.

    `opened_at` and `created_at` never change after insert; everything else is
    the revision's own.
    """
    return IssueRevisionView(
        issue_id=revision.issue_id,
        version=revision.version,
        state=revision.state.value,
        title=revision.title,
        description=revision.description,
        revision_id=revision.revision_id,
        action=revision.action,
        opened_at=issue.opened_at,
        created_at=issue.created_at,
        recorded_at=revision.recorded_at,
    )


def _link_view(event: ProjectLinkEventRecord) -> ProjectLinkView:
    return ProjectLinkView(
        project_id=event.project_id,
        project_situation_id=event.project_situation_id,
        state=event.state,
        membership_revision_no=event.revision_no,
        acceptance_basis=AcceptanceBasis(event.acceptance_basis),
        evidence_anchor_id=event.evidence_anchor_id,
        recorded_at=event.recorded_at,
    )


def _stored_revision(
    issues: IssueRepository, principal_id: str, prior: LineageWriteRequestRecord
) -> tuple[IssueRecord, IssueRevisionRecord]:
    """The Issue and the immutable revision a completed request names."""
    if prior.result_issue_id is None or prior.result_issue_version is None:
        raise RepositoryFailureError
    issue = issues.read_issue(principal_id, prior.result_issue_id)
    revision = issues.read_issue_revision(
        principal_id, prior.result_issue_id, prior.result_issue_version
    )
    if issue is None or revision is None:
        raise RepositoryFailureError
    return issue, revision


def _replayed_revision(
    issues: IssueRepository, principal_id: str, prior: LineageWriteRequestRecord
) -> IssueRevisionResult:
    issue, revision = _stored_revision(issues, principal_id, prior)
    return IssueRevisionResult(issue=_revision_view(issue, revision), replayed=True)


def _require_attested(authority: LineageAuthority) -> None:
    """S2 section 6.1: `denied` unless the derived pair is local-operator attested."""
    if (
        authority.authority_class.value not in ATTESTED_AUTHORITY_CLASSES
        or authority.decision_channel.value not in ATTESTED_DECISION_CHANNELS
    ):
        raise DeniedError()


def _capture_roots(evidence: Sequence[LineageLinkEvidence]) -> frozenset[str]:
    return frozenset(
        cited.anchor.source_root_id
        for cited in evidence
        if cited.anchor.source_family is not EvidenceSourceFamily.MEETING_NOTE_VERSION
    )


def _evidence_views(
    lineage: RecordLineageRepository, principal_id: str, evidence: Sequence[LineageLinkEvidence]
) -> tuple[EvidenceAnchorView, ...]:
    archived = lineage.archived_capture_roots(principal_id, _capture_roots(evidence))
    return tuple(anchor_view(cited, archived) for cited in evidence)


def _closure_view(
    lineage: RecordLineageRepository, principal_id: str, closing: IssueRevisionRecord
) -> IssueClosureView:
    """`IssueClosureView` from the closing revision; no digest (FR1-F05)."""
    if closing.closed_at is None or closing.outcome is None:
        raise RepositoryFailureError
    return IssueClosureView(
        version=closing.version,
        closed_at=closing.closed_at,
        outcome=closing.outcome,
        evidence=_evidence_views(lineage, principal_id, closing.evidence),
    )


def _reopening_view(
    lineage: RecordLineageRepository, principal_id: str, revision: IssueRevisionRecord
) -> IssueReopeningView:
    if revision.reason is None:
        raise RepositoryFailureError
    return IssueReopeningView(
        reason=revision.reason,
        evidence=_evidence_views(lineage, principal_id, revision.evidence),
    )


def _inserted(
    issues: IssueRepository, principal_id: str, anchors: Sequence[EvidenceAnchor], at: datetime
) -> tuple[LineageLinkEvidence, ...]:
    """Reuse-or-insert each anchor in canonical order (S1 section 5.1 anchor writes)."""
    return tuple(
        LineageLinkEvidence(
            anchor_id=insert_evidence_anchor(issues, principal_id, anchor, recorded_at=at),
            anchor=anchor,
        )
        for anchor in anchors
    )


def _head_revision(
    lineage: RecordLineageRepository, principal_id: str, head: LinkHeadRecord
) -> LinkRevisionRecord:
    revision = lineage.read_revision(principal_id, head.link.link_id, head.revision_no)
    if revision is None:
        raise RepositoryFailureError
    return revision


def _native_facts(ref: RecordRef, endpoint: LineageEndpoint | None) -> MemberNativeFacts:
    if endpoint is None:
        return MemberNativeFacts(
            family=ref.family, native_state=None, evidence_state=None, version=None
        )
    return MemberNativeFacts(
        family=ref.family,
        native_state=endpoint.native_state,
        evidence_state=endpoint.evidence_state,
        version=endpoint.native_version,
    )


def _blockers_of(
    head: LinkHeadRecord,
    endpoint: LineageEndpoint | None,
    revision: LinkRevisionRecord,
    archived: Collection[str],
) -> tuple[IssueClosureBlocker, ...]:
    """Section 3.3 for one mandatory membership: every reason it blocks the close."""
    return member_blockers(
        _native_facts(head.link.to_ref, endpoint),
        MembershipHeadEvidence(
            anchors=tuple(cited.anchor for cited in revision.evidence),
            member_native_version=revision.member_native_version,
        ),
        lambda anchor: evidence_availability(anchor, archived),
    )


def _resolution_roots(revisions: Sequence[LinkRevisionRecord]) -> frozenset[str]:
    return frozenset(
        cited.anchor.source_root_id
        for revision in revisions
        for cited in revision.evidence
        if cited.anchor.source_family is not EvidenceSourceFamily.MEETING_NOTE_VERSION
    )


def _replayed_link(
    issues: IssueRepository, principal_id: str, prior: LineageWriteRequestRecord
) -> ProjectLinkResult:
    if prior.result_membership_event_id is None:
        raise RepositoryFailureError
    event = issues.read_membership_event(principal_id, prior.result_membership_event_id)
    if event is None:
        raise RepositoryFailureError
    return ProjectLinkResult(project_link=_link_view(event), issue_id=event.issue_id, replayed=True)


# ---------------------------------------------------------------- the service


@dataclass(frozen=True, slots=True)
class IssueApplication:
    """The six Issue use cases, over the unit of work the caller already opened."""

    # --- issues.create ------------------------------------------------------

    def create_issue(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: IssueCreateRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> IssueRevisionResult:
        """Insert an Issue `situations` row (version 1, `open`) and revision 1."""
        at = ensure_utc(now)
        issues = uow.issues
        digest = request_digest(_CREATE, principal_id, _create_document(request))
        prior = issues.reserve_write_request(
            principal_id, _CREATE, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            return _replayed_revision(issues, principal_id, prior)
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        uow.record_lineage.take_commit_mark(principal_id)
        issue = IssueRecord(
            issue_id=issue_identifier(IdKind.SITUATION),
            version=1,
            state=SituationState.OPEN,
            title=request.title,
            description=request.description,
            opened_at=at,
            created_at=at,
            updated_at=at,
        )
        revision = IssueRevisionRecord(
            issue_id=issue.issue_id,
            version=1,
            revision_id=issue_identifier(IdKind.ISSUE_REVISION),
            predecessor_version=None,
            action=IssueRevisionAction.CREATED,
            state=SituationState.OPEN,
            title=request.title,
            description=request.description,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_CREATE,
            recorded_at=at,
        )
        issues.insert_issue(principal_id, issue, revision)
        issues.complete_write_request(
            principal_id,
            _CREATE,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_issue_id=issue.issue_id,
            result_issue_version=1,
        )
        return IssueRevisionResult(issue=_revision_view(issue, revision), replayed=False)

    # --- issues.read / issues.list -------------------------------------------

    def read_issue(self, uow: UnitOfWork, principal_id: str, issue_id: str) -> IssueView:
        """One Issue with at most 100 Project links. A context Situation is `not_found`.

        A closed Issue carries `closure` (S2 section 7.1): its latest `closed`
        revision's basis.
        """
        issues = uow.issues
        issue = issues.read_issue(principal_id, issue_id)
        if issue is None:
            raise NotFoundError(SafeDetail.ISSUE_ID)
        closure: IssueClosureView | None = None
        if issue.state is SituationState.CLOSED:
            closing = issues.latest_closing_revision(
                principal_id, issue_id, at_or_below=issue.version
            )
            if closing is None:
                raise RepositoryFailureError
            closure = _closure_view(uow.record_lineage, principal_id, closing)
        links = issues.project_links(principal_id, issue_id, limit=MAX_ISSUE_PROJECT_LINKS + 1)
        return IssueView(
            issue_id=issue.issue_id,
            version=issue.version,
            state=issue.state.value,
            title=issue.title,
            description=issue.description,
            opened_at=issue.opened_at,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
            project_links=tuple(_link_view(event) for event in links[:MAX_ISSUE_PROJECT_LINKS]),
            project_links_truncated=len(links) > MAX_ISSUE_PROJECT_LINKS,
            closure=closure,
        )

    def issue_history(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: IssueHistoryRequest,
        *,
        now: datetime,
        visibility: LineageVisibility,
    ) -> IssueHistoryResult:
        """`issues.history` (S3 section 7.3): the revisions known at `T_k`, by version.

        An absent, foreign or context Situation, an Issue no revision of which
        is known at `T_k`, and (remote) an Issue the reader may not see are
        `not_found` / `issue_id`, alike. Each revision carries its closing or
        reopening evidence, visibility-filtered (section 6.4).
        """
        issues = uow.issues
        issue_ref = RecordRef(family=RecordFamily.SITUATION, record_id=request.issue_id)
        issue = issues.read_issue(principal_id, request.issue_id)
        if issue is None or not visibility.sees(issue_ref):
            raise NotFoundError(SafeDetail.ISSUE_ID)
        known_at = lineage_known_at(uow, principal_id, request.known_at, now)
        cut = LineageFactCut(
            watermark=None
            if known_at is None
            else uow.record_lineage.commit_watermark(principal_id, known_at),
            at=known_at,
        )
        if not issues.issue_revisions_known_at(
            principal_id, request.issue_id, cut, after=None, limit=1
        ):
            raise NotFoundError(SafeDetail.ISSUE_ID)
        revisions = issues.issue_revisions_known_at(
            principal_id, request.issue_id, cut, after=request.after, limit=request.page_size + 1
        )
        shown = revisions[: request.page_size]
        sets, _ = visible_anchor_sets(
            uow.record_lineage,
            principal_id,
            [revision.evidence for revision in shown],
            visibility,
        )
        return IssueHistoryResult(
            issue_id=request.issue_id,
            known_at=known_at,
            revisions=tuple(
                IssueHistoryEntryView(
                    **_revision_view(issue, revision).model_dump(),
                    closed_at=revision.closed_at,
                    outcome=revision.outcome,
                    reason=revision.reason,
                    evidence=evidence,
                )
                for revision, evidence in zip(shown, sets, strict=True)
            ),
            next_cursor=shown[-1].version if len(revisions) > request.page_size and shown else None,
        )

    def list_issues(
        self, uow: UnitOfWork, principal_id: str, request: IssueListRequest
    ) -> tuple[tuple[IssueListEntry, ...], str | None]:
        """One keyset page and its `next_cursor` (the last `issue_id`, when more follow)."""
        page: IssueListPage = uow.issues.list_issues(
            principal_id,
            page_size=request.page_size,
            after=request.after,
            state=request.state,
            project_id=request.project_id,
        )
        entries = tuple(
            IssueListEntry(
                issue_id=issue.issue_id,
                version=issue.version,
                state=issue.state.value,
                title=issue.title,
                updated_at=issue.updated_at,
            )
            for issue in page.entries
        )
        next_cursor = entries[-1].issue_id if page.has_more and entries else None
        return entries, next_cursor

    # --- issues.update --------------------------------------------------------

    def update_issue(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: IssueUpdateRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> IssueRevisionResult:
        """Write the next revision and the `situations` row (`version + 1`).

        On a closed Issue (S2 section 7.2) the update is a correction: attested
        (`denied` otherwise, R2-F10), title/description/`clear_fields` only, the
        Issue stays closed with its `closed_at` and `outcome`. A replay of a
        `corrected` revision derives attestation before it answers (R2-F14).
        """
        at = ensure_utc(now)
        issues = uow.issues
        digest = request_digest(_UPDATE, principal_id, _update_document(request))
        prior = issues.reserve_write_request(
            principal_id, _UPDATE, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            stored_issue, stored = _stored_revision(issues, principal_id, prior)
            if stored.action is IssueRevisionAction.CORRECTED:
                _require_attested(authority)
            return IssueRevisionResult(issue=_revision_view(stored_issue, stored), replayed=True)
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        uow.record_lineage.take_commit_mark(principal_id)
        current = issues.lock_issue(principal_id, request.issue_id, for_update=True)
        if current is None:
            raise NotFoundError(SafeDetail.ISSUE_ID)
        closed = current.state is SituationState.CLOSED
        if closed:
            _require_attested(authority)
        if current.version != request.expected_version:
            raise ConflictError(SafeDetail.STALE_VERSION)
        title = current.title if request.title is None else request.title
        if "description" in request.clear_fields:
            description = None
        elif request.description is not None:
            description = request.description
        else:
            description = current.description
        state = current.state if request.state is None else request.state
        moved = state is not current.state
        refused = False
        try:
            action = (
                issue_correction_action(current.state, request.state)
                if closed
                else issue_update_action(current.state, request.state if moved else None)
            )
        except IssueStateMoveError:
            refused = True
            action = IssueRevisionAction.UPDATED
        if refused or (request.state is not None and not moved):
            raise InvalidRequestError(SafeDetail.STATE)
        if not moved and title == current.title and description == current.description:
            # A request that changes nothing is refused (section 7.2).
            raise InvalidRequestError(SafeDetail.MUTATIONS)
        version = current.version + 1
        updated = replace(
            current,
            version=version,
            state=state,
            title=title,
            description=description,
            updated_at=at,
        )
        revision = IssueRevisionRecord(
            issue_id=current.issue_id,
            version=version,
            revision_id=issue_identifier(IdKind.ISSUE_REVISION),
            predecessor_version=current.version,
            action=action,
            state=state,
            title=title,
            description=description,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_UPDATE,
            recorded_at=at,
            # A correction copies the closure it corrects (both `None` otherwise).
            closed_at=current.closed_at,
            outcome=current.outcome,
        )
        issues.update_issue(principal_id, updated, revision)
        issues.complete_write_request(
            principal_id,
            _UPDATE,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_issue_id=current.issue_id,
            result_issue_version=version,
        )
        return IssueRevisionResult(issue=_revision_view(updated, revision), replayed=False)

    # --- issues.close / issues.reopen / issues.closure_readiness (S2) -----------

    def close_issue(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: IssueCloseRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> IssueCloseResult:
        """Close an Issue behind the OD-03 gate (S2 sections 3.3, 6.2 and 7.2).

        Lock order: the request row; the Issue `FOR UPDATE`; `FOR SHARE` in
        `(family token, identifier)` order over every mandatory member's native
        row, the closure set's sources and the source of every `resolution`
        anchor in every mandatory member's head revision (R2-F06); then every
        mandatory membership head `FOR SHARE` by `link_id`. The membership set
        is stable once the Issue is locked: every membership writer shares it.
        """
        at = ensure_utc(now)
        issues, lineage = uow.issues, uow.record_lineage
        digest = request_digest(_CLOSE, principal_id, _close_document(request))
        prior = issues.reserve_write_request(
            principal_id, _CLOSE, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            stored_issue, stored = _stored_revision(issues, principal_id, prior)
            return IssueCloseResult(
                issue=_revision_view(stored_issue, stored),
                closure=_closure_view(lineage, principal_id, stored),
                replayed=True,
            )
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        uow.record_lineage.take_commit_mark(principal_id)
        current = issues.lock_issue(principal_id, request.issue_id, for_update=True)
        if current is None:
            raise NotFoundError(SafeDetail.ISSUE_ID)
        if current.version != request.expected_version:
            raise ConflictError(SafeDetail.STALE_VERSION)
        refused = False
        try:
            action = issue_close_action(current.state)
        except IssueStateMoveError:
            refused = True
            action = IssueRevisionAction.CLOSED
        if refused:
            raise ConflictError(SafeDetail.STATE)
        heads = lineage.mandatory_memberships(principal_id, request.issue_id, share=False)
        revisions = {
            head.link.link_id: _head_revision(lineage, principal_id, head) for head in heads
        }
        resolution_sources = tuple(
            anchor_input_of(cited.anchor)
            for revision in revisions.values()
            for cited in revision.evidence
            if cited.anchor.role is EvidenceRole.RESOLUTION
        )
        closure_set = request.closure_evidence_anchors
        # S3 section 3.2: the live semantic links in the Issue's context. Every
        # contest or reinstate of one shares this Issue, so they are stable once
        # it is locked; their endpoints are shared with the members.
        in_context = links_in_context(lineage, principal_id, request.issue_id)
        issue_ref = RecordRef(family=RecordFamily.SITUATION, record_id=request.issue_id)
        shared_refs = list(dict.fromkeys(head.link.to_ref for head in heads))
        for head in in_context:
            for ref in (head.link.from_ref, head.link.to_ref):
                if ref != issue_ref and ref not in shared_refs:
                    shared_refs.append(ref)
        locked = lock_lineage_sources(
            issues,
            lineage,
            principal_id,
            endpoints=tuple((ref, SafeDetail.MEMBER) for ref in shared_refs),
            anchors=closure_set + resolution_sources,
            anchor_detail=SafeDetail.CLOSURE_EVIDENCE_ANCHORS,
        )
        shared = lineage.mandatory_memberships(principal_id, request.issue_id, share=True)
        if [(head.link.link_id, head.revision_no) for head in shared] != [
            (head.link.link_id, head.revision_no) for head in heads
        ]:
            # Unreachable while every membership writer shares the Issue.
            raise ConflictError(SafeDetail.STALE_VERSION)
        anchors = admit_evidence_set(
            issues,
            principal_id,
            locked.evidence[: len(closure_set)],
            detail=SafeDetail.CLOSURE_EVIDENCE_ANCHORS,
        )
        if not has_resolution_anchor(anchors) or any(
            anchor.role is EvidenceRole.CONTRADICTS for anchor in anchors
        ):
            raise InvalidRequestError(SafeDetail.CLOSURE_EVIDENCE_ANCHORS)
        archived = lineage.archived_capture_roots(
            principal_id, _resolution_roots(tuple(revisions.values()))
        )
        for head in heads:
            if _blockers_of(
                head,
                locked.endpoints.get(head.link.to_ref),
                revisions[head.link.link_id],
                archived,
            ):
                raise ConflictError(SafeDetail.CLOSURE_GATE)
        if any(head.lifecycle_state is LinkLifecycleState.CONTESTED for head in in_context):
            # S3 section 3.2: a disputed claim in the Issue's context holds the close.
            raise ConflictError(SafeDetail.CLOSURE_GATE)
        version = current.version + 1
        revision = IssueRevisionRecord(
            issue_id=current.issue_id,
            version=version,
            revision_id=issue_identifier(IdKind.ISSUE_REVISION),
            predecessor_version=current.version,
            action=action,
            state=SituationState.CLOSED,
            title=current.title,
            description=current.description,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_CLOSE,
            recorded_at=at,
            closed_at=at,
            outcome=request.outcome,
            evidence=_inserted(issues, principal_id, anchors, at),
            evidence_set_digest=evidence_set_digest(anchors),
        )
        updated = replace(
            current,
            version=version,
            state=SituationState.CLOSED,
            updated_at=at,
            closed_at=at,
            outcome=request.outcome,
        )
        issues.update_issue(principal_id, updated, revision)
        issues.complete_write_request(
            principal_id,
            _CLOSE,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_issue_id=current.issue_id,
            result_issue_version=version,
        )
        return IssueCloseResult(
            issue=_revision_view(updated, revision),
            closure=_closure_view(lineage, principal_id, revision),
            replayed=False,
        )

    def reopen_issue(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: IssueReopenRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> IssueReopenResult:
        """Reopen a closed Issue (S2 section 7.2): `active`, closure cleared, nothing else.

        Reopens no member, link or native record. The optional evidence set is
        admitted by the S1 rules with any role and frozen on the revision.
        """
        at = ensure_utc(now)
        issues, lineage = uow.issues, uow.record_lineage
        digest = request_digest(_REOPEN, principal_id, _reopen_document(request))
        prior = issues.reserve_write_request(
            principal_id, _REOPEN, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            stored_issue, stored = _stored_revision(issues, principal_id, prior)
            return IssueReopenResult(
                issue=_revision_view(stored_issue, stored),
                reopening=_reopening_view(lineage, principal_id, stored),
                replayed=True,
            )
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        uow.record_lineage.take_commit_mark(principal_id)
        current = issues.lock_issue(principal_id, request.issue_id, for_update=True)
        if current is None:
            raise NotFoundError(SafeDetail.ISSUE_ID)
        if current.version != request.expected_version:
            raise ConflictError(SafeDetail.STALE_VERSION)
        refused = False
        try:
            action = issue_reopen_action(current.state)
        except IssueStateMoveError:
            refused = True
            action = IssueRevisionAction.REOPENED
        if refused:
            raise ConflictError(SafeDetail.STATE)
        locked = lock_lineage_sources(
            issues, lineage, principal_id, anchors=request.evidence_anchors
        )
        anchors = admit_evidence_set(issues, principal_id, locked.evidence)
        version = current.version + 1
        revision = IssueRevisionRecord(
            issue_id=current.issue_id,
            version=version,
            revision_id=issue_identifier(IdKind.ISSUE_REVISION),
            predecessor_version=current.version,
            action=action,
            state=SituationState.ACTIVE,
            title=current.title,
            description=current.description,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_REOPEN,
            recorded_at=at,
            reason=request.reason,
            evidence=_inserted(issues, principal_id, anchors, at),
            evidence_set_digest=evidence_set_digest(anchors) if anchors else None,
        )
        updated = replace(
            current,
            version=version,
            state=SituationState.ACTIVE,
            updated_at=at,
            closed_at=None,
            outcome=None,
        )
        issues.update_issue(principal_id, updated, revision)
        issues.complete_write_request(
            principal_id,
            _REOPEN,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_issue_id=current.issue_id,
            result_issue_version=version,
        )
        return IssueReopenResult(
            issue=_revision_view(updated, revision),
            reopening=_reopening_view(lineage, principal_id, revision),
            replayed=False,
        )

    def closure_readiness(
        self,
        uow: UnitOfWork,
        principal_id: str,
        issue_id: str,
        *,
        visible: Callable[[RecordRef], bool] | None = None,
    ) -> IssueClosureReadiness:
        """Evaluate the gate without writing or locking (S2 section 7.2).

        Says nothing about the closure evidence `issues.close` is given. A
        closed Issue answers `ready: false` and no blockers. `visible` is the
        reader's section 6.4 family visibility (S3): a blocker whose member, or
        a contested link with an endpoint, it may not see is withheld and
        `restricted` says so; `ready` is computed over everything.
        """
        issues, lineage = uow.issues, uow.record_lineage
        issue = issues.read_issue(principal_id, issue_id)
        if issue is None:
            raise NotFoundError(SafeDetail.ISSUE_ID)
        if issue.state is SituationState.CLOSED:
            return IssueClosureReadiness(
                issue_id=issue.issue_id,
                version=issue.version,
                state=issue.state.value,
                ready=False,
                blockers=(),
                blockers_truncated=False,
            )
        heads = lineage.mandatory_memberships(principal_id, issue_id, share=False)
        natives = lineage.native_members(principal_id, {head.link.to_ref for head in heads})
        revisions = {
            head.link.link_id: _head_revision(lineage, principal_id, head) for head in heads
        }
        archived = lineage.archived_capture_roots(
            principal_id, _resolution_roots(tuple(revisions.values()))
        )
        blocked: list[ClosureBlockerView] = []
        for head in heads:
            member = head.link.to_ref
            native = natives.get(member)
            reasons = _blockers_of(head, native, revisions[head.link.link_id], archived)
            if not reasons or head.link.member_role is None:
                continue
            blocked.append(
                ClosureBlockerView(
                    link_id=head.link.link_id,
                    member=RecordRefView(family=member.family, record_id=member.record_id),
                    role=head.link.member_role,
                    native_state=None if native is None else native.native_state,
                    evidence_state=(
                        native.evidence_state
                        if native is not None
                        and member.family in (RecordFamily.TASK, RecordFamily.COMMITMENT)
                        else None
                    ),
                    reasons=reasons,
                )
            )
        blocked.sort(
            key=lambda view: (view.member.family.value, view.member.record_id, view.link_id)
        )
        # S3 section 3.2: every contested link in the Issue's context, by `link_id`.
        disputed = sorted(
            (
                head
                for head in links_in_context(lineage, principal_id, issue_id)
                if head.lifecycle_state is LinkLifecycleState.CONTESTED
            ),
            key=lambda head: head.link.link_id,
        )
        ready = not blocked and not disputed
        sees = visible if visible is not None else (lambda _ref: True)
        shown = [
            view
            for view in blocked
            if sees(RecordRef(family=view.member.family, record_id=view.member.record_id))
        ]
        contested = [
            ContestedLinkView(link_id=head.link.link_id, relation_type=head.link.relation_type)
            for head in disputed
            if sees(head.link.from_ref) and sees(head.link.to_ref)
        ]
        return IssueClosureReadiness(
            issue_id=issue.issue_id,
            version=issue.version,
            state=issue.state.value,
            ready=ready,
            blockers=tuple(shown[:MAX_CLOSURE_BLOCKERS]),
            blockers_truncated=len(shown) > MAX_CLOSURE_BLOCKERS,
            contested_links=tuple(contested[:MAX_CONTESTED_LINKS]),
            contested_links_truncated=len(contested) > MAX_CONTESTED_LINKS,
            restricted=len(shown) < len(blocked) or len(contested) < len(disputed),
        )

    # --- issues.project_links.add / end ----------------------------------------

    def add_project_link(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: ProjectLinkAddRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> ProjectLinkResult:
        """Assert a new link (`expected = 0`) or reinstate an ended one (`expected = n`)."""
        at = ensure_utc(now)
        issues = uow.issues
        digest = request_digest(_LINK_ADD, principal_id, _link_add_document(request))
        prior = issues.reserve_write_request(
            principal_id, _LINK_ADD, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            return _replayed_link(issues, principal_id, prior)
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        uow.record_lineage.take_commit_mark(principal_id)
        anchor_id = self._share_link_ends(
            issues,
            principal_id,
            issue_id=request.issue_id,
            project_id=request.project_id,
            anchor=request.evidence_anchor,
            at=at,
        )
        psit = issues.claim_project_link(
            principal_id,
            project_id=request.project_id,
            issue_id=request.issue_id,
            project_situation_id=issue_identifier(IdKind.PROJECT_SITUATION),
            linked_at=at,
            association_evidence_ref=anchor_id,
        )
        latest = issues.latest_membership_event(principal_id, request.project_id, request.issue_id)
        expected = request.expected_membership_revision
        if latest is None:
            if expected != 0:
                raise ConflictError(SafeDetail.STALE_VERSION)
            action = IssueProjectMembershipAction.ASSERT
            revision_no = 1
        else:
            if expected != latest.revision_no or latest.state is not (
                IssueProjectMembershipState.ENDED
            ):
                # Stale, or the link is already active: both are `conflict`.
                raise ConflictError(SafeDetail.STALE_VERSION)
            action = IssueProjectMembershipAction.REINSTATE
            revision_no = latest.revision_no + 1
        event = ProjectLinkEventRecord(
            membership_event_id=issue_identifier(IdKind.ISSUE_PROJECT_MEMBERSHIP_EVENT),
            project_id=request.project_id,
            issue_id=request.issue_id,
            project_situation_id=psit,
            revision_no=revision_no,
            predecessor_revision_no=None if latest is None else latest.revision_no,
            action=action,
            state=IssueProjectMembershipState.ACTIVE,
            evidence_anchor_id=anchor_id,
            reason=request.reason,
            acceptance_basis=AcceptanceBasis.USER_CONFIRMED.value,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_LINK_ADD,
            recorded_at=at,
        )
        return self._complete_link(
            issues, principal_id, _LINK_ADD, idempotency_key, digest, event, at
        )

    def end_project_link(
        self,
        uow: UnitOfWork,
        principal_id: str,
        request: ProjectLinkEndRequest,
        idempotency_key: str,
        authority: LineageAuthority,
        now: datetime,
    ) -> ProjectLinkResult:
        """End an active link whose latest event is `expected_membership_revision`."""
        at = ensure_utc(now)
        issues = uow.issues
        digest = request_digest(_LINK_END, principal_id, _link_end_document(request))
        prior = issues.reserve_write_request(
            principal_id, _LINK_END, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            return _replayed_link(issues, principal_id, prior)
        # S3 section 6.2 step 1b: the commit mark, before any other lock.
        uow.record_lineage.take_commit_mark(principal_id)
        self._share_link_ends(
            issues,
            principal_id,
            issue_id=request.issue_id,
            project_id=request.project_id,
            anchor=None,
            at=at,
        )
        latest = issues.latest_membership_event(principal_id, request.project_id, request.issue_id)
        if latest is None:
            # No link between them: nothing names this Issue in that Project.
            raise ConflictError(SafeDetail.STALE_VERSION)
        psit = issues.claim_project_link(
            principal_id,
            project_id=request.project_id,
            issue_id=request.issue_id,
            project_situation_id=latest.project_situation_id,
            linked_at=at,
            association_evidence_ref=None,
        )
        # Re-read under the triplet row lock: a concurrent writer that held it
        # has committed, and its event is now the latest.
        latest = issues.latest_membership_event(principal_id, request.project_id, request.issue_id)
        if (
            latest is None
            or latest.revision_no != request.expected_membership_revision
            or latest.state is not IssueProjectMembershipState.ACTIVE
        ):
            raise ConflictError(SafeDetail.STALE_VERSION)
        event = ProjectLinkEventRecord(
            membership_event_id=issue_identifier(IdKind.ISSUE_PROJECT_MEMBERSHIP_EVENT),
            project_id=request.project_id,
            issue_id=request.issue_id,
            project_situation_id=psit,
            revision_no=latest.revision_no + 1,
            predecessor_revision_no=latest.revision_no,
            action=IssueProjectMembershipAction.END,
            state=IssueProjectMembershipState.ENDED,
            evidence_anchor_id=None,
            reason=request.reason,
            acceptance_basis=AcceptanceBasis.USER_CONFIRMED.value,
            authority_class=authority.authority_class.value,
            decision_channel=authority.decision_channel.value,
            source_capability=_LINK_END,
            recorded_at=at,
        )
        return self._complete_link(
            issues, principal_id, _LINK_END, idempotency_key, digest, event, at
        )

    @staticmethod
    def _share_link_ends(
        issues: IssueRepository,
        principal_id: str,
        *,
        issue_id: str,
        project_id: str,
        anchor: EvidenceAnchorInput | None,
        at: datetime,
    ) -> str | None:
        """Section 6.2 step 3 for a Project-link write, and the anchor if any.

        A link write does not change the Issue, so it is shared, not updated.
        Everything is taken `FOR SHARE` in `(family token, identifier)` order:
        the anchor's source (`capture` / `capture_version` /
        `meeting_note_version`), then `project`, then `situation` (the Issue).
        Each is checked for existence as it is locked, so the first absent or
        foreign one answers `not_found` and nothing is written.
        """
        locked = (
            None
            if anchor is None
            else lock_evidence_source(issues, principal_id, anchor, SafeDetail.EVIDENCE_ANCHOR)
        )
        if not issues.share_project(principal_id, project_id):
            raise NotFoundError(SafeDetail.PROJECT_ID)
        issue = issues.lock_issue(principal_id, issue_id, for_update=False)
        if issue is None:
            raise NotFoundError(SafeDetail.ISSUE_ID)
        if issue.state is SituationState.CLOSED:
            # S2 section 3.2: a closed Issue's Project scope is frozen.
            raise ConflictError(SafeDetail.STATE)
        if locked is None:
            return None
        # Only after every existence check (section 3.2 check order): the
        # source's lifecycle, classification and digests, then the anchor row.
        return admit_evidence_anchor(
            issues, principal_id, locked, recorded_at=at, detail=SafeDetail.EVIDENCE_ANCHOR
        )

    @staticmethod
    def _complete_link(
        issues: IssueRepository,
        principal_id: str,
        capability: str,
        idempotency_key: str,
        digest: str,
        event: ProjectLinkEventRecord,
        at: datetime,
    ) -> ProjectLinkResult:
        issues.insert_membership_event(principal_id, event)
        issues.complete_write_request(
            principal_id,
            capability,
            idempotency_key,
            request_digest=digest,
            completed_at=at,
            result_membership_event_id=event.membership_event_id,
        )
        return ProjectLinkResult(
            project_link=_link_view(event), issue_id=event.issue_id, replayed=False
        )
