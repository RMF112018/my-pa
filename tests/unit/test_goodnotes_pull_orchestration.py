"""Scheduled-client pull core: bounded, deterministic, Principal-bound, no model calls."""

from __future__ import annotations

import base64
import dataclasses
import hashlib
import json
from collections.abc import Callable
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta

import pytest

from my_pa.application.goodnotes_pull_orchestration import (
    ERROR_COMPLETION_CONFLICT,
    ERROR_INVALID_CURSOR,
    ERROR_INVALID_REQUEST,
    ERROR_REPOSITORY_CONFLICT,
    ERROR_STALE_ASSIGNMENT,
    ERROR_STALE_CURSOR,
    ERROR_WRONG_CONTEXT,
    AuthenticatedPullContext,
    GoodNotesPullError,
    GoodNotesPullOrchestrator,
    PullAssignment,
    PullCompletion,
    PullCompletionAdmission,
    PullCompletionConflictError,
    PullCompletionReceipt,
    PullRepositoryConflictError,
    PullRequest,
    PullWorkState,
    stamp_authenticated_pull_context,
)
from my_pa.contracts.ports import GoodNotesPullCompletionReceiptRecord
from my_pa.domain.goodnotes.models import GoodNotesPageWork, issue_stable_id
from my_pa.domain.identity.principal import Principal, PrincipalKind

A = "prn_aaaaaaaaaaaaaaaaaaaaaaaa"
B = "prn_bbbbbbbbbbbbbbbbbbbbbbbb"


def _work(token: str, *, principal_id: str = A) -> GoodNotesPageWork:
    return GoodNotesPageWork(
        run_id=issue_stable_id("gnrun", token),
        page_version_id=issue_stable_id("gnver", token),
        principal_id=principal_id,
        content_sha256=hashlib.sha256(token.encode()).hexdigest(),
        logical_page_id=issue_stable_id("gnlp", token),
        renderer_name="synthetic",
        renderer_version="1",
        render_profile_version="unit-v1",
    )


def _context(
    *, principal_id: str = A, client_id: str = "chatllm-client", context_id: str = "auth-1"
) -> AuthenticatedPullContext:
    return stamp_authenticated_pull_context(
        principal=Principal(
            principal_id=principal_id,
            kind=PrincipalKind.GATEWAY,
            authenticated=True,
        ),
        client_id=client_id,
        context_id=context_id,
    )


def _completion(assignment: PullAssignment, *, result_label: str = "result") -> PullCompletion:
    return PullCompletion(
        assignment_id=assignment.assignment_id,
        run_id=assignment.work.run_id,
        page_version_id=assignment.work.page_version_id,
        content_sha256=assignment.work.content_sha256,
        result_sha256=hashlib.sha256(result_label.encode()).hexdigest(),
        idempotency_key=f"complete-{result_label}",
    )


