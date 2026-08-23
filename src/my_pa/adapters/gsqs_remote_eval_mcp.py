"""Isolated Streamable HTTP MCP surface for GSQS ChatLLM remote evaluation.

This process is not production MCP. It does not import the production tool
registry or compose the main application service. Protocol connection state is
not evaluation state; evaluation state is Phase A ``RemoteEvalService``.
This module lives at ``adapters/gsqs_remote_eval_mcp.py`` so importing it does
not execute ``adapters/mcp/__init__.py``, which would load the production MCP
tool registry and application service.

``wrap_eval_asgi_send`` binds ``DISCLOSED_TO_TRANSPORT`` to a successful final
ASGI image-body send. ``OUTBOUND_ATTEMPT_STARTED`` is recorded durably before
image bytes are handed to ASGI send. Tool return is not disclosure.
``with_transport_callback`` is not used for transport confirmation.
"""

from __future__ import annotations

import asyncio
import base64
import json
from collections.abc import AsyncIterator, Callable, Mapping, MutableMapping, Sequence
from contextlib import asynccontextmanager
from contextvars import ContextVar
from hashlib import sha256
from pathlib import Path
from typing import Final, Protocol

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ContentBlock,
    ImageContent,
    ListToolsResult,
    TextContent,
    Tool,
    ToolAnnotations,
)
from mcp.types import PaginatedRequestParams as ListToolsParams
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route
from starlette.types import Receive, Scope, Send

from my_pa import __version__
from my_pa.adapters.normalization import MAX_REQUEST_BYTES
from my_pa.application.goodnotes_gsqs_remote_eval import RemoteEvalService
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    CASES_PER_REPETITION,
    ERROR_FORBIDDEN_SCOPE,
    ERROR_INTERNAL_FAIL_CLOSED,
    ERROR_NO_ACTIVE_SESSION,
    ERROR_RASTER_INTEGRITY_FAILURE,
    ERROR_RESULT_TOO_LARGE,
    SCHEMA_STATE_V1,
    RemoteEvalError,
    RemoteEvalStore,
)
from my_pa.application.goodnotes_gsqs_remote_eval_storage import (
    reject_symlink,
    session_directory,
)
from my_pa.domain.common.time import format_rfc3339

__all__ = [
    "DEFAULT_EVAL_RESOURCE",
    "EVAL_OAUTH_SCOPE",
    "EVAL_TOOL_NEXT",
    "EVAL_TOOL_STATUS",
    "EVAL_TOOL_SUBMIT",
    "MAX_IMAGE_BYTES",
    "MAX_RESULT_BYTES",
    "MCP_PATH",
    "GsqsDisclosureAttempt",
    "GsqsEvalAuthenticator",
    "GsqsEvalPrincipal",
    "create_gsqs_remote_eval_app",
    "gsqs_eval_disclosure_attempt",
    "gsqs_eval_tools",
    "invoke_gsqs_eval_tool",
    "png_image_content",
    "wrap_eval_asgi_send",
]

SERVER_NAME: Final = "my-pa-gsqs-remote-eval"
MCP_PATH: Final = "/mcp"
HEALTH_PATH: Final = "/healthz"
READINESS_PATH: Final = "/readyz"
DEFAULT_EVAL_RESOURCE: Final = "https://my-pa-gsqs.bobby-fetting.me/mcp"
EVAL_OAUTH_SCOPE: Final = "my-pa.gsqs.evaluate"
EVAL_TOOL_STATUS: Final = "goodnotes.eval.status"
EVAL_TOOL_NEXT: Final = "goodnotes.eval.next"
EVAL_TOOL_SUBMIT: Final = "goodnotes.eval.submit"
MAX_IMAGE_BYTES: Final = 8_388_608
MAX_RESULT_BYTES: Final = 1_048_576
PNG_MIME: Final = "image/png"
PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"
MAX_CONCURRENT_CALLS: Final = 1

