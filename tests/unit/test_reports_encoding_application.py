"""Reports Modernization WP05 B3/B5: `gzip+base64` through the canonical path.

`normalize` and `ApplicationService.invoke` over the FAST world's general
report fake: the public mapping of every decoder rule (no value echoed,
nothing written), the inline-maximum seam, the read's `encoded` round trip,
idempotent replay and conflict, and `reports.update` with gzip content. The
PostgreSQL behaviour is `tests/database/test_reports_encoding.py`'s. Every
byte is synthetic.
"""

from __future__ import annotations

import base64
import gzip
import hashlib
import json
import random
from typing import Any, Final

import pytest

from my_pa.adapters.normalization import normalize
from my_pa.application.commands import report_refusal
from my_pa.application.errors import ApplicationError, InvalidRequestError, SafeDetail
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.errors import ErrorCode
from my_pa.domain.identity.operation import Capability, permitted_purposes
from my_pa.domain.reports.content import INLINE_CONTENT_MAX_BYTES
from my_pa.domain.reports.errors import ReportValidationError
from tests.conftest import Scene, build_service

BODY: Final = "# Synthetic gzip report\n\nCompressed body text.\n"
#: Every rule token the decoder and the gzip validation path can raise.
RULE_TOKENS: Final = (
    "malformed_base64",
    "malformed_gzip",
    "original_size_mismatch",
    "original_digest_mismatch",
    "too_large",
    "expansion_ratio",
    "truncated",
    "trailing_data",
    "nested_stream",
    "uncompressed_size_mismatch",
    "uncompressed_digest_mismatch",
    "malformed_utf8",
    "too_deep",
    "duplicate_key",
    "malformed_json",
    "mixed_shape",
    "required",
    "malformed",
    "blank",
)
SIZE_RULES: Final = frozenset({"too_large", "expansion_ratio"})


def _gz(raw: bytes, level: int = 9) -> bytes:
    return gzip.compress(raw, compresslevel=level, mtime=0)


def _b64(data: bytes) -> str:
    return base64.b64encode(data).decode("ascii")


def _gzip_content(raw: bytes, fmt: str = "markdown", level: int = 9) -> dict[str, Any]:
    return {"format": fmt, "encoding": "gzip+base64", "encoded": _b64(_gz(raw, level))}


def _words(size: int) -> bytes:
    rng = random.Random(5)  # noqa: S311 - deterministic synthetic text, not a secret
    vocabulary = [f"w{rng.getrandbits(32):08x} ".encode() for _ in range(4096)]
    out = bytearray()
    while len(out) < size:
        out += rng.choice(vocabulary)
    return bytes(out[:size])


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


def _publish(content: dict[str, Any], key: str = "gzip-publish") -> dict[str, Any]:
    return {"title": "Synthetic gzip report", "content": content, "idempotency_key": key}


def _normalize_refusal(scene: Scene, payload: dict[str, Any]) -> ApplicationError:
    with pytest.raises(ApplicationError) as refused:
        normalize(
            Capability.REPORTS_PUBLISH.value,
            _wire(scene, Capability.REPORTS_PUBLISH, payload),
        )
    return refused.value


@pytest.mark.parametrize("rule", RULE_TOKENS)
def test_every_rule_is_invalid_request_content(rule: str) -> None:
    refusal = report_refusal(ReportValidationError("content.encoded", rule))
    assert isinstance(refusal, InvalidRequestError)
    expected = (
        (SafeDetail.CONTENT, SafeDetail.MAX_BYTES) if rule in SIZE_RULES else (SafeDetail.CONTENT,)
    )
    assert refusal.safe_details == expected


@pytest.mark.parametrize(
    "field",
    [
        "content.original_byte_count",
        "content.original_sha256",
        "content.uncompressed_byte_count",
        "content.uncompressed_sha256",
    ],
)
def test_a_declared_field_refusal_is_invalid_request_content(field: str) -> None:
    refusal = report_refusal(ReportValidationError(field, "type"))
    assert isinstance(refusal, InvalidRequestError)
    assert refusal.safe_details == (SafeDetail.CONTENT,)


