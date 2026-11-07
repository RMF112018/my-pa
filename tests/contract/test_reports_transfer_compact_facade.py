"""Reports Modernization WP06 Part D: bounded chunked transfer, end to end through the facade.

The harness is `tests/contract/test_reports_compact_facade.py`'s, composed as
`tests/contract/test_reports_content_compact_facade.py` composes it -- the real
remote MCP app (`create_remote_mcp_app`) over httpx's ASGI transport, the real
`RemoteAuthenticator` against the durable grant store, the composition root's
`remote_access_context` and a real `ApplicationService` on a migrated,
disposable PostgreSQL clone -- with a real `FilesystemReportContentStore` AND a
real `FilesystemReportTransferStaging` on one `tmp_path` root. Every request is
an HTTP POST through `my_pa.describe`, `my_pa.write` or `my_pa.read`. What it
proves:

* describe: the exact remote input schema of each of the five
  `reports.transfer.*` names, their catalog kind/feature/annotations, and that
  `read_chunk` is a read and the four uploads are non-destructive writes;
* the walk-through: begin -> append x 3 -> finalize -> `reports.publish`
  `{content: {transfer: ...}}` -> `reports.read` (`body_omitted` +
  `body_chunked_read`) -> `read_chunk` loop -> byte-exact, with the session,
  ledger, content object, version and receipt rows read back and the staging
  discarded once consumed;
* RM-AC-006: 16,777,216 bytes of seeded random ASCII text that no inline
  encoding could carry, uploaded in 64 appends and read back in 64 chunks,
  every request under `MAX_REQUEST_BYTES` (measured and printed);
* a transfer under the response bound reads back inline; a gzip json transfer
  (RM-AC-004/005) reads back its exact original and decoded bytes and is
  searchable by a word of its decoded text only;
* `reports.update` consuming a transfer token;
* begin's server-stamped key: an identical retry replays the same session, a
  second client's identical declaration is its own session, and once a session
  ended (aborted, consumed, or open but expired by time -- then moved to
  `expired`) the identical declaration begins a NEW session (T7');
* no store: the four uploads are absent from describe and `unsupported`
  through `my_pa.write` even when granted; `read_chunk` is still described.

The refusals are in `tests/security/test_reports_transfer_compact_facade_adversarial.py`.
Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
import resource
import sys
import time
import tracemalloc
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.conftest import DEFAULT_LIMITS
from tests.contract.test_reports_compact_facade import (
    CLIENT,
    MINIMAL,
    OTHER_CLIENT,
    PUBLISH,
    READ,
    UPDATE,
    WHEN,
    Exchange,
    Harness,
    describe,
    expected_key,
    grant_row,
    list_tools,
    ok,
    outcome,
    profile_grants,
    update_payload,
    wrapped,
)

from my_pa.adapters.mcp.chatllm_gateway import DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import MAX_REQUEST_BYTES
from my_pa.adapters.remote_request import remote_tool_schema
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES, canonical_json
from my_pa.domain.reports.vocabulary import (
    MAX_DECODED_CONTENT_BYTES,
    READ_INLINE_CONTENT_MAX_BYTES,
    TRANSFER_CHUNK_MAX_BYTES,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore
from my_pa.infrastructure.report_content_stores.staging import FilesystemReportTransferStaging

pytestmark = pytest.mark.database

BEGIN: Final = Capability.REPORTS_TRANSFER_BEGIN
APPEND: Final = Capability.REPORTS_TRANSFER_APPEND
FINALIZE: Final = Capability.REPORTS_TRANSFER_FINALIZE
ABORT: Final = Capability.REPORTS_TRANSFER_ABORT
READ_CHUNK: Final = Capability.REPORTS_TRANSFER_READ_CHUNK
SEARCH: Final = Capability.REPORTS_SEARCH
UPLOADS: Final = (BEGIN, APPEND, FINALIZE, ABORT)
TRANSFER: Final = (*UPLOADS, READ_CHUNK)
CHUNK: Final = TRANSFER_CHUNK_MAX_BYTES
GZIP: Final = "gzip+base64"
#: Every table a transfer, its consumption or a publish/update may write.
TRANSFER_TABLES: Final = (
    "report_transfer_sessions",
    "report_transfer_chunks",
    "report_content_objects",
    "report_versions",
    "report_receipts",
)
#: A word only the decoded text of the gzip json transfer holds.
NEEDLE: Final = "wigeonlantern"
_TOOLS: Final = {tool.name: tool for tool in TOOLS}


# ---- composition -----------------------------------------------------------------------


class Clock:
    """The service's clock: `WHEN` unless a test moves it (session expiry)."""

    def __init__(self) -> None:
        self.now = WHEN

    def __call__(self) -> datetime:
        return self.now

    def advance(self, seconds: int) -> None:
        self.now = self.now + timedelta(seconds=seconds)