_EMPTY_INPUT_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {},
    "additionalProperties": False,
}
_SUBMIT_INPUT_SCHEMA: Final[dict[str, object]] = {
    "type": "object",
    "properties": {
        "lease_id": {"type": "string"},
        "segments": {"type": "array"},
    },
    "required": ["lease_id", "segments"],
    "additionalProperties": False,
}
_SUBMIT_KEYS: Final = frozenset({"lease_id", "segments"})


class GsqsDisclosureAttempt:
    """Attempt identity Worker E reads from the ContextVar at ASGI send."""

    __slots__ = ("attempt_id", "session_id")

    def __init__(self, session_id: str, attempt_id: str) -> None:
        self.session_id = session_id
        self.attempt_id = attempt_id

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.attempt_id == other
        if isinstance(other, GsqsDisclosureAttempt):
            return (self.session_id, self.attempt_id) == (other.session_id, other.attempt_id)
        return NotImplemented


gsqs_eval_disclosure_attempt: ContextVar[GsqsDisclosureAttempt | None] = ContextVar(
    "gsqs_eval_disclosure_attempt",
    default=None,
)


class GsqsEvalPrincipal(Protocol):
    @property
    def principal_id(self) -> str: ...


class GsqsEvalAuthenticator(Protocol):
    def authenticate(self, authorization_header: str | None) -> GsqsEvalPrincipal: ...


class GsqsEvalRasterReader(Protocol):
    def read_png(
        self,
        *,
        session_id: str,
        staged_filename: str,
        content_sha256: str,
        byte_length: int,
    ) -> bytes: ...


def _asgi_body_bytes(message: Mapping[str, object]) -> bytes:
    raw = message.get("body", b"")
    if isinstance(raw, bytes):
        return raw
    if isinstance(raw, bytearray | memoryview):
        return bytes(raw)
    if isinstance(raw, str):
        return raw.encode("utf-8")
    return b""


def _asgi_more_body(message: Mapping[str, object]) -> bool:
    if "more_body" in message:
        return bool(message["more_body"])
    return bool(message.get("more_body", False))


def _asgi_is_http_start(message: Mapping[str, object]) -> bool:
    return message.get("type") == "http.response.start"


def _asgi_is_http_body(message: Mapping[str, object]) -> bool:
    return message.get("type") == "http.response.body"


def _body_carries_image(body: bytes) -> bool:
    """Conservative image-payload detection for an ASGI response body chunk."""

    if not body:
        return False
    if PNG_MAGIC in body:
        return True
    if b"image/png" in body:
        return True
    if b'"mime_type":"image/png"' in body or b'"mimeType":"image/png"' in body:
        return True
    typed_image = b'"type":"image"' in body or b'"type": "image"' in body
    has_data = b'"data"' in body
    return typed_image and has_data


