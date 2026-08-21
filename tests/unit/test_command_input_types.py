"""A caller who sends the wrong type is told which field, not handed a 500.

Three commands dereferenced an optional string behind an `is not None` test —
`if self.title is not None and not self.title.strip()`, which reads as a
guarded access and is not one. A caller sending `{"title": 123}` reached
`int.strip`, which raises `AttributeError`: not a `TypeError`, so
`normalization._command` did not convert it, and not an `ApplicationError`, so
the HTTP transport did not render it. It escaped as a bare
`500 Internal Server Error` with no envelope, no typed code and no correlation
identifier, on `tasks.update`, `tasks.transition` and `review.decide`, none of
them behind a feature switch.

A separate group was quieter and worse. `_idempotency_key` tested truthiness
and never the type, so `123` was *accepted* — no error at all — and reached a
handler that uses the key as a string. The request looked like it worked.

Both are fixed. These tests state the fix as behaviour, at the boundary a
caller actually reaches, so the refusal is pinned to `InvalidRequestError` and
not merely to "something was raised". The architectural rules that keep the
population honest live in `tests/architecture/`; this module is about what one
caller gets back.
"""

from __future__ import annotations

import pytest

from my_pa.application.commands import (
    DecideReviewCase,
    PrepareContext,
    TransitionTask,
    UpdateTask,
    _conversation_context,
    _idempotency_key,
)
from my_pa.application.errors import InvalidRequestError
from my_pa.domain.capture.review import Disposition
from my_pa.domain.common.identifiers import IdKind, make_identifier
from my_pa.domain.task.task import TaskLifecycleState

TASK_ID = make_identifier(IdKind.TASK, "a" * 24)
REVIEW_CASE_ID = make_identifier(IdKind.REVIEW_CASE, "a" * 24)

#: Not `None`, which is a legitimate value for every optional field below and
#: would measure a different rule. The sibling architecture module uses the
#: same value for the same reason.
NOT_A_STRING = 123


def test_update_task_refuses_a_non_string_title() -> None:
    with pytest.raises(InvalidRequestError):
        UpdateTask(
            task_id=TASK_ID,
            expected_version=1,
            idempotency_key="key",
            title=NOT_A_STRING,
        )


def test_transition_task_refuses_a_non_string_closure_evidence_ref() -> None:
    with pytest.raises(InvalidRequestError):
        TransitionTask(
            task_id=TASK_ID,
            to_state=TaskLifecycleState.COMPLETED,
            expected_version=1,
            idempotency_key="key",
            closure_evidence_ref=NOT_A_STRING,
        )


def test_decide_review_case_refuses_a_non_string_corrected_value() -> None:
    with pytest.raises(InvalidRequestError):
        DecideReviewCase(
            review_case_id=REVIEW_CASE_ID,
            expected_review_version=0,
            disposition=Disposition.CORRECT_AND_ACCEPT,
            corrected_value=NOT_A_STRING,
        )


def test_a_non_string_idempotency_key_is_refused_rather_than_accepted() -> None:
    """The quiet one: this used to raise nothing at all.

    `if not value` is true for `""` and false for `123`, so the empty key was
    refused and the wrong type sailed through into a handler that uses it as a
    string. Asserting the emptiness rule alongside it, because a fix that
    checked only the type would pass a test that checked only the type.
    """
    with pytest.raises(InvalidRequestError):
        _idempotency_key(NOT_A_STRING)
    with pytest.raises(InvalidRequestError):
        _idempotency_key("")
    assert _idempotency_key("key") == "key"


def test_update_task_refuses_a_non_string_idempotency_key() -> None:
    """Through a command, so the helper's fix is shown to reach a caller."""
    with pytest.raises(InvalidRequestError):
        UpdateTask(
            task_id=TASK_ID,
            expected_version=1,
            idempotency_key=NOT_A_STRING,
            title="ok",
        )


def test_conversation_context_refuses_a_non_string_and_keeps_none() -> None:
    """This behaviour is not new; the helper holding it is.

    `PrepareContext` already converted the domain validator's refusal inline and
    answered `invalid_request`. The extraction changed no behaviour, so this
    test would have passed before it — which is the point of writing it down:
    the next reader can see the guarantee is the same one.
    """
    with pytest.raises(InvalidRequestError):
        _conversation_context(NOT_A_STRING)
    assert _conversation_context(None) is None
    assert _conversation_context("context") == "context"


def test_prepare_context_refuses_a_non_string_conversation_context() -> None:
    with pytest.raises(InvalidRequestError):
        PrepareContext(query="q", conversation_context=NOT_A_STRING)
