"""Capture remote `/mcp` JSON-RPC exchanges off the request path.

The remote gateway can record every HTTP exchange on its `/mcp` route — request
and response bodies included — into `observability.mcp_interactions`. That is a
deliberate, operator-accepted exception to `AGENTS.md` section 5 ("logs exclude
message bodies by default"), which is why it is off unless
`MY_PA_MCP_INTERACTION_LOG_ENABLED` turns it on, and why everything it stores is
redacted first.

**Two halves, two threads.** `McpInteractionCapture` is ASGI middleware around
the Starlette app `create_remote_mcp_app` returns. On the event loop it only
*tees*: every `http.request` and `http.response.*` message passes through
unchanged, and the tee keeps a reference to each body chunk (up to
`BUFFER_CEILING_BYTES` per body), a byte count of the full wire body, the
status and the response headers. It hashes nothing. After the inner app
returns — so after the final response byte has been handed to the server — the
captured exchange is offered to `InteractionRecorder` with `put_nowait`. One
daemon writer thread then parses the JSON-RPC, redacts, caps, builds the row and
hands it to the injected sink. Nothing here knows what the sink is; the
composition root (`apps/gateway.py`) gives it one that appends through
`infrastructure.persistence.mcp_interactions`.

**Nothing here imports the MCP transport.** The captured path and the façade
tool names whose `arguments.capability` names the canonical target are inputs:
`apps/gateway.py`, the composition root, passes `MCP_PATH` and the three façade
invoke names, so the sibling-transport rule in `test_transport_parity.py` holds.

**Scope is the `/mcp` path and nothing else.** OAuth (`/authorize`, `/token`,
`/register`, ...), health, readiness and protected-resource metadata pass
straight through untouched: they carry credentials and are not JSON-RPC.

**Failure isolation.** Every capture step is wrapped: an exception inside the
tee, the row builder or the sink increments a counter and is otherwise
swallowed, so the request proceeds exactly as it would without the wrapper. The
queue is bounded (`QUEUE_MAXSIZE`); a full queue drops the exchange and counts
it. A failed write is counted, reported as a count-only line on standard error
(never a body, a header or an identifier), and dropped — there is no retry loop.
The counters accumulated since the last successful write ride on the next row
that does get written, as `diagnostics.capture.dropped_before` and
`write_failures_before`.

**Redaction, before truncation.** Headers are allowlisted (`STORED_HEADERS`);
`authorization`, `cookie`, `set-cookie`, `proxy-authorization` and every other
header are never stored. JSON bodies are walked: a value under any key in
`REDACTED_KEYS` (case-insensitive, `-` read as `_`) becomes `"[REDACTED]"`;
every string has `Bearer <token>` and JWT-shaped runs replaced; a string that is
itself a JSON object or array (MCP `TextContent.text` carries the response
envelope that way) is parsed, redacted the same way and re-serialised. A body
that is not JSON, or that overflowed the capture buffer, is redacted as text
(`"key": "value"` pairs for the same keys, plus the Bearer and JWT patterns).
Only then is the result cut to `BODY_CAP_BYTES`, so a credential beyond the cap
never appears and one straddling it is never stored in part. NUL characters,
which PostgreSQL text and JSONB cannot hold, are replaced and flagged.
Bearer and JWT runs are matched anywhere, without a word boundary, so a token
glued to preceding text is still caught (over-redaction is the safe direction).

**What the digests are.** `request_sha256` / `response_sha256` are the SHA-256 of
the *redacted, untruncated* body as this module serialises it — the compact
redacted JSON (`ensure_ascii=False`, `(",", ":")` separators) for a JSON body,
the redacted UTF-8 text otherwise, the empty string for an empty body — computed
on the writer thread before the `BODY_CAP_BYTES` cut. **They are never a digest
of the raw wire body**, so a stored hash cannot serve as an oracle for a
credential the redaction removed. They identify and deduplicate what was stored
and are not wire-integrity checks. When the body was not fully captured (past
`BUFFER_CEILING_BYTES`, or never read by the app), the digest covers the
redacted *buffered prefix* only and `diagnostics.capture.<side>_hash_scope` is
`"redacted_prefix"`; otherwise it is `"redacted_full"`. `request_bytes` /
`response_bytes` remain the full raw wire sizes.

**What the tee sees is what the app read.** The request body is captured only as
far as the inner app consumed it. `_McpEndpoint` refuses `invalid_token` and
`insufficient_scope` before reading the body, so those rows have
`request_bytes = 0` and `request_parse = "not_captured"`.

**The authenticated context** is read from `scope["state"]["remote_mcp_access"]`
after the inner app returns, which is where `_McpEndpoint` in
`adapters/mcp/remote.py` puts the `RemoteAccessContext` it resolved. It is set
only for requests that reach the MCP session manager, so an `invalid_token` or
`insufficient_scope` refusal carries no client or principal.
"""

