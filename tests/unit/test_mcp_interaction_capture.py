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
import threading
import time
from collections.abc import Mapping
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Any

import apps.gateway as gateway
import pytest

from my_pa.adapters import mcp_interaction_capture as capture
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

_URL = "postgresql+psycopg://someone@db.invalid:5432/somewhere"
_WHEN = datetime(2026, 10, 11, 12, 0, tzinfo=UTC)


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
    row = build_interaction_row(_exchange({"jsonrpc": "2.0", "id": 1, "method": "ping"}))
    assert frozenset(INTERACTION_COLUMNS) == store.INSERT_COLUMNS
    assert frozenset(row) == store.INSERT_COLUMNS
    assert BODY_CAP_BYTES == store.BODY_CAP_BYTES
    assert row["outcome"] in store.OUTCOMES


def test_the_interaction_id_is_the_prefixed_uuid4_hex() -> None:
    first = build_interaction_row(_exchange())["interaction_id"]
    second = build_interaction_row(_exchange())["interaction_id"]
    assert isinstance(first, str)
    assert first.startswith("mcpi_") and len(first) == 37
    assert all(c in "0123456789abcdef" for c in first[5:])
    assert first != second


def test_empty_bodies_store_nothing_and_hash_the_empty_string() -> None:
    row = build_interaction_row(_exchange(status=202))
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
    row = build_interaction_row(_exchange(status=401, request_overflowed=True))
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
    row = build_interaction_row(
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
    from_request = build_interaction_row(
        _exchange(request_headers=((b"mcp-session-id", b"sess-1"),))
    )
    from_response = build_interaction_row(
        _exchange(response_headers=((b"mcp-session-id", b"sess-2"),))
    )
    assert from_request["mcp_session_id"] == "sess-1"
    assert from_response["mcp_session_id"] == "sess-2"
    assert build_interaction_row(_exchange())["mcp_session_id"] is None


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
    row = build_interaction_row(
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
    row = build_interaction_row(
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
    row = build_interaction_row(
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
    row = build_interaction_row(_exchange(raw_request=raw))
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
    row = build_interaction_row(
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
    row = build_interaction_row(
        _exchange({"jsonrpc": "2.0", "id": "Bearer MARKERID", "method": "m" * 1000})
    )
    assert row["jsonrpc_id"] == f"Bearer {REDACTED}"
    assert row["jsonrpc_method"] == "m" * 256


# ---- caps, truncation, hashing ----------------------------------------------


def test_a_json_body_within_the_cap_is_stored_as_json() -> None:
    request = {"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {"pad": "x" * 1000}}
    row = build_interaction_row(_exchange(request))
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
    row = build_interaction_row(_exchange(raw_request=raw))
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
    row = build_interaction_row(_exchange(raw_request=raw))
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
    row = build_interaction_row(_exchange(raw_request=raw))
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
    row = build_interaction_row(_exchange(raw_request=raw))
    text = row["request_body_text"]
    assert isinstance(text, str)
    assert len(text.encode()) <= BODY_CAP_BYTES
    assert "QQQQ" not in text
    assert row["request_truncated"] is True


def test_truncation_never_splits_a_multibyte_character() -> None:
    raw = ("é" * BODY_CAP_BYTES).encode()  # two bytes each; not JSON
    row = build_interaction_row(_exchange(raw_request=raw))
    text = row["request_body_text"]
    assert isinstance(text, str)
    assert text == "é" * (BODY_CAP_BYTES // 2)


def test_nul_is_replaced_and_flagged_in_json_and_in_text() -> None:
    json_row = build_interaction_row(_exchange({"text": "a\u0000b", "k\u0000": 1}))
    assert json_row["request_body"] == {"text": "a�b", "k�": 1}
    assert json_row["diagnostics"]["capture"]["nul_replaced"] is True  # type: ignore[index]
    text_row = build_interaction_row(_exchange(raw_request=b"not json \x00 here"))
    assert text_row["request_body_text"] == "not json � here"
    assert text_row["diagnostics"]["capture"]["nul_replaced"] is True  # type: ignore[index]
    assert "\x00" not in _serialized(json_row) + _serialized(text_row)


def test_a_lone_surrogate_is_made_encodable() -> None:
    row = build_interaction_row(_exchange(raw_request=b'{"t": "\\ud800x"}'))
    _serialized(row).encode("utf-8")
    assert row["diagnostics"]["capture"]["nul_replaced"] is True  # type: ignore[index]


# ---- JSON-RPC metadata -------------------------------------------------------


def test_a_canonical_tools_call_names_tool_and_capability() -> None:
    row = build_interaction_row(_exchange(_call("tasks.list", {}, request_id="abc")))
    assert row["jsonrpc_method"] == "tools/call"
    assert row["jsonrpc_id"] == "abc"
    assert row["tool_name"] == "tasks.list"
    assert row["capability"] == "tasks.list"


@pytest.mark.parametrize("facade", ["my_pa.read", "my_pa.write", "my_pa.operator"])
def test_a_facade_invoke_records_the_canonical_capability(facade: str) -> None:
    row = build_interaction_row(
        _exchange(_call(facade, {"capability": "tasks.update", "arguments": {}}, request_id=7))
    )
    assert row["tool_name"] == facade
    assert row["capability"] == "tasks.update"
    assert row["jsonrpc_id"] == "7"


def test_describe_and_malformed_facade_calls_fall_back_to_the_tool_name() -> None:
    describe = build_interaction_row(_exchange(_call("my_pa.describe", {"capability": "x"})))
    malformed = build_interaction_row(_exchange(_call("my_pa.read", {"capability": 3})))
    assert describe["capability"] == "my_pa.describe"
    assert malformed["capability"] == "my_pa.read"


def test_a_batch_array_is_recorded_as_batch() -> None:
    row = build_interaction_row(
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
    assert build_interaction_row(_exchange({"id": True, "method": "m"}))["jsonrpc_id"] is None
    assert build_interaction_row(_exchange({"method": "m"}))["jsonrpc_id"] is None


def test_the_authenticated_context_is_read_by_duck_type() -> None:
    class Kind:
        value = "operator"

    class Principal:
        principal_id = "prn_synthetic"
        kind = Kind()

    class Access:
        principal = Principal()
        authenticated_client_id = "client-synthetic"

    row = build_interaction_row(_exchange(access=Access()))
    assert row["oauth_client_id"] == "client-synthetic"
    assert row["principal_id"] == "prn_synthetic"
    assert row["principal_kind"] == "operator"
    anonymous = build_interaction_row(_exchange())
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
    row = build_interaction_row(
        _exchange(_call("t", {}), _tool_result(json.dumps(envelope), is_error=False))
    )
    assert row["outcome"] == "ok"
    assert row["error_code"] is None
    assert row["correlation_id"] == "corr_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
    assert row["diagnostics"]["is_error"] is False  # type: ignore[index]
    assert row["diagnostics"]["problem"] is None  # type: ignore[index]


def test_an_envelope_error_is_a_tool_error_with_its_problem() -> None:
    envelope = {"correlation_id": _PROBLEM["correlation_id"], "error": _PROBLEM, "result": None}
    row = build_interaction_row(
        _exchange(_call("t", {}), _tool_result(json.dumps(envelope), is_error=True))
    )
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
    row = build_interaction_row(
        _exchange(_call("t", {}), _tool_result(json.dumps(problem), is_error=True))
    )
    assert row["outcome"] == "tool_error"
    assert row["error_code"] == "unsupported"
    assert row["correlation_id"] == _PROBLEM["correlation_id"]


def test_a_jsonrpc_error_records_code_and_message() -> None:
    row = build_interaction_row(
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
    row = build_interaction_row(_exchange(None, {"error": token}, status=status))
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
    row = build_interaction_row(_exchange({"method": "m"}, raw_response=raw, status=status))
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
    recorder = InteractionRecorder(sink, stderr=stderr)
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
    assert report.count("write_failed") == 2
    assert "write_failures=2" in report
    for marker in ("MARKERSTDERR", "MARKERDBERROR", "mcpi_", "password"):
        assert marker not in report


def test_a_full_queue_drops_counts_and_reports_on_the_next_row() -> None:
    rows: list[Mapping[str, object]] = []
    recorder = InteractionRecorder(rows.append, maxsize=1, stderr=io.StringIO())

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
    recorder = InteractionRecorder(rows.append, stderr=io.StringIO())

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

    recorder = InteractionRecorder(slow, stderr=io.StringIO())
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
    recorder = InteractionRecorder(rows.append, stderr=io.StringIO())
    for _ in range(20):
        recorder.submit(_exchange())
    recorder.start()
    recorder.stop(timeout=5)
    assert len(rows) == 20
    assert recorder.dropped == 0


def test_the_writer_is_one_daemon_thread() -> None:
    recorder = InteractionRecorder(lambda _row: None)
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

    wrapped = McpInteractionCapture(inner, collector)  # type: ignore[arg-type]
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
        McpInteractionCapture(_echo_app(), collector),  # type: ignore[arg-type]
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
    _drive(McpInteractionCapture(_echo_app(), collector), "/mcp", chunks)  # type: ignore[arg-type]
    (exchange,) = collector.exchanges
    whole = b"".join(chunks)
    assert exchange.request_bytes == len(whole)
    assert len(exchange.request_body) == BUFFER_CEILING_BYTES
    assert exchange.request_overflowed is True
    row = build_interaction_row(exchange)
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
        McpInteractionCapture(reads_once, collector),  # type: ignore[arg-type]
        "/mcp",
        [first, b'"method":"ping"}'],
    )
    (exchange,) = collector.exchanges
    assert exchange.request_bytes == len(first) < BODY_CAP_BYTES
    assert exchange.request_overflowed is True
    row = build_interaction_row(exchange)
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
    sent, _ = _drive(McpInteractionCapture(_echo_app(), collector), "/mcp", [b"{}"])  # type: ignore[arg-type]
    assert sent == direct
    assert collector.errors == 1
    assert collector.exchanges == []


def test_a_failing_start_passes_the_request_through(monkeypatch: pytest.MonkeyPatch) -> None:
    collector = _Collector()

    def explode(self: object, scope: object) -> None:
        raise RuntimeError("start broke")

    monkeypatch.setattr(capture._Exchange, "__init__", explode)
    direct, _ = _drive(_echo_app(), "/mcp", [b"{}"])
    sent, _ = _drive(McpInteractionCapture(_echo_app(), collector), "/mcp", [b"{}"])  # type: ignore[arg-type]
    assert sent == direct
    assert collector.errors == 1


def test_an_app_exception_still_records_and_still_propagates() -> None:
    collector = _Collector()

    async def broken(scope: Any, receive: Any, send: Any) -> None:  # noqa: ANN401
        await receive()
        raise LookupError("app broke")

    with pytest.raises(LookupError):
        _drive(McpInteractionCapture(broken, collector), "/mcp", [b"{}"])  # type: ignore[arg-type]
    (exchange,) = collector.exchanges
    assert exchange.http_status is None
    assert build_interaction_row(exchange)["outcome"] == "http_error"


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

    wrapped = McpInteractionCapture(app, collector)  # type: ignore[arg-type]
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