def build_transfer_service(
    engine: Engine,
    root: Path | None,
    *,
    clock: Callable[[], datetime] = lambda: WHEN,
    staging: bool = True,
) -> ApplicationService:
    """The facade service with a real content store and (unless told not to) real staging."""
    audit = SqlAlchemyAuditSink(engine)
    store = staged = None
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        store = FilesystemReportContentStore(root)
        if staging:
            staged = FilesystemReportTransferStaging(root)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=clock,
        report_content_store=store,
        report_content_inline_max_bytes=INLINE_CONTENT_MAX_BYTES,
        report_transfer_staging=staged,
    )


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return (tmp_path / "report-content").resolve()


@pytest.fixture
def clock() -> Clock:
    return Clock()


@pytest.fixture
def harness(migrated_engine: Engine, store_root: Path, clock: Clock) -> Harness:
    built = Harness(
        migrated_engine, build_transfer_service(migrated_engine, store_root, clock=clock)
    )
    built.gates()
    return built


def transfer_grants(service: ApplicationService) -> tuple[Any, ...]:
    """`profile_grants` plus the pin that the planner stamps the five exactly (T1)."""
    rows = profile_grants(service)
    assert {
        (BEGIN, Purpose.REPORT_AUTHORING, True, None),
        (APPEND, Purpose.REPORT_AUTHORING, True, None),
        (FINALIZE, Purpose.REPORT_AUTHORING, True, None),
        (ABORT, Purpose.REPORT_AUTHORING, True, None),
        (READ_CHUNK, Purpose.REPORT_READ, False, None),
    } <= set(rows)
    return rows


# ---- bytes ---------------------------------------------------------------------------


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def b64(raw: bytes) -> str:
    return base64.b64encode(raw).decode("ascii")


def random_ascii(size: int, seed: int = 6) -> bytes:
    """`size` bytes of seeded random printable ASCII (+ newlines): near-incompressible text."""
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,;:-\n"
    table = bytes(alphabet[i % len(alphabet)] for i in range(256))
    return rng.randbytes(size).translate(table)


def markdown_text(size: int, seed: int = 11) -> bytes:
    """`size` bytes of synthetic markdown."""
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    words = ("slab", "pour", "crane", "rebar", "permit", "crew", "formwork", "inspection")
    lines = ["# Synthetic transfer report\n"]
    total = len(lines[0])
    while total < size:
        line = f"- {rng.randrange(10**6):06d} {' '.join(rng.choice(words) for _ in range(6))}.\n"
        lines.append(line)
        total += len(line)
    return "".join(lines).encode()[:size]


def pieces(staged: bytes) -> list[bytes]:
    return [staged[start : start + CHUNK] for start in range(0, len(staged), CHUNK)]


# ---- facade calls ----------------------------------------------------------------------


def begin_payload(
    staged: bytes,
    fmt: str = "markdown",
    encoding: str = "identity",
    **extra: Any,  # noqa: ANN401
) -> dict[str, Any]:
    return {
        "format": fmt,
        "encoding": encoding,
        "byte_count": len(staged),
        "sha256": sha(staged),
        **extra,
    }


def append_payload(session_id: str, sequence: int, chunk: bytes) -> dict[str, Any]:
    return {
        "session_id": session_id,
        "sequence": sequence,
        "chunk": b64(chunk),
        "chunk_sha256": sha(chunk),
    }


def reference(session_id: str, token: str) -> dict[str, Any]:
    return {"transfer": {"session_id": session_id, "content_token": token}}


def single(
    harness: Harness,
    token: str,
    tool: str,
    capability: Capability,
    payload: Any,  # noqa: ANN401 - any JSON payload, refusals included
) -> Exchange:
    (answer,) = harness.run([(token, wrapped(tool, capability, payload))])
    return answer


@dataclass
class Upload:
    """One completed upload: the session, its token and every exchange on the way."""

    session_id: str
    content_token: str
    begun: Exchange
    appended: list[Exchange]
    finalized: Exchange


def upload(
    harness: Harness,
    token: str,
    staged: bytes,
    fmt: str = "markdown",
    encoding: str = "identity",
    **extra: Any,  # noqa: ANN401
) -> Upload:
    """begin -> append every chunk -> finalize, through the real facade."""
    begun = single(harness, token, WRITE_TOOL, BEGIN, begin_payload(staged, fmt, encoding, **extra))
    session_id = ok(begun)["session_id"]
    appended = harness.run(
        [
            (token, wrapped(WRITE_TOOL, APPEND, append_payload(session_id, sequence, chunk)))
            for sequence, chunk in enumerate(pieces(staged))
        ]
    )
    for answer in appended:
        ok(answer)
    finalized = single(harness, token, WRITE_TOOL, FINALIZE, {"session_id": session_id})
    return Upload(session_id, ok(finalized)["content_token"], begun, appended, finalized)


