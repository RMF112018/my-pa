"""Dedicated Streamable HTTP MCP surface for GSQS ChatLLM remote evaluation.

This process is not production MCP. It does not import the production tool
registry, does not compose ``ApplicationService``, and does not serve
``goodnotes.propose`` / ``goodnotes.work`` / ``goodnotes.content``. Protocol
connection state is not evaluation state; evaluation state is Phase A
``RemoteEvalService``.

Worker E will wrap ASGI ``send`` via ``wrap_eval_asgi_send`` and read the
``gsqs_eval_disclosure_attempt`` ContextVar. This module records
``OUTBOUND_ATTEMPT_STARTED`` before returning ``ImageContent`` and does **not**
record ``DISCLOSED_TO_TRANSPORT``.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
from collections.abc import AsyncIterator, Callable, Mapping, Sequence
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
    ERROR_FORBIDDEN_SCOPE,
    ERROR_INTERNAL_FAIL_CLOSED,
    ERROR_NO_ACTIVE_SESSION,
    ERROR_RASTER_INTEGRITY_FAILURE,
    ERROR_RESULT_TOO_LARGE,
    ERROR_UNAUTHENTICATED,
    RemoteEvalError,
    RemoteEvalStore,
)
from my_pa.application.goodnotes_gsqs_remote_eval_storage import (
    reject_symlink,
    session_directory,
)
from my_pa.domain.common.time import format_rfc3339

__all__ = [
    "CANONICAL_PUBLIC_HOST",
    "DEFAULT_PORT",
    "EVAL_SERVER_NAME",
    "EVAL_TOOL_NEXT",
    "EVAL_TOOL_STATUS",
    "EVAL_TOOL_SUBMIT",
    "MAX_CONCURRENT_EVAL_CALLS",
    "MAX_EVAL_RESULT_BYTES",
    "MAX_IMAGE_BYTES",
    "MCP_PATH",
    "FilesystemStagedPngReader",
    "GsqsEvalAuthenticator",
    "GsqsEvalPrincipal",
    "GsqsEvalRasterReader",
    "create_gsqs_remote_eval_app",
    "gsqs_eval_disclosure_attempt",
    "gsqs_eval_tools",
    "invoke_gsqs_eval_tool",
    "png_image_content",
    "wrap_eval_asgi_send",
]

EVAL_SERVER_NAME: Final = "my-pa-gsqs-remote-eval"
MCP_PATH: Final = "/mcp"
HEALTH_PATH: Final = "/healthz"
DEFAULT_PORT: Final = 8767
CANONICAL_PUBLIC_HOST: Final = "my-pa-gsqs.bobby-fetting.me"
MAX_CONCURRENT_EVAL_CALLS: Final = 1
MAX_IMAGE_BYTES: Final = 8_388_608
MAX_EVAL_RESULT_BYTES: Final = 1_048_576
PNG_MIME: Final = "image/png"
PNG_MAGIC: Final = b"\x89PNG\r\n\x1a\n"
PUBLIC_STATUS_SCHEMA: Final = "gsqs-remote-eval-public-status-v1"
PUBLIC_NEXT_SCHEMA: Final = "gsqs-remote-eval-public-next-v1"
PUBLIC_SUBMIT_SCHEMA: Final = "gsqs-remote-eval-public-submit-v1"

EVAL_TOOL_STATUS: Final = "goodnotes.eval.status"
EVAL_TOOL_NEXT: Final = "goodnotes.eval.next"
EVAL_TOOL_SUBMIT: Final = "goodnotes.eval.submit"

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
_FORBIDDEN_CLIENT_KEYS: Final = frozenset(
    {
        "session_id",
        "case_id",
        "repetition",
        "content_sha256",
        "corpus",
        "evaluator",
        "prompt",
        "model",
        "score",
        "expected",
        "principal_id",
    }
)

# Worker E reads this ContextVar from wrap_eval_asgi_send. Name:
# ``gsqs_eval_disclosure_attempt``. It holds the disclosure
# ``request_attempt_id`` after ``RemoteEvalService.record_outbound_attempt``
# (durable OUTBOUND_ATTEMPT_STARTED) and before ImageContent is returned to the
# MCP layer. Tool return is not transport completion.
gsqs_eval_disclosure_attempt: ContextVar[str | None] = ContextVar(
    "gsqs_eval_disclosure_attempt",
    default=None,
)


class GsqsEvalPrincipal(Protocol):
    principal_id: str


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


def wrap_eval_asgi_send(
    send: Send,
    *,
    disclosure_journal: object,
    attempt_getter: Callable[[], str | None],
) -> Send:
    """Identity wrapper for now. Worker E will implement send-boundary disclosure.

    Do not record DISCLOSED_TO_TRANSPORT here in Worker D.
    """

    _ = (disclosure_journal, attempt_getter)
    return send


def gsqs_eval_tools() -> tuple[Tool, ...]:
    """The three public remote-eval tools. Not the production registry."""

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
        ),
        Tool(
            name=EVAL_TOOL_SUBMIT,
            description="Submit note-unit.v2 segments for the outstanding lease.",
            input_schema=dict(_SUBMIT_INPUT_SCHEMA),
            annotations=ToolAnnotations(
                read_only_hint=False,
                destructive_hint=False,
                open_world_hint=False,
            ),
        ),
    )


def png_image_content(payload: bytes) -> ImageContent:
    """Native MCP ImageContent from PNG bytes. Never a URL, data URI, or path."""

    return ImageContent(
        type="image",
        data=base64.b64encode(payload).decode("ascii"),
        mime_type=PNG_MIME,
    )


def _payload(document: object) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=True)


def _error_result(code: str) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=_payload({"error": code}))],
        is_error=True,
    )


def _success_result(
    document: Mapping[str, object], image: ImageContent | None = None
) -> CallToolResult:
    blocks: list[ContentBlock] = [TextContent(type="text", text=_payload(document))]
    if image is not None:
        blocks.append(image)
    return CallToolResult(content=blocks, is_error=False)


def _default_bind(principal_id: str, session_principal_id: str) -> None:
    if principal_id != session_principal_id:
        raise RemoteEvalError(ERROR_FORBIDDEN_SCOPE, "principal does not match session")


def _require_empty_arguments(arguments: Mapping[str, object] | None) -> None:
    if arguments:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "unexpected tool arguments")


def _submit_arguments(arguments: Mapping[str, object] | None) -> tuple[str, Sequence[object]]:
    document = {} if arguments is None else dict(arguments)
    extra = set(document) - _SUBMIT_KEYS
    if extra or (set(document) & _FORBIDDEN_CLIENT_KEYS):
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "unexpected tool arguments")
    lease_id = document.get("lease_id")
    segments = document.get("segments")
    if not isinstance(lease_id, str) or not lease_id:
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "lease_id is required")
    if not isinstance(segments, list):
        raise RemoteEvalError(ERROR_INTERNAL_FAIL_CLOSED, "segments are required")
    return lease_id, segments


def _resolve_bound_session(
    store: RemoteEvalStore,
    principal: GsqsEvalPrincipal,
    bind_principal: Callable[[str, str], None],
) -> str:
    session_id = store.find_non_terminal_session_id()
    if session_id is None:
        raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "no active session")
    session = store.load_session(session_id)
    if session is None:
        raise RemoteEvalError(ERROR_NO_ACTIVE_SESSION, "no active session")
    bind_principal(principal.principal_id, session.principal_id)
    return session.session_id


def invoke_gsqs_eval_tool(
    name: str,
    arguments: Mapping[str, object] | None,
    *,
    principal: GsqsEvalPrincipal,
    service: RemoteEvalService,
    store: RemoteEvalStore,
    raster_reader: GsqsEvalRasterReader,
    max_image_bytes: int = MAX_IMAGE_BYTES,
    max_result_bytes: int = MAX_EVAL_RESULT_BYTES,
    bind_principal: Callable[[str, str], None] | None = None,
) -> CallToolResult:
    """Synchronous tool body. Session identity is never taken from tool JSON."""

    binder = _default_bind if bind_principal is None else bind_principal
    try:
        session_id = _resolve_bound_session(store, principal, binder)
        if name == EVAL_TOOL_STATUS:
            _require_empty_arguments(arguments)
            return _status(service, session_id)
        if name == EVAL_TOOL_NEXT:
            _require_empty_arguments(arguments)
            return _next_case(
                service,
                session_id,
                raster_reader,
                max_image_bytes=max_image_bytes,
            )
        if name == EVAL_TOOL_SUBMIT:
            lease_id, segments = _submit_arguments(arguments)
            return _submit(
                service,
                session_id,
                lease_id,
                segments,
                max_result_bytes=max_result_bytes,
            )
        return _error_result("UNSUPPORTED_TOOL")
    except RemoteEvalError as exc:
        return _error_result(exc.code)
    except Exception:
        return _error_result(ERROR_INTERNAL_FAIL_CLOSED)


def _status(service: RemoteEvalService, session_id: str) -> CallToolResult:
    status = service.status(session_id)
    return _success_result(
        {
            "schema_version": PUBLIC_STATUS_SCHEMA,
            "state": status.state.value,
            "repetition": status.active_repetition,
            "repetitions_required": status.repetitions_required,
            "next_case_ordinal": status.next_case_ordinal,
            "cases_per_repetition": status.case_count,
            "expires_at": format_rfc3339(status.expires_at),
            "session_identity_sha256": status.session_identity_sha256,
        }
    )


def _next_case(
    service: RemoteEvalService,
    session_id: str,
    raster_reader: GsqsEvalRasterReader,
    *,
    max_image_bytes: int,
) -> CallToolResult:
    acquired = service.acquire_case(session_id)
    if acquired.byte_length > max_image_bytes or acquired.byte_length < 1:
        raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "raster exceeds max image bytes")
    payload = raster_reader.read_png(
        session_id=session_id,
        staged_filename=acquired.staged_filename,
        content_sha256=acquired.content_sha256,
        byte_length=acquired.byte_length,
    )
    if len(payload) > max_image_bytes:
        raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "raster exceeds max image bytes")
    if len(payload) != acquired.byte_length:
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster length mismatch")
    if sha256(payload).hexdigest() != acquired.content_sha256:
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster digest mismatch")
    if not payload.startswith(PNG_MAGIC):
        raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster is not a PNG")
    attempt_id = service.record_outbound_attempt(
        session_id,
        repetition=acquired.repetition,
        case_id=acquired.case_id,
    )
    gsqs_eval_disclosure_attempt.set(attempt_id)
    return _success_result(
        {
            "schema_version": PUBLIC_NEXT_SCHEMA,
            "repetition": acquired.repetition,
            "ordinal": acquired.ordinal,
            "lease_id": acquired.lease.lease_id,
            "lease_expires_at": format_rfc3339(acquired.lease.expires_at),
            "content_sha256": acquired.content_sha256,
            "mime_type": PNG_MIME,
            "byte_length": len(payload),
        },
        png_image_content(payload),
    )


def _submit(
    service: RemoteEvalService,
    session_id: str,
    lease_id: str,
    segments: Sequence[object],
    *,
    max_result_bytes: int,
) -> CallToolResult:
    encoded = json.dumps(segments, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    if len(encoded) > max_result_bytes:
        raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "result exceeds max result bytes")
    receipt = service.submit_capture(session_id, lease_id, segments)
    return _success_result(
        {
            "schema_version": PUBLIC_SUBMIT_SCHEMA,
            "repetition": receipt.repetition,
            "ordinal": receipt.ordinal,
            "capture_identity_sha256": receipt.capture_identity_sha256,
            "duplicate": receipt.duplicate,
            "state": receipt.state.value,
        }
    )


class FilesystemStagedPngReader:
    """Read a sealed staged PNG under an explicit state root. No source paths."""

    def __init__(self, state_root: Path, *, max_image_bytes: int = MAX_IMAGE_BYTES) -> None:
        self._state_root = Path(state_root)
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
            raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "raster exceeds max image bytes")
        if (
            not staged_filename
            or "/" in staged_filename
            or "\\" in staged_filename
            or ".." in staged_filename
            or staged_filename != Path(staged_filename).name
        ):
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "staged raster is invalid")
        rasters = session_directory(self._state_root, session_id) / "rasters"
        reject_symlink(rasters, what="rasters directory")
        path = rasters / staged_filename
        reject_symlink(path, what="staged raster")
        if not path.is_file():
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "staged raster is missing")
        flags = os.O_RDONLY
        if hasattr(os, "O_NOFOLLOW"):
            flags |= os.O_NOFOLLOW
        descriptor = os.open(path, flags)
        try:
            if os.fstat(descriptor).st_size > self._max_image_bytes:
                raise RemoteEvalError(ERROR_RESULT_TOO_LARGE, "raster exceeds max image bytes")
            payload = os.read(descriptor, byte_length + 1)
        finally:
            os.close(descriptor)
        if len(payload) != byte_length:
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster length mismatch")
        if sha256(payload).hexdigest() != content_sha256:
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster digest mismatch")
        if not payload.startswith(PNG_MAGIC):
            raise RemoteEvalError(ERROR_RASTER_INTEGRITY_FAILURE, "raster is not a PNG")
        return payload


def _create_eval_mcp_server(
    *,
    service: RemoteEvalService,
    store: RemoteEvalStore,
    raster_reader: GsqsEvalRasterReader,
    max_image_bytes: int,
    max_result_bytes: int,
    bind_principal: Callable[[str, str], None] | None,
    call_timeout_seconds: float,
) -> Server[object]:
    published = {tool.name for tool in gsqs_eval_tools()}
    call_slots = asyncio.Semaphore(MAX_CONCURRENT_EVAL_CALLS)

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
        if _principal(context) is None:
            return ListToolsResult(tools=[])
        return ListToolsResult(tools=list(gsqs_eval_tools()))

    async def _call_tool(
        context: ServerRequestContext[object], params: CallToolRequestParams
    ) -> CallToolResult:
        principal = _principal(context)
        if principal is None or params.name not in published:
            return _error_result("UNSUPPORTED_TOOL")
        loop = asyncio.get_running_loop()
        try:
            await asyncio.wait_for(call_slots.acquire(), timeout=call_timeout_seconds)
        except TimeoutError:
            return _error_result(ERROR_INTERNAL_FAIL_CLOSED)

        def _run() -> tuple[CallToolResult, str | None]:
            worker_token = gsqs_eval_disclosure_attempt.set(None)
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
                    bind_principal=bind_principal,
                )
                return result, gsqs_eval_disclosure_attempt.get()
            finally:
                gsqs_eval_disclosure_attempt.reset(worker_token)

        future = loop.run_in_executor(None, _run)
        release_here = True
        result: CallToolResult | None = None
        attempt_id: str | None = None
        try:
            try:
                result, attempt_id = await asyncio.wait_for(
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
        if attempt_id is not None:
            gsqs_eval_disclosure_attempt.set(attempt_id)
        if result is None:
            return _error_result(ERROR_INTERNAL_FAIL_CLOSED)
        return result

    return Server(
        EVAL_SERVER_NAME,
        version=__version__,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )


class _EvalMcpEndpoint:
    """Authenticate independently, then hand the request to the SDK manager."""

    def __init__(
        self,
        manager: StreamableHTTPSessionManager,
        authenticator: GsqsEvalAuthenticator,
        slots: asyncio.Semaphore,
        auth_slots: asyncio.Semaphore,
        timeout_seconds: float,
        disclosure_journal: object,
    ) -> None:
        self.manager = manager
        self.authenticator = authenticator
        self.slots = slots
        self.auth_slots = auth_slots
        self.timeout_seconds = timeout_seconds
        self.disclosure_journal = disclosure_journal

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
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
            except RemoteEvalError as exc:
                self.auth_slots.release()
                status = 401 if exc.code == ERROR_UNAUTHENTICATED else 403
                if exc.code not in {ERROR_UNAUTHENTICATED, ERROR_FORBIDDEN_SCOPE}:
                    status = 401
                response = JSONResponse({"error": exc.code}, status_code=status)
                await response(scope, receive, send)
                return
            except Exception:
                self.auth_slots.release()
                response = JSONResponse({"error": ERROR_UNAUTHENTICATED}, status_code=401)
                await response(scope, receive, send)
                return
            else:
                self.auth_slots.release()
            async with asyncio.timeout(self.timeout_seconds), self.slots:
                scope.setdefault("state", {})["gsqs_eval_principal"] = principal
                wrapped = wrap_eval_asgi_send(
                    send,
                    disclosure_journal=self.disclosure_journal,
                    attempt_getter=gsqs_eval_disclosure_attempt.get,
                )
                await self.manager.handle_request(scope, receive, wrapped)
        except TimeoutError:
            response = JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
            await response(scope, receive, send)
        finally:
            gsqs_eval_disclosure_attempt.reset(token)


def create_gsqs_remote_eval_app(
    *,
    authenticator: GsqsEvalAuthenticator,
    service: RemoteEvalService | None,
    store: RemoteEvalStore | None,
    raster_reader: GsqsEvalRasterReader | None,
    allowed_hosts: tuple[str, ...],
    allowed_origins: tuple[str, ...] = (),
    enabled: bool = False,
    max_image_bytes: int = MAX_IMAGE_BYTES,
    max_result_bytes: int = MAX_EVAL_RESULT_BYTES,
    call_timeout_seconds: float = 30.0,
    bind_principal: Callable[[str, str], None] | None = None,
    disclosure_journal: object | None = None,
) -> Starlette:
    """Compose ``/mcp`` for the isolated eval process.

    Host/Origin are parameterized; Worker F will pass Settings. Canonical future
    host is ``my-pa-gsqs.bobby-fetting.me``. Wildcard origins are refused.
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

    async def disabled_mcp(_request: Request) -> JSONResponse:
        return JSONResponse({"error": "not_found"}, status_code=404)

    if not enabled:
        return Starlette(
            routes=[
                Route(MCP_PATH, disabled_mcp, methods=["GET", "POST", "DELETE"]),
                Route(HEALTH_PATH, health, methods=["GET"]),
            ]
        )
    if service is None or store is None or raster_reader is None:
        raise ValueError("enabled eval MCP requires service, store, and raster_reader")

    server = _create_eval_mcp_server(
        service=service,
        store=store,
        raster_reader=raster_reader,
        max_image_bytes=max_image_bytes,
        max_result_bytes=max_result_bytes,
        bind_principal=bind_principal,
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
    request_slots = asyncio.Semaphore(MAX_CONCURRENT_EVAL_CALLS)
    authentication_slots = asyncio.Semaphore(MAX_CONCURRENT_EVAL_CALLS)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            yield

    return Starlette(
        routes=[
            Route(
                MCP_PATH,
                _EvalMcpEndpoint(
                    manager,
                    authenticator,
                    request_slots,
                    authentication_slots,
                    call_timeout_seconds,
                    disclosure_journal,
                ),
                methods=["GET", "POST", "DELETE"],
            ),
            Route(HEALTH_PATH, health, methods=["GET"]),
        ],
        lifespan=lifespan,
    )