from __future__ import annotations

import contextlib
import hashlib
import json
import queue
import re
import sys
import threading
import time
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any, Final, TextIO

__all__ = [
    "BODY_CAP_BYTES",
    "BUFFER_CEILING_BYTES",
    "INTERACTION_COLUMNS",
    "QUEUE_MAXSIZE",
    "REDACTED",
    "REDACTED_KEYS",
    "STORED_HEADERS",
    "CapturedExchange",
    "InteractionRecorder",
    "InteractionSink",
    "McpInteractionCapture",
    "build_interaction_row",
    "redact_json",
    "redact_text",
]

Scope = MutableMapping[str, Any]
Message = MutableMapping[str, Any]
Receive = Callable[[], Awaitable[Message]]
Send = Callable[[Message], Awaitable[None]]
AsgiApp = Callable[[Scope, Receive, Send], Awaitable[None]]

#: One row, keyed by column name. Exactly `INTERACTION_COLUMNS`.
InteractionSink = Callable[[Mapping[str, object]], None]

#: Ceiling on each stored body, applied to the *redacted* serialization. The
#: persistence module exports the same figure; a unit test holds them equal.
BODY_CAP_BYTES: Final = 262_144
#: Most bytes of one body the tee keeps a reference to. Beyond it the byte count
#: still covers the whole body; the stored prefix and its digest stop here.
BUFFER_CEILING_BYTES: Final = 16 * 1024 * 1024
#: Exchanges waiting for the writer thread. A full queue drops and counts.
QUEUE_MAXSIZE: Final = 1024
#: What a redacted value becomes.
REDACTED: Final = "[REDACTED]"

#: Every column the capture side supplies — the table's columns less the
#: DB-assigned `recorded_at`. A unit test holds this equal to the store's own set.
INTERACTION_COLUMNS: Final = (
    "interaction_id",
    "started_at",
    "latency_ms",
    "http_method",
    "http_status",
    "oauth_client_id",
    "principal_id",
    "principal_kind",
    "mcp_session_id",
    "jsonrpc_method",
    "jsonrpc_id",
    "tool_name",
    "capability",
    "correlation_id",
    "outcome",
    "error_code",
    "request_bytes",
    "response_bytes",
    "request_sha256",
    "response_sha256",
    "request_truncated",
    "response_truncated",
    "request_body",
    "response_body",
    "request_body_text",
    "response_body_text",
    "request_headers",
    "diagnostics",
)

#: The only request headers ever stored. Everything else — credentials and
#: cookies above all — is never read into a row.
STORED_HEADERS: Final = frozenset(
    {
        "content-type",
        "accept",
        "user-agent",
        "mcp-protocol-version",
        "origin",
        "content-length",
    }
)

#: Object keys whose values are always redacted, compared after lower-casing and
#: reading `-` as `_`.
REDACTED_KEYS: Final = frozenset(
    {
        "authorization",
        "proxy_authorization",
        "cookie",
        "set_cookie",
        "access_token",
        "refresh_token",
        "id_token",
        "token",
        "bearer",
        "client_secret",
        "secret",
        "password",
        "passphrase",
        "api_key",
        "apikey",
        "private_key",
        "signing_key",
        "code_verifier",
        "assertion",
        "client_assertion",
        "session_token",
        "credential",
        "credentials",
    }
)

#: Endpoint-level refusal tokens `_McpEndpoint` answers with.
_ENDPOINT_ERRORS: Final = frozenset(
    {"invalid_token", "insufficient_scope", "temporarily_unavailable"}
)
#: Longest metadata string (method, id, tool, capability) copied into a column.
_MAX_METADATA_CHARS: Final = 256
#: How deep a JSON document embedded in a string is followed.
_MAX_EMBEDDED_DEPTH: Final = 4
_NUL: Final = "\x00"
_NUL_REPLACEMENT: Final = "\ufffd"

