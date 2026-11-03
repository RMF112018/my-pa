"""Schedule Scenarios S6-1: operator-approved Project baselines, pure over event lists.

Contract `docs/architecture/schedule-scenarios-contract.md` section 12. A
publication is a **baseline** iff an approved, eligible, non-revoked Baseline
names it; every other publication is a standard update. Everything here is
derived from the append-only per-Project event chains, never stored:

* `baseline_status` folds the baseline events (`propose`, `approve`,
  `reject`, `withdraw`, `revoke`) into one view per Baseline: lifecycle,
  proposed and **effective** type (the `approve` event's, RR2-F01), label,
  `superseded`, eligibility and effectiveness;
* `governing_baseline` reads the governing chain now (maximum `seq`) or **as
  recorded** at an instant (maximum `seq` among `recorded_at <= t`); a
  baseline's `effective_from` is shown, never used for selection (S6-O19);
* `next_baseline_label` is `BL-<n>`, `n` the Project's approval ordinal from 0
  (labels are never reused, S6-O20);
* `decide_baseline_write` and `compare_refusal` are the transition and
  comparison rules the S6-2 writer re-checks under the Project lock.

The database backstops (section 12.1 "enforcement") and the lock are S6-2's.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from enum import StrEnum
from typing import Final

__all__ = [
    "MAX_PENDING_PER_BUCKET",
    "MAX_PENDING_PER_PROJECT",
    "ApproveRequest",
    "BaselineAction",
    "BaselineEvent",
    "BaselinePlan",
    "BaselineRefusal",
    "BaselineStatus",
    "BaselineType",
    "BaselineView",
    "GoverningEvent",
    "ProposeRequest",
    "RejectRequest",
    "RevokeRequest",
    "SetGoverningRequest",
    "WithdrawRequest",
    "baseline_status",
    "compare_refusal",
    "decide_baseline_write",
    "governing_baseline",
    "next_baseline_label",
]

#: Section 8.3 / RR1-F06: pending proposals per Project and per writer bucket per Project.
MAX_PENDING_PER_PROJECT: Final = 50
MAX_PENDING_PER_BUCKET: Final = 10


class BaselineAction(StrEnum):
    PROPOSE = "propose"
    APPROVE = "approve"
    REJECT = "reject"
    WITHDRAW = "withdraw"
    REVOKE = "revoke"


class BaselineType(StrEnum):
    CONTRACT = "contract"
    APPROVED_UPDATE = "approved_update"


class BaselineStatus(StrEnum):
    """Derived, never stored. `ineligible` = approved, but its publication is not eligible."""

    PROPOSED = "proposed"
    APPROVED = "approved"
    INELIGIBLE = "ineligible"
    REJECTED = "rejected"
    WITHDRAWN = "withdrawn"
    REVOKED = "revoked"


class BaselineRefusal(StrEnum):
    """The public error each refusal maps to (section 12.4)."""

    CONFLICT_BASELINE_ID = "conflict(BASELINE_ID)"
    CONFLICT_GOVERNING = "conflict(GOVERNING)"
    CONFLICT_STATUS = "conflict(STATUS)"
    RATE_LIMITED_BASELINE_ID = "rate_limited(BASELINE_ID)"
    INVALID_TO_PUBLICATION_ID = "invalid_request(TO_PUBLICATION_ID)"
    DENIED = "denied"


@dataclass(frozen=True, slots=True)
class BaselineEvent:
    """One `sbev_` event of the Project chain (provenance and reason omitted here)."""

    seq: int
    baseline_id: str
    publication_id: str
    action: BaselineAction
    recorded_at: datetime
    #: The proposed type on `propose`; the effective type on `approve`.
    type: BaselineType | None = None
    label: str | None = None
    effective_from: date | None = None
    supersedes_baseline_id: str | None = None
    proposal_ordinal: int | None = None
    #: The client writer bucket that wrote it; `None` for the attested operator.
    writer_bucket: str | None = None


@dataclass(frozen=True, slots=True)
class GoverningEvent:
    """One `sgov_` event of the Project's governing chain."""

    seq: int
    baseline_id: str
    recorded_at: datetime


@dataclass(frozen=True, slots=True)
class BaselineView:
    baseline_id: str
    publication_id: str
    status: BaselineStatus
    proposed_type: BaselineType | None
    effective_type: BaselineType | None
    label: str | None
    effective_from: date | None
    superseded: bool
    proposer_bucket: str | None

    @property
    def effective(self) -> bool:
        """Approved, not revoked, and its publication eligible (section 12.1)."""
        return self.status is BaselineStatus.APPROVED

    @property
    def pending(self) -> bool:
        return self.status is BaselineStatus.PROPOSED


_DECISIONS: Final = frozenset(
    {BaselineAction.APPROVE, BaselineAction.REJECT, BaselineAction.WITHDRAW}
)


