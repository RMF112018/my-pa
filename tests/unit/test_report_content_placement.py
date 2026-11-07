"""Reports Modernization WP05 C3-C7 in the FAST tier: placement, read, scan, settings.

`normalize` and `ApplicationService.invoke` over the FAST world's report fake
and `InMemoryReportContentStore`. What it proves:

* the settings: `MY_PA_REPORT_CONTENT_ROOT` defaults empty,
  `MY_PA_REPORT_CONTENT_INLINE_MAX_BYTES` defaults 524,288 and refuses
  anything outside 1..524,288; the service refuses such a threshold too;
* placement at the threshold boundary: exactly the threshold is inline,
  one byte more is `managed_blob` (one `put`), and with no store it is
  `invalid_request` `content`/`max_bytes`, nothing written;
* a `put` failure writes nothing and answers `internal_error`;
* a `managed_blob` read returns the exact body within the response bound,
  `body_omitted` above it (with every digest), `encoded` for gzip within the
  bound; every read verifies the parts, so a missing or tampered object is
  `internal_error` with no body, even with `include_body` false;
* a metadata-only update of a blob head reuses its content (no new `put`);
  history, list and search never touch the store;
* the scan reports missing, mismatched (size/digest) and orphan objects.

Every byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import random
from typing import Any, Final

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.report_content import (
    ReportContentMismatch,
    back_up_report_content,
    scan_report_content,
)
from my_pa.application.service import ApplicationService
from my_pa.bootstrap.settings import Settings, SettingsError, load_settings
from my_pa.contracts.ports import ReportContentPart
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES
from my_pa.domain.reports.vocabulary import READ_INLINE_CONTENT_MAX_BYTES
from tests.conftest import (
    DEFAULT_LIMITS,
    FakeUnitOfWork,
    InMemoryReportContentStore,
    Scene,
    build_service,
)

THRESHOLD: Final = 64
_URL: Final = "postgresql+psycopg://synthetic@127.0.0.1/synthetic"


def _wire(scene: Scene, capability: Capability, payload: dict[str, Any]) -> dict[str, Any]:
    (purpose,) = permitted_purposes(capability)
    return {
        "request_id": f"req-{capability.value}",
        "purpose": purpose.value,
        "principal_id": scene.principal.principal_id,
        "requested_at": "2026-11-05T12:00:00Z",
        "payload": payload,
    }


def _invoke(
    service: ApplicationService, scene: Scene, capability: Capability, payload: dict[str, Any]
) -> dict[str, Any]:
    metadata, command = normalize(capability.value, _wire(scene, capability, payload))
    return service.invoke(metadata, command, principal=scene.principal).model_dump(mode="json")


def _ok(answer: dict[str, Any]) -> dict[str, Any]:
    assert answer["error"] is None, answer["error"]
    result = answer["result"]
    assert isinstance(result, dict)
    return result


def _text(size: int, seed: int = 3) -> str:
    rng = random.Random(seed)  # noqa: S311 - deterministic synthetic text, not a secret
    words = [f"w{rng.getrandbits(24):06x}" for _ in range(512)]
    out: list[str] = ["# Synthetic"]
    length = len(out[0])
    while length < size:
        word = " " + rng.choice(words)
        out.append(word)
        length += len(word)
    return "".join(out)[:size]


def _publish(content: dict[str, Any], key: str) -> dict[str, Any]:
    return {"title": "Synthetic blob report", "content": content, "idempotency_key": key}


def _markdown(size: int) -> dict[str, Any]:
    return {"format": "markdown", "body": _text(size)}


def _gzip(raw: bytes) -> dict[str, Any]:
    encoded = base64.b64encode(gzip.compress(raw, compresslevel=9, mtime=0)).decode("ascii")
    return {"format": "text", "encoding": "gzip+base64", "encoded": encoded}


def _service(scene: Scene, store: InMemoryReportContentStore | None) -> ApplicationService:
    return build_service(
        scene.world,
        scene.providers,
        report_content_store=store,
        report_content_inline_max_bytes=THRESHOLD,
    )


def _read(
    service: ApplicationService, scene: Scene, report_id: str, **extra: object
) -> dict[str, Any]:
    return _invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id, **extra})


# ---- settings ----------------------------------------------------------------------


def test_the_settings_default_to_no_store_and_the_inline_maximum() -> None:
    settings = load_settings({"MY_PA_DATABASE_URL": _URL})
    assert settings.report_content_root == ""
    assert settings.report_content_inline_max_bytes == INLINE_CONTENT_MAX_BYTES == 524288
    assert Settings.model_fields["report_content_root"].repr is True  # not a secret
    configured = load_settings(
        {
            "MY_PA_DATABASE_URL": _URL,
            "MY_PA_REPORT_CONTENT_ROOT": "/synthetic/report-content",
            "MY_PA_REPORT_CONTENT_INLINE_MAX_BYTES": "1",
        }
    )
    assert configured.report_content_root == "/synthetic/report-content"
    assert configured.report_content_inline_max_bytes == 1


@pytest.mark.parametrize("value", ["0", "-1", "524289", "1048576", "abc", "1.5"])
def test_an_inline_threshold_outside_its_bounds_refuses_to_start(value: str) -> None:
    with pytest.raises(SettingsError, match="MY_PA_REPORT_CONTENT_INLINE_MAX_BYTES"):
        load_settings({"MY_PA_DATABASE_URL": _URL, "MY_PA_REPORT_CONTENT_INLINE_MAX_BYTES": value})


@pytest.mark.parametrize("value", [0, 524289, True])
def test_the_service_refuses_an_out_of_bounds_threshold(scene: Scene, value: object) -> None:
    with pytest.raises(ValueError, match="threshold"):
        ApplicationService(
            unit_of_work=lambda: FakeUnitOfWork(scene.world),
            limits=DEFAULT_LIMITS,
            report_content_inline_max_bytes=value,  # type: ignore[arg-type]
        )


# ---- placement ---------------------------------------------------------------------


def test_exactly_the_threshold_is_inline_and_one_byte_more_is_a_blob(scene: Scene) -> None:
    store = InMemoryReportContentStore()
    service = _service(scene, store)
    at = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, _publish(_markdown(64), "at")))
    assert store.puts == 0
    over = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, _publish(_markdown(65), "over")))
    assert store.puts == 1
    assert store.stored_object_ids() == (over["content"]["content_id"],)
    inline = _ok(_read(service, scene, at["report_id"]))["content"]
    blob = _ok(_read(service, scene, over["report_id"]))["content"]
    assert inline["storage_kind"] == "inline"
    assert blob["storage_kind"] == "managed_blob"
    assert blob["body"] == _text(65)
    assert blob["decoded_byte_count"] == 65
    stored = store.objects[over["content"]["content_id"]][ReportContentPart.DECODED]
    assert stored == _text(65).encode()


def test_without_a_store_content_above_the_threshold_is_refused_and_nothing_written(
    scene: Scene,
) -> None:
    service = _service(scene, None)
    answer = _invoke(service, scene, Capability.REPORTS_PUBLISH, _publish(_markdown(65), "x"))
    assert answer["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert answer["error"]["safe_details"] == ["content", "max_bytes"]
    assert not scene.world.general_report_versions
    assert not scene.world.general_report_receipts


def test_a_failed_put_writes_nothing(scene: Scene) -> None:
    store = InMemoryReportContentStore()
    store.fail_puts = True
    service = _service(scene, store)
    answer = _invoke(service, scene, Capability.REPORTS_PUBLISH, _publish(_markdown(200), "f"))
    assert answer["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    assert store.puts == 1
    assert store.objects == {}
    assert not scene.world.general_report_versions
    assert not scene.world.general_report_receipts


# ---- read --------------------------------------------------------------------------


def test_a_blob_read_within_the_bound_returns_the_exact_gzip_and_body(scene: Scene) -> None:
    store = InMemoryReportContentStore()
    service = _service(scene, store)
    raw = _text(300).encode()
    content = _gzip(raw)
    published = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, _publish(content, "g")))
    object_id = published["content"]["content_id"]
    assert set(store.objects[object_id]) == {ReportContentPart.DECODED, ReportContentPart.ORIGINAL}
    read = _ok(_read(service, scene, published["report_id"]))["content"]
    assert read["body"] == raw.decode()
    assert read["encoded"] == content["encoded"]
    assert read["decoded_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "body_omitted" not in read
    assert "encoded_omitted" not in read


def test_a_blob_above_the_response_bound_is_marked_body_omitted(scene: Scene) -> None:
    store = InMemoryReportContentStore()
    service = _service(scene, store)
    raw = _text(READ_INLINE_CONTENT_MAX_BYTES + 1).encode()
    content = _gzip(raw)
    published = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, _publish(content, "big")))
    read = _ok(_read(service, scene, published["report_id"]))["content"]
    assert read["body_omitted"] == "exceeds_response_bound"
    # WP06 T16: beside the omission, the chunked read of the decoded part.
    assert read["body_chunked_read"] == {
        "capability": "reports.transfer.read_chunk",
        "part": "decoded",
        "byte_count": len(raw),
        "sha256": hashlib.sha256(raw).hexdigest(),
    }
    assert "body" not in read
    assert "data" not in read
    # The gzip bytes fit the bound, so the exact upload is still returned.
    assert read["encoded"] == content["encoded"]
    assert "encoded_chunked_read" not in read
    assert read["decoded_byte_count"] == len(raw)
    assert read["decoded_sha256"] == hashlib.sha256(raw).hexdigest()
    bare = _ok(_read(service, scene, published["report_id"], include_body=False))["content"]
    assert {
        "body",
        "data",
        "body_omitted",
        "encoded",
        "encoded_omitted",
        "body_chunked_read",
        "encoded_chunked_read",
    }.isdisjoint(bare)


@pytest.mark.parametrize("include_body", [True, False])
@pytest.mark.parametrize("damage", ["missing", "tampered", "original"])
def test_a_missing_or_tampered_object_is_internal_error_with_no_body(
    scene: Scene, include_body: bool, damage: str
) -> None:
    store = InMemoryReportContentStore()
    service = _service(scene, store)
    raw = _text(400).encode()
    published = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, _publish(_gzip(raw), "d")))
    object_id = published["content"]["content_id"]
    if damage == "missing":
        del store.objects[object_id]
    elif damage == "tampered":
        store.objects[object_id][ReportContentPart.DECODED] = raw[:-1] + b"X"
    else:
        original = bytearray(store.objects[object_id][ReportContentPart.ORIGINAL])
        original[10] ^= 0xFF
        store.objects[object_id][ReportContentPart.ORIGINAL] = bytes(original)
    answer = _read(service, scene, published["report_id"], include_body=include_body)
    assert answer["error"]["code"] == ErrorCode.INTERNAL_ERROR.value
    assert answer["result"] is None
    rendered = repr(answer)
    assert raw[:40].decode() not in rendered
    assert published["content"]["decoded_sha256"] not in rendered


def test_a_blob_version_in_a_process_without_a_store_is_internal_error(scene: Scene) -> None:
    store = InMemoryReportContentStore()
    published = _ok(
        _invoke(
            _service(scene, store),
            scene,
            Capability.REPORTS_PUBLISH,
            _publish(_markdown(100), "n"),
        )
    )
    answer = _read(_service(scene, None), scene, published["report_id"])
    assert answer["error"]["code"] == ErrorCode.INTERNAL_ERROR.value


def test_a_metadata_update_of_a_blob_head_reuses_it_and_history_never_reads_the_store(
    scene: Scene,
) -> None:
    store = InMemoryReportContentStore()
    service = _service(scene, store)
    published = _ok(
        _invoke(service, scene, Capability.REPORTS_PUBLISH, _publish(_markdown(150), "m"))
    )
    report_id = published["report_id"]
    updated = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_UPDATE,
            {
                "report_id": report_id,
                "expected_version": 1,
                "patch": {"title": "Renamed synthetic"},
                "change_reason": "Synthetic rename.",
                "idempotency_key": "m-u",
            },
        )
    )
    assert updated["change_kind"] == "metadata"
    assert updated["content_id"] == published["content"]["content_id"]
    assert store.puts == 1
    read = _ok(_read(service, scene, report_id))
    assert read["version_number"] == 2
    assert read["content"]["storage_kind"] == "managed_blob"
    assert read["content"]["body"] == _text(150)
    # The store emptied: history, list and search still answer (they never read it).
    store.objects.clear()
    history = _ok(_invoke(service, scene, Capability.REPORTS_HISTORY, {"report_id": report_id}))
    assert [item["content"]["storage_kind"] for item in history["items"]] == ["managed_blob"] * 2
    listed = _ok(_invoke(service, scene, Capability.REPORTS_LIST, {"plane": "standalone"}))
    assert [item["report_id"] for item in listed["items"]] == [report_id]
    found = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_SEARCH,
            {"plane": "standalone", "query": _text(150).split()[2]},
        )
    )
    assert [item["report_id"] for item in found["items"]] == [report_id]


# ---- reconciliation ------------------------------------------------------------------


def test_the_scan_reports_missing_mismatched_and_orphaned_objects(scene: Scene) -> None:
    store = InMemoryReportContentStore()
    service = _service(scene, store)
    ids = [
        _ok(
            _invoke(
                service,
                scene,
                Capability.REPORTS_PUBLISH,
                _publish(_gzip(_text(200 + n, seed=n).encode()), f"s{n}"),
            )
        )["content"]["content_id"]
        for n in range(4)
    ]
    principal = scene.principal.principal_id
    repository = FakeUnitOfWork(scene.world).general_reports
    clean = scan_report_content(repository, store, principal_id=principal)
    assert clean.checked == 4
    assert clean.consistent
    del store.objects[ids[0]][ReportContentPart.ORIGINAL]
    decoded = store.objects[ids[1]][ReportContentPart.DECODED]
    store.objects[ids[1]][ReportContentPart.DECODED] = decoded + b"!"
    third = store.objects[ids[2]][ReportContentPart.DECODED]
    store.objects[ids[2]][ReportContentPart.DECODED] = b"X" + third[1:]
    orphan = "grcnt_" + "0" * 32
    store.objects[orphan] = {ReportContentPart.DECODED: b"orphan"}
    scan = scan_report_content(repository, store, principal_id=principal)
    assert scan.checked == 4
    assert scan.missing == ((ids[0], ReportContentPart.ORIGINAL),)
    assert set(scan.mismatched) == {
        ReportContentMismatch(ids[1], ReportContentPart.DECODED, "size"),
        ReportContentMismatch(ids[2], ReportContentPart.DECODED, "digest"),
    }
    assert scan.orphans == (orphan,)
    assert not scan.consistent
    # Another Principal's scan checks none of these rows, and still sees the orphan only.
    other = scan_report_content(repository, store, principal_id="prn_" + "f" * 24)
    assert other.checked == 0
    assert other.orphans == (orphan,)


def test_a_backup_copies_verified_objects_and_refuses_a_damaged_one(scene: Scene) -> None:
    store = InMemoryReportContentStore()
    service = _service(scene, store)
    for n in range(2):
        _ok(
            _invoke(
                service,
                scene,
                Capability.REPORTS_PUBLISH,
                _publish(_markdown(100 + n), f"b{n}"),
            )
        )
    repository = FakeUnitOfWork(scene.world).general_reports
    destination = InMemoryReportContentStore()
    summary = back_up_report_content(
        repository, store, destination, principal_id=scene.principal.principal_id
    )
    assert (summary.objects, summary.copied, summary.already_present) == (2, 2, 0)
    assert destination.objects == store.objects
    again = back_up_report_content(
        repository, store, destination, principal_id=scene.principal.principal_id
    )
    assert (again.copied, again.already_present) == (0, 2)
