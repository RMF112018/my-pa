"""CRL-WP-03 CP-CRL-01: the Capture root lifecycle domain.

FAST, no database. Proves the pure rules every later checkpoint calls into:
the closed vocabularies, alternation from active/0, the projection from an
append-only history (CW-AC-01), honest NO_OP and stale-revision conflict
(CW-008/009), reason normalization and bounds, and the caller-intent digest with
frozen vectors that no clock or generated identifier can move (CW-AC-03).
"""

from __future__ import annotations

import dataclasses
import hashlib
import inspect
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.errors import SafeDetail
from my_pa.domain.capture.errors import CaptureError
from my_pa.domain.capture.lifecycle import (
    INITIAL_LIFECYCLE_REVISION,
    INTENT_DIGEST_SCHEME,
    MAX_LIFECYCLE_REASON_CHARACTERS,
    MAX_LIFECYCLE_REVISION,
    CaptureLifecycleError,
    CaptureLifecycleEvent,
    CaptureLifecycleHistoryError,
    CaptureLifecycleIntent,
    CaptureLifecycleOperation,
    CaptureLifecycleOutcome,
    CaptureLifecycleProjection,
    CaptureLifecycleReasonError,
    CaptureLifecycleReceipt,
    CaptureLifecycleRevisionError,
    CaptureLifecycleState,
    CapturePauseCause,
    CaptureProcessingEligibility,
    CaptureProcessingEligibilityResolver,
    CaptureProcessingSubject,
    CaptureReasonCategory,
    StaleCaptureLifecycleRevisionError,
    decide_transition,
    intent_digest,
    normalize_reason,
    operation_for_revision,
    pause_cause_for,
    project_history,
    state_at_revision,
    target_state,
    validate_expected_revision,
)
from my_pa.domain.common.classification import Classification
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.record_events import (
    CAPTURE_CREATED_FIELDS,
    CHANGED_FIELD_PATTERN,
    RECEIPT_IDENTIFIER_PATTERN,
    field_set,
)

OWNER = "prn_owner00000001"
OTHER_OWNER = "prn_owner00000002"
CAPTURE = "cap_capture000001"
OTHER_CAPTURE = "cap_capture000002"
CORRELATION = "corr_correlation01"
AUDIT = "audit_audit0000001"
DIGEST = "a" * 64
T0 = datetime(2026, 10, 1, 12, 0, tzinfo=UTC)
REASON = "No longer relevant"
SENTINEL_REASON = "zqxj-sentinel-lifecycle-reason-7731"


def _event_id(n: int) -> str:
    return make_identifier(IdKind.CAPTURE_LIFECYCLE_EVENT, f"event{n:08d}")


def _history(
    length: int, *, owner: str = OWNER, capture: str = CAPTURE
) -> list[CaptureLifecycleEvent]:
    """A valid history of `length` events built through the decision path."""
    events: list[CaptureLifecycleEvent] = []
    projection = CaptureLifecycleProjection.initial(owner_principal_id=owner, capture_id=capture)
    for n in range(1, length + 1):
        operation = operation_for_revision(n)
        decision = decide_transition(projection, operation, projection.revision)
        event = CaptureLifecycleEvent.following(
            projection,
            decision,
            event_id=_event_id(n),
            transitioned_at=T0 + timedelta(minutes=n),
            intent_digest=DIGEST,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
        )
        events.append(event)
        projection = CaptureLifecycleProjection.from_latest(
            owner_principal_id=owner, capture_id=capture, latest=event
        )
    return events


# --- closed vocabularies -----------------------------------------------------------


def test_the_lifecycle_vocabularies_are_closed() -> None:
    assert {member.value for member in CaptureLifecycleState} == {"active", "archived"}
    assert {member.value for member in CaptureLifecycleOperation} == {"archive", "restore"}
    assert {member.value for member in CaptureLifecycleOutcome} == {"applied", "no_op"}
    assert {member.value for member in CaptureReasonCategory} == {"owner_stated"}
    assert {member.value for member in CapturePauseCause} == {
        "capture_withdrawn",
        "current_policy_ineligible",
    }
    assert {member.value for member in CaptureProcessingEligibility} == {
        "eligible",
        "ineligible",
    }


def test_no_delete_or_purge_operation_exists() -> None:
    for alias in ("delete", "purge", "destroy", "erase", "undo", "hard_delete"):
        with pytest.raises(ValueError):
            CaptureLifecycleOperation(alias)


