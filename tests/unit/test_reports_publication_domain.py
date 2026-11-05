"""Reports Modernization WP02, contract B: inline content, manifest, intent digest.

Pure domain, FAST tier: no database, no clock, no network. Every value is synthetic.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
from datetime import UTC, date, datetime, timedelta, timezone
from typing import Any, Final

import pytest

from my_pa.domain.reports.content import (
    INLINE_CONTENT_MAX_BYTES,
    MAX_CONTENT_DATA_DEPTH,
    canonical_json,
    validate_content,
)
from my_pa.domain.reports.creator import CreatorKind, derive_creator
from my_pa.domain.reports.errors import ReportValidationError
from my_pa.domain.reports.manifest import (
    MAX_MANIFEST_CANONICAL_BYTES,
    ReportManifest,
    build_initial_manifest,
    manifest_digest,
)
from my_pa.domain.reports.publication import (
    PublicationRequest,
    RequestedAssociation,
    validate_client_intent_id,
)
from my_pa.domain.reports.values import ReportAssociation
from my_pa.domain.reports.vocabulary import (
    MANIFEST_SCHEMA,
    AssociationTargetKind,
    AssociationVerification,
    ContentEncoding,
    ContentFormat,
)

SECRET: Final = "synthetic-sensitive-value-7f3a"  # noqa: S105 - a synthetic marker
RECORDED: Final = datetime(2026, 11, 4, 12, 30, 0, 123456, tzinfo=UTC)
AUTHOR: Final = derive_creator(CreatorKind.LOCAL_PRINCIPAL, "prn_aaaa0001aaaa0001aaaa0001")


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _refused(value: object, field: str, code: str) -> ReportValidationError:
    with pytest.raises(ReportValidationError) as caught:
        validate_content(value)
    assert (caught.value.field, caught.value.code) == (field, code)
    return caught.value


# ---- content shapes ----------------------------------------------------------------


@pytest.mark.parametrize("fmt", ["markdown", "text"])
def test_textual_content_decodes_to_its_body_as_utf8(fmt: str) -> None:
    body = "# Synthetic héading\n\nbody ✓\n"
    content = validate_content({"format": fmt, "body": body})
    assert content.format is ContentFormat(fmt)
    assert content.encoding is ContentEncoding.IDENTITY
    assert content.decoded == body.encode("utf-8")
    assert content.decoded_sha256 == _sha(body.encode("utf-8"))
    assert content.decoded_byte_count == len(body.encode("utf-8"))
    assert content.canonical_sha256 is None
    assert content.original_sha256 == content.decoded_sha256


def test_json_content_decodes_to_canonical_json() -> None:
    data = {"b": [1, 2.5, None, True], "a": {"z": "é", "y": 0.0001}}
    content = validate_content({"format": "json", "data": data, "encoding": "identity"})
    expected = b'{"a":{"y":0.0001,"z":"\xc3\xa9"},"b":[1,2.5,null,true]}'
    assert content.decoded == expected
    assert content.decoded_sha256 == _sha(expected) == content.canonical_sha256


def test_mixed_content_is_the_canonical_envelope_of_body_and_data() -> None:
    content = validate_content({"format": "mixed", "body": "note", "data": {"k": 1}})
    expected = json.dumps(
        {"body": "note", "data": {"k": 1}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode()
    assert content.decoded == expected == b'{"body":"note","data":{"k":1}}'
    assert content.canonical_sha256 == content.decoded_sha256 == _sha(expected)
    assert (content.body, content.data) == ("note", {"k": 1})


def test_mixed_admits_empty_containers_and_json_refuses_them() -> None:
    assert validate_content({"format": "mixed", "body": "b", "data": {}}).data == {}
    assert validate_content({"format": "mixed", "body": "b", "data": []}).data == []
    _refused({"format": "json", "data": {}}, "content.data", "empty")
    _refused({"format": "json", "data": []}, "content.data", "empty")


@pytest.mark.parametrize("data", ["string", 7, 1.5, True, [0], {"k": None}])
def test_json_admits_any_top_level_value_but_null(data: object) -> None:
    assert validate_content({"format": "json", "data": data}).data == data


def test_negative_zero_is_hashed_as_the_zero_jsonb_reads_back() -> None:
    content = validate_content({"format": "json", "data": [-0.0]})
    assert content.decoded == b"[0.0]"


@pytest.mark.parametrize(
    ("value", "field", "code"),
    [
        ("markdown", "content", "type"),
        ({"body": "b"}, "content.format", "required"),
        ({"format": "html", "body": "b"}, "content.format", "unknown"),
        ({"format": "markdown", "body": "b", "data": 1}, "content", "unknown_field"),
        ({"format": "json", "data": 1, "body": "b"}, "content", "unknown_field"),
        ({"format": "text", "body": "b", "extra": 1}, "content", "unknown_field"),
        ({"format": "markdown"}, "content.body", "required"),
        ({"format": "json"}, "content.data", "required"),
        ({"format": "mixed", "body": "b"}, "content.data", "required"),
        ({"format": "markdown", "body": 3}, "content.body", "type"),
        ({"format": "markdown", "body": " \n\t "}, "content.body", "blank"),
        ({"format": "markdown", "body": ""}, "content.body", "blank"),
        ({"format": "text", "body": "a\x00b"}, "content.body", "malformed"),
        ({"format": "text", "body": "\ud800"}, "content.body", "malformed"),
        ({"format": "json", "data": None}, "content.data", "null"),
        ({"format": "mixed", "body": "b", "data": None}, "content.data", "null"),
        ({"format": "json", "data": [float("nan")]}, "content.data", "non_finite"),
        ({"format": "json", "data": [1e300]}, "content.data", "out_of_range"),
        ({"format": "json", "data": ["a\x00"]}, "content.data", "malformed"),
        ({"format": "json", "data": {"a\x00": 1}}, "content.data", "malformed"),
        ({"format": "json", "data": {1: 1}}, "content.data", "key_type"),
        ({"format": "json", "data": [(1, 2)]}, "content.data", "value_type"),
        ({"format": "json", "data": [10**5000]}, "content", "too_large"),
        (
            {"format": "markdown", "body": "b", "encoding": "gzip+base64"},
            "content.encoding",
            "unsupported_encoding",
        ),
        ({"format": "markdown", "body": "b", "encoding": "br"}, "content.encoding", "unknown"),
        ({"format": "markdown", "body": "b", "encoding": None}, "content.encoding", "unknown"),
    ],
)
def test_content_refusals(value: object, field: str, code: str) -> None:
    _refused(value, field, code)


def _nested(depth: int) -> object:
    value: object = 1
    for _ in range(depth):
        value = [value]
    return value


def test_data_depth_is_bounded_at_32() -> None:
    assert validate_content({"format": "json", "data": _nested(MAX_CONTENT_DATA_DEPTH)}).data
    _refused(
        {"format": "json", "data": _nested(MAX_CONTENT_DATA_DEPTH + 1)}, "content.data", "too_deep"
    )


def test_the_512_kib_boundary_is_accepted_at_the_limit_and_refused_one_byte_past() -> None:
    assert INLINE_CONTENT_MAX_BYTES == 524288
    at_limit = validate_content({"format": "markdown", "body": "x" * INLINE_CONTENT_MAX_BYTES})
    assert at_limit.decoded_byte_count == INLINE_CONTENT_MAX_BYTES
    _refused(
        {"format": "markdown", "body": "x" * (INLINE_CONTENT_MAX_BYTES + 1)}, "content", "too_large"
    )
    # Measured in decoded bytes, not code points: 2-byte characters reach it sooner.
    _refused(
        {"format": "text", "body": "é" * (INLINE_CONTENT_MAX_BYTES // 2 + 1)},
        "content",
        "too_large",
    )
    # A json value is measured on its canonical bytes: `"` + n + `"`.
    exact = "y" * (INLINE_CONTENT_MAX_BYTES - 2)
    assert validate_content({"format": "json", "data": exact}).decoded_byte_count == (
        INLINE_CONTENT_MAX_BYTES
    )
    _refused({"format": "json", "data": exact + "y"}, "content", "too_large")


def test_refusals_never_echo_the_value() -> None:
    cases: list[object] = [
        {"format": "markdown", "body": SECRET + "\x00"},
        {"format": SECRET, "body": "b"},
        {"format": "json", "data": {SECRET + "\x00": 1}},
        {"format": "json", "data": [SECRET + "\x00"]},
        {"format": "markdown", "body": "b", SECRET: 1},
        {"format": "markdown", "body": "b", "encoding": SECRET},
    ]
    for value in cases:
        with pytest.raises(ReportValidationError) as caught:
            validate_content(value)
        assert SECRET not in str(caught.value)
        assert SECRET not in repr(caught.value.args)
    with pytest.raises(ReportValidationError) as caught_intent:
        validate_client_intent_id(SECRET + " !")
    assert SECRET not in str(caught_intent.value)


# ---- request and intent digest -----------------------------------------------------


def _request(**overrides: object) -> PublicationRequest:
    fields: dict[str, Any] = {
        "title": "Synthetic report",
        "content": validate_content({"format": "markdown", "body": "# Body\n"}),
        "report_type": "weekly_note",
        "topics": ("alpha",),
        "tags": ("t1", "t2"),
        "summary": "A synthetic summary.",
        "report_date": date(2026, 11, 4),
        "coverage_start": datetime(2026, 11, 1, tzinfo=UTC),
        "coverage_end": datetime(2026, 11, 4, tzinfo=UTC),
        "associations": (
            RequestedAssociation(
                AssociationTargetKind.EXTERNAL_SOURCE, "https://x.test/a", "cites"
            ),
        ),
        "metadata": {"k": 1.0},
        "client_intent_id": None,
    }
    fields.update(overrides)
    return PublicationRequest(**fields)


def test_intent_digest_is_stable_and_normalized() -> None:
    first = _request()
    assert first.intent_digest == _request().intent_digest
    assert len(first.intent_digest) == 64
    # The same instant in another offset, and a list for a tuple, are the same intent.
    shifted = _request(
        coverage_start=datetime(2026, 11, 1, 1, tzinfo=timezone(timedelta(hours=1))),
        tags=["t1", "t2"],
    )
    assert shifted.intent_digest == first.intent_digest
    # An explicit identity encoding is the default one.
    explicit = _request(
        content=validate_content({"format": "markdown", "body": "# Body\n", "encoding": "identity"})
    )
    assert explicit.intent_digest == first.intent_digest


def test_intent_digest_is_sensitive_to_client_intent_id_and_to_every_caller_field() -> None:
    base = _request().intent_digest
    assert _request(client_intent_id="run-1").intent_digest != base
    assert (
        _request(client_intent_id="run-1").intent_digest
        != _request(client_intent_id="run-2").intent_digest
    )
    assert _request(title="Other").intent_digest != base
    assert _request(metadata={"k": 2}).intent_digest != base
    assert _request(associations=()).intent_digest != base
    assert (
        _request(content=validate_content({"format": "text", "body": "# Body\n"})).intent_digest
        != base
    )


@pytest.mark.parametrize("value", ["a", "A1._:-z", "9" + "x" * 127])
def test_client_intent_id_admits_the_pattern(value: str) -> None:
    assert validate_client_intent_id(value) == value


@pytest.mark.parametrize("value", ["", "-a", ".a", "a b", "a/b", "9" + "x" * 128, "é"])
def test_client_intent_id_refuses_outside_the_pattern(value: str) -> None:
    with pytest.raises(ReportValidationError) as caught:
        validate_client_intent_id(value)
    assert caught.value.code == "pattern"


def test_request_refusals() -> None:
    with pytest.raises(ReportValidationError, match="coverage_period: order"):
        _request(coverage_start=datetime(2026, 11, 5, tzinfo=UTC))
    with pytest.raises(ReportValidationError, match="coverage_start: naive"):
        _request(coverage_start=datetime(2026, 11, 1))
    with pytest.raises(ReportValidationError, match="report_date: type"):
        _request(report_date=datetime(2026, 11, 4, tzinfo=UTC))
    with pytest.raises(ReportValidationError, match="content: type"):
        _request(content={"format": "markdown", "body": "b"})
    duplicate = RequestedAssociation(AssociationTargetKind.PROJECT, "prj_aaaaaaaa", "about")
    with pytest.raises(ReportValidationError, match="associations: duplicate"):
        _request(associations=(duplicate, duplicate))


def test_request_is_frozen() -> None:
    with pytest.raises(dataclasses.FrozenInstanceError):
        _request().title = "x"  # type: ignore[misc]


# ---- manifest ----------------------------------------------------------------------


def _manifest(request: PublicationRequest) -> ReportManifest:
    stored = tuple(
        item.as_stored(AssociationVerification.ASSERTED) for item in request.associations
    )
    return build_initial_manifest(
        request,
        report_id="grpt_aaaaaaaa",
        version_id="grver_aaaaaaaa",
        content_id="grcnt_aaaaaaaa",
        associations=stored,
        recorded_at=RECORDED,
        author=AUTHOR,
    )


def test_manifest_is_deterministic_principal_free_and_digested() -> None:
    request = _request()
    manifest = _manifest(request)
    assert manifest.canonical == canonical_json(manifest.document)
    assert manifest.sha256 == _sha(manifest.canonical) == manifest_digest(manifest.document)
    assert _manifest(request).canonical == manifest.canonical
    document = manifest.document
    assert document["schema"] == MANIFEST_SCHEMA
    assert (document["version_number"], document["supersedes_version_id"]) == (1, None)
    assert document["change_kind"] == "initial"
    assert document["change_reason"] is None  # WP03 D10: the key exists, null for v1
    assert document["recorded_at"] == "2026-11-04T12:30:00.123456Z"
    assert document["coverage_start"] == "2026-11-01T00:00:00.000000Z"
    assert document["content"]["decoded_sha256"] == request.content.decoded_sha256
    assert document["content"]["storage_kind"] == "inline"
    assert document["associations"][0]["ordinal"] == 0
    assert document["associations"][0]["verification"] == "asserted"
    # WP05 A3: the server-derived author, a pseudonym, never the Principal.
    assert document["author"] == {"kind": "local_principal", "id": AUTHOR.creator_id}
    assert "prn_" not in manifest.canonical.decode()
    assert not any("principal" in key or "owner" in key for key in document)


def test_manifest_is_bounded_at_43690_canonical_bytes() -> None:
    assert MAX_MANIFEST_CANONICAL_BYTES == 43690
    # 64 external associations with 512-character refs push the manifest past the bound.
    long_refs = tuple(
        RequestedAssociation(
            AssociationTargetKind.EXTERNAL_SOURCE, f"{n:03d}" + "r" * 509, "cites", "v" * 512
        )
        for n in range(64)
    )
    with pytest.raises(ReportValidationError) as caught:
        _manifest(_request(associations=long_refs))
    assert (caught.value.field, caught.value.code) == ("manifest", "manifest_too_large")
    # Fewer of them fit: find the largest accepted count and check it is under the bound.
    accepted = None
    for count in range(64, 0, -1):
        try:
            accepted = _manifest(_request(associations=long_refs[:count]))
        except ReportValidationError:
            continue
        break
    assert accepted is not None
    assert len(accepted.canonical) <= MAX_MANIFEST_CANONICAL_BYTES


def test_requested_association_validates_like_the_stored_form() -> None:
    with pytest.raises(ReportValidationError, match="relation: pattern"):
        RequestedAssociation(AssociationTargetKind.PROJECT, "prj_aaaaaaaa", "Bad Relation")
    stored = RequestedAssociation(AssociationTargetKind.ENTITY, "ent_aaaaaaaa", "about").as_stored(
        AssociationVerification.VERIFIED
    )
    assert isinstance(stored, ReportAssociation)
    assert stored.verification is AssociationVerification.VERIFIED
