"""Thin process entrypoint for the isolated GSQS remote-eval MCP surface.

Canonical service name: ``my-pa-gsqs-remote-eval``. Default port 8767.
Settings wiring is Worker F. This file does not read the production MCP tool
registry and does not import Worker C at module import time.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from datetime import datetime
from pathlib import Path
from typing import Final

import uvicorn
from starlette.applications import Starlette

from my_pa.adapters.mcp.gsqs_remote_eval import (
    CANONICAL_PUBLIC_HOST,
    DEFAULT_PORT,
    EVAL_SERVER_NAME,
    FilesystemStagedPngReader,
    GsqsEvalAuthenticator,
    GsqsEvalPrincipal,
    create_gsqs_remote_eval_app,
)
from my_pa.application.goodnotes_gsqs_remote_eval import RemoteEvalService
from my_pa.application.goodnotes_gsqs_remote_eval_contracts import (
    ERROR_FORBIDDEN_SCOPE,
    ERROR_UNAUTHENTICATED,
    RemoteEvalError,
    StagingSealResult,
)
from my_pa.application.goodnotes_gsqs_remote_eval_disclosure import FilesystemDisclosureJournal
from my_pa.application.goodnotes_gsqs_remote_eval_storage import FilesystemRemoteEvalStore
from my_pa.domain.common.time import utc_now

HOST: Final = "127.0.0.1"


class _UtcClock:
    def now(self) -> datetime:
        return utc_now()


class _OperatorOnlyStaging:
    def seal_authorized_rasters(self, session: object, manifest: object) -> StagingSealResult:
        _ = (session, manifest)
        raise RemoteEvalError(ERROR_FORBIDDEN_SCOPE, "seal is operator-only")


class _RejectAuthenticator:
    def authenticate(self, authorization_header: str | None) -> GsqsEvalPrincipal:
        _ = authorization_header
        raise RemoteEvalError(ERROR_UNAUTHENTICATED, "remote evaluation is disabled")


def _load_authenticator() -> GsqsEvalAuthenticator:
    """Lazy Worker C import. Fail closed if that module has not landed."""

    try:
        module = importlib.import_module(
            "my_pa.infrastructure.security.gsqs_remote_eval_authentication"
        )
    except ImportError as exc:
        raise SystemExit(
            "GSQS remote-eval authenticator is not available "
            "(my_pa.infrastructure.security.gsqs_remote_eval_authentication)"
        ) from exc
    builder = getattr(module, "build_gsqs_eval_authenticator", None)
    if callable(builder):
        return builder()
    cls = getattr(module, "GsqsRemoteEvalAuthenticator", None)
    if cls is not None:
        return cls()
    raise SystemExit("GSQS remote-eval authenticator module has no build_gsqs_eval_authenticator")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Serve the isolated GSQS ChatLLM remote-eval MCP surface."
    )
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument(
        "--enabled",
        action="store_true",
        default=False,
        help="serve /mcp (default: boot for health only; /mcp returns 404)",
    )
    parser.add_argument(
        "--state-root",
        type=Path,
        default=None,
        help="explicit eval state root (required when --enabled; tests never use /srv)",
    )
    parser.add_argument(
        "--allowed-host",
        action="append",
        dest="allowed_hosts",
        default=None,
        help="exact Host header value; defaults to bind host plus canonical public host",
    )
    parser.add_argument(
        "--allowed-origin",
        action="append",
        dest="allowed_origins",
        default=None,
        help="exact Origin value; no wildcards",
    )
    return parser


def _allowed_hosts(args: argparse.Namespace) -> tuple[str, ...]:
    if args.allowed_hosts:
        return tuple(args.allowed_hosts)
    return (
        args.host,
        f"{args.host}:{args.port}",
        CANONICAL_PUBLIC_HOST,
        f"{CANONICAL_PUBLIC_HOST}:{args.port}",
    )


def _build_enabled_app(args: argparse.Namespace, authenticator: GsqsEvalAuthenticator) -> Starlette:
    if args.state_root is None:
        raise SystemExit("--state-root is required when --enabled")
    state_root = Path(args.state_root)
    clock = _UtcClock()
    store = FilesystemRemoteEvalStore(state_root)
    disclosure = FilesystemDisclosureJournal(state_root, clock=clock)
    service = RemoteEvalService(
        store=store,
        clock=clock,
        staging=_OperatorOnlyStaging(),
        disclosure=disclosure,
        eval_enabled=True,
    )
    return create_gsqs_remote_eval_app(
        authenticator=authenticator,
        service=service,
        store=store,
        raster_reader=FilesystemStagedPngReader(state_root),
        allowed_hosts=_allowed_hosts(args),
        allowed_origins=tuple(args.allowed_origins or ()),
        enabled=True,
        disclosure_journal=disclosure,
    )


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.enabled:
        app = _build_enabled_app(args, _load_authenticator())
    else:
        app = create_gsqs_remote_eval_app(
            authenticator=_RejectAuthenticator(),
            service=None,
            store=None,
            raster_reader=None,
            allowed_hosts=_allowed_hosts(args),
            allowed_origins=tuple(args.allowed_origins or ()),
            enabled=False,
        )
    print(
        f"serving     {EVAL_SERVER_NAME} on {args.host}:{args.port} enabled={args.enabled}",
        file=sys.stderr,
        flush=True,
    )
    uvicorn.run(app, host=args.host, port=args.port, log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
