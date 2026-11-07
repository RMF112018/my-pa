"""Reports Modernization WP06 (W3b): the five transfer handlers through `ApplicationService`.

Canonical FAST tests, in process, over the `FakeUnitOfWork` with a temporary
`FilesystemReportContentStore` and `FilesystemReportTransferStaging` sharing
one root, through `normalize` and `invoke` exactly as a transport calls them:

* begin (T3, T6, T7, T18): the answer, the keyed replay, the idempotency
  conflict, the three quotas (`rate_limited` `transfer_quota`);
* append (T2, T8): every chunk's answer, the identical replay, the
  conflicting chunk, the gap, the size, oversize, overrun, digest and
  non-canonical Base64 refusals, append on a finalized session;
* finalize (T9, T11): identity and gzip happy paths, `transfer_incomplete`,
  `transfer_state`, the whole-digest mismatch and every gzip/JSON refusal
  (bomb, ratio, nested, trailing, malformed, UTF-8, depth, values);
* abort (T17): open and finalized, the replay, the post-commit discard
  (failures swallowed, never on a refusal);
* T5: one rendered bare `not_found` for unknown / foreign Principal / other
  client / expired / aborted / consumed, on append, finalize and abort;
* read_chunk (T15): inline and blob, decoded and original, `eof` and
  `next_offset`, the offset bound, tamper, withdrawn visibility, a blob
  without a store;
* T14 availability both ways, the handlers' own `unsupported`, and T12 (the
  decode permit taken by finalize and by a transfer-sourced publish/update).

Every refusal is asserted with zero mutation: the session rows, the chunk
ledger, the staging tree and the stored report versions are unchanged. All
bytes are synthetic.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
import threading
from dataclasses import dataclass, replace
from datetime import timedelta
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Final

import pytest

import my_pa.application.service as service_module
from my_pa.adapters.normalization import normalize
from my_pa.application.errors import UnsupportedError
from my_pa.application.service import ApplicationService
from my_pa.contracts.ports import ReportTransferStaging
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.reports.content import content_from_staged
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.vocabulary import (
    MAX_DECODED_CONTENT_BYTES,
    ContentEncoding,
    ContentFormat,
    TransferState,
)
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore
from my_pa.infrastructure.report_content_stores.staging import FilesystemReportTransferStaging
from tests.conftest import WHEN, FakeUnitOfWork, Scene, build_service, operator

CHUNK: Final = 262_144
CLIENT_A: Final = "wp06-synthetic-client-a"
CLIENT_B: Final = "wp06-synthetic-client-b"
UPLOADS: Final = frozenset(
    {
        Capability.REPORTS_TRANSFER_BEGIN,
        Capability.REPORTS_TRANSFER_APPEND,
        Capability.REPORTS_TRANSFER_FINALIZE,
        Capability.REPORTS_TRANSFER_ABORT,
    }
)
NOT_FOUND: Final = {
    "code": ErrorCode.NOT_FOUND.value,
    "message": "no record matches the request within the authorized scope",
    "retry": "conditional",
    "safe_details": [],
}


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _text(size: int, seed: int = 6) -> bytes:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    alphabet = "abcdefghijklmnopqrstuvwxyz      \n"
    return "".join(rng.choice(alphabet) for _ in range(size)).encode()


def _gz(data: bytes) -> bytes:
    return gzip.compress(data, compresslevel=6, mtime=0)


@dataclass
class Rig:
    service: ApplicationService
    scene: Scene
    root: Path
    store: FilesystemReportContentStore | None
    staging: ReportTransferStaging | None


def _rig(
    scene: Scene,
    tmp_path: Path,
    *,
    store: bool = True,
    staging: bool = True,
    inline_max_bytes: int | None = None,
    staging_override: ReportTransferStaging | None = None,
) -> Rig:
    root = (tmp_path / "report-content").resolve()
    root.mkdir(exist_ok=True)
    content_store = FilesystemReportContentStore(root) if store else None
    transfer_staging: ReportTransferStaging | None = (
        staging_override
        if staging_override is not None
        else (FilesystemReportTransferStaging(root) if staging else None)
    )
    extra: dict[str, Any] = {}
    if inline_max_bytes is not None:
        extra["report_content_inline_max_bytes"] = inline_max_bytes
    service = build_service(
        scene.world,
        scene.providers,
        report_content_store=content_store,
        report_transfer_staging=transfer_staging,
        **extra,
    )
    return Rig(service, scene, root, content_store, transfer_staging)


def _invoke(
    rig: Rig,
    capability: Capability,
    payload: dict[str, Any],
    *,
    client: str | None = None,
    principal: Principal | None = None,
) -> dict[str, Any]:
    (purpose,) = permitted_purposes(capability)
    wire = {
        "request_id": f"req-{capability.value}",
        "purpose": purpose.value,
        "principal_id": rig.scene.principal.principal_id,
        "requested_at": "2026-11-07T12:00:00.000Z",
        "payload": payload,
    }
    metadata, command = normalize(capability.value, wire)
    envelope = rig.service.invoke(
        metadata,
        command,
        principal=principal or rig.scene.principal,
        transport=CaptureTransport.REMOTE_CLIENT if client else CaptureTransport.LOCAL,
        authenticated_client_id=client,
    )
    return envelope.model_dump(mode="json")


def _ok(answer: dict[str, Any]) -> dict[str, Any]:
    assert answer["error"] is None, answer["error"]
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def _error(answer: dict[str, Any]) -> dict[str, Any]:
    """The rendered error, without its per-request correlation id."""
    assert answer["error"] is not None, answer["result"]
    error = answer["error"]
    assert isinstance(error, dict)
    assert str(error.pop("correlation_id")).startswith("corr_")
    return error


def _details(answer: dict[str, Any], code: ErrorCode) -> list[str]:
    error = _error(answer)
    assert error["code"] == code.value, error
    details = error["safe_details"]
    assert isinstance(details, list)
    return details


def _begin(
    rig: Rig,
    staged: bytes,
    *,
    fmt: str = "text",
    encoding: str = "identity",
    key: str = "begin-1",
    client: str | None = None,
    principal: Principal | None = None,
    **extra: Any,  # noqa: ANN401
) -> dict[str, Any]:
    payload = {
        "format": fmt,
        "encoding": encoding,
        "byte_count": len(staged),
        "sha256": _sha(staged),
        "idempotency_key": key,
        **extra,
    }
    return _invoke(
        rig, Capability.REPORTS_TRANSFER_BEGIN, payload, client=client, principal=principal
    )


def _pieces(staged: bytes) -> list[bytes]:
    return [staged[offset : offset + CHUNK] for offset in range(0, len(staged), CHUNK)]


def _append(
    rig: Rig,
    session_id: str,
    sequence: int,
    data: bytes,
    *,
    digest: str | None = None,
    chunk: str | None = None,
    client: str | None = None,
    principal: Principal | None = None,
) -> dict[str, Any]:
    payload = {
        "session_id": session_id,
        "sequence": sequence,
        "chunk": _b64(data) if chunk is None else chunk,
        "chunk_sha256": _sha(data) if digest is None else digest,
    }
    return _invoke(
        rig, Capability.REPORTS_TRANSFER_APPEND, payload, client=client, principal=principal
    )


def _session_op(
    rig: Rig,
    capability: Capability,
    session_id: str,
    *,
    client: str | None = None,
    principal: Principal | None = None,
) -> dict[str, Any]:
    return _invoke(rig, capability, {"session_id": session_id}, client=client, principal=principal)


def _finalize(rig: Rig, session_id: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    return _session_op(rig, Capability.REPORTS_TRANSFER_FINALIZE, session_id, **kwargs)


def _abort(rig: Rig, session_id: str, **kwargs: Any) -> dict[str, Any]:  # noqa: ANN401
    return _session_op(rig, Capability.REPORTS_TRANSFER_ABORT, session_id, **kwargs)


def _uploaded(
    rig: Rig,
    staged: bytes,
    *,
    client: str | None = None,
    key: str = "begin-1",
    **begin: Any,  # noqa: ANN401
) -> str:
    session_id = str(_ok(_begin(rig, staged, client=client, key=key, **begin))["session_id"])
    for sequence, piece in enumerate(_pieces(staged)):
        _ok(_append(rig, session_id, sequence, piece, client=client))
    return session_id


def _staging_tree(root: Path) -> list[tuple[str, int]]:
    transfer = root / "transfer"
    if not transfer.exists():
        return []
    return sorted(
        (str(path.relative_to(root)), path.stat().st_size if path.is_file() else -1)
        for path in transfer.rglob("*")
    )


def _snapshot(rig: Rig) -> tuple[object, ...]:
    world = rig.scene.world
    store_ids = () if rig.store is None else rig.store.stored_object_ids()
    return (
        dict(world.report_transfer_sessions),
        {key: list(value) for key, value in world.report_transfer_chunks.items()},
        _staging_tree(rig.root),
        dict(world.general_report_versions),
        store_ids,
    )


@pytest.fixture
def rig(scene: Scene, tmp_path: Path) -> Rig:
    return _rig(scene, tmp_path)


# ---- begin (T3, T6, T7, T18) -----------------------------------------------


def test_begin_answers_the_declaration_and_replays_its_key(rig: Rig) -> None:
    staged = _text(600 * 1024)
    first = _ok(_begin(rig, staged, fmt="markdown", ttl_seconds=900))
    assert first == {
        "session_id": first["session_id"],
        "state": "open",
        "format": "markdown",
        "encoding": "identity",
        "declared_byte_count": len(staged),
        "declared_sha256": _sha(staged),
        "chunk_byte_limit": CHUNK,
        "chunk_count": 3,
        "expires_at": "2026-08-02T12:15:00.000Z",
        "replayed": False,
    }
    assert first["session_id"].startswith("grxfr_")
    before = _snapshot(rig)
    again = _ok(_begin(rig, staged, fmt="markdown", ttl_seconds=900))
    assert again == {**first, "replayed": True}
    assert _snapshot(rig) == before
    # The same key bound to another declaration (here: another TTL) is a conflict.
    other = _begin(rig, staged, fmt="markdown", ttl_seconds=901)
    assert _details(other, ErrorCode.CONFLICT) == ["idempotency_key"]
    assert _snapshot(rig) == before


def test_the_begin_key_of_an_ended_session_begins_a_new_one(rig: Rig) -> None:
    """T7': aborted, consumed or expired, the identical begin is a NEW session."""
    staged = _text(10)
    sessions = rig.scene.world.report_transfer_sessions
    ended: list[str] = []
    for ending in ("aborted", "consumed", "expired"):
        key = f"begin-{ending}"
        session_id = _ok(_begin(rig, staged, key=key))["session_id"]
        if ending == "aborted":
            _ok(_abort(rig, session_id))
        elif ending == "consumed":
            for sequence, piece in enumerate(_pieces(staged)):
                _ok(_append(rig, session_id, sequence, piece))
            _ok(_finalize(rig, session_id))
            _consume(rig, session_id)
        else:
            _expire(rig, session_id)
        again = _ok(_begin(rig, staged, key=key))
        assert again["replayed"] is False and again["state"] == "open"
        assert again["session_id"] != session_id
        # The new session binds the key again.
        assert _ok(_begin(rig, staged, key=key)) == {**again, "replayed": True}
        ended.append(session_id)
    assert [sessions[sid].state for sid in ended] == [
        TransferState.ABORTED,
        TransferState.CONSUMED,
        TransferState.EXPIRED,
    ]