def read_all(
    harness: Harness,
    token: str,
    report_id: str,
    part: str = "decoded",
    **extra: Any,  # noqa: ANN401
) -> tuple[bytes, list[Exchange]]:
    """`read_chunk` from offset 0 to eof; returns the bytes and every exchange.

    A range is of one pinned version (exactly one of `version_id` and
    `version_number`); version 1 unless the caller names one.
    """
    if "version_id" not in extra and "version_number" not in extra:
        extra["version_number"] = 1
    collected = bytearray()
    exchanges: list[Exchange] = []
    offset: int | None = 0
    while offset is not None:
        payload = {"report_id": report_id, "part": part, "offset": offset, **extra}
        answer = single(harness, token, READ_TOOL, READ_CHUNK, payload)
        exchanges.append(answer)
        got = ok(answer)
        chunk = base64.b64decode(got["chunk"], validate=True)
        assert (got["offset"], got["byte_count"]) == (offset, len(chunk))
        assert got["chunk_sha256"] == sha(chunk)
        collected += chunk
        assert got["eof"] is (got["next_offset"] is None)
        offset = got["next_offset"]
    return bytes(collected), exchanges


def rows(engine: Engine, sql: str, **bind: Any) -> list[Any]:  # noqa: ANN401
    with engine.connect() as connection:
        return list(connection.execute(text(sql), bind))


def session_row(engine: Engine, session_id: str) -> Any:  # noqa: ANN401
    (row,) = rows(
        engine,
        "SELECT * FROM knowledge.report_transfer_sessions WHERE session_id = :s",
        s=session_id,
    )
    return row


def staged_tree(root: Path) -> list[str]:
    transfer = root / "transfer"
    if not transfer.exists():
        return []
    return sorted(str(path.relative_to(root)) for path in transfer.rglob("*"))


def staged_files(root: Path, session_id: str) -> list[Path]:
    return sorted(path for path in (root / "transfer").rglob("*") if path.parent.name == session_id)


def example(label: str, answer: Exchange, request: Mapping[str, Any] | None = None) -> None:
    """Print one request/response pair for the hand-back, chunk Base64 truncated."""

    def clip(value: Any) -> Any:  # noqa: ANN401
        if isinstance(value, dict):
            return {
                key: (f"{item[:24]}...({len(item)} chars)" if key == "chunk" else clip(item))
                for key, item in value.items()
            }
        if isinstance(value, list):
            return [clip(item) for item in value]
        if isinstance(value, str) and value.startswith("grxtk_"):
            return value[:12] + "...(token)"
        return value

    _failed, document = outcome(answer)
    shown = {"request": clip(dict(request)) if request else None, "response": clip(document)}
    print(
        f"\n[{label}] request_bytes={answer.request_bytes} response_bytes={answer.response_bytes}"
    )
    print(json.dumps(shown, sort_keys=True)[:2400])


# ---- 1. describe ----------------------------------------------------------------------


def test_describe_returns_the_exact_transfer_schemas(harness: Harness) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    tools, listed, *contracts = harness.run(
        [
            (token, list_tools()),
            (token, describe(feature="reports", limit=100)),
            *((token, describe(capability=capability.value)) for capability in TRANSFER),
        ]
    )
    names = {tool["name"] for tool in tools.document["result"]["tools"]}
    # The facade adds no top-level tool: no `reports.transfer.*` name is listed.
    assert names == {DESCRIBE_TOOL, READ_TOOL, WRITE_TOOL}
    _failed, catalog = outcome(listed)
    items = {item["capability"]: item for item in catalog["items"]}
    for capability in TRANSFER:
        item = items[capability.value]
        kind = "read" if capability is READ_CHUNK else "write"
        assert (item["kind"], item["feature"], item["destructive"], item["idempotent"]) == (
            kind,
            "reports",
            False,
            False,
        ), capability
        assert item["summary"] == _TOOLS[capability.value].description
    for answer, capability in zip(contracts, TRANSFER, strict=True):
        _failed, contract = outcome(answer)
        expected = json.loads(json.dumps(remote_tool_schema(_TOOLS[capability.value].input_schema)))
        assert contract["input_schema"] == expected, capability
        assert contract["profile"] == "chatllm-gateway-v1"
        assert contract["annotations"] == {
            "read_only_hint": capability is READ_CHUNK,
            "destructive_hint": False,
            "idempotent_hint": False,
            "open_world_hint": False,
        }, capability
        payload = contract["input_schema"]["properties"]["payload"]
        assert payload["additionalProperties"] is False, capability
        for server_owned in (
            "idempotency_key",
            "principal_id",
            "owner_principal_id",
            "client_ref",
            "state",
            "content_token_digest",
            "chunk_byte_limit",
            "purpose",
        ):
            assert server_owned not in payload["properties"], (capability, server_owned)
    begin_schema = outcome(contracts[0])[1]["input_schema"]["properties"]["payload"]
    assert begin_schema["required"] == ["format", "encoding", "byte_count", "sha256"]
    assert list(begin_schema["properties"]) == [
        "format",
        "encoding",
        "byte_count",
        "sha256",
        "ttl_seconds",
    ]
    append_schema = outcome(contracts[1])[1]["input_schema"]["properties"]["payload"]
    assert append_schema["properties"]["chunk"]["maxLength"] == 349_528
    assert append_schema["required"] == ["session_id", "sequence", "chunk", "chunk_sha256"]
    read_schema = outcome(contracts[4])[1]["input_schema"]["properties"]["payload"]
    assert read_schema["required"] == ["report_id"]
    assert read_schema["properties"]["length"]["maximum"] == CHUNK


