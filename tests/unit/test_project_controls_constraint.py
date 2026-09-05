"""Unit tests for the PC-CM-IMP-WP01 ProjectConstraint aggregate.

Pure in-process tests: lifecycle matrix, Publish completeness, terminal
invariants, record quality, attention vocabulary, and In My Court. Nothing
here touches a database.
"""

from __future__ import annotations

import ast
import dataclasses
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

import my_pa.domain.project_controls as project_controls
from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.common.time import NaiveDatetimeError
from my_pa.domain.project_controls.category import ConstraintCategory, ConstraintCategoryState
from my_pa.domain.project_controls.constraint import (
    ACTIVE_CONSTRAINT_LIFECYCLE_STATES,
    DRAFT_CONSTRAINT_LIFECYCLE_STATES,
    TERMINAL_CONSTRAINT_LIFECYCLE_STATES,
    ConstraintAttention,
    ConstraintAttentionReason,
    ConstraintFieldKey,
    ConstraintInvariantError,
    ConstraintLifecycleError,
    ConstraintLifecycleMove,
    ConstraintLifecycleOperation,
    ConstraintLifecycleState,
    ConstraintOrigin,
    ConstraintPublishError,
    ConstraintRecordQuality,
    ProjectConstraint,
    check_lifecycle_move,
    in_my_court,
    missing_publish_fields,
    validate_publish_completeness,
)
from my_pa.domain.project_controls.party import PartyKind, PartyRef

PRINCIPAL_ID = "prn_aaaa0001aaaa0001aaaa0001"
OTHER_PRINCIPAL_ID = "prn_bbbb0002bbbb0002bbbb0002"
PROJECT_ID = "prj_aaaa0001aaaa0001aaaa"
OTHER_PROJECT_ID = "prj_bbbb0002bbbb0002bbbb"
CATEGORY_ID = "ccat_aaaa0001aaaa0001aaaa"
CONSTRAINT_ID = "cst_aaaa0001aaaa0001aaaa"
ENTITY_ID = "ent_aaaa0001aaaa0001aaaa"
OTHER_ENTITY_ID = "ent_bbbb0002bbbb0002bbbb"

T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
D_IDENTIFIED = date(2026, 9, 1)
D_DUE = date(2026, 9, 15)

S = ConstraintLifecycleState
OP = ConstraintLifecycleOperation
PRINCIPAL_PARTY = PartyRef(PartyKind.PRINCIPAL)
ENTITY_PARTY = PartyRef(PartyKind.ENTITY, entity_id=ENTITY_ID, label="Acme")


def _category(
    state: ConstraintCategoryState = ConstraintCategoryState.ACTIVE, **overrides: object
) -> ConstraintCategory:
    fields: dict[str, object] = {
        "category_id": CATEGORY_ID,
        "principal_id": PRINCIPAL_ID,
        "project_id": PROJECT_ID,
        "prefix": "DES",
        "title": "Design",
        "state": state,
        "created_at": T0,
        "updated_at": T0,
    }
    fields.update(overrides)
    return ConstraintCategory(**fields)  # type: ignore[arg-type]


def _draft(**overrides: object) -> ProjectConstraint:
    fields: dict[str, object] = {
        "constraint_id": CONSTRAINT_ID,
        "principal_id": PRINCIPAL_ID,
        "lifecycle_state": S.DRAFT,
        "origin": ConstraintOrigin.PRODUCT,
        "created_at": T0,
        "updated_at": T0,
        "project_id": PROJECT_ID,
        "category_id": CATEGORY_ID,
        "description": "Awaiting structural drawings",
        "date_identified": D_IDENTIFIED,
        "due_date": D_DUE,
        "bic": (ENTITY_PARTY,),
    }
    fields.update(overrides)
    return ProjectConstraint(**fields)  # type: ignore[arg-type]


def _published(
    state: ConstraintLifecycleState = S.IDENTIFIED, **overrides: object
) -> ProjectConstraint:
    fields: dict[str, object] = {
        "lifecycle_state": state,
        "constraint_code": "DES-001",
        "published_at": T0,
        "version": 2,
    }
    fields.update(overrides)
    return _draft(**fields)


# --- CM-BE-AC-001 / 007 / 008: first-class, no Task or Commitment coupling ---


def test_project_controls_never_imports_the_task_or_continuity_domain() -> None:
    package_dir = Path(project_controls.__file__).parent
    forbidden = ("my_pa.domain.task", "my_pa.domain.situation")
    for module_path in package_dir.glob("*.py"):
        tree = ast.parse(module_path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom):
                assert node.module is not None
                assert not node.module.startswith(forbidden), (module_path.name, node.module)
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    assert not alias.name.startswith(forbidden), (module_path.name, alias.name)
    # And at runtime: importing the package does not pull the task domain in.
    for name in sys.modules:
        if name.startswith("my_pa.domain.project_controls"):
            assert "task" not in name


