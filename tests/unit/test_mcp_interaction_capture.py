"""The MCP interaction capture: redaction, caps, outcomes, the recorder, composition.

FAST: no database, no network, no server. Rows are built from synthetic
`CapturedExchange` values, and the middleware is driven with in-process ASGI
callables. Every credential-shaped value is a synthetic marker whose absence
from the whole serialized row is what is asserted.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import io
import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import apps.gateway as gateway
import pytest

from my_pa.adapters import mcp_interaction_capture as capture
from my_pa.adapters.mcp.chatllm_gateway import OPERATOR_TOOL, READ_TOOL, WRITE_TOOL
from my_pa.adapters.mcp.remote import MCP_PATH
from my_pa.adapters.mcp_interaction_capture import (
    BODY_CAP_BYTES,
    BUFFER_CEILING_BYTES,
    INTERACTION_COLUMNS,
    REDACTED,
    CapturedExchange,
    InteractionRecorder,
    McpInteractionCapture,
    build_interaction_row,
    redact_json,
    redact_text,
)
from my_pa.bootstrap.settings import ENV_PREFIX, Settings, SettingsError, load_settings
from my_pa.infrastructure.persistence import mcp_interactions as store
from tests.unit import redaction_probe as probe

_URL = "postgresql+psycopg://someone@db.invalid:5432/somewhere"
_WHEN = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)
#: The façade invoke tools, as the composition root passes them.
FACADE = frozenset({READ_TOOL, WRITE_TOOL, OPERATOR_TOOL})


def _exchange(
    request: object = None,
    response: object = None,
    *,
    status: int | None = 200,
    raw_request: bytes | None = None,
    raw_response: bytes | None = None,
    request_headers: tuple[tuple[bytes, bytes], ...] = (),
    response_headers: tuple[tuple[bytes, bytes], ...] = (),
    access: object = None,
    request_overflowed: bool = False,
) -> CapturedExchange:
    request_bytes = (
        raw_request
        if raw_request is not None
        else b""
        if request is None
        else json.dumps(request).encode()
    )
    response_bytes = (
        raw_response
        if raw_response is not None
        else b""
        if response is None
        else json.dumps(response).encode()
    )
    return CapturedExchange(
        http_method="POST",
        started_at=_WHEN,
        latency_ms=1.5,
        request_headers=request_headers,
        request_body=request_bytes,
        request_bytes=len(request_bytes),
        request_overflowed=request_overflowed,
        http_status=status,
        response_headers=response_headers,
        response_body=response_bytes,
        response_bytes=len(response_bytes),
        access=access,
    )


def _row(exchange: CapturedExchange, **counters: int) -> dict[str, object]:
    return build_interaction_row(exchange, facade_invoke_tools=FACADE, **counters)


def _serialized(row: Mapping[str, object]) -> str:
    return json.dumps(row, default=str, ensure_ascii=False)


def _call(name: str, arguments: object, request_id: object = 1) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": name, "arguments": arguments},
    }


def _tool_result(text: str, *, is_error: bool) -> dict[str, object]:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"content": [{"type": "text", "text": text}], "isError": is_error},
    }


# ---- the row contract --------------------------------------------------------


def test_the_row_carries_exactly_the_stores_insert_columns() -> None:
    row = _row(_exchange({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
    assert frozenset(INTERACTION_COLUMNS) == store.INSERT_COLUMNS
    assert frozenset(row) == store.INSERT_COLUMNS
    assert BODY_CAP_BYTES == store.BODY_CAP_BYTES
    assert row["outcome"] in store.OUTCOMES


def test_the_interaction_id_is_the_prefixed_uuid4_hex() -> None:
    first = _row(_exchange())["interaction_id"]
    second = _row(_exchange())["interaction_id"]
    assert isinstance(first, str)
    assert first.startswith("mcpi_") and len(first) == 37
    assert all(c in "0123456789abcdef" for c in first[5:])
    assert first != second


def test_empty_bodies_store_nothing_and_hash_the_empty_string() -> None:
    row = _row(_exchange(status=202))
    empty = hashlib.sha256(b"").hexdigest()
    assert row["request_bytes"] == row["response_bytes"] == 0
    assert row["request_sha256"] == row["response_sha256"] == empty
    assert row["request_body"] is row["response_body"] is None
    assert row["request_body_text"] is row["response_body_text"] is None
    assert row["request_truncated"] is row["response_truncated"] is False
    capture_facts = row["diagnostics"]["capture"]  # type: ignore[index]
    assert capture_facts["request_parse"] == capture_facts["response_parse"] == "empty"
    assert row["outcome"] == "ok"


def test_a_body_the_app_never_read_is_not_captured_rather_than_empty() -> None:
    row = _row(_exchange(status=401, request_overflowed=True))
    assert row["diagnostics"]["capture"]["request_parse"] == "not_captured"  # type: ignore[index]
    assert row["diagnostics"]["capture"]["request_hash_scope"] == "redacted_prefix"  # type: ignore[index]
    assert row["request_sha256"] == hashlib.sha256(b"").hexdigest()
    assert row["request_body_text"] is None
    assert row["request_truncated"] is False


# ---- headers -----------------------------------------------------------------


def test_only_allowlisted_headers_are_stored_and_credentials_never_are() -> None:
    headers = (
        (b"authorization", b"Bearer MARKERAUTHORIZATION"),
        (b"cookie", b"session=MARKERCOOKIE"),
        (b"proxy-authorization", b"Basic MARKERPROXY"),
        (b"x-forwarded-for", b"203.0.113.9"),
        (b"content-type", b"application/json"),
        (b"accept", b"application/json, text/event-stream"),
        (b"mcp-protocol-version", b"2025-06-18"),
        (b"user-agent", b"synthetic-agent/1"),
    )
    row = _row(
        _exchange(
            {"jsonrpc": "2.0", "id": 1, "method": "ping"},
            request_headers=headers,
            response_headers=((b"set-cookie", b"MARKERSETCOOKIE"),),
        )
    )
    assert row["request_headers"] == {
        "content-type": "application/json",
        "accept": "application/json, text/event-stream",
        "mcp-protocol-version": "2025-06-18",
        "user-agent": "synthetic-agent/1",
    }
    text = _serialized(row)
    for marker in ("MARKERAUTHORIZATION", "MARKERCOOKIE", "MARKERPROXY", "MARKERSETCOOKIE"):
        assert marker not in text
    assert "203.0.113.9" not in text


def test_the_session_header_is_read_from_the_request_or_the_response() -> None:
    from_request = _row(_exchange(request_headers=((b"mcp-session-id", b"sess-1"),)))
    from_response = _row(_exchange(response_headers=((b"mcp-session-id", b"sess-2"),)))
    assert from_request["mcp_session_id"] == "sess-1"
    assert from_response["mcp_session_id"] == "sess-2"
    assert _row(_exchange())["mcp_session_id"] is None


# ---- body redaction ----------------------------------------------------------


@pytest.mark.parametrize(
    "key",
    [
        "authorization",
        "Proxy-Authorization",
        "cookie",
        "Set-Cookie",
        "access_token",
        "refresh-token",
        "ID_TOKEN",
        "token",
        "bearer",
        "client_secret",
        "secret",
        "password",
        "passphrase",
        "api_key",
        "apikey",
        "private_key",
        "signing-key",
        "code_verifier",
        "assertion",
        "client_assertion",
        "session_token",
        "credential",
        "credentials",
    ],
)
def test_every_listed_key_is_redacted_at_any_depth(key: str) -> None:
    document = {"outer": [{"inner": {key: "MARKERSECRETVALUE", "kept": "visible"}}]}
    redacted, count, _ = redact_json(document)
    assert count == 1
    assert "MARKERSECRETVALUE" not in json.dumps(redacted)
    assert redacted["outer"][0]["inner"][key] == REDACTED  # type: ignore[index]
    assert redacted["outer"][0]["inner"]["kept"] == "visible"  # type: ignore[index]


def test_a_redacted_key_hides_a_structured_value_whole() -> None:
    redacted, count, _ = redact_json({"credentials": {"user": "MARKERUSER", "n": 7}})
    assert redacted == {"credentials": REDACTED}
    assert count == 1


def test_bearer_and_jwt_runs_are_redacted_inside_any_string() -> None:
    jwt = "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJNQVJLRVIifQ.MARKERSIGNATURE_x-y"
    redacted, count, _ = redact_json(
        {"note": "use Bearer MARKERBEARERTOKEN123 then", "blob": f"jwt={jwt};", "ok": "plain"}
    )
    assert redacted["note"] == f"use Bearer {REDACTED} then"  # type: ignore[index]
    assert redacted["blob"] == f"jwt={REDACTED};"  # type: ignore[index]
    assert redacted["ok"] == "plain"  # type: ignore[index]
    assert count == 2


def test_json_inside_a_text_content_string_is_parsed_and_redacted() -> None:
    envelope = json.dumps({"result": {"refresh_token": "MARKERNESTED", "title": "kept"}})
    row = _row(
        _exchange(
            _call("documents.read", {}),
            _tool_result(envelope, is_error=False),
        )
    )
    body = row["response_body"]
    text = body["result"]["content"][0]["text"]  # type: ignore[index]
    assert "MARKERNESTED" not in _serialized(row)
    assert json.loads(text) == {"result": {"refresh_token": REDACTED, "title": "kept"}}
    assert row["diagnostics"]["capture"]["redactions"] == 1  # type: ignore[index]


def test_an_embedded_document_hides_non_string_values_under_redacted_keys() -> None:
    """The embedded-JSON walk, not the `"key": "value"` text pattern, is what hides these.

    Every secret here is a value the string pattern cannot match — an object, a
    number, an array — so this fails if the embedded document is only
    pattern-redacted instead of parsed and walked.
    """
    envelope = json.dumps(
        {
            "credentials": {"user": "MARKERCREDUSER", "n": 7},
            "password": 98765432123,
            "api_key": ["MARKERAPIKEY"],
            "title": "kept",
        }
    )
    row = _row(
        _exchange(
            _call("documents.read", {}),
            _tool_result(envelope, is_error=False),
        )
    )
    serialized = _serialized(row)
    for marker in ("MARKERCREDUSER", "98765432123", "MARKERAPIKEY"):
        assert marker not in serialized
    text = row["response_body"]["result"]["content"][0]["text"]  # type: ignore[index]
    assert json.loads(text) == {
        "credentials": REDACTED,
        "password": REDACTED,
        "api_key": REDACTED,
        "title": "kept",
    }
    assert row["diagnostics"]["capture"]["redactions"] == 3  # type: ignore[index]


def test_an_embedded_document_without_secrets_keeps_its_original_text() -> None:
    original = '{"b": 1,  "a": "spaced"}'
    redacted, count, _ = redact_json({"text": original})
    assert redacted == {"text": original}
    assert count == 0


def test_the_request_arguments_are_redacted_before_storage() -> None:
    row = _row(
        _exchange(
            _call(
                "capture.create",
                {"payload": {"text": "hello", "api_key": "MARKERAPIKEY"}},
            ),
            _tool_result("{}", is_error=False),
        )
    )
    assert "MARKERAPIKEY" not in _serialized(row)
    assert row["request_body"]["params"]["arguments"]["payload"] == {  # type: ignore[index]
        "text": "hello",
        "api_key": REDACTED,
    }


def test_non_json_text_is_redacted_by_pattern() -> None:
    raw = (
        b'garbage {"password": "MARKERPLAIN", "x": 1} '
        b'\\"client_secret\\":\\"MARKERESCAPED\\" '
        b"{'token': 'MARKERREPR'} Bearer MARKERBEARER"
    )
    row = _row(_exchange(raw_request=raw))
    text = row["request_body_text"]
    assert isinstance(text, str)
    for marker in ("MARKERPLAIN", "MARKERESCAPED", "MARKERREPR", "MARKERBEARER"):
        assert marker not in text
    assert '"password": "[REDACTED]"' in text
    assert row["request_body"] is None
    assert row["request_truncated"] is False
    assert row["diagnostics"]["capture"]["request_parse"] == "invalid_json"  # type: ignore[index]
    assert row["request_sha256"] == hashlib.sha256(text.encode()).hexdigest()
    assert row["request_sha256"] != hashlib.sha256(raw).hexdigest()


def test_redact_text_counts_and_keeps_structure() -> None:
    text, count, nul = redact_text('a "Secret" : "v1" b "secret":"v\\"2" c')
    assert text == 'a "Secret" : "[REDACTED]" b "secret":"[REDACTED]" c'
    assert count == 2
    assert nul is False


def test_a_python_repr_echo_in_a_jsonrpc_error_message_is_redacted() -> None:
    row = _row(
        _exchange(
            _call("x", {"password": "MARKERECHO"}),
            {
                "jsonrpc": "2.0",
                "id": 1,
                "error": {"code": -32602, "message": "bad input_value={'password': 'MARKERECHO'}"},
            },
        )
    )
    assert "MARKERECHO" not in _serialized(row)
    assert row["diagnostics"]["jsonrpc_error"]["code"] == -32602  # type: ignore[index]


def test_metadata_columns_are_redacted_and_bounded() -> None:
    row = _row(_exchange({"jsonrpc": "2.0", "id": "Bearer MARKERID", "method": "m" * 1000}))
    assert row["jsonrpc_id"] == f"Bearer {REDACTED}"
    assert row["jsonrpc_method"] == "m" * 256


# ---- caps, truncation, hashing ----------------------------------------------


def test_a_json_body_within_the_cap_is_stored_as_json() -> None:
    request = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"pad": "x" * 1000}}
    row = _row(_exchange(request))
    raw = json.dumps(request).encode()
    assert row["request_body"] == request
    assert row["request_body_text"] is None
    assert row["request_truncated"] is False
    assert row["request_bytes"] == len(raw)
    compact = json.dumps(request, ensure_ascii=False, separators=(",", ":")).encode()
    assert row["request_sha256"] == hashlib.sha256(compact).hexdigest()
    assert row["diagnostics"]["capture"]["request_hash_scope"] == "redacted_full"  # type: ignore[index]


def test_the_stored_digest_is_of_the_redacted_body_never_the_raw_one() -> None:
    """A stored hash must not be an oracle for a credential the redaction removed."""
    request = {"jsonrpc": "2.0", "id": 1, "params": {"password": "MARKERORACLE", "n": 1}}
    raw = json.dumps(request, separators=(",", ":")).encode()
    row = _row(_exchange(raw_request=raw))
    redacted = json.dumps(
        {"jsonrpc": "2.0", "id": 1, "params": {"password": REDACTED, "n": 1}},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    assert row["request_sha256"] == hashlib.sha256(redacted).hexdigest()
    assert row["request_sha256"] != hashlib.sha256(raw).hexdigest()
    assert row["request_bytes"] == len(raw)


def test_a_json_body_over_the_cap_is_a_truncated_redacted_prefix() -> None:
    pad = "x" * (BODY_CAP_BYTES - 40)
    request = {"pad": pad, "access_token": "T" * 500, "tail": "MARKERTAIL"}
    raw = json.dumps(request).encode()
    row = _row(_exchange(raw_request=raw))
    text = row["request_body_text"]
    assert isinstance(text, str)
    assert len(text.encode()) <= BODY_CAP_BYTES
    assert row["request_body"] is None
    assert row["request_truncated"] is True
    assert "TTTTTTTTTT" not in text
    assert "MARKERTAIL" not in text
    assert row["request_bytes"] == len(raw)
    # The digest covers the redacted body *before* the cap, not the stored prefix.
    full = json.dumps(
        {"pad": pad, "access_token": REDACTED, "tail": "MARKERTAIL"},
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode()
    assert row["request_sha256"] == hashlib.sha256(full).hexdigest()
    assert row["request_sha256"] != hashlib.sha256(raw).hexdigest()
    assert row["diagnostics"]["capture"]["request_parse"] == "json"  # type: ignore[index]


def test_a_token_beyond_the_cap_never_appears() -> None:
    raw = b"x" * (BODY_CAP_BYTES + 100) + b" Bearer MARKERBEYOND"
    row = _row(_exchange(raw_request=raw))
    text = row["request_body_text"]
    assert isinstance(text, str)
    assert len(text.encode()) <= BODY_CAP_BYTES
    assert "MARKERBEYOND" not in _serialized(row)
    assert row["request_truncated"] is True


@pytest.mark.parametrize("shape", ["bearer", "jwt", "pair"])
def test_a_token_straddling_the_cap_is_not_stored_in_part(shape: str) -> None:
    secret = "Q" * 400
    token = {
        "bearer": f"Bearer {secret}",
        "jwt": f"eyJ{secret}.eyJ{secret}.{secret}",
        "pair": f'"password": "{secret}"',
    }[shape]
    raw = (b"y" * (BODY_CAP_BYTES - 100)) + token.encode() + b" " + b"z" * 1000
    row = _row(_exchange(raw_request=raw))
    text = row["request_body_text"]
    assert isinstance(text, str)
    assert len(text.encode()) <= BODY_CAP_BYTES
    assert "QQQQ" not in text
    assert row["request_truncated"] is True


def test_truncation_never_splits_a_multibyte_character() -> None:
    raw = ("é" * BODY_CAP_BYTES).encode()  # two bytes each; not JSON
    row = _row(_exchange(raw_request=raw))
    text = row["request_body_text"]
    assert isinstance(text, str)
    assert text == "é" * (BODY_CAP_BYTES // 2)


def test_nul_is_replaced_and_flagged_in_json_and_in_text() -> None:
    json_row = _row(_exchange({"text": "a\u0000b", "k\u0000": 1}))
    assert json_row["request_body"] == {"text": "a�b", "k�": 1}
    assert json_row["diagnostics"]["capture"]["nul_replaced"] is True  # type: ignore[index]
    text_row = _row(_exchange(raw_request=b"not json \x00 here"))
    assert text_row["request_body_text"] == "not json � here"
    assert text_row["diagnostics"]["capture"]["nul_replaced"] is True  # type: ignore[index]
    assert "\x00" not in _serialized(json_row) + _serialized(text_row)


def test_a_lone_surrogate_is_made_encodable() -> None:
    row = _row(_exchange(raw_request=b'{"t": "\\ud800x"}'))
    _serialized(row).encode("utf-8")
    assert row["diagnostics"]["capture"]["nul_replaced"] is True  # type: ignore[index]


# ---- JSON-RPC metadata -------------------------------------------------------


def test_a_canonical_tools_call_names_tool_and_capability() -> None:
    row = _row(_exchange(_call("tasks.list", {}, request_id="abc")))
    assert row["jsonrpc_method"] == "tools/call"
    assert row["jsonrpc_id"] == "abc"
    assert row["tool_name"] == "tasks.list"
    assert row["capability"] == "tasks.list"


@pytest.mark.parametrize("facade", ["my_pa.read", "my_pa.write", "my_pa.operator"])
def test_a_facade_invoke_records_the_canonical_capability(facade: str) -> None:
    row = _row(
        _exchange(_call(facade, {"capability": "tasks.update", "arguments": {}}, request_id=7))
    )
    assert row["tool_name"] == facade
    assert row["capability"] == "tasks.update"
    assert row["jsonrpc_id"] == "7"


def test_describe_and_malformed_facade_calls_fall_back_to_the_tool_name() -> None:
    describe = _row(_exchange(_call("my_pa.describe", {"capability": "x"})))
    malformed = _row(_exchange(_call("my_pa.read", {"capability": 3})))
    assert describe["capability"] == "my_pa.describe"
    assert malformed["capability"] == "my_pa.read"


def test_a_batch_array_is_recorded_as_batch() -> None:
    row = _row(
        _exchange(
            [{"jsonrpc": "2.0", "id": 1, "method": "ping"}],
            [{"jsonrpc": "2.0", "id": 1, "error": {"code": -32600, "message": "no batches"}}],
        )
    )
    assert row["jsonrpc_method"] == "batch"
    assert row["jsonrpc_id"] is None
    assert row["outcome"] == "jsonrpc_error"
    assert row["error_code"] == "-32600"


def test_a_boolean_id_and_a_notification_have_no_id() -> None:
    assert _row(_exchange({"id": True, "method": "m"}))["jsonrpc_id"] is None
    assert _row(_exchange({"method": "m"}))["jsonrpc_id"] is None


def test_the_authenticated_context_is_read_by_duck_type() -> None:
    class Kind:
        value = "operator"

    class Principal:
        principal_id = "prn_synthetic"
        kind = Kind()

    class Access:
        principal = Principal()
        authenticated_client_id = "client-synthetic"

    row = _row(_exchange(access=Access()))
    assert row["oauth_client_id"] == "client-synthetic"
    assert row["principal_id"] == "prn_synthetic"
    assert row["principal_kind"] == "operator"
    anonymous = _row(_exchange())
    assert anonymous["oauth_client_id"] is anonymous["principal_id"] is None


# ---- outcomes and diagnostics -----------------------------------------------


_PROBLEM = {
    "code": "invalid_request",
    "correlation_id": "corr_0123456789abcdef0123456789abcdef",
    "message": "fixed",
    "retry": "after_correction",
    "safe_details": ["status"],
    "allowed_values": [{"detail": "status", "values": ["open", "done"], "truncated": False}],
}


def test_a_successful_tool_call_is_ok_with_the_envelope_correlation() -> None:
    envelope = {"correlation_id": "corr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa", "error": None}
    row = _row(_exchange(_call("t", {}), _tool_result(json.dumps(envelope), is_error=False)))
    assert row["outcome"] == "ok"
    assert row["error_code"] is None
    assert row["correlation_id"] == "corr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert row["diagnostics"]["is_error"] is False  # type: ignore[index]
    assert row["diagnostics"]["problem"] is None  # type: ignore[index]


def test_an_envelope_error_is_a_tool_error_with_its_problem() -> None:
    envelope = {"correlation_id": _PROBLEM["correlation_id"], "error": _PROBLEM, "result": None}
    row = _row(_exchange(_call("t", {}), _tool_result(json.dumps(envelope), is_error=True)))
    assert row["outcome"] == "tool_error"
    assert row["error_code"] == "invalid_request"
    assert row["correlation_id"] == _PROBLEM["correlation_id"]
    assert row["diagnostics"]["problem"] == {  # type: ignore[index]
        "code": "invalid_request",
        "correlation_id": _PROBLEM["correlation_id"],
        "safe_details": ["status"],
        "allowed_values": _PROBLEM["allowed_values"],
    }


def test_a_bare_problem_detail_is_a_tool_error() -> None:
    problem = {**_PROBLEM, "code": "unsupported", "safe_details": [], "allowed_values": []}
    row = _row(_exchange(_call("t", {}), _tool_result(json.dumps(problem), is_error=True)))
    assert row["outcome"] == "tool_error"
    assert row["error_code"] == "unsupported"
    assert row["correlation_id"] == _PROBLEM["correlation_id"]


def test_a_jsonrpc_error_records_code_and_message() -> None:
    row = _row(
        _exchange(
            {"jsonrpc": "2.0", "id": 5, "method": "nope"},
            {"jsonrpc": "2.0", "id": 5, "error": {"code": -32601, "message": "Method not found"}},
        )
    )
    assert row["outcome"] == "jsonrpc_error"
    assert row["error_code"] == "-32601"
    assert row["diagnostics"]["jsonrpc_error"] == {  # type: ignore[index]
        "code": -32601,
        "message": "Method not found",
    }


@pytest.mark.parametrize(
    ("status", "token", "outcome"),
    [
        (401, "invalid_token", "auth_refused"),
        (403, "insufficient_scope", "auth_refused"),
        (503, "temporarily_unavailable", "unavailable"),
    ],
)
def test_endpoint_refusals_are_classified_by_their_token(
    status: int, token: str, outcome: str
) -> None:
    row = _row(_exchange(None, {"error": token}, status=status))
    assert row["outcome"] == outcome
    assert row["error_code"] == token
    assert row["diagnostics"]["endpoint_error"] == token  # type: ignore[index]


@pytest.mark.parametrize(
    ("status", "raw", "outcome"),
    [
        (406, b'{"detail": "not acceptable"}', "http_error"),
        (404, b"Not Found", "http_error"),
        (None, b"", "http_error"),
        (503, b"", "unavailable"),
        (200, b"<html>", "unparsed"),
        (202, b"", "ok"),
    ],
)
def test_other_statuses_are_classified(status: int | None, raw: bytes, outcome: str) -> None:
    row = _row(_exchange({"method": "m"}, raw_response=raw, status=status))
    assert row["outcome"] == outcome
    assert row["http_status"] == status


def test_every_outcome_the_classifier_returns_is_one_the_table_accepts() -> None:
    assert set(store.OUTCOMES) == {
        "ok",
        "tool_error",
        "jsonrpc_error",
        "http_error",
        "auth_refused",
        "unavailable",
        "unparsed",
    }


# ---- the recorder ------------------------------------------------------------


def _wait_for(predicate: Any, timeout: float = 5.0) -> None:  # noqa: ANN401
    deadline = time.monotonic() + timeout
    while not predicate():
        assert time.monotonic() < deadline, "condition not reached"
        time.sleep(0.01)


def test_a_failed_write_is_counted_reported_by_count_only_and_carried_forward() -> None:
    rows: list[Mapping[str, object]] = []
    failing = [True]

    def sink(row: Mapping[str, object]) -> None:
        if failing[0]:
            raise RuntimeError("database unavailable MARKERDBERROR")
        rows.append(row)

    stderr = io.StringIO()
    recorder = InteractionRecorder(sink, facade_invoke_tools=FACADE, stderr=stderr)
    recorder.start()
    try:
        recorder.submit(_exchange({"method": "m", "password": "MARKERSTDERR"}))
        recorder.submit(_exchange({"method": "m"}))
        _wait_for(lambda: recorder.write_failures == 2)
        failing[0] = False
        recorder.submit(_exchange({"method": "m"}))
        recorder.submit(_exchange({"method": "m"}))
        _wait_for(lambda: len(rows) == 2)
    finally:
        recorder.stop()
    first, second = (row["diagnostics"]["capture"] for row in rows)  # type: ignore[index]
    assert first["write_failures_before"] == 2
    assert second["write_failures_before"] == 0
    report = stderr.getvalue()
    assert report.count("write_failed") == 1  # throttled: first failure only
    assert "write_failures=1" in report
    for marker in ("MARKERSTDERR", "MARKERDBERROR", "mcpi_", "password"):
        assert marker not in report


def test_a_full_queue_drops_counts_and_reports_on_the_next_row() -> None:
    rows: list[Mapping[str, object]] = []
    recorder = InteractionRecorder(
        rows.append, facade_invoke_tools=FACADE, maxsize=1, stderr=io.StringIO()
    )

    def submit_three() -> None:
        for _ in range(3):
            recorder.submit(_exchange())

    # Off the test thread with a bounded wait: a blocking `put` regression must
    # fail here within seconds, not hang the run (the repo has no pytest-timeout).
    submitter = threading.Thread(target=submit_three, daemon=True)
    submitter.start()
    submitter.join(timeout=2.0)
    if submitter.is_alive():
        recorder.start()  # drain so the blocked submitter can finish
        recorder.stop(timeout=2.0)
        pytest.fail("submit blocked on a full queue; it must drop and count instead")
    assert recorder.dropped == 2
    recorder.start()
    try:
        _wait_for(lambda: len(rows) == 1)
        recorder.submit(_exchange())
        _wait_for(lambda: len(rows) == 2)
    finally:
        recorder.stop()
    assert rows[0]["diagnostics"]["capture"]["dropped_before"] == 2  # type: ignore[index]
    assert rows[1]["diagnostics"]["capture"]["dropped_before"] == 0  # type: ignore[index]


def test_a_row_builder_failure_is_a_capture_error_not_a_crash(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows: list[Mapping[str, object]] = []
    recorder = InteractionRecorder(rows.append, facade_invoke_tools=FACADE, stderr=io.StringIO())

    def broken(*_args: object, **_kwargs: object) -> dict[str, object]:
        raise ValueError("builder broke")

    monkeypatch.setattr(capture, "build_interaction_row", broken)
    recorder.start()
    try:
        recorder.submit(_exchange())
        _wait_for(lambda: recorder.capture_errors == 1)
        monkeypatch.undo()
        recorder.submit(_exchange())
        _wait_for(lambda: len(rows) == 1)
    finally:
        recorder.stop()


def test_stop_is_bounded_even_when_the_sink_is_slow() -> None:
    release = threading.Event()

    def slow(_row: Mapping[str, object]) -> None:
        release.wait(5)

    recorder = InteractionRecorder(slow, facade_invoke_tools=FACADE, stderr=io.StringIO())
    recorder.start()
    for _ in range(5):
        recorder.submit(_exchange())
    began = time.monotonic()
    recorder.stop(timeout=0.2)
    elapsed = time.monotonic() - began
    release.set()
    assert elapsed < 1.5
    assert recorder.dropped >= 1  # what was left in the queue is counted, not lost silently
    recorder.submit(_exchange())
    assert recorder.dropped >= 2  # offered after stop


def test_stop_drains_what_is_queued() -> None:
    rows: list[Mapping[str, object]] = []
    recorder = InteractionRecorder(rows.append, facade_invoke_tools=FACADE, stderr=io.StringIO())
    for _ in range(20):
        recorder.submit(_exchange())
    recorder.start()
    recorder.stop(timeout=5)
    assert len(rows) == 20
    assert recorder.dropped == 0


def test_the_writer_is_one_daemon_thread() -> None:
    recorder = InteractionRecorder(lambda _row: None, facade_invoke_tools=FACADE)
    before = {thread.ident for thread in threading.enumerate()}
    recorder.start()
    recorder.start()
    try:
        added = [t for t in threading.enumerate() if t.ident not in before]
        assert len(added) == 1
        assert added[0].daemon is True
    finally:
        recorder.stop()


# ---- the middleware ----------------------------------------------------------


class _Collector:
    """A recorder stand-in that keeps what it is handed."""

    def __init__(self) -> None:
        self.exchanges: list[CapturedExchange] = []
        self.errors = 0
        self.stopped = False

    def submit(self, exchange: CapturedExchange) -> None:
        self.exchanges.append(exchange)

    def note_capture_error(self) -> None:
        self.errors += 1

    def stop(self, timeout: float = 2.0) -> None:
        self.stopped = True


def _drive(
    app: Any,  # noqa: ANN401
    path: str,
    chunks: list[bytes],
    *,
    scope_type: str = "http",
) -> tuple[list[dict[str, object]], dict[str, object]]:
    pending = [
        {"type": "http.request", "body": chunk, "more_body": index < len(chunks) - 1}
        for index, chunk in enumerate(chunks)
    ]
    sent: list[dict[str, object]] = []
    scope: dict[str, object] = {
        "type": scope_type,
        "path": path,
        "method": "POST",
        "headers": [(b"content-type", b"application/json")],
    }

    async def receive() -> dict[str, object]:
        return pending.pop(0) if pending else {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    return sent, scope


def _echo_app(response: bytes = b'{"ok":true}', status: int = 200) -> Any:  # noqa: ANN401
    async def app(scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401
        while True:
            message = await receive()
            if not message.get("more_body"):
                break
        scope.setdefault("state", {})["remote_mcp_access"] = "ACCESS"
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [(b"content-type", b"application/json")],
            }
        )
        await send({"type": "http.response.body", "body": response[:3], "more_body": True})
        await send({"type": "http.response.body", "body": response[3:]})

    return app


def test_only_the_mcp_path_is_captured_and_others_pass_untouched() -> None:
    collector = _Collector()
    seen: list[tuple[object, object]] = []

    async def inner(scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401
        seen.append((receive, send))

    wrapped = McpInteractionCapture(inner, collector, path=MCP_PATH)  # type: ignore[arg-type]
    for path in ("/token", "/authorize", "/healthz", "/readyz", "/mcp/", "/.well-known/x"):
        _drive(wrapped, path, [b"{}"])
    assert collector.exchanges == []
    assert all(callable(receive) and receive.__name__ == "receive" for receive, _ in seen)
    assert all(send.__name__ == "send" for _, send in seen)  # type: ignore[attr-defined]


def test_the_tee_passes_every_message_unchanged_and_records_the_whole_body() -> None:
    collector = _Collector()
    body = b'{"jsonrpc":"2.0","id":1,"method":"ping"}'
    direct, _ = _drive(_echo_app(), "/mcp", [body[:10], body[10:]])
    sent, scope = _drive(
        McpInteractionCapture(_echo_app(), collector, path=MCP_PATH),  # type: ignore[arg-type]
        "/mcp",
        [body[:10], body[10:]],
    )
    assert sent == direct
    (exchange,) = collector.exchanges
    assert exchange.request_body == body
    assert exchange.request_bytes == len(body)
    assert exchange.response_body == b'{"ok":true}'
    assert exchange.http_status == 200
    assert exchange.access == "ACCESS"
    assert exchange.latency_ms >= 0
    assert exchange.started_at.tzinfo is not None
    assert scope["state"] == {"remote_mcp_access": "ACCESS"}


def test_a_body_past_the_buffer_ceiling_is_counted_whole_and_hashed_as_a_prefix() -> None:
    collector = _Collector()
    chunk = b"z" * (1024 * 1024)
    chunks = [chunk] * 16 + [b"tail-bytes"]
    _drive(McpInteractionCapture(_echo_app(), collector, path=MCP_PATH), "/mcp", chunks)  # type: ignore[arg-type]
    (exchange,) = collector.exchanges
    whole = b"".join(chunks)
    assert exchange.request_bytes == len(whole)
    assert len(exchange.request_body) == BUFFER_CEILING_BYTES
    assert exchange.request_overflowed is True
    row = _row(exchange)
    assert row["request_truncated"] is True
    assert row["diagnostics"]["capture"]["request_parse"] == "not_captured"  # type: ignore[index]
    assert row["diagnostics"]["capture"]["request_hash_scope"] == "redacted_prefix"  # type: ignore[index]
    assert row["request_sha256"] == hashlib.sha256(b"z" * BUFFER_CEILING_BYTES).hexdigest()


def test_a_partly_read_body_under_the_ceiling_is_truncated_and_hashed_as_a_prefix() -> None:
    """The app stops reading (or the client goes away) before `more_body` ends.

    Small, so nothing overflowed the buffer: only "never completed" marks the
    body as partial, and that alone must make it a truncated prefix.
    """
    collector = _Collector()
    first = b'{"jsonrpc":"2.0","id":1,'

    async def reads_once(scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401
        await receive()
        await send({"type": "http.response.start", "status": 400, "headers": []})
        await send({"type": "http.response.body", "body": b""})

    _drive(
        McpInteractionCapture(reads_once, collector, path=MCP_PATH),  # type: ignore[arg-type]
        "/mcp",
        [first, b'"method":"ping"}'],
    )
    (exchange,) = collector.exchanges
    assert exchange.request_bytes == len(first) < BODY_CAP_BYTES
    assert exchange.request_overflowed is True
    row = _row(exchange)
    assert row["request_truncated"] is True
    assert row["request_body"] is None
    assert row["request_body_text"] == first.decode()
    capture_facts = row["diagnostics"]["capture"]  # type: ignore[index]
    assert capture_facts["request_parse"] == "not_captured"
    assert capture_facts["request_hash_scope"] == "redacted_prefix"
    assert row["request_sha256"] == hashlib.sha256(first).hexdigest()


def test_a_failing_tee_leaves_the_exchange_untouched(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = _Collector()

    def explode(*_args: object) -> None:
        raise RuntimeError("tee broke")

    direct, _ = _drive(_echo_app(), "/mcp", [b"{}"])
    monkeypatch.setattr(capture._Exchange, "on_response", explode)
    monkeypatch.setattr(capture._Exchange, "on_request", explode)
    sent, _ = _drive(McpInteractionCapture(_echo_app(), collector, path=MCP_PATH), "/mcp", [b"{}"])  # type: ignore[arg-type]
    assert sent == direct
    assert collector.errors == 1
    assert collector.exchanges == []


def test_a_failing_start_passes_the_request_through(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = _Collector()

    def explode(self: object, scope: object) -> None:
        raise RuntimeError("start broke")

    monkeypatch.setattr(capture._Exchange, "__init__", explode)
    direct, _ = _drive(_echo_app(), "/mcp", [b"{}"])
    sent, _ = _drive(McpInteractionCapture(_echo_app(), collector, path=MCP_PATH), "/mcp", [b"{}"])  # type: ignore[arg-type]
    assert sent == direct
    assert collector.errors == 1


def test_an_app_exception_still_records_and_still_propagates() -> None:
    collector = _Collector()

    async def broken(scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401
        await receive()
        raise LookupError("app broke")

    with pytest.raises(LookupError):
        _drive(McpInteractionCapture(broken, collector, path=MCP_PATH), "/mcp", [b"{}"])  # type: ignore[arg-type]
    (exchange,) = collector.exchanges
    assert exchange.http_status is None
    assert _row(exchange)["outcome"] == "http_error"


def test_lifespan_shutdown_stops_the_recorder_before_the_app_hears_it() -> None:
    collector = _Collector()
    messages = [{"type": "lifespan.startup"}, {"type": "lifespan.shutdown"}]
    observed: list[bool] = []

    async def app(scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401
        for _ in range(2):
            await receive()
            observed.append(collector.stopped)

    async def receive() -> dict[str, object]:
        return messages.pop(0)

    async def send(_message: object) -> None:
        return None

    wrapped = McpInteractionCapture(app, collector, path=MCP_PATH)  # type: ignore[arg-type]
    asyncio.run(wrapped({"type": "lifespan"}, receive, send))
    assert observed == [False, True]
    assert collector.exchanges == []


# ---- configuration and composition ------------------------------------------


def test_the_interaction_log_is_off_by_default_and_parses_as_a_boolean() -> None:
    assert load_settings({f"{ENV_PREFIX}DATABASE_URL": _URL}).mcp_interaction_log_enabled is False
    enabled = load_settings(
        {f"{ENV_PREFIX}DATABASE_URL": _URL, f"{ENV_PREFIX}MCP_INTERACTION_LOG_ENABLED": "true"}
    )
    assert enabled.mcp_interaction_log_enabled is True
    with pytest.raises(SettingsError):
        load_settings(
            {
                f"{ENV_PREFIX}DATABASE_URL": _URL,
                f"{ENV_PREFIX}MCP_INTERACTION_LOG_ENABLED": "maybe",
            }
        )


def test_disabled_the_app_is_returned_unwrapped_with_no_thread_and_no_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("no engine may be built while the log is disabled")

    monkeypatch.setattr(gateway, "create_database_engine", refuse)
    app = _echo_app()
    before = threading.active_count()
    served, close = gateway.with_interaction_log(Settings(database_url=_URL), app)
    assert served is app
    assert threading.active_count() == before
    close()


def test_enabled_the_app_is_wrapped_and_the_closer_stops_and_disposes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    built: list[dict[str, object]] = []

    class FakeEngine:
        disposed = False

        def dispose(self) -> None:
            FakeEngine.disposed = True

    def fake_engine(url: object, **kwargs: object) -> FakeEngine:
        built.append({"url": url, **kwargs})
        return FakeEngine()

    monkeypatch.setattr(gateway, "create_database_engine", fake_engine)
    settings = Settings(database_url=_URL, mcp_interaction_log_enabled=True)
    app = _echo_app()
    served, close = gateway.with_interaction_log(settings, app)
    assert isinstance(served, McpInteractionCapture)
    assert served.app is app
    # The composition root is what names the captured route and the façade
    # tools; the adapter imports neither (test_transport_parity).
    assert served.path == MCP_PATH == "/mcp"
    assert (
        served.recorder.facade_invoke_tools
        == frozenset({READ_TOOL, WRITE_TOOL, OPERATOR_TOOL})
        == frozenset({"my_pa.read", "my_pa.write", "my_pa.operator"})
    )
    assert built == [
        {
            "url": settings.parsed_database_url(),
            "statement_timeout_ms": gateway.INTERACTION_LOG_STATEMENT_TIMEOUT_MS,
        }
    ]
    writer = [t for t in threading.enumerate() if t.name == "mcp-interaction-writer"]
    assert writer
    close()
    assert FakeEngine.disposed is True
    _wait_for(lambda: not any(t.is_alive() for t in writer))


def test_mcp_remote_serves_the_wrapped_app_and_closes_the_log_in_its_finally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`_mcp_remote` hands uvicorn the capture, not the bare app, and always closes it.

    uvicorn is made to raise, as a signal re-raised after shutdown would, so the
    closer is proven to run on the `finally` path rather than only after a
    clean return; the runtime is closed after it.
    """
    events: list[str] = []
    bare = _echo_app()

    class FakeEngine:
        def dispose(self) -> None:
            events.append("dispose")

    class Runtime:
        principal = None
        service = object()
        work_engine = SimpleNamespace(begin=lambda: None, connect=lambda: None)

        def close(self) -> None:
            events.append("runtime_close")

    settings = SimpleNamespace(
        remote_mcp_enabled=True,
        oauth_authorization_server="https://issuer.invalid",
        oauth_audience="https://resource.invalid",
        oauth_scopes="relationship.read",
        remote_mcp_public_host="mcp.invalid",
        mcp_surface_disabled=False,
        remote_writes_enabled=False,
        oauth_operator_secret=None,
        mcp_interaction_log_enabled=True,
        parsed_database_url=lambda: _URL,
    )
    monkeypatch.setattr(gateway, "load_settings", lambda: settings)
    monkeypatch.setattr(gateway, "build_gateway_runtime", lambda _settings: Runtime())
    monkeypatch.setattr(gateway, "create_database_engine", lambda *_a, **_k: FakeEngine())
    monkeypatch.setattr(
        gateway, "OriginOAuthServer", lambda **_kwargs: SimpleNamespace(introspect=None)
    )
    monkeypatch.setattr(
        gateway, "RemoteAuthenticator", lambda **_kwargs: SimpleNamespace(authenticate=None)
    )
    monkeypatch.setattr(gateway, "build_origin_oauth_routes", lambda *_args, **_kwargs: ())
    monkeypatch.setattr(gateway, "create_remote_mcp_app", lambda *_args, **_kwargs: bare)
    served: list[object] = []
    writers: list[threading.Thread] = []

    def run(app: object, **_kwargs: object) -> None:
        served.append(app)
        writers.extend(t for t in threading.enumerate() if t.name == "mcp-interaction-writer")
        events.append("serve")
        raise RuntimeError("serving stopped by a signal")

    monkeypatch.setattr(gateway.uvicorn, "run", run)
    with pytest.raises(RuntimeError, match="serving stopped by a signal"):
        gateway._mcp_remote(argparse.Namespace(host="127.0.0.1", port=8766))
    (app,) = served
    assert isinstance(app, McpInteractionCapture)
    assert app.app is bare
    assert writers
    assert events == ["serve", "dispose", "runtime_close"]
    _wait_for(lambda: not any(t.is_alive() for t in writers))


