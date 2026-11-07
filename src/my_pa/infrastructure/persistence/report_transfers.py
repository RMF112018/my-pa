"""The transfer session repository on PostgreSQL (Reports Modernization WP06 B3).

`report_transfer_sessions` and its append-only chunk ledger
`report_transfer_chunks`, over the caller's open connection, so every method
commits or rolls back with the request.

**Every request statement is scoped twice**: by the authenticated Principal
(`_mine` over `partition_criterion`, every INSERT `_bound` over
`principal_bound_values`) AND by the caller's `client_ref` (T4). A session of
another Principal or another client, an expired one (`expires_at <= now`,
whatever its state column says), an aborted or consumed one, and a malformed
identifier are all the one `ReportTransferNotFoundError` (T5). `now` is always
the caller's, never the database clock.

**Begin is serialized per owner** with `pg_advisory_xact_lock` on a key derived
from `("report_transfer_quota", principal_id)` (the precedent is
`entity_reenrichment._lock_principal`, whose key is the bare Principal; the
prefix keeps the two locks apart). Under that lock the owner's sessions (of
every client) that are live by state but expired by time are first moved to
`expired`, oldest first and at most `TRANSFER_BEGIN_REAP_LIMIT` (review R1 #1;
their ids are returned so the service discards their staging after the
commit); then the keyed replay is looked
up among the live sessions only (T7': a keyed session expired by time is moved
to `expired` there, and an ended one frees its key), the T6 quotas counted
(live = state IN (open, finalized) AND expires_at > now) and the row
inserted, so two concurrent begins of one owner cannot both pass the count:
the second reads the first's committed row (READ COMMITTED, a new statement
after the lock was granted).

**Append order (T8, T5), after the caller locked the session:** a finalized
session is `transfer_state`; the size rules (T2); the chunk digest
(defensively; the caller checked it before any lock); an existing ledger row
for the sequence replays when identical, else `transfer_chunk_conflict`; a
sequence other than the ledger length is `transfer_sequence`; then the chunk is
staged (`put_chunk`, exclusive create, an identical leftover verified and
reused) BEFORE the ledger INSERT, and the session's received count moves. A
failing INSERT therefore leaves at most an unledgered staged file, which an
identical retry reuses and the GC reports otherwise.

**The GC queries are not Principal-scoped, on purpose** (`expire_due`,
`terminal_session_ids`, `known_session_ids`), exactly as
`SqlGeneralReportRepository.known_managed_content_ids`: their subject is every
owner's sessions (expiry, staging reclamation, orphan detection); they return
opaque `grxfr_` identifiers only, and their one caller is the operator GC.

No statement here deletes a row; nothing writes `knowledge.intelligence_*`.
"""

from __future__ import annotations

import hashlib
import re
from collections.abc import Iterable
from datetime import UTC, datetime, timedelta
from typing import Final

from sqlalchemy import ColumnElement, Connection, RowMapping, Table, func, select

from my_pa.contracts.ports import (
    ReportIdempotencyConflictError,
    ReportTransferConflictError,
    ReportTransferDigestError,
    ReportTransferNotFoundError,
    ReportTransferQuotaError,
    ReportTransferRepository,
    ReportTransferStaging,
    TransferBegin,
    TransferChunk,
    TransferSession,
)
from my_pa.domain.common.identifiers import IdKind, InvalidIdentifierError, validate_identifier
from my_pa.domain.identity.secret_digests import digests_match
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.transfer import (
    CLIENT_REF_PATTERN,
    TRANSFER_BEGIN_REAP_LIMIT,
    TRANSFER_CHUNK_BYTES,
    TRANSFER_DECLARED_BYTES_PER_OWNER,
    TRANSFER_SESSIONS_PER_CLIENT,
    TRANSFER_SESSIONS_PER_OWNER,
    TransferDeclaration,
    chunk_count,
    content_token_digest,
)
from my_pa.domain.reports.vocabulary import ContentEncoding, ContentFormat, TransferState
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.principal_scope import (
    PrincipalContext,
    capture_context,
    partition_criterion,
    principal_bound_values,
)
from my_pa.infrastructure.persistence.tables import (
    report_transfer_chunks,
    report_transfer_sessions,
)

