"""A tool call in, one `invoke`, an envelope out.

The same module as `adapters/http/app.py` in a different protocol, and
deliberately the same shape: bound the request, hand `(tool name, arguments)` to
`normalize`, call `invoke` once, and return what came back. There is no decision
here either. `tools/call(name, arguments)` maps onto `normalize(capability,
arguments)` with nothing in between, which is why `SPEC-AC-001` is a structural
claim in this repository rather than a comparison of three pipelines: all three
transports call one function, and the pair it builds is the same pair.

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

The `ResponseEnvelope`'s canonical JSON, verbatim, as one text content block —
the same bytes the HTTP transport writes as its body. `isError` is set from the
envelope's own `error`, so the protocol's success flag is a function of the
answer rather than a second judgement about it.

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
from collections.abc import Mapping
from typing import Any

from mcp.server.context import ServerRequestContext
from mcp.server.lowlevel import Server
from mcp.server.stdio import stdio_server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent
from mcp.types import PaginatedRequestParams as ListToolsParams

from my_pa import __version__
from my_pa.adapters.mcp.tools import TOOLS
from my_pa.adapters.normalization import MAX_REQUEST_BYTES, normalize
from my_pa.application.errors import (
    ApplicationError,
    InternalError,
    InvalidRequestError,
    problem_detail,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.v1.errors import ProblemDetail
from my_pa.domain.common.identifiers import IdKind
from my_pa.domain.identity.principal import Principal
from my_pa.domain.source.registry import issue_identifier

__all__ = ["SERVER_NAME", "create_mcp_server", "serve_stdio"]

#: What this server calls itself in `initialize`. Neutral, as `AGENTS.md`
#: section 4 requires of every external and MCP name.
SERVER_NAME = "my-pa"


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


def _answer(
    service: ApplicationService,
    principal: Principal,
    name: str,
    arguments: Mapping[str, Any] | None,
) -> tuple[str, bool]:
    """One tool call, executed synchronously: the text to return and whether it failed.

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
    try:
        metadata, command = normalize(name, _document(arguments))
    except ApplicationError as refusal:
        return _problem(refusal).to_canonical_json(), True
    except Exception:
        return _problem(InternalError()).to_canonical_json(), True
    try:
        envelope = service.invoke(metadata, command, principal=principal)
    except Exception:
        return _problem(InternalError()).to_canonical_json(), True
    return envelope.to_canonical_json(), envelope.error is not None


def create_mcp_server(service: ApplicationService, *, principal: Principal) -> Server[object]:
    """The MCP server serving `service` as the one local `principal`.

    `principal` is the authenticated context the composition root established
    and is fixed for the life of the process, because the process is what the
    trust boundary is: one local operator behind a pipe (`D-30`).
    """

    async def _list_tools(
        context: ServerRequestContext[object], params: ListToolsParams | None
    ) -> ListToolsResult:
        """`tools/list`. Derived; see `adapters/mcp/tools.py`."""
        return ListToolsResult(tools=list(TOOLS))

    async def _call_tool(
        context: ServerRequestContext[object], params: CallToolRequestParams
    ) -> CallToolResult:
        """`tools/call`. The one `await` in this package."""
        loop = asyncio.get_running_loop()
        text, failed = await loop.run_in_executor(
            None, _answer, service, principal, params.name, params.arguments
        )
        return CallToolResult(content=[TextContent(type="text", text=text)], is_error=failed)

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


def serve_stdio(service: ApplicationService, *, principal: Principal) -> None:
    """Serve `service` over standard input and output until the client goes away.

    Synchronous, and that is the boundary: this owns an event loop for the
    length of one connection and returns an ordinary `None`. A caller composes
    it and calls it like any other function.

    **Standard output is the wire.** Anything else written there corrupts the
    protocol stream, which is why the composition root sends its startup notice
    to standard error and why nothing in the application prints.
    """
    asyncio.run(_serve(create_mcp_server(service, principal=principal)))
