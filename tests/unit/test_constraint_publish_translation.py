"""Publish refusals become public tokens, never the exception text."""

from __future__ import annotations

import json

import pytest

from my_pa.adapters.mcp.chatllm_gateway import feature_label, render_describe
from my_pa.application.errors import (
    InternalError,
    InvalidRequestError,
    SafeDetail,
    problem_detail,
)
from my_pa.application.service import (
    _classified_publish_error,
    _constraint_mutation_translated,
)
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.project_controls.constraint import (
    ConstraintFieldKey,
    ConstraintLifecycleError,
    ConstraintPublishError,
)
from my_pa.domain.source.registry import issue_identifier

_MESSAGE = "publish requires: description, due_date"


def _public(error: Exception) -> str:
    assert isinstance(error, (InvalidRequestError, InternalError))
    detail = problem_detail(error, correlation_id=issue_identifier(IdKind.CORRELATION))
    rendered = detail.model_dump_json()
    assert _MESSAGE not in rendered
    assert "publish requires:" not in rendered
    return rendered


def test_lifecycle_error_stays_lifecycle_state() -> None:
    with pytest.raises(InvalidRequestError) as caught, _constraint_mutation_translated():
        raise ConstraintLifecycleError("constraint_lifecycle_move_prohibited", "no")
    assert caught.value.safe_details == (SafeDetail.LIFECYCLE_STATE,)
    _public(caught.value)


@pytest.mark.parametrize(
    "code",
    ["constraint_publish_not_draft", "constraint_publish_state_not_active"],
)
def test_draft_and_state_publish_codes_stay_lifecycle_state(code: str) -> None:
    error = _classified_publish_error(ConstraintPublishError(code, _MESSAGE))
    assert isinstance(error, InvalidRequestError)
    assert error.safe_details == (SafeDetail.LIFECYCLE_STATE,)
    _public(error)


def test_incomplete_publish_names_the_incomplete_token_and_each_field() -> None:
    error = _classified_publish_error(
        ConstraintPublishError(
            "constraint_publish_incomplete",
            _MESSAGE,
            (
                ConstraintFieldKey.PROJECT_ID,
                ConstraintFieldKey.CATEGORY_ID,
                ConstraintFieldKey.DESCRIPTION,
                ConstraintFieldKey.DATE_IDENTIFIED,
                ConstraintFieldKey.DUE_DATE,
                ConstraintFieldKey.BIC,
            ),
        )
    )
    assert isinstance(error, InvalidRequestError)
    assert error.safe_details == (
        SafeDetail.CONSTRAINT_PUBLISH_INCOMPLETE,
        SafeDetail.PROJECT_ID,
        SafeDetail.CATEGORY_ID,
        SafeDetail.DESCRIPTION,
        SafeDetail.DATE_IDENTIFIED,
        SafeDetail.DUE_DATE,
        SafeDetail.BIC,
    )
    assert SafeDetail.DUE_AT not in error.safe_details
    assert error.code is ErrorCode.INVALID_REQUEST
    assert len(error.safe_details) <= 16
    _public(error)


def test_category_and_quality_publish_codes_use_their_domain_tokens() -> None:
    inactive = _classified_publish_error(
        ConstraintPublishError("constraint_publish_category_not_active", _MESSAGE)
    )
    quality = _classified_publish_error(
        ConstraintPublishError("constraint_publish_quality_not_normal", _MESSAGE)
    )
    assert inactive.safe_details == (SafeDetail.CONSTRAINT_PUBLISH_CATEGORY_INACTIVE,)
    assert quality.safe_details == (SafeDetail.CONSTRAINT_PUBLISH_QUALITY,)
    _public(inactive)
    _public(quality)


def test_partition_mismatch_stays_selector_only() -> None:
    error = _classified_publish_error(
        ConstraintPublishError("constraint_publish_category_partition_mismatch", _MESSAGE)
    )
    assert error.safe_details == (SafeDetail.SELECTOR,)
    _public(error)


def test_unknown_publish_code_is_internal_and_hides_the_message() -> None:
    error = _classified_publish_error(
        ConstraintPublishError("constraint_publish_not_a_known_rule", _MESSAGE)
    )
    assert isinstance(error, InternalError)
    assert error.code is ErrorCode.INTERNAL_ERROR
    assert error.safe_details == ()
    _public(error)


def test_three_families_are_constraints_and_sync_stays_out_of_that_filter() -> None:
    assert feature_label("constraints.publish") == "constraints"
    assert feature_label("constraint_categories.reorder") == "constraints"
    assert feature_label("project_controls.status") == "constraints"
    assert feature_label("constraint_sync.state") == "other"
    allowed = frozenset(
        {
            "constraints.publish",
            "constraint_categories.list",
            "project_controls.configure",
            "constraint_sync.state",
            "tasks.list",
        }
    )
    catalog = json.loads(
        render_describe({"feature": "constraints", "limit": 25}, allowed_canonical=allowed)
    )
    names = {row["capability"] for row in catalog["items"]}
    assert names == {
        "constraints.publish",
        "constraint_categories.list",
        "project_controls.configure",
    }
    assert all(row["feature"] == "constraints" for row in catalog["items"])
