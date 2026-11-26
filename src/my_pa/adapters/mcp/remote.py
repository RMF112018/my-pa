"""Official SDK Streamable HTTP composition for the remote MCP surface."""

from __future__ import annotations

import asyncio
import base64
import secrets
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Final, Literal

from mcp.server.context import ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from mcp.shared.exceptions import MCPError
from mcp.types import (
    BlobResourceContents,
    ListResourcesResult,
    ListResourceTemplatesResult,
    PaginatedRequestParams,
    ReadResourceRequestParams,
    ReadResourceResult,
    ResourceTemplate,
)
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Route
from starlette.types import Message, Receive, Scope, Send

from my_pa.adapters.mcp.server import McpAccess, create_mcp_server, published_tools
from my_pa.adapters.normalization import MAX_REQUEST_BYTES
from my_pa.adapters.remote_resources import (
    RemoteResourceRefused,
    RemoteResourceSource,
    RemoteResourceStream,
)
from my_pa.application.service import ApplicationService
from my_pa.contracts.mcp_database_witness import McpWitnessBinding
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.documents.managed import MAX_MANAGED_DOCUMENT_BYTES
from my_pa.domain.identity.chatllm_capability_policy import COMPACT_TOP_LEVEL_TOOL_NAMES
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose

__all__ = [
    "MCP_PATH",
    "RemoteAccessContext",
    "RemoteAccessResolver",
    "create_remote_mcp_app",
    "is_remote_write",
    "remote_tool_names",
]

MCP_PATH: Final = "/mcp"
HEALTH_PATH: Final = "/healthz"
READINESS_PATH: Final = "/readyz"

