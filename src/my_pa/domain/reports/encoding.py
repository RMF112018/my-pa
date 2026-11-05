"""The `gzip+base64` content encoding: a bounded, strict decoder (WP05 B2).

A caller may upload content as `{"format", "encoding": "gzip+base64",
"encoded"}`: `encoded` is the canonical standard Base64 of exactly ONE gzip
member whose gunzipped bytes are the content's text (markdown/text: the UTF-8
body; json: a JSON text of the data; mixed: a JSON object of exactly `body` and
`data`). This module turns `encoded` into the gzip bytes (the *original*) and
the gunzipped bytes, then the text or parsed JSON; `content.validate_content`
applies the identity rules to the result and builds the `ReportContent`.

Every refusal is `ReportValidationError("content.encoded", <rule>)`, the rule a
fixed token and never the value:

1. `malformed_base64`: not a non-empty `str` of standard Base64 with padding
   (no whitespace, no URL-safe alphabet, length a multiple of 4), or not
   canonical (re-encoding the bytes does not give the input back, e.g.
   non-zero pad bits); `too_large` when the string is longer than any original
   within `MAX_ORIGINAL_CONTENT_BYTES` can encode to.
2. `malformed_gzip`: the bytes do not start with the gzip magic and deflate
   method `1f 8b 08`.
3. `original_size_mismatch` / `original_digest_mismatch`: a declared
   `original_byte_count` / `original_sha256` (of the gzip bytes) disagrees.
4. Inflation through `zlib.decompressobj(wbits=31)`, fed `DECODE_CHUNK_BYTES`
   slices with each call producing at most `DECODE_CHUNK_BYTES`; after EVERY
   output piece two separate checks: more than `MAX_DECODED_CONTENT_BYTES` in
   total is `too_large`, more than `MAX_EXPANSION_RATIO` times the gzip bytes is
   `expansion_ratio`. So inflation stops within one piece of either bound and is
   never unbounded. `zlib.error` (a corrupt stream, a bad CRC or length
   trailer) is `malformed_gzip`; a stream that never ends is `truncated`; any
   byte after the member's end (a second member included) is `trailing_data`.
5. `nested_stream`: the gunzipped bytes are themselves gzip.
6. `uncompressed_size_mismatch` / `uncompressed_digest_mismatch`: a declared
   `uncompressed_byte_count` / `uncompressed_sha256` disagrees.
7. `malformed_utf8`: the gunzipped bytes are not strict UTF-8.
8. JSON (json, mixed): one linear, non-recursive pre-scan outside strings,
   BEFORE any parse: `too_deep` for nesting deeper than the bound, so a
   hostile nesting never reaches the recursive parser, and (8a)
   `too_many_values` for more than `MAX_CONTENT_DATA_VALUES` JSON values
   (counted as an upper bound, `1 + [ and { + ,`), so a small upload never
   becomes a parse tree of millions of objects. Then `duplicate_key` for an
   object naming a key twice, and `malformed_json` for anything `json.loads`
   refuses and for `NaN`, `Infinity` and `-Infinity`.

Resources (measured, WP05 corrective B-3; validate_content plus
extract_search_text, Python 3.12, tracemalloc peak): the worst accepted shape
is 16 MiB of 262,142 long strings at 93 MiB (a single 16 MiB string 80 MiB, a
16 MiB markdown body 48 MiB, `[{},...]` at the value cap 29 MiB); the largest
CPU is 1.4 s, for 16 MiB of 4,299-digit integers (every other shape under
0.4 s). The 16 MiB `[{},...]`, `[[],...]`, `[0,...]` and `["a",...]` shapes
that peaked at 0.4-1.3 GB before the value cap are refused in under 0.1 s at
a 32 MiB peak.

Where it runs (WP05 corrective B-4): command construction only checks a gzip
upload's structure (`check_encoded_shape`); the decode itself runs in the
publish/update handler, one at a time process-wide (the application's decode
permit), bounded by `max_decoded`: 16 MiB with a report content store, the
inline threshold without one. The bound applies to the gunzipped bytes AND
to the decoded (canonical) content, so without a store pretty-printed JSON
whose gunzipped text is above the threshold is refused `too_large` even when
its canonical form would fit.
"""

from __future__ import annotations

import binascii
import hashlib
import json
import re
import zlib
from typing import Any, Final, cast

from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.vocabulary import (
    DECODE_CHUNK_BYTES,
    MAX_DECODED_CONTENT_BYTES,
    MAX_EXPANSION_RATIO,
    MAX_ORIGINAL_CONTENT_BYTES,
)

