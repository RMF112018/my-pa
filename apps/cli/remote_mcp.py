"""Operator administration for durable remote MCP clients and kill switches."""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.engine import Row

from my_pa.application.chatllm_data_profile import (
    ChatLLMCompositionPlanes,
    ChatLLMGrantRecord,
    composed_capabilities,
    diff_chatllm_data_profile,
    plan_chatllm_grant_actions,
    profile_diff_as_json,
)
from my_pa.application.service import _HANDLERS
from my_pa.bootstrap.knowledge_discovery_profiles import (
    DISCOVERY_PROFILES,
    KNOWLEDGE_CLIENT_PROFILES,
    KNOWLEDGE_DISCOVERY_ONLY_CAPABILITIES,
    KnowledgeAllowlists,
    allowlist_fingerprint,
    knowledge_allowlists,
    knowledge_client_role,
    profile_for_role,
)
from my_pa.bootstrap.settings import Settings, load_settings
from my_pa.domain.identity.chatllm_capability_policy import CHATLLM_DATA_PROFILE_VERSION
from my_pa.domain.identity.operation import Capability, is_write_capability, permitted_purposes
from my_pa.domain.identity.purpose import Purpose
from my_pa.infrastructure.database.engine import create_database_engine
from my_pa.infrastructure.persistence.remote_identity import (
    RemoteIdentityRepository,
    remote_capability_grants,
    remote_clients,
    remote_security_controls,
)

#: KLP-WP-03 (KLP-AC-146 WP-03 slice): the Knowledge Assertion names raw `grant`
#: governs. An explicit name set, never a `knowledge.` prefix, so the extraction
#: plane's `knowledge.search`/`read`/`reveal`/`coverage` grants are unaffected.
#: KLP-WP-04 added submit and checkpoint to both sets; KLP-WP-05 adds the
#: `record_events.provenance` read here (never a write, so not to the second).
KNOWLEDGE_GRANT_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.KNOWLEDGE_ASSERTIONS_READ,
        Capability.KNOWLEDGE_ASSERTIONS_LIST,
        Capability.KNOWLEDGE_ASSERTIONS_SEARCH,
        Capability.KNOWLEDGE_ASSERTIONS_HISTORY,
        Capability.KNOWLEDGE_ASSERTIONS_REVEAL,
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
        Capability.KNOWLEDGE_ASSERTIONS_SUBMIT,
        Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT,
        Capability.RECORD_EVENTS_PROVENANCE,
    }
)
#: Knowledge writes only profile tooling may install: `profile-apply` for the
#: explicit create, `knowledge-profile-apply` for the discovery pair.
KNOWLEDGE_WRITE_GRANT_CAPABILITIES: frozenset[Capability] = frozenset(
    {
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
        Capability.KNOWLEDGE_ASSERTIONS_SUBMIT,
        Capability.KNOWLEDGE_DISCOVERY_CHECKPOINT,
    }
)


def raw_grant_refusal(
    capability: Capability,
    purpose: Purpose | None,
    *,
    allowlists: KnowledgeAllowlists | None = None,
    oauth_client_id: str | None = None,
) -> str | None:
    """Why raw `grant` refuses this pair, or `None` when it may proceed.

    Evaluated before any connection is opened, so a refusal writes no row.
    KLP-WP-04 (KLP-AC-020/146): with the Settings allowlists supplied, a client
    bound as a discovery or operator-review client is also refused every
    capability outside its exact profile.
    """
    if capability in KNOWLEDGE_WRITE_GRANT_CAPABILITIES:
        installer = (
            "knowledge-profile-apply"
            if capability in KNOWLEDGE_DISCOVERY_ONLY_CAPABILITIES
            else "profile-apply"
        )
        return (
            f"raw grant refuses the Knowledge write {capability.value}; "
            f"install it through {installer}"
        )
    if capability in KNOWLEDGE_GRANT_CAPABILITIES and purpose is None:
        return f"raw grant refuses a Knowledge grant without a purpose ({capability.value})"
    if allowlists is not None and oauth_client_id is not None:
        profile = profile_for_role(knowledge_client_role(allowlists, oauth_client_id))
        if profile is not None and capability not in KNOWLEDGE_CLIENT_PROFILES[profile]:
            return (
                f"raw grant refuses {capability.value} for a client bound to {profile}: "
                "it is outside that client's exact profile"
            )
    return None


def _print_fingerprint(allowlists: KnowledgeAllowlists) -> str:
    """Print, on stderr, the allowlist fingerprint this command evaluated (KLP-AC-020)."""
    fingerprint = allowlist_fingerprint(allowlists)
    print(f"allowlist_fingerprint {fingerprint}", file=sys.stderr)
    return fingerprint


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
        managed_documents=settings.managed_documents_are_composed(),
        relationship_intelligence=settings.relationship_intelligence_enabled,
        relationship_intelligence_writes=settings.relationship_intelligence_writes_enabled,
        relationship_memory=settings.relationship_memory_enabled,
        constraints=True,
        knowledge_assertions=(
            settings.knowledge_assertions_enabled and settings.relationship_intelligence_enabled
        ),
    )


