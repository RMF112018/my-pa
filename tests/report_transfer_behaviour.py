"""One behaviour table for the transfer repository, run on PostgreSQL and on the fake.

Reports Modernization WP06 B3/B6. Each scenario takes a `Harness` (one
transaction per `tx` call, a real filesystem staging under a temporary root)
and asserts the outcome. `tests/database/test_reports_transfer_repository.py`
runs every scenario against `SqlReportTransferRepository` on a disposable
head clone; `tests/unit/test_reports_transfer_repository_fake.py` runs the
same scenarios against the `FakeUnitOfWork` repository (FAST), so the two
cannot diverge on anything this table states.

Every identifier, digest and byte is synthetic.
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Protocol, TypeVar

import pytest

from my_pa.contracts.ports import (
    ReportIdempotencyConflictError,
    ReportTransferConflictError,
    ReportTransferDigestError,
    ReportTransferNotFoundError,
    ReportTransferQuotaError,
    ReportTransferRepository,
    ReportTransferStagingError,
    TransferSession,
)
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.transfer import (
    TRANSFER_CHUNK_BYTES,
    TransferDeclaration,
    mint_content_token,
)
from my_pa.domain.reports.vocabulary import ContentEncoding, ContentFormat, TransferState
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.report_content_stores.staging import FilesystemReportTransferStaging

T = TypeVar("T")

PRINCIPAL_A: Final = "prn_aaaa0001aaaa0001aaaa0001"
PRINCIPAL_B: Final = "prn_bbbb0002bbbb0002bbbb0002"
CLIENT_1: Final = "remote_client:gcrt_" + "1" * 40
CLIENT_2: Final = "remote_client:gcrt_" + "2" * 40
CLIENT_3: Final = "local_principal:gcrt_" + "3" * 40
T0: Final = datetime(2026, 11, 7, 9, 0, tzinfo=UTC)
LATER: Final = T0 + timedelta(minutes=5)
EXPIRED: Final = T0 + timedelta(hours=2)
MAX_DECLARED: Final = 16_777_216


class Harness(Protocol):
    staging: FilesystemReportTransferStaging
    staging_root: Path

    def tx(self, work: Callable[[ReportTransferRepository], T]) -> T:
        """Run `work` in one transaction (committed on success, rolled back on error)."""
        ...

    def content_id(self, principal_id: str) -> str:
        """A content row id of `principal_id` that a session may be consumed into."""
        ...


def payload(byte_count: int, seed: int = 0) -> bytes:
    """Deterministic synthetic bytes."""
    blocks = (
        hashlib.sha256(f"synthetic-{seed}-{i}".encode()).digest()
        for i in range(byte_count // 32 + 1)
    )
    return b"".join(blocks)[:byte_count]


def sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def declaration(
    data: bytes | None = None, *, byte_count: int = 0, ttl: int = 3600
) -> TransferDeclaration:
    if data is not None:
        return TransferDeclaration(
            ContentFormat.TEXT, ContentEncoding.IDENTITY, len(data), sha(data), ttl
        )
    return TransferDeclaration(
        ContentFormat.TEXT, ContentEncoding.IDENTITY, byte_count, "0" * 64, ttl
    )


def pieces(data: bytes) -> list[bytes]:
    return [data[i : i + TRANSFER_CHUNK_BYTES] for i in range(0, len(data), TRANSFER_CHUNK_BYTES)]


#: Three chunks: two full, one of 10 bytes.
THREE: Final = payload(2 * TRANSFER_CHUNK_BYTES + 10)


def begin(
    h: Harness,
    decl: TransferDeclaration,
    key: str,
    *,
    principal_id: str = PRINCIPAL_A,
    client_ref: str = CLIENT_1,
    now: datetime = T0,
) -> tuple[TransferSession, bool]:
    return h.tx(
        lambda r: r.begin(
            decl, principal_id=principal_id, client_ref=client_ref, idempotency_key=key, now=now
        )
    )


def append(
    h: Harness,
    session_id: str,
    sequence: int,
    data: bytes,
    *,
    principal_id: str = PRINCIPAL_A,
    client_ref: str = CLIENT_1,
    now: datetime = LATER,
    chunk_sha256: str | None = None,
) -> tuple[object, bool]:
    def work(r: ReportTransferRepository) -> tuple[object, bool]:
        session = r.lock_usable(
            session_id, principal_id=principal_id, client_ref=client_ref, now=now
        )
        return r.append_chunk(
            session,
            sequence=sequence,
            chunk_sha256=chunk_sha256 or sha(data),
            data=data,
            staging=h.staging,
            now=now,
        )

    return h.tx(work)


def upload(h: Harness, data: bytes, key: str, **kwargs: object) -> TransferSession:
    session, _ = begin(h, declaration(data), key, **kwargs)  # type: ignore[arg-type]
    scope = {k: v for k, v in kwargs.items() if k in ("principal_id", "client_ref")}
    for sequence, piece in enumerate(pieces(data)):
        append(h, session.session_id, sequence, piece, **scope)  # type: ignore[arg-type]
    return lock(h, session.session_id, **scope)  # type: ignore[arg-type]


def lock(
    h: Harness,
    session_id: str,
    *,
    principal_id: str = PRINCIPAL_A,
    client_ref: str = CLIENT_1,
    now: datetime = LATER,
) -> TransferSession:
    return h.tx(
        lambda r: r.lock_usable(
            session_id, principal_id=principal_id, client_ref=client_ref, now=now
        )
    )


def finalize(
    h: Harness, session_id: str, *, client_ref: str = CLIENT_1, now: datetime = LATER
) -> tuple[TransferSession, str]:
    token, digest = mint_content_token()

    def work(r: ReportTransferRepository) -> TransferSession:
        session = r.lock_usable(
            session_id, principal_id=PRINCIPAL_A, client_ref=client_ref, now=now
        )
        r.staged_bytes(session, staging=h.staging)
        return r.finalize(session, token_digest=digest, now=now)

    return h.tx(work), token


def claim(
    h: Harness,
    session_id: str,
    token: str,
    *,
    principal_id: str = PRINCIPAL_A,
    client_ref: str = CLIENT_1,
    now: datetime = LATER,
) -> TransferSession:
    return h.tx(
        lambda r: r.claim_for_consumption(
            session_id, token, principal_id=principal_id, client_ref=client_ref, now=now
        )
    )


def abort(
    h: Harness,
    session_id: str,
    *,
    principal_id: str = PRINCIPAL_A,
    client_ref: str = CLIENT_1,
    now: datetime = LATER,
) -> tuple[TransferSession, bool]:
    return h.tx(
        lambda r: r.abort(session_id, principal_id=principal_id, client_ref=client_ref, now=now)
    )


def consume(h: Harness, session_id: str, token: str) -> TransferSession:
    content_id = h.content_id(PRINCIPAL_A)

    def work(r: ReportTransferRepository) -> TransferSession:
        session = r.claim_for_consumption(
            session_id, token, principal_id=PRINCIPAL_A, client_ref=CLIENT_1, now=LATER
        )
        return r.mark_consumed(session, content_id=content_id, now=LATER)

    return h.tx(work)


def not_found(action: Callable[[], object]) -> None:
    """The one uniform refusal: the exact type, the one message, no extra attribute."""
    with pytest.raises(ReportTransferNotFoundError) as caught:
        action()
    error = caught.value
    assert type(error) is ReportTransferNotFoundError
    assert str(error) == "the transfer session was not found"
    assert not set(vars(error)) - {"__traceback__"}


def conflict(action: Callable[[], object], detail: str) -> None:
    with pytest.raises(ReportTransferConflictError) as caught:
        action()
    assert caught.value.detail == detail


def invalid(action: Callable[[], object], field: str, code: str) -> None:
    with pytest.raises(ReportValidationError) as caught:
        action()
    assert (caught.value.field, caught.value.code) == (field, code)


# ---- scenarios ---------------------------------------------------------------------


def begin_replays_the_same_intent(h: Harness) -> None:
    first, replayed = begin(h, declaration(THREE), "k1")
    assert replayed is False
    assert first.state is TransferState.OPEN
    assert first.chunk_byte_limit == TRANSFER_CHUNK_BYTES
    assert first.expires_at == T0 + timedelta(seconds=3600)
    assert first.client_ref == CLIENT_1 and first.owner_principal_id == PRINCIPAL_A
    assert first.declaration == declaration(THREE)
    again, replayed = begin(h, declaration(THREE), "k1", now=LATER)
    assert replayed is True
    assert again == first
    # The key is scoped by client and owner: another client's same key is a new session.
    other, replayed = begin(h, declaration(THREE), "k1", client_ref=CLIENT_2)
    assert replayed is False and other.session_id != first.session_id
    assert "content_token_digest" not in repr(first)


def begin_refuses_another_intent_on_the_key(h: Harness) -> None:
    begin(h, declaration(THREE), "k1")
    with pytest.raises(ReportIdempotencyConflictError):
        begin(h, declaration(THREE, ttl=600), "k1")
    with pytest.raises(ReportIdempotencyConflictError):
        begin(h, declaration(payload(5)), "k1")


def begin_replay_of_an_unusable_session_is_not_found(h: Harness) -> None:
    aborted, _ = begin(h, declaration(THREE), "k-aborted")
    abort(h, aborted.session_id)
    not_found(lambda: begin(h, declaration(THREE), "k-aborted", now=LATER))
    begin(h, declaration(THREE), "k-expiring")
    not_found(lambda: begin(h, declaration(THREE), "k-expiring", now=EXPIRED))


def quota_per_client(h: Harness) -> None:
    for i in range(4):
        begin(h, declaration(byte_count=10), f"c{i}")
    with pytest.raises(ReportTransferQuotaError):
        begin(h, declaration(byte_count=10), "c4")
    # Another client of the owner, and another owner, still begin.
    begin(h, declaration(byte_count=10), "c4", client_ref=CLIENT_2)
    begin(h, declaration(byte_count=10), "c0", principal_id=PRINCIPAL_B)


def quota_per_owner(h: Harness) -> None:
    for i in range(4):
        begin(h, declaration(byte_count=10), f"a{i}", client_ref=CLIENT_1)
        begin(h, declaration(byte_count=10), f"b{i}", client_ref=CLIENT_2)
    with pytest.raises(ReportTransferQuotaError):
        begin(h, declaration(byte_count=10), "c0", client_ref=CLIENT_3)
    begin(h, declaration(byte_count=10), "c0", principal_id=PRINCIPAL_B, client_ref=CLIENT_3)


def quota_of_declared_bytes(h: Harness) -> None:
    for i in range(4):
        begin(h, declaration(byte_count=MAX_DECLARED), f"big{i}", client_ref=CLIENT_1)
    # 64 MiB live: one more byte from any client of the owner is refused.
    with pytest.raises(ReportTransferQuotaError):
        begin(h, declaration(byte_count=1), "small", client_ref=CLIENT_2)
    begin(h, declaration(byte_count=MAX_DECLARED), "big", principal_id=PRINCIPAL_B)


def quota_counts_only_live_sessions(h: Harness) -> None:
    for i in range(4):
        begin(h, declaration(byte_count=10, ttl=300), f"e{i}")
    with pytest.raises(ReportTransferQuotaError):
        begin(h, declaration(byte_count=10), "e4")
    # At `expires_at` exactly the four are expired by the clock (their state
    # column still says open) and are not counted.
    at = T0 + timedelta(seconds=300)
    fresh = [begin(h, declaration(byte_count=10), f"f{i}", now=at)[0] for i in range(4)]
    with pytest.raises(ReportTransferQuotaError):
        begin(h, declaration(byte_count=10), "f4", now=at)
    # An aborted session is not counted either.
    abort(h, fresh[0].session_id, now=at)
    begin(h, declaration(byte_count=10), "f4", now=at)


def append_in_order_with_replay_and_conflict(h: Harness) -> None:
    session, _ = begin(h, declaration(THREE), "k")
    parts = pieces(THREE)
    chunk, replayed = append(h, session.session_id, 0, parts[0])
    assert replayed is False
    assert (chunk.sequence, chunk.byte_offset, chunk.byte_count) == (0, 0, TRANSFER_CHUNK_BYTES)  # type: ignore[attr-defined]
    again, replayed = append(h, session.session_id, 0, parts[0])
    assert replayed is True and again == chunk
    other = payload(TRANSFER_CHUNK_BYTES, seed=9)
    conflict(lambda: append(h, session.session_id, 0, other), "transfer_chunk_conflict")
    # gap (sequence 2 while 1 is next) and a sequence behind/ahead of the ledger
    conflict(lambda: append(h, session.session_id, 2, parts[2]), "transfer_sequence")
    append(h, session.session_id, 1, parts[1])
    conflict(lambda: append(h, session.session_id, 1, parts[0]), "transfer_chunk_conflict")
    last, replayed = append(h, session.session_id, 2, parts[2])
    assert replayed is False and last.byte_count == 10  # type: ignore[attr-defined]
    current = lock(h, session.session_id)
    assert current.received_byte_count == len(THREE) and current.complete
    ledger = h.tx(lambda r: r.chunks(session.session_id, principal_id=PRINCIPAL_A))
    assert [c.sequence for c in ledger] == [0, 1, 2]
    assert [c.byte_offset for c in ledger] == [0, TRANSFER_CHUNK_BYTES, 2 * TRANSFER_CHUNK_BYTES]
    # Another Principal sees no ledger.
    assert h.tx(lambda r: r.chunks(session.session_id, principal_id=PRINCIPAL_B)) == ()
    assert h.tx(lambda r: r.staged_bytes(current, staging=h.staging)) == THREE


def append_size_rules(h: Harness) -> None:
    session, _ = begin(h, declaration(THREE), "k")
    sid = session.session_id
    invalid(lambda: append(h, sid, 0, payload(TRANSFER_CHUNK_BYTES + 1)), "chunk", "too_large")
    invalid(lambda: append(h, sid, 0, payload(TRANSFER_CHUNK_BYTES - 1)), "chunk", "size")
    invalid(lambda: append(h, sid, 3, payload(10)), "chunk", "size")  # past the last chunk
    invalid(lambda: append(h, sid, 63, payload(10)), "chunk", "size")
    parts = pieces(THREE)
    invalid(
        lambda: append(h, sid, 0, parts[0], chunk_sha256="0" * 64),
        "chunk_sha256",
        "digest_mismatch",
    )
    append(h, sid, 0, parts[0])
    append(h, sid, 1, parts[1])
    # the last chunk overrunning the declaration
    invalid(lambda: append(h, sid, 2, payload(11)), "chunk", "size")
    assert lock(h, sid).received_byte_count == 2 * TRANSFER_CHUNK_BYTES


def append_on_a_finalized_session_is_a_state_conflict(h: Harness) -> None:
    data = payload(100)
    session = upload(h, data, "k")
    finalize(h, session.session_id)
    conflict(lambda: append(h, session.session_id, 0, data), "transfer_state")
    conflict(lambda: append(h, session.session_id, 1, payload(5)), "transfer_state")


def staged_bytes_verify_the_declaration(h: Harness) -> None:
    data = payload(TRANSFER_CHUNK_BYTES + 7)
    wrong = TransferDeclaration(
        ContentFormat.TEXT, ContentEncoding.IDENTITY, len(data), sha(b"other"), 3600
    )
    session, _ = begin(h, wrong, "k")
    for sequence, piece in enumerate(pieces(data)):
        append(h, session.session_id, sequence, piece)
    current = lock(h, session.session_id)
    with pytest.raises(ReportTransferDigestError):
        h.tx(lambda r: r.staged_bytes(current, staging=h.staging))


def staged_bytes_refuse_a_tampered_chunk(h: Harness) -> None:
    data = payload(TRANSFER_CHUNK_BYTES + 7)
    session = upload(h, data, "k")
    files = [p for p in h.staging_root.rglob("*") if p.is_file()]
    assert len(files) == 2
    target = next(p for p in files if p.name.startswith("01-"))
    target.chmod(0o600)
    target.write_bytes(b"x" * 7)
    with pytest.raises(ReportTransferStagingError):
        h.tx(lambda r: r.staged_bytes(session, staging=h.staging))


def finalize_refuses_incomplete_and_settled(h: Harness) -> None:
    session, _ = begin(h, declaration(THREE), "k")
    append(h, session.session_id, 0, pieces(THREE)[0])
    _, digest = mint_content_token()
    current = lock(h, session.session_id)
    conflict(
        lambda: h.tx(lambda r: r.finalize(current, token_digest=digest, now=LATER)),
        "transfer_incomplete",
    )
    done = upload(h, payload(50), "k2")
    finalized, _ = finalize(h, done.session_id)
    assert finalized.state is TransferState.FINALIZED
    assert finalized.finalized_at == LATER and finalized.content_token_digest is not None
    assert "content_token_digest" not in repr(finalized)
    relocked = lock(h, done.session_id)
    conflict(
        lambda: h.tx(lambda r: r.finalize(relocked, token_digest=digest, now=LATER)),
        "transfer_state",
    )


def claim_refusals_are_uniform(h: Harness) -> None:
    session = upload(h, payload(50), "k")
    _, token = finalize(h, session.session_id)
    other = upload(h, payload(60), "k2")
    _, other_token = finalize(h, other.session_id)
    sid = session.session_id
    not_found(lambda: claim(h, sid, mint_content_token()[0]))  # wrong token
    not_found(lambda: claim(h, sid, "grxtk_" + "Z" * 64))  # malformed
    not_found(lambda: claim(h, sid, "not-a-token"))
    not_found(lambda: claim(h, sid, other_token))  # another session's token
    not_found(lambda: claim(h, sid, token, client_ref=CLIENT_2))
    not_found(lambda: claim(h, sid, token, principal_id=PRINCIPAL_B))
    not_found(lambda: claim(h, sid, token, now=EXPIRED))
    not_found(lambda: claim(h, issue_identifier(IdKind.REPORT_TRANSFER_SESSION), token))
    not_found(lambda: claim(h, "grxfr_not-valid", token))
    # An open (unfinalized) session has no token to claim.
    open_session, _ = begin(h, declaration(payload(5)), "k3")
    not_found(lambda: claim(h, open_session.session_id, token))
    claimed = claim(h, sid, token)
    assert claimed.session_id == sid and claimed.state is TransferState.FINALIZED


def consumed_sessions_cannot_be_claimed_again(h: Harness) -> None:
    session = upload(h, payload(50), "k")
    _, token = finalize(h, session.session_id)
    consumed = consume(h, session.session_id, token)
    assert consumed.state is TransferState.CONSUMED
    assert consumed.consumed_at == LATER and consumed.consumed_content_id is not None
    not_found(lambda: claim(h, session.session_id, token))
    not_found(lambda: lock(h, session.session_id))
    not_found(lambda: abort(h, session.session_id))
    not_found(lambda: consume(h, session.session_id, token))


def abort_outcomes(h: Harness) -> None:
    open_session, _ = begin(h, declaration(THREE), "k1")
    aborted, replayed = abort(h, open_session.session_id)
    assert replayed is False and aborted.state is TransferState.ABORTED
    again, replayed = abort(h, open_session.session_id)
    assert replayed is True and again.state is TransferState.ABORTED
    not_found(lambda: lock(h, open_session.session_id))
    # finalized -> aborted keeps the token digest
    done = upload(h, payload(40), "k2")
    finalized, token = finalize(h, done.session_id)
    aborted, replayed = abort(h, done.session_id)
    assert replayed is False and aborted.content_token_digest == finalized.content_token_digest
    not_found(lambda: claim(h, done.session_id, token))
    # consumed and expired are not found; other client / Principal too
    used = upload(h, payload(30), "k3")
    _, used_token = finalize(h, used.session_id)
    consume(h, used.session_id, used_token)
    not_found(lambda: abort(h, used.session_id))
    stale, _ = begin(h, declaration(THREE), "k4")
    not_found(lambda: abort(h, stale.session_id, now=EXPIRED))
    not_found(lambda: abort(h, open_session.session_id, now=EXPIRED))  # aborted then expired
    live, _ = begin(h, declaration(THREE), "k5")
    not_found(lambda: abort(h, live.session_id, client_ref=CLIENT_2))
    not_found(lambda: abort(h, live.session_id, principal_id=PRINCIPAL_B))
    not_found(lambda: abort(h, "grxfr_nope"))


def lock_usable_refusals_are_uniform(h: Harness) -> None:
    session, _ = begin(h, declaration(THREE), "k")
    sid = session.session_id
    assert lock(h, sid).session_id == sid
    not_found(lambda: lock(h, issue_identifier(IdKind.REPORT_TRANSFER_SESSION)))
    not_found(lambda: lock(h, "grxfr_" + "!" * 10))
    not_found(lambda: lock(h, issue_identifier(IdKind.REPORT)))
    not_found(lambda: lock(h, sid, principal_id=PRINCIPAL_B))
    not_found(lambda: lock(h, sid, client_ref=CLIENT_2))
    not_found(lambda: lock(h, sid, now=T0 + timedelta(seconds=3600)))  # expires_at <= now
    not_found(lambda: append(h, sid, 0, pieces(THREE)[0], client_ref=CLIENT_2))


def gc_queries(h: Harness) -> None:
    early, _ = begin(h, declaration(payload(5), ttl=300), "k1")
    late, _ = begin(h, declaration(payload(5), ttl=600), "k2", principal_id=PRINCIPAL_B)
    keeps, _ = begin(h, declaration(payload(5), ttl=86400), "k3")
    gone, _ = begin(h, declaration(payload(5), ttl=600), "k4")
    abort(h, gone.session_id)
    at = T0 + timedelta(hours=1)
    assert h.tx(lambda r: r.expire_due(now=at, limit=1)) == (early.session_id,)
    assert h.tx(lambda r: r.expire_due(now=at, limit=10)) == (late.session_id,)
    assert h.tx(lambda r: r.expire_due(now=at, limit=10)) == ()
    invalid(lambda: h.tx(lambda r: r.expire_due(now=at, limit=0)), "limit", "bounds")
    absent = issue_identifier(IdKind.REPORT_TRANSFER_SESSION)
    ids = [early.session_id, late.session_id, keeps.session_id, gone.session_id, absent, "junk"]
    assert h.tx(lambda r: r.terminal_session_ids(ids)) == frozenset(
        {early.session_id, late.session_id, gone.session_id}
    )
    assert h.tx(lambda r: r.known_session_ids(ids)) == frozenset(
        {early.session_id, late.session_id, keeps.session_id, gone.session_id}
    )
    assert lock(h, keeps.session_id, now=at).state is TransferState.OPEN
    not_found(lambda: lock(h, early.session_id))


SCENARIOS: Final[dict[str, Callable[[Harness], None]]] = {
    function.__name__: function
    for function in (
        begin_replays_the_same_intent,
        begin_refuses_another_intent_on_the_key,
        begin_replay_of_an_unusable_session_is_not_found,
        quota_per_client,
        quota_per_owner,
        quota_of_declared_bytes,
        quota_counts_only_live_sessions,
        append_in_order_with_replay_and_conflict,
        append_size_rules,
        append_on_a_finalized_session_is_a_state_conflict,
        staged_bytes_verify_the_declaration,
        staged_bytes_refuse_a_tampered_chunk,
        finalize_refuses_incomplete_and_settled,
        claim_refusals_are_uniform,
        consumed_sessions_cannot_be_claimed_again,
        abort_outcomes,
        lock_usable_refusals_are_uniform,
        gc_queries,
    )
}