_BEARER: Final = re.compile(r"(bearer)\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
_JWT: Final = re.compile(r"eyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]*")
_KEY_ALTERNATION: Final = "|".join(
    sorted((key.replace("_", "[-_]") for key in REDACTED_KEYS), key=len, reverse=True)
)
#: `"key": "value"` in plain JSON text. The value is a proper JSON string.
_TEXT_PAIR: Final = re.compile(
    r'(?P<head>"(?:' + _KEY_ALTERNATION + r')"\s*:\s*")(?:[^"\\]|\\.)*"',
    re.IGNORECASE | re.DOTALL,
)
#: The same pair one escaping level down, as it appears inside a JSON string
#: (`\"key\":\"value\"`), which is how TextContent carries the envelope.
_ESCAPED_TEXT_PAIR: Final = re.compile(
    r'(?P<head>\\+"(?:' + _KEY_ALTERNATION + r')\\+"\s*:\s*\\+")(?:(?!\\+").)*\\+"',
    re.IGNORECASE | re.DOTALL,
)
#: `'key': 'value'`, as a Python repr of a request echoes it.
_QUOTED_TEXT_PAIR: Final = re.compile(
    r"(?P<head>'(?:" + _KEY_ALTERNATION + r")'\s*:\s*')(?:[^'\\]|\\.)*'",
    re.IGNORECASE | re.DOTALL,
)


def _normalized_key(key: str) -> str:
    return key.lower().replace("-", "_")


def _redact_string_patterns(value: str) -> tuple[str, int]:
    """Credential-shaped runs in one string.

    `"key": "value"` pairs for `REDACTED_KEYS` (plain, one escaping level down,
    and single-quoted as a Python repr echoes them in a validation message),
    then `Bearer <token>` and JWT-shaped runs.
    """
    value, pairs = _TEXT_PAIR.subn(lambda match: f'{match.group("head")}{REDACTED}"', value)
    value, escaped = _ESCAPED_TEXT_PAIR.subn(_escaped_replacement, value)
    value, quoted = _QUOTED_TEXT_PAIR.subn(lambda match: f"{match.group('head')}{REDACTED}'", value)
    value, bearer = _BEARER.subn(lambda match: f"{match.group(1)} {REDACTED}", value)
    value, jwt = _JWT.subn(REDACTED, value)
    return value, pairs + escaped + quoted + bearer + jwt


def _sanitize(value: str) -> tuple[str, bool]:
    """Replace NUL and anything UTF-8 cannot encode (a lone surrogate)."""
    replaced = _NUL in value
    if replaced:
        value = value.replace(_NUL, _NUL_REPLACEMENT)
    try:
        value.encode("utf-8")
    except UnicodeEncodeError:
        value = value.encode("utf-8", errors="replace").decode("utf-8")
        replaced = True
    return value, replaced


@dataclass
class _Walk:
    redactions: int = 0
    nul_replaced: bool = False


def _redact_value(value: object, walk: _Walk, depth: int) -> object:
    if isinstance(value, dict):
        result: dict[str, object] = {}
        for key, item in value.items():
            clean_key, key_replaced = _sanitize(str(key))
            walk.nul_replaced |= key_replaced
            if _normalized_key(clean_key) in REDACTED_KEYS:
                result[clean_key] = REDACTED
                walk.redactions += 1
            else:
                result[clean_key] = _redact_value(item, walk, depth)
        return result
    if isinstance(value, list):
        return [_redact_value(item, walk, depth) for item in value]
    if isinstance(value, str):
        return _redact_string(value, walk, depth)
    return value


def _redact_string(value: str, walk: _Walk, depth: int) -> str:
    stripped = value.lstrip()
    if depth < _MAX_EMBEDDED_DEPTH and stripped[:1] in {"{", "["}:
        try:
            embedded = json.loads(value)
        except (ValueError, RecursionError):
            embedded = None
        if isinstance(embedded, dict | list):
            inner = _Walk()
            redacted = _redact_value(embedded, inner, depth + 1)
            walk.nul_replaced |= inner.nul_replaced
            if inner.redactions:
                walk.redactions += inner.redactions
                return json.dumps(redacted, ensure_ascii=False, separators=(",", ":"))
    value, count = _redact_string_patterns(value)
    walk.redactions += count
    value, replaced = _sanitize(value)
    walk.nul_replaced |= replaced
    return value


def redact_json(value: object) -> tuple[object, int, bool]:
    """Redact a parsed JSON value. Returns `(value, redactions, nul_replaced)`."""
    walk = _Walk()
    redacted = _redact_value(value, walk, 0)
    return redacted, walk.redactions, walk.nul_replaced


def redact_text(value: str) -> tuple[str, int, bool]:
    """Redact text that is not (or no longer) parseable JSON.

    Returns `(text, redactions, nul_replaced)`.
    """
    value, patterns = _redact_string_patterns(value)
    value, replaced = _sanitize(value)
    return value, patterns, replaced


def _escaped_replacement(match: re.Match[str]) -> str:
    head = match.group("head")
    quote = head[head.rfind(":") :].lstrip(": \t\r\n")
    return f"{head}{REDACTED}{quote}"


def _utf8_prefix(value: str, limit: int) -> str:
    """The longest prefix of `value` whose UTF-8 encoding fits `limit` bytes."""
    return value.encode("utf-8")[:limit].decode("utf-8", errors="ignore")


@dataclass
class _Body:
    """One body as the writer thread stores it."""

    parsed: object = None
    is_json: bool = False
    stored_json: object = None
    stored_text: str | None = None
    truncated: bool = False
    parse: str = "empty"
    redactions: int = 0
    nul_replaced: bool = False
    sha256: str = hashlib.sha256(b"").hexdigest()
    hash_scope: str = "redacted_full"


def _process_body(raw: bytes, *, overflowed: bool) -> _Body:
    """`overflowed` means `raw` is not the whole body: past the buffer, or never read."""
    body = _Body()
    if overflowed:
        body.hash_scope = "redacted_prefix"
    if not raw:
        if overflowed:
            body.parse = "not_captured"
        return body
    if not overflowed:
        try:
            body.parsed = json.loads(raw)
            body.is_json = True
        except (ValueError, RecursionError):
            body.is_json = False
    if body.is_json:
        try:
            redacted, body.redactions, body.nul_replaced = redact_json(body.parsed)
            serialized = json.dumps(redacted, ensure_ascii=False, separators=(",", ":"))
        except RecursionError:
            body.is_json = False
        else:
            body.parse = "json"
            encoded_json = serialized.encode("utf-8")
            body.sha256 = hashlib.sha256(encoded_json).hexdigest()
            if len(encoded_json) <= BODY_CAP_BYTES:
                body.stored_json = redacted
            else:
                body.truncated = True
                body.stored_text = _utf8_prefix(serialized, BODY_CAP_BYTES)
            return body
    body.parse = "not_captured" if overflowed else "invalid_json"
    text, body.redactions, body.nul_replaced = redact_text(raw.decode("utf-8", errors="replace"))
    encoded = text.encode("utf-8")
    body.sha256 = hashlib.sha256(encoded).hexdigest()
    body.truncated = overflowed or len(encoded) > BODY_CAP_BYTES
    body.stored_text = _utf8_prefix(text, BODY_CAP_BYTES)
    return body


@dataclass
class _Capture:
    """Incremental state for one direction of one exchange."""

    size: int = 0
    chunks: list[bytes] = field(default_factory=list)
    buffered: int = 0
    overflowed: bool = False
    complete: bool = False

    def add(self, chunk: bytes) -> None:
        if not chunk:
            return
        self.size += len(chunk)
        room = BUFFER_CEILING_BYTES - self.buffered
        if room <= 0:
            self.overflowed = True
            return
        if len(chunk) > room:
            chunk = chunk[:room]
            self.overflowed = True
        self.chunks.append(chunk)
        self.buffered += len(chunk)


@dataclass
class CapturedExchange:
    """Everything the event loop hands the writer thread for one exchange."""

    http_method: str
    started_at: datetime
    latency_ms: float
    request_headers: tuple[tuple[bytes, bytes], ...] = ()
    request_body: bytes = b""
    request_bytes: int = 0
    request_overflowed: bool = False
    http_status: int | None = None
    response_headers: tuple[tuple[bytes, bytes], ...] = ()
    response_body: bytes = b""
    response_bytes: int = 0
    response_overflowed: bool = False
    access: object = None


def _header_map(headers: Iterable[tuple[bytes, bytes]]) -> dict[str, str]:
    found: dict[str, list[str]] = {}
    for name, value in headers:
        found.setdefault(bytes(name).decode("latin-1").lower(), []).append(
            bytes(value).decode("latin-1")
        )
    return {name: ", ".join(values) for name, values in found.items()}


def _metadata(value: object, walk: _Walk) -> str | None:
    """A JSON-RPC metadata value as column text, bounded and redacted."""
    if value is None:
        return None
    text = value if isinstance(value, str) else json.dumps(value, separators=(",", ":"))
    text, count = _redact_string_patterns(text[:_MAX_METADATA_CHARS])
    walk.redactions += count
    text, replaced = _sanitize(text)
    walk.nul_replaced |= replaced
    return text


def _request_metadata(
    parsed: object, walk: _Walk, facade_invoke_tools: frozenset[str]
) -> dict[str, str | None]:
    found: dict[str, str | None] = {
        "jsonrpc_method": None,
        "jsonrpc_id": None,
        "tool_name": None,
        "capability": None,
    }
    if isinstance(parsed, list):
        found["jsonrpc_method"] = "batch"
        return found
    if not isinstance(parsed, dict):
        return found
    method = parsed.get("method")
    found["jsonrpc_method"] = _metadata(method, walk)
    request_id = parsed.get("id")
    if not isinstance(request_id, bool):
        found["jsonrpc_id"] = _metadata(request_id, walk)
    params = parsed.get("params")
    if method == "tools/call" and isinstance(params, dict):
        name = params.get("name")
        if isinstance(name, str):
            found["tool_name"] = _metadata(name, walk)
            capability: object = name
            arguments = params.get("arguments")
            if name in facade_invoke_tools and isinstance(arguments, dict):
                target = arguments.get("capability")
                if isinstance(target, str):
                    capability = target
            found["capability"] = _metadata(capability, walk)
    return found


def _problem(document: Mapping[str, Any], walk: _Walk) -> dict[str, object] | None:
    code = document.get("code")
    if not isinstance(code, str):
        return None
    redacted, count, replaced = redact_json(
        {
            "code": code,
            "correlation_id": document.get("correlation_id"),
            "safe_details": document.get("safe_details", []),
            "allowed_values": document.get("allowed_values", []),
        }
    )
    walk.redactions += count
    walk.nul_replaced |= replaced
    return redacted if isinstance(redacted, dict) else None


@dataclass
class _ResponseFacts:
    is_error: bool | None = None
    problem: dict[str, object] | None = None
    correlation_id: str | None = None
    jsonrpc_error: dict[str, object] | None = None
    endpoint_error: str | None = None


def _tool_result_facts(result: Mapping[str, Any], facts: _ResponseFacts, walk: _Walk) -> None:
    is_error = result.get("isError")
    if isinstance(is_error, bool):
        facts.is_error = is_error
    content = result.get("content")
    if not isinstance(content, list):
        return
    for block in content:
        if not (isinstance(block, dict) and block.get("type") == "text"):
            continue
        text = block.get("text")
        if not isinstance(text, str):
            continue
        try:
            document = json.loads(text)
        except (ValueError, RecursionError):
            continue
        if not isinstance(document, dict):
            continue
        envelope_error = document.get("error")
        problem = (
            _problem(envelope_error, walk)
            if isinstance(envelope_error, dict)
            else _problem(document, walk)
            if "correlation_id" in document
            else None
        )
        correlation = (
            problem.get("correlation_id") if problem is not None else None
        ) or document.get("correlation_id")
        if facts.problem is None and problem is not None:
            facts.problem = problem
        if facts.correlation_id is None and isinstance(correlation, str):
            facts.correlation_id = _metadata(correlation, walk)
        return


def _response_facts(parsed: object, status: int | None, walk: _Walk) -> _ResponseFacts:
    facts = _ResponseFacts()
    if (
        isinstance(parsed, dict)
        and "jsonrpc" not in parsed
        and parsed.get("error") in _ENDPOINT_ERRORS
        and status in {401, 403, 503}
    ):
        facts.endpoint_error = str(parsed["error"])
        return facts
    messages = parsed if isinstance(parsed, list) else [parsed]
    for message in messages:
        if not isinstance(message, dict):
            continue
        error = message.get("error")
        if facts.jsonrpc_error is None and isinstance(error, dict):
            message_text = error.get("message")
            redacted, count, replaced = redact_json(
                {
                    "code": error.get("code"),
                    "message": message_text if isinstance(message_text, str) else None,
                }
            )
            walk.redactions += count
            walk.nul_replaced |= replaced
            facts.jsonrpc_error = redacted if isinstance(redacted, dict) else None
        result = message.get("result")
        if isinstance(result, dict):
            _tool_result_facts(result, facts, walk)
    return facts


def _outcome(facts: _ResponseFacts, status: int | None, response: _Body) -> tuple[str, str | None]:
    if facts.endpoint_error in {"invalid_token", "insufficient_scope"}:
        return "auth_refused", facts.endpoint_error
    if facts.endpoint_error == "temporarily_unavailable" or status == 503:
        return "unavailable", facts.endpoint_error
    if status is None:
        return "http_error", None
    if facts.jsonrpc_error is not None:
        code = facts.jsonrpc_error.get("code")
        return "jsonrpc_error", None if code is None else str(code)
    if status >= 400:
        return "http_error", None
    if facts.is_error:
        code = None if facts.problem is None else facts.problem.get("code")
        return "tool_error", None if code is None else str(code)
    if response.parse in {"json", "empty"}:
        return "ok", None
    return "unparsed", None


def build_interaction_row(
    exchange: CapturedExchange,
    *,
    facade_invoke_tools: frozenset[str],
    dropped_before: int = 0,
    write_failures_before: int = 0,
) -> dict[str, object]:
    """Parse, redact and cap one exchange into a row keyed by `INTERACTION_COLUMNS`.

    `facade_invoke_tools` names the compact façade tools whose
    `arguments.capability` is the canonical target; the composition root
    supplies them, so this module never imports the MCP transport.
    """
    walk = _Walk()
    request = _process_body(exchange.request_body, overflowed=exchange.request_overflowed)
    response = _process_body(exchange.response_body, overflowed=exchange.response_overflowed)
    request_meta = _request_metadata(
        request.parsed if request.is_json else None, walk, facade_invoke_tools
    )
    facts = _response_facts(
        response.parsed if response.is_json else None, exchange.http_status, walk
    )
    outcome, error_code = _outcome(facts, exchange.http_status, response)

    request_headers = _header_map(exchange.request_headers)
    response_headers = _header_map(exchange.response_headers)
    stored_headers: dict[str, str] = {}
    for name, value in request_headers.items():
        if name in STORED_HEADERS:
            stored_headers[name] = _metadata(value, walk) or ""
    session = request_headers.get("mcp-session-id") or response_headers.get("mcp-session-id")

    access = exchange.access
    principal = getattr(access, "principal", None)
    kind = getattr(principal, "kind", None)
    client_id = getattr(access, "authenticated_client_id", None)
    principal_id = getattr(principal, "principal_id", None)

    diagnostics = {
        "is_error": facts.is_error,
        "problem": facts.problem,
        "jsonrpc_error": facts.jsonrpc_error,
        "endpoint_error": facts.endpoint_error,
        "capture": {
            "request_parse": request.parse,
            "response_parse": response.parse,
            "request_hash_scope": request.hash_scope,
            "response_hash_scope": response.hash_scope,
            "redactions": walk.redactions + request.redactions + response.redactions,
            "nul_replaced": walk.nul_replaced or request.nul_replaced or response.nul_replaced,
            "dropped_before": dropped_before,
            "write_failures_before": write_failures_before,
        },
    }
    return {
        "interaction_id": f"mcpi_{uuid.uuid4().hex}",
        "started_at": exchange.started_at,
        "latency_ms": max(0.0, exchange.latency_ms),
        "http_method": exchange.http_method,
        "http_status": exchange.http_status,
        "oauth_client_id": _metadata(client_id, walk) if isinstance(client_id, str) else None,
        "principal_id": _metadata(principal_id, walk) if isinstance(principal_id, str) else None,
        "principal_kind": None if kind is None else str(getattr(kind, "value", kind)),
        "mcp_session_id": _metadata(session, walk),
        "jsonrpc_method": request_meta["jsonrpc_method"],
        "jsonrpc_id": request_meta["jsonrpc_id"],
        "tool_name": request_meta["tool_name"],
        "capability": request_meta["capability"],
        "correlation_id": facts.correlation_id,
        "outcome": outcome,
        "error_code": error_code,
        "request_bytes": exchange.request_bytes,
        "response_bytes": exchange.response_bytes,
        "request_sha256": request.sha256,
        "response_sha256": response.sha256,
        "request_truncated": request.truncated,
        "response_truncated": response.truncated,
        "request_body": request.stored_json,
        "response_body": response.stored_json,
        "request_body_text": request.stored_text,
        "response_body_text": response.stored_text,
        "request_headers": stored_headers,
        "diagnostics": diagnostics,
    }


_STOP: Final = object()


class InteractionRecorder:
    """One bounded queue and one daemon writer thread in front of a sink.

    `submit` never blocks and never raises. `start` launches the writer; `stop`
    drains what it can within `timeout` seconds and returns. The counters are
    process totals: `dropped` (queue full, or offered after stop),
    `write_failures` (the sink raised) and `capture_errors` (the tee or the row
    builder raised).
    """

    def __init__(
        self,
        sink: InteractionSink,
        *,
        facade_invoke_tools: frozenset[str],
        maxsize: int = QUEUE_MAXSIZE,
        stderr: TextIO | None = None,
    ) -> None:
        self._sink = sink
        self.facade_invoke_tools = facade_invoke_tools
        self._queue: queue.Queue[object] = queue.Queue(maxsize=maxsize)
        self._stderr = stderr
        self._lock = threading.Lock()
        self._dropped = 0
        self._write_failures = 0
        self._capture_errors = 0
        self._dropped_reported = 0
        self._failures_reported = 0
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._deadline = 0.0

    @property
    def dropped(self) -> int:
        return self._dropped

    @property
    def write_failures(self) -> int:
        return self._write_failures

    @property
    def capture_errors(self) -> int:
        return self._capture_errors

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._drain_loop, name="mcp-interaction-writer", daemon=True
        )
        self._thread.start()

    def stop(self, timeout: float = 2.0) -> None:
        """Drain within `timeout` seconds, then return whether or not drained."""
        if self._stopping.is_set():
            return
        self._deadline = time.monotonic() + timeout
        self._stopping.set()
        with contextlib.suppress(queue.Full):
            self._queue.put_nowait(_STOP)
        thread = self._thread
        if thread is not None:
            thread.join(timeout)
        abandoned = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, CapturedExchange):
                abandoned += 1
        if abandoned:
            with self._lock:
                self._dropped += abandoned
            self._report(f"abandoned={abandoned}")

    def submit(self, exchange: CapturedExchange) -> None:
        """Offer one exchange to the writer. Never blocks, never raises."""
        try:
            if self._stopping.is_set():
                raise queue.Full
            self._queue.put_nowait(exchange)
        except queue.Full:
            with self._lock:
                self._dropped += 1
        except Exception:
            self.note_capture_error()

    def note_capture_error(self) -> None:
        with self._lock:
            self._capture_errors += 1

    def _report(self, what: str) -> None:
        stream = self._stderr if self._stderr is not None else sys.stderr
        # A failed report must not stop the writer.
        with contextlib.suppress(Exception):
            print(
                f"mcp-interaction-log {what} dropped={self._dropped} "
                f"write_failures={self._write_failures} capture_errors={self._capture_errors}",
                file=stream,
                flush=True,
            )

    def _drain_loop(self) -> None:
        while True:
            if self._stopping.is_set() and time.monotonic() > self._deadline:
                return
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._stopping.is_set():
                    return
                continue
            if item is _STOP:
                return
            if isinstance(item, CapturedExchange):
                self._write(item)

    def _write(self, exchange: CapturedExchange) -> None:
        with self._lock:
            dropped = self._dropped
            failures = self._write_failures
        try:
            row = build_interaction_row(
                exchange,
                facade_invoke_tools=self.facade_invoke_tools,
                dropped_before=dropped - self._dropped_reported,
                write_failures_before=failures - self._failures_reported,
            )
        except Exception:
            self.note_capture_error()
            self._report("capture_error")
            return
        try:
            self._sink(row)
        except Exception:
            with self._lock:
                self._write_failures += 1
            self._report("write_failed")
            return
        self._dropped_reported = dropped
        self._failures_reported = failures


