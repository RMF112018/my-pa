"""Reports Modernization WP05 corrective B-4: gzip content decodes under one permit.

Through `normalize` and `ApplicationService.invoke` over FAST worlds (one per
thread, so only the process-wide permit is shared):

* `REPORT_CONTENT_DECODE_PERMITS` is 1 and two concurrent gzip publishes never
  decode at the same time; an identity publish never waits on the permit;
* without a report content store a gzip upload is inflated at most to the
  inline threshold plus one piece before it is refused `content`/`max_bytes`;
* eight concurrent 16 MiB gzip publishes (store composed) peak at about one
  request's live memory.

Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gc
import gzip
import json
import random
import string
import threading
import time
import tracemalloc
import zlib
from collections.abc import Callable
from pathlib import Path
from typing import Any, Final

import pytest

import my_pa.application.service as service_module
import my_pa.domain.reports.content as content_module
from my_pa.adapters.normalization import normalize
from my_pa.application.service import REPORT_CONTENT_DECODE_PERMITS, ApplicationService
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.reports import encoding
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES, validate_content
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.vocabulary import (
    DECODE_CHUNK_BYTES,
    MAX_CONTENT_DATA_VALUES,
    MAX_DECODED_CONTENT_BYTES,
    MAX_EXPANSION_RATIO,
)
from my_pa.infrastructure.report_content_stores.filesystem import FilesystemReportContentStore
from tests.conftest import Scene, World, build_service

_RNG: Final = random.Random(3)  # noqa: S311 - deterministic synthetic text, not a secret
#: Random characters: enough gzip bytes that large inputs stay under 256:1.
_PAD: Final = "".join(_RNG.choice(string.ascii_letters + string.digits) for _ in range(100_000))


def _gzip(fmt: str, raw: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    return {"format": fmt, "encoding": "gzip+base64", "encoded": encoded}


def _publish(
    service: ApplicationService, scene: Scene, content: dict[str, Any], key: str
) -> dict[str, Any]:
    (purpose,) = permitted_purposes(Capability.REPORTS_PUBLISH)
    wire = {
        "request_id": f"req-{key}",
        "purpose": purpose.value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-11-05T12:00:00Z",
        "payload": {"title": "Synthetic report", "content": content, "idempotency_key": key},
    }
    metadata, command = normalize(Capability.REPORTS_PUBLISH.value, wire)
    return service.invoke(metadata, command, principal=scene.principal).model_dump(mode="json")


def _scene(fixture_root: Path, **kwargs: Any) -> tuple[ApplicationService, Scene]:  # noqa: ANN401
    world = World()
    scene = Scene(world, fixture_root)
    return build_service(world, scene.providers, **kwargs), scene


def _in_threads(count: int, work: Callable[[int], dict[str, Any]]) -> list[dict[str, Any]]:
    barrier = threading.Barrier(count)
    answers: list[dict[str, Any]] = [{} for _ in range(count)]

    def run(index: int) -> None:
        barrier.wait()
        answers[index] = work(index)

    threads = [threading.Thread(target=run, args=(index,)) for index in range(count)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)
        assert not thread.is_alive()
    return answers


def test_one_permit_is_the_frozen_bound() -> None:
    assert REPORT_CONTENT_DECODE_PERMITS == 1
    permit = service_module._REPORT_CONTENT_DECODE_PERMIT
    assert isinstance(permit, type(threading.BoundedSemaphore()))
    assert permit.acquire(blocking=False)
    try:
        assert not permit.acquire(blocking=False)
    finally:
        permit.release()


def test_concurrent_gzip_publishes_never_decode_at_the_same_time(
    monkeypatch: pytest.MonkeyPatch, fixture_root: Path
) -> None:
    decode: Callable[..., tuple[bytes, bytes]] = vars(content_module)["decode_gzip_base64"]
    lock = threading.Lock()
    state = {"in_flight": 0, "max_in_flight": 0, "calls": 0}

    def observed(*args: Any, **kwargs: Any) -> tuple[bytes, bytes]:  # noqa: ANN401
        with lock:
            state["in_flight"] += 1
            state["calls"] += 1
            state["max_in_flight"] = max(state["max_in_flight"], state["in_flight"])
        try:
            time.sleep(0.15)  # wide enough for an unbounded build to overlap
            return decode(*args, **kwargs)
        finally:
            with lock:
                state["in_flight"] -= 1

    monkeypatch.setattr(content_module, "decode_gzip_base64", observed)
    services = [_scene(fixture_root) for _ in range(4)]
    answers = _in_threads(
        4,
        lambda index: _publish(
            *services[index], _gzip("markdown", b"# Synthetic body\n"), f"k{index}"
        ),
    )
    assert all(answer["error"] is None for answer in answers), answers
    assert state["calls"] == 4  # command construction decodes nothing
    assert state["max_in_flight"] == 1


def test_an_identity_publish_does_not_wait_on_the_permit(fixture_root: Path) -> None:
    service, scene = _scene(fixture_root)
    permit = service_module._REPORT_CONTENT_DECODE_PERMIT
    assert permit.acquire(timeout=5)
    try:
        identity: dict[str, Any] = {}
        gzipped: dict[str, Any] = {}
        first = threading.Thread(
            target=lambda: identity.update(
                _publish(service, scene, {"format": "markdown", "body": "# Plain\n"}, "plain")
            )
        )
        second = threading.Thread(
            target=lambda: gzipped.update(
                _publish(service, scene, _gzip("markdown", b"# Gzip\n"), "gzip")
            )
        )
        first.start()
        second.start()
        first.join(timeout=10)
        assert not first.is_alive()
        assert identity["error"] is None
        second.join(timeout=0.5)
        assert second.is_alive()  # the gzip publish waits for the permit
    finally:
        permit.release()
    second.join(timeout=10)
    assert not second.is_alive()
    assert gzipped["error"] is None


class _CountingInflater:
    def __init__(self) -> None:
        self._inner = zlib.decompressobj(wbits=31)
        self.produced = 0

    def decompress(self, data: bytes, max_length: int = 0) -> bytes:
        piece = self._inner.decompress(data, max_length)
        self.produced += len(piece)
        return piece

    def __getattr__(self, name: str) -> object:
        return getattr(self._inner, name)


def test_without_a_store_inflation_stops_at_the_inline_threshold(
    monkeypatch: pytest.MonkeyPatch, fixture_root: Path, tmp_path: Path
) -> None:
    made: list[_CountingInflater] = []

    def counting() -> _CountingInflater:
        made.append(_CountingInflater())
        return made[-1]

    monkeypatch.setattr(encoding, "_new_inflater", counting)
    raw = (_PAD + " words" * (2 * 1024 * 1024 // 6)).encode()  # ~2.1 MiB decoded
    service, scene = _scene(fixture_root)
    answer = _publish(service, scene, _gzip("text", raw), "storeless")
    assert answer["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert answer["error"]["safe_details"] == ["content", "max_bytes"]
    (inflater,) = made
    assert inflater.produced <= INLINE_CONTENT_MAX_BYTES + DECODE_CHUNK_BYTES
    assert not scene.world.general_report_versions
    # With a store composed the same upload is decoded in full and accepted.
    made.clear()
    (tmp_path / "store").mkdir()
    store = FilesystemReportContentStore((tmp_path / "store").resolve())
    stored_service, stored_scene = _scene(fixture_root, report_content_store=store)
    accepted = _publish(stored_service, stored_scene, _gzip("text", raw), "stored")
    assert accepted["error"] is None, accepted["error"]
    assert made[0].produced == len(raw)


def test_eight_concurrent_16_mib_publishes_peak_at_about_one_request(
    fixture_root: Path, tmp_path: Path
) -> None:
    # 262,142 long strings filling 16 MiB decoded: the worst accepted shape
    # (one request about 93 MiB live; eight unbounded about 469 MiB, measured).
    count = MAX_CONTENT_DATA_VALUES - 2
    size = (MAX_DECODED_CONTENT_BYTES - 200_000) // count - 3
    items = ['"' + "s" * size + '"'] * count + ['"' + _PAD + '"']
    content = _gzip("json", ("[" + ",".join(items) + "]").encode())
    del items
    (tmp_path / "store").mkdir()
    store = FilesystemReportContentStore((tmp_path / "store").resolve())
    services = [_scene(fixture_root, report_content_store=store) for _ in range(8)]

    def one(index: int) -> dict[str, Any]:
        answer = _publish(*services[index], dict(content), f"big{index}")
        # Drop this world's copy of the stored version as soon as it answers.
        services[index] = (None, None)  # type: ignore[assignment]
        return answer

    gc.collect()
    tracemalloc.start()
    try:
        answers = _in_threads(8, one)
        peak = tracemalloc.get_traced_memory()[1] / 2**20
    finally:
        tracemalloc.stop()
    assert all(answer["error"] is None for answer in answers)
    assert peak < 160  # MiB: one request is ~93; without the permit ~469


def test_store_less_pretty_json_is_bounded_by_its_gunzipped_bytes(
    fixture_root: Path, tmp_path: Path
) -> None:
    # WP05 corrective B5-1: canonical JSON well under the inline threshold,
    # pretty-printed far above it. Without a store the gunzipped bytes are the
    # bound (the memory guard); with one, the decoded content decides placement.
    data = [
        {"key": f"value {index:06d} {_PAD[index % 1000 : index % 1000 + 40]}"}
        for index in range(4000)
    ]
    canonical = json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    pretty = json.dumps(data, indent=16)
    assert len(canonical.encode()) < INLINE_CONTENT_MAX_BYTES < len(pretty.encode())
    content = _gzip("json", pretty.encode())

    service, scene = _scene(fixture_root)
    refused = _publish(service, scene, content, "pretty-storeless")
    assert refused["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert refused["error"]["safe_details"] == ["content", "max_bytes"]
    assert not scene.world.general_report_versions

    (tmp_path / "store").mkdir()
    store = FilesystemReportContentStore((tmp_path / "store").resolve())
    stored_service, stored_scene = _scene(fixture_root, report_content_store=store)
    accepted = _publish(stored_service, stored_scene, content, "pretty-stored")
    assert accepted["error"] is None, accepted["error"]
    result = accepted["result"]
    assert result["content"]["decoded_byte_count"] == len(canonical.encode())
    (stored,) = stored_scene.world.general_report_versions.values()
    assert stored.storage_kind.value == "inline"
    assert store.stored_object_ids() == ()


def _random_text(rng: random.Random, size: int) -> str:
    return "".join(rng.choice(string.ascii_letters + string.digits) for _ in range(size))


@pytest.mark.parametrize("shape", ["gunzipped_over_16_mib", "gunzipped_over_256_to_1"])
def test_with_a_store_the_gunzipped_bytes_carry_the_size_and_ratio_bounds(
    fixture_root: Path, tmp_path: Path, shape: str
) -> None:
    # WP05 corrective B6-1: pretty-printed JSON whose CANONICAL form is within
    # 16 MiB and 256:1 is still refused, because both bounds are measured on
    # the gunzipped bytes as uploaded -- what the describe text now states.
    rng = random.Random(7)  # noqa: S311 - deterministic synthetic text, not a secret
    if shape == "gunzipped_over_16_mib":
        data: list[str] = ["s" * 60] * 200_000 + [_random_text(rng, 200_000)]
        pretty = json.dumps(data, indent=40).encode()
        rule = "too_large"
    else:
        data = [_random_text(rng, 12) for _ in range(1000)]
        pretty = json.dumps(data, indent=8000).encode()
        rule = "expansion_ratio"
    canonical = json.dumps(data, separators=(",", ":"), ensure_ascii=False).encode()
    original = gzip.compress(pretty, compresslevel=6, mtime=0)
    assert len(canonical) <= MAX_DECODED_CONTENT_BYTES
    assert len(canonical) <= MAX_EXPANSION_RATIO * len(original)
    if rule == "too_large":
        assert len(pretty) > MAX_DECODED_CONTENT_BYTES
        assert len(pretty) <= MAX_EXPANSION_RATIO * len(original)
    else:
        assert len(pretty) <= MAX_DECODED_CONTENT_BYTES
        assert len(pretty) > MAX_EXPANSION_RATIO * len(original)
    content = {
        "format": "json",
        "encoding": "gzip+base64",
        "encoded": base64.b64encode(original).decode("ascii"),
    }
    with pytest.raises(ReportValidationError) as refused:
        validate_content(content)
    assert (refused.value.field, refused.value.code) == ("content.encoded", rule)

    (tmp_path / "store").mkdir()
    store = FilesystemReportContentStore((tmp_path / "store").resolve())
    service, scene = _scene(fixture_root, report_content_store=store)
    answer = _publish(service, scene, content, f"pretty-{shape}")
    assert answer["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert answer["error"]["safe_details"] == ["content", "max_bytes"]
    assert not scene.world.general_report_versions
    assert store.stored_object_ids() == ()