def test_lifecycle_refusals_are_capture_errors() -> None:
    for error in (
        CaptureLifecycleReasonError,
        CaptureLifecycleRevisionError,
        StaleCaptureLifecycleRevisionError,
        CaptureLifecycleHistoryError,
    ):
        assert issubclass(error, CaptureLifecycleError)
        assert issubclass(error, CaptureError)


def test_the_lifecycle_identifier_kinds_are_distinct_and_receipt_shaped() -> None:
    assert IdKind.CAPTURE_LIFECYCLE_EVENT.value == "clev"
    assert IdKind.CAPTURE_LIFECYCLE_RECEIPT.value == "clrcpt"
    receipt = make_identifier(IdKind.CAPTURE_LIFECYCLE_RECEIPT, "receipt0001")
    assert RECEIPT_IDENTIFIER_PATTERN.fullmatch(receipt)


def test_the_lifecycle_safe_details_are_field_and_subject_tokens() -> None:
    assert SafeDetail.EXPECTED_LIFECYCLE_REVISION.value == "expected_lifecycle_revision"
    assert SafeDetail.CAPTURE_WITHDRAWN.value == "capture_withdrawn"
    # Reused, not redeclared.
    assert SafeDetail.LIFECYCLE.value == "lifecycle"
    assert SafeDetail.REASON.value == "reason"
    assert SafeDetail.IDEMPOTENCY_KEY.value == "idempotency_key"


# --- CAPTURE_LIFECYCLE_FIELDS (plan (b.3)) ------------------------------------------


def test_the_lifecycle_changed_fields_are_the_three_read_fields() -> None:
    from my_pa.domain.record_events import CAPTURE_LIFECYCLE_FIELDS

    assert CAPTURE_LIFECYCLE_FIELDS == ("archived_at", "lifecycle_revision", "lifecycle_state")
    assert field_set(*CAPTURE_LIFECYCLE_FIELDS) == CAPTURE_LIFECYCLE_FIELDS
    assert all(CHANGED_FIELD_PATTERN.fullmatch(token) for token in CAPTURE_LIFECYCLE_FIELDS)
    assert "reason" not in CAPTURE_LIFECYCLE_FIELDS
    # MR-C03: create events are unchanged and never name the lifecycle fields.
    assert not set(CAPTURE_LIFECYCLE_FIELDS) & set(CAPTURE_CREATED_FIELDS)


# --- revision and alternation rules ------------------------------------------------


@pytest.mark.parametrize(
    ("revision", "state"),
    [
        (0, CaptureLifecycleState.ACTIVE),
        (1, CaptureLifecycleState.ARCHIVED),
        (2, CaptureLifecycleState.ACTIVE),
        (3, CaptureLifecycleState.ARCHIVED),
        (10, CaptureLifecycleState.ACTIVE),
    ],
)
def test_state_alternates_from_active_zero(revision: int, state: CaptureLifecycleState) -> None:
    assert state_at_revision(revision) is state


@pytest.mark.parametrize(
    ("revision", "operation"),
    [
        (1, CaptureLifecycleOperation.ARCHIVE),
        (2, CaptureLifecycleOperation.RESTORE),
        (3, CaptureLifecycleOperation.ARCHIVE),
        (4, CaptureLifecycleOperation.RESTORE),
    ],
)
def test_odd_revisions_archive_and_even_revisions_restore(
    revision: int, operation: CaptureLifecycleOperation
) -> None:
    assert operation_for_revision(revision) is operation
    assert target_state(operation) is state_at_revision(revision)


def test_revision_zero_is_reached_by_no_operation() -> None:
    with pytest.raises(CaptureLifecycleRevisionError):
        operation_for_revision(0)


@pytest.mark.parametrize("value", [True, False, -1, 1.0, "0", None, MAX_LIFECYCLE_REVISION + 1])
def test_a_malformed_expected_revision_is_refused(value: object) -> None:
    with pytest.raises(CaptureLifecycleRevisionError):
        validate_expected_revision(value)


@pytest.mark.parametrize("value", [0, 1, 2, MAX_LIFECYCLE_REVISION])
def test_a_well_formed_expected_revision_is_returned(value: int) -> None:
    assert validate_expected_revision(value) == value


