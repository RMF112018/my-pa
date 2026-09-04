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
import hmac
import json
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Protocol

from my_pa.application.goodnotes_occurrences import GoodNotesSemanticPromotionEvidence
from my_pa.contracts.ports import (
    GoodNotesPullCompletionConflictError as PullCompletionConflictError,
)
from my_pa.contracts.ports import GoodNotesPullCompletionMaterial as PullCompletionMaterial
from my_pa.contracts.ports import (
    GoodNotesPullRepositoryConflictError as PullRepositoryConflictError,
)
from my_pa.contracts.ports import (
    GoodNotesSemanticProposalMaterial,
    GoodNotesSemanticReviewConflictError,
)
from my_pa.contracts.ports import (
    GoodNotesSemanticReviewDecisionRecord as SemanticReviewDecision,
)
from my_pa.domain.goodnotes.models import GoodNotesPageWork, GoodNotesSemanticReviewCase
from my_pa.domain.identity.principal import Principal

SemanticReviewConflictError = GoodNotesSemanticReviewConflictError

MAX_PULL_BATCH_SIZE = 100
MAX_PULL_RETRIES = 10
MAX_CONTEXT_TOKEN_LENGTH = 128
MAX_IDEMPOTENCY_KEY_LENGTH = 128
MIN_CURSOR_SIGNING_KEY_BYTES = 32
MAX_CURSOR_SIGNING_KEY_BYTES = 128

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

    principal: Principal
    client_id: str
    context_id: str

    def __init__(
        self,
        principal: Principal,
        client_id: str,
        context_id: str,
        *,
        _seal: object,
    ) -> None:
        if _seal is not _CONTEXT_SEAL:
            raise GoodNotesPullError(ERROR_WRONG_CONTEXT)
        if not principal.authenticated or not principal.may_hold_authority:
            raise GoodNotesPullError(ERROR_WRONG_CONTEXT)
        _bounded_token(client_id, maximum=MAX_CONTEXT_TOKEN_LENGTH)
        _bounded_token(context_id, maximum=MAX_CONTEXT_TOKEN_LENGTH)
        object.__setattr__(self, "principal", principal)
        object.__setattr__(self, "client_id", client_id)
        object.__setattr__(self, "context_id", context_id)


def stamp_authenticated_pull_context(
    *, principal: Principal, client_id: str, context_id: str
) -> AuthenticatedPullContext:
    """Create context from authenticated server facts at the future wiring seam."""

    return AuthenticatedPullContext(
        principal,
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
    client_id: str
    context_id: str
    work: GoodNotesPageWork
    attempt: int


@dataclass(frozen=True, slots=True)
class PullBatch:
    assignments: tuple[PullAssignment, ...]
    next_cursor: str | None = field(default=None, repr=False)


@dataclass(frozen=True, slots=True)
class GoodNotesPullAssignment:
    """Public server-stamped work handle with no Principal/client context."""

    assignment_id: str
    run_id: str
    page_version_id: str
    content_sha256: str
    attempt: int
    logical_page_id: str | None = None
    renderer_name: str | None = None
    renderer_version: str | None = None
    render_profile_version: str | None = None


@dataclass(frozen=True, slots=True)
class GoodNotesPullBatch:
    """Bounded public pull result; identities originate in server assignment state."""

    assignments: tuple[GoodNotesPullAssignment, ...]
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


@dataclass(frozen=True, slots=True)
class GoodNotesCompletionReceipt:
    """Content-free public receipt; hides replay fingerprints and result identity."""

    completion_id: str
    assignment_id: str
    replayed: bool


@dataclass(frozen=True, slots=True)
class GoodNotesPullStatus:
    """Content-free status for one server-resolved Principal/client context."""

    pending: int
    assigned: int
    completed: int
    exhausted: int

    def __post_init__(self) -> None:
        values: tuple[object, ...] = (
            self.pending,
            self.assigned,
            self.completed,
            self.exhausted,
        )
        if any(
            isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in values
        ):
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT)


def public_pull_batch(batch: PullBatch) -> GoodNotesPullBatch:
    """Remove Principal/client context from an internal claimed batch."""
    return GoodNotesPullBatch(
        assignments=tuple(
            GoodNotesPullAssignment(
                assignment_id=assignment.assignment_id,
                run_id=assignment.work.run_id,
                page_version_id=assignment.work.page_version_id,
                content_sha256=assignment.work.content_sha256,
                attempt=assignment.attempt,
                logical_page_id=assignment.work.logical_page_id,
                renderer_name=assignment.work.renderer_name,
                renderer_version=assignment.work.renderer_version,
                render_profile_version=assignment.work.render_profile_version,
            )
            for assignment in batch.assignments
        ),
        next_cursor=batch.next_cursor,
    )