def test_project_constraint_is_its_own_aggregate_and_frozen() -> None:
    draft = _draft()
    assert type(draft).__mro__ == (ProjectConstraint, object)
    with pytest.raises(dataclasses.FrozenInstanceError):
        draft.description = "changed"  # type: ignore[misc]


# --- CM-BE-AC-002 / 003 / 005 / 006: identity contracts ---


def test_draft_has_opaque_id_positive_version_and_no_code() -> None:
    draft = _draft()
    assert draft.constraint_id.startswith("cst_")
    assert draft.version == 1
    assert draft.constraint_code is None
    assert draft.published_at is None
    assert draft.is_published is False


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("constraint_id", "tsk_aaaa0001aaaa0001aaaa"),
        ("constraint_id", "not-an-id"),
        ("principal_id", PROJECT_ID),
        ("project_id", "ent_aaaa0001aaaa0001aaaa"),
        ("project_id", CONSTRAINT_ID),
        ("category_id", PROJECT_ID),
    ],
)
def test_identity_fields_are_validated_by_kind(field: str, value: str) -> None:
    with pytest.raises(InvalidIdentifierError):
        _draft(**{field: value})


def test_project_binding_is_the_continuity_prj_identity() -> None:
    assert _draft().project_id == PROJECT_ID
    assert PROJECT_ID.startswith("prj_")


def test_version_must_be_positive() -> None:
    with pytest.raises(ConstraintInvariantError) as excinfo:
        _draft(version=0)
    assert excinfo.value.code == "constraint_version_not_positive"


def test_instants_are_normalised_to_utc_and_naive_is_refused() -> None:
    aware = datetime(2026, 9, 1, 14, 0, tzinfo=UTC).astimezone(UTC)
    assert _draft(created_at=aware).created_at.tzinfo is UTC
    with pytest.raises(NaiveDatetimeError):
        _draft(created_at=datetime(2026, 9, 1, 12, 0))


# --- CM-BE-AC-004 / 005: Draft vs published shape ---


def test_draft_cannot_carry_a_public_code_or_published_at() -> None:
    with pytest.raises(ConstraintInvariantError) as excinfo:
        _draft(constraint_code="DES-001")
    assert excinfo.value.code == "constraint_draft_has_publication"
    with pytest.raises(ConstraintInvariantError):
        _draft(published_at=T0)


@pytest.mark.parametrize("state", sorted(ACTIVE_CONSTRAINT_LIFECYCLE_STATES))
def test_published_active_record_requires_code_and_published_at(
    state: ConstraintLifecycleState,
) -> None:
    published = _published(state)
    assert published.is_published is True
    assert published.constraint_code == "DES-001"
    with pytest.raises(ConstraintInvariantError) as excinfo:
        _draft(lifecycle_state=state)
    assert excinfo.value.code == "constraint_published_without_code"
    with pytest.raises(ConstraintInvariantError):
        _draft(lifecycle_state=state, constraint_code="DES-001")


def test_blank_code_is_refused() -> None:
    with pytest.raises(ConstraintInvariantError) as excinfo:
        _published(constraint_code="   ")
    assert excinfo.value.code == "constraint_code_blank"


# --- Lifecycle vocabulary and matrix ---


def test_lifecycle_states_are_exactly_the_seven_and_partitioned() -> None:
    assert {s.value for s in S} == {
        "draft",
        "identified",
        "pending",
        "in_progress",
        "on_hold",
        "closed",
        "void",
    }
    assert "reopen" not in {s.value for s in S}
    classes = (
        DRAFT_CONSTRAINT_LIFECYCLE_STATES,
        ACTIVE_CONSTRAINT_LIFECYCLE_STATES,
        TERMINAL_CONSTRAINT_LIFECYCLE_STATES,
    )
    assert frozenset().union(*classes) == frozenset(S)
    assert sum(len(c) for c in classes) == len(S)


def test_lifecycle_operations_are_exactly_five() -> None:
    assert {o.value for o in OP} == {"publish", "transition", "close", "void", "reopen"}


def _required_operation(
    current: ConstraintLifecycleState, target: ConstraintLifecycleState
) -> ConstraintLifecycleOperation | None:
    """The accepted matrix, restated independently of the implementation."""
    active = ACTIVE_CONSTRAINT_LIFECYCLE_STATES
    if current is S.DRAFT and target in active:
        return OP.PUBLISH
    if current in active and target in active:
        return OP.TRANSITION
    if current in active and target is S.CLOSED:
        return OP.CLOSE
    if current in active and target is S.VOID:
        return OP.VOID
    if current in TERMINAL_CONSTRAINT_LIFECYCLE_STATES and target in active:
        return OP.REOPEN
    return None


