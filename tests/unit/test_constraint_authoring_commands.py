"""The twelve authoring commands as request shapes (PC-CM-IMP-WP07).

What a caller may state, and what it may not. Four claims:

**No principal authority.** No command carries a `principal_id` field. The
authenticated Principal is the transport's parameter and never a request field
(`CM-BE-AC-083`); the envelope's own `principal_id` is correlation input and is
covered by `tests/contract/test_constraint_authoring_mcp_admission.py`.

**No server-issued code.** No command carries `constraint_code`. The public code
is allocated under the Category row lock by the WP06 service, and a field here
would be a caller choosing one.

**`expected_version` where a record already exists.** Required on the ten that
name one and absent from the two that create one, which is `CM-BE-AC-082` as a
shape rather than as a runtime check.

**A closed patch, not a raw one.** `UpdateConstraint` enumerates every settable
field and takes a closed `ConstraintUpdateField` clear list rather than the
`Mapping[str, object]` the WP06 method takes internally, and the two are held
equal to `UPDATABLE_FIELDS` so they cannot drift.
"""

from __future__ import annotations

import dataclasses
from datetime import date, datetime
from typing import Final

import pytest

from my_pa.application.commands import (
    CloseConstraint,
    CloseConstraintWithFollowUp,
    Command,
    ConstraintUpdateField,
    CreateConstraintCategory,
    CreateConstraintDraft,
    DeactivateConstraintCategory,
    PublishConstraint,
    ReopenConstraint,
    ReorderConstraintCategories,
    TransitionConstraint,
    UpdateConstraint,
    UpdateConstraintCategory,
    VoidConstraint,
)
from my_pa.application.constraint_management import UPDATABLE_FIELDS
from my_pa.application.errors import ErrorCode, InvalidRequestError
from my_pa.application.service import _CONSTRAINT_UPDATE_FIELDS
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.operation import Capability
from my_pa.domain.project_controls.constraint import ConstraintLifecycleState
from my_pa.domain.source.registry import issue_identifier

AUTHORING_COMMANDS: Final[tuple[type, ...]] = (
    CreateConstraintDraft,
    PublishConstraint,
    UpdateConstraint,
    TransitionConstraint,
    CloseConstraint,
    CloseConstraintWithFollowUp,
    VoidConstraint,
    ReopenConstraint,
    CreateConstraintCategory,
    UpdateConstraintCategory,
    DeactivateConstraintCategory,
    ReorderConstraintCategories,
)

#: The two that mint a record and therefore have no version to expect.
CREATIONS: Final[frozenset[type]] = frozenset({CreateConstraintDraft, CreateConstraintCategory})


def _fields(command: type) -> set[str]:
    return {field.name for field in dataclasses.fields(command)}


def _constraint_id() -> str:
    return issue_identifier(IdKind.PROJECT_CONSTRAINT)


def _category_id() -> str:
    return issue_identifier(IdKind.CONSTRAINT_CATEGORY)


def _project_id() -> str:
    return issue_identifier(IdKind.PROJECT)


# ---- the union and the capability each command serves ------------------------


def test_every_authoring_command_is_in_the_command_union() -> None:
    """The union is what `adapters.mcp.tools` derives the published tools from.

    A command absent from it is a capability with no tool, and a capability with
    a tool and no command is an import-time `KeyError`.
    """
    members = set(Command.__value__.__args__)
    assert set(AUTHORING_COMMANDS) <= members


def test_each_command_declares_the_one_capability_it_serves() -> None:
    served = {command.capability for command in AUTHORING_COMMANDS}
    assert len(served) == len(AUTHORING_COMMANDS)
    assert served == {
        Capability.CONSTRAINTS_CREATE,
        Capability.CONSTRAINTS_PUBLISH,
        Capability.CONSTRAINTS_UPDATE,
        Capability.CONSTRAINTS_TRANSITION,
        Capability.CONSTRAINTS_CLOSE,
        Capability.CONSTRAINTS_CLOSE_FOLLOW_UP,
        Capability.CONSTRAINTS_VOID,
        Capability.CONSTRAINTS_REOPEN,
        Capability.CONSTRAINT_CATEGORIES_CREATE,
        Capability.CONSTRAINT_CATEGORIES_UPDATE,
        Capability.CONSTRAINT_CATEGORIES_DEACTIVATE,
        Capability.CONSTRAINT_CATEGORIES_REORDER,
    }


# ---- the bounded-input rules -------------------------------------------------


