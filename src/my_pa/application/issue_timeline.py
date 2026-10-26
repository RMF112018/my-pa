"""`issues.timeline`: one Issue's ordered lineage and native events (S3 contract section 7.3).

**Two planes.** The *lineage plane* is read as of the request's cut (section
3.4): the Issue's revisions, its Project link events, the revisions of its
memberships and of every semantic link **in the Issue's context** (section
3.2's one definition, at the cut: `record_lineage.links_in_context_at`), at
`W(T_v)`; its handoff events at their current effective time and their
corrections, known at `W(T_k)` and in effect at `T_v`. The *native plane* --
the Record Events of the Issue's members (a note version by its Meeting, a
Capture version by its Capture) -- is shown **only when `known_at` is
omitted** (section 12, D-04): nothing native has a commit-ordered knowledge
time, so an as-of timeline omits it and says `partial_native_history`. Native
entries are bounded by the *requested* `valid_at` (never clamped to `T_k`,
R3-F02) and by the watermark `r` frozen on the first page.

**Native disclosure (R3-F03, R3-F04).** The native read is the feed module's
own `issue_member_events`, under the Record Event reader's one predicate (never
copied); for a remote reader its families are the member families the reader
can see and every withholding clause applies. `r` is the newest event under
that predicate among the Issue's covered member records -- the same rows the
page reads, in the same statement -- so it names only an event this timeline
itself could show this reader. Later pages resolve it after the same
visibility check (record_events U-002 step 3).

**No field values.** A native entry carries the event's own columns, never a
former or current field value (`historical_fields_partial: true`), except a
Constraint event whose `record_version` names a stored revision snapshot: it
carries that snapshot's `lifecycle_state` and ball-in-court, rendered exactly
as `constraints.read` renders `bic` (`historical_fields_partial: false`). A
Project link entry never names its Project.

**Order and paging.** `(at, plane_rank, kind_rank, entry_id)`, keyset-paged
under the section 5 cursor with the section 7.2 step 7 checks: shape, binding
(`conflict`), cuts (`invalid_request`), scope (`scope_changed_restart_required`),
then the position -- a well-formed position that is not an entry of the
recomputed timeline answers the restart, as an unresolvable watermark does.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from my_pa.application.constraints import _party_views
from my_pa.application.errors import (
    ConflictError,
    InvalidRequestError,
    NotFoundError,
    SafeDetail,
)
from my_pa.application.lineage_visibility import LineageVisibility
from my_pa.application.record_lineage import (
    LINEAGE_STATEMENT_TIMEOUT_MS,
    issue_inside_set_at,
    links_in_context_at,
)
from my_pa.contracts.ports import (
    ConstraintRevisionSnapshot,
    HandoffCorrectionRecord,
    HandoffRecord,
    IssueTimelineRepository,
    LineageFactCut,
    LinkHeadRecord,
    RecordEventReader,
    TimelineNativeEvent,
    UnitOfWork,
)
from my_pa.contracts.v1.issue_timeline import (
    TIMELINE_ENTRY_ID_KINDS,
    TIMELINE_KIND_RANKS,
    TIMELINE_PLANE_RANKS,
    IssueTimelineView,
    TimelineEntryView,
    TimelineNativeView,
)
from my_pa.contracts.v1.issues import HandoffHolderView
from my_pa.contracts.v1.record_lineage import RecordRefView
from my_pa.domain.common.identifiers import validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.identity.operation import Capability
from my_pa.domain.lineage.asof import CutAfterNowError, completeness, knowledge_cut
from my_pa.domain.lineage.cursor import (
    CursorMalformedError,
    LineageCursor,
    cursor_binding,
    decode_cursor,
    encode_cursor,
    instant_token,
    parse_instant_token,
    scope_digest,
)
from my_pa.domain.lineage.handoff import HandoffCorrectionFact, chain_state
from my_pa.domain.lineage.model import RecordRef
from my_pa.domain.lineage.vocabulary import (
    AcceptanceBasis,
    HandoffCorrectionAction,
    HandoffHolderKind,
    LineageCompleteness,
    RecordFamily,
    RecordLinkKind,
    TimelineEntryKind,
)
from my_pa.domain.project_controls.party import PartyKind
from my_pa.domain.record_events import RecordEventFamily

__all__ = [
    "DEFAULT_TIMELINE_PAGE_SIZE",
    "MAX_TIMELINE_MEMBERS",
    "IssueTimelineRequest",
    "NativeVisibility",
    "read_issue_timeline",
    "timeline_request_document",
]

#: Section 7.3: a page holds 25 entries when the request names no page size.
DEFAULT_TIMELINE_PAGE_SIZE: Final = 25
#: Section 7.3: the native plane covers at most the first 250 members by
#: `(family, record_id)` in code-point order; beyond that `truncated_budget`.
MAX_TIMELINE_MEMBERS: Final = 250

_ISSUES_TIMELINE: Final = Capability.ISSUES_TIMELINE.value
#: Section 7.3: the Record Event family each lineage member family's events are under.
_MEMBER_EVENT_FAMILIES: Final[Mapping[RecordFamily, RecordEventFamily]] = {
    RecordFamily.TASK: RecordEventFamily.TASK,
    RecordFamily.COMMITMENT: RecordEventFamily.COMMITMENT,
    RecordFamily.CONSTRAINT: RecordEventFamily.CONSTRAINT,
    RecordFamily.MEETING: RecordEventFamily.MEETING,
    RecordFamily.MEETING_NOTE_VERSION: RecordEventFamily.MEETING,
    RecordFamily.CAPTURE_VERSION: RecordEventFamily.CAPTURE,
}
#: The member families read by their root (a note by its Meeting, a version by its Capture).
_VERSION_FAMILIES: Final = frozenset(
    {RecordFamily.MEETING_NOTE_VERSION, RecordFamily.CAPTURE_VERSION}
)
_BIC_ROLE: Final = "bic"
#: The page size of one `known_events` read while the timeline gathers every handoff.
_HANDOFF_BATCH: Final = 100

type _Key = tuple[str, int, int, str]


@dataclass(frozen=True, slots=True)
class IssueTimelineRequest:
    """The parsed `issues.timeline` request (section 7.3); `page_size` is effective."""

    issue_id: str
    known_at: datetime | None
    valid_at: datetime | None
    page_size: int
    cursor: str | None


@dataclass(frozen=True, slots=True)
class NativeVisibility:
    """The Record Event visibility of this reader, re-derived by the service each call.

    `families` is the feed's visible family set for this caller (composition
    and, remotely, grants); `include_restricted_memory` is false for a remote
    caller, which then gets every withholding clause.
    """

    families: frozenset[RecordEventFamily]
    include_restricted_memory: bool


@dataclass(frozen=True, slots=True)
class _Cuts:
    """`T_k`, the reported `valid_at` and `T_v` of one answer."""

    known_at: datetime | None
    valid_at: datetime | None
    lineage_valid_at: datetime | None


def timeline_request_document(request: IssueTimelineRequest) -> dict[str, object]:
    """The parsed request without its cursor, optional fields `null` (section 5's `b`)."""
    return {
        "issue_id": request.issue_id,
        "known_at": instant_token(request.known_at),
        "valid_at": instant_token(request.valid_at),
        "page_size": request.page_size,
    }


# --- the position (section 5: `[at, plane_rank, kind_rank, entry_id]`) -------------

_KINDS_BY_RANK: Final = {rank: kind for kind, rank in TIMELINE_KIND_RANKS.items()}


def _timeline_position(value: object) -> bool:
    """Whether `p` has the timeline's shape: an instant, two ranks and a row identifier."""
    if not isinstance(value, list) or len(value) != 4:
        return False
    at, plane, kind_rank, entry_id = value
    if type(plane) is not int or type(kind_rank) is not int or not isinstance(entry_id, str):
        return False
    kind = _KINDS_BY_RANK.get(kind_rank)
    if kind is None or plane != (1 if kind is TimelineEntryKind.NATIVE_EVENT else 0):
        return False
    try:
        parse_instant_token(at)
        validate_identifier(entry_id, TIMELINE_ENTRY_ID_KINDS[kind])
    except (CursorMalformedError, ValueError):
        return False
    return True


def _key(entry: TimelineEntryView) -> _Key:
    token = instant_token(entry.at)
    if token is None:  # pragma: no cover - `at` is required
        raise ValueError("a timeline entry has an instant")
    return (
        token,
        TIMELINE_PLANE_RANKS[entry.plane],
        TIMELINE_KIND_RANKS[entry.kind],
        entry.entry_id,
    )


# --- entries ----------------------------------------------------------------------


def _ref_view(ref: RecordRef) -> RecordRefView:
    return RecordRefView(family=ref.family, record_id=ref.record_id)


def _holder(kind: str, entity_id: str | None) -> HandoffHolderView:
    return HandoffHolderView(kind=HandoffHolderKind(kind), entity_id=entity_id)


def _lineage_entry(
    kind: TimelineEntryKind,
    entry_id: str,
    *,
    at: datetime,
    recorded_at: datetime,
    subject: RecordRef | None,
    action: str,
    **keys: Any,  # noqa: ANN401 - the kind's own keys, validated by the view
) -> TimelineEntryView:
    return TimelineEntryView(
        entry_id=entry_id,
        kind=kind,
        plane="lineage",
        at=at,
        recorded_at=recorded_at,
        subject=None if subject is None else _ref_view(subject),
        action=action,
        historical_fields_partial=False,
        **keys,
    )


def _link_entries(
    heads: Sequence[LinkHeadRecord],
    revisions: Mapping[str, Sequence[Any]],
) -> list[TimelineEntryView]:
    entries: list[TimelineEntryView] = []
    for head in heads:
        link = head.link
        membership = link.kind is RecordLinkKind.ISSUE_MEMBERSHIP
        kind = TimelineEntryKind.MEMBERSHIP if membership else TimelineEntryKind.ASSOCIATION
        for revision in revisions.get(link.link_id, ()):
            entries.append(
                _lineage_entry(
                    kind,
                    revision.revision_id,
                    at=revision.recorded_at,
                    recorded_at=revision.recorded_at,
                    subject=link.to_ref if membership else None,
                    action=revision.action.value,
                    link_id=link.link_id,
                    revision_no=revision.revision_no,
                    relation_type=link.relation_type,
                    member_role=link.member_role,
                    lifecycle_state=revision.lifecycle_state,
                    from_ref=_ref_view(link.from_ref),
                    to_ref=_ref_view(link.to_ref),
                    acceptance_basis=revision.acceptance_basis,
                    user_directed_claim=revision.user_directed_claim,
                    asserting_client_id=revision.asserting_client_id,
                )
            )
    return entries


def _facts(corrections: Sequence[HandoffCorrectionRecord]) -> tuple[HandoffCorrectionFact, ...]:
    return tuple(
        HandoffCorrectionFact(
            correction_no=correction.correction_no,
            action=HandoffCorrectionAction(correction.action),
            corrected_effective_at=correction.corrected_effective_at,
        )
        for correction in corrections
    )


def _known_handoffs(
    uow: UnitOfWork, principal_id: str, issue_id: str, cut: LineageFactCut
) -> tuple[HandoffRecord, ...]:
    """Every handoff event of the Issue known at `cut`, gathered in `known_events` pages."""
    found: list[HandoffRecord] = []
    after: str | None = None
    while True:
        page = uow.issue_handoffs.known_events(
            principal_id,
            issue_id,
            commitment_id=None,
            page_size=_HANDOFF_BATCH,
            after=after,
            watermark=cut.watermark,
            at=cut.at,
        )
        found.extend(page.handoffs)
        if not page.has_more or not page.handoffs:
            return tuple(found)
        after = page.handoffs[-1].handoff_id


def _handoff_entries(
    uow: UnitOfWork,
    principal_id: str,
    issue_id: str,
    *,
    known: LineageFactCut,
    valid_at: datetime,
    visibility: LineageVisibility,
) -> tuple[list[TimelineEntryView], bool]:
    """Handoffs at their current effective time, and corrections, in effect at `T_v`.

    Both are known at `W(T_k)` (section 3.4); an entry about a Commitment the
    reader may not see is withheld.
    """
    events = _known_handoffs(uow, principal_id, issue_id, known)
    corrections = uow.issue_handoffs.corrections_of(
        principal_id,
        [event.handoff_id for event in events],
        watermark=known.watermark,
        at=known.at,
    )
    entries: list[TimelineEntryView] = []
    withheld = False
    for event in events:
        commitment = RecordRef(family=RecordFamily.COMMITMENT, record_id=event.commitment_id)
        known_corrections = corrections.get(event.handoff_id, ())
        folded = chain_state(event.sequence_no, event.effective_at, _facts(known_corrections))
        in_effect = folded.current_effective_at <= valid_at
        shown = [
            correction for correction in known_corrections if correction.recorded_at <= valid_at
        ]
        if not visibility.sees(commitment):
            withheld = withheld or in_effect or bool(shown)
            continue
        if in_effect:
            entries.append(
                _lineage_entry(
                    TimelineEntryKind.HANDOFF,
                    event.handoff_id,
                    at=folded.current_effective_at,
                    recorded_at=event.recorded_at,
                    subject=commitment,
                    action="recorded",
                    handoff_id=event.handoff_id,
                    commitment_id=event.commitment_id,
                    sequence_no=event.sequence_no,
                    from_holder=_holder(event.from_holder_kind, event.from_entity_id),
                    to_holder=_holder(event.to_holder_kind, event.to_entity_id),
                    voided=folded.voided,
                    acceptance_basis=AcceptanceBasis(event.acceptance_basis),
                    user_directed_claim=event.user_directed_claim,
                    asserting_client_id=event.asserting_client_id,
                )
            )
        for correction in shown:
            entries.append(
                _lineage_entry(
                    TimelineEntryKind.HANDOFF_CORRECTION,
                    correction.correction_id,
                    at=correction.recorded_at,
                    recorded_at=correction.recorded_at,
                    subject=commitment,
                    action=correction.action,
                    handoff_id=event.handoff_id,
                    commitment_id=event.commitment_id,
                    correction_id=correction.correction_id,
                    correction_action=HandoffCorrectionAction(correction.action),
                    corrected_effective_at=correction.corrected_effective_at,
                    acceptance_basis=AcceptanceBasis(correction.acceptance_basis),
                    user_directed_claim=correction.user_directed_claim,
                    asserting_client_id=correction.asserting_client_id,
                )
            )
    return entries, withheld


# --- the native plane ------------------------------------------------------------


def _ball_in_court(
    snapshot: ConstraintRevisionSnapshot, labels: Mapping[str, str]
) -> list[dict[str, object]]:
    """The snapshot's `bic`, exactly as `constraints.read` renders its `bic` parties."""
    return [
        {
            "kind": view.kind.value,
            "party_ref_id": view.party_ref_id,
            "display_label": view.display_label,
            "entity_id": view.entity_id,
        }
        for view in _party_views(snapshot.bic, _BIC_ROLE, labels)
    ]


def _event_keys(
    uow: UnitOfWork, principal_id: str, members: Sequence[RecordRef]
) -> dict[tuple[RecordEventFamily, str], RecordRef]:
    """Each covered member's Record Event key, mapped back to the member it is read for.

    A note version is read by its Meeting and a Capture version by its
    Capture; when two members share one key, the first in member order is the
    subject. A member that no longer resolves contributes nothing.
    """
    resolved = uow.record_lineage.resolve_records(
        principal_id,
        [member for member in members if member.family in _VERSION_FAMILIES],
    )
    keys: dict[tuple[RecordEventFamily, str], RecordRef] = {}
    for member in members:
        family = _MEMBER_EVENT_FAMILIES.get(member.family)
        if family is None:
            continue
        record_id: str | None = member.record_id
        if member.family in _VERSION_FAMILIES:
            record = resolved.get(member)
            record_id = None if record is None else record.parent_root_id
        if record_id is not None:
            keys.setdefault((family, record_id), member)
    return keys


def _native_entries(
    uow: UnitOfWork,
    principal_id: str,
    events: Sequence[TimelineNativeEvent],
    subjects: Mapping[tuple[RecordEventFamily, str], RecordRef],
) -> list[TimelineEntryView]:
    timeline: IssueTimelineRepository = uow.issue_timeline
    snapshots = timeline.constraint_snapshots(
        principal_id,
        [
            (event.record_id, event.record_version)
            for event in events
            if event.record_family is RecordEventFamily.CONSTRAINT
        ],
    )
    labels = timeline.entity_labels(
        principal_id,
        {
            party.entity_id
            for snapshot in snapshots.values()
            for party in snapshot.bic
            if party.party_kind is PartyKind.ENTITY
            and party.entity_id is not None
            and not party.display_label
        },
    )
    entries: list[TimelineEntryView] = []
    for event in events:
        snapshot = (
            snapshots.get((event.record_id, event.record_version))
            if event.record_family is RecordEventFamily.CONSTRAINT
            else None
        )
        recorded = (
            None
            if snapshot is None
            else {
                "lifecycle_state": snapshot.lifecycle_state,
                "ball_in_court": _ball_in_court(snapshot, labels),
            }
        )
        entries.append(
            TimelineEntryView(
                entry_id=event.event_id,
                kind=TimelineEntryKind.NATIVE_EVENT,
                plane="native",
                at=event.occurred_at,
                recorded_at=event.recorded_at,
                subject=_ref_view(subjects[(event.record_family, event.record_id)]),
                action=event.event_kind.value,
                historical_fields_partial=recorded is None,
                native=TimelineNativeView(
                    record_family=event.record_family,
                    record_id=event.record_id,
                    event_kind=event.event_kind,
                    record_version=event.record_version,
                    changed_fields=event.changed_fields,
                    source_capability=event.source_capability,
                ),
                recorded_fields=recorded,
            )
        )
    return entries


class _WatermarkVanishedError(Exception):
    """The frozen watermark no longer resolves for this reader (answer the restart)."""


def _watermark_position(
    uow: UnitOfWork,
    principal_id: str,
    watermark: str | None,
    native: NativeVisibility,
    families: frozenset[RecordEventFamily],
) -> int:
    """A later page's sequence bound: `r`'s position, after the page's own visibility check."""
    if watermark is None:
        return 0
    reader: RecordEventReader = uow.record_event_reader
    visible = reader.visible_event_ids(
        principal_id=principal_id,
        event_ids=frozenset({watermark}),
        families=families,
        include_restricted_memory=native.include_restricted_memory,
    )
    position = (
        reader.resolve_position(principal_id=principal_id, event_id=watermark)
        if watermark in visible
        else None
    )
    if position is None:
        raise _WatermarkVanishedError
    return position


# --- the read ---------------------------------------------------------------------


def _restart(request: IssueTimelineRequest, cuts: _Cuts) -> IssueTimelineView:
    """Section 7.2 step 7 for the timeline: `scope_changed_restart_required`, no entry."""
    code = LineageCompleteness.SCOPE_CHANGED_RESTART_REQUIRED
    return IssueTimelineView(
        issue_id=request.issue_id,
        known_at=cuts.known_at,
        valid_at=cuts.valid_at,
        lineage_valid_at=cuts.lineage_valid_at,
        entries=(),
        complete_state=code,
        qualifiers=(code,),
        next_cursor=None,
    )


def _checked_cursor(
    request: IssueTimelineRequest, principal_id: str, *, horizon: datetime | None
) -> LineageCursor:
    """Section 7.2 step 7, the checks before the scope: shape, binding, cuts."""
    try:
        cursor = decode_cursor(request.cursor, _timeline_position)
    except CursorMalformedError as error:
        raise InvalidRequestError(SafeDetail.CURSOR) from error
    if cursor.native_cut_at is not None:
        # `issues.timeline` has no note-version cut (section 5, R3-F26).
        raise InvalidRequestError(SafeDetail.CURSOR)
    expected = cursor_binding(
        capability=_ISSUES_TIMELINE,
        principal_id=principal_id,
        request=timeline_request_document(request),
        known_at=cursor.known_at,
        lineage_valid_at=cursor.lineage_valid_at,
        native_cut_at=None,
        record_event_watermark=cursor.record_event_watermark,
    )
    if cursor.binding != expected:
        raise ConflictError(SafeDetail.CURSOR)
    known, valid = cursor.known_at, cursor.lineage_valid_at
    if known is None or valid is None or horizon is None or known > horizon or valid > known:
        raise InvalidRequestError(SafeDetail.CURSOR)
    if (request.known_at is not None and known > ensure_utc(request.known_at)) or (
        request.valid_at is not None and valid > ensure_utc(request.valid_at)
    ):
        raise InvalidRequestError(SafeDetail.CURSOR)
    if request.known_at is not None and cursor.record_event_watermark is not None:
        # An as-of timeline reads no native plane, so it freezes no watermark.
        raise InvalidRequestError(SafeDetail.CURSOR)
    return cursor


def read_issue_timeline(
    uow: UnitOfWork,
    principal_id: str,
    request: IssueTimelineRequest,
    *,
    now: datetime,
    visibility: LineageVisibility,
    native: NativeVisibility,
) -> IssueTimelineView:
    """`issues.timeline` (S3 section 7.3): one page, recomputed under the frozen cuts.

    An absent, foreign or context Situation, an Issue no revision of which is
    known at `T_k`, and (remote) an Issue the reader may not see are
    `not_found` / `issue_id`, alike.
    """
    lineage = uow.record_lineage
    timeline: IssueTimelineRepository = uow.issue_timeline
    lineage.bound_read_statements(LINEAGE_STATEMENT_TIMEOUT_MS)
    at = ensure_utc(now)
    issue = RecordRef(family=RecordFamily.SITUATION, record_id=request.issue_id)
    horizon = lineage.commit_horizon(principal_id)
    scope = scope_digest(visibility.grant_digest)
    cursor: LineageCursor | None = None
    if request.cursor is not None:
        cursor = _checked_cursor(request, principal_id, horizon=horizon)
        cuts = _Cuts(
            known_at=cursor.known_at,
            valid_at=request.valid_at if request.valid_at is not None else cursor.known_at,
            lineage_valid_at=cursor.lineage_valid_at,
        )
        if cursor.scope != scope:
            return _restart(request, cuts)
    else:
        try:
            cut = knowledge_cut(
                known_at=request.known_at, valid_at=request.valid_at, now=at, horizon=horizon
            )
        except CutAfterNowError as error:
            detail = SafeDetail.KNOWN_AT if error.field == "known_at" else SafeDetail.VALID_AT
            raise InvalidRequestError(detail) from error
        cuts = _Cuts(
            known_at=cut.known_at, valid_at=cut.valid_at, lineage_valid_at=cut.lineage_valid_at
        )
    # The cursor's checks come first (section 7.2 step 7, as `records.lineage`):
    # they compare the request with itself and disclose nothing about the Issue.
    if not visibility.sees(issue) or uow.issues.read_issue(principal_id, request.issue_id) is None:
        raise NotFoundError(SafeDetail.ISSUE_ID)
    t_k, t_v = cuts.known_at, cuts.lineage_valid_at
    if t_k is None or t_v is None:
        raise NotFoundError(SafeDetail.ISSUE_ID)
    known = LineageFactCut(watermark=lineage.commit_watermark(principal_id, t_k), at=t_k)
    valid = (
        known
        if t_v == t_k
        else LineageFactCut(watermark=lineage.commit_watermark(principal_id, t_v), at=t_v)
    )
    revisions = timeline.issue_revisions(principal_id, request.issue_id, valid)
    if not revisions and (
        valid is known or not timeline.issue_revisions(principal_id, request.issue_id, known)
    ):
        raise NotFoundError(SafeDetail.ISSUE_ID)

    codes: set[LineageCompleteness] = set()
    entries: list[TimelineEntryView] = [
        _lineage_entry(
            TimelineEntryKind.ISSUE_REVISION,
            revision.revision_id,
            at=revision.recorded_at,
            recorded_at=revision.recorded_at,
            subject=issue,
            action=revision.action.value,
            issue_version=revision.version,
            state=revision.state.value,
            title=revision.title,
            closed_at=revision.closed_at,
            outcome=revision.outcome,
        )
        for revision in revisions
    ]
    entries.extend(
        _lineage_entry(
            TimelineEntryKind.PROJECT_LINK,
            event.membership_event_id,
            at=event.recorded_at,
            recorded_at=event.recorded_at,
            subject=None,
            action=event.action.value,
            project_id=event.project_id,
            membership_revision_no=event.revision_no,
            link_state=event.state,
            acceptance_basis=AcceptanceBasis(event.acceptance_basis),
            user_directed_claim=event.user_directed_claim,
            asserting_client_id=event.asserting_client_id,
        )
        for event in timeline.project_link_events(principal_id, request.issue_id, valid)
    )

    # Memberships and associations: section 3.2's one predicate, at the read's cut.
    inside, members = issue_inside_set_at(lineage, principal_id, request.issue_id, valid)
    in_context = links_in_context_at(lineage, principal_id, request.issue_id, valid, inside=inside)
    shown_links: list[LinkHeadRecord] = []
    for head in in_context:
        link = head.link
        endpoints = (
            (link.to_ref,)
            if link.kind is RecordLinkKind.ISSUE_MEMBERSHIP
            else (link.from_ref, link.to_ref)
        )
        if all(visibility.sees(ref) for ref in endpoints):
            shown_links.append(head)
        else:
            codes.add(LineageCompleteness.RESTRICTED_EVIDENCE)
    entries.extend(
        _link_entries(
            shown_links,
            timeline.link_revisions(
                principal_id, [head.link.link_id for head in shown_links], valid
            ),
        )
    )

    handoffs, withheld = _handoff_entries(
        uow, principal_id, request.issue_id, known=known, valid_at=t_v, visibility=visibility
    )
    entries.extend(handoffs)
    if withheld:
        codes.add(LineageCompleteness.RESTRICTED_EVIDENCE)

    # The native plane: only for a current timeline (section 12, D-04).
    visible_members = sorted(
        {head.link.to_ref for head in members if visibility.sees(head.link.to_ref)},
        key=lambda ref: (ref.family.value, ref.record_id),
    )
    if len(visible_members) < len({head.link.to_ref for head in members}):
        codes.add(LineageCompleteness.RESTRICTED_EVIDENCE)
    watermark: str | None = None
    if request.known_at is not None:
        if any(member.family in _MEMBER_EVENT_FAMILIES for member in visible_members):
            codes.add(LineageCompleteness.PARTIAL_NATIVE_HISTORY)
    else:
        if len(visible_members) > MAX_TIMELINE_MEMBERS:
            codes.add(LineageCompleteness.TRUNCATED_BUDGET)
        subjects = _event_keys(uow, principal_id, visible_members[:MAX_TIMELINE_MEMBERS])
        families = native.families & {family for family, _ in subjects}
        sequence_at_most: int | None = None
        if cursor is not None:
            try:
                sequence_at_most = _watermark_position(
                    uow, principal_id, cursor.record_event_watermark, native, families
                )
            except _WatermarkVanishedError:
                return _restart(request, cuts)
        events = timeline.native_events(
            principal_id,
            subjects,
            families=families,
            include_restricted_memory=native.include_restricted_memory,
            occurred_at_most=request.valid_at,
            sequence_at_most=sequence_at_most,
        )
        # `r`: the newest event among exactly these rows, read in this statement.
        watermark = (
            cursor.record_event_watermark
            if cursor is not None
            else (events[-1].event_id if events else None)
        )
        entries.extend(_native_entries(uow, principal_id, events, subjects))

    ordered = sorted(entries, key=_key)
    keys = [_key(entry) for entry in ordered]
    start = 0
    if cursor is not None:
        position = tuple(cursor.position) if isinstance(cursor.position, list) else ()
        if position not in keys:
            # R3-F14, R3-F23: a well-formed position that is not an entry of the
            # recomputed timeline -- vanished, hidden or edited -- answers alike.
            return _restart(request, cuts)
        start = keys.index(position) + 1
    end = min(start + request.page_size, len(ordered))
    next_cursor: str | None = None
    if end < len(ordered) and end > start:
        next_cursor = encode_cursor(
            LineageCursor(
                binding=cursor_binding(
                    capability=_ISSUES_TIMELINE,
                    principal_id=principal_id,
                    request=timeline_request_document(request),
                    known_at=t_k,
                    lineage_valid_at=t_v,
                    native_cut_at=None,
                    record_event_watermark=watermark,
                ),
                scope=scope,
                known_at=t_k,
                lineage_valid_at=t_v,
                native_cut_at=None,
                record_event_watermark=watermark,
                position=list(keys[end - 1]),
            )
        )
    state, qualifiers = completeness(codes)
    return IssueTimelineView(
        issue_id=request.issue_id,
        known_at=t_k,
        valid_at=cuts.valid_at,
        lineage_valid_at=t_v,
        entries=tuple(ordered[start:end]),
        complete_state=state,
        qualifiers=qualifiers,
        next_cursor=next_cursor,
    )
