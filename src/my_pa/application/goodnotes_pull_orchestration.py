"""Bounded client-pull orchestration for immutable GoodNotes semantic work.

The authenticated server layer stamps :class:`AuthenticatedPullContext`; pull
requests and completion submissions cannot carry a Principal or replace that
context.  This module selects and admits work only.  It does not read source
paths, mutate a source, call a model, send externally, or choose a schedule.

Persistence and public command/transport wiring are deliberately injected and
remain separate.  A repository implementation must claim and complete each
batch atomically so a stale concurrent request cannot partially write.
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

from my_pa.domain.common.identifiers import IdKind, validate_identifier
from my_pa.domain.goodnotes.models import GoodNotesPageWork

MAX_PULL_BATCH_SIZE = 100
MAX_PULL_RETRIES = 10
MAX_CONTEXT_TOKEN_LENGTH = 128
MAX_IDEMPOTENCY_KEY_LENGTH = 128

ERROR_INVALID_REQUEST = "INVALID_REQUEST"
ERROR_INVALID_CURSOR = "INVALID_CURSOR"
ERROR_STALE_CURSOR = "STALE_CURSOR"
ERROR_WRONG_CONTEXT = "WRONG_CONTEXT"
ERROR_STALE_ASSIGNMENT = "STALE_ASSIGNMENT"
ERROR_COMPLETION_CONFLICT = "COMPLETION_CONFLICT"
ERROR_REPOSITORY_CONFLICT = "REPOSITORY_CONFLICT"

_CONTEXT_SEAL = object()


class GoodNotesPullError(ValueError):
    """Fail-closed pull error with a stable, content-free code."""

    def __init__(self, code: str) -> None:
        self.code = code
        super().__init__(code)


@dataclass(frozen=True, slots=True, init=False)
class AuthenticatedPullContext:
    """Identity stamped by authenticated server composition, never request data."""

    principal_id: str
    client_id: str
    context_id: str

    def __init__(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        *,
        _seal: object,
    ) -> None:
        if _seal is not _CONTEXT_SEAL:
            raise GoodNotesPullError(ERROR_WRONG_CONTEXT)
        validate_identifier(principal_id, IdKind.PRINCIPAL)
        _bounded_token(client_id, maximum=MAX_CONTEXT_TOKEN_LENGTH)
        _bounded_token(context_id, maximum=MAX_CONTEXT_TOKEN_LENGTH)
        object.__setattr__(self, "principal_id", principal_id)
        object.__setattr__(self, "client_id", client_id)
        object.__setattr__(self, "context_id", context_id)


def stamp_authenticated_pull_context(
    *, principal_id: str, client_id: str, context_id: str
) -> AuthenticatedPullContext:
    """Create context from authenticated server facts at the future wiring seam."""

    return AuthenticatedPullContext(
        principal_id,
        client_id,
        context_id,
        _seal=_CONTEXT_SEAL,
    )


@dataclass(frozen=True, slots=True)
class PullRequest:
    """Caller-selectable discovery controls; identity is intentionally absent."""

    batch_size: int
    cursor: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        raw_batch_size: object = self.batch_size
        if (
            isinstance(raw_batch_size, bool)
            or not isinstance(raw_batch_size, int)
            or not 1 <= self.batch_size <= MAX_PULL_BATCH_SIZE
        ):
            raise GoodNotesPullError(ERROR_INVALID_REQUEST)
        raw_cursor: object = self.cursor
        if raw_cursor is not None and (
            not isinstance(raw_cursor, str) or not raw_cursor or len(raw_cursor) > 2048
        ):
            raise GoodNotesPullError(ERROR_INVALID_CURSOR)


@dataclass(frozen=True, slots=True)
class PullWorkState:
    work: GoodNotesPageWork
    attempts: int = 0
    completed: bool = False

    def __post_init__(self) -> None:
        if isinstance(self.attempts, bool) or not isinstance(self.attempts, int):
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT)
        if self.attempts < 0 or self.attempts > MAX_PULL_RETRIES:
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT)


@dataclass(frozen=True, slots=True)
class PullAssignment:
    assignment_id: str
    context_id: str
    work: GoodNotesPageWork
    attempt: int


@dataclass(frozen=True, slots=True)
class PullBatch:
    assignments: tuple[PullAssignment, ...]
    next_cursor: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class PullCompletion:
    """Content-free completion identity; semantic payload uses existing proposal flow."""

    assignment_id: str
    run_id: str
    page_version_id: str
    content_sha256: str
    result_sha256: str
    idempotency_key: str

    def __post_init__(self) -> None:
        _sha256(self.assignment_id)
        _sha256(self.content_sha256)
        _sha256(self.result_sha256)
        _bounded_token(self.idempotency_key, maximum=MAX_IDEMPOTENCY_KEY_LENGTH)


@dataclass(frozen=True, slots=True)
class PullCompletionAdmission:
    completion: PullCompletion
    request_fingerprint: str


@dataclass(frozen=True, slots=True)
class PullCompletionReceipt:
    completion_id: str
    assignment_id: str
    idempotency_key: str
    request_fingerprint: str
    result_sha256: str
    replayed: bool = False


class PullRepositoryConflictError(Exception):
    """Atomic claim or completion observed concurrent/stale repository state."""


class PullCompletionConflictError(Exception):
    """An idempotency key or assignment was completed with different content."""


class GoodNotesPullRepository(Protocol):
    """Principal-partitioned orchestration ledger; never a source-provider port."""

    def work_states(self, principal_id: str) -> tuple[PullWorkState, ...]: ...

    def claim_batch(
        self,
        principal_id: str,
        context_id: str,
        assignments: tuple[PullAssignment, ...],
        expected_attempts: tuple[int, ...],
        *,
        max_attempts: int,
    ) -> tuple[PullAssignment, ...]:
        """Atomically increment exact expected attempts and store assignments."""

    def assignment(self, principal_id: str, assignment_id: str) -> PullAssignment | None: ...

    def complete_batch(
        self,
        principal_id: str,
        context_id: str,
        admissions: tuple[PullCompletionAdmission, ...],
    ) -> tuple[PullCompletionReceipt, ...]:
        """Atomically store all completions, replay all, or reject without writes."""


class GoodNotesPullOrchestrator:
    """Deterministic pull policy with configurable non-time retry and batch bounds."""

    def __init__(
        self,
        *,
        repository: GoodNotesPullRepository,
        max_batch_size: int,
        max_attempts: int,
    ) -> None:
        raw_max_batch_size: object = max_batch_size
        if (
            isinstance(raw_max_batch_size, bool)
            or not isinstance(raw_max_batch_size, int)
            or not 1 <= max_batch_size <= MAX_PULL_BATCH_SIZE
        ):
            raise GoodNotesPullError(ERROR_INVALID_REQUEST)
        raw_max_attempts: object = max_attempts
        if (
            isinstance(raw_max_attempts, bool)
            or not isinstance(raw_max_attempts, int)
            or not 1 <= max_attempts <= MAX_PULL_RETRIES
        ):
            raise GoodNotesPullError(ERROR_INVALID_REQUEST)
        self._repository = repository
        self._max_batch_size = max_batch_size
        self._max_attempts = max_attempts

    def discover(self, context: AuthenticatedPullContext, request: PullRequest) -> PullBatch:
        if request.batch_size > self._max_batch_size:
            raise GoodNotesPullError(ERROR_INVALID_REQUEST)
        states = self._validated_states(context)
        snapshot = _snapshot_digest(tuple(state.work for state in states))
        after = _decode_cursor(request.cursor, context, snapshot) if request.cursor else None
        start = _resume_index(states, after)
        chosen: list[tuple[PullWorkState, PullAssignment]] = []
        for state in states[start:]:
            if state.completed or state.attempts >= self._max_attempts:
                continue
            attempt = state.attempts + 1
            assignment = PullAssignment(
                assignment_id=_assignment_id(context, state.work, attempt),
                context_id=context.context_id,
                work=state.work,
                attempt=attempt,
            )
            chosen.append((state, assignment))
            if len(chosen) == request.batch_size:
                break
        if not chosen:
            return PullBatch(assignments=(), next_cursor=None)
        assignments = tuple(item[1] for item in chosen)
        expected = tuple(item[0].attempts for item in chosen)
        try:
            claimed = self._repository.claim_batch(
                context.principal_id,
                context.context_id,
                assignments,
                expected,
                max_attempts=self._max_attempts,
            )
        except PullRepositoryConflictError:
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT) from None
        if claimed != assignments:
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT)
        last_key = _work_key(assignments[-1].work)
        has_more = any(
            not state.completed and state.attempts < self._max_attempts
            for state in states[_resume_index(states, last_key) :]
        )
        next_cursor = _encode_cursor(context, snapshot, last_key) if has_more else None
        return PullBatch(assignments=assignments, next_cursor=next_cursor)

    def complete(
        self,
        context: AuthenticatedPullContext,
        completions: Sequence[PullCompletion],
    ) -> tuple[PullCompletionReceipt, ...]:
        values = tuple(completions)
        if not values or len(values) > self._max_batch_size:
            raise GoodNotesPullError(ERROR_INVALID_REQUEST)
        if len({item.assignment_id for item in values}) != len(values):
            raise GoodNotesPullError(ERROR_INVALID_REQUEST)
        if len({item.idempotency_key for item in values}) != len(values):
            raise GoodNotesPullError(ERROR_INVALID_REQUEST)
        states = {_work_key(item.work): item for item in self._validated_states(context)}
        admissions: list[PullCompletionAdmission] = []
        for completion in values:
            assignment = self._repository.assignment(context.principal_id, completion.assignment_id)
            if assignment is None:
                raise GoodNotesPullError(ERROR_STALE_ASSIGNMENT)
            if assignment.context_id != context.context_id:
                raise GoodNotesPullError(ERROR_WRONG_CONTEXT)
            work = assignment.work
            if (
                work.principal_id != context.principal_id
                or completion.run_id != work.run_id
                or completion.page_version_id != work.page_version_id
                or completion.content_sha256 != work.content_sha256
            ):
                raise GoodNotesPullError(ERROR_STALE_ASSIGNMENT)
            state = states.get(_work_key(work))
            if (
                state is None
                or assignment.attempt < 1
                or assignment.attempt > self._max_attempts
                or state.attempts < assignment.attempt
            ):
                raise GoodNotesPullError(ERROR_STALE_ASSIGNMENT)
            admissions.append(
                PullCompletionAdmission(
                    completion=completion,
                    request_fingerprint=_completion_fingerprint(context, completion),
                )
            )
        try:
            receipts = self._repository.complete_batch(
                context.principal_id,
                context.context_id,
                tuple(admissions),
            )
        except PullCompletionConflictError:
            raise GoodNotesPullError(ERROR_COMPLETION_CONFLICT) from None
        except PullRepositoryConflictError:
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT) from None
        if len(receipts) != len(values):
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT)
        return receipts

    def _validated_states(self, context: AuthenticatedPullContext) -> tuple[PullWorkState, ...]:
        states = tuple(sorted(self._repository.work_states(context.principal_id), key=_state_key))
        keys = tuple(_work_key(item.work) for item in states)
        if len(set(keys)) != len(keys):
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT)
        if any(item.work.principal_id != context.principal_id for item in states):
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT)
        return states


def _bounded_token(value: object, *, maximum: int) -> None:
    if not isinstance(value, str) or not value or len(value) > maximum:
        raise GoodNotesPullError(ERROR_INVALID_REQUEST)
    if any(character.isspace() for character in value):
        raise GoodNotesPullError(ERROR_INVALID_REQUEST)


def _sha256(value: object) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise GoodNotesPullError(ERROR_INVALID_REQUEST)


def _work_key(work: GoodNotesPageWork) -> tuple[str, str, str]:
    return (work.run_id, work.page_version_id, work.content_sha256)


def _state_key(state: PullWorkState) -> tuple[str, str, str]:
    return _work_key(state.work)


def _snapshot_digest(works: tuple[GoodNotesPageWork, ...]) -> str:
    payload = [_work_key(work) for work in works]
    return _digest(payload)


def _assignment_id(context: AuthenticatedPullContext, work: GoodNotesPageWork, attempt: int) -> str:
    return _digest(
        [context.principal_id, context.client_id, context.context_id, *_work_key(work), attempt]
    )


def _completion_fingerprint(context: AuthenticatedPullContext, completion: PullCompletion) -> str:
    return _digest(
        [
            context.principal_id,
            context.client_id,
            context.context_id,
            completion.assignment_id,
            completion.run_id,
            completion.page_version_id,
            completion.content_sha256,
            completion.result_sha256,
        ]
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _context_binding(context: AuthenticatedPullContext) -> str:
    return _digest([context.principal_id, context.client_id, context.context_id])


def _encode_cursor(
    context: AuthenticatedPullContext,
    snapshot: str,
    after: tuple[str, str, str],
) -> str:
    payload = {"v": 1, "context": _context_binding(context), "snapshot": snapshot, "after": after}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    envelope = {
        "body": base64.urlsafe_b64encode(body).decode(),
        "checksum": hashlib.sha256(body).hexdigest(),
    }
    return base64.urlsafe_b64encode(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    ).decode()


def _decode_cursor(
    token: str,
    context: AuthenticatedPullContext,
    snapshot: str,
) -> tuple[str, str, str]:
    try:
        envelope = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        body = base64.urlsafe_b64decode(envelope["body"].encode())
        if hashlib.sha256(body).hexdigest() != envelope["checksum"]:
            raise ValueError
        payload = json.loads(body.decode())
        if payload.get("v") != 1:
            raise ValueError
        after = payload["after"]
        if (
            not isinstance(after, list)
            or len(after) != 3
            or not all(isinstance(item, str) for item in after)
        ):
            raise ValueError
    except (
        binascii.Error,
        KeyError,
        TypeError,
        ValueError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        raise GoodNotesPullError(ERROR_INVALID_CURSOR) from None
    if payload.get("context") != _context_binding(context):
        raise GoodNotesPullError(ERROR_WRONG_CONTEXT)
    if payload.get("snapshot") != snapshot:
        raise GoodNotesPullError(ERROR_STALE_CURSOR)
    return (after[0], after[1], after[2])


def _resume_index(states: tuple[PullWorkState, ...], after: tuple[str, str, str] | None) -> int:
    if after is None:
        return 0
    keys = tuple(_work_key(item.work) for item in states)
    try:
        return keys.index(after) + 1
    except ValueError:
        raise GoodNotesPullError(ERROR_STALE_CURSOR) from None
