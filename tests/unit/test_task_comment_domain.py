"""Unit tests for the WP-TUX-01 TaskComment domain model."""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from my_pa.domain.common.identifiers import InvalidIdentifierError
from my_pa.domain.task.comment import (
    MAX_TASK_COMMENT_BODY_CHARACTERS,
    TaskComment,
    validate_task_comment_body,
)
from my_pa.domain.task.history import TaskMutationActor

PRINCIPAL_ID = "prn_aaaa0001aaaa0001aaaa0001"
TASK_ID = "tsk_aaaa0001aaaa0001aaaa"
COMMENT_ID = "tcm_aaaa0001aaaa0001aaaa"
DIGEST = "a" * 64
IDEMPOTENCY_KEY = "idemkey01abcdefgh"


def _instant(year: int, month: int, day: int, hour: int = 12) -> datetime:
    return datetime(year, month, day, hour, tzinfo=UTC)


class TestTaskComment:
    def _comment(self, **overrides: object) -> TaskComment:
        fields: dict[str, object] = {
            "comment_id": COMMENT_ID,
            "principal_id": PRINCIPAL_ID,
            "task_id": TASK_ID,
            "body": "Ship the civil-day fix first.",
            "author_kind": TaskMutationActor.PRINCIPAL,
            "author_id": PRINCIPAL_ID,
            "created_at": _instant(2027, 1, 1),
            "idempotency_key": IDEMPOTENCY_KEY,
            "request_digest": DIGEST,
        }
        fields.update(overrides)
        return TaskComment(**fields)  # type: ignore[arg-type]

    def test_a_valid_comment_constructs(self) -> None:
        comment = self._comment()
        assert comment.author_kind is TaskMutationActor.PRINCIPAL
        assert comment.body == "Ship the civil-day fix first."

    def test_blank_body_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-blank body"):
            self._comment(body="   ")

    def test_empty_body_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="non-blank body"):
            self._comment(body="")

    def test_body_at_the_character_bound_constructs(self) -> None:
        body = "x" * MAX_TASK_COMMENT_BODY_CHARACTERS
        comment = self._comment(body=body)
        assert len(comment.body) == MAX_TASK_COMMENT_BODY_CHARACTERS

    def test_body_above_the_character_bound_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at most"):
            self._comment(body="x" * (MAX_TASK_COMMENT_BODY_CHARACTERS + 1))

    def test_body_preserves_internal_and_edge_whitespace_when_nonblank(self) -> None:
        body = "  keep  internal  "
        assert validate_task_comment_body(body) == body
        comment = self._comment(body=body)
        assert comment.body == body

    def test_invalid_comment_id_is_rejected(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self._comment(comment_id="not-an-id")

    def test_principal_author_requires_a_principal_id(self) -> None:
        with pytest.raises(InvalidIdentifierError):
            self._comment(
                author_kind=TaskMutationActor.PRINCIPAL,
                author_id="tsk_aaaa0001aaaa0001aaaa",
            )

    def test_idempotency_key_must_match_the_opaque_pattern(self) -> None:
        with pytest.raises(ValueError, match="idempotency key"):
            self._comment(idempotency_key="short")

    def test_request_digest_must_be_sha256_hex(self) -> None:
        with pytest.raises(ValueError, match="request digest"):
            self._comment(request_digest="not-a-digest")