class _EvalDisclosureSend:
    """ASGI send wrapper that binds disclosure to a successful final image body send."""

    def __init__(
        self,
        send: Send,
        *,
        confirm_disclosed: Callable[[str, str], None] | None,
        confirm_not_disclosed: Callable[[str, str], None] | None,
        attempt_holder: MutableMapping[str, object] | None = None,
    ) -> None:
        self._send = send
        self._confirm_disclosed = confirm_disclosed
        self._confirm_not_disclosed = confirm_not_disclosed
        self._attempt_holder = attempt_holder
        self._attempt: GsqsDisclosureAttempt | None = None
        self._saw_start = False
        self._body_handed = False
        self._image_handed = False
        self._final_body_succeeded = False
        self._terminal_attempted = False
        self._ambiguous = False

    def _capture_attempt(self) -> GsqsDisclosureAttempt | None:
        if self._attempt is None:
            self._attempt = gsqs_eval_disclosure_attempt.get()
        if self._attempt is None and self._attempt_holder is not None:
            stored = self._attempt_holder.get("gsqs_eval_disclosure_attempt")
            if isinstance(stored, GsqsDisclosureAttempt):
                self._attempt = stored
        return self._attempt

    def _confirm(self, action: Callable[[str, str], None] | None) -> None:
        attempt = self._capture_attempt()
        if attempt is None or action is None:
            return
        self._terminal_attempted = True
        action(attempt.session_id, attempt.attempt_id)

    async def __call__(self, message: MutableMapping[str, object]) -> None:
        is_start = _asgi_is_http_start(message)
        is_body = _asgi_is_http_body(message)
        image_chunk = False
        final_body = False
        if is_body:
            body = _asgi_body_bytes(message)
            image_chunk = _body_carries_image(body)
            final_body = not _asgi_more_body(message)
            if image_chunk and self._capture_attempt() is None:
                raise RuntimeError("gsqs eval image send refused without outbound attempt")
            self._body_handed = True
            if image_chunk:
                self._image_handed = True
        try:
            await self._send(message)
        except BaseException:
            if self._image_handed:
                self._ambiguous = True
            raise
        if is_start:
            self._saw_start = True
        if is_body and final_body:
            self._final_body_succeeded = True
            if self._image_handed:
                self._confirm(self._confirm_disclosed)
            else:
                self._confirm(self._confirm_not_disclosed)

    def finalize(self) -> None:
        if self._terminal_attempted or self._ambiguous:
            return
        if self._capture_attempt() is None:
            return
        if self._image_handed:
            self._ambiguous = True
            return
        if self._saw_start and not self._body_handed:
            self._ambiguous = True
            return
        self._confirm(self._confirm_not_disclosed)


def wrap_eval_asgi_send(
    send: Send,
    *_args: object,
    service: RemoteEvalService | None = None,
    confirm_disclosed: Callable[[str, str], None] | None = None,
    confirm_not_disclosed: Callable[[str, str], None] | None = None,
    attempt_holder: MutableMapping[str, object] | None = None,
    **_kwargs: object,
) -> Send:
    """Bind DISCLOSED_TO_TRANSPORT to a successful final ASGI image-body send.

    ``OUTBOUND_ATTEMPT_STARTED`` must already be durable: image body chunks are
    refused unless an attempt identity is visible. Without ``service`` or confirm
    callbacks this remains an identity wrapper so tool return is never treated as
    disclosure. ``with_transport_callback`` is not used. ``attempt_holder`` is
    the ASGI ``scope['state']`` dict: MCP may invoke the tool in a sibling task,
    so ContextVar alone is not visible at send.
    """

    if service is not None:
        if confirm_disclosed is None:
            confirm_disclosed = service.confirm_disclosed_to_transport
        if confirm_not_disclosed is None:
            confirm_not_disclosed = service.confirm_not_disclosed
    if confirm_disclosed is None and confirm_not_disclosed is None:
        return send
    return _EvalDisclosureSend(
        send,
        confirm_disclosed=confirm_disclosed,
        confirm_not_disclosed=confirm_not_disclosed,
        attempt_holder=attempt_holder,
    )


def _metadata_url(resource: str) -> str:
    suffix = "/mcp" if resource.endswith("/mcp") else ""
    origin = resource.removesuffix(suffix).rstrip("/")
    return f"{origin}/.well-known/oauth-protected-resource{suffix}"


def _authenticator_exceptions(exc: BaseException) -> tuple[BaseException, ...]:
    """Walk ``to_thread``/wait_for wrappers without flattening the refusal first."""

    pending: list[BaseException] = [exc]
    seen: set[int] = set()
    found: list[BaseException] = []
    while pending:
        current = pending.pop()
        marker = id(current)
        if marker in seen:
            continue
        seen.add(marker)
        found.append(current)
        if isinstance(current, BaseExceptionGroup):
            pending.extend(current.exceptions)
        if current.__cause__ is not None:
            pending.append(current.__cause__)
        if current.__context__ is not None:
            pending.append(current.__context__)
    return tuple(found)


def _is_forbidden_scope_refusal(exc: BaseException) -> bool:
    for item in _authenticator_exceptions(exc):
        if getattr(item, "code", None) == ERROR_FORBIDDEN_SCOPE:
            return True
    return False


