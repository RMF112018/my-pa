"""Reports Modernization WP05 B/C: gzip+base64 and report content store refusals on the facade.

The harness is `tests/contract/test_reports_content_compact_facade.py`'s: the
real remote MCP app over the durable grant store on PostgreSQL, its service
composed with a real `FilesystemReportContentStore` on `tmp_path`. Every
refusal below happens before any mutation: each asserts the standalone report
tables (and the `knowledge.intelligence_*` tables) hold exactly the rows they
held, and that the store holds exactly the objects it held. No refusal echoes
the value it refused.

* every `content.encoded` decoder rule (Base64 shape and canonicality, gzip
  magic, corruption, truncation, trailing bytes and members, nesting, the
  ratio and the 16 MiB bounds, declared sizes and digests, UTF-8, JSON
  syntax, duplicate keys, depth, NaN, the mixed shape), the encoded/body
  mixtures and forged server fields inside `content`;
* decoded content above the inline threshold in a composition WITHOUT a store
  is refused `content`/`max_bytes`;
* a foreign Principal's blob report reads exactly as a nonexistent one;
* a missing or tampered stored object makes `my_pa.read` answer
  `internal_error` with no body, digest, identifier or path;
* gzip payloads under the profile, grant, revocation, wrong-wrapper and
  write-gate refusals of `reports.publish`, `reports.update` and `reports.read`.

Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import json
from collections.abc import Iterator
from datetime import timedelta
from pathlib import Path
from typing import Any, Final

import pytest
from sqlalchemy import Engine
from tests.conftest import metadata_for, operator
from tests.contract.test_reports_compact_facade import (
    CLIENT,
    INTELLIGENCE_TABLES,
    MINIMAL,
    OTHER_CLIENT,
    PLANE_TABLES,
    PUBLISH,
    READ,
    UPDATE,
    WHEN,
    Harness,
    counts,
    describe,
    grant_row,
    ok,
    outcome,
    profile_grants,
    refusal,
    remote_principal,
    update_payload,
    wrapped,
)
from tests.contract.test_reports_content_compact_facade import (
    GZIP,
    LOW,
    b64,
    build_stored_service,
    bulk_text,
    gz,
    gzip_content,
    object_dir,
    sha,
)

from my_pa.adapters.mcp.chatllm_gateway import OPERATOR_TOOL, READ_TOOL, WRITE_TOOL
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES
from my_pa.domain.reports.vocabulary import MAX_DECODED_CONTENT_BYTES, MAX_EXPANSION_RATIO
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore

pytestmark = pytest.mark.database

_ALL_TABLES: Final = PLANE_TABLES + INTELLIGENCE_TABLES
_RAW: Final = b"# Gzipped refusal probe\n\nSynthetic text about a dunlin survey.\n"


@pytest.fixture
def store_root(tmp_path: Path) -> Path:
    return tmp_path / "report-content"


@pytest.fixture
def harness(migrated_engine: Engine, store_root: Path) -> Harness:
    built = Harness(migrated_engine, build_stored_service(migrated_engine, store_root, LOW))
    built.gates()
    return built


def _store(root: Path) -> FilesystemReportContentStore:
    root.mkdir(parents=True, exist_ok=True)
    return FilesystemReportContentStore(root)


class _State:
    """Rows and store objects before a request, compared after it."""

    def __init__(self, harness: Harness, root: Path) -> None:
        self.harness, self.root = harness, root
        self.rows = counts(harness.engine, _ALL_TABLES)
        self.objects = _store(root).stored_object_ids()

    def unchanged(self) -> None:
        assert counts(self.harness.engine, _ALL_TABLES) == self.rows
        assert _store(self.root).stored_object_ids() == self.objects


def _with_padding(raw: bytes, remainder: int) -> bytes:
    """A gzip member of `raw` (plus filler) whose length is `remainder` mod 3."""
    for filler in range(64):
        original = gz(raw + b" " * filler)
        if len(original) % 3 == remainder:
            return original
    raise AssertionError("no filler fits")  # pragma: no cover


def _non_canonical_pad_bits() -> str:
    encoded = b64(_with_padding(_RAW, 1))  # ends "xy=="
    assert encoded.endswith("==")
    alphabet = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"
    index = alphabet.index(encoded[-3])
    assert index & 0b1111 == 0
    forged = encoded[:-3] + alphabet[index | 1] + "=="
    assert base64.b64decode(forged) == base64.b64decode(encoded)
    return forged


def _flip(original: bytes, at: int) -> bytes:
    return original[:at] + bytes([original[at] ^ 0xFF]) + original[at + 1 :]


_ORIGINAL: Final = gz(_RAW)


def _encoded_cases() -> Iterator[tuple[str, dict[str, Any]]]:
    good = b64(_ORIGINAL)
    yield "empty", {"format": "markdown", "encoding": GZIP, "encoded": ""}
    yield (
        "whitespace",
        {"format": "markdown", "encoding": GZIP, "encoded": good[:8] + "\n" + good[8:]},
    )
    yield (
        "inner_space",
        {"format": "markdown", "encoding": GZIP, "encoded": good[:8] + "    " + good[8:]},
    )
    yield "bad_padding", {"format": "markdown", "encoding": GZIP, "encoded": good + "===="}
    yield (
        "missing_padding",
        {
            "format": "markdown",
            "encoding": GZIP,
            "encoded": b64(_with_padding(_RAW, 1)).rstrip("="),
        },
    )
    yield "urlsafe", {"format": "markdown", "encoding": GZIP, "encoded": "-_" + good[2:]}
    yield (
        "non_canonical_pad_bits",
        {
            "format": "markdown",
            "encoding": GZIP,
            "encoded": _non_canonical_pad_bits(),
        },
    )
    yield "not_gzip", {"format": "markdown", "encoding": GZIP, "encoded": b64(_RAW)}
    yield (
        "corrupt_deflate",
        {
            "format": "markdown",
            "encoding": GZIP,
            "encoded": b64(_flip(_ORIGINAL, 14)),
        },
    )
    yield (
        "corrupt_crc",
        {
            "format": "markdown",
            "encoding": GZIP,
            "encoded": b64(_flip(_ORIGINAL, len(_ORIGINAL) - 6)),
        },
    )
    yield "truncated", {"format": "markdown", "encoding": GZIP, "encoded": b64(_ORIGINAL[:-10])}
    yield (
        "trailing_member",
        {
            "format": "markdown",
            "encoding": GZIP,
            "encoded": b64(_ORIGINAL + gz(b"second member")),
        },
    )
    yield (
        "trailing_byte",
        {
            "format": "markdown",
            "encoding": GZIP,
            "encoded": b64(_ORIGINAL + b"\x00"),
        },
    )
    yield "nested_gzip", gzip_content("markdown", _ORIGINAL)
    yield "invalid_utf8", gzip_content("markdown", b"# Title\n\n\xff\xfe synthetic")
    yield "blank_body", gzip_content("markdown", b"   \n\t ")
    yield "nul_body", gzip_content("markdown", b"# Title\x00 synthetic")
    yield "invalid_json", gzip_content("json", b'{"a": 1,')
    yield "duplicate_key", gzip_content("json", b'{"a": 1, "a": 2}')
    yield "too_deep", gzip_content("json", b"[" * 40 + b"]" * 40)
    yield "nan", gzip_content("json", b'{"a": NaN}')
    yield "mixed_without_data", gzip_content("mixed", json.dumps({"body": "x"}).encode())
    yield (
        "mixed_extra_key",
        gzip_content("mixed", json.dumps({"body": "x", "data": {}, "extra": 1}).encode()),
    )
    raw_size = len(_RAW)
    for name, wrong in (
        ("original_byte_count", len(_ORIGINAL) + 1),
        ("original_sha256", sha(_RAW)),
        ("uncompressed_byte_count", raw_size - 1),
        ("uncompressed_sha256", sha(_ORIGINAL)),
    ):
        yield f"false_{name}", {**gzip_content("markdown", _RAW), name: wrong}
    yield "body_and_encoded", {**gzip_content("markdown", _RAW), "body": _RAW.decode()}
    yield "data_and_encoded", {**gzip_content("json", b"{}"), "data": {}}
    yield (
        "identity_with_encoded",
        {
            "format": "markdown",
            "body": _RAW.decode(),
            "encoded": b64(_ORIGINAL),
        },
    )
    yield (
        "identity_with_declared",
        {
            "format": "markdown",
            "body": _RAW.decode(),
            "original_sha256": sha(_RAW),
        },
    )
    yield "gzip_without_encoded", {"format": "markdown", "encoding": GZIP}
    yield (
        "unknown_encoding",
        {"format": "markdown", "encoding": "deflate", "encoded": b64(_ORIGINAL)},
    )


_ENCODED_CASES: Final = dict(_encoded_cases())
#: Server-owned fields forged inside `content`: refused by the closed schema.
_FORGED_CONTENT_FIELDS: Final = (
    "storage_kind",
    "blob_ref",
    "decoded_sha256",
    "decoded_byte_count",
    "canonical_sha256",
    "content_id",
    "body_omitted",
    "encoded_omitted",
)


def _no_echo(document: Any, *values: str) -> None:  # noqa: ANN401
    rendered = json.dumps(document)
    for value in values:
        if len(value) >= 12:
            assert value[:12] not in rendered
            assert value[-12:] not in rendered


def _refused_before_mutation(
    harness: Harness, root: Path, content: dict[str, Any], expected: tuple[str, list[str]]
) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    seed = ok(harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, MINIMAL))])[0])
    state = _State(harness, root)
    published, updated = harness.run(
        [
            (token, wrapped(WRITE_TOOL, PUBLISH, {**MINIMAL, "content": content})),
            (
                token,
                wrapped(
                    WRITE_TOOL, UPDATE, update_payload(seed["report_id"], 1, {"content": content})
                ),
            ),
        ]
    )
    for answer in (published, updated):
        assert refusal(answer) == expected
        encoded = content.get("encoded")
        _no_echo(answer.document, *([encoded] if isinstance(encoded, str) else []))
    state.unchanged()


@pytest.mark.parametrize("case", sorted(_ENCODED_CASES))
def test_a_malformed_gzip_content_is_refused_before_mutation(
    harness: Harness, store_root: Path, case: str
) -> None:
    _refused_before_mutation(
        harness, store_root, _ENCODED_CASES[case], ("invalid_request", ["content"])
    )


@pytest.mark.parametrize("name", _FORGED_CONTENT_FIELDS)
def test_a_forged_server_field_inside_content_is_refused(
    harness: Harness, store_root: Path, name: str
) -> None:
    forged = {**gzip_content("markdown", _RAW), name: "managed_blob"}
    _refused_before_mutation(harness, store_root, forged, ("invalid_request", ["content"]))


def _bomb() -> dict[str, Any]:
    raw = b"a" * (1 << 20)
    assert len(raw) > MAX_EXPANSION_RATIO * len(gz(raw))
    return gzip_content("text", raw)


def _over_sixteen_mib() -> dict[str, Any]:
    raw = bulk_text(MAX_DECODED_CONTENT_BYTES + 1)
    content = gzip_content("markdown", raw, level=6)
    assert len(raw) <= MAX_EXPANSION_RATIO * len(base64.b64decode(content["encoded"]))
    return content


@pytest.mark.parametrize("case", ["bomb_over_ratio", "decoded_over_16_mib"])
def test_a_gzip_over_a_size_bound_is_refused_with_max_bytes(
    harness: Harness, store_root: Path, case: str
) -> None:
    content = _bomb() if case == "bomb_over_ratio" else _over_sixteen_mib()
    _refused_before_mutation(
        harness, store_root, content, ("invalid_request", ["content", "max_bytes"])
    )


def test_above_the_inline_threshold_without_a_store_is_refused_with_max_bytes(
    migrated_engine: Engine,
) -> None:
    """A composition with no report content store (WP04 behaviour plus inline gzip)."""
    storeless = Harness(migrated_engine, build_stored_service(migrated_engine, None))
    storeless.gates()
    token = storeless.client(CLIENT, profile_grants(storeless.service))
    raw = bulk_text(INLINE_CONTENT_MAX_BYTES + 1)
    before = counts(migrated_engine, _ALL_TABLES)
    gzipped, identity = storeless.run(
        [
            (
                token,
                wrapped(WRITE_TOOL, PUBLISH, {**MINIMAL, "content": gzip_content("markdown", raw)}),
            ),
            # An identity body over the inline maximum is refused the same way.
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    PUBLISH,
                    {**MINIMAL, "content": {"format": "markdown", "body": raw.decode()}},
                ),
            ),
        ]
    )
    for answer in (gzipped, identity):
        assert answer.request_bytes < MAX_REQUEST_BYTES
        assert refusal(answer) == ("invalid_request", ["content", "max_bytes"])
    assert counts(migrated_engine, _ALL_TABLES) == before
    # Exactly at the threshold still publishes inline.
    at = {**MINIMAL, "content": gzip_content("markdown", raw[:-1])}
    (answer,) = storeless.run([(token, wrapped(WRITE_TOOL, PUBLISH, at))])
    assert ok(answer)["content"]["decoded_byte_count"] == INLINE_CONTENT_MAX_BYTES


# ---- blob reads -------------------------------------------------------------------------


def _blob_report(harness: Harness, token: str) -> dict[str, Any]:
    (answer,) = harness.run(
        [
            (
                token,
                wrapped(
                    WRITE_TOOL,
                    PUBLISH,
                    {**MINIMAL, "content": gzip_content("markdown", bulk_text(LOW * 4))},
                ),
            )
        ]
    )
    receipt = ok(answer)
    return receipt


def test_a_foreign_principals_blob_report_reads_exactly_as_a_nonexistent_one(
    harness: Harness, store_root: Path
) -> None:
    stranger = operator()
    assert stranger.principal_id != remote_principal().principal_id
    _metadata, command = normalize(
        PUBLISH.value,
        {
            "request_id": "req-foreign-blob",
            "purpose": Purpose.REPORT_AUTHORING.value,
            "principal_id": stranger.principal_id,
            "requested_at": "2026-11-04T12:00:00Z",
            "payload": {
                **MINIMAL,
                "content": gzip_content("markdown", bulk_text(LOW * 4, seed=5)),
                "idempotency_key": "idk_foreign_blob_report_0001",
            },
        },
    )
    foreign = harness.service.invoke(
        metadata_for(PUBLISH, Purpose.REPORT_AUTHORING, stranger), command, principal=stranger
    )
    assert foreign.result is not None, foreign.error
    content_id = foreign.result["content"]["content_id"]
    assert (object_dir(store_root, content_id) / "decoded").is_file()
    token = harness.client(CLIENT, profile_grants(harness.service))
    theirs, by_version, missing = harness.run(
        [
            (token, wrapped(READ_TOOL, READ, {"report_id": foreign.result["report_id"]})),
            (
                token,
                wrapped(
                    READ_TOOL,
                    READ,
                    {
                        "report_id": foreign.result["report_id"],
                        "version_id": foreign.result["version_id"],
                        "include_manifest": True,
                    },
                ),
            ),
            (token, wrapped(READ_TOOL, READ, {"report_id": "grpt_00000000nothere0"})),
        ]
    )
    redacted = []
    for answer in (theirs, by_version, missing):
        _failed, document = outcome(answer)
        assert (document["error"]["code"], document["error"]["safe_details"]) == (
            "not_found",
            ["artifact_id"],
        )
        redacted.append({k: v for k, v in document["error"].items() if k != "correlation_id"})
        for leaked in (foreign.result["report_id"], content_id, foreign.result["version_id"]):
            assert leaked not in json.dumps(answer.document)
    assert redacted[0] == redacted[1] == redacted[2]


def _damaged_read(harness: Harness, store_root: Path, damage: str, include_body: bool) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    receipt = _blob_report(harness, token)
    content_id = receipt["content"]["content_id"]
    folder = object_dir(store_root, content_id)
    part = folder / ("original" if damage == "tampered_original" else "decoded")
    if damage == "missing":
        part.unlink()
    elif damage == "missing_object":
        for child in folder.iterdir():
            child.unlink()
        folder.rmdir()
    else:
        raw = bytearray(part.read_bytes())
        raw[len(raw) // 2] ^= 0x01
        part.chmod(0o600)
        part.write_bytes(bytes(raw))
    state = _State(harness, store_root)
    (answer,) = harness.run(
        [
            (
                token,
                wrapped(
                    READ_TOOL,
                    READ,
                    {"report_id": receipt["report_id"], "include_body": include_body},
                ),
            )
        ]
    )
    code, details = refusal(answer)
    assert (code, details) == ("internal_error", [])
    rendered = json.dumps(answer.document)
    for leaked in (
        content_id,
        receipt["content"]["decoded_sha256"],
        str(store_root),
        "decoded",
        "synthetic",
        "Synthetic",
    ):
        assert leaked not in rendered, leaked
    state.unchanged()


@pytest.mark.parametrize("include_body", [True, False], ids=["body", "no_body"])
@pytest.mark.parametrize(
    "damage", ["missing", "missing_object", "tampered_decoded", "tampered_original"]
)
def test_a_missing_or_tampered_blob_reads_as_internal_error(
    harness: Harness, store_root: Path, damage: str, include_body: bool
) -> None:
    _damaged_read(harness, store_root, damage, include_body)


# ---- profile, grant, revocation, wrapper and write gates with gzip payloads -----------------


def _gzip_publish() -> dict[str, Any]:
    return {**MINIMAL, "content": gzip_content("markdown", bulk_text(LOW * 2, seed=9))}


def _gzip_update(report_id: str) -> dict[str, Any]:
    return update_payload(
        report_id, 1, {"content": gzip_content("markdown", bulk_text(LOW * 2, seed=10))}
    )


def _seeded(harness: Harness) -> str:
    """A blob report published by a fully granted second client (same Principal)."""
    token = harness.client(OTHER_CLIENT, profile_grants(harness.service))
    return str(_blob_report(harness, token)["report_id"])


def _requests(capability: Capability, report_id: str) -> tuple[str, dict[str, Any]]:
    if capability is PUBLISH:
        return WRITE_TOOL, _gzip_publish()
    if capability is UPDATE:
        return WRITE_TOOL, _gzip_update(report_id)
    return READ_TOOL, {"report_id": report_id}


_GATED: Final = (PUBLISH, UPDATE, READ)


@pytest.mark.parametrize("capability", _GATED, ids=lambda c: c.value)
def test_a_name_omitted_from_the_profile_is_hidden_and_refused_with_gzip(
    harness: Harness, store_root: Path, capability: Capability
) -> None:
    report_id = _seeded(harness)
    rows = tuple(row for row in profile_grants(harness.service) if row[0] is not capability)
    token = harness.client(CLIENT, rows)
    tool, payload = _requests(capability, report_id)
    state = _State(harness, store_root)
    exact, called = harness.run(
        [
            (token, describe(capability=capability.value)),
            (token, wrapped(tool, capability, payload)),
        ]
    )
    assert refusal(exact) == ("unsupported", [])
    assert refusal(called) == ("unsupported", [])
    state.unchanged()


@pytest.mark.parametrize("capability", _GATED, ids=lambda c: c.value)
def test_an_expired_or_inexact_grant_is_refused_with_gzip(
    harness: Harness, store_root: Path, capability: Capability
) -> None:
    report_id = _seeded(harness)
    others = tuple(row for row in profile_grants(harness.service) if row[0] is not capability)
    expired = harness.client(
        CLIENT, (*others, grant_row(capability, expires_at=WHEN - timedelta(seconds=1)))
    )
    wrong_purpose = Purpose.REPORT_LIFECYCLE if capability is READ else Purpose.REPORT_READ
    inexact = harness.client(
        "synthetic-reports-facade-client-3", (*others, grant_row(capability, purpose=wrong_purpose))
    )
    tool, payload = _requests(capability, report_id)
    state = _State(harness, store_root)
    answers = harness.run(
        [
            (expired, wrapped(tool, capability, payload)),
            (inexact, wrapped(tool, capability, payload)),
        ]
    )
    for answer in answers:
        assert refusal(answer) == ("unsupported", [])
    state.unchanged()


@pytest.mark.parametrize("capability", _GATED, ids=lambda c: c.value)
def test_a_revoked_client_is_refused_with_gzip(
    harness: Harness, store_root: Path, capability: Capability
) -> None:
    report_id = _seeded(harness)
    token = harness.client(CLIENT, profile_grants(harness.service))
    harness.revoke(CLIENT)
    tool, payload = _requests(capability, report_id)
    state = _State(harness, store_root)
    (answer,) = harness.run([(token, wrapped(tool, capability, payload))])
    assert (answer.status, answer.document) == (401, {"error": "invalid_token"})
    state.unchanged()


@pytest.mark.parametrize("capability", _GATED, ids=lambda c: c.value)
def test_the_wrong_wrapper_is_refused_with_gzip(
    harness: Harness, store_root: Path, capability: Capability
) -> None:
    report_id = _seeded(harness)
    token = harness.client(CLIENT, profile_grants(harness.service))
    tool, payload = _requests(capability, report_id)
    wrong = READ_TOOL if tool == WRITE_TOOL else WRITE_TOOL
    state = _State(harness, store_root)
    swapped, operator_tool = harness.run(
        [
            (token, wrapped(wrong, capability, payload)),
            (token, wrapped(OPERATOR_TOOL, capability, payload)),
        ]
    )
    assert refusal(swapped)[0] == "invalid_request"
    assert refusal(operator_tool) == ("unsupported", [])
    state.unchanged()


@pytest.mark.parametrize(
    ("process", "durable_global", "client"),
    [(False, True, True), (True, False, True), (True, True, False)],
    ids=["process_writes_off", "global_writes_off", "client_writes_off"],
)
def test_any_write_gate_off_refuses_gzip_writes_and_still_reads(
    harness: Harness, store_root: Path, process: bool, durable_global: bool, client: bool
) -> None:
    report_id = _seeded(harness)
    harness.gates(writes=durable_global)
    token = harness.client(CLIENT, profile_grants(harness.service), writes=client)
    state = _State(harness, store_root)
    published, updated, served = harness.run(
        [
            (token, wrapped(WRITE_TOOL, PUBLISH, _gzip_publish())),
            (token, wrapped(WRITE_TOOL, UPDATE, _gzip_update(report_id))),
            (token, wrapped(READ_TOOL, READ, {"report_id": report_id})),
        ],
        process_writes=process,
    )
    assert refusal(published) == ("unsupported", [])
    assert refusal(updated) == ("unsupported", [])
    assert ok(served)["content"]["storage_kind"] == "managed_blob"
    state.unchanged()


def test_remote_access_disabled_refuses_gzip_publish(harness: Harness, store_root: Path) -> None:
    token = harness.client(CLIENT, profile_grants(harness.service))
    harness.gates(remote=False)
    state = _State(harness, store_root)
    (answer,) = harness.run([(token, wrapped(WRITE_TOOL, PUBLISH, _gzip_publish()))])
    assert (answer.status, answer.document) == (401, {"error": "invalid_token"})
    state.unchanged()


def test_a_gzip_publish_echoes_nothing_it_refused(harness: Harness, store_root: Path) -> None:
    """Sanity of `_no_echo`: a valid probe's encoded prefix is absent from a refusal."""
    content = {**gzip_content("markdown", _RAW), "uncompressed_sha256": sha(b"other")}
    token = harness.client(CLIENT, profile_grants(harness.service))
    (answer,) = harness.run(
        [(token, wrapped(WRITE_TOOL, PUBLISH, {**MINIMAL, "content": content}))]
    )
    assert refusal(answer) == ("invalid_request", ["content"])
    rendered = json.dumps(answer.document)
    for value in (content["encoded"][:12], sha(b"other")[:12], sha(_RAW)[:12], "dunlin"):
        assert value not in rendered
    assert gzip.decompress(base64.b64decode(content["encoded"])) == _RAW
