"""Reports Modernization WP06 Part C layers 1-4: the bounded chunked transfer commands.

The five `reports.transfer.*` capabilities' classification (layers 1-2), their
commands, closed MCP JSON schemas and normalization (layers 3-4), and the
transfer reference variant of `reports.publish` `content` / `reports.update`
`patch.content` (T10, shape only). Handlers are W3b's: the five are
registered with a placeholder that answers `unsupported`, and the four uploads
are withheld unless a report content store and the transfer staging are both
composed (T14).

Every identifier, digest and byte here is synthetic.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any, Final

import jsonschema
import pytest

from my_pa.adapters.mcp.tools import payload_schema_for
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.application.commands import (
    TRANSFER_CHUNK_MAX_BASE64_CHARACTERS,
    AbortReportTransfer,
    AppendReportTransfer,
    BeginReportTransfer,
    FinalizeReportTransfer,
    PublishGeneralReport,
    ReadReportTransferChunk,
    UpdateGeneralReport,
    publication_request,
    transfer_declaration,
)
from my_pa.application.errors import ApplicationError, SafeDetail
from my_pa.application.service import (
    _HANDLERS,
    _REPORT_TRANSFER_UPLOAD_CAPABILITIES,
)
from my_pa.domain.identity.chatllm_capability_policy import (
    CHATLLM_CAPABILITY_POLICY,
    ChatLLMCapabilityClass,
)
from my_pa.domain.identity.operation import (
    Capability,
    is_destructive_capability,
    is_operator_only,
    is_write_capability,
    permitted_purposes,
)
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.policy.decision import _SCOPELESS
from my_pa.domain.reports.transfer import TRANSFER_CHUNK_BYTES

TRANSFER: Final = (
    Capability.REPORTS_TRANSFER_BEGIN,
    Capability.REPORTS_TRANSFER_APPEND,
    Capability.REPORTS_TRANSFER_FINALIZE,
    Capability.REPORTS_TRANSFER_ABORT,
    Capability.REPORTS_TRANSFER_READ_CHUNK,
)
UPLOADS: Final = TRANSFER[:4]
SESSION: Final = "grxfr_synthetic0001"
REPORT: Final = "grpt_synthetic0001"
VERSION: Final = "grver_synthetic0001"
TOKEN: Final = "grxtk_" + "ab" * 32
DIGEST: Final = "0" * 64
SHA_PATTERN: Final = "^[0-9a-f]{64}$"
SESSION_PATTERN: Final = "^grxfr_[A-Za-z0-9]{8,64}$"
B64_PATTERN: Final = "^(?:[A-Za-z0-9+/]{4})*(?:[A-Za-z0-9+/]{2}==|[A-Za-z0-9+/]{3}=)?$"
REFERENCE: Final[dict[str, Any]] = {"transfer": {"session_id": SESSION, "content_token": TOKEN}}

BEGIN: Final[dict[str, Any]] = {
    "format": "markdown",
    "encoding": "identity",
    "byte_count": 600 * 1024,
    "sha256": DIGEST,
    "idempotency_key": "begin-synthetic",
}
APPEND: Final[dict[str, Any]] = {
    "session_id": SESSION,
    "sequence": 0,
    "chunk": base64.b64encode(b"synthetic").decode("ascii"),
    "chunk_sha256": hashlib.sha256(b"synthetic").hexdigest(),
}
READ: Final[dict[str, Any]] = {"report_id": REPORT, "version_number": 1}
VALID: Final[dict[Capability, dict[str, Any]]] = {
    Capability.REPORTS_TRANSFER_BEGIN: BEGIN,
    Capability.REPORTS_TRANSFER_APPEND: APPEND,
    Capability.REPORTS_TRANSFER_FINALIZE: {"session_id": SESSION},
    Capability.REPORTS_TRANSFER_ABORT: {"session_id": SESSION},
    Capability.REPORTS_TRANSFER_READ_CHUNK: READ,
}
COMMANDS: Final[dict[Capability, type]] = {
    Capability.REPORTS_TRANSFER_BEGIN: BeginReportTransfer,
    Capability.REPORTS_TRANSFER_APPEND: AppendReportTransfer,
    Capability.REPORTS_TRANSFER_FINALIZE: FinalizeReportTransfer,
    Capability.REPORTS_TRANSFER_ABORT: AbortReportTransfer,
    Capability.REPORTS_TRANSFER_READ_CHUNK: ReadReportTransferChunk,
}


def _wire(capability: Capability, payload: dict[str, Any]) -> dict[str, Any]:
    (permitted,) = permitted_purposes(capability)
    return {
        "request_id": f"req-{capability.value}",
        "purpose": permitted.value,
        "principal_id": "prn_synthetic0001",
        "requested_at": "2026-11-07T12:00:00Z",
        "payload": payload,
    }


def _refused(capability: Capability, payload: dict[str, Any]) -> list[str]:
    with pytest.raises(ApplicationError) as refused:
        normalize(capability.value, _wire(capability, payload))
    assert refused.value.code.value == "invalid_request"
    return [detail.value for detail in refused.value.safe_details]


# ---- layers 1-2: vocabulary, purposes, classification --------------------------------


def test_the_five_names_and_their_classification() -> None:
    assert [capability.value for capability in TRANSFER] == [
        "reports.transfer.begin",
        "reports.transfer.append",
        "reports.transfer.finalize",
        "reports.transfer.abort",
        "reports.transfer.read_chunk",
    ]
    for capability in UPLOADS:
        assert permitted_purposes(capability) == frozenset({Purpose.REPORT_AUTHORING})
        assert is_write_capability(capability)
        # T1: additive -- no report is created and nothing is destroyed.
        assert not is_destructive_capability(capability)
    read = Capability.REPORTS_TRANSFER_READ_CHUNK
    assert permitted_purposes(read) == frozenset({Purpose.REPORT_READ})
    assert not is_write_capability(read)
    for capability in TRANSFER:
        assert not is_operator_only(capability)  # client-usable
        assert capability in _SCOPELESS
        policy = CHATLLM_CAPABILITY_POLICY[capability]
        assert policy.classification is ChatLLMCapabilityClass.DATA_REQUIRED
        assert policy.classification is (
            CHATLLM_CAPABILITY_POLICY[Capability.REPORTS_PUBLISH].classification
        )
        assert policy.family == "reports"
        assert capability in _HANDLERS
    assert frozenset(UPLOADS) == _REPORT_TRANSFER_UPLOAD_CAPABILITIES


# ---- layers 3-4: the exact schemas ----------------------------------------------------


def test_begin_schema_is_exact_and_closed() -> None:
    schema = payload_schema_for(BeginReportTransfer)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["format", "encoding", "byte_count", "sha256", "idempotency_key"]
    properties = schema["properties"]
    assert set(properties) == {
        "format",
        "encoding",
        "byte_count",
        "sha256",
        "idempotency_key",
        "ttl_seconds",
    }
    assert properties["format"]["type"] == "string"
    assert properties["format"]["enum"] == ["markdown", "text", "json", "mixed"]
    assert properties["encoding"]["enum"] == ["identity", "gzip+base64"]
    assert (properties["byte_count"]["type"], properties["byte_count"]["minimum"]) == (
        "integer",
        1,
    )
    assert properties["byte_count"]["maximum"] == 16_777_216
    assert properties["sha256"]["pattern"] == SHA_PATTERN
    assert properties["idempotency_key"] == {"type": "string"}  # as reports.publish
    assert (properties["ttl_seconds"]["minimum"], properties["ttl_seconds"]["maximum"]) == (
        300,
        86_400,
    )
    protocol = properties["format"]["description"]
    for phrase in ("262,144 raw bytes", "at most 64", "one-use content_token", "abort and begin"):
        assert phrase in protocol, phrase
    assert "4 live sessions per client" in properties["ttl_seconds"]["description"]
    assert "default 3600" in properties["ttl_seconds"]["description"]


def test_append_schema_is_exact_and_closed() -> None:
    schema = payload_schema_for(AppendReportTransfer)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["session_id", "sequence", "chunk", "chunk_sha256"]
    properties = schema["properties"]
    assert properties["session_id"]["pattern"] == SESSION_PATTERN
    assert (properties["sequence"]["minimum"], properties["sequence"]["maximum"]) == (0, 63)
    chunk = properties["chunk"]
    assert chunk["type"] == "string"
    assert (chunk["minLength"], chunk["maxLength"]) == (4, 349_528)
    assert chunk["pattern"] == B64_PATTERN
    assert chunk["contentEncoding"] == "base64"
    assert properties["chunk_sha256"]["pattern"] == SHA_PATTERN
    assert len(base64.b64encode(bytes(TRANSFER_CHUNK_BYTES))) == (
        TRANSFER_CHUNK_MAX_BASE64_CHARACTERS
    )


@pytest.mark.parametrize("command", [FinalizeReportTransfer, AbortReportTransfer])
def test_finalize_and_abort_schemas_name_only_the_session(command: type) -> None:
    schema = payload_schema_for(command)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["session_id"]
    assert set(schema["properties"]) == {"session_id"}
    assert schema["properties"]["session_id"]["pattern"] == SESSION_PATTERN
    assert schema["properties"]["session_id"]["type"] == "string"


def test_finalize_schema_states_that_finalize_is_not_replayable() -> None:
    description = payload_schema_for(FinalizeReportTransfer)["properties"]["session_id"][
        "description"
    ]
    assert "one-use" in description and "not replayable" in description


def test_read_chunk_schema_is_exact_and_closed() -> None:
    schema = payload_schema_for(ReadReportTransferChunk)
    assert schema["additionalProperties"] is False
    assert schema["required"] == ["report_id"]
    properties = schema["properties"]
    assert set(properties) == {
        "report_id",
        "version_id",
        "version_number",
        "part",
        "offset",
        "length",
        "include_withdrawn",
    }
    assert properties["report_id"]["pattern"] == "^grpt_[A-Za-z0-9]{8,64}$"
    assert properties["version_id"]["pattern"] == "^grver_[A-Za-z0-9]{8,64}$"
    assert properties["version_number"]["minimum"] == 1
    assert properties["part"]["enum"] == ["decoded", "original"]
    assert (properties["offset"]["minimum"], properties["offset"]["maximum"]) == (
        0,
        16_777_216,
    )
    assert (properties["length"]["minimum"], properties["length"]["maximum"]) == (1, 262_144)
    assert properties["include_withdrawn"]["type"] == "boolean"


def _content_variants(schema: dict[str, Any]) -> list[dict[str, Any]]:
    variants = schema["oneOf"]
    assert len(variants) == 2
    for variant in variants:
        assert variant["type"] == "object"
        assert variant["additionalProperties"] is False
    return variants


def test_publish_and_update_content_take_the_closed_transfer_reference() -> None:
    publish = payload_schema_for(PublishGeneralReport)["properties"]["content"]
    patch = payload_schema_for(UpdateGeneralReport)["properties"]["patch"]["properties"]["content"]
    for content in (publish, patch):
        assert content["type"] == "object"
        inline, reference = _content_variants(content)
        assert inline["required"] == ["format"]
        assert "transfer" not in inline["properties"]
        assert reference["required"] == ["transfer"]
        assert set(reference["properties"]) == {"transfer"}
        inner = reference["properties"]["transfer"]
        assert inner["additionalProperties"] is False
        assert inner["required"] == ["session_id", "content_token"]
        assert inner["properties"]["session_id"]["pattern"] == SESSION_PATTERN
        assert inner["properties"]["content_token"]["pattern"] == "^grxtk_[0-9a-f]{64}$"
        assert "reports.transfer.begin" in content["description"]
        validator = jsonschema.Draft202012Validator(content)
        assert validator.is_valid(REFERENCE)
        assert validator.is_valid({"format": "markdown", "body": "# Synthetic"})
        for refused in (
            {**REFERENCE, "format": "markdown"},
            {"transfer": {**REFERENCE["transfer"], "format": "text"}},
            {"transfer": {"session_id": SESSION}},
            {"transfer": {"session_id": SESSION, "content_token": "grxtk_short"}},
        ):
            assert not validator.is_valid(refused), refused


def test_reports_read_text_points_at_the_chunked_read() -> None:
    publish = payload_schema_for(PublishGeneralReport)["properties"]["content"]
    assert "body_chunked_read" in publish["description"]
    assert "reports.transfer.read_chunk" in publish["description"]


@pytest.mark.parametrize("capability", TRANSFER, ids=lambda c: c.value)
def test_every_valid_example_satisfies_its_published_schema(capability: Capability) -> None:
    schema = payload_schema_for(COMMANDS[capability])
    jsonschema.Draft202012Validator(schema).validate(VALID[capability])
    _metadata, command = normalize(capability.value, _wire(capability, VALID[capability]))
    assert type(command) is COMMANDS[capability]


def test_a_full_chunk_append_fits_the_request_ceiling() -> None:
    raw = bytes(range(256)) * (TRANSFER_CHUNK_BYTES // 256)
    payload = {
        "session_id": SESSION,
        "sequence": 63,
        "chunk": base64.b64encode(raw).decode("ascii"),
        "chunk_sha256": hashlib.sha256(raw).hexdigest(),
    }
    assert len(payload["chunk"]) == TRANSFER_CHUNK_MAX_BASE64_CHARACTERS
    wire = _wire(Capability.REPORTS_TRANSFER_APPEND, payload)
    assert len(json.dumps(wire).encode("utf-8")) < MAX_REQUEST_BYTES
    _metadata, command = normalize("reports.transfer.append", wire)
    assert isinstance(command, AppendReportTransfer)
    assert "chunk=" not in repr(command)  # the bytes stay out of a repr


# ---- layers 3-4: every bound, refused naming its field --------------------------------


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"format": "html"}, "format"),
        ({"format": 1}, "format"),
        ({"encoding": "gzip"}, "encoding"),
        ({"encoding": None}, "encoding"),
        ({"byte_count": 0}, "byte_count"),
        ({"byte_count": 16_777_217}, "byte_count"),
        ({"byte_count": True}, "byte_count"),
        ({"byte_count": "1"}, "byte_count"),
        ({"sha256": "A" * 64}, "sha256"),
        ({"sha256": "0" * 63}, "sha256"),
        ({"sha256": 7}, "sha256"),
        ({"ttl_seconds": 299}, "ttl_seconds"),
        ({"ttl_seconds": 86_401}, "ttl_seconds"),
        ({"ttl_seconds": True}, "ttl_seconds"),
        ({"idempotency_key": ""}, "idempotency_key"),
        ({"idempotency_key": "k" * 129}, "idempotency_key"),
    ],
)
def test_begin_bounds(change: dict[str, Any], detail: str) -> None:
    assert _refused(Capability.REPORTS_TRANSFER_BEGIN, {**BEGIN, **change}) == [detail]


def test_begin_bounds_admit_their_edges() -> None:
    for change in (
        {"byte_count": 1, "ttl_seconds": 300},
        {"byte_count": 16_777_216, "ttl_seconds": 86_400},
        {"encoding": "gzip+base64", "format": "mixed"},
    ):
        _metadata, command = normalize(
            "reports.transfer.begin", _wire(Capability.REPORTS_TRANSFER_BEGIN, {**BEGIN, **change})
        )
        assert isinstance(command, BeginReportTransfer)
    declaration = transfer_declaration(BeginReportTransfer(**BEGIN))
    assert declaration.ttl_seconds == 3600
    assert declaration.byte_count == 600 * 1024


@pytest.mark.parametrize(
    ("change", "detail"),
    [
        ({"session_id": "grpt_synthetic0001"}, "session_id"),
        ({"session_id": "grxfr_short"}, "session_id"),
        ({"session_id": 5}, "session_id"),
        ({"sequence": -1}, "sequence"),
        ({"sequence": 64}, "sequence"),
        ({"sequence": True}, "sequence"),
        ({"sequence": "0"}, "sequence"),
        ({"chunk": ""}, "chunk"),
        ({"chunk": "abc"}, "chunk"),
        ({"chunk": "ab c"}, "chunk"),
        ({"chunk": "YWJj\n"}, "chunk"),
        ({"chunk": "YW=j"}, "chunk"),
        ({"chunk": "-_-_"}, "chunk"),
        ({"chunk": "A" * (TRANSFER_CHUNK_MAX_BASE64_CHARACTERS + 4)}, "chunk"),
        ({"chunk": 1}, "chunk"),
        ({"chunk_sha256": "F" * 64}, "chunk_sha256"),
        ({"chunk_sha256": None}, "chunk_sha256"),
    ],
)
def test_append_bounds(change: dict[str, Any], detail: str) -> None:
    assert _refused(Capability.REPORTS_TRANSFER_APPEND, {**APPEND, **change}) == [detail]


@pytest.mark.parametrize(
    "capability", [Capability.REPORTS_TRANSFER_FINALIZE, Capability.REPORTS_TRANSFER_ABORT]
)
@pytest.mark.parametrize("session", ["grpt_synthetic0001", "grxfr_x", 9, None])
def test_finalize_and_abort_refuse_a_malformed_session(
    capability: Capability, session: object
) -> None:
    assert _refused(capability, {"session_id": session}) == ["session_id"]


@pytest.mark.parametrize(
    ("payload", "details"),
    [
        ({"report_id": REPORT}, ["version_id", "version_number"]),
        ({**READ, "version_id": VERSION}, ["version_id", "version_number"]),
        ({"report_id": "rpt_synthetic0001", "version_number": 1}, ["artifact_id"]),
        ({"report_id": 3, "version_number": 1}, ["artifact_id"]),
        ({"report_id": REPORT, "version_id": "grpt_synthetic0001"}, ["version_id"]),
        ({"report_id": REPORT, "version_id": 4}, ["version_id"]),
        ({**READ, "version_number": 0}, ["version_number"]),
        ({**READ, "version_number": True}, ["version_number"]),
        ({**READ, "part": "encoded"}, ["part"]),
        ({**READ, "part": 1}, ["part"]),
        ({**READ, "offset": -1}, ["offset"]),
        ({**READ, "offset": 16_777_217}, ["offset"]),
        ({**READ, "offset": False}, ["offset"]),
        ({**READ, "length": 0}, ["length"]),
        ({**READ, "length": 262_145}, ["length"]),
        ({**READ, "include_withdrawn": "yes"}, ["include_withdrawn"]),
    ],
)
def test_read_chunk_bounds(payload: dict[str, Any], details: list[str]) -> None:
    assert _refused(Capability.REPORTS_TRANSFER_READ_CHUNK, payload) == details


def test_read_chunk_defaults_and_edges() -> None:
    command = ReadReportTransferChunk(report_id=REPORT, version_id=VERSION)
    assert (command.part, command.offset, command.length) == ("decoded", 0, 262_144)
    assert command.include_withdrawn is False
    for change in (
        {"part": "original", "offset": 16_777_216, "length": 1, "include_withdrawn": True},
        {"length": 262_144},
    ):
        _metadata, normalized = normalize(
            "reports.transfer.read_chunk",
            _wire(Capability.REPORTS_TRANSFER_READ_CHUNK, {**READ, **change}),
        )
        assert isinstance(normalized, ReadReportTransferChunk)


#: Fields the server owns, or the plane's pipeline vocabulary, never a caller's.
_SERVER_OWNED: Final[dict[Capability, tuple[str, ...]]] = {
    Capability.REPORTS_TRANSFER_BEGIN: (
        "session_id",
        "principal_id",
        "owner_principal_id",
        "client_ref",
        "state",
        "chunk_byte_limit",
        "expires_at",
        "intent_digest",
        "content_token",
        "content_token_digest",
    ),
    Capability.REPORTS_TRANSFER_APPEND: (
        "byte_offset",
        "byte_count",
        "received_byte_count",
        "principal_id",
        "client_ref",
        "received_at",
        "idempotency_key",
    ),
    Capability.REPORTS_TRANSFER_FINALIZE: (
        "content_token",
        "content_token_digest",
        "state",
        "finalized_at",
        "sha256",
        "client_ref",
        "idempotency_key",
    ),
    Capability.REPORTS_TRANSFER_ABORT: ("state", "client_ref", "principal_id", "idempotency_key"),
    Capability.REPORTS_TRANSFER_READ_CHUNK: (
        "chunk",
        "chunk_sha256",
        "total_byte_count",
        "plane",
        "principal_id",
        "idempotency_key",
    ),
}


@pytest.mark.parametrize(
    ("capability", "field"),
    [(capability, field) for capability, fields in _SERVER_OWNED.items() for field in fields],
    ids=lambda value: value.value if isinstance(value, Capability) else value,
)
def test_server_owned_fields_are_refused(capability: Capability, field: str) -> None:
    assert _refused(capability, {**VALID[capability], field: "x"}) == []


@pytest.mark.parametrize("capability", TRANSFER, ids=lambda c: c.value)
def test_pipeline_fields_are_refused_by_their_token(capability: Capability) -> None:
    assert _refused(capability, {**VALID[capability], "cycle_run_id": "x"}) == ["cycle_run_id"]


# ---- T10: the transfer reference on publish and update (shape only) -------------------


def _publish(content: object) -> dict[str, Any]:
    return {"title": "Synthetic", "content": content, "idempotency_key": "publish-synthetic"}


def _update(content: object) -> dict[str, Any]:
    return {
        "report_id": REPORT,
        "expected_version": 1,
        "patch": {"content": content},
        "change_reason": "Synthetic",
        "idempotency_key": "update-synthetic",
    }


def test_publish_and_update_accept_a_well_formed_reference() -> None:
    _metadata, publish = normalize(
        "reports.publish", _wire(Capability.REPORTS_PUBLISH, _publish(REFERENCE))
    )
    assert isinstance(publish, PublishGeneralReport)
    assert TOKEN not in repr(publish)
    _metadata, update = normalize(
        "reports.update", _wire(Capability.REPORTS_UPDATE, _update(REFERENCE))
    )
    assert isinstance(update, UpdateGeneralReport)


@pytest.mark.parametrize(
    "content",
    [
        {**REFERENCE, "format": "markdown"},
        {**REFERENCE, "encoding": "identity"},
        {"transfer": {**REFERENCE["transfer"], "format": "text"}},
        {"transfer": {"session_id": SESSION}},
        {"transfer": {"content_token": TOKEN}},
        {"transfer": {"session_id": "grpt_synthetic0001", "content_token": TOKEN}},
        {"transfer": {"session_id": SESSION, "content_token": "grxtk_" + "AB" * 32}},
        {"transfer": {"session_id": SESSION, "content_token": TOKEN + "0"}},
        {"transfer": {"session_id": SESSION, "content_token": 1}},
        {"transfer": [SESSION, TOKEN]},
        {"transfer": None},
    ],
)
def test_a_malformed_reference_is_refused_on_transfer(content: dict[str, Any]) -> None:
    assert _refused(Capability.REPORTS_PUBLISH, _publish(content)) == ["transfer"]
    assert _refused(Capability.REPORTS_UPDATE, _update(content)) == ["transfer"]


def test_a_reference_is_never_consumed_before_the_handlers_land() -> None:
    """W3a interim: the handler path cannot consume a reference yet (W3b replaces this)."""
    command = PublishGeneralReport(**_publish(REFERENCE))
    with pytest.raises(ApplicationError) as refused:
        publication_request(command, max_decoded=1024)
    assert refused.value.code.value == "unsupported"


def test_inline_content_is_unchanged_by_the_reference_variant() -> None:
    assert _refused(
        Capability.REPORTS_PUBLISH, _publish({"format": "markdown", "transfer": {}})
    ) == ["transfer"]
    _metadata, publish = normalize(
        "reports.publish",
        _wire(Capability.REPORTS_PUBLISH, _publish({"format": "markdown", "body": "# Synthetic"})),
    )
    assert isinstance(publish, PublishGeneralReport)
    assert _refused(Capability.REPORTS_PUBLISH, _publish({"body": "no format"})) == ["content"]
    assert SafeDetail.TRANSFER.value == "transfer"
