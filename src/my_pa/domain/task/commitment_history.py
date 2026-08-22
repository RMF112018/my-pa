"""One append-only mutation receipt per Commitment write.

`CommitmentHistoryEntry` mirrors `domain.task.history.TaskHistoryEntry`
structurally: a record that a mutation was *attempted*, what this build
normalised the request into, what version the Commitment was at before and
after, who or what asked, and what happened — never the caller's raw request.
See `history.py`'s module docstring for the full rationale behind every one of
these fields; it applies here unchanged.

`TaskMutationActor` and `TaskMutationOutcome` are reused as-is from
`domain.task.history`, per the approved plan: this module does not duplicate
either vocabulary, because an actor kind and a mutation outcome mean the same
thing for a Commitment mutation as they do for a Task one.

`CommitmentMutationAction` is its own closed vocabulary, sized to only what
this package needs: `CREATE` (a new commitment proposed or directly accepted)
and `CLOSE` (an explicit `close_commitment` call). There is no `LINK` member
here — linking a Task to a Commitment is recorded on the *Task's* own history
(`TaskMutationAction.LINK_COMMITMENT`), because the mutation is a write to the
Task row, not to the Commitment row, and inventing a second, mirrored receipt
for the same fact would be exactly the kind of speculative table this
package's minimal-implementation constraint refuses.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc
from my_pa.domain.task.history import (
    IDEMPOTENCY_KEY_PATTERN,
    MAX_CLIENT_CONTEXT_CHARACTERS,
    TaskMutationActor,
    TaskMutationOutcome,
)

__all__ = ["CommitmentHistoryEntry", "CommitmentMutationAction"]


class CommitmentMutationAction(StrEnum):
    """What this build normalised a commitment mutation request into."""

    CREATE = "create"
    UPDATE = "update"
    CLOSE = "close"


@dataclass(frozen=True, slots=True)
class CommitmentHistoryEntry:
    """One append-only row: a commitment mutation, its target, and what happened.

    `before_version`/`after_version` are the Commitment's `version` column,
    read before and after the attempt, exactly as `TaskHistoryEntry`'s own
    pairing works.
    """

    history_id: str
    principal_id: str
    commitment_id: str
    action: CommitmentMutationAction
    actor: TaskMutationActor
    outcome: TaskMutationOutcome
    before_version: int
    after_version: int
    occurred_at: datetime
    recorded_at: datetime
    idempotency_key: str | None = None
    client_context: str | None = None
    request_digest: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.history_id, IdKind.COMMITMENT_HISTORY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.commitment_id, IdKind.COMMITMENT)
        if not isinstance(self.action, CommitmentMutationAction):
            raise ValueError("a commitment history entry names one known action")
        if not isinstance(self.actor, TaskMutationActor):
            raise ValueError("a commitment history entry names one known actor")
        if not isinstance(self.outcome, TaskMutationOutcome):
            raise ValueError("a commitment history entry names one known outcome")
        if self.before_version < 0:
            raise ValueError("a commitment history entry records a non-negative before-version")
        if self.outcome is TaskMutationOutcome.APPLIED:
            if self.after_version <= self.before_version:
                raise ValueError("an applied mutation advances the version it recorded")
        elif self.after_version != self.before_version:
            raise ValueError("a rejected or no-op mutation records no version change")
        ensure_utc(self.occurred_at)
        ensure_utc(self.recorded_at)
        if self.idempotency_key is not None and not IDEMPOTENCY_KEY_PATTERN.fullmatch(
            self.idempotency_key
        ):
            raise ValueError("an idempotency key must be 8-128 opaque characters")
        if self.client_context is not None:
            stripped = self.client_context.strip()
            if not stripped:
                raise ValueError("client context must be non-blank when present")
            if len(stripped) > MAX_CLIENT_CONTEXT_CHARACTERS:
                raise ValueError("client context exceeds the stored bound")
        if self.request_digest is not None and not re.fullmatch(
            r"[0-9a-f]{64}", self.request_digest
        ):
            raise ValueError("a request digest is a lowercase SHA-256 hex value")