@pytest.mark.parametrize("operation", list(OP))
@pytest.mark.parametrize("target", list(S))
@pytest.mark.parametrize("current", list(S))
def test_full_lifecycle_matrix_by_operation(
    current: ConstraintLifecycleState,
    target: ConstraintLifecycleState,
    operation: ConstraintLifecycleOperation,
) -> None:
    if current == target:
        if operation is OP.TRANSITION:
            assert check_lifecycle_move(current, target, operation) is ConstraintLifecycleMove.NO_OP
        else:
            with pytest.raises(ConstraintLifecycleError) as excinfo:
                check_lifecycle_move(current, target, operation)
            assert excinfo.value.code == "constraint_lifecycle_operation_mismatch"
        return
    required = _required_operation(current, target)
    if required is None:
        with pytest.raises(ConstraintLifecycleError) as excinfo:
            check_lifecycle_move(current, target, operation)
        assert excinfo.value.code == "constraint_lifecycle_move_prohibited"
    elif operation is required:
        assert check_lifecycle_move(current, target, operation) is ConstraintLifecycleMove.CHANGE
    else:
        with pytest.raises(ConstraintLifecycleError) as excinfo:
            check_lifecycle_move(current, target, operation)
        assert excinfo.value.code == "constraint_lifecycle_operation_mismatch"


def test_matrix_helper_names_every_allowed_move_the_contract_lists() -> None:
    # 4 publish + 12 active-to-other-active + 4 close + 4 void + 8 reopen.
    allowed = [(c, t) for c in S for t in S if c != t and _required_operation(c, t) is not None]
    assert len(allowed) == 32
    prohibited = [(c, t) for c in S for t in S if c != t and _required_operation(c, t) is None]
    # DRAFT->CLOSED/VOID (2), active->DRAFT (4), CLOSED<->VOID (2), terminal->DRAFT (2).
    assert len(prohibited) == 10


@pytest.mark.parametrize("target", sorted(TERMINAL_CONSTRAINT_LIFECYCLE_STATES))
@pytest.mark.parametrize("operation", list(OP))
def test_draft_cannot_become_terminal_by_any_operation(
    target: ConstraintLifecycleState, operation: ConstraintLifecycleOperation
) -> None:
    with pytest.raises(ConstraintLifecycleError) as excinfo:
        check_lifecycle_move(S.DRAFT, target, operation)
    assert excinfo.value.code == "constraint_lifecycle_move_prohibited"


@pytest.mark.parametrize(
    ("current", "target"),
    [
        (S.IDENTIFIED, S.CLOSED),
        (S.ON_HOLD, S.VOID),
        (S.CLOSED, S.IDENTIFIED),
        (S.VOID, S.IN_PROGRESS),
        (S.DRAFT, S.IDENTIFIED),
    ],
)
def test_close_void_reopen_and_publish_are_not_generic_transitions(
    current: ConstraintLifecycleState, target: ConstraintLifecycleState
) -> None:
    with pytest.raises(ConstraintLifecycleError) as excinfo:
        check_lifecycle_move(current, target, OP.TRANSITION)
    assert excinfo.value.code == "constraint_lifecycle_operation_mismatch"


def test_same_state_is_a_no_op_only_as_a_transition() -> None:
    for state in S:
        assert check_lifecycle_move(state, state, OP.TRANSITION) is ConstraintLifecycleMove.NO_OP
    with pytest.raises(ConstraintLifecycleError):
        check_lifecycle_move(S.CLOSED, S.CLOSED, OP.CLOSE)


# --- Terminal invariants ---


def test_closed_requires_completion_date_and_forbids_void_fields() -> None:
    closed = _published(S.CLOSED, completion_date=D_DUE, closure_commentary="done")
    assert closed.completion_date == D_DUE
    with pytest.raises(ConstraintInvariantError) as excinfo:
        _published(S.CLOSED)
    assert excinfo.value.code == "constraint_closed_requires_completion_date"
    with pytest.raises(ConstraintInvariantError) as excinfo:
        _published(S.CLOSED, completion_date=D_DUE, void_reason="no")
    assert excinfo.value.code == "constraint_closed_carries_void_fields"
    with pytest.raises(ConstraintInvariantError):
        _published(S.CLOSED, completion_date=D_DUE, voided_date=D_DUE)