__all__ = [
    "ENCODED_FIELD",
    "GZIP_MAGIC",
    "check_encoded_shape",
    "decode_gzip_base64",
    "parse_json_text",
    "utf8_text",
]

#: The field every refusal of this module names.
ENCODED_FIELD: Final = "content.encoded"
#: A gzip member: ID1 ID2 and CM = 8 (deflate), RFC 1952 section 2.3.1.
GZIP_MAGIC: Final = b"\x1f\x8b\x08"
_NESTED_MAGIC: Final = b"\x1f\x8b"

#: Anchored, possessive: one forward pass, nothing given back (linear in the input).
_BASE64: Final = re.compile(r"\A[A-Za-z0-9+/]*+={0,2}\Z")
#: Base64 characters of `MAX_ORIGINAL_CONTENT_BYTES` bytes, with padding.
_MAX_ENCODED_CHARACTERS: Final = 4 * -(-MAX_ORIGINAL_CONTENT_BYTES // 3)
#: A multiple of 4, so every slice but the last decodes on its own.
_BASE64_SLICE_CHARACTERS: Final = 4 * DECODE_CHUNK_BYTES


def _refuse(rule: str) -> ReportValidationError:
    return ReportValidationError(ENCODED_FIELD, rule)


def check_encoded_shape(encoded: object) -> None:
    """The O(1) part of step 1: a non-empty `str` no longer than any original can encode to.

    What command construction checks of a gzip upload (WP05 corrective B-4):
    nothing is decoded, inflated or parsed there; `decode_gzip_base64` repeats
    this and does the rest in the handler, under the decode permit.
    """
    if type(encoded) is not str or not encoded:
        raise _refuse("malformed_base64")
    if len(encoded) > _MAX_ENCODED_CHARACTERS:
        raise _refuse("too_large")


def _base64_bytes(encoded: object) -> bytes:
    """Step 1: the bytes canonical standard Base64 `encoded` names."""
    check_encoded_shape(encoded)
    encoded = cast("str", encoded)
    if len(encoded) % 4 or not _BASE64.match(encoded):
        raise _refuse("malformed_base64")
    try:
        ascii_text = encoded.encode("ascii")
        decoded = b"".join(
            binascii.a2b_base64(
                ascii_text[start : start + _BASE64_SLICE_CHARACTERS], strict_mode=True
            )
            for start in range(0, len(ascii_text), _BASE64_SLICE_CHARACTERS)
        )
    except (binascii.Error, UnicodeEncodeError):
        raise _refuse("malformed_base64") from None
    # Canonical: rejects non-zero pad bits, the one ambiguity strict mode keeps.
    if binascii.b2a_base64(decoded, newline=False) != ascii_text:
        raise _refuse("malformed_base64")
    return decoded


def _new_inflater() -> zlib._Decompress:
    """One gzip-member inflater (`wbits=31`: a gzip header and trailer, nothing else)."""
    return zlib.decompressobj(wbits=31)


def _inflate(original: bytes, max_decoded: int) -> bytes:
    """Step 4: the gunzipped bytes of exactly one member, never inflated unbounded.

    `max_decoded` is the size bound: `MAX_DECODED_CONTENT_BYTES` when the
    caller can place content that large, else its inline threshold (WP05
    corrective B-4), so a deployment without a report content store never
    inflates past it.
    """
    inflater = _new_inflater()
    ratio_bound = MAX_EXPANSION_RATIO * len(original)
    pieces: list[bytes] = []
    total = 0

    def take(piece: bytes) -> None:
        nonlocal total
        total += len(piece)
        # Two separate checks after every piece, size first.
        if total > max_decoded:
            raise _refuse("too_large")
        if total > ratio_bound:
            raise _refuse("expansion_ratio")
        pieces.append(piece)

    position = 0
    try:
        while position < len(original) and not inflater.eof:
            pending = original[position : position + DECODE_CHUNK_BYTES]
            position += len(pending)
            while pending and not inflater.eof:
                take(inflater.decompress(pending, DECODE_CHUNK_BYTES))
                pending = inflater.unconsumed_tail
        # Output zlib still holds after the last input byte, a piece at a time.
        while not inflater.eof:
            piece = inflater.decompress(b"", DECODE_CHUNK_BYTES)
            if not piece:
                break
            take(piece)
    except zlib.error:
        raise _refuse("malformed_gzip") from None
    if not inflater.eof:
        raise _refuse("truncated")
    if inflater.unused_data or position < len(original):
        raise _refuse("trailing_data")
    return b"".join(pieces)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def decode_gzip_base64(
    encoded: object,
    *,
    original_byte_count: int | None = None,
    original_sha256: str | None = None,
    uncompressed_byte_count: int | None = None,
    uncompressed_sha256: str | None = None,
    max_decoded: int = MAX_DECODED_CONTENT_BYTES,
) -> tuple[bytes, bytes]:
    """Steps 1-6: `(original, uncompressed)`, the gzip bytes and the gunzipped bytes.

    The declared counts and digests are optional and already well-formed (the
    caller validated their types); a declared value that disagrees is refused.
    `max_decoded` (at most `MAX_DECODED_CONTENT_BYTES`) bounds the inflation.
    """
    max_decoded = min(max_decoded, MAX_DECODED_CONTENT_BYTES)
    original = _base64_bytes(encoded)
    if not original.startswith(GZIP_MAGIC):
        raise _refuse("malformed_gzip")
    if original_byte_count is not None and original_byte_count != len(original):
        raise _refuse("original_size_mismatch")
    if original_sha256 is not None and original_sha256 != _sha256(original):
        raise _refuse("original_digest_mismatch")
    uncompressed = _inflate(original, max_decoded)
    if uncompressed.startswith(_NESTED_MAGIC):
        raise _refuse("nested_stream")
    if uncompressed_byte_count is not None and uncompressed_byte_count != len(uncompressed):
        raise _refuse("uncompressed_size_mismatch")
    if uncompressed_sha256 is not None and uncompressed_sha256 != _sha256(uncompressed):
        raise _refuse("uncompressed_digest_mismatch")
    return original, uncompressed


def utf8_text(uncompressed: bytes) -> str:
    """Step 7: the gunzipped bytes as strict UTF-8 text."""
    try:
        return uncompressed.decode("utf-8")
    except UnicodeDecodeError:
        raise _refuse("malformed_utf8") from None


def _json_shape_refusal(text: str, *, max_depth: int, max_values: int) -> str | None:
    """`too_deep` or `too_many_values` for `text` before any parse, else `None`.

    One forward pass over the characters, no regex and no recursion, so it is
    linear in the text whatever the text is (a hostile one included: WP05
    corrective B-1). It tracks only "inside a string" and "after a backslash
    inside a string", and outside strings counts:

    - depth: `+1` at `[`/`{`, `-1` at `]`/`}`; above `max_depth` is `too_deep`.
      On valid JSON this is the exact nesting depth.
    - values (WP05 B2 step 8a): an upper bound on the JSON values the text
      can hold, `1 + (number of [ and {) + (number of ,)`, all outside
      strings. Every value is the top-level one or an element or member value
      of a container, and a container of k > 0 elements has k - 1 commas, so
      the true count is at most this (an empty container counts one too
      many). Above `max_values` is `too_many_values`. Object keys are not
      values.

    It stops at the first bound passed. An unterminated string simply runs to
    the end of the text: what follows its opening quote is string content to
    the parser too, which then refuses the text as malformed.
    """
    depth = 0
    values = 1
    in_string = False
    escaped = False
    for character in text:
        if in_string:
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
        elif character == '"':
            in_string = True
        elif character == ",":
            values += 1
            if values > max_values:
                return "too_many_values"
        elif character == "[" or character == "{":
            depth += 1
            if depth > max_depth:
                return "too_deep"
            values += 1
            if values > max_values:
                return "too_many_values"
        elif character == "]" or character == "}":
            depth -= 1
    return None


class _DuplicateKeyError(Exception):
    """Raised inside `json.loads`; deliberately not a `ValueError`."""


def _unique_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result = dict(pairs)
    if len(result) != len(pairs):
        raise _DuplicateKeyError
    return result


def _no_constant(_name: str) -> object:
    raise ValueError("non-finite JSON constant")


def parse_json_text(text: str, *, max_depth: int, max_values: int) -> object:
    """Steps 8 and 8a: one JSON value, depth- and value-count-checked before it is parsed."""
    shape = _json_shape_refusal(text, max_depth=max_depth, max_values=max_values)
    if shape is not None:
        raise _refuse(shape)
    try:
        return json.loads(text, object_pairs_hook=_unique_object, parse_constant=_no_constant)
    except _DuplicateKeyError:
        raise _refuse("duplicate_key") from None
    except (ValueError, RecursionError):
        # `JSONDecodeError` is a `ValueError`, as is an over-long integer.
        raise _refuse("malformed_json") from None
