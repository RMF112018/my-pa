"""`meetings.context.read`: the communications context of a batch of Meetings (WP5-S3).

The service half of the WP5 design (sections 3.1-3.11; Manager rulings D3-D8,
D9, D11-D14, A-3). Its MCP wiring (the capability, the policy, the
`MY_PA_COMMUNICATIONS_ENABLED` gate, ChatLLM) is S5. This module answers the
Meeting core, the provider binding state, the communications section and the
`pulse` section (S4). It never reads a project-report table itself: the
`pulse` section is composed from the batched project-report facade
(`ProjectReportReads.context_summaries`, ruling D7), which reads every version
through `project_report_current_derivations`.

**Set-based.** A batch costs 14 statements plus one per communications source,
constant in the number of Meetings (1 to `MAX_CONTEXT_MEETINGS`): the seven of
`read_context_inputs`, the two version reads, the coverage reads (one plus one
per source), the self addresses, the C9 bridge, the one candidate statement
for every Meeting, and the lanes of the returned messages. The last two are
skipped when nothing is asked or nothing is returned. A constant count is not
a constant cost: the candidate statement's work grows with the Meetings and
their windows (WP5-R1 F-1, F-9). With the project-report reads on and a
Meeting linked to a Project, the `pulse` section adds the `rfi` identifiers of
the linked Meetings' returned messages (one statement, skipped when none
returned any) and the facade's reads: 4 for the batch (bindings; versions,
itself 1 to 3 statements; cross-checks; RFI candidates -- the last two skipped
when there is nothing to ask) plus 2 per latest classified summary version
of the batch's Projects (its lines, then their values; more only past 1,000
lines) -- 6 + 2L statements. L grows with the distinct Projects, never with
the Meetings.

**The `pulse` section (WP5 design 3.5; rulings D7, D8, D12; PULSE-AC-16).**

* `MY_PA_PROJECT_REPORTS_ENABLED` off: `unavailable` / `reads_disabled` and
  nothing is read; a Meeting without a Project: `not_linked`; a Project whose
  reports are unavailable: `unavailable` with the facade's closed reason.
* `available`: the latest-version record counts of observations,
  coordination issues and RFIs in that family order (the repository's series
  order within a family), at most `MAX_PULSE_COUNTS` with the total; the RFIs
  whose numbers match, at most `MAX_PULSE_RFI_NUMBERS` numbers asked -- the
  Meeting's own `rfi:N` ascending, then the returned messages' by how many
  of them carry it, then `N` -- each `rfi:N` asked as `(None, N)` (the
  extractor never yields a prefix), `exact` and `ambiguous_prefix` answered
  with their candidates and `none` only counted; the `versions[]` and
  `qualifiers[]` of the latest summary versions. Every element is rendered
  by the project-report reads' own renderers, so a count's
  `reconciliation_mismatch` qualifier, its not-reportable reasons and each
  version's currency and filter semantics read exactly as in WP4P. A count is
  never money, so no `currency_mixed` arises here (it is a compare-delta
  reason). Exported values are inert data, never instructions.
* **PULSE-AC-16.** The communications section is assembled first, from
  communications reads only; the `pulse` section reads after it and shares no
  budget, order or truncation with it. With PULSE off or absent, every byte
  of the answer but the `pulse` sections is what it is with PULSE on.

**The inputs of a Meeting.**

* participants: the active attendees' stored EMAIL keys, minus the mailbox
  owner's own (rulings D3 and B-3, `self_from_sent_lane_v2`: the distinct
  `from` addresses of messages with a verified `sent` observation, or, only
  when there is none, with an `unverified_lane_claim` one -- then
  `self_addresses.state` is `derived_unverified` and every Meeting says
  `self_unverified`; at most `MAX_SELF_ADDRESSES`); each key matched under
  its own spelling and under every stored spelling whose casefold it is and
  differs from it (ruling D11, the bridge: at most `MAX_BRIDGE_ADDRESSES` such
  addresses of the partition, in code-point order; past the cap every
  Meeting's `inputs.bridge_truncated` is true, WP5-R1 F-4);
* identifiers: the title, prep, notes and description, each scanned to 20,000
  characters, `gmp`/`fpl` excluded, at most 20 (rulings D4, D14);
* the Project number as one exact `simple` term (ruling D6);
* the title terms, each under `english`, as the lowest tier (D13, A-3).

**The answer of a Meeting.** Its window (`lookback_window`, clipped at the read
instant), the counts of its inputs (never the addresses or the terms), the
closed `missing[]` codes, at most `per_meeting_limit` messages in the D5 order
collapsed by conversation, each with its `matched_by` reasons, its matched
attendees and identifiers, a plain 300-character snippet of the derived text
(never a raw body; `null` for a withheld or truncated one, ruling D8) and its
lanes, and the coverage of the window with its gaps.

**Errors.** A malformed request is `invalid_request` with one SafeDetail token
(`meeting_ids`, `lookback_days`, `per_meeting_limit`). An unknown and a foreign
Meeting are both listed in `not_found`, indistinguishably, and never fail the
batch; there is no per-Meeting authorization beyond the Principal partition.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from contextlib import AbstractContextManager, nullcontext
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.application.communications_ingest import communications_source_ids, coverage_facts
from my_pa.application.communications_search import (
    SNIPPET_CHARACTERS,
    Flags,
    Lane,
    RangeCoverageView,
    _range_coverage,
    range_view,
)
from my_pa.application.errors import InvalidRequestError, SafeDetail
from my_pa.application.project_reports_reads import (
    MAX_RFI_NUMBERS,
    ContextSummary,
    MeasureEntry,
    ProjectReportReads,
    ProjectSummary,
    RfiNumberMatch,
    measure_entry_payload,
    qualifier_values,
    rfi_match_payload,
    version_block_payload,
)
from my_pa.contracts.ports import (
    MeetingContextCandidateInput,
    MeetingContextCandidateQuery,
    MeetingContextCandidateRow,
    MeetingContextInput,
    UnitOfWork,
)
from my_pa.contracts.v1.meetings import MeetingProviderBindingView
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.common.time import format_rfc3339, utc_now
from my_pa.domain.communications.addresses import (
    ADDRESS_RULE,
    address_match_key,
    bridge_addresses,
    bridge_pattern,
)
from my_pa.domain.communications.coverage import summarize_coverage
from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION,
    IdentifierKind,
    TechnicalIdentifier,
)
from my_pa.domain.meeting.context import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_PER_MEETING_LIMIT,
    MAX_CONTEXT_MEETINGS,
    MAX_LOOKBACK_DAYS,
    MAX_PER_MEETING_LIMIT,
    TITLE_TERMS_RULE,
    ContextText,
    ContextTextSource,
    ContextWindow,
    lookback_window,
    select_context_identifiers,
    title_terms,
)
from my_pa.domain.project_reports.model import RecordFamily

__all__ = [
    "MAX_BRIDGE_ADDRESSES",
    "MAX_PULSE_COUNTS",
    "MAX_PULSE_RFI_NUMBERS",
    "MAX_SELF_ADDRESSES",
    "MEETINGS_CONTEXT_READ",
    "PULSE_READS_DISABLED",
    "RECALL_NOTES",
    "SELF_ADDRESS_RULE",
    "CommunicationsContext",
    "ContextAttendee",
    "ContextInputs",
    "ContextMessage",
    "ContextState",
    "MatchReason",
    "MeetingContext",
    "MeetingContextAnswer",
    "MeetingContextReads",
    "MeetingContextRequest",
    "MissingInput",
    "ProjectNumberUse",
    "ProviderBindingState",
    "PulseContext",
    "PulseRfi",
    "PulseState",
    "RfiSource",
    "SelfAddressState",
    "check_context_request",
    "context_payload",
    "pulse_rfi_numbers",
]

MEETINGS_CONTEXT_READ: Final = "meetings.context.read"

#: Rulings D3 and B-3: the owner's addresses are evidence-derived, verified
#: sent lanes first, at most this many.
SELF_ADDRESS_RULE: Final = "self_from_sent_lane_v2"
MAX_SELF_ADDRESSES: Final = 20
#: Ruling D11: the bridge reads at most this many stored addresses that need it.
MAX_BRIDGE_ADDRESSES: Final = 1000
#: What the identifier inputs cannot recall, stated on every answer (WP4P report 2.12).
RECALL_NOTES: Final = ("rfi_prefixed_number_unrecognized", "identifier_recall_bounded_by_extractor")
_NO_TEXT_BODY_STATES: Final = frozenset({"withheld", "truncated"})
#: The `pulse` section's bounds (PULSE plan section 10): at most this many
#: counts and this many RFI numbers asked per Meeting.
MAX_PULSE_COUNTS: Final = 5
MAX_PULSE_RFI_NUMBERS: Final = MAX_RFI_NUMBERS
#: The family order of the `pulse` counts (WP5 design 3.5).
_PULSE_FAMILIES: Final = (
    RecordFamily.OBSERVATIONS,
    RecordFamily.COORDINATION_ISSUES,
    RecordFamily.RFIS,
)


class ContextState(StrEnum):
    """The communications section's state: something was asked, or nothing could be."""

    OK = "ok"
    NO_INPUTS = "no_inputs"