@pytest.mark.parametrize(
    ("content", "details"),
    [
        (
            {"format": "markdown", "encoding": "gzip+base64", "encoded": "SECRET-not-base64"},
            ["content"],
        ),
        (_gzip_content(b"SECRET" * 1, level=9) | {"original_sha256": "0" * 64}, ["content"]),
        (
            {
                "format": "markdown",
                "encoding": "gzip+base64",
                "encoded": _b64(_gz(b"SECRET " * 200_000)),
            },
            ["content", "max_bytes"],
        ),
        (_gzip_content(b'{"SECRET": 1, "SECRET": 2}', fmt="json"), ["content"]),
    ],
)
def test_a_refusal_echoes_nothing_and_writes_nothing(
    scene: Scene, content: dict[str, Any], details: list[str]
) -> None:
    refusal = _normalize_refusal(scene, _publish(content))
    assert isinstance(refusal, InvalidRequestError)
    assert [item.value for item in refusal.safe_details] == details
    rendered = f"{refusal!s} {refusal!r} {refusal.args!r}"
    assert "SECRET" not in rendered
    assert content["encoded"][:16] not in rendered
    assert refusal.__context__ is None
    assert not scene.world.general_report_versions


def test_publish_and_read_round_trip_the_exact_encoded_string(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    content = _gzip_content(BODY.encode())
    original = _gz(BODY.encode())
    published = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, _publish(content)))
    assert published["content"]["decoded_sha256"] == hashlib.sha256(BODY.encode()).hexdigest()
    report_id = published["report_id"]
    read = _ok(_invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id}))
    payload = read["content"]
    assert payload["encoding"] == "gzip+base64"
    assert payload["body"] == BODY
    assert payload["encoded"] == content["encoded"]
    assert payload["original_sha256"] == hashlib.sha256(original).hexdigest()
    assert payload["original_byte_count"] == len(original)
    assert payload["decoded_byte_count"] == len(BODY.encode())
    assert "encoded_omitted" not in payload
    bare = _ok(
        _invoke(
            service, scene, Capability.REPORTS_READ, {"report_id": report_id, "include_body": False}
        )
    )
    assert {"body", "data", "encoded", "encoded_omitted"}.isdisjoint(bare["content"])
    assert bare["content"]["original_sha256"] == payload["original_sha256"]


def test_an_identity_read_gains_the_two_original_fields(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    published = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_PUBLISH,
            _publish({"format": "markdown", "body": BODY}, key="identity"),
        )
    )
    read = _ok(
        _invoke(service, scene, Capability.REPORTS_READ, {"report_id": published["report_id"]})
    )
    payload = read["content"]
    assert payload["original_sha256"] == payload["decoded_sha256"]
    assert payload["original_byte_count"] == payload["decoded_byte_count"]
    assert "encoded" not in payload
    assert "encoded_omitted" not in payload


@pytest.mark.parametrize("fmt", ["json", "mixed"])
def test_structured_gzip_content_reads_back_its_data(scene: Scene, fmt: str) -> None:
    service = build_service(scene.world, scene.providers)
    data = {"risk": 3, "items": [1, 2.5, "é"]}
    document: object = data if fmt == "json" else {"body": BODY, "data": data}
    content = _gzip_content(json.dumps(document, indent=2).encode(), fmt=fmt)
    published = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, _publish(content, key=fmt)))
    read = _ok(
        _invoke(service, scene, Capability.REPORTS_READ, {"report_id": published["report_id"]})
    )
    assert read["content"]["data"] == data
    assert read["content"]["encoded"] == content["encoded"]


