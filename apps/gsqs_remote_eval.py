"""Composition root for the isolated GSQS ChatLLM remote-eval MCP process.

    .venv/bin/python apps/gsqs_remote_eval.py
    .venv/bin/python apps/gsqs_remote_eval.py --port 8767

This is not production MCP. It does not import the production tool registry or
compose the gateway application service. Default bind is loopback ``127.0.0.1``
on ``MY_PA_GSQS_REMOTE_EVAL_PORT`` (8767). Phase B does not deploy it.

**Disabled by default.** ``/healthz`` answers; ``/readyz`` is 503; ``/mcp`` is
404. Enabling requires Settings validation (HTTPS public origin, explicit state
root, concurrency 1, no wildcard origins). The intended NAS state root is
``/srv/my-pa/gsqs-remote-eval``; Settings leaves that path empty so tests cannot
inherit it. Tests override to a temporary directory and must never use ``/srv``.

**Token introspection and DCR/PKCE.** When enabled, the process composes
``OriginOAuthServer`` for the evaluation resource
``https://my-pa-gsqs.bobby-fetting.me/mcp`` and scope ``my-pa.gsqs.evaluate``,
uses ``.introspect`` for bearer authentication, and mounts the origin OAuth
HTTP routes (register, authorize, token, revoke, authorization-server metadata)
so ChatLLM can complete DCR+PKCE against this audience. Production MCP cannot
issue eval tokens: authorize rejects ``resource != self.resource``. Composition
does not mint live clients and does not run a database migration. If the
authenticator cannot be composed, the process fails closed with a message that
names the gap and never echoes secrets. Tests inject authenticator and
``RemoteEvalService`` through ``build_eval_app_from_settings``.
"""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Callable, Sequence
from datetime import datetime
from pathlib import Path
from typing import Final

import uvicorn
from sqlalchemy.engine import Engine
from starlette.applications import Starlette
from starlette.routing import BaseRoute

from my_pa.adapters.gsqs_remote_eval_mcp import (
    DEFAULT_EVAL_RESOURCE,
    GsqsEvalAuthenticator,
    GsqsEvalPrincipal,
    create_gsqs_remote_eval_app,
)
from my_pa.adapters.http.oauth import build_origin_oauth_routes
from my_pa.application.goodnotes_gsqs_remote_eval import RemoteEvalService
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    ERROR_UNAUTHENTICATED,
    RemoteEvalError,
)
from my_pa.application.goodnotes_gsqs_remote_eval_disclosure import FilesystemDisclosureJournal
from my_pa.application.goodnotes_gsqs_remote_eval_staging import FilesystemRasterStaging
from my_pa.application.goodnotes_gsqs_remote_eval_storage import (
    FilesystemRemoteEvalStore,
    mkdir_private,
    reject_symlink,
)
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.domain.common.time import utc_now
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.security.gsqs_remote_eval_authentication import (
    GsqsRemoteEvalAuthenticator,
    build_evaluation_origin_oauth_settings,
)
from my_pa.infrastructure.security.origin_authorization import OriginOAuthServer

HOST: Final = "127.0.0.1"
DEFAULT_PORT: Final = 8767
INTENDED_STATE_ROOT: Final = "/srv/my-pa/gsqs-remote-eval"
GRACEFUL_SHUTDOWN_SECONDS: Final = 30
_AUTHENTICATOR_COMPOSE_REFUSAL: Final = (
    "GSQS remote-eval authenticator cannot be composed; the evaluation process "
    "needs origin introspection for its own resource and cannot start enabled "
    "without it. Tests must inject authenticator and service through "
    "build_eval_app_from_settings."
)


class _UtcClock:
    def now(self) -> datetime:
        return utc_now()


class _RejectAuthenticator:
    def authenticate(self, authorization_header: str | None) -> GsqsEvalPrincipal:
        _ = authorization_header
        raise RemoteEvalError(ERROR_UNAUTHENTICATED, "remote evaluation is disabled")