# ---- 2. the walk-through ------------------------------------------------------------------


@pytest.mark.e2e
def test_begin_append_finalize_publish_read_and_read_chunk_walk_through(
    harness: Harness, store_root: Path
) -> None:
    """A 600 KiB markdown transfer, every step through the facade, every row read back."""
    token = harness.client(CLIENT, transfer_grants(harness.service))
    staged = markdown_text(600 * 1024)
    assert len(staged) > READ_INLINE_CONTENT_MAX_BYTES
    chunks = pieces(staged)
    assert [len(chunk) for chunk in chunks] == [CHUNK, CHUNK, len(staged) - 2 * CHUNK]

    begin_request = begin_payload(staged)
    begun = single(harness, token, WRITE_TOOL, BEGIN, begin_request)
    example("begin", begun, begin_request)
    opened = ok(begun)
    session_id = opened["session_id"]
    assert opened == {
        "session_id": session_id,
        "state": "open",
        "format": "markdown",
        "encoding": "identity",
        "declared_byte_count": len(staged),
        "declared_sha256": sha(staged),
        "chunk_byte_limit": CHUNK,
        "chunk_count": 3,
        "expires_at": opened["expires_at"],
        "replayed": False,
    }
    row = session_row(harness.engine, session_id)
    assert (row.state, row.received_byte_count, row.content_token_digest) == ("open", 0, None)
    assert row.client_ref.startswith("remote_client:gcrt_")
    assert row.idempotency_key == expected_key(begin_request, CLIENT, BEGIN)

    for sequence, chunk in enumerate(chunks):
        request = append_payload(session_id, sequence, chunk)
        answer = single(harness, token, WRITE_TOOL, APPEND, request)
        if sequence == 0:
            example("append[0]", answer, request)
        got = ok(answer)
        received = sum(len(piece) for piece in chunks[: sequence + 1])
        assert got == {
            "session_id": session_id,
            "sequence": sequence,
            "byte_offset": sequence * CHUNK,
            "byte_count": len(chunk),
            "chunk_sha256": sha(chunk),
            "received_byte_count": received,
            "declared_byte_count": len(staged),
            "complete": sequence == 2,
            "next_sequence": None if sequence == 2 else sequence + 1,
            "expires_at": opened["expires_at"],
            "replayed": False,
        }
        assert answer.request_bytes < MAX_REQUEST_BYTES
    ledger = rows(
        harness.engine,
        "SELECT sequence, byte_offset, byte_count, chunk_sha256 FROM "
        "knowledge.report_transfer_chunks WHERE session_id = :s ORDER BY sequence",
        s=session_id,
    )
    assert [tuple(entry) for entry in ledger] == [
        (n, n * CHUNK, len(chunk), sha(chunk)) for n, chunk in enumerate(chunks)
    ]
    assert len(staged_files(store_root, session_id)) == 3

    finalized = single(harness, token, WRITE_TOOL, FINALIZE, {"session_id": session_id})
    example("finalize", finalized, {"session_id": session_id})
    closed = ok(finalized)
    content_token = closed["content_token"]
    assert closed == {
        "session_id": session_id,
        "state": "finalized",
        "content_token": content_token,
        "expires_at": opened["expires_at"],
        "byte_count": len(staged),
        "sha256": sha(staged),
        "format": "markdown",
        "encoding": "identity",
        "decoded_byte_count": len(staged),
        "decoded_sha256": sha(staged),
    }
    row = session_row(harness.engine, session_id)
    assert row.state == "finalized"
    # Only the token's digest is stored; the raw token is nowhere in the row.
    assert row.content_token_digest is not None
    assert content_token not in json.dumps([str(value) for value in row])

    publish_request = {
        "title": "Synthetic transferred report",
        "content": reference(session_id, content_token),
    }
    published = single(harness, token, WRITE_TOOL, PUBLISH, publish_request)
    example("reports.publish", published, publish_request)
    receipt = ok(published)
    content_id = receipt["content"]["content_id"]
    assert receipt["content"]["decoded_sha256"] == sha(staged)
    assert published.request_bytes < 1024

    # DB readback: the session is consumed into the version's content, the content
    # is a managed blob, the version and receipt exist, the staging is discarded.
    row = session_row(harness.engine, session_id)
    assert (row.state, row.consumed_content_id) == ("consumed", content_id)
    assert row.consumed_at is not None
    (content,) = rows(
        harness.engine,
        "SELECT storage_kind, blob_ref, decoded_sha256, decoded_byte_count FROM "
        "knowledge.report_content_objects WHERE content_id = :c",
        c=content_id,
    )
    assert tuple(content) == ("managed_blob", content_id, sha(staged), len(staged))
    (version,) = rows(
        harness.engine,
        "SELECT report_id, version_number, content_id FROM knowledge.report_versions "
        "WHERE version_id = :v",
        v=receipt["version_id"],
    )
    assert tuple(version) == (receipt["report_id"], 1, content_id)
    (stored_receipt,) = rows(
        harness.engine,
        "SELECT report_id, version_id FROM knowledge.report_receipts WHERE receipt_id = :r",
        r=receipt["receipt_id"],
    )
    assert tuple(stored_receipt) == (receipt["report_id"], receipt["version_id"])
    assert staged_files(store_root, session_id) == []
    assert not (store_root / "transfer").exists() or not any(
        path.name == session_id for path in (store_root / "transfer").rglob("*")
    )

    read_request = {"report_id": receipt["report_id"]}
    served = single(harness, token, READ_TOOL, READ, read_request)
    example("reports.read", served, read_request)
    got = ok(served)["content"]
    assert got["body_omitted"] == "exceeds_response_bound"
    assert got["body_chunked_read"] == {
        "capability": READ_CHUNK.value,
        "part": "decoded",
        "byte_count": len(staged),
        "sha256": sha(staged),
    }
    assert "body" not in got

    readback, exchanges = read_all(harness, token, receipt["report_id"])
    first_request = {
        "report_id": receipt["report_id"],
        "part": "decoded",
        "offset": 0,
        "version_number": 1,
    }
    example("read_chunk[0]", exchanges[0], first_request)
    example("read_chunk[last]", exchanges[-1])
    assert readback == staged
    assert len(exchanges) == 3
    last = ok(exchanges[-1])
    assert (last["total_byte_count"], last["part_sha256"], last["eof"]) == (
        len(staged),
        sha(staged),
        True,
    )
    assert max(answer.response_bytes for answer in exchanges) < 360_000