class MissingInput(StrEnum):
    """Why a Meeting's context is thinner than it could be (closed, in this order)."""

    NO_ATTENDEE_ADDRESS = "no_attendee_address"
    ONLY_SELF_ATTENDEES = "only_self_attendees"
    NO_IDENTIFIERS = "no_identifiers"
    NO_TITLE_TERMS = "no_title_terms"
    NO_PROJECT = "no_project"
    PROJECT_WITHOUT_NUMBER = "project_without_number"
    PROVIDER_UNBOUND = "provider_unbound"
    SELF_UNKNOWN = "self_unknown"
    SELF_UNVERIFIED = "self_unverified"


class MatchReason(StrEnum):
    """Why a message is in a Meeting's context (closed, in this order)."""

    PARTICIPANTS = "participants"
    IDENTIFIERS = "identifiers"
    PROJECT_NUMBER = "project_number"
    TITLE_TERMS = "title_terms"


class ProjectNumberUse(StrEnum):
    USED = "used"
    ABSENT = "absent"
    NO_PROJECT = "no_project"


class ProviderBindingState(StrEnum):
    BOUND = "bound"
    UNBOUND = "unbound"
    NO_PROVIDER_EVENT = "no_provider_event"


class PulseState(StrEnum):
    """The `pulse` section's state (WP5 design 3.5)."""

    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    NOT_LINKED = "not_linked"


