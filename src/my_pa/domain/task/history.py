"""One append-only mutation receipt per Task write.

`TaskHistoryEntry` is the domain half of `knowledge.task_history`: a record that
a mutation was *attempted*, what this build normalised the request into, what
version the Task was at before and after, who or what asked, and what happened
— never the caller's raw request. `client_context` names the client or tool
that issued the request (a short, closed-shape label) and is not a place a
request body, a natural-language instruction, or any other sensitive source
text may go; `AGENTS.md` section 5 requires logs to exclude message bodies and
this table is exactly that kind of log.

**Idempotency is optional and scoped per Principal.** A mutation carrying no
`idempotency_key` is simply not replay-protected; one that carries a key is
protected only against another mutation from the same Principal reusing it,
which is what `tables.py`'s `task_history_idempotency_key_is_unique_per_principal`
partial unique index enforces — the same shape `capture_submissions` already
uses for the same reason.

**The version pairing is the receipt's whole point.** `outcome = APPLIED`
requires `after_version > before_version`, because an applied mutation that did
not advance the optimistic-concurrency version is a mutation the receipt claims
happened and the row disagrees with. `REJECTED` and `NO_OP` both require
`after_version == before_version`: nothing changed, and the receipt says so
rather than inventing a version bump for a write that did not occur.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Final

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.common.time import ensure_utc

__all__ = [
    "IDEMPOTENCY_KEY_PATTERN",
    "MAX_CLIENT_CONTEXT_CHARACTERS",
    "TaskHistoryEntry",
    "TaskMutationAction",
    "TaskMutationActor",
    "TaskMutationOutcome",
]

#: The same shape `capture_submissions.idempotency_key` restates in `tables.py`:
#: opaque and bounded, never a value a request body could smuggle meaning
#: through.
IDEMPOTENCY_KEY_PATTERN: Final = re.compile(r"\A[A-Za-z0-9_-]{8,128}\Z")

#: A client label, not a request. Bounded well below anything a body could fit,
#: so a caller that tries to log one there gets a domain error instead of a
#: quietly truncated leak.
MAX_CLIENT_CONTEXT_CHARACTERS: Final = 128


class TaskMutationAction(StrEnum):
    """What this build normalised a mutation request into.

    A closed vocabulary rather than free text, for the same reason every other
    interpreted field in this codebase is closed: a reader of the history has to
    be able to tell what happened without re-deriving it from a diff of two
    rows.
    """

    CREATE = "create"
    UPDATE_TITLE = "update_title"
    TRANSITION_LIFECYCLE = "transition_lifecycle"
    SET_PRIORITY = "set_priority"
    SCHEDULE = "schedule"
    DEFER = "defer"
    ARCHIVE = "archive"
    UNARCHIVE = "unarchive"
    SET_RECURRENCE = "set_recurrence"
    CANCEL_RECURRENCE = "cancel_recurrence"
    #: WP-TM-05: linking a Task to a Commitment, and setting/clearing its
    #: `TaskRole`. Both are writes to the Task row alone — neither ever writes
    #: the linked Commitment — so both are recorded here rather than on
    #: `CommitmentMutationAction`.
    LINK_COMMITMENT = "link_commitment"
    SET_ROLE = "set_role"


class TaskMutationActor(StrEnum):
    """Who or what asked for the mutation, closed to three kinds this build has."""

    PRINCIPAL = "principal"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class TaskMutationOutcome(StrEnum):
    """What became of the mutation, once this build finished interpreting it."""

    APPLIED = "applied"
    REJECTED = "rejected"
    NO_OP = "no_op"


@dataclass(frozen=True, slots=True)
class TaskHistoryEntry:
    """One append-only row: a mutation, its target, and what happened.

    `before_version`/`after_version` are the Task's `version` column, read
    before and after the attempt — the optimistic-concurrency receipt that lets
    a reader confirm a claimed mutation against the row it names without trusting
    the claim.
    """

    history_id: str
    principal_id: str
    task_id: str
    action: TaskMutationAction
    actor: TaskMutationActor
    outcome: TaskMutationOutcome
    before_version: int
    after_version: int
    occurred_at: datetime
    recorded_at: datetime
    idempotency_key: str | None = None
    client_context: str | None = None

    def __post_init__(self) -> None:
        validate_identifier(self.history_id, IdKind.TASK_HISTORY)
        validate_identifier(self.principal_id, IdKind.PRINCIPAL)
        validate_identifier(self.task_id, IdKind.TASK)
        if not isinstance(self.action, TaskMutationAction):
            raise ValueError("a task history entry names one known action")
        if not isinstance(self.actor, TaskMutationActor):
            raise ValueError("a task history entry names one known actor")
        if not isinstance(self.outcome, TaskMutationOutcome):
            raise ValueError("a task history entry names one known outcome")
        if self.before_version < 0:
            raise ValueError("a task history entry records a non-negative before-version")
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
