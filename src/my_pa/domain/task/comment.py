"""One append-only Task comment the Principal authors against a Task.

WP-TUX-01 admits a first-class comment child of `Task`: a row that records what
the Principal (or another admitted actor) wrote about one Task, without becoming
a Task-state mutation. Comment append does not advance `Task.version` and does
not write `TaskHistoryEntry` — Task history remains Task-state mutation history,
and a comment is its own immutable receipt.

`body` is stored exactly as authored after blankness validation: trim only to
detect empty input, preserve internal whitespace and punctuation, and never treat
the text as trusted HTML. The bound matches the relationship-memory statement
cap (`4_000` Unicode characters) so a comment cannot smuggle a capture-sized
payload through a Task surface.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.task.history import IDEMPOTENCY_KEY_PATTERN, TaskMutationActor

__all__ = [
    "MAX_TASK_COMMENT_BODY_CHARACTERS",
    "TaskComment",
    "validate_task_comment_body",
]

#: The same character budget relationship memory uses for a statement: large
#: enough for a working note, far below anything a capture body could fit.
MAX_TASK_COMMENT_BODY_CHARACTERS: Final = 4_000


def validate_task_comment_body(body: str) -> str:
    """Return `body` unchanged, or refuse it.

    Two statements rather than one condition, for the reason neighbouring domain
    validators split their own: domain models are plain dataclasses with no
    runtime type enforcement, so a non-string really can reach here and must fail
    as a domain error rather than as an incidental `AttributeError` from
    `strip()`. Trim is used only to detect emptiness; the stored value is the
    authored string, including leading or trailing whitespace the Principal kept.
    """
    if not isinstance(body, str):
        raise ValueError("a task comment body is text")
    if not body.strip():
        raise ValueError("a task comment carries a non-blank body")
    if len(body) > MAX_TASK_COMMENT_BODY_CHARACTERS:
        raise ValueError(
            f"a task comment body is at most {MAX_TASK_COMMENT_BODY_CHARACTERS} characters"
        )
    return body


@dataclass(frozen=True, slots=True)
class TaskComment:
    """One append-only comment bound to one Task under one Principal partition.

    `author_kind` reuses `TaskMutationActor`: a comment is authored by one of the
    same three closed kinds a Task mutation already admits, so a reader does not
    learn a fourth actor vocabulary for the same question. `author_id` names the
    actor within that kind — a Principal id when the author is the Principal.
    """

    comment_id: str
    principal_id: str
    task_id: str
    body: str
    author_kind: TaskMutationActor
    author_id: str
    created_at: datetime
    idempotency_key: str
    request_digest: str

    def __post_init__(self) -> None:
        validate_identifier(self.comment_id, IdKind.TASK_COMMENT)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.task_id, IdKind.TASK)
        validate_task_comment_body(self.body)
        if not isinstance(self.author_kind, TaskMutationActor):
            raise ValueError("a task comment names one known author kind")
        if self.author_kind is TaskMutationActor.PRINCIPAL:
            validate_identifier(self.author_id, IdKind.PRINCIPAL)
        else:
            validate_identifier(self.author_id)
        ensure_utc(self.created_at)
        if not IDEMPOTENCY_KEY_PATTERN.fullmatch(self.idempotency_key):
            raise ValueError("an idempotency key must be 8-128 opaque characters")
        if not re.fullmatch(r"[0-9a-f]{64}", self.request_digest):
            raise ValueError("a request digest is a lowercase SHA-256 hex value")