@dataclass
class _MemoryPullRepository:
    states: dict[tuple[str, str, str], PullWorkState]
    assignments: dict[tuple[str, str], PullAssignment] = field(default_factory=dict)
    receipts: dict[tuple[str, str], PullCompletionReceipt] = field(default_factory=dict)
    keys: dict[tuple[str, str, str], PullCompletionReceipt] = field(default_factory=dict)
    client_states: dict[tuple[str, str, tuple[str, str, str]], PullWorkState] = field(
        default_factory=dict
    )
    sessions: dict[tuple[str, str], tuple[str, int, int]] = field(default_factory=dict)
    now: datetime = datetime(2026, 9, 5, tzinfo=UTC)
    claim_calls: int = 0
    complete_calls: int = 0
    source_mutations: int = 0
    fail_claim: bool = False
    assignment_clients: list[str] = field(default_factory=list)
    corrupt_receipt: Callable[[PullCompletionReceipt], PullCompletionReceipt] | None = None
    reverse_receipts: bool = False

    @classmethod
    def with_work(cls, *works: GoodNotesPageWork) -> _MemoryPullRepository:
        return cls(states={_key(work): PullWorkState(work=work) for work in works})

    def lock_session(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        *,
        max_attempts: int,
        lease_seconds: int,
    ) -> datetime:
        key = (principal_id, client_id)
        policy = (context_id, max_attempts, lease_seconds)
        if self.sessions.setdefault(key, policy) != policy:
            raise PullRepositoryConflictError
        return self.now

    def work_states(self, principal_id: str, client_id: str) -> tuple[PullWorkState, ...]:
        return tuple(
            self.client_states.get((principal_id, client_id, _key(item.work)), item)
            for item in self.states.values()
            if item.work.principal_id == principal_id
        )

    def claim_batch(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        assignments: tuple[PullAssignment, ...],
        expected_attempts: tuple[int, ...],
        *,
        max_attempts: int,
        lease_seconds: int,
    ) -> tuple[PullAssignment, ...]:
        self.lock_session(
            principal_id,
            client_id,
            context_id,
            max_attempts=max_attempts,
            lease_seconds=lease_seconds,
        )
        self.claim_calls += 1
        if self.fail_claim:
            raise PullRepositoryConflictError
        pending: list[tuple[tuple[str, str, str], PullWorkState, PullAssignment]] = []
        for assignment, expected in zip(assignments, expected_attempts, strict=True):
            key = _key(assignment.work)
            state = self.client_states.get((principal_id, client_id, key), self.states.get(key))
            if (
                state is None
                or state.work.principal_id != principal_id
                or state.attempts != expected
                or state.completed
                or (
                    state.assigned_at is not None
                    and self.now < state.assigned_at + timedelta(seconds=lease_seconds)
                )
                or expected >= max_attempts
                or assignment.client_id != client_id
                or assignment.context_id != context_id
                or assignment.attempt != expected + 1
            ):
                raise PullRepositoryConflictError
            pending.append((key, state, assignment))
        for key, state, assignment in pending:
            self.client_states[(principal_id, client_id, key)] = replace(
                state,
                attempts=assignment.attempt,
                latest_assignment=assignment,
                assigned_at=self.now,
            )
            self.assignments[(principal_id, assignment.assignment_id)] = assignment
        return assignments

    def assignment(
        self, principal_id: str, client_id: str, assignment_id: str
    ) -> PullAssignment | None:
        self.assignment_clients.append(client_id)
        return self.assignments.get((principal_id, assignment_id))

    def complete_batch(
        self,
        principal_id: str,
        client_id: str,
        context_id: str,
        admissions: tuple[PullCompletionAdmission, ...],
    ) -> tuple[PullCompletionReceipt, ...]:
        self.complete_calls += 1
        result: list[PullCompletionReceipt] = []
        pending: list[tuple[tuple[str, str, str], PullCompletionReceipt]] = []
        for admission in admissions:
            completion = admission.completion
            assignment = self.assignments.get((principal_id, completion.assignment_id))
            if (
                assignment is None
                or assignment.client_id != client_id
                or assignment.context_id != context_id
            ):
                raise PullRepositoryConflictError
            prior_assignment = self.receipts.get((principal_id, completion.assignment_id))
            prior_key = self.keys.get((principal_id, client_id, completion.idempotency_key))
            prior = prior_assignment or prior_key
            if prior is not None:
                if (
                    prior.assignment_id != completion.assignment_id
                    or prior.idempotency_key != completion.idempotency_key
                    or prior.request_fingerprint != admission.request_fingerprint
                    or prior.result_sha256 != completion.result_sha256
                ):
                    raise PullCompletionConflictError
                result.append(replace(prior, replayed=True))
                continue
            receipt = PullCompletionReceipt(
                completion_id=hashlib.sha256(
                    f"{principal_id}:{completion.assignment_id}".encode()
                ).hexdigest(),
                assignment_id=completion.assignment_id,
                idempotency_key=completion.idempotency_key,
                request_fingerprint=admission.request_fingerprint,
                result_sha256=completion.result_sha256,
            )
            pending.append((_key(assignment.work), receipt))
            result.append(receipt)
        for key, receipt in pending:
            self.receipts[(principal_id, receipt.assignment_id)] = receipt
            self.keys[(principal_id, client_id, receipt.idempotency_key)] = receipt
            partition_key = (principal_id, client_id, key)
            self.client_states[partition_key] = replace(
                self.client_states[partition_key], completed=True
            )
        if self.corrupt_receipt is not None:
            result = [self.corrupt_receipt(receipt) for receipt in result]
        if self.reverse_receipts:
            result.reverse()
        return tuple(result)