@pytest.mark.e2e
def test_a_transfer_under_the_response_bound_is_inline_and_read_chunk_reads_the_row(
    harness: Harness, store_root: Path
) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    staged = markdown_text(300 * 1024, seed=12)
    done = upload(harness, token, staged)
    receipt = ok(
        single(
            harness,
            token,
            WRITE_TOOL,
            PUBLISH,
            {**MINIMAL, "content": reference(done.session_id, done.content_token)},
        )
    )
    (storage,) = rows(
        harness.engine,
        "SELECT storage_kind FROM knowledge.report_content_objects WHERE content_id = :c",
        c=receipt["content"]["content_id"],
    )
    assert storage[0] == "inline"
    got = ok(single(harness, token, READ_TOOL, READ, {"report_id": receipt["report_id"]}))
    assert got["content"]["body"].encode() == staged
    assert "body_chunked_read" not in got["content"]
    readback, exchanges = read_all(harness, token, receipt["report_id"], length=100_000)
    assert readback == staged
    assert len(exchanges) == 4
    original, _ = read_all(harness, token, receipt["report_id"], part="original")
    assert original == staged


# ---- 3. RM-AC-006: 16 MiB ----------------------------------------------------------------


@pytest.mark.e2e
@pytest.mark.slow
def test_sixteen_mebibytes_upload_and_read_back_through_the_facade(
    harness: Harness, store_root: Path, record_property: Callable[[str, object], None]
) -> None:
    """RM-AC-006: 16,777,216 random ASCII bytes in 64 appends, read back in 64 chunks."""
    token = harness.client(CLIENT, transfer_grants(harness.service))
    staged = random_ascii(MAX_DECODED_CONTENT_BYTES)
    assert len(staged) == 16_777_216
    # No inline encoding could carry it: even its gzip member exceeds one request.
    assert len(gzip.compress(staged, compresslevel=9, mtime=0)) > MAX_REQUEST_BYTES
    timings: dict[str, float] = {}
    tracemalloc.start()
    started = time.perf_counter()

    begun = single(harness, token, WRITE_TOOL, BEGIN, begin_payload(staged, "text"))
    session_id = ok(begun)["session_id"]
    assert ok(begun)["chunk_count"] == 64
    timings["begin"] = time.perf_counter() - started

    mark = time.perf_counter()
    largest_request = 0
    largest_append_response = 0
    for batch in range(0, 64, 16):
        answers = harness.run(
            [
                (
                    token,
                    wrapped(
                        WRITE_TOOL,
                        APPEND,
                        append_payload(session_id, n, staged[n * CHUNK : (n + 1) * CHUNK]),
                    ),
                )
                for n in range(batch, batch + 16)
            ]
        )
        for answer in answers:
            ok(answer)
            largest_request = max(largest_request, answer.request_bytes)
            largest_append_response = max(largest_append_response, answer.response_bytes)
    timings["append_x64"] = time.perf_counter() - mark
    assert largest_request < MAX_REQUEST_BYTES

    mark = time.perf_counter()
    finalized = single(harness, token, WRITE_TOOL, FINALIZE, {"session_id": session_id})
    closed = ok(finalized)
    assert (closed["decoded_byte_count"], closed["decoded_sha256"]) == (len(staged), sha(staged))
    timings["finalize"] = time.perf_counter() - mark

    mark = time.perf_counter()
    published = single(
        harness,
        token,
        WRITE_TOOL,
        PUBLISH,
        {**MINIMAL, "content": reference(session_id, closed["content_token"])},
    )
    receipt = ok(published)
    timings["publish"] = time.perf_counter() - mark
    assert session_row(harness.engine, session_id).state == "consumed"

    mark = time.perf_counter()
    readback, exchanges = read_all(harness, token, receipt["report_id"])
    timings["read_chunk_x64"] = time.perf_counter() - mark
    timings["total"] = time.perf_counter() - started
    _current, traced_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()

    assert len(exchanges) == 64
    assert sha(readback) == sha(staged)
    assert readback == staged
    largest_response = max(answer.response_bytes for answer in exchanges)
    largest_request = max(
        largest_request,
        begun.request_bytes,
        finalized.request_bytes,
        published.request_bytes,
        *(answer.request_bytes for answer in exchanges),
    )
    assert largest_request < MAX_REQUEST_BYTES
    rss = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    peak_rss_bytes = rss if sys.platform == "darwin" else rss * 1024
    measured = {
        "largest_request_bytes": largest_request,
        "max_request_bytes": MAX_REQUEST_BYTES,
        "largest_append_response_bytes": largest_append_response,
        "largest_read_chunk_response_bytes": largest_response,
        "tracemalloc_peak_bytes": traced_peak,
        "peak_rss_bytes": peak_rss_bytes,
        **{f"seconds_{name}": round(value, 2) for name, value in timings.items()},
    }
    for name, value in measured.items():
        record_property(name, value)
    print("\nRM-AC-006 measurements: " + json.dumps(measured, sort_keys=True))


