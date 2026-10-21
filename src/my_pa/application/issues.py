"""The Issue use cases of record lineage S1 (S1 contract sections 6 and 7.2).

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
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import TYPE_CHECKING, Final

from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.application.lineage_endpoints import (
    EvidenceAnchorInput,
    admit_evidence_anchor,
    lock_evidence_source,
)
from my_pa.contracts.ports import (
    IssueListPage,
    IssueRecord,
    IssueRepository,
    IssueRevisionRecord,
    LineageWriteRequestRecord,
    ProjectLinkEventRecord,
    RepositoryFailureError,
    UnitOfWork,
)
from my_pa.contracts.v1.issues import (
    MAX_ISSUE_PROJECT_LINKS,
    IssueListEntry,
    IssueRevisionView,
    IssueView,
    ProjectLinkView,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.lineage.canonical import request_digest
from my_pa.domain.lineage.vocabulary import (
    AcceptanceBasis,
    IssueProjectMembershipAction,
    IssueProjectMembershipState,
    IssueRevisionAction,
)
from my_pa.domain.situation.issue_lifecycle import IssueStateMoveError, issue_update_action
from my_pa.domain.situation.situation import SituationState
from my_pa.domain.source.registry import issue_identifier

if TYPE_CHECKING:
    # Type-only: `lineage_authority` reads `Authorization`, whose module imports
    # the command union that imports this module's request values.
    from my_pa.application.lineage_authority import LineageAuthority

__all__ = [
    "IssueApplication",
    "IssueCreateRequest",
    "IssueListRequest",
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
        state=revision.state.value,  # type: ignore[arg-type]
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


def _replayed_revision(
    issues: IssueRepository, principal_id: str, prior: LineageWriteRequestRecord
) -> IssueRevisionResult:
    if prior.result_issue_id is None or prior.result_issue_version is None:
        raise RepositoryFailureError
    issue = issues.read_issue(principal_id, prior.result_issue_id)
    revision = issues.read_issue_revision(
        principal_id, prior.result_issue_id, prior.result_issue_version
    )
    if issue is None or revision is None:
        raise RepositoryFailureError
    return IssueRevisionResult(issue=_revision_view(issue, revision), replayed=True)


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
        """One Issue with at most 100 Project links. A context Situation is `not_found`."""
        issues = uow.issues
        issue = issues.read_issue(principal_id, issue_id)
        if issue is None:
            raise NotFoundError(SafeDetail.ISSUE_ID)
        links = issues.project_links(principal_id, issue_id, limit=MAX_ISSUE_PROJECT_LINKS + 1)
        return IssueView(
            issue_id=issue.issue_id,
            version=issue.version,
            state=issue.state.value,  # type: ignore[arg-type]
            title=issue.title,
            description=issue.description,
            opened_at=issue.opened_at,
            created_at=issue.created_at,
            updated_at=issue.updated_at,
            project_links=tuple(_link_view(event) for event in links[:MAX_ISSUE_PROJECT_LINKS]),
            project_links_truncated=len(links) > MAX_ISSUE_PROJECT_LINKS,
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
                state=issue.state.value,  # type: ignore[arg-type]
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
        """Write the next revision and the `situations` row (`version + 1`)."""
        at = ensure_utc(now)
        issues = uow.issues
        digest = request_digest(_UPDATE, principal_id, _update_document(request))
        prior = issues.reserve_write_request(
            principal_id, _UPDATE, idempotency_key, digest, created_at=at
        )
        if prior is not None:
            return _replayed_revision(issues, principal_id, prior)
        current = issues.lock_issue(principal_id, request.issue_id, for_update=True)
        if current is None:
            raise NotFoundError(SafeDetail.ISSUE_ID)
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
            action = issue_update_action(current.state, request.state if moved else None)
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
        if issues.lock_issue(principal_id, issue_id, for_update=False) is None:
            raise NotFoundError(SafeDetail.ISSUE_ID)
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