def test_void_requires_date_and_nonblank_reason_and_forbids_completion() -> None:
    void = _published(S.VOID, voided_date=D_DUE, void_reason="duplicate")
    assert void.void_reason == "duplicate"
    for overrides in (
        {"voided_date": D_DUE},
        {"void_reason": "x"},
        {"voided_date": D_DUE, "void_reason": "  "},
    ):
        with pytest.raises(ConstraintInvariantError) as excinfo:
            _published(S.VOID, **overrides)
        assert excinfo.value.code == "constraint_void_requires_reason"
    with pytest.raises(ConstraintInvariantError) as excinfo:
        _published(S.VOID, voided_date=D_DUE, void_reason="dup", completion_date=D_DUE)
    assert excinfo.value.code == "constraint_void_carries_completion_date"


@pytest.mark.parametrize("state", sorted(ACTIVE_CONSTRAINT_LIFECYCLE_STATES | {S.DRAFT}))
@pytest.mark.parametrize(
    "overrides",
    [{"completion_date": D_DUE}, {"voided_date": D_DUE}, {"void_reason": "x"}],
)
def test_non_terminal_states_reject_terminal_fields(
    state: ConstraintLifecycleState, overrides: dict[str, object]
) -> None:
    build = _draft if state is S.DRAFT else _published
    with pytest.raises(ConstraintInvariantError) as excinfo:
        build(lifecycle_state=state, **overrides)
    assert excinfo.value.code == "constraint_active_carries_terminal_fields"


# --- Publish completeness ---


def test_publish_completeness_happy_path_defaults_to_identified() -> None:
    draft = _draft()
    assert missing_publish_fields(draft) == ()
    validate_publish_completeness(draft, _category())
    validate_publish_completeness(draft, _category(), S.ON_HOLD)


@pytest.mark.parametrize(
    ("overrides", "expected"),
    [
        ({"description": None}, ConstraintFieldKey.DESCRIPTION),
        ({"description": "   "}, ConstraintFieldKey.DESCRIPTION),
        ({"bic": ()}, ConstraintFieldKey.BIC),
        ({"project_id": None}, ConstraintFieldKey.PROJECT_ID),
        ({"category_id": None}, ConstraintFieldKey.CATEGORY_ID),
        ({"date_identified": None}, ConstraintFieldKey.DATE_IDENTIFIED),
        ({"due_date": None}, ConstraintFieldKey.DUE_DATE),
    ],
)
def test_publish_reports_each_missing_field(
    overrides: dict[str, object], expected: ConstraintFieldKey
) -> None:
    draft = _draft(**overrides)
    assert missing_publish_fields(draft) == (expected,)
    with pytest.raises(ConstraintPublishError) as excinfo:
        validate_publish_completeness(draft, _category())
    assert excinfo.value.code == "constraint_publish_incomplete"
    assert excinfo.value.missing_fields == (expected,)


def test_publish_reports_all_missing_fields_in_contract_order() -> None:
    draft = _draft(
        project_id=None,
        category_id=None,
        description=None,
        date_identified=None,
        due_date=None,
        bic=(),
    )
    assert missing_publish_fields(draft) == tuple(
        k for k in ConstraintFieldKey if k is not ConstraintFieldKey.CONSTRAINT_CODE
    )


@pytest.mark.parametrize("state", [S.DRAFT, S.CLOSED, S.VOID])
def test_publish_rejects_non_active_initial_state(state: ConstraintLifecycleState) -> None:
    with pytest.raises(ConstraintPublishError) as excinfo:
        validate_publish_completeness(_draft(), _category(), state)
    assert excinfo.value.code == "constraint_publish_state_not_active"


@pytest.mark.parametrize(
    "state", [ConstraintCategoryState.INACTIVE, ConstraintCategoryState.ARCHIVED]
)
def test_publish_requires_an_active_category(state: ConstraintCategoryState) -> None:
    with pytest.raises(ConstraintPublishError) as excinfo:
        validate_publish_completeness(_draft(), _category(state))
    assert excinfo.value.code == "constraint_publish_category_not_active"


@pytest.mark.parametrize(
    "overrides",
    [
        {"principal_id": OTHER_PRINCIPAL_ID},
        {"project_id": OTHER_PROJECT_ID},
        {"category_id": "ccat_bbbb0002bbbb0002bbbb"},
    ],
)
def test_publish_requires_the_drafts_own_category_in_the_same_partition(
    overrides: dict[str, object],
) -> None:
    with pytest.raises(ConstraintPublishError) as excinfo:
        validate_publish_completeness(_draft(), _category(**overrides))
    assert excinfo.value.code == "constraint_publish_category_partition_mismatch"