def _key(work: GoodNotesPageWork) -> tuple[str, str, str]:
    return (work.run_id, work.page_version_id, work.content_sha256)


def _service(
    repository: _MemoryPullRepository, *, max_batch_size: int = 2, max_attempts: int = 2
) -> GoodNotesPullOrchestrator:
    return GoodNotesPullOrchestrator(
        repository=repository,
        max_batch_size=max_batch_size,
        max_attempts=max_attempts,
        cursor_signing_key=_cursor_signing_key(),
    )


def _cursor_signing_key() -> bytes:
    return hashlib.sha256(b"synthetic GoodNotes cursor signing material").digest()


def test_request_cannot_carry_principal_or_authenticated_context() -> None:
    fields = {item.name for item in dataclasses.fields(PullRequest)}
    assert fields == {"batch_size", "cursor"}
    with pytest.raises(TypeError):
        PullRequest(batch_size=1, principal_id=A)  # type: ignore[call-arg]
    with pytest.raises(GoodNotesPullError) as raised:
        AuthenticatedPullContext(
            Principal(A, PrincipalKind.GATEWAY, authenticated=True),
            "client",
            "context",
            _seal=object(),
        )
    assert raised.value.code == ERROR_WRONG_CONTEXT


def test_application_and_durable_completion_use_one_receipt_contract() -> None:
    assert PullCompletionReceipt is GoodNotesPullCompletionReceiptRecord


@pytest.mark.parametrize("batch_size", (0, -1, 101, True))
def test_batch_bound_fails_before_repository_use(batch_size: int) -> None:
    repo = _MemoryPullRepository.with_work(_work("a"))
    with pytest.raises(GoodNotesPullError) as raised:
        PullRequest(batch_size=batch_size)
    assert raised.value.code == ERROR_INVALID_REQUEST
    assert repo.claim_calls == 0


def test_discovery_is_deterministic_bounded_and_resumes_without_duplicates() -> None:
    works = (_work("z"), _work("a"), _work("m"))
    repo = _MemoryPullRepository.with_work(*works)
    service = _service(repo)
    context = _context()
    first = service.discover(context, PullRequest(batch_size=2))
    expected = tuple(sorted(works, key=_key))
    assert tuple(item.work for item in first.assignments) == expected[:2]
    assert first.next_cursor is not None
    service.complete(
        context,
        tuple(
            _completion(item, result_label=str(index))
            for index, item in enumerate(first.assignments)
        ),
    )
    second = service.discover(context, PullRequest(batch_size=2, cursor=first.next_cursor))
    assert tuple(item.work for item in second.assignments) == expected[2:]
    assert second.next_cursor is None
    assert {item.assignment_id for item in first.assignments}.isdisjoint(
        item.assignment_id for item in second.assignments
    )


def test_cursor_is_context_bound_malformed_and_stale_after_snapshot_change() -> None:
    repo = _MemoryPullRepository.with_work(_work("a"), _work("b"), _work("c"))
    service = _service(repo, max_batch_size=1)
    context = _context()
    first = service.discover(context, PullRequest(batch_size=1))
    assert first.next_cursor is not None
    with pytest.raises(GoodNotesPullError) as wrong:
        service.discover(
            _context(context_id="auth-2"),
            PullRequest(batch_size=1, cursor=first.next_cursor),
        )
    assert wrong.value.code == ERROR_REPOSITORY_CONFLICT
    with pytest.raises(GoodNotesPullError) as malformed:
        service.discover(context, PullRequest(batch_size=1, cursor="not-a-cursor"))
    assert malformed.value.code == ERROR_INVALID_CURSOR
    added = _work("d")
    repo.states[_key(added)] = PullWorkState(work=added)
    with pytest.raises(GoodNotesPullError) as stale:
        service.discover(context, PullRequest(batch_size=1, cursor=first.next_cursor))
    assert stale.value.code == ERROR_STALE_CURSOR


