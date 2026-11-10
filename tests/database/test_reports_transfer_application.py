"""Reports Modernization WP06 (W3b): the transfer handlers on PostgreSQL.

The `database` tier, each test on its own disposable clone (`migrated_engine`),
through `ApplicationService` with the real `SqlAlchemyUnitOfWork`, a real
`FilesystemReportContentStore` and `FilesystemReportTransferStaging` on one
`tmp_path` root. What it proves on the real schema (row locks, the chunk
guard, the rollback the FAST fake cannot show):

* the walk-through: begin -> append x 3 -> finalize -> abort, with the rows
  and the ledger read back after each step, the token's digest the only stored
  form, and the staging discarded after the abort committed;
* a refused finalize (whole digest) and a refused append leave every row and
  the staging exactly as they were;
* cross-client (the same Principal, another OAuth client) and foreign
  Principal operations are the one bare `not_found`, with zero mutation.

Every byte is synthetic.
"""

from __future__ import annotations

import base64
import hashlib
import random
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text

from my_pa.adapters.normalization import normalize
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore
from my_pa.infrastructure.report_content_stores.staging import FilesystemReportTransferStaging
from tests.conftest import DEFAULT_LIMITS, operator

pytestmark = pytest.mark.database

WHEN: Final = datetime(2026, 11, 7, 12, tzinfo=UTC)
CHUNK: Final = 262_144
CLIENT_A: Final = "wp06-db-synthetic-client-a"
CLIENT_B: Final = "wp06-db-synthetic-client-b"


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _text(size: int, seed: int = 4) -> bytes:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    return "".join(rng.choice("abcdefghij klmnop\n") for _ in range(size)).encode()


class Rig:
    def __init__(self, engine: Engine, tmp_path: Path) -> None:
        self.engine = engine
        self.root = (tmp_path / "report-content").resolve()
        self.root.mkdir()
        self.staging = FilesystemReportTransferStaging(self.root)
        audit = SqlAlchemyAuditSink(engine)
        self.service = ApplicationService(
            unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
            limits=DEFAULT_LIMITS,
            clock=lambda: WHEN,
            report_content_store=FilesystemReportContentStore(self.root),
            report_transfer_staging=self.staging,
        )

    def invoke(
        self,
        principal: Principal,
        capability: Capability,
        payload: dict[str, Any],
        *,
        client: str | None = None,
    ) -> dict[str, Any]:
        (purpose,) = permitted_purposes(capability)
        metadata, command = normalize(
            capability.value,
            {
                "request_id": f"req-{capability.value}",
                "purpose": purpose.value,
                "principal_id": principal.principal_id,
                "requested_at": "2026-11-07T12:00:00Z",
                "payload": payload,
            },
        )
        return self.service.invoke(
            metadata,
            command,
            principal=principal,
            transport=CaptureTransport.REMOTE_CLIENT if client else CaptureTransport.LOCAL,
            authenticated_client_id=client,
        ).model_dump(mode="json")

    def sessions(self) -> list[dict[str, Any]]:
        with self.engine.connect() as connection:
            rows = connection.execute(
                text(
                    "SELECT session_id, owner_principal_id, client_ref, state, "
                    "received_byte_count, content_token_digest, finalized_at "
                    "FROM knowledge.report_transfer_sessions ORDER BY session_id"
                )
            ).mappings()
            return [dict(row) for row in rows]

    def chunks(self) -> list[tuple[str, int, int, int, str]]:
        with self.engine.connect() as connection:
            return [
                (str(r[0]), int(r[1]), int(r[2]), int(r[3]), str(r[4]))
                for r in connection.execute(
                    text(
                        "SELECT session_id, sequence, byte_offset, byte_count, chunk_sha256 "
                        "FROM knowledge.report_transfer_chunks ORDER BY session_id, sequence"
                    )
                )
            ]

    def tree(self) -> list[str]:
        transfer = self.root / "transfer"
        if not transfer.exists():
            return []
        return sorted(str(path.relative_to(self.root)) for path in transfer.rglob("*"))

    def snapshot(self) -> tuple[object, ...]:
        return (self.sessions(), self.chunks(), self.tree())


