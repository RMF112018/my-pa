"""Inline report content: validation, canonical bytes and digests (WP02, contract B1).

A content value is one of four shapes, each a JSON object:

- `markdown` and `text`: `{"format", "body"}`;
- `json`: `{"format", "data"}`;
- `mixed`: `{"format", "body", "data"}`.

Each may also carry `"encoding"`, and only `"identity"` is accepted here:
`"gzip+base64"` is a known encoding this plane cannot yet decode and is
refused as `unsupported_encoding` (WP05). Any other key is refused.

The decoded bytes are what the digests name: the body as UTF-8 for
`markdown`/`text`, the canonical JSON of `data` for `json`, and the canonical
JSON of `{"body": body, "data": data}` for `mixed`. Under the identity encoding
the original bytes are the decoded bytes. Every refusal names a field and a
rule, never the value.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.values import NOT_A_SCALAR, json_scalar
from my_pa.domain.reports.vocabulary import ContentEncoding, ContentFormat

__all__ = [
    "INLINE_CONTENT_MAX_BYTES",
    "MAX_CONTENT_DATA_DEPTH",
    "ReportContent",
    "canonical_json",
    "content_of",
    "validate_content",
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

    Built only by `content_of`, which derives every digest from the body and
    data it holds, so the fields cannot disagree with one another. The body,
    the data and the decoded bytes are kept out of `repr`: a logged or
    asserted value names the format and the digests, never the content.
    """

    format: ContentFormat
    encoding: ContentEncoding
    body: str | None = field(repr=False)
    data: Any = field(repr=False)
    decoded: bytes = field(repr=False)
    decoded_sha256: str
    canonical_sha256: str | None

    @property
    def decoded_byte_count(self) -> int:
        return len(self.decoded)

    @property
    def original_sha256(self) -> str:
        """Identity encoding: the original is the decoded bytes."""
        return self.decoded_sha256

    @property
    def original_byte_count(self) -> int:
        return len(self.decoded)


def content_of(content_format: ContentFormat, *, body: str | None, data: object) -> ReportContent:
    """The content value of already-valid parts, with its bytes and digests.

    Also the read path's recomputation: a stored body and data are passed
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
        encoding=ContentEncoding.IDENTITY,
        body=body,
        data=data,
        decoded=decoded,
        decoded_sha256=digest,
        canonical_sha256=None if textual else digest,
    )


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


def validate_content(value: object) -> ReportContent:
    """Validate one caller content object and return it with its digests."""
    if type(value) is not dict:
        raise ReportValidationError("content", "type")
    raw_format = value.get("format")
    if type(raw_format) is not str:
        raise ReportValidationError("content.format", "required")
    try:
        content_format = ContentFormat(raw_format)
    except ValueError:
        raise ReportValidationError("content.format", "unknown") from None
    if any(key not in _KEYS[content_format] for key in value):
        raise ReportValidationError("content", "unknown_field")
    if "encoding" in value:
        encoding = value["encoding"]
        if encoding == ContentEncoding.GZIP_BASE64.value and type(encoding) is str:
            raise ReportValidationError("content.encoding", "unsupported_encoding")
        if encoding != ContentEncoding.IDENTITY.value or type(encoding) is not str:
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