class _EvalAuthenticatorAdapter:
    """Present origin introspection as the eval MCP authenticator Protocol."""

    def __init__(self, inner: GsqsRemoteEvalAuthenticator) -> None:
        self._inner = inner

    def authenticate(self, authorization_header: str | None) -> GsqsEvalPrincipal:
        return self._inner.authenticate(authorization_header)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve the isolated GSQS ChatLLM remote-eval MCP surface."
    )
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=None)
    return parser


def eval_state_is_ready(state_root: Path, store: FilesystemRemoteEvalStore) -> bool:
    """Settings-valid, state root usable, store accessible, journal parent readable.

    No session is required. The callable returns a boolean; ready JSON stays
    ``{"status": "ready"}`` / ``{"status": "unavailable"}`` and never carries
    session IDs, rasters, gold, or tokens.
    """
    try:
        if (
            not state_root.exists()
            or state_root.is_symlink()
            or not state_root.is_dir()
            or not os.access(state_root, os.R_OK | os.X_OK)
        ):
            return False
        reject_symlink(state_root, what="state_root")
        store.list_session_ids()
        sessions = state_root / "sessions"
        if (
            not sessions.exists()
            or sessions.is_symlink()
            or not sessions.is_dir()
            or not os.access(sessions, os.R_OK | os.X_OK)
        ):
            return False
        reject_symlink(sessions, what="sessions")
        return True
    except Exception:
        return False


def prepare_eval_state_root(state_root: Path) -> None:
    """Create the operator-intended spool directories if they are absent.

    The host mount is an operator act. Inside it the process creates ``sessions``
    and ``authorized-rasters`` with mode ``0o700``. This is not a private gold
    mount and not a source raster-root beyond the sealed Phase A spool.
    """
    mkdir_private(state_root)
    mkdir_private(state_root / "sessions")
    mkdir_private(state_root / "authorized-rasters")


def compose_eval_service(settings: Settings) -> RemoteEvalService:
    """Filesystem store, staging, and disclosure journal under the configured root."""
    state_root = Path(settings.gsqs_remote_eval_state_root.strip())
    prepare_eval_state_root(state_root)
    clock = _UtcClock()
    store = FilesystemRemoteEvalStore(state_root)
    staging = FilesystemRasterStaging(state_root, state_root / "authorized-rasters")
    disclosure = FilesystemDisclosureJournal(state_root, clock=clock)
    return RemoteEvalService(
        store=store,
        clock=clock,
        staging=staging,
        disclosure=disclosure,
        eval_enabled=True,
        lease_seconds=settings.gsqs_remote_eval_lease_seconds,
    )


def compose_eval_authenticator(
    settings: Settings,
) -> tuple[GsqsEvalAuthenticator, Engine, OriginOAuthServer]:
    """Build origin OAuth for the evaluation resource, or fail closed.

    Construction does not register live clients and does not migrate. The
    returned ``OriginOAuthServer`` is the same instance used for introspection
    so DCR/PKCE can issue tokens for this audience. Engine callers own
    ``dispose()``.
    """
    engine: Engine | None = None
    message = ""
    try:
        engine = create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30_000)
        oauth = build_evaluation_origin_oauth_settings(
            connections=engine.begin,
            issuer=settings.gsqs_remote_eval_public_origin.strip().rstrip("/"),
            resource=settings.gsqs_remote_eval_oauth_audience.strip(),
        )
        authorization_server = OriginOAuthServer(
            connections=engine.begin,
            issuer=str(oauth["issuer"]),
            resource=str(oauth["resource"]),
            supported_scopes=frozenset({settings.gsqs_remote_eval_oauth_scope.strip()}),
        )
        authenticator = GsqsRemoteEvalAuthenticator(
            token_context=authorization_server.introspect,
            connections=engine.begin,
            required_resource=settings.gsqs_remote_eval_oauth_audience.strip(),
            required_scope=settings.gsqs_remote_eval_oauth_scope.strip(),
        )
        return _EvalAuthenticatorAdapter(authenticator), engine, authorization_server
    except Exception:
        if engine is not None:
            engine.dispose()
        message = _AUTHENTICATOR_COMPOSE_REFUSAL
    raise SystemExit(message)