def _chain(events: Iterable[BaselineEvent]) -> list[BaselineEvent]:
    ordered = sorted(events, key=lambda event: event.seq)
    if [event.seq for event in ordered] != list(range(1, len(ordered) + 1)):
        raise ValueError("a baseline event chain is seq 1, 2, ... without gaps")
    return ordered


def baseline_status(
    events: Iterable[BaselineEvent], *, eligible_publication_ids: Iterable[str]
) -> dict[str, BaselineView]:
    """Every Baseline of the Project by id, in the order its first event was recorded."""
    eligible = frozenset(eligible_publication_ids)
    ordered = _chain(events)
    superseded = {
        event.supersedes_baseline_id
        for event in ordered
        if event.action is BaselineAction.APPROVE and event.supersedes_baseline_id is not None
    }
    views: dict[str, BaselineView] = {}
    for event in ordered:
        current = views.get(event.baseline_id)
        if current is None:
            current = BaselineView(
                baseline_id=event.baseline_id,
                publication_id=event.publication_id,
                status=BaselineStatus.PROPOSED,
                proposed_type=None,
                effective_type=None,
                label=None,
                effective_from=None,
                superseded=event.baseline_id in superseded,
                proposer_bucket=None,
            )
        views[event.baseline_id] = _folded(current, event, eligible)
    return views


def _folded(view: BaselineView, event: BaselineEvent, eligible: frozenset[str]) -> BaselineView:
    action = event.action
    if action is BaselineAction.PROPOSE:
        return replace(view, proposed_type=event.type, proposer_bucket=event.writer_bucket)
    if action is BaselineAction.APPROVE:
        status = (
            BaselineStatus.APPROVED
            if view.publication_id in eligible
            else BaselineStatus.INELIGIBLE
        )
        return replace(
            view,
            status=status,
            effective_type=event.type,
            label=event.label,
            effective_from=event.effective_from,
        )
    if action is BaselineAction.REJECT:
        return replace(view, status=BaselineStatus.REJECTED)
    if action is BaselineAction.WITHDRAW:
        return replace(view, status=BaselineStatus.WITHDRAWN)
    return replace(view, status=BaselineStatus.REVOKED)


def governing_baseline(
    events: Iterable[GoverningEvent], *, as_of: datetime | None = None
) -> str | None:
    """The governing Baseline now, or as recorded at `as_of` (ties resolve by `seq`)."""
    chain = sorted(events, key=lambda event: event.seq)
    if [event.seq for event in chain] != list(range(1, len(chain) + 1)):
        raise ValueError("a governing chain is seq 1, 2, ... without gaps")
    if as_of is not None:
        chain = [event for event in chain if event.recorded_at <= as_of]
    return chain[-1].baseline_id if chain else None


def next_baseline_label(events: Iterable[BaselineEvent]) -> str:
    """`BL-<n>`: `n` approvals already recorded in the Project (revoked ones included)."""
    approvals = sum(1 for event in events if event.action is BaselineAction.APPROVE)
    return f"BL-{approvals}"


# --- transitions (section 12.3, 12.4) -------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ProposeRequest:
    publication_id: str
    type: BaselineType
    writer_bucket: str


@dataclass(frozen=True, slots=True)
class ApproveRequest:
    """Exactly one of `baseline_id` / `publication_id`; operator only (caller-enforced)."""

    type: BaselineType
    effective_from: date
    baseline_id: str | None = None
    publication_id: str | None = None
    supersedes_baseline_id: str | None = None
    #: The import-time approval, written before the parse decides eligibility.
    at_import: bool = False


@dataclass(frozen=True, slots=True)
class RejectRequest:
    baseline_id: str


@dataclass(frozen=True, slots=True)
class WithdrawRequest:
    baseline_id: str
    #: The caller's writer bucket; `None` for the attested operator.
    writer_bucket: str | None


@dataclass(frozen=True, slots=True)
class RevokeRequest:
    baseline_id: str


@dataclass(frozen=True, slots=True)
class SetGoverningRequest:
    baseline_id: str
    expected_governing_baseline_id: str | None


BaselineRequest = (
    ProposeRequest
    | ApproveRequest
    | RejectRequest
    | WithdrawRequest
    | RevokeRequest
    | SetGoverningRequest
)


@dataclass(frozen=True, slots=True)
class BaselinePlan:
    """What the writer appends: `baseline_id` `None` = a new Baseline row (caller mints it)."""

    action: BaselineAction | None
    baseline_id: str | None
    publication_id: str | None = None
    label: str | None = None
    proposal_ordinal: int | None = None
    #: True for `set_governing`, which appends a governing event instead.
    governing: bool = False


def _pending_on(views: Iterable[BaselineView], publication_id: str) -> BaselineView | None:
    return next(
        (view for view in views if view.pending and view.publication_id == publication_id),
        None,
    )


def _approved_once(events: Sequence[BaselineEvent], publication_id: str) -> bool:
    return any(
        event.action is BaselineAction.APPROVE and event.publication_id == publication_id
        for event in events
    )