def public_completion_receipts(
    receipts: Sequence[PullCompletionReceipt],
) -> tuple[GoodNotesCompletionReceipt, ...]:
    """Project internal replay records without fingerprints, keys, or result digests."""
    return tuple(
        GoodNotesCompletionReceipt(
            completion_id=receipt.completion_id,
            assignment_id=receipt.assignment_id,
            replayed=receipt.replayed,
        )
        for receipt in receipts
    )


class GoodNotesPullRepository(Protocol):
    """Principal-partitioned orchestration ledger; never a source-provider port."""

    def work_states(self, principal_id: str) -> tuple[PullWorkState, ...]: ...

    def claim_batch(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        assignments: tuple[PullAssignment, ...],
        expected_attempts: tuple[int, ...],
        *,
        max_attempts: int,
    ) -> tuple[PullAssignment, ...]:
        """Atomically increment exact expected attempts and store assignments."""

    def assignment(
        self, principal_id: str, client_id: str, assignment_id: str
    ) -> PullAssignment | None: ...

    def completion_material(
        self, principal_id: str, client_id: str, assignment_id: str
    ) -> PullCompletionMaterial | None:
        """Resolve exactly one proposal for an authenticated assignment."""

    def semantic_proposal_material(
        self, principal_id: str, proposal_id: str
    ) -> GoodNotesSemanticProposalMaterial | None: ...

    def semantic_review_case(
        self, principal_id: str, review_case_id: str
    ) -> GoodNotesSemanticReviewCase | None: ...

    def complete_batch(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        admissions: tuple[PullCompletionAdmission, ...],
    ) -> tuple[PullCompletionReceipt, ...]:
        """Atomically store all completions, replay all, or reject without writes."""

    def status(self, principal_id: str, client_id: str) -> GoodNotesPullStatus:
        """Return content-free durable counts for this exact client partition."""

    def record_semantic_review(self, decision: SemanticReviewDecision) -> SemanticReviewDecision:
        """Append or exactly replay one proposal-bound review decision."""

    def semantic_review_evidence(
        self, principal_id: str, run_id: str, proposal_sha256s: tuple[str, ...]
    ) -> tuple[GoodNotesSemanticPromotionEvidence, ...]:
        """Project persisted decisions for the R8 promotion gate."""


class GoodNotesPullOrchestrator:
    """Deterministic pull policy with configurable non-time retry and batch bounds."""

    def __init__(
        self,
        *,
        repository: GoodNotesPullRepository,
        max_batch_size: int,
        max_attempts: int,
        cursor_signing_key: bytes,
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
        raw_cursor_signing_key: object = cursor_signing_key
        if (
            not isinstance(raw_cursor_signing_key, bytes)
            or not MIN_CURSOR_SIGNING_KEY_BYTES
            <= len(raw_cursor_signing_key)
            <= MAX_CURSOR_SIGNING_KEY_BYTES
        ):
            raise GoodNotesPullError(ERROR_INVALID_REQUEST)
        self._repository = repository
        self._max_batch_size = max_batch_size
        self._max_attempts = max_attempts
        self._cursor_signing_key = cursor_signing_key

    def discover(self, context: AuthenticatedPullContext, request: PullRequest) -> PullBatch:
        if request.batch_size > self._max_batch_size:
            raise GoodNotesPullError(ERROR_INVALID_REQUEST)
        states = self._validated_states(context)
        snapshot = _snapshot_digest(tuple(state.work for state in states))
        after = (
            _decode_cursor(request.cursor, context, snapshot, self._cursor_signing_key)
            if request.cursor
            else None
        )
        start = _resume_index(states, after)
        chosen: list[tuple[PullWorkState, PullAssignment]] = []
        for state in states[start:]:
            if state.completed or state.attempts >= self._max_attempts:
                continue
            attempt = state.attempts + 1
            assignment = PullAssignment(
                assignment_id=_assignment_id(context, state.work, attempt),
                client_id=context.client_id,
                context_id=context.context_id,
                work=state.work,
                attempt=attempt,
            )
            chosen.append((state, assignment))
            if len(chosen) == request.batch_size:
                break
        if not chosen:
            try:
                claimed = self._repository.claim_batch(
                    context.principal.principal_id,
                    context.client_id,
                    context.context_id,
                    (),
                    (),
                    max_attempts=self._max_attempts,
                )
            except PullRepositoryConflictError:
                raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT) from None
            if claimed:
                raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT)
            return PullBatch(assignments=(), next_cursor=None)
        assignments = tuple(item[1] for item in chosen)
        expected = tuple(item[0].attempts for item in chosen)
        try:
            claimed = self._repository.claim_batch(
                context.principal.principal_id,
                context.client_id,
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
        next_cursor = (
            _encode_cursor(context, snapshot, last_key, self._cursor_signing_key)
            if has_more
            else None
        )
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
            assignment = self._repository.assignment(
                context.principal.principal_id,
                context.client_id,
                completion.assignment_id,
            )
            if assignment is None:
                raise GoodNotesPullError(ERROR_STALE_ASSIGNMENT)
            if (
                assignment.client_id != context.client_id
                or assignment.context_id != context.context_id
            ):
                raise GoodNotesPullError(ERROR_WRONG_CONTEXT)
            work = assignment.work
            if (
                not _work_is_bound_to_principal(work, context.principal.principal_id)
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
                or state.attempts != assignment.attempt
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
                context.principal.principal_id,
                context.client_id,
                context.context_id,
                tuple(admissions),
            )
        except PullCompletionConflictError:
            raise GoodNotesPullError(ERROR_COMPLETION_CONFLICT) from None
        except PullRepositoryConflictError:
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT) from None
        if (
            len(receipts) != len(admissions)
            or any(
                not _receipt_matches_admission(receipt, admission)
                for receipt, admission in zip(receipts, admissions, strict=True)
            )
            or len({receipt.completion_id for receipt in receipts}) != len(receipts)
        ):
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT)
        return receipts

    def _validated_states(self, context: AuthenticatedPullContext) -> tuple[PullWorkState, ...]:
        states = tuple(
            sorted(self._repository.work_states(context.principal.principal_id), key=_state_key)
        )
        keys = tuple(_work_key(item.work) for item in states)
        if len(set(keys)) != len(keys):
            raise GoodNotesPullError(ERROR_REPOSITORY_CONFLICT)
        if any(
            not _work_is_bound_to_principal(state.work, context.principal.principal_id)
            for state in states
        ):
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


