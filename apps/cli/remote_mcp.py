"""Operator administration for durable remote MCP clients and kill switches."""

from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select

from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    ChatLLMGrantRecord,
    composed_capabilities,
    diff_chatllm_data_profile,
    plan_chatllm_grant_actions,
    profile_diff_as_json,
)
from my_pa.application.service import _HANDLERS
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.domain.identity.chatllm_capability_policy import CHATLLM_DATA_PROFILE_VERSION
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


def _add_profile_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--oauth-client-id", required=True)
    parser.add_argument("--scope", required=True)
    parser.add_argument("--resource", required=True)
    parser.add_argument(
        "--profile-version",
        required=True,
        help="must match the repository ChatLLM data profile version",
    )


def _planes_from_settings(settings: Settings) -> ChatLLMCompositionPlanes:
    return ChatLLMCompositionPlanes(
        managed_documents=bool(settings.managed_document_root),
        relationship_intelligence=settings.relationship_intelligence_enabled,
        relationship_intelligence_writes=settings.relationship_intelligence_writes_enabled,
        relationship_memory=settings.relationship_memory_enabled,
        constraints=True,
    )


def _grant_records(rows: tuple[object, ...]) -> tuple[ChatLLMGrantRecord, ...]:
    records: list[ChatLLMGrantRecord] = []
    for row in rows:
        try:
            capability = Capability(row.capability)
        except ValueError:
            continue
        try:
            purpose = None if row.purpose is None else Purpose(row.purpose)
        except ValueError:
            continue
        records.append(
            ChatLLMGrantRecord(
                capability=capability,
                purpose=purpose,
                is_write=bool(row.is_write),
                resource=row.resource,
                scope=row.external_scope,
                expires_at=row.expires_at,
                revoked_at=row.revoked_at,
                grant_id=row.id,
            )
        )
    return tuple(records)


def _run_profile_command(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    repository: RemoteIdentityRepository,
    settings: Settings,
    now: datetime,
) -> int:
    if args.profile_version != CHATLLM_DATA_PROFILE_VERSION:
        parser.error(
            f"profile version must be {CHATLLM_DATA_PROFILE_VERSION}; got {args.profile_version}"
        )
    remote_client_id = repository.client_id_for_oauth_id(args.oauth_client_id)
    if remote_client_id is None:
        parser.error("remote client not found")
    implemented = frozenset(_HANDLERS)
    composed = composed_capabilities(implemented, _planes_from_settings(settings))
    records = _grant_records(repository.list_capability_grants(remote_client_id=remote_client_id))
    diff = diff_chatllm_data_profile(
        implemented=implemented,
        composed=composed,
        grants=records,
        now=now,
        resource=args.resource,
        scope=args.scope,
    )
    if args.command == "profile-diff":
        print(json.dumps(profile_diff_as_json(diff), indent=2, sort_keys=True))
        return 0 if diff.is_healthy() else 1
    actions = plan_chatllm_grant_actions(
        diff, records, now=now, resource=args.resource, scope=args.scope
    )
    payload = {
        "profile_version": diff.profile_version,
        "healthy": diff.is_healthy(),
        "actions": [
            {
                "kind": action.kind,
                "capability": action.capability.value,
                "purpose": action.purpose.value,
                "write": action.is_write,
                "grant_id": None if action.grant_id is None else str(action.grant_id),
            }
            for action in actions
            if action.kind != "noop"
        ],
        "unexpected_control_plane": sorted(item.value for item in diff.unexpected_control_plane),
        "policy_required_not_implemented": sorted(
            item.value for item in diff.policy_required_not_implemented
        ),
    }
    if args.command == "profile-plan":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0 if diff.is_healthy() else 1
    if not args.apply:
        parser.error("profile-apply requires --apply after reviewing profile-plan")
    for action in actions:
        if action.kind == "noop":
            continue
        if action.kind == "renew":
            if action.grant_id is None or not repository.clear_grant_expiry(
                grant_id=action.grant_id
            ):
                parser.error(f"failed to renew {action.capability.value}")
            continue
        repository.grant(
            remote_client_id=remote_client_id,
            external_scope=args.scope,
            capability=action.capability,
            now=now,
            is_write=action.is_write,
            resource=args.resource,
            expires_at=None,
            purpose=action.purpose,
        )
    print(json.dumps({"applied": True, **payload}, indent=2, sort_keys=True))
    return 0


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
    profile_diff = sub.add_parser("profile-diff")
    _add_profile_arguments(profile_diff)
    profile_plan = sub.add_parser("profile-plan")
    _add_profile_arguments(profile_plan)
    profile_apply = sub.add_parser("profile-apply")
    _add_profile_arguments(profile_apply)
    profile_apply.add_argument("--apply", action="store_true")
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
            elif args.command in {"profile-diff", "profile-plan", "profile-apply"}:
                return _run_profile_command(parser, args, repository, settings, now)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