def test_an_event_whose_operation_breaks_alternation_is_unrepresentable() -> None:
    with pytest.raises(CaptureLifecycleHistoryError):
        CaptureLifecycleEvent(
            event_id=_event_id(1),
            owner_principal_id=OWNER,
            capture_id=CAPTURE,
            lifecycle_revision=1,
            operation=CaptureLifecycleOperation.RESTORE,
            resulting_state=CaptureLifecycleState.ACTIVE,
            predecessor_event_id=None,
            predecessor_revision=None,
            transitioned_at=T0,
            intent_digest=DIGEST,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
        )


def test_an_event_whose_resulting_state_disagrees_with_its_operation_is_unrepresentable() -> None:
    with pytest.raises(CaptureLifecycleHistoryError):
        CaptureLifecycleEvent(
            event_id=_event_id(1),
            owner_principal_id=OWNER,
            capture_id=CAPTURE,
            lifecycle_revision=1,
            operation=CaptureLifecycleOperation.ARCHIVE,
            resulting_state=CaptureLifecycleState.ACTIVE,
            predecessor_event_id=None,
            predecessor_revision=None,
            transitioned_at=T0,
            intent_digest=DIGEST,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
        )


@pytest.mark.parametrize(
    ("revision", "predecessor_event_id", "predecessor_revision"),
    [
        (1, _event_id(0), 0),  # the first event has no predecessor
        (2, None, None),  # every later one has one
        (2, _event_id(1), None),  # both halves or neither
        (3, _event_id(1), 1),  # the immediately prior revision only
    ],
)
def test_predecessor_linkage_is_contiguous(
    revision: int, predecessor_event_id: str | None, predecessor_revision: int | None
) -> None:
    with pytest.raises(CaptureLifecycleHistoryError):
        CaptureLifecycleEvent(
            event_id=_event_id(revision),
            owner_principal_id=OWNER,
            capture_id=CAPTURE,
            lifecycle_revision=revision,
            operation=operation_for_revision(revision),
            resulting_state=state_at_revision(revision),
            predecessor_event_id=predecessor_event_id,
            predecessor_revision=predecessor_revision,
            transitioned_at=T0,
            intent_digest=DIGEST,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
        )


def test_an_event_records_only_the_owner_stated_category_and_no_reason() -> None:
    (event,) = _history(1)
    assert event.reason_category is CaptureReasonCategory.OWNER_STATED
    assert "reason" not in {f.name for f in dataclasses.fields(CaptureLifecycleEvent)}


# --- state projection (CW-AC-01) ---------------------------------------------------


def test_state_projection_from_events() -> None:
    """CW-AC-01: lifecycle 0 -> 1 -> 2 is a separate, append-only history."""
    initial = project_history(owner_principal_id=OWNER, capture_id=CAPTURE, events=[])
    assert initial == CaptureLifecycleProjection.initial(
        owner_principal_id=OWNER, capture_id=CAPTURE
    )
    assert (initial.state, initial.revision, initial.archived_at, initial.latest_event_id) == (
        CaptureLifecycleState.ACTIVE,
        0,
        None,
        None,
    )

    archive, restore = _history(2)
    after_archive = project_history(owner_principal_id=OWNER, capture_id=CAPTURE, events=[archive])
    assert after_archive.state is CaptureLifecycleState.ARCHIVED
    assert after_archive.revision == 1
    assert after_archive.archived_at == archive.transitioned_at
    assert after_archive.latest_event_id == archive.event_id

    after_restore = project_history(
        owner_principal_id=OWNER, capture_id=CAPTURE, events=[archive, restore]
    )
    assert after_restore.state is CaptureLifecycleState.ACTIVE
    assert after_restore.revision == 2
    assert after_restore.archived_at is None
    assert after_restore.latest_event_id == restore.event_id
    # The earlier withdrawal event is still in the history; restore removed nothing.
    assert restore.predecessor_event_id == archive.event_id
    assert restore.predecessor_revision == 1


def test_a_later_archive_opens_a_new_interval() -> None:
    """CW-005: a re-archive has its own interval time, without erasing the first."""
    events = _history(3)
    projection = project_history(owner_principal_id=OWNER, capture_id=CAPTURE, events=events)
    assert projection.state is CaptureLifecycleState.ARCHIVED
    assert projection.archived_at == events[2].transitioned_at
    assert projection.archived_at != events[0].transitioned_at