# ---- widened redaction (review N1) and the queued-bytes budget (review N2) ----


@pytest.mark.parametrize(
    "key",
    [
        "accessToken",
        "refreshToken",
        "clientSecret",
        "idToken",
        "privateKey",
        "auth_token",
        "oauth_token",
        "github_token",
        "x_api_key",
        "X-Api-Key",
        "db_password",
        "Code Verifier",
        "sessionCookie",
    ],
)
def test_camel_case_spaced_and_suffixed_credential_keys_are_redacted(key: str) -> None:
    redacted, count, _ = redact_json({"wrap": {key: "MARKERWIDE", "kept": 1}})
    assert redacted == {"wrap": {key: REDACTED, "kept": 1}}
    assert count == 1


def test_token_named_fields_that_are_not_credentials_are_kept() -> None:
    document = {"tokens": ["a"], "max_tokens": 5, "token_count": 3, "nextCursor": "c1"}
    redacted, count, _ = redact_json(document)
    assert redacted == document
    assert count == 0


@pytest.mark.parametrize(
    "raw",
    [
        '{"password": 12345, "x": 1',
        '{"token": true, "x": 1',
        '{"accessToken": null, "x": 1',
        '{"github_token": -3.5e2, "x": 1',
        '\\"x_api_key\\": 98765, \\"x\\": 1',
        "{'clientSecret': 424242, 'x': 1",
    ],
)
def test_the_text_path_redacts_scalar_values_and_widened_keys(raw: str) -> None:
    text, count, _ = redact_text(raw)
    for marker in ("12345", "true", "null", "-3.5e2", "98765", "424242"):
        assert marker not in text
    assert REDACTED in text
    assert count == 1