# ---- 4. gzip json transfer (RM-AC-004/005) ------------------------------------------------


@pytest.mark.e2e
def test_a_gzip_json_transfer_reads_back_original_and_decoded_and_is_searchable(
    harness: Harness, store_root: Path
) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    rng = random.Random(21)  # noqa: S311 - deterministic synthetic data, not a secret
    data = {
        "title": "Synthetic json transfer",
        "rows": [
            {
                "n": n,
                "note": f"row {n} {rng.randrange(10**9):09d}" + (f" {NEEDLE}" if n == 7 else ""),
            }
            for n in range(30_000)
        ],
    }
    raw = json.dumps(data, indent=1).encode()
    original = gzip.compress(raw, compresslevel=6, mtime=0)
    assert len(original) > CHUNK  # at least two chunks
    decoded = canonical_json(data)
    done = upload(harness, token, original, "json", GZIP)
    closed = ok(done.finalized)
    assert (closed["byte_count"], closed["sha256"]) == (len(original), sha(original))
    assert (closed["decoded_byte_count"], closed["decoded_sha256"]) == (len(decoded), sha(decoded))
    receipt = ok(
        single(
            harness,
            token,
            WRITE_TOOL,
            PUBLISH,
            {**MINIMAL, "content": reference(done.session_id, done.content_token)},
        )
    )
    got = ok(single(harness, token, READ_TOOL, READ, {"report_id": receipt["report_id"]}))[
        "content"
    ]
    assert (got["encoding"], got["format"]) == (GZIP, "json")
    assert (got["original_byte_count"], got["original_sha256"]) == (len(original), sha(original))
    assert (got["decoded_byte_count"], got["decoded_sha256"]) == (len(decoded), sha(decoded))
    if "encoded_omitted" in got:
        assert got["encoded_chunked_read"] == {
            "capability": READ_CHUNK.value,
            "part": "original",
            "byte_count": len(original),
            "sha256": sha(original),
        }
    exact_original, _ = read_all(harness, token, receipt["report_id"], part="original")
    assert exact_original == original
    exact_decoded, _ = read_all(harness, token, receipt["report_id"], part="decoded")
    assert exact_decoded == decoded
    assert json.loads(exact_decoded) == data
    (found,) = harness.run(
        [(token, wrapped(READ_TOOL, SEARCH, {"plane": "standalone", "query": NEEDLE}))]
    )
    assert [item["report_id"] for item in ok(found)["items"]] == [receipt["report_id"]]
    # Never from the Base64 transport text: a run of it finds nothing.
    transport = b64(original)
    probe = next(
        transport[at : at + 16]
        for at in range(4000, len(transport))
        if transport[at : at + 16].isalnum()
    )
    (nothing,) = harness.run(
        [(token, wrapped(READ_TOOL, SEARCH, {"plane": "standalone", "query": probe}))]
    )
    assert ok(nothing)["items"] == []