def _ok(answer: dict[str, Any]) -> dict[str, Any]:
    assert answer["error"] is None, answer["error"]
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def _error(answer: dict[str, Any]) -> dict[str, Any]:
    error = answer["error"]
    assert isinstance(error, dict), answer
    error = dict(error)
    error.pop("correlation_id")
    return error


def _begin(
    rig: Rig,
    principal: Principal,
    staged: bytes,
    *,
    key: str,
    client: str | None = None,
    sha256: str | None = None,
) -> str:
    answer = _ok(
        rig.invoke(
            principal,
            Capability.REPORTS_TRANSFER_BEGIN,
            {
                "format": "markdown",
                "encoding": "identity",
                "byte_count": len(staged),
                "sha256": sha256 or _sha(staged),
                "idempotency_key": key,
            },
            client=client,
        )
    )
    return str(answer["session_id"])


def _append(
    rig: Rig,
    principal: Principal,
    session_id: str,
    sequence: int,
    data: bytes,
    *,
    client: str | None = None,
) -> dict[str, Any]:
    return rig.invoke(
        principal,
        Capability.REPORTS_TRANSFER_APPEND,
        {
            "session_id": session_id,
            "sequence": sequence,
            "chunk": base64.b64encode(data).decode("ascii"),
            "chunk_sha256": _sha(data),
        },
        client=client,
    )


def _op(
    rig: Rig,
    principal: Principal,
    capability: Capability,
    session_id: str,
    *,
    client: str | None = None,
) -> dict[str, Any]:
    return rig.invoke(principal, capability, {"session_id": session_id}, client=client)


def test_begin_append_finalize_abort_walk_through(migrated_engine: Engine, tmp_path: Path) -> None:
    rig = Rig(migrated_engine, tmp_path)
    principal = operator()
    staged = _text(2 * CHUNK + 777)
    pieces = [staged[offset : offset + CHUNK] for offset in range(0, len(staged), CHUNK)]
    session_id = _begin(rig, principal, staged, key="walk", client=CLIENT_A)
    (row,) = rig.sessions()
    client_ref = f"remote_client:{derive_creator(CreatorKind.REMOTE_CLIENT, CLIENT_A).creator_id}"
    assert row["session_id"] == session_id and row["client_ref"] == client_ref
    assert row["owner_principal_id"] == principal.principal_id and row["state"] == "open"
    for sequence, piece in enumerate(pieces):
        answer = _ok(_append(rig, principal, session_id, sequence, piece, client=CLIENT_A))
        assert answer["received_byte_count"] == min(len(staged), (sequence + 1) * CHUNK)
        assert answer["complete"] is (sequence == len(pieces) - 1)
    assert rig.chunks() == [
        (session_id, index, index * CHUNK, len(piece), _sha(piece))
        for index, piece in enumerate(pieces)
    ]
    assert rig.staging.has_session(session_id)
    # An identical re-send replays without a write.
    before = rig.snapshot()
    assert _ok(_append(rig, principal, session_id, 1, pieces[1], client=CLIENT_A))["replayed"]
    assert rig.snapshot() == before
    finalized = _ok(
        _op(rig, principal, Capability.REPORTS_TRANSFER_FINALIZE, session_id, client=CLIENT_A)
    )
    token = finalized["content_token"]
    assert finalized["decoded_sha256"] == _sha(staged)
    (row,) = rig.sessions()
    assert row["state"] == "finalized" and row["finalized_at"] == WHEN
    assert row["content_token_digest"] == _sha(bytes.fromhex(token[len("grxtk_") :]))
    # The raw token is stored nowhere in the plane or the audit trail.
    with migrated_engine.connect() as connection:
        for table in ("knowledge.report_transfer_sessions", "knowledge.audit_events"):
            dumped = connection.execute(
                text(f"SELECT coalesce(string_agg(t::text, ''), '') FROM {table} t")  # noqa: S608
            ).scalar_one()
            assert token[6:] not in dumped, table
    aborted = _ok(
        _op(rig, principal, Capability.REPORTS_TRANSFER_ABORT, session_id, client=CLIENT_A)
    )
    assert aborted == {"session_id": session_id, "state": "aborted", "replayed": False}
    (row,) = rig.sessions()
    assert row["state"] == "aborted" and row["content_token_digest"] is not None
    assert not rig.staging.has_session(session_id)
    assert rig.chunks() != []  # the ledger is append-only; only staging is discarded
    replay = _ok(
        _op(rig, principal, Capability.REPORTS_TRANSFER_ABORT, session_id, client=CLIENT_A)
    )
    assert replay["replayed"] is True