class _Exchange:
    """The event-loop half: what the tee has seen of one `/mcp` exchange."""

    def __init__(self, scope: Scope) -> None:
        self.method = str(scope.get("method", ""))
        self.started_at = datetime.now(UTC)
        self.started = time.monotonic()
        self.finished: float | None = None
        self.request_headers = tuple(scope.get("headers", ()))
        self.request = _Capture()
        self.response = _Capture()
        self.status: int | None = None
        self.response_headers: tuple[tuple[bytes, bytes], ...] = ()
        self.broken = False

    def on_request(self, message: Message) -> None:
        if message.get("type") == "http.request":
            self.request.add(bytes(message.get("body", b"")))
            if not message.get("more_body", False):
                self.request.complete = True

    def on_response(self, message: Message, sent_at: float) -> None:
        kind = message.get("type")
        if kind == "http.response.start":
            self.status = int(message["status"])
            self.response_headers = tuple(message.get("headers", ()))
        elif kind == "http.response.body":
            self.response.add(bytes(message.get("body", b"")))
            if not message.get("more_body", False):
                self.response.complete = True
                self.finished = sent_at

    def captured(self, scope: Scope) -> CapturedExchange:
        finished = self.finished if self.finished is not None else time.monotonic()
        state = scope.get("state")
        access = state.get("remote_mcp_access") if isinstance(state, Mapping) else None
        return CapturedExchange(
            http_method=self.method,
            started_at=self.started_at,
            latency_ms=(finished - self.started) * 1000.0,
            request_headers=self.request_headers,
            request_body=b"".join(self.request.chunks),
            request_bytes=self.request.size,
            request_overflowed=self.request.overflowed or not self.request.complete,
            http_status=self.status,
            response_headers=self.response_headers,
            response_body=b"".join(self.response.chunks),
            response_bytes=self.response.size,
            response_overflowed=self.response.overflowed or not self.response.complete,
            access=access,
        )