def test_basic_credentials_in_text_are_redacted_and_prose_is_not() -> None:
    text, count, _ = redact_text("sent Basic dXNlcjpwYXNzd29yZA== then a basic setup")
    assert text == f"sent Basic {REDACTED} then a basic setup"
    assert count == 1
    redacted, count, _ = redact_json({"note": "sent basic QWxhZGRpbjpvcGVu here"})
    assert redacted == {"note": f"sent basic {REDACTED} here"}


def test_cookie_header_lines_in_text_are_redacted() -> None:
    text, count, _ = redact_text(
        "GET /\r\nCookie: session=MARKERCOOKIE1; theme=dark\r\n"
        "Set-Cookie: sid=MARKERCOOKIE2; HttpOnly\r\nAccept: */*"
    )
    assert "MARKERCOOKIE" not in text
    assert text.endswith(f"Cookie: {REDACTED}\r\nSet-Cookie: {REDACTED}\r\nAccept: */*")
    assert count == 2
    redacted, _, _ = redact_json({"echo": "cookie: a=MARKERCOOKIE3"})
    assert "MARKERCOOKIE3" not in json.dumps(redacted)


def test_the_queued_bytes_budget_drops_counts_and_is_released_after_a_write() -> None:
    rows: list[Mapping[str, object]] = []
    recorder = InteractionRecorder(
        rows.append, facade_invoke_tools=FACADE, max_queued_bytes=100, stderr=io.StringIO()
    )
    body = {"pad": "x" * 30}
    size = len(json.dumps(body).encode())  # 41 bytes; two fit in 100, three do not
    began = time.monotonic()
    recorder.submit(_exchange(body))
    recorder.submit(_exchange(body))
    recorder.submit(_exchange(body))  # 3 x 41 > 100: dropped, not waited for
    assert time.monotonic() - began < 0.5
    assert recorder.dropped == 1
    assert recorder.queued_bytes == 2 * size
    recorder.start()
    try:
        _wait_for(lambda: len(rows) == 2)
        _wait_for(lambda: recorder.queued_bytes == 0)
        recorder.submit(_exchange(body))
        recorder.submit(_exchange(body))
        _wait_for(lambda: len(rows) == 4)
    finally:
        recorder.stop()
    assert recorder.dropped == 1
    assert recorder.queued_bytes == 0
    assert capture.QUEUED_BYTES_BUDGET == 64 * 1024 * 1024
    assert capture.QUEUED_BYTES_BUDGET >= 2 * BUFFER_CEILING_BYTES