# ---- 5. reports.update consumes a transfer token -----------------------------------------


@pytest.mark.e2e
def test_reports_update_consumes_a_transfer_token(harness: Harness, store_root: Path) -> None:
    token = harness.client(CLIENT, transfer_grants(harness.service))
    first = ok(single(harness, token, WRITE_TOOL, PUBLISH, MINIMAL))
    staged = markdown_text(CHUNK + 4096, seed=31)
    done = upload(harness, token, staged)
    request = update_payload(
        first["report_id"], 1, {"content": reference(done.session_id, done.content_token)}
    )
    updated = single(harness, token, WRITE_TOOL, UPDATE, request)
    example("reports.update", updated, request)
    result = ok(updated)
    assert (result["version_number"], result["change_kind"], result["outcome"]) == (
        2,
        "content",
        "applied",
    )
    assert result["decoded_sha256"] == sha(staged)
    row = session_row(harness.engine, done.session_id)
    assert (row.state, row.consumed_content_id) == ("consumed", result["content_id"])
    (version,) = rows(
        harness.engine,
        "SELECT content_id FROM knowledge.report_versions WHERE version_id = :v",
        v=result["version_id"],
    )
    assert version[0] == result["content_id"]
    readback, _ = read_all(harness, token, first["report_id"], version_number=2)
    assert readback == staged
    assert staged_files(store_root, done.session_id) == []


# ---- 6. begin's server-stamped, client-bound key -------------------------------------------


def test_an_identical_begin_replays_and_another_client_opens_its_own(harness: Harness) -> None:
    rows_ = transfer_grants(harness.service)
    first = harness.client(CLIENT, rows_)
    second = harness.client(OTHER_CLIENT, rows_)
    staged = markdown_text(4096, seed=41)
    payload = begin_payload(staged)
    original, retried, theirs = harness.run(
        [
            (first, wrapped(WRITE_TOOL, BEGIN, payload)),
            (first, wrapped(WRITE_TOOL, BEGIN, payload)),
            (second, wrapped(WRITE_TOOL, BEGIN, payload)),
        ]
    )
    opened, replayed, other = ok(original), ok(retried), ok(theirs)
    assert replayed == {**opened, "replayed": True}
    assert other["session_id"] != opened["session_id"]
    assert other["replayed"] is False
    keys = {
        row.session_id: row.idempotency_key
        for row in rows(harness.engine, "SELECT * FROM knowledge.report_transfer_sessions")
    }
    assert keys == {
        opened["session_id"]: expected_key(payload, CLIENT, BEGIN),
        other["session_id"]: expected_key(payload, OTHER_CLIENT, BEGIN),
    }
    # A different ttl is a different declaration, so a different key and session.
    (later,) = harness.run([(first, wrapped(WRITE_TOOL, BEGIN, {**payload, "ttl_seconds": 600}))])
    assert ok(later)["session_id"] not in keys