def test_begin_quotas_are_rate_limited_with_zero_mutation(rig: Rig) -> None:
    for index in range(4):
        _ok(_begin(rig, _text(10, seed=index), key=f"a{index}", client=CLIENT_A))
    before = _snapshot(rig)
    fifth = _begin(rig, _text(10, seed=9), key="a9", client=CLIENT_A)
    assert _details(fifth, ErrorCode.RATE_LIMITED) == ["transfer_quota"]
    assert _snapshot(rig) == before
    # Per owner: 8 across clients (the local Principal is a third client).
    for index in range(4):
        _ok(_begin(rig, _text(10, seed=20 + index), key=f"b{index}", client=CLIENT_B))
    before = _snapshot(rig)
    ninth = _begin(rig, _text(10, seed=30), key="local-1")
    assert _details(ninth, ErrorCode.RATE_LIMITED) == ["transfer_quota"]
    assert _snapshot(rig) == before


def test_the_declared_bytes_quota_is_64_mib_per_owner(scene: Scene, tmp_path: Path) -> None:
    rig = _rig(scene, tmp_path)
    full = {"byte_count": 16 * 1024 * 1024, "sha256": "0" * 64}
    for index in range(4):
        payload = {"format": "text", "encoding": "identity", "idempotency_key": f"f{index}"}
        _ok(_invoke(rig, Capability.REPORTS_TRANSFER_BEGIN, {**payload, **full}))
    before = _snapshot(rig)
    over = _begin(rig, _text(1), key="one-more", client=CLIENT_A)
    assert _details(over, ErrorCode.RATE_LIMITED) == ["transfer_quota"]
    assert _snapshot(rig) == before