def _authentication_challenge(
    resource: str,
    exc: BaseException,
    scopes: frozenset[str],
) -> JSONResponse:
    metadata_url = _metadata_url(resource)
    if _is_forbidden_scope_refusal(exc):
        scope_value = " ".join(sorted(scopes))
        return JSONResponse(
            {"error": "insufficient_scope"},
            status_code=403,
            headers={
                "WWW-Authenticate": (
                    f'Bearer resource_metadata="{metadata_url}", '
                    'error="insufficient_scope", '
                    'error_description="the presented bearer credential lacks the required scope", '
                    f'scope="{scope_value}"'
                )
            },
        )
    return JSONResponse(
        {"error": "invalid_token"},
        status_code=401,
        headers={"WWW-Authenticate": f'Bearer resource_metadata="{metadata_url}"'},
    )


def _oauth_meta(scopes: frozenset[str]) -> dict[str, object]:
    return {"securitySchemes": [{"type": "oauth2", "scopes": sorted(scopes)}]}


def gsqs_eval_tools(
    *, oauth_scopes: frozenset[str] = frozenset({EVAL_OAUTH_SCOPE})
) -> tuple[Tool, ...]:
    """The three public remote-eval tools. Not the production registry."""

    meta = _oauth_meta(oauth_scopes)
    return (
        Tool(
            name=EVAL_TOOL_STATUS,
            description="Safe public status of the single active remote-eval session.",
            input_schema=dict(_EMPTY_INPUT_SCHEMA),
            annotations=ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                open_world_hint=False,
            ),
            _meta=meta,
        ),
        Tool(
            name=EVAL_TOOL_NEXT,
            description="Acquire the current leased case and return its PNG as ImageContent.",
            input_schema=dict(_EMPTY_INPUT_SCHEMA),
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=False,
                open_world_hint=False,
            ),
            _meta=meta,
        ),
        Tool(
            name=EVAL_TOOL_SUBMIT,
            description="Submit analyzer segments for the outstanding lease.",
            input_schema=dict(_SUBMIT_INPUT_SCHEMA),
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=False,
                open_world_hint=False,
            ),
            _meta=meta,
        ),
    )


def png_image_content(payload: bytes) -> ImageContent:
    """Native MCP ImageContent from PNG bytes. Never a URL, data URI, or path."""

    return ImageContent(
        type="image",
        data=base64.standard_b64encode(payload).decode("ascii"),
        mime_type=PNG_MIME,
    )


def _json_text(document: Mapping[str, object]) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _error_result(code: str, message: str = "") -> CallToolResult:
    _ = message
    return CallToolResult(
        content=[
            TextContent(
                type="text",
                text=_json_text({"code": code, "error": code}),
            )
        ],
        is_error=True,
    )


def _success_result(
    document: Mapping[str, object], image: ImageContent | None = None
) -> CallToolResult:
    blocks: list[ContentBlock] = [TextContent(type="text", text=_json_text(document))]
    if image is not None:
        blocks.append(image)
    return CallToolResult(content=blocks, is_error=False)


def _store_of(service: RemoteEvalService, store: RemoteEvalStore | None) -> RemoteEvalStore:
    if store is not None:
        return store
    return service._store


def _require_empty_arguments(arguments: Mapping[str, object] | None) -> None:
    if arguments:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "unexpected tool arguments")


def _submit_arguments(arguments: Mapping[str, object] | None) -> tuple[str, Sequence[object]]:
    document = {} if arguments is None else dict(arguments)
    extra = set(document) - _SUBMIT_KEYS
    if extra:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "unexpected tool arguments")
    lease_id = document.get("lease_id")
    segments = document.get("segments")
    if not isinstance(lease_id, str) or not lease_id:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "lease_id is required")
    if not isinstance(segments, list):
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "segments are required")
    return lease_id, segments


