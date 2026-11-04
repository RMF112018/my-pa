"""Schedule Scenarios S6-2: bounded decompression and digest verification (FAST).

Contract `docs/architecture/schedule-scenarios-contract.md` section 14.8.3
(S6-2-D11). A stored stream inflates to at most its kind's bound -- and the
bound is the allocation, not a check after it -- must end exactly where it
says, must equal its stored size, and must carry the stored digest of its
canonical bytes. Every value is synthetic.
"""

from __future__ import annotations

import hashlib
import json
import types
import zlib
from typing import Any, Final

import pytest

from my_pa.contracts.ports import ScenarioIntegrityError
from my_pa.infrastructure.persistence import schedule_plane_codec as codec
from my_pa.infrastructure.persistence.schedule_plane_codec import (
    compress_canonical,
    decompress_bounded,
    verified_canonical,
    verified_document,
)

LIMIT: Final = 4_096
SCHEMA: Final = "schedule-scenario-content-v1"


def _digest(canonical: bytes, schema: str = SCHEMA) -> str:
    return hashlib.sha256(schema.encode("ascii") + b"\n" + canonical).hexdigest()


class _Spy:
    """Wraps `zlib.decompressobj` and records the size of every inflation it returns."""

    def __init__(self) -> None:
        self.produced: list[int] = []

    def decompressobj(self) -> Any:  # noqa: ANN401 - mirrors zlib's untyped object
        real = zlib.decompressobj()
        spy = self

        class _Inflater:
            def decompress(self, data: bytes, max_length: int = 0) -> bytes:
                out = real.decompress(data, max_length)
                spy.produced.append(len(out))
                return out

            @property
            def unconsumed_tail(self) -> bytes:
                return real.unconsumed_tail

            @property
            def unused_data(self) -> bytes:
                return real.unused_data

            @property
            def eof(self) -> bool:
                return real.eof

        return _Inflater()


def test_decompression_is_bounded(monkeypatch: pytest.MonkeyPatch) -> None:
    """A bomb never inflates past `limit + 1` bytes; every malformed stream is refused."""
    spy = _Spy()
    monkeypatch.setattr(
        codec, "zlib", types.SimpleNamespace(decompressobj=spy.decompressobj, error=zlib.error)
    )
    exact = b"a" * LIMIT
    assert decompress_bounded(zlib.compress(exact, 6), LIMIT) == exact
    bomb = zlib.compress(b"\0" * (LIMIT * 64), 9)
    with pytest.raises(ScenarioIntegrityError) as refused:
        decompress_bounded(bomb, LIMIT)
    assert refused.value.code == "decompress_bound"
    assert max(spy.produced) <= LIMIT + 1, spy.produced
    one_over = zlib.compress(b"a" * (LIMIT + 1), 6)
    stream = zlib.compress(b"b" * 100, 6)
    for broken in (one_over, stream[:-6], stream + b"trailing", b"not a zlib stream", b""):
        with pytest.raises(ScenarioIntegrityError) as refused:
            decompress_bounded(broken, LIMIT)
        assert refused.value.code == "decompress_bound"
    with pytest.raises(ValueError, match="positive integer"):
        decompress_bounded(stream, 0)


def test_compression_round_trips_and_refuses_empty_input() -> None:
    canonical = json.dumps({"schema": SCHEMA, "x": 1}).encode()
    assert zlib.decompress(compress_canonical(canonical)) == canonical
    with pytest.raises(ValueError, match="non-empty"):
        compress_canonical(b"")


def test_the_stored_size_and_digest_are_verified() -> None:
    canonical = json.dumps({"schema": SCHEMA, "value": 7}).encode()
    blob = compress_canonical(canonical)
    ok = verified_canonical(
        blob,
        kind="content",
        schema=SCHEMA,
        sha256=_digest(canonical),
        size_bytes=len(canonical),
        limit=LIMIT,
    )
    assert ok == canonical
    cases = {
        "content_digest": {"sha256": _digest(canonical + b" ")},
        "content_size": {"size_bytes": len(canonical) + 1},
        "decompress_bound": {"size_bytes": len(canonical) - 1},
    }
    for code, override in cases.items():
        arguments: dict[str, Any] = {
            "kind": "content",
            "schema": SCHEMA,
            "sha256": _digest(canonical),
            "size_bytes": len(canonical),
            "limit": LIMIT,
            **override,
        }
        with pytest.raises(ScenarioIntegrityError) as refused:
            verified_canonical(blob, **arguments)
        assert refused.value.code == code, (code, refused.value.code)
    # A digest under another schema is another document's digest.
    with pytest.raises(ScenarioIntegrityError, match="result_digest"):
        verified_canonical(
            blob,
            kind="result",
            schema="schedule-cpm-result-v1",
            sha256=_digest(canonical),
            size_bytes=len(canonical),
            limit=LIMIT,
        )


def test_a_verified_document_is_one_json_object() -> None:
    document = {"schema": "schedule-cpm-result-v1", "status": "computed"}
    canonical = json.dumps(document).encode()
    decoded, raw = verified_document(
        compress_canonical(canonical),
        kind="result",
        schema="schedule-cpm-result-v1",
        sha256=_digest(canonical, "schedule-cpm-result-v1"),
        size_bytes=len(canonical),
        limit=LIMIT,
    )
    assert decoded == document and raw == canonical
    for bad in (b"[1, 2]", b"\xff\xfe not json"):
        with pytest.raises(ScenarioIntegrityError) as refused:
            verified_document(
                compress_canonical(bad),
                kind="output",
                schema=SCHEMA,
                sha256=_digest(bad),
                size_bytes=len(bad),
                limit=LIMIT,
            )
        assert refused.value.code == "output_decode"