def test_from_latest_agrees_with_the_full_fold() -> None:
    for length in range(5):
        events = _history(length)
        latest = events[-1] if events else None
        assert project_history(
            owner_principal_id=OWNER, capture_id=CAPTURE, events=events
        ) == CaptureLifecycleProjection.from_latest(
            owner_principal_id=OWNER, capture_id=CAPTURE, latest=latest
        )


def test_a_history_with_a_gap_is_a_broken_store() -> None:
    events = _history(3)
    with pytest.raises(CaptureLifecycleHistoryError):
        project_history(owner_principal_id=OWNER, capture_id=CAPTURE, events=[events[0], events[2]])


def test_a_history_not_starting_at_one_is_a_broken_store() -> None:
    events = _history(2)
    with pytest.raises(CaptureLifecycleHistoryError):
        project_history(owner_principal_id=OWNER, capture_id=CAPTURE, events=[events[1]])


def test_a_mislinked_predecessor_is_a_broken_store() -> None:
    first, second = _history(2)
    forked = dataclasses.replace(second, predecessor_event_id=_event_id(99))
    with pytest.raises(CaptureLifecycleHistoryError):
        project_history(owner_principal_id=OWNER, capture_id=CAPTURE, events=[first, forked])


@pytest.mark.parametrize(("owner", "capture"), [(OTHER_OWNER, CAPTURE), (OWNER, OTHER_CAPTURE)])
def test_a_foreign_event_never_projects_onto_a_root(owner: str, capture: str) -> None:
    events = _history(1, owner=owner, capture=capture)
    with pytest.raises(CaptureLifecycleHistoryError):
        project_history(owner_principal_id=OWNER, capture_id=CAPTURE, events=events)
    with pytest.raises(CaptureLifecycleHistoryError):
        CaptureLifecycleProjection.from_latest(
            owner_principal_id=OWNER, capture_id=CAPTURE, latest=events[0]
        )


def test_an_inconsistent_projection_is_unrepresentable() -> None:
    with pytest.raises(CaptureLifecycleHistoryError):  # state disagrees with revision
        CaptureLifecycleProjection(
            owner_principal_id=OWNER,
            capture_id=CAPTURE,
            state=CaptureLifecycleState.ARCHIVED,
            revision=2,
            archived_at=T0,
            latest_event_id=_event_id(2),
        )
    with pytest.raises(CaptureLifecycleHistoryError):  # active with an archive time
        CaptureLifecycleProjection(
            owner_principal_id=OWNER,
            capture_id=CAPTURE,
            state=CaptureLifecycleState.ACTIVE,
            revision=2,
            archived_at=T0,
            latest_event_id=_event_id(2),
        )
    with pytest.raises(CaptureLifecycleHistoryError):  # revision 0 names an event
        CaptureLifecycleProjection(
            owner_principal_id=OWNER,
            capture_id=CAPTURE,
            state=CaptureLifecycleState.ACTIVE,
            revision=0,
            archived_at=None,
            latest_event_id=_event_id(1),
        )


# --- decisions: APPLIED, NO_OP, stale (CW-008/009) ---------------------------------


def test_fresh_archive_of_an_active_root_applies_one_transition() -> None:
    projection = CaptureLifecycleProjection.initial(owner_principal_id=OWNER, capture_id=CAPTURE)
    decision = decide_transition(projection, CaptureLifecycleOperation.ARCHIVE, 0)
    assert decision.outcome is CaptureLifecycleOutcome.APPLIED
    assert (decision.expected_lifecycle_revision, decision.resulting_lifecycle_revision) == (0, 1)
    assert decision.resulting_state is CaptureLifecycleState.ARCHIVED


def test_fresh_restore_of_an_archived_root_applies_one_transition() -> None:
    (archive,) = _history(1)
    projection = CaptureLifecycleProjection.from_latest(
        owner_principal_id=OWNER, capture_id=CAPTURE, latest=archive
    )
    decision = decide_transition(projection, CaptureLifecycleOperation.RESTORE, 1)
    assert decision.outcome is CaptureLifecycleOutcome.APPLIED
    assert (decision.expected_lifecycle_revision, decision.resulting_lifecycle_revision) == (1, 2)
    assert decision.resulting_state is CaptureLifecycleState.ACTIVE