# ---- append (T2, T8) --------------------------------------------------------


def test_append_answers_every_chunk_and_replays_an_identical_one(rig: Rig) -> None:
    staged = _text(2 * CHUNK + 1000)
    session_id = _ok(_begin(rig, staged))["session_id"]
    pieces = _pieces(staged)
    answers = [_ok(_append(rig, session_id, index, piece)) for index, piece in enumerate(pieces)]
    assert answers[0] == {
        "session_id": session_id,
        "sequence": 0,
        "byte_offset": 0,
        "byte_count": CHUNK,
        "chunk_sha256": _sha(pieces[0]),
        "received_byte_count": CHUNK,
        "declared_byte_count": len(staged),
        "complete": False,
        "next_sequence": 1,
        "expires_at": "2026-08-02T13:00:00.000Z",
        "replayed": False,
    }
    assert answers[2] == {
        **answers[0],
        "sequence": 2,
        "byte_offset": 2 * CHUNK,
        "byte_count": 1000,
        "chunk_sha256": _sha(pieces[2]),
        "received_byte_count": len(staged),
        "complete": True,
        "next_sequence": None,
    }
    assert rig.staging is not None and rig.staging.has_session(session_id)
    before = _snapshot(rig)
    replay = _ok(_append(rig, session_id, 1, pieces[1]))
    assert replay["replayed"] is True
    assert replay["sequence"] == 1 and replay["received_byte_count"] == len(staged)
    assert _snapshot(rig) == before


