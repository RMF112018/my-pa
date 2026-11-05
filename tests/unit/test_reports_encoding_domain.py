"""Reports Modernization WP05 B1/B2: the `gzip+base64` content decoder.

Pure domain: `validate_content` dispatching to `domain.reports.encoding`.
Every rule token has a minimal crafted input, and two tests count what the
inflater actually produced to prove decoding stops within one piece of a
bound. Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
import zlib
from typing import Any, Final

import pytest

from my_pa.domain.reports import encoding
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES, validate_content
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.publication import content_payload
from my_pa.domain.reports.vocabulary import (
    DECODE_CHUNK_BYTES,
    MAX_DECODED_CONTENT_BYTES,
    MAX_EXPANSION_RATIO,
    READ_INLINE_CONTENT_MAX_BYTES,
    ContentEncoding,
)

GZIP: Final = "gzip+base64"
_ALPHABET: Final = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789+/"


def _gz(raw: bytes, level: int = 9) -> bytes:
    return gzip.compress(raw, compresslevel=level, mtime=0)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _content(fmt: str, raw: bytes, **extra: object) -> dict[str, Any]:
    return {"format": fmt, "encoding": GZIP, "encoded": _b64(_gz(raw)), **extra}


def _encoded(fmt: str, encoded: object) -> dict[str, Any]:
    return {"format": fmt, "encoding": GZIP, "encoded": encoded}


def _refused(value: object) -> tuple[str, str]:
    with pytest.raises(ReportValidationError) as caught:
        validate_content(value)
    return caught.value.field, caught.value.code


def _words(size: int, seed: int = 0) -> bytes:
    """`size` bytes of text that compresses well under the 256:1 ratio."""
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    vocabulary = [f"w{rng.getrandbits(32):08x} ".encode() for _ in range(4096)]
    out = bytearray()
    while len(out) < size:
        out += rng.choice(vocabulary)
    return bytes(out[:size])


def test_the_constants_are_frozen() -> None:
    assert MAX_EXPANSION_RATIO == 256
    assert DECODE_CHUNK_BYTES == 65536
    assert READ_INLINE_CONTENT_MAX_BYTES == 524288
    assert MAX_DECODED_CONTENT_BYTES == 16_777_216


# ---- happy paths ---------------------------------------------------------------


@pytest.mark.parametrize(
    ("fmt", "raw", "identity"),
    [
        (
            "markdown",
            "# Synthetic é ✓\n".encode(),
            {"format": "markdown", "body": "# Synthetic é ✓\n"},
        ),
        ("text", b"plain synthetic text\n", {"format": "text", "body": "plain synthetic text\n"}),
        (
            "json",
            b'{ "b": [1, 2.5, null, true],\n  "a": {"x": "\\u00e9"} }',
            {"format": "json", "data": {"b": [1, 2.5, None, True], "a": {"x": "é"}}},
        ),
        (
            "mixed",
            b'{"data": [1, {"k": "v"}], "body": "see data"}',
            {"format": "mixed", "body": "see data", "data": [1, {"k": "v"}]},
        ),
    ],
)
def test_each_format_decodes_to_the_identity_content(
    fmt: str, raw: bytes, identity: dict[str, Any]
) -> None:
    original = _gz(raw)
    content = validate_content(
        {
            "format": fmt,
            "encoding": GZIP,
            "encoded": _b64(original),
            "original_byte_count": len(original),
            "original_sha256": _sha(original),
            "uncompressed_byte_count": len(raw),
            "uncompressed_sha256": _sha(raw),
        }
    )
    plain = validate_content(identity)
    assert content.encoding is ContentEncoding.GZIP_BASE64
    assert content.original == original
    assert content.original_sha256 == _sha(original)
    assert content.original_byte_count == len(original)
    # The decoded bytes and digests are the identity content's exactly.
    assert content.decoded == plain.decoded
    assert content.decoded_sha256 == plain.decoded_sha256
    assert content.canonical_sha256 == plain.canonical_sha256
    assert (content.body, content.data) == (plain.body, plain.data)
    # The original never appears in a repr; the identity original is the decoded.
    assert _b64(original) not in repr(content)
    assert "original=" not in repr(content)
    assert plain.original is None
    assert plain.original_sha256 == plain.decoded_sha256
    assert plain.original_byte_count == plain.decoded_byte_count


def test_the_intent_payload_names_the_gzip_bytes_and_identity_is_unchanged() -> None:
    raw = b"# same text\n"
    first = validate_content(_content("markdown", raw))
    other = validate_content(
        {"format": "markdown", "encoding": GZIP, "encoded": _b64(_gz(raw, level=1))}
    )
    plain = validate_content({"format": "markdown", "body": raw.decode()})
    assert content_payload(plain) == {
        "format": "markdown",
        "encoding": "identity",
        "body": raw.decode(),
    }
    assert content_payload(first)["original_sha256"] == first.original_sha256
    # Same decoded content, other gzip bytes (the header's XFL differs): another intent.
    assert first.decoded == other.decoded
    assert first.original != other.original
    assert content_payload(first) != content_payload(other)


def test_depth_32_is_accepted_and_mixed_data_gets_the_same_depth() -> None:
    deep = b"[" * 32 + b"1" + b"]" * 32
    assert validate_content(_content("json", deep)).data is not None
    mixed = b'{"body": "b", "data": ' + deep + b"}"
    assert validate_content(_content("mixed", mixed)).body == "b"


def test_the_inline_maximum_is_not_the_gzip_domain_bound() -> None:
    # Placement (inline or refused) is the repository's; the domain bound is 16 MiB.
    raw = _words(INLINE_CONTENT_MAX_BYTES + 1)
    assert validate_content(_content("text", raw)).decoded_byte_count == len(raw)


# ---- refusals: one minimal input per rule -----------------------------------


def _valid_original() -> bytes:
    """A gzip member whose length leaves Base64 padding (len % 3 == 1)."""
    for size in range(1, 64):
        original = _gz(b"x" * size)
        if len(original) % 3 == 1:
            return original
    raise AssertionError("unreachable")


def test_malformed_base64() -> None:
    original = _valid_original()
    good = _b64(original)
    assert good.endswith("==")
    for bad in (
        "",
        123,
        None,
        good[:8] + "\n" + good[8:-1],  # whitespace (length kept a multiple of 4)
        good[:4] + " " + good[5:],
        good + "\n",
        good.replace("=", ""),  # missing padding
        good + "====",  # extra padding
        good[:-2] + "=A",  # data after padding
        "H4sI-_8A",  # URL-safe alphabet
        "H4sI" + "AAA",  # length not a multiple of 4
        "é" * 4,
    ):
        assert _refused(_encoded("markdown", bad)) == ("content.encoded", "malformed_base64"), bad


def test_non_canonical_pad_bits_are_malformed_base64() -> None:
    good = _b64(_valid_original())
    # The character before "==" carries 2 data bits and 4 pad bits; set one pad bit.
    last = _ALPHABET.index(good[-3])
    forged = good[:-3] + _ALPHABET[last | 1] + "=="
    assert forged != good
    assert base64.b64decode(forged) == base64.b64decode(good)  # lenient decoders agree
    assert _refused(_encoded("markdown", forged)) == ("content.encoded", "malformed_base64")


def test_an_encoded_string_too_long_for_any_original_is_too_large() -> None:
    assert _refused(_encoded("markdown", "AAAA" * (6 * 1024 * 1024))) == (
        "content.encoded",
        "too_large",
    )


@pytest.mark.parametrize(
    "original",
    [
        b"plain text, not gzip",
        zlib.compress(b"zlib, not gzip"),
        b"\x1f\x8b\x07" + _gz(b"x")[3:],  # gzip magic, not deflate
    ],
)
def test_not_gzip_is_malformed_gzip(original: bytes) -> None:
    assert _refused(_encoded("markdown", _b64(original))) == ("content.encoded", "malformed_gzip")


def test_corrupted_deflate_and_bad_crc_are_malformed_gzip() -> None:
    original = bytearray(_gz(b"synthetic body text\n"))
    corrupt = bytearray(original)
    corrupt[10] = 0xFF  # BTYPE 11: a reserved deflate block type
    assert _refused(_encoded("text", _b64(bytes(corrupt)))) == ("content.encoded", "malformed_gzip")
    bad_crc = bytearray(original)
    bad_crc[-8] ^= 0x01
    assert _refused(_encoded("text", _b64(bytes(bad_crc)))) == ("content.encoded", "malformed_gzip")
    bad_size = bytearray(original)
    bad_size[-1] ^= 0x01
    assert _refused(_encoded("text", _b64(bytes(bad_size)))) == (
        "content.encoded",
        "malformed_gzip",
    )


@pytest.mark.parametrize("cut", [1, 4, 8, 12])
def test_a_truncated_member_is_truncated(cut: int) -> None:
    original = _gz(b"synthetic body text that is long enough\n" * 4)
    assert _refused(_encoded("text", _b64(original[:-cut]))) == ("content.encoded", "truncated")


def test_a_trailing_byte_is_trailing_data() -> None:
    original = _gz(b"synthetic body\n")
    for extra in (b"\x00", b"x"):
        assert _refused(_encoded("text", _b64(original + extra))) == (
            "content.encoded",
            "trailing_data",
        )


def test_two_concatenated_members_are_trailing_data() -> None:
    both = _gz(b"first member\n") + _gz(b"second member\n")
    assert gzip.decompress(both) == b"first member\nsecond member\n"  # gzip itself joins them
    assert _refused(_encoded("text", _b64(both))) == ("content.encoded", "trailing_data")


def test_trailing_data_beyond_the_first_input_slice_is_trailing_data() -> None:
    original = _gz(b"tiny\n") + b"\x00" * (DECODE_CHUNK_BYTES * 2)
    assert _refused(_encoded("text", _b64(original))) == ("content.encoded", "trailing_data")


def test_a_nested_gzip_stream_is_nested_stream() -> None:
    assert _refused(_content("text", _gz(b"inner\n"))) == ("content.encoded", "nested_stream")


@pytest.mark.parametrize(
    ("declared", "code"),
    [
        ({"original_byte_count": 1}, "original_size_mismatch"),
        ({"original_sha256": "0" * 64}, "original_digest_mismatch"),
        ({"uncompressed_byte_count": 1}, "uncompressed_size_mismatch"),
        ({"uncompressed_sha256": "0" * 64}, "uncompressed_digest_mismatch"),
    ],
)
def test_a_declared_fact_that_disagrees_is_a_mismatch(declared: dict[str, Any], code: str) -> None:
    assert _refused(_content("text", b"synthetic text\n", **declared)) == ("content.encoded", code)


@pytest.mark.parametrize(
    ("declared", "field", "code"),
    [
        ({"original_byte_count": True}, "content.original_byte_count", "type"),
        ({"original_byte_count": 1.0}, "content.original_byte_count", "type"),
        ({"original_byte_count": -1}, "content.original_byte_count", "bounds"),
        ({"uncompressed_byte_count": 16_777_217}, "content.uncompressed_byte_count", "bounds"),
        ({"original_sha256": 5}, "content.original_sha256", "type"),
        ({"original_sha256": "A" * 64}, "content.original_sha256", "pattern"),
        ({"uncompressed_sha256": "0" * 63}, "content.uncompressed_sha256", "pattern"),
        ({"body": "b"}, "content", "unknown_field"),
        ({"data": 1}, "content", "unknown_field"),
        ({"extra": 1}, "content", "unknown_field"),
    ],
)
def test_declared_fields_and_keys_are_checked(
    declared: dict[str, Any], field: str, code: str
) -> None:
    assert _refused(_content("text", b"synthetic text\n", **declared)) == (field, code)


def test_a_missing_encoded_is_required() -> None:
    assert _refused({"format": "text", "encoding": GZIP}) == ("content.encoded", "required")


@pytest.mark.parametrize(
    ("fmt", "raw", "code"),
    [
        ("text", b"\xff\xfe broken", "malformed_utf8"),
        ("markdown", b"\xed\xa0\x80", "malformed_utf8"),  # an encoded surrogate
        ("text", b"a\x00b", "malformed"),
        ("markdown", b"  \n\t", "blank"),
        ("json", b"{", "malformed_json"),
        ("json", b"[1,]", "malformed_json"),
        ("json", b"1 2", "malformed_json"),
        ("json", b'{"a": 1, "a": 2}', "duplicate_key"),
        ("mixed", b'{"body": "b", "data": {"k": 1, "k": 1}}', "duplicate_key"),
        ("json", b"[NaN]", "malformed_json"),
        ("json", b"[Infinity]", "malformed_json"),
        ("json", b"[-Infinity]", "malformed_json"),
        ("json", b"[1e400]", "non_finite"),
        ("json", b"null", "null"),
        ("json", b"[]", "empty"),
        ("json", b'["\\u0000"]', "malformed"),
        ("json", b"[" * 33 + b"1" + b"]" * 33, "too_deep"),
        ("mixed", b'{"body": "b", "data": ' + b"[" * 33 + b"1" + b"]" * 33 + b"}", "too_deep"),
        ("mixed", b'{"body": "b", "data": 1, "extra": 2}', "mixed_shape"),
        ("mixed", b'{"body": "b"}', "mixed_shape"),
        ("mixed", b'["b", 1]', "mixed_shape"),
        ("mixed", b'{"body": " ", "data": 1}', "blank"),
    ],
)
def test_the_decoded_text_obeys_the_identity_rules(fmt: str, raw: bytes, code: str) -> None:
    assert _refused(_content(fmt, raw)) == ("content.encoded", code)


def test_a_huge_integer_is_malformed_json() -> None:
    assert _refused(_content("json", b"[" + b"9" * 5000 + b"]")) == (
        "content.encoded",
        "malformed_json",
    )


def test_a_100k_deep_nesting_is_refused_by_the_pre_scan_before_any_parse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def never(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("json.loads must not see a too-deep text")

    monkeypatch.setattr(json, "loads", never)
    for raw in (b"[" * 100_000 + b"]" * 100_000, b'{"a":' * 100_000 + b"1" + b"}" * 100_000):
        # Stored (level 0) so the 256:1 ratio is not what refuses it.
        value = _encoded("json", _b64(_gz(raw, level=0)))
        assert _refused(value) == ("content.encoded", "too_deep")


def test_brackets_inside_strings_do_not_count_toward_depth() -> None:
    raw = b'["' + b"[" * 100 + b'\\"' + b"{" * 100 + b'"]'
    assert validate_content(_content("json", raw)).data == ["[" * 100 + '"' + "{" * 100]


# ---- the two output bounds, evaluated after every piece ---------------------


class _CountingInflater:
    """A `zlib.decompressobj` that records every piece it produced."""

    def __init__(self) -> None:
        self._inner = zlib.decompressobj(wbits=31)
        self.pieces: list[int] = []

    def decompress(self, data: bytes, max_length: int = 0) -> bytes:
        piece = self._inner.decompress(data, max_length)
        self.pieces.append(len(piece))
        return piece

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


@pytest.fixture
def inflaters(monkeypatch: pytest.MonkeyPatch) -> list[_CountingInflater]:
    made: list[_CountingInflater] = []

    def counting() -> _CountingInflater:
        made.append(_CountingInflater())
        return made[-1]

    monkeypatch.setattr(encoding, "_new_inflater", counting)
    return made


def test_a_bomb_over_the_ratio_stops_within_one_piece(
    inflaters: list[_CountingInflater],
) -> None:
    raw = b"a" * (8 * 1024 * 1024)  # far over 256:1, far under 16 MiB
    original = _gz(raw)
    assert len(raw) > MAX_EXPANSION_RATIO * len(original)
    assert _refused(_encoded("text", _b64(original))) == ("content.encoded", "expansion_ratio")
    (inflater,) = inflaters
    produced = sum(inflater.pieces)
    assert max(inflater.pieces) <= DECODE_CHUNK_BYTES
    assert produced <= MAX_EXPANSION_RATIO * len(original) + DECODE_CHUNK_BYTES
    assert produced < len(raw) // 2


def test_a_ratio_compliant_stream_over_16_mib_is_too_large_and_stops_early(
    inflaters: list[_CountingInflater],
) -> None:
    raw = _words(MAX_DECODED_CONTENT_BYTES + 4 * DECODE_CHUNK_BYTES)
    original = _gz(raw, level=1)
    assert len(raw) <= MAX_EXPANSION_RATIO * len(original)
    assert _refused(_encoded("text", _b64(original))) == ("content.encoded", "too_large")
    (inflater,) = inflaters
    produced = sum(inflater.pieces)
    assert max(inflater.pieces) <= DECODE_CHUNK_BYTES
    assert produced <= MAX_DECODED_CONTENT_BYTES + DECODE_CHUNK_BYTES
    assert produced < len(raw)