# ---- linear patterns, non-finite JSON, wider coverage (review B1, B2, N1-N4) ----

#: Shape tables and measurement helpers live in `tests/unit/redaction_probe.py`
#: so each linearity probe can also run in a subprocess under a timeout.
_MIB = probe._MIB
_PEM_BEGIN = probe._PEM_BEGIN
_PEM_END = probe._PEM_END
_PEM_CERT_END = probe._PEM_CERT_END
_assert_linear = probe._assert_linear
#: Wall-clock limit for one probe subprocess. Idle, the slowest probe finishes
#: in about 2 s, and under 20 busy loops on 14 cores in about 6 s, so 60 s is a
#: 10x margin; a quadratic regression is cut off here instead of running for
#: minutes (a quadratic `_DOTTED_RUN` ran over 600 s in-process at 1 MiB).
_PROBE_TIMEOUT_SECONDS = 60
_ROOT = Path(__file__).resolve().parents[2]


def _run_probe(kind: str, name: str) -> None:
    """Run one probe of `redaction_probe` in a subprocess, failing within the timeout."""
    environment = {
        **os.environ,
        "PYTHONPATH": os.pathsep.join([str(_ROOT / "src"), str(_ROOT)]),
    }
    began = time.monotonic()
    try:
        done = subprocess.run(  # noqa: S603 - fixed interpreter, fixed module, table keys
            [sys.executable, "-m", "tests.unit.redaction_probe", kind, name],
            cwd=_ROOT,
            env=environment,
            capture_output=True,
            text=True,
            timeout=_PROBE_TIMEOUT_SECONDS,
            check=False,
        )
    except subprocess.TimeoutExpired:
        pytest.fail(
            f"{kind} probe {name!r} did not finish within {_PROBE_TIMEOUT_SECONDS}s "
            f"({time.monotonic() - began:.0f}s): super-linear"
        )
    assert done.returncode == 0, done.stderr[-4000:]


