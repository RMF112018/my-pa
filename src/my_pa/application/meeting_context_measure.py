"""`measure-context`: the latency of `meetings.context.read` over probe Meetings (WP5-S6).

Design section 3.12 and ruling D16. The Manager's isolated database holds the
corpora but no real Meeting, so the measurement builds up to
`MAX_CONTEXT_MEETINGS` **in-memory probe Meetings, never persisted**, and runs
the capability's own assembler over them through the `MeetingContextInput`
seam (`MeetingContextReads.read_inputs`): every statement after the Meeting
input reads is the capability's, in the capability's order.

**The probes.**

* anchors: `meetings` instants evenly spaced over `[earliest covered +
  lookback, latest covered]` of the Principal's communications coverage (the
  latest covered instant alone when the coverage is shorter than the lookback;
  the read instant when nothing is covered, stated `anchor_basis: none`);
* attendees: the participants (at most `MAX_PROBE_ATTENDEES`) of the latest
  message at or before the anchor that has at least `MIN_PROBE_PARTICIPANTS`
  participants other than the owner's derived addresses, keyed as a Meeting
  keys them (`address_match_key`);
* identifiers: the `PROBE_IDENTIFIERS` most frequent non-bare identifiers of
  the anchor's lookback window, written into the probe's prep text in a
  surface form the extractor reads back;
* title: the fixed synthetic `PROBE_TITLE`, so the text path is exercised;
* Project: round-robin over the Projects with an active project-report
  binding, with their stored numbers, when there are any.

**Counts only.** The answer is closed codes, counts and milliseconds: never an
address, subject, snippet, name, title, Project number, identifier or id. The
probe facts stay in memory. Per shape (1 Meeting and `meetings` Meetings, each
with `MY_PA_PROJECT_REPORTS_ENABLED` off and on): p50, p95 and the maximum
over `runs` timed runs after one untimed warm run, and the statements of that
warm run -- the capability's statements less the seven Meeting input reads,
which the in-memory probes do not make. Per probe: the input counts, the
`missing[]` codes, the matches by tier and by `matched_by` reason, the coverage
state and gaps, and the `pulse` state with its RFI states. Once: the
self-address state and count, the C9 bridge count and truncation, the
`identity_kind_mismatch` quarantine count (ruling D11, question Q5) and, for
the D15 shapes, whether each target is met (a target, not a gate: the operator
amendment to D15).
"""

from __future__ import annotations

import statistics
import time
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Final

from pydantic import ValidationError

from my_pa.application.communications_ingest import communications_source_ids, coverage_facts
from my_pa.application.meeting_context import (
    MAX_BRIDGE_ADDRESSES,
    MAX_SELF_ADDRESSES,
    MeetingContextAnswer,
    MeetingContextReads,
)
from my_pa.contracts.ports import MeetingContextInput, UnitOfWork
from my_pa.contracts.v1.meetings import MeetingAttendeeView
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.common.time import utc_now
from my_pa.domain.communications.addresses import (
    address_match_key,
    bridge_addresses,
    bridge_pattern,
)
from my_pa.domain.communications.coverage import CoverageSummary, summarize_coverage
from my_pa.domain.communications.identifiers import (
    IDENTIFIER_VERSION,
    IdentifierKind,
    TechnicalIdentifier,
    surface_form,
)
from my_pa.domain.meeting.context import (
    DEFAULT_LOOKBACK_DAYS,
    DEFAULT_PER_MEETING_LIMIT,
    MAX_CONTEXT_MEETINGS,
    MAX_LOOKBACK_DAYS,
    MAX_PER_MEETING_LIMIT,
    ContextText,
)
from my_pa.domain.meeting.model import AttendeeResponseStatus, MeetingStatus

__all__ = [
    "DEFAULT_RUNS",
    "IDENTITY_KIND_MISMATCH",
    "MAX_PROBE_ATTENDEES",
    "MAX_RUNS",
    "MIN_PROBE_PARTICIPANTS",
    "PROBE_IDENTIFIERS",
    "PROBE_TITLE",
    "MeetingContextMeasurement",
    "ProbeFacts",
    "probe_anchors",
    "probe_meetings",
]

