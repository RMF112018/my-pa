"""Schedule Scenarios S6-2: compressed storage of canonical plane bytes, verified on read.

Contract: `docs/architecture/schedule-scenarios-contract.md` section 14.8.3
(S6-2-D11). Content, change sets, CPM results and outputs are stored as one
zlib stream of their canonical bytes; every digest is over the canonical
bytes, never over the compressed ones, so the compressed bytes need not be
deterministic.

Reading back is bounded and verified, in this order:

1. `decompress_bounded` inflates at most `limit + 1` bytes and refuses a
   stream that would inflate further, is truncated, or carries trailing data
   (`ScenarioIntegrityError("decompress_bound")`), so a stored bomb never
   allocates more than its kind's bound;
2. the inflated length must equal the row's stored `*_size_bytes` exactly;
3. `sha256(<schema> + "\\n" + canonical)` must equal the row's stored digest
   (`"<kind>_digest"`);
4. the canonical bytes must be one JSON object (`"<kind>_decode"`).

No SQL here: the repository reads the row and hands the columns over.
"""

from __future__ import annotations

import hashlib
import json
import zlib
from collections.abc import Mapping
from typing import Final

from my_pa.contracts.ports import ScenarioIntegrityError

__all__ = [
    "COMPRESSION_LEVEL",
    "compress_canonical",
    "decompress_bounded",
    "verified_canonical",
    "verified_document",
]

#: Section 14.8.3: `zlib.compress(canonical, 6)`.
COMPRESSION_LEVEL: Final = 6


def compress_canonical(canonical: bytes) -> bytes:
    """One zlib stream of the canonical bytes (refuses empty input: every CHECK is >= 1)."""
    if not canonical:
        raise ValueError("canonical plane bytes are a non-empty bytes value")
    return zlib.compress(canonical, COMPRESSION_LEVEL)


def decompress_bounded(blob: bytes, limit: int) -> bytes:
    """Inflate `blob` to at most `limit` bytes, or raise `decompress_bound`.

    `max_length = limit + 1` is what bounds the allocation: a stream that would
    inflate past `limit` stops one byte over and is refused, whatever its
    declared or real size. A stream that ends early (`not eof`), leaves input
    unconsumed or carries bytes after its end is refused too.
    """
    if type(limit) is not int or limit < 1:
        raise ValueError("a decompression limit is a positive integer")
    inflater = zlib.decompressobj()
    try:
        out = inflater.decompress(blob, limit + 1)
    except zlib.error:
        raise ScenarioIntegrityError("decompress_bound") from None
    if len(out) > limit or inflater.unconsumed_tail or inflater.unused_data or not inflater.eof:
        raise ScenarioIntegrityError("decompress_bound")
    return out


def verified_canonical(
    blob: bytes, *, kind: str, schema: str, sha256: str, size_bytes: int, limit: int
) -> bytes:
    """The stored canonical bytes, bounded by `min(limit, size_bytes)` and digest-checked."""
    if type(size_bytes) is not int or size_bytes < 1:
        raise ScenarioIntegrityError(f"{kind}_size")
    out = decompress_bounded(blob, min(limit, size_bytes))
    if len(out) != size_bytes:
        raise ScenarioIntegrityError(f"{kind}_size")
    if hashlib.sha256(schema.encode("ascii") + b"\n" + out).hexdigest() != sha256:
        raise ScenarioIntegrityError(f"{kind}_digest")
    return out


def verified_document(
    blob: bytes, *, kind: str, schema: str, sha256: str, size_bytes: int, limit: int
) -> tuple[Mapping[str, object], bytes]:
    """`verified_canonical`, then the bytes decoded as one JSON object."""
    canonical = verified_canonical(
        blob, kind=kind, schema=schema, sha256=sha256, size_bytes=size_bytes, limit=limit
    )
    try:
        document = json.loads(canonical)
    except (ValueError, UnicodeDecodeError):
        raise ScenarioIntegrityError(f"{kind}_decode") from None
    if not isinstance(document, dict):
        raise ScenarioIntegrityError(f"{kind}_decode")
    return document, canonical