@pytest.mark.parametrize(
    ("case", "code", "details"),
    [
        ("conflicting_chunk", ErrorCode.CONFLICT, ["transfer_chunk_conflict"]),
        ("gap", ErrorCode.CONFLICT, ["transfer_sequence"]),
        ("short_non_final", ErrorCode.INVALID_REQUEST, ["chunk"]),
        ("oversize", ErrorCode.INVALID_REQUEST, ["chunk", "max_bytes"]),
        ("overrun", ErrorCode.INVALID_REQUEST, ["chunk"]),
        ("digest", ErrorCode.INVALID_REQUEST, ["chunk_sha256"]),
        ("non_canonical_base64", ErrorCode.INVALID_REQUEST, ["chunk"]),
    ],
)
def test_append_refusals_write_nothing(
    rig: Rig, case: str, code: ErrorCode, details: list[str]
) -> None:
    staged = _text(3 * CHUNK)
    session_id = _ok(_begin(rig, staged))["session_id"]
    pieces = _pieces(staged)
    _ok(_append(rig, session_id, 0, pieces[0]))
    before = _snapshot(rig)
    if case == "conflicting_chunk":
        answer = _append(rig, session_id, 0, pieces[1])
    elif case == "gap":
        answer = _append(rig, session_id, 2, pieces[2])
    elif case == "short_non_final":
        answer = _append(rig, session_id, 1, pieces[1][:-1])
    elif case == "oversize":
        answer = _append(rig, session_id, 1, pieces[1] + b"xy")
    elif case == "overrun":
        answer = _append(rig, session_id, 3, pieces[2])
    elif case == "digest":
        answer = _append(rig, session_id, 1, pieces[1], digest=_sha(b"other"))
    else:
        # Shape-valid padded Base64 with non-zero pad bits ("QQ==" is canonical).
        answer = _append(rig, session_id, 1, b"A", chunk="QR==")
    assert _details(answer, code) == details
    assert _snapshot(rig) == before


def test_append_and_finalize_on_a_finalized_session_are_transfer_state(rig: Rig) -> None:
    staged = _text(100)
    session_id = _uploaded(rig, staged)
    _ok(_finalize(rig, session_id))
    before = _snapshot(rig)
    assert _details(_append(rig, session_id, 0, staged), ErrorCode.CONFLICT) == ["transfer_state"]
    assert _details(_finalize(rig, session_id), ErrorCode.CONFLICT) == ["transfer_state"]
    assert _snapshot(rig) == before


# ---- finalize (T9, T11) -----------------------------------------------------


def test_finalize_an_identity_transfer_returns_a_one_use_token(rig: Rig) -> None:
    staged = _text(600 * 1024)
    session_id = _uploaded(rig, staged, fmt="markdown")
    answer = _ok(_finalize(rig, session_id))
    token = answer["content_token"]
    assert answer == {
        "session_id": session_id,
        "state": "finalized",
        "content_token": token,
        "expires_at": "2026-08-02T13:00:00.000Z",
        "byte_count": len(staged),
        "sha256": _sha(staged),
        "format": "markdown",
        "encoding": "identity",
        "decoded_byte_count": len(staged),
        "decoded_sha256": _sha(staged),
    }
    assert isinstance(token, str) and len(token) == 6 + 64 and token.startswith("grxtk_")
    session = rig.scene.world.report_transfer_sessions[session_id]
    assert session.state is TransferState.FINALIZED
    # Only the digest of the raw token is stored, never the token.
    assert session.content_token_digest == _sha(bytes.fromhex(token[6:]))
    assert token not in repr(rig.scene.world.report_transfer_sessions)


def test_finalize_a_gzip_json_transfer_names_the_canonical_decoded_bytes(rig: Rig) -> None:
    data = {"rows": [{"n": index, "label": f"row {index}"} for index in range(2000)]}
    pretty = json.dumps(data, indent=2).encode()
    staged = _gz(pretty)
    session_id = _uploaded(rig, staged, fmt="json", encoding="gzip+base64")
    answer = _ok(_finalize(rig, session_id))
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    assert answer["encoding"] == "gzip+base64"
    assert answer["byte_count"] == len(staged) and answer["sha256"] == _sha(staged)
    assert answer["decoded_byte_count"] == len(canonical.encode())
    assert answer["decoded_sha256"] == _sha(canonical.encode())


def test_finalize_before_every_byte_arrived_is_transfer_incomplete(rig: Rig) -> None:
    staged = _text(CHUNK + 10)
    session_id = _ok(_begin(rig, staged))["session_id"]
    _ok(_append(rig, session_id, 0, staged[:CHUNK]))
    before = _snapshot(rig)
    assert _details(_finalize(rig, session_id), ErrorCode.CONFLICT) == ["transfer_incomplete"]
    assert _snapshot(rig) == before


def test_staged_bytes_that_are_not_the_declaration_are_refused_at_finalize(rig: Rig) -> None:
    staged = _text(500)
    # Every chunk digest is right; the declared whole digest is another text's.
    session_id = _ok(
        _invoke(
            rig,
            Capability.REPORTS_TRANSFER_BEGIN,
            {
                "format": "text",
                "encoding": "identity",
                "byte_count": len(staged),
                "sha256": _sha(b"x" * len(staged)),
                "idempotency_key": "mismatch",
            },
        )
    )["session_id"]
    _ok(_append(rig, session_id, 0, staged))
    before = _snapshot(rig)
    assert _details(_finalize(rig, session_id), ErrorCode.INVALID_REQUEST) == ["transfer"]
    assert _snapshot(rig) == before
    assert rig.scene.world.report_transfer_sessions[session_id].state is TransferState.OPEN


def _random_digits(count: int) -> str:
    rng = random.Random(11)  # noqa: S311 - deterministic synthetic text, not a secret
    return ",".join(str(rng.randrange(10)) for _ in range(count))


def _bomb() -> bytes:
    # Over 16 MiB gunzipped while staying within 256:1 (random text keeps it).
    rng = random.Random(5)  # noqa: S311 - deterministic synthetic text, not a secret
    noise = "".join(rng.choice("abcdefghijklmnopqrstuvwxyz0123456789") for _ in range(110_000))
    return _gz(noise.encode() + b" " * (16 * 1024 * 1024 + 1))