def _work_is_bound_to_principal(work: GoodNotesPageWork, principal_id: str) -> bool:
    """Compare immutable work with the resolved-Principal normalization."""
    return work == replace(work, principal_id=principal_id)


def _state_key(state: PullWorkState) -> tuple[str, str, str]:
    return _work_key(state.work)


def _snapshot_digest(works: tuple[GoodNotesPageWork, ...]) -> str:
    payload = [_work_key(work) for work in works]
    return _digest(payload)


def _assignment_id(context: AuthenticatedPullContext, work: GoodNotesPageWork, attempt: int) -> str:
    return _digest(
        [
            context.principal.principal_id,
            context.client_id,
            context.context_id,
            *_work_key(work),
            attempt,
        ]
    )


def _completion_fingerprint(context: AuthenticatedPullContext, completion: PullCompletion) -> str:
    return _digest(
        [
            context.principal.principal_id,
            context.client_id,
            context.context_id,
            completion.assignment_id,
            completion.run_id,
            completion.page_version_id,
            completion.content_sha256,
            completion.result_sha256,
        ]
    )


def _receipt_matches_admission(receipt: object, admission: PullCompletionAdmission) -> bool:
    if not isinstance(receipt, PullCompletionReceipt):
        return False
    completion = admission.completion
    return (
        _is_sha256(receipt.completion_id)
        and receipt.assignment_id == completion.assignment_id
        and receipt.idempotency_key == completion.idempotency_key
        and receipt.request_fingerprint == admission.request_fingerprint
        and receipt.result_sha256 == completion.result_sha256
        and isinstance(receipt.replayed, bool)
    )


def _is_sha256(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode()).hexdigest()


def _context_binding(context: AuthenticatedPullContext) -> str:
    return _digest([context.principal.principal_id, context.client_id, context.context_id])


def _encode_cursor(
    context: AuthenticatedPullContext,
    snapshot: str,
    after: tuple[str, str, str],
    signing_key: bytes,
) -> str:
    payload = {"v": 1, "context": _context_binding(context), "snapshot": snapshot, "after": after}
    body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    envelope = {
        "body": base64.urlsafe_b64encode(body).decode(),
        "mac": hmac.new(signing_key, body, hashlib.sha256).hexdigest(),
    }
    return base64.urlsafe_b64encode(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    ).decode()


def _decode_cursor(
    token: str,
    context: AuthenticatedPullContext,
    snapshot: str,
    signing_key: bytes,
) -> tuple[str, str, str]:
    try:
        envelope = json.loads(base64.urlsafe_b64decode(token.encode()).decode())
        body = base64.urlsafe_b64decode(envelope["body"].encode())
        supplied_mac = envelope["mac"]
        if not isinstance(supplied_mac, str) or not hmac.compare_digest(
            hmac.new(signing_key, body, hashlib.sha256).hexdigest(), supplied_mac
        ):
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
