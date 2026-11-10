"""Reports Modernization WP05 B4-B6: `gzip+base64` content on PostgreSQL, inline storage.

The `database` tier, each test on its own disposable clone (`migrated_engine`).
What it proves:

* a gzip publish stores the exact gzip bytes as `inline_original`, their
  digest and size as `original_*`, and the decoded content and digests exactly
  as the identity content of the same text; the read rebuilds the content with
  its original, the manifest names the gzip facts, and the read payload's
  `encoded` is the caller's string byte for byte;
* `reports.update` with gzip content writes a new gzip content object, and a
  later metadata-only update keeps that content pointer and search text;
* the search projection is the decoded text, never Base64 or gzip bytes;
* a replay of the same gzip request replays, another gzip stream under the key
  conflicts; decoded content above the inline maximum writes nothing;
* the schema's CHECKs refuse a gzip row without, or with other, original
  bytes; with the digest CHECK dropped in the clone, a read still refuses a
  row whose `inline_original` no longer matches `original_sha256`.

Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import pytest
from sqlalchemy import Engine, text
from sqlalchemy.exc import IntegrityError

from my_pa.application.service import _general_read_payload
from my_pa.contracts.ports import ReportIdempotencyConflictError, ReportIntegrityError
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.reports.catalog import extract_search_text
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES, validate_content
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.manifest import manifest_digest
from my_pa.domain.reports.revision import ReportPatch, UpdateRequest, UpdateResult
from my_pa.domain.reports.vocabulary import ChangeKind, ContentEncoding
from my_pa.domain.source.registry import issue_identifier
from my_pa.infrastructure.persistence.reports import SqlGeneralReportRepository
from tests.database.test_reports_general_persistence import (
    PRINCIPAL_A,
    _counts,
    _publish,
    _publish_committed,
    _read,
    _request,
    _tamper,
    _tamper_manifest_and_digest,
)

pytestmark = pytest.mark.database

_CLOCK: dict[str, datetime] = {"now": datetime(2026, 11, 5, 12, 0, tzinfo=UTC)}

RAW: Final[dict[str, bytes]] = {
    "markdown": "# Gzipped synthetic\n\nZephyrine quokkas wander é ✓\n".encode(),
    "text": b"plain gzipped synthetic text\n",
    "json": b'{"visiblevalueword": [1, 2.5, null, true], "nested": {"k": "\\u00e9"}}',
    "mixed": b'{"body": "see data", "data": {"risk": 3, "items": [1, -0.0]}}',
}
IDENTITY: Final[dict[str, dict[str, Any]]] = {
    "markdown": {"format": "markdown", "body": RAW["markdown"].decode()},
    "text": {"format": "text", "body": RAW["text"].decode()},
    "json": {"format": "json", "data": json.loads(RAW["json"])},
    "mixed": {"format": "mixed", **json.loads(RAW["mixed"])},
}


def _gz(raw: bytes, level: int = 9) -> bytes:
    return gzip.compress(raw, compresslevel=level, mtime=0)


def _gzip_content(fmt: str, raw: bytes, level: int = 9) -> dict[str, Any]:
    return {
        "format": fmt,
        "encoding": "gzip+base64",
        "encoded": base64.b64encode(_gz(raw, level)).decode("ascii"),
    }


def _content_row(engine: Engine, content_id: str) -> Any:  # noqa: ANN401
    with engine.connect() as connection:
        return (
            connection.execute(
                text("SELECT * FROM knowledge.report_content_objects WHERE content_id = :c"),
                {"c": content_id},
            )
            .one()
            ._mapping
        )


def _version_row(engine: Engine, version_id: str) -> Any:  # noqa: ANN401
    with engine.connect() as connection:
        return (
            connection.execute(
                text("SELECT * FROM knowledge.report_versions WHERE version_id = :v"),
                {"v": version_id},
            )
            .one()
            ._mapping
        )


def _update(
    engine: Engine, report_id: str, expected: int, patch: ReportPatch, key: str
) -> UpdateResult:
    _CLOCK["now"] += timedelta(seconds=1)
    with engine.begin() as connection:
        return SqlGeneralReportRepository(connection).update(
            UpdateRequest(
                report_id=report_id,
                expected_version=expected,
                patch=patch,
                change_reason="Synthetic change.",
            ),
            principal_id=PRINCIPAL_A,
            creator=derive_creator(CreatorKind.LOCAL_PRINCIPAL, PRINCIPAL_A),
            idempotency_key=key,
            recorded_at=_CLOCK["now"],
            correlation_id=issue_identifier(IdKind.CORRELATION),
            audit_id=issue_identifier(IdKind.AUDIT),
        )


@pytest.mark.parametrize("fmt", sorted(RAW))
def test_gzip_publish_stores_the_exact_gzip_bytes_and_reads_them_back(
    migrated_engine: Engine, fmt: str
) -> None:
    caller = _gzip_content(fmt, RAW[fmt])
    original = _gz(RAW[fmt])
    request = _request(caller)
    plain = validate_content(IDENTITY[fmt])
    result = _publish_committed(migrated_engine, request, f"gzip-{fmt}")

    row = _content_row(migrated_engine, result.content_id)
    assert row["original_encoding"] == "gzip+base64"
    assert row["storage_kind"] == "inline"
    assert bytes(row["inline_original"]) == original
    assert row["original_sha256"] == hashlib.sha256(original).hexdigest()
    assert row["original_byte_count"] == len(original)
    assert row["decoded_sha256"] == plain.decoded_sha256
    assert row["decoded_byte_count"] == plain.decoded_byte_count
    assert row["canonical_sha256"] == plain.canonical_sha256

    stored = _read(migrated_engine, result.receipt.report_id)
    content = stored.content  # type: ignore[attr-defined]
    assert content.encoding is ContentEncoding.GZIP_BASE64
    assert content.original == original
    assert content.decoded == plain.decoded
    manifest_content = stored.manifest["content"]  # type: ignore[attr-defined]
    assert manifest_content["encoding"] == "gzip+base64"
    assert manifest_content["original_sha256"] == row["original_sha256"]
    assert manifest_content["original_byte_count"] == len(original)

    payload = _general_read_payload(stored, include_body=True, include_manifest=False)  # type: ignore[arg-type]
    assert payload["content"]["encoded"] == caller["encoded"]
    assert payload["content"]["original_sha256"] == row["original_sha256"]
    assert payload["content"]["original_byte_count"] == len(original)
    if fmt in ("markdown", "text"):
        assert payload["content"]["body"] == RAW[fmt].decode()
    else:
        assert payload["content"]["data"] == plain.data


def test_the_search_projection_is_the_decoded_text_never_base64_or_gzip(
    migrated_engine: Engine,
) -> None:
    caller = _gzip_content("markdown", RAW["markdown"])
    request = _request(caller, title="Plain title", summary=None, topics=(), tags=())
    result = _publish_committed(migrated_engine, request, "gzip-search")
    version_id = result.receipt.version_id
    stored = str(_version_row(migrated_engine, version_id)["search_text"])
    assert stored == extract_search_text(validate_content(IDENTITY["markdown"]))
    assert "Zephyrine quokkas" in stored
    assert caller["encoded"] not in stored
    assert caller["encoded"][:12] not in stored
    assert "H4sI" not in stored
    with migrated_engine.connect() as connection:
        hits = connection.execute(
            text(
                "SELECT search_document @@ plainto_tsquery('english', :q) "
                "FROM knowledge.report_versions WHERE version_id = :v"
            ),
            {"v": version_id, "q": "zephyrine quokka"},
        ).scalar_one()
        base64_hit = connection.execute(
            text(
                "SELECT search_document @@ plainto_tsquery('english', :q) "
                "FROM knowledge.report_versions WHERE version_id = :v"
            ),
            {"v": version_id, "q": caller["encoded"]},
        ).scalar_one()
    assert hits is True
    assert base64_hit is False


def test_update_with_gzip_content_then_metadata_only_keeps_the_pointer(
    migrated_engine: Engine,
) -> None:
    first = _publish_committed(migrated_engine, _request(IDENTITY["markdown"]), "gzip-upd-base")
    report_id = first.receipt.report_id
    new_raw = b"# Revised gzipped body\n\nNumbat words.\n"
    caller = _gzip_content("markdown", new_raw)
    second = _update(
        migrated_engine,
        report_id,
        1,
        ReportPatch(content=validate_content(caller)),
        "gzip-upd-1",
    )
    assert second.change_kind is ChangeKind.CONTENT
    assert second.content_id != first.content_id
    row = _content_row(migrated_engine, second.content_id)
    assert bytes(row["inline_original"]) == _gz(new_raw)
    third = _update(migrated_engine, report_id, 2, ReportPatch(title="New title"), "gzip-upd-2")
    assert third.change_kind is ChangeKind.METADATA
    assert third.content_id == second.content_id
    assert (
        _version_row(migrated_engine, third.version_id)["search_text"]
        == _version_row(migrated_engine, second.version_id)["search_text"]
    )
    stored = _read(migrated_engine, report_id)
    assert stored.version.version_number == 3  # type: ignore[attr-defined]
    assert stored.content.original == _gz(new_raw)  # type: ignore[attr-defined]
    payload = _general_read_payload(stored, include_body=True, include_manifest=False)  # type: ignore[arg-type]
    assert payload["content"]["encoded"] == caller["encoded"]


def test_a_gzip_replay_replays_and_another_stream_under_the_key_conflicts(
    migrated_engine: Engine,
) -> None:
    request = _request(_gzip_content("text", RAW["text"]))
    first = _publish_committed(migrated_engine, request, "gzip-key")
    again = _publish_committed(
        migrated_engine, _request(_gzip_content("text", RAW["text"])), "gzip-key"
    )
    assert again.replayed is True
    assert again.receipt == first.receipt
    before = _counts(migrated_engine)
    other = _request(_gzip_content("text", RAW["text"], level=1))
    assert other.content.decoded == request.content.decoded
    with pytest.raises(ReportIdempotencyConflictError):
        _publish_committed(migrated_engine, other, "gzip-key")
    assert _counts(migrated_engine) == before


def _words(size: int) -> bytes:
    rng = random.Random(7)  # noqa: S311 - deterministic synthetic text, not a secret
    vocabulary = [f"w{rng.getrandbits(32):08x} ".encode() for _ in range(4096)]
    out = bytearray()
    while len(out) < size:
        out += rng.choice(vocabulary)
    return bytes(out[:size])


def test_decoded_content_above_the_inline_maximum_writes_nothing(migrated_engine: Engine) -> None:
    raw = _words(INLINE_CONTENT_MAX_BYTES + 1)
    request = _request(_gzip_content("text", raw))
    before = _counts(migrated_engine)
    with migrated_engine.begin() as connection, pytest.raises(ReportValidationError) as refused:
        _publish(connection, request, "gzip-over")
    assert (refused.value.field, refused.value.code) == ("content", "too_large")
    assert _counts(migrated_engine) == before
    # Exactly at the maximum is inline.
    at = _publish_committed(migrated_engine, _request(_gzip_content("text", raw[:-1])), "gzip-at")
    assert _content_row(migrated_engine, at.content_id)["decoded_byte_count"] == len(raw) - 1


@pytest.mark.parametrize(
    ("statement", "constraint"),
    [
        (
            "UPDATE knowledge.report_content_objects SET inline_original = NULL "
            "WHERE content_id = :c",
            "encoded_inline_report_content_keeps_its_original",
        ),
        (
            "UPDATE knowledge.report_content_objects SET inline_original = "
            "decode(repeat('00', original_byte_count), 'hex') WHERE content_id = :c",
            "inline_report_content_keeps_its_original_digest",
        ),
    ],
)
def test_the_schema_refuses_a_gzip_row_without_its_exact_original(
    migrated_engine: Engine, statement: str, constraint: str
) -> None:
    result = _publish_committed(
        migrated_engine, _request(_gzip_content("text", RAW["text"])), "gzip-check"
    )
    with pytest.raises(IntegrityError) as refused:
        _tamper(migrated_engine, "report_content_objects", statement, {"c": result.content_id})
    assert constraint in str(refused.value.orig)


@pytest.mark.parametrize("forge_manifest", [False, True])
def test_a_read_refuses_an_original_that_no_longer_matches_its_digest(
    migrated_engine: Engine, forge_manifest: bool
) -> None:
    """Other gzip bytes of the same length under the stored `original_sha256`.

    The schema's digest CHECK is dropped in this clone, so the size CHECK and
    every decoded digest still agree. Without `forge_manifest` the rebuilt
    manifest (it names the digest of the bytes read) also disagrees, a second
    guard; with it the manifest and both its digests are rewritten to name the
    forged bytes, so the reader's own `sha256(inline_original) ==
    original_sha256` comparison is the only guard left.
    """
    result = _publish_committed(
        migrated_engine,
        _request(_gzip_content("text", RAW["text"])),
        f"gzip-tamper-{forge_manifest}",
    )
    stored = _read(migrated_engine, result.receipt.report_id)
    assert stored is not None
    with migrated_engine.begin() as connection:
        connection.execute(
            text(
                "ALTER TABLE knowledge.report_content_objects DROP CONSTRAINT "
                "inline_report_content_keeps_its_original_digest"
            )
        )
    forged = bytearray(_gz(RAW["text"]))
    forged[4] = 0x01  # MTIME: still a valid member of the same text and length
    _tamper(
        migrated_engine,
        "report_content_objects",
        "UPDATE knowledge.report_content_objects SET inline_original = :o WHERE content_id = :c",
        {"o": bytes(forged), "c": result.content_id},  # type: ignore[dict-item]
    )
    if forge_manifest:
        manifest = dict(stored.manifest)  # type: ignore[attr-defined]
        manifest["content"] = {
            **manifest["content"],
            "original_sha256": hashlib.sha256(bytes(forged)).hexdigest(),
        }
        _tamper_manifest_and_digest(
            migrated_engine, result.receipt.version_id, manifest, manifest_digest(manifest)
        )
    with pytest.raises(ReportIntegrityError):
        _read(migrated_engine, result.receipt.report_id)