#: (format, staged bytes, the pipeline's rule, expected safe details) per refused shape.
_GZIP_REFUSALS: Final = {
    "bomb": ("text", _bomb, "too_large", ["transfer", "max_bytes"]),
    "ratio": (
        "text",
        lambda: _gz(b" " * (2 * 1024 * 1024)),
        "expansion_ratio",
        ["transfer", "max_bytes"],
    ),
    "nested": ("text", lambda: _gz(_gz(b"inner synthetic text")), "nested_stream", ["transfer"]),
    "trailing": (
        "text",
        lambda: _gz(b"synthetic text") + b"trailing",
        "trailing_data",
        ["transfer"],
    ),
    "malformed": ("text", lambda: b"not a gzip member at all", "malformed_gzip", ["transfer"]),
    "utf8": ("text", lambda: _gz(b"\xff\xfe\xfd synthetic"), "malformed_utf8", ["transfer"]),
    "depth": ("json", lambda: _gz(b"[" * 40 + b"]" * 40), "too_deep", ["transfer"]),
    "values": (
        "json",
        lambda: _gz(("[" + _random_digits(262_145) + "]").encode()),
        "too_many_values",
        ["transfer", "max_bytes"],
    ),
}


@pytest.mark.parametrize("shape", sorted(_GZIP_REFUSALS))
def test_gzip_transfer_refusals_happen_at_finalize_with_zero_mutation(rig: Rig, shape: str) -> None:
    fmt, build, rule, details = _GZIP_REFUSALS[shape]
    staged = build()
    # The refusal is the one the shape names (the shared pipeline, T11) ...
    with pytest.raises(ReportValidationError) as refused:
        content_from_staged(
            ContentFormat(fmt),
            ContentEncoding.GZIP_BASE64,
            staged,
            max_decoded=MAX_DECODED_CONTENT_BYTES,
        )
    assert (refused.value.field, refused.value.code) == ("transfer", rule)
    # ... and through the service it is refused at finalize, writing nothing.
    session_id = _uploaded(rig, staged, fmt=fmt, encoding="gzip+base64")
    before = _snapshot(rig)
    answer = _finalize(rig, session_id)
    assert _details(answer, ErrorCode.INVALID_REQUEST) == details
    assert _snapshot(rig) == before
    session = rig.scene.world.report_transfer_sessions[session_id]
    assert session.state is TransferState.OPEN and session.content_token_digest is None


# ---- abort (T17) and the post-commit discard --------------------------------


def test_abort_ends_an_open_session_discards_its_staging_and_replays(rig: Rig) -> None:
    staged = _text(CHUNK + 5)
    session_id = _uploaded(rig, staged)
    assert rig.staging is not None and rig.staging.has_session(session_id)
    assert _ok(_abort(rig, session_id)) == {
        "session_id": session_id,
        "state": "aborted",
        "replayed": False,
    }
    assert rig.scene.world.report_transfer_sessions[session_id].state is TransferState.ABORTED
    assert not rig.staging.has_session(session_id)
    assert _staging_tree(rig.root) == [] or all(
        session_id not in name for name, _size in _staging_tree(rig.root)
    )
    before = _snapshot(rig)
    assert _ok(_abort(rig, session_id)) == {
        "session_id": session_id,
        "state": "aborted",
        "replayed": True,
    }
    assert _snapshot(rig) == before


def test_abort_of_a_finalized_session_keeps_its_token_digest(rig: Rig) -> None:
    session_id = _uploaded(rig, _text(64))
    _ok(_finalize(rig, session_id))
    digest = rig.scene.world.report_transfer_sessions[session_id].content_token_digest
    assert _ok(_abort(rig, session_id))["replayed"] is False
    session = rig.scene.world.report_transfer_sessions[session_id]
    assert session.state is TransferState.ABORTED and session.content_token_digest == digest


class _RecordingStaging(FilesystemReportTransferStaging):
    """The real adapter, recording `discard` calls (and failing them on request)."""

    def __init__(self, root: Path, *, fail: bool) -> None:
        super().__init__(root)
        self.fail = fail
        self.discarded: list[str] = []

    def discard(self, session_id: str) -> bool:
        self.discarded.append(session_id)
        if self.fail:
            raise OSError("synthetic discard failure")
        return super().discard(session_id)