@pytest.mark.parametrize("command", AUTHORING_COMMANDS, ids=lambda c: c.__name__)
def test_no_authoring_command_carries_a_principal_field(command: type) -> None:
    named = {field for field in _fields(command) if "principal" in field}
    assert named == set(), f"{command.__name__} lets a caller name a Principal"


@pytest.mark.parametrize("command", AUTHORING_COMMANDS, ids=lambda c: c.__name__)
def test_no_authoring_command_carries_a_server_issued_code(command: type) -> None:
    assert "constraint_code" not in _fields(command)
    assert not [field for field in _fields(command) if field.endswith("_code")]


@pytest.mark.parametrize("command", AUTHORING_COMMANDS, ids=lambda c: c.__name__)
def test_expected_version_is_present_on_the_ten_and_absent_from_the_two(command: type) -> None:
    """`CM-BE-AC-082`. Required, not optional: a defaulted version would be a bypass."""
    fields = {field.name: field for field in dataclasses.fields(command)}
    if command in CREATIONS:
        assert "expected_version" not in fields
        return
    if command is ReorderConstraintCategories:
        # One reorder names the whole ordered sequence, so its versions are the
        # parallel array beside it rather than one scalar.
        assert fields["expected_versions"].default is dataclasses.MISSING
        return
    assert "expected_version" in fields
    assert fields["expected_version"].default is dataclasses.MISSING


@pytest.mark.parametrize("command", AUTHORING_COMMANDS, ids=lambda c: c.__name__)
def test_no_authoring_command_carries_a_workbook_or_synchronisation_field(command: type) -> None:
    """`CM-BE-AC-086`, and `PC-CM-IMP-WP11`'s plane kept out of this one."""
    forbidden = ("workbook", "sharepoint", "sync", "excel", "worksheet")
    named = sorted(field for field in _fields(command) if any(word in field for word in forbidden))
    assert named == []


@pytest.mark.parametrize("command", AUTHORING_COMMANDS, ids=lambda c: c.__name__)
def test_no_authoring_command_takes_a_raw_patch_object(command: type) -> None:
    """The WP06 `values` seam is internal and is not the public wire contract."""
    assert "values" not in _fields(command)
    assert "patch" not in _fields(command)


# ---- the closed update vocabulary -------------------------------------------


def test_the_clear_vocabulary_is_exactly_what_an_update_may_touch() -> None:
    assert {member.value for member in ConstraintUpdateField} == set(UPDATABLE_FIELDS)


def test_the_dispatchers_field_list_is_the_same_set() -> None:
    """`service.py` writes the nine names out; this is what stops the two drifting."""
    assert set(_CONSTRAINT_UPDATE_FIELDS) == set(UPDATABLE_FIELDS)


def test_a_field_cannot_be_both_set_and_cleared() -> None:
    with pytest.raises(InvalidRequestError) as refusal:
        UpdateConstraint(
            constraint_id=_constraint_id(),
            expected_version=1,
            description="a new description",
            clear_fields=(ConstraintUpdateField.DESCRIPTION,),
        )
    assert refusal.value.code is ErrorCode.INVALID_REQUEST


def test_a_repeated_clear_field_is_refused() -> None:
    with pytest.raises(InvalidRequestError):
        UpdateConstraint(
            constraint_id=_constraint_id(),
            expected_version=1,
            clear_fields=(ConstraintUpdateField.REFERENCE, ConstraintUpdateField.REFERENCE),
        )


# ---- dates, versions and keys ------------------------------------------------


def test_a_date_field_refuses_an_instant() -> None:
    """A Constraint's dates carry no clock, and `isinstance(datetime, date)` is true."""
    with pytest.raises(InvalidRequestError):
        CloseConstraint(
            constraint_id=_constraint_id(),
            expected_version=1,
            completion_date=datetime(2026, 9, 7, 12),
        )


def test_a_date_field_accepts_a_calendar_date() -> None:
    command = CloseConstraint(
        constraint_id=_constraint_id(), expected_version=1, completion_date=date(2026, 9, 7)
    )
    assert command.completion_date == date(2026, 9, 7)


@pytest.mark.parametrize("version", [-1, "1", 1.0, True, None])
def test_expected_version_refuses_anything_but_a_whole_number(version: object) -> None:
    with pytest.raises(InvalidRequestError):
        CloseConstraint(constraint_id=_constraint_id(), expected_version=version)  # type: ignore[arg-type]