PROBE_TITLE: Final = "OAC coordination meeting RFI"
MAX_PROBE_ATTENDEES: Final = 8
MIN_PROBE_PARTICIPANTS: Final = 3
PROBE_IDENTIFIERS: Final = 2
DEFAULT_RUNS: Final = 40
MAX_RUNS: Final = 500
#: The quarantine reason whose count re-confirms ruling D11 (question Q5).
IDENTITY_KIND_MISMATCH: Final = "identity_kind_mismatch"
#: Ruling D15 (a target since the operator amendment): shape -> (p50, p95) ms.
_TARGET_DEFAULTS_10: Final = (300.0, 750.0)
_TARGET_DEFAULTS_1_P95: Final = 300.0
_TARGET_MAXIMUM_10_P95: Final = 2000.0

#: One anchor's facts: the participant addresses as stored, and `(kind, value)` pairs.
ProbeFacts = tuple[tuple[str, ...], tuple[tuple[str, str], ...]]
#: `(anchors, lookback, excluded stored addresses) -> one ProbeFacts per anchor`.
ProbeFactsReader = Callable[[Sequence[datetime], timedelta, Sequence[str]], Sequence[ProbeFacts]]


@dataclass(frozen=True, slots=True)
class _Corpus:
    summary: CoverageSummary
    owner_addresses: tuple[str, ...]
    stored_non_ascii: tuple[str, ...]
    projects: tuple[tuple[str, str | None], ...]


def probe_anchors(
    summary: CoverageSummary, lookback: timedelta, count: int, now: datetime
) -> tuple[tuple[datetime, ...], str]:
    """`count` instants evenly spaced over the covered range less the lookback, and the basis."""
    if not summary.intervals or summary.latest_covered is None:
        return (now,) * count, "none"
    latest = summary.latest_covered
    first = min(summary.intervals[0].start + lookback, latest)
    if count == 1:
        return (latest,), "coverage"
    step = (latest - first) / (count - 1)
    return tuple(first + step * k for k in range(count)), "coverage"


def _attendee(k: int, j: int, address: str, anchor: datetime) -> MeetingAttendeeView | None:
    try:
        return MeetingAttendeeView(
            attendee_id=make_identifier(IdKind.MEETING_ATTENDEE, f"probe{k:04d}{j:04d}"),
            email=address_match_key(address),
            is_organizer=j == 0,
            response_status=AttendeeResponseStatus.UNKNOWN,
            added_at=anchor,
        )
    except ValidationError:  # an address no Meeting could hold
        return None


def probe_meetings(
    anchors: Sequence[datetime],
    facts: Sequence[ProbeFacts],
    projects: Sequence[tuple[str, str | None]],
) -> tuple[tuple[MeetingContextInput, ...], int]:
    """The probe Meetings (never persisted) and how many attendee addresses were skipped."""
    probes: list[MeetingContextInput] = []
    skipped = 0
    for k, (anchor, (addresses, identifiers)) in enumerate(zip(anchors, facts, strict=True)):
        attendees: list[MeetingAttendeeView] = []
        for j, address in enumerate(addresses):
            attendee = _attendee(k, j, address, anchor)
            if attendee is None:
                skipped += 1
            else:
                attendees.append(attendee)
        surfaces = [
            form
            for kind, value in identifiers
            if (form := surface_form(TechnicalIdentifier(IdentifierKind(kind), value)))
        ]
        project_id, number = projects[k % len(projects)] if projects else (None, None)
        probes.append(
            MeetingContextInput(
                meeting_id=make_identifier(IdKind.MEETING, f"probe{k:08d}"),
                meeting_series_id=None,
                series_title=None,
                title=PROBE_TITLE,
                status=MeetingStatus.SCHEDULED,
                start_at=anchor,
                end_at=anchor + timedelta(hours=1),
                timezone_name="UTC",
                project_id=project_id,
                version=1,
                attendees=tuple(attendees),
                description=None,
                note=None,
                prep=ContextText(" ".join(surfaces)) if surfaces else None,
                provider_binding=None,
                review_marked=False,
                project_number=number,
            )
        )
    return tuple(probes), skipped


def _percentile_95(samples: Sequence[float]) -> float:
    ordered = sorted(samples)
    return ordered[int(0.95 * (len(ordered) - 1))]


def _tally(values: Iterable[str]) -> dict[str, int]:
    return dict(sorted(Counter(values).items()))


def _ms(seconds: float) -> float:
    return round(seconds * 1000, 1)


