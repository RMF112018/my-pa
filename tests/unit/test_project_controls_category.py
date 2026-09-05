"""Unit tests for the PC-CM-IMP-WP01 Constraint Category contract."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.project_controls.category import (
    CONSTRAINT_CATEGORY_PREFIX_PATTERN,
    ConstraintCategory,
    ConstraintCategoryError,
    ConstraintCategoryState,
    revise_category,
)

PRINCIPAL_ID = "prn_aaaa0001aaaa0001aaaa0001"
PROJECT_ID = "prj_aaaa0001aaaa0001aaaa"
CATEGORY_ID = "ccat_aaaa0001aaaa0001aaaa"
T0 = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
T1 = datetime(2026, 9, 2, 12, 0, tzinfo=UTC)


def _category(**overrides: object) -> ConstraintCategory:
    fields: dict[str, object] = {
        "category_id": CATEGORY_ID,
        "principal_id": PRINCIPAL_ID,
        "project_id": PROJECT_ID,
        "prefix": "DES",
        "title": "Design",
        "state": ConstraintCategoryState.ACTIVE,
        "created_at": T0,
        "updated_at": T0,
    }
    fields.update(overrides)
    return ConstraintCategory(**fields)  # type: ignore[arg-type]


def test_category_is_scoped_to_one_principal_and_one_continuity_project() -> None:
    category = _category()
    assert category.principal_id.startswith("prn_")
    assert category.project_id.startswith("prj_")
    assert category.category_id.startswith("ccat_")
    with pytest.raises(InvalidIdentifierError):
        _category(category_id="cst_aaaa0001aaaa0001aaaa")
    with pytest.raises(InvalidIdentifierError):
        _category(project_id=PRINCIPAL_ID)
    with pytest.raises(InvalidIdentifierError):
        _category(principal_id=PROJECT_ID)


def test_category_states_are_exactly_three() -> None:
    assert {s.value for s in ConstraintCategoryState} == {"active", "inactive", "archived"}
    for state in ConstraintCategoryState:
        assert _category(state=state).state is state


@pytest.mark.parametrize("prefix", ["A", "9", "A" * 16, "A-b_1", "ab-cd-ef-gh-ij-k", "1_"])
def test_valid_prefix_boundaries(prefix: str) -> None:
    assert CONSTRAINT_CATEGORY_PREFIX_PATTERN.match(prefix)
    assert _category(prefix=prefix).prefix == prefix


@pytest.mark.parametrize(
    "prefix",
    ["", "A" * 17, "-DES", "_DES", "DE S", " DES", "DES ", "DES.1", "DES/1", "DÉS", "DES\n"],
)
def test_invalid_prefix_boundaries(prefix: str) -> None:
    assert not CONSTRAINT_CATEGORY_PREFIX_PATTERN.match(prefix)
    with pytest.raises(ConstraintCategoryError) as excinfo:
        _category(prefix=prefix)
    assert excinfo.value.code == "category_prefix_invalid"


def test_title_must_be_nonblank_and_display_order_nonnegative() -> None:
    with pytest.raises(ConstraintCategoryError) as excinfo:
        _category(title="  ")
    assert excinfo.value.code == "category_title_blank"
    with pytest.raises(ConstraintCategoryError) as excinfo:
        _category(display_order=-1)
    assert excinfo.value.code == "category_display_order_negative"


def test_prefix_is_mutable_until_locked() -> None:
    unlocked = _category()
    assert unlocked.is_prefix_locked is False
    revised = revise_category(unlocked, prefix="STR", updated_at=T1)
    assert revised.prefix == "STR"
    assert revised.updated_at == T1
    assert unlocked.prefix == "DES"


def test_prefix_change_is_refused_once_locked() -> None:
    locked = _category(prefix_locked_at=T0)
    assert locked.is_prefix_locked is True
    with pytest.raises(ConstraintCategoryError) as excinfo:
        revise_category(locked, prefix="STR")
    assert excinfo.value.code == "category_prefix_locked"
    # Restating the same prefix is not a change and is not refused.
    assert revise_category(locked, prefix="DES").prefix == "DES"


def test_title_description_and_display_order_stay_mutable_while_locked() -> None:
    locked = _category(prefix_locked_at=T0)
    revised = revise_category(
        locked, title="Design (revised)", description="Drawings", display_order=3, updated_at=T1
    )
    assert revised.prefix == "DES"
    assert revised.is_prefix_locked is True
    assert revised.prefix_locked_at == T0
    assert (revised.title, revised.description, revised.display_order) == (
        "Design (revised)",
        "Drawings",
        3,
    )
    with pytest.raises(ConstraintCategoryError):
        revise_category(locked, title="x", prefix="NEW")


def test_locked_prefix_cannot_be_invalidated_through_revision() -> None:
    with pytest.raises(ConstraintCategoryError) as excinfo:
        revise_category(_category(), prefix="-bad")
    assert excinfo.value.code == "category_prefix_invalid"