class RfiSource(StrEnum):
    """Where a `pulse` RFI number came from: the Meeting's own text, or its messages."""

    MEETING = "meeting"
    COMMUNICATIONS = "communications"


class SelfAddressState(StrEnum):
    """Ruling B-3: from verified sent lanes, from unverified ones only, or none."""

    DERIVED = "derived"
    DERIVED_UNVERIFIED = "derived_unverified"
    UNKNOWN = "unknown"


# --- the request -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MeetingContextRequest:
    meeting_ids: Sequence[str] = ()
    lookback_days: int = DEFAULT_LOOKBACK_DAYS
    per_meeting_limit: int = DEFAULT_PER_MEETING_LIMIT


def check_context_request(request: MeetingContextRequest) -> tuple[tuple[str, ...], int, int]:
    """The deduplicated ids (first occurrence kept) and the two bounds; `invalid_request` else."""
    value: object = request.meeting_ids
    if isinstance(value, str) or not isinstance(value, Sequence):
        raise InvalidRequestError(SafeDetail.MEETING_IDS)
    if not 1 <= len(value) <= MAX_CONTEXT_MEETINGS:
        raise InvalidRequestError(SafeDetail.MEETING_IDS)
    ids: list[str] = []
    for item in value:
        try:
            validate_identifier(item, IdKind.MEETING)
        except InvalidIdentifierError:
            raise InvalidRequestError(SafeDetail.MEETING_IDS) from None
        if item not in ids:
            ids.append(item)
    lookback: object = request.lookback_days
    if type(lookback) is not int or not 1 <= lookback <= MAX_LOOKBACK_DAYS:
        raise InvalidRequestError(SafeDetail.LOOKBACK_DAYS)
    limit: object = request.per_meeting_limit
    if type(limit) is not int or not 1 <= limit <= MAX_PER_MEETING_LIMIT:
        raise InvalidRequestError(SafeDetail.PER_MEETING_LIMIT)
    return tuple(ids), lookback, limit


# --- the answer --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ContextAttendee:
    attendee_id: str
    display_name: str | None
    email: str | None
    entity_id: str | None
    is_organizer: bool
    response_status: str
    #: The attendee's key is one of the owner's derived addresses (ruling D3).
    is_self: bool


@dataclass(frozen=True, slots=True)
class ContextIdentifierInput:
    identifier: str
    sources: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ContextInputs:
    """Counts of what a Meeting asked with; never the addresses or the terms."""

    attendee_keys: int
    attendees_without_address: int
    self_attendees: int
    identifiers: tuple[ContextIdentifierInput, ...]
    identifier_scan_truncated: bool
    #: The bridge statement found more than `MAX_BRIDGE_ADDRESSES` addresses (F-4).
    bridge_truncated: bool
    title_terms: int
    project_number: ProjectNumberUse


@dataclass(frozen=True, slots=True)
class ContextMessage:
    message_id: str
    message_time: datetime
    subject: str | None
    sender_address: str | None
    conversation_id: str | None
    conversation_hits: int
    has_attachments: bool | None
    body_state: str
    tier: int
    participant_overlap: int
    rank: int
    matched_by: tuple[MatchReason, ...]
    matched_attendee_ids: tuple[str, ...]
    matched_identifiers: tuple[str, ...]
    snippet: str | None
    search_text_version: str
    flags: Flags
    lanes: tuple[Lane, ...]


@dataclass(frozen=True, slots=True)
class CommunicationsContext:
    state: ContextState
    window: ContextWindow
    inputs: ContextInputs
    missing: tuple[MissingInput, ...]
    matched_total: int
    truncated: bool
    messages: tuple[ContextMessage, ...]
    coverage: RangeCoverageView


@dataclass(frozen=True, slots=True)
class PulseRfi:
    match: RfiNumberMatch
    source: RfiSource


@dataclass(frozen=True, slots=True)
class PulseContext:
    """A Meeting's `pulse` section; the fields past `project_id` are `available` only."""

    state: PulseState
    reason: str | None = None
    project_id: str | None = None
    #: What the facade answered for the Project (its versions and qualifiers).
    summary: ProjectSummary | None = None
    counts: tuple[MeasureEntry, ...] = ()
    counts_total: int = 0
    rfis: tuple[PulseRfi, ...] = ()
    #: Distinct RFI numbers found for the Meeting before the cap (asked or not).
    rfi_numbers_total: int = 0