def test_a_failed_post_commit_discard_is_swallowed_and_left_to_the_gc(
    scene: Scene, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    root = (tmp_path / "report-content").resolve()
    root.mkdir()
    staging = _RecordingStaging(root, fail=True)
    rig = _rig(scene, tmp_path, staging_override=staging)
    session_id = _uploaded(rig, _text(32))
    answer = _ok(_abort(rig, session_id))
    assert answer["state"] == "aborted"
    assert staging.discarded == [session_id]
    assert staging.has_session(session_id)  # left for the GC
    assert rig.scene.world.report_transfer_sessions[session_id].state is TransferState.ABORTED
    # Logged without the identifier.
    assert any("transfer GC" in record.getMessage() for record in caplog.records)
    assert all(session_id not in record.getMessage() for record in caplog.records)


def test_no_discard_runs_for_a_refused_abort(scene: Scene, tmp_path: Path) -> None:
    root = (tmp_path / "report-content").resolve()
    root.mkdir()
    staging = _RecordingStaging(root, fail=False)
    rig = _rig(scene, tmp_path, staging_override=staging)
    session_id = _uploaded(rig, _text(32))
    assert _error(_abort(rig, session_id, client=CLIENT_A)) == NOT_FOUND
    assert staging.discarded == []
    assert staging.has_session(session_id)


# ---- T5: one bare not_found ---------------------------------------------------


def _expire(rig: Rig, session_id: str) -> None:
    sessions = rig.scene.world.report_transfer_sessions
    sessions[session_id] = replace(sessions[session_id], expires_at=WHEN - timedelta(seconds=1))


def _consume(rig: Rig, session_id: str) -> None:
    sessions = rig.scene.world.report_transfer_sessions
    sessions[session_id] = replace(
        sessions[session_id], state=TransferState.CONSUMED, consumed_at=WHEN
    )


def test_every_unusable_session_answers_the_same_bare_not_found(rig: Rig) -> None:
    staged = _text(40)
    stranger = operator()
    cases: dict[str, tuple[str, dict[str, Any]]] = {}
    cases["unknown"] = ("grxfr_" + "z" * 24, {})
    cases["foreign_principal"] = (_uploaded(rig, staged, key="foreign"), {"principal": stranger})
    cases["other_client"] = (
        _uploaded(rig, staged, key="client", client=CLIENT_A),
        {"client": CLIENT_B},
    )
    cases["local_vs_remote"] = (_uploaded(rig, staged, key="local"), {"client": CLIENT_A})
    expired = _uploaded(rig, staged, key="expired")
    _expire(rig, expired)
    cases["expired"] = (expired, {})
    aborted = _uploaded(rig, staged, key="aborted")
    _ok(_abort(rig, aborted))
    cases["aborted"] = (aborted, {})
    consumed = _uploaded(rig, staged, key="consumed")
    _ok(_finalize(rig, consumed))
    _consume(rig, consumed)
    cases["consumed"] = (consumed, {})
    rendered: dict[str, dict[str, Any]] = {}
    for name, (session_id, caller) in cases.items():
        before = _snapshot(rig)
        operations = {
            "append": _append(rig, session_id, 0, staged, **caller),
            "finalize": _finalize(rig, session_id, **caller),
        }
        if name != "aborted":  # the owner's aborted session replays its abort (T17)
            operations["abort"] = _abort(rig, session_id, **caller)
        for operation, answer in operations.items():
            rendered[f"{name}/{operation}"] = _error(answer)
        assert _snapshot(rig) == before, name
    assert all(error == NOT_FOUND for error in rendered.values()), rendered
    assert len({json.dumps(error, sort_keys=True) for error in rendered.values()}) == 1


# ---- read_chunk (T15) ---------------------------------------------------------


def _publish(rig: Rig, content: dict[str, Any], key: str) -> dict[str, Any]:
    return _ok(
        _invoke(
            rig,
            Capability.REPORTS_PUBLISH,
            {"title": "Synthetic report", "content": content, "idempotency_key": key},
        )
    )


def _read_chunk(rig: Rig, report_id: str, **payload: Any) -> dict[str, Any]:  # noqa: ANN401
    return _invoke(
        rig,
        Capability.REPORTS_TRANSFER_READ_CHUNK,
        {"report_id": report_id, "version_number": 1, **payload},
    )


def _read_all(rig: Rig, report_id: str, part: str, length: int) -> tuple[bytes, list[Any]]:
    offset: int | None = 0
    out = b""
    seen: list[Any] = []
    while offset is not None:
        answer = _ok(_read_chunk(rig, report_id, part=part, offset=offset, length=length))
        chunk = base64.b64decode(answer["chunk"])
        assert answer["chunk_sha256"] == _sha(chunk) and answer["byte_count"] == len(chunk)
        out += chunk
        seen.append(answer["next_offset"])
        offset = answer["next_offset"]
        assert answer["eof"] is (offset is None)
    return out, seen


def test_read_chunk_of_an_inline_version_decoded_and_original(rig: Rig) -> None:
    body = _text(1000).decode()
    identity = _publish(rig, {"format": "markdown", "body": body}, "inline-identity")
    first = _ok(_read_chunk(rig, identity["report_id"], length=300))
    assert first == {
        "plane": "standalone",
        "report_id": identity["report_id"],
        "version_id": identity["version_id"],
        "version_number": 1,
        "part": "decoded",
        "offset": 0,
        "byte_count": 300,
        "chunk": _b64(body.encode()[:300]),
        "chunk_sha256": _sha(body.encode()[:300]),
        "total_byte_count": 1000,
        "part_sha256": _sha(body.encode()),
        "eof": False,
        "next_offset": 300,
    }
    decoded, offsets = _read_all(rig, identity["report_id"], "decoded", 300)
    assert decoded == body.encode() and offsets == [300, 600, 900, None]
    # Identity: the original part is the decoded bytes.
    original, _ = _read_all(rig, identity["report_id"], "original", 1000)
    assert original == body.encode()
    raw = _text(2000, seed=8)
    gz = _gz(raw)
    gzipped = _publish(
        rig, {"format": "text", "encoding": "gzip+base64", "encoded": _b64(gz)}, "inline-gzip"
    )
    assert _read_all(rig, gzipped["report_id"], "decoded", 512)[0] == raw
    whole = _ok(_read_chunk(rig, gzipped["report_id"], part="original"))
    assert base64.b64decode(whole["chunk"]) == gz
    assert whole["part_sha256"] == _sha(gz) and whole["eof"] is True
    assert whole["next_offset"] is None


def test_read_chunk_of_a_blob_streams_verified_ranges(scene: Scene, tmp_path: Path) -> None:
    rig = _rig(scene, tmp_path, inline_max_bytes=64)
    raw = _text(CHUNK + 4321, seed=9)
    gz = _gz(raw)
    report = _publish(
        rig, {"format": "text", "encoding": "gzip+base64", "encoded": _b64(gz)}, "blob"
    )
    (stored,) = rig.scene.world.general_report_versions.values()
    assert stored.storage_kind.value == "managed_blob"
    decoded, offsets = _read_all(rig, report["report_id"], "decoded", CHUNK)
    assert decoded == raw and offsets == [CHUNK, None]
    original, _ = _read_all(rig, report["report_id"], "original", 1000)
    assert original == gz


def test_read_chunk_offset_at_or_past_the_end_is_refused(rig: Rig) -> None:
    report = _publish(rig, {"format": "text", "body": "synthetic ten"}, "short")
    for offset in (13, 14, 10_000):
        answer = _read_chunk(rig, report["report_id"], offset=offset)
        assert _details(answer, ErrorCode.INVALID_REQUEST) == ["offset"]
    last = _ok(_read_chunk(rig, report["report_id"], offset=12))
    assert base64.b64decode(last["chunk"]) == b"n" and last["eof"] is True


def test_a_tampered_blob_part_is_internal_error_with_no_bytes(scene: Scene, tmp_path: Path) -> None:
    rig = _rig(scene, tmp_path, inline_max_bytes=64)
    raw = _text(5000, seed=12)
    report = _publish(rig, {"format": "text", "body": raw.decode()}, "tamper")
    (part,) = [path for path in (rig.root / "content").rglob("*") if path.is_file()]
    part.chmod(0o600)
    damaged = bytearray(part.read_bytes())
    damaged[-1] ^= 0x01
    part.write_bytes(bytes(damaged))
    answer = _read_chunk(rig, report["report_id"], length=10)
    error = _error(answer)
    assert error["code"] == ErrorCode.INTERNAL_ERROR.value and error["safe_details"] == []
    assert answer["result"] is None


def test_a_blob_read_without_a_store_is_internal_error(scene: Scene, tmp_path: Path) -> None:
    rig = _rig(scene, tmp_path, inline_max_bytes=64)
    report = _publish(rig, {"format": "text", "body": _text(500).decode()}, "storeless")
    storeless = _rig(scene, tmp_path, store=False, staging=False)
    error = _error(_read_chunk(storeless, report["report_id"]))
    assert error["code"] == ErrorCode.INTERNAL_ERROR.value and error["safe_details"] == []


def test_read_chunk_visibility_is_reports_reads(rig: Rig) -> None:
    report = _publish(rig, {"format": "text", "body": "synthetic withdrawn"}, "withdrawn")
    unknown = _error(_read_chunk(rig, "grpt_" + "q" * 24))
    foreign = _error(
        _invoke(
            rig,
            Capability.REPORTS_TRANSFER_READ_CHUNK,
            {"report_id": report["report_id"], "version_number": 1},
            principal=operator(),
        )
    )
    legacy_read_of_unknown = _error(
        _invoke(rig, Capability.REPORTS_READ, {"report_id": "grpt_" + "q" * 24})
    )
    assert unknown == foreign == legacy_read_of_unknown
    assert unknown["code"] == ErrorCode.NOT_FOUND.value
    _ok(
        _invoke(
            rig,
            Capability.REPORTS_ARCHIVE,
            {
                "report_id": report["report_id"],
                "expected_lifecycle_revision": 0,
                "idempotency_key": "archive-1",
            },
        )
    )
    assert _error(_read_chunk(rig, report["report_id"])) == unknown
    shown = _ok(_read_chunk(rig, report["report_id"], include_withdrawn=True))
    assert base64.b64decode(shown["chunk"]) == b"synthetic withdrawn"


# ---- T14 availability and the handlers' own refusal ----------------------------


@pytest.mark.parametrize(
    ("store", "staging", "served"),
    [(False, False, False), (True, False, False), (False, True, False), (True, True, True)],
)
def test_uploads_are_served_only_with_both_store_and_staging(
    scene: Scene, tmp_path: Path, store: bool, staging: bool, served: bool
) -> None:
    rig = _rig(scene, tmp_path, store=store, staging=staging)
    available = rig.service.available_capabilities
    assert Capability.REPORTS_TRANSFER_READ_CHUNK in available
    assert (available >= UPLOADS) is served
    assert not (UPLOADS & available) or served
    before = _snapshot(rig)
    answers = [
        _begin(rig, _text(10)),
        _append(rig, "grxfr_" + "y" * 24, 0, b"x"),
        _finalize(rig, "grxfr_" + "y" * 24),
        _abort(rig, "grxfr_" + "y" * 24),
    ]
    if served:
        assert answers[0]["error"] is None
        assert all(_error(answer) == NOT_FOUND for answer in answers[1:])
    else:
        for answer in answers:
            assert _details(answer, ErrorCode.UNSUPPORTED) == []
        assert _snapshot(rig) == before


def test_each_upload_handler_itself_refuses_unsupported_without_staging(
    scene: Scene, tmp_path: Path
) -> None:
    # A transport that dispatches straight through `_HANDLERS` meets the same
    # refusal, before the handler reads the authorization or the unit of work.
    for store in (False, True):
        rig = _rig(scene, tmp_path, store=store, staging=not store)
        session: dict[str, Any] = {"session_id": "grxfr_" + "s" * 24}
        commands: dict[Capability, dict[str, Any]] = {
            Capability.REPORTS_TRANSFER_BEGIN: {
                "format": "text",
                "encoding": "identity",
                "byte_count": 1,
                "sha256": "0" * 64,
                "idempotency_key": "b",
            },
            Capability.REPORTS_TRANSFER_APPEND: {
                **session,
                "sequence": 0,
                "chunk": "QQ==",
                "chunk_sha256": _sha(b"A"),
            },
            Capability.REPORTS_TRANSFER_FINALIZE: session,
            Capability.REPORTS_TRANSFER_ABORT: session,
        }
        for capability, payload in commands.items():
            handler = service_module._HANDLERS[capability]
            with pytest.raises(UnsupportedError):
                handler(
                    rig.service,
                    FakeUnitOfWork(scene.world),
                    SimpleNamespace(),
                    _command(capability, payload),
                )


# ---- T12: the decode permit -------------------------------------------------


def test_finalize_waits_for_the_decode_permit_and_append_does_not(rig: Rig) -> None:
    staged = _text(CHUNK + 10)
    session_id = _ok(_begin(rig, staged))["session_id"]
    permit = service_module._REPORT_CONTENT_DECODE_PERMIT
    assert permit.acquire(timeout=5)
    finalized: dict[str, Any] = {}
    try:
        # Append (bounded to one chunk) never takes the permit.
        for sequence, piece in enumerate(_pieces(staged)):
            _ok(_append(rig, session_id, sequence, piece))
        worker = threading.Thread(target=lambda: finalized.update(_finalize(rig, session_id)))
        worker.start()
        worker.join(timeout=0.5)
        assert worker.is_alive()  # waiting on the permit
        assert not finalized
    finally:
        permit.release()
    worker.join(timeout=10)
    assert not worker.is_alive()
    assert _ok(finalized)["state"] == "finalized"


def _command(capability: Capability, payload: dict[str, Any]) -> object:
    (purpose,) = permitted_purposes(capability)
    wire = {
        "request_id": "req",
        "purpose": purpose.value,
        "principal_id": "prn_" + "a" * 24,
        "requested_at": "2026-11-07T12:00:00.000Z",
        "payload": payload,
    }
    return normalize(capability.value, wire)[1]


def test_the_permit_predicate_covers_finalize_and_transfer_sourced_writes() -> None:
    permit = service_module._REPORT_CONTENT_DECODE_PERMIT
    choose = service_module._report_content_decode_permit
    reference = {
        "transfer": {"session_id": "grxfr_" + "s" * 24, "content_token": "grxtk_" + "0" * 64}
    }
    takes = [
        _command(Capability.REPORTS_TRANSFER_FINALIZE, {"session_id": "grxfr_" + "s" * 24}),
        _command(
            Capability.REPORTS_PUBLISH,
            {"title": "Synthetic", "content": reference, "idempotency_key": "p1"},
        ),
        _command(
            Capability.REPORTS_UPDATE,
            {
                "report_id": "grpt_" + "r" * 24,
                "expected_version": 1,
                "change_reason": "Synthetic transfer update.",
                "patch": {"content": reference},
                "idempotency_key": "u1",
            },
        ),
    ]
    for command in takes:
        assert choose(command) is permit, type(command).__name__
    skips = [
        _command(
            Capability.REPORTS_PUBLISH,
            {
                "title": "Synthetic",
                "content": {"format": "text", "body": "x"},
                "idempotency_key": "p",
            },
        ),
        _command(
            Capability.REPORTS_TRANSFER_BEGIN,
            {
                "format": "text",
                "encoding": "identity",
                "byte_count": 1,
                "sha256": "0" * 64,
                "idempotency_key": "b",
            },
        ),
        _command(
            Capability.REPORTS_TRANSFER_APPEND,
            {
                "session_id": "grxfr_" + "s" * 24,
                "sequence": 0,
                "chunk": "QQ==",
                "chunk_sha256": "0" * 64,
            },
        ),
        _command(Capability.REPORTS_TRANSFER_ABORT, {"session_id": "grxfr_" + "s" * 24}),
        _command(
            Capability.REPORTS_TRANSFER_READ_CHUNK,
            {"report_id": "grpt_" + "r" * 24, "version_number": 1},
        ),
    ]
    for command in skips:
        assert choose(command) is not permit, type(command).__name__