def _probe_counts(answer: MeetingContextAnswer) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    for k, context in enumerate(answer.meetings):
        section = context.communications
        tiers = Counter(str(message.tier) for message in section.messages)
        reasons = Counter(
            reason.value for message in section.messages for reason in message.matched_by
        )
        pulse = context.pulse
        rfi_states = Counter(rfi.match.state for rfi in pulse.rfis)
        found.append(
            {
                "probe": k,
                "inputs": {
                    "attendee_keys": section.inputs.attendee_keys,
                    "self_attendees": section.inputs.self_attendees,
                    "identifiers": len(section.inputs.identifiers),
                    "title_terms": section.inputs.title_terms,
                    "project_number": section.inputs.project_number.value,
                },
                "state": section.state.value,
                "missing": [code.value for code in section.missing],
                "matched_total": section.matched_total,
                "returned": len(section.messages),
                "truncated": section.truncated,
                "by_tier": dict(sorted(tiers.items())),
                "by_matched_by": dict(sorted(reasons.items())),
                "coverage_state": section.coverage.state,
                "coverage_gaps": section.coverage.gaps_total,
                "pulse_state": pulse.state.value,
                "pulse_reason": pulse.reason,
                "pulse_counts_total": pulse.counts_total,
                "rfis_exact": rfi_states.get("exact", 0),
                "rfis_ambiguous": rfi_states.get("ambiguous_prefix", 0),
                "rfi_numbers_total": pulse.rfi_numbers_total,
            }
        )
    return found