def build_eval_app_from_settings(
    settings: Settings,
    *,
    authenticator: GsqsEvalAuthenticator,
    service: RemoteEvalService | None = None,
    bind_host: str = HOST,
    bind_port: int | None = None,
    readiness: Callable[[], bool] | None = None,
    extra_routes: Sequence[BaseRoute] = (),
) -> Starlette:
    """Compose the isolated eval ASGI app from validated Settings.

    Tests inject authenticator and service and override ``state_root`` to tmp.
    """
    port = settings.gsqs_remote_eval_port if bind_port is None else bind_port
    enabled = settings.gsqs_remote_eval_enabled
    if enabled and service is None:
        raise ValueError("enabled GSQS remote-eval requires a RemoteEvalService")
    if readiness is None:
        if enabled and service is not None:
            store = service._store
            state_root = Path(settings.gsqs_remote_eval_state_root.strip())

            def _filesystem_ready() -> bool:
                return isinstance(store, FilesystemRemoteEvalStore) and eval_state_is_ready(
                    state_root, store
                )

            def _injected_ready() -> bool:
                return True

            if isinstance(store, FilesystemRemoteEvalStore):
                readiness = _filesystem_ready
            else:
                readiness = _injected_ready
        else:

            def _disabled_ready() -> bool:
                return False

            readiness = _disabled_ready
    public_origin = settings.gsqs_remote_eval_public_origin.strip().rstrip("/")
    audience = settings.gsqs_remote_eval_oauth_audience.strip() or DEFAULT_EVAL_RESOURCE
    return create_gsqs_remote_eval_app(
        authenticator,
        service,
        enabled=enabled,
        allowed_hosts=settings.gsqs_remote_eval_transport_hosts(bind_host=bind_host, port=port),
        allowed_origins=settings.gsqs_remote_eval_origin_allowlist(),
        resource=audience,
        authorization_servers=(public_origin,) if public_origin else (),
        scopes=frozenset({settings.gsqs_remote_eval_oauth_scope.strip()}),
        max_image_bytes=settings.gsqs_remote_eval_max_image_bytes,
        max_result_bytes=settings.gsqs_remote_eval_max_result_bytes,
        readiness=readiness,
        extra_routes=extra_routes,
    )


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    settings = load_settings()
    host = args.host
    port = settings.gsqs_remote_eval_port if args.port is None else args.port
    engine: Engine | None = None
    try:
        if settings.gsqs_remote_eval_enabled:
            authenticator, engine, authorization_server = compose_eval_authenticator(settings)
            service = compose_eval_service(settings)
            app = build_eval_app_from_settings(
                settings,
                authenticator=authenticator,
                service=service,
                bind_host=host,
                bind_port=port,
                extra_routes=build_origin_oauth_routes(
                    authorization_server,
                    operator_secret=settings.gsqs_remote_eval_oauth_operator_secret,
                ),
            )
        else:
            app = build_eval_app_from_settings(
                settings,
                authenticator=_RejectAuthenticator(),
                service=None,
                bind_host=host,
                bind_port=port,
            )
        print(
            f"serving     gsqs-remote-eval on {host}:{port} "
            f"enabled={settings.gsqs_remote_eval_enabled}",
            file=sys.stderr,
            flush=True,
        )
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_config=None,
            access_log=False,
            server_header=False,
            timeout_graceful_shutdown=GRACEFUL_SHUTDOWN_SECONDS,
        )
    finally:
        if engine is not None:
            engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