class McpInteractionCapture:
    """ASGI middleware teeing one path's exchanges to an `InteractionRecorder`.

    `path` is the remote MCP route, supplied by the composition root. Every
    other path, and every non-HTTP scope, passes straight through. On a
    lifespan shutdown the recorder is stopped (bounded by `stop_timeout`) before
    the inner app hears of it, because uvicorn re-raises a captured signal after
    lifespan shutdown and the composition root's `finally` never runs on that
    path; this is the only place the flush is reached on a normal stop.
    """

    def __init__(
        self,
        app: AsgiApp,
        recorder: InteractionRecorder,
        *,
        path: str,
        stop_timeout: float = 2.0,
    ) -> None:
        self.app = app
        self.recorder = recorder
        self.path = path
        self.stop_timeout = stop_timeout

    def _begin(self, scope: Scope) -> _Exchange | None:
        try:
            if scope.get("type") != "http" or scope.get("path") != self.path:
                return None
            return _Exchange(scope)
        except Exception:
            self.recorder.note_capture_error()
            return None

    def _tee_step(self, exchange: _Exchange, step: Callable[[], None]) -> None:
        if exchange.broken:
            return
        try:
            step()
        except Exception:
            exchange.broken = True
            self.recorder.note_capture_error()

    def _finish(self, exchange: _Exchange, scope: Scope) -> None:
        if exchange.broken:
            return
        try:
            self.recorder.submit(exchange.captured(scope))
        except Exception:
            self.recorder.note_capture_error()

    def _on_lifespan(self, message: Message) -> None:
        try:
            if message.get("type") == "lifespan.shutdown":
                self.recorder.stop(self.stop_timeout)
        except Exception:
            self.recorder.note_capture_error()

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        exchange = self._begin(scope)
        if exchange is None:
            if scope.get("type") != "lifespan":
                await self.app(scope, receive, send)
                return

            async def lifespan_receive() -> Message:
                message = await receive()
                self._on_lifespan(message)
                return message

            await self.app(scope, lifespan_receive, send)
            return
        captured = exchange

        async def tee_receive() -> Message:
            message = await receive()
            self._tee_step(captured, lambda: captured.on_request(message))
            return message

        async def tee_send(message: Message) -> None:
            await send(message)
            sent_at = time.monotonic()
            self._tee_step(captured, lambda: captured.on_response(message, sent_at))

        try:
            await self.app(scope, tee_receive, tee_send)
        finally:
            self._finish(captured, scope)