def decide_baseline_write(
    events: Sequence[BaselineEvent],
    governing_events: Sequence[GoverningEvent],
    request: BaselineRequest,
    *,
    eligible_publication_ids: Iterable[str],
) -> BaselinePlan | BaselineRefusal:
    """Section 12 transition rules over the Project's chains, as read under the lock."""
    eligible = frozenset(eligible_publication_ids)
    views = baseline_status(events, eligible_publication_ids=eligible)
    governing = governing_baseline(governing_events)
    if isinstance(request, ProposeRequest):
        return _propose(events, views, request, eligible)
    if isinstance(request, ApproveRequest):
        return _approve(events, views, request, eligible)
    if isinstance(request, SetGoverningRequest):
        target = views.get(request.baseline_id)
        if target is None or not target.effective:
            return BaselineRefusal.CONFLICT_BASELINE_ID
        if request.expected_governing_baseline_id != governing:
            return BaselineRefusal.CONFLICT_GOVERNING
        return BaselinePlan(None, request.baseline_id, governing=True)
    target = views.get(request.baseline_id)
    if target is None:
        return BaselineRefusal.CONFLICT_BASELINE_ID
    if isinstance(request, RevokeRequest):
        if target.status not in (BaselineStatus.APPROVED, BaselineStatus.INELIGIBLE):
            return BaselineRefusal.CONFLICT_BASELINE_ID
        if governing == target.baseline_id:
            return BaselineRefusal.CONFLICT_GOVERNING
        return BaselinePlan(BaselineAction.REVOKE, target.baseline_id, target.publication_id)
    if not target.pending:
        return BaselineRefusal.CONFLICT_BASELINE_ID
    if isinstance(request, WithdrawRequest):
        if request.writer_bucket is not None and request.writer_bucket != target.proposer_bucket:
            return BaselineRefusal.DENIED
        return BaselinePlan(BaselineAction.WITHDRAW, target.baseline_id, target.publication_id)
    return BaselinePlan(BaselineAction.REJECT, target.baseline_id, target.publication_id)


def _propose(
    events: Sequence[BaselineEvent],
    views: dict[str, BaselineView],
    request: ProposeRequest,
    eligible: frozenset[str],
) -> BaselinePlan | BaselineRefusal:
    publication = request.publication_id
    if publication not in eligible:
        return BaselineRefusal.CONFLICT_STATUS
    if _approved_once(events, publication) or _pending_on(views.values(), publication):
        return BaselineRefusal.CONFLICT_BASELINE_ID
    pending = [view for view in views.values() if view.pending]
    if len(pending) >= MAX_PENDING_PER_PROJECT or (
        sum(1 for view in pending if view.proposer_bucket == request.writer_bucket)
        >= MAX_PENDING_PER_BUCKET
    ):
        return BaselineRefusal.RATE_LIMITED_BASELINE_ID
    decided = {
        event.baseline_id
        for event in events
        if event.action in _DECISIONS and event.publication_id == publication
    }
    ordinal = sum(
        1
        for event in events
        if event.action is BaselineAction.PROPOSE
        and event.publication_id == publication
        and event.baseline_id in decided
    )
    return BaselinePlan(BaselineAction.PROPOSE, None, publication, proposal_ordinal=ordinal)


def _approve(
    events: Sequence[BaselineEvent],
    views: dict[str, BaselineView],
    request: ApproveRequest,
    eligible: frozenset[str],
) -> BaselinePlan | BaselineRefusal:
    if (request.baseline_id is None) == (request.publication_id is None):
        raise ValueError("an approval names exactly one of baseline_id / publication_id")
    if request.baseline_id is not None:
        target = views.get(request.baseline_id)
        if target is None or not target.pending:
            return BaselineRefusal.CONFLICT_BASELINE_ID
        baseline_id: str | None = target.baseline_id
        publication = target.publication_id
    else:
        publication = request.publication_id or ""
        adopted = _pending_on(views.values(), publication)
        baseline_id = None if adopted is None else adopted.baseline_id
    if _approved_once(events, publication):
        return BaselineRefusal.CONFLICT_BASELINE_ID
    if not request.at_import and publication not in eligible:
        return BaselineRefusal.CONFLICT_STATUS
    superseded = request.supersedes_baseline_id
    if superseded is not None:
        named = views.get(superseded)
        if named is None or named.status is not BaselineStatus.APPROVED:
            return BaselineRefusal.CONFLICT_BASELINE_ID
    return BaselinePlan(
        BaselineAction.APPROVE, baseline_id, publication, label=next_baseline_label(events)
    )


def compare_refusal(
    baseline: BaselineView | None,
    *,
    baseline_series_id: str,
    to_series_id: str,
    to_eligible: bool,
) -> BaselineRefusal | None:
    """`schedule_baselines.compare` pairs an effective Baseline within its own Series only."""
    if baseline is None or not baseline.effective:
        return BaselineRefusal.CONFLICT_BASELINE_ID
    if to_series_id != baseline_series_id or not to_eligible:
        return BaselineRefusal.INVALID_TO_PUBLICATION_ID
    return None