def test_cursor_payload_cannot_be_forged_with_a_recomputed_public_hash() -> None:
    works = (_work("a"), _work("b"), _work("c"))
    repo = _MemoryPullRepository.with_work(*works)
    service = _service(repo, max_batch_size=1)
    context = _context()
    first = service.discover(context, PullRequest(batch_size=1))
    assert first.next_cursor is not None
    claims_before_forgery = repo.claim_calls

    envelope = json.loads(base64.urlsafe_b64decode(first.next_cursor.encode()).decode())
    payload = json.loads(base64.urlsafe_b64decode(envelope["body"].encode()).decode())
    payload["after"] = list(_key(max(works, key=_key)))
    rewritten_body = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    envelope["body"] = base64.urlsafe_b64encode(rewritten_body).decode()
    envelope["mac"] = hashlib.sha256(rewritten_body).hexdigest()
    forged = base64.urlsafe_b64encode(
        json.dumps(envelope, sort_keys=True, separators=(",", ":")).encode()
    ).decode()

    with pytest.raises(GoodNotesPullError) as rejected:
        service.discover(context, PullRequest(batch_size=1, cursor=forged))
    assert rejected.value.code == ERROR_INVALID_CURSOR
    assert repo.claim_calls == claims_before_forgery

    continued = service.discover(context, PullRequest(batch_size=1, cursor=first.next_cursor))
    assert continued.assignments == first.assignments


@pytest.mark.parametrize("key", (b"short", b"x" * 129, "x" * 32))
def test_cursor_signing_key_has_no_weak_default_and_is_bounded(key: object) -> None:
    repo = _MemoryPullRepository.with_work(_work("key"))
    with pytest.raises(GoodNotesPullError) as raised:
        GoodNotesPullOrchestrator(
            repository=repo,
            max_batch_size=1,
            max_attempts=1,
            cursor_signing_key=key,  # type: ignore[arg-type]
        )
    assert raised.value.code == ERROR_INVALID_REQUEST


def test_cursor_signing_key_is_required_and_not_exposed_by_service_repr() -> None:
    repo = _MemoryPullRepository.with_work(_work("key-required"))
    with pytest.raises(TypeError):
        GoodNotesPullOrchestrator(  # type: ignore[call-arg]
            repository=repo,
            max_batch_size=1,
            max_attempts=1,
        )
    signing_key = b"s" * 32
    service = GoodNotesPullOrchestrator(
        repository=repo,
        max_batch_size=1,
        max_attempts=1,
        cursor_signing_key=signing_key,
    )
    assert signing_key.decode() not in repr(service)
    assert signing_key.hex() not in repr(service)


def test_retries_are_bounded_and_never_mutate_the_source() -> None:
    repo = _MemoryPullRepository.with_work(_work("retry"))
    service = _service(repo, max_batch_size=1, max_attempts=2)
    context = _context()
    first = service.discover(context, PullRequest(batch_size=1))
    repo.now += timedelta(seconds=900)
    second = service.discover(context, PullRequest(batch_size=1))
    repo.now += timedelta(seconds=900)
    exhausted = service.discover(context, PullRequest(batch_size=1))
    assert [first.assignments[0].attempt, second.assignments[0].attempt] == [1, 2]
    assert exhausted.assignments == ()
    assert repo.source_mutations == 0


def test_only_the_current_retry_assignment_may_complete() -> None:
    repo = _MemoryPullRepository.with_work(_work("stale-retry"))
    service = _service(repo, max_batch_size=1, max_attempts=2)
    context = _context()
    first = service.discover(context, PullRequest(batch_size=1)).assignments[0]
    repo.now += timedelta(seconds=900)
    second = service.discover(context, PullRequest(batch_size=1)).assignments[0]
    assert (first.attempt, second.attempt) == (1, 2)
    with pytest.raises(GoodNotesPullError) as stale:
        service.complete(context, (_completion(first),))
    assert stale.value.code == ERROR_STALE_ASSIGNMENT
    assert repo.complete_calls == 0
    assert repo.receipts == {}
    accepted = service.complete(context, (_completion(second),))
    assert accepted[0].assignment_id == second.assignment_id
    assert accepted[0].replayed is False


def test_atomic_claim_conflict_returns_no_partial_batch() -> None:
    repo = _MemoryPullRepository.with_work(_work("a"), _work("b"))
    repo.fail_claim = True
    with pytest.raises(GoodNotesPullError) as raised:
        _service(repo).discover(_context(), PullRequest(batch_size=2))
    assert raised.value.code == ERROR_REPOSITORY_CONFLICT
    assert all(item.attempts == 0 for item in repo.states.values())