__all__ = ["MAX_EXPIRE_BATCH", "SqlReportTransferRepository", "quota_lock_key"]

#: The most sessions one `expire_due` call moves.
MAX_EXPIRE_BATCH: Final = 1000
_MAX_KEY_CHARACTERS: Final = 128
_LIVE: Final = (TransferState.OPEN.value, TransferState.FINALIZED.value)
_TERMINAL: Final = (
    TransferState.CONSUMED.value,
    TransferState.ABORTED.value,
    TransferState.EXPIRED.value,
)
_CLIENT_REF: Final = re.compile(CLIENT_REF_PATTERN.replace("^", r"\A", 1).replace("$", r"\Z"))
_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")
_QUOTA_LOCK_PREFIX: Final = "report_transfer_quota"


def quota_lock_key(principal_id: str) -> str:
    """The text the per-owner begin advisory lock key is hashed from."""
    return f"{_QUOTA_LOCK_PREFIX}:{principal_id}"


def _mine(table: Table, context: PrincipalContext) -> ColumnElement[bool]:
    return partition_criterion(table, context)


def _bound(values: dict[str, object], table: Table, context: PrincipalContext) -> dict[str, object]:
    return principal_bound_values(values, table, context)


def _utc(value: object, field: str) -> datetime:
    if (
        not isinstance(value, datetime)
        or value.tzinfo is None
        or value.tzinfo.utcoffset(value) is None
    ):
        raise ReportValidationError(field, "naive")
    return value.astimezone(UTC)


def _client_ref(value: str) -> str:
    if type(value) is not str or not _CLIENT_REF.match(value):
        raise ReportValidationError("client_ref", "pattern")
    return value


def _session_id_or_none(value: object) -> str | None:
    if type(value) is not str:
        return None
    try:
        validate_identifier(value, IdKind.REPORT_TRANSFER_SESSION)
    except InvalidIdentifierError:
        return None
    return value


def _hydrate(row: RowMapping) -> TransferSession:
    return TransferSession(
        session_id=str(row["session_id"]),
        owner_principal_id=str(row["owner_principal_id"]),
        client_ref=str(row["client_ref"]),
        state=TransferState(row["state"]),
        format=ContentFormat(row["format"]),
        encoding=ContentEncoding(row["original_encoding"]),
        declared_byte_count=int(row["declared_byte_count"]),
        declared_sha256=str(row["declared_sha256"]),
        chunk_byte_limit=int(row["chunk_byte_limit"]),
        received_byte_count=int(row["received_byte_count"]),
        idempotency_key=str(row["idempotency_key"]),
        intent_digest=str(row["intent_digest"]),
        created_at=row["created_at"],
        expires_at=row["expires_at"],
        finalized_at=row["finalized_at"],
        consumed_content_id=(
            None if row["consumed_content_id"] is None else str(row["consumed_content_id"])
        ),
        consumed_at=row["consumed_at"],
        content_token_digest=(
            None if row["content_token_digest"] is None else str(row["content_token_digest"])
        ),
    )


def _chunk(row: RowMapping) -> TransferChunk:
    return TransferChunk(
        session_id=str(row["session_id"]),
        sequence=int(row["sequence"]),
        byte_offset=int(row["byte_offset"]),
        byte_count=int(row["byte_count"]),
        chunk_sha256=str(row["chunk_sha256"]),
        received_at=row["received_at"],
    )


