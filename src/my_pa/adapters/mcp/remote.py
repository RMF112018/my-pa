"""Official SDK Streamable HTTP composition for the remote MCP surface."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable, Sequence
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Final

from mcp.server.context import ServerRequestContext
from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
from mcp.server.transport_security import TransportSecuritySettings
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import BaseRoute, Route
from starlette.types import Receive, Scope, Send

from my_pa.adapters.mcp.server import McpAccess, create_mcp_server, published_tools
from my_pa.adapters.normalization import MAX_REQUEST_BYTES
from my_pa.application.service import ApplicationService
from my_pa.domain.capture.submission import CaptureTransport
from my_pa.domain.documents.managed import MAX_MANAGED_DOCUMENT_BYTES
from my_pa.domain.identity.operation import Capability, is_operator_only, permitted_purposes
from my_pa.domain.identity.principal import Principal
from my_pa.domain.identity.purpose import Purpose

__all__ = [
    "MCP_PATH",
    "RemoteAccessContext",
    "RemoteAccessResolver",
    "create_remote_mcp_app",
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
        Purpose.CAPTURE_AUTHORING,
        Purpose.REVIEW_DISPOSITION,
        Purpose.DOCUMENT_AUTHORING,
        Purpose.CONTINUITY_AUTHORING,
        Purpose.TASK_AUTHORING,
        Purpose.COMMITMENT_AUTHORING,
        Purpose.CONTEXT_PREFERENCE,
        Purpose.GOODNOTES_PROPOSAL,
        Purpose.REPORT_AUTHORING,
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
        # them from every remote profile before this set is consulted. The
        # membership is still load-bearing rather than decorative: it is what
        # keeps the classification true if the operator gate is ever the thing
        # that changes, and it is the axis
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


RemoteAccessResolver = Callable[[str | None], RemoteAccessContext | None]


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
    ) -> None:
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
            async with asyncio.timeout(self.timeout_seconds), self.slots:
                scope.setdefault("state", {})["remote_mcp_access"] = resolved
                await self.manager.handle_request(scope, receive, send)
        except TimeoutError:
            response = JSONResponse({"error": "temporarily_unavailable"}, status_code=503)
            await response(scope, receive, send)


def remote_tool_names(service: ApplicationService, *, writes_enabled: bool) -> frozenset[str]:
    """Deterministically classify the canonical, composed capability set."""

    names: set[str] = set()
    composed = {tool.name for tool in published_tools(service)}
    for capability in Capability:
        if capability.value not in composed or is_operator_only(capability):
            continue
        is_write = bool(permitted_purposes(capability) & _WRITE_PURPOSES)
        if writes_enabled or not is_write:
            names.add(capability.value)
    return frozenset(names)


def create_remote_mcp_app(
    service: ApplicationService,
    *,
    resolve_access: RemoteAccessResolver,
    allowed_hosts: tuple[str, ...],
    allowed_origins: tuple[str, ...] = (),
    global_enabled: bool = True,
    remote_enabled: bool = False,
    writes_enabled: bool = False,
    max_concurrent_calls: int = 8,
    call_timeout_seconds: float = 30.0,
    readiness: Callable[[], bool] = lambda: True,
    resource: str = "",
    authorization_servers: tuple[str, ...] = (),
    scopes: frozenset[str] = frozenset(),
    additional_routes: Sequence[BaseRoute] = (),
) -> Starlette:
    """Compose `/mcp` without moving identity or policy into the transport.

    The resolver receives only the Authorization header. It cannot inspect the
    MCP document and therefore cannot accept caller-selected authority from it.
    """

    if not allowed_hosts:
        raise ValueError("at least one exact allowed host is required")

    profile = remote_tool_names(service, writes_enabled=writes_enabled)
    serving = global_enabled and remote_enabled

    def access_for_request(context: ServerRequestContext[object]) -> McpAccess | None:
        request = context.request
        resolved = (
            None if request is None else request.scope.get("state", {}).get("remote_mcp_access")
        )
        if resolved is None:
            return None
        principal, granted = resolved.principal, resolved.allowed_capabilities
        allowed = profile if granted is None else profile & granted
        return McpAccess(
            principal=principal,
            allowed_tools=allowed,
            allowed_capability_purposes=resolved.capability_purposes,
            transport=CaptureTransport.REMOTE_CLIENT,
        )

    server = create_mcp_server(
        service,
        enabled=serving,
        access_for_request=access_for_request,
        oauth_scopes=scopes,
        max_concurrent_calls=max_concurrent_calls,
        call_timeout_seconds=call_timeout_seconds,
        max_result_bytes=MAX_REMOTE_RESULT_BYTES,
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