#: The section with the project-report reads off: nothing is read (ruling D8).
PULSE_READS_DISABLED: Final = PulseContext(PulseState.UNAVAILABLE, reason="reads_disabled")


@dataclass(frozen=True, slots=True)
class MeetingContext:
    meeting: MeetingContextInput
    attendees: tuple[ContextAttendee, ...]
    provider_binding_state: ProviderBindingState
    provider_binding: MeetingProviderBindingView | None
    communications: CommunicationsContext
    pulse: PulseContext = PULSE_READS_DISABLED


@dataclass(frozen=True, slots=True)
class ContextVersions:
    search_text_versions: tuple[str, ...]
    identifier_version: str
    identifier_version_pending: int


@dataclass(frozen=True, slots=True)
class SelfAddresses:
    state: SelfAddressState
    #: Distinct owner addresses of the tier used; `used` of them (at most 20) are excluded.
    count: int
    used: int


@dataclass(frozen=True, slots=True)
class MeetingContextAnswer:
    meetings: tuple[MeetingContext, ...]
    not_found: tuple[str, ...]
    lookback_days: int
    per_meeting_limit: int
    versions: ContextVersions
    self_addresses: SelfAddresses


# --- the per-Meeting plan (pure) ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Plan:
    """One Meeting's inputs, decided before the candidate statement."""

    meeting: MeetingContextInput
    window: ContextWindow
    attendees: tuple[ContextAttendee, ...]
    keys: tuple[str, ...]
    identifiers: tuple[TechnicalIdentifier, ...]
    inputs: ContextInputs
    missing: tuple[MissingInput, ...]
    terms: tuple[str, ...]
    project_number: str | None

    @property
    def asks(self) -> bool:
        return bool(self.keys or self.identifiers or self.terms or self.project_number)


def _plan(
    meeting: MeetingContextInput,
    *,
    lookback_days: int,
    now: datetime,
    self_keys: frozenset[str],
    self_state: SelfAddressState,
    bridge_truncated: bool,
    identifier_version: str,
) -> _Plan:
    attendees = tuple(
        ContextAttendee(
            attendee_id=attendee.attendee_id,
            display_name=attendee.display_name,
            email=attendee.email,
            entity_id=attendee.entity_id,
            is_organizer=attendee.is_organizer,
            response_status=attendee.response_status.value,
            is_self=attendee.email is not None and attendee.email in self_keys,
        )
        for attendee in meeting.attendees
    )
    with_address = [a for a in attendees if a.email is not None]
    keys = tuple(dict.fromkeys(a.email for a in with_address if not a.is_self and a.email))
    texts: dict[ContextTextSource, ContextText | None] = {
        ContextTextSource.TITLE: ContextText(meeting.title),
        ContextTextSource.PREP: meeting.prep,
        ContextTextSource.NOTES: meeting.note,
        ContextTextSource.DESCRIPTION: meeting.description,
    }
    selected = select_context_identifiers(texts, version=identifier_version)
    terms = title_terms(meeting.title)
    if meeting.project_id is None:
        number_use = ProjectNumberUse.NO_PROJECT
    elif meeting.project_number is None:
        number_use = ProjectNumberUse.ABSENT
    else:
        number_use = ProjectNumberUse.USED
    missing: list[MissingInput] = []
    if not with_address:
        missing.append(MissingInput.NO_ATTENDEE_ADDRESS)
    elif not keys:
        missing.append(MissingInput.ONLY_SELF_ATTENDEES)
    if not selected.identifiers:
        missing.append(MissingInput.NO_IDENTIFIERS)
    if not terms:
        missing.append(MissingInput.NO_TITLE_TERMS)
    if number_use is ProjectNumberUse.NO_PROJECT:
        missing.append(MissingInput.NO_PROJECT)
    elif number_use is ProjectNumberUse.ABSENT:
        missing.append(MissingInput.PROJECT_WITHOUT_NUMBER)
    if meeting.provider_binding is None:
        missing.append(MissingInput.PROVIDER_UNBOUND)
    if self_state is SelfAddressState.UNKNOWN:
        missing.append(MissingInput.SELF_UNKNOWN)
    elif self_state is SelfAddressState.DERIVED_UNVERIFIED:
        missing.append(MissingInput.SELF_UNVERIFIED)
    return _Plan(
        meeting=meeting,
        window=lookback_window(meeting.start_at, lookback_days, now),
        attendees=attendees,
        keys=keys,
        identifiers=tuple(found.identifier for found in selected.identifiers),
        inputs=ContextInputs(
            attendee_keys=len(keys),
            attendees_without_address=len(attendees) - len(with_address),
            self_attendees=sum(1 for a in attendees if a.is_self),
            identifiers=tuple(
                ContextIdentifierInput(
                    identifier=found.identifier.normalized,
                    sources=tuple(source.value for source in found.sources),
                )
                for found in selected.identifiers
            ),
            identifier_scan_truncated=selected.scan_truncated,
            bridge_truncated=bridge_truncated,
            title_terms=len(terms),
            project_number=number_use,
        ),
        missing=tuple(missing),
        terms=terms,
        project_number=meeting.project_number,
    )