@pytest.mark.parametrize(
    ("length", "operation"),
    [
        (0, CaptureLifecycleOperation.RESTORE),
        (1, CaptureLifecycleOperation.ARCHIVE),
        (2, CaptureLifecycleOperation.RESTORE),
        (3, CaptureLifecycleOperation.ARCHIVE),
    ],
)
def test_a_fresh_same_state_request_is_an_honest_no_op(
    length: int, operation: CaptureLifecycleOperation
) -> None:
    events = _history(length)
    projection = project_history(owner_principal_id=OWNER, capture_id=CAPTURE, events=events)
    decision = decide_transition(projection, operation, length)
    assert decision.outcome is CaptureLifecycleOutcome.NO_OP
    assert decision.resulting_lifecycle_revision == decision.expected_lifecycle_revision == length
    assert decision.resulting_state is projection.state
    # A NO_OP appends nothing, so the archive time is never reset.
    with pytest.raises(CaptureLifecycleHistoryError):
        CaptureLifecycleEvent.following(
            projection,
            decision,
            event_id=_event_id(99),
            transitioned_at=T0 + timedelta(days=1),
            intent_digest=DIGEST,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
        )


@pytest.mark.parametrize("operation", list(CaptureLifecycleOperation))
@pytest.mark.parametrize("expected", [0, 2, 3])
def test_a_stale_expected_revision_conflicts_even_when_state_already_desired(
    operation: CaptureLifecycleOperation, expected: int
) -> None:
    (archive,) = _history(1)
    projection = CaptureLifecycleProjection.from_latest(
        owner_principal_id=OWNER, capture_id=CAPTURE, latest=archive
    )
    with pytest.raises(StaleCaptureLifecycleRevisionError) as caught:
        decide_transition(projection, operation, expected)
    assert str(expected) not in str(caught.value)
    assert "1" not in str(caught.value)


def test_a_malformed_expected_revision_is_invalid_not_stale() -> None:
    projection = CaptureLifecycleProjection.initial(owner_principal_id=OWNER, capture_id=CAPTURE)
    with pytest.raises(CaptureLifecycleRevisionError):
        decide_transition(projection, CaptureLifecycleOperation.ARCHIVE, True)


def test_an_applied_event_follows_only_the_projection_it_was_decided_on() -> None:
    projection = CaptureLifecycleProjection.initial(owner_principal_id=OWNER, capture_id=CAPTURE)
    decision = decide_transition(projection, CaptureLifecycleOperation.ARCHIVE, 0)
    other = CaptureLifecycleProjection.initial(owner_principal_id=OWNER, capture_id=OTHER_CAPTURE)
    with pytest.raises(CaptureLifecycleHistoryError):
        CaptureLifecycleEvent.following(
            other,
            decision,
            event_id=_event_id(1),
            transitioned_at=T0,
            intent_digest=DIGEST,
            correlation_id=CORRELATION,
            audit_id=AUDIT,
        )


# --- receipts (plan (e.2)) ---------------------------------------------------------


def _receipt(**overrides: object) -> CaptureLifecycleReceipt:
    values: dict[str, object] = {
        "receipt_id": make_identifier(IdKind.CAPTURE_LIFECYCLE_RECEIPT, "receipt0001"),
        "owner_principal_id": OWNER,
        "idempotency_key": "key-1",
        "capture_id": CAPTURE,
        "operation": CaptureLifecycleOperation.ARCHIVE,
        "intent_digest": DIGEST,
        "expected_lifecycle_revision": 0,
        "resulting_lifecycle_revision": 1,
        "outcome": CaptureLifecycleOutcome.APPLIED,
        "event_id": _event_id(1),
        "issued_at": T0,
        "correlation_id": CORRELATION,
        "audit_id": AUDIT,
    }
    values.update(overrides)
    return CaptureLifecycleReceipt(**values)  # type: ignore[arg-type]


def test_honest_receipt_outcomes_are_representable() -> None:
    _receipt()
    _receipt(
        outcome=CaptureLifecycleOutcome.NO_OP,
        operation=CaptureLifecycleOperation.RESTORE,
        resulting_lifecycle_revision=0,
        event_id=None,
    )
    _receipt(
        outcome=CaptureLifecycleOutcome.NO_OP,
        expected_lifecycle_revision=1,
        resulting_lifecycle_revision=1,
        event_id=_event_id(1),
    )


