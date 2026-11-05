"""Reports Modernization WP05 B/C: gzip+base64 content and the report content store, end to end.

The harness is `tests/contract/test_reports_compact_facade.py`'s -- the real
remote MCP app (`create_remote_mcp_app`) over httpx's ASGI transport, the real
`RemoteAuthenticator` against the durable grant store, the composition root's
`remote_access_context` and a real `ApplicationService` on a migrated,
disposable PostgreSQL clone -- except that the service is composed with a real
`FilesystemReportContentStore` on `tmp_path` (and, where stated, a low inline
threshold). Every request is an HTTP POST through `my_pa.describe`,
`my_pa.write` or `my_pa.read`. What it proves:

* describe: `reports.publish` and `reports.update` carry the one extended
  content schema; `reports.read`'s input schema has no content field;
* gzip+base64 markdown, json and mixed publish and read back exactly: decoded
  body/data, `encoded` byte-identical to the upload, every digest equal to one
  computed here, `storage_kind` inline;
* above the response bound a report is a `managed_blob` (object on disk, row
  `blob_ref`), reads as metadata + digests + `body_omitted`, and search finds a
  word only its decoded text holds; under the bound (low threshold) a blob
  reads back its exact body;
* the largest executable decoded size (16,777,216 bytes) publishes within the
  request ceiling and the 256:1 ratio; measurements are recorded as junit
  properties (`record_property`);
* a gzip content update and a metadata-only update on a blob head; an
  identical gzip retry replays, a different stream of the same content is a
  different client-bound key (so a new report, never a conflict, through the
  facade);
* the `my_pa.read` HTTP response size at the response bound is pinned.

The refusals are in `tests/security/test_reports_content_compact_facade_adversarial.py`.
Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
import struct
import time
import zlib
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from tests.conftest import DEFAULT_LIMITS
from tests.contract.test_reports_compact_facade import (
    CLIENT,
    MINIMAL,
    PLANE_TABLES,
    PUBLISH,
    READ,
    UPDATE,
    WHEN,
    Exchange,
    Harness,
    _large_markdown,
    counts,
    describe,
    expected_key,
    ok,
    outcome,
    profile_grants,
    update_payload,
    wrapped,
)

from my_pa.adapters.mcp.chatllm_gateway import READ_TOOL, WRITE_TOOL
from my_pa.adapters.normalization import MAX_REQUEST_BYTES
from my_pa.application.service import ApplicationService
from my_pa.domain.identity.operation import Capability
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES, canonical_json
from my_pa.domain.reports.vocabulary import (
    MAX_DECODED_CONTENT_BYTES,
    MAX_EXPANSION_RATIO,
    READ_INLINE_CONTENT_MAX_BYTES,
)
from my_pa.infrastructure.persistence.audit import SqlAlchemyAuditSink
from my_pa.infrastructure.persistence.unit_of_work import SqlAlchemyUnitOfWork
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore

pytestmark = pytest.mark.database

SEARCH: Final = Capability.REPORTS_SEARCH
LOW: Final = 4096
GZIP: Final = "gzip+base64"
#: A word only the decoded text of the large report holds.
NEEDLE: Final = "ptarmiganquill"


# ---- composition -----------------------------------------------------------------------


def build_stored_service(
    engine: Engine, root: Path | None, threshold: int = INLINE_CONTENT_MAX_BYTES
) -> ApplicationService:
    """The facade service composed with a real filesystem content store on `root`."""
    audit = SqlAlchemyAuditSink(engine)
    store = None
    if root is not None:
        root.mkdir(parents=True, exist_ok=True)
        store = FilesystemReportContentStore(root)
    return ApplicationService(
        unit_of_work=lambda: SqlAlchemyUnitOfWork(engine, audit=audit),
        limits=DEFAULT_LIMITS,
        clock=lambda: WHEN,
        report_content_store=store,
        report_content_inline_max_bytes=threshold,
    )


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "report-content"


@pytest.fixture
def harness(migrated_engine: Engine, store_root: Path) -> Harness:
    built = Harness(migrated_engine, build_stored_service(migrated_engine, store_root))
    built.gates()
    return built


@pytest.fixture
def low_harness(migrated_engine: Engine, store_root: Path) -> Harness:
    built = Harness(migrated_engine, build_stored_service(migrated_engine, store_root, LOW))
    built.gates()
    return built


# ---- content builders ------------------------------------------------------------------


def gz(raw: bytes, level: int = 9) -> bytes:
    return gzip.compress(raw, compresslevel=level, mtime=0)


def b64(original: bytes) -> str:
    return base64.b64encode(original).decode("ascii")


def gzip_content(fmt: str, raw: bytes, *, level: int = 9, **declared: Any) -> dict[str, Any]:  # noqa: ANN401
    return {"format": fmt, "encoding": GZIP, "encoded": b64(gz(raw, level)), **declared}


def bulk_text(size: int, *, every: int = 40, needle: str | None = None, seed: int = 7) -> bytes:
    """`size` bytes of synthetic markdown compressing about 100:1 (inside 256:1)."""
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    vocabulary = ("risk", "slab", "pour", "crane", "rebar", "delay", "permit", "crew")
    steady = "- Synthetic schedule narrative, steady progress, no real data.\n"
    lines = ["# Synthetic bulk report\n"]
    if needle is not None:
        lines.append(f"Field note: {needle} observed on level three.\n")
    total = sum(len(line) for line in lines)
    number = 0
    while total < size:
        line = (
            f"- {rng.randrange(10**6):06d} {' '.join(rng.choice(vocabulary) for _ in range(5))}.\n"
            if number % every == 0
            else steady
        )
        lines.append(line)
        total += len(line)
        number += 1
    return "".join(lines).encode()[:size]


def stored_tail_gzip(decoded: bytes) -> bytes:
    """A gzip member of `decoded` whose size is as close to (and not above) the bound.

    A compressed run of `a` followed by stored (uncompressed) deflate blocks:
    `decoded` must start with that run. Used to build the largest original a
    read still returns as `encoded` for a decoded size at the bound.
    """
    run = len(decoded) - len(decoded.lstrip(b"a"))
    compressor = zlib.compressobj(9, zlib.DEFLATED, -15)
    head = compressor.compress(decoded[:run]) + compressor.flush(zlib.Z_SYNC_FLUSH)
    rest = decoded[run:]
    blocks = bytearray()
    for start in range(0, len(rest), 65535):
        chunk = rest[start : start + 65535]
        final = start + 65535 >= len(rest)
        blocks += bytes([1 if final else 0]) + struct.pack("<HH", len(chunk), len(chunk) ^ 0xFFFF)
        blocks += chunk
    header = b"\x1f\x8b\x08\x00\x00\x00\x00\x00\x02\xff"
    trailer = struct.pack("<II", zlib.crc32(decoded), len(decoded) & 0xFFFFFFFF)
    return header + head + bytes(blocks) + trailer


def noise_text(size: int, seed: int = 29) -> bytes:
    """`size` bytes of nearly incompressible synthetic ASCII text, not starting with `a`."""
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    alphabet = b"ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789 .,\n"
    return b"Z" + bytes(rng.choice(alphabet) for _ in range(size - 1))


def served_encoded_of(raw: bytes) -> str:
    return b64(gz(raw))


def largest_original_at_the_bound() -> tuple[bytes, bytes]:
    """(decoded, original): decoded exactly 524,288 bytes, original the largest <= 524,288."""
    noise = noise_text(READ_INLINE_CONTENT_MAX_BYTES)
    for run in range(16, 4096):
        decoded = b"a" * run + noise[: READ_INLINE_CONTENT_MAX_BYTES - run]
        original = stored_tail_gzip(decoded)
        if len(original) <= READ_INLINE_CONTENT_MAX_BYTES:
            assert gzip.decompress(original) == decoded
            return decoded, original
    raise AssertionError("no run length fits")  # pragma: no cover


# ---- facade helpers --------------------------------------------------------------------


def publish(harness: Harness, token: str, payload: Mapping[str, Any]) -> tuple[Exchange, Any]:
    (answer,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, payload))])
    return answer, ok(answer)


def read(
    harness: Harness,
    token: str,
    report_id: str,
    **extra: Any,  # noqa: ANN401
) -> tuple[Exchange, dict[str, Any]]:
    (answer,) = harness.run([(token, wrapped(READ_TOOL, READ, {"report_id": report_id, **extra}))])
    return answer, ok(answer)


def content_row(engine: Engine, content_id: str) -> Any:  # noqa: ANN401
    with engine.connect() as connection:
        return connection.execute(
            text("SELECT * FROM knowledge.report_content_objects WHERE content_id = :c"),
            {"c": content_id},
        ).one()


def object_dir(root: Path, content_id: str) -> Path:
    (found,) = [path for path in root.rglob(content_id) if path.is_dir()]
    return found


def sha(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


# ---- 1. describe ------------------------------------------------------------------------


def test_publish_and_update_describe_the_one_extended_content_schema(harness: Harness) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    published, updated, served = harness.run(
        [
            (token, describe(capability=PUBLISH.value)),
            (token, describe(capability=UPDATE.value)),
            (token, describe(capability=READ.value)),
        ]
    )
    publish_content = outcome(published)[1]["input_schema"]["properties"]["payload"]["properties"][
        "content"
    ]
    update_patch = outcome(updated)[1]["input_schema"]["properties"]["payload"]["properties"][
        "patch"
    ]
    update_content = update_patch["properties"]["content"]
    # One schema; the update's description adds only the same-content sentence (N4).
    assert {k: v for k, v in update_content.items() if k != "description"} == {
        k: v for k, v in publish_content.items() if k != "description"
    }
    assert update_content["description"] == (
        f"{publish_content['description']} A patch.content whose format, encoding and "
        "decoded content equal the head's is a metadata-only change that keeps the "
        "head's content, including its original gzip bytes (the new upload's bytes are "
        "not stored)."
    )
    assert publish_content["properties"]["encoding"]["enum"] == ["identity", GZIP]
    assert publish_content["properties"]["encoded"]["type"] == "string"
    for name in ("original_byte_count", "uncompressed_byte_count"):
        field = publish_content["properties"][name]
        assert (field["type"], field["minimum"], field["maximum"]) == (
            "integer",
            0,
            MAX_DECODED_CONTENT_BYTES,
        )
    for name in ("original_sha256", "uncompressed_sha256"):
        assert publish_content["properties"][name]["pattern"] == "^[0-9a-f]{64}$"
    described = publish_content["description"]
    for limit in (
        "524,288",
        "16,777,216",
        # WP05 corrective B6-1: the ratio and the size name the gunzipped bytes.
        "The gunzipped bytes are at most 16,777,216 and at most 256 times the gzip bytes",
        "the decoded (canonical) content is at most 16,777,216 bytes",
        "pretty-printed JSON counts its whitespace",
        "262,144",
        f"{MAX_REQUEST_BYTES:,}",
        "body_omitted",
        # WP05 corrective B5-1: the store-less bound names the gunzipped bytes too.
        "both the gunzipped bytes of a gzip+base64 upload and the decoded content",
    ):
        assert limit in described, limit
    assert "chunk" not in described
    read_payload = outcome(served)[1]["input_schema"]["properties"]["payload"]
    # `reports.read` gains no input field for WP05.
    assert set(read_payload["properties"]) == {
        "report_id",
        "include_body",
        "version_id",
        "version_number",
        "include_manifest",
        "include_withdrawn",
    }
    assert read_payload["additionalProperties"] is False


# ---- 2a. inline gzip ---------------------------------------------------------------------

_DATA: Final = {"phase": "foundation", "risks": [{"id": 1, "level": "high"}], "ok": True}
_BODY: Final = "# Gzipped assessment\n\nSynthetic narrative with a curlew note.\n"


@pytest.mark.parametrize(
    ("fmt", "raw"),
    [
        ("markdown", _BODY.encode()),
        ("json", json.dumps(_DATA, indent=2).encode()),
        ("mixed", json.dumps({"body": _BODY, "data": _DATA}).encode()),
    ],
)
def test_gzip_content_publishes_and_reads_back_exactly(
    harness: Harness, store_root: Path, fmt: str, raw: bytes
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    original = gz(raw)
    content = {
        "format": fmt,
        "encoding": GZIP,
        "encoded": b64(original),
        "original_byte_count": len(original),
        "original_sha256": sha(original),
        "uncompressed_byte_count": len(raw),
        "uncompressed_sha256": sha(raw),
    }
    _answer, receipt = publish(harness, token, {**MINIMAL, "content": content})
    _answer, served = read(harness, token, receipt["report_id"])
    got = served["content"]
    assert (got["encoding"], got["storage_kind"], got["format"]) == (GZIP, "inline", fmt)
    assert got["encoded"] == content["encoded"]
    assert (got["original_sha256"], got["original_byte_count"]) == (sha(original), len(original))
    if fmt == "markdown":
        expected = _BODY.encode()
        assert got["body"] == _BODY
        assert "data" not in got
        assert got["canonical_sha256"] is None
    elif fmt == "json":
        expected = canonical_json(_DATA)
        assert got["data"] == _DATA
        assert "body" not in got
        assert got["canonical_sha256"] == sha(expected)
    else:
        expected = canonical_json({"body": _BODY, "data": _DATA})
        assert (got["body"], got["data"]) == (_BODY, _DATA)
    assert got["decoded_sha256"] == sha(expected) == receipt["content"]["decoded_sha256"]
    assert got["decoded_byte_count"] == len(expected)
    row = content_row(harness.engine, got["content_id"])
    assert (row.storage_kind, row.blob_ref, bytes(row.inline_original)) == (
        "inline",
        None,
        original,
    )
    # No object is written for inline content.
    assert not store_root.exists() or not any(store_root.rglob("decoded"))


# ---- 2b/2c. managed blob --------------------------------------------------------------------


def test_a_large_gzip_report_is_a_blob_read_as_body_omitted_and_searchable(
    harness: Harness, store_root: Path
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    raw = bulk_text(READ_INLINE_CONTENT_MAX_BYTES * 4, needle=NEEDLE)
    original = gz(raw)
    assert len(raw) <= MAX_EXPANSION_RATIO * len(original)
    payload = {
        "title": "Synthetic bulk schedule report",
        "summary": "A synthetic summary.",
        "content": {"format": "markdown", "encoding": GZIP, "encoded": b64(original)},
    }
    published, receipt = publish(harness, token, payload)
    assert published.request_bytes < MAX_REQUEST_BYTES
    content_id = receipt["content"]["content_id"]
    row = content_row(harness.engine, content_id)
    assert (row.storage_kind, row.blob_ref) == ("managed_blob", content_id)
    assert (row.inline_text, row.inline_original) == (None, None)
    folder = object_dir(store_root, content_id)
    assert (folder / "decoded").read_bytes() == raw
    assert (folder / "original").read_bytes() == original

    answer, served = read(harness, token, receipt["report_id"])
    got = served["content"]
    assert got["storage_kind"] == "managed_blob"
    assert got["body_omitted"] == "exceeds_response_bound"
    # The gzip bytes are within the bound, so the exact upload still comes back.
    assert len(original) <= READ_INLINE_CONTENT_MAX_BYTES
    assert got["encoded"] == b64(original)
    assert "encoded_omitted" not in got
    assert "body" not in got and "data" not in got
    assert (got["decoded_sha256"], got["decoded_byte_count"]) == (sha(raw), len(raw))
    assert (got["original_sha256"], got["original_byte_count"]) == (sha(original), len(original))
    assert answer.response_bytes < 8192 + len(b64(original)) * 2

    (found,) = harness.run(
        [(token, wrapped(READ_TOOL, SEARCH, {"plane": "standalone", "query": NEEDLE}))]
    )
    assert [item["report_id"] for item in ok(found)["items"]] == [receipt["report_id"]]
    assert NEEDLE not in json.dumps(payload["title"]) + str(payload["summary"])


def test_a_blob_under_the_response_bound_reads_back_its_exact_body(
    low_harness: Harness, store_root: Path
) -> None:
    token = low_harness.client(CLIENT, profile_grants(low_harness.service))
    for fmt, raw in (
        ("markdown", bulk_text(LOW * 8)),
        ("json", json.dumps({"rows": [f"synthetic row {n}" for n in range(800)]}).encode()),
    ):
        original = gz(raw)
        _answer, receipt = publish(
            low_harness, token, {**MINIMAL, "content": gzip_content(fmt, raw)}
        )
        content_id = receipt["content"]["content_id"]
        assert content_row(low_harness.engine, content_id).storage_kind == "managed_blob"
        assert (object_dir(store_root, content_id) / "original").read_bytes() == original
        _answer, served = read(low_harness, token, receipt["report_id"])
        got = served["content"]
        assert got["storage_kind"] == "managed_blob"
        assert "body_omitted" not in got
        assert got["encoded"] == b64(original)
        if fmt == "markdown":
            assert got["body"].encode() == raw
        else:
            assert got["data"] == json.loads(raw)
    # An identity body above the low threshold is a blob too.
    identity = bulk_text(LOW * 2).decode()
    _answer, receipt = publish(
        low_harness, token, {**MINIMAL, "content": {"format": "markdown", "body": identity}}
    )
    _answer, served = read(low_harness, token, receipt["report_id"])
    assert served["content"]["storage_kind"] == "managed_blob"
    assert served["content"]["body"] == identity
    assert "encoded" not in served["content"]


# ---- 2d. the largest executable decoded size ---------------------------------------------------


def test_the_largest_decoded_size_publishes_within_the_request_ceiling(
    harness: Harness, store_root: Path, record_property: Callable[[str, object], None]
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    raw = bulk_text(MAX_DECODED_CONTENT_BYTES)
    original = gz(raw, level=6)
    ratio = len(raw) / len(original)
    assert len(raw) == MAX_DECODED_CONTENT_BYTES
    assert ratio <= MAX_EXPANSION_RATIO
    started = time.monotonic()
    published, receipt = publish(
        harness,
        token,
        {**MINIMAL, "content": {"format": "markdown", "encoding": GZIP, "encoded": b64(original)}},
    )
    publish_seconds = time.monotonic() - started
    assert published.request_bytes < MAX_REQUEST_BYTES
    assert receipt["content"]["decoded_byte_count"] == MAX_DECODED_CONTENT_BYTES
    assert receipt["content"]["decoded_sha256"] == sha(raw)
    started = time.monotonic()
    answer, served = read(harness, token, receipt["report_id"])
    read_seconds = time.monotonic() - started
    assert served["content"]["body_omitted"] == "exceeds_response_bound"
    assert served["content"]["original_sha256"] == sha(original)
    folder = object_dir(store_root, receipt["content"]["content_id"])
    assert (folder / "decoded").stat().st_size == MAX_DECODED_CONTENT_BYTES
    for name, value in (
        ("request_bytes", published.request_bytes),
        ("gzip_bytes", len(original)),
        ("decoded_bytes", len(raw)),
        ("ratio", round(ratio, 1)),
        ("publish_seconds", round(publish_seconds, 2)),
        ("read_seconds", round(read_seconds, 2)),
        ("read_response_bytes", answer.response_bytes),
    ):
        record_property(name, value)
    assert publish_seconds < 60


# ---- 2e. updates on a blob head ----------------------------------------------------------------


def test_gzip_and_metadata_only_updates_on_a_blob_head(
    low_harness: Harness, store_root: Path
) -> None:
    token = low_harness.client(CLIENT, profile_grants(low_harness.service))
    first_raw = bulk_text(LOW * 4, seed=1)
    _answer, receipt = publish(
        low_harness, token, {**MINIMAL, "content": gzip_content("markdown", first_raw)}
    )
    rid = receipt["report_id"]
    second_raw = bulk_text(LOW * 5, seed=2)
    (content_update,) = low_harness.run(
        [
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    UPDATE,
                    update_payload(rid, 1, {"content": gzip_content("markdown", second_raw)}),
                ),
            )
        ]
    )
    second = ok(content_update)
    assert (second["change_kind"], second["version_number"]) == ("content", 2)
    assert second["content_id"] != receipt["content"]["content_id"]
    assert second["decoded_sha256"] == sha(second_raw)
    assert content_row(low_harness.engine, second["content_id"]).storage_kind == "managed_blob"
    objects = sorted(path.name for path in store_root.rglob("grcnt_*"))
    assert objects == sorted([receipt["content"]["content_id"], second["content_id"]])
    before = counts(low_harness.engine)
    (metadata_update,) = low_harness.run(
        [(token, wrapped(WRITE_TOOL, UPDATE, update_payload(rid, 2, {"title": "Renamed"})))]
    )
    third = ok(metadata_update)
    assert (third["change_kind"], third["version_number"]) == ("metadata", 3)
    assert third["content_id"] == second["content_id"]
    after = counts(low_harness.engine)
    assert after["report_content_objects"] == before["report_content_objects"]
    assert sorted(path.name for path in store_root.rglob("grcnt_*")) == objects
    _answer, served = read(low_harness, token, rid)
    assert (served["version_number"], served["title"]) == (3, "Renamed")
    assert served["content"]["body"].encode() == second_raw
    assert served["content"]["encoded"] == b64(gz(second_raw))


# ---- 2f. idempotency -----------------------------------------------------------------------------


def test_an_identical_gzip_retry_replays_and_another_stream_is_another_key(
    harness: Harness,
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    raw = _BODY.encode()
    payload = {**MINIMAL, "content": gzip_content("markdown", raw)}
    first, again = harness.run(
        [
            (token, wrapped(WRITE_TOOL, PUBLISH, payload)),
            (token, wrapped(WRITE_TOOL, PUBLISH, payload)),
        ]
    )
    created, replayed = ok(first), ok(again)
    assert (created["replayed"], replayed["replayed"]) == (False, True)
    assert replayed["report_id"] == created["report_id"]
    assert counts(harness.engine)["report_roots"] == 1
    # Same decoded content, another gzip stream: the facade's key is the
    # client-bound hash of the whole payload, so this is a different key and a
    # different report; the same-key/different-stream conflict is reachable only
    # through a caller-supplied key (tests/database/test_reports_encoding.py).
    other = {**MINIMAL, "content": gzip_content("markdown", raw, level=1)}
    assert other["content"]["encoded"] != payload["content"]["encoded"]
    assert expected_key(other, CLIENT) != expected_key(payload, CLIENT)
    (distinct,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, other))])
    third = ok(distinct)
    assert third["replayed"] is False and third["report_id"] != created["report_id"]
    assert third["content"]["decoded_sha256"] == created["content"]["decoded_sha256"]
    with harness.engine.connect() as connection:
        keys = dict(
            connection.execute(
                text("SELECT report_id, idempotency_key FROM knowledge.report_receipts")
            )
            .tuples()
            .all()
        )
    assert keys == {
        created["report_id"]: expected_key(payload, CLIENT),
        third["report_id"]: expected_key(other, CLIENT),
    }


# ---- 3. the response bound ------------------------------------------------------------------


def test_the_read_response_at_the_bound_is_pinned(
    harness: Harness, record_property: Callable[[str, object], None]
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    # (i) identity markdown at the bound.
    body = _large_markdown()
    _answer, identity = publish(
        harness, token, {**MINIMAL, "content": {"format": "markdown", "body": body}}
    )
    identity_read, served = read(harness, token, identity["report_id"])
    assert served["content"]["body"] == body
    # (ii) gzip at the bound with the largest original that is still returned.
    decoded, original = largest_original_at_the_bound()
    gzip_published, at_bound = publish(
        harness,
        token,
        {**MINIMAL, "content": {"format": "text", "encoding": GZIP, "encoded": b64(original)}},
    )
    assert gzip_published.request_bytes < MAX_REQUEST_BYTES
    gzip_read, served = read(harness, token, at_bound["report_id"])
    assert served["content"]["body"].encode() == decoded
    assert served["content"]["encoded"] == b64(original)
    # One gzip byte more and `encoded` is omitted, the body still returned.
    level0 = gz(decoded, level=0)
    assert len(level0) > READ_INLINE_CONTENT_MAX_BYTES
    _answer, over = publish(
        harness,
        token,
        {**MINIMAL, "content": {"format": "text", "encoding": GZIP, "encoded": b64(level0)}},
    )
    _answer, served = read(harness, token, over["report_id"])
    assert served["content"]["encoded_omitted"] == "exceeds_response_bound"
    assert served["content"]["body"].encode() == decoded
    # (iii) a blob above the bound: body omitted, the (small) gzip upload returned.
    big = bulk_text(READ_INLINE_CONTENT_MAX_BYTES + 1)
    _answer, blob = publish(harness, token, {**MINIMAL, "content": gzip_content("markdown", big)})
    omitted_read, served = read(harness, token, blob["report_id"])
    assert served["content"]["body_omitted"] == "exceeds_response_bound"
    assert "encoded" in served["content"]
    # (iii') both above the bound (incompressible text, stored gzip blocks):
    # metadata and digests only.
    incompressible = noise_text(READ_INLINE_CONTENT_MAX_BYTES + 4096)
    stored = gz(incompressible, level=0)
    both_published, both = publish(
        harness,
        token,
        {**MINIMAL, "content": {"format": "text", "encoding": GZIP, "encoded": b64(stored)}},
    )
    assert both_published.request_bytes < MAX_REQUEST_BYTES
    both_read, served = read(harness, token, both["report_id"])
    assert served["content"]["body_omitted"] == "exceeds_response_bound"
    assert served["content"]["encoded_omitted"] == "exceeds_response_bound"
    assert "body" not in served["content"] and "encoded" not in served["content"]
    # (iv) the escape-heaviest body at the bound: control characters (each
    # `\\u00XX` escaped twice by the nested JSON) sprinkled to stay within 256:1.
    rng = random.Random(3)  # noqa: S311 - deterministic synthetic text, not a secret
    controls = bytes(
        rng.choice(b"abcdefgh") if index % 32 == 0 else 1
        for index in range(READ_INLINE_CONTENT_MAX_BYTES)
    )
    _answer, escaped = publish(
        harness, token, {**MINIMAL, "content": gzip_content("text", controls)}
    )
    escaped_read, served = read(harness, token, escaped["report_id"])
    assert served["content"]["body"].encode() == controls
    # (v) the worst measured: random control characters, so the body is
    # escape-heavy AND its gzip upload (returned as `encoded`) is large.
    random_controls = bytes(rng.randrange(1, 32) for _ in range(READ_INLINE_CONTENT_MAX_BYTES))
    worst_original = gz(random_controls)
    worst_published, worst = publish(
        harness,
        token,
        {
            **MINIMAL,
            "content": {"format": "text", "encoding": GZIP, "encoded": b64(worst_original)},
        },
    )
    assert worst_published.request_bytes < MAX_REQUEST_BYTES
    worst_read, served = read(harness, token, worst["report_id"])
    assert served["content"]["body"].encode() == random_controls
    assert served["content"]["encoded"] == b64(worst_original)
    for name, answer in (
        ("identity_bound_response_bytes", identity_read),
        ("gzip_bound_response_bytes", gzip_read),
        ("body_omitted_response_bytes", omitted_read),
        ("both_omitted_response_bytes", both_read),
        ("escape_heavy_bound_response_bytes", escaped_read),
        ("worst_bound_response_bytes", worst_read),
    ):
        record_property(name, answer.response_bytes)
    record_property("gzip_bound_original_bytes", len(original))
    record_property("gzip_bound_request_bytes", gzip_published.request_bytes)
    record_property("worst_original_bytes", len(worst_original))
    # Pinned upper bounds (bytes of the whole HTTP response body).
    assert identity_read.response_bytes < 600_000
    assert gzip_read.response_bytes < 1_400_000
    assert omitted_read.response_bytes < 4_096 + len(served_encoded_of(big))
    assert both_read.response_bytes < 4_096
    assert escaped_read.response_bytes < 3_800_000
    assert worst_read.response_bytes < 4_400_000
    assert set(counts(harness.engine, PLANE_TABLES)) == set(PLANE_TABLES)