def test_an_identical_begin_after_its_session_ended_opens_a_new_session(
    harness: Harness, clock: Clock
) -> None:
    """T7': abort / consume / expiry free the server-stamped key for the same declaration."""
    token = harness.client(CLIENT, transfer_grants(harness.service))
    # abort -> begin again with the identical declaration -> a NEW session (T9's recovery).
    staged = markdown_text(4096, seed=42)
    payload = begin_payload(staged)
    aborted = ok(single(harness, token, WRITE_TOOL, BEGIN, payload))
    ok(single(harness, token, WRITE_TOOL, ABORT, {"session_id": aborted["session_id"]}))
    renewed = ok(single(harness, token, WRITE_TOOL, BEGIN, payload))
    assert renewed["replayed"] is False and renewed["state"] == "open"
    assert renewed["session_id"] != aborted["session_id"]
    # The new session binds the key: a retry replays it.
    assert ok(single(harness, token, WRITE_TOOL, BEGIN, payload)) == {**renewed, "replayed": True}
    # consume -> identical begin -> a NEW session.
    consumed_text = markdown_text(3000, seed=43)
    done = upload(harness, token, consumed_text)
    ok(
        single(
            harness,
            token,
            WRITE_TOOL,
            PUBLISH,
            {**MINIMAL, "content": reference(done.session_id, done.content_token)},
        )
    )
    again = ok(single(harness, token, WRITE_TOOL, BEGIN, begin_payload(consumed_text)))
    assert again["replayed"] is False and again["session_id"] != done.session_id
    # An open keyed session expired by time -> identical begin -> a NEW session,
    # and the old row is now `expired`.
    expiring_text = markdown_text(2000, seed=44)
    expiring = begin_payload(expiring_text, ttl_seconds=300)
    stale = ok(single(harness, token, WRITE_TOOL, BEGIN, expiring))
    assert session_row(harness.engine, stale["session_id"]).state == "open"
    clock.advance(300)  # expires_at <= now
    fresh = ok(single(harness, token, WRITE_TOOL, BEGIN, expiring))
    assert fresh["replayed"] is False and fresh["session_id"] != stale["session_id"]
    assert session_row(harness.engine, stale["session_id"]).state == "expired"
    states = {
        row.session_id: (row.state, row.idempotency_key)
        for row in rows(harness.engine, "SELECT * FROM knowledge.report_transfer_sessions")
    }
    assert states[aborted["session_id"]] == ("aborted", expected_key(payload, CLIENT, BEGIN))
    assert states[renewed["session_id"]] == ("open", expected_key(payload, CLIENT, BEGIN))
    assert states[done.session_id][0] == "consumed"
    assert states[again["session_id"]][0] == "open"
    assert states[done.session_id][1] == states[again["session_id"]][1]
    assert states[stale["session_id"]] == ("expired", expected_key(expiring, CLIENT, BEGIN))
    assert states[fresh["session_id"]] == ("open", expected_key(expiring, CLIENT, BEGIN))


# ---- 7. availability: no store ---------------------------------------------------------------


@pytest.mark.parametrize("composition", ["no_store", "store_without_staging"])
def test_without_store_and_staging_the_uploads_are_absent_and_unsupported(
    migrated_engine: Engine, store_root: Path, composition: str
) -> None:
    root = None if composition == "no_store" else store_root
    harness = Harness(migrated_engine, build_transfer_service(migrated_engine, root, staging=False))
    harness.gates()
    assert not set(UPLOADS) & set(harness.service.available_capabilities)
    assert READ_CHUNK in harness.service.available_capabilities
    # Granted explicitly: availability, not the grant, withholds them.
    granted = (*profile_grants(harness.service), *(grant_row(capability) for capability in UPLOADS))
    token = harness.client(CLIENT, granted)
    staged = markdown_text(2048, seed=51)
    listed, exact_read_chunk, *answers = harness.run(
        [
            (token, describe(feature="reports", limit=100)),
            (token, describe(capability=READ_CHUNK.value)),
            *((token, describe(capability=capability.value)) for capability in UPLOADS),
            (token, wrapped(WRITE_TOOL, BEGIN, begin_payload(staged))),
            (
                token,
                wrapped(WRITE_TOOL, APPEND, append_payload("grxfr_00000000nothere0", 0, staged)),
            ),
            (token, wrapped(WRITE_TOOL, FINALIZE, {"session_id": "grxfr_00000000nothere0"})),
            (token, wrapped(WRITE_TOOL, ABORT, {"session_id": "grxfr_00000000nothere0"})),
        ]
    )
    _failed, catalog = outcome(listed)
    described = {item["capability"] for item in catalog["items"]}
    assert READ_CHUNK.value in described
    assert not {capability.value for capability in UPLOADS} & described
    _failed, read_chunk_contract = outcome(exact_read_chunk)
    assert read_chunk_contract["item"]["capability"] == READ_CHUNK.value
    for answer in answers:
        failed, document = outcome(answer)
        assert failed, document
        problem = document.get("error", document)
        assert (problem["code"], problem.get("safe_details") or []) == ("unsupported", [])
    assert (
        rows(migrated_engine, "SELECT count(*) FROM knowledge.report_transfer_sessions")[0][0] == 0
    )
    # read_chunk still serves an inline report without a store.
    receipt = ok(single(harness, token, WRITE_TOOL, PUBLISH, MINIMAL))
    readback, _ = read_all(harness, token, receipt["report_id"])
    assert readback == MINIMAL["content"]["body"].encode()