def test_completion_replays_idempotently_and_completed_work_is_not_rediscovered() -> None:
    repo = _MemoryPullRepository.with_work(_work("done"))
    service = _service(repo, max_batch_size=1)
    context = _context()
    assignment = service.discover(context, PullRequest(batch_size=1)).assignments[0]
    completion = _completion(assignment)
    first = service.complete(context, (completion,))
    second = service.complete(context, (completion,))
    assert first[0].replayed is False
    assert second[0].replayed is True
    assert second[0].completion_id == first[0].completion_id
    assert service.discover(context, PullRequest(batch_size=1)).assignments == ()
    assert repo.source_mutations == 0


@pytest.mark.parametrize(
    "corrupt_receipt",
    (
        lambda receipt: replace(receipt, completion_id="not-a-sha256"),
        lambda receipt: replace(receipt, assignment_id="f" * 64),
        lambda receipt: replace(receipt, idempotency_key="wrong-key"),
        lambda receipt: replace(receipt, request_fingerprint="f" * 64),
        lambda receipt: replace(receipt, result_sha256="f" * 64),
        lambda receipt: replace(receipt, replayed=1),
    ),
    ids=(
        "completion-id",
        "assignment-id",
        "idempotency-key",
        "request-fingerprint",
        "result-sha256",
        "replayed-flag",
    ),
)
def test_corrupt_completion_receipt_is_rejected(
    corrupt_receipt: Callable[[PullCompletionReceipt], PullCompletionReceipt],
) -> None:
    repo = _MemoryPullRepository.with_work(_work("corrupt-receipt"))
    repo.corrupt_receipt = corrupt_receipt
    service = _service(repo, max_batch_size=1)
    context = _context()
    assignment = service.discover(context, PullRequest(batch_size=1)).assignments[0]

    with pytest.raises(GoodNotesPullError) as raised:
        service.complete(context, (_completion(assignment),))

    assert raised.value.code == ERROR_REPOSITORY_CONFLICT


def test_completion_receipts_must_correspond_to_admission_order() -> None:
    repo = _MemoryPullRepository.with_work(_work("first"), _work("second"))
    repo.reverse_receipts = True
    service = _service(repo)
    context = _context()
    assignments = service.discover(context, PullRequest(batch_size=2)).assignments
    completions = tuple(
        _completion(assignment, result_label=str(index))
        for index, assignment in enumerate(assignments)
    )

    with pytest.raises(GoodNotesPullError) as raised:
        service.complete(context, completions)

    assert raised.value.code == ERROR_REPOSITORY_CONFLICT


def test_changed_idempotent_completion_conflicts_without_overwrite() -> None:
    repo = _MemoryPullRepository.with_work(_work("conflict"))
    service = _service(repo, max_batch_size=1)
    context = _context()
    assignment = service.discover(context, PullRequest(batch_size=1)).assignments[0]
    original = _completion(assignment)
    first = service.complete(context, (original,))[0]
    changed = replace(original, result_sha256=hashlib.sha256(b"changed").hexdigest())
    with pytest.raises(GoodNotesPullError) as raised:
        service.complete(context, (changed,))
    assert raised.value.code == ERROR_COMPLETION_CONFLICT
    assert repo.receipts[(A, assignment.assignment_id)] == first


def test_wrong_context_and_mismatched_work_reject_before_completion_write() -> None:
    repo = _MemoryPullRepository.with_work(_work("wrong"))
    service = _service(repo, max_batch_size=2)
    context = _context()
    assignment = service.discover(context, PullRequest(batch_size=1)).assignments[0]
    completion = _completion(assignment)
    with pytest.raises(GoodNotesPullError) as wrong:
        service.complete(_context(context_id="auth-2"), (completion,))
    assert wrong.value.code == ERROR_REPOSITORY_CONFLICT
    mismatched = replace(completion, content_sha256="f" * 64)
    with pytest.raises(GoodNotesPullError) as stale:
        service.complete(context, (mismatched,))
    assert stale.value.code == ERROR_STALE_ASSIGNMENT
    assert repo.receipts == {}