@pytest.mark.parametrize("family", sorted(probe._ADVERSARIAL))
def test_every_redaction_pattern_family_is_linear_on_adversarial_input(family: str) -> None:
    _run_probe("family", family)


def test_an_adversarial_tools_call_body_builds_its_row_quickly() -> None:
    """The reviewer's shape on the full row path: up to a ~450 KB tools/call body.

    Timed like the probes below: a 16x size spread, minimum of three, a ratio
    judged only on a measurable large sample, and the absolute backstop.
    """

    def body(scale: int) -> CapturedExchange:
        arguments = {
            "a": "eyJ" * (3_750 * scale),
            "b": "\\" * (10_000 * scale),
            "c": '\\"token\\":' * (625 * scale),
        }
        return _exchange(_call("tasks.list", arguments))

    exchanges = {1: body(1), 16: body(16)}
    _assert_linear(_row, exchanges.__getitem__, "tools/call row", sizes=(1, 16))
    assert _row(exchanges[16])["outcome"] == "ok"


@pytest.mark.parametrize(
    ("raw", "stored"),
    [
        (b'{"x": NaN, "y": 1}', {"x": "NaN", "y": 1}),
        (b'{"x": Infinity, "y": -Infinity}', {"x": "Infinity", "y": "-Infinity"}),
        (b'{"x": 1e999, "y": 1.5}', {"x": "1e999", "y": 1.5}),
        (b'{"x": -1e999}', {"x": "-1e999"}),
    ],
)
def test_non_finite_numbers_are_kept_as_strings_and_flagged(raw: bytes, stored: object) -> None:
    row = _row(_exchange(raw_request=raw, raw_response=raw))
    assert row["request_body"] == stored
    assert row["response_body"] == stored
    assert row["diagnostics"]["capture"]["non_finite_replaced"] is True  # type: ignore[index]
    # What JSONB will be handed is strict JSON.
    json.dumps(row["request_body"], allow_nan=False)
    assert _row(_exchange({"x": 1.5}))["diagnostics"]["capture"]["non_finite_replaced"] is False  # type: ignore[index]