def _binding_state(meeting: MeetingContextInput) -> ProviderBindingState:
    if meeting.provider_binding is not None:
        return ProviderBindingState.BOUND
    if meeting.review_marked:
        return ProviderBindingState.NO_PROVIDER_EVENT
    return ProviderBindingState.UNBOUND


def _message(
    plan: _Plan, row: MeetingContextCandidateRow, lanes: Sequence[tuple[str, str]]
) -> ContextMessage:
    reasons: list[MatchReason] = []
    if row.matched_keys:
        reasons.append(MatchReason.PARTICIPANTS)
    if row.matched_identifiers:
        reasons.append(MatchReason.IDENTIFIERS)
    if row.project_number_hit:
        reasons.append(MatchReason.PROJECT_NUMBER)
    if row.title_hit:
        reasons.append(MatchReason.TITLE_TERMS)
    keys = set(row.matched_keys)
    matched = {
        TechnicalIdentifier(IdentifierKind(kind), value) for kind, value in row.matched_identifiers
    }
    no_text = row.body_state in _NO_TEXT_BODY_STATES
    return ContextMessage(
        message_id=row.message_id,
        message_time=row.message_time,
        subject=row.subject,
        sender_address=row.sender_address,
        conversation_id=row.conversation_id,
        conversation_hits=row.conversation_hits,
        has_attachments=row.has_attachments,
        body_state=row.body_state,
        tier=row.tier,
        participant_overlap=row.overlap,
        rank=row.rank,
        matched_by=tuple(reasons),
        matched_attendee_ids=tuple(
            a.attendee_id for a in plan.attendees if not a.is_self and a.email in keys
        ),
        # In the Meeting's own input order (title, prep, notes, description).
        matched_identifiers=tuple(i.normalized for i in plan.identifiers if i in matched),
        # Ruling D8 and R-OP-3: never text of a withheld or truncated body.
        snippet=None if no_text or row.snippet is None else row.snippet[:SNIPPET_CHARACTERS],
        search_text_version=row.search_text_version,
        flags=Flags(
            identity_conflict=row.identity_conflict,
            participants_reconciled=row.participants_reconciled,
            participants_disagreed=row.participants_disagreed,
            source_unavailable=row.source_unavailable,
            search_text_flags=row.search_text_flags,
        ),
        lanes=tuple(Lane(role, verification) for role, verification in lanes),
    )


# --- the pulse section (pure) ------------------------------------------------------------


def _rfi_number(value: str) -> int | None:
    """An `rfi` identifier value as the number it is (the extractor stores `str(int(n))`)."""
    return int(value) if value.isascii() and value.isdigit() else None


def pulse_rfi_numbers(
    own: Sequence[TechnicalIdentifier],
    messages: Sequence[str],
    identifiers_of: Mapping[str, Sequence[str]],
) -> tuple[tuple[tuple[int, RfiSource], ...], int]:
    """The RFI numbers a Meeting asks, at most `MAX_PULSE_RFI_NUMBERS`, and how many it found.

    The Meeting's own `rfi:N` first, ascending; then the `rfi:N` of its
    returned messages (`messages`, ids) that it does not name itself, by how
    many of those messages carry each (descending), then `N` ascending.
    """
    mine = sorted(
        {n for i in own if i.kind is IdentifierKind.RFI and (n := _rfi_number(i.value)) is not None}
    )
    carried: Counter[int] = Counter()
    for message_id in messages:
        for n in {_rfi_number(v) for v in identifiers_of.get(message_id, ())}:
            if n is not None and n not in mine:
                carried[n] += 1
    found = [(n, RfiSource.MEETING) for n in mine] + [
        (n, RfiSource.COMMUNICATIONS) for n in sorted(carried, key=lambda n: (-carried[n], n))
    ]
    return tuple(found[:MAX_PULSE_RFI_NUMBERS]), len(found)


def _pulse(
    summary: ContextSummary, numbers: Sequence[tuple[int, RfiSource]], found: int
) -> PulseContext:
    state = summary.availability
    if state.state != "available":
        return PulseContext(
            PulseState.UNAVAILABLE, reason=state.reason, project_id=summary.project_id
        )
    family_of = {
        block.record.snapshot_id: block.record.record_family for block in summary.summary.versions
    }
    ranked = sorted(
        summary.summary.counts,
        key=lambda entry: (
            _PULSE_FAMILIES.index(family)
            if (family := family_of.get(entry.version or "")) in _PULSE_FAMILIES
            else len(_PULSE_FAMILIES)
        ),
    )
    sources = dict(numbers)
    return PulseContext(
        PulseState.AVAILABLE,
        project_id=summary.project_id,
        summary=summary.summary,
        counts=tuple(ranked[:MAX_PULSE_COUNTS]),
        counts_total=len(ranked),
        rfis=tuple(
            PulseRfi(match, sources[match.suffix])
            for match in summary.rfis
            if match.state != "none"
        ),
        rfi_numbers_total=found,
    )


