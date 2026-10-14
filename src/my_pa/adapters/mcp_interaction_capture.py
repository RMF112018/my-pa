"""Capture remote `/mcp` JSON-RPC exchanges off the request path.

The remote gateway can record every HTTP exchange on its `/mcp` route — request
and response bodies included — into `observability.mcp_interactions`. That is a
deliberate, operator-accepted exception to `AGENTS.md` section 5 ("logs exclude
message bodies by default"), which is why it is off unless
`MY_PA_MCP_INTERACTION_LOG_ENABLED` turns it on, and why everything it stores is
redacted first.

**Three parts: tee, writer thread, row worker.** `McpInteractionCapture` is
ASGI middleware around the Starlette app `create_remote_mcp_app` returns. On
the event loop it only *tees*: every `http.request` and `http.response.*`
message passes through unchanged, and the tee keeps a reference to each body
chunk (up to `BUFFER_CEILING_BYTES` per body), a byte count of the full wire
body, the status and the response headers. It hashes nothing. After the inner
app returns — so after the final response byte has been handed to the server —
the captured exchange is offered to `InteractionRecorder` with `put_nowait`.
One daemon writer thread takes it, has the row built, and hands the row to the
injected sink. In the gateway the row is built by `ProcessRowBuilder` in one
child process that imports only this module: parsing, redaction, hashing and
capping hold *that* process's GIL, never the gateway's. The writer thread only
sends the bodies over a socket and waits (both release the GIL), and the whole
round trip, sends included, is bounded by a watchdog that kills the worker.
Measured with a 1 ms ticker thread: building a 16 MiB text body in-thread
stalled the gateway's threads for about 1.3 s; through the worker the longest
stall was under 2 ms idle and 35 ms under heavy CPU contention. A row that
takes longer than its bound (30 s in the gateway), a worker that stops reading
or crashes, kills that worker, drops that row and counts a capture error; the
next row starts a fresh worker, and repeated failed starts open a backing-off
circuit breaker. Nothing here knows what the sink is; the composition root
(`apps/gateway.py`) gives it one that appends through
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
queue is bounded twice: by count (`QUEUE_MAXSIZE`, 1024) and by the body bytes
the queued exchanges hold together (`QUEUED_BYTES_BUDGET`, 64 MiB); an exchange
that would exceed either is dropped and counted, never waited for. Each body
buffers at most `BUFFER_CEILING_BYTES` (16 MiB). The tee keeps references to
the chunks the server sends; after the inner app returns, `_Exchange.captured`
joins each body's chunks on the event loop — a single-chunk body (the usual
Starlette response) is returned as the same object, a multi-chunk body is
copied once, at most 16 MiB per direction. A failed write is
counted, reported as a count-only line on standard error (never a body, a
header or an identifier), and dropped — there is no retry loop.
The counters accumulated since the last successful write ride on the next row
that does get written, as `diagnostics.capture.dropped_before` and
`write_failures_before`.

**Redaction, before truncation.** Headers are allowlisted (`STORED_HEADERS`);
`authorization`, `cookie`, `set-cookie`, `proxy-authorization` and every other
header are never stored. JSON bodies are walked: keys are normalised
(lower-cased; `-`, `_`, `.`, spaces and invisible format characters removed, so
`accessToken`, `api.key` and `access_token` match), and a value of any type
under a key in `REDACTED_KEYS`, or one ending in a `REDACTED_KEY_SUFFIXES`
entry (`auth_token`, `x_api_key`, ...), becomes `"[REDACTED]"`. Every string
(and a body that is not JSON, or that overflowed the capture buffer, as a
whole) goes through `_redact_string_patterns`: PEM private-key blocks; `"key":
value` pairs for the same keys, where value is a string or a non-string scalar,
plain, one escaping level down and Python-repr quoted (dotted keys such as
`oauth.token` included, and escaped pairs at the four escaping levels the JSON
path follows); a credential value cut off by the end of the text; `key=value`
form and query-string pairs; the password in URL userinfo; credential header
lines (`Cookie:`, `Set-Cookie:`, `Authorization:` of any scheme, `X-Api-Key:`,
`*-Token:`, `*-Secret:`); `key: value` and `key = value` lines (YAML, TOML,
INI, logs); bare `key: value` pairs (relaxed JSON); `Bearer` and `Basic`
credentials; and JWTs inside dotted base64url runs. Object keys that are not
credential keys go through the same patterns (a colliding result gets a ` #n`
suffix), and every metadata column and stored header is redacted whole before
it is cut to 256 characters. A string that is itself a JSON object or array
(MCP `TextContent.text` carries the response envelope that way) is parsed,
redacted the same way and re-serialised. Only then is the result cut to
`BODY_CAP_BYTES`, so a credential beyond the cap never appears and one
straddling it is never stored in part. NUL characters, which PostgreSQL text
and JSONB cannot hold, are replaced and flagged, and so are `NaN`, `Infinity`
and overflowing numbers, which JSONB refuses: they are kept as the strings they
were written as (`non_finite_replaced`). Every pattern is linear by
construction (the rules are in the comment above `_BEARER`, and a unit test
probes every compiled pattern for quadratic growth); a text-path credential
whose value is an array or object is a stated limit, not matched.

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
import dataclasses
import hashlib
import json
import math
import os
import queue
import re
import socket
import subprocess
import sys
import threading
import time
import unicodedata
import uuid
from collections.abc import Awaitable, Callable, Iterable, Mapping, MutableMapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from multiprocessing.connection import Connection
from pathlib import Path
from typing import Any, Final, Protocol, TextIO

__all__ = [
    "BODY_CAP_BYTES",
    "BUFFER_CEILING_BYTES",
    "DROP_REPORT_SECONDS",
    "INTERACTION_COLUMNS",
    "QUEUED_BYTES_BUDGET",
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
#: Most body bytes all queued exchanges may hold together. The count bound alone
#: would admit 1024 x 2 x `BUFFER_CEILING_BYTES` (32 GiB); with this budget the
#: queue holds at most 64 MiB of bodies, i.e. at least two exchanges at the
#: per-body ceiling. A submit that would exceed it is dropped and counted.
QUEUED_BYTES_BUDGET: Final = 64 * 1024 * 1024
#: A drop, and likewise a write failure, is reported on standard error
#: (count-only) at the first occurrence, then at most once per this many seconds
#: each, so a sustained overload or database outage is visible without waiting
#: for the next written row and without a line per request.
DROP_REPORT_SECONDS: Final = 60.0
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

#: Object keys whose values are always redacted. Keys are compared after
#: `_normalized_key`: lower-cased, with `-`, `_` and spaces removed, so
#: `access_token`, `Access-Token` and `accessToken` are one key. A key matches
#: when its normalised form is in this set *or* ends with one of
#: `REDACTED_KEY_SUFFIXES`.
REDACTED_KEYS: Final = frozenset(
    {
        "authorization",
        "proxyauthorization",
        "cookie",
        "setcookie",
        "accesstoken",
        "refreshtoken",
        "idtoken",
        "token",
        "bearer",
        "clientsecret",
        "secret",
        "password",
        "passphrase",
        "apikey",
        "privatekey",
        "signingkey",
        "codeverifier",
        "assertion",
        "clientassertion",
        "sessiontoken",
        "credential",
        "credentials",
        "secretkey",
        "accesskey",
        "authorizationcode",
        "secrets",
        "pwd",
        "passwd",
        "passcode",
        "privatekeypem",
        "authheader",
        "authorizationheader",
    }
)
#: Normalised suffixes that make any key credential-bearing: `auth_token`,
#: `oauth_token`, `github_token`, `x_api_key`, `lease_token`, `db_password`...
#: Checked against the field names this repository publishes: `tokens`,
#: `max_tokens` and `token_count` do not end in a suffix (plural / `count`), so
#: no non-secret exception set is needed. `lease_token` and `idempotency_token`
#: are matched and redacted deliberately; the first is a bearer-style lease.
#: MCP's own `progressToken` is matched too: an opaque client correlation value,
#: lost to over-redaction rather than kept by an exception. `accesskey` and
#: `secretkey` cover `aws_access_key` and `aws_secret_access_key`; `secrets` and
#: `passwd` their plural and short forms. The bare key `code` is deliberately
#: *not* matched: dozens of domain `*_code` fields are vocabulary, not secrets.
#: None of the additions names a field in `contracts`, `application`, `domain`
#: or `adapters`.
REDACTED_KEY_SUFFIXES: Final = (
    "token",
    "secret",
    "secrets",
    "password",
    "passwd",
    "passphrase",
    "apikey",
    "accesskey",
    "secretkey",
    "privatekey",
    "signingkey",
    "credential",
    "credentials",
    "cookie",
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

# Every pattern below is linear by construction, because the writer thread runs
# them over bodies an untrusted client chooses. The rules: a pattern that scans
# a run starts only at the run's first character (a lookbehind anchor); every
# quantified prefix or escape run is bounded; a repeated group's alternatives
# partition the input (each character can be consumed one way only); and every
# scan that could reach a near-miss terminator stops at the first terminator of
# its kind and then *succeeds* (or stops at the next start of its own kind), so
# no start ever rescans text a later start will scan again.
# `tests/unit/test_mcp_interaction_capture.py` checks this for every compiled
# pattern in the module (`tests/unit/redaction_probe.py`): measured in thread
# CPU time, one 512 K-character run of a worst-case shape must cost less than
# 4x sixteen 32 K runs of it (linear ~1x, quadratic ~16x), and each probe runs
# in a subprocess that is killed after 60 s.

_BEARER: Final = re.compile(r"(bearer)\s+[A-Za-z0-9\-._~+/]+=*", re.IGNORECASE)
#: `Basic <base64>`. Only the scheme word is case-insensitive: the run must look
#: like base64 (eight or more characters including a digit, an upper-case
#: letter, `+`, `/` or `=`), so prose such as "basic information" is left alone.
_BASIC: Final = re.compile(r"((?i:basic))\s+(?=[A-Za-z0-9+/]*[0-9A-Z+/=])[A-Za-z0-9+/]{8,}={0,2}")
#: A credential-bearing header line inside text: `Cookie:`, `Set-Cookie:`,
#: `Authorization:` / `Proxy-Authorization:` with any scheme, `X-Api-Key:` /
#: `Api-Key:`, and any `*-Token:` or `*-Secret:` header. The name starts a word;
#: the value runs to the end of the line, a quote or a backslash.
_HEADER_LINE: Final = re.compile(
    r"(?<![A-Za-z0-9\-])((?:set-)?cookie|(?:proxy-)?authorization|(?:x-)?api-key"
    r"|[A-Za-z0-9\-]{0,64}?-(?:token|secret))[ \t]*:[ \t]*(?![ \t]*\[REDACTED\])[^\r\n\"\\]+",
    re.IGNORECASE,
)
#: The password in URL userinfo, `scheme://user:password@host`. Every part is
#: bounded and the scheme starts a word.
_URL_USERINFO: Final = re.compile(
    r"(?<![A-Za-z0-9+.\-])([A-Za-z][A-Za-z0-9+.\-]{0,31}://[^\s/:@\"'\\]{0,256}:)"
    r"(?!\[REDACTED\])[^\s/@\"'\\]{1,256}@"
)
#: A whole dotted base64url run, started only at its first character. The
#: callback redacts from the first `eyJ` onward when two dots follow it, so a
#: JWT glued to preceding text is still caught without restarting at every `eyJ`.
_DOTTED_RUN: Final = re.compile(r"(?<![A-Za-z0-9_.\-])[A-Za-z0-9_\-]+(?:\.[A-Za-z0-9_\-]*)+")
#: A PEM or PGP private-key block. The body stops at the first `-----` of any
#: kind; the match then takes a matching `END` line if that is what follows,
#: and otherwise ends there (or at the end of the text). It never fails once
#: the `BEGIN` line matched, so no later `BEGIN` rescans the same body. A
#: near-miss `END` is not consumed, but everything up to it is redacted. The
#: armour is split across literals so no key signature appears in source.
_PEM_PRIVATE_KEY: Final = re.compile(
    "-----BEGIN "
    + r"[A-Z ]{0,40}PRIVATE KEY(?: BLOCK)?-----"
    + r"(?:[^-]|-(?!----))*"
    + "(?:-----END "
    + r"[A-Z ]{0,40}PRIVATE KEY(?: BLOCK)?-----|(?=-----)|\Z)"
)
_SEP: Final = r"[-_. ]?"


def _key_pattern(prefix_class: str, separator: str) -> str:
    """A credential key as text: an exact key, or a bounded prefix and a suffix."""
    return (
        r"(?:(?:proxy" + separator + r")?authorization(?:" + separator + r"(?:code|header))?"
        r"|auth" + separator + r"header|passcode|private" + separator + r"key" + separator + r"pem"
        r"|bearer"
        r"|(?:client" + separator + r")?assertion|code" + separator + r"verifier|pwd"
        r"|" + prefix_class + r"{0,64}?(?:token|secrets?|password|passwd|passphrase"
        r"|api" + separator + r"key|private" + separator + r"key|signing" + separator + r"key"
        r"|access" + separator + r"key|secret" + separator + r"key|credentials?|cookie))"
    )


#: Inside quotes a key may contain `-`, `_`, `.` or spaces (`oauth.token`).
_KEY_PATTERN: Final = _key_pattern(r"[A-Za-z0-9_.\- ]", _SEP)
#: In a query string or form body a key is one word (no spaces), so a run of
#: spaces cannot make every position a candidate start.
_FORM_KEY_PATTERN: Final = _key_pattern(r"[A-Za-z0-9_.\-]", r"[-_.]?")
#: A JSON scalar that is not a string.
_SCALAR: Final = r"(?:-?\d[\d.eE+\-]*|true|false|null)"
#: `"key": value` in plain JSON text, where value is a JSON string or scalar.
_TEXT_PAIR: Final = re.compile(
    r'(?P<head>"' + _KEY_PATTERN + r'"\s*:\s*)(?:"(?:[^"\\]|\\.)*"|' + _SCALAR + r")",
    re.IGNORECASE | re.DOTALL,
)
#: The JSON escaping levels the text path redacts, as backslashes before a
#: quote. A document embedded in a JSON string is escaped once more at each
#: level, which doubles the backslashes and adds one: 1, 3, 7, 15. That is the
#: four embedding levels the JSON path follows (`_MAX_EMBEDDED_DEPTH`), and the
#: bound is what keeps the escape run from being an unbounded backtracking
#: point.
_ESCAPE_LEVELS: Final = (1, 3, 7, 15)


def _escaped_pair(level: int, *, unterminated: bool) -> re.Pattern[str]:
    r"""`\"key\": value` at one escaping level, terminated or cut off by the end.

    The quote run is exactly `level` backslashes and a quote, starting at the
    run's first backslash. The value is a partition of the text into
    non-backslash, non-quote characters; backslash runs not followed by a
    quote; and quote runs *longer* than `level` (a deeper level's quote, which
    belongs to the value). It stops at the first quote run of `level` or fewer
    backslashes, which every later head at this level contains, so a scan never
    crosses a later head.
    """
    quote = r"(?<!\\)\\{" + str(level) + r'}"'
    value = r'(?:[^\\"]|\\+(?!["\\])|\\{' + str(level + 1) + r',}")*'
    head = r"(?P<head>" + quote + _KEY_PATTERN + quote + r"\s*:\s*)"
    if unterminated:
        return re.compile(
            head + quote + value + r"\\*\Z",
            re.IGNORECASE | re.DOTALL,
        )
    return re.compile(
        head + r"(?:" + quote + value + r"\\{0," + str(level) + r'}"|' + _SCALAR + r")",
        re.IGNORECASE | re.DOTALL,
    )


_ESCAPED_TEXT_PAIRS: Final = tuple(
    _escaped_pair(level, unterminated=False) for level in _ESCAPE_LEVELS
)
_ESCAPED_UNTERMINATED_PAIRS: Final = tuple(
    _escaped_pair(level, unterminated=True) for level in _ESCAPE_LEVELS
)
#: `'key': value`, as a Python repr of a request echoes it.
_QUOTED_TEXT_PAIR: Final = re.compile(
    r"(?P<head>'" + _KEY_PATTERN + r"'\s*:\s*)(?:'(?:[^'\\]|\\.)*'|"
    r"-?\d[\d.eE+\-]*|True|False|None)",
    re.IGNORECASE | re.DOTALL,
)
#: A credential value cut off by the end of the text (a truncated or
#: never-finished body): the key and its opening quote are kept, the rest of the
#: text is redacted.
_UNTERMINATED_PAIR: Final = re.compile(
    r'(?P<head>"' + _KEY_PATTERN + r'"\s*:\s*")(?:[^"\\]|\\.)*\\?\Z',
    re.IGNORECASE | re.DOTALL,
)
#: `key: value` at the start of a line, as YAML, `.env`-style dumps and logs write
#: it (`password: x`, `client_secret: x`, `x_api_key: x`). The key uses the
#: one-word form grammar; indentation and the gap around the colon are bounded,
#: and the value runs to the end of the line.
_COLON_LINE: Final = re.compile(
    r"(?m)^(?P<head>[ \t]{0,64}" + _FORM_KEY_PATTERN + r"[ \t]{0,16}:[ \t]{0,16})"
    r"(?![ \t]*\[REDACTED\])[^\r\n]+",
    re.IGNORECASE,
)
#: `key = value` at the start of a line, as TOML, INI and code write it
#: (`password = "x"`, `db_password = x`). Same key grammar and bounds as
#: `_COLON_LINE`; the value runs to the end of the line.
_EQUALS_LINE: Final = re.compile(
    r"(?m)^(?P<head>[ \t]{0,64}" + _FORM_KEY_PATTERN + r"[ \t]{0,16}=[ \t]{0,16})"
    r"(?![ \t]*\[REDACTED\])[^\r\n]+",
    re.IGNORECASE,
)
#: `key: value` with a bare (unquoted) value anywhere in a line, as invalid or
#: relaxed JSON writes it (`{password: abc, ...}`). The key starts a word and is
#: not quoted (quoted pairs are `_TEXT_PAIR`'s); the value is one run of
#: characters up to whitespace, `,`, `}`, `]` or a quote, and does not start with
#: a quote, `[` or `{`.
_BARE_PAIR: Final = re.compile(
    r"(?P<head>(?<![A-Za-z0-9_.\-\"'\\])" + _FORM_KEY_PATTERN + r"[ \t]{0,16}:[ \t]{0,16})"
    r"(?![\"'\[{])[^\s,}\]\"']+",
    re.IGNORECASE,
)
#: `key=value` in a query string or form body. The key starts only at the start
#: of a word, and the value runs to `&`, whitespace, a quote or a backslash.
_FORM_PAIR: Final = re.compile(
    r"(?P<head>(?<![A-Za-z0-9_.\-])" + _FORM_KEY_PATTERN + r"=)(?!\[REDACTED\])[^&\s\"'\\]+",
    re.IGNORECASE,
)


def _escaped_replacement(level: int, *, closed: bool) -> Callable[[re.Match[str]], str]:
    """Keep the head; replace the value with an escaped `[REDACTED]` at `level`."""
    quote = "\\" * level + '"'
    tail = quote if closed else ""

    def replace(match: re.Match[str]) -> str:
        return f"{match.group('head')}{quote}{REDACTED}{tail}"

    return replace


def _redact_dotted_run(match: re.Match[str], counter: list[int]) -> str:
    run = match.group(0)
    start = run.find("eyJ")
    if start < 0 or run.count(".", start) < 2:
        return run
    counter[0] += 1
    return run[:start] + REDACTED


def _normalized_key(key: str) -> str:
    """Lower-cased, without `-`, `_`, `.`, spaces or invisible format characters.

    `api.key`, `access-token`, `accessToken` and `pass\u200bword` (a zero-width
    space, Unicode category Cf) all normalise to their plain spelling.
    """
    return "".join(
        character
        for character in key.lower()
        if character not in "-_. " and unicodedata.category(character) != "Cf"
    )


def _is_credential_key(key: str) -> bool:
    normalized = _normalized_key(key)
    return normalized in REDACTED_KEYS or normalized.endswith(REDACTED_KEY_SUFFIXES)


def _redact_string_patterns(value: str) -> tuple[str, int]:
    """Credential-shaped runs in one string.

    `"key": "value"` pairs for `REDACTED_KEYS` (plain, one escaping level down,
    and single-quoted as a Python repr echoes them in a validation message),
    then `Bearer <token>` and JWT-shaped runs.
    """
    value, count = _PEM_PRIVATE_KEY.subn(REDACTED, value)
    value, found = _TEXT_PAIR.subn(lambda match: f'{match.group("head")}"{REDACTED}"', value)
    count += found
    for level, pattern in zip(_ESCAPE_LEVELS, _ESCAPED_TEXT_PAIRS, strict=True):
        value, found = pattern.subn(_escaped_replacement(level, closed=True), value)
        count += found
    value, found = _QUOTED_TEXT_PAIR.subn(lambda match: f"{match.group('head')}'{REDACTED}'", value)
    count += found
    value, found = _UNTERMINATED_PAIR.subn(lambda match: f"{match.group('head')}{REDACTED}", value)
    count += found
    for level, pattern in zip(_ESCAPE_LEVELS, _ESCAPED_UNTERMINATED_PAIRS, strict=True):
        value, found = pattern.subn(_escaped_replacement(level, closed=False), value)
        count += found
    value, found = _FORM_PAIR.subn(lambda match: f"{match.group('head')}{REDACTED}", value)
    count += found
    value, found = _EQUALS_LINE.subn(lambda match: f"{match.group('head')}{REDACTED}", value)
    count += found
    value, found = _URL_USERINFO.subn(lambda match: f"{match.group(1)}{REDACTED}@", value)
    count += found
    value, found = _HEADER_LINE.subn(lambda match: f"{match.group(1)}: {REDACTED}", value)
    count += found
    value, found = _COLON_LINE.subn(lambda match: f"{match.group('head')}{REDACTED}", value)
    count += found
    value, found = _BARE_PAIR.subn(lambda match: f"{match.group('head')}{REDACTED}", value)
    count += found
    value, found = _BEARER.subn(lambda match: f"{match.group(1)} {REDACTED}", value)
    count += found
    value, found = _BASIC.subn(lambda match: f"{match.group(1)} {REDACTED}", value)
    count += found
    jwt = [0]
    value = _DOTTED_RUN.sub(lambda match: _redact_dotted_run(match, jwt), value)
    return value, count + jwt[0]


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


def _loads(text: str | bytes) -> tuple[Any, bool]:
    """`json.loads`, with `NaN`, `Infinity`, `-Infinity` and overflowing numbers kept as strings.

    Python accepts and re-emits those; PostgreSQL JSONB rejects them, so a body
    carrying one would lose its whole row at insert. Returns the value and
    whether anything was replaced.
    """
    replaced = [False]

    def constant(name: str) -> str:
        replaced[0] = True
        return name

    def number(literal: str) -> float | str:
        value = float(literal)
        if math.isfinite(value):
            return value
        replaced[0] = True
        return literal

    return json.loads(text, parse_constant=constant, parse_float=number), replaced[0]


def _dumps(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def _without_noise(key: str) -> str:
    """`key` without NUL and lone surrogates, so `pass\x00word` is still `password`."""
    return "".join(
        character
        for character in key
        if character != _NUL and not 0xD800 <= ord(character) <= 0xDFFF
    )


def _unique_key(key: str, taken: dict[str, object], next_suffix: dict[str, int]) -> str:
    """`key`, or `key #2`, `key #3`, ... when redaction made two keys equal.

    Two distinct keys can become one after redaction (`"Bearer A"` and
    `"Bearer B"` both become `"Bearer [REDACTED]"`). Neither value is dropped:
    the later key gets the next free ` #n` suffix. `next_suffix` remembers the
    last suffix per base, so many colliding keys cost linear, not quadratic, time.
    """
    if key not in taken:
        return key
    suffix = next_suffix.get(key, 1)
    while True:
        suffix += 1
        candidate = f"{key} #{suffix}"
        if candidate not in taken:
            next_suffix[key] = suffix
            return candidate


def _redact_value(value: object, walk: _Walk, depth: int) -> object:
    if isinstance(value, dict):
        result: dict[str, object] = {}
        next_suffix: dict[str, int] = {}
        for key, item in value.items():
            clean_key, key_replaced = _sanitize(str(key))
            walk.nul_replaced |= key_replaced
            if _is_credential_key(clean_key) or _is_credential_key(_without_noise(str(key))):
                # The key's own text can carry a credential too
                # (`"https://u:PASS@h/x_token"`), so it is redacted as a string.
                redacted_key, count = _redact_string_patterns(clean_key)
                walk.redactions += count + 1
                result[_unique_key(redacted_key, result, next_suffix)] = REDACTED
                continue
            # A key is text too: a URL with userinfo, a bearer token or a JWT
            # used as a key is redacted like any other string.
            redacted_key, count = _redact_string_patterns(clean_key)
            walk.redactions += count
            result[_unique_key(redacted_key, result, next_suffix)] = _redact_value(
                item, walk, depth
            )
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
            # A non-finite value inside an embedded document stays a string of
            # the outer one, which JSONB holds; only the parse must not fail.
            embedded, _ = _loads(value)
        except (ValueError, RecursionError):
            embedded = None
        if isinstance(embedded, dict | list):
            inner = _Walk()
            redacted = _redact_value(embedded, inner, depth + 1)
            walk.nul_replaced |= inner.nul_replaced
            if inner.redactions:
                walk.redactions += inner.redactions
                return _dumps(redacted)
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
    non_finite_replaced: bool = False
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
            body.parsed, body.non_finite_replaced = _loads(raw)
            body.is_json = True
        except (ValueError, RecursionError):
            body.is_json = False
    if body.is_json:
        try:
            redacted, body.redactions, body.nul_replaced = redact_json(body.parsed)
            serialized = _dumps(redacted)
        except (ValueError, RecursionError):
            body.is_json = False
            body.non_finite_replaced = False
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
    """A metadata value as column text: redacted whole, *then* cut to 256 characters.

    Redacting before the cut is the same rule the bodies follow: a credential
    straddling the cut (a URL whose `@` falls past it) is recognised whole and
    never stored in part.
    """
    if value is None:
        return None
    if isinstance(value, str):
        text, count = _redact_string_patterns(value)
    else:
        # An id or method given as an object or array is redacted structurally
        # (`{"password": ["S"]}`), exactly as a body would be; that walk already
        # applies the string patterns to every key and leaf.
        structured, count, replaced = redact_json(value)
        walk.nul_replaced |= replaced
        text = json.dumps(structured, ensure_ascii=False, separators=(",", ":"))
    text = text[:_MAX_METADATA_CHARS]
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
            document, _ = _loads(text)
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
    capture_errors_before: int = 0,
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
            "non_finite_replaced": request.non_finite_replaced or response.non_finite_replaced,
            "dropped_before": dropped_before,
            "write_failures_before": write_failures_before,
            "capture_errors_before": capture_errors_before,
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


def _held_bytes(exchange: CapturedExchange) -> int:
    return len(exchange.request_body) + len(exchange.response_body)


class RowBuilder(Protocol):
    """Turns one captured exchange into a row; raises when it cannot."""

    def __call__(
        self,
        exchange: CapturedExchange,
        *,
        facade_invoke_tools: frozenset[str],
        dropped_before: int = 0,
        write_failures_before: int = 0,
        capture_errors_before: int = 0,
    ) -> dict[str, object]: ...


def _build_in_process(
    exchange: CapturedExchange,
    *,
    facade_invoke_tools: frozenset[str],
    dropped_before: int = 0,
    write_failures_before: int = 0,
    capture_errors_before: int = 0,
) -> dict[str, object]:
    """The default builder: `build_interaction_row`, in the calling thread."""
    return build_interaction_row(
        exchange,
        facade_invoke_tools=facade_invoke_tools,
        dropped_before=dropped_before,
        write_failures_before=write_failures_before,
        capture_errors_before=capture_errors_before,
    )


@dataclass(frozen=True)
class _PortablePrincipal:
    principal_id: object
    kind: object


@dataclass(frozen=True)
class _PortableAccess:
    """The two facts the row reads from the access context, in picklable form."""

    principal: _PortablePrincipal | None
    authenticated_client_id: object


def _portable_access(access: object) -> _PortableAccess | None:
    if access is None:
        return None
    principal = getattr(access, "principal", None)
    kind = getattr(principal, "kind", None)
    return _PortableAccess(
        principal=None
        if principal is None
        else _PortablePrincipal(
            principal_id=getattr(principal, "principal_id", None),
            kind=None if kind is None else str(getattr(kind, "value", kind)),
        ),
        authenticated_client_id=getattr(access, "authenticated_client_id", None),
    )


class RowBuildFailedError(RuntimeError):
    """The worker process failed, crashed or exceeded its time for one row."""


def _row_worker(connection: Connection) -> None:
    """Child-process loop: one header and two bodies in, one row out, until EOF.

    The bodies arrive with `send_bytes` (no pickling of up to 2 x 16 MiB); the
    header is a small pickled `CapturedExchange` with empty bodies.
    """
    while True:
        try:
            message = connection.recv()
        except (EOFError, OSError):
            return
        if message is None:
            return
        header, options = message
        try:
            request = connection.recv_bytes()
            response = connection.recv_bytes()
        except (EOFError, OSError):
            return
        try:
            exchange = dataclasses.replace(header, request_body=request, response_body=response)
            row = build_interaction_row(exchange, **options)
        except MemoryError:
            # Past the address-space limit: say so and exit, so the parent
            # replaces this (possibly fragmented) process with a fresh one.
            del request, response
            with contextlib.suppress(Exception):
                connection.send(("memory", None))
            return
        except Exception:
            connection.send(("error", None))
        else:
            connection.send(("ok", row))


def _limit_address_space(limit: int) -> bool:
    """Cap this process's virtual address space at `limit` bytes (`RLIMIT_AS`).

    Returns whether the cap is in force. Linux enforces it: an allocation past
    it raises `MemoryError`. macOS does not support lowering `RLIMIT_AS` (the
    call raises `ValueError`), so there the worker runs uncapped and says so.
    """
    if limit <= 0:
        return False
    try:
        import resource  # POSIX-only; imported where the worker needs it

        resource.setrlimit(resource.RLIMIT_AS, (limit, limit))
    except (ImportError, ValueError, OSError):
        return False
    return True


def _row_worker_main(descriptor: int, memory_limit: int = 0) -> None:
    """Entry point of the worker process: cap memory, announce readiness, serve rows."""
    connection = Connection(descriptor)
    capped = _limit_address_space(memory_limit)
    connection.send(("ready", {"memory_limited": capped}))
    _row_worker(connection)


#: How the worker process is started: this interpreter, importing only this
#: module (`-c`), with the socket descriptor appended as the last argument. A
#: `multiprocessing` spawn would re-import the gateway's `__main__` in the child
#: (about 134 MiB measured); this imports the capture module and the stdlib.
_WORKER_COMMAND: Final = (
    sys.executable,
    "-c",
    # The module's own name rather than a literal: the sibling-transport guard
    # matches any text naming the MCP transport package.
    f"import sys; from {__name__} import _row_worker_main; "
    "_row_worker_main(int(sys.argv[1]), int(sys.argv[2]))",
)


class ProcessRowBuilder:
    """Builds rows in one child process, so their CPU never holds the gateway's GIL.

    Every regex and JSON step of `build_interaction_row` holds the GIL for its
    whole run (measured in-thread: a 16 MiB text body stalled a 1 ms ticker
    for about 1.3 s). Here the writer thread only sends the bodies over a
    socket (`send_bytes`, which releases the GIL while it writes), waits with
    `poll` (which releases it too) and unpickles the finished row.

    **The worker** is one child process started with `subprocess` from
    `_WORKER_COMMAND` on the first row; it imports only this module, so it does
    not re-run the gateway's imports. It must announce itself within
    `startup_seconds`.

    **Every round trip is bounded.** A watchdog timer armed before the first
    byte is sent kills the worker when `timeout_seconds` pass, which also
    unblocks a send into a worker that has stopped reading (the write fails
    with a broken pipe). A timeout, a crash, a broken pipe or a failed build
    raises `RowBuildFailedError`: the recorder counts a capture error and drops
    that row, never retrying. A dead or killed worker is replaced on the next
    row.

    **Start failures back off.** After `breaker_threshold` consecutive failed
    starts, no start is attempted for `breaker_seconds`, doubling on each
    further failed start up to `breaker_max_seconds`; meanwhile every row fails
    at once (a counted capture error), so a broken worker cannot turn into a
    respawn per request. A successful start resets the breaker. Failed starts
    are reported on `stderr` as a count-only `worker_start_failed` line, at the
    first and then at most once per 60 s.

    **The worker's memory is capped** when `memory_limit_bytes` is set: it
    lowers its own `RLIMIT_AS` before announcing itself. A row that needs more
    raises `MemoryError` in the worker, which reports it and exits; the row
    fails here (a counted capture error) and the next row starts a fresh worker.
    It is not a failed start, so it never trips the breaker. Linux enforces the
    cap; macOS cannot lower `RLIMIT_AS`, and `memory_limited` records which.

    **`close` never blocks.** It takes the builder's lock only briefly; if a
    round trip holds it, the worker is killed (which ends that round trip).
    Otherwise the socket is closed so the worker exits at EOF, then it is
    terminated and finally killed, each wait bounded by `exit_seconds`. After
    `close` no worker is started.
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        startup_seconds: float = 20.0,
        exit_seconds: float = 0.5,
        breaker_threshold: int = 3,
        breaker_seconds: float = 60.0,
        breaker_max_seconds: float = 900.0,
        worker_command: tuple[str, ...] = _WORKER_COMMAND,
        memory_limit_bytes: int = 0,
        clock: Callable[[], float] = time.monotonic,
        stderr: TextIO | None = None,
    ) -> None:
        self._timeout = timeout_seconds
        self._startup = startup_seconds
        self._exit_seconds = exit_seconds
        self._breaker_threshold = breaker_threshold
        self._breaker_initial = breaker_seconds
        self._breaker_max = breaker_max_seconds
        self._command = worker_command
        self._memory_limit = memory_limit_bytes
        #: Whether the running worker reported its address-space cap in force.
        self.memory_limited: bool | None = None
        self._clock = clock
        self._stderr = stderr
        self._lock = threading.Lock()
        self._process: subprocess.Popen[bytes] | None = None
        self._connection: Connection | None = None
        self._closed = False
        self._start_failures = 0
        self._consecutive_start_failures = 0
        self._tripped = False
        self._breaker_cooldown = breaker_seconds
        self._suspended_until = 0.0
        self._last_start_report: float | None = None
        self.start_attempts = 0

    @property
    def worker_pid(self) -> int | None:
        process = self._process
        return None if process is None else process.pid

    def _report_start_failure(self) -> None:
        now = self._clock()
        if self._last_start_report is not None and now - self._last_start_report < 60.0:
            return
        self._last_start_report = now
        suspended = max(0.0, self._suspended_until - now)
        stream = self._stderr if self._stderr is not None else sys.stderr
        with contextlib.suppress(Exception):
            print(
                f"mcp-interaction-log worker_start_failed start_failures={self._start_failures} "
                f"suspended_seconds={suspended:.0f}",
                file=stream,
                flush=True,
            )

    def _start(self) -> Connection:
        """Start a worker and wait for it to announce itself; raise on failure."""
        if self._clock() < self._suspended_until:
            raise RowBuildFailedError("worker starts are suspended")
        self.start_attempts += 1
        parent, child = socket.socketpair()
        process: subprocess.Popen[bytes] | None = None
        connection = Connection(parent.detach())
        try:
            environment = dict(os.environ)
            package_root = str(Path(__file__).resolve().parents[2])
            environment["PYTHONPATH"] = os.pathsep.join(
                [package_root, *filter(None, [environment.get("PYTHONPATH")])]
            )
            process = subprocess.Popen(  # noqa: S603 - fixed interpreter and code, no shell
                [*self._command, str(child.fileno()), str(self._memory_limit)],
                pass_fds=(child.fileno(),),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                env=environment,
            )
            child.close()
            if not connection.poll(self._startup):
                raise RowBuildFailedError("worker did not start in time")
            status, facts = connection.recv()
            if status != "ready":
                raise RowBuildFailedError("worker announced something else")
            self.memory_limited = bool(isinstance(facts, dict) and facts.get("memory_limited"))
        except Exception as failure:
            with contextlib.suppress(Exception):
                child.close()
            with contextlib.suppress(Exception):
                connection.close()
            if process is not None:
                self._kill(process)
            self._start_failures += 1
            self._consecutive_start_failures += 1
            if self._tripped or self._consecutive_start_failures >= self._breaker_threshold:
                if self._tripped:
                    # The trial start after a cool-down failed: back off longer.
                    self._breaker_cooldown = min(self._breaker_cooldown * 2, self._breaker_max)
                self._suspended_until = self._clock() + self._breaker_cooldown
                self._tripped = True
            self._report_start_failure()
            if isinstance(failure, RowBuildFailedError):
                raise
            raise RowBuildFailedError("worker failed to start") from failure
        self._consecutive_start_failures = 0
        self._tripped = False
        self._breaker_cooldown = self._breaker_initial
        self._process, self._connection = process, connection
        return connection

    def _worker(self) -> Connection:
        if self._closed:
            raise RowBuildFailedError("row builder is closed")
        process, connection = self._process, self._connection
        if connection is not None and process is not None and process.poll() is None:
            return connection
        self._discard()
        return self._start()

    def _kill(self, process: subprocess.Popen[bytes]) -> None:
        """Kill `process` and reap it, waiting at most `exit_seconds`. Never raises."""
        with contextlib.suppress(Exception):
            process.kill()
        with contextlib.suppress(Exception):
            process.wait(self._exit_seconds)

    def _discard(self) -> None:
        """Kill and forget the current worker, if any."""
        process, connection = self._process, self._connection
        self._process, self._connection = None, None
        if process is not None:
            self._kill(process)
        if connection is not None:
            with contextlib.suppress(Exception):
                connection.close()

    def __call__(
        self,
        exchange: CapturedExchange,
        *,
        facade_invoke_tools: frozenset[str],
        dropped_before: int = 0,
        write_failures_before: int = 0,
        capture_errors_before: int = 0,
    ) -> dict[str, object]:
        header = dataclasses.replace(
            exchange,
            request_body=b"",
            response_body=b"",
            access=_portable_access(exchange.access),
        )
        options = {
            "facade_invoke_tools": facade_invoke_tools,
            "dropped_before": dropped_before,
            "write_failures_before": write_failures_before,
            "capture_errors_before": capture_errors_before,
        }
        with self._lock:
            connection = self._worker()
            process = self._process
            deadline = time.monotonic() + self._timeout
            # Bounds the whole round trip, sends included: killing the worker
            # makes a blocked send fail with a broken pipe.
            watchdog = threading.Timer(self._timeout, self._kill, args=(process,))
            watchdog.daemon = True
            watchdog.start()
            try:
                connection.send((header, options))
                connection.send_bytes(exchange.request_body)
                connection.send_bytes(exchange.response_body)
                if not connection.poll(max(0.0, deadline - time.monotonic())):
                    raise RowBuildFailedError("row build timed out")
                status, row = connection.recv()
            except RowBuildFailedError:
                self._discard()
                raise
            except Exception as failure:
                self._discard()
                raise RowBuildFailedError("row worker failed") from failure
            finally:
                watchdog.cancel()
        if status == "memory":
            with self._lock:
                self._discard()
            raise RowBuildFailedError("row exceeded the worker's memory limit")
        if status != "ok" or not isinstance(row, dict):
            raise RowBuildFailedError("row build raised in the worker")
        return row

    def close(self) -> None:
        """Stop the worker without ever blocking for long. Idempotent.

        Bounded by about 0.2 s plus three `exit_seconds` waits.
        """
        self._closed = True
        acquired = self._lock.acquire(timeout=0.2)
        try:
            process, connection = self._process, self._connection
            if process is None:
                return
            if not acquired:
                # A round trip holds the lock and may be blocked in a send:
                # killing the worker ends it; that thread then discards.
                self._kill(process)
                return
            if connection is not None:
                with contextlib.suppress(Exception):
                    connection.close()  # the worker exits at EOF
            self._process, self._connection = None, None
            for stop in (None, process.terminate, process.kill):
                if stop is not None:
                    with contextlib.suppress(Exception):
                        stop()
                with contextlib.suppress(Exception):
                    process.wait(self._exit_seconds)
                if process.poll() is not None:
                    return
        finally:
            if acquired:
                self._lock.release()


