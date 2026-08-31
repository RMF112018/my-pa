"""Scheduled-client pull core: bounded, deterministic, Principal-bound, no model calls."""

from __future__ import annotations

import dataclasses
import hashlib
from dataclasses import dataclass, field, replace

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
from my_pa.domain.goodnotes.models import GoodNotesPageWork, issue_stable_id

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
        principal_id=principal_id,
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
    keys: dict[tuple[str, str], PullCompletionReceipt] = field(default_factory=dict)
    claim_calls: int = 0
    complete_calls: int = 0
    source_mutations: int = 0
    fail_claim: bool = False

    @classmethod
    def with_work(cls, *works: GoodNotesPageWork) -> _MemoryPullRepository:
        return cls(states={_key(work): PullWorkState(work=work) for work in works})

    def work_states(self, principal_id: str) -> tuple[PullWorkState, ...]:
        return tuple(
            item for item in self.states.values() if item.work.principal_id == principal_id
        )

    def claim_batch(
        self,
        principal_id: str,
        context_id: str,
        assignments: tuple[PullAssignment, ...],
        expected_attempts: tuple[int, ...],
        *,
        max_attempts: int,
    ) -> tuple[PullAssignment, ...]:
        self.claim_calls += 1
        if self.fail_claim:
            raise PullRepositoryConflictError
        pending: list[tuple[tuple[str, str, str], PullWorkState, PullAssignment]] = []
        for assignment, expected in zip(assignments, expected_attempts, strict=True):
            key = _key(assignment.work)
            state = self.states.get(key)
            if (
                state is None
                or state.work.principal_id != principal_id
                or state.attempts != expected
                or state.completed
                or expected >= max_attempts
                or assignment.context_id != context_id
                or assignment.attempt != expected + 1
            ):
                raise PullRepositoryConflictError
            pending.append((key, state, assignment))
        for key, state, assignment in pending:
            self.states[key] = replace(state, attempts=assignment.attempt)
            self.assignments[(principal_id, assignment.assignment_id)] = assignment
        return assignments

    def assignment(self, principal_id: str, assignment_id: str) -> PullAssignment | None:
        return self.assignments.get((principal_id, assignment_id))

    def complete_batch(
        self,
        principal_id: str,
        context_id: str,
        admissions: tuple[PullCompletionAdmission, ...],
    ) -> tuple[PullCompletionReceipt, ...]:
        self.complete_calls += 1
        result: list[PullCompletionReceipt] = []
        pending: list[tuple[tuple[str, str, str], PullCompletionReceipt]] = []
        for admission in admissions:
            completion = admission.completion
            assignment = self.assignments.get((principal_id, completion.assignment_id))
            if assignment is None or assignment.context_id != context_id:
                raise PullRepositoryConflictError
            prior_assignment = self.receipts.get((principal_id, completion.assignment_id))
            prior_key = self.keys.get((principal_id, completion.idempotency_key))
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
            self.keys[(principal_id, receipt.idempotency_key)] = receipt
            self.states[key] = replace(self.states[key], completed=True)
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
    )


def test_request_cannot_carry_principal_or_authenticated_context() -> None:
    fields = {item.name for item in dataclasses.fields(PullRequest)}
    assert fields == {"batch_size", "cursor"}
    with pytest.raises(TypeError):
        PullRequest(batch_size=1, principal_id=A)  # type: ignore[call-arg]
    with pytest.raises(GoodNotesPullError) as raised:
        AuthenticatedPullContext(A, "client", "context", _seal=object())
    assert raised.value.code == ERROR_WRONG_CONTEXT


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
    assert wrong.value.code == ERROR_WRONG_CONTEXT
    with pytest.raises(GoodNotesPullError) as malformed:
        service.discover(context, PullRequest(batch_size=1, cursor="not-a-cursor"))
    assert malformed.value.code == ERROR_INVALID_CURSOR
    added = _work("d")
    repo.states[_key(added)] = PullWorkState(work=added)
    with pytest.raises(GoodNotesPullError) as stale:
        service.discover(context, PullRequest(batch_size=1, cursor=first.next_cursor))
    assert stale.value.code == ERROR_STALE_CURSOR


def test_retries_are_bounded_and_never_mutate_the_source() -> None:
    repo = _MemoryPullRepository.with_work(_work("retry"))
    service = _service(repo, max_batch_size=1, max_attempts=2)
    context = _context()
    first = service.discover(context, PullRequest(batch_size=1))
    second = service.discover(context, PullRequest(batch_size=1))
    exhausted = service.discover(context, PullRequest(batch_size=1))
    assert [first.assignments[0].attempt, second.assignments[0].attempt] == [1, 2]
    assert exhausted.assignments == ()
    assert repo.source_mutations == 0


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
    assert wrong.value.code == ERROR_WRONG_CONTEXT
    mismatched = replace(completion, content_sha256="f" * 64)
    with pytest.raises(GoodNotesPullError) as stale:
        service.complete(context, (mismatched,))
    assert stale.value.code == ERROR_STALE_ASSIGNMENT
    assert repo.receipts == {}


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