# Base64 plus the response envelope must fit without making the legal maximum
# managed-document read impossible. This is still a finite transport ceiling.
MAX_REMOTE_RESULT_BYTES: Final = (MAX_MANAGED_DOCUMENT_BYTES * 4 // 3) + (1 << 20)

_WRITE_PURPOSES: Final = frozenset(
    {
        Purpose.BOUNDED_ENROLLMENT,
        Purpose.GOODNOTES_PULL,
        Purpose.GOODNOTES_CORRECTION,
        Purpose.GSQS_B0_EXECUTION,
        Purpose.CAPTURE_AUTHORING,
        Purpose.CANVAS_WORKSPACE_AUTHORING,
        Purpose.REVIEW_DISPOSITION,
        Purpose.DOCUMENT_AUTHORING,
        Purpose.CONTINUITY_AUTHORING,
        Purpose.TASK_AUTHORING,
        Purpose.COMMITMENT_AUTHORING,
        # PC-CM-IMP-WP07. Remote write-gating is `permitted_purposes(capability)
        # & _WRITE_PURPOSES`, so leaving this out would classify all twelve
        # Constraint mutations as reads on the remote transport -- a grant issued
        # to read would reach them. `constraint_read` stays out, for the same
        # reason every other read purpose does.
        Purpose.CONSTRAINT_AUTHORING,
        Purpose.CONSTRAINT_SYNC_AUTHORING,
        # WP-MTG-04 (plan D-06). Without it the three Meeting writes would be
        # classified remote reads -- routed to `my_pa.read` and not write-gated.
        # `meeting_read` stays out, for the reason every read purpose does.
        Purpose.MEETING_AUTHORING,
        # KLP-WP-03 (KLP-AC-016/017/103). Without it `knowledge.assertions.create`
        # would be classified a remote read -- published while writes are
        # disabled and routed to `my_pa.read`. `knowledge_assertion_read` stays out.
        Purpose.KNOWLEDGE_ASSERTION_AUTHORING,
        # KLP-WP-04 (KLP-AC-016/103): the discovery pair's purpose. Without it
        # submit and checkpoint would be classified remote reads.
        Purpose.KNOWLEDGE_ASSERTION_OBSERVATION,
        # Record lineage S1 (contract section 7). Without it the four Issue
        # writes would be classified remote reads. `issue_read` stays out.
        Purpose.ISSUE_AUTHORING,
        # Record lineage S1: the three association writes' purpose.
        # `record_lineage_read` and `meeting_note_history_read` stay out.
        Purpose.RECORD_LINEAGE_AUTHORING,
        # Record lineage S2: the two composite Work writes' purpose.
        Purpose.ISSUE_WORK_AUTHORING,
        # Record lineage S3: the operator-only backfill's purpose.
        Purpose.LINEAGE_BACKFILL,
        # CPM Workbench S5b-2 (contract section 3.12): the operator-only schedule
        # import's purpose; the import is never published remotely, and this keeps
        # it a write if a later publication rule ever reached it. `schedule_read`
        # stays out.
        Purpose.SCHEDULE_IMPORT,
        Purpose.CONTEXT_PREFERENCE,
        Purpose.GOODNOTES_PROPOSAL,
        Purpose.REPORT_AUTHORING,
        # Reports Modernization WP03: archive, delete (to Trash) and restore of a
        # standalone report. Without it the three would be classified remote
        # reads -- published while writes are disabled and routed to
        # `my_pa.read`. `report_read` (and so `reports.history`) stays out.
        Purpose.REPORT_LIFECYCLE,
        # Reports Modernization WP05b: the operator-only custody purposes, as the
        # attested lineage confirms' `record_lineage_authoring` and the schedule
        # import's `schedule_import`. The four are never published remotely; this
        # keeps the three custody writes writes if a later publication rule ever
        # reached them. `reports.retention.get` shares `report_retention` but is a
        # read: `_REMOTE_READS_UNDER_WRITE_PURPOSES` names it (Reports
        # Modernization WP08), so a new capability under the purpose stays a write.
        Purpose.REPORT_HOLD,
        Purpose.REPORT_RETENTION,
        # Schedule Scenarios S6-3 (schedule-scenarios contract section 15.12.2):
        # the 6 client-usable plane writes' purpose -- without it they would be
        # classified remote reads, published while writes are disabled and routed
        # to `my_pa.read` -- and the operator-only baseline approval's, which is
        # never published remotely; this keeps those 4 writes if a later
        # publication rule ever reached them. `schedule_analysis_read` stays out.
        Purpose.SCHEDULE_ANALYSIS_AUTHORING,
        Purpose.SCHEDULE_BASELINE_APPROVAL,
        # Files workspace (contract section 1.1): the 10 `files.*` writes' purpose.
        # Without it they would be classified remote reads -- published while
        # writes are disabled and routed to `my_pa.read`. `file_workspace_read`
        # (and so `files.download.begin`) stays out.
        Purpose.FILE_WORKSPACE_AUTHORING,
        # P6 XER import S7-4a (contract section 10.7): the 2 P6 writes' purposes.
        # Without them the import and the selection would be classified remote
        # reads -- published while writes are disabled and routed to `my_pa.read`.
        Purpose.SCHEDULE_P6_IMPORT,
        Purpose.SCHEDULE_P6_CONFIGURATION,
        Purpose.RELATIONSHIP_MEMORY_AUTHORING,
        Purpose.ENTITY_OBSERVATION_INGEST,
        Purpose.ENTITY_AUTHORING,
        # Phase B's three, each admitted because the capability it permits
        # persists a row. A proposal is a request rather than a canonical fact
        # and it is still written down, so a remote producer needs
        # remote-writes-enabled to raise one.
        Purpose.ENTITY_PROPOSAL,
        Purpose.RELATIONSHIP_MEMORY_PROPOSAL,
        # `entity_identity_correction` covers `entities.merge.preview` as well as
        # `entities.merge`, and the coupling is accepted rather than worked
        # around (Manager R-7). This set is intersected with a capability's
        # permitted purposes, so a shared purpose makes both write-gated — and
        # that is the safe direction: the preview persists a durable control row
        # and reads the exact identities of two people, so requiring
        # remote-writes-enabled *plus* an operator grant for it is the boundary
        # operator §24 asks for rather than an accident of the derivation.
        # Splitting the purpose to un-gate the preview was considered and
        # refused; `domain/identity/purpose.py` records why.
        #
        # Both capabilities are operator-only, so `remote_tool_names` withholds
        # them unless the composition root attaches the exact server-resolved
        # ``remote.operator`` marker. The membership remains load-bearing: even
        # that profile cannot publish either name unless remote writes are also
        # enabled, and it is the axis
        # `tests/contract/test_entity_remote_exposure.py` asserts against.
        Purpose.ENTITY_IDENTITY_CORRECTION,
    }
)


@dataclass(frozen=True)
class RemoteAccessContext:
    """Identity and grant ceiling resolved from the HTTP credential only."""

    principal: Principal
    allowed_capabilities: frozenset[str] | None = None
    capability_purposes: frozenset[tuple[Capability, Purpose | None]] | None = None
    relationship_grant_profile: Literal["remote.operator"] | None = None
    compact_publication: bool = False
    compact_operator_publication: bool = False
    authenticated_client_id: str | None = field(default=None, repr=False)
    service: ApplicationService | None = field(default=None, repr=False, compare=False)
    database_witness: McpWitnessBinding | None = field(default=None, repr=False, compare=False)


RemoteAccessResolver = Callable[[str | None], RemoteAccessContext | None]


#: Where a `resources/read` handler leaves its opened stream for `_McpEndpoint`.
_PENDING_RESOURCE: Final = "remote_mcp_resource"
#: JSON-RPC "resource not found" (MCP); every refusal answers it with a token.
_RESOURCE_REFUSED_CODE: Final = -32002
#: The longest one streamed body send may wait on a reader that stopped reading.
RESOURCE_SEND_IDLE_SECONDS: Final = 30.0


@dataclass
class _PendingResource:
    marker: str
    opened: RemoteResourceStream


class _DeferredResponse:
    """Hold a response that carries a resource marker until it can be streamed.

    A `resources/read` answer is built by the SDK, with every header, origin
    and protocol check it makes, around a random placeholder blob. Only when
    the handler registered a pending resource for this request is the
    response held; any other response passes straight through. After the SDK
    returns -- and after the `/mcp` slot and call timeout are released -- the
    placeholder is replaced by the streamed base64, with an exact
    `Content-Length`, so the file is never buffered whole.
    """

    def __init__(self, send: Send, state: dict[str, object], max_held_bytes: int) -> None:
        self._send = send
        self._state = state
        self._max_held = max_held_bytes
        self.start: Message | None = None
        self.body = bytearray()
        self.complete = False

    async def __call__(self, message: Message) -> None:
        kind = message.get("type")
        if kind == "http.response.start" and self._state.get(_PENDING_RESOURCE) is not None:
            self.start = message
            return
        if kind == "http.response.body" and self.start is not None and not self.complete:
            self.body.extend(message.get("body", b""))
            if len(self.body) > self._max_held:
                raise RuntimeError("held response past its bound")
            self.complete = not message.get("more_body", False)
            return
        await self._send(message)

    async def release(self, send_idle_seconds: float) -> None:
        """Send the held response, streaming the pending resource into its placeholder."""
        pending = self._state.pop(_PENDING_RESOURCE, None)
        if not isinstance(pending, _PendingResource):
            return
        try:
            if self.start is None or not self.complete:
                return
            marker = pending.marker.encode("ascii")
            body = bytes(self.body)
            if body.count(marker) != 1:
                await self._send(self.start)
                await self._send({"type": "http.response.body", "body": body})
                return
            prefix, suffix = body.split(marker)
            encoded_length = 4 * ((pending.opened.size + 2) // 3)
            headers = [
                (name, value)
                for name, value in self.start.get("headers", [])
                if name.lower() != b"content-length"
            ]
            headers.append(
                (b"content-length", str(len(prefix) + encoded_length + len(suffix)).encode())
            )
            send = self._send

            async def bounded(chunk: bytes) -> None:
                async with asyncio.timeout(send_idle_seconds):
                    await send({"type": "http.response.body", "body": chunk, "more_body": True})

            async def write(piece: bytes) -> None:
                await bounded(base64.b64encode(piece))

            await self._send({**self.start, "headers": headers})
            await bounded(prefix)
            await pending.opened.stream(write)
            await self._send({"type": "http.response.body", "body": suffix})
        except Exception:
            # The headers may have left: the stream stops short of its
            # Content-Length and the server closes the connection.
            return
        finally:
            await pending.opened.aclose()


def _metadata_url(resource: str) -> str:
    suffix = "/mcp" if resource.endswith("/mcp") else ""
    origin = resource.removesuffix(suffix).rstrip("/")
    return f"{origin}/.well-known/oauth-protected-resource{suffix}"


class _McpEndpoint:
    """Keep the SDK manager on Starlette's ASGI endpoint path."""

    def __init__(
        self,
        manager: StreamableHTTPSessionManager,
        resolver: RemoteAccessResolver,
        resource: str,
        slots: asyncio.Semaphore,
        auth_slots: asyncio.Semaphore,
        timeout_seconds: float,
        required_scopes: frozenset[str],
        resource_send_idle_seconds: float = RESOURCE_SEND_IDLE_SECONDS,
    ) -> None:
        self.resource_send_idle_seconds = resource_send_idle_seconds
        self.manager = manager
        self.resolver = resolver
        self.resource = resource
        self.slots = slots
        self.auth_slots = auth_slots
        self.timeout_seconds = timeout_seconds
        self.required_scopes = required_scopes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        headers = dict(scope.get("headers", ()))
        raw = headers.get(b"authorization")
        authorization = None if raw is None else raw.decode("latin-1")
        try:
            await asyncio.wait_for(self.auth_slots.acquire(), timeout=self.timeout_seconds)
            authentication = asyncio.create_task(asyncio.to_thread(self.resolver, authorization))
            try:
                resolved = await asyncio.wait_for(
                    asyncio.shield(authentication), timeout=self.timeout_seconds
                )
            except TimeoutError:
                # The thread cannot be cancelled. Keep its capacity charged
                # until it actually stops; callers waiting for capacity remain
                # cancellable and leave no queued background work behind.
                authentication.add_done_callback(lambda _task: self.auth_slots.release())
                raise
            except asyncio.CancelledError:
                authentication.add_done_callback(lambda _task: self.auth_slots.release())
                raise
            except Exception:
                self.auth_slots.release()
                resolved = None
            else:
                self.auth_slots.release()
            if resolved is None:
                challenge = f'Bearer resource_metadata="{_metadata_url(self.resource)}"'
                response = JSONResponse(
                    {"error": "invalid_token"},
                    status_code=401,
                    headers={"WWW-Authenticate": challenge},
                )
                await response(scope, receive, send)
                return
            if resolved.allowed_capabilities is not None and not resolved.allowed_capabilities:
                scope_value = " ".join(sorted(self.required_scopes))
                metadata_url = _metadata_url(self.resource)
                response = JSONResponse(
                    {"error": "insufficient_scope"},
                    status_code=403,
                    headers={
                        "WWW-Authenticate": (
                            f'Bearer resource_metadata="{metadata_url}", '
                            'error="insufficient_scope", '
                            'error_description="No approved MCP capability grant is active", '
                            f'scope="{scope_value}"'
                        )
                    },
                )
                await response(scope, receive, send)
                return
            state = scope.setdefault("state", {})
            deferred = _DeferredResponse(send, state, MAX_REQUEST_BYTES)
            try:
                async with asyncio.timeout(self.timeout_seconds), self.slots:
                    state["remote_mcp_access"] = resolved
                    await self.manager.handle_request(scope, receive, deferred)
            except BaseException:
                pending = state.pop(_PENDING_RESOURCE, None)
                if isinstance(pending, _PendingResource):
                    await pending.opened.aclose()
                raise
            # Outside the call slot and its timeout: a resource stream keeps
            # its own bounds (files-workspace contract section 17.3).
            await deferred.release(self.resource_send_idle_seconds)
        except TimeoutError:
            response = JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
            await response(scope, receive, send)


_REMOTE_OPERATOR_IDENTITY_CAPABILITIES: Final = frozenset(
    {
        Capability.ENTITIES_MERGE_PREVIEW,
        Capability.ENTITIES_MERGE,
        Capability.ENTITIES_SPLIT_PREVIEW,
        Capability.ENTITIES_SPLIT,
    }
)


#: Reads whose only permitted purpose is also a write purpose. Each name here is
#: an explicit exception, so any other capability under that purpose -- including
#: one added later -- stays write-gated (the safe direction). Reports
#: Modernization WP08: `reports.retention.get` reads the retention period under
#: `report_retention`, which `reports.retention.set` writes; it stays operator-only
#: and so withheld remotely either way.
_REMOTE_READS_UNDER_WRITE_PURPOSES: Final = frozenset({Capability.REPORTS_RETENTION_GET})


def is_remote_write(capability: Capability) -> bool:
    """Whether the current remote profile treats `capability` as a write.

    This is the purpose intersection `remote_tool_names` already uses, which is
    also preserves the write gate for durable operator previews. The only
    exceptions are the named reads in `_REMOTE_READS_UNDER_WRITE_PURPOSES`.
    """
    if capability in _REMOTE_READS_UNDER_WRITE_PURPOSES:
        return False
    return bool(permitted_purposes(capability) & _WRITE_PURPOSES)


def remote_tool_names(
    service: ApplicationService,
    *,
    writes_enabled: bool,
    relationship_grant_profile: Literal["remote.operator"] | None = None,
    compact_operator_publication: bool = False,
) -> frozenset[str]:
    """Deterministically classify the canonical, composed capability set."""

    names: set[str] = set()
    composed = {tool.name for tool in published_tools(service, authenticated_client_present=True)}
    for capability in Capability:
        if capability.value not in composed:
            continue
        if is_operator_only(capability) and not (
            (
                compact_operator_publication
                and capability
                in _REMOTE_OPERATOR_IDENTITY_CAPABILITIES | {Capability.SOURCES_ENROLL}
            )
            or (
                relationship_grant_profile == "remote.operator"
                and capability in _REMOTE_OPERATOR_IDENTITY_CAPABILITIES
            )
        ):
            continue
        if writes_enabled or not is_remote_write(capability):
            names.add(capability.value)
    return frozenset(names)


def create_remote_mcp_app(
    service: ApplicationService,
    *,
    resolve_access: RemoteAccessResolver,
    allowed_hosts: tuple[str, ...],
    allowed_origins: tuple[str, ...] = (),
    global_enabled: bool = True,
    require_bound_service: bool = False,
    remote_enabled: bool = False,
    writes_enabled: bool = False,
    max_concurrent_calls: int = 8,
    call_timeout_seconds: float = 30.0,
    readiness: Callable[[], bool] = lambda: True,
    resource: str = "",
    authorization_servers: tuple[str, ...] = (),
    scopes: frozenset[str] = frozenset(),
    additional_routes: Sequence[BaseRoute] = (),
    resources: RemoteResourceSource | None = None,
) -> Starlette:
    """Compose `/mcp` without moving identity or policy into the transport.

    The resolver receives only the Authorization header. It cannot inspect the
    MCP document and therefore cannot accept caller-selected authority from it.
    """

    if not allowed_hosts:
        raise ValueError("at least one exact allowed host is required")

    profile = remote_tool_names(service, writes_enabled=writes_enabled)
    operator_profile = remote_tool_names(
        service,
        writes_enabled=writes_enabled,
        relationship_grant_profile="remote.operator",
    )
    compact_operator_profile = remote_tool_names(
        service, writes_enabled=writes_enabled, compact_operator_publication=True
    )
    serving = global_enabled and remote_enabled

    def access_for_request(context: ServerRequestContext[object]) -> McpAccess | None:
        request = context.request
        resolved = (
            None if request is None else request.scope.get("state", {}).get("remote_mcp_access")
        )
        if resolved is None or (require_bound_service and resolved.service is None):
            return None
        principal, granted = resolved.principal, resolved.allowed_capabilities
        request_profile = (
            compact_operator_profile
            if resolved.compact_publication and resolved.compact_operator_publication
            else operator_profile
            if resolved.relationship_grant_profile == "remote.operator"
            else profile
        )
        allowed = request_profile if granted is None else request_profile & granted
        compact = resolved.compact_publication
        published = allowed
        canonical = None
        if compact:
            from my_pa.adapters.mcp.chatllm_gateway import facade_tool_names

            canonical = allowed
            # Files-workspace contract section 17.4: the eligible primary file
            # names are also published top-level, under their canonical names.
            published = facade_tool_names(allowed) | (allowed & COMPACT_TOP_LEVEL_TOOL_NAMES)
        return McpAccess(
            principal=principal,
            allowed_tools=published,
            allowed_capability_purposes=resolved.capability_purposes,
            transport=CaptureTransport.REMOTE_CLIENT,
            compact_publication=compact,
            allowed_canonical_targets=canonical,
            authenticated_client_id=resolved.authenticated_client_id,
            service=resolved.service,
            database_witness=resolved.database_witness,
        )

    def resolved_access(context: ServerRequestContext[object]) -> RemoteAccessContext | None:
        request = context.request
        resolved = (
            None if request is None else request.scope.get("state", {}).get("remote_mcp_access")
        )
        if not isinstance(resolved, RemoteAccessContext) or (
            require_bound_service and resolved.service is None
        ):
            return None
        return resolved

    async def list_resources(
        _context: ServerRequestContext[object], _params: PaginatedRequestParams | None
    ) -> ListResourcesResult:
        # Resources are reachable only through a tool result's link.
        return ListResourcesResult(resources=[])

    async def list_resource_templates(
        context: ServerRequestContext[object], _params: PaginatedRequestParams | None
    ) -> ListResourceTemplatesResult:
        if resources is None or not serving or resolved_access(context) is None:
            return ListResourceTemplatesResult(resource_templates=[])
        return ListResourceTemplatesResult(
            resource_templates=[
                ResourceTemplate(
                    name=template.name,
                    uri_template=template.uri_template,
                    description=template.description,
                    mime_type=template.mime_type,
                )
                for template in resources.templates()
            ]
        )

    async def read_resource(
        context: ServerRequestContext[object], params: ReadResourceRequestParams
    ) -> ReadResourceResult:
        resolved = resolved_access(context)
        request = context.request
        if resources is None or not serving or resolved is None or request is None:
            raise MCPError(code=_RESOURCE_REFUSED_CODE, message="unsupported")
        state = request.scope.setdefault("state", {})
        if state.get(_PENDING_RESOURCE) is not None:
            raise MCPError(code=_RESOURCE_REFUSED_CODE, message="unsupported")
        uri = str(params.uri)
        try:
            opened = await resources.open(uri, resolved)
        except RemoteResourceRefused as refusal:
            raise MCPError(code=_RESOURCE_REFUSED_CODE, message=refusal.reason) from None
        marker = secrets.token_hex(32)
        state[_PENDING_RESOURCE] = _PendingResource(marker, opened)
        return ReadResourceResult(
            contents=[BlobResourceContents(uri=uri, mime_type=opened.mime_type, blob=marker)]
        )

    server = create_mcp_server(
        service,
        enabled=serving,
        access_for_request=access_for_request,
        oauth_scopes=scopes,
        max_concurrent_calls=max_concurrent_calls,
        call_timeout_seconds=call_timeout_seconds,
        max_result_bytes=MAX_REMOTE_RESULT_BYTES,
        on_list_resources=None if resources is None else list_resources,
        on_list_resource_templates=None if resources is None else list_resource_templates,
        on_read_resource=None if resources is None else read_resource,
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
    request_slots = asyncio.Semaphore(max_concurrent_calls)
    authentication_slots = asyncio.Semaphore(max_concurrent_calls)

    @asynccontextmanager
    async def lifespan(_app: Starlette) -> AsyncIterator[None]:
        async with manager.run():
            yield

    async def health(_request: Request) -> JSONResponse:
        return JSONResponse({"status": "ok"})

    async def ready(_request: Request) -> JSONResponse:
        try:
            is_ready = serving and readiness()
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
    if not resource or not authorization_servers:
        raise ValueError("resource and authorization server metadata are required")

    return Starlette(
        routes=[
            *additional_routes,
            Route(
                MCP_PATH,
                _McpEndpoint(
                    manager,
                    resolve_access,
                    resource,
                    request_slots,
                    authentication_slots,
                    call_timeout_seconds,
                    scopes,
                ),
                methods=["GET", "POST", "DELETE"],
            ),
            Route(metadata_path, protected_resource, methods=["GET"]),
            Route(f"{metadata_path}/mcp", protected_resource, methods=["GET"]),
            Route(HEALTH_PATH, health, methods=["GET"]),
            Route(READINESS_PATH, ready, methods=["GET"]),
        ],
        lifespan=lifespan,
    )
