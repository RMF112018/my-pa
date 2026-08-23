"""A tool call in, one `invoke`, an envelope out.

The same module as `adapters/http/app.py` in a different protocol, and
deliberately the same shape: bound the request, hand `(tool name, arguments)` to
`normalize`, call `invoke` once, and return what came back. There is no decision
here either. `tools/call(name, arguments)` maps onto `normalize(capability,
arguments)` with nothing in between, which is why `SPEC-AC-001` is a structural
claim in this repository rather than a comparison of three pipelines: all three
transports call one function, and the pair it builds is the same pair.

Remote MCP is the same path after one extra shaping step: the adapter refuses
caller-owned copies of server-owned envelope fields and then composes those
fields from authenticated context. `normalize` still builds the pair.

**The official SDK, stdio only** (`D-26`, `D-30`). `initialize`, `tools/list`,
`tools/call`, the JSON-RPC framing, and the protocol-version negotiation are the
SDK's, because they are conformance to a specification this repository does not
own and a hand-rolled copy drifts silently. No socket is opened: the SDK's
network transports are never imported here, and the composition root offers no
option to select one.

## The async boundary, and exactly where it is

`D-27` keeps `domain`, `application`, and `infrastructure` synchronous, and
before this module `grep -rn "async def|await " src apps tests` answered with
nothing. The SDK's request handlers are `Awaitable`-returning by signature, so
two `async def` functions below are the permitted edge — and they are the whole
of it:

* `_list_tools` returns a constant and awaits nothing;
* `_call_tool` awaits exactly one thing, the synchronous answer running in a
  worker thread.

`serve_stdio` is an ordinary `def`. It owns the event loop for the length of one
connection and does not hand one out, so nothing outside this package ever sees
a coroutine, an event loop, or a task. That is what "async does not leak past
`adapters/mcp`" means here, and it is checked by
`tests/architecture/test_async_stays_at_the_transport_edge.py` rather than
promised.

**Stdlib `asyncio`, not `anyio`.** `D-27` was drafted naming
`anyio.to_thread.run_sync`; WP-4B2a bridged the other direction with
`asyncio.run_coroutine_threadsafe` rather than take the dependency, and this is
the same trade in the other direction — `run_in_executor` is one line and
`AGENTS.md` section 2 admits a dependency only for what the standard library
cannot reasonably do. `asyncio.run` in `serve_stdio` is what makes it safe:
anyio runs on the backend it finds, so owning the loop is what fixes the backend
to asyncio and makes `get_running_loop` in the handler a fact rather than a
hope.

**The offload is not decoration.** The SDK dispatches each request into its own
task, so a handler that ran the synchronous application on the event loop would
stall every other request on the connection — including the client's cancel —
for the length of a database call. The default executor bounds how many run at
once, above the connection pool that bounds them again; a request beyond both
waits and then fails closed, which is the same queue the HTTP transport puts
requests in.

## What a caller receives

The `ResponseEnvelope`'s canonical JSON, verbatim, remains the canonical JSON
text block — the same bytes the HTTP transport writes as its body. When an
authorized success result matches the pinned-raster projection shape, a second
image content block is appended whose data is the same base64 string already in
that envelope. Failures and non-matching successes stay one text block.
`isError` is set from the envelope's own `error`, so the protocol's success flag
is a function of the answer rather than a second judgement about it.

A request that never became an envelope — an unknown tool, arguments that are
not a document, a payload past the transport's ceiling — has no envelope to
return, because one requires the caller's `request_id` and inventing one would
be fabricating the identity of a request that could not be read. Those answer
with the `ProblemDetail` alone, built by the same `problem_detail` the
application uses, exactly as `adapters/http/app.py` answers them.

**No credential is issued, read, or required** (`D-30`). The acting principal is
the composition root's and is a property of the process; `metadata.principal_id`
arrives from the caller and stays correlation input the application does not
trust.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import (
    CallToolRequestParams,
    CallToolResult,
    ContentBlock,
    ImageContent,
    ListToolsResult,
    TextContent,
    Tool,
)
from mcp.types import PaginatedRequestParams as ListToolsParams

from my_pa import __version__
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.adapters.remote_request import compose_remote_arguments, remote_tool_schema
from my_pa.application.errors import (
    ApplicationError,
    InternalError,
    InvalidRequestError,
    UnsupportedError,
    problem_detail,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.errors import ProblemDetail
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.common.time import utc_now
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose
from my_pa.domain.source.registry import issue_identifier

__all__ = ["SERVER_NAME", "McpAccess", "create_mcp_server", "published_tools", "serve_stdio"]

#: What this server calls itself in `initialize`. Neutral, as `AGENTS.md`
#: section 4 requires of every external and MCP name.
SERVER_NAME = "my-pa"


@dataclass(frozen=True)
class McpAccess:
    """Server-established identity and tool ceiling for one MCP request."""

    principal: Principal
    allowed_tools: frozenset[str] | None = None
    allowed_capability_purposes: frozenset[tuple[Capability, Purpose | None]] | None = None
    transport: CaptureTransport = CaptureTransport.LOCAL


def _document(arguments: Mapping[str, Any] | None) -> Mapping[str, Any]:
    """The tool call's arguments, bounded, or a refusal.

    Bounded on the encoded size rather than on a field count, and against one
    shared number rather than a second one. `MAX_REQUEST_BYTES` lives beside
    `normalize` because it is derived from the largest request the *contract*
    can express — an enrollment at its domain ceiling — so it belongs to the
    request rather than to any protocol; restating it here would be the drift
    `SPEC-AC-001` exists to prevent.

    **Where it is enforced differs, and that is not a gap this can close.** HTTP
    refuses on the declared `content-length` before it reads a byte. The SDK has
    already parsed and framed the message by the time a handler runs, so there
    is no declared length to refuse against and no point before the parse at
    which this could act. What this bounds is therefore what the *application*
    is asked to do with a document that has already arrived, and the framing
    cost of an oversized one is the SDK's to bear. Named rather than implied,
    because a reader comparing the two transports would otherwise assume the
    guarantees are identical.
    """
    document = arguments or {}
    try:
        encoded = json.dumps(document, separators=(",", ":")).encode()
    except (TypeError, ValueError):
        # A value JSON cannot re-encode did not arrive over JSON-RPC, so this is
        # a caller reaching the server in process with something the protocol
        # could not have delivered. Refused rather than measured.
        pass
    else:
        if len(encoded) <= MAX_REQUEST_BYTES:
            return document
    raise InvalidRequestError()


def _problem(error: ApplicationError) -> ProblemDetail:
    """Render a refusal this transport made, in the application's vocabulary.

    The correlation identifier is issued here because the request never reached
    the application and none exists yet. It is what an operator correlates the
    refusal by; nothing else in the answer is new.
    """
    return problem_detail(error, correlation_id=issue_identifier(IdKind.CORRELATION))


_INCONSISTENT_RASTER = object()


def _is_hex64(value: object) -> bool:
    return (
        isinstance(value, str)
        and len(value) == 64
        and not (set(value.lower()) - set("0123456789abcdef"))
    )


def _non_empty_str(value: object) -> bool:
    return isinstance(value, str) and value != ""


def _image_from_result(result: object) -> ImageContent | object | None:
    """Project a pinned-raster success result as one image block, or nothing.

    Keyword unpacking is the inspection: a request-derived mapping must not be
    subscripted. Encoded-length mismatch after the other fields match is a
    sentinel, not a silent text-only success.
    """
    if not isinstance(result, dict):
        return None
    try:
        return _image_from_mapping(**result)
    except TypeError:
        return None


def _image_from_mapping(
    *,
    media_type: object = None,
    content_base64: object = None,
    digest: object = None,
    exact_render_sha256: object = None,
    content_sha256: object = None,
    byte_length: object = None,
    run_id: object = None,
    page_version_id: object = None,
    renderer_name: object = None,
    renderer_version: object = None,
    render_profile_version: object = None,
    **_ignored: object,
) -> ImageContent | object | None:
    if media_type != "image/png":
        return None
    if not isinstance(content_base64, str) or not content_base64:
        return None
    if not (_is_hex64(digest) and _is_hex64(exact_render_sha256) and _is_hex64(content_sha256)):
        return None
    if not isinstance(byte_length, int) or isinstance(byte_length, bool) or byte_length < 1:
        return None
    if not (
        _non_empty_str(run_id)
        and _non_empty_str(page_version_id)
        and _non_empty_str(renderer_name)
        and _non_empty_str(renderer_version)
        and _non_empty_str(render_profile_version)
    ):
        return None
    if len(content_base64) != ((byte_length + 2) // 3) * 4:
        return _INCONSISTENT_RASTER
    return ImageContent(type="image", data=content_base64, mime_type="image/png")


def _result_bytes(blocks: Sequence[ContentBlock]) -> int:
    """Every content block, in the units the result-size ceiling counts."""
    total = 0
    for block in blocks:
        if isinstance(block, ImageContent):
            total += len(block.data.encode("ascii"))
        elif isinstance(block, TextContent):
            total += len(block.text.encode("utf-8"))
    return total


def _answer(
    service: ApplicationService,
    principal: Principal,
    name: str,
    arguments: Mapping[str, Any] | None,
    transport: CaptureTransport = CaptureTransport.LOCAL,
    allowed_capability_purposes: frozenset[tuple[Capability, Purpose | None]] | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> tuple[str, bool, ImageContent | None]:
    """One tool call, executed synchronously: text, failure flag, optional image.

    Runs in a worker thread. Nothing awaits inside it and nothing it calls is
    async, which is the property that keeps the boundary one function wide.

    **The terminal catch is deliberate, and it is about a log rather than a
    caller.** `ApplicationService.invoke` already refuses to raise, so what
    remains is this module's own rendering. If anything did escape, the SDK
    would answer with a generic protocol error and write `logger.exception` —
    a traceback carrying the request into whatever an operator has logging
    configured to do, which `AGENTS.md` section 5 forbids and no response-body
    assertion would ever see.
    """
    request_arguments = arguments
    if transport is CaptureTransport.REMOTE_CLIENT:
        try:
            request_arguments = compose_remote_arguments(
                capability_name=name,
                arguments=arguments or {},
                principal=principal,
                grants=allowed_capability_purposes,
                clock=clock,
            )
        except InvalidRequestError as refusal:
            return _problem(refusal).to_canonical_json(), True, None
        except UnsupportedError as refusal:
            return _problem(refusal).to_canonical_json(), True, None
    try:
        metadata, command = normalize(name, _document(request_arguments))
    except ApplicationError as refusal:
        return _problem(refusal).to_canonical_json(), True, None
    except Exception:
        return _problem(InternalError()).to_canonical_json(), True, None
    if allowed_capability_purposes is not None and not (
        (metadata.capability, None) in allowed_capability_purposes
        or (metadata.capability, metadata.purpose) in allowed_capability_purposes
    ):
        return _problem(UnsupportedError()).to_canonical_json(), True, None
    try:
        envelope = service.invoke(
            metadata,
            command,
            principal=principal,
            transport=transport,
            capability_grants=allowed_capability_purposes,
        )
    except Exception:
        return _problem(InternalError()).to_canonical_json(), True, None
    if envelope.error is not None:
        return envelope.to_canonical_json(), True, None
    projected = _image_from_result(envelope.result)
    if isinstance(projected, ImageContent):
        return envelope.to_canonical_json(), False, projected
    if projected is None:
        return envelope.to_canonical_json(), False, None
    return _problem(InternalError()).to_canonical_json(), True, None


def published_tools(service: ApplicationService) -> tuple[Tool, ...]:
    """The tools this *composed* process can actually serve.

    `TOOLS` is derived from the capability set at import and is what the build
    implements. This is what the running process can serve, which is smaller
    whenever a capability needs something the composition root did not supply —
    today, the `documents.` names in a process with no managed root. The filter
    reads `ApplicationService.available_capabilities` and decides nothing:
    publishing a tool a caller is then refused for would make `tools/list` a
    second, wrong statement of the capability set, which is exactly what
    `adapters/mcp/tools.py` exists to prevent.

    Not a policy filter, and it must not become one. Which purposes may invoke a
    capability, and whether it is operator-only, stay behind `invoke`; this reads
    only whether the process was composed with what the capability needs.
    """
    available = {capability.value for capability in service.available_capabilities}
    return tuple(tool for tool in TOOLS if tool.name in available)


def _remote_tool(tool: Tool, *, oauth_scopes: frozenset[str]) -> Tool:
    """Remote schema and OAuth metadata over the canonical tool contract."""
    schema = remote_tool_schema(tool.input_schema)
    meta = dict(tool.meta or {})
    # `mcp==2.0` carries extension metadata through `_meta`. OpenAI clients use
    # this declaration with protected-resource discovery; it is descriptive
    # only, while bearer, scope, grant, and capability enforcement remain at
    # the origin and application boundaries.
    meta["securitySchemes"] = [{"type": "oauth2", "scopes": sorted(oauth_scopes)}]
    return tool.model_copy(update={"inputSchema": schema, "input_schema": schema, "meta": meta})


def create_mcp_server(
    service: ApplicationService,
    *,
    principal: Principal | None = None,
    enabled: bool = True,
    access_for_request: Callable[[ServerRequestContext[object]], McpAccess | None] | None = None,
    oauth_scopes: frozenset[str] = frozenset(),
    max_concurrent_calls: int | None = None,
    call_timeout_seconds: float | None = None,
    max_result_bytes: int | None = None,
    clock: Callable[[], datetime] = utc_now,
) -> Server[object]:
    """The MCP server serving `service` as the one local `principal`.

    `principal` is the authenticated context the composition root established
    and is fixed for the life of the process, because the process is what the
    trust boundary is: one local operator behind a pipe (`D-30`).

    **`enabled` is the kill switch, and it kills both halves.** A surface that
    only stopped publishing tools would still answer `tools/call` for a name a
    client already knew, and a client that has spoken to this server before knows
    every one of them. So `tools/list` publishes nothing *and* `tools/call` is
    refused before the service is reached — the refusal is built here, from the
    application's own error vocabulary, and no `invoke` happens.

    The switch is composed rather than read here: `bootstrap.gateway` decides,
    from `MY_PA_MCP_SURFACE_DISABLED` and from whether the bound client is still
    usable. This module holds a boolean and no configuration.
    """

    if principal is None and access_for_request is None:
        raise ValueError("principal or access_for_request is required")
    if max_concurrent_calls is not None and max_concurrent_calls <= 0:
        raise ValueError("max_concurrent_calls must be positive")
    if call_timeout_seconds is not None and call_timeout_seconds <= 0:
        raise ValueError("call_timeout_seconds must be positive")
    if max_result_bytes is not None and max_result_bytes <= 0:
        raise ValueError("max_result_bytes must be positive")
    call_slots = asyncio.Semaphore(max_concurrent_calls or 1)

    def _access(context: ServerRequestContext[object]) -> McpAccess | None:
        if access_for_request is not None:
            try:
                return access_for_request(context)
            except Exception:
                return None
        return McpAccess(principal) if principal is not None else None

    async def _list_tools(
        context: ServerRequestContext[object], params: ListToolsParams | None
    ) -> ListToolsResult:
        """`tools/list`. Derived; see `adapters/mcp/tools.py`."""
        access = _access(context)
        if not enabled or access is None:
            return ListToolsResult(tools=[])
        tools = published_tools(service)
        if access.allowed_tools is not None:
            tools = tuple(tool for tool in tools if tool.name in access.allowed_tools)
        if access.transport is CaptureTransport.REMOTE_CLIENT:
            tools = tuple(_remote_tool(tool, oauth_scopes=oauth_scopes) for tool in tools)
        return ListToolsResult(tools=list(tools))

    async def _call_tool(
        context: ServerRequestContext[object], params: CallToolRequestParams
    ) -> CallToolResult:
        """`tools/call`. The one `await` in this package."""
        access = _access(context)
        published = {tool.name for tool in published_tools(service)}
        remote_refusal = access_for_request is not None and (
            params.name not in published
            or (
                access is not None
                and access.allowed_tools is not None
                and params.name not in access.allowed_tools
            )
        )
        if not enabled or access is None or remote_refusal:
            # No thread, no service, no envelope. There is no request identity to
            # build one from and nothing to correlate a disabled surface against
            # beyond the refusal itself.
            return CallToolResult(
                content=[
                    TextContent(type="text", text=_problem(UnsupportedError()).to_canonical_json())
                ],
                is_error=True,
            )
        loop = asyncio.get_running_loop()
        awaitable = call_slots.acquire()
        if call_timeout_seconds is None:
            await awaitable
        else:
            try:
                await asyncio.wait_for(awaitable, timeout=call_timeout_seconds)
            except TimeoutError:
                return CallToolResult(
                    content=[
                        TextContent(type="text", text=_problem(InternalError()).to_canonical_json())
                    ],
                    is_error=True,
                )
        future = loop.run_in_executor(
            None,
            _answer,
            service,
            access.principal,
            params.name,
            params.arguments,
            access.transport,
            access.allowed_capability_purposes,
            clock,
        )
        release_here = True
        try:
            if call_timeout_seconds is None:
                text, failed, image = await future
            else:
                try:
                    text, failed, image = await asyncio.wait_for(
                        asyncio.shield(future), timeout=call_timeout_seconds
                    )
                except TimeoutError:
                    # A Python worker thread cannot be cancelled safely. Keep its
                    # slot occupied until it really exits, while refusing the
                    # caller at the configured deadline.
                    release_here = False
                    future.add_done_callback(
                        lambda _done: loop.call_soon_threadsafe(call_slots.release)
                    )
                    return CallToolResult(
                        content=[
                            TextContent(
                                type="text", text=_problem(InternalError()).to_canonical_json()
                            )
                        ],
                        is_error=True,
                    )
        finally:
            if release_here:
                call_slots.release()
        content: list[ContentBlock] = [TextContent(type="text", text=text)]
        if not failed and image is not None:
            content.append(image)
        if max_result_bytes is not None and _result_bytes(content) > max_result_bytes:
            text, failed = _problem(InternalError()).to_canonical_json(), True
            content = [TextContent(type="text", text=text)]
        return CallToolResult(content=content, is_error=failed)

    return Server(
        SERVER_NAME,
        version=__version__,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )


async def _serve(server: Server[object]) -> None:
    """One stdio connection, until the client closes the read side."""
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def serve_stdio(
    service: ApplicationService,
    *,
    principal: Principal,
    enabled: bool = True,
    allowed_tools: frozenset[str] | None = None,
    allowed_capability_purposes: frozenset[tuple[Capability, Purpose | None]] | None = None,
) -> None:
    """Serve `service` over standard input and output until the client goes away.

    Synchronous, and that is the boundary: this owns an event loop for the
    length of one connection and returns an ordinary `None`. A caller composes
    it and calls it like any other function.

    **Standard output is the wire.** Anything else written there corrupts the
    protocol stream, which is why the composition root sends its startup notice
    to standard error and why nothing in the application prints.

    `allowed_tools` is an optional ceiling. When set, unpublished and
    out-of-ceiling names are refused before `invoke`, which is how the GSQS B0
    evaluation surface withholds `goodnotes.propose`.
    """
    access_for_request = None
    if allowed_tools is not None or allowed_capability_purposes is not None:
        access = McpAccess(
            principal,
            allowed_tools=allowed_tools,
            allowed_capability_purposes=allowed_capability_purposes,
        )

        def _access(_context: ServerRequestContext[object]) -> McpAccess:
            return access

        access_for_request = _access
    asyncio.run(
        _serve(
            create_mcp_server(
                service,
                principal=principal,
                enabled=enabled,
                access_for_request=access_for_request,
            )
        )
    )