class InteractionRecorder:
    """One bounded queue and one daemon writer thread in front of a sink.

    `submit` never blocks and never raises. `start` launches the writer; `stop`
    drains what it can within `timeout` seconds, closes the row builder and
    returns. The counters are process totals: `dropped` (queue full, or offered
    after stop), `write_failures` (the sink raised) and `capture_errors` (the
    tee or the row builder raised or timed out).

    `builder` turns a captured exchange into a row. The default builds it in
    this process (unit tests); the gateway injects a `ProcessRowBuilder`, which
    builds it in a child process so the regex and JSON work never holds this
    process's GIL. A builder with a `close()` method is closed by `stop`.
    """

    def __init__(
        self,
        sink: InteractionSink,
        *,
        facade_invoke_tools: frozenset[str],
        maxsize: int = QUEUE_MAXSIZE,
        max_queued_bytes: int = QUEUED_BYTES_BUDGET,
        drop_report_seconds: float = DROP_REPORT_SECONDS,
        stderr: TextIO | None = None,
        builder: RowBuilder | None = None,
    ) -> None:
        self._sink = sink
        self._builder: RowBuilder = builder if builder is not None else _build_in_process
        self.facade_invoke_tools = facade_invoke_tools
        self._queue: queue.Queue[object] = queue.Queue(maxsize=maxsize)
        self._stderr = stderr
        self._lock = threading.Lock()
        self._dropped = 0
        self._write_failures = 0
        self._capture_errors = 0
        self._dropped_reported = 0
        self._failures_reported = 0
        self._capture_errors_reported = 0
        self._thread: threading.Thread | None = None
        self._stopping = threading.Event()
        self._deadline = 0.0
        self._max_queued_bytes = max_queued_bytes
        self._queued_bytes = 0
        self._drop_report_seconds = drop_report_seconds
        self._last_report: dict[str, float] = {}

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
            thread.join(max(0.0, self._deadline - time.monotonic()))
        close = getattr(self._builder, "close", None)
        if close is not None:
            with contextlib.suppress(Exception):
                close()
        abandoned = 0
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            if isinstance(item, CapturedExchange):
                abandoned += 1
                self._release(item)
        if abandoned:
            with self._lock:
                self._dropped += abandoned
            self._report(f"abandoned={abandoned}")

    def submit(self, exchange: CapturedExchange) -> None:
        """Offer one exchange to the writer. Never blocks, never raises."""
        try:
            if self._stopping.is_set():
                raise queue.Full
            size = _held_bytes(exchange)
            with self._lock:
                if self._queued_bytes + size > self._max_queued_bytes:
                    raise queue.Full
                self._queued_bytes += size
            try:
                self._queue.put_nowait(exchange)
            except queue.Full:
                self._release(exchange)
                raise
        except queue.Full:
            with self._lock:
                self._dropped += 1
                due = self._report_due("dropped")
            if due:
                # Count-only, at most once per interval, outside the lock.
                self._report("dropped")
        except Exception:
            self.note_capture_error()

    @property
    def queued_bytes(self) -> int:
        """Body bytes held by exchanges waiting for the writer."""
        return self._queued_bytes

    def _release(self, exchange: CapturedExchange) -> None:
        with self._lock:
            self._queued_bytes -= _held_bytes(exchange)

    def note_capture_error(self) -> None:
        with self._lock:
            self._capture_errors += 1

    def _report_due(self, kind: str) -> bool:
        """First occurrence of `kind`, then at most once per interval. Call under the lock."""
        now = time.monotonic()
        last = self._last_report.get(kind)
        if last is not None and now - last < self._drop_report_seconds:
            return False
        self._last_report[kind] = now
        return True

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
                self._release(item)
                self._write(item)

    def _write(self, exchange: CapturedExchange) -> None:
        with self._lock:
            dropped = self._dropped
            failures = self._write_failures
            errors = self._capture_errors
        try:
            row = self._builder(
                exchange,
                facade_invoke_tools=self.facade_invoke_tools,
                dropped_before=dropped - self._dropped_reported,
                write_failures_before=failures - self._failures_reported,
                capture_errors_before=errors - self._capture_errors_reported,
            )
        except Exception:
            with self._lock:
                self._capture_errors += 1
                due = self._report_due("capture_error")
            if due:
                # Count-only and throttled like drops; never the exchange.
                self._report("capture_error")
            return
        try:
            self._sink(row)
        except Exception:
            with self._lock:
                self._write_failures += 1
                due = self._report_due("write_failed")
            if due:
                # Count-only, first failure then at most once per interval: a
                # database outage must not become a line per request.
                self._report("write_failed")
            return
        self._dropped_reported = dropped
        self._failures_reported = failures
        self._capture_errors_reported = errors


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