def test_decoded_content_above_the_inline_maximum_is_refused_until_the_store_exists(
    scene: Scene,
) -> None:
    service = build_service(scene.world, scene.providers)
    # Random words: well under the 256:1 ratio, so only the size decides.
    at_bound = _words(INLINE_CONTENT_MAX_BYTES)
    accepted = _invoke(
        service, scene, Capability.REPORTS_PUBLISH, _publish(_gzip_content(at_bound), key="at")
    )
    _ok(accepted)
    over = _invoke(
        service,
        scene,
        Capability.REPORTS_PUBLISH,
        _publish(_gzip_content(at_bound + b"a"), key="over"),
    )
    assert over["error"]["code"] == ErrorCode.INVALID_REQUEST.value
    assert over["error"]["safe_details"] == ["content", "max_bytes"]
    assert len(scene.world.general_report_versions) == 1


def test_a_retry_replays_and_another_gzip_stream_under_the_key_conflicts(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    payload = _publish(_gzip_content(BODY.encode()), key="gzip-key")
    first = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, payload))
    again = _ok(_invoke(service, scene, Capability.REPORTS_PUBLISH, payload))
    assert again["replayed"] is True
    assert again["report_id"] == first["report_id"]
    # The same decoded body in other gzip bytes is another request.
    other = _publish(_gzip_content(BODY.encode(), level=1), key="gzip-key")
    assert other["content"]["encoded"] != payload["content"]["encoded"]
    conflict = _invoke(service, scene, Capability.REPORTS_PUBLISH, other)
    assert conflict["error"]["code"] == ErrorCode.CONFLICT.value
    assert conflict["error"]["safe_details"] == ["idempotency_key"]
    # And the identity body under the key too.
    identity = _publish({"format": "markdown", "body": BODY}, key="gzip-key")
    assert (
        _invoke(service, scene, Capability.REPORTS_PUBLISH, identity)["error"]["code"]
        == ErrorCode.CONFLICT.value
    )
    assert len(scene.world.general_report_versions) == 1


def _update(report_id: str, key: str, patch: dict[str, Any]) -> dict[str, Any]:
    return {
        "report_id": report_id,
        "expected_version": 1,
        "patch": patch,
        "change_reason": "A synthetic revision.",
        "idempotency_key": key,
    }


def test_update_takes_gzip_content_and_replays_or_conflicts_like_publish(scene: Scene) -> None:
    service = build_service(scene.world, scene.providers)
    published = _ok(
        _invoke(
            service,
            scene,
            Capability.REPORTS_PUBLISH,
            _publish({"format": "markdown", "body": BODY}, key="base"),
        )
    )
    report_id = published["report_id"]
    new_body = b"# Revised synthetic body\n"
    patch = {"content": _gzip_content(new_body)}
    updated = _ok(
        _invoke(service, scene, Capability.REPORTS_UPDATE, _update(report_id, "u1", patch))
    )
    assert updated["change_kind"] == "content"
    replay = _ok(
        _invoke(service, scene, Capability.REPORTS_UPDATE, _update(report_id, "u1", patch))
    )
    assert replay["replayed"] is True
    other = {"content": _gzip_content(new_body, level=1)}
    conflict = _invoke(service, scene, Capability.REPORTS_UPDATE, _update(report_id, "u1", other))
    assert conflict["error"]["code"] == ErrorCode.CONFLICT.value
    read = _ok(_invoke(service, scene, Capability.REPORTS_READ, {"report_id": report_id}))
    assert read["version_number"] == 2
    assert read["content"]["body"] == new_body.decode()
    assert read["content"]["encoded"] == patch["content"]["encoded"]


def test_an_invalid_gzip_patch_is_refused_naming_content(scene: Scene) -> None:
    with pytest.raises(ApplicationError) as refused:
        normalize(
            Capability.REPORTS_UPDATE.value,
            _wire(
                scene,
                Capability.REPORTS_UPDATE,
                _update(
                    "grpt_" + "a" * 26,
                    "bad",
                    {"content": {"format": "text", "encoding": "gzip+base64", "encoded": "AAAA"}},
                ),
            ),
        )
    assert isinstance(refused.value, InvalidRequestError)
    assert refused.value.safe_details == (SafeDetail.CONTENT,)