def test_refused_finalize_and_append_change_nothing(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    rig = Rig(migrated_engine, tmp_path)
    principal = operator()
    staged = _text(2 * CHUNK + 50, seed=5)
    session_id = _begin(rig, principal, staged, key="digest", sha256=_sha(b"other"))
    _ok(_append(rig, principal, session_id, 0, staged[:CHUNK]))
    before = rig.snapshot()
    gap = _append(rig, principal, session_id, 2, staged[2 * CHUNK :])
    assert _error(gap)["code"] == ErrorCode.CONFLICT.value
    assert _error(gap)["safe_details"] == ["transfer_sequence"]
    early = _op(rig, principal, Capability.REPORTS_TRANSFER_FINALIZE, session_id)
    assert _error(early)["safe_details"] == ["transfer_incomplete"]
    assert rig.snapshot() == before
    _ok(_append(rig, principal, session_id, 1, staged[CHUNK : 2 * CHUNK]))
    _ok(_append(rig, principal, session_id, 2, staged[2 * CHUNK :]))
    before = rig.snapshot()
    refused = _op(rig, principal, Capability.REPORTS_TRANSFER_FINALIZE, session_id)
    assert _error(refused)["code"] == ErrorCode.INVALID_REQUEST.value
    assert _error(refused)["safe_details"] == ["transfer"]
    assert rig.snapshot() == before


def test_cross_client_and_foreign_operations_are_the_one_not_found(
    migrated_engine: Engine, tmp_path: Path
) -> None:
    rig = Rig(migrated_engine, tmp_path)
    owner = operator()
    stranger = operator()
    staged = _text(1000, seed=6)
    session_id = _begin(rig, owner, staged, key="mine", client=CLIENT_A)
    _ok(_append(rig, owner, session_id, 0, staged[:500] + staged[500:], client=CLIENT_A))
    before = rig.snapshot()
    rendered: list[dict[str, Any]] = []
    callers: list[tuple[Principal, str | None]] = [
        (owner, CLIENT_B),
        (owner, None),
        (stranger, CLIENT_A),
    ]
    for principal, client in callers:
        rendered.append(_error(_append(rig, principal, session_id, 0, staged, client=client)))
        for capability in (
            Capability.REPORTS_TRANSFER_FINALIZE,
            Capability.REPORTS_TRANSFER_ABORT,
        ):
            rendered.append(_error(_op(rig, principal, capability, session_id, client=client)))
    unknown = _error(
        _op(rig, owner, Capability.REPORTS_TRANSFER_FINALIZE, "grxfr_" + "u" * 24, client=CLIENT_A)
    )
    assert all(error == unknown for error in rendered), rendered
    assert unknown["code"] == ErrorCode.NOT_FOUND.value and unknown["safe_details"] == []
    assert rig.snapshot() == before
    # The owner's own client still finalizes it.
    finalized = _op(rig, owner, Capability.REPORTS_TRANSFER_FINALIZE, session_id, client=CLIENT_A)
    assert _ok(finalized)["state"] == "finalized"