def _resolve_bound_session(store: RemoteEvalStore, principal: GsqsEvalPrincipal) -> str:
    session_id = store.find_non_terminal_session_id()
    if session_id is None:
        raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "no active session")
    session = store.load_session(session_id)
    if session is None:
        raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "no active session")
    if principal.principal_id != session.principal_id:
        raise RemoteEvalError(ERROR_FORBIDDEN_SCOPE, "principal does not match session")
    return session.session_id


class FilesystemStagedPngReader:
    """Read a sealed staged PNG under the eval store state root. No source paths."""

    def __init__(self, store: object, *, max_image_bytes: int = MAX_IMAGE_BYTES) -> None:
        self._store = store
        self._max_image_bytes = max_image_bytes

    def read_png(
        self,
        *,
        session_id: str,
        staged_filename: str,
        content_sha256: str,
        byte_length: int,
    ) -> bytes:
        if byte_length > self._max_image_bytes or byte_length < 1:
            raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "raster exceeds max_image_bytes")
        if (
            not staged_filename
            or "/" in staged_filename
            or "\\" in staged_filename
            or ".." in staged_filename
            or staged_filename != Path(staged_filename).name
        ):
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "staged raster is invalid")
        state_root = getattr(self._store, "_state_root", None)
        if state_root is None:
            raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "staged raster is unavailable")
        rasters = session_directory(Path(state_root), session_id) / "rasters"
        reject_symlink(rasters, what="rasters directory")
        path = rasters / staged_filename
        reject_symlink(path, what="staged raster")
        if not path.is_file():
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "staged raster is missing")
        payload = path.read_bytes()
        if len(payload) > self._max_image_bytes:
            raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "raster exceeds max_image_bytes")
        if len(payload) != byte_length:
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster length mismatch")
        if sha256(payload).hexdigest() != content_sha256:
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster digest mismatch")
        if not payload.startswith(PNG_MAGIC):
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster is not a PNG")
        return payload


def _status_payload(service: RemoteEvalService, session_id: str) -> dict[str, object]:
    status = service.status(session_id)
    return {
        "schema_version": SCHEMA_STATE_V1,
        "state": str(status.state),
        "repetition": status.active_repetition,
        "repetitions_required": status.repetitions_required,
        "next_case_ordinal": status.next_case_ordinal,
        "cases_per_repetition": status.case_count if status.case_count else CASES_PER_REPETITION,
        "expires_at": format_rfc3339(status.expires_at),
        "session_identity_sha256": status.session_identity_sha256,
    }


def _next_result(
    service: RemoteEvalService,
    session_id: str,
    raster_reader: GsqsEvalRasterReader,
    *,
    max_image_bytes: int,
) -> CallToolResult:
    acquired = service.acquire_case(session_id)
    if acquired.byte_length > max_image_bytes or acquired.byte_length < 1:
        raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "raster exceeds max_image_bytes")
    payload = raster_reader.read_png(
        session_id=session_id,
        staged_filename=acquired.staged_filename,
        content_sha256=acquired.content_sha256,
        byte_length=acquired.byte_length,
    )
    if len(payload) > max_image_bytes:
        raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "raster exceeds max_image_bytes")
    if len(payload) != acquired.byte_length:
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster length mismatch")
    if sha256(payload).hexdigest() != acquired.content_sha256:
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster digest mismatch")
    if not payload.startswith(PNG_MAGIC):
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster is not a PNG")
    # STARTED is durable before ImageContent exists and before ASGI send.
    attempt_id = service.record_outbound_attempt(
        session_id,
        repetition=acquired.repetition,
        case_id=acquired.case_id,
    )
    gsqs_eval_disclosure_attempt.set(
        GsqsDisclosureAttempt(session_id=session_id, attempt_id=attempt_id)
    )
    return _success_result(
        {
            "lease_id": acquired.lease.lease_id,
            "ordinal": acquired.ordinal,
            "repetition": acquired.repetition,
            "content_sha256": acquired.content_sha256,
            "mime_type": PNG_MIME,
            "byte_length": len(payload),
        },
        png_image_content(payload),
    )