@pytest.mark.parametrize("key", ["short", "has spaces!!!!!", "a" * 129, 12345678])
def test_an_idempotency_key_outside_the_persisted_pattern_is_refused(key: object) -> None:
    """The same `^[A-Za-z0-9_-]{8,128}$` the history tables carry as a CHECK."""
    with pytest.raises(InvalidRequestError):
        CloseConstraint(
            constraint_id=_constraint_id(),
            expected_version=1,
            idempotency_key=key,  # type: ignore[arg-type]
        )


def test_an_idempotency_key_inside_the_persisted_pattern_is_accepted() -> None:
    command = CloseConstraint(
        constraint_id=_constraint_id(), expected_version=1, idempotency_key="close-0001_A"
    )
    assert command.idempotency_key == "close-0001_A"


# ---- the two atomic operations ----------------------------------------------


def test_close_with_follow_up_is_one_command_carrying_both_halves() -> None:
    """One operation and one tool: never a close followed by a create."""
    command = CloseConstraintWithFollowUp(
        constraint_id=_constraint_id(),
        expected_version=3,
        successor_description="The follow-up control.",
    )
    assert command.capability is Capability.CONSTRAINTS_CLOSE_FOLLOW_UP
    assert command.successor_state is ConstraintLifecycleState.IDENTIFIED


def test_a_reorder_names_its_versions_one_per_category_in_order() -> None:
    first, second = _category_id(), _category_id()
    command = ReorderConstraintCategories(
        project_id=_project_id(),
        ordered_category_ids=(first, second),
        expected_versions=(1, 2),
    )
    assert command.ordered_category_ids == (first, second)
    assert command.expected_versions == (1, 2)


def test_a_reorder_with_mismatched_lengths_is_refused() -> None:
    with pytest.raises(InvalidRequestError):
        ReorderConstraintCategories(
            project_id=_project_id(),
            ordered_category_ids=(_category_id(), _category_id()),
            expected_versions=(1,),
        )


def test_a_reorder_naming_one_category_twice_is_refused() -> None:
    repeated = _category_id()
    with pytest.raises(InvalidRequestError):
        ReorderConstraintCategories(
            project_id=_project_id(),
            ordered_category_ids=(repeated, repeated),
            expected_versions=(1, 1),
        )


def test_a_reorder_naming_nothing_is_refused() -> None:
    with pytest.raises(InvalidRequestError):
        ReorderConstraintCategories(
            project_id=_project_id(), ordered_category_ids=(), expected_versions=()
        )


# ---- required text -----------------------------------------------------------


def test_a_void_requires_a_stated_reason() -> None:
    with pytest.raises(InvalidRequestError):
        VoidConstraint(constraint_id=_constraint_id(), expected_version=1, void_reason="  ")


def test_a_category_requires_a_code_segment_and_a_title() -> None:
    with pytest.raises(InvalidRequestError):
        CreateConstraintCategory(project_id=_project_id(), code_segment="", title="Site")
    with pytest.raises(InvalidRequestError):
        CreateConstraintCategory(project_id=_project_id(), code_segment="SIT", title=" ")


def test_a_deactivation_names_a_category_and_a_version_and_nothing_else() -> None:
    assert _fields(DeactivateConstraintCategory) == {
        "category_id",
        "expected_version",
        "idempotency_key",
        "client_context",
        "correlation_id",
    }


def test_a_category_update_cannot_set_state() -> None:
    """Deactivation is its own operation, and there is no archive."""
    assert "state" not in _fields(UpdateConstraintCategory)


def test_a_transition_names_only_a_state_a_version_and_the_record() -> None:
    command = TransitionConstraint(
        constraint_id=_constraint_id(),
        to_state=ConstraintLifecycleState.PENDING,
        expected_version=2,
    )
    assert command.to_state is ConstraintLifecycleState.PENDING
    assert "lifecycle_state" not in _fields(TransitionConstraint)


def test_a_reopen_refuses_a_state_outside_the_closed_vocabulary() -> None:
    with pytest.raises(InvalidRequestError):
        ReopenConstraint(
            constraint_id=_constraint_id(),
            to_state="identified",  # type: ignore[arg-type]
            expected_version=1,
        )


def test_a_publish_defaults_to_the_first_active_state() -> None:
    command = PublishConstraint(constraint_id=_constraint_id(), expected_version=1)
    assert command.to_state is ConstraintLifecycleState.IDENTIFIED