def test_basic_prose_of_any_case_shape_is_kept() -> None:
    phrase = "Here is basic information about the project and Basic overview"
    text, count, _ = redact_text(phrase)
    assert text == phrase
    assert count == 0


@pytest.mark.parametrize(
    "key",
    [
        "aws_secret_access_key",
        "secretAccessKey",
        "secret_key",
        "accessKey",
        "aws_access_key",
        "authorization_code",
        "authorizationCode",
        "secrets",
        "app_secrets",
        "pwd",
        "passwd",
        "db_passwd",
    ],
)
def test_the_added_credential_keys_are_redacted_in_json_and_in_text(key: str) -> None:
    redacted, count, _ = redact_json({key: "MARKERADDED"})
    assert redacted == {key: REDACTED}
    assert count == 1
    text, count, _ = redact_text(f'{{"{key}": "MARKERADDED", "x": 1')
    assert "MARKERADDED" not in text
    assert count == 1


def test_code_and_domain_code_fields_are_kept() -> None:
    document = {"code": "invalid_request", "status_code": 3, "country_code": "US"}
    assert redact_json(document) == (document, 0, False)
    text = '{"code": "abc", "status_code": "x"} ?code=abc&state=s'
    assert redact_text(text) == (text, 0, False)


def test_a_pem_private_key_block_is_redacted_whole_and_when_cut_off() -> None:
    block = (
        _PEM_BEGIN.format(kind="RSA ")
        + "\nMIIEMARKERPEMBODY\nmore-lines\n"
        + _PEM_END.format(kind="RSA ")
    )
    text, count, _ = redact_text(f"before {block} after")
    assert text == f"before {REDACTED} after"
    assert count == 1
    redacted, _, _ = redact_json({"pem": "x", "note": f"key: {block}"})
    assert "MARKERPEMBODY" not in json.dumps(redacted)
    cut, count, _ = redact_text("head " + _PEM_BEGIN.format(kind="") + "\nMIIEMARKERCUT")
    assert cut == f"head {REDACTED}"
    assert count == 1