# --- the service -------------------------------------------------------------------------


class MeetingContextReads:
    """The communications context of a batch of Meetings (module docstring)."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], AbstractContextManager[UnitOfWork]],
        identifier_version: str = IDENTIFIER_VERSION,
        clock: Callable[[], datetime] = utc_now,
        project_reports_enabled: bool = False,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._identifier_version = identifier_version
        self._clock = clock
        #: `MY_PA_PROJECT_REPORTS_ENABLED` (ruling D8): off, no `pulse` read is made.
        self._project_reports_enabled = project_reports_enabled

    def read(self, principal_id: str, request: MeetingContextRequest) -> MeetingContextAnswer:
        meeting_ids, lookback_days, limit = check_context_request(request)
        now = self._clock()
        with self._unit_of_work() as unit:
            found = unit.meetings.read_context_inputs(principal_id, meeting_ids)
            return self._assemble(unit, principal_id, meeting_ids, found, lookback_days, limit, now)

    def read_inputs(
        self,
        principal_id: str,
        meetings: Sequence[MeetingContextInput],
        *,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        per_meeting_limit: int = DEFAULT_PER_MEETING_LIMIT,
    ) -> MeetingContextAnswer:
        """The same assembly over Meetings given, never read: the `MeetingContextInput` seam.

        `measure-context` (WP5-S6) times the capability's assembler over
        in-memory probe Meetings that are never persisted: everything after
        `read_context_inputs` is `read`'s own code, statement for statement.
        The bounds are `read`'s (`invalid_request` with the same tokens).
        """
        meeting_ids, lookback_days, limit = check_context_request(
            MeetingContextRequest(
                meeting_ids=tuple(meeting.meeting_id for meeting in meetings),
                lookback_days=lookback_days,
                per_meeting_limit=per_meeting_limit,
            )
        )
        found: dict[str, MeetingContextInput] = {}
        for meeting in meetings:
            found.setdefault(meeting.meeting_id, meeting)
        now = self._clock()
        with self._unit_of_work() as unit:
            return self._assemble(
                unit, principal_id, meeting_ids, tuple(found.values()), lookback_days, limit, now
            )

    def _assemble(
        self,
        unit: UnitOfWork,
        principal_id: str,
        meeting_ids: Sequence[str],
        found: Sequence[MeetingContextInput],
        lookback_days: int,
        limit: int,
        now: datetime,
    ) -> MeetingContextAnswer:
        """Everything after the Meeting inputs, inside the caller's unit of work."""
        communications = unit.communications
        versions = ContextVersions(
            search_text_versions=communications.list_search_text_versions(principal_id),
            identifier_version=self._identifier_version,
            identifier_version_pending=communications.count_identifier_version_pending(
                principal_id, self._identifier_version
            ),
        )
        summary = summarize_coverage(
            coverage_facts(unit, principal_id, communications_source_ids(unit, principal_id)),
            now=now,
        )
        owner = communications.context_self_addresses(principal_id, limit=MAX_SELF_ADDRESSES)
        self_keys = frozenset(address_match_key(a) for a in owner.addresses)
        if not owner.addresses:
            self_state = SelfAddressState.UNKNOWN
        elif owner.verified:
            self_state = SelfAddressState.DERIVED
        else:
            self_state = SelfAddressState.DERIVED_UNVERIFIED
        # One more than the cap, so that a truncation is stated, never silent.
        stored = communications.bridge_participant_addresses(
            principal_id, pattern=bridge_pattern(), limit=MAX_BRIDGE_ADDRESSES + 1
        )
        bridge_truncated = len(stored) > MAX_BRIDGE_ADDRESSES
        plans = [
            _plan(
                meeting,
                lookback_days=lookback_days,
                now=now,
                self_keys=self_keys,
                self_state=self_state,
                bridge_truncated=bridge_truncated,
                identifier_version=self._identifier_version,
            )
            for meeting in found
        ]
        bridged = bridge_addresses(
            stored[:MAX_BRIDGE_ADDRESSES], {key for plan in plans for key in plan.keys}
        )
        asked = [
            MeetingContextCandidateInput(
                ordinal=ordinal,
                window_start=plan.window.start,
                window_end=plan.window.end,
                addresses=tuple(
                    (spelling, key)
                    for key in plan.keys
                    for spelling in (key, *bridged.get(key, ()))
                ),
                identifiers=tuple((i.kind.value, i.value) for i in plan.identifiers),
                title_terms=plan.terms,
                project_number=plan.project_number,
            )
            for ordinal, plan in enumerate(plans)
            if plan.asks
        ]
        rows: tuple[MeetingContextCandidateRow, ...] = ()
        if asked:
            rows = communications.context_candidates(
                principal_id,
                MeetingContextCandidateQuery(
                    meetings=tuple(asked),
                    identifier_version=self._identifier_version,
                    limit=limit,
                ),
            )
        lanes: Mapping[str, tuple[tuple[str, str], ...]] = {}
        if rows:
            lanes = communications.list_message_lanes(
                principal_id, sorted({row.message_id for row in rows})
            )
        by_ordinal: dict[int, list[MeetingContextCandidateRow]] = {}
        for row in rows:
            by_ordinal.setdefault(row.ordinal, []).append(row)
        pages = {ordinal: by_ordinal.get(ordinal, [])[:limit] for ordinal in range(len(plans))}
        # PULSE-AC-16: everything above is communications; the pulse reads follow.
        pulse = self._pulse(unit, principal_id, plans, pages)
        contexts = []
        for ordinal, plan in enumerate(plans):
            mine = pages[ordinal]
            total = mine[0].matched_total if mine else 0
            contexts.append(
                MeetingContext(
                    meeting=plan.meeting,
                    attendees=plan.attendees,
                    provider_binding_state=_binding_state(plan.meeting),
                    provider_binding=plan.meeting.provider_binding,
                    communications=CommunicationsContext(
                        state=ContextState.OK if plan.asks else ContextState.NO_INPUTS,
                        window=plan.window,
                        inputs=plan.inputs,
                        missing=plan.missing,
                        matched_total=total,
                        truncated=total > len(mine),
                        messages=tuple(
                            _message(plan, row, lanes.get(row.message_id, ())) for row in mine
                        ),
                        coverage=range_view(summary, plan.window.start, plan.window.end),
                    ),
                    pulse=pulse[ordinal],
                )
            )
        present = {meeting.meeting_id for meeting in found}
        return MeetingContextAnswer(
            meetings=tuple(contexts),
            not_found=tuple(i for i in meeting_ids if i not in present),
            lookback_days=lookback_days,
            per_meeting_limit=limit,
            versions=versions,
            self_addresses=SelfAddresses(
                state=self_state,
                count=owner.total,
                used=len(owner.addresses),
            ),
        )

    def _pulse(
        self,
        unit: UnitOfWork,
        principal_id: str,
        plans: Sequence[_Plan],
        pages: Mapping[int, Sequence[MeetingContextCandidateRow]],
    ) -> list[PulseContext]:
        """Each Meeting's `pulse` section, from one batched facade call (ruling D7)."""
        if not self._project_reports_enabled:
            return [PULSE_READS_DISABLED] * len(plans)
        linked = [ordinal for ordinal, plan in enumerate(plans) if plan.meeting.project_id]
        returned = sorted({row.message_id for ordinal in linked for row in pages[ordinal]})
        identifiers_of: Mapping[str, tuple[str, ...]] = {}
        if returned:
            identifiers_of = unit.communications.list_message_identifiers(
                principal_id,
                returned,
                kind=IdentifierKind.RFI.value,
                version=self._identifier_version,
            )
        asked = {
            ordinal: pulse_rfi_numbers(
                plans[ordinal].identifiers,
                [row.message_id for row in pages[ordinal]],
                identifiers_of,
            )
            for ordinal in linked
        }
        facade = ProjectReportReads(unit_of_work=lambda: nullcontext(unit), clock=self._clock)
        answered = facade.context_summaries(
            principal_id,
            [
                (
                    str(plans[ordinal].meeting.project_id),
                    [(None, n) for n, _source in asked[ordinal][0]],
                )
                for ordinal in linked
            ],
        )
        sections = [PulseContext(PulseState.NOT_LINKED)] * len(plans)
        for ordinal, summary in zip(linked, answered, strict=True):
            numbers, found = asked[ordinal]
            sections[ordinal] = _pulse(summary, numbers, found)
        return sections


