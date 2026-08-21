"""Unit tests for the WP-TM-01 task domain: lifecycle, recurrence, history, Task.

These are pure in-process tests: nothing here touches a database. The schema
side of the same work package is `tests/schema/test_task_schema_migration.py`.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.situation.continuity import ContinuityAcceptanceKind, ContinuityEvidenceState
from my_pa.domain.task.history import (
    MAX_CLIENT_CONTEXT_CHARACTERS,
    TaskHistoryEntry,
    TaskMutationAction,
    TaskMutationActor,
    TaskMutationOutcome,
)
from my_pa.domain.task.lifecycle import (
    TERMINAL_TASK_LIFECYCLE_STATES,
    TaskLifecycleState,
    TaskPriority,
    legacy_state_for,
)
from my_pa.domain.task.recurrence import (
    RecurrenceError,
    RecurrenceFrequency,
    RecurrenceRule,
    Weekday,
    next_occurrence,
)
from my_pa.domain.task.task import Task

PRINCIPAL_ID = "prn_aaaa0001aaaa0001aaaa0001"
TASK_ID = "tsk_aaaa0001aaaa0001aaaa"
RECURRENCE_ID = "trec_aaaa0001aaaa0001aaaa"
HISTORY_ID = "thst_aaaa0001aaaa0001aaaa"
EVIDENCE_REF = "cap_aaaa0001aaaa0001aaaa"
REVIEW_DECISION_ID = "rdec_aaaa0001aaaa0001aaaa"

NEW_YORK = ZoneInfo("America/New_York")


def _instant(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


def _ny_local(year: int, month: int, day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(year, month, day, hour, minute, tzinfo=NEW_YORK).astimezone(UTC)


class TestTaskLifecycleState:
    def test_legacy_state_for_maps_terminal_states_to_closed(self) -> None:
        for state in TERMINAL_TASK_LIFECYCLE_STATES:
            assert legacy_state_for(state) == "closed"

    def test_legacy_state_for_maps_non_terminal_states_to_open(self) -> None:
        for state in TaskLifecycleState:
            if state not in TERMINAL_TASK_LIFECYCLE_STATES:
                assert legacy_state_for(state) == "open"

    def test_exactly_two_terminal_states(self) -> None:
        assert {
            TaskLifecycleState.COMPLETED,
            TaskLifecycleState.CANCELLED,
        } == TERMINAL_TASK_LIFECYCLE_STATES

    def test_task_priority_has_four_members(self) -> None:
        assert {member.value for member in TaskPriority} == {"p1", "p2", "p3", "p4"}


class TestRecurrenceRuleValidation:
    def _rule(self, **overrides: object) -> RecurrenceRule:
        fields: dict[str, object] = {
            "recurrence_id": RECURRENCE_ID,
            "principal_id": PRINCIPAL_ID,
            "frequency": RecurrenceFrequency.DAILY,
            "timezone": "America/New_York",
            "anchor_at": _ny_local(2027, 1, 4, 21),
        }
        fields.update(overrides)
        return RecurrenceRule(**fields)  # type: ignore[arg-type]

    def test_a_valid_daily_rule_constructs(self) -> None:
        rule = self._rule()
        assert rule.frequency is RecurrenceFrequency.DAILY
        assert not rule.is_cancelled

    def test_interval_below_one_is_rejected(self) -> None:
        with pytest.raises(RecurrenceError, match="interval"):
            self._rule(interval=0)

    def test_selected_weekdays_requires_at_least_one_weekday(self) -> None:
        with pytest.raises(RecurrenceError, match="selected-weekdays"):
            self._rule(frequency=RecurrenceFrequency.SELECTED_WEEKDAYS)

    def test_weekly_requires_exactly_one_weekday(self) -> None:
        with pytest.raises(RecurrenceError, match="weekly"):
            self._rule(frequency=RecurrenceFrequency.WEEKLY)
        with pytest.raises(RecurrenceError, match="weekly"):
            self._rule(
                frequency=RecurrenceFrequency.WEEKLY,
                weekdays=frozenset({Weekday.MONDAY, Weekday.TUESDAY}),
            )

    def test_weekdays_frequency_auto_fills_monday_to_friday(self) -> None:
        rule = self._rule(frequency=RecurrenceFrequency.WEEKDAYS)
        assert rule.weekdays == frozenset(
            {
                Weekday.MONDAY,
                Weekday.TUESDAY,
                Weekday.WEDNESDAY,
                Weekday.THURSDAY,
                Weekday.FRIDAY,
            }
        )

    def test_daily_or_monthly_rejects_weekdays(self) -> None:
        with pytest.raises(RecurrenceError, match="only weekly"):
            self._rule(weekdays=frozenset({Weekday.MONDAY}))

    def test_invalid_timezone_is_rejected(self) -> None:
        with pytest.raises(RecurrenceError, match="IANA"):
            self._rule(timezone="Not/AZone")

    def test_blank_timezone_is_rejected(self) -> None:
        with pytest.raises(RecurrenceError, match="non-blank"):
            self._rule(timezone="  ")

    def test_naive_anchor_is_rejected(self) -> None:
        with pytest.raises(RecurrenceError, match="timezone-aware"):
            self._rule(anchor_at=datetime(2027, 1, 4, 21))

    def test_invalid_frequency_type_is_rejected(self) -> None:
        with pytest.raises(RecurrenceError, match="one known frequency"):
            self._rule(frequency="daily")

    def test_is_cancelled_reflects_cancelled_at(self) -> None:
        rule = self._rule(cancelled_at=_instant(2027, 2, 1))
        assert rule.is_cancelled


class TestNextOccurrence:
    def test_cancelled_rule_has_no_next_occurrence(self) -> None:
        rule = RecurrenceRule(
            recurrence_id=RECURRENCE_ID,
            principal_id=PRINCIPAL_ID,
            frequency=RecurrenceFrequency.DAILY,
            timezone="America/New_York",
            anchor_at=_ny_local(2027, 1, 4, 21),
            cancelled_at=_instant(2027, 1, 5),
        )
        assert next_occurrence(rule) is None

    def test_daily_nine_pm_stays_nine_pm_local_across_spring_forward(self) -> None:
        # 2027-03-14 is the America/New_York spring-forward date: 02:00 -> 03:00.
        rule = RecurrenceRule(
            recurrence_id=RECURRENCE_ID,
            principal_id=PRINCIPAL_ID,
            frequency=RecurrenceFrequency.DAILY,
            timezone="America/New_York",
            anchor_at=_ny_local(2027, 3, 12, 21),
        )
        before = next_occurrence(rule, after=_instant(2027, 3, 12, 12))
        after_transition = next_occurrence(rule, after=_instant(2027, 3, 14, 12))
        assert before is not None and after_transition is not None
        before_local = before.astimezone(NEW_YORK)
        after_local = after_transition.astimezone(NEW_YORK)
        assert before_local.hour == 21
        assert after_local.hour == 21
        assert before_local.utcoffset() != after_local.utcoffset()

    def test_daily_two_thirty_am_skips_forward_through_the_spring_forward_gap(self) -> None:
        rule = RecurrenceRule(
            recurrence_id=RECURRENCE_ID,
            principal_id=PRINCIPAL_ID,
            frequency=RecurrenceFrequency.DAILY,
            timezone="America/New_York",
            anchor_at=_ny_local(2027, 3, 13, 2, 30),
        )
        occurrence = next_occurrence(rule, after=_instant(2027, 3, 13, 12))
        assert occurrence is not None
        local = occurrence.astimezone(NEW_YORK)
        assert (local.hour, local.minute) == (3, 30)

    def test_daily_one_thirty_am_resolves_to_the_earlier_instant_on_fall_back(self) -> None:
        # 2027-11-07 is the America/New_York fall-back date: 02:00 -> 01:00,
        # so 01:30 local occurs twice; fold=0 must pick the earlier (EDT) one.
        rule = RecurrenceRule(
            recurrence_id=RECURRENCE_ID,
            principal_id=PRINCIPAL_ID,
            frequency=RecurrenceFrequency.DAILY,
            timezone="America/New_York",
            anchor_at=_ny_local(2027, 11, 5, 1, 30),
        )
        occurrence = next_occurrence(rule, after=_instant(2027, 11, 6, 12))
        assert occurrence is not None
        local = occurrence.astimezone(NEW_YORK)
        assert (local.hour, local.minute) == (1, 30)
        assert local.fold == 0
        assert local.utcoffset() == timedelta(hours=-4)

    def test_weekly_returns_the_named_weekday_only(self) -> None:
        rule = RecurrenceRule(
            recurrence_id=RECURRENCE_ID,
            principal_id=PRINCIPAL_ID,
            frequency=RecurrenceFrequency.WEEKLY,
            timezone="UTC",
            anchor_at=_instant(2027, 1, 4, 9),
            weekdays=frozenset({Weekday.MONDAY}),
        )
        occurrence = next_occurrence(rule, after=_instant(2027, 1, 4, 9))
        assert occurrence is not None
        assert Weekday(occurrence.astimezone(UTC).weekday()) is Weekday.MONDAY

    def test_monthly_clamps_to_the_last_real_day_of_the_target_month(self) -> None:
        rule = RecurrenceRule(
            recurrence_id=RECURRENCE_ID,
            principal_id=PRINCIPAL_ID,
            frequency=RecurrenceFrequency.MONTHLY,
            timezone="UTC",
            anchor_at=_instant(2027, 1, 31, 9),
        )
        occurrence = next_occurrence(rule, after=_instant(2027, 1, 31, 9))
        assert occurrence is not None
        assert (occurrence.month, occurrence.day) == (2, 28)

    def test_no_after_returns_the_anchor_when_it_already_matches(self) -> None:
        rule = RecurrenceRule(
            recurrence_id=RECURRENCE_ID,
            principal_id=PRINCIPAL_ID,
            frequency=RecurrenceFrequency.DAILY,
            timezone="UTC",
            anchor_at=_instant(2027, 1, 4, 9),
        )
        assert next_occurrence(rule) == _instant(2027, 1, 4, 9)


class TestTaskHistoryEntry:
    def _entry(self, **overrides: object) -> TaskHistoryEntry:
        fields: dict[str, object] = {
            "history_id": HISTORY_ID,
            "principal_id": PRINCIPAL_ID,
            "task_id": TASK_ID,
            "action": TaskMutationAction.CREATE,
            "actor": TaskMutationActor.PRINCIPAL,
            "outcome": TaskMutationOutcome.APPLIED,
            "before_version": 0,
            "after_version": 1,
            "occurred_at": _instant(2027, 1, 1),
            "recorded_at": _instant(2027, 1, 1),
        }
        fields.update(overrides)
        return TaskHistoryEntry(**fields)  # type: ignore[arg-type]

    def test_a_valid_applied_entry_constructs(self) -> None:
        entry = self._entry()
        assert entry.outcome is TaskMutationOutcome.APPLIED

    def test_applied_outcome_requires_the_version_to_advance(self) -> None:
        with pytest.raises(ValueError, match="advances the version"):
            self._entry(before_version=1, after_version=1)

    def test_rejected_outcome_requires_no_version_change(self) -> None:
        with pytest.raises(ValueError, match="no version change"):
            self._entry(outcome=TaskMutationOutcome.REJECTED, before_version=1, after_version=2)
        entry = self._entry(outcome=TaskMutationOutcome.REJECTED, before_version=1, after_version=1)
        assert entry.outcome is TaskMutationOutcome.REJECTED

    def test_no_op_outcome_requires_no_version_change(self) -> None:
        with pytest.raises(ValueError, match="no version change"):
            self._entry(outcome=TaskMutationOutcome.NO_OP, before_version=1, after_version=2)

    def test_negative_before_version_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-negative"):
            self._entry(before_version=-1, after_version=0, outcome=TaskMutationOutcome.NO_OP)

    def test_idempotency_key_must_match_the_opaque_pattern(self) -> None:
        with pytest.raises(ValueError, match="idempotency key"):
            self._entry(idempotency_key="short")
        entry = self._entry(idempotency_key="a" * 32)
        assert entry.idempotency_key == "a" * 32

    def test_client_context_must_be_non_blank_when_present(self) -> None:
        with pytest.raises(ValueError, match="non-blank"):
            self._entry(client_context="   ")

    def test_client_context_is_bounded(self) -> None:
        with pytest.raises(ValueError, match="exceeds"):
            self._entry(client_context="x" * (MAX_CLIENT_CONTEXT_CHARACTERS + 1))
        entry = self._entry(client_context="x" * MAX_CLIENT_CONTEXT_CHARACTERS)
        assert entry.client_context is not None

    def test_invalid_task_id_is_rejected(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self._entry(task_id="not-an-id")


class TestTask:
    def _task(self, **overrides: object) -> Task:
        fields: dict[str, object] = {
            "task_id": TASK_ID,
            "principal_id": PRINCIPAL_ID,
            "title": "Draft the remediation checkpoint",
            "lifecycle_state": TaskLifecycleState.OPEN,
            "evidence_state": ContinuityEvidenceState.PROPOSED,
            "origin_evidence_ref": EVIDENCE_REF,
            "opened_at": _instant(2027, 1, 1),
            "created_at": _instant(2027, 1, 1),
            "updated_at": _instant(2027, 1, 1),
        }
        fields.update(overrides)
        return Task(**fields)  # type: ignore[arg-type]

    def test_a_minimal_open_task_constructs(self) -> None:
        task = self._task()
        assert task.version == 1
        assert task.closed_at is None

    def test_blank_title_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-blank title"):
            self._task(title="   ")

    def test_priority_must_be_a_known_value(self) -> None:
        with pytest.raises(ValueError, match="one known value"):
            self._task(priority="urgent")
        task = self._task(priority=TaskPriority.P1)
        assert task.priority is TaskPriority.P1

    def test_version_below_one_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="starts at one"):
            self._task(version=0)

    def test_terminal_state_requires_closed_at(self) -> None:
        with pytest.raises(ValueError, match="records when it closed"):
            self._task(lifecycle_state=TaskLifecycleState.COMPLETED)

    def test_non_terminal_state_rejects_closed_at(self) -> None:
        with pytest.raises(ValueError, match="records when it closed"):
            self._task(closed_at=_instant(2027, 1, 2))

    def test_terminal_state_requires_closure_evidence(self) -> None:
        with pytest.raises(ValueError, match="evidence that closed it"):
            self._task(
                lifecycle_state=TaskLifecycleState.CANCELLED,
                closed_at=_instant(2027, 1, 2),
            )

    def test_a_completed_task_with_closure_evidence_constructs(self) -> None:
        task = self._task(
            lifecycle_state=TaskLifecycleState.COMPLETED,
            closed_at=_instant(2027, 1, 2),
            closure_evidence_ref=EVIDENCE_REF,
        )
        assert task.closed_at is not None

    def test_accepted_evidence_state_requires_a_review_decision(self) -> None:
        with pytest.raises(ValueError, match="review decision"):
            self._task(evidence_state=ContinuityEvidenceState.ACCEPTED)

    def test_review_decision_without_accepted_state_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="review decision"):
            self._task(accepted_by_review_decision_id=REVIEW_DECISION_ID)

    def test_an_accepted_task_with_a_review_decision_constructs(self) -> None:
        task = self._task(
            evidence_state=ContinuityEvidenceState.ACCEPTED,
            accepted_by_review_decision_id=REVIEW_DECISION_ID,
        )
        assert task.accepted_by_review_decision_id == REVIEW_DECISION_ID

    def test_a_direct_principal_accepted_task_constructs_without_a_review_decision(self) -> None:
        task = self._task(
            evidence_state=ContinuityEvidenceState.ACCEPTED,
            acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
        )
        assert task.acceptance_kind is ContinuityAcceptanceKind.DIRECT_PRINCIPAL
        assert task.accepted_by_review_decision_id is None

    def test_a_direct_principal_task_rejects_a_review_decision(self) -> None:
        with pytest.raises(ValueError, match="does not cite a review decision"):
            self._task(
                evidence_state=ContinuityEvidenceState.ACCEPTED,
                acceptance_kind=ContinuityAcceptanceKind.DIRECT_PRINCIPAL,
                accepted_by_review_decision_id=REVIEW_DECISION_ID,
            )

    def test_invalid_recurrence_id_is_rejected(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self._task(recurrence_id="not-an-id")

    def test_blank_origin_evidence_ref_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="evidence it was read out of"):
            self._task(origin_evidence_ref="  ")