@pytest.mark.parametrize(
    "overrides",
    [
        {"resulting_lifecycle_revision": 0},  # applied without a move
        {"resulting_lifecycle_revision": 2},  # applied by two
        {"event_id": None},  # applied without its event
        {"outcome": CaptureLifecycleOutcome.NO_OP},  # no-op that moved
        {  # a no-op at revision zero naming an event
            "outcome": CaptureLifecycleOutcome.NO_OP,
            "resulting_lifecycle_revision": 0,
        },
        {  # a no-op past revision zero naming none
            "outcome": CaptureLifecycleOutcome.NO_OP,
            "expected_lifecycle_revision": 1,
            "resulting_lifecycle_revision": 1,
            "event_id": None,
        },
        {"idempotency_key": ""},
    ],
)
def test_a_dishonest_receipt_is_unrepresentable(overrides: dict[str, object]) -> None:
    with pytest.raises(CaptureLifecycleHistoryError):
        _receipt(**overrides)


def test_a_receipt_holds_no_reason_and_its_repr_omits_the_key() -> None:
    receipt = _receipt(idempotency_key="zqxj-sentinel-key-0042")
    assert "reason" not in {f.name for f in dataclasses.fields(CaptureLifecycleReceipt)}
    assert "zqxj-sentinel-key-0042" not in repr(receipt)


# --- reason normalization and bounds (CW-007) --------------------------------------


def test_reason_bounds_0_and_501_code_points_refused() -> None:
    """CW-AC-03: the trimmed reason holds 1..500 code points."""
    assert MAX_LIFECYCLE_REASON_CHARACTERS == 500
    for refused in ("", " ", "\t\n 　", "x" * 501, " " + "é" * 501 + " "):
        with pytest.raises(CaptureLifecycleReasonError):
            normalize_reason(refused)
    assert normalize_reason("x") == "x"
    assert normalize_reason("x" * 500) == "x" * 500
    # Code points, not bytes: 500 four-byte characters are within the bound.
    assert normalize_reason("\U0001f600" * 500) == "\U0001f600" * 500
    # Boundary whitespace does not count against the bound.
    assert normalize_reason("  " + "x" * 500 + "\n") == "x" * 500


def test_reason_normalization_trims_only_the_boundary() -> None:
    assert normalize_reason("  No  longer\trelevant \n") == "No  longer\trelevant"
    assert normalize_reason("Done") != normalize_reason("done")
    assert normalize_reason("Café") != normalize_reason("Café")
    assert normalize_reason(normalize_reason("  x  ")) == "x"


@pytest.mark.parametrize("value", [None, 7, b"bytes", ["x"], "\ud800 lone surrogate"])
def test_a_malformed_reason_is_refused(value: object) -> None:
    with pytest.raises(CaptureLifecycleReasonError):
        normalize_reason(value)


def test_a_reason_refusal_never_carries_the_reason() -> None:
    for value in (" " * 3, SENTINEL_REASON * 20):
        with pytest.raises(CaptureLifecycleReasonError) as caught:
            normalize_reason(value)
        assert SENTINEL_REASON not in str(caught.value)
        assert SENTINEL_REASON not in repr(caught.value)


def test_an_intent_normalizes_its_reason_and_hides_it_from_repr() -> None:
    intent = CaptureLifecycleIntent(
        owner_principal_id=OWNER,
        capture_id=CAPTURE,
        operation=CaptureLifecycleOperation.ARCHIVE,
        expected_lifecycle_revision=0,
        reason=f"  {SENTINEL_REASON}  ",
    )
    assert intent.reason == SENTINEL_REASON
    assert SENTINEL_REASON not in repr(intent)
    assert SENTINEL_REASON not in intent.digest


# --- the caller-intent digest (CW-007, CW-AC-03) -----------------------------------