class MeetingContextMeasurement:
    """Counts-only latency of the context assembler over probe Meetings (module docstring)."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], AbstractContextManager[UnitOfWork]],
        probe_facts: ProbeFactsReader,
        quarantined: Callable[[str], int],
        statements: Callable[[], int],
        identifier_version: str = IDENTIFIER_VERSION,
        clock: Callable[[], datetime] = utc_now,
        timer: Callable[[], float] = time.perf_counter,
    ) -> None:
        self._unit_of_work = unit_of_work
        self._probe_facts = probe_facts
        self._quarantined = quarantined
        #: The statements issued so far on the measured engine (a running total).
        self._statements = statements
        self._identifier_version = identifier_version
        self._clock = clock
        self._timer = timer

    def _corpus(self, principal_id: str, now: datetime) -> _Corpus:
        with self._unit_of_work() as unit:
            summary = summarize_coverage(
                coverage_facts(unit, principal_id, communications_source_ids(unit, principal_id)),
                now=now,
            )
            communications = unit.communications
            owner = communications.context_self_addresses(principal_id, limit=MAX_SELF_ADDRESSES)
            stored = communications.bridge_participant_addresses(
                principal_id, pattern=bridge_pattern(), limit=MAX_BRIDGE_ADDRESSES + 1
            )
            bindings = unit.project_reports.list_bindings(principal_id, active_only=True)
            bound = sorted({binding.project_id for binding in bindings})
            projects = []
            for project_id in bound:
                project = unit.projects.get_project(principal_id, project_id)
                if project is not None:
                    projects.append((project_id, project.project_number))
        return _Corpus(summary, tuple(owner.addresses), tuple(stored), tuple(projects))

    def measure(
        self,
        principal_id: str,
        *,
        meetings: int = MAX_CONTEXT_MEETINGS,
        runs: int = DEFAULT_RUNS,
        lookback_days: int = DEFAULT_LOOKBACK_DAYS,
        per_meeting_limit: int = DEFAULT_PER_MEETING_LIMIT,
    ) -> dict[str, object]:
        """The counts-only measurement (module docstring)."""
        if not 1 <= meetings <= MAX_CONTEXT_MEETINGS or not 1 <= runs <= MAX_RUNS:
            raise ValueError("a probe count and a run count are bounded")
        if not 1 <= lookback_days <= MAX_LOOKBACK_DAYS:
            raise ValueError("the lookback is bounded")
        if not 1 <= per_meeting_limit <= MAX_PER_MEETING_LIMIT:
            raise ValueError("the per-Meeting limit is bounded")
        now = self._clock()
        lookback = timedelta(days=lookback_days)
        corpus = self._corpus(principal_id, now)
        anchors, basis = probe_anchors(corpus.summary, lookback, meetings, now)
        facts = self._probe_facts(anchors, lookback, corpus.owner_addresses)
        probes, skipped = probe_meetings(anchors, facts, corpus.projects)
        latency: dict[str, dict[str, object]] = {}
        answers: dict[str, MeetingContextAnswer] = {}
        for count in sorted({1, meetings}):
            for pulse in (False, True):
                name = f"meetings_{count}_pulse_{'on' if pulse else 'off'}"
                reads = MeetingContextReads(
                    unit_of_work=self._unit_of_work,
                    identifier_version=self._identifier_version,
                    clock=lambda: now,
                    project_reports_enabled=pulse,
                )

                def call(
                    reads: MeetingContextReads = reads, count: int = count
                ) -> MeetingContextAnswer:
                    return reads.read_inputs(
                        principal_id,
                        probes[:count],
                        lookback_days=lookback_days,
                        per_meeting_limit=per_meeting_limit,
                    )

                before = self._statements()
                warm = call()  # untimed: it warms the plans and counts the statements
                statements = self._statements() - before
                answers[name] = warm
                samples = []
                for _ in range(runs):
                    start = self._timer()
                    call()
                    samples.append(self._timer() - start)
                latency[name] = {
                    "p50_ms": _ms(statistics.median(samples)),
                    "p95_ms": _ms(_percentile_95(samples)),
                    "max_ms": _ms(max(samples)),
                    "statements": statements,
                }
        full = answers[f"meetings_{meetings}_pulse_on"]
        detail = _probe_counts(full)
        keys = {
            address_match_key(attendee.email)
            for probe in probes
            for attendee in probe.attendees
            if attendee.email is not None
        }
        bridged = bridge_addresses(corpus.stored_non_ascii[:MAX_BRIDGE_ADDRESSES], keys)
        return {
            "probes": len(probes),
            "anchor_basis": basis,
            "runs": runs,
            "lookback_days": lookback_days,
            "per_meeting_limit": per_meeting_limit,
            "probe_attendees_skipped": skipped,
            "latency": latency,
            "targets": self._targets(latency, meetings, lookback_days, per_meeting_limit),
            "per_probe": detail,
            "coverage": {
                "by_state": _tally(c.communications.coverage.state for c in full.meetings),
                "gaps": sum(c.communications.coverage.gaps_total for c in full.meetings),
            },
            "pulse": {
                "bound_projects": len(corpus.projects),
                "by_state": _tally(c.pulse.state.value for c in full.meetings),
            },
            "self_addresses": {
                "state": full.self_addresses.state.value,
                "count": full.self_addresses.count,
                "used": full.self_addresses.used,
            },
            "bridge": {
                "non_ascii_participant_addresses": min(
                    len(corpus.stored_non_ascii), MAX_BRIDGE_ADDRESSES
                ),
                "truncated": len(corpus.stored_non_ascii) > MAX_BRIDGE_ADDRESSES,
                "bridged_spellings": sum(len(spellings) for spellings in bridged.values()),
            },
            "quarantined_identity_kind_mismatch": self._quarantined(IDENTITY_KIND_MISMATCH),
        }

    @staticmethod
    def _targets(
        latency: dict[str, dict[str, object]], meetings: int, lookback_days: int, limit: int
    ) -> dict[str, object]:
        """Ruling D15's targets, for the shapes the arguments measured (others `null`)."""

        def p(name: str, key: str) -> float:
            return float(str(latency[name][key]))

        defaults = (lookback_days, limit) == (DEFAULT_LOOKBACK_DAYS, DEFAULT_PER_MEETING_LIMIT)
        maximum = (lookback_days, limit) == (MAX_LOOKBACK_DAYS, MAX_PER_MEETING_LIMIT)
        full = meetings == MAX_CONTEXT_MEETINGS
        targets: dict[str, object] = {
            "meetings_10_defaults": None,
            "meetings_1_defaults": None,
            "meetings_10_maximum": None,
        }
        if defaults and full:
            p50, p95 = _TARGET_DEFAULTS_10
            targets["meetings_10_defaults"] = {
                pulse: p(f"meetings_10_pulse_{pulse}", "p50_ms") <= p50
                and p(f"meetings_10_pulse_{pulse}", "p95_ms") <= p95
                for pulse in ("off", "on")
            }
        if defaults:
            targets["meetings_1_defaults"] = {
                pulse: p(f"meetings_1_pulse_{pulse}", "p95_ms") <= _TARGET_DEFAULTS_1_P95
                for pulse in ("off", "on")
            }
        if maximum and full:
            targets["meetings_10_maximum"] = {
                pulse: p(f"meetings_10_pulse_{pulse}", "p95_ms") <= _TARGET_MAXIMUM_10_P95
                for pulse in ("off", "on")
            }
        return targets