def test_second_client_in_same_context_cannot_complete_first_clients_assignment() -> None:
    repo = _MemoryPullRepository.with_work(_work("client-bound"))
    service = _service(repo, max_batch_size=1)
    first_client = _context(client_id="chatllm-client-a")
    assignment = service.discover(first_client, PullRequest(batch_size=1)).assignments[0]
    completion = _completion(assignment)

    with pytest.raises(GoodNotesPullError) as wrong:
        service.complete(
            _context(client_id="chatllm-client-b", context_id=first_client.context_id),
            (completion,),
        )
    assert wrong.value.code == ERROR_WRONG_CONTEXT
    assert repo.assignment_clients[-1] == "chatllm-client-b"
    assert repo.complete_calls == 0
    assert repo.receipts == {}

    accepted = service.complete(first_client, (completion,))
    assert accepted[0].assignment_id == assignment.assignment_id


def test_malformed_multi_completion_rejects_atomically() -> None:
    repo = _MemoryPullRepository.with_work(_work("a"), _work("b"))
    service = _service(repo)
    context = _context()
    assignments = service.discover(context, PullRequest(batch_size=2)).assignments
    valid = _completion(assignments[0], result_label="a")
    stale = replace(
        _completion(assignments[1], result_label="b"), page_version_id=valid.page_version_id
    )
    with pytest.raises(GoodNotesPullError) as raised:
        service.complete(context, (valid, stale))
    assert raised.value.code == ERROR_STALE_ASSIGNMENT
    assert repo.complete_calls == 0
    assert repo.receipts == {}


def test_other_principal_work_is_never_discovered() -> None:
    mine = _work("mine")
    other = _work("other", principal_id=B)
    repo = _MemoryPullRepository.with_work(other, mine)
    batch = _service(repo).discover(_context(), PullRequest(batch_size=2))
    assert tuple(item.work for item in batch.assignments) == (mine,)


@pytest.mark.parametrize("lease", [True, False, 0, 59, 86401, 900.0])
def test_invalid_assignment_lease_fails_before_repository_use(lease: int) -> None:
    repo = _MemoryPullRepository.with_work(_work("lease"))
    with pytest.raises(GoodNotesPullError, match=ERROR_INVALID_REQUEST):
        GoodNotesPullOrchestrator(
            repository=repo,
            max_batch_size=1,
            max_attempts=2,
            cursor_signing_key=_cursor_signing_key(),
            assignment_lease_seconds=lease,
        )
    assert repo.sessions == {}


def test_restart_cursor_loss_and_lease_boundary_preserve_assignment() -> None:
    repo = _MemoryPullRepository.with_work(_work("lease"))
    first = _service(repo).discover(_context(), PullRequest(1)).assignments[0]
    repo.now += timedelta(seconds=899, microseconds=999999)
    assert _service(repo).discover(_context(), PullRequest(1)).assignments == (first,)
    repo.now += timedelta(microseconds=1)
    second = _service(repo).discover(_context(), PullRequest(1)).assignments[0]
    assert second.attempt == 2 and second.assignment_id != first.assignment_id
    assert _service(repo).discover(_context(), PullRequest(1)).assignments == (second,)
    repo.now += timedelta(seconds=900)
    assert _service(repo).discover(_context(), PullRequest(1)).assignments == ()
    # Expiry alone never invalidates an unsuperseded completion.
    assert (
        _service(repo).complete(_context(), (_completion(second),))[0].assignment_id
        == second.assignment_id
    )


def test_expired_completion_winning_prevents_successor() -> None:
    repo = _MemoryPullRepository.with_work(_work("completion-first"))
    first = _service(repo).discover(_context(), PullRequest(1)).assignments[0]
    repo.now += timedelta(seconds=900)
    _service(repo).complete(_context(), (_completion(first),))
    assert _service(repo).discover(_context(), PullRequest(1)).assignments == ()
    assert next(iter(repo.client_states.values())).attempts == 1


def test_clients_have_independent_attempts_and_completion_keys() -> None:
    repo = _MemoryPullRepository.with_work(_work("clients"))
    client_a, client_b = _context(client_id="a"), _context(client_id="b")
    a = _service(repo).discover(client_a, PullRequest(1)).assignments[0]
    b = _service(repo).discover(client_b, PullRequest(1)).assignments[0]
    assert a.attempt == b.attempt == 1 and a.assignment_id != b.assignment_id
    _service(repo).complete(client_a, (_completion(a),))
    assert _service(repo).discover(client_b, PullRequest(1)).assignments == (b,)
    _service(repo).complete(client_b, (_completion(b),))
    assert len(repo.keys) == 2