def test_only_a_draft_of_normal_quality_can_be_published() -> None:
    with pytest.raises(ConstraintPublishError) as excinfo:
        validate_publish_completeness(_published(), _category())
    assert excinfo.value.code == "constraint_publish_not_draft"
    legacy = _draft(
        origin=ConstraintOrigin.LEGACY_WORKBOOK_IMPORT,
        record_quality=ConstraintRecordQuality.LEGACY_INCOMPLETE,
    )
    with pytest.raises(ConstraintPublishError) as excinfo:
        validate_publish_completeness(legacy, _category())
    assert excinfo.value.code == "constraint_publish_quality_not_normal"


# --- Record quality / attention vocabulary ---


def test_record_quality_is_data_quality_not_lifecycle() -> None:
    assert {q.value for q in ConstraintRecordQuality} == {"normal", "legacy_incomplete"}
    assert "legacy_incomplete" not in {s.value for s in S}
    legacy = _published(
        origin=ConstraintOrigin.LEGACY_WORKBOOK_IMPORT,
        record_quality=ConstraintRecordQuality.LEGACY_INCOMPLETE,
        description=None,
        bic=(),
    )
    # Incomplete legacy data sits in an ordinary lifecycle state.
    assert legacy.lifecycle_state is S.IDENTIFIED
    assert missing_publish_fields(legacy) == (
        ConstraintFieldKey.DESCRIPTION,
        ConstraintFieldKey.BIC,
    )
    with pytest.raises(ConstraintInvariantError) as excinfo:
        _draft(record_quality=ConstraintRecordQuality.LEGACY_INCOMPLETE)
    assert excinfo.value.code == "constraint_legacy_quality_requires_legacy_origin"


def test_attention_and_field_vocabulary_is_stable() -> None:
    assert {r.value for r in ConstraintAttentionReason} == {
        "legacy_incomplete",
        "open_sync_conflict",
        "data_quality_exception",
    }
    assert {k.value for k in ConstraintFieldKey} == {
        "project_id",
        "category_id",
        "constraint_code",
        "description",
        "date_identified",
        "due_date",
        "bic",
    }
    assert {o.value for o in ConstraintOrigin} == {"product", "legacy_workbook_import"}


def test_needs_attention_is_derived_from_reasons_not_missing_fields() -> None:
    assert ConstraintAttention().needs_attention is False
    assert ConstraintAttention(missing_fields=(ConstraintFieldKey.BIC,)).needs_attention is False
    flagged = ConstraintAttention(
        reasons=(ConstraintAttentionReason.LEGACY_INCOMPLETE,),
        missing_fields=(ConstraintFieldKey.DESCRIPTION, ConstraintFieldKey.BIC),
    )
    assert flagged.needs_attention is True
    assert flagged.missing_fields == (ConstraintFieldKey.DESCRIPTION, ConstraintFieldKey.BIC)


# --- In My Court ---


@pytest.mark.parametrize("state", sorted(ACTIVE_CONSTRAINT_LIFECYCLE_STATES))
def test_in_my_court_when_bic_contains_principal_and_state_is_active(
    state: ConstraintLifecycleState,
) -> None:
    assert in_my_court(state, (ENTITY_PARTY, PRINCIPAL_PARTY)) is True
    assert in_my_court(state, (ENTITY_PARTY,)) is False


@pytest.mark.parametrize("state", [S.DRAFT, S.CLOSED, S.VOID])
def test_in_my_court_is_false_outside_active_states(state: ConstraintLifecycleState) -> None:
    assert in_my_court(state, (PRINCIPAL_PARTY,)) is False
    assert in_my_court(state, (ENTITY_PARTY,), frozenset({ENTITY_ID})) is False


def test_in_my_court_via_proven_entity_binding_only() -> None:
    assert in_my_court(S.PENDING, (ENTITY_PARTY,), frozenset({ENTITY_ID})) is True
    assert in_my_court(S.PENDING, (ENTITY_PARTY,), frozenset({OTHER_ENTITY_ID})) is False
    assert in_my_court(S.PENDING, (ENTITY_PARTY,)) is False


def test_unresolved_never_yields_in_my_court_and_labels_never_match() -> None:
    unresolved = PartyRef(PartyKind.UNRESOLVED, label="Acme")
    assert unresolved.label == ENTITY_PARTY.label
    # Same wording as a proven entity, yet no identity: never in my court.
    assert in_my_court(S.IDENTIFIED, (unresolved,), frozenset({ENTITY_ID})) is False
    # And the responsible collection plays no part in the rule at all.
    assert in_my_court(S.IDENTIFIED, ()) is False