def check_chunk_size(session: TransferSession, sequence: int, data: bytes) -> None:
    """T2's size rules for chunk `sequence` of `session` (shared with the fake).

    More than 262,144 bytes is `("chunk", "too_large")`; an empty chunk, a
    sequence past the declaration's last chunk (an overrun) or a chunk of
    another size than its sequence's fixed size is `("chunk", "size")`.
    """
    if len(data) > TRANSFER_CHUNK_BYTES:
        raise ReportValidationError("chunk", "too_large")
    count = chunk_count(session.declared_byte_count)
    if not data or sequence >= count:
        raise ReportValidationError("chunk", "size")
    expected = min(
        TRANSFER_CHUNK_BYTES, session.declared_byte_count - sequence * TRANSFER_CHUNK_BYTES
    )
    if len(data) != expected:
        raise ReportValidationError("chunk", "size")


def check_chunk_digest(chunk_sha256: str, data: bytes) -> None:
    """The chunk's digest is its bytes' (`("chunk_sha256", "digest_mismatch")`)."""
    if type(chunk_sha256) is not str or not _SHA256_HEX.match(chunk_sha256):
        raise ReportValidationError("chunk_sha256", "pattern")
    if hashlib.sha256(data).hexdigest() != chunk_sha256:
        raise ReportValidationError("chunk_sha256", "digest_mismatch")