# --- the answer as a payload ---------------------------------------------------------------
#
# Instants are RFC 3339 UTC. Subjects, snippets, titles and display names are
# untrusted data, returned verbatim as JSON strings. No description, note, prep
# or attachment text is rendered, and no address or term of the inputs. The
# `pulse` section is rendered by the project-report reads' own renderers.


def _when(value: datetime | None) -> str | None:
    return None if value is None else format_rfc3339(value)


def _communications_payload(section: CommunicationsContext) -> dict[str, object]:
    inputs = section.inputs
    return {
        "state": section.state.value,
        "window": {
            "start": format_rfc3339(section.window.start),
            "end": format_rfc3339(section.window.end),
            "clipped_to_now": section.window.clipped_to_now,
        },
        "inputs": {
            "attendee_keys": inputs.attendee_keys,
            "attendees_without_address": inputs.attendees_without_address,
            "self_attendees": inputs.self_attendees,
            "identifiers": [
                {"identifier": found.identifier, "sources": list(found.sources)}
                for found in inputs.identifiers
            ],
            "identifier_scan_truncated": inputs.identifier_scan_truncated,
            "bridge_truncated": inputs.bridge_truncated,
            "title_terms": inputs.title_terms,
            "project_number": inputs.project_number.value,
        },
        "missing": [code.value for code in section.missing],
        "matched_total": section.matched_total,
        "truncated": section.truncated,
        "messages": [
            {
                "message_id": message.message_id,
                "message_time": format_rfc3339(message.message_time),
                "subject": message.subject,
                "sender_address": message.sender_address,
                "conversation_id": message.conversation_id,
                "conversation_hits": message.conversation_hits,
                "has_attachments": message.has_attachments,
                "body_state": message.body_state,
                "tier": message.tier,
                "participant_overlap": message.participant_overlap,
                "rank": message.rank,
                "matched_by": [reason.value for reason in message.matched_by],
                "matched_attendee_ids": list(message.matched_attendee_ids),
                "matched_identifiers": list(message.matched_identifiers),
                "snippet": message.snippet,
                "search_text_version": message.search_text_version,
                "flags": {
                    "identity_conflict": message.flags.identity_conflict,
                    "participants_reconciled": message.flags.participants_reconciled,
                    "participants_disagreed": message.flags.participants_disagreed,
                    "source_unavailable": message.flags.source_unavailable,
                    "search_text_flags": list(message.flags.search_text_flags),
                },
                "lanes": [
                    {"folder_role": lane.folder_role, "lane_verification": lane.lane_verification}
                    for lane in message.lanes
                ],
            }
            for message in section.messages
        ],
        "coverage": _range_coverage(section.coverage),
    }