def _submit_result(
    service: RemoteEvalService,
    session_id: str,
    lease_id: str,
    segments: Sequence[object],
    *,
    max_result_bytes: int,
) -> CallToolResult:
    encoded = json.dumps(list(segments), separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > max_result_bytes:
        raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "result exceeds max_result_bytes")
    receipt = service.submit_capture(session_id, lease_id, segments)
    document: dict[str, object] = {
        "repetition": receipt.repetition,
        "ordinal": receipt.ordinal,
        "capture_identity_sha256": receipt.capture_identity_sha256,
        "duplicate": receipt.duplicate,
        "state": str(receipt.state),
    }
    if len(_json_text(document).encode("utf-8")) > max_result_bytes:
        raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "result exceeds max_result_bytes")
    return _success_result(document)


def invoke_gsqs_eval_tool(
    name: str,
    arguments: Mapping[str, object] | None,
    *,
    principal: GsqsEvalPrincipal,
    service: RemoteEvalService,
    store: RemoteEvalStore | None = None,
    raster_reader: GsqsEvalRasterReader | None = None,
    max_image_bytes: int = MAX_IMAGE_BYTES,
    max_result_bytes: int = MAX_RESULT_BYTES,
) -> CallToolResult:
    """Synchronous tool body. Session identity is never taken from tool JSON."""

    try:
        resolved_store = _store_of(service, store)
        session_id = _resolve_bound_session(resolved_store, principal)
        reader = raster_reader or FilesystemStagedPngReader(
            resolved_store, max_image_bytes=max_image_bytes
        )
        if name == EVAL_TOOL_STATUS:
            _require_empty_arguments(arguments)
            return _success_result(_status_payload(service, session_id))
        if name == EVAL_TOOL_NEXT:
            _require_empty_arguments(arguments)
            return _next_result(service, session_id, reader, max_image_bytes=max_image_bytes)
        if name == EVAL_TOOL_SUBMIT:
            lease_id, segments = _submit_arguments(arguments)
            return _submit_result(
                service,
                session_id,
                lease_id,
                segments,
                max_result_bytes=max_result_bytes,
            )
        return _error_result("UNSUPPORTED_TOOL")
    except RemoteEvalError as exc:
        return _error_result(exc.code, str(exc) or exc.code)
    except Exception:
        return _error_result(ERROR_INTERNAL_FAIL_CLOSED, "internal failure")


def _create_eval_server(
    *,
    service: RemoteEvalService,
    store: RemoteEvalStore,
    raster_reader: GsqsEvalRasterReader,
    enabled: bool,
    oauth_scopes: frozenset[str],
    max_image_bytes: int,
    max_result_bytes: int,
    call_timeout_seconds: float,
) -> Server[object]:
    published = {tool.name for tool in gsqs_eval_tools(oauth_scopes=oauth_scopes)}
    call_slots = asyncio.Semaphore(MAX_CONCURRENT_CALLS)

    def _principal(context: ServerRequestContext[object]) -> GsqsEvalPrincipal | None:
        request = context.request
        if request is None:
            return None
        resolved = request.scope.get("state", {}).get("gsqs_eval_principal")
        return resolved if resolved is not None else None

    async def _list_tools(
        context: ServerRequestContext[object], params: ListToolsParams | None
    ) -> ListToolsResult:
        _ = params
        if not enabled or _principal(context) is None:
            return ListToolsResult(tools=[])
        return ListToolsResult(tools=list(gsqs_eval_tools(oauth_scopes=oauth_scopes)))

    async def _call_tool(
        context: ServerRequestContext[object], params: CallToolRequestParams
    ) -> CallToolResult:
        principal = _principal(context)
        if not enabled or principal is None or params.name not in published:
            return _error_result("UNSUPPORTED_TOOL")
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(call_slots.acquire(), timeout=call_timeout_seconds)
        except TimeoutError:
            return _error_result(ERROR_INTERNAL_FAIL_CLOSED)

        def _execute_tool() -> tuple[CallToolResult, GsqsDisclosureAttempt | None]:
            token = gsqs_eval_disclosure_attempt.set(None)
            try:
                result = invoke_gsqs_eval_tool(
                    params.name,
                    params.arguments,
                    principal=principal,
                    service=service,
                    store=store,
                    raster_reader=raster_reader,
                    max_image_bytes=max_image_bytes,
                    max_result_bytes=max_result_bytes,
                )
                return result, gsqs_eval_disclosure_attempt.get()
            finally:
                gsqs_eval_disclosure_attempt.reset(token)

        future = loop.run_in_executor(None, _execute_tool)
        release_here = True
        try:
            try:
                result, attempt = await asyncio.wait_for(
                    asyncio.shield(future), timeout=call_timeout_seconds
                )
            except TimeoutError:
                release_here = False
                future.add_done_callback(
                    lambda _done: loop.call_soon_threadsafe(call_slots.release)
                )
                return _error_result(ERROR_INTERNAL_FAIL_CLOSED)
        finally:
            if release_here:
                call_slots.release()
        if attempt is not None:
            gsqs_eval_disclosure_attempt.set(attempt)
            request = context.request
            if request is not None:
                request.scope.setdefault("state", {})["gsqs_eval_disclosure_attempt"] = attempt
        return result

    return Server(
        SERVER_NAME,
        version=__version__,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )


class _EvalMcpEndpoint:
    """Authenticate from the Authorization header, then hand off to the SDK manager."""

    def __init__(
        self,
        manager: StreamableHTTPSessionManager,
        authenticator: GsqsEvalAuthenticator,
        resource: str,
        slots: asyncio.Semaphore,
        auth_slots: asyncio.Semaphore,
        timeout_seconds: float,
        enabled: bool,
        service: RemoteEvalService,
        scopes: frozenset[str],
    ) -> None:
        self.manager = manager
        self.authenticator = authenticator
        self.resource = resource
        self.slots = slots
        self.auth_slots = auth_slots
        self.timeout_seconds = timeout_seconds
        self.enabled = enabled
        self.service = service
        self.scopes = scopes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled:
            response = JSONResponse({"error": "not_found"}, status_code=404)
            await response(scope, receive, send)
            return
        headers = dict(scope.get("headers", ()))
        raw = headers.get(b"authorization")
        authorization = None if raw is None else raw.decode("latin-1")
        token = gsqs_eval_disclosure_attempt.set(None)
        try:
            await asyncio.wait_for(self.auth_slots.acquire(), timeout=self.timeout_seconds)
            authentication = asyncio.create_task(
                asyncio.to_thread(self.authenticator.authenticate, authorization)
            )
            try:
                principal = await asyncio.wait_for(
                    asyncio.shield(authentication), timeout=self.timeout_seconds
                )
            except TimeoutError:
                authentication.add_done_callback(lambda _task: self.auth_slots.release())
                raise
            except asyncio.CancelledError:
                authentication.add_done_callback(lambda _task: self.auth_slots.release())
                raise
            except Exception as exc:
                self.auth_slots.release()
                thread_exc = authentication.exception() if authentication.done() else None
                refusal = thread_exc if thread_exc is not None else exc
                response = _authentication_challenge(self.resource, refusal, self.scopes)
                await response(scope, receive, send)
                return
            else:
                self.auth_slots.release()
            async with asyncio.timeout(self.timeout_seconds), self.slots:
                state = scope.setdefault("state", {})
                state["gsqs_eval_principal"] = principal
                wrapped = wrap_eval_asgi_send(send, service=self.service, attempt_holder=state)
                try:
                    await self.manager.handle_request(scope, receive, wrapped)
                finally:
                    closer = getattr(wrapped, "finalize", None)
                    if callable(closer):
                        closer()
        except TimeoutError:
            response = JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
            await response(scope, receive, send)
        finally:
            gsqs_eval_disclosure_attempt.reset(token)