def test_oldest_outstanding_precedes_cursor_and_fresh_work() -> None:
    works = tuple(sorted((_work("a"), _work("b"), _work("c")), key=_key))
    repo = _MemoryPullRepository.with_work(*works)
    first = _service(repo).discover(_context(), PullRequest(1))
    repo.now += timedelta(seconds=1)
    expanded = _service(repo).discover(_context(), PullRequest(2, cursor=first.next_cursor))
    assert expanded.assignments[0] == first.assignments[0]
    assert expanded.assignments[1].work == works[1]
    assert _service(repo).discover(_context(), PullRequest(1)).assignments == first.assignments
    _service(repo).complete(_context(), (_completion(first.assignments[0]),))
    assert (
        _service(repo).discover(_context(), PullRequest(1)).assignments == expanded.assignments[1:]
    )


@pytest.mark.parametrize("change", ["lease", "attempts", "context"])
def test_existing_session_rejects_changed_policy(change: str) -> None:
    repo = _MemoryPullRepository.with_work(_work("policy"))
    _service(repo).discover(_context(), PullRequest(1))
    service = GoodNotesPullOrchestrator(
        repository=repo,
        max_batch_size=2,
        max_attempts=3 if change == "attempts" else 2,
        assignment_lease_seconds=901 if change == "lease" else 900,
        cursor_signing_key=_cursor_signing_key(),
    )
    with pytest.raises(GoodNotesPullError, match=ERROR_REPOSITORY_CONFLICT):
        service.discover(
            _context(context_id="changed" if change == "context" else "auth-1"), PullRequest(1)
        )
    assert next(iter(repo.client_states.values())).attempts == 1


@pytest.mark.parametrize(
    "corruption", ["time", "future", "missing", "client", "context", "identity", "work", "attempt"]
)
def test_corrupt_assignment_state_fails_closed(corruption: str) -> None:
    repo = _MemoryPullRepository.with_work(_work("corrupt"))
    first = _service(repo).discover(_context(), PullRequest(1)).assignments[0]
    key, state = next(iter(repo.client_states.items()))
    changes: dict[str, object] = {}
    if corruption == "time":
        changes["assigned_at"] = repo.now.replace(tzinfo=None)
    elif corruption == "future":
        changes["assigned_at"] = repo.now + timedelta(seconds=1)
    elif corruption == "missing":
        changes["latest_assignment"] = None
    else:
        assignment_changes = {
            "client": {"client_id": "foreign"},
            "context": {"context_id": "foreign"},
            "identity": {"assignment_id": "f" * 64},
            "work": {"work": _work("foreign")},
            "attempt": {"attempt": 2},
        }
        changes["latest_assignment"] = replace(first, **assignment_changes[corruption])
    repo.client_states[key] = replace(state, **changes)
    with pytest.raises(GoodNotesPullError, match=ERROR_REPOSITORY_CONFLICT):
        _service(repo).discover(_context(), PullRequest(1))


def test_naive_repository_clock_fails_closed() -> None:
    repo = _MemoryPullRepository.with_work(_work("clock"))
    repo.now = repo.now.replace(tzinfo=None)
    with pytest.raises(GoodNotesPullError, match=ERROR_REPOSITORY_CONFLICT):
        _service(repo).discover(_context(), PullRequest(1))
    assert repo.claim_calls == 0


def test_resume_order_uses_assignment_age_before_work_key() -> None:
    older_work, later_work = sorted((_work("old"), _work("new")), key=_key, reverse=True)
    repo = _MemoryPullRepository.with_work(older_work)
    first = _service(repo).discover(_context(), PullRequest(1)).assignments[0]
    repo.now += timedelta(seconds=1)
    repo.states[_key(later_work)] = PullWorkState(later_work)
    expanded = _service(repo).discover(_context(), PullRequest(2)).assignments
    assert expanded[0] == first and expanded[1].work == later_work
    # Repository inventory sorts the later work first; persisted age still wins.
    assert _service(repo).discover(_context(), PullRequest(1)).assignments == (first,)