#: Frozen vectors. A change to any of these is a change to every stored digest,
#: so it is a new `INTENT_DIGEST_SCHEME`, never an edit to this table.
FROZEN_VECTORS = [
    (
        OWNER,
        CaptureLifecycleOperation.ARCHIVE,
        CAPTURE,
        0,
        "No longer relevant",
        "fcfc7df39f4174ce1a0c3f688636f0c516cf742cbe41535b0bfdf0779b7a27b1",
    ),
    (
        OWNER,
        CaptureLifecycleOperation.RESTORE,
        CAPTURE,
        1,
        "No longer relevant",
        "798a38e25a0040805ba826aba2b1f78c1d874c33c82c05fedd56911d23f31c96",
    ),
    (
        OWNER,
        CaptureLifecycleOperation.ARCHIVE,
        CAPTURE,
        2,
        "Café notes — duplicate",
        "b854af0067dba045089ecf850c7b806366274c61a040f9f1972614758d7d3e9d",
    ),
    (  # case is significant
        OWNER,
        CaptureLifecycleOperation.ARCHIVE,
        CAPTURE,
        0,
        "no longer relevant",
        "454f0f8d2b94d4fc427f3d4f24e426adb27510f36dd1efee05e0ebe55e5b7cc7",
    ),
    (  # internal whitespace is significant
        OWNER,
        CaptureLifecycleOperation.ARCHIVE,
        CAPTURE,
        0,
        "No  longer relevant",
        "0e51263a5310cac1ef5cc8f752e4ee43ed29739806848069bd8d9363e85e4e54",
    ),
    (  # NFD ...
        OWNER,
        CaptureLifecycleOperation.ARCHIVE,
        CAPTURE,
        0,
        "Café",
        "7949c07c4ceffea4b439acb2499ed4587a55f4cf2a01b0bc966d232806b95398",
    ),
    (  # ... and NFC are different intents: no Unicode normalization
        OWNER,
        CaptureLifecycleOperation.ARCHIVE,
        CAPTURE,
        0,
        "Café",
        "1c36bacf326889e00e1e3e650a17cd4e82489977088fb1af835aa0089a232ab2",
    ),
    (  # the owning partition is material
        OTHER_OWNER,
        CaptureLifecycleOperation.ARCHIVE,
        CAPTURE,
        0,
        "No longer relevant",
        "57d89ff243b7fc2eae8977ec181aa7820734be7f158ac268a7dde02f72db5a33",
    ),
    (  # the root is material
        OWNER,
        CaptureLifecycleOperation.ARCHIVE,
        OTHER_CAPTURE,
        0,
        "No longer relevant",
        "eda3c683abc6a6ee507ebb4e92bc79aa89873c9c3665f8d56df40628b42b19d8",
    ),
]


@pytest.mark.parametrize(
    ("owner", "operation", "capture", "revision", "reason", "expected"), FROZEN_VECTORS
)
def test_digest_vectors_are_frozen(
    owner: str,
    operation: CaptureLifecycleOperation,
    capture: str,
    revision: int,
    reason: str,
    expected: str,
) -> None:
    assert (
        intent_digest(
            owner_principal_id=owner,
            operation=operation,
            capture_id=capture,
            expected_lifecycle_revision=revision,
            reason=reason,
        )
        == expected
    )


def test_the_digest_material_is_the_documented_canonical_json() -> None:
    """The first vector, recomputed from its literal material with no module code."""
    assert INTENT_DIGEST_SCHEME == "capture-lifecycle-intent-v1"
    material = (
        '{"capture_id":"cap_capture000001","expected_lifecycle_revision":0,'
        '"operation":"archive","owner_principal_id":"prn_owner00000001",'
        '"reason":"No longer relevant","scheme":"capture-lifecycle-intent-v1"}'
    )
    assert hashlib.sha256(material.encode("ascii")).hexdigest() == FROZEN_VECTORS[0][-1]


def test_every_frozen_vector_is_distinct() -> None:
    assert len({vector[-1] for vector in FROZEN_VECTORS}) == len(FROZEN_VECTORS)


def test_digest_ignores_clock_and_ids() -> None:
    """CW-AC-03: no time or generated identifier can enter the digest."""
    assert set(inspect.signature(intent_digest).parameters) == {
        "owner_principal_id",
        "operation",
        "capture_id",
        "expected_lifecycle_revision",
        "reason",
    }
    intent_fields = {f.name for f in dataclasses.fields(CaptureLifecycleIntent)}
    assert intent_fields == set(inspect.signature(intent_digest).parameters)

    first = CaptureLifecycleIntent(
        owner_principal_id=OWNER,
        capture_id=CAPTURE,
        operation=CaptureLifecycleOperation.ARCHIVE,
        expected_lifecycle_revision=0,
        reason=REASON,
    )
    # Two events and receipts minted for the same intent at different times,
    # with different generated ids, bind the same digest.
    digests = set()
    for n, moment in enumerate((T0, T0 + timedelta(days=400))):
        projection = CaptureLifecycleProjection.initial(
            owner_principal_id=OWNER, capture_id=CAPTURE
        )
        decision = decide_transition(projection, first.operation, 0)
        event = CaptureLifecycleEvent.following(
            projection,
            decision,
            event_id=_event_id(n + 1),
            transitioned_at=moment,
            intent_digest=first.digest,
            correlation_id=make_identifier(IdKind.CORRELATION, f"corr{n:08d}"),
            audit_id=make_identifier(IdKind.AUDIT, f"audit{n:08d}"),
        )
        digests.add(event.intent_digest)
    assert digests == {FROZEN_VECTORS[0][-1]}


