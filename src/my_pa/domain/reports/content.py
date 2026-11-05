"""Inline report content: validation, canonical bytes and digests (WP02, contract B1).

A content value is one of four shapes, each a JSON object:

- `markdown` and `text`: `{"format", "body"}`;
- `json`: `{"format", "data"}`;
- `mixed`: `{"format", "body", "data"}`.

Each may also carry `"encoding"`: omitted or `"identity"`, the shapes above;
`"gzip+base64"` (WP05 B1), `{"format", "encoding", "encoded"}` plus the
optional declared `original_byte_count`, `original_sha256` (of the gzip bytes),
`uncompressed_byte_count` and `uncompressed_sha256` (of the gunzipped bytes),
decoded by `domain.reports.encoding`. `body` and `data` are refused with
gzip, `encoded` and the declared fields with identity, as any other key is.

The decoded bytes are what the digests name: the body as UTF-8 for
`markdown`/`text`, the canonical JSON of `data` for `json`, and the canonical
JSON of `{"body": body, "data": data}` for `mixed`, whatever the encoding.
Under the identity encoding the original bytes are the decoded bytes; under
gzip they are the uploaded gzip bytes, kept in `ReportContent.original`.
Identity content is bounded by `INLINE_CONTENT_MAX_BYTES` (decoded) here. Gzip
content is bounded by `max_decoded` (at most `MAX_DECODED_CONTENT_BYTES`) twice:
on the gunzipped bytes as uploaded (with `MAX_EXPANSION_RATIO` times the gzip
bytes, in `encoding`) and on the decoded (canonical) bytes; its JSON by
`MAX_CONTENT_DATA_DEPTH` and `MAX_CONTENT_DATA_VALUES` in the uploaded text.
Placement (inline, the store, or a refusal) is the repository's decision.
Every refusal names a field and a rule, never the value.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final, cast

from my_pa.domain.reports.encoding import (
    ENCODED_FIELD,
    check_encoded_shape,
    decode_gzip_base64,
    parse_json_text,
    utf8_text,
)
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.values import NOT_A_SCALAR, json_scalar
from my_pa.domain.reports.vocabulary import (
    MAX_CONTENT_DATA_VALUES,
    MAX_DECODED_CONTENT_BYTES,
    MAX_ORIGINAL_CONTENT_BYTES,
    ContentEncoding,
    ContentFormat,
)

__all__ = [
    "INLINE_CONTENT_MAX_BYTES",
    "MAX_CONTENT_DATA_DEPTH",
    "ReportContent",
    "canonical_json",
    "content_facts",
    "content_from_decoded",
    "content_of",
    "is_gzip_content",
    "validate_content",
    "validate_content_structure",
]

#: The decoded size an inline content value may have (512 KiB).
INLINE_CONTENT_MAX_BYTES: Final = 524288
#: A top-level JSON value is depth 1; every nested object or array adds one.
MAX_CONTENT_DATA_DEPTH: Final = 32

_TEXTUAL: Final = frozenset({ContentFormat.MARKDOWN, ContentFormat.TEXT})
_KEYS: Final[Mapping[ContentFormat, frozenset[str]]] = {
    ContentFormat.MARKDOWN: frozenset({"format", "encoding", "body"}),
    ContentFormat.TEXT: frozenset({"format", "encoding", "body"}),
    ContentFormat.JSON: frozenset({"format", "encoding", "data"}),
    ContentFormat.MIXED: frozenset({"format", "encoding", "body", "data"}),
}
#: WP05 B1: the declared facts of a gzip upload, each optional.
_DECLARED_COUNTS: Final = ("original_byte_count", "uncompressed_byte_count")
_DECLARED_DIGESTS: Final = ("original_sha256", "uncompressed_sha256")
#: The same keys for every format: the format is inside the gzip stream.
_GZIP_KEYS: Final = frozenset(
    {"format", "encoding", "encoded", *_DECLARED_COUNTS, *_DECLARED_DIGESTS}
)
_SHA256_HEX: Final = re.compile(r"\A[0-9a-f]{64}\Z")


def _without_negative_zero(value: object) -> object:
    if type(value) is float and value == 0.0:
        return 0.0
    if isinstance(value, list):
        return [_without_negative_zero(item) for item in value]
    if isinstance(value, dict):
        return {key: _without_negative_zero(item) for key, item in value.items()}
    return value


def canonical_json(value: object) -> bytes:
    """The one canonical serialization this plane hashes.

    Sorted keys, `(",", ":")`, `ensure_ascii=False`, no NaN, UTF-8, and `-0.0`
    written as `0.0`: PostgreSQL's `numeric` has no negative zero, so a stored
    jsonb value reads back as `0.0`, and bytes hashed before storing must equal
    bytes hashed after reading. Raises `ValueError` for a value JSON cannot
    hold (the caller has validated it).
    """
    return json.dumps(
        _without_negative_zero(value),
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


@dataclass(frozen=True, slots=True)
class ReportContent:
    """One inline content value with its decoded bytes and their digests.

    Built by `content_of`, which derives every digest from the body and data
    it holds, so the fields cannot disagree with one another. The body, the
    data and the decoded bytes are kept out of `repr`: a logged or asserted
    value names the format and the digests, never the content.

    **WP05 C: a content value may be facts only.** `content_facts` builds one
    for a `managed_blob` row read without the report content store (a history
    page, an update's head, the read before the service verifies the blob):
    `materialized` is false, `body`, `data` and `original` are `None`, and
    `decoded` is empty -- `decoded_byte_count` is a field, not `len(decoded)`,
    so the facts still name the true size. Anything that needs the content
    itself (`extract_search_text`, an intent digest) refuses such a value
    rather than reading an empty body.
    """

    format: ContentFormat
    encoding: ContentEncoding
    body: str | None = field(repr=False)
    data: Any = field(repr=False)
    decoded: bytes = field(repr=False)
    decoded_sha256: str
    canonical_sha256: str | None
    #: WP05 B2 step 9: the uploaded gzip bytes; `None` under identity, where
    #: the original is the decoded bytes.
    original: bytes | None = field(repr=False)
    original_sha256: str
    original_byte_count: int
    decoded_byte_count: int
    #: WP05 C: `False` only for `content_facts` (the bytes are in the store).
    materialized: bool = True


def content_of(
    content_format: ContentFormat,
    *,
    body: str | None,
    data: object,
    original: bytes | None = None,
) -> ReportContent:
    """The content value of already-valid parts, with its bytes and digests.

    `original` is the gzip bytes the parts were decoded from (`gzip+base64`),
    or `None` for identity content, whose original is its decoded bytes. Also
    the read path's recomputation: a stored body, data and original are passed
    through here and the digests compared with the stored ones.
    """
    textual = content_format in _TEXTUAL
    if textual:
        if body is None:
            raise ReportValidationError("content.body", "required")
        decoded = body.encode("utf-8")
    elif content_format is ContentFormat.JSON:
        decoded = canonical_json(data)
    else:
        decoded = canonical_json({"body": body, "data": data})
    digest = _sha256(decoded)
    return ReportContent(
        format=content_format,
        encoding=ContentEncoding.IDENTITY if original is None else ContentEncoding.GZIP_BASE64,
        body=body,
        data=data,
        decoded=decoded,
        decoded_sha256=digest,
        canonical_sha256=None if textual else digest,
        original=original,
        original_sha256=digest if original is None else _sha256(original),
        original_byte_count=len(decoded) if original is None else len(original),
        decoded_byte_count=len(decoded),
    )


def content_facts(
    content_format: ContentFormat,
    encoding: ContentEncoding,
    *,
    decoded_sha256: str,
    decoded_byte_count: int,
    canonical_sha256: str | None,
    original_sha256: str,
    original_byte_count: int,
) -> ReportContent:
    """The facts of a content value whose bytes are not held here (WP05 C, `managed_blob`).

    Checks the facts agree with one another as `content_of` would have made
    them (a structured value's canonical digest is its decoded digest, a
    textual one has none; identity content is its own original), else
    `ReportValidationError("content", "facts")`. Says nothing about the bytes:
    the report content store verifies those against these facts.
    """
    textual = content_format in _TEXTUAL
    consistent = (
        type(decoded_byte_count) is int
        and type(original_byte_count) is int
        and 1 <= decoded_byte_count <= MAX_DECODED_CONTENT_BYTES
        and 0 <= original_byte_count <= MAX_ORIGINAL_CONTENT_BYTES
        and _SHA256_HEX.match(decoded_sha256) is not None
        and _SHA256_HEX.match(original_sha256) is not None
        and (canonical_sha256 is None if textual else canonical_sha256 == decoded_sha256)
        and (
            encoding is not ContentEncoding.IDENTITY
            or (original_sha256 == decoded_sha256 and original_byte_count == decoded_byte_count)
        )
    )
    if not consistent:
        raise ReportValidationError("content", "facts")
    return ReportContent(
        format=content_format,
        encoding=encoding,
        body=None,
        data=None,
        decoded=b"",
        decoded_sha256=decoded_sha256,
        canonical_sha256=canonical_sha256,
        original=None,
        original_sha256=original_sha256,
        original_byte_count=original_byte_count,
        decoded_byte_count=decoded_byte_count,
        materialized=False,
    )


def content_from_decoded(
    content_format: ContentFormat, decoded: bytes, *, original: bytes | None = None
) -> ReportContent:
    """Rebuild a content value from its stored decoded bytes (WP05 C5).

    The inverse of `content_of`'s serialization: textual bytes are the UTF-8
    body; `json` bytes are the canonical JSON of the data; `mixed` bytes the
    canonical JSON of `{"body", "data"}`. The result is passed through
    `content_of`, so its digests are recomputed; the caller compares them with
    the stored ones. Malformed bytes raise `ReportValidationError("content",
    "stored")`, never echoing them.
    """
    try:
        text = decoded.decode("utf-8")
        if content_format in _TEXTUAL:
            return content_of(content_format, body=text, data=None, original=original)
        parsed = json.loads(text)
        if content_format is ContentFormat.JSON:
            return content_of(content_format, body=None, data=parsed, original=original)
        if type(parsed) is not dict or set(parsed) != {"body", "data"}:
            raise ReportValidationError("content", "stored")
        return content_of(
            content_format, body=parsed["body"], data=parsed["data"], original=original
        )
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError):
        raise ReportValidationError("content", "stored") from None


def _body(value: object) -> str:
    if type(value) is not str:
        raise ReportValidationError("content.body", "type")
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        raise ReportValidationError("content.body", "malformed") from None
    if "\x00" in value:
        raise ReportValidationError("content.body", "malformed")
    if not value.strip():
        raise ReportValidationError("content.body", "blank")
    return value


def _data_key(key: object) -> str:
    if type(key) is not str:
        raise ReportValidationError("content.data", "key_type")
    try:
        key.encode("utf-8")
    except UnicodeEncodeError:
        raise ReportValidationError("content.data", "malformed") from None
    if "\x00" in key:
        raise ReportValidationError("content.data", "malformed")
    return key


def _data_value(value: object, depth: int) -> object:
    scalar = json_scalar(value, "content.data")
    if scalar is not NOT_A_SCALAR:
        return scalar
    kind = type(value)
    if kind is list or kind is dict:
        if depth + 1 > MAX_CONTENT_DATA_DEPTH:
            raise ReportValidationError("content.data", "too_deep")
        if isinstance(value, list):
            return [_data_value(item, depth + 1) for item in value]
        if isinstance(value, dict):
            return {_data_key(key): _data_value(item, depth + 1) for key, item in value.items()}
    raise ReportValidationError("content.data", "value_type")


def _data(value: object, content_format: ContentFormat) -> object:
    """Any JSON value but null; an empty object or array only inside `mixed`."""
    if value is None:
        raise ReportValidationError("content.data", "null")
    if type(value) in (list, dict) and not value and content_format is ContentFormat.JSON:
        raise ReportValidationError("content.data", "empty")
    return _data_value(value, 0)


def _declared_count(value: Mapping[str, object], name: str) -> int | None:
    if name not in value:
        return None
    count = value[name]
    if type(count) is not int:
        raise ReportValidationError(f"content.{name}", "type")
    bound = (
        MAX_ORIGINAL_CONTENT_BYTES if name == "original_byte_count" else MAX_DECODED_CONTENT_BYTES
    )
    if not 0 <= count <= bound:
        raise ReportValidationError(f"content.{name}", "bounds")
    return count


def _declared_digest(value: Mapping[str, object], name: str) -> str | None:
    if name not in value:
        return None
    digest = value[name]
    if type(digest) is not str:
        raise ReportValidationError(f"content.{name}", "type")
    if not _SHA256_HEX.match(digest):
        raise ReportValidationError(f"content.{name}", "pattern")
    return digest


def _gzip_shape(value: Mapping[str, object]) -> None:
    """The structure of a gzip upload: keys, `encoded`'s type and length, declared fields."""
    if any(key not in _GZIP_KEYS for key in value):
        raise ReportValidationError("content", "unknown_field")
    if "encoded" not in value:
        raise ReportValidationError(ENCODED_FIELD, "required")
    _declared_count(value, "original_byte_count")
    _declared_digest(value, "original_sha256")
    _declared_count(value, "uncompressed_byte_count")
    _declared_digest(value, "uncompressed_sha256")
    check_encoded_shape(value["encoded"])


def _gzip_content(
    value: Mapping[str, object], content_format: ContentFormat, max_decoded: int
) -> ReportContent:
    """WP05 B1/B2: one `gzip+base64` content object, decoded and validated."""
    if any(key not in _GZIP_KEYS for key in value):
        raise ReportValidationError("content", "unknown_field")
    if "encoded" not in value:
        raise ReportValidationError(ENCODED_FIELD, "required")
    original, uncompressed = decode_gzip_base64(
        value["encoded"],
        original_byte_count=_declared_count(value, "original_byte_count"),
        original_sha256=_declared_digest(value, "original_sha256"),
        uncompressed_byte_count=_declared_count(value, "uncompressed_byte_count"),
        uncompressed_sha256=_declared_digest(value, "uncompressed_sha256"),
        max_decoded=max_decoded,
    )
    text = utf8_text(uncompressed)
    body: str | None = None
    data: object = None
    try:
        if content_format in _TEXTUAL:
            body = _body(text)
        else:
            # A mixed object's data sits one level below its `{body, data}`
            # wrapper, which also adds itself and one comma to the value bound.
            wrapped = content_format is ContentFormat.MIXED
            parsed = parse_json_text(
                text,
                max_depth=MAX_CONTENT_DATA_DEPTH + (1 if wrapped else 0),
                max_values=MAX_CONTENT_DATA_VALUES + (2 if wrapped else 0),
            )
            if wrapped:
                if type(parsed) is not dict or set(parsed) != {"body", "data"}:
                    raise ReportValidationError(ENCODED_FIELD, "mixed_shape")
                body = _body(parsed["body"])
                data = _data(parsed["data"], content_format)
            else:
                data = _data(parsed, content_format)
    except ReportValidationError as error:
        # The identity rules, named on the field the caller sent.
        refusal = ReportValidationError(ENCODED_FIELD, error.code)
    else:
        try:
            content = content_of(content_format, body=body, data=data, original=original)
        except ValueError:
            raise ReportValidationError("content", "too_large") from None
        if content.decoded_byte_count > min(max_decoded, MAX_DECODED_CONTENT_BYTES):
            raise ReportValidationError("content", "too_large")
        return content
    raise refusal


def is_gzip_content(value: object) -> bool:
    """Whether `value` asks for the `gzip+base64` encoding (decoded under the permit)."""
    if type(value) is not dict:
        return False
    encoding = value.get("encoding")
    return type(encoding) is str and encoding == ContentEncoding.GZIP_BASE64.value


def _content_format(value: object) -> ContentFormat:
    if type(value) is not dict:
        raise ReportValidationError("content", "type")
    raw_format = value.get("format")
    if type(raw_format) is not str:
        raise ReportValidationError("content.format", "required")
    try:
        return ContentFormat(raw_format)
    except ValueError:
        raise ReportValidationError("content.format", "unknown") from None


def validate_content_structure(value: object) -> ReportContent | None:
    """What command construction validates of a content object (WP05 corrective B-4).

    Identity content is validated in full (the request bounds it) and
    returned. A `gzip+base64` upload is checked for its structure only -- its
    keys, `encoded` a non-empty `str` no longer than the Base64 of the largest
    original, the declared fields' types, bounds and patterns -- and `None` is
    returned: decoding, inflating and parsing happen in the handler through
    `validate_content`, under the decode permit and with the deployment's
    decode limit. Every refusal raised here is one `validate_content` raises.
    """
    _content_format(value)
    if is_gzip_content(value):
        _gzip_shape(cast("dict[str, object]", value))
        return None
    return validate_content(value)


def validate_content(
    value: object, *, max_decoded: int = MAX_DECODED_CONTENT_BYTES
) -> ReportContent:
    """Validate one caller content object and return it with its digests.

    Dispatches by encoding (WP05 B1): `gzip+base64` is decoded by
    `domain.reports.encoding`, its decoded size bounded by `max_decoded`
    (WP05 corrective B-4: the handler passes its inline threshold when no
    report content store is composed); anything else takes the identity path,
    unchanged byte for byte from WP02 (`max_decoded` does not apply to it).
    """
    content_format = _content_format(value)
    value = cast("dict[str, object]", value)
    if is_gzip_content(value):
        return _gzip_content(value, content_format, max_decoded)
    encoding = value.get("encoding")
    if any(key not in _KEYS[content_format] for key in value):
        raise ReportValidationError("content", "unknown_field")
    if "encoding" in value and (
        encoding != ContentEncoding.IDENTITY.value or type(encoding) is not str
    ):
        raise ReportValidationError("content.encoding", "unknown")
    body: str | None = None
    data: object = None
    if "body" in _KEYS[content_format]:
        if "body" not in value:
            raise ReportValidationError("content.body", "required")
        body = _body(value["body"])
    if "data" in _KEYS[content_format]:
        if "data" not in value:
            raise ReportValidationError("content.data", "required")
        data = _data(value["data"], content_format)
    try:
        content = content_of(content_format, body=body, data=data)
    except ValueError:
        # An `int` beyond the interpreter's digit limit (4300): far over the bound.
        raise ReportValidationError("content", "too_large") from None
    if content.decoded_byte_count > INLINE_CONTENT_MAX_BYTES:
        raise ReportValidationError("content", "too_large")
    return content