def _grant_records(rows: tuple[Row[Any], ...]) -> tuple[ChatLLMGrantRecord, ...]:
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
    allowlists = knowledge_allowlists(settings)
    fingerprint = _print_fingerprint(allowlists)
    bound = profile_for_role(knowledge_client_role(allowlists, args.oauth_client_id))
    if bound is not None:
        # KLP-AC-040: the ordinary ChatLLM profile names create and review.decide,
        # so it is never planned or written for a Knowledge-bound client.
        parser.error(
            f"client is bound to {bound}; the ChatLLM data profile is never planned or "
            "applied for it -- use knowledge-profile-plan/apply"
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
        rendered = {**profile_diff_as_json(diff), "allowlist_fingerprint": fingerprint}
        print(json.dumps(rendered, indent=2, sort_keys=True))
        return 0 if diff.is_healthy() else 1
    actions = plan_chatllm_grant_actions(
        diff, records, now=now, resource=args.resource, scope=args.scope
    )
    payload = {
        "allowlist_fingerprint": fingerprint,
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


def knowledge_profile_refusal(profile: str, capability: Capability) -> str | None:
    """Why a Knowledge profile command refuses to plan `capability`, or `None`.

    KLP-AC-040: a discovery profile never plans `knowledge.assertions.create` or
    `review.decide`. The profile table already omits both; this is the explicit,
    separately testable statement of the rule.
    """
    if profile in DISCOVERY_PROFILES and capability in (
        Capability.KNOWLEDGE_ASSERTIONS_CREATE,
        Capability.REVIEW_DECIDE,
    ):
        return f"{profile} never plans {capability.value}"
    if capability not in KNOWLEDGE_CLIENT_PROFILES[profile]:
        return f"{capability.value} is outside {profile}"
    return None


def _knowledge_profile_grant(capability: Capability) -> tuple[Purpose, bool]:
    (purpose,) = permitted_purposes(capability)
    return purpose, is_write_capability(capability)


def _run_knowledge_profile_command(
    parser: argparse.ArgumentParser,
    args: argparse.Namespace,
    repository: RemoteIdentityRepository,
    settings: Settings,
    now: datetime,
) -> int:
    """Plan or apply exactly one Knowledge client profile (KLP-AC-019/020/040/146).

    The only path that installs discovery and operator-review grants. The client
    must be in the matching Settings allowlist and the named profile must be the
    one its role binds; every planned grant carries its single permitted purpose
    and `is_write`. Active grants outside the profile are reported -- the gateway
    overlay already strips them -- and never extended.
    """
    allowlists = knowledge_allowlists(settings)
    fingerprint = _print_fingerprint(allowlists)
    bound = profile_for_role(knowledge_client_role(allowlists, args.oauth_client_id))
    if bound is None:
        parser.error("client is not in a Knowledge discovery or operator-review allowlist")
    if args.profile != bound:
        parser.error(f"client is bound to {bound}, not {args.profile}")
    desired = KNOWLEDGE_CLIENT_PROFILES[bound]
    for capability in desired:
        refusal = knowledge_profile_refusal(bound, capability)
        if refusal is not None:
            parser.error(refusal)
    remote_client_id = repository.client_id_for_oauth_id(args.oauth_client_id)
    if remote_client_id is None:
        parser.error("remote client not found")
    records = _grant_records(repository.list_capability_grants(remote_client_id=remote_client_id))
    active = [
        record
        for record in records
        if record.revoked_at is None
        and (record.expires_at is None or record.expires_at > now)
        and record.resource == args.resource
        and record.scope == args.scope
    ]
    actions: list[dict[str, object]] = []
    for capability in sorted(desired, key=lambda member: member.value):
        purpose, is_write = _knowledge_profile_grant(capability)
        present = any(
            record.capability is capability
            and record.purpose is purpose
            and record.is_write is is_write
            for record in active
        )
        if not present:
            actions.append(
                {
                    "kind": "grant",
                    "capability": capability.value,
                    "purpose": purpose.value,
                    "write": is_write,
                }
            )
    outside = sorted({record.capability.value for record in active} - {c.value for c in desired})
    payload: dict[str, object] = {
        "profile": bound,
        "allowlist_fingerprint": fingerprint,
        "actions": actions,
        "outside_profile": outside,
    }
    if args.command == "knowledge-profile-plan":
        print(json.dumps(payload, indent=2, sort_keys=True))
        return 0
    if not args.apply:
        parser.error("knowledge-profile-apply requires --apply after reviewing the plan")
    for action in actions:
        capability = Capability(str(action["capability"]))
        purpose, is_write = _knowledge_profile_grant(capability)
        repository.grant(
            remote_client_id=remote_client_id,
            external_scope=args.scope,
            capability=capability,
            now=now,
            is_write=is_write,
            resource=args.resource,
            expires_at=None,
            purpose=purpose,
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
    for name in ("knowledge-profile-plan", "knowledge-profile-apply"):
        knowledge_profile = sub.add_parser(name)
        knowledge_profile.add_argument("--oauth-client-id", required=True)
        knowledge_profile.add_argument("--scope", required=True)
        knowledge_profile.add_argument("--resource", required=True)
        knowledge_profile.add_argument(
            "--profile", choices=sorted(KNOWLEDGE_CLIENT_PROFILES), required=True
        )
        if name == "knowledge-profile-apply":
            knowledge_profile.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    if args.command == "grant":
        refusal = raw_grant_refusal(args.capability, args.purpose)
        if refusal is not None:
            parser.error(refusal)

    settings = load_settings()
    if args.command == "grant":
        allowlists = knowledge_allowlists(settings)
        _print_fingerprint(allowlists)
        refusal = raw_grant_refusal(
            args.capability,
            args.purpose,
            allowlists=allowlists,
            oauth_client_id=args.oauth_client_id,
        )
        if refusal is not None:
            parser.error(refusal)
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
            elif args.command in {"knowledge-profile-plan", "knowledge-profile-apply"}:
                return _run_knowledge_profile_command(parser, args, repository, settings, now)
    finally:
        engine.dispose()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