def test_digest_is_over_the_normalized_reason() -> None:
    def digest(reason: str) -> str:
        return intent_digest(
            owner_principal_id=OWNER,
            operation=CaptureLifecycleOperation.ARCHIVE,
            capture_id=CAPTURE,
            expected_lifecycle_revision=0,
            reason=reason,
        )

    assert digest("  No longer relevant\n") == digest("No longer relevant")


@pytest.mark.parametrize(
    "change",
    [
        {"operation": CaptureLifecycleOperation.RESTORE},
        {"capture_id": OTHER_CAPTURE},
        {"expected_lifecycle_revision": 1},
        {"reason": "No longer relevant."},
        {"owner_principal_id": OTHER_OWNER},
    ],
)
def test_changed_intent_changes_the_digest(change: dict[str, object]) -> None:
    base: dict[str, object] = {
        "owner_principal_id": OWNER,
        "operation": CaptureLifecycleOperation.ARCHIVE,
        "capture_id": CAPTURE,
        "expected_lifecycle_revision": 0,
        "reason": REASON,
    }
    assert intent_digest(**{**base, **change}) != intent_digest(**base)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "bad",
    [
        {"owner_principal_id": "cap_capture000001"},
        {"capture_id": "prn_owner00000001"},
        {"expected_lifecycle_revision": True},
        {"operation": "delete"},
        {"reason": "   "},
    ],
)
def test_the_digest_refuses_malformed_intent(bad: dict[str, object]) -> None:
    base: dict[str, object] = {
        "owner_principal_id": OWNER,
        "operation": CaptureLifecycleOperation.ARCHIVE,
        "capture_id": CAPTURE,
        "expected_lifecycle_revision": 0,
        "reason": REASON,
    }
    with pytest.raises((ValueError, CaptureError)):
        intent_digest(**{**base, **bad})  # type: ignore[arg-type]


# --- then-current eligibility (CW-016, MR-C12) -------------------------------------


class _Refusing:
    def eligibility(self, subject: CaptureProcessingSubject) -> CaptureProcessingEligibility:
        return CaptureProcessingEligibility.INELIGIBLE


def test_the_eligibility_resolver_is_a_structural_seam() -> None:
    resolver: CaptureProcessingEligibilityResolver = _Refusing()
    subject = CaptureProcessingSubject(
        owner_principal_id=OWNER,
        capture_id=CAPTURE,
        version_id="capver_version00001",
        processing_policy="local_only",
        classification=Classification.PRIVATE_LOCAL,
    )
    assert resolver.eligibility(subject) is CaptureProcessingEligibility.INELIGIBLE
    assert "text" not in {f.name for f in dataclasses.fields(CaptureProcessingSubject)}


@pytest.mark.parametrize(
    ("state", "eligibility", "cause"),
    [
        (CaptureLifecycleState.ACTIVE, CaptureProcessingEligibility.ELIGIBLE, None),
        (
            CaptureLifecycleState.ACTIVE,
            CaptureProcessingEligibility.INELIGIBLE,
            CapturePauseCause.CURRENT_POLICY_INELIGIBLE,
        ),
        (
            CaptureLifecycleState.ARCHIVED,
            CaptureProcessingEligibility.ELIGIBLE,
            CapturePauseCause.CAPTURE_WITHDRAWN,
        ),
        (
            CaptureLifecycleState.ARCHIVED,
            CaptureProcessingEligibility.INELIGIBLE,
            CapturePauseCause.CAPTURE_WITHDRAWN,
        ),
    ],
)
def test_archive_dominates_then_current_policy(
    state: CaptureLifecycleState,
    eligibility: CaptureProcessingEligibility,
    cause: CapturePauseCause | None,
) -> None:
    assert pause_cause_for(state, eligibility) is cause


def test_the_initial_revision_is_zero() -> None:
    assert INITIAL_LIFECYCLE_REVISION == 0
