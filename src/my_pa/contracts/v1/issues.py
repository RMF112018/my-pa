"""The public shapes of an Issue answer (record lineage S1 contract section 7.1).

Four models: `IssueRevisionView` for the `issues.create`/`issues.update` write
results, `IssueView` for an `issues.read`, `ProjectLinkView` for one native
Issue↔Project link, and `IssueListEntry` for an `issues.list` row.

**What these models cannot carry is the point of them.** No `principal_id`, no
idempotency key and no request digest: the caller acts inside its own partition,
and the request identity is the server's arbitration of a write, not part of
what the write did. `IssueRevisionView` is rebuilt from the immutable revision a
write recorded, so a replay answers byte-for-byte what the original did (apart
from `replayed`, which is beside it) even after the Issue moved on.
"""

from __future__ import annotations

from typing import Literal

from pydantic import Field, field_validator

from my_pa.contracts.v1.base import StrictModel, UtcDatetime
from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.lineage.model import MAX_ISSUE_DESCRIPTION_CHARACTERS, MAX_ISSUE_TITLE_CHARACTERS
from my_pa.domain.lineage.vocabulary import (
    AcceptanceBasis,
    IssueProjectMembershipState,
    IssueRevisionAction,
)

__all__ = [
    "MAX_ISSUE_PROJECT_LINKS",
    "IssueListEntry",
    "IssueRevisionView",
    "IssueView",
    "ProjectLinkView",
]

#: At most this many Project links in one `IssueView` (section 7.1).
MAX_ISSUE_PROJECT_LINKS = 100

#: The three Issue states S1 holds (section 3).
IssueState = Literal["open", "active", "suspended"]

_Title = Field(min_length=1, max_length=MAX_ISSUE_TITLE_CHARACTERS)
_Description = Field(default=None, max_length=MAX_ISSUE_DESCRIPTION_CHARACTERS)


def _valid_issue_id(value: str) -> str:
    return validate_identifier(value, IdKind.SITUATION)


class IssueRevisionView(StrictModel):
    """One immutable Issue revision as an `issues.create`/`issues.update` result.

    Carries no Project links: a link write never changes the Issue's version.
    """

    issue_id: str
    kind: Literal["issue_workstream"] = "issue_workstream"
    version: int = Field(ge=1)
    state: IssueState
    title: str = _Title
    description: str | None = _Description
    revision_id: str
    action: IssueRevisionAction
    opened_at: UtcDatetime
    created_at: UtcDatetime
    recorded_at: UtcDatetime

    @field_validator("issue_id")
    @classmethod
    def _issue_id(cls, value: str) -> str:
        return _valid_issue_id(value)

    @field_validator("revision_id")
    @classmethod
    def _revision_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.ISSUE_REVISION)


class ProjectLinkView(StrictModel):
    """One native Issue↔Project link, as its latest membership event states it."""

    project_id: str
    project_situation_id: str
    state: IssueProjectMembershipState
    membership_revision_no: int = Field(ge=1)
    acceptance_basis: AcceptanceBasis
    evidence_anchor_id: str | None = None
    recorded_at: UtcDatetime

    @field_validator("project_id")
    @classmethod
    def _project_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.PROJECT)

    @field_validator("project_situation_id")
    @classmethod
    def _project_situation_id(cls, value: str) -> str:
        return validate_identifier(value, IdKind.PROJECT_SITUATION)

    @field_validator("evidence_anchor_id")
    @classmethod
    def _evidence_anchor_id(cls, value: str | None) -> str | None:
        return None if value is None else validate_identifier(value, IdKind.LINEAGE_EVIDENCE_ANCHOR)


class IssueView(StrictModel):
    """One Issue as `issues.read` answers it, with at most 100 Project links."""

    issue_id: str
    kind: Literal["issue_workstream"] = "issue_workstream"
    version: int = Field(ge=1)
    state: IssueState
    title: str = _Title
    description: str | None = _Description
    opened_at: UtcDatetime
    created_at: UtcDatetime
    updated_at: UtcDatetime
    project_links: tuple[ProjectLinkView, ...] = Field(max_length=MAX_ISSUE_PROJECT_LINKS)
    project_links_truncated: bool

    @field_validator("issue_id")
    @classmethod
    def _issue_id(cls, value: str) -> str:
        return _valid_issue_id(value)


class IssueListEntry(StrictModel):
    """One Issue as an `issues.list` page row: no description, no links."""

    issue_id: str
    version: int = Field(ge=1)
    state: IssueState
    title: str = _Title
    updated_at: UtcDatetime

    @field_validator("issue_id")
    @classmethod
    def _issue_id(cls, value: str) -> str:
        return _valid_issue_id(value)
