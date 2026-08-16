"""Operator administration for durable remote MCP clients and kill switches."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from my_pa.bootstrap.settings import load_settings
from my_pa.domain.identity.operation import Capability
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_capability_grants,
    remote_clients,
    remote_security_controls,
)


def _uuid(value: str) -> UUID:
    return UUID(value)


def _instant(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError("timestamp must include an offset or Z")
    return parsed.astimezone(UTC)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Administer remote MCP authority")
    sub = parser.add_subparsers(dest="command", required=True)
    control = sub.add_parser("control")
    control.add_argument("--remote-enabled", action=argparse.BooleanOptionalAction, required=True)
    control.add_argument("--writes-enabled", action=argparse.BooleanOptionalAction, required=True)
    register = sub.add_parser("register")
    register.add_argument("--oauth-client-id", required=True)
    register.add_argument("--client-name", required=True)
    register.add_argument("--redirect-uri", action="append", required=True)
    register.add_argument("--scope", action="append", required=True)
    register.add_argument("--writes-enabled", action="store_true")
    register.add_argument("--expires-at", type=_instant)
    grant = sub.add_parser("grant")
    grant.add_argument("--oauth-client-id", required=True)
    grant.add_argument("--scope", required=True)
    grant.add_argument("--capability", type=Capability, choices=list(Capability), required=True)
    grant.add_argument("--purpose", type=Purpose, choices=list(Purpose))
    grant.add_argument("--resource", required=True)
    grant.add_argument("--expires-at", type=_instant)
    grant.add_argument("--write", action="store_true")
    revoke = sub.add_parser("revoke")
    revoke.add_argument("--oauth-client-id", required=True)
    revoke_grant = sub.add_parser("revoke-grant")
    revoke_grant.add_argument("--grant-uuid", type=_uuid, required=True)
    set_writes = sub.add_parser("set-client-writes")
    set_writes.add_argument("--oauth-client-id", required=True)
    set_writes.add_argument(
        "--writes-enabled",
        action=argparse.BooleanOptionalAction,
        required=True,
    )
    set_refresh = sub.add_parser("set-client-refresh")
    set_refresh.add_argument("--oauth-client-id", required=True)
    set_refresh.add_argument(
        "--refresh-enabled",
        action=argparse.BooleanOptionalAction,
        required=True,
    )
    args = parser.parse_args(argv)

    settings = load_settings()
    engine = create_database_engine(settings.parsed_database_url(), statement_timeout_ms=30_000)
    now = datetime.now(UTC)
    try:
        with engine.begin() as connection:
            repository = RemoteIdentityRepository(connection)
            if args.command == "control":
                connection.execute(
                    remote_security_controls.update()
                    .where(remote_security_controls.c.singleton.is_(True))
                    .values(
                        remote_enabled=args.remote_enabled,
                        writes_enabled=args.writes_enabled,
                        updated_at=now,
                    )
                )
                print("remote MCP controls updated")
            elif args.command == "register":
                identifier = repository.register_client(
                    oauth_client_id=args.oauth_client_id,
                    client_name=args.client_name,
                    redirect_uris=json.dumps(args.redirect_uri, separators=(",", ":")),
                    registered_scopes=" ".join(sorted(set(args.scope))),
                    now=now,
                    writes_enabled=args.writes_enabled,
                    expires_at=args.expires_at,
                )
                print(identifier)
            elif args.command == "grant":
                remote_client_id = connection.execute(
                    select(remote_clients.c.id).where(
                        remote_clients.c.oauth_client_id == args.oauth_client_id
                    )
                ).scalar_one_or_none()
                if remote_client_id is None:
                    parser.error("remote client not found")
                identifier = repository.grant(
                    remote_client_id=remote_client_id,
                    external_scope=args.scope,
                    capability=args.capability,
                    now=now,
                    is_write=args.write,
                    purpose=args.purpose,
                    resource=args.resource,
                    expires_at=args.expires_at,
                )
                print(identifier)
            elif args.command == "revoke":
                if not repository.revoke_client(
                    oauth_client_id=args.oauth_client_id,
                    now=now,
                ):
                    parser.error("remote client not found")
                print("remote MCP client revoked")
            elif args.command == "revoke-grant":
                result = connection.execute(
                    remote_capability_grants.update()
                    .where(remote_capability_grants.c.id == args.grant_uuid)
                    .values(revoked_at=now)
                )
                if result.rowcount != 1:
                    parser.error("remote grant not found")
                print("remote MCP grant revoked")
            elif args.command == "set-client-writes":
                if not repository.set_client_writes(
                    oauth_client_id=args.oauth_client_id,
                    writes_enabled=args.writes_enabled,
                ):
                    parser.error("remote client not found")
                print(
                    "remote MCP client writes " + ("enabled" if args.writes_enabled else "disabled")
                )
            elif args.command == "set-client-refresh":
                if not repository.set_client_refresh(
                    oauth_client_id=args.oauth_client_id,
                    refresh_enabled=args.refresh_enabled,
                ):
                    parser.error("remote client not found")
                print(
                    "remote MCP client refresh "
                    + ("enabled" if args.refresh_enabled else "disabled")
                )
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