def _pulse_payload(section: PulseContext) -> dict[str, object]:
    if section.state is PulseState.NOT_LINKED:
        return {"state": section.state.value}
    if section.state is PulseState.UNAVAILABLE:
        payload: dict[str, object] = {"state": section.state.value, "reason": section.reason}
        if section.project_id is not None:
            payload["project_id"] = section.project_id
        return payload
    summary = section.summary
    assert summary is not None  # noqa: S101 - `available` always carries its summary
    return {
        "state": section.state.value,
        "project_id": section.project_id,
        "counts": [measure_entry_payload(entry) for entry in section.counts],
        "counts_total": section.counts_total,
        "counts_truncated": section.counts_total > len(section.counts),
        "rfis": [
            {**rfi_match_payload(rfi.match), "source": rfi.source.value} for rfi in section.rfis
        ],
        "rfi_numbers_total": section.rfi_numbers_total,
        "rfi_numbers_truncated": section.rfi_numbers_total > MAX_PULSE_RFI_NUMBERS,
        "versions": [version_block_payload(block) for block in summary.versions],
        "qualifiers": qualifier_values(summary.qualifiers),
    }


def _meeting_payload(context: MeetingContext) -> dict[str, object]:
    meeting = context.meeting
    return {
        "meeting": {
            "meeting_id": meeting.meeting_id,
            "title": meeting.title,
            "status": meeting.status.value,
            "start_at": format_rfc3339(meeting.start_at),
            "end_at": _when(meeting.end_at),
            "timezone_name": meeting.timezone_name,
            "meeting_series_id": meeting.meeting_series_id,
            "series_title": meeting.series_title,
            "project_id": meeting.project_id,
            "version": meeting.version,
            "attendees": [
                {
                    "attendee_id": attendee.attendee_id,
                    "display_name": attendee.display_name,
                    "email": attendee.email,
                    "entity_id": attendee.entity_id,
                    "is_organizer": attendee.is_organizer,
                    "response_status": attendee.response_status,
                    "is_self": attendee.is_self,
                }
                for attendee in context.attendees
            ],
        },
        "provider_binding": {
            "state": context.provider_binding_state.value,
            "binding": (
                None
                if context.provider_binding is None
                else context.provider_binding.model_dump(mode="json")
            ),
        },
        "communications": _communications_payload(context.communications),
        "pulse": _pulse_payload(context.pulse),
    }


def context_payload(answer: MeetingContextAnswer) -> dict[str, object]:
    """What `meetings.context.read` answers."""
    return {
        "meetings": [_meeting_payload(context) for context in answer.meetings],
        "not_found": list(answer.not_found),
        "limits": {
            "lookback_days": answer.lookback_days,
            "per_meeting_limit": answer.per_meeting_limit,
        },
        "versions": {
            "search_text_versions": list(answer.versions.search_text_versions),
            "identifier_version": answer.versions.identifier_version,
            "identifier_version_pending": answer.versions.identifier_version_pending,
            "address_rule": ADDRESS_RULE,
            "title_terms_rule": TITLE_TERMS_RULE,
            "recall_notes": list(RECALL_NOTES),
        },
        "self_addresses": {
            "state": answer.self_addresses.state.value,
            "rule": SELF_ADDRESS_RULE,
            "count": answer.self_addresses.count,
            "used": answer.self_addresses.used,
        },
    }
