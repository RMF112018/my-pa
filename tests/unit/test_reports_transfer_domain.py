"""Reports Modernization WP06 B1/B2: the pure transfer rules and the one content pipeline.

What it proves, without a database or a file:

* the chunk arithmetic (T2): 1 byte is 1 chunk, 262,144 is 1, 262,145 is 2,
  16 MiB is exactly 64; every chunk but the last is exactly 262,144 bytes;
* `TransferDeclaration` (T3) bounds and its `intent_digest` (TTL included);
* the client binding (T4) matches the schema's frozen pattern;
* the content token (T9): minted `grxtk_` + 64 hex, its digest the stored
  form, and every malformed presentation answered `None`, never raised;
* the transfer reference shape (T10): exactly one key, exactly two inner keys;
* `content_from_staged` (T11) gives the inline pipeline's exact content for
  the same text, and refuses every hostile shape on the field `transfer`
  with the inline rule code.

Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
import re
import zlib
from pathlib import Path
from typing import Any, Final

import pytest

from my_pa.domain.identity.secret_digests import digest_bytes, digests_match
from my_pa.domain.reports import content as content_module
from my_pa.domain.reports.content import (
    INLINE_CONTENT_MAX_BYTES,
    content_from_staged,
    validate_content,
)
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.encoding import decode_gzip_base64, decode_gzip_bytes
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.transfer import (
    CLIENT_REF_PATTERN,
    CONTENT_TOKEN_PATTERN,
    MAX_TRANSFER_BYTE_COUNT,
    MAX_TRANSFER_CHUNKS,
    TRANSFER_CHUNK_BYTES,
    TRANSFER_DECLARED_BYTES_PER_OWNER,
    TRANSFER_SESSIONS_PER_CLIENT,
    TRANSFER_SESSIONS_PER_OWNER,
    TRANSFER_TTL_DEFAULT_SECONDS,
    TRANSFER_TTL_MAX_SECONDS,
    TRANSFER_TTL_MIN_SECONDS,
    TransferDeclaration,
    TransferReference,
    chunk_count,
    chunk_offset,
    client_ref_of,
    content_token_digest,
    expected_chunk_size,
    mint_content_token,
    parse_transfer_reference,
)
from my_pa.domain.reports.vocabulary import (
    MAX_CONTENT_DATA_VALUES,
    TRANSFER_CHUNK_MAX_BYTES,
    ContentEncoding,
    ContentFormat,
)

_SHA: Final = "a" * 64
_SESSION: Final = "grxfr_" + "0123456789abcdef" * 2
_TOKEN: Final = "grxtk_" + "0f" * 32
MIB_16: Final = 16 * 1024 * 1024


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _gz(data: bytes) -> bytes:
    return gzip.compress(data, mtime=0)


# ---- constants and chunk arithmetic -------------------------------------------------


def test_the_constants_are_the_contract_values() -> None:
    assert TRANSFER_CHUNK_BYTES == TRANSFER_CHUNK_MAX_BYTES == 262144
    assert MAX_TRANSFER_CHUNKS == 64
    assert MAX_TRANSFER_BYTE_COUNT == MIB_16 == MAX_TRANSFER_CHUNKS * TRANSFER_CHUNK_BYTES
    assert (TRANSFER_TTL_MIN_SECONDS, TRANSFER_TTL_DEFAULT_SECONDS, TRANSFER_TTL_MAX_SECONDS) == (
        300,
        3600,
        86400,
    )
    assert TRANSFER_SESSIONS_PER_CLIENT == 4
    assert TRANSFER_SESSIONS_PER_OWNER == 8
    assert TRANSFER_DECLARED_BYTES_PER_OWNER == 67_108_864 == 4 * MIB_16


@pytest.mark.parametrize(
    ("byte_count", "count"),
    [(1, 1), (262143, 1), (262144, 1), (262145, 2), (524288, 2), (524289, 3), (MIB_16, 64)],
)
def test_chunk_count(byte_count: int, count: int) -> None:
    assert chunk_count(byte_count) == count


def test_every_chunk_but_the_last_is_exactly_the_chunk_size() -> None:
    for byte_count in (1, 262144, 262145, 1_000_000, MIB_16 - 1, MIB_16):
        count = chunk_count(byte_count)
        sizes = [expected_chunk_size(byte_count, sequence) for sequence in range(count)]
        assert sum(sizes) == byte_count
        assert all(size == TRANSFER_CHUNK_BYTES for size in sizes[:-1])
        assert 1 <= sizes[-1] <= TRANSFER_CHUNK_BYTES
        assert [chunk_offset(sequence) for sequence in range(count)] == [
            sequence * 262144 for sequence in range(count)
        ]
        with pytest.raises(ReportValidationError) as raised:
            expected_chunk_size(byte_count, count)
        assert (raised.value.field, raised.value.code) == ("sequence", "bounds")
    assert expected_chunk_size(MIB_16, 63) == TRANSFER_CHUNK_BYTES
    assert expected_chunk_size(262145, 1) == 1


@pytest.mark.parametrize(
    ("call", "field", "code"),
    [
        (lambda: chunk_count(0), "byte_count", "bounds"),
        (lambda: chunk_count(MIB_16 + 1), "byte_count", "bounds"),
        (lambda: chunk_count(True), "byte_count", "type"),
        (lambda: chunk_count(1.0), "byte_count", "type"),
        (lambda: chunk_offset(-1), "sequence", "bounds"),
        (lambda: chunk_offset(64), "sequence", "bounds"),
        (lambda: chunk_offset(False), "sequence", "type"),
        (lambda: expected_chunk_size(10, -1), "sequence", "bounds"),
    ],
)
def test_chunk_arithmetic_refusals(call: Any, field: str, code: str) -> None:  # noqa: ANN401
    with pytest.raises(ReportValidationError) as raised:
        call()
    assert (raised.value.field, raised.value.code) == (field, code)


# ---- declaration ----------------------------------------------------------------------


def test_a_declaration_accepts_the_bounds_and_coerces_its_enumerations() -> None:
    low = TransferDeclaration("markdown", "identity", 1, _SHA, 300)
    assert low.format is ContentFormat.MARKDOWN and low.encoding is ContentEncoding.IDENTITY
    high = TransferDeclaration(ContentFormat.JSON, ContentEncoding.GZIP_BASE64, MIB_16, _SHA, 86400)
    assert high.chunk_count == 64
    assert TransferDeclaration("text", "identity", 5, _SHA).ttl_seconds == 3600


@pytest.mark.parametrize(
    ("arguments", "field", "code"),
    [
        (("pdf", "identity", 1, _SHA, 3600), "format", "unknown"),
        ((1, "identity", 1, _SHA, 3600), "format", "type"),
        (("text", "gzip", 1, _SHA, 3600), "encoding", "unknown"),
        (("text", None, 1, _SHA, 3600), "encoding", "type"),
        (("text", "identity", 0, _SHA, 3600), "byte_count", "bounds"),
        (("text", "identity", MIB_16 + 1, _SHA, 3600), "byte_count", "bounds"),
        (("text", "identity", True, _SHA, 3600), "byte_count", "type"),
        (("text", "identity", "5", _SHA, 3600), "byte_count", "type"),
        (("text", "identity", 1, "A" * 64, 3600), "sha256", "pattern"),
        (("text", "identity", 1, "a" * 63, 3600), "sha256", "pattern"),
        (("text", "identity", 1, b"a" * 64, 3600), "sha256", "type"),
        (("text", "identity", 1, _SHA, 299), "ttl_seconds", "bounds"),
        (("text", "identity", 1, _SHA, 86401), "ttl_seconds", "bounds"),
        (("text", "identity", 1, _SHA, 3600.0), "ttl_seconds", "type"),
        (("text", "identity", 1, _SHA, True), "ttl_seconds", "type"),
    ],
)
def test_a_declaration_refuses_out_of_bounds_fields(
    arguments: tuple[Any, ...], field: str, code: str
) -> None:
    with pytest.raises(ReportValidationError) as raised:
        TransferDeclaration(*arguments)
    assert (raised.value.field, raised.value.code) == (field, code)
    assert str(raised.value) == f"{field}: {code}"


def test_the_intent_digest_binds_every_field_including_the_ttl() -> None:
    base = TransferDeclaration("text", "identity", 10, _SHA, 3600)
    assert base.intent_digest == TransferDeclaration("text", "identity", 10, _SHA).intent_digest
    canonical = json.dumps(
        {
            "byte_count": 10,
            "encoding": "identity",
            "format": "text",
            "sha256": _SHA,
            "ttl_seconds": 3600,
        },
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    assert base.intent_digest == _sha(canonical)
    others = [
        TransferDeclaration("markdown", "identity", 10, _SHA, 3600),
        TransferDeclaration("text", "gzip+base64", 10, _SHA, 3600),
        TransferDeclaration("text", "identity", 11, _SHA, 3600),
        TransferDeclaration("text", "identity", 10, "b" * 64, 3600),
        TransferDeclaration("text", "identity", 10, _SHA, 3601),
    ]
    assert len({base.intent_digest, *(other.intent_digest for other in others)}) == 6


# ---- client binding ---------------------------------------------------------------------


def test_the_client_ref_is_kind_and_creator_id_and_matches_the_schema_pattern() -> None:
    migration = (
        Path(__file__).parents[2]
        / "migrations/versions/20261104_4c37731671fc_general_report_plane.py"
    ).read_text()
    # The schema restates the pattern with the colon escaped for SQLAlchemy's
    # bind parsing (`\\:` in the migration's source text).
    escaped = CLIENT_REF_PATTERN.replace(":", "\\\\:")
    assert f"'{escaped}'" in migration
    pattern = re.compile(CLIENT_REF_PATTERN)
    for kind in CreatorKind:
        creator = derive_creator(kind, "synthetic-subject")
        ref = client_ref_of(creator)
        assert ref == f"{kind.value}:{creator.creator_id}"
        assert pattern.match(ref)
    remote = client_ref_of(derive_creator(CreatorKind.REMOTE_CLIENT, "client-a"))
    local = client_ref_of(derive_creator(CreatorKind.LOCAL_PRINCIPAL, "client-a"))
    assert remote != local
    with pytest.raises(ReportValidationError):
        client_ref_of("remote_client:gcrt_" + "0" * 40)  # type: ignore[arg-type]


# ---- content token ----------------------------------------------------------------------


def test_a_minted_token_has_the_shape_and_its_digest_is_the_stored_form() -> None:
    presented, digest = mint_content_token()
    assert re.fullmatch(CONTENT_TOKEN_PATTERN, presented)
    assert content_token_digest(presented) == digest
    assert digests_match(content_token_digest(presented) or "", digest)
    assert digest == digest_bytes(bytes.fromhex(presented.removeprefix("grxtk_")))
    again, other = mint_content_token()
    assert again != presented and other != digest


@pytest.mark.parametrize(
    "presented",
    [
        None,
        42,
        b"grxtk_" + b"0" * 64,
        "",
        "grxtk_",
        "grxtk_" + "0" * 63,
        "grxtk_" + "0" * 65,
        "grxtk_" + "A" * 64,
        "GRXTK_" + "0" * 64,
        "grxfr_" + "0" * 64,
        " grxtk_" + "0" * 64,
        "grxtk_" + "0" * 64 + "\n",
        "grxtk_" + "g" * 64,
        "0" * 64,
    ],
)
def test_a_malformed_token_has_no_digest_and_never_raises(presented: object) -> None:
    assert content_token_digest(presented) is None


# ---- transfer reference -----------------------------------------------------------------


def test_a_well_formed_reference_parses_and_hides_its_token() -> None:
    reference = parse_transfer_reference(
        {"transfer": {"session_id": _SESSION, "content_token": _TOKEN}}
    )
    assert reference == TransferReference(_SESSION, _TOKEN)
    assert _TOKEN not in repr(reference)


@pytest.mark.parametrize(
    "value",
    [
        None,
        "transfer",
        ["transfer"],
        {},
        {"format": "markdown", "body": "inline"},
        {"format": "json", "data": {"transfer": {}}},
    ],
)
def test_anything_without_a_transfer_key_is_not_a_reference(value: object) -> None:
    assert parse_transfer_reference(value) is None


@pytest.mark.parametrize(
    ("value", "field", "code"),
    [
        (
            {"transfer": {"session_id": _SESSION, "content_token": _TOKEN}, "format": "text"},
            "transfer",
            "unknown_field",
        ),
        (
            {
                "transfer": {"session_id": _SESSION, "content_token": _TOKEN},
                "encoding": "identity",
            },
            "transfer",
            "unknown_field",
        ),
        (
            {"transfer": {"session_id": _SESSION, "content_token": _TOKEN, "format": "text"}},
            "transfer",
            "unknown_field",
        ),
        (
            {"transfer": {"session_id": _SESSION, "content_token": _TOKEN, "encoding": "gzip"}},
            "transfer",
            "unknown_field",
        ),
        (
            {"transfer": {"session_id": _SESSION, "content_token": _TOKEN, 1: "x"}},
            "transfer",
            "unknown_field",
        ),
        ({"transfer": [_SESSION, _TOKEN]}, "transfer", "type"),
        ({"transfer": None}, "transfer", "type"),
        ({"transfer": {"content_token": _TOKEN}}, "transfer.session_id", "required"),
        ({"transfer": {"session_id": _SESSION}}, "transfer.content_token", "required"),
        (
            {"transfer": {"session_id": 7, "content_token": _TOKEN}},
            "transfer.session_id",
            "type",
        ),
        (
            {"transfer": {"session_id": "grcnt_" + "0" * 32, "content_token": _TOKEN}},
            "transfer.session_id",
            "pattern",
        ),
        (
            {"transfer": {"session_id": "grxfr_../../x", "content_token": _TOKEN}},
            "transfer.session_id",
            "pattern",
        ),
        (
            {"transfer": {"session_id": _SESSION, "content_token": "grxtk_" + "0" * 63}},
            "transfer.content_token",
            "pattern",
        ),
        (
            {"transfer": {"session_id": _SESSION, "content_token": None}},
            "transfer.content_token",
            "type",
        ),
    ],
)
def test_every_unknown_key_or_malformed_value_is_refused(
    value: object, field: str, code: str
) -> None:
    with pytest.raises(ReportValidationError) as raised:
        parse_transfer_reference(value)
    assert (raised.value.field, raised.value.code) == (field, code)
    assert _TOKEN not in str(raised.value)


# ---- the one content pipeline (T11) -----------------------------------------------------

_MAX: Final = 16 * 1024 * 1024


def _inline_gzip(content_format: str, raw: bytes) -> dict[str, Any]:
    return {
        "format": content_format,
        "encoding": "gzip+base64",
        "encoded": base64.b64encode(_gz(raw)).decode(),
    }


_TEXTS: Final = [
    ("markdown", "# Synthetic\n\nA body with ünïcode.\n".encode()),
    ("text", b"plain synthetic text"),
    ("json", b'{ "b": [1, 2.5, "x"],  "a": {"nested": true} }'),
    ("mixed", b'{"data": {"k": [1, 2]}, "body": "Synthetic mixed body"}'),
]


@pytest.mark.parametrize(("content_format", "raw"), _TEXTS)
def test_staged_gzip_is_exactly_inline_gzip(content_format: str, raw: bytes) -> None:
    gz = _gz(raw)
    inline = validate_content(_inline_gzip(content_format, raw), max_decoded=_MAX)
    staged = content_from_staged(
        ContentFormat(content_format), ContentEncoding.GZIP_BASE64, gz, max_decoded=_MAX
    )
    assert staged == inline
    assert staged.original == gz and staged.original_sha256 == _sha(gz)
    assert staged.encoding is ContentEncoding.GZIP_BASE64


@pytest.mark.parametrize(("content_format", "raw"), _TEXTS)
def test_staged_identity_is_the_text_canonicalized_like_inline(
    content_format: str, raw: bytes
) -> None:
    staged = content_from_staged(
        ContentFormat(content_format), ContentEncoding.IDENTITY, raw, max_decoded=_MAX
    )
    gzipped = content_from_staged(
        ContentFormat(content_format), ContentEncoding.GZIP_BASE64, _gz(raw), max_decoded=_MAX
    )
    assert staged.original is None and staged.encoding is ContentEncoding.IDENTITY
    assert staged.original_sha256 == staged.decoded_sha256 == gzipped.decoded_sha256
    assert staged.decoded == gzipped.decoded
    # The same as inline identity content built from the parsed parts.
    if content_format in ("markdown", "text"):
        inline = validate_content({"format": content_format, "body": raw.decode()})
        assert staged.decoded == raw
    elif content_format == "json":
        inline = validate_content({"format": "json", "data": json.loads(raw)})
        assert staged.decoded != raw  # canonicalized; the declared digest names `raw`
    else:
        inline = validate_content({"format": "mixed", **json.loads(raw)})
    assert staged == inline


def test_staged_identity_beyond_the_inline_bound_is_accepted_up_to_max_decoded() -> None:
    raw = b"x" * (INLINE_CONTENT_MAX_BYTES + 1)
    staged = content_from_staged(
        ContentFormat.TEXT, ContentEncoding.IDENTITY, raw, max_decoded=_MAX
    )
    assert staged.decoded_byte_count == len(raw)
    with pytest.raises(ReportValidationError) as raised:
        content_from_staged(
            ContentFormat.TEXT, ContentEncoding.IDENTITY, raw, max_decoded=len(raw) - 1
        )
    assert (raised.value.field, raised.value.code) == ("transfer", "too_large")


def _bomb() -> bytes:
    return _gz(b"0" * (2 * 1024 * 1024))


def _two_members() -> bytes:
    return _gz(b"first") + _gz(b"second")


def _nested() -> bytes:
    return _gz(_gz(b"inner synthetic text"))


def _corrupt_crc() -> bytes:
    data = bytearray(_gz(b"synthetic text body"))
    data[-8] ^= 0xFF
    return bytes(data)


def _deep_json() -> bytes:
    return b"[" * 40 + b"0" + b"]" * 40


def _many_random_values() -> bytes:
    """Above the value cap, varied enough that its gzip stays under the ratio bound."""
    generator = random.Random(6)  # noqa: S311 - synthetic data
    numbers = ",".join(str(generator.randrange(10**6)) for _ in range(MAX_CONTENT_DATA_VALUES + 1))
    return f"[{numbers}]".encode()


def _many_values() -> bytes:
    return b"[" + b"0," * MAX_CONTENT_DATA_VALUES + b"0]"


@pytest.mark.parametrize(
    ("content_format", "encoding", "staged", "max_decoded", "code"),
    [
        ("text", "gzip+base64", _bomb(), 100_000, "too_large"),
        ("text", "gzip+base64", _bomb(), _MAX, "expansion_ratio"),
        ("text", "gzip+base64", _nested(), _MAX, "nested_stream"),
        ("text", "gzip+base64", _two_members(), _MAX, "trailing_data"),
        ("text", "gzip+base64", _gz(b"synthetic") + b"\x00", _MAX, "trailing_data"),
        ("text", "gzip+base64", _gz(b"synthetic text body")[:-6], _MAX, "truncated"),
        ("text", "gzip+base64", _corrupt_crc(), _MAX, "malformed_gzip"),
        ("text", "gzip+base64", b"not gzip at all", _MAX, "malformed_gzip"),
        ("text", "gzip+base64", zlib.compress(b"zlib, not gzip"), _MAX, "malformed_gzip"),
        ("text", "gzip+base64", _gz(b"\xff\xfe bad"), _MAX, "malformed_utf8"),
        ("text", "identity", b"\xff\xfe bad", _MAX, "malformed_utf8"),
        ("text", "identity", b"   \n", _MAX, "blank"),
        ("text", "identity", b"nul\x00inside", _MAX, "malformed"),
        ("json", "identity", _deep_json(), _MAX, "too_deep"),
        ("json", "gzip+base64", _gz(_deep_json()), _MAX, "too_deep"),
        ("json", "identity", _many_values(), _MAX, "too_many_values"),
        ("json", "gzip+base64", _gz(_many_random_values()), _MAX, "too_many_values"),
        ("json", "identity", b'{"a": 1, "a": 2}', _MAX, "duplicate_key"),
        ("json", "gzip+base64", _gz(b'{"a": 1, "a": 2}'), _MAX, "duplicate_key"),
        ("json", "identity", b'{"a": NaN}', _MAX, "malformed_json"),
        ("json", "identity", b"{not json", _MAX, "malformed_json"),
        ("json", "identity", b"null", _MAX, "null"),
        ("json", "identity", b"{}", _MAX, "empty"),
        ("mixed", "identity", b'{"body": "b"}', _MAX, "mixed_shape"),
        ("mixed", "identity", b'{"body": "b", "data": 1, "x": 2}', _MAX, "mixed_shape"),
        ("mixed", "gzip+base64", _gz(b"[1, 2]"), _MAX, "mixed_shape"),
        ("text", "identity", b"x" * 11, 10, "too_large"),
    ],
    ids=lambda value: value if isinstance(value, str) else type(value).__name__,
)
def test_every_hostile_staged_shape_is_refused_on_transfer(
    content_format: str, encoding: str, staged: bytes, max_decoded: int, code: str
) -> None:
    with pytest.raises(ReportValidationError) as raised:
        content_from_staged(
            ContentFormat(content_format),
            ContentEncoding(encoding),
            staged,
            max_decoded=max_decoded,
        )
    assert (raised.value.field, raised.value.code) == ("transfer", code)
    assert str(raised.value) == f"transfer: {code}"


@pytest.mark.parametrize(
    "staged",
    [_bomb(), _nested(), _two_members(), _corrupt_crc(), _gz(b"\xff bad"), _gz(_deep_json())],
    ids=["bomb", "nested", "two_members", "corrupt_crc", "utf8", "deep_json"],
)
def test_staged_gzip_refuses_with_the_inline_rule_code(staged: bytes) -> None:
    content_format = "json" if staged == _gz(_deep_json()) else "text"
    with pytest.raises(ReportValidationError) as inline:
        validate_content(
            {
                "format": content_format,
                "encoding": "gzip+base64",
                "encoded": base64.b64encode(staged).decode(),
            },
            max_decoded=_MAX,
        )
    with pytest.raises(ReportValidationError) as transfer:
        content_from_staged(
            ContentFormat(content_format), ContentEncoding.GZIP_BASE64, staged, max_decoded=_MAX
        )
    assert inline.value.field == "content.encoded"
    assert transfer.value.field == "transfer"
    assert transfer.value.code == inline.value.code


def test_unknown_format_encoding_or_a_non_bytes_value_is_refused() -> None:
    for arguments in (("pdf", "identity", b"x"), ("text", "zip", b"x"), ("text", "identity", "x")):
        with pytest.raises(ReportValidationError) as raised:
            content_from_staged(*arguments, max_decoded=_MAX)
        assert raised.value.field == "transfer"


def test_decode_gzip_base64_is_step_one_then_decode_gzip_bytes() -> None:
    raw = b"synthetic gunzipped text"
    gz = _gz(raw)
    assert decode_gzip_base64(base64.b64encode(gz).decode()) == (gz, raw)
    assert decode_gzip_bytes(gz) == raw
    assert decode_gzip_bytes(gz, original_byte_count=len(gz), uncompressed_sha256=_sha(raw)) == raw
    for kwargs, code in (
        ({"original_byte_count": len(gz) + 1}, "original_size_mismatch"),
        ({"original_sha256": "0" * 64}, "original_digest_mismatch"),
        ({"uncompressed_byte_count": 1}, "uncompressed_size_mismatch"),
        ({"uncompressed_sha256": "0" * 64}, "uncompressed_digest_mismatch"),
    ):
        with pytest.raises(ReportValidationError) as raised:
            decode_gzip_bytes(gz, **kwargs)
        assert (raised.value.field, raised.value.code) == ("content.encoded", code)
    # The magic is checked before a declared size: the inline order is kept.
    with pytest.raises(ReportValidationError) as raised:
        decode_gzip_bytes(b"plain", original_byte_count=1)
    assert raised.value.code == "malformed_gzip"


def test_inline_gzip_and_staged_share_one_post_gunzip_stage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []
    stage = vars(content_module)["_decoded_stage"]

    def observed(*args: Any, **kwargs: Any) -> Any:  # noqa: ANN401
        calls.append("stage")
        return stage(*args, **kwargs)

    monkeypatch.setattr(content_module, "_decoded_stage", observed)
    validate_content(_inline_gzip("text", b"synthetic"), max_decoded=_MAX)
    content_from_staged(
        ContentFormat.TEXT, ContentEncoding.GZIP_BASE64, _gz(b"s"), max_decoded=_MAX
    )
    content_from_staged(ContentFormat.TEXT, ContentEncoding.IDENTITY, b"s", max_decoded=_MAX)
    assert calls == ["stage", "stage", "stage"]