def create_gsqs_remote_eval_app(
    authenticator: GsqsEvalAuthenticator,
    service: RemoteEvalService | None = None,
    *,
    enabled: bool = False,
    allowed_hosts: tuple[str, ...],
    allowed_origins: tuple[str, ...] = (),
    resource: str = DEFAULT_EVAL_RESOURCE,
    authorization_servers: tuple[str, ...] = (),
    scopes: frozenset[str] = frozenset({EVAL_OAUTH_SCOPE}),
    max_image_bytes: int = MAX_IMAGE_BYTES,
    max_result_bytes: int = MAX_RESULT_BYTES,
    readiness: Callable[[], bool] = lambda: True,
    store: RemoteEvalStore | None = None,
    raster_reader: GsqsEvalRasterReader | None = None,
    call_timeout_seconds: float = 30.0,
) -> Starlette:
    """Compose ``/mcp`` for the isolated eval process.

    Host/Origin are parameterized; Worker F will pass Settings. Wildcard
    origins are refused. Concurrent MCP calls are fixed at 1.
    """

    if not allowed_hosts:
        raise ValueError("at least one exact allowed host is required")
    if any(origin == "*" for origin in allowed_origins):
        raise ValueError("wildcard origins are not allowed")
    if max_image_bytes <= 0 or max_result_bytes <= 0:
        raise ValueError("size limits must be positive")
    if call_timeout_seconds <= 0:
        raise ValueError("call_timeout_seconds must be positive")

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def ready(_request: Request) -> JSONResponse:
        try:
            is_ready = enabled and readiness()
        except Exception:
            is_ready = False
        return JSONResponse(
            {"status": "ready" if is_ready else "unavailable"},
            status_code=200 if is_ready else 503,
        )

    async def protected_resource(_request: Request) -> JSONResponse:
        return JSONResponse(
            {
                "resource": resource,
                "authorization_servers": list(authorization_servers),
                "bearer_methods_supported": ["header"],
                "scopes_supported": sorted(scopes),
            }
        )

    metadata_path = "/.well-known/oauth-protected-resource"
    routes: list[Route] = [
        Route(HEALTH_PATH, health, methods=["GET"]),
        Route(READINESS_PATH, ready, methods=["GET"]),
        Route(metadata_path, protected_resource, methods=["GET"]),
        Route(f"{metadata_path}/mcp", protected_resource, methods=["GET"]),
    ]

    if not enabled:

        async def disabled_mcp(_request: Request) -> JSONResponse:
            return JSONResponse({"error": "not_found"}, status_code=404)

        routes.insert(0, Route(MCP_PATH, disabled_mcp, methods=["GET", "POST", "DELETE"]))
        return Starlette(routes=routes)

    if service is None:
        raise ValueError("enabled eval MCP requires a RemoteEvalService")
    resolved_store = _store_of(service, store)
    reader = raster_reader or FilesystemStagedPngReader(
        resolved_store, max_image_bytes=max_image_bytes
    )
    server = _create_eval_server(
        service=service,
        store=resolved_store,
        raster_reader=reader,
        enabled=True,
        oauth_scopes=scopes,
        max_image_bytes=max_image_bytes,
        max_result_bytes=max_result_bytes,
        call_timeout_seconds=call_timeout_seconds,
    )
    manager = StreamableHTTPSessionManager(
        app=server,
        json_response=True,
        stateless=True,
        security_settings=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=list(allowed_hosts),
            allowed_origins=list(allowed_origins),
        ),
        max_request_body_size=MAX_REQUEST_BYTES,
    )
    request_slots = asyncio.Semaphore(MAX_CONCURRENT_CALLS)
    authentication_slots = asyncio.Semaphore(MAX_CONCURRENT_CALLS)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            yield

    routes.insert(
        0,
        Route(
            MCP_PATH,
            _EvalMcpEndpoint(
                manager,
                authenticator,
                resource,
                request_slots,
                authentication_slots,
                call_timeout_seconds,
                True,
                service,
                scopes,
            ),
            methods=["GET", "POST", "DELETE"],
        ),
    )
    return Starlette(routes=routes, lifespan=lifespan)