def test_query_string_and_form_credentials_are_redacted() -> None:
    text, count, _ = redact_text(
        "grant_type=authorization_code&client_secret=S1&code_verifier=V2"
        "&refresh_token=R3&password=P4&api_key=K5&github_token=G6&code=keep&state=keep"
    )
    assert text == (
        f"grant_type=authorization_code&client_secret={REDACTED}&code_verifier={REDACTED}"
        f"&refresh_token={REDACTED}&password={REDACTED}&api_key={REDACTED}"
        f"&github_token={REDACTED}&code=keep&state=keep"
    )
    assert count == 6


@pytest.mark.parametrize(
    ("cut", "expected"),
    [
        ('{"x": 1, "refresh_token":"ABCDEFGH', '{"x": 1, "refresh_token":"' + REDACTED),
        ('{"x": 1, "apiKey": "ABC\\"DEF', '{"x": 1, "apiKey": "' + REDACTED),
        (
            '"t": "{\\"x\\":1,\\"access_token\\":\\"ABCDEF',
            '"t": "{\\"x\\":1,\\"access_token\\":\\"' + REDACTED,
        ),
    ],
)
def test_a_credential_value_cut_off_by_the_end_of_the_text_is_redacted(
    cut: str, expected: str
) -> None:
    text, count, _ = redact_text(cut)
    assert text == expected
    assert count == 1


def test_a_cut_off_credential_in_an_overflowed_body_never_reaches_the_row() -> None:
    raw = b'{"jsonrpc":"2.0","params":{"refresh_token":"MARKERCUTOFF'
    row = _row(_exchange(raw_request=raw, request_overflowed=True))
    assert "MARKERCUTOFF" not in _serialized(row)


def test_drops_are_reported_count_only_at_the_first_and_then_rate_limited() -> None:
    stderr = io.StringIO()
    recorder = InteractionRecorder(
        lambda _row: None, facade_invoke_tools=FACADE, maxsize=1, stderr=stderr
    )
    for _ in range(4):
        recorder.submit(_exchange({"password": "MARKERDROP"}))
    lines = stderr.getvalue().splitlines()
    assert lines == ["mcp-interaction-log dropped dropped=1 write_failures=0 capture_errors=0"]
    eager = io.StringIO()
    every = InteractionRecorder(
        lambda _row: None,
        facade_invoke_tools=FACADE,
        maxsize=1,
        stderr=eager,
        drop_report_seconds=0.0,
    )
    for _ in range(4):
        every.submit(_exchange())
    assert [line.split()[2] for line in eager.getvalue().splitlines()] == [
        "dropped=1",
        "dropped=2",
        "dropped=3",
    ]
    assert "MARKERDROP" not in stderr.getvalue() + eager.getvalue()
    assert capture.DROP_REPORT_SECONDS == 60.0


def test_every_compiled_pattern_has_probe_shapes() -> None:
    assert {probe._shape_key(name) for name in probe._compiled_patterns()} == set(
        probe._PATTERN_SHAPES
    )


@pytest.mark.parametrize("name", sorted(probe._compiled_patterns()))
def test_every_compiled_pattern_is_linear_on_its_worst_case_shapes(name: str) -> None:
    _run_probe("pattern", name)


@pytest.mark.parametrize("name", sorted(probe._REVIEWER_INPUTS))
def test_the_reviewers_quadratic_inputs_are_linear_through_redact_text(name: str) -> None:
    _run_probe("reviewer", name)