class SqlReportTransferRepository(ReportTransferRepository):
    """The transfer port over one connection the caller owns (see the module docstring)."""

    def __init__(self, connection: Connection) -> None:
        self._connection: Final = connection

    # ---- begin -------------------------------------------------------------

    def begin(
        self,
        declaration: TransferDeclaration,
        *,
        principal_id: str,
        client_ref: str,
        idempotency_key: str,
        now: datetime,
    ) -> TransferBegin:
        if not isinstance(declaration, TransferDeclaration):
            raise ReportValidationError("declaration", "type")
        context = capture_context(principal_id)
        client = _client_ref(client_ref)
        if type(idempotency_key) is not str or not 1 <= len(idempotency_key) <= _MAX_KEY_CHARACTERS:
            raise ReportValidationError("idempotency_key", "bounds")
        at = _utc(now, "now")
        table = report_transfer_sessions
        self._connection.execute(
            select(
                func.pg_advisory_xact_lock(func.hashtextextended(quota_lock_key(principal_id), 0))
            )
        ).scalar_one()
        # Review R1 #1: reap this owner's (every client's) sessions that are
        # live by state but expired by time, oldest first and bounded, BEFORE
        # the keyed lookup and the quota count. A row another transaction holds
        # (the GC, a concurrent request) is skipped, not waited for; the keyed
        # one is still ended below.
        reaped = [
            str(value)
            for value in self._connection.execute(
                select(table.c.session_id)
                .where(_mine(table, context), table.c.state.in_(_LIVE), table.c.expires_at <= at)
                .order_by(table.c.expires_at, table.c.session_id)
                .limit(TRANSFER_BEGIN_REAP_LIMIT)
                .with_for_update(skip_locked=True)
            ).scalars()
        ]
        if reaped:
            self._connection.execute(
                table.update()
                .where(
                    _mine(table, context),
                    table.c.session_id.in_(reaped),
                    table.c.state.in_(_LIVE),
                )
                .values(state=TransferState.EXPIRED.value)
            )
        # T7': the key binds only a live session (the partial unique index
        # `a_report_transfer_begin_is_keyed`); a consumed, aborted or expired
        # one is ignored, so the same declaration begins a new session.
        keyed = (
            self._connection.execute(
                select(table)
                .where(
                    _mine(table, context),
                    table.c.client_ref == client,
                    table.c.idempotency_key == idempotency_key,
                    table.c.state.in_(_LIVE),
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        if keyed is not None:
            original = _hydrate(keyed)
            if original.expires_at > at:
                if original.intent_digest != declaration.intent_digest:
                    raise ReportIdempotencyConflictError()
                return TransferBegin(original, True, tuple(reaped))
            # Live by its state column but expired by time and not reaped above
            # (past the limit or skipped): end it (the guard admits
            # open|finalized -> expired) so the key is free again.
            reaped.append(original.session_id)
            self._connection.execute(
                table.update()
                .where(
                    _mine(table, context),
                    table.c.session_id == original.session_id,
                    table.c.state.in_(_LIVE),
                )
                .values(state=TransferState.EXPIRED.value)
            )
        live = self._connection.execute(
            select(
                func.count().label("sessions"),
                func.count().filter(table.c.client_ref == client).label("client_sessions"),
                func.coalesce(func.sum(table.c.declared_byte_count), 0).label("declared"),
            ).where(
                _mine(table, context),
                table.c.state.in_(_LIVE),
                table.c.expires_at > at,
            )
        ).one()
        if (
            int(live.client_sessions) >= TRANSFER_SESSIONS_PER_CLIENT
            or int(live.sessions) >= TRANSFER_SESSIONS_PER_OWNER
            or int(live.declared) + declaration.byte_count > TRANSFER_DECLARED_BYTES_PER_OWNER
        ):
            raise ReportTransferQuotaError()
        values = _bound(
            {
                "session_id": issue_identifier(IdKind.REPORT_TRANSFER_SESSION),
                "client_ref": client,
                "state": TransferState.OPEN.value,
                "format": declaration.format.value,
                "original_encoding": declaration.encoding.value,
                "declared_byte_count": declaration.byte_count,
                "declared_sha256": declaration.sha256,
                "chunk_byte_limit": TRANSFER_CHUNK_BYTES,
                "received_byte_count": 0,
                "created_at": at,
                "expires_at": at + timedelta(seconds=declaration.ttl_seconds),
                "idempotency_key": idempotency_key,
                "intent_digest": declaration.intent_digest,
            },
            table,
            context,
        )
        row = (
            self._connection.execute(table.insert().values(**values).returning(table))
            .mappings()
            .one()
        )
        return TransferBegin(_hydrate(row), False, tuple(reaped))

    # ---- the caller's session ----------------------------------------------

    def _locked(
        self, session_id: object, context: PrincipalContext, client: str
    ) -> TransferSession | None:
        valid = _session_id_or_none(session_id)
        if valid is None:
            return None
        table = report_transfer_sessions
        row = (
            self._connection.execute(
                select(table)
                .where(
                    _mine(table, context),
                    table.c.session_id == valid,
                    table.c.client_ref == client,
                )
                .with_for_update()
            )
            .mappings()
            .one_or_none()
        )
        return None if row is None else _hydrate(row)

    def lock_usable(
        self, session_id: str, *, principal_id: str, client_ref: str, now: datetime
    ) -> TransferSession:
        context = capture_context(principal_id)
        client = _client_ref(client_ref)
        at = _utc(now, "now")
        session = self._locked(session_id, context, client)
        if session is None or not session.usable_at(at):
            raise ReportTransferNotFoundError()
        return session

    def chunks(self, session_id: str, *, principal_id: str) -> tuple[TransferChunk, ...]:
        context = capture_context(principal_id)
        valid = _session_id_or_none(session_id)
        if valid is None:
            return ()
        table = report_transfer_chunks
        rows = (
            self._connection.execute(
                select(table)
                .where(_mine(table, context), table.c.session_id == valid)
                .order_by(table.c.sequence)
            )
            .mappings()
            .all()
        )
        return tuple(_chunk(row) for row in rows)

    def append_chunk(
        self,
        session: TransferSession,
        *,
        sequence: int,
        chunk_sha256: str,
        data: bytes,
        staging: ReportTransferStaging,
        now: datetime,
    ) -> tuple[TransferChunk, bool]:
        at = _utc(now, "now")
        if type(sequence) is not int:
            raise ReportValidationError("sequence", "type")
        if type(data) is not bytes:
            raise ReportValidationError("chunk", "type")
        if session.state is TransferState.FINALIZED:
            raise ReportTransferConflictError("transfer_state")
        if session.state is not TransferState.OPEN:
            raise ReportTransferNotFoundError()
        check_chunk_size(session, sequence, data)
        check_chunk_digest(chunk_sha256, data)
        context = capture_context(session.owner_principal_id)
        ledger = self.chunks(session.session_id, principal_id=session.owner_principal_id)
        existing = next((chunk for chunk in ledger if chunk.sequence == sequence), None)
        if existing is not None:
            if existing.byte_count == len(data) and existing.chunk_sha256 == chunk_sha256:
                return existing, True
            raise ReportTransferConflictError("transfer_chunk_conflict")
        if sequence != len(ledger):
            raise ReportTransferConflictError("transfer_sequence")
        # Staged BEFORE the ledger row: a row never names bytes that are not there.
        staging.put_chunk(session.session_id, sequence, chunk_sha256=chunk_sha256, data=data)
        chunks = report_transfer_chunks
        row = (
            self._connection.execute(
                chunks.insert()
                .values(
                    **_bound(
                        {
                            "session_id": session.session_id,
                            "sequence": sequence,
                            "byte_offset": sequence * TRANSFER_CHUNK_BYTES,
                            "byte_count": len(data),
                            "chunk_sha256": chunk_sha256,
                            "received_at": at,
                        },
                        chunks,
                        context,
                    )
                )
                .returning(chunks)
            )
            .mappings()
            .one()
        )
        sessions = report_transfer_sessions
        moved = self._connection.execute(
            sessions.update()
            .where(
                _mine(sessions, context),
                sessions.c.session_id == session.session_id,
                sessions.c.client_ref == session.client_ref,
                sessions.c.state == TransferState.OPEN.value,
            )
            .values(received_byte_count=sessions.c.received_byte_count + len(data))
        )
        if moved.rowcount != 1:  # pragma: no cover - the caller holds the row lock
            raise ReportTransferNotFoundError()
        return _chunk(row), False

    def staged_bytes(self, session: TransferSession, *, staging: ReportTransferStaging) -> bytes:
        ledger = self.chunks(session.session_id, principal_id=session.owner_principal_id)
        pieces: list[bytes] = []
        for expected_sequence, chunk in enumerate(ledger):
            if chunk.sequence != expected_sequence:  # pragma: no cover - the guard orders them
                raise ReportTransferDigestError()
            pieces.append(
                staging.read_chunk(
                    session.session_id,
                    chunk.sequence,
                    chunk_sha256=chunk.chunk_sha256,
                    expected_byte_count=chunk.byte_count,
                )
            )
        staged = b"".join(pieces)
        if (
            len(staged) != session.declared_byte_count
            or hashlib.sha256(staged).hexdigest() != session.declared_sha256
        ):
            raise ReportTransferDigestError()
        return staged

    def _move(
        self, session: TransferSession, *, from_states: tuple[str, ...], **values: object
    ) -> TransferSession:
        context = capture_context(session.owner_principal_id)
        table = report_transfer_sessions
        row = (
            self._connection.execute(
                table.update()
                .where(
                    _mine(table, context),
                    table.c.session_id == session.session_id,
                    table.c.client_ref == session.client_ref,
                    table.c.state.in_(from_states),
                )
                .values(**values)
                .returning(table)
            )
            .mappings()
            .one_or_none()
        )
        if row is None:
            raise ReportTransferNotFoundError()
        return _hydrate(row)

    def finalize(
        self, session: TransferSession, *, token_digest: str, now: datetime
    ) -> TransferSession:
        at = _utc(now, "now")
        if type(token_digest) is not str or not _SHA256_HEX.match(token_digest):
            raise ReportValidationError("content_token_digest", "pattern")
        if session.state is TransferState.FINALIZED:
            raise ReportTransferConflictError("transfer_state")
        if session.state is not TransferState.OPEN:
            raise ReportTransferNotFoundError()
        if session.received_byte_count != session.declared_byte_count:
            raise ReportTransferConflictError("transfer_incomplete")
        return self._move(
            session,
            from_states=(TransferState.OPEN.value,),
            state=TransferState.FINALIZED.value,
            content_token_digest=token_digest,
            finalized_at=at,
        )

    def claim_for_consumption(
        self,
        session_id: str,
        content_token: str,
        *,
        principal_id: str,
        client_ref: str,
        now: datetime,
    ) -> TransferSession:
        session = self.lock_usable(
            session_id, principal_id=principal_id, client_ref=client_ref, now=now
        )
        presented = content_token_digest(content_token)
        if (
            session.state is not TransferState.FINALIZED
            or presented is None
            or not digests_match(presented, session.content_token_digest)
        ):
            raise ReportTransferNotFoundError()
        return session

    def mark_consumed(
        self, session: TransferSession, *, content_id: str, now: datetime
    ) -> TransferSession:
        at = _utc(now, "now")
        validate_identifier(content_id, IdKind.REPORT_CONTENT)
        if session.state is not TransferState.FINALIZED:
            raise ReportTransferNotFoundError()
        return self._move(
            session,
            from_states=(TransferState.FINALIZED.value,),
            state=TransferState.CONSUMED.value,
            consumed_content_id=content_id,
            consumed_at=at,
        )

    def abort(
        self, session_id: str, *, principal_id: str, client_ref: str, now: datetime
    ) -> tuple[TransferSession, bool]:
        context = capture_context(principal_id)
        client = _client_ref(client_ref)
        at = _utc(now, "now")
        # A dedicated scoped lookup: an aborted session is not `lock_usable`.
        session = self._locked(session_id, context, client)
        if session is None or session.expires_at <= at:
            raise ReportTransferNotFoundError()
        if session.state is TransferState.ABORTED:
            return session, True
        if session.state not in (TransferState.OPEN, TransferState.FINALIZED):
            raise ReportTransferNotFoundError()
        return (
            self._move(session, from_states=_LIVE, state=TransferState.ABORTED.value),
            False,
        )

    # ---- GC (operator; NOT Principal-scoped, see the module docstring) -------

    def expire_due(self, *, now: datetime, limit: int) -> tuple[str, ...]:
        at = _utc(now, "now")
        if type(limit) is not int or not 1 <= limit <= MAX_EXPIRE_BATCH:
            raise ReportValidationError("limit", "bounds")
        table = report_transfer_sessions
        due = tuple(
            str(value)
            for value in self._connection.execute(
                select(table.c.session_id)
                .where(table.c.state.in_(_LIVE), table.c.expires_at <= at)
                .order_by(table.c.expires_at, table.c.session_id)
                .limit(limit)
                .with_for_update(skip_locked=True)
            ).scalars()
        )
        if due:
            self._connection.execute(
                table.update()
                .where(table.c.session_id.in_(due), table.c.state.in_(_LIVE))
                .values(state=TransferState.EXPIRED.value)
            )
        return due

    def _which(self, session_ids: Iterable[str], *, terminal: bool) -> frozenset[str]:
        wanted = sorted({valid for value in session_ids if (valid := _session_id_or_none(value))})
        if not wanted:
            return frozenset()
        table = report_transfer_sessions
        statement = select(table.c.session_id).where(table.c.session_id.in_(wanted))
        if terminal:
            statement = statement.where(table.c.state.in_(_TERMINAL))
        return frozenset(str(value) for value in self._connection.execute(statement).scalars())

    def terminal_session_ids(self, session_ids: Iterable[str]) -> frozenset[str]:
        return self._which(session_ids, terminal=True)

    def known_session_ids(self, session_ids: Iterable[str]) -> frozenset[str]:
        return self._which(session_ids, terminal=False)