def test_url_userinfo_passwords_are_redacted() -> None:
    text, count, _ = redact_text(
        "dsn postgresql+psycopg://app:MARKERURLPASS@db.example/x and https://example.org/a:b@c"
    )
    assert text == (
        f"dsn postgresql+psycopg://app:{REDACTED}@db.example/x and https://example.org/a:b@c"
    )
    assert count == 1
    redacted, _, _ = redact_json({"url": "ftp://u:MARKERFTP@h"})
    assert redacted == {"url": f"ftp://u:{REDACTED}@h"}


@pytest.mark.parametrize(
    ("line", "expected"),
    [
        ("Authorization: Token MARKERHDR1", f"Authorization: {REDACTED}"),
        ("authorization: Digest username=x, response=MARKERHDR2", f"authorization: {REDACTED}"),
        ("Proxy-Authorization: Basic MARKERHDR3", f"Proxy-Authorization: {REDACTED}"),
        ("X-Api-Key: MARKERHDR4", f"X-Api-Key: {REDACTED}"),
        ("X-Auth-Token:MARKERHDR5", f"X-Auth-Token: {REDACTED}"),
        ("X-Client-Secret: MARKERHDR6", f"X-Client-Secret: {REDACTED}"),
    ],
)
def test_credential_header_lines_of_any_scheme_are_redacted(line: str, expected: str) -> None:
    text, count, _ = redact_text(f"GET /\r\n{line}\r\nAccept: */*")
    assert text == f"GET /\r\n{expected}\r\nAccept: */*"
    assert count == 1


def test_dotted_credential_keys_are_redacted_on_the_text_path() -> None:
    text, count, _ = redact_text('{"oauth.token": "MARKERDOT1", "a.b.client_secret": 7, "x": 1')
    assert "MARKERDOT1" not in text
    assert '"a.b.client_secret": "[REDACTED]"' in text
    assert count == 2
    form, count, _ = redact_text("oauth.token=MARKERDOT2&x=1")
    assert form == f"oauth.token={REDACTED}&x=1"
    assert count == 1
    redacted, _, _ = redact_json({"oauth.token": "MARKERDOT3"})
    assert redacted == {"oauth.token": REDACTED}


def test_escaped_pairs_keep_deeper_quotes_inside_the_redacted_value() -> None:
    level_one = 'a \\"apiKey\\": \\"AB\\\\\\"CD\\" z'
    text, count, _ = redact_text(level_one)
    assert text == f'a \\"apiKey\\": \\"{REDACTED}\\" z'
    assert count == 1
    level_three = "\\\\\\" + '"token' + "\\\\\\" + '":' + "\\\\\\" + '"MARKERL3' + "\\\\\\" + '" y'
    text, count, _ = redact_text(level_three)
    assert "MARKERL3" not in text
    assert count == 1


def test_a_pgp_private_key_block_and_a_near_miss_end_are_redacted() -> None:
    begin = "-----BEGIN " + "PGP PRIVATE KEY BLOCK-----"
    end = "-----END " + "PGP PRIVATE KEY BLOCK-----"
    text, count, _ = redact_text(f"a {begin}\nMARKERPGP\n{end} b")
    assert text == f"a {REDACTED} b"
    assert count == 1
    near, count, _ = redact_text(_PEM_BEGIN.format(kind="") + "\nMARKERNEAR\n" + _PEM_CERT_END)
    assert near == REDACTED + _PEM_CERT_END
    assert count == 1


# ---- redact before cutting metadata; object keys; colon lines; throttling (review 4) ----

#: A URL whose `@` lands past the 256-character metadata cut.
_STRADDLE = "x" * 230 + " https://u:MARKERMETA9" + "Q" * 40 + "@host"


@pytest.mark.parametrize("column", ["jsonrpc_id", "tool_name", "capability", "header"])
def test_metadata_is_redacted_whole_before_it_is_cut(column: str) -> None:
    if column == "jsonrpc_id":
        exchange = _exchange({"jsonrpc": "2.0", "id": _STRADDLE, "method": "m"})
    elif column == "tool_name":
        exchange = _exchange(_call(_STRADDLE, {}))
    elif column == "capability":
        exchange = _exchange(_call("my_pa.read", {"capability": _STRADDLE, "arguments": {}}))
    else:
        exchange = _exchange(request_headers=((b"user-agent", _STRADDLE.encode()),))
    row = _row(exchange)
    stored = row["request_headers"]["user-agent"] if column == "header" else row[column]  # type: ignore[index]
    assert isinstance(stored, str)
    assert len(stored) <= 256
    assert "MARKERMETA9" not in stored
    assert "MARKERMETA9" not in json.dumps(row["request_headers"]) + str(row["jsonrpc_id"])
    assert stored == ("x" * 230 + f" https://u:{REDACTED}@host")[:256]


@pytest.mark.parametrize(
    "key",
    [
        "https://u:MARKERKEY1@h/x",
        "Bearer MARKERKEY2xyz",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiJNQVJLRVJLRVkzIn0.sig",
    ],
)
def test_object_keys_are_redacted_like_strings(key: str) -> None:
    redacted, count, _ = redact_json({"sources": {key: {"n": 1}}, "plain": 1})
    text = json.dumps(redacted)
    assert "MARKERKEY" not in text
    assert "eyJzdWIi" not in text
    assert count == 1
    assert redacted["plain"] == 1  # type: ignore[index]


def test_a_key_inside_an_embedded_document_is_redacted_with_or_without_other_redactions() -> None:
    for extra in ({}, {"token": "t"}):
        inner = json.dumps({"sources": {"https://u:MARKEREMB@h/x": {"n": 1}}, **extra})
        row = _row(_exchange(_call("documents.read", {}), _tool_result(inner, is_error=False)))
        assert "MARKEREMB" not in _serialized(row)


def test_keys_that_collide_after_redaction_keep_every_value() -> None:
    redacted, count, _ = redact_json(
        {
            "Bearer AAAAAAAA": 1,
            "Bearer BBBBBBBB": 2,
            "Bearer CCCCCCCC": 3,
            "Bearer [REDACTED] #2": 4,
        }
    )
    assert redacted == {
        "Bearer [REDACTED]": 1,
        "Bearer [REDACTED] #2": 2,
        "Bearer [REDACTED] #3": 3,
        "Bearer [REDACTED] #2 #2": 4,
    }
    assert count == 3


@pytest.mark.parametrize(
    "line",
    [
        "password: MARKERCOLON1",
        "  api_key: MARKERCOLON2",
        "client_secret:MARKERCOLON3",
        "x_api_key :  MARKERCOLON4 trailing",
        "DB_PASSWORD: MARKERCOLON5",
    ],
)
def test_colon_style_credential_lines_are_redacted(line: str) -> None:
    text, count, _ = redact_text(f"config:\n{line}\nname: kept")
    assert "MARKERCOLON" not in text
    assert text.endswith("\nname: kept")
    assert count == 1


def test_colon_lines_do_not_touch_non_credential_keys_or_mid_line_text() -> None:
    text = "status: open\npassword_hint: kept\nthe password: is a word here"
    assert redact_text(text) == (text, 0, False)


def test_write_failures_are_reported_at_the_first_and_then_rate_limited() -> None:
    def failing(_row: Mapping[str, object]) -> None:
        raise ConnectionError("MARKERDBDOWN")

    stderr = io.StringIO()
    recorder = InteractionRecorder(failing, facade_invoke_tools=FACADE, stderr=stderr)
    recorder.start()
    try:
        for _ in range(5):
            recorder.submit(_exchange({"password": "MARKERFAILROW"}))
        _wait_for(lambda: recorder.write_failures == 5)
    finally:
        recorder.stop()
    assert stderr.getvalue().splitlines() == [
        "mcp-interaction-log write_failed dropped=0 write_failures=1 capture_errors=0"
    ]
    eager = io.StringIO()
    every = InteractionRecorder(
        failing, facade_invoke_tools=FACADE, stderr=eager, drop_report_seconds=0.0
    )
    every.start()
    try:
        for _ in range(3):
            every.submit(_exchange())
        _wait_for(lambda: every.write_failures == 3)
    finally:
        every.stop()
    assert eager.getvalue().count("write_failed") == 3
    assert "MARKER" not in stderr.getvalue() + eager.getvalue()
